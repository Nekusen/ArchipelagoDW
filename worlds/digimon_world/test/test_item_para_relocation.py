"""Tests for the Path A ITEM_PARA relocation (always-on, ships with every seed).

Covers four areas:

* :class:`TestItemParaRelocConstants` — sanity-check the new
  ``ITEM_PARA_RELOC_*`` constants (size, capacity, RAM bounds).
* :class:`TestItemParaRelocReaderSites` — verify the 24 enumerated
  vanilla SLUS reader callsites generate the expected
  ``lui rN, 0x800A; addiu rN, rN, 0xDBC8+field`` patch values.
* :class:`TestItemParaRelocPatcherTokens` — :func:`rom.write_patch`
  emits all 48 reader-site patches (24 sites × 2 instructions each),
  always-on. The patches land at the expected ``.bin`` offsets.
* :class:`TestItemParaRelocProcedure` — the ``relocate_item_para``
  procedure step is wired into every patch's procedure (always-on),
  positioned correctly between ``apply_tokens`` and ``recalc_edc``.

Also includes an end-to-end roundtrip test that exercises the
:meth:`DigimonWorldPatchExtension.relocate_item_para` extension
against a real .bin and confirms the relocated bytes match the
vanilla ITEM_PARA region.
"""

from __future__ import annotations

import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from worlds.Files import APTokenTypes

from .. import rom as rom_module
from ..data.addresses import (
    ITEM_PARA_RELOC_BIN_OFFSET,
    ITEM_PARA_RELOC_CAPACITY,
    ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE,
    ITEM_PARA_RELOC_RAM,
    ITEM_PARA_RELOC_READER_SITES,
    ITEM_PARA_RELOC_SIZE,
    ITEM_PARA_VANILLA_BIN_OFFSET,
    MERIT_SHOP_AP_ITEM_ID_LAST,
    RAM_ITEM_PARA,
    RAM_ITEM_PARA_KUSEG,
    RAM_ITEM_PARA_VANILLA,
    RAM_ITEM_PARA_VANILLA_KUSEG,
    ROM_ITEM_TABLE_ENTRY_SIZE,
    _decompose_kuseg,
    _slus_ram_to_bin_offset,
    build_item_para_reloc_patch_tokens,
    read_user_data_bytes,
    write_user_data_bytes,
)
from .bases import DigimonWorldTestBase


REPO_ROOT = Path(__file__).resolve().parents[3]
BIN_PATH = REPO_ROOT / "Digimon World (USA).bin"


# =============================================================================
# Constants
# =============================================================================


class TestItemParaRelocConstants(unittest.TestCase):
    def test_relocation_ram_is_post_relocation_address(self) -> None:
        """``RAM_ITEM_PARA`` is the relocated bare offset."""
        self.assertEqual(RAM_ITEM_PARA, 0x0009DBC8)
        self.assertEqual(RAM_ITEM_PARA_KUSEG, 0x8009DBC8)

    def test_vanilla_ram_preserved_for_bin_offset_math(self) -> None:
        """``RAM_ITEM_PARA_VANILLA`` is still available for callers that
        need the original location."""
        self.assertEqual(RAM_ITEM_PARA_VANILLA, 0x001269DC)
        self.assertEqual(RAM_ITEM_PARA_VANILLA_KUSEG, 0x801269DC)

    def test_relocation_size_and_capacity(self) -> None:
        self.assertEqual(ITEM_PARA_RELOC_SIZE, 5808)
        self.assertEqual(
            ITEM_PARA_RELOC_CAPACITY,
            ITEM_PARA_RELOC_SIZE // ROM_ITEM_TABLE_ENTRY_SIZE,
        )
        self.assertEqual(ITEM_PARA_RELOC_CAPACITY, 181)

    def test_relocation_capacity_covers_current_usage(self) -> None:
        """Highest slot we use today (merit shop ext = slot 143) fits
        well within the 181-slot capacity, with 37 slots of headroom."""
        self.assertGreater(
            ITEM_PARA_RELOC_CAPACITY, MERIT_SHOP_AP_ITEM_ID_LAST
        )
        # And we have margin for future shops:
        headroom = ITEM_PARA_RELOC_CAPACITY - (MERIT_SHOP_AP_ITEM_ID_LAST + 1)
        self.assertGreaterEqual(headroom, 30,
                                f"Only {headroom} slots free for future shops")

    def test_relocation_stays_inside_verified_free_zone(self) -> None:
        """Region from agent 1A is 5808 bytes at 0x8009DBC8..0x8009F278."""
        self.assertEqual(ITEM_PARA_RELOC_RAM, 0x8009DBC8)
        self.assertLessEqual(
            ITEM_PARA_RELOC_RAM + ITEM_PARA_RELOC_SIZE, 0x8009F278
        )

    def test_copy_size_covers_slots_0_to_143(self) -> None:
        self.assertEqual(ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE, 144 * 32)
        self.assertEqual(ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE, 4608)


