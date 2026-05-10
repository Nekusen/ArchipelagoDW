"""Phase 4 v1 BizHawk client for the Digimon World 1 APWorld.

Architecture (locked Phase 0): BizHawk + Nymashock + APProcedurePatch +
the **generic** Lua connector (``data/lua/connector_bizhawk_generic.lua``).
This client subclasses :class:`worlds._bizhawk.client.BizHawkClient` so
the in-tree BizHawk framework (auto-Lua injection, JSON-RPC transport,
``MainRAM``-domain reads) does the heavy lifting. We just supply
DW1-specific validation, polling, and write semantics.

What v1 of this client actually does
====================================

* :meth:`validate_rom` — confirms BizHawk is connected to a running PSX
  game and that the live save block is in a plausible state (a
  ``RAM_PROSPERITY_POINTS`` byte in 0..100). The Phase 3 patcher's
  PVD volume-id marker is **not** read here because it lives in the
  ISO9660 system area, which the PSX BIOS doesn't load into MainRAM.
  Confirming we're connected to *the right seed* needs Phase 3 v2 work
  (write the slot identifier into the executable, where it will be
  RAM-mapped at runtime).
* :meth:`set_auth` — left as the AP default (the user is prompted for
  slot name on first connect). Phase 4 v2 will store the slot name in
  RAM via Phase 3 v2 patcher writes, and read it back here.
* :meth:`game_watcher` — runs every ``ctx.watcher_timeout`` (~100 ms by
  default) and dispatches to:

  - :meth:`_check_locations` — polls a per-location RAM-bit table and
    sends ``LocationChecks`` for newly-set bits. v1 ships an **empty**
    table; per-location bits are a pending RE deliverable (PLAN.md
    Q2). The framework is in place.
  - :meth:`_deliver_items` — applies items from
    :attr:`ctx.items_received` to RAM. v1 ships **empty** delivery
    routes. The skeleton consults a counter at a (yet-undiscovered)
    RAM address.
  - :meth:`_check_goal` — fire ``StatusUpdate(GoalComplete)`` when the
    player meets the configured goal (Machinedramon defeated, or
    in-game prosperity ≥ the ``prosperity_goal`` slot_data threshold).

Pending RE deliverables (PLAN.md Q2 subquestions)
-------------------------------------------------

The framework is wired; these tables are empty pending verification:

* per-recruit RAM completion bits (50 entries),
* per-chest RAM pickup bits (73 entries),
* per-prosperity-NPC RAM completion bits (15 entries),
* the items_received counter address (where the client stores how many
  items it has delivered, so we don't double-deliver),
* the AP-flag scratch region inside the live save block,
* the Machinedramon-defeat flag.

When each one lands, populate the corresponding constant near the top
of this module and add a route to :meth:`_check_locations` /
:meth:`_deliver_items`. The structural code below should not need to
change.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, ClassVar, NamedTuple

import worlds._bizhawk as bizhawk
from NetUtils import ClientStatus
from worlds._bizhawk.client import BizHawkClient

from .data.addresses import (
    AGUMON_RECRUIT_BIT,
    AP_CHEST_SENTINEL_ITEM_ID,
    AP_RECRUIT_ITEM_DIGIMON,
    BEATEN_RAM_BITS,
    BIRDRAMON_FLIGHT_RAM_BITS,
    CARD_BLOCK_BASE,
    CARD_BLOCK_SIZE,
    CARD_LOCATION_NIBBLES,
    DWAP_CHEST_RAM_BITS,
    EASY_MONOCHROMON_MAP_ID,
    EASY_MONOCHROMON_PROFIT_TARGET,
    FAST_DRIMOGEMON_DIGGING_STATE_TARGET,
    FAST_DRIMOGEMON_DRIMO_STATE_TARGET,
    AP_ITEM_BOUGHT_MERIT_VALUE_BYTES,
    AP_SHOP_BOUGHT_SENTINEL_RAM,
    AP_SHOP_BOUGHT_VISIBLE_BYTES,
    AP_TRIGGER_ARRAY_BASE,
    ITEM_PARA_MERIT_VALUE_OFFSET,
    FAST_DRIMOGEMON_TUNNEL_STATE_TARGET,
    KEYITEM_DELIVERY_RAM_BITS,
    KEYITEM_LOCATION_RAM_BITS,
    MERIT_SHOP_DISPATCH,
    RAM_ITEM_PARA,
    ROM_ITEM_TABLE_ENTRY_SIZE,
    RAM_CURRENT_BITS,
    RAM_CURRENT_BRAINS,
    RAM_CURRENT_DEFENSE,
    RAM_CURRENT_OFFENSE,
    RAM_CURRENT_SPEED,
    RAM_GREAT_CANYON_BRIDGE_UNLOCKED,
    RAM_HAS_BEATEN_DRIMOGEMON,
    RAM_INVENTORY_EMPTY_SLOT_ID,
    RAM_INVENTORY_ITEM_IDS_BASE,
    RAM_INVENTORY_QUANTITIES_BASE,
    RAM_INVENTORY_SLOT_COUNT,
    RAM_ITEM_BANK_BASE,
    RAM_ITEM_BANK_SIZE,
    RAM_MAX_HP,
    RAM_MAX_MP,
    RAM_MERAMON_TUNNEL_DIGGING_STATE,
    RAM_MERAMON_TUNNEL_DRIMO_STATE,
    RAM_MACHINEDRAMON_DEFEATED_BYTE,
    RAM_MACHINEDRAMON_DEFEATED_MASK,
    RAM_MERAMON_TUNNEL_STATE,
    RAM_MONOCHROME_PROFIT,
    RAM_PROSPERITY_POINTS,
    RAM_STAT_CAP,
    RAM_STAT_CAP_FLAG,
    RAM_STAT_GAIN_MULT,
    RAM_TROPICAL_JUNGLE_BRIDGE_FIXED,
    RECRUIT_RAM_BITS,
    STAT_CAP_FLAG_TARGET,
    STAT_CAP_TARGET,
    VENDING_LOCATION_RAM_BITS,
)
from .items import (
    ITEM_ID_BASE,
    ITEM_NAME_TO_ID,
    PROGRESSIVE_BUNDLES,
    PROSPERITY_PER_ITEM,
    PROSPERITY_POINT_NAME,
    digimon_id_for_recruit_item,
)

if TYPE_CHECKING:
    from worlds._bizhawk.context import BizHawkClientContext

# Type for a single RAM write — what bizhawk.write expects.
RamWrite = tuple[int, list[int], str]
# An item delivery route reads RAM (to compute additive deltas) and
# returns a list of writes to apply. Async because reads are async.
ItemDeliverer = Callable[["BizHawkClientContext"], Awaitable[list[RamWrite]]]


logger = logging.getLogger("Client")


# =============================================================================
# Memory-domain constants
# =============================================================================
# Nymashock exposes PS1 RAM as the ``MainRAM`` domain (per
# ``nymashock_memory_domain.md``). We never read from System Bus
# (0x80000000) or from a ROM domain; everything is offsets inside
# MainRAM.

DOMAIN_MAIN_RAM = "MainRAM"

# Plausible-range bound for RAM_PROSPERITY_POINTS used by validate_rom.
# DW1's prosperity counter saturates at 100 in normal play; an
# uninitialized save slot reads 0; anything > 100 means we are not
# looking at a running DW1 (almost certainly a different game).
_PROSPERITY_VALIDATION_CEILING = 100


# =============================================================================
# Path D dynamic-city-toggle constants
# =============================================================================
# See ``_reconcile_recruits`` for the toggle algorithm.
#
# CURRENT_SCREEN_ADDR — single byte holding the current map/screen ID
# the engine is rendering. Verified live and cross-referenced with the
# DW1-SydPatches decompilation
# (``references/DW1-SydPatches/SLUS_labels.asm:246`` — ``CURRENT_SCREEN``
# at ``0x80134DA8`` = MainRAM offset ``0x00134DA8``, type ``uint8_t``).
# (DWAP's C# client reads a different field at ``0x00134FFE`` as a
# 2-byte short; both addresses appear to track map state but at
# different points in the transition flow. The decompilation address
# is the authoritative one and matches our live observations.)
#
# CITY_SCREENS — exhaustive set of screen IDs whose Region (per DWAP's
# ``Helpers.cs:DigimonMap()`` table, IDs 0..254) is one of: File City
# Top, File City Bottom, Jijimon's House, Birdra Transport, Arena
# Lobby, Item Keeper, Centar Clinic, Restaurant, Item Shop, Secret
# Shop. 52 screens total. NOT a contiguous range — non-city screens
# interleave at IDs 209, 210, 212, 219..222, 224..235.
#
# RECRUIT_BLOCK_BASE / RECRUIT_BLOCK_SIZE — byte range covering all
# recruit-completion bits (trigger 200..258 inclusive). The trigger
# array starts at 0x001BDFCD; bit 200 lives at offset 200//8=25
# (``0x001BDFE6``); bit 258 at offset 258//8=32 (``0x001BDFED``). 8
# bytes inclusive. We read this whole block in one batched read each
# tick rather than per-Digimon byte reads.

CURRENT_SCREEN_ADDR: int = 0x00134DA8
CITY_SCREENS: frozenset[int] = frozenset({
    # 168..208 — File City Top + Bottom + Jijimon's House + Birdra
    # Transport + Arena Lobby (lobby-without-Mecha variant only)
    *range(168, 209),
    # 211 — Item Keeper
    211,
    # 213..218 — Centar Clinic, Restaurant x2, Item Shop, Secret Shop,
    # Jijimon's House (Base Model)
    *range(213, 219),
    # 223 — Arena Lobby (with MetalGreymon/Airdramon)
    223,
    # 236, 237, 238 — File City Top (Final / Initial cutscene variants)
    236, 237, 238,
})
RECRUIT_BLOCK_BASE: int = 0x001BDFE6
RECRUIT_BLOCK_SIZE: int = 8

# AP-delivered scratch mirror — 8 bytes of client-managed RAM that the
# toggle writes each tick with the AP-bit map (same byte/bit layout as
# the recruit block). ``ctx.items_received`` lives in the Python client
# only; this mirror exposes the same information to BizHawk Lua scripts
# for live debugging. Located in the gap immediately after the
# items_received counter (which is itself in unused-trigger gap space
# verified live 2026-04-28).
AP_BITS_MIRROR_BASE: int = 0x001BDFF0
AP_BITS_MIRROR_SIZE: int = 8

# BEATEN block — 8 bytes covering bits 720..783 of the trigger array.
# The setTrigger wrapper redirects setTrigger(200+X) to setTrigger(720+X)
# whenever vanilla DW1 tries to mark Digimon X recruited; bit 720+X
# therefore = "player has won the wild fight at X's spawn point".
# Bytes 0x001BE027..0x001BE02E are entirely unused by vanilla (verified
# in :data:`worlds.digimon_world.data.addresses.BEATEN_RAM_BITS`).
BEATEN_BLOCK_BASE: int = 0x001BE027
BEATEN_BLOCK_SIZE: int = 8

# changeMap wrapper scratch — the wrapper writes $a0 (destination map id
# of the call to vanilla's scriptTickChangeMap) here on every fire. We
# use this as the source of truth for the city/field decision instead
# of CURRENT_SCREEN_ADDR. Vanilla updates CURRENT_SCREEN_ADDR *after*
# the wrapper has already loaded the destination's recruit bits, so a
# toggle keyed on CURRENT_SCREEN reads the source and clobbers the
# wrapper's write. Keying on $a0 makes the toggle agree with the
# wrapper through the entire transition window.
WRAPPER_LAST_A0_ADDR: int = 0x000958A0


class _RecruitToggleRow(NamedTuple):
    """Precomputed offsets for one AP-pool recruit Digimon, used by
    :meth:`DigimonWorldClient._reconcile_recruits` each tick."""
    digimon_id: int
    recruit_block_off: int  # byte offset within RECRUIT_BLOCK_BASE..+SIZE
    recruit_bit: int        # bit index within that byte
    beaten_block_off: int   # byte offset within BEATEN_BLOCK_BASE..+SIZE
    beaten_bit: int         # bit index within that byte


def _build_recruit_toggle_targets() -> tuple[_RecruitToggleRow, ...]:
    """Enumerate per-Digimon byte/bit offsets for the recruit toggle.

    Agumon is excluded because his recruit bit is force-enforced
    separately by :meth:`DigimonWorldClient._enforce_agumon_recruited`.
    """

    rows: list[_RecruitToggleRow] = []
    for name in AP_RECRUIT_ITEM_DIGIMON:
        recruit_byte_addr, recruit_bit = RECRUIT_RAM_BITS[name]
        beaten_byte_addr, beaten_bit = BEATEN_RAM_BITS[name]
        recruit_block_off = recruit_byte_addr - RECRUIT_BLOCK_BASE
        beaten_block_off = beaten_byte_addr - BEATEN_BLOCK_BASE
        if not (0 <= recruit_block_off < RECRUIT_BLOCK_SIZE):
            continue
        if not (0 <= beaten_block_off < BEATEN_BLOCK_SIZE):
            continue
        did = digimon_id_for_recruit_item(f"{name} Recruit")
        if did is None:
            continue
        rows.append(_RecruitToggleRow(
            did, recruit_block_off, recruit_bit,
            beaten_block_off, beaten_bit,
        ))
    return tuple(rows)


_RECRUIT_TOGGLE_TARGETS: tuple[_RecruitToggleRow, ...] = (
    _build_recruit_toggle_targets()
)


# =============================================================================
# Per-location detection tables
# =============================================================================
#
# * **Chests** — bit-set checks at the vanilla DWAP-mapped trigger bits.
# * **Recruits** (Plan A revised) — bit-set checks at the *recruit*
#   bits (200+X). When the player completes any recruit cutscene
#   (fight, NPC dialog, plot-trigger), vanilla calls
#   ``setTrigger(200+X)`` directly. AP polls bit 200+X to detect
#   "the player completed the cutscene" → fire the AP location.
#   The recruit-block (200+X) is the "cutscene completed" signal;
#   the beaten-block (720+X) is the "AP delivered the recruit item"
#   signal. ROM-patches on per-Digimon city scripts redirect their
#   visibility gates from 200+X → 720+X so the city only shows X
#   after AP has delivered.
# Airdramon was dropped from AP coverage 2026-05-08 (see addresses.py
# ``_AP_RECRUIT_EXCLUDED``). It retains its entry in RECRUIT_RAM_BITS
# as a low-level vanilla mapping, but the bit is NOT polled by
# ``_check_locations`` because no AP location exists for it. Filter it
# out here so polling doesn't try to send a nonexistent location ID.
#
# Seadramon was dropped 2026-05-09 (see ``_AP_RECRUIT_EXCLUDED``) — his
# recruit cutscene IS the Blue Flute pickup. The cutscene's bit
# (trigger 210, byte 0x001BDFE7 bit 2) is still polled, but under the
# ``Blue Flute Pickup`` keyitem location name (via
# :data:`KEYITEM_LOCATION_RAM_BITS`). Filtering Seadramon out of the
# recruit-bit poll here ensures we don't try to fire a non-existent
# ``Seadramon`` AP location from the same bit.
_DROPPED_RECRUITS_BLACKLIST: frozenset[str] = frozenset({
    "Airdramon",
    "Seadramon",
    # Nanimon dropped 2026-05-09: per the recruitment guide he drops
    # keychains but never appears as a city NPC, so there's nothing
    # for AP to detect.
    "Nanimon",
    # Giromon dropped 2026-05-09: his Restaurant Jukebox crashes
    # the NTSC build, so we don't make him an AP location either.
    "Giromon",
})
LOCATION_RAM_BITS: dict[str, tuple[int, int]] = {
    **DWAP_CHEST_RAM_BITS,
    **{name: bits for name, bits in RECRUIT_RAM_BITS.items()
       if name not in _DROPPED_RECRUITS_BLACKLIST},
    **KEYITEM_LOCATION_RAM_BITS,
    **VENDING_LOCATION_RAM_BITS,
}

# Threshold-based detection (e.g. NPC-gift PP gates) is unused in v7 —
# the K Prosperity locations are gone; PP is delivered as an AP item.
LOCATION_RAM_THRESHOLDS: dict[str, tuple[int, int]] = {}


# =============================================================================
# Per-item delivery routes (populated; activated when ITEMS_RECEIVED_COUNTER set)
# =============================================================================
#
# Three categories, each with a route factory:
#
# * **Recruit souls** (48 items, dw_codes 4000..4049) — **no-op**. The
#   soul item is an AP-logic-only key (used by :mod:`.rules` for
#   progression gating); it must not write the corresponding recruit
#   bit, because that bit is also the one
#   :meth:`DigimonWorldClient._check_locations` reads to detect "the
#   player recruited X". Writing it on delivery would cause AP to
#   fire that recruit location immediately, returning whatever was
#   placed there — feedback loop. The recruit bit only flips when
#   DW1 itself sets it (i.e. when the player actually recruits).
# * **Bank items** (consumables, DV items, key items, all in DWAP's
#   2000-block, dw_codes 2000..2127) — increment the byte at
#   ``RAM_ITEM_BANK_BASE + (dw_code - 2000)``, capped at
#   :data:`_BANK_QUANTITY_CAP`. The bank layout was verified live
#   2026-04-28; see ``data.addresses`` for details. **NOT idempotent**:
#   re-delivery would stack quantity. Hence the
#   :data:`ITEMS_RECEIVED_COUNTER` is required to gate against
#   re-delivery on reconnect.
# * **Money** (1000 Bits, 5000 Bits — dw_codes 3001, 3002) — 4-byte LE
#   add at :data:`RAM_CURRENT_BITS`, capped at :data:`_MONEY_CAP`.
#   Same idempotency caveat as bank items.

# DW1's per-slot bank quantity caps at some value the game enforces.
# Real cap TBD; 99 is the FFT convention and a safe upper bound for v1.
_BANK_QUANTITY_CAP: int = 99

# DW1's bits cap. DWAP doesn't pin this down; 9_999_999 is the value
# DWAP-era discussion suggests as the in-game ceiling but it's not a
# manifest-verified constant. Capping defensively.
_MONEY_CAP: int = 9_999_999


# Hard ceiling for the in-game prosperity byte. DW1 saturates at 100
# in normal play; we don't issue more than this regardless of how many
# Prosperity Point items the seed contains.
PROSPERITY_RAM_CAP: int = 100


def _make_prosperity_deliverer() -> ItemDeliverer:
    """Return an :class:`ItemDeliverer` for ``Prosperity Point``.

    Each delivery bumps the in-game prosperity byte by
    :data:`PROSPERITY_PER_ITEM` (= 2; saturating at
    :data:`PROSPERITY_RAM_CAP`). The deliverer is **idempotent**: if the
    byte is already at the target, the write is dropped.

    Note: the watcher's :meth:`DigimonWorldClient._enforce_prosperity`
    runs every tick to pin the byte to ``ProsperityPoint count *
    PROSPERITY_PER_ITEM`` so vanilla DW1's recruit-derived PP recompute
    cannot leak through. The deliverer just bumps the target value.
    """

    async def deliver(ctx: BizHawkClientContext) -> list[RamWrite]:
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(RAM_PROSPERITY_POINTS, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current:
            return []
        new_value = min(PROSPERITY_RAM_CAP, current[0] + PROSPERITY_PER_ITEM)
        if new_value == current[0]:
            return []
        return [(RAM_PROSPERITY_POINTS, [new_value], DOMAIN_MAIN_RAM)]

    return deliver


def _make_recruit_deliverer(digimon_id: int) -> ItemDeliverer:
    """Return an :class:`ItemDeliverer` for a ``"<Digimon> Recruit"`` item.

    Plan A revised: AP delivery writes bit 720+X (BEATEN_RAM_BITS) for
    the digimon. Bit 720+X is the "AP delivered" signal; per-Digimon
    city-visibility ROM patches gate city-spawn on this bit. Wild-spawn
    (bit 200+X) is left to vanilla — set when the player completes the
    in-game recruit cutscene.

    Idempotent: reads the byte first, ORs in the bit, writes back. If
    the bit is already set (e.g. multi-delivery on reconnect), returns
    no writes.
    """

    # Reverse-lookup: find this Digimon's BEATEN_BLOCK byte+bit via
    # _RECRUIT_TOGGLE_TARGETS (which maps digimon_id → block offsets).
    row = next(
        (r for r in _RECRUIT_TOGGLE_TARGETS if r.digimon_id == digimon_id),
        None,
    )
    if row is None:
        # Defensive: should not happen for a well-formed recruit table.
        async def deliver_noop(_ctx: BizHawkClientContext) -> list[RamWrite]:
            return []
        return deliver_noop

    byte_addr = BEATEN_BLOCK_BASE + row.beaten_block_off
    bit_index = row.beaten_bit
    bit_mask = 1 << bit_index

    async def deliver(ctx: BizHawkClientContext) -> list[RamWrite]:
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(byte_addr, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current or (current[0] & bit_mask):
            return []
        return [(byte_addr, [current[0] | bit_mask], DOMAIN_MAIN_RAM)]

    return deliver


def _make_keyitem_bit_deliverer(byte_addr: int, bit_index: int) -> ItemDeliverer:
    """Return an :class:`ItemDeliverer` that ORs a single trigger-array
    bit into RAM.

    Used for "key items" whose canonical state is a trigger bit, not an
    inventory entry — see memory note `dw1_old_fishrod_flag.md`. The
    rod is the v1 entrant; future verified key items are wired through
    the same factory.

    Idempotent: reads the byte first, returns no writes if the bit is
    already set.
    """

    bit_mask = 1 << bit_index

    async def deliver(ctx: BizHawkClientContext) -> list[RamWrite]:
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(byte_addr, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current or (current[0] & bit_mask):
            return []
        return [(byte_addr, [current[0] | bit_mask], DOMAIN_MAIN_RAM)]

    return deliver


def _make_bank_deliverer(dw_code: int) -> ItemDeliverer:
    """Return an :class:`ItemDeliverer` that increments the bank slot
    quantity for a 2000-block ``dw_code`` (capped at
    :data:`_BANK_QUANTITY_CAP`).

    NOT idempotent: relies on :data:`ITEMS_RECEIVED_COUNTER` gating to
    avoid re-delivery on reconnect.
    """

    slot = dw_code - 2000
    if slot < 0 or slot >= RAM_ITEM_BANK_SIZE:
        raise ValueError(
            f"dw_code {dw_code} maps to bank slot {slot}, outside "
            f"the 0..{RAM_ITEM_BANK_SIZE - 1} range",
        )
    address = RAM_ITEM_BANK_BASE + slot

    async def deliver(ctx: BizHawkClientContext) -> list[RamWrite]:
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(address, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current:
            return []
        new_qty = min(_BANK_QUANTITY_CAP, current[0] + 1)
        if new_qty == current[0]:
            return []  # already at cap; quietly drop the delivery
        return [(address, [new_qty], DOMAIN_MAIN_RAM)]

    return deliver


def _make_progressive_bundle_deliverer() -> ItemDeliverer:
    """Return a no-op :class:`ItemDeliverer` for the 6 ``Progressive ...``
    recruit-bundle items.

    The actual BEATEN-bit OR-writes happen each tick in
    :meth:`DigimonWorldClient._reconcile_recruits`, which inspects
    ``ctx.items_received`` and re-derives the per-Digimon bit set
    from the cumulative count of each Progressive item. Routing the
    items through ``_deliver_items`` is still required so the
    items_received counter advances on each delivery (otherwise
    delivery would block on the unhandled Progressive item every
    reconnect). This deliverer returns an empty write list — the
    counter advance happens unconditionally in ``_deliver_items``.
    """

    async def deliver(_ctx: BizHawkClientContext) -> list[RamWrite]:
        return []

    return deliver


def _make_money_deliverer(amount: int) -> ItemDeliverer:
    """Return an :class:`ItemDeliverer` that adds ``amount`` to the
    bits counter (capped at :data:`_MONEY_CAP`)."""

    async def deliver(ctx: BizHawkClientContext) -> list[RamWrite]:
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(RAM_CURRENT_BITS, 4, DOMAIN_MAIN_RAM)],
        ))[0]
        if len(current) != 4:
            return []
        current_value = int.from_bytes(current, "little")
        new_value = min(_MONEY_CAP, current_value + amount)
        if new_value == current_value:
            return []  # already at cap
        return [(
            RAM_CURRENT_BITS,
            list(new_value.to_bytes(4, "little")),
            DOMAIN_MAIN_RAM,
        )]

    return deliver


def _build_item_delivery_routes() -> dict[str, ItemDeliverer]:
    """Construct :data:`ITEM_DELIVERY_ROUTES` from the items table.

    Routes by item name / ``dw_code`` band:

    * ``Prosperity Point`` → +``PROSPERITY_PER_ITEM`` PP at
      :data:`RAM_PROSPERITY_POINTS`.
    * ``"<Digimon> Recruit"`` (1000-block, Phase 5 piece C) → set the
      recruit-completion bit ``200 + digimon_id`` directly. This
      bypasses the setTrigger wrapper (which would otherwise redirect
      into the beaten range).
    * ``"Progressive <Feature>"`` (Phase 7 recruit bundles) → no-op
      route. The actual BEATEN-bit writes for each bundled Digimon
      happen each tick in
      :meth:`DigimonWorldClient._reconcile_recruits`, which derives
      them cumulatively from ``ctx.items_received``. Routing the
      delivery through here is still required so the counter
      advances on each delivery.
    * 2000-block dw_code (consumables, DV items, key items) → bank-byte
      increment.
    * 3001 → 1000-bit money deliverer.
    * 3002 → 5000-bit money deliverer.

    Items outside these ranges are intentionally skipped (no route
    registered); :meth:`DigimonWorldClient._deliver_items` logs a
    warning when AP sends one.
    """

    routes: dict[str, ItemDeliverer] = {}
    for name, ap_id in ITEM_NAME_TO_ID.items():
        dw_code = ap_id - ITEM_ID_BASE
        if name == PROSPERITY_POINT_NAME:
            routes[name] = _make_prosperity_deliverer()
            continue
        recruit_id = digimon_id_for_recruit_item(name)
        if recruit_id is not None:
            routes[name] = _make_recruit_deliverer(recruit_id)
            continue
        # Phase 7 ``Progressive <Feature>`` recruit-bundle items get a
        # no-op route so the counter advances cleanly. The real
        # BEATEN-bit work happens in ``_reconcile_recruits`` each
        # watcher tick.
        if name in PROGRESSIVE_BUNDLES:
            routes[name] = _make_progressive_bundle_deliverer()
            continue
        # Key items live as trigger-array bits, not bank slots — must be
        # checked before the 2000-block bank route below or AP would
        # write a meaningless quantity byte and the player would never
        # actually receive the item.
        if name in KEYITEM_DELIVERY_RAM_BITS:
            byte_addr, bit_index = KEYITEM_DELIVERY_RAM_BITS[name]
            routes[name] = _make_keyitem_bit_deliverer(byte_addr, bit_index)
            continue
        # Birdramon flight destination items: each unlocks one entry in
        # the patched callRoutine 10 destination table. Reuses the
        # keyitem bit deliverer (same byte+bit OR semantics).
        if name in BIRDRAMON_FLIGHT_RAM_BITS:
            byte_addr, bit_index = BIRDRAMON_FLIGHT_RAM_BITS[name]
            routes[name] = _make_keyitem_bit_deliverer(byte_addr, bit_index)
            continue
        if 2000 <= dw_code < 2000 + RAM_ITEM_BANK_SIZE:
            routes[name] = _make_bank_deliverer(dw_code)
        elif dw_code == 3001:
            routes[name] = _make_money_deliverer(1000)
        elif dw_code == 3002:
            routes[name] = _make_money_deliverer(5000)
    return routes


ITEM_DELIVERY_ROUTES: dict[str, ItemDeliverer] = _build_item_delivery_routes()


# =============================================================================
# items_received counter
# =============================================================================
# 3 bytes at ``0x001BDF20..0x001BDF22`` — pre-bank scratch region.
# The counter is checked at the start of :meth:`_deliver_items` against
# ``len(ctx.items_received)`` to skip already-delivered items on
# reconnect — without it, additive deliveries (bank quantities, money)
# would duplicate every reconnect.
#
# Layout:
#   * byte 0 (0x001BDF20): magic = 0xA5 (corruption sentinel).
#   * byte 1 (0x001BDF21): counter low byte.
#   * byte 2 (0x001BDF22): counter high byte.
#
# On read: if magic byte != 0xA5, treat counter as 0 (corrupted /
# uninitialized). On write: always write all 3 bytes atomically so
# magic is re-established with every delivery.
#
# Why this address (chosen 2026-05-09 after Noble Mane / Giga Hand bug):
#   * Outside the bank UI display range (bank: 0x001BDF2C..0x001BDFAB).
#     The bank UI iterates all 128 slots and shows any non-zero quantity
#     as ``<item-name>: N``, so any counter byte landing in the bank
#     surfaces as a phantom item — see "previous addresses" below.
#   * Outside the card-vending nibble array (0x001BDFAC..0x001BDFCC).
#   * Outside the trigger bit-array (0x001BDFCD..0x001BE040). Bytes
#     inside the trigger array have a ~1/8 chance per bit of being
#     written by some ``setTrigger N`` call somewhere in the engine /
#     script bytecode (~1300+ such calls).
#   * Save-persistent (the bank starts at ``0x001BDF2C``, immediately
#     after this region — same save-block segment).
#   * Empirically dormant. Two RAM snapshots from a mid-playthrough
#     session (``tools/dw1_ram_snapshot_01.txt`` / ``_02.txt``, frame
#     360k+) show ``0x001BDF20..0x001BDF2F`` as 16 contiguous zero
#     bytes. The Cheat-Engine table claims this region holds key-item
#     flags (Coral Charm / Moon Mirror / Blue Flute), but live testing
#     2026-05-01 disproved that for ``0x001BDF23`` (old fishrod) — the
#     true flag for every key item we've checked turned out to live in
#     the trigger bit-array instead. See memory notes
#     ``dw1_keyitem_flag_block.md`` and ``dw1_old_fishrod_flag.md``.
#   * Self-healing magic byte: if any future engine path *does* clobber
#     the magic byte, the next delivery rewrites it (additive items
#     would re-deliver once after corruption — only on actual
#     corruption, not normal play).
#
# Previous addresses
# ------------------
# ``0x001BDFA9..0x001BDFAB`` (bank slots 125, 126, 127) — abandoned
#   2026-05-09 because the bank UI displayed the magic byte and counter
#   as quantities of vanilla DW1 items in those slots:
#   slot 125 = "Giga Hand" (showed 165, the magic byte), slot 126 =
#   "Noble Mane" (showed the counter low byte). The original reasoning
#   ("DW1 never writes these slots so they're safe") was right about
#   the *game* not touching them, but missed that the bank UI reads
#   them anyway.
# ``0x001BDFEE..0x001BDFEF`` (gap B of trigger array) — abandoned
#   2026-05-01 because those bytes correspond to triggers 264-279, and
#   the game sets ``trigger 274`` after every scripted battle in scripts
#   1/2/101/105 (post-battle setTrigger), which clobbered our counter
#   HIGH byte to 0x04 mid-playthrough. The magic sentinel below detects
#   any future regression of the same kind.

ITEMS_RECEIVED_COUNTER_ADDR: int = 0x001BDF20
ITEMS_RECEIVED_COUNTER_SIZE: int = 3
ITEMS_RECEIVED_COUNTER_MAGIC: int = 0xA5

# Kept for back-compat — points at the full 3-byte block (magic + counter).
ITEMS_RECEIVED_COUNTER: tuple[int, int] | None = (
    ITEMS_RECEIVED_COUNTER_ADDR, ITEMS_RECEIVED_COUNTER_SIZE,
)



# =============================================================================
# The client itself
# =============================================================================


class DigimonWorldClient(BizHawkClient):
    """v1 BizHawk client for Digimon World 1.

    Frame-rate impact: each ``game_watcher`` iteration does a single
    small MainRAM read (1 byte for ``validate_rom`` + 1 byte for goal
    check, plus per-location reads when those tables fill in). On a
    typical BizHawk install with the generic Lua connector this is well
    inside the 60 fps budget.
    """

    game: ClassVar[str] = "Digimon World"
    system: ClassVar[str] = "PSX"
    patch_suffix: ClassVar[str] = ".apdw1"

    def __init__(self) -> None:
        # Cache for AP-side lookups; populated lazily on first watcher
        # tick after we have a server connection.
        self._location_name_to_id: dict[str, int] | None = None
        self._item_name_to_id: dict[str, int] | None = None
        self._goal_complete_sent = False
        # Names of chest AP locations whose AP-placed item is the
        # player's own DW1-representable item. Vanilla DW1 hands those
        # items to the player directly via the chest-pickup flow, so
        # the client must NOT also bank-deliver the matching
        # ReceivedItem (it would duplicate the quantity). Populated
        # from slot_data on first watcher tick that sees a synced
        # connection.
        self._vanilla_grant_chests: frozenset[str] | None = None
        # QoL toggle flags shipped via slot_data. ``None`` = not yet
        # received from server; treat as off until they land. Both
        # default to "on" once slot_data arrives because the world's
        # default for the underlying option is :class:`DefaultOnToggle`.
        self._fast_drimogemon: bool | None = None
        self._easy_monochromon: bool | None = None
        # Stat-gain multiplier (1..10). 1 = vanilla rate, no enforcer
        # writes. Driven by slot_data.
        self._stat_gain_multiplier: int | None = None
        # Tropical Jungle bridge: True = pin the bridge-fixed bit so
        # the bridge is open from the start; False (vanilla) = leave
        # the bit alone and let the in-game cutscene set it.
        self._bridge_always_open: bool | None = None
        # Great Canyon bridge: same shape as the Tropical Jungle bridge
        # toggle, controlling :data:`RAM_GREAT_CANYON_BRIDGE_UNLOCKED`.
        self._great_canyon_always_open: bool | None = None
        # God Mode: when True, partner stats are pinned to near-max each
        # tick. Testing-only.
        self._god_mode: bool | None = None
        # Goal selection from the user's yaml. 0 = machinedramon (fires
        # when DW1's post-Machinedramon ``setTrigger 50`` flips), 1 =
        # prosperity (fires when in-game prosperity meets the
        # configured ``prosperity_goal`` threshold). ``None`` = not yet
        # received from slot_data.
        self._goal: int | None = None
        # Prosperity threshold from the user's ``prosperity_goal`` yaml
        # option (range 20..100, default 50). Used by ``_check_goal``
        # when ``goal == prosperity``. ``None`` = not yet received from
        # slot_data — until then the goal check is a no-op.
        self._prosperity_goal: int | None = None
    # ------------------------------------------------------------------
    # validate_rom
    # ------------------------------------------------------------------

    async def validate_rom(self, ctx: BizHawkClientContext) -> bool:
        """Accept the connection if BizHawk is on a plausible DW1 save.

        v1 sanity check: read one byte at ``RAM_PROSPERITY_POINTS`` and
        require it to be in 0..100. The PSX BIOS leaves this address
        untouched, so a failed read or an out-of-range value usually
        means we are not looking at a running PSX game (or are looking
        at the wrong PSX game). The user is responsible for loading
        the seed-matched ROM — that check is Phase 4 v2.
        """

        try:
            data = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(RAM_PROSPERITY_POINTS, 1, DOMAIN_MAIN_RAM)],
            ))[0]
        except bizhawk.RequestFailedError:
            return False

        if not data:
            return False
        if data[0] > _PROSPERITY_VALIDATION_CEILING:
            return False

        ctx.game = self.game
        # 0b111 = receive all categories: own-world items + starter +
        # precollected. Necessary because chest checks fire on the
        # in-game pickup (visual item lands in bank), but the AP
        # routing of "what that chest actually held" comes back via
        # items_received. Without bit 0 set, e.g. an AP-placed
        # ``Coelamon Soul`` on a chest never reaches the recruit-bit
        # writer.
        ctx.items_handling = 0b111
        ctx.want_slot_data = True
        return True

    # ------------------------------------------------------------------
    # set_auth
    # ------------------------------------------------------------------
    # Default behaviour (the user is prompted for slot name) is fine for
    # v1; Phase 4 v2 will store the slot name in a RAM-mapped portion of
    # the executable via a Phase 3 v2 patcher write, and read it here.

    # ------------------------------------------------------------------
    # game_watcher
    # ------------------------------------------------------------------

    async def game_watcher(self, ctx: BizHawkClientContext) -> None:
        if ctx.server is None or ctx.slot is None:
            return
        if self._location_name_to_id is None:
            from . import DigimonWorldWorld
            self._location_name_to_id = DigimonWorldWorld.location_name_to_id
            self._item_name_to_id = DigimonWorldWorld.item_name_to_id
        if self._vanilla_grant_chests is None and ctx.slot_data is not None:
            self._vanilla_grant_chests = frozenset(
                ctx.slot_data.get("vanilla_grant_chests", ()),
            )
        if self._fast_drimogemon is None and ctx.slot_data is not None:
            self._fast_drimogemon = bool(ctx.slot_data.get("fast_drimogemon", 0))
        if self._easy_monochromon is None and ctx.slot_data is not None:
            self._easy_monochromon = bool(ctx.slot_data.get("easy_monochromon", 0))
        if self._goal is None and ctx.slot_data is not None:
            self._goal = int(ctx.slot_data.get("goal", 0))
        if self._prosperity_goal is None and ctx.slot_data is not None:
            # Default to vanilla 50 PP for backward compatibility with
            # pre-Phase-9 seeds (the option didn't exist; goal: prosperity
            # auto-fired at 50).
            self._prosperity_goal = int(ctx.slot_data.get("prosperity_goal", 50))
        if self._stat_gain_multiplier is None and ctx.slot_data is not None:
            self._stat_gain_multiplier = int(
                ctx.slot_data.get("stat_gain_multiplier", 1),
            )
        if self._bridge_always_open is None and ctx.slot_data is not None:
            # BridgeUnlock: 0 = always_open (default), 1 = vanilla.
            self._bridge_always_open = (
                int(ctx.slot_data.get("bridge_unlock", 0)) == 0
            )
        if self._great_canyon_always_open is None and ctx.slot_data is not None:
            # GreatCanyonUnlock: 0 = always_open (default), 1 = vanilla.
            self._great_canyon_always_open = (
                int(ctx.slot_data.get("great_canyon_unlock", 0)) == 0
            )
        if self._god_mode is None and ctx.slot_data is not None:
            self._god_mode = bool(ctx.slot_data.get("god_mode", 0))

        try:
            await self._check_locations(ctx)
            await self._deliver_items(ctx)
            await self._reconcile_recruits(ctx)
            await self._reconcile_keyitem_flags(ctx)
            await self._reconcile_merit_shop_sentinel(ctx)
            await self._wipe_chest_sentinels(ctx)
            if self._fast_drimogemon:
                await self._enforce_fast_drimogemon(ctx)
            if self._easy_monochromon:
                await self._enforce_easy_monochromon(ctx)
            if self._stat_gain_multiplier and self._stat_gain_multiplier > 1:
                await self._enforce_stat_gain_multiplier(ctx)
            await self._enforce_prosperity(ctx)
            await self._enforce_agumon_recruited(ctx)
            if self._bridge_always_open:
                await self._enforce_bridge_always_open(ctx)
            if self._great_canyon_always_open:
                await self._enforce_great_canyon_always_open(ctx)
            if self._god_mode:
                await self._enforce_god_mode(ctx)
            await self._check_goal(ctx)
        except bizhawk.RequestFailedError:
            # Lua connector failed to respond; exit the handler and
            # let the BizHawk framework reconnect on the next tick.
            return

    async def _wipe_chest_sentinels(self, ctx: BizHawkClientContext) -> None:
        """Remove any AP chest-sentinel items (id 129) from the player's
        inventory.

        Defensive belt-and-suspenders pairing with the chestGiveItem
        wrapper installed by Phase 5 piece A's patcher: the wrapper
        intercepts ``giveItem(129, ...)`` at the script-bytecode chest
        pickup callsite and short-circuits the inventory write. Live
        testing showed AP ITEM still landing in inventory in some
        flows — likely because vanilla DW1 has additional grant paths
        (NPC dialog, plot triggers, possibly a non-script chest path)
        that bypass the patched ``jal``. This wipe catches whatever the
        wrapper missed: each tick, scan the 10 inventory slots and
        clear any holding the sentinel ID.

        Cost: a single 10-byte read; writes only when sentinels are
        actually present.
        """

        ids = (await bizhawk.read(
            ctx.bizhawk_ctx,
            [(RAM_INVENTORY_ITEM_IDS_BASE, RAM_INVENTORY_SLOT_COUNT, DOMAIN_MAIN_RAM)],
        ))[0]
        if len(ids) != RAM_INVENTORY_SLOT_COUNT:
            return

        writes: list[RamWrite] = []
        for slot in range(RAM_INVENTORY_SLOT_COUNT):
            if ids[slot] == AP_CHEST_SENTINEL_ITEM_ID:
                writes.append((
                    RAM_INVENTORY_ITEM_IDS_BASE + slot,
                    [RAM_INVENTORY_EMPTY_SLOT_ID],
                    DOMAIN_MAIN_RAM,
                ))
                writes.append((
                    RAM_INVENTORY_QUANTITIES_BASE + slot,
                    [0],
                    DOMAIN_MAIN_RAM,
                ))
        if writes:
            await bizhawk.write(ctx.bizhawk_ctx, writes)

    async def _reconcile_recruits(self, ctx: BizHawkClientContext) -> None:
        """Defensive enforcement: keep BEATEN_BLOCK bits set for any
        recruit AP has delivered, plus any Digimon bundled into a
        Progressive ladder item the player has received.

        Plan A revised: AP delivery of an individual ``<X> Recruit``
        item writes bit 720+X to BEATEN_BLOCK in
        :func:`_make_recruit_deliverer`. The Phase 7 (2026-05-09)
        bundling rework replaced 26 individual recruit items with 6
        Progressive ladder items (``Progressive Item Shop``,
        ``Progressive Secret Shop``, ``Progressive Restaurant``,
        ``Progressive Arena``, ``Progressive Green Gym``,
        ``Progressive Treasure Hunt``). When the Nth copy of a
        Progressive item is received, this method ORs in BEATEN bits
        for every Digimon up through tier N of that ladder.

        This per-tick pass also defends against any vanilla code that
        might clear bytes in the BEATEN block (unlikely but safe).
        It NEVER touches the recruit-block (200+X) — vanilla owns
        that, and clearing recruit bits would break wild-spawn
        suppression.

        Idempotent: only writes the bytes whose value actually
        changed.
        """

        # Collect (beaten_block_off, bit_index) tuples for every bit
        # that should be set right now.
        bits_to_set: set[tuple[int, int]] = set()

        # 1. Individual recruit items (the 18 non-bundled recruits).
        received_dids: set[int] = set()
        progressive_counts: dict[str, int] = {}
        for item in ctx.items_received:
            item_name = ctx.item_names.lookup_in_game(item.item, ctx.game)
            did = digimon_id_for_recruit_item(item_name)
            if did is not None:
                received_dids.add(did)
            if item_name in PROGRESSIVE_BUNDLES:
                progressive_counts[item_name] = (
                    progressive_counts.get(item_name, 0) + 1
                )

        for row in _RECRUIT_TOGGLE_TARGETS:
            if row.digimon_id in received_dids:
                bits_to_set.add((row.beaten_block_off, row.beaten_bit))

        # 2. Progressive ladder items — set BEATEN bits for every
        # Digimon in tiers 1..count of each Progressive ladder. Tiers
        # are cumulative: receiving the Nth copy implicitly satisfies
        # tiers 1..N.
        for prog_name, count in progressive_counts.items():
            tiers = PROGRESSIVE_BUNDLES[prog_name]
            for tier_idx in range(min(count, len(tiers))):
                for digimon_name in tiers[tier_idx]:
                    if digimon_name not in BEATEN_RAM_BITS:
                        # Defensive: a bundle entry references a
                        # Digimon without a BEATEN bit (e.g. Gekomon
                        # if he's added later without a recruit-bit
                        # mapping). Skip silently.
                        continue
                    byte_addr, bit_idx = BEATEN_RAM_BITS[digimon_name]
                    block_off = byte_addr - BEATEN_BLOCK_BASE
                    if 0 <= block_off < BEATEN_BLOCK_SIZE:
                        bits_to_set.add((block_off, bit_idx))

        if not bits_to_set:
            return

        try:
            blocks = await bizhawk.read(
                ctx.bizhawk_ctx,
                [(BEATEN_BLOCK_BASE, BEATEN_BLOCK_SIZE, DOMAIN_MAIN_RAM)],
            )
        except bizhawk.RequestFailedError:
            return
        if len(blocks) != 1 or len(blocks[0]) != BEATEN_BLOCK_SIZE:
            return
        beaten_bytes = bytearray(blocks[0])
        original = bytes(beaten_bytes)

        for block_off, bit_idx in bits_to_set:
            beaten_bytes[block_off] |= 1 << bit_idx

        writes: list[RamWrite] = [
            (BEATEN_BLOCK_BASE + off, [beaten_bytes[off]], DOMAIN_MAIN_RAM)
            for off in range(BEATEN_BLOCK_SIZE)
            if beaten_bytes[off] != original[off]
        ]
        if writes:
            await bizhawk.write(ctx.bizhawk_ctx, writes)

    async def _reconcile_merit_shop_sentinel(self, ctx: BizHawkClientContext) -> None:
        """For each item in :data:`MERIT_SHOP_DISPATCH`, if its AP
        location trigger is set, ensure ITEM_PARA[item_id]'s
        ``meritValue`` field is bumped to the unaffordable post-purchase
        value (:data:`AP_ITEM_BOUGHT_MERIT_VALUE_BYTES`). Handles
        save/reload (ITEM_PARA reloads from disc on boot, so any
        runtime patch is reverted; this ticker re-applies the bump
        whenever the persistent trigger says the player already bought
        the item).

        Surgical: only the 2-byte ``meritValue`` field at offset
        ``ITEM_PARA_MERIT_VALUE_OFFSET`` (= 24) is touched. The slot's
        name, icon CLUT index, sortingValue, etc. all stay vanilla — so
        for slot 83 (also the chest sentinel), the chest pickup
        textbox continues to read "Found AP Item!" cleanly post-
        purchase.

        Idempotent: reads the trigger byte and the slot's current
        ``meritValue``; only writes when both "trigger set" and "merit
        value not already at the post-purchase value" hold.
        """

        if not MERIT_SHOP_DISPATCH:
            return

        target_merit_bytes = list(AP_ITEM_BOUGHT_MERIT_VALUE_BYTES)

        for item_id, trigger_id in MERIT_SHOP_DISPATCH:
            trigger_byte_addr = AP_TRIGGER_ARRAY_BASE + (trigger_id // 8)
            trigger_mask = 1 << (trigger_id % 8)
            merit_addr = (
                RAM_ITEM_PARA
                + item_id * ROM_ITEM_TABLE_ENTRY_SIZE
                + ITEM_PARA_MERIT_VALUE_OFFSET
            )

            try:
                blocks = await bizhawk.read(
                    ctx.bizhawk_ctx,
                    [
                        (trigger_byte_addr, 1, DOMAIN_MAIN_RAM),
                        (merit_addr, len(target_merit_bytes), DOMAIN_MAIN_RAM),
                    ],
                )
            except bizhawk.RequestFailedError:
                return
            if (
                len(blocks) != 2
                or len(blocks[0]) != 1
                or len(blocks[1]) != len(target_merit_bytes)
            ):
                continue
            trigger_set = (blocks[0][0] & trigger_mask) != 0
            current_merit = list(blocks[1])
            if not trigger_set:
                continue
            if current_merit == target_merit_bytes:
                continue
            # Trigger is set but meritValue isn't bumped — apply.
            try:
                await bizhawk.write(
                    ctx.bizhawk_ctx,
                    [(merit_addr, target_merit_bytes, DOMAIN_MAIN_RAM)],
                )
            except bizhawk.RequestFailedError:
                return

    async def _reconcile_keyitem_flags(self, ctx: BizHawkClientContext) -> None:
        """Pin key-item trigger bits to AP-delivered state each tick.

        DW1 stores several "key items" as bits in the trigger array
        rather than as inventory entries. AP delivery of those items
        writes the matching bit; this watcher runs each tick and forces
        every bit in :data:`KEYITEM_DELIVERY_RAM_BITS` to match what AP
        has actually delivered:

        * AP delivered the item -> bit must be set.
        * AP has not delivered  -> bit must be cleared, even if a
          vanilla cutscene just flipped it.

        For rod items, the targeted bits are triggers 45 and 46 — the
        same gates the fishing minigame reads
        (``getBestFishingRod()`` in
        ``references/DW1-SydPatches/src/Fishing.cpp``). The
        rod-give cutscene sets trigger 45 simultaneously with trigger
        320 (the script's "rod-given" memory bit); the watcher clears
        45 within ~100 ms if AP hasn't delivered the rod, which gates
        fishing on AP delivery without disturbing the script's memory
        bit. The corresponding location signal
        (``Old Fishrod Pickup`` polled at OLD_FISHROD_GATE = trigger
        45) latches in the same instruction window the cutscene plays
        in, so the AP send fires before the watcher clears the bit.

        Idempotent: only writes when the byte's actual value differs
        from the target.
        """

        if not KEYITEM_DELIVERY_RAM_BITS:
            return

        received_keyitem_names = {
            ctx.item_names.lookup_in_game(item.item, ctx.game)
            for item in ctx.items_received
        }

        # Group target bits by byte address — multiple key items may share
        # a byte in the trigger array, so we coalesce reads/writes.
        targets_by_byte: dict[int, list[tuple[int, bool]]] = {}
        for item_name, (byte_addr, bit_index) in KEYITEM_DELIVERY_RAM_BITS.items():
            should_be_set = item_name in received_keyitem_names
            targets_by_byte.setdefault(byte_addr, []).append((bit_index, should_be_set))

        try:
            blocks = await bizhawk.read(
                ctx.bizhawk_ctx,
                [(addr, 1, DOMAIN_MAIN_RAM) for addr in targets_by_byte],
            )
        except bizhawk.RequestFailedError:
            return
        if any(len(b) != 1 for b in blocks):
            return

        writes: list[RamWrite] = []
        for (byte_addr, bits), block in zip(
            targets_by_byte.items(), blocks, strict=True,
        ):
            current = block[0]
            new_value = current
            for bit_index, should_be_set in bits:
                mask = 1 << bit_index
                if should_be_set:
                    new_value |= mask
                else:
                    new_value &= ~mask & 0xFF
            if new_value != current:
                writes.append((byte_addr, [new_value], DOMAIN_MAIN_RAM))
        if writes:
            await bizhawk.write(ctx.bizhawk_ctx, writes)

    async def _enforce_agumon_recruited(self, ctx: BizHawkClientContext) -> None:
        """Pin Agumon's recruit-completion bit on every tick.

        Agumon is the in-city bank NPC and a key delivery mechanic;
        the player must always have him in city for AP item delivery
        to work. Pre-setting bit 203 has a side effect — vanilla DW1
        reads the same bit when deciding whether to spawn the wild
        Agumon NPC for the recruit fight, so pre-setting it blocks
        that fight forever. Per the user's preference, accept the
        Agumon location loss (better than risking the bank to break
        and losing items). The Agumon location is dropped from the
        AP pool in :data:`worlds.digimon_world.locations._RECRUIT_REGIONS`.

        Cheap: one byte read, at most one byte write per tick. The
        write is OR-into-existing (idempotent).
        """

        byte_addr, bit_index = AGUMON_RECRUIT_BIT
        bit_mask = 1 << bit_index
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(byte_addr, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current:
            return
        if current[0] & bit_mask:
            return  # already set
        await bizhawk.write(
            ctx.bizhawk_ctx,
            [(byte_addr, [current[0] | bit_mask], DOMAIN_MAIN_RAM)],
        )

    async def _enforce_fast_drimogemon(self, ctx: BizHawkClientContext) -> None:
        """Collapse Drimogemon's 10-day dig wait to "already dug" state.

        Mirrors DWAP's ``EnsureWorldFlags`` for the Fast Drimogemon
        option. Once :data:`RAM_HAS_BEATEN_DRIMOGEMON` reads 1 (i.e.
        the player has beaten the Drimogemon fight), pin the three
        Lava Cave tunnel-state bytes so the player can walk straight
        through without waiting in-game days.

        Cheap: one batched 4-byte read per tick; writes only fire
        when the targets aren't already set.
        """

        addrs = [
            (RAM_HAS_BEATEN_DRIMOGEMON, 1, DOMAIN_MAIN_RAM),
            (RAM_MERAMON_TUNNEL_DRIMO_STATE, 1, DOMAIN_MAIN_RAM),
            (RAM_MERAMON_TUNNEL_STATE, 1, DOMAIN_MAIN_RAM),
            (RAM_MERAMON_TUNNEL_DIGGING_STATE, 1, DOMAIN_MAIN_RAM),
        ]
        try:
            blocks = await bizhawk.read(ctx.bizhawk_ctx, addrs)
        except bizhawk.RequestFailedError:
            return
        if any(len(b) != 1 for b in blocks):
            return
        beaten, drimo_state, tunnel_state, digging_state = (b[0] for b in blocks)
        if beaten != 1:
            return  # Drimogemon not beaten yet — leave dig sequence alone

        writes: list[RamWrite] = []
        if drimo_state != FAST_DRIMOGEMON_DRIMO_STATE_TARGET:
            writes.append((
                RAM_MERAMON_TUNNEL_DRIMO_STATE,
                [FAST_DRIMOGEMON_DRIMO_STATE_TARGET],
                DOMAIN_MAIN_RAM,
            ))
        if tunnel_state != FAST_DRIMOGEMON_TUNNEL_STATE_TARGET:
            writes.append((
                RAM_MERAMON_TUNNEL_STATE,
                [FAST_DRIMOGEMON_TUNNEL_STATE_TARGET],
                DOMAIN_MAIN_RAM,
            ))
        if digging_state != FAST_DRIMOGEMON_DIGGING_STATE_TARGET:
            writes.append((
                RAM_MERAMON_TUNNEL_DIGGING_STATE,
                [FAST_DRIMOGEMON_DIGGING_STATE_TARGET],
                DOMAIN_MAIN_RAM,
            ))
        if writes:
            await bizhawk.write(ctx.bizhawk_ctx, writes)

    async def _enforce_bridge_always_open(self, ctx: BizHawkClientContext) -> None:
        """Pin the Tropical Jungle bridge-fixed trigger bit.

        Mirrors :meth:`_enforce_agumon_recruited`: read the byte, OR in
        the target bit if it's not already set, write back. The bit is
        sticky in the save file once set, so this is effectively a
        one-time write per save load. Cheap: one byte read, at most
        one byte write per tick.
        """

        byte_addr, bit_index = RAM_TROPICAL_JUNGLE_BRIDGE_FIXED
        bit_mask = 1 << bit_index
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(byte_addr, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current:
            return
        if current[0] & bit_mask:
            return  # already set
        await bizhawk.write(
            ctx.bizhawk_ctx,
            [(byte_addr, [current[0] | bit_mask], DOMAIN_MAIN_RAM)],
        )

    async def _enforce_great_canyon_always_open(self, ctx: BizHawkClientContext) -> None:
        """Pin the Great Canyon bridge-unlocked trigger bit.

        Same shape as :meth:`_enforce_bridge_always_open`. The byte at
        :data:`RAM_GREAT_CANYON_BRIDGE_UNLOCKED` holds at least one
        unrelated story-event flag in lower bits, so the write is a
        bit-OR rather than a byte assignment.
        """

        byte_addr, bit_index = RAM_GREAT_CANYON_BRIDGE_UNLOCKED
        bit_mask = 1 << bit_index
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(byte_addr, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current:
            return
        if current[0] & bit_mask:
            return  # already set
        await bizhawk.write(
            ctx.bizhawk_ctx,
            [(byte_addr, [current[0] | bit_mask], DOMAIN_MAIN_RAM)],
        )

    async def _enforce_easy_monochromon(self, ctx: BizHawkClientContext) -> None:
        """Auto-resolve the Monochromon meat-trade minigame.

        Mirrors DWAP's ``EnsureWorldFlags`` for the Easy Monochromon
        option. While the player is on the Monochromon business map
        (id :data:`EASY_MONOCHROMON_MAP_ID`), pin the profit counter
        at :data:`RAM_MONOCHROME_PROFIT` to the target value so the
        trade resolves immediately. No-op on every other map.
        """

        try:
            blocks = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (CURRENT_SCREEN_ADDR, 1, DOMAIN_MAIN_RAM),
                    (RAM_MONOCHROME_PROFIT, 4, DOMAIN_MAIN_RAM),
                ],
            )
        except bizhawk.RequestFailedError:
            return
        if len(blocks) != 2 or len(blocks[0]) != 1 or len(blocks[1]) != 4:
            return
        screen_id = blocks[0][0]
        if screen_id != EASY_MONOCHROMON_MAP_ID:
            return
        current_profit = int.from_bytes(blocks[1], "little")
        if current_profit >= EASY_MONOCHROMON_PROFIT_TARGET:
            return
        await bizhawk.write(
            ctx.bizhawk_ctx,
            [(
                RAM_MONOCHROME_PROFIT,
                list(EASY_MONOCHROMON_PROFIT_TARGET.to_bytes(4, "little")),
                DOMAIN_MAIN_RAM,
            )],
        )

    async def _enforce_stat_gain_multiplier(self, ctx: BizHawkClientContext) -> None:
        """Pin DW1's stat-gain multiplier and stat cap.

        Mirrors DWAP's ``SetExpMultiplier`` for the Stat Gain Multiplier
        option. Vanilla DW1 stores three adjacent values that govern
        training-stat behaviour: a cap-unlock flag, a multiplier
        applied to gains, and a hard cap. Pinning all three each tick
        bumps training speed by the player-chosen factor.

        Cheap: one batched 3-write whenever any of the targets drift
        from spec; otherwise no-op.
        """

        assert self._stat_gain_multiplier is not None
        target_mult = self._stat_gain_multiplier * 10
        try:
            blocks = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (RAM_STAT_CAP_FLAG, 1, DOMAIN_MAIN_RAM),
                    (RAM_STAT_GAIN_MULT, 2, DOMAIN_MAIN_RAM),
                    (RAM_STAT_CAP, 2, DOMAIN_MAIN_RAM),
                ],
            )
        except bizhawk.RequestFailedError:
            return
        if (len(blocks) != 3 or len(blocks[0]) != 1
                or len(blocks[1]) != 2 or len(blocks[2]) != 2):
            return
        cur_flag = blocks[0][0]
        cur_mult = int.from_bytes(blocks[1], "little")
        cur_cap = int.from_bytes(blocks[2], "little")

        writes: list[RamWrite] = []
        if cur_flag != STAT_CAP_FLAG_TARGET:
            writes.append((RAM_STAT_CAP_FLAG, [STAT_CAP_FLAG_TARGET], DOMAIN_MAIN_RAM))
        if cur_mult != target_mult:
            writes.append((
                RAM_STAT_GAIN_MULT,
                list(target_mult.to_bytes(2, "little")),
                DOMAIN_MAIN_RAM,
            ))
        if cur_cap != STAT_CAP_TARGET:
            writes.append((
                RAM_STAT_CAP,
                list(STAT_CAP_TARGET.to_bytes(2, "little")),
                DOMAIN_MAIN_RAM,
            ))
        if writes:
            await bizhawk.write(ctx.bizhawk_ctx, writes)

    async def _enforce_god_mode(self, ctx: BizHawkClientContext) -> None:
        """Pin partner stats to max while the GodMode option is on.

        Writes ``999`` to Offense/Defense/Speed/Brain (each u16 LE) and
        ``9999`` to Max HP / Max MP (each u16 LE). Also pins the Auto
        Pilot bank slot to 99 and the bits counter to ``_MONEY_CAP`` so
        the player can warp back from anywhere and pay Birdramon-Messenger
        flight fees indefinitely. Only writes the bytes that drift, so
        steady-state cost is one read per tick.

        Testing aid only — see :class:`worlds.digimon_world.options.GodMode`.
        """

        stat_target = 999
        max_hp_mp_target = 9999
        u16_targets: list[tuple[int, int]] = [
            (RAM_CURRENT_OFFENSE, stat_target),
            (RAM_CURRENT_DEFENSE, stat_target),
            (RAM_CURRENT_SPEED, stat_target),
            (RAM_CURRENT_BRAINS, stat_target),
            (RAM_MAX_HP, max_hp_mp_target),
            (RAM_MAX_MP, max_hp_mp_target),
        ]
        # Auto Pilot lives in DW1 internal item slot 22 -> RAM_ITEM_BANK_BASE + 22.
        auto_pilot_addr = RAM_ITEM_BANK_BASE + 22

        try:
            u16_blocks = await bizhawk.read(
                ctx.bizhawk_ctx,
                [(addr, 2, DOMAIN_MAIN_RAM) for addr, _ in u16_targets],
            )
            auto_pilot_block, money_block = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (auto_pilot_addr, 1, DOMAIN_MAIN_RAM),
                    (RAM_CURRENT_BITS, 4, DOMAIN_MAIN_RAM),
                ],
            )
        except bizhawk.RequestFailedError:
            return
        if (
            len(u16_blocks) != len(u16_targets)
            or any(len(b) != 2 for b in u16_blocks)
            or len(auto_pilot_block) != 1
            or len(money_block) != 4
        ):
            return

        writes: list[RamWrite] = []
        for (addr, target), block in zip(u16_targets, u16_blocks, strict=True):
            current = int.from_bytes(block, "little")
            if current != target:
                writes.append((
                    addr, list(target.to_bytes(2, "little")), DOMAIN_MAIN_RAM,
                ))
        if auto_pilot_block[0] != _BANK_QUANTITY_CAP:
            writes.append((
                auto_pilot_addr, [_BANK_QUANTITY_CAP], DOMAIN_MAIN_RAM,
            ))
        if int.from_bytes(money_block, "little") != _MONEY_CAP:
            writes.append((
                RAM_CURRENT_BITS,
                list(_MONEY_CAP.to_bytes(4, "little")),
                DOMAIN_MAIN_RAM,
            ))
        if writes:
            await bizhawk.write(ctx.bizhawk_ctx, writes)

    async def _enforce_prosperity(self, ctx: BizHawkClientContext) -> None:
        """Pin the in-game prosperity byte to the AP-controlled value.

        AP is the single source of truth for prosperity in this world:
        the byte must equal ``ProsperityPoint count *
        PROSPERITY_PER_ITEM`` (saturating at
        :data:`PROSPERITY_RAM_CAP`). Any vanilla DW1 attempt to bump
        prosperity (e.g. the recruit-derived recompute) is overwritten
        on the next tick.

        Cheap: one RAM read, at most one byte write.
        """

        pp_item_count = sum(
            1
            for item in ctx.items_received
            if ctx.item_names.lookup_in_game(item.item, ctx.game)
            == PROSPERITY_POINT_NAME
        )
        target = min(PROSPERITY_RAM_CAP, pp_item_count * PROSPERITY_PER_ITEM)
        current = (await bizhawk.read(
            ctx.bizhawk_ctx, [(RAM_PROSPERITY_POINTS, 1, DOMAIN_MAIN_RAM)],
        ))[0]
        if not current:
            return
        if current[0] == target:
            return
        await bizhawk.write(
            ctx.bizhawk_ctx, [(RAM_PROSPERITY_POINTS, [target], DOMAIN_MAIN_RAM)],
        )

    async def _check_locations(self, ctx: BizHawkClientContext) -> None:
        """Poll per-location RAM signals and send LocationChecks for new ones.

        Three detection styles:

        * **Bit-set** (chests, recruits, key-item gates) — read one byte,
          test a single bit.
        * **Threshold** (currently unused; reserved) — read one byte,
          compare ``>= min_value``.
        * **Nibble** (card vending, opt-in) — read the 33-byte card
          block once, test the 4-bit count for each card. ``> 0`` means
          owned. Only polled if the player has at least one card AP
          location in their slot (i.e. the option was on).
        """

        assert self._location_name_to_id is not None
        new_checks: list[int] = []

        for location_name, (offset, bit_index) in LOCATION_RAM_BITS.items():
            location_id = self._location_name_to_id.get(location_name)
            if location_id is None or location_id in ctx.locations_checked:
                continue
            data = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(offset, 1, DOMAIN_MAIN_RAM)],
            ))[0]
            if data and data[0] & (1 << bit_index):
                new_checks.append(location_id)

        for location_name, (offset, min_value) in LOCATION_RAM_THRESHOLDS.items():
            location_id = self._location_name_to_id.get(location_name)
            if location_id is None or location_id in ctx.locations_checked:
                continue
            data = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(offset, 1, DOMAIN_MAIN_RAM)],
            ))[0]
            if data and data[0] >= min_value:
                new_checks.append(location_id)

        await self._check_card_locations(ctx, new_checks)

        if new_checks:
            checked = await ctx.check_locations(new_checks)
            for location_id in checked:
                ctx.locations_checked.add(location_id)

    async def _check_card_locations(
        self, ctx: BizHawkClientContext, new_checks: list[int],
    ) -> None:
        """Append any newly-owned card AP locations to ``new_checks``.

        Reads the contiguous 33-byte card-counter block in one call. Each
        card occupies one nibble; ``count > 0`` means the player has
        bought it at least once. Cards already in
        ``ctx.locations_checked`` are skipped.

        Skips the entire batched read when no card AP location for this
        slot exists on the server (the
        :class:`worlds.digimon_world.options.CardLocations` option is
        off, or the server hasn't sent location data yet).
        """

        assert self._location_name_to_id is not None
        if not ctx.server_locations:
            return
        # Cheap guard: no card AP id is in the server's location set,
        # meaning the option is off for this slot.
        card_ids = {
            self._location_name_to_id[name] for name in CARD_LOCATION_NIBBLES
        }
        if card_ids.isdisjoint(ctx.server_locations):
            return
        block = (await bizhawk.read(
            ctx.bizhawk_ctx,
            [(CARD_BLOCK_BASE, CARD_BLOCK_SIZE, DOMAIN_MAIN_RAM)],
        ))[0]
        if len(block) != CARD_BLOCK_SIZE:
            return
        for location_name, nibble in CARD_LOCATION_NIBBLES.items():
            location_id = self._location_name_to_id.get(location_name)
            if (location_id is None
                    or location_id in ctx.locations_checked
                    or location_id not in ctx.server_locations):
                continue
            byte_val = block[nibble.byte_addr - CARD_BLOCK_BASE]
            count = (byte_val >> 4) if nibble.is_upper else (byte_val & 0x0F)
            if count > 0:
                new_checks.append(location_id)

    async def _deliver_items(self, ctx: BizHawkClientContext) -> None:
        """Apply the next pending item from ``ctx.items_received`` to RAM.

        Algorithm:

        1. Read the items_received counter from
           :data:`ITEMS_RECEIVED_COUNTER`'s scratch bytes.
        2. If the counter equals ``len(ctx.items_received)``, nothing
           pending; return.
        3. Otherwise, look up the route for the next pending item, run
           the deliverer (which reads RAM and computes the write list),
           append the counter increment, and submit a single
           :func:`bizhawk.write` for both writes atomically.

        Atomicity matters: if we wrote the item bytes but not the
        counter, a crash or disconnect between the two writes would
        cause re-delivery on reconnect. Bundling them in one
        :func:`bizhawk.write` call ensures both land or neither does.

        Until :data:`ITEMS_RECEIVED_COUNTER` is set (still pending live
        verification of the chosen scratch byte), the body early-
        returns and the client is *watching only* — no RAM writes.
        """

        if not ITEM_DELIVERY_ROUTES or ITEMS_RECEIVED_COUNTER is None:
            return

        # Read the 3-byte counter block: [magic, counter_lo, counter_hi].
        # Treat a missing/wrong magic byte as "counter == 0" so a fresh
        # save (block all zeros) starts delivery from item 0, and any
        # accidental clobber is automatically self-healing on next write.
        counter_data = (await bizhawk.read(
            ctx.bizhawk_ctx,
            [(ITEMS_RECEIVED_COUNTER_ADDR,
              ITEMS_RECEIVED_COUNTER_SIZE, DOMAIN_MAIN_RAM)],
        ))[0]
        if counter_data[0] == ITEMS_RECEIVED_COUNTER_MAGIC:
            applied = int.from_bytes(counter_data[1:3], "little")
        else:
            applied = 0  # uninitialized or clobbered — start over
        if applied >= len(ctx.items_received):
            return  # nothing pending

        next_item = ctx.items_received[applied]
        item_name = ctx.item_names.lookup_in_game(next_item.item, ctx.game)

        next_counter = applied + 1
        counter_advance: list[RamWrite] = [(
            ITEMS_RECEIVED_COUNTER_ADDR,
            [
                ITEMS_RECEIVED_COUNTER_MAGIC,
                next_counter & 0xFF,
                (next_counter >> 8) & 0xFF,
            ],
            DOMAIN_MAIN_RAM,
        )]

        # Vanilla-grant chest path. When this item came from one of the
        # player's own vanilla-grant chests, vanilla DW1 normally hands
        # the item to the player via the chest-pickup flow — so the
        # bank deliverer must not also fire (would double-deliver).
        # But the AP location can also be marked checked WITHOUT the
        # player physically opening the chest (``send_location``,
        # ``!collect``, AP coop). The chest's "taken" bit
        # distinguishes the two cases:
        #
        # * Bit set  -> player physically opened the chest. Vanilla
        #   ``giveItem`` already fired. Skip the bank write.
        # * Bit clear -> the location got checked some other way and no
        #   in-game ``giveItem`` ran. Fall through to the normal
        #   deliverer AND set the chest bit ourselves so a subsequent
        #   physical chest-open just shows the chest as already taken
        #   (vanilla skips the giveItem path entirely on already-taken
        #   chests, so no double-delivery).
        if (
            next_item.player == ctx.slot
            and self._vanilla_grant_chests is not None
        ):
            location_name = ctx.location_names.lookup_in_game(
                next_item.location, ctx.game,
            )
            if location_name in self._vanilla_grant_chests:
                chest_bit = DWAP_CHEST_RAM_BITS.get(location_name)
                if chest_bit is None:
                    # Defensive: every vanilla-grant chest name should
                    # also be in DWAP_CHEST_RAM_BITS (asserted in
                    # data.addresses). If the mapping ever drifts,
                    # fall back to the historical skip behavior so we
                    # don't double-deliver.
                    await bizhawk.write(ctx.bizhawk_ctx, counter_advance)
                    return
                byte_addr, bit_index = chest_bit
                mask = 1 << bit_index
                current = (await bizhawk.read(
                    ctx.bizhawk_ctx, [(byte_addr, 1, DOMAIN_MAIN_RAM)],
                ))[0]
                if not current:
                    return  # transient read failure; retry next tick
                if current[0] & mask:
                    # Chest already opened in-game -> vanilla giveItem
                    # already fired. Just advance the counter.
                    await bizhawk.write(ctx.bizhawk_ctx, counter_advance)
                    return
                # Chest bit clear -> deliver via the normal route AND
                # mark the chest taken so a later physical open doesn't
                # fire vanilla giveItem on the same item.
                counter_advance.append((
                    byte_addr, [current[0] | mask], DOMAIN_MAIN_RAM,
                ))

        deliverer = ITEM_DELIVERY_ROUTES.get(item_name)
        if deliverer is None:
            # Unknown item — increment the counter anyway so we don't
            # block on it forever, and log so RE work can add a route.
            logger.warning("No delivery route for item %r; skipping", item_name)
            await bizhawk.write(ctx.bizhawk_ctx, counter_advance)
            return

        write_list = await deliverer(ctx)
        write_list.extend(counter_advance)
        await bizhawk.write(ctx.bizhawk_ctx, write_list)

    async def _check_goal(self, ctx: BizHawkClientContext) -> None:
        """Fire ``StatusUpdate(GoalComplete)`` for the configured goal.

        * ``goal = machinedramon`` (slot_data ``goal == 0``): fires once
          DW1's post-Machinedramon victory cutscene runs ``setTrigger 50``
          (Analogman defeated) — bit 2 of
          :data:`RAM_MACHINEDRAMON_DEFEATED_BYTE`. The setter is at
          Script 184 §51 offset 0x4406, fires immediately after the
          "Peace has returned to File Island" dialog and before the
          warp into the C-level credits roll. The bit is never cleared
          by vanilla and lives outside the changeMap-wrapper clobber
          range — so a single poll-and-test is sufficient and the bit
          survives screen transitions / save+reload. The
          ``prosperity_goal`` option doesn't gate completion here on
          its own (Mt. Infinity's in-game gate already enforces the
          threshold before the player can fight Machinedramon), but
          AP's ``Final Battle`` rule in rules.py mirrors the threshold
          for logic correctness.
        * ``goal = prosperity`` (slot_data ``goal == 1``): fires once
          in-game prosperity reaches the ``prosperity_goal`` threshold
          (slot_data ``prosperity_goal``, default 50). Each delivered
          ``Prosperity Point`` AP item bumps prosperity by
          :data:`PROSPERITY_PER_ITEM` = 3, so the threshold is reachable
          once enough items have been received.

        While ``slot_data`` hasn't arrived yet (``_goal is None``) we
        do nothing — avoids a spurious release on a stale read before
        the goal is known.
        """

        if self._goal_complete_sent or ctx.finished_game:
            return
        if self._goal is None or self._prosperity_goal is None:
            return

        if self._goal == 0:  # machinedramon
            try:
                data = (await bizhawk.read(
                    ctx.bizhawk_ctx,
                    [(RAM_MACHINEDRAMON_DEFEATED_BYTE, 1, DOMAIN_MAIN_RAM)],
                ))[0]
            except bizhawk.RequestFailedError:
                return
            if not data or not (data[0] & RAM_MACHINEDRAMON_DEFEATED_MASK):
                return
        elif self._goal == 1:  # prosperity
            try:
                data = (await bizhawk.read(
                    ctx.bizhawk_ctx,
                    [(RAM_PROSPERITY_POINTS, 1, DOMAIN_MAIN_RAM)],
                ))[0]
            except bizhawk.RequestFailedError:
                return
            if not data or data[0] < self._prosperity_goal:
                return
        else:
            return  # unknown goal value — leave the player to manual !status

        await ctx.send_msgs([{
            "cmd": "StatusUpdate",
            "status": ClientStatus.CLIENT_GOAL,
        }])
        ctx.finished_game = True
        self._goal_complete_sent = True


__all__ = [
    "DOMAIN_MAIN_RAM",
    "ITEMS_RECEIVED_COUNTER",
    "ITEMS_RECEIVED_COUNTER_ADDR",
    "ITEMS_RECEIVED_COUNTER_MAGIC",
    "ITEMS_RECEIVED_COUNTER_SIZE",
    "ITEM_DELIVERY_ROUTES",
    "LOCATION_RAM_BITS",
    "PROSPERITY_RAM_CAP",
    "DigimonWorldClient",
]
