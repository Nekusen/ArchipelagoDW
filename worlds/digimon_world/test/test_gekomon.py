"""Gekomon's arena location: the Script 135 §8 splice constants and token, the option gating
and the logic rule. Static research + lab validation in ``work/dw1_re/decomp/gekomon/NOTES.md``."""

from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path
from typing import Any, ClassVar

from worlds.Files import APTokenTypes

from .. import rom as rom_module
from ..client import LOCATION_RAM_BITS
from ..data.addresses import (
    GEKOMON_LOCATION_BIT,
    GEKOMON_LOCATION_NAME,
    GEKOMON_TRIGGER_ID,
    ROM_GEKOMON_GATE_OPERAND_OFFSET,
    ROM_GEKOMON_SPLICE_OFFSET,
    ROM_GEKOMON_SPLICE_VALUE,
    ROM_GEKOMON_SPLICE_VANILLA,
)
from ..locations import LOCATION_NAME_GROUPS, LOCATION_NAME_TO_ID, RECRUIT_NAMES
from .bases import DigimonWorldTestBase

_VANILLA_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


class TestConstants(unittest.TestCase):
    def test_bit_bytes_and_tables(self) -> None:
        self.assertEqual(GEKOMON_TRIGGER_ID, 780)
        self.assertEqual(GEKOMON_LOCATION_BIT, (0x001BE02E, 4))
        self.assertEqual(ROM_GEKOMON_SPLICE_OFFSET, 0x14043E42)
        self.assertEqual(ROM_GEKOMON_SPLICE_VALUE, bytes.fromhex("1C000C03FE00FF00"))   # setTrigger 780; end; EOF
        self.assertEqual(ROM_GEKOMON_SPLICE_VANILLA[:4], bytes.fromhex("FE00FF00"))     # end; EOF; residue...
        self.assertEqual(LOCATION_RAM_BITS[GEKOMON_LOCATION_NAME], GEKOMON_LOCATION_BIT)
        self.assertEqual(LOCATION_NAME_TO_ID[GEKOMON_LOCATION_NAME], 69_064_000)
        self.assertIn(GEKOMON_LOCATION_NAME, LOCATION_NAME_GROUPS["Recruits"])
        self.assertNotIn(GEKOMON_LOCATION_NAME, LOCATION_NAME_GROUPS["Arena Cup"])
        self.assertNotIn(GEKOMON_LOCATION_NAME, RECRUIT_NAMES)      # no item, no 200+X bit, no PP row

    def test_one_write(self) -> None:
        patch = _TokenCollector()
        rom_module._write_gekomon_tokens(patch)  # type: ignore[arg-type]
        self.assertEqual(patch.tokens, [(ROM_GEKOMON_SPLICE_OFFSET, ROM_GEKOMON_SPLICE_VALUE)])


@unittest.skipUnless(_VANILLA_BIN.exists() or os.environ.get("DW1_VANILLA_BIN"), "vanilla disc not available")
class TestVanillaBytesOnDisc(unittest.TestCase):
    def test_splice_and_gate_sites(self) -> None:
        rom = Path(os.environ.get("DW1_VANILLA_BIN", _VANILLA_BIN)).read_bytes()
        self.assertEqual(rom[ROM_GEKOMON_SPLICE_OFFSET:ROM_GEKOMON_SPLICE_OFFSET + 8], ROM_GEKOMON_SPLICE_VANILLA)
        # §8's gate reads Greymon's vanilla bit on the disc (the AP build redirects it to 725).
        self.assertEqual(struct.unpack_from("<H", rom, ROM_GEKOMON_GATE_OPERAND_OFFSET)[0], 205)


class TestArenaLocationsOff(DigimonWorldTestBase):
    """The location is a recruit check, not an arena check: it is in the pool whatever
    ``arena_locations`` says, and it needs Progressive Arena (Gekomon is bundled into it)."""

    options: ClassVar[dict[str, Any]] = {"arena_locations": "off"}

    def test_location_present_and_gated(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn(GEKOMON_LOCATION_NAME, names)
        self.assertAccessDependency([GEKOMON_LOCATION_NAME], [["Progressive Arena"]], only_check_listed=True)


class TestArenaLocationsOn(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"arena_locations": "all"}

    def test_location_present_and_gated(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn(GEKOMON_LOCATION_NAME, names)
        self.assertAccessDependency([GEKOMON_LOCATION_NAME], [["Progressive Arena"]], only_check_listed=True)
