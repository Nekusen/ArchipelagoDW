"""Enemy stat scaling and species randomization (:mod:`worlds.digimon_world.enemies`).

Covers the generated data table's integrity, the screen -> region map, the two planners as
pure functions, and the tokens the patcher emits for a plan. The disc-level behaviour behind
these tables was lab-validated on 2026-08-28 (see ``tools/PATCH_PROCESS.md``).
"""

from __future__ import annotations

import struct
import unittest
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import enemies
from .. import rom as rom_module
from ..data.addresses import (
    FIELD_RECORD_HP,
    FIELD_RECORD_MOVES,
    FIELD_RECORD_TYPE,
    MAPHEAD_OP_LOAD_DIGIMON,
    MAPHEAD_OP_SET_DIGIMON,
    MAPHEAD_SCN_SIZE,
    NPC_MODEL_SLOTS,
    field_record_bin_offset,
    maphead_bin_offset,
)
from ..regions import REGION_NAMES
from .bases import DigimonWorldTestBase


class TestEnemyRecordTable(unittest.TestCase):
    def test_table_sizes(self) -> None:
        self.assertEqual(len(enemies.RECORDS), 989)
        self.assertEqual(len(enemies.SPECIES_BY_ID), 180)
        self.assertEqual(len(enemies.SITES), 1177)

    def test_records_are_unique_and_ordered_on_disc(self) -> None:
        keys = [(r.map, r.slot) for r in enemies.RECORDS]
        self.assertEqual(len(keys), len(set(keys)))
        for records in enemies.RECORDS_BY_MAP.values():
            offsets = [r.bin_off for r in records]
            self.assertEqual(offsets, sorted(offsets))
            self.assertEqual([r.slot for r in records], list(range(len(records))))

    def test_randomizer_gabumon_anchor(self) -> None:
        """meekrhino's documented MIST06 Gabumon stat anchor (0x0A7EEA8C) is our record's HP word."""
        record = next(r for r in enemies.RECORDS_BY_MAP[120] if r.bin_off == 0x0A7EEA76)
        self.assertEqual(enemies.SPECIES_BY_ID[record.type].name, "Gabumon")
        self.assertEqual(field_record_bin_offset(record.bin_off, FIELD_RECORD_HP), 0x0A7EEA8C)

    def test_maphead_sites_agree_with_records(self) -> None:
        for site in enemies.SITES:
            self.assertIn(site.kind, (0, 1))
            self.assertLess(site.file_off + 3, MAPHEAD_SCN_SIZE)
            types = {r.type for r in enemies.RECORDS_BY_MAP[site.map]}
            self.assertIn(site.species, types, site)
            if site.kind == 1:
                self.assertEqual(enemies.RECORD_INDEX[(site.map, site.slot)].type, site.species, site)
            else:
                self.assertEqual(site.slot, -1)
        # every species that gets placed on a screen is also loaded there
        for map_id, sites in enemies.SITES_BY_MAP.items():
            loaded = {s.species for s in sites if s.kind == 0}
            placed = {s.species for s in sites if s.kind == 1}
            self.assertTrue(placed <= loaded, (map_id, placed - loaded))

    def test_species_views(self) -> None:
        icemon = enemies.SPECIES_BY_ID[94]
        self.assertEqual(icemon.name, "Icemon")
        self.assertEqual(icemon.tech_slots, (0, 1, 2))
        self.assertTrue(icemon.fights)
        self.assertFalse(enemies.SPECIES_BY_ID[134].fights)   # the ferry Seadramon clone
        self.assertFalse(enemies.SPECIES_BY_ID[0].fights)     # "main character"
        self.assertEqual(enemies.SPECIES_BY_ID[80].heap, 57344)

    def test_no_screen_loads_more_than_the_model_slots(self) -> None:
        """A screen never loads more distinct species than NPC_MODEL has slots on any one
        MAPHEAD branch; the table itself lists up to 8 species, so only the branch-free
        screens can be checked statically — every screen with <= 5 species trivially passes and
        the others rely on the vanilla script branching, which substitution never changes."""
        for map_id, records in enemies.RECORDS_BY_MAP.items():
            if len({r.type for r in records}) <= NPC_MODEL_SLOTS:
                continue
            self.assertGreater(len(records), NPC_MODEL_SLOTS, map_id)

    def test_maphead_offsets(self) -> None:
        self.assertEqual(maphead_bin_offset(0), 142982 * 2352 + 24)
        self.assertEqual(maphead_bin_offset(2048), 142983 * 2352 + 24)
        self.assertEqual(MAPHEAD_OP_LOAD_DIGIMON, 0x46)
        self.assertEqual(MAPHEAD_OP_SET_DIGIMON, 0x47)


