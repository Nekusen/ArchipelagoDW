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
  - :meth:`_check_goal` — if the player's prosperity hits 100, fire
    ``StatusUpdate(GoalComplete)``. This is a placeholder until the
    Machinedramon-defeat flag is RE'd; with the Phase 2 logic the
    seed is logically completable at 50 PP, and 100 PP is the
    in-game maximum, so this trigger is a strict *over*-condition. It
    will never spuriously fire mid-run.

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
from typing import TYPE_CHECKING, ClassVar

import worlds._bizhawk as bizhawk
from NetUtils import ClientStatus
from worlds._bizhawk.client import BizHawkClient

from .data.addresses import (
    AGUMON_RECRUIT_BIT,
    BEATEN_RAM_BITS,
    DWAP_CHEST_RAM_BITS,
    RAM_CURRENT_BITS,
    RAM_ITEM_BANK_BASE,
    RAM_ITEM_BANK_SIZE,
    RAM_PROSPERITY_POINTS,
)
from .items import (
    ITEM_ID_BASE,
    ITEM_NAME_TO_ID,
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


# =============================================================================
# Per-location detection tables
# =============================================================================
#
# * **Chests** — bit-set checks at the vanilla DWAP-mapped trigger bits.
# * **Recruits** (Phase 5 piece C) — bit-set checks at the *beaten* bits
#   produced by the setTrigger wrapper installed in the patcher. When
#   the player completes any recruit cutscene (fight, NPC dialog,
#   plot-trigger), vanilla calls ``setTrigger(200+digimon_id)``; the
#   wrapper redirects that to ``setTrigger(723+digimon_id)`` so the
#   "beaten" bit lights up but vanilla join-city behavior stays
#   suppressed. AP polls the beaten bit to fire the location check.
LOCATION_RAM_BITS: dict[str, tuple[int, int]] = {
    **DWAP_CHEST_RAM_BITS,
    **BEATEN_RAM_BITS,
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

    Phase 5 piece C "deferred write" model: this deliverer is a no-op at
    delivery time. It does NOT immediately write the recruit-completion
    bit (200 + digimon_id), because pre-emptively setting that bit
    triggers vanilla DW1's wild-spawn block — the player can no longer
    encounter Digimon X in the wild (the location for X then never
    fires).

    Instead, the actual write is done by
    :meth:`DigimonWorldClient._reconcile_recruits` once both conditions
    hold: (a) AP has delivered ``<X> Recruit`` (the item is in
    ``ctx.items_received``), and (b) the player has actually beaten
    Digimon X (bit 720+id is SET). At that point — typically right
    after the wild fight completes — the recruit bit is written and
    Digimon X joins the city.

    ``digimon_id`` is unused at delivery time but kept in the deliverer
    factory signature so the dispatch table layout is unchanged.
    """

    _ = digimon_id  # intentionally unused at delivery time

    async def deliver(_ctx: BizHawkClientContext) -> list[RamWrite]:
        return []  # no immediate write; reconcile_recruits handles it

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
# A 2-byte little-endian counter at ``0x001BDFEE..0x001BDFEF`` that the
# client owns and increments after each successful delivery. The
# counter is checked at the start of :meth:`_deliver_items` against
# ``len(ctx.items_received)`` to skip already-delivered items on
# reconnect — without it, additive deliveries (bank quantities, money)
# would duplicate every reconnect.
#
# Why this address: the bytes lie in the gap between the recruit-flag
# region (ends at 0x001BDFED) and the next region of interest. They
# stayed at 0 across **40 markers** of live play covering walking,
# fighting, menus, item use, stat training, save-to-memory-card,
# bank deposits/withdrawals, and multiple recruit/chest events. No
# observed write by DW1 itself. Verified 2026-04-28.
#
# 2 bytes = 65536 max items_received per slot, well above any
# realistic seed size.

ITEMS_RECEIVED_COUNTER: tuple[int, int] | None = (0x001BDFEE, 2)


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

        try:
            await self._check_locations(ctx)
            await self._deliver_items(ctx)
            await self._reconcile_recruits(ctx)
            await self._enforce_prosperity(ctx)
            await self._enforce_agumon_recruited(ctx)
            await self._check_goal(ctx)
        except bizhawk.RequestFailedError:
            # Lua connector failed to respond; exit the handler and
            # let the BizHawk framework reconnect on the next tick.
            return

    async def _reconcile_recruits(self, ctx: BizHawkClientContext) -> None:
        """Dynamic city-toggle of recruit-completion bits (Phase 5 piece C, Path D).

        For every ``"<X> Recruit"`` item AP has delivered, the
        recruit-completion bit (200+digimon_id) is set IFF the player
        is currently in a "city" screen, otherwise cleared.

        Why dynamic toggle: vanilla DW1 reuses bit 200+X for two
        unrelated semantics — wild-spawn gate (set => wild Digimon
        won't appear in field) and city-presence gate (set => city
        model spawns). Pre-emptively setting it on AP delivery blocks
        the wild fight; never setting it removes city presence. We
        sidestep this conflict by setting the bit ONLY while the
        player is in a city screen and clearing it the moment they
        leave. Vanilla wild-spawn gate (in field maps) sees bit 200+X
        cleared → wild X spawns. Vanilla city checks (Map.cpp:1715
        compiled-C plus city-script reads) see bit 200+X set → city
        Digimon are rendered.

        Race window: client polls every ~100ms, so on a screen
        transition there's a window where vanilla loads the new map
        with the previous bit-state. Mitigation: the player can
        re-enter the screen (free reload). Acceptable per user
        guidance.

        :data:`CITY_SCREENS` enumerates the screen IDs we treat as
        "in city". This is the union of `getFileCityTopMap`'s 12
        outdoor-variant return values (168..179), the no-Agumon
        fallback (204), and observed city sub-building screens
        (180, 211, 218, 238). Add more here as the player encounters
        new city sub-areas.

        Idempotent — the writes only fire when the byte's actual
        value differs from desired, never duplicating.
        """

        # Discover every received Recruit item's digimon_id.
        received_dids: set[int] = set()
        for item in ctx.items_received:
            item_name = ctx.item_names.lookup_in_game(item.item, ctx.game)
            did = digimon_id_for_recruit_item(item_name)
            if did is not None:
                received_dids.add(did)
        if not received_dids:
            return

        # Read current screen + the recruit byte block in one batched read.
        try:
            blocks = await bizhawk.read(
                ctx.bizhawk_ctx,
                [
                    (CURRENT_SCREEN_ADDR, 1, DOMAIN_MAIN_RAM),
                    (RECRUIT_BLOCK_BASE, RECRUIT_BLOCK_SIZE, DOMAIN_MAIN_RAM),
                ],
            )
        except bizhawk.RequestFailedError:
            return
        if (len(blocks) != 2 or len(blocks[0]) != 1
                or len(blocks[1]) != RECRUIT_BLOCK_SIZE):
            return
        screen_id = blocks[0][0]
        in_city = screen_id in CITY_SCREENS
        recruit_bytes = bytearray(blocks[1])

        original = bytes(recruit_bytes)

        # For each received Recruit, set the bit if in city / clear if not.
        for did in received_dids:
            recruit_trig = 200 + did  # 203..258
            block_off = recruit_trig // 8 - (RECRUIT_BLOCK_BASE - 0x001BDFCD)
            if not (0 <= block_off < RECRUIT_BLOCK_SIZE):
                continue  # outside cached block (shouldn't happen)
            mask = 1 << (recruit_trig % 8)
            if in_city:
                recruit_bytes[block_off] |= mask
            else:
                recruit_bytes[block_off] &= 0xFF ^ mask

        # Submit only the bytes that actually changed.
        writes: list[RamWrite] = [
            (RECRUIT_BLOCK_BASE + off, [recruit_bytes[off]], DOMAIN_MAIN_RAM)
            for off in range(RECRUIT_BLOCK_SIZE)
            if recruit_bytes[off] != original[off]
        ]
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

        Bit-set checks for chests (vanilla DWAP bits) and recruits
        (vanilla recruit bits — fired by the spawn-point's encounter
        regardless of trigger remap). Threshold checks were dropped
        in v7 along with the K Prosperity locations.
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

        if new_checks:
            checked = await ctx.check_locations(new_checks)
            for location_id in checked:
                ctx.locations_checked.add(location_id)

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

        counter_address, counter_size = ITEMS_RECEIVED_COUNTER
        counter_data = (await bizhawk.read(
            ctx.bizhawk_ctx,
            [(counter_address, counter_size, DOMAIN_MAIN_RAM)],
        ))[0]
        applied = int.from_bytes(counter_data, "little")
        if applied >= len(ctx.items_received):
            return  # nothing pending

        next_item = ctx.items_received[applied]
        item_name = ctx.item_names.lookup_in_game(next_item.item, ctx.game)

        counter_advance: list[RamWrite] = [(
            counter_address,
            list((applied + 1).to_bytes(counter_size, "little")),
            DOMAIN_MAIN_RAM,
        )]

        # Skip the bank delivery when this item came from one of the
        # player's own vanilla-grant chests: vanilla DW1 has already
        # handed the item to the player via the chest-pickup flow.
        # Doubly-delivering would stack the bank quantity. The counter
        # still advances so subsequent items are processed.
        if (
            next_item.player == ctx.slot
            and self._vanilla_grant_chests is not None
        ):
            location_name = ctx.location_names.lookup_in_game(
                next_item.location, ctx.game,
            )
            if location_name in self._vanilla_grant_chests:
                await bizhawk.write(ctx.bizhawk_ctx, counter_advance)
                return

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
        """Fire ``StatusUpdate(GoalComplete)`` once prosperity hits the
        Final-Battle threshold (50).

        Placeholder goal trigger pending Machinedramon-flag RE work.
        Phase 5 piece C: max PP is 50 (25 ``Prosperity Point`` items
        delivering :data:`PROSPERITY_PER_ITEM` = 2 each). The client
        enforces PP from received items, so reaching 50 means the
        player has all PP items and can theoretically clear the Final
        Battle. The AP completion condition still requires AS Decoder
        in addition; we rely on AP fill to ensure that's reachable
        whenever PP is.
        """

        if self._goal_complete_sent or ctx.finished_game:
            return
        try:
            data = (await bizhawk.read(
                ctx.bizhawk_ctx,
                [(RAM_PROSPERITY_POINTS, 1, DOMAIN_MAIN_RAM)],
            ))[0]
        except bizhawk.RequestFailedError:
            return
        if data and data[0] >= 50:
            await ctx.send_msgs([{
                "cmd": "StatusUpdate",
                "status": ClientStatus.CLIENT_GOAL,
            }])
            ctx.finished_game = True
            self._goal_complete_sent = True


__all__ = [
    "DOMAIN_MAIN_RAM",
    "ITEMS_RECEIVED_COUNTER",
    "ITEM_DELIVERY_ROUTES",
    "LOCATION_RAM_BITS",
    "PROSPERITY_RAM_CAP",
    "DigimonWorldClient",
]