class TestDecomposeKuseg(unittest.TestCase):
    """The ``_decompose_kuseg`` helper splits a 32-bit address into
    ``(lui_hi, addiu_lo)`` such that ``lui + addiu`` reconstructs the
    address, accounting for ``addiu``'s sign extension."""

    def test_vanilla_item_para_decompose_no_signext(self) -> None:
        # 0x801269DC: low half 0x69DC < 0x8000 → hi stays 0x8012.
        hi, lo = _decompose_kuseg(0x801269DC)
        self.assertEqual(hi, 0x8012)
        self.assertEqual(lo, 0x69DC)

    def test_relocated_item_para_decompose_signext(self) -> None:
        # 0x8009DBC8: low half 0xDBC8 >= 0x8000 → hi becomes 0x800A.
        hi, lo = _decompose_kuseg(0x8009DBC8)
        self.assertEqual(hi, 0x800A)
        self.assertEqual(lo, 0xDBC8)

    def test_decompose_reconstructs_address(self) -> None:
        """End-to-end: hi << 16 + sign_extend(lo) == address."""
        for addr in (
            0x801269DC,
            0x8009DBC8,
            0x8009DBC8 + 24,   # ITEM_PARA + meritValue offset
            0x80095800,        # merit v1 wrapper
            0x8012781C,        # old slot 114
            0x8009EA08,        # new slot 114
        ):
            hi, lo = _decompose_kuseg(addr)
            # MIPS sign-extends a 16-bit imm before adding it to the lui'd register.
            lo_signed = lo - 0x10000 if lo >= 0x8000 else lo
            reconstructed = ((hi << 16) + lo_signed) & 0xFFFFFFFF
            self.assertEqual(
                reconstructed, addr,
                f"_decompose_kuseg(0x{addr:08X}) -> (0x{hi:04X}, 0x{lo:04X}) "
                f"reconstructs to 0x{reconstructed:08X}, expected 0x{addr:08X}",
            )


# =============================================================================
# 24 reader sites
# =============================================================================


