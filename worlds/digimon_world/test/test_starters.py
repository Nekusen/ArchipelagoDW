"""Tests for starter-Digimon randomization (clean-room of meekrhino's
``randomizeStarters``).

Covers:

* The static metadata constants (playable / finisher / bubble id sets).
* Table parsing for both DIGIMON_PARA and TECH_PARA against synthetic
  blobs we control.
* Eligible-pool computation under various level masks.
* Tech selection: weakest-vs-random, plus the no-eligible-tech edge
  case (a Fresh whose only tech is Bubble).
* End-to-end :func:`pick_starters` returns two distinct Digimon and
  their assignments are plausibly typed.
* Patcher contract: option ON writes ``starters.json`` and inserts
  the ``shuffle_starters`` step; option OFF does neither.
* Apply-time extension smoke-test against a synthetic ROM.
"""

from __future__ import annotations

import json
import struct
import unittest
import zipfile
from random import Random
from typing import Any, ClassVar
from unittest import mock

from worlds.digimon_world import rom as rom_module
from worlds.digimon_world import starters
from worlds.digimon_world.data.addresses import (
    ROM_DIGIMON_DATA,
    ROM_STARTER_CHK_DIGIMON,
    ROM_STARTER_EQUIP_ANIM,
    ROM_STARTER_LEARN_TECH,
    ROM_STARTER_SET_DIGIMON,
    ROM_STARTER_STAT_CHK_DIGIMON,
    ROM_TECHNIQUE_DATA,
)

from .bases import DigimonWorldTestBase

# =============================================================================
# Synthetic table builders
# =============================================================================


def _make_digimon_table(
    entries: dict[int, tuple[int, list[int]]],
    count: int = ROM_DIGIMON_DATA.count,
) -> bytes:
    """Build synthetic DIGIMON_PARA user data.

    ``entries`` maps ``digimon_id -> (level, tech_list)``. Tech list
    is padded / truncated to 16 entries with NO_TECH_ID for missing.
    Default for unmentioned ids: level 0, empty tech list.
    """

    out = bytearray()
    for i in range(count):
        level, raw_techs = entries.get(i, (0, []))
        techs = list(raw_techs[:16]) + [starters.NO_TECH_ID] * max(
            0, 16 - len(raw_techs),
        )
        out.extend(
            struct.pack(
                starters.DIGIMON_RECORD_FORMAT,
                f"digi{i:03d}".encode("ascii").ljust(20, b"\x00"),  # name
                0,           # models (i32)
                0,           # radius (i16)
                0,           # height (i16)
                0,           # type
                level,       # level
                0, 0, 0,     # spec[3]
                0,           # item
                0,           # drop_rate
                *techs,      # tech[16]
            ),
        )
    return bytes(out)


def _make_tech_table(
    entries: dict[int, int],
    count: int = ROM_TECHNIQUE_DATA.count,
) -> bytes:
    """Build synthetic TECH_PARA user data.

    ``entries`` maps ``tech_id -> power``. Default for unmentioned
    ids is power 0 (non-damaging).
    """

    out = bytearray()
    for i in range(count):
        power = entries.get(i, 0)
        out.extend(
            struct.pack(
                starters.TECH_RECORD_FORMAT,
                0,        # unkn1 u16
                0,        # aiDist u16
                power,    # power u16
                0, 0, 0,  # mp3, itime, range
                0, 0,     # spec, effect
                0, 0,     # accuracy, effChance
                0,        # unkn2
            ),
        )
    return bytes(out)


# =============================================================================
# Static metadata sanity
# =============================================================================


