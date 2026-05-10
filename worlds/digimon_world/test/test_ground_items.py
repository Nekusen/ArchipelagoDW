"""Tests for ground-item randomization (clean-room of meekrhino's
``randomizeMapSpawnItems``).

Covers:

* The pure pool / filter logic in :mod:`worlds.digimon_world.ground_items`,
  exercised against a synthetic ITEM_PARA whose properties we control —
  no real ROM required.
* The apply-time shuffle's determinism given a fixed seed.
* The generation-time patcher contract: when
  :class:`worlds.digimon_world.options.GroundItemRandomization` is on,
  the patch zip carries a ``ground_items.json`` blob and the patch's
  procedure picks up the ``shuffle_ground_items`` step. When it's off,
  neither is present.
"""

from __future__ import annotations

import json
import struct
import unittest
import zipfile
from random import Random
from typing import Any, ClassVar
from unittest import mock

from worlds.digimon_world import ground_items
from worlds.digimon_world import rom as rom_module
from worlds.digimon_world.data.addresses import (
    ROM_ITEM_TABLE_ENTRY_COUNT,
    ROM_MAP_ITEM_OFFSETS,
)

from .bases import DigimonWorldTestBase

# =============================================================================
# Synthetic ITEM_PARA helpers
# =============================================================================
#
# Every test that exercises filter logic builds its own 128-entry
# ITEM_PARA from this helper so the input is fully under test control —
# ITEM_PARA on the real ROM has its own quirks that aren't useful for
# verifying filter semantics.


def _make_table(entries: dict[int, tuple[int, int, bool]]) -> bytes:
    """Build 4096 bytes of synthetic ITEM_PARA user data.

    ``entries`` maps ``item_id -> (price, sort, dropable)``. Any id not
    in the dict gets ``price=0, sort=0xFF, dropable=False`` (effectively
    junk that the filter excludes).
    """

    fmt = ground_items.ITEM_TABLE_RECORD_FORMAT
    out = bytearray()
    for i in range(ROM_ITEM_TABLE_ENTRY_COUNT):
        price, sort, dropable = entries.get(i, (0, 0xFF, False))
        out.extend(
            struct.pack(
                fmt,
                f"item{i:03d}".encode("ascii").ljust(20, b"\x00"),  # name
                price,
                0,        # merit
                sort,
                0,        # color
                dropable,
            ),
        )
    return bytes(out)


# =============================================================================
# Pool-set sanity
# =============================================================================


class TestPoolConstants(unittest.TestCase):
    """The id-pool sets are clean-room copies of meekrhino's source.
    These tests catch accidental drift (e.g. someone editing the range
    expression and shifting a boundary)."""

    def test_consumable_size(self) -> None:
        # range(0x00, 0x21) = 33; range(0x26, 0x73) = 77; tail set = 5.
        self.assertEqual(len(ground_items.CONSUMABLE_ITEM_IDS), 33 + 77 + 5)

    def test_quest_size(self) -> None:
        # range(0x73, 0x79) = 6; range(0x7B, 0x7D) = 2.
        self.assertEqual(len(ground_items.QUEST_ITEM_IDS), 6 + 2)

    def test_banned_includes_chest_sentinel(self) -> None:
        # AP_CHEST_SENTINEL_ITEM_ID is 0x53; it must always be banned
        # so the shuffle never picks it as a replacement.
        from worlds.digimon_world.data.addresses import AP_CHEST_SENTINEL_ITEM_ID
        self.assertIn(AP_CHEST_SENTINEL_ITEM_ID, ground_items.BANNED_ITEM_IDS)

    def test_food_exception_ids(self) -> None:
        # Rain Plant (0x79) and Steak (0x7A) are food-by-id even though
        # their ITEM_PARA sort is not SORT_FOOD.
        self.assertEqual(
            ground_items.FOOD_EXCEPTION_ITEM_IDS, frozenset({0x79, 0x7A}),
        )

    def test_consumable_quest_disjoint(self) -> None:
        # An id can't be both consumable and quest.
        overlap = ground_items.CONSUMABLE_ITEM_IDS & ground_items.QUEST_ITEM_IDS
        self.assertEqual(overlap, frozenset())


