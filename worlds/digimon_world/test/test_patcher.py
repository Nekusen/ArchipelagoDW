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
import unittest
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
        * 4 softlock-fix bands: ROM_FIX_ROTATION (2 bytes total),
          ROM_FIX_MOVE_TO (2*4 = 8 bytes), ROM_FIX_TOY_TOWN
          (2*4 = 8 bytes), ROM_FIX_LEO_CAVE (8*1 byte). The standalone's
          fifth, ROM_OGREMON_SOFTLOCK, is retired (2026-08-29) and must
          NOT be written — nor may any token land inside the quest chain's
          MAPHEAD / script gate pairs.
        * Per-chest item byte writes + chestGiveItem wrapper +
          chest-pickup ``jal`` redirect (Phase 5 piece A).

        Note: closed-shuffle recruit remap was dropped in Phase 5
        piece C; the setTrigger wrapper now decouples fight-completion
        from city-join, replacing the visual-only remap.
        """

        import struct

        from ..data.addresses import (
            OGREMON_CHAIN_GATE_PAIRS,
            ROM_FIX_LEO_CAVE_OFFSETS,
            ROM_FIX_LEO_CAVE_VALUE,
            ROM_FIX_MOVE_TO_OFFSETS,
            ROM_FIX_MOVE_TO_VALUE,
            ROM_FIX_ROTATION_OFFSETS,
            ROM_FIX_ROTATION_VALUE,
            ROM_FIX_TOY_TOWN_OFFSETS,
            ROM_FIX_TOY_TOWN_VALUE,
            ROM_OGREMON_SOFTLOCK_OFFSETS,
            ROM_PP_CALC_PATCH_OFFSET,
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

        # Plan A revised: the setTrigger wrapper is no longer installed.
        # Vanilla setTrigger(200+X) sets bit 200+X directly (cutscene
        # completion); AP delivery writes bit 720+X via the recruit
        # deliverer. Per-Digimon city-script ROM patches gate city
        # visibility on bit 720+X. The wrapper bytes / patch site stay
        # defined in addresses.py for now (in case we revive them).
        observed_offsets = {off for off, _ in observed}
        self.assertNotIn(ROM_SETTRIGGER_WRAPPER_OFFSET, observed_offsets)
        self.assertNotIn(ROM_SETTRIGGER_PATCH_OFFSET, observed_offsets)

        # The standalone randomizer's PP-calc rewrite must NOT be written: it
        # patched the prosperity loop to read a field we never seed (retired
        # 2026-08-28 after the dw_decomp audit).
        self.assertNotIn(ROM_PP_CALC_PATCH_OFFSET, observed_offsets)

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
        # The standalone's "Ogremon softlock" write is retired (it re-targeted
        # TUNN02's model-load gate and hung the bandit cutscene); nothing may
        # write it, and no token may land inside any quest-chain gate pair.
        for off in ROM_OGREMON_SOFTLOCK_OFFSETS:
            self.assertNotIn(off, observed_offsets)
        for group in OGREMON_CHAIN_GATE_PAIRS:
            for _label, gate_off, cond, _ids in group:
                for off, data in observed:
                    self.assertTrue(off + len(data) <= gate_off or off >= gate_off + len(cond),
                                    f"token at {off:#x} overlaps gate {_label}")

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
# QoL option-gated tokens (Phase 5 polish)
# =============================================================================


def _capture_tokens(world: Any) -> set[tuple[int, bytes]]:
    """Run ``generate_output`` against an in-memory patch capture and
    return the resulting (offset, data) set for assertions."""
    import struct  # noqa: F401  (kept for parity with TestGenerateOutput)

    captured: dict[str, bytes] = {}

    def fake_write(self_patch: Any, target: str) -> None:
        with zipfile.ZipFile(target, "w") as _:
            pass
        captured.update(self_patch.files)

    with mock.patch.object(
        rom_module.DigimonWorldProcedurePatch, "write", fake_write,
    ):
        world.generate_output(".")

    blob = captured["token_data.bin"]
    token_count = int.from_bytes(blob[:4], "little")
    tokens: list[tuple[int, int, int, bytes]] = []
    bpr = 4
    for _ in range(token_count):
        ttype = blob[bpr]
        off = int.from_bytes(blob[bpr + 1:bpr + 5], "little")
        size = int.from_bytes(blob[bpr + 5:bpr + 9], "little")
        data = blob[bpr + 9:bpr + 9 + size]
        tokens.append((ttype, off, size, data))
        bpr += 9 + size
    return {(off, data) for _t, off, _s, data in tokens}


class TestQoLPatcherOptionsOn(DigimonWorldTestBase):
    """All QoL toggles ON: skip-intro / type-unlocks bytecode + spawn-rate
    boost should land in the token blob."""

    options: ClassVar[dict[str, Any]] = {
        "skip_intro": 1,
        "type_lock_unlocks": 1,
        "spawn_rate_boost": 50,
        # Cards on so fill has enough progression-eligible locations
        # alongside the 35 EXCLUDED unconfirmed chests.
        "card_locations": True,
    }

    def test_skip_intro_tokens_present(self) -> None:
        import struct

        from ..data.addresses import (
            ROM_SKIP_INTRO_FORMAT,
            ROM_SKIP_INTRO_INSIDE_DEST,
            ROM_SKIP_INTRO_INSIDE_OFFSET,
            ROM_SKIP_INTRO_OPCODE,
            ROM_SKIP_INTRO_OUTSIDE_DEST,
            ROM_SKIP_INTRO_OUTSIDE_OFFSET,
        )
        observed = _capture_tokens(self.world)
        outside = struct.pack(
            ROM_SKIP_INTRO_FORMAT, ROM_SKIP_INTRO_OPCODE, ROM_SKIP_INTRO_OUTSIDE_DEST,
        )
        inside = struct.pack(
            ROM_SKIP_INTRO_FORMAT, ROM_SKIP_INTRO_OPCODE, ROM_SKIP_INTRO_INSIDE_DEST,
        )
        self.assertIn((ROM_SKIP_INTRO_OUTSIDE_OFFSET, outside), observed)
        self.assertIn((ROM_SKIP_INTRO_INSIDE_OFFSET, inside), observed)

    def test_type_lock_unlock_tokens_present(self) -> None:
        import struct

        from ..data.addresses import (
            ROM_UNLOCK_GREYLORD_OFFSETS,
            ROM_UNLOCK_GREYLORD_VALUE,
            ROM_UNLOCK_ICE_OFFSETS,
            ROM_UNLOCK_ICE_VALUE,
            ROM_UNLOCK_TOY_TOWN_FORMAT,
            ROM_UNLOCK_TOY_TOWN_OFFSETS,
            ROM_UNLOCK_TOY_TOWN_VALUE,
            ROM_UNLOCK_TYPE_LOCK_FORMAT,
        )
        observed = _capture_tokens(self.world)
        greylord = struct.pack(ROM_UNLOCK_TYPE_LOCK_FORMAT, ROM_UNLOCK_GREYLORD_VALUE)
        for off in ROM_UNLOCK_GREYLORD_OFFSETS:
            self.assertIn((off, greylord), observed)
        ice = struct.pack(ROM_UNLOCK_TYPE_LOCK_FORMAT, ROM_UNLOCK_ICE_VALUE)
        for off in ROM_UNLOCK_ICE_OFFSETS:
            self.assertIn((off, ice), observed)
        toy_town = struct.pack(ROM_UNLOCK_TOY_TOWN_FORMAT, ROM_UNLOCK_TOY_TOWN_VALUE)
        for off in ROM_UNLOCK_TOY_TOWN_OFFSETS:
            self.assertIn((off, toy_town), observed)

    def test_spawn_rate_boost_tokens_present(self) -> None:
        import struct

        from ..data.addresses import (
            ROM_SPAWN_RATE_FORMAT,
            ROM_SPAWN_RATE_MAMEMON_OFFSETS,
            ROM_SPAWN_RATE_MMAMEMON_OFFSETS,
            ROM_SPAWN_RATE_OTAMAMON_OFFSETS,
            ROM_SPAWN_RATE_PIXIMON_OFFSETS,
        )
        observed = _capture_tokens(self.world)
        # spawn_rate_boost = 50 → large = 49, small = 50 // 33 = 1
        large_bytes = struct.pack(ROM_SPAWN_RATE_FORMAT, 49)
        small_bytes = struct.pack(ROM_SPAWN_RATE_FORMAT, 1)
        for offsets in (
            ROM_SPAWN_RATE_MAMEMON_OFFSETS,
            ROM_SPAWN_RATE_PIXIMON_OFFSETS,
            ROM_SPAWN_RATE_MMAMEMON_OFFSETS,
        ):
            for off in offsets:
                self.assertIn((off, large_bytes), observed)
        for off in ROM_SPAWN_RATE_OTAMAMON_OFFSETS:
            self.assertIn((off, small_bytes), observed)


class TestVendingPatcherOn(DigimonWorldTestBase):
    """VendingLocations on: setTrigger opcode-overwrite tokens land for
    every (machine, ROM copy, item, overwrite-offset) tuple, plus the
    one-line gacha MP Floppy fix."""

    options: ClassVar[dict[str, Any]] = {
        "vending_locations": True,
        "card_locations": True,  # fill capacity for EXCLUDED chests
    }

    def test_vending_settrigger_overwrite_tokens_present(self) -> None:
        from ..data.addresses import VENDING_MACHINES, encode_set_trigger

        observed = _capture_tokens(self.world)
        for machine in VENDING_MACHINES:
            for base in machine.script_bases:
                for item in machine.items:
                    expected_bytes = encode_set_trigger(item.trigger_id)
                    for off in item.overwrite_offsets:
                        self.assertIn(
                            (base + off, expected_bytes), observed,
                            f"missing setTrigger {item.trigger_id} at "
                            f"{base + off:#x} for {item.location_name}",
                        )

    def test_no_text_substitution_tokens_emitted(self) -> None:
        """Vanilla menu / preface / result text is NOT touched. We
        verify by checking the patcher emits no showTextbox-prefixed
        (``1A 00``) tokens for any of the known former text-slot
        offsets."""
        from ..data.addresses import VENDING_MACHINES

        observed = {off: data for off, data in _capture_tokens(self.world)}
        # Probe a couple of offsets that the previous text pass used to
        # rewrite (Greatlake menu @ 190, Greatlake meat result @ 502,
        # Ancient Dino MP Floppy result @ 3670). After the change none
        # of these should carry a token.
        greatlake_base = VENDING_MACHINES[0].script_bases[0]
        ancient_dino_base = VENDING_MACHINES[3].script_bases[0]
        for off in (greatlake_base + 190, greatlake_base + 502,
                    ancient_dino_base + 3670):
            self.assertNotIn(off, observed)

    def test_gacha_mp_floppy_fix_token_present(self) -> None:
        """Vanilla DW1 bug fix: ``jumpTo 3840`` overwrite of the buggy
        conditional at offset 3726 (Ancient Dino script base + 3726).
        Without this, MP Floppy's setTrigger 901 is unreachable except
        when the player's bag is full."""
        from ..data.addresses import (
            ROM_GACHA_MP_FLOPPY_FIX_BYTES,
            ROM_GACHA_MP_FLOPPY_FIX_OFFSET,
        )

        observed = _capture_tokens(self.world)
        self.assertIn(
            (ROM_GACHA_MP_FLOPPY_FIX_OFFSET, ROM_GACHA_MP_FLOPPY_FIX_BYTES),
            observed,
        )
        # Sanity: the fix bytes are exactly 4 (``jumpTo 3840``).
        self.assertEqual(len(ROM_GACHA_MP_FLOPPY_FIX_BYTES), 4)
        self.assertEqual(ROM_GACHA_MP_FLOPPY_FIX_BYTES[:2], b"\x16\x00")


