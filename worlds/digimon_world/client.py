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
    DWAP_CHEST_RAM_BITS,
    RAM_CURRENT_BITS,
    RAM_ITEM_BANK_BASE,
    RAM_ITEM_BANK_SIZE,
    RAM_PROSPERITY_POINTS,
    RECRUIT_RAM_BITS,
)
from .items import ITEM_ID_BASE, ITEM_NAME_TO_ID
from .locations import PROSPERITY_THRESHOLDS

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
# Per-location detection tables
# =============================================================================
#
# Two dispatch styles, mirroring DWAP's runtime semantics:
#
# * :data:`LOCATION_RAM_BITS` — ``name → (byte_address, bit_index)``. The
#   location fires when ``ram[byte_address] & (1 << bit_index)`` is set.
#   Used for recruits and chests.
# * :data:`LOCATION_RAM_THRESHOLDS` — ``name → (byte_address, min_value)``.
#   The location fires when ``ram[byte_address] >= min_value``. Used for
#   the K-th prosperity NPC gift.
#
# **Validation status (2026-04-28):** six independent samples verified
# live against DWAP's ``Resources/{Locations,Chests,Prosperity}.json``:
# Agumon, Coelamon, Betamon recruit bits all match; Dragon Eye Lake
# chest and Tropical Jungle chest (DWAP "Chest 43") both match; the
# prosperity counter at ``RAM_PROSPERITY_POINTS`` ticks per DWAP's
# per-recruit ``prosperity_value`` (1, 2, 1 → byte 0→1→3→4). Six
# independent samples across three different DWAP source files all
# match → the data is authored correctly even though DWAP's runtime
# hook never installed. The remaining 44 recruit bits and 63 chest
# bits are extrapolated from the same source file, with the failure
# mode of "one specific location never auto-fires" rather than
# anything catastrophic.

LOCATION_RAM_BITS: dict[str, tuple[int, int]] = {
    **RECRUIT_RAM_BITS,
    **DWAP_CHEST_RAM_BITS,
}

LOCATION_RAM_THRESHOLDS: dict[str, tuple[int, int]] = {
    f"{k} Prosperity": (RAM_PROSPERITY_POINTS, k) for k in PROSPERITY_THRESHOLDS
}


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


def _make_soul_deliverer(soul_item_name: str) -> ItemDeliverer:
    """Return a no-op :class:`ItemDeliverer` for an ``X Soul`` item.

    Souls are **AP-logic-only**: they exist so :mod:`.rules` can gate
    progression on ``Has("Agumon Soul")`` etc. at fill time, but they
    must not write to game RAM. Specifically, they must not OR the
    corresponding bit in :data:`RECRUIT_RAM_BITS` — that bit is the
    same one :meth:`DigimonWorldClient._check_locations` polls to
    detect "the player recruited X". If the deliverer flipped that
    bit, AP would fire the recruit location for X immediately on
    soul delivery, returning whatever item AP placed there, which
    could itself cause more bits to flip — a feedback loop.

    The semantics we want:

    * AP-side, ``Has("Agumon Soul")`` is the logical key for reaching
      anything that depends on Agumon being recruitable.
    * In-game, the player still has to actually recruit Agumon. When
      they do, DW1 sets the recruit bit and our location-poll fires
      the AP check.

    Validating ``soul_item_name`` shape — every soul we ship has a
    recruit-bit entry — guards against typos in the items table.
    """

    digimon = soul_item_name.removesuffix(" Soul")
    if digimon not in RECRUIT_RAM_BITS:
        raise ValueError(f"No RAM bit for soul item {soul_item_name!r}")

    async def deliver(_ctx: BizHawkClientContext) -> list[RamWrite]:
        return []

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

    Routes by ``dw_code`` band:

    * 2000..2127 → bank deliverer
    * 3001 → 1000-bit money deliverer
    * 3002 → 5000-bit money deliverer
    * 4000..4049 → soul deliverer

    Items outside these ranges are intentionally skipped (no route
    registered); :meth:`DigimonWorldClient._deliver_items` logs a
    warning when AP sends one.
    """

    routes: dict[str, ItemDeliverer] = {}
    for name, ap_id in ITEM_NAME_TO_ID.items():
        dw_code = ap_id - ITEM_ID_BASE
        if 4000 <= dw_code <= 4049:
            routes[name] = _make_soul_deliverer(name)
        elif 2000 <= dw_code < 2000 + RAM_ITEM_BANK_SIZE:
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

        try:
            await self._check_locations(ctx)
            await self._deliver_items(ctx)
            await self._check_goal(ctx)
        except bizhawk.RequestFailedError:
            # Lua connector failed to respond; exit the handler and
            # let the BizHawk framework reconnect on the next tick.
            return

    async def _check_locations(self, ctx: BizHawkClientContext) -> None:
        """Poll per-location RAM signals and send LocationChecks for new ones.

        Two dispatch paths:

        * :data:`LOCATION_RAM_BITS` — bit-set checks (recruits, future
          chests). The dict stores ``(byte_address, bit_index)``; the
          location fires when ``ram[byte] & (1 << bit_index)`` is set.
        * :data:`LOCATION_RAM_THRESHOLDS` — value comparisons (the K
          prosperity NPC gifts). The dict stores
          ``(byte_address, min_value)``; the location fires when
          ``ram[byte] >= min_value``.

        Both tables read from MainRAM. Phase 4 v2.1 should batch these
        into a single windowed read; v2.0 keeps it simple with one
        request per location to make live validation easy to reason
        about (each request maps 1:1 to one location).
        """

        if not LOCATION_RAM_BITS and not LOCATION_RAM_THRESHOLDS:
            return

        assert self._location_name_to_id is not None
        new_checks: list[int] = []

        # Bit checks
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

        # Threshold checks
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
        deliverer = ITEM_DELIVERY_ROUTES.get(item_name)
        if deliverer is None:
            # Unknown item — increment the counter anyway so we don't
            # block on it forever, and log so RE work can add a route.
            logger.warning("No delivery route for item %r; skipping", item_name)
            await bizhawk.write(ctx.bizhawk_ctx, [(
                counter_address,
                list((applied + 1).to_bytes(counter_size, "little")),
                DOMAIN_MAIN_RAM,
            )])
            return

        write_list = await deliverer(ctx)
        write_list.append((
            counter_address,
            list((applied + 1).to_bytes(counter_size, "little")),
            DOMAIN_MAIN_RAM,
        ))
        await bizhawk.write(ctx.bizhawk_ctx, write_list)

    async def _check_goal(self, ctx: BizHawkClientContext) -> None:
        """Fire ``StatusUpdate(GoalComplete)`` once prosperity hits 100.

        Placeholder goal trigger pending Machinedramon-flag RE work.
        DW1's prosperity counter saturates at 100; the seed is
        logically completable at 50 PP under Phase 2 rules, so 100 PP
        is a strict *over*-condition.
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
        if data and data[0] >= 100:
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
    "DigimonWorldClient",
]
