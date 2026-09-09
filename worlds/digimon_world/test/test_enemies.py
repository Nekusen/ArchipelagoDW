"""Enemy stats / techniques / species randomization (:mod:`worlds.digimon_world.enemies`).

Covers the generated data table's integrity, the screen -> region map, the three planners as
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


def _powers(species: enemies.Species, moves: tuple[int, ...]) -> list[int]:
    return sorted(species.slot_power(m - enemies.ANIM_MOVE_BASE) for m in moves if m != enemies.NO_MOVE)


class TestEnemyRecordTable(unittest.TestCase):
    def test_table_sizes(self) -> None:
        self.assertEqual(len(enemies.RECORDS), 989)
        self.assertEqual(len(enemies.SPECIES_BY_ID), 180)
        self.assertEqual(len(enemies.SITES), 1177)
        self.assertEqual(len(enemies.MOVES_BY_ID), 122)

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

    def test_species_and_move_views(self) -> None:
        icemon = enemies.SPECIES_BY_ID[94]
        self.assertEqual(icemon.name, "Icemon")
        self.assertEqual(icemon.tech_slots, (0, 1, 2))
        self.assertEqual(icemon.damaging_slots, (0, 1, 2))
        self.assertEqual([icemon.slot_power(k) for k in icemon.tech_slots], [320, 264, 126])
        self.assertTrue(icemon.fights)
        self.assertFalse(enemies.SPECIES_BY_ID[134].fights)   # the ferry Seadramon clone
        self.assertFalse(enemies.SPECIES_BY_ID[0].fights)     # "main character"
        self.assertEqual(enemies.SPECIES_BY_ID[80].heap, 57344)
        goburimon = enemies.SPECIES_BY_ID[80]
        self.assertIn(4, goburimon.tech_slots)                # War Cry, a buff ...
        self.assertNotIn(4, goburimon.damaging_slots)         # ... has power 0
        spit_fire = enemies.MOVES_BY_ID[2]
        self.assertEqual(spit_fire[:6], (2, "Spit Fire", 66, 10, 0, 0))
        self.assertEqual((spit_fire.accuracy, spit_fire.status_chance, spit_fire.range), (43, 0, 2))
        self.assertEqual((goburimon.drop_item, goburimon.drop_chance), (38, 30))   # Meat, 30 %
        self.assertEqual(enemies.MOVES_BY_ID[0x2D].name, "Counter")
        self.assertEqual(enemies.RECORD_INDEX[(2, 0)].tech_powers(), (66, 279, 52))
        self.assertEqual(enemies.RECORD_INDEX[(49, 1)].move_count, 0)   # Monochromon's shop customer

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

    def test_wild_metrics_cover_the_main_regions(self) -> None:
        metrics = enemies.region_wild_metrics()
        for region in ("Native Forest", "Great Canyon", "Freezeland", "Mt. Infinity", "Toy Town"):
            self.assertIn(region, metrics)
            self.assertIsNotNone(metrics[region].tech_level)
        self.assertLess(metrics["Native Forest"].budget, metrics["Mt. Infinity"].budget)
        self.assertLess(metrics["Native Forest"].tech_level, metrics["Mt. Infinity"].tech_level)
        self.assertIn(2, enemies.screen_wild_metrics())
        self.assertNotIn(109, enemies.screen_wild_metrics())
        # File City's strolling babies are decoration: never a metric, never a target
        self.assertNotIn("File City", metrics)
        self.assertNotIn(180, enemies.screen_wild_metrics())
        targets = enemies.plan_full_random_targets(Random(1))
        self.assertFalse({m for m in targets if enemies.screen_region(m) == "File City"})
        substitutions, _ = enemies.plan_substitutions(Random(1), include_story=True, same_level=False)
        self.assertFalse({m for m, _ in substitutions if enemies.screen_region(m) == "File City"})


class TestProgressivePlanner(unittest.TestCase):
    def test_depth_order_receives_vanilla_difficulty_order(self) -> None:
        metrics = enemies.region_wild_metrics()
        # Mt. Infinity opened first and Native Forest last: they swap difficulty.
        depths = dict.fromkeys(metrics, 50)
        depths["Mt. Infinity"] = 0
        depths["Native Forest"] = 99
        targets = enemies.plan_region_targets(depths, 100)
        self.assertLess(targets["Mt. Infinity"].stat_factor, 1.0)
        self.assertGreater(targets["Native Forest"].stat_factor, 1.0)
        self.assertAlmostEqual(
            targets["Native Forest"].stat_factor * metrics["Native Forest"].budget,
            max(m.budget for m in metrics.values()), places=6,
        )
        # technique power follows the same re-assignment
        self.assertGreater(targets["Native Forest"].tech_level, metrics["Native Forest"].tech_level)
        self.assertLess(targets["Mt. Infinity"].tech_level, metrics["Mt. Infinity"].tech_level)

    def test_vanilla_order_is_identity(self) -> None:
        metrics = enemies.region_wild_metrics()
        depths = {region: rank for rank, region in enumerate(sorted(metrics, key=lambda r: metrics[r].budget))}
        targets = enemies.plan_region_targets(depths, 100)
        for region, target in targets.items():
            self.assertAlmostEqual(target.stat_factor, 1.0, places=9, msg=region)
        self.assertEqual(enemies.plan_stat_overrides(enemies.screen_targets_from_regions(targets)), {})

    def test_strength_blends_and_clamps(self) -> None:
        metrics = enemies.region_wild_metrics()
        order = sorted(metrics, key=lambda r: metrics[r].budget, reverse=True)
        depths = {region: rank for rank, region in enumerate(order)}
        full = enemies.plan_region_targets(depths, 100)
        half = enemies.plan_region_targets(depths, 50)
        for region in full:
            f, h = full[region].stat_factor, half[region].stat_factor
            self.assertGreaterEqual(f, enemies.SCALE_FACTOR_MIN)
            self.assertLessEqual(f, enemies.SCALE_FACTOR_MAX)
            self.assertGreaterEqual((h - 1.0) * (f - 1.0), 0.0)
            self.assertLessEqual(abs(h - 1.0), abs(f - 1.0))
            if enemies.SCALE_FACTOR_MIN < f < enemies.SCALE_FACTOR_MAX:
                self.assertAlmostEqual(h, 1.0 + (f - 1.0) / 2, places=9)
        self.assertEqual(enemies.plan_region_targets(depths, 0), {})

    def test_stat_overrides_scale_every_fighter_of_the_region(self) -> None:
        targets = enemies.screen_targets_from_regions({"Native Forest": enemies.Targets(2.0, None)})
        overrides = enemies.plan_stat_overrides(targets)
        goburimon = enemies.RECORD_INDEX[(2, 0)]
        self.assertEqual(overrides[(2, 0)], (800, 1600, 800, 1600, 320, 140, 100, 100, 600))
        self.assertEqual(goburimon.stats, (400, 800, 400, 800, 160, 70, 50, 50, 300))
        self.assertIn((3, 0), overrides)          # Etemon (story) scales with its screen
        self.assertIn((2, 2), overrides)          # Palmon recruit fight scales too
        self.assertNotIn((6, 0), overrides)       # the ferry Seadramon NPC is untouched
        self.assertNotIn((109, 0), overrides)     # intro screen excluded
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

    def test_moves_track_the_target_power(self) -> None:
        rockmon = enemies.SPECIES_BY_ID[108]      # Sonic Jab 52 .. Aurora Freeze 430
        weak = enemies.pick_moves_by_level(rockmon, 3, 60.0)
        strong = enemies.pick_moves_by_level(rockmon, 3, 450.0)
        self.assertLess(sum(_powers(rockmon, weak)), sum(_powers(rockmon, strong)))
        self.assertEqual(len(_powers(rockmon, weak)), 3)
        self.assertNotIn(0, _powers(rockmon, strong))       # damaging techniques first
        self.assertEqual(enemies.pick_moves_by_level(rockmon, 3, 60.0), weak)   # deterministic
        # Mt. Infinity fodder brought down to Native Forest power
        targets = {166: enemies.Targets(1.0, 60.0)}
        overrides = enemies.plan_move_overrides(enemies.STATS_PROGRESSIVE, Random(0), {}, targets)
        self.assertTrue(overrides)
        for (map_id, slot), (moves, prio) in overrides.items():
            record = enemies.RECORD_INDEX[(map_id, slot)]
            self.assertEqual(map_id, 166)
            self.assertEqual(prio, record.prio)
            self.assertEqual(sum(1 for m in moves if m != enemies.NO_MOVE), record.move_count)
            self.assertLess(sum(_powers(enemies.SPECIES_BY_ID[record.type], moves)),
                            sum(record.tech_powers()) + 1)


class TestFullRandomPlanner(unittest.TestCase):
    def test_targets_stay_inside_vanilla(self) -> None:
        metrics = enemies.screen_wild_metrics()
        budgets = [m.budget for m in metrics.values()]
        targets = enemies.plan_full_random_targets(Random(5))
        self.assertEqual(set(targets), set(metrics))
        for map_id, target in targets.items():
            borrowed = target.stat_factor * metrics[map_id].budget
            self.assertGreaterEqual(borrowed, min(budgets) * 0.999)
            self.assertLessEqual(borrowed, max(budgets) * 1.001)
        self.assertEqual(targets, enemies.plan_full_random_targets(Random(5)))
        self.assertNotEqual(targets, enemies.plan_full_random_targets(Random(6)))

    def test_random_moves_come_from_the_list(self) -> None:
        targets = enemies.plan_full_random_targets(Random(7))
        overrides = enemies.plan_move_overrides(enemies.STATS_FULL_RANDOM, Random(7), {}, targets)
        self.assertTrue(overrides)
        for (map_id, slot), (moves, prio) in overrides.items():
            record = enemies.RECORD_INDEX[(map_id, slot)]
            species = enemies.SPECIES_BY_ID[record.type]
            used = [m - enemies.ANIM_MOVE_BASE for m in moves if m != enemies.NO_MOVE]
            self.assertEqual(len(used), len(set(used)))
            for k in used:
                self.assertIn(k, species.tech_slots)
            self.assertEqual(prio, record.prio)


class TestSubstitutionPlanner(unittest.TestCase):
    def test_pool_is_one_row_per_identity_and_excludes_nothing_else(self) -> None:
        goburimon = enemies.SPECIES_BY_ID[80]
        pool = enemies.substitute_pool(goburimon, same_level=True)
        self.assertTrue(pool)
        names = [species.name for species in pool]
        self.assertCountEqual(names, set(names), "an identity must appear at most once")
        for species in pool:
            self.assertEqual(species.level, goburimon.level)
            self.assertTrue(species.fights)
        # rolling what was already there is a legitimate outcome, so it is in the pool ...
        self.assertIn(goburimon.name, names)
        self.assertGreater(len(enemies.substitute_pool(goburimon, same_level=False)), len(pool))

    def test_drawing_the_original_identity_leaves_the_vanilla_row(self) -> None:
        """... and resolves to "keep vanilla", never to the identity's other row."""
        for seed in range(12):
            substitutions, final = enemies.plan_substitutions(
                Random(seed), include_story=True, same_level=bool(seed % 2))
            for (map_id, original), substitute in substitutions.items():
                self.assertNotEqual(enemies.SPECIES_BY_ID[original].name,
                                    enemies.SPECIES_BY_ID[substitute].name,
                                    (map_id, original, substitute))
            for (map_id, slot), species_id in final.items():
                self.assertNotEqual(species_id, enemies.RECORD_INDEX[(map_id, slot)].type)

    def test_pool_holds_no_identity_back(self) -> None:
        """Recruit target, story boss and town clone describe a record, not a species."""
        candidates = {species.name for species in enemies.SUBSTITUTE_CANDIDATES}
        for name in ("Mamemon", "Andromon", "Piximon",          # recruit targets
                     "Machinedramon", "WaruSeadramon", "WaruMonzaemon"):   # story bosses
            self.assertIn(name, candidates)
        every_fighting_identity = {
            species.name for species in enemies.SPECIES_BY_ID.values()
            if species.fights and species.level
        }
        self.assertEqual(candidates, every_fighting_identity)

    def test_representative_is_a_row_the_game_fights_with(self) -> None:
        """Never a town / quest clone: only vanilla-battled rows have proven animations."""
        by_id = {species.id: species for species in enemies.SUBSTITUTE_CANDIDATES}
        for species in enemies.SUBSTITUTE_CANDIDATES:
            self.assertLess(species.id, enemies.CLONE_SPECIES_BASE, species)
        # the recruit rows win over their lighter town clones ...
        for full, clone in ((55, 173), (48, 166), (51, 169), (5, 129), (22, 144)):
            self.assertIn(full, by_id)
            self.assertNotIn(clone, by_id)
        # ... and the clone measured to hard-fault in battle is excluded twice over.
        for species_id in enemies.ANIM_TABLE_UNSAFE:
            self.assertNotIn(species_id, by_id)

    def test_representative_is_the_cheapest_qualifying_row(self) -> None:
        by_name: dict[str, list[Any]] = {}
        for species in enemies.SPECIES_BY_ID.values():
            if species.level:
                by_name.setdefault(species.name, []).append(species)
        for species in enemies.SUBSTITUTE_CANDIDATES:
            qualifying = [other for other in by_name[species.name]
                          if other.fights and other.id < enemies.CLONE_SPECIES_BASE
                          and other.id not in enemies.ANIM_TABLE_UNSAFE]
            self.assertEqual(species.heap, min(other.heap for other in qualifying), species)

    def test_substitutions_stay_inside_the_screen_budget(self) -> None:
        """Over-budget is a hard crash, so no plan may ever exceed a screen's arena."""
        for seed in range(8):
            with self.subTest(seed=seed):
                substitutions, _ = enemies.plan_substitutions(
                    Random(seed), include_story=True, same_level=bool(seed % 2))
                per_screen: dict[int, dict[int, int]] = {}
                for (map_id, original), substitute in substitutions.items():
                    per_screen.setdefault(map_id, {})[original] = substitute
                for map_id, chosen in per_screen.items():
                    self.assertLessEqual(enemies.screen_peak(map_id, chosen),
                                         enemies.screen_budget(map_id))

    def test_every_candidate_is_admissible_somewhere(self) -> None:
        """Exact form of "nothing is unreachable": no sampling, every screen and group.

        A candidate that no (screen, group) can ever admit is dead weight in the pool and a
        sign the budget data has drifted. The only identities allowed to be unreachable are
        the ones no *original* group can call for -- see the two tests below.
        """
        screens = [map_id for map_id in sorted(enemies.RECORDS_BY_MAP)
                   if enemies._combat_screen(map_id) and map_id in enemies.SITES_BY_MAP
                   and map_id in enemies.SCREEN_TRACES]
        self.assertTrue(screens)
        for same_level in (False, True):
            with self.subTest(same_level=same_level):
                admissible: set[str] = set()
                for map_id in screens:
                    budget = enemies.screen_budget(map_id)
                    for group in enemies._substitutable_groups(map_id, True):
                        pool = enemies.substitute_pool(enemies.SPECIES_BY_ID[group], same_level)
                        admissible |= {
                            candidate.name for candidate in pool
                            if candidate.name not in admissible
                            and enemies.screen_peak(map_id, {group: candidate.id}) <= budget
                        }
                expected = {species.name for species in enemies.SUBSTITUTE_CANDIDATES}
                if same_level:
                    # nothing to replace at Fresh / In-Training: no wild group is either level
                    expected = {name for name in expected
                                if enemies.SPECIES_BY_ID[
                                    next(s.id for s in enemies.SUBSTITUTE_CANDIDATES
                                         if s.name == name)].level >= 3}
                self.assertEqual(admissible, expected)

    def test_every_identity_can_appear(self) -> None:
        """The point of the budget model: nothing is unreachable for want of arena."""
        seen: set[str] = set()
        for seed in range(20):
            substitutions, _ = enemies.plan_substitutions(
                Random(seed), include_story=True, same_level=False)
            seen |= {enemies.SPECIES_BY_ID[s].name for s in substitutions.values()}
        self.assertEqual(seen, {species.name for species in enemies.SUBSTITUTE_CANDIDATES})

    def test_same_level_reaches_every_identity_of_every_level_in_play(self) -> None:
        """Fresh / In-Training never appear because no *original* group is one."""
        seen: set[str] = set()
        for seed in range(20):
            substitutions, _ = enemies.plan_substitutions(
                Random(seed), include_story=True, same_level=True)
            seen |= {enemies.SPECIES_BY_ID[s].name for s in substitutions.values()}
        planned, _ = enemies.plan_substitutions(Random(0), include_story=True, same_level=True)
        levels_in_play = {enemies.SPECIES_BY_ID[original].level for _, original in planned}
        self.assertEqual(levels_in_play, {3, 4, 5})
        self.assertEqual(seen, {species.name for species in enemies.SUBSTITUTE_CANDIDATES
                                if species.level in levels_in_play})

    def test_wild_mode_never_touches_story_or_npc(self) -> None:
        substitutions, final = enemies.plan_substitutions(Random(1), include_story=False, same_level=True)
        self.assertTrue(substitutions)
        for (map_id, species), substitute in substitutions.items():
            self.assertNotEqual(species, substitute)
            for record in enemies.RECORDS_BY_MAP[map_id]:
                if record.type == species:
                    self.assertEqual(enemies.classify_record(record), enemies.CLASS_WILD)
                    self.assertEqual(final[(record.map, record.slot)], substitute)
            self.assertNotIn(map_id, enemies.EXCLUDED_SCREENS)
        self.assertNotIn((225, 115), substitutions)   # Machinedramon
        self.assertNotIn((1, 152), substitutions)     # Kunemon recruit fight
        self.assertIn((2, 80), substitutions)         # MAYO03 Goburimon

    def test_story_mode_swaps_bosses_but_keeps_stats(self) -> None:
        substitutions, _ = enemies.plan_substitutions(Random(2), include_story=True, same_level=False)
        self.assertIn((1, 152), substitutions)
        # (225, 115) — the old example here — is now script-placed-excluded
        # (MGEN99 script-places the final boss); (2, 164) is a story group
        # that remains substitutable.
        self.assertIn((2, 164), substitutions)
        # stats live in stat_overrides only; substitution never writes them
        plan = enemies.EnemyPlan({}, substitutions, {}, {}, {}, {})
        self.assertEqual(plan.stat_overrides, {})

    def test_script_placed_groups_are_never_substituted(self) -> None:
        # 2026-08-31 playtest + story-swap audit: these screens' scripts
        # place the fight entity themselves (loadDigimon/setDigimon in the
        # script, not MAPHEAD), so a substituted record leaves the script
        # operand stale, the placement is refused and the cutscene stalls
        # against an absent entity — Leomon, the OGRE11 post-battle Whamon
        # scene (setTrigger 224 unreachable) and WaruMonzaemon were hit live.
        for pair in ((76, 151), (76, 166), (143, 112), (142, 154), (151, 70)):
            self.assertIn(pair, enemies.SCRIPT_PLACED_GROUPS)
        for seed in range(5):
            for include_story in (False, True):
                substitutions, _final = enemies.plan_substitutions(
                    Random(seed), include_story=include_story, same_level=False,
                )
                hit = set(substitutions) & enemies.SCRIPT_PLACED_GROUPS
                self.assertFalse(hit, (seed, include_story, hit))

    def test_story_mode_retains_value_after_the_exclusion(self) -> None:
        # The audit found 47 of 60 story groups clean — the option must
        # still substitute a healthy majority of them.
        substitutions, _ = enemies.plan_substitutions(Random(2), include_story=True, same_level=False)
        story = [
            (m, sp) for (m, sp) in substitutions
            if enemies.CLASS_STORY in {
                enemies.classify_record(r)
                for r in enemies.RECORDS_BY_MAP[m] if r.type == sp
            }
        ]
        self.assertGreaterEqual(len(story), 40)

    def test_vanilla_mode_gives_swapped_species_power_equivalent_moves(self) -> None:
        _, final = enemies.plan_substitutions(Random(3), include_story=False, same_level=True)
        moves = enemies.plan_move_overrides(enemies.STATS_VANILLA, Random(3), final, {})
        self.assertEqual(set(moves), set(final))     # exactly the swapped records get a moveset
        for (map_id, slot), (new_moves, prio) in moves.items():
            record = enemies.RECORD_INDEX[(map_id, slot)]
            substitute = enemies.SPECIES_BY_ID[final[(map_id, slot)]]
            self.assertEqual(prio, record.prio)
            self.assertEqual(len(new_moves), 4)
            used = [m - enemies.ANIM_MOVE_BASE for m in new_moves if m != enemies.NO_MOVE]
            if record.move_count == 0:              # non-combat placement: explicitly no techniques
                self.assertEqual(used, [])
                continue
            self.assertTrue(used)
            self.assertEqual(len(used), len(set(used)))
            for k in used:
                self.assertIn(k, substitute.tech_slots)
            wanted = min(record.move_count, len(substitute.tech_slots))
            self.assertEqual(len(used), max(1, wanted))
        # power equivalence on a concrete case: MAYO03 Goburimon (66/279/52) -> Icemon (320/264/126)
        goburimon = enemies.RECORD_INDEX[(2, 0)]
        picked = enemies.pick_moves_equivalent(goburimon, enemies.SPECIES_BY_ID[80], enemies.SPECIES_BY_ID[94])
        self.assertEqual(picked, (0x2E, 0x2F, 0x30, 0xFF))

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
            region_depths={}, region_targets={}, screen_targets={},
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
            start = (offset - 24) % 2352
            self.assertLessEqual(start + len(data), 2048)


