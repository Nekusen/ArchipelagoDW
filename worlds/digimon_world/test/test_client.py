"""Tests for the Digimon World 1 BizHawk client (Phase 5 piece C).

What this client does:

* Polls every recruit AP location via the *beaten* trigger bit
  (Phase 5 piece C: the setTrigger wrapper redirects every
  ``setTrigger(200+digimon_id)`` into the unused 723..778 range, so
  the player can fight any Digimon without auto-joining the city).
* Polls every chest AP location via DWAP's chest-bit table (65).
* On items_received, dispatches each item to a deliverer:
  - inventory-first deliverers (bank fallback; fish ids bank-only) for
    the 2000-block items;
  - money deliverers for the 3001/3002 bits items;
  - prosperity deliverer for the ``Prosperity Point`` item
    (delivers ``PROSPERITY_PER_ITEM`` = 2 PP per item);
  - recruit deliverer for ``"<Digimon> Recruit"`` items (writes the
    recruit-completion bit ``200+digimon_id`` directly, bypassing
    the wrapper).
* Each tick, force-pins the in-game prosperity byte to ``PP-item count
  * PROSPERITY_PER_ITEM`` (saturating at :data:`PROSPERITY_RAM_CAP`).
* Each tick, force-sets Agumon's recruit bit (he's the bank NPC).
* Goal trigger fires once prosperity reaches 50 (max deliverable from
  25 ``Prosperity Point`` items @ 2 PP each).
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from unittest import mock

from .. import client as client_module
from ..client import (
    DOMAIN_MAIN_RAM,
    ITEM_DELIVERY_ROUTES,
    ITEMS_RECEIVED_COUNTER,
    LOCATION_RAM_BITS,
    PROSPERITY_RAM_CAP,
    DigimonWorldClient,
)
from ..data.addresses import (
    AUTO_PILOT_ITEM_ID,
    BEATEN_RAM_BITS,
    DWAP_CHEST_RAM_BITS,
    FISH_LOCATION_INVENTORY_IDS,
    RAM_INVENTORY_EMPTY_SLOT_ID,
    RAM_INVENTORY_ITEM_IDS_BASE,
    RAM_INVENTORY_MAX_SIZE,
    RAM_INVENTORY_QUANTITIES_BASE,
    RAM_INVENTORY_STACK_CAP,
    RAM_ITEM_BANK_BASE,
    RAM_PROSPERITY_POINTS,
    RECRUIT_RAM_BITS,
)
from ..items import (
    ITEM_NAME_TO_ID,
    KEYCHAIN_ITEM_NAME,
    PROSPERITY_PER_ITEM,
    PROSPERITY_POINT_NAME,
)
from ..locations import CHEST_NAMES, RECRUIT_NAMES
from .bases import DigimonWorldTestBase


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeItemNames:
    """Stand-in for ``ctx.item_names`` — maps AP item codes to names."""

    def __init__(self, mapping: dict[int, str] | None = None) -> None:
        self._mapping = dict(mapping or {})

    def lookup_in_game(self, code: int, game: str | None = None) -> str:
        return self._mapping.get(code, f"Unknown Item {code}")


class _RecvItem:
    """Minimal ``NetworkItem`` stand-in (only ``.item`` is read)."""

    def __init__(self, item: int) -> None:
        self.item = item


class _FakeClientCtx:
    """Stand-in for :class:`DigimonWorldClientContext`. Only the fields
    the client actually touches are present."""

    def __init__(self, *, server: Any = None, slot: int | None = 1,
                 finished_game: bool = False) -> None:
        # ``bizhawk_ctx`` is the legacy compat alias for ``ctx.emu``
        # (the active :class:`EmulatorAdapter`). Tests mock
        # ``client_module.bizhawk.read``/``write``, so this object is
        # opaque — never dereferenced.
        self.bizhawk_ctx = object()
        self.emu = self.bizhawk_ctx
        self.server = server if server is not None else object()
        self.slot = slot
        self.game: str = "Digimon World"
        self.items_handling = 0
        self.want_slot_data = False
        self.items_received: list[Any] = []
        self.item_names = _FakeItemNames()
        self.locations_checked: set[int] = set()
        self.finished_game = finished_game
        self.sent_msgs: list[Any] = []

    async def send_msgs(self, msgs: Any) -> None:
        self.sent_msgs.append(msgs)


# =============================================================================
# Class-level wiring
# =============================================================================


class TestClientRegistration(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_client_attributes(self) -> None:
        self.assertEqual(DigimonWorldClient.game, "Digimon World")
        self.assertEqual(DigimonWorldClient.system, "PSX")
        self.assertEqual(DigimonWorldClient.patch_suffix, ".apdw1")

    def test_apdw1_suffix_registered_with_bizhawk_component(self) -> None:
        """``.apdw1`` is claimed by our own BizHawk client component
        (registered in :mod:`worlds.digimon_world.launcher`), not by
        ``worlds._bizhawk``'s :class:`SuffixIdentifier`. Open Patch
        routes to the BizHawk client; the Duckstation client is a
        separate Launcher button with no suffix association."""

        from worlds.LauncherComponents import SuffixIdentifier
        from ..launcher import bizhawk_client_component, duckstation_client_component
        self.assertIsInstance(bizhawk_client_component.file_identifier, SuffixIdentifier)
        self.assertIn(".apdw1", bizhawk_client_component.file_identifier.suffixes)
        # Duckstation client must NOT claim .apdw1 — first-match-wins
        # in Launcher.open_patch means a duplicate claim would steal
        # the route from BizHawk depending on registration order.
        self.assertIsNone(duckstation_client_component.file_identifier)


# =============================================================================
# Detection tables
# =============================================================================


class TestRecruitDispatch(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_all_recruits_in_dispatch(self) -> None:
        for recruit_name in RECRUIT_NAMES:
            self.assertIn(recruit_name, LOCATION_RAM_BITS)

    def test_recruit_dispatch_uses_recruit_bits(self) -> None:
        """Plan A revised: AP location detection polls the vanilla
        recruit bits (200+X). Cutscene completion sets bit 200+X
        directly (no setTrigger redirect), so the AP location fires
        when the cutscene ends. AP delivery writes bit 720+X (handled
        by the recruit deliverer).

        Coelamon is the one exception (restored 2026-08-22): the
        client pins his vanilla bit 249 every tick, so his location
        polls the remapped shore-cutscene trigger 779 instead — see
        addresses.py ``COELAMON_RECRUIT_LOCATION_BIT``."""

        from ..data.addresses import COELAMON_RECRUIT_LOCATION_BIT
        for recruit_name in RECRUIT_NAMES:
            if recruit_name == "Coelamon":
                self.assertEqual(
                    LOCATION_RAM_BITS[recruit_name],
                    COELAMON_RECRUIT_LOCATION_BIT,
                )
                self.assertNotEqual(
                    LOCATION_RAM_BITS[recruit_name],
                    RECRUIT_RAM_BITS[recruit_name],
                )
                continue
            self.assertEqual(
                LOCATION_RAM_BITS[recruit_name],
                RECRUIT_RAM_BITS[recruit_name],
            )


class TestChestDispatch(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_all_chests_in_dispatch(self) -> None:
        for chest_name in CHEST_NAMES:
            self.assertIn(chest_name, LOCATION_RAM_BITS)

    def test_chest_dispatch_matches_manifest(self) -> None:
        for chest_name in CHEST_NAMES:
            self.assertEqual(
                LOCATION_RAM_BITS[chest_name],
                DWAP_CHEST_RAM_BITS[chest_name],
            )

    def test_no_recruit_chest_collision(self) -> None:
        # Arena cup locations intentionally share RAM bits: 4 AP
        # locations gate on each cup-tier trigger so a single cup win
        # fires 4 checks. The client polls per-location-name, so
        # collisions within ARENA_CUP_LOCATION_RAM_BITS are fine.
        seen: dict[tuple[int, int], str] = {}
        for name, key in LOCATION_RAM_BITS.items():
            if name.startswith("Arena Cup: "):
                continue
            if key in seen:
                self.fail(f"{name} collides with {seen[key]} at {key}")
            seen[key] = name

    def test_dispatch_size(self) -> None:
        # 50 recruits - 4 dropped (Airdramon, Seadramon, Nanimon,
        # Giromon) + 65 chests + 8 key items (Old Fishrod Pickup,
        # Mansion Key Pickup, Frig Key Pickup, Gear Pickup, Rain Plant
        # Pickup, Blue Flute Pickup, Leomonstone Pickup, Amazing Rod
        # Pickup) + 10 vending machines + 7 recycle shop slots +
        # 14 merit shop slots + 5 Nanimon Quest sites.
        # Per-seed availability of the option-gated entries (the 10
        # vending, the 7 recycle shop, the 14 merit shop) is filtered
        # on the AP server side; the dispatch dict is unconditional.
        # The 5 Nanimon Quest sites are always-on (not option-gated).
        # Airdramon, Seadramon, Nanimon, and Giromon stay in
        # RECRUIT_RAM_BITS but are filtered out of LOCATION_RAM_BITS via
        # ``_DROPPED_RECRUITS_BLACKLIST``.
        # Lava Cave Access / Tropical Jungle Bridge / Great Canyon
        # Bridge are AP items only — no associated AP location.
        # Steak is intentionally not AP-tracked: vanilla DW1 spawns it
        # from the Overdell fridge (gated on Frig Key) and is left on
        # the vanilla path.
        # Merit shop: 14 AP slots. Slots 135..143 live in the freed
        # ITEM_DESC_PTR region (contiguous with vanilla ITEM_PARA);
        # slots 144..148 live in the Cave6 ext segment via the
        # merit-scan teleport wrapper.
        # 43 recruits (50 vanilla - 7 dropped: Airdramon, Seadramon,
        # Nanimon, Giromon, Devimon, Megadramon, MetalGreymon; Coelamon
        # restored 2026-08-22 — polled at the remapped trigger 779, not
        # his vanilla recruit bit).
        # 63 chests (65 - 2 Lava Cave 5/6 dropped 2026-05-24).
        # 20 arena cup checks (5 grade tiers x 4 per tier).
        # 1 boss-defeat event (Meteormon).
        # 25 item shop + 12 secret shop rows (shopsanity, 2026-08-21).
        # 1 Piximon's Training Manual (opt-in, trigger 877, 2026-08-21).
        # 1 Gekomon arena dialog (opt-in with arena_locations, trigger 780, 2026-08-29).
        self.assertEqual(
            len(LOCATION_RAM_BITS),
            43 + 63 + 8 + 10 + 7 + 14 + 25 + 12 + 5 + 20 + 1 + 1 + 1,
        )


# =============================================================================
# Item delivery routes
# =============================================================================


class TestItemDeliveryRoutes(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_prosperity_route_present(self) -> None:
        self.assertIn(PROSPERITY_POINT_NAME, ITEM_DELIVERY_ROUTES)

    def test_all_consumables_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for name in ITEM_NAME_GROUPS["Consumables"]:
            self.assertIn(name, ITEM_DELIVERY_ROUTES)

    def test_all_dv_items_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for name in ITEM_NAME_GROUPS["DV Items"]:
            self.assertIn(name, ITEM_DELIVERY_ROUTES)

    def test_all_progression_keys_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for name in ITEM_NAME_GROUPS["Progression Keys"]:
            self.assertIn(name, ITEM_DELIVERY_ROUTES)

    def test_money_routes(self) -> None:
        self.assertIn("1000 Bits", ITEM_DELIVERY_ROUTES)
        self.assertIn("5000 Bits", ITEM_DELIVERY_ROUTES)

    def test_all_progressive_bundles_have_routes(self) -> None:
        """Every ``Progressive <Feature>`` recruit-bundle item must have
        a delivery route. Without it, ``_deliver_items`` logs
        ``"No delivery route for item X; skipping"`` on each tick the
        item is received. The route is a no-op (the BEATEN-bit work
        happens in ``_reconcile_recruits``) but its presence is what
        keeps the warning from firing."""

        from ..items import PROGRESSIVE_BUNDLES
        for prog_name in PROGRESSIVE_BUNDLES:
            self.assertIn(prog_name, ITEM_DELIVERY_ROUTES, prog_name)

    def test_all_region_access_items_have_routes(self) -> None:
        """``<Region> Region Access`` items own a ROM-read trigger bit
        since the region-gate feature (2026-08-21): delivery must OR the
        bit in (keyitem semantics) so the walk-on wrapper / script-gate
        stubs see the unlock, and the route's presence keeps the
        items_received counter advancing without ``"No delivery route"``
        warnings."""

        from ..regions import LOCKABLE_REGIONS, region_access_item_name
        for region in LOCKABLE_REGIONS:
            name = region_access_item_name(region)
            self.assertIn(name, ITEM_DELIVERY_ROUTES, name)

    def test_every_shipped_item_has_a_route(self) -> None:
        """Generic regression: every item the world ships in the pool
        (across all option permutations available at the test base) must
        have a delivery route. Catches any future item type that gets
        added to ``ITEM_NAME_TO_ID`` without a corresponding route in
        :func:`_build_item_delivery_routes`, which would silently spam
        warnings on each delivery."""

        from ..items import ITEM_NAME_TO_ID
        missing = [
            name for name in ITEM_NAME_TO_ID
            if name not in ITEM_DELIVERY_ROUTES
        ]
        self.assertEqual(missing, [], f"items without delivery routes: {missing}")


class TestProsperityDelivery(DigimonWorldTestBase):
    """Each Prosperity Point delivery bumps the prosperity byte by
    :data:`PROSPERITY_PER_ITEM` (saturating at PROSPERITY_RAM_CAP).
    Idempotent at the cap."""

    options: ClassVar[dict[str, Any]] = {}

    def test_unsaturated_delivery_writes_increment(self) -> None:
        deliverer = ITEM_DELIVERY_ROUTES[PROSPERITY_POINT_NAME]
        ctx = _FakeClientCtx()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([42])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(len(writes), 1)
        addr, byte_list, domain = writes[0]
        self.assertEqual(addr, RAM_PROSPERITY_POINTS)
        self.assertEqual(byte_list, [42 + PROSPERITY_PER_ITEM])
        self.assertEqual(domain, DOMAIN_MAIN_RAM)

    def test_saturated_delivery_is_noop(self) -> None:
        deliverer = ITEM_DELIVERY_ROUTES[PROSPERITY_POINT_NAME]
        ctx = _FakeClientCtx()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([PROSPERITY_RAM_CAP])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(writes, [])


# =============================================================================
# Inventory-first item delivery (2000-block)
# =============================================================================


def _pad_inventory(values: list[int], fill: int) -> bytes:
    """Extend a slot list to the structural 30-byte array."""

    assert len(values) <= RAM_INVENTORY_MAX_SIZE
    return bytes(values) + bytes(
        [fill] * (RAM_INVENTORY_MAX_SIZE - len(values)),
    )


class TestInventoryFirstDelivery(DigimonWorldTestBase):
    """2000-block deliveries go to the on-hand inventory when a slot is
    available (stack merge or first empty slot, mirroring vanilla
    ``giveItem``), falling back to the bank byte otherwise. Fish ids
    are bank-only so fishing detection can't false-fire."""

    options: ClassVar[dict[str, Any]] = {}

    # "Meat" = dw_code 2038 → in-game item id 38.
    ITEM_NAME = "Meat"
    ITEM_ID = 38
    BANK_ADDR = RAM_ITEM_BANK_BASE + ITEM_ID

    def _deliver(self, item_name: str, *, bank_qty: int = 0,
                 size: int = 10, ids: bytes, counts: bytes,
                 items_received: list[Any] | None = None,
                 item_names: _FakeItemNames | None = None) -> list[Any]:
        deliverer = ITEM_DELIVERY_ROUTES[item_name]
        ctx = _FakeClientCtx()
        if items_received is not None:
            ctx.items_received = items_received
        if item_names is not None:
            ctx.item_names = item_names

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([bank_qty]), bytes([size]), ids, counts]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            return _run(deliverer(ctx))

    def test_lands_in_first_empty_slot(self) -> None:
        ids = _pad_inventory([5], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1], 0)
        writes = self._deliver(self.ITEM_NAME, ids=ids, counts=counts)
        self.assertEqual(writes, [
            (RAM_INVENTORY_ITEM_IDS_BASE + 1, [self.ITEM_ID], DOMAIN_MAIN_RAM),
            (RAM_INVENTORY_QUANTITIES_BASE + 1, [1], DOMAIN_MAIN_RAM),
        ])

    def test_stacks_onto_existing_slot(self) -> None:
        ids = _pad_inventory([self.ITEM_ID], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([4], 0)
        writes = self._deliver(self.ITEM_NAME, ids=ids, counts=counts)
        self.assertEqual(writes, [
            (RAM_INVENTORY_QUANTITIES_BASE + 0, [5], DOMAIN_MAIN_RAM),
        ])

    def test_first_matching_slot_wins(self) -> None:
        # Duplicate stacks (poked/glitched state): mirror getItemCount —
        # only the first is touched.
        ids = _pad_inventory(
            [7, 7, self.ITEM_ID, 9, 9, self.ITEM_ID],
            RAM_INVENTORY_EMPTY_SLOT_ID,
        )
        counts = _pad_inventory([1, 1, 10, 1, 1, 20], 0)
        writes = self._deliver(self.ITEM_NAME, ids=ids, counts=counts)
        self.assertEqual(writes, [
            (RAM_INVENTORY_QUANTITIES_BASE + 2, [11], DOMAIN_MAIN_RAM),
        ])

    def test_full_stack_falls_back_to_bank(self) -> None:
        # Vanilla keeps one stack per id: a full stack refuses the give
        # even with empty slots free, so AP routes to the bank instead
        # of opening a second stack.
        ids = _pad_inventory([self.ITEM_ID], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([RAM_INVENTORY_STACK_CAP], 0)
        writes = self._deliver(
            self.ITEM_NAME, bank_qty=7, ids=ids, counts=counts,
        )
        self.assertEqual(writes, [(self.BANK_ADDR, [8], DOMAIN_MAIN_RAM)])

    def test_full_inventory_falls_back_to_bank(self) -> None:
        # 10 occupied slots at capacity 10; the empty slots at 10..29
        # are beyond the scan bound and must NOT be used.
        ids = _pad_inventory(list(range(1, 11)), RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1] * 10, 0)
        writes = self._deliver(
            self.ITEM_NAME, bank_qty=0, size=10, ids=ids, counts=counts,
        )
        self.assertEqual(writes, [(self.BANK_ADDR, [1], DOMAIN_MAIN_RAM)])

    def test_fish_ids_stay_bank_only(self) -> None:
        # Every fish delivery goes to the bank even with a fully empty
        # inventory — an inventory landing while the player stands on a
        # fishing screen would false-fire the fish AP location.
        ids = _pad_inventory([], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([], 0)
        for location_name, fish_id in FISH_LOCATION_INVENTORY_IDS:
            fish_item = location_name.removeprefix("Fishing: ")
            writes = self._deliver(fish_item, ids=ids, counts=counts)
            self.assertEqual(
                writes,
                [(RAM_ITEM_BANK_BASE + fish_id, [1], DOMAIN_MAIN_RAM)],
                fish_item,
            )

    def test_size_zero_treated_as_vanilla_default(self) -> None:
        # Uninitialized save: size byte 0 → scan the vanilla 10 slots.
        ids = _pad_inventory([], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([], 0)
        writes = self._deliver(self.ITEM_NAME, size=0, ids=ids, counts=counts)
        self.assertEqual(writes, [
            (RAM_INVENTORY_ITEM_IDS_BASE + 0, [self.ITEM_ID], DOMAIN_MAIN_RAM),
            (RAM_INVENTORY_QUANTITIES_BASE + 0, [1], DOMAIN_MAIN_RAM),
        ])

    def test_vanilla_size_flicker_clamped_to_keychain_target(self) -> None:
        # A vanilla ``setInventorySize 30`` flicker (Nanimon cutscene)
        # inflates the live size byte before the keychain reconciler
        # re-pins it. With zero keychains received the AP capacity is
        # 10, so the free slot at index 12 must NOT be used.
        ids = _pad_inventory(list(range(1, 11)), RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1] * 10, 0)
        writes = self._deliver(
            self.ITEM_NAME, size=30, ids=ids, counts=counts,
        )
        self.assertEqual(writes, [(self.BANK_ADDR, [1], DOMAIN_MAIN_RAM)])

    def test_keychain_expansion_widens_scan_bound(self) -> None:
        # One received Progressive Keychain → AP capacity 20: the free
        # slot at index 10 becomes usable.
        kc_code = ITEM_NAME_TO_ID[KEYCHAIN_ITEM_NAME]
        ids = _pad_inventory(list(range(1, 11)), RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1] * 10, 0)
        writes = self._deliver(
            self.ITEM_NAME, size=20, ids=ids, counts=counts,
            items_received=[_RecvItem(kc_code)],
            item_names=_FakeItemNames({kc_code: KEYCHAIN_ITEM_NAME}),
        )
        self.assertEqual(writes, [
            (RAM_INVENTORY_ITEM_IDS_BASE + 10, [self.ITEM_ID], DOMAIN_MAIN_RAM),
            (RAM_INVENTORY_QUANTITIES_BASE + 10, [1], DOMAIN_MAIN_RAM),
        ])

    def test_bank_cap_drops_delivery(self) -> None:
        # Bank fallback at the 99 cap: the delivery is quietly dropped
        # (historical bank-deliverer behavior preserved).
        ids = _pad_inventory([self.ITEM_ID], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([RAM_INVENTORY_STACK_CAP], 0)
        writes = self._deliver(
            self.ITEM_NAME, bank_qty=99, ids=ids, counts=counts,
        )
        self.assertEqual(writes, [])


# =============================================================================
# Infinite Auto Pilot reconciler
# =============================================================================


class TestAutoPilotReconciler(DigimonWorldTestBase):
    """``infinite_auto_pilot`` QoL: keep exactly one Auto Pilot (id 22)
    in the on-hand inventory — top up when absent and a slot is free,
    never stack extras, never displace an item."""

    options: ClassVar[dict[str, Any]] = {}

    def _reconcile(self, *, size: int = 10, ids: bytes,
                   counts: bytes) -> list[Any]:
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()
        seen: list[Any] = []

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([size]), ids, counts]

        async def fake_write(_bizhawk_ctx: Any, writes: list[Any]) -> None:
            seen.extend(writes)

        with mock.patch.object(client_module.bizhawk, "read", fake_read), \
                mock.patch.object(client_module.bizhawk, "write", fake_write):
            _run(client._reconcile_auto_pilot(ctx))
        return seen

    def test_tops_up_when_absent(self) -> None:
        ids = _pad_inventory([5, 7], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1, 1], 0)
        writes = self._reconcile(ids=ids, counts=counts)
        self.assertEqual(writes, [
            (RAM_INVENTORY_ITEM_IDS_BASE + 2, [AUTO_PILOT_ITEM_ID],
             DOMAIN_MAIN_RAM),
            (RAM_INVENTORY_QUANTITIES_BASE + 2, [1], DOMAIN_MAIN_RAM),
        ])

    def test_present_copy_is_left_alone(self) -> None:
        # One copy present (any positive count) → no writes, even with
        # free slots available: never stack extras.
        ids = _pad_inventory([AUTO_PILOT_ITEM_ID], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1], 0)
        self.assertEqual(self._reconcile(ids=ids, counts=counts), [])

    def test_zero_count_copy_topped_in_place(self) -> None:
        # Defensive: a held id-22 slot with count 0 is topped back to 1
        # in place (covers either consumption semantic without ever
        # creating a second copy).
        ids = _pad_inventory([AUTO_PILOT_ITEM_ID], RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([0], 0)
        writes = self._reconcile(ids=ids, counts=counts)
        self.assertEqual(writes, [
            (RAM_INVENTORY_QUANTITIES_BASE + 0, [1], DOMAIN_MAIN_RAM),
        ])

    def test_full_inventory_waits_for_free_slot(self) -> None:
        ids = _pad_inventory(list(range(1, 11)), RAM_INVENTORY_EMPTY_SLOT_ID)
        counts = _pad_inventory([1] * 10, 0)
        self.assertEqual(self._reconcile(ids=ids, counts=counts), [])

    def test_watcher_flag_defaults_off(self) -> None:
        # Until slot_data arrives (or with the option off) the watcher
        # must not run the reconciler: the flag is None/False-y.
        client = DigimonWorldClient()
        self.assertFalse(client._infinite_auto_pilot)


# =============================================================================
# items_received counter
# =============================================================================


class TestItemsReceivedCounter(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_counter_set(self) -> None:
        self.assertIsNotNone(ITEMS_RECEIVED_COUNTER)

    def test_counter_address_is_in_main_ram(self) -> None:
        assert ITEMS_RECEIVED_COUNTER is not None
        addr, size = ITEMS_RECEIVED_COUNTER
        self.assertLess(addr, 0x200000)
        self.assertGreaterEqual(size, 1)
        self.assertLessEqual(size, 4)

    def test_counter_does_not_collide_with_location_bits(self) -> None:
        assert ITEMS_RECEIVED_COUNTER is not None
        counter_addr, counter_size = ITEMS_RECEIVED_COUNTER
        counter_range = range(counter_addr, counter_addr + counter_size)
        location_addrs: set[int] = {
            addr for addr, _bit in LOCATION_RAM_BITS.values()
        }
        for byte_addr in counter_range:
            self.assertNotIn(byte_addr, location_addrs)

    def test_counter_outside_bank_ui_range(self) -> None:
        # The bank UI iterates all 128 bank slots and renders any
        # non-zero quantity as ``<item-name>: N`` — including for slots
        # where the player has never legitimately deposited anything.
        # If the counter lived in this range, the magic byte (0xA5 =
        # 165) would surface in-game as 165 of whatever item the slot
        # corresponds to. (Regression guard for the 2026-05-09 Noble
        # Mane / Giga Hand bug.)
        from ..data.addresses import RAM_ITEM_BANK_BASE, RAM_ITEM_BANK_SIZE
        assert ITEMS_RECEIVED_COUNTER is not None
        counter_addr, counter_size = ITEMS_RECEIVED_COUNTER
        bank_end = RAM_ITEM_BANK_BASE + RAM_ITEM_BANK_SIZE
        for byte_addr in range(counter_addr, counter_addr + counter_size):
            self.assertFalse(
                RAM_ITEM_BANK_BASE <= byte_addr < bank_end,
                f"counter byte 0x{byte_addr:08X} lands in the bank UI "
                f"display range 0x{RAM_ITEM_BANK_BASE:08X}.."
                f"0x{bank_end - 1:08X} — the bank UI will surface the "
                f"magic byte as a phantom item in slot "
                f"{byte_addr - RAM_ITEM_BANK_BASE}",
            )

    def test_counter_outside_card_nibble_array(self) -> None:
        # The card-vending logic packs 66 ownership counters as nibbles
        # in 0x001BDFAC..0x001BDFCC (33 bytes). A counter byte landing
        # here would corrupt two card counters at once.
        from ..data.addresses import CARD_BLOCK_BASE, CARD_BLOCK_SIZE
        assert ITEMS_RECEIVED_COUNTER is not None
        counter_addr, counter_size = ITEMS_RECEIVED_COUNTER
        card_end = CARD_BLOCK_BASE + CARD_BLOCK_SIZE
        for byte_addr in range(counter_addr, counter_addr + counter_size):
            self.assertFalse(
                CARD_BLOCK_BASE <= byte_addr < card_end,
                f"counter byte 0x{byte_addr:08X} lands in the card "
                f"nibble array 0x{CARD_BLOCK_BASE:08X}.."
                f"0x{card_end - 1:08X}",
            )

    def test_counter_outside_trigger_array(self) -> None:
        # The trigger bit-array is the most-written region in DW1: every
        # ``setTrigger N`` opcode (1300+ in the script bytecode, plus
        # engine-level callers) ORs a bit into ``base + N // 8``. The
        # original counter at 0x001BDFEE was clobbered by trigger 274
        # mid-playthrough — see memory note ``dw1_counter_safe_address``.
        from ..data.addresses import AP_TRIGGER_ARRAY_BASE
        assert ITEMS_RECEIVED_COUNTER is not None
        counter_addr, counter_size = ITEMS_RECEIVED_COUNTER
        trigger_end = 0x001BE041  # one past the documented trigger array tail
        for byte_addr in range(counter_addr, counter_addr + counter_size):
            self.assertFalse(
                AP_TRIGGER_ARRAY_BASE <= byte_addr < trigger_end,
                f"counter byte 0x{byte_addr:08X} lands in the trigger "
                f"bit-array 0x{AP_TRIGGER_ARRAY_BASE:08X}.."
                f"0x{trigger_end - 1:08X}",
            )


# =============================================================================
# validate_rom
# =============================================================================


class TestValidateRom(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def _validate_with_response(self, response: bytes | None) -> bool:
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [response if response is not None else b""]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            return _run(client.validate_rom(ctx))

    def test_accepts_typical_save(self) -> None:
        self.assertTrue(self._validate_with_response(bytes([42])))

    def test_accepts_fresh_save(self) -> None:
        self.assertTrue(self._validate_with_response(bytes([0])))

    def test_accepts_max_prosperity(self) -> None:
        self.assertTrue(self._validate_with_response(bytes([100])))

    def test_rejects_out_of_range(self) -> None:
        self.assertFalse(self._validate_with_response(bytes([200])))

    def test_rejects_empty_response(self) -> None:
        self.assertFalse(self._validate_with_response(b""))

    def test_rejects_request_failure(self) -> None:
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()

        async def failing_read(*_args: Any, **_kwargs: Any) -> Any:
            raise client_module.bizhawk.RequestFailedError("simulated")

        with mock.patch.object(client_module.bizhawk, "read", failing_read):
            self.assertFalse(_run(client.validate_rom(ctx)))


# =============================================================================
# Goal detection
# =============================================================================


class TestGoalDetection(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def _run_check_goal(self, prosperity_value: int,
                        already_finished: bool = False,
                        already_sent: bool = False,
                        goal: int = 1,
                        prosperity_goal: int = 50) -> _FakeClientCtx:
        # ``goal`` defaults to 1 (prosperity) so the legacy tests that
        # were written before the goal option was honored continue to
        # exercise the auto-fire path. Callers that want the
        # machinedramon path pass ``goal=0``. ``prosperity_goal`` mirrors
        # the slot_data ``prosperity_goal`` threshold; default 50
        # matches the option's vanilla default.
        client = DigimonWorldClient()
        client._goal_complete_sent = already_sent
        client._goal = goal
        client._prosperity_goal = prosperity_goal
        ctx = _FakeClientCtx(finished_game=already_finished)

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([prosperity_value])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            _run(client._check_goal(ctx))
        return ctx

    def test_below_threshold_no_msg(self) -> None:
        # Phase 5 piece C: threshold dropped from 100 to 50 (max
        # deliverable from 25 PP items @ 2 PP each).
        ctx = self._run_check_goal(49)
        self.assertEqual(ctx.sent_msgs, [])
        self.assertFalse(ctx.finished_game)

    def test_at_threshold_fires_once(self) -> None:
        ctx = self._run_check_goal(50)
        self.assertEqual(len(ctx.sent_msgs), 1)
        msg = ctx.sent_msgs[0][0]
        self.assertEqual(msg["cmd"], "StatusUpdate")
        from NetUtils import ClientStatus
        self.assertEqual(msg["status"], ClientStatus.CLIENT_GOAL)
        self.assertTrue(ctx.finished_game)

    def test_idempotent_when_already_finished(self) -> None:
        ctx = self._run_check_goal(100, already_finished=True)
        self.assertEqual(ctx.sent_msgs, [])

    def test_idempotent_when_already_sent(self) -> None:
        ctx = self._run_check_goal(100, already_sent=True)
        self.assertEqual(ctx.sent_msgs, [])

    def test_prosperity_goal_uses_configured_threshold(self) -> None:
        """Phase 9: ``goal: prosperity`` fires at the configured
        ``prosperity_goal`` (slot_data), not the legacy hardcoded 50.
        """

        # threshold=80, byte=70 → no fire.
        ctx = self._run_check_goal(70, prosperity_goal=80)
        self.assertEqual(ctx.sent_msgs, [])
        # threshold=80, byte=80 → fires.
        ctx = self._run_check_goal(80, prosperity_goal=80)
        self.assertEqual(len(ctx.sent_msgs), 1)
        # threshold=30, byte=30 → fires (would have stayed below the
        # legacy 50 cutoff).
        ctx = self._run_check_goal(30, prosperity_goal=30)
        self.assertEqual(len(ctx.sent_msgs), 1)

    def test_unset_prosperity_goal_does_not_fire(self) -> None:
        """If slot_data hasn't arrived yet (``_prosperity_goal`` is
        None) the goal check is a no-op — avoids a spurious release on
        a stale prosperity read."""

        client = DigimonWorldClient()
        client._goal = 1  # prosperity
        client._prosperity_goal = None  # not yet from slot_data
        ctx = _FakeClientCtx()

        async def fake_read(_b: Any, _r: list[Any]) -> list[bytes]:
            return [bytes([100])]  # well above any threshold

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            _run(client._check_goal(ctx))
        self.assertEqual(ctx.sent_msgs, [])

    def test_machinedramon_goal_does_not_fire_when_bit_unset(self) -> None:
        # With goal=machinedramon, _check_goal reads
        # RAM_MACHINEDRAMON_DEFEATED_BYTE and tests bit 2 (mask 0x04).
        # A returned byte of 50 (0x32) has bit 2 unset -> no fire.
        # Also covers the historical bug (2026-05-01) where reaching
        # prosperity 50 used to fire GoalComplete on the machinedramon
        # goal: byte 50 has bit 2 unset, so even if some path
        # accidentally fed prosperity into this read, the bit-test
        # would still gate correctly.
        ctx = self._run_check_goal(50, goal=0)
        self.assertEqual(ctx.sent_msgs, [])
        self.assertFalse(ctx.finished_game)

    def test_machinedramon_goal_fires_when_bit_set(self) -> None:
        # Byte value with bit 2 set (mask 0x04) -> goal fires.
        ctx = self._run_check_goal(0x04, goal=0)
        self.assertEqual(len(ctx.sent_msgs), 1)
        msg = ctx.sent_msgs[0][0]
        self.assertEqual(msg["cmd"], "StatusUpdate")
        from NetUtils import ClientStatus
        self.assertEqual(msg["status"], ClientStatus.CLIENT_GOAL)
        self.assertTrue(ctx.finished_game)

    def test_machinedramon_goal_fires_when_bit_set_among_others(self) -> None:
        # Bit 2 plus other bits set (e.g. recruit bits 3..7 are
        # adjacent in the same byte). Goal still fires — the test
        # masks for bit 2 only.
        ctx = self._run_check_goal(0xFC, goal=0)  # bits 2..7 set
        self.assertEqual(len(ctx.sent_msgs), 1)
        self.assertTrue(ctx.finished_game)

    def test_machinedramon_goal_no_fire_for_unrelated_recruit_bits(self) -> None:
        # Adjacent recruit bits 3..7 set, but bit 2 unset (mask 0xFB).
        # Must NOT fire — recruit-completion writes (e.g. Agumon at
        # bit 3 of the same byte) shouldn't trigger goal completion.
        ctx = self._run_check_goal(0xF8, goal=0)  # bits 3..7 set, bit 2 clear
        self.assertEqual(ctx.sent_msgs, [])
        self.assertFalse(ctx.finished_game)

    def test_unset_goal_does_not_auto_fire(self) -> None:
        # If slot_data hasn't arrived yet (_goal is None), do nothing —
        # avoids a spurious release on a stale read before the goal
        # is known.
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([50])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            _run(client._check_goal(ctx))
        self.assertEqual(ctx.sent_msgs, [])
        self.assertFalse(ctx.finished_game)


# =============================================================================
# Item delivery (no pending items = no writes)
# =============================================================================


class TestDeliverItemsNoopOnNoPending(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_no_pending_means_no_write(self) -> None:
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()
        ctx.items_received = []

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [b"\x00\x00"]

        with mock.patch.object(client_module.bizhawk, "read", fake_read), \
             mock.patch.object(client_module.bizhawk, "write") as mocked_write:
            _run(client._deliver_items(ctx))
            mocked_write.assert_not_called()


# =============================================================================
# Manifest shape sanity
# =============================================================================


class TestManifestRecruitTableShape(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_all_recruit_names_have_recruit_bits(self) -> None:
        # RECRUIT_NAMES (41) is a subset of RECRUIT_RAM_BITS (50 —
        # vanilla recruit bit-block). Excluded from RECRUIT_NAMES:
        # Agumon (force-recruited bank NPC), Digitamamon (post-game
        # optional), Airdramon (dropped 2026-05-08), Seadramon
        # (dropped 2026-05-09 — recruit cutscene IS Blue Flute
        # pickup), Nanimon (dropped 2026-05-09 — never joins city),
        # Giromon (dropped 2026-05-09 — Jukebox crashes NTSC build),
        # Devimon / Megadramon / MetalGreymon (dropped 2026-05-27 —
        # all three Mt. Infinity recruit bits get set post-Machinedramon,
        # after the goal would already have fired). Coelamon was dropped
        # 2026-05-24 and RESTORED 2026-08-22 (shore cutscene remapped to
        # its own AP trigger — see addresses.py
        # ``ROM_COELAMON_CUTSCENE_REMAP_*``). See addresses.py
        # ``_AP_RECRUIT_EXCLUDED``.
        for recruit_name in RECRUIT_NAMES:
            self.assertIn(recruit_name, RECRUIT_RAM_BITS)
        self.assertEqual(len(RECRUIT_RAM_BITS), 50)
        self.assertEqual(len(RECRUIT_NAMES), 41)
        for excluded in ("Agumon", "Digitamamon", "Airdramon",
                         "Seadramon", "Nanimon", "Giromon",
                         "Devimon", "Megadramon", "MetalGreymon"):
            self.assertNotIn(excluded, RECRUIT_NAMES)
        self.assertIn("Greymon", RECRUIT_NAMES)
        self.assertIn("Coelamon", RECRUIT_NAMES)
        self.assertIn("Agumon", RECRUIT_RAM_BITS)
        self.assertIn("Digitamamon", RECRUIT_RAM_BITS)

    def test_bit_indices_in_byte_range(self) -> None:
        for (_offset, bit_index) in RECRUIT_RAM_BITS.values():
            self.assertIn(bit_index, range(8))

    def test_addresses_in_main_ram(self) -> None:
        for (offset, _bit) in RECRUIT_RAM_BITS.values():
            self.assertLess(offset, 0x200000)

    def test_no_address_bit_collisions(self) -> None:
        seen: dict[tuple[int, int], str] = {}
        for recruit_name, key in RECRUIT_RAM_BITS.items():
            if key in seen:
                self.fail(f"{recruit_name} collides with {seen[key]} at {key}")
            seen[key] = recruit_name


class TestManifestChestTableShape(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_chest_count(self) -> None:
        # 63 = 65 - 2 (Lava Cave 5/6 dropped 2026-05-24 — chests
        # don't exist in any reachable area).
        self.assertEqual(len(DWAP_CHEST_RAM_BITS), 63)

    def test_chest_addresses_in_main_ram(self) -> None:
        for (offset, _bit) in DWAP_CHEST_RAM_BITS.values():
            self.assertLess(offset, 0x200000)

    def test_chest_bits_in_byte_range(self) -> None:
        for (_offset, bit) in DWAP_CHEST_RAM_BITS.values():
            self.assertIn(bit, range(8))

    def test_no_chest_collisions(self) -> None:
        seen: dict[tuple[int, int], str] = {}
        for chest_name, key in DWAP_CHEST_RAM_BITS.items():
            if key in seen:
                self.fail(f"{chest_name} collides with {seen[key]} at {key}")
            seen[key] = chest_name


# =============================================================================
# Self-doc invariants
# =============================================================================


class TestManifestConstants(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_main_ram_domain_string(self) -> None:
        self.assertEqual(DOMAIN_MAIN_RAM, "MainRAM")

    def test_prosperity_address_in_main_ram(self) -> None:
        self.assertLess(RAM_PROSPERITY_POINTS, 0x200000)
