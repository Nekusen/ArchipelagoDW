"""Technique data / element matrix randomization (:mod:`worlds.digimon_world.techniques`).

Covers the vanilla table, the shuffle / random planners as pure functions (pool boundaries,
value ranges, status rules), the tokens the patcher emits, the option wiring, and the
composition with the enemy planner (scaling reads the randomized powers).
"""

from __future__ import annotations

import struct
import unittest
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import enemies, techniques
from .. import rom as rom_module
from ..data.addresses import (
    ROM_ELEMENT_MATRIX_OFFSET,
    ROM_MOVE_DATA_OFFSET,
    element_matrix_bin_offset,
    iter_user_data_chunks,
    move_data_bin_offset,
)
from ..data.enemy_records import ELEMENT_MATRIX
from .bases import DigimonWorldTestBase

_ALL_ON = {"power": True, "mp_cost": True, "accuracy": True, "effect": True, "effect_chance": True}


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestVanillaTable(unittest.TestCase):
    def test_table(self) -> None:
        self.assertEqual(len(techniques.VANILLA_VALUES), techniques.MOVE_COUNT)
        fire_tower = techniques.VANILLA_VALUES[0]
        self.assertEqual(fire_tower, techniques.TechValues(155, 27, 55, 3, 8))
        self.assertEqual(techniques.MOVE_NAMES[0x2D], "Counter")
        self.assertEqual(techniques.MOVE_NAMES[121], "tech79")            # the nameless internal record
        # partner-learnable techniques are the first 58; finishers keep 100 accuracy / 40 MP
        self.assertTrue(all(techniques.is_learnable(i) for i in range(58)))
        self.assertFalse(techniques.is_learnable(58))
        self.assertEqual((techniques.VANILLA_VALUES[58].accuracy, techniques.VANILLA_VALUES[58].mp_cost), (100, 40))
        # buffs have power 0 and no status
        war_cry = next(i for i, name in techniques.MOVE_NAMES.items() if name == "War Cry")
        self.assertEqual(techniques.VANILLA_VALUES[war_cry].power, 0)
        self.assertEqual(techniques.VANILLA_VALUES[war_cry].status, techniques.STATUS_NONE)

    def test_matrix(self) -> None:
        self.assertEqual(len(ELEMENT_MATRIX), 7)
        self.assertTrue(all(len(row) == 7 for row in ELEMENT_MATRIX))
        self.assertTrue(all(v in techniques.ELEMENT_VALUES for row in ELEMENT_MATRIX for v in row))
        self.assertEqual(ELEMENT_MATRIX[0], (10, 15, 5, 20, 20, 15, 20))    # Fire techniques


class TestShuffle(unittest.TestCase):
    def test_vanilla_mode_changes_nothing(self) -> None:
        self.assertEqual(techniques.randomize_technique_data(Random(1), techniques.DATA_VANILLA, **_ALL_ON), {})

    def test_shuffle_is_a_permutation_inside_the_partner_pool(self) -> None:
        moves = techniques.randomize_technique_data(
            Random(7), techniques.DATA_SHUFFLE, power=True, mp_cost=True, accuracy=True, effect=False,
            effect_chance=False,
        )
        self.assertTrue(moves)
        self.assertTrue(all(techniques.is_learnable(i) for i in moves))
        final = {i: moves.get(i, techniques.VANILLA_VALUES[i]) for i in range(techniques.PARTNER_MOVE_COUNT)}
        vanilla = [techniques.VANILLA_VALUES[i] for i in range(techniques.PARTNER_MOVE_COUNT)]
        for field in ("power", "mp_cost", "accuracy"):
            self.assertEqual(sorted(getattr(v, field) for v in final.values()),
                             sorted(getattr(v, field) for v in vanilla), field)
        # buffs keep power 0 (powers only swap among damaging techniques)
        for i, values in final.items():
            self.assertEqual(values.power == 0, techniques.VANILLA_VALUES[i].power == 0, i)
            self.assertEqual((values.status, values.status_chance),
                             (techniques.VANILLA_VALUES[i].status, techniques.VANILLA_VALUES[i].status_chance))

    def test_single_field_toggles(self) -> None:
        for field in ("power", "mp_cost", "accuracy"):
            flags = {k: k == field for k in _ALL_ON}
            moves = techniques.randomize_technique_data(Random(3), techniques.DATA_SHUFFLE, **flags)
            for i, values in moves.items():
                vanilla = techniques.VANILLA_VALUES[i]
                for other in ("power", "mp_cost", "accuracy", "status", "status_chance"):
                    if other != field:
                        self.assertEqual(getattr(values, other), getattr(vanilla, other), (i, other))

    def test_status_rules(self) -> None:
        moves = techniques.randomize_technique_data(
            Random(11), techniques.DATA_SHUFFLE, power=False, mp_cost=False, accuracy=False, effect=True,
            effect_chance=True,
        )
        final = {i: moves.get(i, techniques.VANILLA_VALUES[i]) for i in range(techniques.PARTNER_MOVE_COUNT)}
        with_status = [v for v in final.values() if v.status != techniques.STATUS_NONE]
        self.assertTrue(with_status)
        for values in final.values():
            if values.power == 0:
                self.assertEqual(values.status, techniques.STATUS_NONE)
            if values.status == techniques.STATUS_NONE:
                self.assertEqual(values.status_chance, 0)
            else:
                self.assertIn(values.status, techniques.STATUS_EFFECT_IDS)
                self.assertTrue(1 <= values.status_chance <= techniques.STATUS_CHANCE_MAX)