class TestEnemyOptionsThroughGeneration(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "enemy_stats": "progressive",
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
        self.assertTrue(plan.region_targets)
        self.assertTrue(plan.move_overrides)
        self.assertFalse(plan.screen_targets)


class TestEnemyOptionsFullRandom(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"enemy_stats": "full_random"}

    def test_plan_without_fill(self) -> None:
        self.world.post_fill()
        plan = self.world.enemy_plan
        self.assertTrue(plan.screen_targets)
        self.assertFalse(plan.region_targets)
        self.assertFalse(plan.substitutions)
        self.assertTrue(plan.stat_overrides)
        self.assertTrue(plan.move_overrides)


class TestEnemyOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plan_is_empty(self) -> None:
        self.world.post_fill()
        self.assertTrue(self.world.enemy_plan.empty)


class TestTechniqueWeights(unittest.TestCase):
    def test_random_weights(self) -> None:
        rng = Random(1)
        for moves in ((0x2E, 0x2F, 0x30, 0xFF), (0x2E, 0xFF, 0xFF, 0xFF), (0x2E, 0x2F, 0x30, 0x31), (0xFF,) * 4):
            weights = enemies.random_weights(rng, moves)
            used = [k for k, m in enumerate(moves) if m != enemies.NO_MOVE]
            self.assertEqual(sum(weights), enemies.WEIGHT_TOTAL if used else 0, moves)
            self.assertTrue(all(weights[k] >= 1 for k in used))
            self.assertTrue(all(weights[k] == 0 for k in range(4) if k not in used))

    def test_overrides_cover_every_touchable_record_and_keep_movesets(self) -> None:
        prior = {(2, 0): ((0x2E, 0x2F, 0xFF, 0xFF), (50, 50, 0, 0))}
        out = enemies.plan_weight_overrides(Random(2), prior)
        self.assertEqual(out[(2, 0)][0], (0x2E, 0x2F, 0xFF, 0xFF))
        self.assertEqual(sum(out[(2, 0)][1]), enemies.WEIGHT_TOTAL)
        touchable = [r for r in enemies.RECORDS if enemies._touchable(r)]
        self.assertEqual(set(out), {(r.map, r.slot) for r in touchable} | set(prior))
        for record in touchable:
            moves, prio = out[(record.map, record.slot)]
            if (record.map, record.slot) not in prior:
                self.assertEqual(moves, record.moves)
            self.assertEqual(sum(prio), enemies.WEIGHT_TOTAL)


class TestTechniqueWeightsOption(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"enemy_technique_weights": True}

    def test_plan(self) -> None:
        self.world.post_fill()
        plan = self.world.enemy_plan
        self.assertFalse(plan.empty)
        self.assertFalse(plan.stat_overrides or plan.substitutions)
        self.assertGreater(len(plan.move_overrides), 400)
