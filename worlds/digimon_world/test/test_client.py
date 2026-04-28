"""Phase 4 v1 tests for the Digimon World 1 BizHawk client.

These tests cover what we *can* check without a live BizHawk + ROM:

* the client class registers correctly with
  :class:`worlds._bizhawk.client.AutoBizHawkClientRegister`,
* its ``patch_suffix`` is appended to the BizHawk Client component's
  :class:`worlds.LauncherComponents.SuffixIdentifier`,
* the v1 RE-pending tables are intentionally empty (a regression on
  this would mask Phase 4 v2 RE deliverables landing late),
* ``validate_rom`` accepts/rejects against simulated MainRAM reads,
* ``_check_goal`` fires ``StatusUpdate`` exactly once when prosperity
  saturates.

The actual Lua-mediated runtime is mocked via ``unittest.mock``; we
substitute :func:`worlds._bizhawk.read` and
:meth:`worlds._bizhawk.context.BizHawkClientContext.send_msgs` /
:meth:`check_locations` with awaitable stubs.
"""

from __future__ import annotations

import asyncio
from typing import Any, ClassVar
from unittest import mock

from worlds._bizhawk.client import AutoBizHawkClientRegister

from .. import client as client_module
from ..client import (
    DOMAIN_MAIN_RAM,
    ITEM_DELIVERY_ROUTES,
    ITEMS_RECEIVED_COUNTER,
    LOCATION_RAM_BITS,
    LOCATION_RAM_THRESHOLDS,
    DigimonWorldClient,
)
from ..data.addresses import (
    DWAP_CHEST_RAM_BITS,
    RAM_PROSPERITY_POINTS,
    RECRUIT_RAM_BITS,
)
from ..locations import CHEST_NAMES, PROSPERITY_THRESHOLDS, RECRUIT_NAMES
from .bases import DigimonWorldTestBase


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeBizHawkCtx:
    """Stand-in for the inner ``ctx.bizhawk_ctx`` argument."""

    def __init__(self, read_responses: list[bytes]) -> None:
        self._read_responses = list(read_responses)
        self.read_calls: list[Any] = []

    def pop_response(self) -> bytes:
        return self._read_responses.pop(0)


class _FakeClientCtx:
    """Stand-in for :class:`BizHawkClientContext`. Only the fields the
    client actually touches are present."""

    def __init__(self, *, server: Any = None, slot: int | None = 1,
                 finished_game: bool = False) -> None:
        self.bizhawk_ctx = _FakeBizHawkCtx([])
        # Treat None as "connected" sentinel so callers don't have to
        # pass anything; the client only checks `is None`.
        self.server = server if server is not None else object()
        self.slot = slot
        self.game: str = ""
        self.items_handling = 0
        self.want_slot_data = False
        self.items_received: list[Any] = []
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

    def test_client_registers_with_metaclass(self) -> None:
        psx_handlers = AutoBizHawkClientRegister.game_handlers.get(("PSX",), {})
        self.assertIn("Digimon World", psx_handlers,
                      "DigimonWorldClient is not registered for PSX")
        self.assertIsInstance(psx_handlers["Digimon World"], DigimonWorldClient)

    def test_apdw1_suffix_is_in_bizhawk_component(self) -> None:
        from worlds._bizhawk.client import component as bizhawk_component
        self.assertIn(".apdw1", bizhawk_component.file_identifier.suffixes,
                      "DigimonWorldClient's patch_suffix did not propagate "
                      "to the BizHawk Client SuffixIdentifier")


# =============================================================================
# Detection tables — populated from DWAP, 6 samples live-verified 2026-04-28
# =============================================================================


