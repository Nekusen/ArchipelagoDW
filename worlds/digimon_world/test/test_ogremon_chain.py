"""Ogremon / Whamon quest chain: the MAPHEAD model-load gates and the script cutscene gates of
every fight screen must keep reading the same triggers (``OGREMON_CHAIN_GATE_PAIRS``), the
standalone's mis-targeted "Ogremon softlock" write stays retired, the two guards G1 / G2 are
emitted, and the fast-Drimogemon enforcer keys on trigger 140. Research + lab:
``work/dw1_re/decomp/ogremon_chain/NOTES.md`` (2026-08-29)."""

from __future__ import annotations

import asyncio
import os
import struct
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from worlds.Files import APTokenTypes

from .. import client as client_module
from .. import rom as rom_module
from ..client import DigimonWorldClient
from ..data.addresses import (
    MAPHEAD_LOAD_GATE_TUNN02,
    OGREMON_CHAIN_GATE_PAIRS,
    RAM_DRIMOGEMON_FIGHT_BIT,
    RAM_MERAMON_TUNNEL_DIGGING_STATE,
    RAM_MERAMON_TUNNEL_DRIMO_STATE,
    RAM_MERAMON_TUNNEL_STATE,
    ROM_DRIMOGEMON_BERSERK_GATE_IF_VANILLA,
    ROM_DRIMOGEMON_BERSERK_GATE_OFFSET,
    ROM_DRIMOGEMON_BERSERK_GATE_VALUE,
    ROM_OGRE03_NANIMON_GATE_IF_VANILLA,
    ROM_OGRE03_NANIMON_GATE_OFFSETS,
    ROM_OGRE03_NANIMON_GATE_VALUE,
    ROM_OGREMON_SOFTLOCK_OFFSETS,
)

_VANILLA_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


def _trigger_ids(cond: bytes) -> frozenset[int]:
    """Trigger ids named by an IF condition: ``19 00 | mode | id [| conj | id]*``."""

    return frozenset(struct.unpack_from("<H", cond, i)[0] for i in range(4, len(cond), 4))


class _TokenCollector:
    def __init__(self) -> None:
        self.tokens: list[tuple[int, bytes]] = []

    def write_token(self, kind: Any, offset: int, data: bytes) -> None:
        assert kind == APTokenTypes.WRITE
        self.tokens.append((offset, data))


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


class TestGuards(unittest.TestCase):
    def test_three_writes(self) -> None:
        patch = _TokenCollector()
        rom_module._write_ogremon_guard_tokens(patch)  # type: ignore[arg-type]
        self.assertEqual(patch.tokens, [
            (ROM_OGRE03_NANIMON_GATE_OFFSETS[0], b"\xAF\x00"),      # MAPHEAD.SCN, live
            (ROM_OGRE03_NANIMON_GATE_OFFSETS[1], b"\xAF\x00"),      # DG.SCN dead copy
            (ROM_DRIMOGEMON_BERSERK_GATE_OFFSET, b"\x8C\x00"),      # Script 28 §5: 234 -> 140
        ])
        self.assertEqual(struct.unpack("<H", ROM_OGRE03_NANIMON_GATE_VALUE)[0], 175)
        self.assertEqual(struct.unpack("<H", ROM_DRIMOGEMON_BERSERK_GATE_VALUE)[0], 140)
        self.assertEqual(RAM_DRIMOGEMON_FIGHT_BIT, (0x001BDFDE, 4))

    def test_fast_drimogemon_keys_on_trigger_140(self) -> None:
        """The enforcer pins the tunnel only once bit 4 of the trigger-140 byte is set — never on
        the last-battle outcome word DWAP used."""

        fight_byte, fight_bit = RAM_DRIMOGEMON_FIGHT_BIT
        for triggers, expect_writes in ((0x00, False), (0xFF & ~(1 << fight_bit), False), (1 << fight_bit, True)):
            client = DigimonWorldClient()
            seen: list[Any] = []

            async def fake_read(_ctx: Any, requests: list[Any], _t: int = triggers) -> list[bytes]:
                out = []
                for addr, _size, _dom in requests:
                    out.append(bytes([_t]) if addr == fight_byte else b"\x00")
                return out

            async def fake_write(_ctx: Any, writes: list[Any], _seen: list[Any] = seen) -> None:
                _seen.extend(writes)

            with mock.patch.object(client_module.bizhawk, "read", fake_read), \
                    mock.patch.object(client_module.bizhawk, "write", fake_write):
                asyncio.get_event_loop().run_until_complete(client._enforce_fast_drimogemon(mock.Mock()))
            if expect_writes:
                self.assertEqual({w[0] for w in seen}, {RAM_MERAMON_TUNNEL_DRIMO_STATE, RAM_MERAMON_TUNNEL_STATE,
                                                        RAM_MERAMON_TUNNEL_DIGGING_STATE})
            else:
                self.assertEqual(seen, [])


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

    def test_guard_sites(self) -> None:
        rom = Path(os.environ.get("DW1_VANILLA_BIN", _VANILLA_BIN)).read_bytes()
        for off in ROM_OGRE03_NANIMON_GATE_OFFSETS:          # the IF starts 4 bytes before the operand
            self.assertEqual(rom[off - 4:off - 4 + len(ROM_OGRE03_NANIMON_GATE_IF_VANILLA)],
                             ROM_OGRE03_NANIMON_GATE_IF_VANILLA, hex(off))
        off = ROM_DRIMOGEMON_BERSERK_GATE_OFFSET
        self.assertEqual(rom[off - 4:off - 4 + len(ROM_DRIMOGEMON_BERSERK_GATE_IF_VANILLA)],
                         ROM_DRIMOGEMON_BERSERK_GATE_IF_VANILLA)
