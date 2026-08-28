"""Digivolution randomization (:mod:`worlds.digimon_world.evolutions`).

Covers the vanilla tables, the tree / requirements / special-evolution planners as pure
functions, the tokens the patcher emits (including the Toy Town gate interplay with
``type_lock_unlocks``), and the option wiring.
"""

from __future__ import annotations

import struct
import unittest
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import evolutions as evo
from .. import rom as rom_module
from ..data.addresses import (
    ROM_EVO_REQUIREMENTS,
    ROM_EVO_STAT_GAINS,
    ROM_EVO_TO_FROM,
    ROM_SPECIAL_EVO,
    ROM_SPECIAL_EVO_TOY_TOWN_GATE_OFFSET,
    iter_user_data_chunks,
)
from .bases import DigimonWorldTestBase


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


def _final_paths(changed: dict[int, evo.EvoPath]) -> dict[int, evo.EvoPath]:
    return {**evo.VANILLA_PATHS, **changed}


class TestVanillaTables(unittest.TestCase):
    def test_paths(self) -> None:
        self.assertEqual(len(evo.VANILLA_PATHS), 62)
        agumon = evo.VANILLA_PATHS[3]
        self.assertEqual(agumon.sources, (2,))                                     # Koromon
        self.assertEqual([evo.SPECIES_NAME[t] for t in agumon.targets],
                         ["Greymon", "Meramon", "Birdramon", "Centarumon", "Monochromon", "Tyrannomon"])
        self.assertEqual(evo.VANILLA_PATHS[evo.DEVIMON].sources, ())              # special-only in vanilla
        self.assertEqual(evo.VANILLA_PATHS[1].targets, (2,))                       # Botamon -> Koromon

    def test_requirements_and_gains(self) -> None:
        self.assertEqual(len(evo.VANILLA_REQUIREMENTS), 63)
        agumon = evo.VANILLA_REQUIREMENTS[3]
        self.assertEqual((agumon.digimon, agumon.stats, agumon.care, agumon.weight), (2, (1, 1, 1, -1, -1, -1), 0, 15))
        self.assertEqual(evo.VANILLA_REQUIREMENTS[evo.DEVIMON], evo.NO_REQUIREMENTS)
        self.assertEqual(len(evo.VANILLA_GAINS), 66)
        self.assertEqual(evo.VANILLA_GAINS[3], (1000, 500, 100, 50, 50, 50))
        self.assertEqual(evo.VANILLA_GAINS[evo.DEVIMON], (0, 0, 0, 0, 0, 10))

    def test_levels(self) -> None:
        self.assertEqual(evo.species_of_level(evo.LEVEL_FRESH), [1, 15, 29, 43])
        self.assertEqual(evo.species_of_level(evo.LEVEL_IN_TRAINING), [2, 16, 30, 44])
        self.assertEqual(len(evo.species_of_level(evo.LEVEL_ROOKIE)), 9)
        self.assertEqual(len(evo.species_of_level(evo.LEVEL_CHAMPION)), 30)
        self.assertEqual(len(evo.species_of_level(evo.LEVEL_CHAMPION, exclude_special=True)), 29)
        self.assertEqual(len(evo.species_of_level(evo.LEVEL_ULTIMATE, exclude_special=True)), 15)
        self.assertNotIn(62, evo.PARTNER_SPECIES_IDS)                              # WereGarurumon, level 0
        self.assertEqual(len(evo.natural_targets(evo.LEVEL_IN_TRAINING, False)), 8)   # 9 Rookies minus Kunemon
        self.assertNotIn(evo.DEVIMON, evo.natural_targets(evo.LEVEL_ROOKIE, False))
        self.assertIn(evo.DEVIMON, evo.natural_targets(evo.LEVEL_ROOKIE, True))