class TestRecruitDispatchPopulated(DigimonWorldTestBase):
    """LOCATION_RAM_BITS contains all 50 recruits at the DWAP addresses."""

    options: ClassVar[dict[str, Any]] = {}

    def test_all_recruits_in_dispatch(self) -> None:
        for recruit_name in RECRUIT_NAMES:
            self.assertIn(recruit_name, LOCATION_RAM_BITS,
                          f"{recruit_name} missing from LOCATION_RAM_BITS")

    def test_recruit_dispatch_matches_manifest(self) -> None:
        for recruit_name in RECRUIT_NAMES:
            self.assertEqual(
                LOCATION_RAM_BITS[recruit_name],
                RECRUIT_RAM_BITS[recruit_name],
                f"{recruit_name} client bit ≠ manifest bit",
            )


class TestChestDispatchPopulated(DigimonWorldTestBase):
    """LOCATION_RAM_BITS contains all 65 DWAP-named chests."""

    options: ClassVar[dict[str, Any]] = {}

    def test_all_chests_in_dispatch(self) -> None:
        for chest_name in CHEST_NAMES:
            self.assertIn(chest_name, LOCATION_RAM_BITS,
                          f"{chest_name} missing from LOCATION_RAM_BITS")

    def test_chest_dispatch_matches_manifest(self) -> None:
        for chest_name in CHEST_NAMES:
            self.assertEqual(
                LOCATION_RAM_BITS[chest_name],
                DWAP_CHEST_RAM_BITS[chest_name],
                f"{chest_name} client bit ≠ manifest bit",
            )

    def test_no_recruit_chest_collision(self) -> None:
        """A recruit and a chest should never share the same (addr, bit)."""

        seen: dict[tuple[int, int], str] = {}
        for name, key in LOCATION_RAM_BITS.items():
            if key in seen:
                self.fail(f"{name} collides with {seen[key]} at {key}")
            seen[key] = name


class TestProsperityThresholdDispatch(DigimonWorldTestBase):
    """LOCATION_RAM_THRESHOLDS covers every Phase 2 prosperity threshold."""

    options: ClassVar[dict[str, Any]] = {}

    def test_all_thresholds_present(self) -> None:
        for k in PROSPERITY_THRESHOLDS:
            self.assertIn(f"{k} Prosperity", LOCATION_RAM_THRESHOLDS)
        self.assertEqual(len(LOCATION_RAM_THRESHOLDS), len(PROSPERITY_THRESHOLDS))

    def test_thresholds_use_prosperity_byte(self) -> None:
        for offset, _value in LOCATION_RAM_THRESHOLDS.values():
            self.assertEqual(offset, RAM_PROSPERITY_POINTS)

    def test_threshold_values_match_name(self) -> None:
        for k in PROSPERITY_THRESHOLDS:
            _addr, value = LOCATION_RAM_THRESHOLDS[f"{k} Prosperity"]
            self.assertEqual(value, k)


class TestItemDeliveryRoutesPopulated(DigimonWorldTestBase):
    """Phase 4 v3 — every poolable item has a delivery route, except
    items the framework intentionally skips (e.g. Victory event)."""

    options: ClassVar[dict[str, Any]] = {}

    def test_all_souls_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for soul_name in ITEM_NAME_GROUPS["Recruit Souls"]:
            self.assertIn(soul_name, ITEM_DELIVERY_ROUTES,
                          f"{soul_name} missing from ITEM_DELIVERY_ROUTES")

    def test_all_consumables_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for name in ITEM_NAME_GROUPS["Consumables"]:
            self.assertIn(name, ITEM_DELIVERY_ROUTES,
                          f"{name} missing from ITEM_DELIVERY_ROUTES")

    def test_all_dv_items_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for name in ITEM_NAME_GROUPS["DV Items"]:
            self.assertIn(name, ITEM_DELIVERY_ROUTES,
                          f"{name} missing from ITEM_DELIVERY_ROUTES")

    def test_all_progression_keys_have_routes(self) -> None:
        from ..items import ITEM_NAME_GROUPS
        for name in ITEM_NAME_GROUPS["Progression Keys"]:
            self.assertIn(name, ITEM_DELIVERY_ROUTES,
                          f"{name} missing from ITEM_DELIVERY_ROUTES")

    def test_money_routes(self) -> None:
        self.assertIn("1000 Bits", ITEM_DELIVERY_ROUTES)
        self.assertIn("5000 Bits", ITEM_DELIVERY_ROUTES)