class TestClassificationAndRegions(unittest.TestCase):
    def test_every_fighting_record_has_a_region(self) -> None:
        unmapped = sorted({
            r.map for r in enemies.RECORDS
            if enemies.classify_record(r) != enemies.CLASS_NPC
            and r.map not in enemies.EXCLUDED_SCREENS
            and enemies.screen_region(r.map) is None
        })
        self.assertEqual(unmapped, [])

    def test_regions_exist(self) -> None:
        for map_id in enemies.RECORDS_BY_MAP:
            region = enemies.screen_region(map_id)
            if region is not None:
                self.assertIn(region, REGION_NAMES, (map_id, region))

    def test_classes(self) -> None:
        by_name = {
            (r.map, enemies.SPECIES_BY_ID[r.type].name): enemies.classify_record(r) for r in enemies.RECORDS
        }
        self.assertEqual(by_name[(2, "Goburimon")], enemies.CLASS_WILD)
        self.assertEqual(by_name[(2, "Palmon")], enemies.CLASS_STORY)      # recruit fight (clone id 164)
        self.assertEqual(by_name[(6, "Seadramon")], enemies.CLASS_NPC)     # ferry clone, no techniques
        self.assertEqual(by_name[(1, "Kunemon")], enemies.CLASS_STORY)     # recruit fight (clone id 152)
        self.assertEqual(by_name[(5, "Coelamon")], enemies.CLASS_STORY)    # recruit id
        self.assertEqual(by_name[(225, "Machinedramon")], enemies.CLASS_STORY)
        counts = dict.fromkeys((enemies.CLASS_WILD, enemies.CLASS_STORY, enemies.CLASS_NPC), 0)
        for record in enemies.RECORDS:
            counts[enemies.classify_record(record)] += 1
        # 548 fighting records carry a species id below the clone range and outside the
        # recruit set (the census figure); the explicit story bosses come off that number.
        boss_records = sum(1 for r in enemies.RECORDS if r.type in enemies.STORY_BOSS_SPECIES)
        self.assertGreater(boss_records, 0)
        self.assertEqual(counts[enemies.CLASS_WILD], 548 - boss_records)
        self.assertEqual(counts[enemies.CLASS_NPC], 175)

    def test_wild_budgets_cover_the_main_regions(self) -> None:
        budgets = enemies.region_wild_budgets()
        for region in ("Native Forest", "Great Canyon", "Freezeland", "Mt. Infinity", "Toy Town"):
            self.assertIn(region, budgets)
        self.assertLess(budgets["Native Forest"], budgets["Mt. Infinity"])


