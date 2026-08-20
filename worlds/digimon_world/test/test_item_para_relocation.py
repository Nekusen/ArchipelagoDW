"""Tests for the always-on ITEM_PARA 256-slot relocation.

The design was lab-validated 2026-08-20 through all three PATCH_PROCESS
nets (``work/dw1_re/decomp/item_para_reloc/NOTES.md``); these tests pin
the production port byte-for-byte to the validated values:

* :class:`TestRelocationConstants` — claim word, region geometry, boot
  hook site, seed block, jal redirect (embedded literals from the lab
  spec ``item_para_reloc_spec.py``).
* :class:`TestBootHookBytecode` — the 37-word hook equals the expected
  word list literal, and a delay-slot-faithful R3000 interpreter
  (ported from the lab's Net 1) replays it against a model RAM:
  output == vanilla 4 KB + seed + zeros, displaced callee called
  first, every write inside the table or the hook's own stack frame.
* :class:`TestReaderSitePatches` — all 24 SLUS site pairs and 7
  overlay site pairs match the lab spec literals (patched AND vanilla
  words, overlay .bin offsets).
* :class:`TestRelocationTokens` — :func:`rom.write_patch` emits the
  claim word, hook body, jal redirect, 960-byte seed zero-fill, and
  all 62 reader words on EVERY seed (option-independent), with the
  zero-fill preceding any ext-slot entry token.
* :class:`TestVanillaWordsAgainstSourceBin` — when the canonical
  source .bin is present, every patched site's vanilla word is
  verified in the actual image (skipped on machines without the ROM).
"""

from __future__ import annotations

import hashlib
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
    _ITEM_PARA_READER_SITES,
    BOOT_SEED_HOOK_PATCH_VALUE,
    BOOT_SEED_HOOK_SITE_OFFSET,
    BOOT_SEED_HOOK_SITE_RAM,
    BOOT_SEED_HOOK_VANILLA_WORD,
    EXT_ITEM_PARA_SEED_BIN_OFFSET,
    EXT_ITEM_PARA_SEED_RAM,
    EXT_ITEM_PARA_SEED_SIZE,
    HEAP_CLAIM_WORD_BIN_OFFSET,
    HEAP_CLAIM_WORD_PATCHED,
    HEAP_CLAIM_WORD_RAM,
    HEAP_CLAIM_WORD_VANILLA,
    ITEM_PARA_BOOT_HOOK_BYTES,
    ITEM_PARA_BOOT_HOOK_OFFSET,
    ITEM_PARA_BOOT_HOOK_RAM,
    ITEM_PARA_OVERLAY_WORD_PATCHES,
    ITEM_PARA_READER_WORD_PATCHES,
    ITEM_PARA_RELOC_BASE_KUSEG,
    ITEM_PARA_RELOC_END_KUSEG,
    ITEM_PARA_RELOC_EXT_KUSEG,
    RAM_ITEM_PARA_KUSEG,
    ROM_BIN_SHA1,
    _slus_ram_to_bin_offset,
    read_user_data_bytes,
)
from .bases import DigimonWorldTestBase