# =============================================================================
# parse_item_table
# =============================================================================


class TestParseItemTable(unittest.TestCase):

    def test_round_trip(self) -> None:
        table = _make_table({
            0x10: (500, ground_items.SORT_FOOD, True),
            0x47: (9999, ground_items.SORT_STATEVO, True),  # evo
            0x50: (300, 0x00, True),                         # heal
        })
        items = ground_items.parse_item_table(table)
        self.assertEqual(len(items), ROM_ITEM_TABLE_ENTRY_COUNT)
        self.assertEqual(items[0x10].price, 500)
        self.assertEqual(items[0x10].sort, ground_items.SORT_FOOD)
        self.assertTrue(items[0x10].dropable)
        self.assertTrue(items[0x10].is_food)
        self.assertTrue(items[0x47].is_evo)
        self.assertFalse(items[0x50].is_food)
        self.assertFalse(items[0x50].is_evo)

    def test_food_exceptions_classified_as_food(self) -> None:
        # Sort != SORT_FOOD, but id in the exception set -> still food.
        table = _make_table({0x79: (10, 0x00, True), 0x7A: (10, 0x00, True)})
        items = ground_items.parse_item_table(table)
        self.assertTrue(items[0x79].is_food)
        self.assertTrue(items[0x7A].is_food)

    def test_wrong_size_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "bytes"):
            ground_items.parse_item_table(b"\x00" * 100)


# =============================================================================
# eligible_replacement_ids
# =============================================================================