class TestChestRandomizationOffPatcher(DigimonWorldTestBase):
    """ChestRandomization off — none of the chest-specific patcher
    helpers run. The chestGiveItem wrapper, AP_ITEM table entry, and
    per-chest item byte writes are all suppressed."""

    # Pair with cards on so the seed has enough non-chest locations to
    # absorb the mandatory progression items (see
    # :class:`.test_stub_logic.TestChestRandomizationOff` rationale).
    options: ClassVar[dict[str, Any]] = {
        "chest_randomization": False,
        "card_locations": True,
    }

    def test_chest_tokens_absent(self) -> None:
        from ..data.addresses import (
            CHEST_NAME_TO_ROM_OFFSETS,
            ROM_CHEST_GIVEITEM_PATCH_OFFSET,
            ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
        )

        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        # Note: ROM_AP_ITEM_ENTRY_OFFSET is NOT asserted absent — slot 83's
        # ITEM_PARA entry is also written by the always-on merit shop wrapper
        # patcher (slot 83 is the merit shop's AP-purchase row), so it shows
        # up in observed offsets regardless of chest randomization.
        self.assertNotIn(ROM_CHEST_GIVEITEM_PATCH_OFFSET, observed_offsets)
        self.assertNotIn(ROM_CHEST_GIVEITEM_WRAPPER_OFFSET, observed_offsets)
        # And no per-chest item byte writes either.
        for offsets in CHEST_NAME_TO_ROM_OFFSETS.values():
            for offset in offsets:
                self.assertNotIn(offset + 1, observed_offsets)