class TestTree(unittest.TestCase):
    def _check_shape(self, paths: dict[int, evo.EvoPath], requirements: bool, obtain_all: bool = False) -> None:
        for species, path in paths.items():
            level = evo.SPECIES_LEVEL[species]
            for target in path.targets:
                self.assertEqual(evo.SPECIES_LEVEL[target], level + 1, (species, target))
                self.assertNotIn(target, evo.NEVER_NATURAL_TARGETS)
                if not requirements:
                    self.assertNotEqual(target, evo.DEVIMON)
            if level in evo.TARGET_COUNTS and species not in evo.SPECIAL_ONLY_SPECIES:
                low, high = evo.TARGET_COUNTS[level]
                self.assertGreaterEqual(len(path.targets), low, (species, path))
                if not obtain_all:      # obtain-all's first pass may hand a source more than the max
                    self.assertLessEqual(len(path.targets), high, (species, path))
            # from lists agree with the to lists (62 = WereGarurumon's chart-only row, kept vanilla)
            if species != 62:
                sources = tuple(s for s in sorted(paths) if species in paths[s].to)
                self.assertEqual(sorted(path.sources), sorted(sources[:5]), species)
        for fresh in evo.species_of_level(evo.LEVEL_FRESH):
            self.assertEqual(paths[fresh], evo.VANILLA_PATHS[fresh])
        self.assertEqual(paths[62], evo.VANILLA_PATHS[62])

    def test_shape(self) -> None:
        for seed in range(5):
            changed = evo.randomize_tree(Random(seed), obtain_all=False, requirements_randomized=False)
            self.assertTrue(changed)
            self._check_shape(_final_paths(changed), requirements=False)

    def test_obtain_all_keeps_every_natural_species_reachable(self) -> None:
        for seed in range(5):
            changed = evo.randomize_tree(Random(seed), obtain_all=True, requirements_randomized=True)
            paths = _final_paths(changed)
            self._check_shape(paths, requirements=True, obtain_all=True)
            for level in (evo.LEVEL_IN_TRAINING, evo.LEVEL_ROOKIE, evo.LEVEL_CHAMPION):
                for target in evo.natural_targets(level, True):
                    self.assertTrue(paths[target].sources, (seed, level, evo.SPECIES_NAME[target]))
            self.assertTrue(paths[evo.DEVIMON].sources)

    def test_deterministic(self) -> None:
        self.assertEqual(evo.randomize_tree(Random(4), True, True), evo.randomize_tree(Random(4), True, True))


class TestRequirements(unittest.TestCase):
    def test_rows(self) -> None:
        paths = _final_paths(evo.randomize_tree(Random(2), obtain_all=True, requirements_randomized=True))
        changed = evo.randomize_requirements(Random(2), paths)
        rows = {**evo.VANILLA_REQUIREMENTS, **changed}
        for species, reqs in rows.items():
            level = evo.SPECIES_LEVEL[species]
            cleared = (species not in evo.PARTNER_SPECIES_IDS or level < evo.LEVEL_ROOKIE
                       or species in evo.NO_REQUIREMENT_SPECIES)
            if cleared:
                self.assertEqual(reqs, evo.NO_REQUIREMENTS, species)
                continue
            self.assertEqual(reqs.flags & ~(evo.FLAG_MAX_BATTLES | evo.FLAG_MAX_CARE), 0)
            self.assertEqual(reqs.happiness, evo.NONE)
            if level == evo.LEVEL_ROOKIE:
                self.assertEqual(sorted(reqs.stats), [-1, -1, -1, 1, 1, 1])
                self.assertEqual((reqs.care, reqs.weight, reqs.battles, reqs.techs, reqs.flags), (0, 15, -2, 0, 0))
                self.assertEqual(reqs.digimon, paths[species].frm[2])
            elif level == evo.LEVEL_CHAMPION:
                self.assertTrue(1 <= sum(v == 100 for v in reqs.stats) <= 4)
                self.assertTrue(0 <= reqs.care <= 6 and 5 <= reqs.weight <= 50 and 10 <= reqs.techs <= 35)
                self.assertTrue(reqs.discipline == -1 or 45 <= reqs.discipline <= 95)
                self.assertTrue(reqs.battles == -1 or 2 <= reqs.battles <= 15)
            else:
                self.assertTrue(4 <= sum(v != -1 for v in reqs.stats) <= 6)
                self.assertTrue(all(v == -1 or 200 <= v <= 700 for v in reqs.stats))
                self.assertTrue(0 <= reqs.care <= 15 and 5 <= reqs.weight <= 70 and 21 <= reqs.techs <= 50)
            if reqs.digimon != evo.NONE:
                self.assertIn(reqs.digimon, paths[species].sources)
        self.assertNotEqual(rows[evo.DEVIMON], evo.NO_REQUIREMENTS)

    def test_stat_requirement_shapes(self) -> None:
        rng = Random(1)
        self.assertEqual(sorted(evo.random_stat_requirements(rng, evo.LEVEL_ROOKIE)), [-1, -1, -1, 1, 1, 1])
        champion = evo.random_stat_requirements(rng, evo.LEVEL_CHAMPION)
        self.assertTrue(all(v in (-1, 100) for v in champion))