class TestStaticMetadata(unittest.TestCase):

    def test_playable_size(self) -> None:
        # range(0x01, 0x3E) = 61, plus {0x3F, 0x40, 0x41} = 3 -> 64.
        self.assertEqual(len(starters.PLAYABLE_DIGIMON_IDS), 64)
        self.assertNotIn(0x00, starters.PLAYABLE_DIGIMON_IDS)
        self.assertNotIn(0x3E, starters.PLAYABLE_DIGIMON_IDS)
        self.assertIn(0x41, starters.PLAYABLE_DIGIMON_IDS)

    def test_finisher_range(self) -> None:
        # range(0x3A, 0x71) = 55 ids.
        self.assertEqual(len(starters.FINISHER_TECH_IDS), 0x71 - 0x3A)
        self.assertIn(0x3A, starters.FINISHER_TECH_IDS)
        self.assertNotIn(0x71, starters.FINISHER_TECH_IDS)

    def test_bubble_range(self) -> None:
        self.assertEqual(starters.BUBBLE_TECH_IDS, frozenset(range(0x71, 0x79)))

    def test_tech_slot_to_anim_id(self) -> None:
        # DW1's animation-id table places the 16 tech-slot animations at
        # contiguous bytes 0x2E..0x3D. Slot N (1-based) -> 0x2E + (N-1).
        # Source: meekrhino's digimon/util.py:181-195.
        self.assertEqual(starters.tech_slot_to_anim_id(1), 0x2E)
        self.assertEqual(starters.tech_slot_to_anim_id(2), 0x2F)
        self.assertEqual(starters.tech_slot_to_anim_id(16), 0x3D)

    def test_tech_slot_to_anim_id_rejects_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            starters.tech_slot_to_anim_id(0)
        with self.assertRaises(ValueError):
            starters.tech_slot_to_anim_id(17)


# =============================================================================
# Table parsing
# =============================================================================


class TestParseTables(unittest.TestCase):

    def test_digimon_round_trip(self) -> None:
        table = _make_digimon_table({
            0x03: (starters.LEVEL_ROOKIE, [0x05, 0x10, 0x6F]),
            0x40: (starters.LEVEL_ULTIMATE, [0x70, 0x71]),
        })
        digimons = starters.parse_digimon_table(table, ROM_DIGIMON_DATA.count)
        self.assertEqual(len(digimons), ROM_DIGIMON_DATA.count)
        agumon = digimons[0x03]
        self.assertEqual(agumon.level, starters.LEVEL_ROOKIE)
        self.assertEqual(agumon.tech_list[:3], (0x05, 0x10, 0x6F))
        self.assertEqual(agumon.tech_list[3], starters.NO_TECH_ID)
        self.assertTrue(agumon.is_playable)

    def test_digimon_wrong_size_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "bytes"):
            starters.parse_digimon_table(b"\x00" * 100, ROM_DIGIMON_DATA.count)

    def test_tech_round_trip(self) -> None:
        table = _make_tech_table({0x05: 100, 0x3A: 9999})
        techs = starters.parse_tech_table(table, ROM_TECHNIQUE_DATA.count)
        self.assertEqual(len(techs), ROM_TECHNIQUE_DATA.count)
        self.assertTrue(techs[0x05].is_damaging)
        self.assertFalse(techs[0x05].is_finisher)
        self.assertTrue(techs[0x05].is_learnable)
        self.assertTrue(techs[0x3A].is_finisher)
        self.assertFalse(techs[0x3A].is_learnable)
        self.assertTrue(techs[0x71].tech_id in starters.BUBBLE_TECH_IDS)
        self.assertFalse(techs[0x71].is_learnable)


# =============================================================================
# Eligible-starter pool
# =============================================================================