class TestEligibleReplacementIds(unittest.TestCase):
    """Filter behaviour with various option combinations."""

    def _build(self, **overrides: tuple[int, int, bool]) -> list[ground_items.ItemProps]:
        """Default landscape: a small mix of consumable / food / evo /
        quest items. ``overrides`` map id -> (price, sort, dropable)."""

        # A junk-everywhere baseline for ids 0..127.
        base: dict[int, tuple[int, int, bool]] = {}
        # Consumable, dropable, low-value heal.
        base[0x05] = (100, 0x00, True)
        # Consumable, dropable, food, low-value.
        base[0x10] = (200, ground_items.SORT_FOOD, True)
        # Consumable, dropable, food, high-value.
        base[0x11] = (5000, ground_items.SORT_FOOD, True)
        # Consumable, dropable, food-exception (id 0x79), low-value.
        base[0x79] = (50, 0x00, True)
        # Consumable, dropable, evo (sort=STATEVO, id>=0x47).
        base[0x50] = (3000, ground_items.SORT_STATEVO, True)
        # Consumable, NOT dropable -> excluded ("notQuest" filter).
        base[0x06] = (100, 0x00, False)
        # Banned (0x53 = chest sentinel).
        base[0x53] = (100, 0x00, True)
        # NOT consumable (id 0x21 is between consumable ranges).
        base[0x21] = (100, 0x00, True)
        base.update(overrides)
        return ground_items.parse_item_table(_make_table(base))

    def test_basic_pool_excludes_non_consumable_evo_quest_banned(self) -> None:
        items = self._build()
        vanilla = items[0x05]  # plain low-value consumable
        result = ground_items.eligible_replacement_ids(
            items, vanilla=vanilla,
            food_only=False, match_value=False, value_cutoff=1000,
        )
        # 0x05 / 0x10 / 0x11 / 0x79 should all be eligible (consumable,
        # dropable, not banned, not evo). 0x50 is evo — out. 0x06 is
        # not dropable — out. 0x53 is banned — out. 0x21 is not in
        # the consumable range — out.
        self.assertIn(0x05, result)
        self.assertIn(0x10, result)
        self.assertIn(0x11, result)
        self.assertIn(0x79, result)
        self.assertNotIn(0x50, result)
        self.assertNotIn(0x06, result)
        self.assertNotIn(0x53, result)
        self.assertNotIn(0x21, result)

    def test_food_only_with_food_vanilla_restricts_to_food(self) -> None:
        items = self._build()
        vanilla = items[0x10]  # food
        result = ground_items.eligible_replacement_ids(
            items, vanilla=vanilla,
            food_only=True, match_value=False, value_cutoff=1000,
        )
        # Only food entries: 0x10, 0x11, 0x79.
        for fid in (0x10, 0x11, 0x79):
            self.assertIn(fid, result)
        self.assertNotIn(0x05, result)

    def test_food_only_with_non_food_vanilla_does_nothing(self) -> None:
        items = self._build()
        vanilla = items[0x05]  # not food
        result = ground_items.eligible_replacement_ids(
            items, vanilla=vanilla,
            food_only=True, match_value=False, value_cutoff=1000,
        )
        # food_only is conditional on the vanilla being food; here it
        # isn't, so the filter is the same as food_only=False.
        self.assertIn(0x05, result)
        self.assertIn(0x10, result)
        self.assertIn(0x11, result)
        self.assertIn(0x79, result)

    def test_match_value_keeps_low_with_low(self) -> None:
        items = self._build()
        vanilla = items[0x05]  # 100 bits — low side of cutoff 1000
        result = ground_items.eligible_replacement_ids(
            items, vanilla=vanilla,
            food_only=False, match_value=True, value_cutoff=1000,
        )
        # 0x11 is 5000 bits (high side) -> excluded.
        self.assertNotIn(0x11, result)
        self.assertIn(0x05, result)
        self.assertIn(0x10, result)
        self.assertIn(0x79, result)

    def test_match_value_keeps_high_with_high(self) -> None:
        items = self._build()
        vanilla = items[0x11]  # 5000 bits — high side
        result = ground_items.eligible_replacement_ids(
            items, vanilla=vanilla,
            food_only=False, match_value=True, value_cutoff=1000,
        )
        # Only 0x11 has price >= 1000 in our pool.
        self.assertEqual(result, [0x11])

    def test_match_value_off_ignores_price(self) -> None:
        items = self._build()
        vanilla = items[0x05]  # cheap
        result = ground_items.eligible_replacement_ids(
            items, vanilla=vanilla,
            food_only=False, match_value=False, value_cutoff=1000,
        )
        self.assertIn(0x11, result)


# =============================================================================
# compute_ground_item_replacements determinism
# =============================================================================