class TestScalingPlanner(unittest.TestCase):
    def test_depth_order_receives_vanilla_budget_order(self) -> None:
        budgets = enemies.region_wild_budgets()
        # Mt. Infinity opened first and Native Forest last: they swap difficulty.
        depths = dict.fromkeys(budgets, 0)
        depths["Mt. Infinity"] = 0
        depths["Native Forest"] = 99
        for region in budgets:
            if region not in ("Mt. Infinity", "Native Forest"):
                depths[region] = 50
        factors = enemies.plan_region_factors(depths, 100)
        self.assertLess(factors["Mt. Infinity"], 1.0)
        self.assertGreater(factors["Native Forest"], 1.0)
        # the strongest vanilla budget went to the deepest region
        self.assertAlmostEqual(
            factors["Native Forest"] * budgets["Native Forest"], max(budgets.values()), places=6,
        )

    def test_vanilla_order_is_identity(self) -> None:
        budgets = enemies.region_wild_budgets()
        depths = {region: rank for rank, region in enumerate(sorted(budgets, key=budgets.get))}
        factors = enemies.plan_region_factors(depths, 100)
        for region, factor in factors.items():
            self.assertAlmostEqual(factor, 1.0, places=9, msg=region)
        self.assertEqual(enemies.plan_stat_overrides(factors), {})

    def test_strength_blends_and_clamps(self) -> None:
        budgets = enemies.region_wild_budgets()
        depths = {region: rank for rank, region in enumerate(sorted(budgets, key=budgets.get, reverse=True))}
        full = enemies.plan_region_factors(depths, 100)
        half = enemies.plan_region_factors(depths, 50)
        for region in full:
            self.assertGreaterEqual(full[region], enemies.SCALE_FACTOR_MIN)
            self.assertLessEqual(full[region], enemies.SCALE_FACTOR_MAX)
            # half strength sits between vanilla and the full factor, on the same side of 1.0
            self.assertGreaterEqual((half[region] - 1.0) * (full[region] - 1.0), 0.0)
            self.assertLessEqual(abs(half[region] - 1.0), abs(full[region] - 1.0))
            if enemies.SCALE_FACTOR_MIN < full[region] < enemies.SCALE_FACTOR_MAX:
                self.assertAlmostEqual(half[region], 1.0 + (full[region] - 1.0) / 2, places=9)
        self.assertEqual(enemies.plan_region_factors(depths, 0), {})

    def test_stat_overrides_scale_every_fighter_of_the_region(self) -> None:
        overrides = enemies.plan_stat_overrides({"Native Forest": 2.0})
        goburimon = enemies.RECORD_INDEX[(2, 0)]
        self.assertEqual(overrides[(2, 0)], (800, 1600, 800, 1600, 320, 140, 100, 100, 600))
        self.assertEqual(goburimon.stats, (400, 800, 400, 800, 160, 70, 50, 50, 300))
        self.assertIn((3, 0), overrides)          # Etemon (story) scales with its screen
        self.assertIn((2, 2), overrides)          # Palmon recruit fight scales too
        self.assertNotIn((6, 0), overrides)       # the ferry Seadramon NPC is untouched
        self.assertNotIn((109, 0), overrides)     # intro screen excluded
        self.assertTrue(all(r.map in enemies.RECORDS_BY_MAP for (r, _) in
                            ((enemies.RECORD_INDEX[k], v) for k, v in overrides.items())))
        for key in overrides:
            self.assertEqual(enemies.screen_region(key[0]), "Native Forest")

    def test_scale_stats_caps(self) -> None:
        record = enemies.RECORD_INDEX[(3, 0)]      # Etemon 5600 hp
        scaled = enemies.scale_stats(record, 5.0)
        self.assertEqual(scaled[0], 9999)
        self.assertEqual(scaled[4], 999)
        self.assertLessEqual(scaled[2], scaled[0])
        low = enemies.scale_stats(record, 0.0001)
        self.assertEqual(low[:8], (1,) * 8)


