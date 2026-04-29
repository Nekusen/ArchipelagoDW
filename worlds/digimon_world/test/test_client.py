"""Tests for the Digimon World 1 BizHawk client (Phase 5 piece C).

What this client does:

* Polls every recruit AP location via the *beaten* trigger bit
  (Phase 5 piece C: the setTrigger wrapper redirects every
  ``setTrigger(200+digimon_id)`` into the unused 723..778 range, so
  the player can fight any Digimon without auto-joining the city).
* Polls every chest AP location via DWAP's chest-bit table (65).
* On items_received, dispatches each item to a deliverer:
  - bank deliverers for the 2000-block items;
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

from worlds._bizhawk.client import AutoBizHawkClientRegister

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
    BEATEN_RAM_BITS,
    DWAP_CHEST_RAM_BITS,
    RAM_PROSPERITY_POINTS,
    RECRUIT_RAM_BITS,
)
from ..items import PROSPERITY_PER_ITEM, PROSPERITY_POINT_NAME
from ..locations import CHEST_NAMES, RECRUIT_NAMES
from .bases import DigimonWorldTestBase


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


class _FakeClientCtx:
    """Stand-in for :class:`BizHawkClientContext`. Only the fields the
    client actually touches are present."""

    def __init__(self, *, server: Any = None, slot: int | None = 1,
                 finished_game: bool = False) -> None:
        self.bizhawk_ctx = object()  # opaque — passed to mocked bizhawk.read/write
        self.server = server if server is not None else object()
        self.slot = slot
        self.game: str = "Digimon World"
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
        self.assertIn("Digimon World", psx_handlers)
        self.assertIsInstance(psx_handlers["Digimon World"], DigimonWorldClient)

    def test_apdw1_suffix_is_in_bizhawk_component(self) -> None:
        from worlds._bizhawk.client import component as bizhawk_component
        self.assertIn(".apdw1", bizhawk_component.file_identifier.suffixes)


# =============================================================================
# Detection tables
# =============================================================================


class TestRecruitDispatch(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_all_recruits_in_dispatch(self) -> None:
        for recruit_name in RECRUIT_NAMES:
            self.assertIn(recruit_name, LOCATION_RAM_BITS)

    def test_recruit_dispatch_uses_beaten_bits(self) -> None:
        """Phase 5 piece C: detection moved from vanilla recruit bits to
        the redirected ``beaten`` bits installed by the setTrigger
        wrapper — the recruit bits never light up post-wrapper."""

        for recruit_name in RECRUIT_NAMES:
            self.assertEqual(
                LOCATION_RAM_BITS[recruit_name],
                BEATEN_RAM_BITS[recruit_name],
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
        seen: dict[tuple[int, int], str] = {}
        for name, key in LOCATION_RAM_BITS.items():
            if key in seen:
                self.fail(f"{name} collides with {seen[key]} at {key}")
            seen[key] = name

    def test_dispatch_size(self) -> None:
        # 50 recruits + 65 chests
        self.assertEqual(len(LOCATION_RAM_BITS), 50 + 65)


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

    def test_counter_outside_known_used_regions(self) -> None:
        assert ITEMS_RECEIVED_COUNTER is not None
        counter_addr, counter_size = ITEMS_RECEIVED_COUNTER
        counter_range = range(counter_addr, counter_addr + counter_size)

        used_addrs: set[int] = set()
        for addr, _bit in LOCATION_RAM_BITS.values():
            used_addrs.add(addr)
        from ..data.addresses import RAM_ITEM_BANK_BASE, RAM_ITEM_BANK_SIZE
        used_addrs.update(range(
            RAM_ITEM_BANK_BASE,
            RAM_ITEM_BANK_BASE + RAM_ITEM_BANK_SIZE,
        ))
        for byte_addr in counter_range:
            self.assertNotIn(byte_addr, used_addrs)


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
                        already_sent: bool = False) -> _FakeClientCtx:
        client = DigimonWorldClient()
        client._goal_complete_sent = already_sent
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
        # RECRUIT_NAMES (49, post-Agumon-drop) is a subset of
        # RECRUIT_RAM_BITS (50, manifest still includes Agumon for the
        # client's force-set deliverer).
        for recruit_name in RECRUIT_NAMES:
            self.assertIn(recruit_name, RECRUIT_RAM_BITS)
        self.assertEqual(len(RECRUIT_RAM_BITS), 50)
        self.assertEqual(len(RECRUIT_NAMES), 49)
        self.assertNotIn("Agumon", RECRUIT_NAMES)
        self.assertIn("Agumon", RECRUIT_RAM_BITS)

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
        self.assertEqual(len(DWAP_CHEST_RAM_BITS), 65)

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
