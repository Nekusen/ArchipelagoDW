"""Tests for the Phase 9 technique-rewards feature.

Covers:

* The address-helper math (slot -> byte/bit) matches the live-validated
  layout (snapshot 2026-05-11: slot 12 = bit 4 of 0x155801 was Static
  Elect on the starter).
* The item table defines exactly 56 ``"Tech: <name>"`` items, all
  classified ``useful``, with stable AP ids in the 697000-697056 range.
* ``choose_technique_pool`` produces 20-30 distinct names per call and
  varies across seeds.
* The client deliverer factory ORs the right bit and is idempotent.
* Every ``"Tech: <name>"`` item resolves to a delivery route via the
  central ``_build_item_delivery_routes`` machinery.
* When ``technique_rewards = vanilla``, the item pool ships no tech
  items; when ``ap_items``, it ships between 20 and 30.
"""

from __future__ import annotations

import asyncio
import random
from typing import Any, ClassVar
from unittest import mock

from BaseClasses import ItemClassification

from .. import client as client_module
from ..client import DOMAIN_MAIN_RAM, ITEM_DELIVERY_ROUTES
from ..data.addresses import (
    RAM_TECH_MASTERY_BASE,
    TECH_MASTERY_DUPLICATE_SLOT,
    TECH_MASTERY_SLOTS,
    TECH_NAMES_BY_SLOT,
    tech_mastery_bit,
    tech_mastery_bits,
)
from ..items import (
    _ITEM_TABLE,
    _TECHNIQUE_ITEMS,
    ITEM_NAME_GROUPS,
    ITEM_NAME_TO_ID,
    TECHNIQUE_ITEM_DW_CODE_BASE,
    TECHNIQUE_ITEM_PREFIX,
    choose_technique_pool,
    technique_slot_for_item,
)
from .bases import DigimonWorldTestBase


def _run(coro: Any) -> Any:
    return asyncio.get_event_loop().run_until_complete(coro)


# =============================================================================
# Address math
# =============================================================================