class TestComputeGroundItemReplacements(unittest.TestCase):
    """The apply-time shuffle entry point. Determinism guaranteed by
    the caller-provided RNG."""

    def _synthetic_rom(self, vanilla_id: int) -> bytes:
        """A bytes buffer big enough to host every map-item offset, with
        ``rom[offset+1] = vanilla_id`` at every spot. We don't need a
        full BIN — only the bytes the shuffle reads at offset+1."""

        max_off = max(ROM_MAP_ITEM_OFFSETS) + 2
        buf = bytearray(max_off)
        for off in ROM_MAP_ITEM_OFFSETS:
            buf[off] = 0x74  # spawnItem opcode (cosmetic; not read)
            buf[off + 1] = vanilla_id
        return bytes(buf)

    def test_same_seed_same_replacements(self) -> None:
        # Pool of two food items so the RNG actually gets to choose.
        table = _make_table({
            0x10: (200, ground_items.SORT_FOOD, True),
            0x11: (5000, ground_items.SORT_FOOD, True),
            0x05: (100, 0x00, True),
        })
        rom = self._synthetic_rom(vanilla_id=0x05)

        a = ground_items.compute_ground_item_replacements(
            rom, random=Random(12345),
            food_only=False, match_value=False, value_cutoff=1000,
            map_item_offsets=ROM_MAP_ITEM_OFFSETS,
            item_table_user_data=table,
        )
        b = ground_items.compute_ground_item_replacements(
            rom, random=Random(12345),
            food_only=False, match_value=False, value_cutoff=1000,
            map_item_offsets=ROM_MAP_ITEM_OFFSETS,
            item_table_user_data=table,
        )
        self.assertEqual(a, b)
        self.assertEqual(set(a.keys()), set(ROM_MAP_ITEM_OFFSETS))

    def test_different_seeds_different_replacements(self) -> None:
        table = _make_table({
            0x10: (200, 0x00, True),
            0x11: (300, 0x00, True),
            0x12: (400, 0x00, True),
            0x05: (100, 0x00, True),
        })
        rom = self._synthetic_rom(vanilla_id=0x05)

        a = ground_items.compute_ground_item_replacements(
            rom, random=Random(1),
            food_only=False, match_value=False, value_cutoff=1000,
            map_item_offsets=ROM_MAP_ITEM_OFFSETS,
            item_table_user_data=table,
        )
        b = ground_items.compute_ground_item_replacements(
            rom, random=Random(2),
            food_only=False, match_value=False, value_cutoff=1000,
            map_item_offsets=ROM_MAP_ITEM_OFFSETS,
            item_table_user_data=table,
        )
        # Astronomically unlikely for two RNGs to produce identical
        # 463-element sequences from a 4-item pool.
        self.assertNotEqual(a, b)

    def test_replacements_are_in_pool(self) -> None:
        table = _make_table({
            0x10: (200, 0x00, True),
            0x11: (300, 0x00, True),
            0x05: (100, 0x00, True),
        })
        rom = self._synthetic_rom(vanilla_id=0x05)
        result = ground_items.compute_ground_item_replacements(
            rom, random=Random(7),
            food_only=False, match_value=False, value_cutoff=1000,
            map_item_offsets=ROM_MAP_ITEM_OFFSETS,
            item_table_user_data=table,
        )
        for new_id in result.values():
            self.assertIn(new_id, {0x05, 0x10, 0x11})


# =============================================================================
# Patcher contract — option ON
# =============================================================================


def _capture_patch(world: Any) -> tuple[dict[str, bytes], list[tuple[str, list[str]]]]:
    """Run ``generate_output`` and capture the resulting patch's files
    and per-instance procedure."""

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


class TestGroundItemPatcherOn(DigimonWorldTestBase):
    """Default: GroundItemRandomization is DefaultOnToggle.

    With it on, the patch must carry ``ground_items.json`` and the
    patch's procedure must include the ``shuffle_ground_items`` step.
    """

    options: ClassVar[dict[str, Any]] = {}

    def test_ground_items_params_blob_present(self) -> None:
        files, _procedure = _capture_patch(self.world)
        self.assertIn("ground_items.json", files)
        params = json.loads(files["ground_items.json"])
        # Required keys, types.
        self.assertIn("seed", params)
        self.assertIsInstance(params["seed"], int)
        self.assertIn("food_only", params)
        self.assertIsInstance(params["food_only"], bool)
        self.assertIn("match_value", params)
        self.assertIsInstance(params["match_value"], bool)
        self.assertIn("value_cutoff", params)
        self.assertIsInstance(params["value_cutoff"], int)

    def test_shuffle_ground_items_in_procedure(self) -> None:
        _files, procedure = _capture_patch(self.world)
        steps = [name for name, _args in procedure]
        self.assertIn("shuffle_ground_items", steps)
        # Must run after apply_tokens and before recalc_edc.
        self.assertLess(steps.index("apply_tokens"), steps.index("shuffle_ground_items"))
        self.assertLess(steps.index("shuffle_ground_items"), steps.index("recalc_edc"))


class TestGroundItemPatcherCustomOptions(DigimonWorldTestBase):
    """Non-default option values flow through the params blob."""

    options: ClassVar[dict[str, Any]] = {
        "ground_items_food_only": True,
        "ground_items_match_value": False,
        "ground_items_value_cutoff": 5000,
    }

    def test_params_reflect_options(self) -> None:
        files, _procedure = _capture_patch(self.world)
        params = json.loads(files["ground_items.json"])
        self.assertTrue(params["food_only"])
        self.assertFalse(params["match_value"])
        self.assertEqual(params["value_cutoff"], 5000)