# Lab-validated literals (work/dw1_re/patches/item_para_reloc.json):
# per SLUS reader site, (lui_ram, lui_patched, lui_vanilla,
#                        addiu_ram, addiu_patched, addiu_vanilla).
EXPECTED_READER_SITES = (
    (0x800AA3AC, 0x3C02801C, 0x3C028012, 0x800AA3B0, 0x2442FB70, 0x244269DC),
    (0x800AA760, 0x3C02801C, 0x3C028012, 0x800AA764, 0x2442FB70, 0x244269DC),
    (0x800DAB40, 0x3C02801C, 0x3C028012, 0x800DAB48, 0x2442FB70, 0x244269DC),
    (0x800DAC10, 0x3C02801C, 0x3C028012, 0x800DAC18, 0x2442FB70, 0x244269DC),
    (0x800DAD70, 0x3C02801C, 0x3C028012, 0x800DAD74, 0x2442FB70, 0x244269DC),
    (0x800DB7C8, 0x3C02801C, 0x3C028012, 0x800DB7D0, 0x2442FB8C, 0x244269F8),
    (0x800DC814, 0x3C02801C, 0x3C028012, 0x800DC81C, 0x2442FB70, 0x244269DC),
    (0x800DC8E8, 0x3C02801C, 0x3C028012, 0x800DC8F0, 0x2442FB8D, 0x244269F9),
    (0x800DCAB8, 0x3C05801C, 0x3C058012, 0x800DCAC0, 0x24A5FB8A, 0x24A569F6),
    (0x800E4D20, 0x3C02801C, 0x3C028012, 0x800E4D28, 0x2442FB8A, 0x244269F6),
    (0x800FA8F8, 0x3C02801C, 0x3C028012, 0x800FA8FC, 0x2442FB84, 0x244269F0),
    (0x800FAAAC, 0x3C05801C, 0x3C058012, 0x800FAAB4, 0x24A5FB8D, 0x24A569F9),
    (0x800FB018, 0x3C02801C, 0x3C028012, 0x800FB020, 0x2442FB88, 0x244269F4),
    (0x800FB740, 0x3C02801C, 0x3C028012, 0x800FB744, 0x2442FB70, 0x244269DC),
    (0x800FB75C, 0x3C02801C, 0x3C028012, 0x800FB760, 0x2442FB70, 0x244269DC),
    (0x800FD034, 0x3C02801C, 0x3C028012, 0x800FD03C, 0x2442FB84, 0x244269F0),
    (0x800FE7F4, 0x3C02801C, 0x3C028012, 0x800FE7F8, 0x2442FB70, 0x244269DC),
    (0x800FE874, 0x3C02801C, 0x3C028012, 0x800FE878, 0x2442FB84, 0x244269F0),
    (0x800FE8FC, 0x3C02801C, 0x3C028012, 0x800FE900, 0x2442FB88, 0x244269F4),
    (0x800FF01C, 0x3C02801C, 0x3C028012, 0x800FF024, 0x2442FB70, 0x244269DC),
    (0x800FF0A8, 0x3C02801C, 0x3C028012, 0x800FF0B0, 0x2442FB70, 0x244269DC),
    (0x80101A4C, 0x3C02801C, 0x3C028012, 0x80101A54, 0x2442FB70, 0x244269DC),
    (0x80106D90, 0x3C05801C, 0x3C058012, 0x80106D98, 0x24A5FB84, 0x24A569F0),
    (0x8010732C, 0x3C09801C, 0x3C098012, 0x80107330, 0x2529FB88, 0x252969F4),
)

# Per overlay word, (bin_offset, patched, vanilla). Offsets Net-3
# verified in the lab's built image.
EXPECTED_OVERLAY_WORDS = (
    (0x14B6010C, 0x3C02801C, 0x3C028012),   # BTL_REL.BIN+0xFED4
    (0x14B60110, 0x2442FB70, 0x244269DC),   # BTL_REL.BIN+0xFED8
    (0x14B9F07C, 0x3C02801C, 0x3C028012),   # FISH_REL.BIN+0x0BA4
    (0x14B9F084, 0x2442FB70, 0x244269DC),   # FISH_REL.BIN+0x0BAC
    (0x14B9F6E4, 0x3C03801C, 0x3C038012),   # FISH_REL.BIN+0x10DC
    (0x14B9F6EC, 0x2463FB8A, 0x246369F6),   # FISH_REL.BIN+0x10E4
    (0x14BA8A44, 0x3C02801C, 0x3C028012),   # FISH_REL.BIN+0x913C
    (0x14BA8A48, 0x2442FB70, 0x244269DC),   # FISH_REL.BIN+0x9140
    (0x14BA8A84, 0x3C02801C, 0x3C028012),   # FISH_REL.BIN+0x917C
    (0x14BA8A88, 0x2442FB70, 0x244269DC),   # FISH_REL.BIN+0x9180
    (0x14BA8CF8, 0x3C02801C, 0x3C028012),   # FISH_REL.BIN+0x93F0
    (0x14BA8CFC, 0x2442FB70, 0x244269DC),   # FISH_REL.BIN+0x93F4
    (0x14BA8D38, 0x3C02801C, 0x3C028012),   # FISH_REL.BIN+0x9430
    (0x14BA8D3C, 0x2442FB70, 0x244269DC),   # FISH_REL.BIN+0x9434
)

# The 37 hook words: identical to the lab hook except the seed-source
# addiu low half (0x5FE0 -> 0x6800) and byte count (0xE0 -> 0x3C0).
EXPECTED_HOOK_WORDS = (
    0x27BDFFE8, 0xAFBF0014, 0x0C03BAF7, 0x00000000,
    0x3C088012, 0x250869DC, 0x3C09801C, 0x2529FB70, 0x240A1000,
    0x8D0B0000, 0x25080004, 0xAD2B0000, 0x254AFFFC, 0x1540FFFB, 0x25290004,
    0x3C09801C, 0x25290B70, 0x240A1000,
    0xAD200000, 0x254AFFFC, 0x1540FFFD, 0x25290004,
    0x3C088009, 0x25086800, 0x3C09801C, 0x25290B70, 0x240A03C0,
    0x8D0B0000, 0x25080004, 0xAD2B0000, 0x254AFFFC, 0x1540FFFB, 0x25290004,
    0x8FBF0014, 0x27BD0018, 0x03E00008, 0x00000000,
)


