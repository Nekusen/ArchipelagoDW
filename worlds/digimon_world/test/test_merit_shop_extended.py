"""Tests for the Merit Shop multi-slot AP randomization.

Covers four areas:

* :class:`TestMeritShopLocations` — the 14 AP locations register with
  the expected names, IDs, and region (``Geko Swamp``) when
  :class:`worlds.digimon_world.options.MeritShopLocations` is on, and
  don't appear when it's off.
* :class:`TestMeritShopTriggers` — the trigger range 912..925 lives in
  the documented gap (bytes 0x001BE03F + 0x001BE040) and doesn't
  collide with anything in :data:`LOCATION_RAM_BITS` or with the
  Meramon-tunnel danger zone.
* :class:`TestMeritShopPatcherOn` / :class:`TestMeritShopPatcherOff` —
  :func:`rom.write_patch` emits the expected token set when the option
  is on (14 extended ITEM_PARA entries with non-zero merit prices,
  14 AP description strings, vanilla-item meritValue zero-outs for all
  14 vanilla entries, extended wrapper, jal override, scan-loop bound
  patch); emits none of those tokens when the option is off, and
  leaves the always-on N=1 merit wrapper untouched.
* :class:`TestMeritShopExtendedWrapper` — the 572-byte wrapper bytecode
  decode-verifies against the 15-entry dispatch shape.
* :class:`TestExtSeedSegment` and friends — the ext slots' seed-block
  staging under the always-on ITEM_PARA 256-slot relocation.

**Relocated-table era**: all ext slots 128..157 live at natural
positions in the relocated 256-slot ITEM_PARA table (heap-claimed
region), staged via the .bin-backed EXT_ITEM_PARA seed block at RAM
0x80096800 and copied in by the boot seed hook. The Cave6
multi-segment architecture (freed-desc + Cave6 ext + scan/name/row/
deduct teleport wrappers, ``docs/item_para_cave6_multisegment.md``)
is retired; see ``test_item_para_relocation.py`` for the relocation
machinery itself.
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
    AP_TRIGGER_ARRAY_BASE,
    ITEM_PARA_MERIT_VALUE_OFFSET,
    MERIT_AP_DESC_STRINGS_BIN_OFFSET,
    MERIT_SHOP_AP_ITEM_ID_BASE,
    MERIT_SHOP_AP_ITEM_ID_COUNT,
    MERIT_SHOP_AP_ITEM_IDS,
    MERIT_SHOP_AP_ITEM_ID_LAST,
    MERIT_SHOP_EXT_DISPATCH,
    MERIT_SHOP_LOCATION_NAMES,
    MERIT_SHOP_LOCATION_RAM_BITS,
    MERIT_SHOP_TRIGGER_BASE,
    MERIT_SHOP_TRIGGER_IDS,
    MERIT_SHOP_VANILLA_ENTRIES,
    RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE,
    ROM_ITEM_TABLE_ENTRY_SIZE,
    ROM_MERIT_SCAN_BOUND_OFFSET,
    ROM_MERIT_SCAN_BOUND_VALUE,
    ROM_MERIT_SHOP_EXT_PATCH_VALUE,
    ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
    ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET,
    ROM_MERIT_SHOP_EXT_WRAPPER_RAM,
    ROM_MERIT_SHOP_PATCH_OFFSET,
    ROM_MERIT_SHOP_PATCH_VALUE,
    _table_byte_to_bin_flat,
    ext_item_para_slot_bin_offset,
)
from ..locations import MERIT_SHOP_LOCATION_NAMES as LOC_NAMES
from .bases import DigimonWorldTestBase


# =============================================================================
# Locations
# =============================================================================


class TestMeritShopLocations(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"merit_shop_locations": 1}

    def test_fourteen_locations_with_expected_names(self) -> None:
        self.assertEqual(len(MERIT_SHOP_LOCATION_NAMES), 14)
        for i, name in enumerate(MERIT_SHOP_LOCATION_NAMES, start=1):
            self.assertEqual(name, f"Merit Shop #{i}")

    def test_locations_present_in_world_when_option_on(self) -> None:
        for name in MERIT_SHOP_LOCATION_NAMES:
            self.world.get_location(name)  # raises KeyError on miss

    def test_locations_attached_to_geko_swamp(self) -> None:
        # Volume Villa is modeled as part of Geko Swamp, matching the
        # existing Amazing Rod Pickup location's placement.
        for name in MERIT_SHOP_LOCATION_NAMES:
            self.assertEqual(
                self.world.get_location(name).parent_region.name,
                "Geko Swamp",
            )

    def test_location_ids_in_69_057_block(self) -> None:
        from ..locations import LOCATION_NAME_TO_ID
        for i, name in enumerate(MERIT_SHOP_LOCATION_NAMES):
            self.assertEqual(LOCATION_NAME_TO_ID[name], 69_057_000 + i)

    def test_locations_absent_when_option_off(self) -> None:
        from worlds.digimon_world.test.bases import DigimonWorldTestBase as Base

        class _Off(Base):
            options = {"merit_shop_locations": 0}

        instance = _Off()
        instance.world_setup()
        for name in MERIT_SHOP_LOCATION_NAMES:
            with self.assertRaises(KeyError, msg=f"{name} should not exist"):
                instance.world.get_location(name)


# =============================================================================
# Trigger allocation
# =============================================================================


class TestMeritShopTriggers(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_trigger_count_matches_slot_count(self) -> None:
        self.assertEqual(len(MERIT_SHOP_TRIGGER_IDS), MERIT_SHOP_AP_ITEM_ID_COUNT)
        self.assertEqual(len(MERIT_SHOP_TRIGGER_IDS), 14)

    def test_triggers_consecutive_starting_at_912(self) -> None:
        self.assertEqual(MERIT_SHOP_TRIGGER_BASE, 912)
        self.assertEqual(
            MERIT_SHOP_TRIGGER_IDS,
            tuple(range(912, 926)),
        )

    def test_triggers_land_in_documented_gap_bytes(self) -> None:
        # 912..919 -> byte 0x001BE03F, 920 -> byte 0x001BE040 bit 0
        bytes_used = {
            AP_TRIGGER_ARRAY_BASE + (t // 8) for t in MERIT_SHOP_TRIGGER_IDS
        }
        self.assertEqual(bytes_used, {0x001BE03F, 0x001BE040})

    def test_triggers_stay_clear_of_meramon_tunnel(self) -> None:
        for trig in MERIT_SHOP_TRIGGER_IDS:
            byte_addr = AP_TRIGGER_ARRAY_BASE + (trig // 8)
            self.assertLess(
                byte_addr,
                RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE,
                f"trigger {trig} (byte 0x{byte_addr:08X}) overflows into "
                f"the Meramon tunnel state machine",
            )

    def test_triggers_dont_collide_with_recycle_or_other_ap_triggers(self) -> None:
        # Recycle shop = 904..910, Vending = 890..901, Old Fishrod = 902,
        # Amazing Rod = 903. None of those land in our 912..925 band.
        from ..data.addresses import (
            AMAZING_ROD_LOCATION_TRIGGER_ID,
            OLD_FISHROD_LOCATION_TRIGGER_ID,
            RECYCLE_SHOP_TRIGGER_IDS,
            VENDING_MACHINES,
        )
        existing = {AMAZING_ROD_LOCATION_TRIGGER_ID,
                    OLD_FISHROD_LOCATION_TRIGGER_ID}
        for machine in VENDING_MACHINES:
            for item in machine.items:
                existing.add(item.trigger_id)
        for trig in RECYCLE_SHOP_TRIGGER_IDS:
            existing.add(trig)
        for trig in MERIT_SHOP_TRIGGER_IDS:
            self.assertNotIn(trig, existing,
                             f"merit trigger {trig} collides with an "
                             f"existing AP trigger")

    def test_location_ram_bits_table(self) -> None:
        self.assertEqual(len(MERIT_SHOP_LOCATION_RAM_BITS), 14)
        for i, name in enumerate(MERIT_SHOP_LOCATION_NAMES):
            byte_addr, bit_idx = MERIT_SHOP_LOCATION_RAM_BITS[name]
            trig = MERIT_SHOP_TRIGGER_IDS[i]
            self.assertEqual(byte_addr, AP_TRIGGER_ARRAY_BASE + (trig // 8))
            self.assertEqual(bit_idx, trig % 8)


# =============================================================================
# Constant sanity
# =============================================================================


class TestMeritShopConstants(unittest.TestCase):
    def test_slot_range(self) -> None:
        self.assertEqual(MERIT_SHOP_AP_ITEM_ID_BASE, 135)
        self.assertEqual(MERIT_SHOP_AP_ITEM_ID_COUNT, 14)
        self.assertEqual(MERIT_SHOP_AP_ITEM_ID_LAST, 148)
        self.assertEqual(
            MERIT_SHOP_AP_ITEM_IDS,
            tuple(range(135, 149)),
        )

    def test_slot_range_fits_the_seed_segment(self) -> None:
        # All 14 merit slots live in the single EXT_ITEM_PARA seed
        # segment (relocated-table staging) — no freed-desc / Cave6
        # split anymore.
        from ..data.addresses import (
            EXT_ITEM_PARA_SEED_SLOT_BASE,
            EXT_ITEM_PARA_SEED_SLOT_LAST,
        )
        for slot in range(MERIT_SHOP_AP_ITEM_ID_BASE, MERIT_SHOP_AP_ITEM_ID_LAST + 1):
            self.assertGreaterEqual(slot, EXT_ITEM_PARA_SEED_SLOT_BASE)
            self.assertLessEqual(slot, EXT_ITEM_PARA_SEED_SLOT_LAST)

    def test_slots_follow_recycle_range(self) -> None:
        from ..data.addresses import (
            RECYCLE_SHOP_AP_ITEM_ID_BASE,
            RECYCLE_SHOP_AP_ITEM_ID_COUNT,
        )
        self.assertEqual(
            MERIT_SHOP_AP_ITEM_ID_BASE,
            RECYCLE_SHOP_AP_ITEM_ID_BASE + RECYCLE_SHOP_AP_ITEM_ID_COUNT,
        )

    def test_vanilla_entries_match_count(self) -> None:
        # All 14 vanilla entries become AP locations now that the
        # Cave6 ext segment provides slots 144..148.
        self.assertEqual(len(MERIT_SHOP_VANILLA_ENTRIES), 14)
        self.assertEqual(
            len(MERIT_SHOP_VANILLA_ENTRIES), MERIT_SHOP_AP_ITEM_ID_COUNT,
        )
        # All vanilla slot ids are in the canonical 128-entry range.
        for slot_id, _name, _merit in MERIT_SHOP_VANILLA_ENTRIES:
            self.assertLess(slot_id, 128)

    def test_amazing_rod_in_vanilla_entries(self) -> None:
        # Amazing rod (slot 117) is one of the 14 vanilla merit-shop
        # entries we zero out. It's *also* already zeroed by the v1
        # always-on patcher; the duplicate write is idempotent.
        slot_ids = {entry[0] for entry in MERIT_SHOP_VANILLA_ENTRIES}
        self.assertIn(0x75, slot_ids)

    def test_scan_bound_encoding(self) -> None:
        # sltiu $r1, $r5, 0x95 = (0x0B << 26) | (5 << 21) | (1 << 16) | 0x95
        # (= scan covers slots 0..148; merit shop's last AP slot is 148).
        expected = (0x0B << 26) | (5 << 21) | (1 << 16) | (MERIT_SHOP_AP_ITEM_ID_LAST + 1)
        self.assertEqual(ROM_MERIT_SCAN_BOUND_VALUE, expected)
        # And specifically: 0x2CA10095.
        self.assertEqual(ROM_MERIT_SCAN_BOUND_VALUE, 0x2CA10095)

    def test_ext_patch_value_targets_extended_wrapper(self) -> None:
        expected = (
            0x0C000000 | ((ROM_MERIT_SHOP_EXT_WRAPPER_RAM >> 2) & 0x03FFFFFF)
        )
        self.assertEqual(ROM_MERIT_SHOP_EXT_PATCH_VALUE, expected)
        # The override must point somewhere *different* from the v1
        # wrapper target (= ROM_MERIT_SHOP_PATCH_VALUE).
        self.assertNotEqual(ROM_MERIT_SHOP_EXT_PATCH_VALUE, ROM_MERIT_SHOP_PATCH_VALUE)

    def test_locations_module_exposes_names(self) -> None:
        self.assertEqual(LOC_NAMES, MERIT_SHOP_LOCATION_NAMES)


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
    @staticmethod
    def run(world: Any) -> tuple[
        list[tuple[int, int, bytes]],
        list[Any],
    ]:
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


class TestMeritShopPatcherOn(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"merit_shop_locations": 1}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)
        # Note: the merit-shop and v1 always-on patcher both write the
        # 4-byte ROM_MERIT_SHOP_PATCH_OFFSET site. ``observed_last``
        # captures the final value at each offset (insertion-order
        # iteration); ``observed_all`` captures every value written.
        self.observed_last: dict[int, bytes] = {}
        self.observed_all: list[tuple[int, bytes]] = []
        for _t, off, data in self.tokens:
            self.observed_last[off] = data
            self.observed_all.append((off, data))

    def test_all_tokens_are_writes(self) -> None:
        for ttype, *_ in self.tokens:
            self.assertEqual(ttype, APTokenTypes.WRITE)

    def test_extended_item_para_entries_present(self) -> None:
        for slot in MERIT_SHOP_AP_ITEM_IDS:
            offset = ext_item_para_slot_bin_offset(slot)
            self.assertIn(offset, self.observed_last,
                          f"ext ITEM_PARA slot {slot} not patched")
            self.assertEqual(len(self.observed_last[offset]), 32)

    def test_extended_item_para_merit_values_match_vanilla(self) -> None:
        # Each AP slot's ``meritValue`` field (bytes 24..25) must equal
        # the vanilla merit price of the slot it replaces — so the
        # shop's scan picks it up at the same display cost.
        for i, slot in enumerate(MERIT_SHOP_AP_ITEM_IDS):
            offset = ext_item_para_slot_bin_offset(slot)
            entry = self.observed_last[offset]
            merit = struct.unpack_from(
                "<h", entry, ITEM_PARA_MERIT_VALUE_OFFSET,
            )[0]
            _vanilla_id, _vanilla_name, expected = MERIT_SHOP_VANILLA_ENTRIES[i]
            self.assertEqual(
                merit, expected,
                f"slot {slot} meritValue={merit} != vanilla {expected}",
            )

    def test_extended_item_para_count_matches_ap_slot_count(self) -> None:
        # Exactly MERIT_SHOP_AP_ITEM_ID_COUNT (= 14) extended slots get
        # 32-byte entry writes in the EXT_ITEM_PARA seed block.
        written_slots = sum(
            1 for slot in MERIT_SHOP_AP_ITEM_IDS
            if len(self.observed_last.get(
                ext_item_para_slot_bin_offset(slot), b"")) == 32
        )
        self.assertEqual(written_slots, MERIT_SHOP_AP_ITEM_ID_COUNT)
        # Defensive: no 32-byte entry for slots beyond 148 (headroom
        # reserved for future shops in the seed block).
        for slot in range(149, 158):
            self.assertNotEqual(
                len(self.observed_last.get(
                    ext_item_para_slot_bin_offset(slot), b"")), 32,
                f"slot {slot} entry write not expected from merit shop",
            )

    def test_merit_ap_desc_strings_present(self) -> None:
        for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT):
            offset = MERIT_AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN
            self.assertIn(offset, self.observed_last,
                          f"merit AP desc string {i} not patched")
            self.assertEqual(
                len(self.observed_last[offset]), AP_DESC_STRING_MAX_LEN,
            )
            self.assertTrue(self.observed_last[offset].startswith(AP_DESC_PREFIX))

    def test_vanilla_merit_values_zeroed(self) -> None:
        for vanilla_id, _name, vanilla_merit in MERIT_SHOP_VANILLA_ENTRIES:
            merit_offset = _table_byte_to_bin_flat(
                vanilla_id * ROM_ITEM_TABLE_ENTRY_SIZE
                + ITEM_PARA_MERIT_VALUE_OFFSET,
            )
            # Find the LAST token written at this offset — the merit-shop
            # zero-out should be the final word, even if the always-on
            # v1 patcher wrote something here first (it does for slot 117).
            writes = [
                data for off, data in self.observed_all if off == merit_offset
            ]
            self.assertTrue(writes,
                            f"slot {vanilla_id} meritValue offset never written")
            self.assertEqual(writes[-1], b"\x00\x00",
                             f"slot {vanilla_id} meritValue final write "
                             f"{writes[-1]!r} != b'\\x00\\x00' "
                             f"(vanilla was {vanilla_merit})")

    def test_extended_wrapper_present(self) -> None:
        self.assertIn(ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET, self.observed_last)
        self.assertEqual(
            self.observed_last[ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET],
            ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
        )

    def test_jal_hijack_overridden_to_extended_wrapper(self) -> None:
        # The always-on v1 patcher writes ROM_MERIT_SHOP_PATCH_VALUE at
        # ROM_MERIT_SHOP_PATCH_OFFSET; we must override that with
        # ROM_MERIT_SHOP_EXT_PATCH_VALUE. Check the FINAL value.
        self.assertIn(ROM_MERIT_SHOP_PATCH_OFFSET, self.observed_last)
        final = struct.unpack(
            "<I", self.observed_last[ROM_MERIT_SHOP_PATCH_OFFSET],
        )[0]
        self.assertEqual(final, ROM_MERIT_SHOP_EXT_PATCH_VALUE,
                         f"final jal hijack 0x{final:08X} != extended "
                         f"target 0x{ROM_MERIT_SHOP_EXT_PATCH_VALUE:08X}")
        # And there should be 2 writes at that offset (v1 first, then
        # our override).
        writes_at_jal = [
            data for off, data in self.observed_all if off == ROM_MERIT_SHOP_PATCH_OFFSET
        ]
        self.assertEqual(len(writes_at_jal), 2,
                         f"expected 2 writes at jal site, got {len(writes_at_jal)}")

    def test_scan_loop_bound_patch_present(self) -> None:
        self.assertIn(ROM_MERIT_SCAN_BOUND_OFFSET, self.observed_last)
        final = struct.unpack(
            "<I", self.observed_last[ROM_MERIT_SCAN_BOUND_OFFSET],
        )[0]
        self.assertEqual(final, ROM_MERIT_SCAN_BOUND_VALUE)

    def test_relocate_extension_runs(self) -> None:
        names = [step[0] for step in self.procedure]
        self.assertIn("relocate_item_desc_ptr", names)


class TestMeritShopPatcherOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"merit_shop_locations": 0}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)
        self.observed_offsets = {off for _t, off, _d in self.tokens}

    def test_no_extended_wrapper_token(self) -> None:
        self.assertNotIn(ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET, self.observed_offsets)

    def test_no_scan_loop_bound_patch(self) -> None:
        self.assertNotIn(ROM_MERIT_SCAN_BOUND_OFFSET, self.observed_offsets)

    def test_no_extended_item_para_writes(self) -> None:
        for slot in MERIT_SHOP_AP_ITEM_IDS:
            self.assertNotIn(
                ext_item_para_slot_bin_offset(slot), self.observed_offsets,
            )

    def test_no_merit_ap_desc_strings(self) -> None:
        for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT):
            self.assertNotIn(
                MERIT_AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN,
                self.observed_offsets,
            )

    def test_v1_jal_hijack_remains_n1_target(self) -> None:
        # The merit-shop jal-hijack offset *is* still written by the v1
        # always-on patcher, but with the N=1 wrapper target.
        writes_at_jal: list[bytes] = []
        for _t, off, data in self.tokens:
            if off == ROM_MERIT_SHOP_PATCH_OFFSET:
                writes_at_jal.append(data)
        self.assertEqual(len(writes_at_jal), 1)
        final = struct.unpack("<I", writes_at_jal[0])[0]
        self.assertEqual(final, ROM_MERIT_SHOP_PATCH_VALUE,
                         "v1 jal hijack should target N=1 wrapper when "
                         "MeritShopLocations is off")

    def test_no_merit_shop_meritvalue_zero_outs_beyond_v1(self) -> None:
        # The v1 always-on patcher zeroes slot 117 (Amazing rod) — that
        # single zero write is expected. No OTHER vanilla merit slot
        # should be zeroed when the option is off.
        amazing_rod_merit_offset = _table_byte_to_bin_flat(
            0x75 * ROM_ITEM_TABLE_ENTRY_SIZE + ITEM_PARA_MERIT_VALUE_OFFSET,
        )
        for vanilla_id, _name, _merit in MERIT_SHOP_VANILLA_ENTRIES:
            if vanilla_id == 0x75:
                continue  # zeroed by v1 patcher; not a regression
            merit_offset = _table_byte_to_bin_flat(
                vanilla_id * ROM_ITEM_TABLE_ENTRY_SIZE
                + ITEM_PARA_MERIT_VALUE_OFFSET,
            )
            self.assertNotIn(
                merit_offset, self.observed_offsets,
                f"slot {vanilla_id} unexpectedly zeroed with option off",
            )
        # And the Amazing Rod offset is in the expected set.
        self.assertIn(amazing_rod_merit_offset, self.observed_offsets)


# =============================================================================
# Extended wrapper bytecode shape
# =============================================================================


class TestMeritShopExtendedWrapper(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    EXPECTED_SIZE: ClassVar[int] = (38 + 7 * 15) * 4  # 572 B for N=15

    def test_wrapper_size(self) -> None:
        self.assertEqual(len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES), self.EXPECTED_SIZE)

    def test_dispatch_table_size(self) -> None:
        # 1 (slot 83) + 14 (slots 135..148) = 15.
        self.assertEqual(len(MERIT_SHOP_EXT_DISPATCH), 15)

    def test_dispatch_first_entry_is_amazing_rod(self) -> None:
        # The v1 ``Amazing Rod Pickup`` slot stays as a 10th merit-shop
        # row even when the option is on — it's the first dispatch
        # entry, mirroring MERIT_SHOP_DISPATCH for the option-off path.
        from ..data.addresses import (
            AMAZING_ROD_LOCATION_TRIGGER_ID,
            AP_CHEST_SENTINEL_ITEM_ID,
        )
        self.assertEqual(
            MERIT_SHOP_EXT_DISPATCH[0],
            (AP_CHEST_SENTINEL_ITEM_ID, AMAZING_ROD_LOCATION_TRIGGER_ID),
        )

    def test_dispatch_extended_entries_match_slot_ranges(self) -> None:
        # Entries 1..14 map slot 135+i to trigger 912+i for i in 0..13.
        for i in range(14):
            entry_slot, entry_trig = MERIT_SHOP_EXT_DISPATCH[1 + i]
            self.assertEqual(entry_slot, MERIT_SHOP_AP_ITEM_ID_BASE + i)
            self.assertEqual(entry_trig, MERIT_SHOP_TRIGGER_BASE + i)

    def test_per_entry_addiu_at_encoded_correctly(self) -> None:
        # For each dispatch entry, the first per-entry instruction is
        # ``addiu $at, $0, item_id`` = 0x24010000 | item_id.
        words = struct.unpack(
            f"<{len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) // 4}I",
            ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
        )
        # Per-entry blocks start at word index 4 (after 4 prologue
        # instructions), 7 instructions per block.
        for i, (item_id, _trig) in enumerate(MERIT_SHOP_EXT_DISPATCH):
            w = words[4 + i * 7]
            self.assertEqual(w, 0x24010000 | (item_id & 0xFFFF),
                             f"dispatch[{i}] addiu word 0x{w:08X} != expected")

    def test_per_entry_addiu_a0_encodes_trigger(self) -> None:
        # The 5th instruction per block (index 4 within the block, after
        # bne + nop + jal) is ``addiu $a0, $0, trigger_id`` = the
        # delay-slot instruction passing the trigger to setTrigger.
        # = 0x24040000 | trigger_id.
        words = struct.unpack(
            f"<{len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) // 4}I",
            ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
        )
        for i, (_id, trig) in enumerate(MERIT_SHOP_EXT_DISPATCH):
            w = words[4 + i * 7 + 4]
            self.assertEqual(w, 0x24040000 | (trig & 0xFFFF),
                             f"dispatch[{i}] addiu $a0 word 0x{w:08X} "
                             f"!= expected for trigger {trig}")

    def test_jal_settrigger_present_per_entry(self) -> None:
        # Each block's 4th instruction (index 3) is ``jal 0x801065C0``.
        SETTRIGGER_RAM = 0x801065C0
        jal_settrigger = 0x0C000000 | ((SETTRIGGER_RAM >> 2) & 0x03FFFFFF)
        words = struct.unpack(
            f"<{len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) // 4}I",
            ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
        )
        for i in range(len(MERIT_SHOP_EXT_DISPATCH)):
            w = words[4 + i * 7 + 3]
            self.assertEqual(w, jal_settrigger,
                             f"dispatch[{i}] jal-setTrigger 0x{w:08X}")

    def test_give_item_path_tail_call(self) -> None:
        # After all per-entry blocks (at word index 4 + 7*N), the
        # 4-word stack-restore sequence is followed by
        # ``j 0x800C5240; nop`` — the tail-call to vanilla giveItem.
        GIVEITEM_RAM = 0x800C5240
        j_giveitem = 0x08000000 | ((GIVEITEM_RAM >> 2) & 0x03FFFFFF)
        words = struct.unpack(
            f"<{len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) // 4}I",
            ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
        )
        n = len(MERIT_SHOP_EXT_DISPATCH)
        # give_item path = prologue(4) + per_entry(7*N) + lw/lw/lw/addiu(4) = 4 + 7N + 4
        # The j giveItem is the 5th instruction of give_item = base + 4.
        gi_base = 4 + 7 * n
        self.assertEqual(words[gi_base + 4], j_giveitem)
        self.assertEqual(words[gi_base + 5], 0)  # nop delay slot

    def test_wrapper_fits_in_cave6(self) -> None:
        from ..data.addresses import _CAVE6_END_RAM
        end_ram = ROM_MERIT_SHOP_EXT_WRAPPER_RAM + len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES)
        self.assertLessEqual(end_ram, _CAVE6_END_RAM)


# =============================================================================
# Ext-slot seed segment (relocated-table era; replaces Cave6 multi-segment)
# =============================================================================


class TestExtSeedSegment(unittest.TestCase):
    """EXT_ITEM_PARA seed block + single-segment ext-slot routing.

    Migrated from the retired Cave6 multi-segment coverage: the ext
    slots now live at natural positions in the relocated 256-slot
    table, staged via ONE contiguous .bin-backed seed block (which
    reuses the retired Cave6 ext segment's footprint).
    """

    def test_seed_segment_size_and_alignment(self) -> None:
        from ..data.addresses import (
            EXT_ITEM_PARA_SEED_RAM,
            EXT_ITEM_PARA_SEED_SIZE,
            EXT_ITEM_PARA_SEED_SLOT_BASE,
            EXT_ITEM_PARA_SEED_SLOT_COUNT,
            EXT_ITEM_PARA_SEED_SLOT_LAST,
        )
        # Aligned to a Mode2/2352 sector boundary (sector 148351 starts
        # at RAM 0x80096800) so the 960-byte zero-fill token is a flat
        # single-sector write.
        self.assertEqual(EXT_ITEM_PARA_SEED_RAM, 0x80096800)
        self.assertEqual(EXT_ITEM_PARA_SEED_SLOT_BASE, 128)
        self.assertEqual(EXT_ITEM_PARA_SEED_SLOT_COUNT, 30)
        self.assertEqual(EXT_ITEM_PARA_SEED_SLOT_LAST, 157)
        self.assertEqual(
            EXT_ITEM_PARA_SEED_SIZE, EXT_ITEM_PARA_SEED_SLOT_COUNT * 32,
        )
        self.assertLessEqual(
            EXT_ITEM_PARA_SEED_RAM + EXT_ITEM_PARA_SEED_SIZE, 0x80097000,
        )

    def test_ext_slot_helper_is_single_segment(self) -> None:
        from ..data.addresses import (
            EXT_ITEM_PARA_SEED_BIN_OFFSET,
            EXT_ITEM_PARA_SEED_SLOT_LAST,
            ext_item_para_slot_bin_offset,
        )
        # Slot 128 = seed base; every subsequent slot is contiguous
        # (+32) — no freed-desc / Cave6 split anymore.
        self.assertEqual(
            ext_item_para_slot_bin_offset(128), EXT_ITEM_PARA_SEED_BIN_OFFSET,
        )
        for slot in range(129, EXT_ITEM_PARA_SEED_SLOT_LAST + 1):
            self.assertEqual(
                ext_item_para_slot_bin_offset(slot),
                ext_item_para_slot_bin_offset(slot - 1) + 32,
                f"slot {slot} not contiguous with slot {slot - 1}",
            )
        # Out-of-range slots reject on both sides.
        with self.assertRaises(ValueError):
            ext_item_para_slot_bin_offset(127)
        with self.assertRaises(ValueError):
            ext_item_para_slot_bin_offset(EXT_ITEM_PARA_SEED_SLOT_LAST + 1)

    def test_merit_slots_fit_inside_seed_segment(self) -> None:
        from ..data.addresses import EXT_ITEM_PARA_SEED_SLOT_LAST
        self.assertLessEqual(MERIT_SHOP_AP_ITEM_ID_LAST, EXT_ITEM_PARA_SEED_SLOT_LAST)

    def test_teleport_machinery_is_retired(self) -> None:
        # The Cave6 teleport wrappers and their inline patch constants
        # must not resurface — the relocation's plain reader-word
        # patches replace them.
        from ..data import addresses
        for name in (
            "CAVE6_ITEM_PARA_EXT_RAM",
            "CAVE6_ITEM_PARA_EXT_BIN_OFFSET",
            "CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM",
            "CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM",
            "CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM",
            "CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM",
            "ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES",
            "ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES",
            "ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES",
            "ROM_MERIT_DEDUCT_TELEPORT_WRAPPER_BYTES",
            "ROM_MERIT_SCAN_BASE_PATCH_BYTES",
            "ROM_MERIT_NAME_PATCH_BYTES",
            "ROM_MERIT_ROW_PATCH_BYTES",
            "ROM_MERIT_DEDUCT_PATCH_BYTES",
        ):
            self.assertFalse(
                hasattr(addresses, name),
                f"retired constant {name} resurfaced",
            )


class TestExtSeedPatcherOn(DigimonWorldTestBase):
    """Merit option ON: ext entries land in the seed block; the former
    teleport patch sites carry plain relocated reader words."""

    options: ClassVar[dict[str, Any]] = {"merit_shop_locations": 1}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)
        self.observed_last: dict[int, bytes] = {}
        self.ordered: list[tuple[int, bytes]] = []
        for _t, off, data in self.tokens:
            self.observed_last[off] = data
            self.ordered.append((off, data))

    def test_ext_slots_written_inside_seed_block(self) -> None:
        from ..data.addresses import (
            EXT_ITEM_PARA_SEED_BIN_OFFSET,
            EXT_ITEM_PARA_SEED_SIZE,
        )
        for slot in MERIT_SHOP_AP_ITEM_IDS:
            offset = ext_item_para_slot_bin_offset(slot)
            self.assertIn(offset, self.observed_last, f"slot {slot} not written")
            self.assertEqual(len(self.observed_last[offset]), 32)
            self.assertGreaterEqual(offset, EXT_ITEM_PARA_SEED_BIN_OFFSET)
            self.assertLessEqual(
                offset + 32,
                EXT_ITEM_PARA_SEED_BIN_OFFSET + EXT_ITEM_PARA_SEED_SIZE,
            )

    def test_seed_zero_fill_precedes_ext_entries(self) -> None:
        from ..data.addresses import (
            EXT_ITEM_PARA_SEED_BIN_OFFSET,
            EXT_ITEM_PARA_SEED_SIZE,
        )
        zero_index = None
        first_entry_index = None
        for i, (off, data) in enumerate(self.ordered):
            if off == EXT_ITEM_PARA_SEED_BIN_OFFSET and len(data) == EXT_ITEM_PARA_SEED_SIZE:
                zero_index = i
                self.assertEqual(data, b"\x00" * EXT_ITEM_PARA_SEED_SIZE)
            if (len(data) == 32 and first_entry_index is None
                    and EXT_ITEM_PARA_SEED_BIN_OFFSET
                    <= off < EXT_ITEM_PARA_SEED_BIN_OFFSET + EXT_ITEM_PARA_SEED_SIZE):
                first_entry_index = i
        self.assertIsNotNone(zero_index, "seed zero-fill token missing")
        self.assertIsNotNone(first_entry_index, "no ext entry token found")
        self.assertLess(zero_index, first_entry_index,
                        "zero-fill must precede ext entry tokens")

    def test_former_teleport_sites_carry_relocated_reader_words(self) -> None:
        # The four merit reader sites that used to receive 12/16-byte
        # ``j teleport; nop...`` patches now receive plain 4-byte
        # re-based lui words from the always-on relocation.
        from ..data.addresses import _slus_ram_to_bin_offset
        for lui_ram, expected_lui in (
            (0x8010732C, 0x3C09801C),   # merit scan (r9)
            (0x80101A4C, 0x3C02801C),   # name renderer (r2)
            (0x800FE7F4, 0x3C02801C),   # row display (r2)
            (0x800FB018, 0x3C02801C),   # purchase deduct (r2)
        ):
            offset = _slus_ram_to_bin_offset(lui_ram)
            self.assertIn(offset, self.observed_last, hex(lui_ram))
            data = self.observed_last[offset]
            self.assertEqual(len(data), 4,
                             f"site 0x{lui_ram:08X} got a {len(data)}-byte write "
                             f"(teleport-style patch resurfaced?)")
            self.assertEqual(struct.unpack("<I", data)[0], expected_lui)

    def test_scan_bound_reaches_slot_148(self) -> None:
        final = struct.unpack(
            "<I", self.observed_last[ROM_MERIT_SCAN_BOUND_OFFSET],
        )[0]
        self.assertEqual(final, 0x2CA10095)


class TestExtSeedPatcherOff(DigimonWorldTestBase):
    """Merit option OFF: the always-on relocation still zero-fills the
    seed block, but no 32-byte ext entries are staged."""

    options: ClassVar[dict[str, Any]] = {
        "merit_shop_locations": 0,
        "recycle_shop_locations": 0,
    }

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)

    def test_seed_block_zero_filled_but_no_entries(self) -> None:
        from ..data.addresses import (
            EXT_ITEM_PARA_SEED_BIN_OFFSET,
            EXT_ITEM_PARA_SEED_SIZE,
        )
        seed_lo = EXT_ITEM_PARA_SEED_BIN_OFFSET
        seed_hi = seed_lo + EXT_ITEM_PARA_SEED_SIZE
        zero_fills = [
            data for _t, off, data in self.tokens
            if off == seed_lo and len(data) == EXT_ITEM_PARA_SEED_SIZE
        ]
        self.assertEqual(len(zero_fills), 1, "always-on zero-fill missing")
        self.assertEqual(zero_fills[0], b"\x00" * EXT_ITEM_PARA_SEED_SIZE)
        entry_writes = [
            (off, data) for _t, off, data in self.tokens
            if seed_lo <= off < seed_hi and len(data) == 32
        ]
        self.assertEqual(entry_writes, [],
                         "ext entries staged with both shop options off")

    def test_scan_bound_not_patched(self) -> None:
        offsets = {off for _t, off, _d in self.tokens}
        self.assertNotIn(ROM_MERIT_SCAN_BOUND_OFFSET, offsets)
