"""Species technique-list randomization (:mod:`worlds.digimon_world.technique_lists`)."""

from __future__ import annotations

import unittest
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import enemies
from .. import rom as rom_module
from .. import technique_lists as tl
from ..data.addresses import DIGIMON_DATA_MOVES_OFFSET, digimon_data_bin_offset
from .bases import DigimonWorldTestBase


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestPools(unittest.TestCase):
    def test_classes_and_elements(self) -> None:
        self.assertEqual(tl.tech_class(0), tl.CLASS_NORMAL)
        self.assertEqual(tl.tech_class(57), tl.CLASS_NORMAL)
        self.assertEqual(tl.tech_class(58), tl.CLASS_FINISHER)
        self.assertEqual(tl.tech_class(112), tl.CLASS_FINISHER)
        self.assertEqual(tl.tech_class(113), tl.CLASS_BUBBLE)
        fire_normals = tl.candidate_pool(0)                     # Fire Tower
        self.assertEqual(fire_normals, list(range(0, 8)))
        self.assertTrue(all(tl.ELEMENT_OF[t] == tl.ELEMENT_OF[0] for t in fire_normals))
        self.assertEqual(tl.candidate_pool(115), [115])         # a bubble never moves
        finisher_pool = tl.candidate_pool(58)
        self.assertTrue(all(58 <= t <= 112 and tl.ELEMENT_OF[t] == tl.ELEMENT_OF[58] for t in finisher_pool))

    def test_shuffleable_species(self) -> None:
        species = tl.shuffleable_species()
        self.assertTrue(set(range(1, 62)) <= set(species))       # every partner species
        self.assertNotIn(169, species)
        self.assertNotIn(0, species)
        self.assertNotIn(134, species)                            # the ferry Seadramon clone: no list


class TestRandomizeList(unittest.TestCase):
    def test_structure_is_preserved(self) -> None:
        for seed in range(5):
            lists = tl.randomize_lists(Random(seed))
            self.assertTrue(lists)
            for species_id, moves in lists.items():
                vanilla = enemies.SPECIES_BY_ID[species_id].moves
                self.assertEqual(len(moves), 16)
                populated = [k for k in range(16) if vanilla[k] != enemies.NO_MOVE]
                self.assertEqual([k for k in range(16) if moves[k] != enemies.NO_MOVE], populated)
                for k in populated:
                    self.assertEqual(tl.tech_class(moves[k]), tl.tech_class(vanilla[k]), (species_id, k))
                    self.assertEqual(tl.ELEMENT_OF[moves[k]], tl.ELEMENT_OF[vanilla[k]], (species_id, k))
                    if vanilla[k] >= tl.BUBBLE_FIRST:
                        self.assertEqual(moves[k], vanilla[k])
                used = [m for m in moves if m != enemies.NO_MOVE]
                self.assertEqual(len(used), len(set(used)), species_id)
            if 60 in lists:
                self.assertEqual(lists[60][14], enemies.SPECIES_BY_ID[60].moves[14])   # H-Kabuterimon, hard-wired

    def test_deterministic(self) -> None:
        self.assertEqual(tl.randomize_lists(Random(9)), tl.randomize_lists(Random(9)))

    def test_species_table_and_enemy_planner(self) -> None:
        plan = tl.ListPlan(tl.randomize_lists(Random(1)))
        table = plan.species_table
        self.assertEqual(len(table), 180)
        changed = next(iter(plan.lists))
        self.assertEqual(table[changed].moves, plan.lists[changed])
        self.assertEqual(table[changed].tech_slots, enemies.SPECIES_BY_ID[changed].tech_slots)
        # the enemy planner reads the shuffled powers through the table
        vanilla_metrics = enemies.region_wild_metrics()
        shuffled_metrics = enemies.region_wild_metrics(species_table=table)
        self.assertEqual(set(vanilla_metrics), set(shuffled_metrics))
        self.assertTrue(any(vanilla_metrics[r].tech_level != shuffled_metrics[r].tech_level for r in vanilla_metrics))

    def test_tokens(self) -> None:
        moves = tuple(enemies.SPECIES_BY_ID[3].moves)
        plan = tl.ListPlan({3: moves})
        patch = _TokenCollector()
        rom_module._write_species_list_tokens(patch, plan)  # type: ignore[arg-type]
        self.assertEqual(patch.tokens, [(digimon_data_bin_offset(3, DIGIMON_DATA_MOVES_OFFSET), bytes(moves))])


class TestSpeciesListOption(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"species_technique_lists": True, "enemy_stats": "full_random"}

    def test_plan(self) -> None:
        self.assertGreater(len(self.world.list_plan.lists), 100)
        self.world.post_fill()
        self.assertTrue(self.world.enemy_plan.move_overrides)


class TestSpeciesListOptionOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plan_is_empty(self) -> None:
        self.assertTrue(self.world.list_plan.empty)