def simulate_hook(
    words: list[int], base_ram: int, ram: bytearray, fun_init: int,
) -> tuple[list[tuple[int, int]], list[int]]:
    """Execute the hook against a 2 MB model RAM with R3000 load-delay
    and branch-delay semantics (port of the lab's Net-1 interpreter).

    The jal to ``fun_init`` is stubbed: it records the call, clobbers
    the caller-saved registers (as the real callee + InitHeap3 may),
    and returns. Returns ``(writes, calls)`` where ``writes`` is
    ``[(phys_addr, size)]``.
    """

    sp_reg, ra_reg, gp_reg = 29, 31, 28
    regs = [0] * 32
    regs[sp_reg] = 0x001FFC00 + 0x80000000
    regs[ra_reg] = 0xDEAD0000
    regs[gp_reg] = 0x8013BB2C
    pc = base_ram
    pending_load: tuple[int, int] | None = None
    writes: list[tuple[int, int]] = []
    calls: list[int] = []
    steps = 0

    def rd32(addr: int) -> int:
        return struct.unpack_from("<I", ram, addr & 0x1FFFFF)[0]

    def wr32(addr: int, val: int) -> None:
        p = addr & 0x1FFFFF
        struct.pack_into("<I", ram, p, val & 0xFFFFFFFF)
        writes.append((p, 4))

    def fetch(addr: int) -> int:
        idx = (addr - base_ram) // 4
        if 0 <= idx < len(words):
            return words[idx]
        raise AssertionError(f"PC left the hook body: 0x{addr:08X}")

    def execute(word: int, cur_pc: int) -> int | str | None:
        nonlocal pending_load
        op = word >> 26
        rs = (word >> 21) & 31
        rt = (word >> 16) & 31
        imm = word & 0xFFFF
        simm = imm - 0x10000 if imm & 0x8000 else imm
        new_load: tuple[int, int] | None = None
        branch: int | str | None = None
        if word == 0:
            pass
        elif op == 0x00 and (word & 0x3F) == 0x08:          # jr
            branch = regs[rs]
        elif op == 0x0F:                                     # lui
            regs[rt] = (imm << 16) & 0xFFFFFFFF
        elif op == 0x09:                                     # addiu
            regs[rt] = (regs[rs] + simm) & 0xFFFFFFFF
        elif op == 0x23:                                     # lw
            assert (regs[rs] + simm) % 4 == 0, "unaligned lw"
            new_load = (rt, rd32(regs[rs] + simm))
        elif op == 0x2B:                                     # sw
            assert (regs[rs] + simm) % 4 == 0, "unaligned sw"
            wr32(regs[rs] + simm, regs[rt])
        elif op == 0x05:                                     # bne
            if regs[rs] != regs[rt]:
                branch = cur_pc + 4 + simm * 4
        elif op == 0x03:                                     # jal
            target = (cur_pc & 0xF0000000) | ((word & 0x03FFFFFF) << 2)
            calls.append(target)
            if target != fun_init:
                raise AssertionError(f"unexpected jal 0x{target:08X}")
            regs[ra_reg] = cur_pc + 8
            for r in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 24, 25):
                regs[r] = 0xBADBAD00 + r
            branch = "stub-return"
        else:
            raise AssertionError(f"unhandled opcode 0x{op:02X} in 0x{word:08X}")
        if pending_load is not None:
            regs[pending_load[0]] = pending_load[1]
        pending_load = new_load
        return branch

    while True:
        steps += 1
        assert steps < 100_000, "hook simulation runaway"
        branch = execute(fetch(pc), pc)
        if branch is None:
            pc += 4
            continue
        delay_branch = execute(fetch(pc + 4), pc + 4)
        assert delay_branch is None, "branch in delay slot"
        if branch == "stub-return":
            pc = pc + 8
        elif branch == 0xDEAD0000:
            break
        else:
            assert isinstance(branch, int)
            pc = branch
    return writes, calls