class TestNoDeliveryDetectionOverlap(DigimonWorldTestBase):
    """Delivery write-addresses must NOT overlap any detection
    read-address. Overlap creates a feedback loop where AP delivering
    item X causes location X to fire and return another item.

    The original soul-deliverer bug fell into this trap; this test
    guards against future regressions in any category.
    """

    options: ClassVar[dict[str, Any]] = {}

    def test_bank_does_not_overlap_detection(self) -> None:
        from ..data.addresses import RAM_ITEM_BANK_BASE, RAM_ITEM_BANK_SIZE
        bank_range = set(range(
            RAM_ITEM_BANK_BASE,
            RAM_ITEM_BANK_BASE + RAM_ITEM_BANK_SIZE,
        ))
        detection = self._all_detection_addresses()
        self.assertFalse(
            bank_range & detection,
            f"Bank delivery range overlaps detection: "
            f"{sorted(bank_range & detection)}",
        )

    def test_money_does_not_overlap_detection(self) -> None:
        from ..data.addresses import RAM_CURRENT_BITS
        money_range = set(range(RAM_CURRENT_BITS, RAM_CURRENT_BITS + 4))
        detection = self._all_detection_addresses()
        self.assertFalse(
            money_range & detection,
            f"Money delivery range overlaps detection: "
            f"{sorted(money_range & detection)}",
        )

    @staticmethod
    def _all_detection_addresses() -> set[int]:
        addresses: set[int] = set()
        for addr, _bit in LOCATION_RAM_BITS.values():
            addresses.add(addr)
        for addr, _value in LOCATION_RAM_THRESHOLDS.values():
            addresses.add(addr)
        return addresses


class TestSoulDeliveryIsNoOp(DigimonWorldTestBase):
    """Soul deliveries must not write any RAM.

    Regression guard for the feedback loop bug: if the soul deliverer
    OR'd the recruit bit, it would auto-fire the recruit location for
    that Digimon, returning whatever AP placed there — a chain.
    """

    options: ClassVar[dict[str, Any]] = {}

    def test_every_soul_route_returns_empty_writes(self) -> None:
        from ..items import ITEM_NAME_GROUPS

        ctx = _FakeClientCtx()

        async def fake_read(*_args: Any, **_kwargs: Any) -> Any:
            self.fail("Soul deliverer must not call bizhawk.read")

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            for soul_name in ITEM_NAME_GROUPS["Recruit Souls"]:
                deliverer = ITEM_DELIVERY_ROUTES[soul_name]
                writes = _run(deliverer(ctx))
                self.assertEqual(
                    writes, [],
                    f"{soul_name} deliverer returned writes {writes!r}; "
                    f"souls must be no-op deliveries to avoid the "
                    f"recruit-bit feedback loop.",
                )


class TestItemsReceivedCounterActivated(DigimonWorldTestBase):
    """The counter scratch byte is set, item delivery is active.

    Verified 2026-04-28: 0x001BDFEE/0x001BDFEF stayed at 0 across 40
    snapshot markers covering walking, fighting, menus, item use,
    stat training, save-to-memory-card, and bank deposits/withdrawals.
    """

    options: ClassVar[dict[str, Any]] = {}

    def test_items_received_counter_set(self) -> None:
        self.assertIsNotNone(ITEMS_RECEIVED_COUNTER)

    def test_counter_address_is_in_main_ram(self) -> None:
        assert ITEMS_RECEIVED_COUNTER is not None
        addr, size = ITEMS_RECEIVED_COUNTER
        self.assertLess(addr, 0x200000, f"counter at 0x{addr:X} > 2 MiB")
        self.assertGreaterEqual(size, 1)
        self.assertLessEqual(size, 4, "u32 max — anything wider is excessive")

    def test_counter_outside_known_used_regions(self) -> None:
        """The chosen counter address must not collide with any address
        the dispatch tables already use, or it would overwrite live game
        data on every delivery."""

        assert ITEMS_RECEIVED_COUNTER is not None
        counter_addr, counter_size = ITEMS_RECEIVED_COUNTER
        counter_range = range(counter_addr, counter_addr + counter_size)

        used_addrs: set[int] = set()
        for addr, _bit in LOCATION_RAM_BITS.values():
            used_addrs.add(addr)
        for addr, _value in LOCATION_RAM_THRESHOLDS.values():
            used_addrs.add(addr)
        # Bank slots: 128 bytes starting at RAM_ITEM_BANK_BASE.
        from ..data.addresses import RAM_ITEM_BANK_BASE, RAM_ITEM_BANK_SIZE
        used_addrs.update(range(
            RAM_ITEM_BANK_BASE,
            RAM_ITEM_BANK_BASE + RAM_ITEM_BANK_SIZE,
        ))
        for byte_addr in counter_range:
            self.assertNotIn(
                byte_addr, used_addrs,
                f"counter byte 0x{byte_addr:X} collides with a "
                f"location/bank address",
            )