class TestEligibleStarterIds(unittest.TestCase):

    def test_filters_by_level(self) -> None:
        digimons = starters.parse_digimon_table(
            _make_digimon_table({
                0x01: (starters.LEVEL_FRESH, []),
                0x03: (starters.LEVEL_ROOKIE, []),
                0x04: (starters.LEVEL_ROOKIE, []),
                0x20: (starters.LEVEL_CHAMPION, []),
                0x40: (starters.LEVEL_ULTIMATE, []),
            }),
            ROM_DIGIMON_DATA.count,
        )
        result = starters.eligible_starter_ids(
            digimons,
            allowed_levels=frozenset({starters.LEVEL_ROOKIE}),
        )
        self.assertEqual(set(result), {0x03, 0x04})

    def test_filters_unplayable_ids(self) -> None:
        # ID 0x00 should never be eligible regardless of level.
        digimons = starters.parse_digimon_table(
            _make_digimon_table({
                0x00: (starters.LEVEL_ROOKIE, []),
                0x03: (starters.LEVEL_ROOKIE, []),
            }),
            ROM_DIGIMON_DATA.count,
        )
        result = starters.eligible_starter_ids(
            digimons,
            allowed_levels=frozenset({starters.LEVEL_ROOKIE}),
        )
        self.assertNotIn(0x00, result)
        self.assertIn(0x03, result)

    def test_multiple_levels(self) -> None:
        digimons = starters.parse_digimon_table(
            _make_digimon_table({
                0x03: (starters.LEVEL_ROOKIE, []),
                0x20: (starters.LEVEL_CHAMPION, []),
                0x40: (starters.LEVEL_ULTIMATE, []),
            }),
            ROM_DIGIMON_DATA.count,
        )
        result = starters.eligible_starter_ids(
            digimons,
            allowed_levels=frozenset({
                starters.LEVEL_ROOKIE, starters.LEVEL_CHAMPION,
            }),
        )
        self.assertEqual(set(result), {0x03, 0x20})


# =============================================================================
# Tech selection
# =============================================================================


class TestPickStarterTech(unittest.TestCase):

    def test_use_weakest_picks_first_eligible_slot(self) -> None:
        # Slot 1 is non-damaging (skip), slot 2 is damaging (pick).
        digimon = starters.parse_digimon_table(
            _make_digimon_table({
                0x03: (starters.LEVEL_ROOKIE, [0x05, 0x10]),
            }),
            ROM_DIGIMON_DATA.count,
        )[0x03]
        techs = starters.parse_tech_table(
            _make_tech_table({0x05: 0, 0x10: 100}),
            ROM_TECHNIQUE_DATA.count,
        )
        result = starters.pick_starter_tech(
            digimon, techs, random=Random(0), use_weakest=True,
        )
        self.assertEqual(result, (0x10, 2))

    def test_use_weakest_skips_finisher_and_counter(self) -> None:
        # Slot 1: Counter (special-cased excluded). Slot 2: finisher.
        # Slot 3: regular damaging — pick this one.
        digimon = starters.parse_digimon_table(
            _make_digimon_table({
                0x03: (starters.LEVEL_ROOKIE, [
                    starters.COUNTER_TECH_ID, 0x3A, 0x05,
                ]),
            }),
            ROM_DIGIMON_DATA.count,
        )[0x03]
        techs = starters.parse_tech_table(
            _make_tech_table({
                starters.COUNTER_TECH_ID: 100, 0x3A: 9999, 0x05: 100,
            }),
            ROM_TECHNIQUE_DATA.count,
        )
        result = starters.pick_starter_tech(
            digimon, techs, random=Random(0), use_weakest=True,
        )
        self.assertEqual(result, (0x05, 3))

    def test_random_picks_from_eligible_pool(self) -> None:
        digimon = starters.parse_digimon_table(
            _make_digimon_table({
                0x03: (starters.LEVEL_ROOKIE, [0x05, 0x06, 0x07]),
            }),
            ROM_DIGIMON_DATA.count,
        )[0x03]
        techs = starters.parse_tech_table(
            _make_tech_table({0x05: 100, 0x06: 100, 0x07: 100}),
            ROM_TECHNIQUE_DATA.count,
        )
        # Many seeds should hit each slot eventually.
        seen: set[int] = set()
        for seed in range(50):
            result = starters.pick_starter_tech(
                digimon, techs, random=Random(seed), use_weakest=False,
            )
            self.assertIsNotNone(result)
            assert result is not None  # type narrowing
            tech_id, _slot = result
            self.assertIn(tech_id, {0x05, 0x06, 0x07})
            seen.add(tech_id)
        self.assertEqual(seen, {0x05, 0x06, 0x07})

    def test_no_eligible_tech_returns_none(self) -> None:
        # Vanilla DW1 Bubble (0x71) has power 0 -> non-damaging ->
        # excluded by both weakest and random paths. A Digimon whose
        # tech list contains only Bubble has no eligible starter tech.
        digimon = starters.parse_digimon_table(
            _make_digimon_table({
                0x01: (starters.LEVEL_FRESH, [0x71]),
            }),
            ROM_DIGIMON_DATA.count,
        )[0x01]
        techs = starters.parse_tech_table(
            _make_tech_table({}),  # all techs power=0 by default
            ROM_TECHNIQUE_DATA.count,
        )
        result = starters.pick_starter_tech(
            digimon, techs, random=Random(0), use_weakest=True,
        )
        self.assertIsNone(result)