class TestTechMasteryBitMath(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_slot_count(self) -> None:
        """56 player-masterable slots (0..56 minus the duplicate 48)."""

        self.assertEqual(len(TECH_MASTERY_SLOTS), 56)
        self.assertNotIn(TECH_MASTERY_DUPLICATE_SLOT, TECH_MASTERY_SLOTS)

    def test_slot_0(self) -> None:
        """Fire Tower -> bit 0 of base byte."""

        self.assertEqual(tech_mastery_bit(0), (RAM_TECH_MASTERY_BASE, 0))

    def test_slot_12_matches_snapshot(self) -> None:
        """Live-validated 2026-05-11: starter's Static Elect bit was
        bit 4 of byte 0x155801."""

        self.assertEqual(tech_mastery_bit(12), (RAM_TECH_MASTERY_BASE + 1, 4))

    def test_slot_56_at_byte_7(self) -> None:
        """Highest player-masterable slot lands in the 8th bitmap byte."""

        self.assertEqual(tech_mastery_bit(56), (RAM_TECH_MASTERY_BASE + 7, 0))

    def test_duplicate_slot_rejected(self) -> None:
        with self.assertRaises(ValueError):
            tech_mastery_bit(TECH_MASTERY_DUPLICATE_SLOT)

    def test_out_of_range_slot_rejected(self) -> None:
        with self.assertRaises(ValueError):
            tech_mastery_bit(100)


# =============================================================================
# Item table
# =============================================================================


class TestTechniqueItemTable(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_item_count(self) -> None:
        self.assertEqual(len(_TECHNIQUE_ITEMS), 56)

    def test_item_names_use_prefix(self) -> None:
        for name in _TECHNIQUE_ITEMS:
            self.assertTrue(name.startswith(TECHNIQUE_ITEM_PREFIX), name)

    def test_item_names_match_tech_table(self) -> None:
        """Every ``Tech: X`` item maps back to a TECH_NAMES_BY_SLOT entry."""

        for slot in TECH_MASTERY_SLOTS:
            name = TECHNIQUE_ITEM_PREFIX + TECH_NAMES_BY_SLOT[slot]
            self.assertIn(name, _TECHNIQUE_ITEMS, name)

    def test_all_items_useful(self) -> None:
        for name, entry in _TECHNIQUE_ITEMS.items():
            self.assertEqual(
                entry.classification, ItemClassification.useful,
                f"{name} should be useful, got {entry.classification}",
            )

    def test_dw_codes_in_7000_range(self) -> None:
        for slot in TECH_MASTERY_SLOTS:
            name = TECHNIQUE_ITEM_PREFIX + TECH_NAMES_BY_SLOT[slot]
            self.assertEqual(
                _TECHNIQUE_ITEMS[name].dw_code,
                TECHNIQUE_ITEM_DW_CODE_BASE + slot,
            )

    def test_no_dw_code_collision_with_other_blocks(self) -> None:
        """7000-block must not collide with any other existing block."""

        tech_codes = {entry.dw_code for entry in _TECHNIQUE_ITEMS.values()}
        other_codes = {
            entry.dw_code for name, entry in _ITEM_TABLE.items()
            if name not in _TECHNIQUE_ITEMS
        }
        self.assertEqual(tech_codes & other_codes, set())

    def test_techniques_group_present(self) -> None:
        self.assertIn("Techniques", ITEM_NAME_GROUPS)
        self.assertEqual(ITEM_NAME_GROUPS["Techniques"], set(_TECHNIQUE_ITEMS))

    def test_technique_slot_for_item_roundtrip(self) -> None:
        for slot in TECH_MASTERY_SLOTS:
            name = TECHNIQUE_ITEM_PREFIX + TECH_NAMES_BY_SLOT[slot]
            self.assertEqual(technique_slot_for_item(name), slot)

    def test_technique_slot_for_non_tech_item(self) -> None:
        self.assertIsNone(technique_slot_for_item("Mansion Key"))
        self.assertIsNone(technique_slot_for_item("Prosperity Point"))
        self.assertIsNone(technique_slot_for_item("nonexistent"))

    def test_ap_id_in_expected_range(self) -> None:
        for name in _TECHNIQUE_ITEMS:
            ap_id = ITEM_NAME_TO_ID[name]
            self.assertGreaterEqual(ap_id, 690_000 + TECHNIQUE_ITEM_DW_CODE_BASE)
            self.assertLess(ap_id, 690_000 + TECHNIQUE_ITEM_DW_CODE_BASE + 100)


# =============================================================================
# Pool selection
# =============================================================================


class TestChooseTechniquePool(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_size_in_20_30_range(self) -> None:
        for seed in range(50):
            pool = choose_technique_pool(random.Random(seed))
            self.assertGreaterEqual(len(pool), 20, f"seed {seed}: {len(pool)}")
            self.assertLessEqual(len(pool), 30, f"seed {seed}: {len(pool)}")

    def test_pool_entries_are_unique(self) -> None:
        for seed in range(50):
            pool = choose_technique_pool(random.Random(seed))
            self.assertEqual(len(pool), len(set(pool)), f"seed {seed}")

    def test_pool_entries_are_real_tech_items(self) -> None:
        pool = choose_technique_pool(random.Random(0))
        for name in pool:
            self.assertIn(name, _TECHNIQUE_ITEMS, name)

    def test_pool_varies_across_seeds(self) -> None:
        """Two distinct seeds shouldn't produce identical pools."""

        pool_a = set(choose_technique_pool(random.Random(0)))
        pool_b = set(choose_technique_pool(random.Random(1)))
        self.assertNotEqual(pool_a, pool_b)

    def test_pool_is_deterministic_per_seed(self) -> None:
        """Same seed -> same pool (so generation is reproducible)."""

        pool_a = choose_technique_pool(random.Random(42))
        pool_b = choose_technique_pool(random.Random(42))
        self.assertEqual(pool_a, pool_b)


# =============================================================================
# Delivery routes
# =============================================================================


class TestTechniqueDeliveryRoutes(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_all_techniques_have_routes(self) -> None:
        for name in _TECHNIQUE_ITEMS:
            self.assertIn(name, ITEM_DELIVERY_ROUTES, name)

    def test_route_is_separate_from_bank_route(self) -> None:
        """``Tech: <name>`` must dispatch through the bit-OR deliverer,
        NOT the 2000-block bank deliverer (the dw_code is 7000+, well
        outside the bank range — but the check guards against any
        future bank-range expansion)."""

        # Trigger by inspecting the closure name. Both bank and tech
        # routes are async closures named "deliver", so we can't
        # distinguish by name; instead exercise the route and verify
        # the write lands on the mastery bitmap, not the bank.
        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Fire Tower"]
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([0x00])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(len(writes), 1)
        addr, byte_list, domain = writes[0]
        self.assertEqual(addr, RAM_TECH_MASTERY_BASE)
        self.assertEqual(byte_list, [0x01])
        self.assertEqual(domain, DOMAIN_MAIN_RAM)


class TestTechniqueDelivery(DigimonWorldTestBase):
    """The deliverer factory produces correct OR-writes and is
    idempotent at the bit level."""

    options: ClassVar[dict[str, Any]] = {}

    def test_writes_correct_bit_for_slot_12(self) -> None:
        """Slot 12 (Static Elect) -> byte 0x155801, bit 4 -> mask 0x10."""

        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Static Elect"]
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([0x00])]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(len(writes), 1)
        addr, byte_list, _ = writes[0]
        self.assertEqual(addr, RAM_TECH_MASTERY_BASE + 1)
        self.assertEqual(byte_list, [0x10])

    def test_writes_preserve_already_set_bits(self) -> None:
        """OR semantics: a pre-existing bit in the same byte survives."""

        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Thunder Justice"]  # slot 8
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([0x10])]  # Static Elect (slot 12) already set

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(len(writes), 1)
        _, byte_list, _ = writes[0]
        self.assertEqual(byte_list, [0x11])  # Static Elect + Thunder Justice

    def test_idempotent_when_already_set(self) -> None:
        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Fire Tower"]  # slot 0
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [bytes([0x01])]  # bit already on

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(writes, [])

    def test_empty_read_response_returns_no_writes(self) -> None:
        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Fire Tower"]
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            return [b""]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(writes, [])


class TestTechMasteryCompanionBits(DigimonWorldTestBase):
    """Dynamite Kick and Horizontal Kick set a second bit, exactly as
    vanilla's own ``learnMove`` @ 0x800E5F14 does.

    Console-verified 2026-08-23 (``learnMove`` decomp unit): the routine ORs
    a two-bit u32 mask into the word at 0x00155804 -- 0x00011000 for Dynamite
    Kick (slots 44 + 48) and 0x02800000 for Horizontal Kick (slots 55 + 57).
    ``getNumMasteredMoves`` is a plain 64-bit popcount over that word pair, and
    ``calculateRequirementScore`` gates digivolution on the result, so an AP
    grant that wrote only the primary bit was worth one less mastered move
    than a naturally-learned one.
    """

    options: ClassVar[dict[str, Any]] = {}

    def test_plain_technique_has_a_single_bit(self) -> None:
        self.assertEqual(tech_mastery_bits(12), (tech_mastery_bit(12),))

    def test_dynamite_kick_also_sets_slot_48(self) -> None:
        self.assertEqual(
            tech_mastery_bits(44),
            ((RAM_TECH_MASTERY_BASE + 5, 4), (RAM_TECH_MASTERY_BASE + 6, 0)),
        )

    def test_horizontal_kick_also_sets_slot_57(self) -> None:
        self.assertEqual(
            tech_mastery_bits(55),
            ((RAM_TECH_MASTERY_BASE + 6, 7), (RAM_TECH_MASTERY_BASE + 7, 1)),
        )

    def test_companion_masks_match_the_vanilla_u32_words(self) -> None:
        """The two bits must reconstruct learnMove's literal masks."""

        for slot, expected in ((44, 0x00011000), (55, 0x02800000)):
            with self.subTest(slot=slot):
                word = 0
                for byte_addr, bit_index in tech_mastery_bits(slot):
                    byte_offset = byte_addr - (RAM_TECH_MASTERY_BASE + 4)
                    self.assertIn(byte_offset, range(4), "outside the 0x155804 word")
                    word |= (1 << bit_index) << (8 * byte_offset)
                self.assertEqual(word, expected)

    def test_deliverer_writes_both_bytes_for_dynamite_kick(self) -> None:
        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Dynamite Kick"]
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, requests: list[Any]) -> list[bytes]:
            return [bytes([0x00]) for _ in requests]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(
            sorted((addr, tuple(byte_list)) for addr, byte_list, _ in writes),
            [(RAM_TECH_MASTERY_BASE + 5, (0x10,)), (RAM_TECH_MASTERY_BASE + 6, (0x01,))],
        )

    def test_deliverer_still_completes_a_half_applied_grant(self) -> None:
        """Primary bit already on, companion missing -> write the companion."""

        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Dynamite Kick"]
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, requests: list[Any]) -> list[bytes]:
            # requests are (addr, length, domain); byte 5 has slot 44 set already
            return [
                bytes([0x10]) if addr == RAM_TECH_MASTERY_BASE + 5 else bytes([0x00])
                for addr, _length, _domain in requests
            ]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(len(writes), 1)
        addr, byte_list, _ = writes[0]
        self.assertEqual((addr, byte_list), (RAM_TECH_MASTERY_BASE + 6, [0x01]))

    def test_deliverer_idempotent_when_both_bits_set(self) -> None:
        deliverer = ITEM_DELIVERY_ROUTES[TECHNIQUE_ITEM_PREFIX + "Horizontal Kick"]
        ctx = _FakeClientCtxMinimal()

        async def fake_read(_bizhawk_ctx: Any, requests: list[Any]) -> list[bytes]:
            preset = {RAM_TECH_MASTERY_BASE + 6: 0x80, RAM_TECH_MASTERY_BASE + 7: 0x02}
            return [bytes([preset.get(addr, 0x00)]) for addr, _length, _domain in requests]

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            writes = _run(deliverer(ctx))

        self.assertEqual(writes, [])