class TestManifestRecruitTableShape(DigimonWorldTestBase):
    """The DWAP-ingested manifest table is preserved for reference. These
    tests check its *shape* (50 entries, bit indices 0..7, no collisions)
    so we'd notice if it got corrupted, but they say nothing about
    correctness — those addresses are unverified."""

    options: ClassVar[dict[str, Any]] = {}

    def test_all_50_recruits_present(self) -> None:
        for recruit_name in RECRUIT_NAMES:
            self.assertIn(recruit_name, RECRUIT_RAM_BITS)
        self.assertEqual(len(RECRUIT_RAM_BITS), len(RECRUIT_NAMES))

    def test_bit_indices_in_byte_range(self) -> None:
        for recruit_name, (_offset, bit_index) in RECRUIT_RAM_BITS.items():
            self.assertIn(bit_index, range(8),
                          f"{recruit_name} bit_index {bit_index} not in 0..7")

    def test_addresses_in_main_ram(self) -> None:
        for recruit_name, (offset, _bit) in RECRUIT_RAM_BITS.items():
            self.assertLess(offset, 0x200000,
                            f"{recruit_name} offset 0x{offset:X} > 2 MiB")

    def test_no_address_bit_collisions(self) -> None:
        seen: dict[tuple[int, int], str] = {}
        for recruit_name, key in RECRUIT_RAM_BITS.items():
            if key in seen:
                self.fail(f"{recruit_name} collides with {seen[key]} at {key}")
            seen[key] = recruit_name


class TestManifestChestTableShape(DigimonWorldTestBase):
    """Likewise for the DWAP chest table — shape only, not correctness."""

    options: ClassVar[dict[str, Any]] = {}

    def test_chest_count(self) -> None:
        # DWAP ships 65 chest entries; the standalone randomizer's
        # ROM_CHEST_ITEM_OFFSETS lists 73 placement offsets. The
        # 8-entry gap is reconciliation work for after live validation.
        self.assertEqual(len(DWAP_CHEST_RAM_BITS), 65)

    def test_chest_addresses_in_main_ram(self) -> None:
        for chest_name, (offset, _bit) in DWAP_CHEST_RAM_BITS.items():
            self.assertLess(offset, 0x200000,
                            f"{chest_name} offset 0x{offset:X} > 2 MiB")

    def test_chest_bits_in_byte_range(self) -> None:
        for chest_name, (_offset, bit) in DWAP_CHEST_RAM_BITS.items():
            self.assertIn(bit, range(8),
                          f"{chest_name} bit {bit} not in 0..7")

    def test_no_chest_collisions(self) -> None:
        seen: dict[tuple[int, int], str] = {}
        for chest_name, key in DWAP_CHEST_RAM_BITS.items():
            if key in seen:
                self.fail(f"{chest_name} collides with {seen[key]} at {key}")
            seen[key] = chest_name


# =============================================================================
# validate_rom
# =============================================================================


