"""Phase 3 patcher tests.

These tests exercise the parts of :mod:`worlds.digimon_world.rom` and
:mod:`worlds.digimon_world.data.edc` that don't need access to a real
SLUS-01032 BIN — the actual full-disc patch step is a user-confirmable
step (Phase 3 exit criterion in PLAN.md §c).

What is covered:

* ``_build_volume_id`` produces the expected 32-byte AP marker.
* ``DigimonWorldPatchExtension.verify_rom_hash`` rejects wrong-size
  data and SHA-1 mismatches, and accepts a synthetic byte string whose
  hash matches the manifest.
* The token blob produced for a generated seed contains exactly one
  WRITE token at the expected offset/length.
* EDC recalc on a synthetic 32-sector Mode2/2352 image only touches
  the sectors that actually differ, leaves the system area alone, and
  is byte-deterministic.
"""

from __future__ import annotations

import hashlib
import zipfile
from typing import Any, ClassVar
from unittest import mock

from worlds.Files import APTokenTypes

from .. import rom as rom_module
from ..data import edc
from ..data.addresses import (
    ROM_BIN_BYTES,
    ROM_BIN_SHA1,
    SECTOR_SIZE_BYTES,
)
from .bases import DigimonWorldTestBase

# =============================================================================
# Volume id construction
# =============================================================================