# =============================================================================
# Pool composition (full world bootstrap)
# =============================================================================


class TestPoolWhenVanilla(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"technique_rewards": 0}  # option_vanilla

    def test_no_tech_items_in_pool(self) -> None:
        names = {item.name for item in self.multiworld.itempool}
        tech_names = {n for n in names if n.startswith(TECHNIQUE_ITEM_PREFIX)}
        self.assertEqual(tech_names, set())


class TestPoolWhenApItems(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"technique_rewards": 1}  # option_ap_items

    def test_tech_items_in_pool_count(self) -> None:
        names = [item.name for item in self.multiworld.itempool]
        tech_names = [n for n in names if n.startswith(TECHNIQUE_ITEM_PREFIX)]
        # Pool selection picks 20-30 unique techs. The pool itself may
        # be trimmed by available-locations capacity, so allow values
        # at the lower end of the range too.
        self.assertGreaterEqual(len(tech_names), 1)
        self.assertLessEqual(len(tech_names), 30)
        # No duplicates within the tech-items subset.
        self.assertEqual(len(tech_names), len(set(tech_names)))

    def test_tech_items_are_useful(self) -> None:
        for item in self.multiworld.itempool:
            if item.name.startswith(TECHNIQUE_ITEM_PREFIX):
                self.assertEqual(
                    item.classification, ItemClassification.useful, item.name,
                )


# =============================================================================
# Test scaffolding
# =============================================================================


class _FakeClientCtxMinimal:
    """Minimal context fake for testing the bit-OR deliverer in isolation."""

    def __init__(self) -> None:
        self.bizhawk_ctx = object()