class TestVendingPatcherOff(DigimonWorldTestBase):
    """VendingLocations off: zero vending-related tokens emitted."""

    options: ClassVar[dict[str, Any]] = {}

    def test_vending_tokens_absent(self) -> None:
        from ..data.addresses import (
            ROM_GACHA_MP_FLOPPY_FIX_OFFSET,
            VENDING_MACHINES,
        )

        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for machine in VENDING_MACHINES:
            for base in machine.script_bases:
                for item in machine.items:
                    for off in item.overwrite_offsets:
                        self.assertNotIn(base + off, observed_offsets)
        # The gacha fix is gated on vending_locations being on.
        self.assertNotIn(ROM_GACHA_MP_FLOPPY_FIX_OFFSET, observed_offsets)


class TestMeritShopWrapperPatcher(DigimonWorldTestBase):
    """Merit Shop give-item wrapper: always-on. Installs a small MIPS
    wrapper into Cave6 free space and hijacks the merit-shop function's
    ``jal 0x800C5240`` so every shop purchase routes through our
    setTrigger dispatch. With the default
    ``MERIT_SHOP_DISPATCH = ((117, 903),)``, item 117 (Amazing Rod)
    fires AP location ``Amazing Rod Pickup`` (trigger 903). Other
    items pass through unchanged."""

    options: ClassVar[dict[str, Any]] = {}

    def test_wrapper_bytes_emitted(self) -> None:
        from ..data.addresses import (
            MERIT_SHOP_DISPATCH,
            ROM_MERIT_SHOP_WRAPPER_BYTES,
            ROM_MERIT_SHOP_WRAPPER_OFFSET,
        )

        observed = _capture_tokens(self.world)
        # Wrapper size = (38 + 7N) instructions × 4 bytes
        # (4 prologue + 6 give_item + 28 mark_bought + 7 per entry).
        self.assertEqual(
            len(ROM_MERIT_SHOP_WRAPPER_BYTES),
            (38 + 7 * len(MERIT_SHOP_DISPATCH)) * 4,
        )
        self.assertIn(
            (ROM_MERIT_SHOP_WRAPPER_OFFSET, ROM_MERIT_SHOP_WRAPPER_BYTES), observed,
            f"missing Merit-Shop wrapper at {ROM_MERIT_SHOP_WRAPPER_OFFSET:#x}",
        )

    def test_sentinel_entry_emitted(self) -> None:
        from ..data.addresses import (
            ROM_AP_SHOP_BOUGHT_ENTRY_BYTES,
            ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(len(ROM_AP_SHOP_BOUGHT_ENTRY_BYTES), 32)
        self.assertTrue(ROM_AP_SHOP_BOUGHT_ENTRY_BYTES.startswith(b"AP Item Bought"))
        self.assertIn(
            (ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET, ROM_AP_SHOP_BOUGHT_ENTRY_BYTES), observed,
            f"missing AP-shop sentinel slot 114 at {ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET:#x}",
        )

    def test_presale_name_rewrites_emitted(self) -> None:
        from ..data.addresses import (
            MERIT_SHOP_DISPATCH,
            ROM_AP_SHOP_PRESALE_NAME_BYTES,
            _merit_shop_presale_name_offset,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(len(ROM_AP_SHOP_PRESALE_NAME_BYTES), 20)
        self.assertTrue(ROM_AP_SHOP_PRESALE_NAME_BYTES.startswith(b"AP Item"))
        for item_id, _trigger_id in MERIT_SHOP_DISPATCH:
            offset = _merit_shop_presale_name_offset(item_id)
            self.assertIn(
                (offset, ROM_AP_SHOP_PRESALE_NAME_BYTES), observed,
                f"missing presale rename for slot {item_id} at {offset:#x}",
            )

    def test_jal_hijack_emitted(self) -> None:
        import struct as _struct

        from ..data.addresses import (
            ROM_MERIT_SHOP_PATCH_FORMAT,
            ROM_MERIT_SHOP_PATCH_OFFSET,
            ROM_MERIT_SHOP_PATCH_VALUE,
        )

        observed = _capture_tokens(self.world)
        expected = _struct.pack(ROM_MERIT_SHOP_PATCH_FORMAT, ROM_MERIT_SHOP_PATCH_VALUE)
        self.assertIn(
            (ROM_MERIT_SHOP_PATCH_OFFSET, expected), observed,
            f"missing Merit-Shop jal hijack at {ROM_MERIT_SHOP_PATCH_OFFSET:#x}",
        )

    def test_wrapper_decode_sanity(self) -> None:
        """Spot-check that the assembled wrapper has the expected
        opcodes at known offsets. Catches future edits that desync the
        builder from the design."""
        import struct as _struct

        from ..data.addresses import (
            MERIT_SHOP_DISPATCH,
            ROM_MERIT_SHOP_WRAPPER_BYTES,
            ROM_MERIT_SHOP_WRAPPER_RAM,
        )

        def word_at(off: int) -> int:
            return _struct.unpack("<I", ROM_MERIT_SHOP_WRAPPER_BYTES[off:off + 4])[0]

        # Prologue: addiu $sp, $sp, -0x10
        self.assertEqual(word_at(0x00), 0x27BDFFF0)
        # First per-entry block at +0x10: addiu $at, $0, item_id
        item_id = MERIT_SHOP_DISPATCH[0][0]
        trigger_id = MERIT_SHOP_DISPATCH[0][1]
        self.assertEqual(word_at(0x10), 0x24010000 | (item_id & 0xFFFF))
        # bne $a0, $at, +5 (skip 5 instructions after the delay slot to
        # land on the next block / give_item path).
        self.assertEqual(word_at(0x14), 0x14810005)
        # jal setTrigger (RAM 0x801065C0)
        self.assertEqual(word_at(0x1C), 0x0C041970)
        # delay slot: addiu $a0, $0, trigger_id
        self.assertEqual(word_at(0x20), 0x24040000 | (trigger_id & 0xFFFF))
        # j mark_bought: target = wrapper_ram + 0x28 + 28*N
        n = len(MERIT_SHOP_DISPATCH)
        mark_ram = ROM_MERIT_SHOP_WRAPPER_RAM + 0x28 + 28 * n
        expected_j_mark = 0x08000000 | ((mark_ram >> 2) & 0x03FFFFFF)
        self.assertEqual(word_at(0x24), expected_j_mark)
        # give_item path's j instruction (5th instruction after the per-entry
        # blocks): j 0x800C5240
        give_item_j_off = 0x10 + 28 * n + 0x10
        self.assertEqual(word_at(give_item_j_off), 0x08031490)
        # mark_bought path's jr $ra: located at the END of the path,
        # one instruction before the trailing nop. 28-instr path; jr is
        # the 27th instruction (0-indexed: 26), so at offset path_start + 26*4.
        mark_jr_off = 0x10 + 28 * n + 0x18 + 26 * 4
        self.assertEqual(word_at(mark_jr_off), 0x03E00008)

    def test_amazing_rod_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``AMAZING_ROD_LOCATION_BIT`` is the canonical RAM bit
        for trigger 903 derived from
        ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``."""
        from ..data.addresses import (
            AMAZING_ROD_LOCATION_BIT,
            AMAZING_ROD_LOCATION_TRIGGER_ID,
            AP_TRIGGER_ARRAY_BASE,
        )

        n = AMAZING_ROD_LOCATION_TRIGGER_ID
        self.assertEqual(
            AMAZING_ROD_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestLeomonstoneNeuterPatcher(DigimonWorldTestBase):
    """Leomonstone giveItem neuter: always-on. All 7 ``giveItem 118 1``
    calls in Script 109 (3 ROM copies of Section_52 + 1 orphan retry)
    get rewritten with ``setTrigger 135``. Trigger 135 is the AP
    location signal for ``Leomonstone Pickup``."""

    options: ClassVar[dict[str, Any]] = {}

    def test_neuter_tokens_present(self) -> None:
        from ..data.addresses import (
            LEOMONSTONE_LOCATION_TRIGGER_ID,
            ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE,
            ROM_LEOMONSTONE_GIVEITEM_OFFSETS,
            VENDING_OPCODE_SETTRIGGER,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(len(ROM_LEOMONSTONE_GIVEITEM_OFFSETS), 7)
        self.assertEqual(len(ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE), 4)
        self.assertEqual(
            ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE,
            bytes((
                VENDING_OPCODE_SETTRIGGER, 0x00,
                LEOMONSTONE_LOCATION_TRIGGER_ID & 0xFF,
                (LEOMONSTONE_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_LEOMONSTONE_GIVEITEM_OFFSETS:
            self.assertIn(
                (offset, ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE), observed,
                f"missing Leomonstone giveItem neuter at {offset:#x}",
            )

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``LEOMONSTONE_LOCATION_BIT`` is the canonical RAM bit
        for trigger 135 derived from
        ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            LEOMONSTONE_LOCATION_BIT,
            LEOMONSTONE_LOCATION_TRIGGER_ID,
        )

        n = LEOMONSTONE_LOCATION_TRIGGER_ID
        self.assertEqual(
            LEOMONSTONE_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestBlueFluteNeuterPatcher(DigimonWorldTestBase):
    """Blue Flute giveItem neuter: always-on. Both ``giveItem 115 1`` calls
    in Script 7 Section_82 (Seadramon friendship cutscene) get rewritten
    with ``setTrigger 210``. Single ROM copy = 2 .bin offsets. Trigger
    210 — same bit Seadramon's recruit used to poll (Seadramon is now in
    ``_AP_RECRUIT_EXCLUDED``) — is the AP location signal for
    ``Blue Flute Pickup``."""

    options: ClassVar[dict[str, Any]] = {}

    def test_neuter_tokens_present(self) -> None:
        from ..data.addresses import (
            BLUE_FLUTE_LOCATION_TRIGGER_ID,
            ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE,
            ROM_BLUE_FLUTE_GIVEITEM_OFFSETS,
            VENDING_OPCODE_SETTRIGGER,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(len(ROM_BLUE_FLUTE_GIVEITEM_OFFSETS), 2)
        self.assertEqual(len(ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE), 4)
        self.assertEqual(
            ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE,
            bytes((
                VENDING_OPCODE_SETTRIGGER, 0x00,
                BLUE_FLUTE_LOCATION_TRIGGER_ID & 0xFF,
                (BLUE_FLUTE_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_BLUE_FLUTE_GIVEITEM_OFFSETS:
            self.assertIn(
                (offset, ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE), observed,
                f"missing Blue Flute giveItem neuter at {offset:#x}",
            )

    def test_location_bit_matches_seadramon_recruit_bit(self) -> None:
        """Sanity: ``BLUE_FLUTE_LOCATION_BIT`` must equal Seadramon's
        recruit bit — they are the same in-game event. Catches drift if
        either side is edited (also asserted at module-load time in
        addresses.py)."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            BLUE_FLUTE_LOCATION_BIT,
            BLUE_FLUTE_LOCATION_TRIGGER_ID,
            RECRUIT_RAM_BITS,
        )

        n = BLUE_FLUTE_LOCATION_TRIGGER_ID
        self.assertEqual(
            BLUE_FLUTE_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )
        self.assertEqual(BLUE_FLUTE_LOCATION_BIT, RECRUIT_RAM_BITS["Seadramon"])