# =============================================================================
# pick_starters end-to-end
# =============================================================================


class TestPickStarters(unittest.TestCase):

    def _build(self, *, num_eligible: int = 4) -> tuple[
        list[starters.DigimonProps], list[starters.TechProps],
    ]:
        digimon_entries: dict[int, tuple[int, list[int]]] = {}
        # Pile of eligible rookies starting at id 0x03 (which is in
        # PLAYABLE_DIGIMON_IDS).
        for i in range(num_eligible):
            digi_id = 0x03 + i
            digimon_entries[digi_id] = (starters.LEVEL_ROOKIE, [0x05, 0x10])
        tech_entries = {0x05: 100, 0x10: 200}
        digimons = starters.parse_digimon_table(
            _make_digimon_table(digimon_entries),
            ROM_DIGIMON_DATA.count,
        )
        techs = starters.parse_tech_table(
            _make_tech_table(tech_entries),
            ROM_TECHNIQUE_DATA.count,
        )
        return digimons, techs

    def test_returns_two_distinct_digimon(self) -> None:
        digimons, techs = self._build(num_eligible=4)
        result = starters.pick_starters(
            digimons, techs,
            random=Random(0),
            allowed_levels=frozenset({starters.LEVEL_ROOKIE}),
            use_weakest_tech=True,
        )
        self.assertIsNotNone(result)
        assert result is not None
        first, second = result
        self.assertNotEqual(first.digimon_id, second.digimon_id)
        # Both should have a tech assignment (every eligible Digimon
        # in this fixture has a damaging tech).
        self.assertIsNotNone(first.tech_id)
        self.assertIsNotNone(second.tech_id)

    def test_pool_too_small_returns_none(self) -> None:
        digimons, techs = self._build(num_eligible=1)
        result = starters.pick_starters(
            digimons, techs,
            random=Random(0),
            allowed_levels=frozenset({starters.LEVEL_ROOKIE}),
            use_weakest_tech=True,
        )
        self.assertIsNone(result)

    def test_deterministic_under_same_seed(self) -> None:
        digimons, techs = self._build(num_eligible=10)
        a = starters.pick_starters(
            digimons, techs,
            random=Random(7),
            allowed_levels=frozenset({starters.LEVEL_ROOKIE}),
            use_weakest_tech=True,
        )
        b = starters.pick_starters(
            digimons, techs,
            random=Random(7),
            allowed_levels=frozenset({starters.LEVEL_ROOKIE}),
            use_weakest_tech=True,
        )
        self.assertEqual(a, b)


# =============================================================================
# Patcher contract — option ON / OFF
# =============================================================================


