"""Tests for the Archipelago logo icon on ITEM.TIM slot 83.

* :class:`TestItemTimManifest` — tile/CLUT offset geometry and the
  ITEM_CLUT_DATA table anchor (pure manifest, no ROM).
* :class:`TestLogoArtShape` — palette + pixel-art byte-shape invariants
  (packing, index bounds, hue coverage).
* :class:`TestRequantizeHelpers` — the apply-time nearest-color
  re-indexing helpers, on synthetic palettes.
* :class:`TestIconTokens` — token emission (always-on, default options).
* :class:`TestVanillaAnchorsAgainstSourceBin` — TIM structure +
  ITEM_CLUT_DATA vanilla bytes in the canonical dump (auto-skipped
  without the ROM).
* :class:`TestEndToEndTogglesAndLogo` — full generate -> .apdw1 ->
  procedure-apply with the Frigimon/Mojyamon toggles OFF and the
  always-on logo, byte-verifying both features (ROM-gated).
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from BaseClasses import ItemClassification

from .. import rom as rom_module
from ..data.addresses import (
    AP_ICON_CLUT_BIN_OFFSETS,
    AP_ICON_CLUT_INDEX,
    AP_ICON_ID_FALLBACK,
    AP_ICON_ID_TABLE_BASE_ITEM_ID,
    AP_ICON_ID_TABLE_DEFAULT_BYTES,
    AP_ICON_ID_TABLE_OFFSET,
    AP_ICON_ID_TABLE_RAM,
    AP_ICON_ID_TABLE_SIZE,
    AP_ITEM_ICON_INDEX,
    AP_ITEM_ICON_TILE_BIN_OFFSETS,
    AP_LOGO_CLUT_BYTES,
    AP_LOGO_PALETTE,
    AP_LOGO_PIXEL_ROWS,
    AP_LOGO_TILE_ROW_BYTES,
    ITEM_CLUT_DATA_RAM,
    ITEM_CLUT_DATA_VANILLA,
    ITEM_TIM_CLUT_COUNT,
    ITEM_TIM_CLUT_DATA_FILE_OFFSET,
    ITEM_TIM_CLUT_SIZE_BYTES,
    ITEM_TIM_COPY_BASE_BIN_OFFSETS,
    ITEM_TIM_LBA,
    ITEM_TIM_PIXEL_DATA_FILE_OFFSET,
    ITEM_TIM_SIZE_BYTES,
    RAINBOWHORN_ITEM_ID,
    RAINBOWHORN_NEW_CLUT_INDEX,
    RAINBOWHORN_TILE_BIN_OFFSETS,
    ROM_ICON_CLAMP_PATCH_OFFSET,
    ROM_ICON_CLAMP_WRAPPER_BYTES,
    ROM_ICON_CLAMP_WRAPPER_OFFSET,
    ROM_ICON_CLAMP_WRAPPER_RAM,
    ROM_SET_ITEM_TEXTURE_RETURN_RAM,
    ROM_SET_ITEM_TEXTURE_VANILLA_WORDS,
    item_clut_data_bin_offset,
    item_tim_clut_bin_offsets,
    item_tim_tile_row_bin_offsets,
    read_user_data_bytes,
)
from .bases import DigimonWorldTestBase
from .test_patcher import _capture_tokens

_LOCAL_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"

_SECTOR = 2352
_HEADER = 24
_USER = 2048


# =============================================================================
# ITEM.TIM offset geometry
# =============================================================================


class TestItemTimManifest(unittest.TestCase):
    def test_two_on_disc_copies(self) -> None:
        """Standalone ITEM.TIM + the embedded ETCTIM.BIN copy (the one
        the game uploads to VRAM at boot)."""

        self.assertEqual(ITEM_TIM_COPY_BASE_BIN_OFFSETS,
                         (0x010C16B8, 0x010A0538))
        self.assertEqual(ITEM_TIM_COPY_BASE_BIN_OFFSETS[0],
                         ITEM_TIM_LBA * _SECTOR + _HEADER)

    def test_tile_offset_counts(self) -> None:
        for per_copy in (AP_ITEM_ICON_TILE_BIN_OFFSETS,
                         RAINBOWHORN_TILE_BIN_OFFSETS):
            self.assertEqual(len(per_copy), 2)
            for rows in per_copy:
                self.assertEqual(len(rows), 16)

    def test_slot83_first_row_arithmetic(self) -> None:
        """Slot 83 = col 3, row 5. First tile row at TIM file offset
        800 + 80*128 + 3*8 = 11064 -> sector 5, byte 824 of the
        standalone copy."""

        file_offset = ITEM_TIM_PIXEL_DATA_FILE_OFFSET + 80 * 128 + 3 * 8
        self.assertEqual(file_offset, 11064)
        expected = (ITEM_TIM_LBA + 5) * _SECTOR + _HEADER + (11064 - 5 * _USER)
        self.assertEqual(AP_ITEM_ICON_TILE_BIN_OFFSETS[0][0], expected)

    def test_no_tile_row_straddles_a_sector(self) -> None:
        for per_copy in (AP_ITEM_ICON_TILE_BIN_OFFSETS,
                         RAINBOWHORN_TILE_BIN_OFFSETS):
            for rows in per_copy:
                for off in rows:
                    pos = off % _SECTOR
                    self.assertTrue(_HEADER <= pos <= _HEADER + _USER - 8,
                                    hex(off))

    def test_adjacent_slots_share_scanlines(self) -> None:
        """Slots 83 and 84 sit on the same texture rows, 8 bytes apart
        (within each copy)."""

        for rows83, rows84 in zip(AP_ITEM_ICON_TILE_BIN_OFFSETS,
                                  RAINBOWHORN_TILE_BIN_OFFSETS, strict=True):
            for a, b in zip(rows83, rows84, strict=True):
                self.assertEqual(b - a, 8)

    def test_clut_offset_arithmetic(self) -> None:
        """CLUT 22 at TIM file offset 20 + 22*32 = 724; per-copy .bin
        offsets, each inside one user-data window."""

        self.assertEqual(ITEM_TIM_CLUT_DATA_FILE_OFFSET, 20)
        self.assertEqual(
            AP_ICON_CLUT_BIN_OFFSETS[0],
            ITEM_TIM_LBA * _SECTOR + _HEADER + 724,
        )
        self.assertEqual(item_tim_clut_bin_offsets(AP_ICON_CLUT_INDEX),
                         AP_ICON_CLUT_BIN_OFFSETS)
        for off in AP_ICON_CLUT_BIN_OFFSETS:
            pos = off % _SECTOR
            self.assertTrue(
                _HEADER <= pos <= _HEADER + _USER - ITEM_TIM_CLUT_SIZE_BYTES,
            )

    def test_clut_data_table_anchor(self) -> None:
        """ITEM_CLUT_DATA sits right after ITEM_PARA + ITEM_DESC_PTR."""

        self.assertEqual(ITEM_CLUT_DATA_RAM, 0x80127BDC)
        self.assertEqual(item_clut_data_bin_offset(AP_ITEM_ICON_INDEX),
                         0x14D68B77)
        self.assertEqual(item_clut_data_bin_offset(RAINBOWHORN_ITEM_ID),
                         0x14D68B78)

    def test_vanilla_clut_assignments_recorded(self) -> None:
        self.assertEqual(ITEM_CLUT_DATA_VANILLA,
                         {AP_ITEM_ICON_INDEX: 16, RAINBOWHORN_ITEM_ID: 22})
        self.assertLess(AP_ICON_CLUT_INDEX, ITEM_TIM_CLUT_COUNT)
        self.assertLess(RAINBOWHORN_NEW_CLUT_INDEX, ITEM_TIM_CLUT_COUNT)


# =============================================================================
# Logo art byte-shape
# =============================================================================


class TestLogoArtShape(unittest.TestCase):
    def test_palette_shape(self) -> None:
        self.assertEqual(len(AP_LOGO_PALETTE), 16)
        self.assertEqual(AP_LOGO_PALETTE[0], (0, 0, 0))
        for color in AP_LOGO_PALETTE:
            for chan in color:
                self.assertTrue(0 <= chan <= 255 and chan % 8 == 0, color)

    def test_clut_bytes_roundtrip(self) -> None:
        """15-bit packing is lossless for our multiples-of-8 palette."""

        self.assertEqual(len(AP_LOGO_CLUT_BYTES), 32)
        self.assertEqual(rom_module._decode_clut15(AP_LOGO_CLUT_BYTES),
                         AP_LOGO_PALETTE)
        # Index 0 must be raw 0x0000 (PSX renders it fully transparent).
        self.assertEqual(AP_LOGO_CLUT_BYTES[:2], b"\x00\x00")
        # No other entry may accidentally be raw 0 (it would vanish).
        for i in range(1, 16):
            raw = struct.unpack_from("<H", AP_LOGO_CLUT_BYTES, i * 2)[0]
            self.assertNotEqual(raw, 0, f"palette index {i}")

    def test_pixel_rows_shape(self) -> None:
        self.assertEqual(len(AP_LOGO_PIXEL_ROWS), 16)
        for row in AP_LOGO_PIXEL_ROWS:
            self.assertEqual(len(row), 16)
            for ch in row:
                self.assertIn(ch, ".123456789abcdef")

    def test_row_packing_low_nibble_left(self) -> None:
        for row_str, row_bytes in zip(AP_LOGO_PIXEL_ROWS,
                                      AP_LOGO_TILE_ROW_BYTES, strict=True):
            self.assertEqual(len(row_bytes), 8)
            indices = [0 if ch == "." else int(ch, 16) for ch in row_str]
            for i, byte in enumerate(row_bytes):
                self.assertEqual(byte & 0xF, indices[2 * i])
                self.assertEqual(byte >> 4, indices[2 * i + 1])

    def test_all_six_hues_present(self) -> None:
        """The ring uses all six AP circle hues + the white highlight."""

        used = {ch for row in AP_LOGO_PIXEL_ROWS for ch in row if ch != "."}
        for hue in "2468ace":  # red/orange/yellow/green/blue/purple/white
            self.assertIn(hue, used)

    def test_background_dominates(self) -> None:
        """The circles keep spacing: background stays the majority so
        the ring reads at 16x16 (sanity guard against fill-in edits)."""

        flat = "".join(AP_LOGO_PIXEL_ROWS)
        self.assertGreater(flat.count("."), 128)


# =============================================================================
# Icon-id wrapper + table shape
# =============================================================================


class TestIconIdWrapperShape(unittest.TestCase):
    WORDS = struct.unpack(f"<{len(ROM_ICON_CLAMP_WRAPPER_BYTES) // 4}I",
                          ROM_ICON_CLAMP_WRAPPER_BYTES)

    def test_wrapper_is_16_instructions(self) -> None:
        self.assertEqual(len(ROM_ICON_CLAMP_WRAPPER_BYTES), 64)

    def test_reproduced_vanilla_words(self) -> None:
        """The wrapper replays the two displaced setItemTexture prologue
        instructions (idx 13 and the j-delay slot, idx 15)."""

        self.assertEqual(self.WORDS[13], ROM_SET_ITEM_TEXTURE_VANILLA_WORDS[0])
        self.assertEqual(self.WORDS[15], ROM_SET_ITEM_TEXTURE_VANILLA_WORDS[1])

    def test_jump_back_target(self) -> None:
        expected = 0x08000000 | ((ROM_SET_ITEM_TEXTURE_RETURN_RAM >> 2)
                                 & 0x03FFFFFF)
        self.assertEqual(self.WORDS[14], expected)

    def test_table_address_construction(self) -> None:
        """lui/addiu at idx 6/7 must rebuild AP_ICON_ID_TABLE_RAM."""

        hi = self.WORDS[6] & 0xFFFF
        lo = self.WORDS[7] & 0xFFFF
        lo_signed = lo - 0x10000 if lo >= 0x8000 else lo
        self.assertEqual((hi << 16) + lo_signed, AP_ICON_ID_TABLE_RAM)

    def test_branch_targets(self) -> None:
        """bne(1) and beq(10) land on .keep (idx 13); beq(4) lands on
        .fallback (idx 12)."""

        def target(branch_idx: int) -> int:
            offset = self.WORDS[branch_idx] & 0xFFFF
            offset = offset - 0x10000 if offset >= 0x8000 else offset
            return branch_idx + 1 + offset

        self.assertEqual(target(1), 13)
        self.assertEqual(target(4), 12)
        self.assertEqual(target(10), 13)

    def test_fallback_loads_logo_slot(self) -> None:
        self.assertEqual(self.WORDS[12], 0x24050000 | AP_ICON_ID_FALLBACK)

    def test_lbu_load_delay_respected(self) -> None:
        """The lbu at idx 9 must not have $a1 consumed in the next
        instruction (R3000 load-delay slot): idx 10 is a branch on
        $zero and idx 11 is a nop."""

        self.assertEqual(self.WORDS[9] >> 26, 0x24)  # lbu opcode
        self.assertEqual(self.WORDS[10], 0x10000002)  # beq $0, $0, +2
        self.assertEqual(self.WORDS[11], 0)           # nop

    def test_table_geometry(self) -> None:
        self.assertEqual(
            AP_ICON_ID_TABLE_RAM,
            ROM_ICON_CLAMP_WRAPPER_RAM + len(ROM_ICON_CLAMP_WRAPPER_BYTES),
        )
        self.assertEqual(AP_ICON_ID_TABLE_RAM, 0x80095F80)
        self.assertEqual(AP_ICON_ID_TABLE_SIZE, 58)
        self.assertEqual(AP_ICON_ID_TABLE_BASE_ITEM_ID, 128)
        # The claim must stay clear of the merit AP desc strings.
        self.assertLessEqual(AP_ICON_ID_TABLE_RAM + AP_ICON_ID_TABLE_SIZE,
                             0x80096000)

    def test_default_table_is_all_logo(self) -> None:
        self.assertEqual(
            AP_ICON_ID_TABLE_DEFAULT_BYTES,
            bytes((AP_ICON_ID_FALLBACK,)) * AP_ICON_ID_TABLE_SIZE,
        )


# =============================================================================
# Icon-id table emission (placement matrix)
# =============================================================================


class TestIconIdTableTokens(DigimonWorldTestBase):
    """Matrix: local inventory item -> its own tile id; local AP-only
    abstraction -> logo; another player's item -> logo; unfilled /
    option-off slots -> logo."""

    options: ClassVar[dict[str, Any]] = {"recycle_shop_locations": 2}

    def test_table_matrix(self) -> None:
        from ..items import ITEM_NAME_TO_ID, DigimonWorldItem, dw1_internal_item_id

        world = self.world
        # Slot 128 (Recycle Shop #1): our own real inventory item.
        world.get_location("Recycle Shop #1").place_locked_item(
            world.create_item("Med Recovery"),
        )
        # Slot 129: our own AP-only abstraction (Progressive ladder).
        world.get_location("Recycle Shop #2").place_locked_item(
            world.create_item("Progressive Item Shop"),
        )
        # Slot 130: another player's copy of a DW1-named item.
        self.multiworld.player_name[2] = "RemoteFriend"
        foreign = DigimonWorldItem(
            "Med Recovery", ItemClassification.filler,
            ITEM_NAME_TO_ID["Med Recovery"], 2,
        )
        world.get_location("Recycle Shop #3").place_locked_item(foreign)

        observed = dict(_capture_tokens(world))
        table = observed[AP_ICON_ID_TABLE_OFFSET]
        self.assertEqual(len(table), AP_ICON_ID_TABLE_SIZE)

        med_recovery_id = dw1_internal_item_id("Med Recovery")
        self.assertIsNotNone(med_recovery_id)
        self.assertEqual(table[0], med_recovery_id)          # local real item
        self.assertEqual(table[1], AP_ICON_ID_FALLBACK)      # local abstraction
        self.assertEqual(table[2], AP_ICON_ID_FALLBACK)      # foreign item
        # Unfilled recycle slots + every option-off shop slot: logo.
        self.assertTrue(
            all(b == AP_ICON_ID_FALLBACK for b in table[3:]),
        )


class TestIconIdTableDefaultEmission(DigimonWorldTestBase):
    """With every shop option off, neither the icon-id wrapper nor the
    table is emitted (ext ids never render without shopsanity)."""

    options: ClassVar[dict[str, Any]] = {}

    def test_no_wrapper_or_table_tokens(self) -> None:
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        self.assertNotIn(AP_ICON_ID_TABLE_OFFSET, observed_offsets)
        self.assertNotIn(ROM_ICON_CLAMP_WRAPPER_OFFSET, observed_offsets)


class TestIconIdTableUnfilledEmission(DigimonWorldTestBase):
    """Shopsanity on but locations unfilled -> table emitted, all-logo."""

    options: ClassVar[dict[str, Any]] = {"recycle_shop_locations": 2}

    def test_all_logo(self) -> None:
        observed = dict(_capture_tokens(self.world))
        self.assertEqual(observed[AP_ICON_ID_TABLE_OFFSET],
                         AP_ICON_ID_TABLE_DEFAULT_BYTES)
        self.assertEqual(observed[ROM_ICON_CLAMP_WRAPPER_OFFSET],
                         ROM_ICON_CLAMP_WRAPPER_BYTES)


# =============================================================================
# Requantization helpers
# =============================================================================


class TestRequantizeHelpers(unittest.TestCase):
    _SRC = ((0, 0, 0), (248, 0, 0), (0, 248, 0), (0, 0, 248)) + ((0, 0, 0),) * 12
    _DST = ((0, 0, 0), (0, 0, 240), (216, 8, 8), (8, 216, 8)) + ((80, 80, 80),) * 12

    def test_nearest_index_never_zero(self) -> None:
        # Pure black is closest to index 0, but 0 is transparent and
        # must be excluded from the search.
        idx = rom_module._nearest_clut_index((0, 0, 0), self._DST)
        self.assertNotEqual(idx, 0)

    def test_nearest_index_picks_expected_hue(self) -> None:
        self.assertEqual(rom_module._nearest_clut_index((248, 0, 0), self._DST), 2)
        self.assertEqual(rom_module._nearest_clut_index((0, 248, 0), self._DST), 3)
        self.assertEqual(rom_module._nearest_clut_index((0, 0, 248), self._DST), 1)

    def test_requantize_row_preserves_transparency(self) -> None:
        # pixels: 0,1,2,3, 0,0, ... (low nibble = left)
        row = bytes((0x10, 0x32, 0, 0, 0, 0, 0, 0))
        out = rom_module._requantize_tile_row(row, self._SRC, self._DST)
        # 0 stays 0; 1 (red) -> 2; 2 (green) -> 3; 3 (blue) -> 1
        self.assertEqual(out, bytes((0x20, 0x13, 0, 0, 0, 0, 0, 0)))


# =============================================================================
# Token emission (always-on)
# =============================================================================


class TestIconTokens(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_logo_and_clut_tokens_present(self) -> None:
        observed = _capture_tokens(self.world)
        for rows in AP_ITEM_ICON_TILE_BIN_OFFSETS:
            for off, row_bytes in zip(rows, AP_LOGO_TILE_ROW_BYTES,
                                      strict=True):
                self.assertIn((off, row_bytes), observed)
        for clut_off in AP_ICON_CLUT_BIN_OFFSETS:
            self.assertIn((clut_off, AP_LOGO_CLUT_BYTES), observed)
        self.assertIn(
            (item_clut_data_bin_offset(AP_ITEM_ICON_INDEX),
             bytes((AP_ICON_CLUT_INDEX,))),
            observed,
        )
        self.assertIn(
            (item_clut_data_bin_offset(RAINBOWHORN_ITEM_ID),
             bytes((RAINBOWHORN_NEW_CLUT_INDEX,))),
            observed,
        )

    def test_neighbor_clut_data_entries_untouched(self) -> None:
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for item_id in (82, 85):
            self.assertNotIn(item_clut_data_bin_offset(item_id),
                             observed_offsets)

    def test_procedure_includes_requantize_step(self) -> None:
        self.assertIn(
            ("requantize_rainbowhorn", []),
            rom_module.DigimonWorldProcedurePatch.procedure,
        )


# =============================================================================
# Vanilla-byte anchors (needs the local SLUS-01032 dump; skipped on CI)
# =============================================================================


@unittest.skipUnless(_LOCAL_BIN.is_file(), "SLUS-01032 dump not present")
class TestVanillaAnchorsAgainstSourceBin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = _LOCAL_BIN.read_bytes()

    def test_tim_header_both_copies(self) -> None:
        for base in ITEM_TIM_COPY_BASE_BIN_OFFSETS:
            magic, flags = struct.unpack_from("<II", self.rom, base)
            self.assertEqual(magic, 0x10, hex(base))
            self.assertEqual(flags, 0x08, hex(base))  # 4bpp + CLUT

    def test_clut_block_header_both_copies(self) -> None:
        for base in ITEM_TIM_COPY_BASE_BIN_OFFSETS:
            length, dx, dy, w, h = struct.unpack_from(
                "<IHHHH", self.rom, base + 8,
            )
            self.assertEqual(length, 780)
            # matches getClut(0xE0, +0x1E8)
            self.assertEqual((dx, dy), (224, 488))
            self.assertEqual((w, h), (16, ITEM_TIM_CLUT_COUNT))

    def test_copies_byte_identical(self) -> None:
        """The embedded ETCTIM.BIN copy is byte-identical to the
        standalone file, so identical patch bytes are valid for both."""

        standalone, embedded = (
            read_user_data_bytes(self.rom, base, ITEM_TIM_SIZE_BYTES)
            for base in ITEM_TIM_COPY_BASE_BIN_OFFSETS
        )
        self.assertEqual(standalone, embedded)

    def test_item_clut_data_vanilla_bytes(self) -> None:
        for item_id, vanilla in ITEM_CLUT_DATA_VANILLA.items():
            self.assertEqual(self.rom[item_clut_data_bin_offset(item_id)],
                             vanilla, f"entry {item_id}")

    def test_set_item_texture_displaced_words(self) -> None:
        """The two prologue instructions the entry hijack displaces (and
        the wrapper reproduces) are byte-verified against the dump."""

        expected = struct.pack("<II", *ROM_SET_ITEM_TEXTURE_VANILLA_WORDS)
        self.assertEqual(
            self.rom[ROM_ICON_CLAMP_PATCH_OFFSET:
                     ROM_ICON_CLAMP_PATCH_OFFSET + 8],
            expected,
        )

    def test_vanilla_cluts_start_transparent(self) -> None:
        """Every vanilla CLUT's index 0 is raw 0x0000 — confirms the
        transparent-index convention the logo palette follows."""

        for k in (AP_ICON_CLUT_INDEX, RAINBOWHORN_NEW_CLUT_INDEX, 16):
            for off in item_tim_clut_bin_offsets(k):
                self.assertEqual(self.rom[off:off + 2], b"\x00\x00",
                                 f"CLUT {k} @ {off:#x}")


# =============================================================================
# End-to-end: toggles OFF + logo on -> .apdw1 -> procedure apply
# =============================================================================


class TestEndToEndTogglesAndLogo(DigimonWorldTestBase):
    """One pipeline covering both deliverables: the Frigimon / Mojyamon
    locations are toggled OFF and the (always-on) AP logo icon lands in
    the patched bin. ROM-gated — auto-skips without the local dump."""

    options: ClassVar[dict[str, Any]] = {
        "frigimon_recruit_location": False,
        "mojyamon_recruit_location": False,
        # Shopsanity on so the icon-id wrapper + table are exercised
        # end-to-end (they are gated on any shop mode != off).
        "recycle_shop_locations": 2,
    }

    def test_apply_and_byte_verify(self) -> None:
        if not _LOCAL_BIN.is_file():
            self.skipTest("SLUS-01032 dump not present")
        source = _LOCAL_BIN.read_bytes()

        # Deliverable 1: the two locations are gone from this seed.
        for name in ("Frigimon", "Mojyamon"):
            with self.assertRaises(KeyError):
                self.world.get_location(name)

        with tempfile.TemporaryDirectory() as tmp_dir:
            self.world.generate_output(tmp_dir)
            apdw1 = next(Path(tmp_dir).glob("*.apdw1"))

            patch = rom_module.DigimonWorldProcedurePatch(path=str(apdw1))
            patch.read()
            with mock.patch.object(
                rom_module, "_get_base_rom_as_bytes", lambda: source,
            ):
                patch.patch(str(Path(tmp_dir) / "e2e.cue"))
            patched = (Path(tmp_dir) / "e2epatched.bin").read_bytes()

        self.assertEqual(len(patched), len(source))

        # Deliverable 2a: logo tile + AP palette + CLUT redirects, in
        # BOTH on-disc TIM copies.
        for rows in AP_ITEM_ICON_TILE_BIN_OFFSETS:
            for off, row_bytes in zip(rows, AP_LOGO_TILE_ROW_BYTES,
                                      strict=True):
                self.assertEqual(patched[off:off + 8], row_bytes, hex(off))
        for clut_off in AP_ICON_CLUT_BIN_OFFSETS:
            self.assertEqual(patched[clut_off:clut_off + 32],
                             AP_LOGO_CLUT_BYTES)
        self.assertEqual(patched[item_clut_data_bin_offset(AP_ITEM_ICON_INDEX)],
                         AP_ICON_CLUT_INDEX)
        self.assertEqual(patched[item_clut_data_bin_offset(RAINBOWHORN_ITEM_ID)],
                         RAINBOWHORN_NEW_CLUT_INDEX)

        # Icon-id wrapper + table: the 64-byte trampoline landed, and —
        # with the test multiworld unfilled — every slot falls back to
        # the logo (58 x 83).
        wrap = ROM_ICON_CLAMP_WRAPPER_OFFSET
        self.assertEqual(
            patched[wrap:wrap + len(ROM_ICON_CLAMP_WRAPPER_BYTES)],
            ROM_ICON_CLAMP_WRAPPER_BYTES,
        )
        self.assertEqual(
            patched[AP_ICON_ID_TABLE_OFFSET:
                    AP_ICON_ID_TABLE_OFFSET + AP_ICON_ID_TABLE_SIZE],
            AP_ICON_ID_TABLE_DEFAULT_BYTES,
        )
        # Entry hijack in place (j wrapper), vanilla words preserved in
        # the wrapper body.
        j_word = struct.unpack_from("<I", patched, ROM_ICON_CLAMP_PATCH_OFFSET)[0]
        self.assertEqual(
            j_word, 0x08000000 | ((ROM_ICON_CLAMP_WRAPPER_RAM >> 2) & 0x03FFFFFF),
        )

        # Deliverable 2b: Rainbowhorn's tile was requantized — changed
        # from vanilla, transparency preserved, and exactly the mapping
        # the extension computes from the source CLUTs.
        def clut(index: int) -> tuple[tuple[int, int, int], ...]:
            off = item_tim_clut_bin_offsets(index)[0]
            return rom_module._decode_clut15(source[off:off + 32])

        src_pal, dst_pal = clut(AP_ICON_CLUT_INDEX), clut(RAINBOWHORN_NEW_CLUT_INDEX)
        changed = False
        for rows in RAINBOWHORN_TILE_BIN_OFFSETS:
            for off in rows:
                vanilla_row = source[off:off + 8]
                expected = rom_module._requantize_tile_row(
                    vanilla_row, src_pal, dst_pal,
                )
                self.assertEqual(patched[off:off + 8], expected, hex(off))
                changed |= expected != vanilla_row
                for v_byte, p_byte in zip(vanilla_row, patched[off:off + 8],
                                          strict=True):
                    self.assertEqual(v_byte & 0xF == 0, p_byte & 0xF == 0)
                    self.assertEqual(v_byte >> 4 == 0, p_byte >> 4 == 0)
        self.assertTrue(changed, "requantization was a no-op")

        # Negative tests: neighbors stay vanilla (both copies).
        for slot in (82, 85):
            for rows in item_tim_tile_row_bin_offsets(slot):
                for off in rows:
                    self.assertEqual(patched[off:off + 8],
                                     source[off:off + 8],
                                     f"slot {slot} tile touched")
        for k in (21, 23, 16, 8):
            for off in item_tim_clut_bin_offsets(k):
                self.assertEqual(patched[off:off + 32], source[off:off + 32],
                                 f"CLUT {k} touched")
        for item_id in (82, 85):
            off = item_clut_data_bin_offset(item_id)
            self.assertEqual(patched[off], source[off],
                             f"ITEM_CLUT_DATA[{item_id}] touched")