class TestRandom(unittest.TestCase):
    def test_random_mode_reaches_enemy_techniques_and_stays_in_range(self) -> None:
        moves = techniques.randomize_technique_data(Random(5), techniques.DATA_RANDOM, **_ALL_ON)
        self.assertTrue(any(not techniques.is_learnable(i) for i in moves))
        self.assertNotIn(121, moves)
        for i, values in moves.items():
            vanilla = techniques.VANILLA_VALUES[i]
            self.assertTrue(0 <= values.power <= techniques.POWER_CAP)
            self.assertEqual(values.power == 0, vanilla.power == 0)
            self.assertTrue(0 <= values.mp_cost <= techniques.MP_COST_BYTE_CAP)
            if values.power:
                self.assertLessEqual(values.mp_cost, 140 * values.power // 300 + 1)
            self.assertTrue(33 <= values.accuracy <= 100)

    def test_enemy_only_techniques_keep_status(self) -> None:
        moves = techniques.randomize_technique_data(Random(5), techniques.DATA_RANDOM, **_ALL_ON)
        for i, values in moves.items():
            if not techniques.is_learnable(i):
                self.assertEqual((values.status, values.status_chance),
                                 (techniques.VANILLA_VALUES[i].status, techniques.VANILLA_VALUES[i].status_chance))

    def test_deterministic(self) -> None:
        a = techniques.randomize_technique_data(Random(99), techniques.DATA_RANDOM, **_ALL_ON)
        b = techniques.randomize_technique_data(Random(99), techniques.DATA_RANDOM, **_ALL_ON)
        self.assertEqual(a, b)

    def test_matrix_values(self) -> None:
        matrix = techniques.randomize_element_matrix(Random(2))
        self.assertEqual(len(matrix), 7)
        self.assertTrue(all(len(row) == 7 and all(v in techniques.ELEMENT_VALUES for v in row) for row in matrix))
        self.assertNotEqual(matrix, tuple(tuple(row) for row in ELEMENT_MATRIX))


class TestPlanAndTokens(unittest.TestCase):
    def test_powers_overlay(self) -> None:
        plan = techniques.TechniquePlan({0: techniques.TechValues(500, 10, 80, 0, 0)}, None)
        powers = plan.powers
        self.assertEqual(powers[0], 500)
        self.assertEqual(powers[2], 66)
        self.assertEqual(len(powers), techniques.MOVE_COUNT)
        self.assertTrue(techniques.EMPTY_PLAN.empty)
        self.assertFalse(plan.empty)

    def test_tokens(self) -> None:
        matrix = tuple(tuple(20 if r == c else 2 for c in range(7)) for r in range(7))
        plan = techniques.TechniquePlan(
            {0: techniques.TechValues(500, 10, 80, 1, 30), 0x5C: techniques.TechValues(300, 40, 100, 0, 0)},
            matrix,
        )
        patch = _TokenCollector()
        rom_module._write_technique_tokens(patch, plan)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        # Fire Tower: power .. statusChance with vanilla iframes 26 / range 2 / element 0 in between
        self.assertEqual(tokens[move_data_bin_offset(0, 4)], struct.pack("<hBBBBBBB", 500, 10, 26, 2, 0, 1, 80, 30))
        self.assertEqual(move_data_bin_offset(0, 4), ROM_MOVE_DATA_OFFSET + 4)
        # technique 0x5C's record straddles a sector boundary (the standalone's exclusion) between
        # its distance word and the span we write, so the span itself is one token past the gap
        self.assertEqual(move_data_bin_offset(0x5C, 0), 0x14D673B4)
        self.assertEqual(move_data_bin_offset(0x5C, 4), 0x14D673B8 + 2352 - 2048)
        self.assertEqual(len(tokens[move_data_bin_offset(0x5C, 4)]), 9)
        # ... and a write covering the whole record would be split in two by the chunker
        chunks = list(iter_user_data_chunks(ROM_MOVE_DATA_OFFSET, 0x5C * 16, bytes(16)))
        self.assertEqual([(off, len(data)) for off, data in chunks],
                         [(0x14D673B4, 4), (0x14D673B8 + 2352 - 2048, 12)])
        # the matrix is one 49-byte run
        self.assertEqual(tokens[ROM_ELEMENT_MATRIX_OFFSET], bytes(v for row in matrix for v in row))
        self.assertEqual(element_matrix_bin_offset(1, 0), ROM_ELEMENT_MATRIX_OFFSET + 7)

    def test_no_tokens_for_the_empty_plan(self) -> None:
        patch = _TokenCollector()
        rom_module._write_technique_tokens(patch, techniques.EMPTY_PLAN)  # type: ignore[arg-type]
        self.assertEqual(patch.tokens, [])


class TestEnemyPlannerReadsRandomizedPowers(unittest.TestCase):
    def test_pick_moves_by_level_follows_the_table(self) -> None:
        icemon = enemies.SPECIES_BY_ID[94]
        vanilla = enemies.pick_moves_by_level(icemon, 1, 130)
        self.assertEqual(vanilla, (0x2E + 2, 0xFF, 0xFF, 0xFF))         # slot 2 = 126 power in vanilla
        powers = dict(enemies.VANILLA_POWERS)
        powers[icemon.moves[0]] = 130                                    # now slot 0 is the closest
        self.assertEqual(enemies.pick_moves_by_level(icemon, 1, 130, powers), (0x2E, 0xFF, 0xFF, 0xFF))

    def test_metrics_follow_the_table(self) -> None:
        doubled = {tech_id: power * 2 for tech_id, power in enemies.VANILLA_POWERS.items()}
        vanilla = enemies.region_wild_metrics()["Native Forest"].tech_level
        self.assertAlmostEqual(enemies.region_wild_metrics(doubled)["Native Forest"].tech_level, vanilla * 2)


class TestTechniqueOptions(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "technique_data": "randomized",
        "type_effectiveness": True,
        "enemy_stats": "full_random",
    }

    def test_plans(self) -> None:
        plan = self.world.technique_plan
        self.assertTrue(plan.moves)
        self.assertIsNotNone(plan.matrix)
        self.world.post_fill()
        self.assertTrue(self.world.enemy_plan.move_overrides)


class TestTechniqueOptionsShuffle(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "technique_data": "shuffle",
        "technique_effect": False,
        "technique_effect_chance": False,
    }

    def test_plan(self) -> None:
        plan = self.world.technique_plan
        self.assertTrue(plan.moves)
        self.assertTrue(all(techniques.is_learnable(i) for i in plan.moves))
        self.assertIsNone(plan.matrix)


class TestTechniqueOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plan_is_empty(self) -> None:
        self.assertTrue(self.world.technique_plan.empty)