class TestValidateRom(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def _validate_with_response(self, response: bytes | None) -> bool:
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()

        async def fake_read(_bizhawk_ctx: Any, requests: list[Any]) -> list[bytes]:
            return [response if response is not None else b""]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            return _run(client.validate_rom(ctx))

    def test_accepts_typical_save(self) -> None:
        # 0..100 is in-range. Pick a mid-game value.
        self.assertTrue(self._validate_with_response(bytes([42])))

    def test_accepts_fresh_save(self) -> None:
        # Right after starting the game, prosperity = 0.
        self.assertTrue(self._validate_with_response(bytes([0])))

    def test_accepts_max_prosperity(self) -> None:
        # 100 is the in-game cap; still valid.
        self.assertTrue(self._validate_with_response(bytes([100])))

    def test_rejects_out_of_range(self) -> None:
        # Anything > 100 is "we are not looking at DW1".
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
                        already_sent: bool = False) -> _FakeClientCtx:
        client = DigimonWorldClient()
        client._goal_complete_sent = already_sent
        ctx = _FakeClientCtx(finished_game=already_finished)

        async def fake_read(_bizhawk_ctx: Any, requests: list[Any]) -> list[bytes]:
            return [bytes([prosperity_value])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            _run(client._check_goal(ctx))

        # also stash the client so the test can introspect it
        ctx._client = client  # type: ignore[attr-defined]
        return ctx

    def test_below_threshold_no_msg(self) -> None:
        ctx = self._run_check_goal(99)
        self.assertEqual(ctx.sent_msgs, [])
        self.assertFalse(ctx.finished_game)

    def test_at_threshold_fires_once(self) -> None:
        ctx = self._run_check_goal(100)
        self.assertEqual(len(ctx.sent_msgs), 1)
        msg = ctx.sent_msgs[0][0]
        self.assertEqual(msg["cmd"], "StatusUpdate")
        # ClientStatus.CLIENT_GOAL is 30 in NetUtils; just verify the
        # numeric value is what AP expects.
        from NetUtils import ClientStatus
        self.assertEqual(msg["status"], ClientStatus.CLIENT_GOAL)
        self.assertTrue(ctx.finished_game)

    def test_idempotent_when_already_finished(self) -> None:
        ctx = self._run_check_goal(100, already_finished=True)
        self.assertEqual(ctx.sent_msgs, [],
                         "Once finished_game is True, do not re-send")

    def test_idempotent_when_already_sent(self) -> None:
        ctx = self._run_check_goal(100, already_sent=True)
        self.assertEqual(ctx.sent_msgs, [],
                         "_goal_complete_sent should suppress re-fires")


# =============================================================================
# Item-delivery skeleton (no-op while v1 tables are empty)
# =============================================================================


class TestDeliverItemsNoopOnNoPending(DigimonWorldTestBase):
    """When the counter equals ``len(ctx.items_received)``, no writes
    should happen. This is the steady state of a connected client with
    no new items."""

    options: ClassVar[dict[str, Any]] = {}

    def test_no_pending_means_no_write(self) -> None:
        client = DigimonWorldClient()
        ctx = _FakeClientCtx()
        ctx.items_received = []  # nothing pending

        # Counter reads as 0 (matches len=0 → early return after read).
        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [b"\x00\x00"]

        with mock.patch.object(client_module.bizhawk, "read", fake_read), \
             mock.patch.object(client_module.bizhawk, "write") as mocked_write:
            _run(client._deliver_items(ctx))
            mocked_write.assert_not_called()


# =============================================================================
# Self-doc invariants the manifest depends on
# =============================================================================


class TestManifestConstants(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_main_ram_domain_string(self) -> None:
        self.assertEqual(DOMAIN_MAIN_RAM, "MainRAM")

    def test_prosperity_address_is_in_main_ram_range(self) -> None:
        # PSX MainRAM is exactly 2 MiB; any address >= 0x200000 would
        # be a manifest mistake.
        self.assertLess(RAM_PROSPERITY_POINTS, 0x200000)
