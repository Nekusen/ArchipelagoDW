"""Partner raising parameters (:mod:`worlds.digimon_world.raising`) and the music shuffle
(:mod:`worlds.digimon_world.music`)."""

from __future__ import annotations

import unittest
from random import Random
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import evolutions, music, raising
from .. import rom as rom_module
from ..data.addresses import (
    RAISE_DATA_FAVORITE_FOOD_OFFSET,
    RAISE_DATA_ROW_SIZE,
    ROM_RAISE_DATA_OFFSET,
    iter_user_data_chunks,
    maphead_bin_offset,
)
from ..data.enemy_records import RAISE_DATA
from .bases import DigimonWorldTestBase


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestRaising(unittest.TestCase):
    def test_vanilla_rows(self) -> None:
        self.assertEqual(len(RAISE_DATA), 66)
        agumon = raising.VANILLA_RAISE[3]
        self.assertEqual(agumon, raising.RaiseRow(38, 1, 0, 0, 15))          # Meat, 19:00-04:00, Drill/ADR, even, 15
        self.assertEqual(raising.VANILLA_RAISE[1].favorite_food, 0)          # Botamon: no favourite
        self.assertEqual(raising.VANILLA_RAISE[1].sleep_cycle, 6)
        self.assertEqual(RAISE_DATA[3][:8], (1, 5, 9, 13, 17, 21, -1, -1))   # meal hours
        self.assertEqual(raising.VANILLA_RAISE[11].training_type, 4)         # Numemon's penalty aptitude

    def test_species_and_rows(self) -> None:
        species = raising.raisable_species()
        self.assertNotIn(1, species)                                          # Fresh
        self.assertNotIn(2, species)                                          # In-Training
        self.assertNotIn(0, species)
        self.assertNotIn(62, species)                                         # WereGarurumon: not a partner
        self.assertIn(3, species)
        self.assertIn(65, species)
        rows = raising.randomize_raising(Random(1))
        self.assertTrue(rows)
        for species_id, row in rows.items():
            self.assertIn(species_id, species)
            self.assertIn(row.favorite_food, raising.FOOD_IDS)
            self.assertIn(row.sleep_cycle, raising.SLEEP_SCHEDULES)
            self.assertIn(row.favored_region, raising.REGION_NAMES)
            self.assertIn(row.training_type, raising.TRAINING_TYPES)
            low, high = raising.WEIGHT_BANDS[evolutions.SPECIES_LEVEL[species_id]]
            self.assertTrue(low <= row.default_weight <= high)
        self.assertEqual(rows, raising.randomize_raising(Random(1)))
        self.assertIn("likes", raising.describe_row(rows[3]))

    def test_tokens(self) -> None:
        plan = raising.RaisePlan({3: raising.RaiseRow(40, 2, 7, 3, 18), 20: raising.RaiseRow(50, 0, 1, 1, 30)})
        patch = _TokenCollector()
        rom_module._write_raise_tokens(patch, plan)  # type: ignore[arg-type]
        tokens = dict(patch.tokens)
        self.assertEqual(tokens[ROM_RAISE_DATA_OFFSET + 3 * RAISE_DATA_ROW_SIZE + RAISE_DATA_FAVORITE_FOOD_OFFSET],
                         bytes((40, 2, 7, 3, 18)))
        # row 20 (Birdramon) straddles the block's sector boundary: still one 5-byte span, past the gap
        chunks = list(iter_user_data_chunks(ROM_RAISE_DATA_OFFSET, 20 * RAISE_DATA_ROW_SIZE, bytes(28)))
        self.assertEqual(len(chunks), 2)
        self.assertEqual(sum(len(data) for _, data in patch.tokens), 10)


class TestMusic(unittest.TestCase):
    def test_sites_and_tracks(self) -> None:
        self.assertEqual(len(music.SITES), 261)
        self.assertEqual(len({s.section for s in music.SITES}), 250)
        self.assertEqual(music.SITES[0], music.BgmSite(0, 1138, 1, 0))
        self.assertEqual(music.track_name(1), "Non Bewildering Forest Theme")
        self.assertEqual(music.track_name(1, 1), "Non Bewildering Forest Night Theme")
        self.assertEqual(music.track_name(6), "Canyon Theme")
        self.assertEqual(music.track_name(33, 1), "Normal Battle Theme")
        eligible = music.eligible_sites()
        self.assertEqual(len(eligible), 261 - 23)                            # 23 forced-mode (2..10) sites
        self.assertTrue(all(music.SITES[i].mode in (0, 1) for i in eligible))
        self.assertTrue(all(music.SITES[i].font in music.FIELD_FONTS for i in eligible))

    def test_modes(self) -> None:
        self.assertEqual(music.randomize_music(Random(1), music.SHUFFLE_OFF), {})
        areas = music.randomize_music(Random(1), music.SHUFFLE_AREAS)
        self.assertTrue(areas)
        mapping: dict[int, set[int]] = {}
        for index, font in areas.items():
            self.assertIn(font, music.FIELD_FONTS)
            mapping.setdefault(music.SITES[index].font, set()).add(font)
        self.assertTrue(all(len(fonts) == 1 for fonts in mapping.values()))   # one theme per vanilla theme
        self.assertEqual(len({next(iter(f)) for f in mapping.values()}), len(mapping))   # a permutation
        screens = music.randomize_music(Random(1), music.SHUFFLE_SCREENS)
        per_section: dict[int, set[int]] = {}
        for index, font in screens.items():
            per_section.setdefault(music.SITES[index].section, set()).add(font)
        self.assertTrue(all(len(fonts) == 1 for fonts in per_section.values()))
        chaos = music.randomize_music(Random(2), music.SHUFFLE_CHAOS)
        self.assertTrue(all(f in music.FIELD_FONTS or f == music.BATTLE_FONT for f in chaos.values()))
        self.assertTrue(all(f not in music.JINGLE_FONTS for f in chaos.values()))
        self.assertEqual(areas, music.randomize_music(Random(1), music.SHUFFLE_AREAS))

    def test_tokens_and_spoiler(self) -> None:
        plan = music.BgmPlan({0: 15, 1: 15}, music.SHUFFLE_AREAS)
        patch = _TokenCollector()
        rom_module._write_bgm_tokens(patch, plan)  # type: ignore[arg-type]
        self.assertEqual(patch.tokens,
                         [(maphead_bin_offset(1138 + 1), b"\x0f"), (maphead_bin_offset(1212 + 1), b"\x0f")])
        self.assertEqual(music.describe_plan(plan), ["Non Bewildering Forest Theme -> Freezeland Theme"])
        lines = music.describe_plan(music.BgmPlan({0: 15}, music.SHUFFLE_SCREENS))
        self.assertEqual(lines, ["MAYO01: Non Bewildering Forest Theme -> Freezeland Theme"])


class TestRaisingMusicOptions(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"partner_raising": True, "bgm_shuffle": "areas"}

    def test_plans(self) -> None:
        self.assertGreater(len(self.world.raise_plan.overrides), 50)
        self.assertGreater(len(self.world.bgm_plan.overrides), 150)


class TestRaisingMusicOptionsOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_default_plans_are_empty(self) -> None:
        self.assertTrue(self.world.raise_plan.empty)
        self.assertTrue(self.world.bgm_plan.empty)