class TestVolumeId(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_length_is_exactly_32(self) -> None:
        body = rom_module._build_volume_id("seed-abc-1")
        self.assertEqual(len(body), rom_module.VOLUME_ID_LENGTH)
        self.assertEqual(len(body), 32)

    def test_starts_with_prefix(self) -> None:
        body = rom_module._build_volume_id("anything")
        self.assertTrue(body.startswith(rom_module.VOLUME_ID_PREFIX))

    def test_deterministic(self) -> None:
        a = rom_module._build_volume_id("seed-xyz-1")
        b = rom_module._build_volume_id("seed-xyz-1")
        self.assertEqual(a, b)

    def test_distinct_seeds_distinct_ids(self) -> None:
        a = rom_module._build_volume_id("seed-aaa-1")
        b = rom_module._build_volume_id("seed-bbb-1")
        self.assertNotEqual(a, b)

    def test_iso9660_d_characters_only(self) -> None:
        """ISO9660 d-characters: A-Z, 0-9, underscore, plus space padding."""

        body = rom_module._build_volume_id("seed-test-7")
        allowed = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_ ")
        for byte in body:
            self.assertIn(byte, allowed,
                          f"byte {byte!r} not a d-character in {body!r}")


# =============================================================================
# SHA-1 verifier
# =============================================================================


class TestVerifyRomHash(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_rejects_wrong_size(self) -> None:
        too_small = bytes(ROM_BIN_BYTES - 1)
        with self.assertRaisesRegex(ValueError, "size"):
            rom_module.DigimonWorldPatchExtension.verify_rom_hash(mock.MagicMock(), too_small)

    def test_rejects_correct_size_wrong_hash(self) -> None:
        wrong = bytes(ROM_BIN_BYTES)  # all-zero, definitely wrong SHA-1
        with self.assertRaisesRegex(ValueError, "SHA-1"):
            rom_module.DigimonWorldPatchExtension.verify_rom_hash(mock.MagicMock(), wrong)

    def test_accepts_synthetic_match(self) -> None:
        """Patch the manifest hash to match a synthetic dataset, then verify."""

        synthetic = b"\xAB" * ROM_BIN_BYTES
        actual_hash = hashlib.sha1(synthetic).hexdigest().upper()
        with mock.patch.object(rom_module, "ROM_BIN_SHA1", actual_hash):
            result = rom_module.DigimonWorldPatchExtension.verify_rom_hash(
                mock.MagicMock(), synthetic,
            )
        self.assertEqual(result, synthetic)

    def test_manifest_hash_is_uppercase_hex(self) -> None:
        self.assertEqual(len(ROM_BIN_SHA1), 40)
        self.assertEqual(ROM_BIN_SHA1, ROM_BIN_SHA1.upper())
        int(ROM_BIN_SHA1, 16)  # raises if not pure hex


# =============================================================================
# Token blob produced by generate_output
# =============================================================================


class TestGenerateOutput(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_generate_output_writes_apdw1_with_expected_tokens(self) -> None:
        """Capture the patch zip into an in-memory store and inspect it.

        Phase 5 piece C: the token blob holds, in some order:

        * 1 volume-id WRITE.
        * setTrigger wrapper bytes (32 bytes at Cave6 offset) + 8-byte
          patch at the vanilla setTrigger entry (replaces first 2 instrs
          with ``j wrapper`` + ``nop``).
        * 1 PP-calc patch WRITE (44 bytes).
        * 5 softlock-fix bands: ROM_FIX_ROTATION (2 bytes total),
          ROM_FIX_MOVE_TO (2*4 = 8 bytes), ROM_FIX_TOY_TOWN
          (2*4 = 8 bytes), ROM_FIX_LEO_CAVE (8*1 byte),
          ROM_OGREMON_SOFTLOCK (2*2 = 4 bytes).
        * Per-chest item byte writes + chestGiveItem wrapper +
          chest-pickup ``jal`` redirect (Phase 5 piece A).

        Note: closed-shuffle recruit remap was dropped in Phase 5
        piece C; the setTrigger wrapper now decouples fight-completion
        from city-join, replacing the visual-only remap.
        """

        import struct

        from ..data.addresses import (
            ROM_FIX_LEO_CAVE_OFFSETS,
            ROM_FIX_LEO_CAVE_VALUE,
            ROM_FIX_MOVE_TO_OFFSETS,
            ROM_FIX_MOVE_TO_VALUE,
            ROM_FIX_ROTATION_OFFSETS,
            ROM_FIX_ROTATION_VALUE,
            ROM_FIX_TOY_TOWN_OFFSETS,
            ROM_FIX_TOY_TOWN_VALUE,
            ROM_OGREMON_SOFTLOCK_OFFSETS,
            ROM_OGREMON_SOFTLOCK_VALUE,
            ROM_PP_CALC_PATCH_OFFSET,
            ROM_PP_CALC_PATCH_VALUE,
            ROM_SETTRIGGER_PATCH_FORMAT,
            ROM_SETTRIGGER_PATCH_OFFSET,
            ROM_SETTRIGGER_PATCH_VALUE,
            ROM_SETTRIGGER_WRAPPER_BYTES,
            ROM_SETTRIGGER_WRAPPER_OFFSET,
        )

        captured: dict[str, bytes] = {}

        def fake_write(self_patch: Any, target: str) -> None:
            with zipfile.ZipFile(target, "w") as _:
                pass  # not used; we read self_patch.files instead
            captured.update(self_patch.files)

        with mock.patch.object(
            rom_module.DigimonWorldProcedurePatch, "write", fake_write,
        ):
            self.world.generate_output(".")

        self.assertIn("token_data.bin", captured,
                      "generate_output should have populated token_data.bin")
        token_blob = captured["token_data.bin"]

        # Token blob layout (worlds/Files.py:407-427):
        #   uint32_le token_count
        #   for each: uint8 type, uint32_le offset, uint32_le size, bytes data
        token_count = int.from_bytes(token_blob[:4], "little")
        tokens: list[tuple[int, int, int, bytes]] = []
        bpr = 4
        for _ in range(token_count):
            token_type = token_blob[bpr]
            offset = int.from_bytes(token_blob[bpr + 1:bpr + 5], "little")
            size = int.from_bytes(token_blob[bpr + 5:bpr + 9], "little")
            data = token_blob[bpr + 9:bpr + 9 + size]
            tokens.append((token_type, offset, size, data))
            bpr += 9 + size
        for ttype, *_ in tokens:
            self.assertEqual(ttype, APTokenTypes.WRITE)

        # Index every token by (offset, data) for set comparison.
        observed: set[tuple[int, bytes]] = {(off, data) for _t, off, _s, data in tokens}

        # Volume-id token.
        first_off = tokens[0][1]
        first_data = tokens[0][3]
        self.assertEqual(first_off, rom_module.VOLUME_ID_OFFSET)
        self.assertTrue(first_data.startswith(rom_module.VOLUME_ID_PREFIX))
        self.assertEqual(len(first_data), rom_module.VOLUME_ID_LENGTH)

        # Phase 5 piece C: setTrigger wrapper installation. The 32-byte
        # wrapper sits in Cave6 right after the chest-pickup wrapper, and
        # the 8-byte patch at the setTrigger entry redirects through it.
        self.assertIn(
            (ROM_SETTRIGGER_WRAPPER_OFFSET, ROM_SETTRIGGER_WRAPPER_BYTES),
            observed,
        )
        expected_settrigger_patch_bytes = struct.pack(
            ROM_SETTRIGGER_PATCH_FORMAT, *ROM_SETTRIGGER_PATCH_VALUE,
        )
        self.assertIn(
            (ROM_SETTRIGGER_PATCH_OFFSET, expected_settrigger_patch_bytes),
            observed,
        )

        # PP-calc patch token.
        expected_pp_bytes = b"".join(
            word.to_bytes(4, "big") for word in ROM_PP_CALC_PATCH_VALUE
        )
        self.assertIn((ROM_PP_CALC_PATCH_OFFSET, expected_pp_bytes), observed)

        # Softlock-fix tokens.
        rotation_bytes = struct.pack("B", ROM_FIX_ROTATION_VALUE)
        for off in ROM_FIX_ROTATION_OFFSETS:
            self.assertIn((off, rotation_bytes), observed)
        move_to_bytes = struct.pack("<I", ROM_FIX_MOVE_TO_VALUE)
        for off in ROM_FIX_MOVE_TO_OFFSETS:
            self.assertIn((off, move_to_bytes), observed)
        toy_town_bytes = struct.pack(">I", ROM_FIX_TOY_TOWN_VALUE)
        for off in ROM_FIX_TOY_TOWN_OFFSETS:
            self.assertIn((off, toy_town_bytes), observed)
        leo_cave_bytes = struct.pack("B", ROM_FIX_LEO_CAVE_VALUE)
        for off in ROM_FIX_LEO_CAVE_OFFSETS:
            self.assertIn((off, leo_cave_bytes), observed)
        ogremon_bytes = struct.pack("<H", ROM_OGREMON_SOFTLOCK_VALUE)
        for off in ROM_OGREMON_SOFTLOCK_OFFSETS:
            self.assertIn((off, ogremon_bytes), observed)

        # Chest-item replacement tokens.
        # WorldTestBase.setUp does NOT run fill, so every chest's
        # location.item is None and Phase 5 piece A's per-chest decision
        # falls back to the AP sentinel byte for all 73 spawnChest
        # offsets. A real Generate.py run would have a mix of sentinel
        # and real DW1 internal item ids; that's exercised by the
        # fill-driven test below.
        from ..data.addresses import (
            AP_CHEST_SENTINEL_ITEM_ID,
            CHEST_NAME_TO_ROM_OFFSETS,
            ROM_AP_ITEM_ENTRY_BYTES,
            ROM_AP_ITEM_ENTRY_OFFSET,
            ROM_CHEST_GIVEITEM_PATCH_FORMAT,
            ROM_CHEST_GIVEITEM_PATCH_OFFSET,
            ROM_CHEST_GIVEITEM_PATCH_VALUE,
            ROM_CHEST_GIVEITEM_WRAPPER_BYTES,
            ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
        )
        chest_item_bytes = struct.pack("B", AP_CHEST_SENTINEL_ITEM_ID)
        for offsets in CHEST_NAME_TO_ROM_OFFSETS.values():
            for off in offsets:
                self.assertIn((off + 1, chest_item_bytes), observed)
        # Item-table entry for the AP sentinel name. Sentinel id is 83
        # (vanilla "Electo ring", unused/gamebreaking) — well inside
        # ITEM_PARA's 128-entry bound, so this write doesn't spill
        # into ITEM_DESC_PTR.
        self.assertIn(
            (ROM_AP_ITEM_ENTRY_OFFSET, ROM_AP_ITEM_ENTRY_BYTES),
            observed,
        )
        # Phase 5 piece A: chestGiveItem wrapper installed at Cave6,
        # plus the chest-pickup ``jal giveItem`` redirected to it. These
        # writes are unconditional — they happen regardless of AP fill
        # placement.
        self.assertIn(
            (ROM_CHEST_GIVEITEM_WRAPPER_OFFSET, ROM_CHEST_GIVEITEM_WRAPPER_BYTES),
            observed,
        )
        expected_jal_bytes = struct.pack(
            ROM_CHEST_GIVEITEM_PATCH_FORMAT, ROM_CHEST_GIVEITEM_PATCH_VALUE,
        )
        self.assertIn(
            (ROM_CHEST_GIVEITEM_PATCH_OFFSET, expected_jal_bytes),
            observed,
        )


# =============================================================================
# EDC recalculation against a synthetic disc image
# =============================================================================


def _make_synthetic_disc(sector_count: int) -> bytearray:
    """Build a 2352-byte/sector image of ``sector_count`` Mode2 Form1 sectors.

    Each sector starts with the standard sync header, has a Mode2/Form1
    submode (mode = 2, form = 0), then arbitrary user data. EDC/ECC are
    initially zeroed; the recalculator re-fills them on first pass.
    """

    sync = bytes([0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 0])
    image = bytearray(sector_count * SECTOR_SIZE_BYTES)
    for i in range(sector_count):
        start = i * SECTOR_SIZE_BYTES
        image[start:start + 12] = sync
        # Sector address (MSF) — leave as zeros for the test.
        # Mode byte at 0x0F.
        image[start + 0x0F] = 2
        # Submode at 0x12: form 1 (bit 0x20 clear), data sector.
        image[start + 0x12] = 0x00
        # Some user data so EDC isn't trivially zero.
        image[start + 0x18:start + 0x18 + 16] = bytes(
            [(i + j) & 0xFF for j in range(16)]
        )
    return image


class TestEdcRecalc(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    SECTOR_COUNT: ClassVar[int] = edc.SYSTEM_AREA_SECTORS + 16  # 32 sectors total

    def test_size_mismatch_raises(self) -> None:
        a = _make_synthetic_disc(self.SECTOR_COUNT)
        b = _make_synthetic_disc(self.SECTOR_COUNT - 1)
        with self.assertRaisesRegex(ValueError, "identical sizes"):
            edc.diff_recalc_in_place(a, b)

    def test_non_sector_aligned_raises(self) -> None:
        bad = bytearray(SECTOR_SIZE_BYTES * 8 + 5)
        with self.assertRaisesRegex(ValueError, "Mode2/2352"):
            edc.diff_recalc_in_place(bad, bytes(len(bad)))

    def test_identical_inputs_recompute_zero_sectors(self) -> None:
        base = bytes(_make_synthetic_disc(self.SECTOR_COUNT))
        target = bytearray(base)
        stats = edc.diff_recalc_in_place(target, base)
        self.assertEqual(stats.recalc_sectors, 0)
        self.assertEqual(stats.identical_sectors,
                         self.SECTOR_COUNT - edc.SYSTEM_AREA_SECTORS)
        self.assertEqual(target, base)  # nothing was rewritten

    def test_changed_sector_is_recalculated_and_system_area_untouched(self) -> None:
        base = bytes(_make_synthetic_disc(self.SECTOR_COUNT))
        target = bytearray(base)

        # Modify one byte in sector 17 (post system area).
        modify_offset = 17 * SECTOR_SIZE_BYTES + 0x40
        target[modify_offset] ^= 0xFF

        # Modify one byte in sector 5 (system area). EDC should NOT touch it.
        sys_offset = 5 * SECTOR_SIZE_BYTES + 0x40
        target[sys_offset] ^= 0xFF

        stats = edc.diff_recalc_in_place(target, base)
        self.assertEqual(stats.recalc_sectors, 1)
        self.assertEqual(stats.identical_sectors,
                         self.SECTOR_COUNT - edc.SYSTEM_AREA_SECTORS - 1)

        # System-area byte mutation survives — recalc skipped that sector.
        self.assertNotEqual(target[sys_offset], base[sys_offset])

        # Modified sector's user-data byte is preserved; only EDC/ECC
        # bytes (sector tail) and the sync header (re-stamped) are
        # rewritten.
        self.assertNotEqual(target[modify_offset], base[modify_offset])
        # The byte we mutated is still present after recalc.
        self.assertEqual(target[modify_offset], base[modify_offset] ^ 0xFF)

    def test_recalc_is_deterministic(self) -> None:
        base = bytes(_make_synthetic_disc(self.SECTOR_COUNT))
        a = bytearray(base)
        b = bytearray(base)
        a[18 * SECTOR_SIZE_BYTES + 0x40] ^= 0xAA
        b[18 * SECTOR_SIZE_BYTES + 0x40] ^= 0xAA
        edc.diff_recalc_in_place(a, base)
        edc.diff_recalc_in_place(b, base)
        self.assertEqual(a, b)