def _capture_patch(world: Any) -> tuple[dict[str, bytes], list[tuple[str, list[str]]]]:
    captured_files: dict[str, bytes] = {}
    captured_procedure: list[tuple[str, list[str]]] = []

    def fake_write(self_patch: Any, target: str) -> None:
        with zipfile.ZipFile(target, "w") as _:
            pass
        captured_files.update(self_patch.files)
        captured_procedure.extend(self_patch.procedure)

    with mock.patch.object(
        rom_module.DigimonWorldProcedurePatch, "write", fake_write,
    ):
        world.generate_output(".")
    return captured_files, captured_procedure


class TestStarterPatcherOn(DigimonWorldTestBase):
    """Default options: StarterRandomization is DefaultOnToggle and
    only ``starter_allow_rookie`` is enabled by default."""

    options: ClassVar[dict[str, Any]] = {}

    def test_starters_params_blob_present(self) -> None:
        files, _procedure = _capture_patch(self.world)
        self.assertIn("starters.json", files)
        params = json.loads(files["starters.json"])
        self.assertIn("seed", params)
        self.assertIsInstance(params["seed"], int)
        self.assertIn("allowed_levels", params)
        self.assertEqual(params["allowed_levels"], [starters.LEVEL_ROOKIE])
        self.assertIn("use_weakest_tech", params)
        self.assertTrue(params["use_weakest_tech"])

    def test_shuffle_starters_in_procedure(self) -> None:
        _files, procedure = _capture_patch(self.world)
        steps = [name for name, _args in procedure]
        self.assertIn("shuffle_starters", steps)
        self.assertLess(steps.index("apply_tokens"), steps.index("shuffle_starters"))
        self.assertLess(steps.index("shuffle_starters"), steps.index("recalc_edc"))


class TestStarterPatcherCustomLevels(DigimonWorldTestBase):
    """Multiple level toggles propagate as a multi-element list."""

    options: ClassVar[dict[str, Any]] = {
        "starter_allow_rookie": True,
        "starter_allow_champion": True,
        "starter_allow_ultimate": True,
        "starter_use_weakest_tech": False,
    }

    def test_levels_combined(self) -> None:
        files, _procedure = _capture_patch(self.world)
        params = json.loads(files["starters.json"])
        self.assertEqual(
            sorted(params["allowed_levels"]),
            sorted([
                starters.LEVEL_ROOKIE,
                starters.LEVEL_CHAMPION,
                starters.LEVEL_ULTIMATE,
            ]),
        )
        self.assertFalse(params["use_weakest_tech"])


class TestStarterPatcherOff(DigimonWorldTestBase):
    """Master toggle off: no params blob and no procedure step."""

    options: ClassVar[dict[str, Any]] = {
        "randomize_starter": False,
    }

    def test_no_starter_params(self) -> None:
        files, procedure = _capture_patch(self.world)
        self.assertNotIn("starters.json", files)
        self.assertNotIn(
            "shuffle_starters",
            {name for name, _args in procedure},
        )


# =============================================================================
# Apply-time extension smoke test
# =============================================================================