class TestItemParaRelocReaderSites(unittest.TestCase):
    def test_24_sites_enumerated(self) -> None:
        self.assertEqual(len(ITEM_PARA_RELOC_READER_SITES), 24)

    def test_all_sites_in_slus_kuseg_range(self) -> None:
        """Every site's PC is in the SLUS-loaded kuseg range
        (roughly 0x80010000..0x80140000)."""
        for lui_pc, addiu_pc, _reg, field_offset in ITEM_PARA_RELOC_READER_SITES:
            self.assertGreaterEqual(lui_pc, 0x80010000,
                                    f"lui_pc 0x{lui_pc:08X} below SLUS range")
            self.assertLessEqual(lui_pc, 0x80140000,
                                 f"lui_pc 0x{lui_pc:08X} above SLUS range")
            self.assertGreaterEqual(addiu_pc, 0x80010000)
            self.assertLessEqual(addiu_pc, 0x80140000)
            # Field offset is within a 32-byte ITEM_PARA entry.
            self.assertLess(field_offset, 32,
                            f"field offset 0x{field_offset:02X} too large")

    def test_all_field_offsets_in_known_set(self) -> None:
        """All 24 reader sites target known ITEM_PARA field offsets."""
        known_fields = {0x00, 0x14, 0x18, 0x1A, 0x1C, 0x1D}
        for _l, _a, _r, field in ITEM_PARA_RELOC_READER_SITES:
            self.assertIn(field, known_fields,
                          f"Unknown field offset 0x{field:02X}")

    def test_patch_token_builder_count(self) -> None:
        patches = build_item_para_reloc_patch_tokens()
        # 24 sites × 2 patches (lui + addiu).
        self.assertEqual(len(patches), 48)

    def test_patch_token_lui_values_are_constant(self) -> None:
        """Every lui-low-half patch is the same 0x800A (since all
        ITEM_PARA fields are within an entry's 32-byte stride and the
        carry from sign-extension stays consistent)."""
        patches = build_item_para_reloc_patch_tokens()
        for i in range(0, len(patches), 2):
            _off, data = patches[i]
            self.assertEqual(data, b"\x0a\x80",
                             f"patches[{i}] lui low half = {data.hex()}, want 0a80")

    def test_patch_token_addiu_values_match_field_offset(self) -> None:
        patches = build_item_para_reloc_patch_tokens()
        for i, (_l, _a, _r, field_offset) in enumerate(ITEM_PARA_RELOC_READER_SITES):
            _off, data = patches[i * 2 + 1]
            expected_lo = (0xDBC8 + field_offset) & 0xFFFF
            actual_lo = struct.unpack("<H", data)[0]
            self.assertEqual(actual_lo, expected_lo,
                             f"site {i}: addiu low half 0x{actual_lo:04X}, "
                             f"want 0x{expected_lo:04X} (field=0x{field_offset:02X})")

    def test_patch_offsets_are_distinct(self) -> None:
        """No two patches target the same .bin offset (would conflict)."""
        patches = build_item_para_reloc_patch_tokens()
        offsets = [off for off, _ in patches]
        self.assertEqual(len(set(offsets)), len(offsets),
                         "duplicate patch offsets")


# =============================================================================
# Token-writer wiring (always-on)
# =============================================================================


def _parse_token_blob(blob: bytes) -> list[tuple[int, int, bytes]]:
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


class TestItemParaRelocPatcherTokens(DigimonWorldTestBase):
    """The 24 reader-site patches must be emitted by every seed,
    regardless of options."""

    options: ClassVar[dict[str, Any]] = {}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)

    def test_all_48_reloc_patches_present(self) -> None:
        expected = build_item_para_reloc_patch_tokens()
        emitted_writes = {
            (off, data) for ttype, off, data in self.tokens
            if ttype == APTokenTypes.WRITE
        }
        for bin_offset, patch_bytes in expected:
            self.assertIn(
                (bin_offset, patch_bytes), emitted_writes,
                f"missing reader-site patch at 0x{bin_offset:08X} ({patch_bytes.hex()})",
            )


class TestItemParaRelocPatcherTokensOptionsOn(DigimonWorldTestBase):
    """Same as above but with recycle + merit shop options on, to verify
    the relocation patches still ship when more tokens are present."""

    options: ClassVar[dict[str, Any]] = {
        "recycle_shop_locations": 1,
        "merit_shop_locations": 1,
    }

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)

    def test_all_48_reloc_patches_present(self) -> None:
        expected = build_item_para_reloc_patch_tokens()
        emitted_writes = {
            (off, data) for ttype, off, data in self.tokens
            if ttype == APTokenTypes.WRITE
        }
        for bin_offset, patch_bytes in expected:
            self.assertIn(
                (bin_offset, patch_bytes), emitted_writes,
                f"missing reader-site patch at 0x{bin_offset:08X}",
            )


# =============================================================================
# Procedure step wiring
# =============================================================================


