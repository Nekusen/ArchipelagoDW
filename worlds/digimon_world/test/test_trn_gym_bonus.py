"""Green Gym training bonus follows AP-delivered recruits (``TRN_GYM_BONUS_WORD_PATCHES``).

The two ``addiu $a0, $zero, imm`` immediates in TRN_REL.BIN that select the recruit bit
``isTriggerSet`` checks (219 Kabuterimon / 251 Kuwagamon) are redirected to the AP mirror bits
(739 / 771). Lab-validated 2026-08-28 (``work/dw1_re/decomp/trn_gym_bonus/NOTES.md``); these
tests pin the manifest and the patcher's always-on emission.
"""

from __future__ import annotations

import struct
import unittest
from typing import Any

from worlds.Files import APTokenTypes

from .. import rom as rom_module
from ..data.addresses import TRN_GYM_BONUS_WORD_PATCHES, _mips_addiu


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestTrnGymBonus(unittest.TestCase):
    def test_manifest(self) -> None:
        self.assertEqual(
            TRN_GYM_BONUS_WORD_PATCHES,
            ((0x14C88920, 0x240402E3, 0x240400DB), (0x14C8896C, 0x24040303, 0x240400FB)),
        )
        for bin_offset, patched, vanilla in TRN_GYM_BONUS_WORD_PATCHES:
            # both words are addiu $a0, $zero, imm and only the immediate changes
            self.assertEqual(patched >> 16, 0x2404)
            self.assertEqual(vanilla >> 16, 0x2404)
            self.assertEqual((patched & 0xFFFF) - (vanilla & 0xFFFF), 520)   # 200+X -> 720+X
            self.assertEqual(bin_offset % 4, 0)
            self.assertLessEqual((bin_offset - 24) % 2352 + 4, 2048)          # inside user data
        self.assertEqual(TRN_GYM_BONUS_WORD_PATCHES[0][1], _mips_addiu(4, 0, 739))
        self.assertEqual(TRN_GYM_BONUS_WORD_PATCHES[1][1], _mips_addiu(4, 0, 771))

    def test_tokens(self) -> None:
        patch = _TokenCollector()
        rom_module._write_trn_gym_bonus_tokens(patch)  # type: ignore[arg-type]
        self.assertEqual(
            patch.tokens,
            [(off, struct.pack("<I", word)) for off, word, _ in TRN_GYM_BONUS_WORD_PATCHES],
        )