class TestSpecialEvolutions(unittest.TestCase):
    def test_results(self) -> None:
        for seed in range(5):
            special = evo.randomize_special_evolutions(Random(seed))
            self.assertEqual(sorted(special), list(range(len(ROM_SPECIAL_EVO))))
            for index, target in special.items():
                _offsets, vanilla, source = ROM_SPECIAL_EVO[index]
                self.assertIn(target, evo.PARTNER_SPECIES_IDS)
                self.assertEqual(evo.SPECIES_LEVEL[target], evo.SPECIES_LEVEL[vanilla])
                self.assertNotIn(target, (vanilla, source))


class TestTokens(unittest.TestCase):
    def test_tokens(self) -> None:
        plan = evo.EvolutionPlan(
            paths={3: evo.EvoPath((-1, -1, 2, -1, -1), (-1, -1, 5, 9, -1, -1)),
                   37: evo.EvoPath((-1, -1, 3, -1, -1), (-1, -1, 12, -1, -1, -1))},
            requirements={5: evo.EvoRequirements(3, 100, -1, 100, -1, -1, -1, 3, 25, -1, -1, -1, 20, 0x10)},
            gains={evo.DEVIMON: evo.DEVIMON_GAINS},
            special={0: 27, 3: 24},
        )
        patch = _TokenCollector()
        rom_module._write_evolution_tokens(patch, plan, type_lock_unlocks=False)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        self.assertEqual(tokens[ROM_EVO_TO_FROM.offset + 2 * 11],
                         struct.pack("<11b", -1, -1, 2, -1, -1, -1, -1, 5, 9, -1, -1))
        # Bakemon's row (37) straddles the block's sector boundary: two tokens
        bakemon = list(iter_user_data_chunks(ROM_EVO_TO_FROM.offset, 36 * 11, bytes(11)))
        self.assertEqual(len(bakemon), 2)
        self.assertEqual(b"".join(tokens[off] for off, _ in bakemon),
                         struct.pack("<11b", -1, -1, 3, -1, -1, -1, -1, 12, -1, -1, -1))
        self.assertEqual(tokens[ROM_EVO_REQUIREMENTS.offset + 5 * 28],
                         struct.pack("<13hb", 3, 100, -1, 100, -1, -1, -1, 3, 25, -1, -1, -1, 20, 0x10))
        self.assertEqual(tokens[ROM_EVO_STAT_GAINS.offset + 6 * 14], struct.pack("<6h", *evo.DEVIMON_GAINS))
        for offset in ROM_SPECIAL_EVO[0][0]:
            self.assertEqual(tokens[offset], bytes([27]))
        self.assertEqual(tokens[ROM_SPECIAL_EVO[3][0][0]], bytes([24]))

    def test_toy_town_gate_is_left_to_the_unlock(self) -> None:
        plan = evo.EvolutionPlan({}, {}, {}, {0: 27})
        patch = _TokenCollector()
        rom_module._write_evolution_tokens(patch, plan, type_lock_unlocks=True)  # type: ignore[arg-type]
        offsets = [off for off, _ in patch.tokens]
        self.assertNotIn(ROM_SPECIAL_EVO_TOY_TOWN_GATE_OFFSET, offsets)
        self.assertEqual(len(offsets), len(ROM_SPECIAL_EVO[0][0]) - 1)

    def test_no_tokens_for_the_empty_plan(self) -> None:
        patch = _TokenCollector()
        rom_module._write_evolution_tokens(patch, evo.EMPTY_PLAN, type_lock_unlocks=True)  # type: ignore[arg-type]
        self.assertEqual(patch.tokens, [])


class TestDigivolutionOptions(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "digivolution_randomization": True,
        "digivolution_obtain_all": True,
        "digivolution_requirements": True,
        "special_digivolutions": True,
    }

    def test_plan(self) -> None:
        plan = self.world.evolution_plan
        self.assertTrue(plan.paths and plan.requirements and plan.special)
        self.assertEqual(plan.gains, {evo.DEVIMON: evo.DEVIMON_GAINS})


class TestDigivolutionTreeOnly(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"digivolution_randomization": True}

    def test_plan(self) -> None:
        plan = self.world.evolution_plan
        self.assertTrue(plan.paths)
        self.assertFalse(plan.requirements or plan.special or plan.gains)
        for path in plan.paths.values():
            self.assertNotIn(evo.DEVIMON, path.targets)


class TestDigivolutionOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"digivolution_requirements": True, "special_digivolutions": True}

    def test_sub_options_need_the_master(self) -> None:
        self.assertTrue(self.world.evolution_plan.empty)