class TestSubstitutionPlanner(unittest.TestCase):
    def test_pool_respects_heap_and_level(self) -> None:
        goburimon = enemies.SPECIES_BY_ID[80]
        pool = enemies.substitute_pool(goburimon, same_level=True)
        self.assertTrue(pool)
        for species in pool:
            self.assertLessEqual(species.heap, goburimon.heap)
            self.assertEqual(species.level, goburimon.level)
            self.assertTrue(species.fights)
            self.assertNotIn(species.id, enemies.RECRUIT_SPECIES_IDS)
            self.assertNotIn(species.id, enemies.STORY_BOSS_SPECIES)
            self.assertLess(species.id, enemies.CLONE_SPECIES_BASE)
        self.assertGreater(len(enemies.substitute_pool(goburimon, same_level=False)), len(pool))

    def test_wild_mode_never_touches_story_or_npc(self) -> None:
        substitutions, moves = enemies.plan_substitutions(Random(1), include_story=False, same_level=True)
        self.assertTrue(substitutions)
        for (map_id, species), substitute in substitutions.items():
            self.assertNotEqual(species, substitute)
            for record in enemies.RECORDS_BY_MAP[map_id]:
                if record.type == species:
                    self.assertEqual(enemies.classify_record(record), enemies.CLASS_WILD)
                    self.assertIn((record.map, record.slot), moves)
            self.assertNotIn(map_id, enemies.EXCLUDED_SCREENS)
        self.assertNotIn((225, 115), substitutions)   # Machinedramon
        self.assertNotIn((1, 152), substitutions)     # Kunemon recruit fight
        self.assertIn((2, 80), substitutions)         # MAYO03 Goburimon

    def test_story_mode_swaps_bosses_but_keeps_stats(self) -> None:
        substitutions, _ = enemies.plan_substitutions(Random(2), include_story=True, same_level=False)
        self.assertIn((1, 152), substitutions)
        self.assertIn((225, 115), substitutions)
        # stats live in stat_overrides only; substitution never writes them
        plan = enemies.EnemyPlan({}, substitutions, {}, {}, {})
        self.assertEqual(plan.stat_overrides, {})

    def test_movesets_come_from_the_substitute(self) -> None:
        rng = Random(3)
        substitutions, moves = enemies.plan_substitutions(rng, include_story=False, same_level=True)
        for (map_id, slot), (new_moves, prio) in moves.items():
            record = enemies.RECORD_INDEX[(map_id, slot)]
            substitute = enemies.SPECIES_BY_ID[substitutions[(map_id, record.type)]]
            self.assertEqual(prio, record.prio)
            self.assertEqual(len(new_moves), 4)
            used = [m for m in new_moves if m != enemies.NO_MOVE]
            self.assertTrue(used)
            self.assertEqual(len(used), len(set(used)))
            for move in used:
                self.assertIn(move - enemies.ANIM_MOVE_BASE, substitute.tech_slots)
            wanted = min(sum(1 for m in record.moves if m != enemies.NO_MOVE), len(substitute.tech_slots))
            self.assertEqual(len(used), max(1, wanted))

    def test_deterministic(self) -> None:
        a = enemies.plan_substitutions(Random(42), include_story=False, same_level=True)
        b = enemies.plan_substitutions(Random(42), include_story=False, same_level=True)
        self.assertEqual(a, b)


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestEnemyTokens(unittest.TestCase):
    def test_tokens_for_a_plan(self) -> None:
        goburimon = enemies.RECORD_INDEX[(2, 0)]
        plan = enemies.EnemyPlan(
            stat_overrides={(2, 0): (1234, 77, 1234, 77, 222, 33, 44, 55, 999)},
            substitutions={(0, 83): 94},
            move_overrides={(0, 0): ((0x2E, 0x2F, 0x30, 0xFF), (40, 30, 30, 0))},
            region_depths={}, region_factors={},
        )
        patch = _TokenCollector()
        rom_module._write_enemy_tokens(patch, plan)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        # the nine stat words, contiguous inside one sector -> one token (the lab PoC's exact bytes)
        self.assertEqual(
            tokens[field_record_bin_offset(goburimon.bin_off, FIELD_RECORD_HP)],
            struct.pack("<9h", 1234, 77, 1234, 77, 222, 33, 44, 55, 999),
        )
        self.assertEqual(
            tokens[field_record_bin_offset(0x1420C5C, FIELD_RECORD_MOVES)],
            struct.pack("<8h", 0x2E, 0x2F, 0x30, 0xFF, 40, 30, 30, 0),
        )
        # every ModokiBetamon record on MAYO01 becomes Icemon ...
        for record in enemies.RECORDS_BY_MAP[0]:
            if record.type == 83:
                self.assertEqual(tokens[field_record_bin_offset(record.bin_off, FIELD_RECORD_TYPE)],
                                 struct.pack("<h", 94))
        # ... and so do the MAPHEAD operands: loadDigimon @1158, setDigimon @1162/1166/1178
        for vm in (1158, 1162, 1166, 1178):
            self.assertEqual(tokens[maphead_bin_offset(vm + 1)], bytes([94]))
        self.assertNotIn(maphead_bin_offset(1186 + 1), tokens)   # the Dokunemon branch is untouched

    def test_word_runs_split_at_sector_boundaries(self) -> None:
        patch = _TokenCollector()
        # find a record whose stat words straddle a user-data boundary, if any; otherwise
        # verify the merge produces exactly one token for a plain record
        straddling = [
            r for r in enemies.RECORDS
            if field_record_bin_offset(r.bin_off, FIELD_RECORD_HP + 8)
            != field_record_bin_offset(r.bin_off, FIELD_RECORD_HP) + 16
        ]
        target = straddling[0] if straddling else enemies.RECORDS[0]
        rom_module._write_field_record_words(patch, target.bin_off, FIELD_RECORD_HP, target.stats)  # type: ignore[arg-type]
        self.assertEqual(len(patch.tokens), 2 if straddling else 1)
        joined = b"".join(data for _, data in patch.tokens)
        self.assertEqual(joined, struct.pack("<9h", *target.stats))
        for offset, data in patch.tokens:
            # a token never crosses the 2048-byte user-data window of its sector
            start = (offset - 24) % 2352
            self.assertLessEqual(start + len(data), 2048)


class TestEnemyOptionsThroughGeneration(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "enemy_scaling": "vanilla_curve",
        "enemy_randomization": "wild",
    }

    def test_plan_is_built_after_fill(self) -> None:
        from Fill import distribute_items_restrictive
        distribute_items_restrictive(self.multiworld)
        self.world.post_fill()
        plan = self.world.enemy_plan
        self.assertFalse(plan.empty)
        self.assertIn("Native Forest", plan.region_depths)
        self.assertEqual(plan.region_depths["File City"], 0)
        self.assertTrue(plan.substitutions)
        self.assertTrue(plan.region_factors)


class TestEnemyOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plan_is_empty(self) -> None:
        self.world.post_fill()
        self.assertTrue(self.world.enemy_plan.empty)