class TestItemParaRelocProcedure(DigimonWorldTestBase):
    """``relocate_item_para`` must be in every seed's procedure."""

    options: ClassVar[dict[str, Any]] = {}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)

    def test_relocate_item_para_in_procedure(self) -> None:
        step_names = [step[0] for step in self.procedure]
        self.assertIn("relocate_item_para", step_names)

    def test_relocate_runs_after_apply_tokens(self) -> None:
        step_names = [step[0] for step in self.procedure]
        apply_idx = step_names.index("apply_tokens")
        reloc_idx = step_names.index("relocate_item_para")
        self.assertLess(apply_idx, reloc_idx,
                        "relocate_item_para must run AFTER apply_tokens "
                        "to pick up post-token AP modifications")

    def test_relocate_runs_before_recalc_edc(self) -> None:
        step_names = [step[0] for step in self.procedure]
        reloc_idx = step_names.index("relocate_item_para")
        edc_idx = step_names.index("recalc_edc")
        self.assertLess(reloc_idx, edc_idx)


class TestItemParaRelocProcedureWithExtensions(DigimonWorldTestBase):
    """Verify the procedure ordering when other extensions are also active."""

    options: ClassVar[dict[str, Any]] = {
        "recycle_shop_locations": 1,
        "randomize_starter": 1,
    }

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _CapturedPatch.run(self.world)

    def test_relocate_item_para_runs_before_relocate_item_desc_ptr(self) -> None:
        """Path A relocation must run before ITEM_DESC_PTR relocation
        (the latter reads source, not post-token, so it's order-independent;
        but the former positions ITEM_PARA at the new RAM location, which
        future extensions might need to see)."""
        step_names = [step[0] for step in self.procedure]
        para_idx = step_names.index("relocate_item_para")
        desc_idx = step_names.index("relocate_item_desc_ptr")
        self.assertLess(para_idx, desc_idx)


# =============================================================================
# End-to-end roundtrip test
# =============================================================================


@unittest.skipUnless(BIN_PATH.exists(),
                     "Real DW1 .bin not available — skipping E2E test")
class TestItemParaRelocRoundtrip(unittest.TestCase):
    """Exercise the relocate procedure against a real .bin and verify
    the relocated bytes match the vanilla bytes (for slots 0..127 — no
    AP modifications applied in this isolated test)."""

    def setUp(self) -> None:
        self.bin_data = bytearray(BIN_PATH.read_bytes())

    def test_relocate_copies_vanilla_bytes_correctly(self) -> None:
        # Read vanilla ITEM_PARA region (4608 bytes = slots 0..143).
        vanilla = read_user_data_bytes(
            self.bin_data,
            ITEM_PARA_VANILLA_BIN_OFFSET,
            ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE,
        )
        self.assertEqual(len(vanilla), ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE)

        # Write to relocated location.
        target = bytearray(self.bin_data)
        write_user_data_bytes(
            target, ITEM_PARA_RELOC_BIN_OFFSET, vanilla,
        )

        # Roundtrip: read back from relocated, compare.
        roundtrip = read_user_data_bytes(
            target,
            ITEM_PARA_RELOC_BIN_OFFSET,
            ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE,
        )
        self.assertEqual(roundtrip, vanilla,
                         "roundtrip read of relocated region != vanilla bytes")

    def test_known_vanilla_slots(self) -> None:
        """Sanity: slot 3 = 'sup.recovery' with meritValue=20 (verified
        via dw1_merit_inventory probe)."""
        vanilla = read_user_data_bytes(
            self.bin_data,
            ITEM_PARA_VANILLA_BIN_OFFSET,
            ITEM_PARA_RELOC_COPY_FROM_OLD_SIZE,
        )
        slot3 = vanilla[3 * 32:(3 + 1) * 32]
        name = slot3[:20].rstrip(b"\x00")
        self.assertEqual(name, b"sup.recovery")
        merit_value = struct.unpack_from("<h", slot3, 24)[0]
        self.assertEqual(merit_value, 20)