# =============================================================================
# Patcher contract — option OFF
# =============================================================================


class TestGroundItemPatcherOff(DigimonWorldTestBase):
    """With the master toggle off, no params blob, no procedure step,
    every ground-item spot keeps its vanilla id."""

    options: ClassVar[dict[str, Any]] = {
        "randomize_ground_items": False,
    }

    def test_no_ground_items_params(self) -> None:
        files, procedure = _capture_patch(self.world)
        self.assertNotIn("ground_items.json", files)
        steps = [name for name, _args in procedure]
        self.assertNotIn("shuffle_ground_items", steps)


# =============================================================================
# Apply-time extension smoke test
# =============================================================================


class TestShuffleGroundItemsExtension(unittest.TestCase):
    """Smoke-test the apply-time extension method directly: feed it a
    synthetic ROM + params, confirm the returned bytes have map-item
    bytes rewritten and unrelated bytes preserved."""

    def test_rewrites_map_item_bytes_only(self) -> None:
        table = _make_table({
            0x05: (100, 0x00, True),
            0x10: (200, ground_items.SORT_FOOD, True),
        })

        # Build a synthetic ROM big enough to hold every map-item offset
        # plus the ITEM_PARA region. Mark a "canary" byte just outside
        # the map-item set to verify it's untouched.
        from worlds.digimon_world.data.addresses import (
            ROM_ITEM_TABLE_BASE,
            ROM_ITEM_TABLE_ENTRY_SIZE,
            SECTOR_SIZE_BYTES,
        )

        # Big enough to cover both the map-item offsets and the item
        # table (rounded up to sector boundary).
        size = max(
            max(ROM_MAP_ITEM_OFFSETS) + 2,
            ROM_ITEM_TABLE_BASE + ROM_ITEM_TABLE_ENTRY_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE * 2,
        )
        # Round up to next sector.
        size = ((size + SECTOR_SIZE_BYTES - 1) // SECTOR_SIZE_BYTES + 4) * SECTOR_SIZE_BYTES
        rom = bytearray(size)
        # Plant the synthetic table — write each entry at its
        # sector-aware flat offset.
        from worlds.digimon_world.data.addresses import _table_byte_to_bin_flat
        for i in range(ROM_ITEM_TABLE_ENTRY_COUNT):
            for j in range(ROM_ITEM_TABLE_ENTRY_SIZE):
                rom[_table_byte_to_bin_flat(i * ROM_ITEM_TABLE_ENTRY_SIZE + j)] = (
                    table[i * ROM_ITEM_TABLE_ENTRY_SIZE + j]
                )
        # Plant vanilla item id 0x05 at each map-item offset's +1 byte.
        for off in ROM_MAP_ITEM_OFFSETS:
            rom[off] = 0x74
            rom[off + 1] = 0x05

        # Canary byte well outside any region we touch.
        canary_off = 0
        rom[canary_off] = 0xCA

        params = {
            "seed": 42,
            "food_only": False,
            "match_value": False,
            "value_cutoff": 1000,
        }
        caller = mock.MagicMock()
        caller.get_file.return_value = json.dumps(params).encode("ascii")

        patched = rom_module.DigimonWorldPatchExtension.shuffle_ground_items(
            caller, bytes(rom), "ground_items.json",
        )

        self.assertEqual(len(patched), len(rom))
        # Canary preserved.
        self.assertEqual(patched[canary_off], 0xCA)
        # Every map-item id byte is now in {0x05, 0x10}.
        for off in ROM_MAP_ITEM_OFFSETS:
            self.assertIn(patched[off + 1], {0x05, 0x10})
        # opcode byte preserved.
        for off in ROM_MAP_ITEM_OFFSETS:
            self.assertEqual(patched[off], 0x74)
