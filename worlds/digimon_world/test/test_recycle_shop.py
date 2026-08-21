"""Tests for the Recycle Shop randomization (Phase 10).

Covers four areas:

* :class:`TestRecycleShopLocations` — the 7 AP locations register
  with the expected names and IDs in the
  :data:`worlds.digimon_world.options.RecycleShopLocations`-enabled
  pool, and don't appear when the option is off.
* :class:`TestRecycleShopTriggers` — the trigger range 904..910 lives
  in the documented gap C byte (0x001BE03E) and doesn't collide with
  any existing AP-allocated trigger.
* :class:`TestRecycleShopPatcher` — :func:`rom.write_patch` emits the
  expected token set when the option is on (extended ITEM_PARA
  entries, AP description strings, callsite patches, wrapper, jal
  hijack) and emits none of those tokens when the option is off.
* :class:`TestRecycleShopWrapper` — the 60-byte MIPS wrapper
  bytecode disassembles to the expected dispatch shape.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
import zipfile
from typing import Any, ClassVar
from unittest import mock

from worlds.Files import APTokenTypes

from .. import rom as rom_module
from ..data.addresses import (
    AP_DESC_PREFIX,
    AP_DESC_STRING_MAX_LEN,
    AP_DESC_STRINGS_BIN_OFFSET,
    AP_DESC_SUFFIX,
    AP_TRIGGER_ARRAY_BASE,
    RAM_RECYCLE_SHOP_GP_SLOT,
    RECYCLE_SHOP_AP_ITEM_ID_BASE,
    RECYCLE_SHOP_AP_ITEM_ID_COUNT,
    RECYCLE_SHOP_AP_ITEM_IDS,
    RECYCLE_SHOP_LOCATION_NAMES,
    RECYCLE_SHOP_LOCATION_RAM_BITS,
    RECYCLE_SHOP_TRIGGER_BASE,
    RECYCLE_SHOP_TRIGGER_IDS,
    RECYCLE_SHOP_VANILLA_PRICES,
    RELOC_ITEM_DESC_PTR_ADDIU_VALUE,
    RELOC_ITEM_DESC_PTR_LUI_VALUE,
    RELOC_ITEM_DESC_PTR_PATCH_SITES,
    ROM_RECYCLE_SHOP_PATCH_OFFSET,
    ROM_RECYCLE_SHOP_PATCH_VALUE,
    ROM_RECYCLE_SHOP_WRAPPER_BYTES,
    ROM_RECYCLE_SHOP_WRAPPER_OFFSET,
    ROM_RECYCLE_SHOP_WRAPPER_RAM,
    build_ap_desc_string,
    build_ap_item_para_entry,
    ext_item_para_slot_bin_offset,
)
from ..locations import RECYCLE_SHOP_LOCATION_NAMES as LOC_NAMES
from .bases import DigimonWorldTestBase


# =============================================================================
# Locations
# =============================================================================


class TestRecycleShopLocations(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"recycle_shop_locations": 1}

    def test_seven_locations_with_expected_names(self) -> None:
        self.assertEqual(len(RECYCLE_SHOP_LOCATION_NAMES), 7)
        for i, name in enumerate(RECYCLE_SHOP_LOCATION_NAMES, start=1):
            self.assertEqual(name, f"Recycle Shop #{i}")

    def test_locations_present_in_world_when_option_on(self) -> None:
        for name in RECYCLE_SHOP_LOCATION_NAMES:
            self.world.get_location(name)  # raises KeyError on miss

    def test_locations_attached_to_gear_savanna(self) -> None:
        for name in RECYCLE_SHOP_LOCATION_NAMES:
            self.assertEqual(self.world.get_location(name).parent_region.name,
                             "Gear Savanna")

    def test_location_ids_in_69_056_block(self) -> None:
        from ..locations import LOCATION_NAME_TO_ID
        for i, name in enumerate(RECYCLE_SHOP_LOCATION_NAMES):
            self.assertEqual(LOCATION_NAME_TO_ID[name], 69_056_000 + i)

    def test_locations_absent_when_option_off(self) -> None:
        # Spin up a second world with the option off and confirm none
        # of the recycle-shop locations exist in its pool.
        from worlds.digimon_world.test.bases import DigimonWorldTestBase as Base

        class _Off(Base):
            options = {"recycle_shop_locations": 0}

        instance = _Off()
        instance.world_setup()
        for name in RECYCLE_SHOP_LOCATION_NAMES:
            with self.assertRaises(KeyError, msg=f"{name} should not exist"):
                instance.world.get_location(name)


# =============================================================================
# Trigger allocation
# =============================================================================


class TestRecycleShopTriggers(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_trigger_count_matches_slot_count(self) -> None:
        self.assertEqual(len(RECYCLE_SHOP_TRIGGER_IDS), RECYCLE_SHOP_AP_ITEM_ID_COUNT)
        self.assertEqual(len(RECYCLE_SHOP_TRIGGER_IDS), 7)

    def test_triggers_consecutive_starting_at_904(self) -> None:
        self.assertEqual(RECYCLE_SHOP_TRIGGER_BASE, 904)
        self.assertEqual(
            RECYCLE_SHOP_TRIGGER_IDS,
            tuple(range(904, 911)),
        )

    def test_all_triggers_share_byte_0x1BE03E(self) -> None:
        for trig in RECYCLE_SHOP_TRIGGER_IDS:
            byte_addr = AP_TRIGGER_ARRAY_BASE + (trig // 8)
            self.assertEqual(byte_addr, 0x001BE03E,
                             f"trigger {trig} mapped to 0x{byte_addr:08X}, "
                             f"expected 0x001BE03E")

    def test_triggers_dont_collide_with_existing_ap_triggers(self) -> None:
        # Vending = 890..901, Old Fishrod = 902, Amazing Rod = 903.
        # All four sets live in bytes 0x001BE03C..0x001BE03D; the
        # recycle range starts at byte 0x001BE03E so there's no overlap.
        from ..data.addresses import (
            AMAZING_ROD_LOCATION_TRIGGER_ID,
            OLD_FISHROD_LOCATION_TRIGGER_ID,
            VENDING_MACHINES,
        )
        existing = {AMAZING_ROD_LOCATION_TRIGGER_ID,
                    OLD_FISHROD_LOCATION_TRIGGER_ID}
        for machine in VENDING_MACHINES:
            for item in machine.items:
                existing.add(item.trigger_id)
        for trig in RECYCLE_SHOP_TRIGGER_IDS:
            self.assertNotIn(trig, existing,
                             f"recycle trigger {trig} collides with an "
                             f"existing AP trigger")

    def test_location_ram_bits_table(self) -> None:
        self.assertEqual(len(RECYCLE_SHOP_LOCATION_RAM_BITS), 7)
        for i, name in enumerate(RECYCLE_SHOP_LOCATION_NAMES):
            byte_addr, bit_idx = RECYCLE_SHOP_LOCATION_RAM_BITS[name]
            trig = RECYCLE_SHOP_TRIGGER_IDS[i]
            self.assertEqual(byte_addr, AP_TRIGGER_ARRAY_BASE + (trig // 8))
            self.assertEqual(bit_idx, trig % 8)


# =============================================================================
# Helper builders
# =============================================================================


class TestRecycleShopHelpers(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_item_para_entry_layout(self) -> None:
        bs = build_ap_item_para_entry("Foobar", 1234)
        self.assertEqual(len(bs), 32)
        # Name in bytes 0..19 (NUL-padded ASCII, truncated to 14)
        self.assertEqual(bs[:6], b"Foobar")
        self.assertEqual(bs[6:20], b"\x00" * 14)
        # value (i32) at bytes 20..23
        self.assertEqual(struct.unpack_from("<i", bs, 20)[0], 1234)
        # meritValue, sortingValue, itemColor, dropable, unk all zero
        self.assertEqual(bs[24:32], b"\x00" * 8)

    def test_item_para_entry_truncates_long_names(self) -> None:
        bs = build_ap_item_para_entry("AVeryLongItemNameThatExceedsLimit", 500)
        # 14-char limit per spec
        self.assertEqual(bs[:14], b"AVeryLongItemN")
        # remaining name bytes zeroed
        self.assertEqual(bs[14:20], b"\x00" * 6)

    def test_desc_string_layout(self) -> None:
        bs = build_ap_desc_string("Tester")
        self.assertEqual(len(bs), AP_DESC_STRING_MAX_LEN)
        # Body = "From Tester's World\x00"
        body = AP_DESC_PREFIX + b"Tester" + AP_DESC_SUFFIX + b"\x00"
        self.assertEqual(bs[:len(body)], body)
        # Tail is NUL-padded
        self.assertEqual(bs[len(body):], b"\x00" * (AP_DESC_STRING_MAX_LEN - len(body)))

    def test_desc_string_truncates_long_player_names(self) -> None:
        long_name = "X" * 200
        bs = build_ap_desc_string(long_name)
        self.assertEqual(len(bs), AP_DESC_STRING_MAX_LEN)
        # Trailing NUL is preserved (renderer halts cleanly)
        self.assertEqual(bs[-1], 0)
        # Body starts with the prefix
        self.assertTrue(bs.startswith(AP_DESC_PREFIX))


# =============================================================================
# Patcher token writes
# =============================================================================


def _parse_token_blob(blob: bytes) -> list[tuple[int, int, bytes]]:
    """Return ``[(token_type, offset, data)]`` for inspection."""
    n = int.from_bytes(blob[:4], "little")
    out: list[tuple[int, int, bytes]] = []
    i = 4
    for _ in range(n):
        ttype = blob[i]
        off = int.from_bytes(blob[i + 1:i + 5], "little")
        sz = int.from_bytes(blob[i + 5:i + 9], "little")
        data = bytes(blob[i + 9:i + 9 + sz])
        out.append((ttype, off, data))
        i += 9 + sz
    return out


class _CapturedPatch:
    """Helper that runs ``world.generate_output`` under a write mock and
    returns the captured token blob as a parsed token list, plus the
    procedure list."""

    @staticmethod
    def run(world: Any) -> tuple[list[tuple[int, int, bytes]], list[Any]]:
        captured: dict[str, bytes] = {}
        procedure_holder: list[Any] = []

        def fake_write(self_patch: Any, target: str) -> None:
            with zipfile.ZipFile(target, "w") as _:
                pass
            captured.update(self_patch.files)
            procedure_holder.append(list(self_patch.procedure))

        with mock.patch.object(
            rom_module.DigimonWorldProcedurePatch, "write", fake_write,
        ), tempfile.TemporaryDirectory() as tmp_dir:
            world.generate_output(tmp_dir)

        return _parse_token_blob(captured["token_data.bin"]), procedure_holder[0]


class TestRecycleShopPatcherOn(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"recycle_shop_locations": 1}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)
        self.observed: dict[int, bytes] = {off: data for _t, off, data in self.tokens}

    def test_all_tokens_are_writes(self) -> None:
        for ttype, *_ in self.tokens:
            self.assertEqual(ttype, APTokenTypes.WRITE)

    def test_extended_item_para_entries_present(self) -> None:
        for slot in RECYCLE_SHOP_AP_ITEM_IDS:
            offset = ext_item_para_slot_bin_offset(slot)
            self.assertIn(offset, self.observed,
                          f"ext ITEM_PARA slot {slot} not patched")
            self.assertEqual(len(self.observed[offset]), 32)

    def test_extended_item_para_prices_match_vanilla_recycle_slots(self) -> None:
        for i, slot in enumerate(RECYCLE_SHOP_AP_ITEM_IDS):
            offset = ext_item_para_slot_bin_offset(slot)
            entry = self.observed[offset]
            price = struct.unpack_from("<i", entry, 20)[0]
            self.assertEqual(price, RECYCLE_SHOP_VANILLA_PRICES[i])

    def test_ap_desc_strings_present(self) -> None:
        for i in range(7):
            offset = AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN
            self.assertIn(offset, self.observed,
                          f"AP desc string {i} not patched")
            self.assertEqual(len(self.observed[offset]), AP_DESC_STRING_MAX_LEN)
            # Each desc starts with the "From " prefix
            self.assertTrue(self.observed[offset].startswith(AP_DESC_PREFIX))

    def test_callsite_patches_present_with_correct_encodings(self) -> None:
        lui_bytes = struct.pack("<I", RELOC_ITEM_DESC_PTR_LUI_VALUE)
        addiu_bytes = struct.pack("<I", RELOC_ITEM_DESC_PTR_ADDIU_VALUE)
        for lui_off, addiu_off in RELOC_ITEM_DESC_PTR_PATCH_SITES:
            self.assertIn(lui_off, self.observed)
            self.assertEqual(self.observed[lui_off], lui_bytes)
            self.assertIn(addiu_off, self.observed)
            self.assertEqual(self.observed[addiu_off], addiu_bytes)

    def test_shopsanity_wrappers_present(self) -> None:
        # Shopsanity era (2026-08-21): the recycle shop rides the shared
        # builder wrapper + extended giveItem wrapper instead of the
        # retired v1 60-B wrapper / init-epilogue wrapper.
        from ..data.addresses import (
            SHOP_AP_BUILDER_WRAPPER_BYTES,
            SHOP_AP_BUILDER_WRAPPER_OFFSET,
            SHOP_AP_GIVEITEM_EXT_BYTES,
            SHOP_AP_GIVEITEM_EXT_OFFSET,
        )
        self.assertEqual(
            self.observed[SHOP_AP_BUILDER_WRAPPER_OFFSET], SHOP_AP_BUILDER_WRAPPER_BYTES,
        )
        self.assertEqual(
            self.observed[SHOP_AP_GIVEITEM_EXT_OFFSET], SHOP_AP_GIVEITEM_EXT_BYTES,
        )

    def test_jal_hijack_targets_extended_wrapper(self) -> None:
        # Same callsite the v1 wrapper hijacked (0x800FB410), now
        # redirected to the extended giveItem wrapper.
        from ..data.addresses import SHOP_AP_GIVEITEM_JAL_VALUE
        self.assertIn(ROM_RECYCLE_SHOP_PATCH_OFFSET, self.observed)
        self.assertEqual(
            struct.unpack("<I", self.observed[ROM_RECYCLE_SHOP_PATCH_OFFSET])[0],
            SHOP_AP_GIVEITEM_JAL_VALUE,
        )

    def test_retired_v1_wrapper_tokens_absent(self) -> None:
        # The v1 60-B giveItem wrapper and the entry_count==7 init
        # epilogue wrapper are retired — their bytes must never be
        # emitted again. Their Cave6 space was freed; the init wrapper's
        # region has since been legitimately reclaimed by the icon-id
        # table (2026-08-21), so the check is "not the retired BYTES",
        # not "offset untouched".
        from ..data.addresses import (
            ROM_RECYCLE_SHOP_INIT_PATCH_OFFSET,
            ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES,
            ROM_RECYCLE_SHOP_INIT_WRAPPER_OFFSET,
        )
        self.assertNotIn(ROM_RECYCLE_SHOP_WRAPPER_OFFSET, self.observed)
        self.assertNotEqual(
            self.observed.get(ROM_RECYCLE_SHOP_INIT_WRAPPER_OFFSET),
            ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES,
        )
        self.assertNotIn(ROM_RECYCLE_SHOP_INIT_PATCH_OFFSET, self.observed)
        # ... and no token anywhere carries the old jal value.
        old_jal = struct.pack("<I", ROM_RECYCLE_SHOP_PATCH_VALUE)
        for _t, _off, data in self.tokens:
            self.assertNotEqual(data, old_jal)

    def test_relocate_extension_in_procedure(self) -> None:
        names = [step[0] for step in self.procedure]
        self.assertIn("relocate_item_desc_ptr", names)
        # Order: must come after apply_tokens and before recalc_edc
        apply_idx = names.index("apply_tokens")
        reloc_idx = names.index("relocate_item_desc_ptr")
        edc_idx = names.index("recalc_edc")
        self.assertLess(apply_idx, reloc_idx)
        self.assertLess(reloc_idx, edc_idx)


class TestRecycleShopPatcherOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"recycle_shop_locations": 0}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)
        self.observed_offsets = {off for _t, off, _d in self.tokens}

    def test_no_recycle_shop_tokens(self) -> None:
        self.assertNotIn(ROM_RECYCLE_SHOP_WRAPPER_OFFSET, self.observed_offsets)
        self.assertNotIn(ROM_RECYCLE_SHOP_PATCH_OFFSET, self.observed_offsets)
        # No 32-byte ext ITEM_PARA entries. (Slot 128's offset equals
        # the always-on relocation's 960-byte seed zero-fill token, so
        # check write LENGTHS, not offset presence.)
        for slot in RECYCLE_SHOP_AP_ITEM_IDS:
            slot_offset = ext_item_para_slot_bin_offset(slot)
            entry_writes = [
                data for _t, off, data in self.tokens
                if off == slot_offset and len(data) == 32
            ]
            self.assertEqual(entry_writes, [],
                             f"unexpected ext entry write for slot {slot}")
        for i in range(7):
            self.assertNotIn(
                AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN,
                self.observed_offsets,
            )
        for lui_off, addiu_off in RELOC_ITEM_DESC_PTR_PATCH_SITES:
            self.assertNotIn(lui_off, self.observed_offsets)
            self.assertNotIn(addiu_off, self.observed_offsets)

    def test_no_relocate_extension_in_procedure(self) -> None:
        names = [step[0] for step in self.procedure]
        self.assertNotIn("relocate_item_desc_ptr", names)


# =============================================================================
# Wrapper bytecode shape (RETIRED v1 wrapper — constants only)
# =============================================================================


class TestRecycleShopWrapper(DigimonWorldTestBase):
    """The v1 60-B wrapper is RETIRED (2026-08-21, superseded by the
    shopsanity extended giveItem wrapper) and never emitted anymore —
    these tests only pin the historical constants so the freed Cave6
    region's documentation stays accurate."""

    options: ClassVar[dict[str, Any]] = {}

    def test_wrapper_size(self) -> None:
        # 15 instructions × 4 bytes each.
        self.assertEqual(len(ROM_RECYCLE_SHOP_WRAPPER_BYTES), 60)

    def test_wrapper_starts_with_at_minus_base(self) -> None:
        # First instruction: addiu $at, $a0, -RECYCLE_SHOP_AP_ITEM_ID_BASE
        # opcode 0x09 (addiu), rs=$a0(4), rt=$at(1), imm=signed 16
        first = struct.unpack_from("<I", ROM_RECYCLE_SHOP_WRAPPER_BYTES, 0)[0]
        expected = 0x24810000 | ((-RECYCLE_SHOP_AP_ITEM_ID_BASE) & 0xFFFF)
        self.assertEqual(first, expected,
                         f"first instr 0x{first:08X} != expected 0x{expected:08X}")

    def test_wrapper_jal_settrigger_present(self) -> None:
        # jal 0x801065C0 = 0x0C000000 | ((0x801065C0 >> 2) & 0x03FFFFFF)
        SETTRIGGER_RAM = 0x801065C0
        jal_settrigger = 0x0C000000 | ((SETTRIGGER_RAM >> 2) & 0x03FFFFFF)
        words = struct.unpack(
            f"<{len(ROM_RECYCLE_SHOP_WRAPPER_BYTES) // 4}I",
            ROM_RECYCLE_SHOP_WRAPPER_BYTES,
        )
        self.assertIn(jal_settrigger, words,
                      "wrapper missing jal setTrigger")

    def test_wrapper_tail_call_giveitem(self) -> None:
        # Last two instructions: j 0x800C5240, nop
        GIVEITEM_RAM = 0x800C5240
        j_giveitem = 0x08000000 | ((GIVEITEM_RAM >> 2) & 0x03FFFFFF)
        last_two = struct.unpack_from("<II", ROM_RECYCLE_SHOP_WRAPPER_BYTES, 52)
        self.assertEqual(last_two, (j_giveitem, 0x00000000))

    def test_jal_hijack_value_targets_wrapper_ram(self) -> None:
        expected = 0x0C000000 | ((ROM_RECYCLE_SHOP_WRAPPER_RAM >> 2) & 0x03FFFFFF)
        self.assertEqual(ROM_RECYCLE_SHOP_PATCH_VALUE, expected)


# =============================================================================
# Constants sanity (lightweight smoke for module load)
# =============================================================================


class TestRecycleShopConstants(unittest.TestCase):
    def test_gp_slot_address(self) -> None:
        # Per RE: gp = 0x8013BB2C, displacement = 0x6BC4
        # bare offset = (0x8013BB2C - 0x6BC4) - 0x80000000 = 0x00134F68
        self.assertEqual(RAM_RECYCLE_SHOP_GP_SLOT, 0x00134F68)

    def test_ap_item_id_range(self) -> None:
        self.assertEqual(RECYCLE_SHOP_AP_ITEM_ID_BASE, 128)
        self.assertEqual(RECYCLE_SHOP_AP_ITEM_ID_COUNT, 7)
        self.assertEqual(
            RECYCLE_SHOP_AP_ITEM_IDS,
            (128, 129, 130, 131, 132, 133, 134),
        )

    def test_locations_module_exposes_names(self) -> None:
        # The locations module re-exports the canonical name tuple.
        self.assertEqual(LOC_NAMES, RECYCLE_SHOP_LOCATION_NAMES)