class TestRelocationConstants(unittest.TestCase):
    def test_heap_claim_word(self) -> None:
        self.assertEqual(HEAP_CLAIM_WORD_RAM, 0x80113AB4)
        self.assertEqual(HEAP_CLAIM_WORD_BIN_OFFSET, 0x14D51A7C)
        self.assertEqual(HEAP_CLAIM_WORD_VANILLA, 0x801BFB64)
        self.assertEqual(HEAP_CLAIM_WORD_PATCHED, 0x801C1B64)

    def test_region_geometry(self) -> None:
        self.assertEqual(ITEM_PARA_RELOC_BASE_KUSEG, 0x801BFB70)
        self.assertEqual(ITEM_PARA_RELOC_EXT_KUSEG, 0x801C0B70)
        self.assertEqual(ITEM_PARA_RELOC_END_KUSEG, 0x801C1B70)
        # Exact fit: 256 slots x 32 B with zero spare bytes before the
        # new arena base.
        self.assertEqual(
            ITEM_PARA_RELOC_END_KUSEG - ITEM_PARA_RELOC_BASE_KUSEG, 256 * 32,
        )

    def test_boot_hook_site(self) -> None:
        self.assertEqual(BOOT_SEED_HOOK_SITE_RAM, 0x800EE80C)
        self.assertEqual(BOOT_SEED_HOOK_VANILLA_WORD, 0x0C03BAF7)
        self.assertEqual(ITEM_PARA_BOOT_HOOK_RAM, 0x800965BC)
        self.assertEqual(BOOT_SEED_HOOK_PATCH_VALUE, 0x0C02596F)

    def test_seed_block(self) -> None:
        self.assertEqual(EXT_ITEM_PARA_SEED_RAM, 0x80096800)
        self.assertEqual(EXT_ITEM_PARA_SEED_SIZE, 960)
        self.assertEqual(
            EXT_ITEM_PARA_SEED_BIN_OFFSET,
            _slus_ram_to_bin_offset(EXT_ITEM_PARA_SEED_RAM),
        )


class TestBootHookBytecode(unittest.TestCase):
    def test_hook_words_match_expected(self) -> None:
        words = struct.unpack("<37I", ITEM_PARA_BOOT_HOOK_BYTES)
        self.assertEqual(words, EXPECTED_HOOK_WORDS)

    def test_interpreter_replay(self) -> None:
        # Model RAM: recognizable vanilla table + seed patterns; poison
        # the destination so untouched bytes would show.
        ram = bytearray(0x200000)
        vanilla = bytes((7 * i + 3) & 0xFF for i in range(4096))
        seed = bytes((11 * i + 5) & 0xFF for i in range(EXT_ITEM_PARA_SEED_SIZE))
        vp = RAM_ITEM_PARA_KUSEG & 0x1FFFFF
        sp = EXT_ITEM_PARA_SEED_RAM & 0x1FFFFF
        base = ITEM_PARA_RELOC_BASE_KUSEG & 0x1FFFFF
        end = ITEM_PARA_RELOC_END_KUSEG & 0x1FFFFF
        ram[vp:vp + 4096] = vanilla
        ram[sp:sp + len(seed)] = seed
        # Poison the destination AND the 16 bytes beyond it (the new
        # arena base block header) so untouched bytes would show.
        ram[base:end + 16] = b"\xEE" * (0x2000 + 16)

        words = list(struct.unpack("<37I", ITEM_PARA_BOOT_HOOK_BYTES))
        writes, calls = simulate_hook(
            words, ITEM_PARA_BOOT_HOOK_RAM, ram, 0x800EEBDC,
        )

        # Displaced callee called exactly once, before anything else.
        self.assertEqual(calls, [0x800EEBDC])
        # Output = vanilla 4 KB + seed + zeros.
        expected = vanilla + seed + b"\x00" * (0x1000 - len(seed))
        self.assertEqual(bytes(ram[base:end]), expected)
        # Write containment: every store inside the table or the hook's
        # own 0x18-byte stack frame.
        stack_lo = (0x001FFC00 + 0x80000000 - 0x18) & 0x1FFFFF
        for addr, _size in writes:
            in_table = base <= addr < end
            in_stack = stack_lo <= addr < stack_lo + 0x18
            self.assertTrue(in_table or in_stack,
                            f"stray hook write at phys 0x{addr:06X}")
        # The zero loop must never touch the new arena base header at
        # RELOC_END (0x801C1B70) — the poison there must survive.
        self.assertEqual(bytes(ram[end:end + 16]), b"\xEE" * 16)