class TestRainPlantNeuterPatcher(DigimonWorldTestBase):
    """Rain Plant giveItem neuter: always-on. The single ``giveItem 121 1``
    in Script 162 Section_83 (Tanemon planter cutscene in Native
    Forest) gets rewritten with ``setTrigger 76``. Single ROM copy =
    1 .bin offset. Trigger 76 is the AP location signal."""

    options: ClassVar[dict[str, Any]] = {}

    def test_neuter_tokens_present(self) -> None:
        from ..data.addresses import (
            RAIN_PLANT_LOCATION_TRIGGER_ID,
            ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE,
            ROM_RAIN_PLANT_GIVEITEM_OFFSETS,
            VENDING_OPCODE_SETTRIGGER,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(len(ROM_RAIN_PLANT_GIVEITEM_OFFSETS), 1)
        self.assertEqual(len(ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE), 4)
        self.assertEqual(
            ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE,
            bytes((
                VENDING_OPCODE_SETTRIGGER, 0x00,
                RAIN_PLANT_LOCATION_TRIGGER_ID & 0xFF,
                (RAIN_PLANT_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_RAIN_PLANT_GIVEITEM_OFFSETS:
            self.assertIn(
                (offset, ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE), observed,
                f"missing Rain Plant giveItem neuter at {offset:#x}",
            )

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``RAIN_PLANT_LOCATION_BIT`` is the canonical RAM bit
        for trigger 76 derived from
        ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            RAIN_PLANT_LOCATION_BIT,
            RAIN_PLANT_LOCATION_TRIGGER_ID,
        )

        n = RAIN_PLANT_LOCATION_TRIGGER_ID
        self.assertEqual(
            RAIN_PLANT_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestGearNeuterPatcher(DigimonWorldTestBase):
    """Gear giveItem neuter: always-on. Both ``giveItem 120 1`` calls in
    Script 144 Section_83 (Toy Town WaruMonzaemon defeat cutscene) get
    rewritten with ``setTrigger 270``. Single ROM copy = 2 .bin offsets.
    Trigger 270 is the AP location signal (set by the cutscene's own
    ``setTrigger 270`` at script offset 4518)."""

    options: ClassVar[dict[str, Any]] = {}

    def test_neuter_tokens_present(self) -> None:
        from ..data.addresses import (
            GEAR_LOCATION_TRIGGER_ID,
            ROM_GEAR_GIVEITEM_NEUTER_VALUE,
            ROM_GEAR_GIVEITEM_OFFSETS,
            VENDING_OPCODE_SETTRIGGER,
        )

        observed = _capture_tokens(self.world)
        # 4-byte rewrite at each of the two sites (single ROM copy).
        self.assertEqual(len(ROM_GEAR_GIVEITEM_OFFSETS), 2)
        self.assertEqual(len(ROM_GEAR_GIVEITEM_NEUTER_VALUE), 4)
        self.assertEqual(
            ROM_GEAR_GIVEITEM_NEUTER_VALUE,
            bytes((
                VENDING_OPCODE_SETTRIGGER, 0x00,
                GEAR_LOCATION_TRIGGER_ID & 0xFF,
                (GEAR_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_GEAR_GIVEITEM_OFFSETS:
            self.assertIn(
                (offset, ROM_GEAR_GIVEITEM_NEUTER_VALUE), observed,
                f"missing Gear giveItem neuter at {offset:#x}",
            )

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``GEAR_LOCATION_BIT`` is the canonical RAM bit for
        trigger 270 derived from
        ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            GEAR_LOCATION_BIT,
            GEAR_LOCATION_TRIGGER_ID,
        )

        n = GEAR_LOCATION_TRIGGER_ID
        self.assertEqual(
            GEAR_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestFrigKeyNeuterPatcher(DigimonWorldTestBase):
    """Frig Key giveItem neuter: always-on. Both ``giveItem 123 1`` calls
    in Script 63 Section_5 (Myotismon Frig-Key dialog) get rewritten
    with ``setTrigger 104`` across 2 ROM copies = 4 .bin offsets.
    Trigger 104 — set by the cutscene's own ``setTrigger 104`` at
    script offset 238 and now also by our substituted instructions —
    is the AP location signal."""

    options: ClassVar[dict[str, Any]] = {}

    def test_neuter_tokens_present(self) -> None:
        from ..data.addresses import (
            FRIG_KEY_LOCATION_TRIGGER_ID,
            ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE,
            ROM_FRIG_KEY_GIVEITEM_OFFSETS,
            VENDING_OPCODE_SETTRIGGER,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(len(ROM_FRIG_KEY_GIVEITEM_OFFSETS), 4)
        self.assertEqual(len(ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE), 4)
        self.assertEqual(
            ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE,
            bytes((
                VENDING_OPCODE_SETTRIGGER, 0x00,
                FRIG_KEY_LOCATION_TRIGGER_ID & 0xFF,
                (FRIG_KEY_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_FRIG_KEY_GIVEITEM_OFFSETS:
            self.assertIn(
                (offset, ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE), observed,
                f"missing Frig Key giveItem neuter at {offset:#x}",
            )

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``FRIG_KEY_LOCATION_BIT`` is the canonical RAM bit
        for trigger 104 derived from
        ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            FRIG_KEY_LOCATION_BIT,
            FRIG_KEY_LOCATION_TRIGGER_ID,
        )

        n = FRIG_KEY_LOCATION_TRIGGER_ID
        self.assertEqual(
            FRIG_KEY_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestMansionKeyNeuterPatcher(DigimonWorldTestBase):
    """Mansion Key giveItem neuter: always-on. Both ``giveItem 119 1``
    calls in Script 54 Section_81 (across 2 ROM copies = 4 .bin
    offsets) get rewritten with ``setTrigger 110`` so the vanilla
    cutscene no longer puts the key in inventory; only AP delivery
    (bank slot 119) does. Trigger 110 — set by both the cutscene's
    own ``setTrigger 110`` and our substituted instructions — is the
    AP location signal. See addresses.py:
    ``ROM_MANSION_KEY_GIVEITEM_*``."""

    options: ClassVar[dict[str, Any]] = {}

    def test_neuter_tokens_present(self) -> None:
        from ..data.addresses import (
            MANSION_KEY_LOCATION_TRIGGER_ID,
            ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE,
            ROM_MANSION_KEY_GIVEITEM_OFFSETS,
            VENDING_OPCODE_SETTRIGGER,
        )

        observed = _capture_tokens(self.world)
        # 4-byte rewrite at each of the four sites (both giveItem paths
        # in two ROM copies of Script 54).
        self.assertEqual(len(ROM_MANSION_KEY_GIVEITEM_OFFSETS), 4)
        self.assertEqual(len(ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE), 4)
        self.assertEqual(
            ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE,
            bytes((
                VENDING_OPCODE_SETTRIGGER, 0x00,
                MANSION_KEY_LOCATION_TRIGGER_ID & 0xFF,
                (MANSION_KEY_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_MANSION_KEY_GIVEITEM_OFFSETS:
            self.assertIn(
                (offset, ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE), observed,
                f"missing Mansion Key giveItem neuter at {offset:#x}",
            )

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``MANSION_KEY_LOCATION_BIT`` is the canonical RAM
        bit for trigger 110 derived from
        ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            MANSION_KEY_LOCATION_BIT,
            MANSION_KEY_LOCATION_TRIGGER_ID,
        )

        n = MANSION_KEY_LOCATION_TRIGGER_ID
        self.assertEqual(
            MANSION_KEY_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestOldFishrodRemapPatcher(DigimonWorldTestBase):
    """Old Fishrod cutscene remap: always-on. The rod-give cutscene's
    references to trigger 45 (in both the section gate and the
    setTrigger) get rewritten to trigger 902 — decoupling vanilla
    cutscene completion (location signal) from rod ownership (fishing
    enable). See addresses.py: ``ROM_OLD_FISHROD_REMAP_*``."""

    options: ClassVar[dict[str, Any]] = {}

    def test_remap_tokens_present(self) -> None:
        from ..data.addresses import (
            OLD_FISHROD_LOCATION_TRIGGER_ID,
            ROM_OLD_FISHROD_REMAP_OFFSETS,
            ROM_OLD_FISHROD_REMAP_VALUE,
        )

        observed = _capture_tokens(self.world)
        # 2-byte trigger-ID rewrite at each of the two remap sites.
        self.assertEqual(len(ROM_OLD_FISHROD_REMAP_VALUE), 2)
        self.assertEqual(
            ROM_OLD_FISHROD_REMAP_VALUE,
            bytes((
                OLD_FISHROD_LOCATION_TRIGGER_ID & 0xFF,
                (OLD_FISHROD_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_OLD_FISHROD_REMAP_OFFSETS:
            self.assertIn(
                (offset, ROM_OLD_FISHROD_REMAP_VALUE), observed,
                f"missing rod-cutscene remap write at {offset:#x}",
            )

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``OLD_FISHROD_LOCATION_BIT`` is the canonical RAM bit
        for trigger 902 derived from ``mem[0x001BDFCD + N/8] |= 1 << (N % 8)``.
        Catches drift between the location pollers and the patched
        cutscene if anyone touches one without the other."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            OLD_FISHROD_LOCATION_BIT,
            OLD_FISHROD_LOCATION_TRIGGER_ID,
        )

        n = OLD_FISHROD_LOCATION_TRIGGER_ID
        self.assertEqual(
            OLD_FISHROD_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )


class TestCoelamonRecruitRemapPatcher(DigimonWorldTestBase):
    """Coelamon shore-cutscene remap: always-on (restored 2026-08-22).

    Script 6's five trigger-249 references (four guard reads + the
    ``setTrigger`` operand, plus three dead residue twins) are rewritten
    to trigger 779 so the shore state machine runs on its own persistent
    "cutscene done" bit. **Loop regression coverage**: the original
    2026-05-24 bug was the recruit cutscene re-firing forever because
    its guard bit stayed unmarked; the remap makes the guard read the
    same bit the cutscene sets, and the client pin of vanilla bit 249
    can neither block nor re-fire the cutscene (live-verified — see
    ``work/dw1_re/decomp/_coelamon_recruit/NOTES.md``). See
    addresses.py: ``ROM_COELAMON_CUTSCENE_REMAP_*``."""

    options: ClassVar[dict[str, Any]] = {}  # bridge_unlock default = always_open

    def test_remap_tokens_present(self) -> None:
        from ..data.addresses import (
            COELAMON_RECRUIT_LOCATION_TRIGGER_ID,
            ROM_COELAMON_CUTSCENE_REMAP_OFFSETS,
            ROM_COELAMON_CUTSCENE_REMAP_VALUE,
        )

        observed = _capture_tokens(self.world)
        # 2-byte trigger-ID rewrite at each of the 5 live + 3 residue sites.
        self.assertEqual(len(ROM_COELAMON_CUTSCENE_REMAP_OFFSETS), 8)
        self.assertEqual(
            ROM_COELAMON_CUTSCENE_REMAP_VALUE,
            bytes((
                COELAMON_RECRUIT_LOCATION_TRIGGER_ID & 0xFF,
                (COELAMON_RECRUIT_LOCATION_TRIGGER_ID >> 8) & 0xFF,
            )),
        )
        for offset in ROM_COELAMON_CUTSCENE_REMAP_OFFSETS:
            self.assertIn(
                (offset, ROM_COELAMON_CUTSCENE_REMAP_VALUE), observed,
                f"missing Coelamon cutscene remap write at {offset:#x}",
            )

    def test_gate_tokens_absent_in_always_open(self) -> None:
        # bridge_unlock = always_open: the take-across gate keeps its
        # vanilla 1506 branch target (185 is pinned from the start).
        from ..data.addresses import ROM_COELAMON_GATE_OFFSETS

        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for offset in ROM_COELAMON_GATE_OFFSETS:
            self.assertNotIn(offset, observed_offsets)

    def test_location_bit_matches_trigger_formula(self) -> None:
        """Sanity: ``COELAMON_RECRUIT_LOCATION_BIT`` is the canonical
        RAM bit for trigger 779 per ``mem[0x001BDFCD + N/8] |= 1 << (N%8)``,
        and it is NOT Coelamon's vanilla recruit bit (which the client
        pins every tick — polling that would self-fire the location)."""
        from ..data.addresses import (
            AP_TRIGGER_ARRAY_BASE,
            COELAMON_RECRUIT_LOCATION_BIT,
            COELAMON_RECRUIT_LOCATION_TRIGGER_ID,
            RECRUIT_RAM_BITS,
        )

        n = COELAMON_RECRUIT_LOCATION_TRIGGER_ID
        self.assertEqual(
            COELAMON_RECRUIT_LOCATION_BIT,
            (AP_TRIGGER_ARRAY_BASE + n // 8, n % 8),
        )
        self.assertNotEqual(
            COELAMON_RECRUIT_LOCATION_BIT, RECRUIT_RAM_BITS["Coelamon"],
        )


class TestCoelamonGateShuffledPatcher(DigimonWorldTestBase):
    """bridge_unlock = shuffled: the take-across gate patch must land at
    the CORRECTED branch-target offsets (vm 598 / residue twin 3690).

    Regression trap for the +4 offset bug shipped before 2026-08-22:
    the old offsets (0x13FE0572 / 0x13FE12B6) are the ``4F 14`` head of
    the recruit cutscene's ``moveCameraTo`` — writing there corrupted
    the cutscene and left the ferry bypass open. No token may ever
    write those offsets again."""

    options: ClassVar[dict[str, Any]] = {"bridge_unlock": 2}

    # The pre-2026-08-22 (wrong) shipment offsets.
    _LEGACY_WRONG_OFFSETS = (0x13FE0572, 0x13FE12B6)

    def test_gate_tokens_at_corrected_offsets(self) -> None:
        from ..data.addresses import (
            ROM_COELAMON_CUTSCENE_REMAP_OFFSETS,
            ROM_COELAMON_GATE_OFFSETS,
            ROM_COELAMON_GATE_VALUE,
        )

        observed = _capture_tokens(self.world)
        self.assertEqual(ROM_COELAMON_GATE_OFFSETS, (0x13FE056E, 0x13FE12B2))
        self.assertEqual(ROM_COELAMON_GATE_VALUE, bytes((0xFC, 0x05)))  # 1532 LE
        for offset in ROM_COELAMON_GATE_OFFSETS:
            self.assertIn(
                (offset, ROM_COELAMON_GATE_VALUE), observed,
                f"missing corrected take-across gate write at {offset:#x}",
            )
        # The two Coelamon families write disjoint bytes of Script 6.
        self.assertFalse(
            set(ROM_COELAMON_GATE_OFFSETS)
            & set(ROM_COELAMON_CUTSCENE_REMAP_OFFSETS),
        )

    def test_legacy_wrong_offsets_never_written(self) -> None:
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for offset in self._LEGACY_WRONG_OFFSETS:
            self.assertNotIn(
                offset, observed_offsets,
                f"legacy +4-bug offset {offset:#x} written — this "
                f"corrupts the recruit cutscene's moveCameraTo head",
            )


class TestQoLPatcherOptionsOff(DigimonWorldTestBase):
    """Skip-intro and type-unlocks OFF: their tokens should NOT appear.
    Spawn-rate-boost is a Range and always writes (the option just
    controls the value); set to 1 to assert vanilla rate (large=0)."""

    options: ClassVar[dict[str, Any]] = {
        "skip_intro": 0,
        "type_lock_unlocks": 0,
        "spawn_rate_boost": 1,
        "card_locations": True,  # fill capacity for EXCLUDED chests
    }

    def test_skip_intro_tokens_absent(self) -> None:
        from ..data.addresses import (
            ROM_SKIP_INTRO_INSIDE_OFFSET,
            ROM_SKIP_INTRO_OUTSIDE_OFFSET,
        )
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        self.assertNotIn(ROM_SKIP_INTRO_OUTSIDE_OFFSET, observed_offsets)
        self.assertNotIn(ROM_SKIP_INTRO_INSIDE_OFFSET, observed_offsets)

    def test_type_lock_unlock_tokens_absent(self) -> None:
        from ..data.addresses import (
            ROM_UNLOCK_GREYLORD_OFFSETS,
            ROM_UNLOCK_ICE_OFFSETS,
            ROM_UNLOCK_TOY_TOWN_OFFSETS,
        )
        observed_offsets = {off for off, _ in _capture_tokens(self.world)}
        for off in (
            *ROM_UNLOCK_GREYLORD_OFFSETS,
            *ROM_UNLOCK_ICE_OFFSETS,
            *ROM_UNLOCK_TOY_TOWN_OFFSETS,
        ):
            self.assertNotIn(off, observed_offsets)

    def test_spawn_rate_minimum_writes_vanilla_value(self) -> None:
        import struct

        from ..data.addresses import (
            ROM_SPAWN_RATE_FORMAT,
            ROM_SPAWN_RATE_MAMEMON_OFFSETS,
            ROM_SPAWN_RATE_OTAMAMON_OFFSETS,
        )
        observed = _capture_tokens(self.world)
        # spawn_rate_boost = 1 → large = 0, small = 0
        zero_byte = struct.pack(ROM_SPAWN_RATE_FORMAT, 0)
        for off in ROM_SPAWN_RATE_MAMEMON_OFFSETS:
            self.assertIn((off, zero_byte), observed)
        for off in ROM_SPAWN_RATE_OTAMAMON_OFFSETS:
            self.assertIn((off, zero_byte), observed)


@unittest.skip("changeMap wrapper temporarily disabled for live bisect")
class TestChangeMapWrapper(DigimonWorldTestBase):
    """Phase 5 polish: race-free changeMap hook for city/field bit sync."""

    options: ClassVar[dict[str, Any]] = {}

    def test_changemap_wrapper_tokens_present(self) -> None:
        import struct

        from ..data.addresses import (
            ROM_CHANGEMAP_PATCH_FORMAT,
            ROM_CHANGEMAP_PATCH_OFFSET,
            ROM_CHANGEMAP_PATCH_VALUE,
            ROM_CHANGEMAP_WRAPPER_BYTES,
            ROM_CHANGEMAP_WRAPPER_OFFSET,
            ROM_CITY_BITMAP_BYTES,
            ROM_CITY_BITMAP_OFFSET,
        )
        observed = _capture_tokens(self.world)
        # 80-byte wrapper at Cave6 offset.
        self.assertIn(
            (ROM_CHANGEMAP_WRAPPER_OFFSET, ROM_CHANGEMAP_WRAPPER_BYTES),
            observed,
        )
        # 32-byte city bitmap immediately after.
        self.assertIn(
            (ROM_CITY_BITMAP_OFFSET, ROM_CITY_BITMAP_BYTES),
            observed,
        )
        # 4-byte JAL redirect at vanilla call site.
        expected_jal = struct.pack(
            ROM_CHANGEMAP_PATCH_FORMAT, ROM_CHANGEMAP_PATCH_VALUE,
        )
        self.assertIn((ROM_CHANGEMAP_PATCH_OFFSET, expected_jal), observed)


class TestQoLSlotData(DigimonWorldTestBase):
    """Client-side QoL flags must round-trip via fill_slot_data so the
    BizHawk client can act on them at runtime."""

    options: ClassVar[dict[str, Any]] = {
        "fast_drimogemon": 1,
        "easy_monochromon": 0,
        "infinite_auto_pilot": 1,
        "card_locations": True,  # fill capacity for EXCLUDED chests
    }

    def test_qol_flags_in_slot_data(self) -> None:
        slot_data = self.world.fill_slot_data()
        self.assertEqual(slot_data["fast_drimogemon"], 1)
        self.assertEqual(slot_data["easy_monochromon"], 0)
        self.assertEqual(slot_data["infinite_auto_pilot"], 1)


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
