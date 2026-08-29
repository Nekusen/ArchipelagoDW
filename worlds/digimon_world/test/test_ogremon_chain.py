"""Ogremon / Whamon quest chain: the MAPHEAD model-load gates and the script cutscene gates of
every fight screen must keep reading the same triggers (``OGREMON_CHAIN_GATE_PAIRS``), and the
standalone's mis-targeted "Ogremon softlock" write stays retired. Research:
``work/dw1_re/decomp/ogremon_chain/NOTES.md`` (2026-08-29)."""

from __future__ import annotations

import os
import struct
import unittest
from pathlib import Path

from ..data.addresses import (
    MAPHEAD_LOAD_GATE_TUNN02,
    OGREMON_CHAIN_GATE_PAIRS,
    ROM_OGREMON_SOFTLOCK_OFFSETS,
)

_VANILLA_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


def _trigger_ids(cond: bytes) -> frozenset[int]:
    """Trigger ids named by an IF condition: ``19 00 | mode | id [| conj | id]*``."""

    return frozenset(struct.unpack_from("<H", cond, i)[0] for i in range(4, len(cond), 4))


class TestGatePairs(unittest.TestCase):
    def test_pairs_agree_and_pin_their_ids(self) -> None:
        for group in OGREMON_CHAIN_GATE_PAIRS:
            ids = {_trigger_ids(cond) for _, _, cond, _ in group}
            self.assertEqual(len(ids), 1, group[0][0])
            self.assertEqual(ids.pop(), group[0][3], group[0][0])
            for label, _off, cond, _ in group:
                self.assertEqual(cond[:2], b"\x19\x00", label)     # IF opcode

    def test_retired_write_is_inside_the_tunnel_gate(self) -> None:
        live = ROM_OGREMON_SOFTLOCK_OFFSETS[1]
        self.assertTrue(MAPHEAD_LOAD_GATE_TUNN02 < live < MAPHEAD_LOAD_GATE_TUNN02 + 10)


@unittest.skipUnless(_VANILLA_BIN.exists() or os.environ.get("DW1_VANILLA_BIN"), "vanilla disc not available")
class TestVanillaBytesOnDisc(unittest.TestCase):
    def test_gate_conditions_and_retired_sites(self) -> None:
        rom = Path(os.environ.get("DW1_VANILLA_BIN", _VANILLA_BIN)).read_bytes()
        for group in OGREMON_CHAIN_GATE_PAIRS:
            for label, off, cond, _ in group:
                self.assertEqual(rom[off:off + len(cond)], cond, label)
                self.assertEqual(rom[off + len(cond):off + len(cond) + 2], b"\x18\x00", label)   # "then"
        for off in ROM_OGREMON_SOFTLOCK_OFFSETS:
            self.assertEqual(struct.unpack_from("<H", rom, off)[0], 150)     # vanilla: trigger 150