class TestReaderSitePatches(unittest.TestCase):
    def test_slus_site_count_and_order(self) -> None:
        self.assertEqual(len(_ITEM_PARA_READER_SITES), 24)
        self.assertEqual(len(ITEM_PARA_READER_WORD_PATCHES), 48)
        self.assertEqual(len(EXPECTED_READER_SITES), 24)

    def test_slus_sites_match_lab_spec(self) -> None:
        for i, (lui_ram, lui_patch, lui_van,
                addiu_ram, addiu_patch, addiu_van) in enumerate(EXPECTED_READER_SITES):
            site_lui_ram, site_addiu_ram, _reg, _field = _ITEM_PARA_READER_SITES[i]
            self.assertEqual(site_lui_ram, lui_ram, f"site {i} lui RAM")
            self.assertEqual(site_addiu_ram, addiu_ram, f"site {i} addiu RAM")
            got_lui = ITEM_PARA_READER_WORD_PATCHES[2 * i]
            got_addiu = ITEM_PARA_READER_WORD_PATCHES[2 * i + 1]
            self.assertEqual(got_lui[0], _slus_ram_to_bin_offset(lui_ram))
            self.assertEqual(got_lui[1], lui_patch, f"site {i} lui patched")
            self.assertEqual(got_lui[2], lui_van, f"site {i} lui vanilla")
            self.assertEqual(got_addiu[0], _slus_ram_to_bin_offset(addiu_ram))
            self.assertEqual(got_addiu[1], addiu_patch, f"site {i} addiu patched")
            self.assertEqual(got_addiu[2], addiu_van, f"site {i} addiu vanilla")

    def test_overlay_words_match_lab_spec(self) -> None:
        self.assertEqual(len(ITEM_PARA_OVERLAY_WORD_PATCHES), 14)
        for i, (off, patched, vanilla) in enumerate(EXPECTED_OVERLAY_WORDS):
            fname, got_off, got_patched, got_vanilla = (
                ITEM_PARA_OVERLAY_WORD_PATCHES[i]
            )
            self.assertIn(fname, ("BTL_REL.BIN", "FISH_REL.BIN"))
            self.assertEqual(got_off, off, f"overlay word {i} offset")
            self.assertEqual(got_patched, patched, f"overlay word {i} patched")
            self.assertEqual(got_vanilla, vanilla, f"overlay word {i} vanilla")

    def test_uniform_hi_half(self) -> None:
        # Every patched lui carries hi 0x801C (sign-extension window).
        for _off, patched, _van in ITEM_PARA_READER_WORD_PATCHES[::2]:
            self.assertEqual(patched & 0xFFFF, 0x801C)


def _parse_token_blob(blob: bytes) -> list[tuple[int, int, bytes]]:
    n = int.from_bytes(blob[:4], "little")
    out: list[tuple[int, int, bytes]] = []
    i = 4
    for _ in range(n):
        ttype = blob[i]
        off = int.from_bytes(blob[i + 1:i + 5], "little")
        sz = int.from_bytes(blob[i + 5:i + 9], "little")
        out.append((ttype, off, bytes(blob[i + 9:i + 9 + sz])))
        i += 9 + sz
    return out


class _CapturedPatch:
    @staticmethod
    def run(world: Any) -> list[tuple[int, int, bytes]]:
        captured: dict[str, bytes] = {}

        def fake_write(self_patch: Any, target: str) -> None:
            with zipfile.ZipFile(target, "w") as _:
                pass
            captured.update(self_patch.files)

        with mock.patch.object(
            rom_module.DigimonWorldProcedurePatch, "write", fake_write,
        ), tempfile.TemporaryDirectory() as tmp_dir:
            world.generate_output(tmp_dir)

        return _parse_token_blob(captured["token_data.bin"])