class TestShuffleStartersExtension(unittest.TestCase):
    """Build a synthetic ROM with planted DIGIMON_PARA + TECH_PARA,
    invoke the apply-time extension directly, verify the starter
    bytes get rewritten and unrelated bytes preserved."""

    def test_rewrites_starter_bytes(self) -> None:
        from worlds.digimon_world.data.addresses import (
            ROM_BIN_BYTES,
            _flat_to_user_data,
        )

        # Build synthetic tables.
        digimon_entries = {
            0x03: (starters.LEVEL_ROOKIE, [0x05, 0x10]),
            0x04: (starters.LEVEL_ROOKIE, [0x05, 0x10]),
            0x11: (starters.LEVEL_ROOKIE, [0x05, 0x10]),
        }
        tech_entries = {0x05: 100, 0x10: 200}
        digimon_user_data = _make_digimon_table(digimon_entries)
        tech_user_data = _make_tech_table(tech_entries)

        # Allocate a ROM-sized buffer and plant the user-data records
        # into their sector-correct flat positions.
        rom = bytearray(ROM_BIN_BYTES)
        for i, byte in enumerate(digimon_user_data):
            rom[_flat_to_user_data(ROM_DIGIMON_DATA.offset, i)] = byte
        for i, byte in enumerate(tech_user_data):
            rom[_flat_to_user_data(ROM_TECHNIQUE_DATA.offset, i)] = byte
        # Plant a canary far away from any starter offsets.
        rom[0] = 0xCA

        params = {
            "seed": 12345,
            "allowed_levels": [starters.LEVEL_ROOKIE],
            "use_weakest_tech": True,
        }
        caller = mock.MagicMock()
        caller.get_file.return_value = json.dumps(params).encode("ascii")

        patched = rom_module.DigimonWorldPatchExtension.shuffle_starters(
            caller, bytes(rom), "starters.json",
        )
        self.assertEqual(len(patched), len(rom))
        self.assertEqual(patched[0], 0xCA)

        # Both starter Digimon bytes must now be in {0x03, 0x04, 0x11}
        # and they must be different from each other.
        chosen = [
            patched[ROM_STARTER_SET_DIGIMON[0]],
            patched[ROM_STARTER_SET_DIGIMON[1]],
        ]
        for digimon_id in chosen:
            self.assertIn(digimon_id, {0x03, 0x04, 0x11})
        self.assertNotEqual(chosen[0], chosen[1])

        # The chk-id sites must match the set-id sites.
        for i in (0, 1):
            self.assertEqual(
                patched[ROM_STARTER_CHK_DIGIMON[i]],
                patched[ROM_STARTER_SET_DIGIMON[i]],
            )

        # The shared stat-check site uses slot 0's id.
        self.assertEqual(
            patched[ROM_STARTER_STAT_CHK_DIGIMON],
            patched[ROM_STARTER_SET_DIGIMON[0]],
        )

        # learn-tech bytes must be in {0x05, 0x10} (the only damaging
        # techs in the synthetic pool); equip-anim must be the slot
        # encoding for slot 1 (0x01) since 0x05 is at index 0 in the
        # tech list and weakest selection picks it.
        for i in (0, 1):
            self.assertIn(patched[ROM_STARTER_LEARN_TECH[i]], {0x05, 0x10})
            self.assertIn(
                patched[ROM_STARTER_EQUIP_ANIM[i]],
                {starters.tech_slot_to_anim_id(1)},
            )

    def test_pool_too_small_leaves_rom_unchanged(self) -> None:
        from worlds.digimon_world.data.addresses import (
            ROM_BIN_BYTES,
            _flat_to_user_data,
        )

        # Only ONE eligible Digimon -> pick_starters returns None,
        # extension must return the rom unchanged.
        digimon_user_data = _make_digimon_table({
            0x03: (starters.LEVEL_ROOKIE, [0x05]),
        })
        tech_user_data = _make_tech_table({0x05: 100})
        rom = bytearray(ROM_BIN_BYTES)
        rom[ROM_STARTER_SET_DIGIMON[0]] = 0xAA  # vanilla canary
        rom[ROM_STARTER_SET_DIGIMON[1]] = 0xBB
        for i, byte in enumerate(digimon_user_data):
            rom[_flat_to_user_data(ROM_DIGIMON_DATA.offset, i)] = byte
        for i, byte in enumerate(tech_user_data):
            rom[_flat_to_user_data(ROM_TECHNIQUE_DATA.offset, i)] = byte

        params = {
            "seed": 1,
            "allowed_levels": [starters.LEVEL_ROOKIE],
            "use_weakest_tech": True,
        }
        caller = mock.MagicMock()
        caller.get_file.return_value = json.dumps(params).encode("ascii")

        patched = rom_module.DigimonWorldPatchExtension.shuffle_starters(
            caller, bytes(rom), "starters.json",
        )
        self.assertEqual(patched[ROM_STARTER_SET_DIGIMON[0]], 0xAA)
        self.assertEqual(patched[ROM_STARTER_SET_DIGIMON[1]], 0xBB)
