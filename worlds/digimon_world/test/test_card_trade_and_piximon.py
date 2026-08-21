"""Tests for the 2026-08-21 QoL batch closers: the card-trade value
multiplier and the Piximon Training Manual location.

* :class:`TestCardTradeManifest` — table geometry, vanilla-value
  distribution, sector-hop arithmetic (pure manifest, no ROM).
* :class:`TestCardTradeTokens*` — token-emission matrix for the
  ``card_trade_multiplier`` option (on / default-off / clamp).
* :class:`TestPiximonManualPatcher*` — token + location + rule matrix
  for the ``piximon_manual_location`` toggle.
* :class:`TestPiximonManualClientWiring` — the client poll-table entry.
* :class:`TestVanillaAnchorsAgainstSourceBin` — byte-verifies every
  patched offset's vanilla content in the canonical SLUS-01032 dump
  (auto-skipped on machines without the ROM).
* :class:`TestEndToEndBothFeatures` — full generate -> .apdw1 ->
  procedure-apply -> byte-verify with both features enabled (also
  ROM-gated).
"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from .. import rom as rom_module
from ..data.addresses import (
    AP_TRIGGER_ARRAY_BASE,
    CARD_TRADE_ENTRY_STRIDE,
    CARD_TRADE_TABLE_ENTRIES,
    CARD_TRADE_VALUE_CAP,
    CARD_TRADE_VALUE_TABLE_BIN_OFFSET,
    CARD_TRADE_VALUE_TABLE_RAM,
    CARD_TRADE_VANILLA_VALUES,
    PIXIMON_MANUAL_GIVEITEM_SCRIPT,
    PIXIMON_MANUAL_GIVEITEM_VM_OFFSET,
    PIXIMON_MANUAL_LOCATION_BIT,
    PIXIMON_MANUAL_LOCATION_NAME,
    PIXIMON_MANUAL_LOCATION_RAM_BITS,
    PIXIMON_MANUAL_TRIGGER_ID,
    ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS,
    ROM_PIXIMON_MANUAL_GIVEITEM_VANILLA,
    ROM_PIXIMON_MANUAL_NEUTER_VALUE,
    card_trade_value_bin_offset,
    read_user_data_bytes,
    script_vm_to_bin_offset,
)
from .bases import DigimonWorldTestBase
from .test_patcher import _capture_tokens

_LOCAL_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"

# All card-table value-halfword offsets, for absence assertions.
_ALL_CARD_VALUE_OFFSETS = frozenset(
    card_trade_value_bin_offset(i) for i in range(CARD_TRADE_TABLE_ENTRIES)
)


# =============================================================================
# Card-trade manifest geometry
# =============================================================================


class TestCardTradeManifest(unittest.TestCase):
    def test_table_anchor(self) -> None:
        self.assertEqual(CARD_TRADE_VALUE_TABLE_RAM, 0x8012FFDA)
        self.assertEqual(CARD_TRADE_VALUE_TABLE_BIN_OFFSET, 0x14D72222)
        self.assertEqual(card_trade_value_bin_offset(0),
                         CARD_TRADE_VALUE_TABLE_BIN_OFFSET)

    def test_vanilla_distribution(self) -> None:
        """65 entries: zero placeholder + 100 x5, 30 x20, 10 x25, 5 x10,
        1 x4 (the 64 tradeable cards)."""

        self.assertEqual(len(CARD_TRADE_VANILLA_VALUES), 65)
        self.assertEqual(CARD_TRADE_VANILLA_VALUES[0], 0)
        counts = {v: CARD_TRADE_VANILLA_VALUES.count(v) for v in (100, 30, 10, 5, 1)}
        self.assertEqual(counts, {100: 5, 30: 20, 10: 25, 5: 10, 1: 4})

    def test_sector_hop_between_entries_9_and_10(self) -> None:
        """The Mode2/2352 boundary splits the table after entry 9: flat
        delta jumps by 4 + 304 interleave bytes."""

        self.assertEqual(card_trade_value_bin_offset(9),
                         CARD_TRADE_VALUE_TABLE_BIN_OFFSET + 9 * CARD_TRADE_ENTRY_STRIDE)
        self.assertEqual(card_trade_value_bin_offset(10),
                         CARD_TRADE_VALUE_TABLE_BIN_OFFSET + 40 + 304)

    def test_no_value_halfword_straddles_a_sector(self) -> None:
        for i in range(CARD_TRADE_TABLE_ENTRIES):
            off = card_trade_value_bin_offset(i)
            self.assertTrue(24 <= off % 2352 <= 2072 - 2, (i, hex(off)))


# =============================================================================
# Card-trade token emission
# =============================================================================


class TestCardTradeTokensOn(DigimonWorldTestBase):
    """``card_trade_multiplier: 8`` emits one 2-byte value write per
    nonzero table entry, at 8x the vanilla value."""

    options: ClassVar[dict[str, Any]] = {"card_trade_multiplier": 8}

    def test_all_nonzero_entries_scaled(self) -> None:
        observed = _capture_tokens(self.world)
        for i, vanilla in enumerate(CARD_TRADE_VANILLA_VALUES):
            if vanilla == 0:
                continue
            self.assertIn(
                (card_trade_value_bin_offset(i), struct.pack("<h", vanilla * 8)),
                observed, f"entry {i} (vanilla {vanilla}) not scaled",
            )

    def test_zero_rows_untouched(self) -> None:
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for i, vanilla in enumerate(CARD_TRADE_VANILLA_VALUES):
            if vanilla == 0:
                self.assertNotIn(card_trade_value_bin_offset(i), observed_offsets)

    def test_boosted_values_stay_under_cap(self) -> None:
        observed = dict(_capture_tokens(self.world))
        for i, vanilla in enumerate(CARD_TRADE_VANILLA_VALUES):
            if vanilla == 0:
                continue
            data = observed[card_trade_value_bin_offset(i)]
            self.assertEqual(len(data), 2)
            self.assertLessEqual(struct.unpack("<h", data)[0], CARD_TRADE_VALUE_CAP)


class TestCardTradeTokensDefaultOff(DigimonWorldTestBase):
    """Default multiplier 1 = vanilla — zero card-table tokens."""

    options: ClassVar[dict[str, Any]] = {}

    def test_no_card_table_tokens(self) -> None:
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        self.assertFalse(observed_offsets & _ALL_CARD_VALUE_OFFSETS)


class TestCardTradeCapClamp(unittest.TestCase):
    """The writer clamps ``vanilla * multiplier`` at the merit counter's
    9999 cap (defensive — unreachable within the option's 1..20 range,
    where the max product is 100 x 20 = 2000)."""

    def test_writer_clamps_at_cap(self) -> None:
        writes: list[tuple[int, bytes]] = []
        fake_patch = mock.MagicMock()
        fake_patch.write_token = (
            lambda _t, off, data: writes.append((off, bytes(data)))
        )
        rom_module._write_card_trade_multiplier_tokens(fake_patch, 150)
        by_offset = dict(writes)
        # 100 x 150 = 15000 -> clamped to 9999.
        top_card = by_offset[card_trade_value_bin_offset(1)]
        self.assertEqual(struct.unpack("<h", top_card)[0], CARD_TRADE_VALUE_CAP)
        # 30 x 150 = 4500 -> below the cap, unclamped.
        mid_card = by_offset[card_trade_value_bin_offset(6)]
        self.assertEqual(struct.unpack("<h", mid_card)[0], 4500)

    def test_writer_noop_at_multiplier_1(self) -> None:
        fake_patch = mock.MagicMock()
        rom_module._write_card_trade_multiplier_tokens(fake_patch, 1)
        fake_patch.write_token.assert_not_called()


# =============================================================================
# Piximon Training Manual — patcher + location + rule matrix
# =============================================================================


class TestPiximonManualPatcherOn(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"piximon_manual_location": True}

    def test_neuter_token_present(self) -> None:
        observed = _capture_tokens(self.world)
        for offset in ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS:
            self.assertIn((offset, ROM_PIXIMON_MANUAL_NEUTER_VALUE), observed)

    def test_neuter_bytes_are_settrigger_877(self) -> None:
        self.assertEqual(ROM_PIXIMON_MANUAL_NEUTER_VALUE,
                         bytes((0x1C, 0x00, 0x6D, 0x03)))
        self.assertEqual(PIXIMON_MANUAL_TRIGGER_ID, 877)

    def test_location_exists_in_file_city(self) -> None:
        location = self.world.get_location(PIXIMON_MANUAL_LOCATION_NAME)
        self.assertEqual(location.parent_region.name, "File City")

    def test_location_requires_progressive_item_shop_x3(self) -> None:
        """Unreachable without any Progressive Item Shop; reachable with
        all 3 copies (Piximon is a T3-bundled recruit and the offer only
        exists in the tier-3 shop building)."""

        self.assertAccessDependency(
            [PIXIMON_MANUAL_LOCATION_NAME],
            [["Progressive Item Shop"]],
            only_check_listed=True,
        )


class TestPiximonManualPatcherOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_no_neuter_token(self) -> None:
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for offset in ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS:
            self.assertNotIn(offset, observed_offsets)

    def test_location_absent(self) -> None:
        with self.assertRaises(KeyError):
            self.world.get_location(PIXIMON_MANUAL_LOCATION_NAME)


class TestPiximonManualClientWiring(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_poll_table_entry(self) -> None:
        from ..client import LOCATION_RAM_BITS

        self.assertEqual(
            LOCATION_RAM_BITS.get(PIXIMON_MANUAL_LOCATION_NAME),
            PIXIMON_MANUAL_LOCATION_BIT,
        )

    def test_bit_matches_trigger_formula(self) -> None:
        self.assertEqual(
            PIXIMON_MANUAL_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + PIXIMON_MANUAL_TRIGGER_ID // 8,
             PIXIMON_MANUAL_TRIGGER_ID % 8),
        )
        self.assertEqual(PIXIMON_MANUAL_LOCATION_BIT, (0x001BE03A, 5))

    def test_ram_bits_dict_is_single_entry(self) -> None:
        self.assertEqual(
            PIXIMON_MANUAL_LOCATION_RAM_BITS,
            {PIXIMON_MANUAL_LOCATION_NAME: PIXIMON_MANUAL_LOCATION_BIT},
        )


# =============================================================================
# Vanilla-byte anchors (needs the local SLUS-01032 dump; skipped on CI)
# =============================================================================


@unittest.skipUnless(_LOCAL_BIN.is_file(), "SLUS-01032 dump not present")
class TestVanillaAnchorsAgainstSourceBin(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.rom = _LOCAL_BIN.read_bytes()

    def test_card_table_vanilla_values(self) -> None:
        """Every embedded vanilla value matches the source .bin."""

        for i, vanilla in enumerate(CARD_TRADE_VANILLA_VALUES):
            got = struct.unpack_from(
                "<h", self.rom, card_trade_value_bin_offset(i),
            )[0]
            self.assertEqual(got, vanilla, f"entry {i}")

    def test_card_table_terminator(self) -> None:
        """The table ends at entry 64: 2 alignment-pad bytes, then a
        4-byte-aligned kuseg pointer array (first pointer 0x80134554)."""

        tail = read_user_data_bytes(
            self.rom,
            card_trade_value_bin_offset(0),
            CARD_TRADE_TABLE_ENTRIES * CARD_TRADE_ENTRY_STRIDE + 6,
        )
        table_bytes = CARD_TRADE_TABLE_ENTRIES * CARD_TRADE_ENTRY_STRIDE
        self.assertEqual(tail[table_bytes:table_bytes + 2], b"\x00\x00")
        ptr = struct.unpack_from("<I", tail, table_bytes + 2)[0]
        self.assertEqual(ptr, 0x80134554)

    def test_piximon_give_site_vanilla_bytes(self) -> None:
        """``giveItem 33 1`` at the archive-slot-derived offset."""

        offset = ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS[0]
        self.assertEqual(
            self.rom[offset:offset + 4], ROM_PIXIMON_MANUAL_GIVEITEM_VANILLA,
        )

    def test_piximon_give_site_context(self) -> None:
        """The 12 bytes after the give site are the §82 give-failed
        check ``if trigger(0) == false then 4480`` — pins the site to
        the right script flow, not a coincidental byte match."""

        offset = script_vm_to_bin_offset(
            PIXIMON_MANUAL_GIVEITEM_SCRIPT,
            PIXIMON_MANUAL_GIVEITEM_VM_OFFSET + 4,
        )
        expected_if = struct.pack("<HHHHHH", 0x0019, 0, 0, 0x0018, 4480, 0x0019)
        self.assertEqual(self.rom[offset:offset + 12], expected_if)


# =============================================================================
# End-to-end: generate -> .apdw1 -> procedure apply -> byte-verify
# =============================================================================


class TestEndToEndBothFeatures(DigimonWorldTestBase):
    """Full pipeline with both features enabled: ``generate_output``
    writes a real ``.apdw1``; the real procedure (verify_rom_hash ->
    apply_tokens -> recalc_edc) applies it to the canonical dump; the
    output is byte-verified. ROM-gated — auto-skips without the local
    dump."""

    options: ClassVar[dict[str, Any]] = {
        "card_trade_multiplier": 8,
        "piximon_manual_location": True,
    }

    def test_apply_and_byte_verify(self) -> None:
        if not _LOCAL_BIN.is_file():
            self.skipTest("SLUS-01032 dump not present")
        source = _LOCAL_BIN.read_bytes()

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

        # Feature 1: every nonzero card value x8; cardRef halfwords and
        # zero rows byte-identical to the source. The cardRef offset is
        # computed sector-aware — entry 9's value halfword ends exactly
        # at its sector's user-data edge, so ``value_offset + 2`` in
        # flat space would land in that sector's (recomputed) EDC bytes
        # rather than the cardRef.
        from ..data.addresses import _slus_ram_to_bin_offset
        for i, vanilla in enumerate(CARD_TRADE_VANILLA_VALUES):
            off = card_trade_value_bin_offset(i)
            got = struct.unpack_from("<h", patched, off)[0]
            self.assertEqual(got, vanilla * 8, f"entry {i} value")
            ref_off = _slus_ram_to_bin_offset(
                CARD_TRADE_VALUE_TABLE_RAM + i * CARD_TRADE_ENTRY_STRIDE + 2,
            )
            self.assertEqual(patched[ref_off:ref_off + 2],
                             source[ref_off:ref_off + 2],
                             f"entry {i} cardRef clobbered")

        # Feature 2: setTrigger 877 over the give site; neighbors
        # untouched (negative test).
        give = ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS[0]
        self.assertEqual(patched[give:give + 4], ROM_PIXIMON_MANUAL_NEUTER_VALUE)
        self.assertEqual(patched[give - 4:give], source[give - 4:give])
        self.assertEqual(patched[give + 4:give + 16], source[give + 4:give + 16])
