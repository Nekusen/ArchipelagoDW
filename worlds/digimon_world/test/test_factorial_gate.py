"""Factorial Town <-> Gear Savanna gate (Andromon's iron door, ``factorial_gate``).

Research + lab validation 2026-09-01 (``work/dw1_re/decomp/factorial_gate/NOTES.md``):
trigger 328 opens the door; the quest-side neuter (five 328 -> 329 rewrites) went
through the three PATCH_PROCESS nets. These tests pin the production wiring: option
modes, pool emission, neuter tokens, delivery bit, and the logic edges.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..data.addresses import (
    FACTORIAL_GATE_TRIGGER_ID,
    KEYITEM_DELIVERY_RAM_BITS,
    RAM_FACTORIAL_GATE_OPEN,
    ROM_FACTORIAL_GATE_NEUTER_OFFSETS,
    ROM_FACTORIAL_GATE_NEUTER_VALUE,
)
from .bases import DigimonWorldTestBase
from .test_region_gates import _capture_tokens


class TestConstants(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_bit_matches_the_trigger_formula(self) -> None:
        self.assertEqual(FACTORIAL_GATE_TRIGGER_ID, 328)
        self.assertEqual(
            RAM_FACTORIAL_GATE_OPEN,
            (0x001BDFCD + 328 // 8, 328 % 8),
        )
        self.assertEqual(RAM_FACTORIAL_GATE_OPEN, (0x001BDFF6, 0))

    def test_neuter_family_matches_the_lab_spec(self) -> None:
        self.assertEqual(ROM_FACTORIAL_GATE_NEUTER_OFFSETS, (
            0x14050A8C, 0x140503FC, 0x14050A94, 0x140B9AA2, 0x13FD8922,
        ))
        self.assertEqual(ROM_FACTORIAL_GATE_NEUTER_VALUE, bytes((0x49, 0x01)))

    def test_delivery_bit_registered(self) -> None:
        self.assertEqual(
            KEYITEM_DELIVERY_RAM_BITS["Factorial Town Gate"],
            RAM_FACTORIAL_GATE_OPEN,
        )


class TestVanillaMode(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"factorial_gate": "vanilla"}

    def test_no_item_no_tokens_no_edges(self) -> None:
        item_names = {item.name for item in self.multiworld.itempool}
        self.assertNotIn("Factorial Town Gate", item_names)
        written = {off for off, _data in _capture_tokens(self.world)}
        for off in ROM_FACTORIAL_GATE_NEUTER_OFFSETS:
            self.assertNotIn(off, written)
        entrances = {e.name for e in self.multiworld.get_entrances(self.player)}
        self.assertNotIn("Gear Savanna to Factorial Town", entrances)
        self.assertNotIn("Factorial Town to Gear Savanna", entrances)


class TestShuffledMode(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"factorial_gate": "shuffled"}

    def test_item_in_pool_once(self) -> None:
        count = sum(
            1 for item in self.multiworld.itempool
            if item.name == "Factorial Town Gate"
        )
        self.assertEqual(count, 1)

    def test_neuter_tokens_emitted(self) -> None:
        tokens = _capture_tokens(self.world)
        for off in ROM_FACTORIAL_GATE_NEUTER_OFFSETS:
            self.assertIn((off, ROM_FACTORIAL_GATE_NEUTER_VALUE), tokens)

    def test_gate_item_is_a_second_entrance(self) -> None:
        # Without both the ferry (Whamon Recruit) and the gate item,
        # Factorial Town is unreachable; either one alone suffices
        # (the gate side also needs Gear Savanna, which the rest of the
        # pool provides).
        self.collect_all_but(["Whamon Recruit", "Factorial Town Gate"])
        self.assertFalse(self.can_reach_region("Factorial Town"))

        gate = self.collect_by_name("Factorial Town Gate")
        self.assertTrue(self.can_reach_region("Factorial Town"))

        self.remove(gate)
        self.assertFalse(self.can_reach_region("Factorial Town"))
        self.collect_by_name("Whamon Recruit")
        self.assertTrue(self.can_reach_region("Factorial Town"))

    def test_gate_blocks_both_directions(self) -> None:
        # The door physically blocks both ways: the reverse edge carries
        # the same rule (research: the closed door seals even the
        # warp-strip cells).
        self.collect_all_but(["Factorial Town Gate"])
        self.assertFalse(self.can_reach_entrance("Factorial Town to Gear Savanna"))
        self.collect_by_name("Factorial Town Gate")
        self.assertTrue(self.can_reach_entrance("Factorial Town to Gear Savanna"))


class TestAlwaysOpenMode(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"factorial_gate": "always_open"}

    def test_no_item_but_neuter_still_emitted(self) -> None:
        # The neuter is NOT shuffled-only (unlike the Great Canyon
        # template): a client-pinned 328 would sequence-break Andromon's
        # recruit chain through the quest-side readers.
        item_names = {item.name for item in self.multiworld.itempool}
        self.assertNotIn("Factorial Town Gate", item_names)
        tokens = _capture_tokens(self.world)
        for off in ROM_FACTORIAL_GATE_NEUTER_OFFSETS:
            self.assertIn((off, ROM_FACTORIAL_GATE_NEUTER_VALUE), tokens)

    def test_gear_savanna_side_is_a_free_entrance(self) -> None:
        self.collect_all_but(["Whamon Recruit"])
        self.assertTrue(self.can_reach_region("Factorial Town"))