class TestRelocationTokens(DigimonWorldTestBase):
    """The relocation tokens are emitted on every seed (default
    options — both shop options off)."""

    options: ClassVar[dict[str, Any]] = {}

    def setUp(self) -> None:
        super().setUp()
        self.tokens = _CapturedPatch.run(self.world)
        self.observed_last: dict[int, bytes] = {}
        for _t, off, data in self.tokens:
            self.observed_last[off] = data

    def test_all_tokens_are_writes(self) -> None:
        for ttype, *_ in self.tokens:
            self.assertEqual(ttype, APTokenTypes.WRITE)

    def test_claim_word_token(self) -> None:
        self.assertEqual(
            self.observed_last.get(HEAP_CLAIM_WORD_BIN_OFFSET),
            struct.pack("<I", HEAP_CLAIM_WORD_PATCHED),
        )

    def test_hook_body_token(self) -> None:
        self.assertEqual(
            self.observed_last.get(ITEM_PARA_BOOT_HOOK_OFFSET),
            ITEM_PARA_BOOT_HOOK_BYTES,
        )

    def test_jal_redirect_token(self) -> None:
        self.assertEqual(
            self.observed_last.get(BOOT_SEED_HOOK_SITE_OFFSET),
            struct.pack("<I", BOOT_SEED_HOOK_PATCH_VALUE),
        )

    def test_seed_zero_fill_token(self) -> None:
        self.assertEqual(
            self.observed_last.get(EXT_ITEM_PARA_SEED_BIN_OFFSET),
            b"\x00" * EXT_ITEM_PARA_SEED_SIZE,
        )

    def test_all_62_reader_words_emitted(self) -> None:
        for off, patched, _van in ITEM_PARA_READER_WORD_PATCHES:
            self.assertEqual(self.observed_last.get(off),
                             struct.pack("<I", patched), hex(off))
        for _fname, off, patched, _van in ITEM_PARA_OVERLAY_WORD_PATCHES:
            self.assertEqual(self.observed_last.get(off),
                             struct.pack("<I", patched), hex(off))


class TestRelocationTokensWithShops(DigimonWorldTestBase):
    """With both shop options on, the ext entries overlay the seed
    zero-fill (insertion order)."""

    options: ClassVar[dict[str, Any]] = {
        "recycle_shop_locations": 1,
        "merit_shop_locations": 1,
    }

    def setUp(self) -> None:
        super().setUp()
        self.tokens = _CapturedPatch.run(self.world)

    def test_zero_fill_before_all_ext_entries(self) -> None:
        seed_lo = EXT_ITEM_PARA_SEED_BIN_OFFSET
        seed_hi = seed_lo + EXT_ITEM_PARA_SEED_SIZE
        zero_index = None
        entry_indices = []
        for i, (_t, off, data) in enumerate(self.tokens):
            if off == seed_lo and len(data) == EXT_ITEM_PARA_SEED_SIZE:
                zero_index = i
            elif seed_lo <= off < seed_hi and len(data) == 32:
                entry_indices.append(i)
        self.assertIsNotNone(zero_index)
        # 7 recycle + 14 merit ext entries.
        self.assertEqual(len(entry_indices), 21)
        self.assertTrue(all(i > zero_index for i in entry_indices))


class TestVanillaWordsAgainstSourceBin(unittest.TestCase):
    """Byte-verify every patched site's vanilla word in the canonical
    source image (skipped when the ROM is not on this machine)."""

    ROM_PATH: ClassVar[Path] = (
        Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"
    )

    @classmethod
    def setUpClass(cls) -> None:
        if not cls.ROM_PATH.is_file():
            raise unittest.SkipTest("canonical source .bin not present")
        cls.rom = cls.ROM_PATH.read_bytes()

    def test_rom_identity(self) -> None:
        self.assertEqual(
            hashlib.sha1(self.rom).hexdigest().upper(), ROM_BIN_SHA1.upper(),
        )

    def test_claim_word_vanilla(self) -> None:
        got = struct.unpack_from("<I", self.rom, HEAP_CLAIM_WORD_BIN_OFFSET)[0]
        self.assertEqual(got, HEAP_CLAIM_WORD_VANILLA)

    def test_boot_jal_vanilla_and_delay_nop(self) -> None:
        data = read_user_data_bytes(self.rom, BOOT_SEED_HOOK_SITE_OFFSET, 8)
        self.assertEqual(struct.unpack_from("<I", data, 0)[0],
                         BOOT_SEED_HOOK_VANILLA_WORD)
        self.assertEqual(struct.unpack_from("<I", data, 4)[0], 0)

    def test_slus_reader_vanilla_words(self) -> None:
        for off, _patched, vanilla in ITEM_PARA_READER_WORD_PATCHES:
            got = struct.unpack_from("<I", self.rom, off)[0]
            self.assertEqual(got, vanilla,
                             f"vanilla word drift at bin 0x{off:X}")

    def test_overlay_reader_vanilla_words(self) -> None:
        for fname, off, _patched, vanilla in ITEM_PARA_OVERLAY_WORD_PATCHES:
            got = struct.unpack_from("<I", self.rom, off)[0]
            self.assertEqual(got, vanilla,
                             f"vanilla word drift in {fname} at bin 0x{off:X}")
