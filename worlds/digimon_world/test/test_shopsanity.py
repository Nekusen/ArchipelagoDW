"""Shopsanity tests (item shop + secret shop + per-shop 3-mode config).

Covers the production port of the lab-validated 2026-08-21 shopsanity
design (``work/dw1_re/decomp/_scan_shopsanity/NOTES.md``, spec builder
``work/dw1_re/patches/shopsanity_spec.py``, three nets):

* Byte-for-byte reproduction of the validated builder wrapper, extended
  giveItem wrapper, extended boot hook, jal redirects, and config bytes.
  The expectation literals below are frozen copies of the lab
  ``shopsanity_iso.json`` output — do not regenerate them from the
  production builders (that would make the test a tautology).
* Trigger-id allocation invariants (784..799 / 856..876 only, the
  >=800-is-pstat rule, no collision with any shipped allocation).
* Extended-hook structure + a delay-slot-faithful interpreter replay
  (both seed blocks copied, staging re-zeroed).
* Patcher token emission across the option matrix, including the
  merit-on/recycle-off regression (ext slots 128..134 stay zeroed — the
  old garbage-rows bug must stay dead) and the retired-v1-wrapper
  negatives.
* New locations / rules / pool wiring and the legacy option aliases.
* Vanilla-byte anchors read from a local SLUS-01032 dump (skipped when
  the dump isn't present, e.g. on CI).
"""

from __future__ import annotations

import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar
from unittest import mock

from Options import OptionError
from worlds.Files import APTokenTypes

from .. import rom as rom_module
from ..data.addresses import (
    AP_TRIGGER_ARRAY_BASE,
    ARENA_CUP_LOCATION_RAM_BITS,
    BOSS_LOCATION_RAM_BITS,
    DWAP_CHEST_RAM_BITS,
    EXT_ITEM_PARA_SEED_BIN_OFFSET,
    EXT_ITEM_PARA_SEED_RAM,
    EXT_ITEM_PARA_SEED_SIZE,
    ITEM_PARA_BOOT_HOOK_BYTES,
    ITEM_PARA_BOOT_HOOK_EXT_BYTES,
    ITEM_PARA_BOOT_HOOK_OFFSET,
    ITEM_PARA_BOOT_HOOK_RAM,
    ITEM_PARA_RELOC_BASE_KUSEG,
    ITEM_PARA_RELOC_END_KUSEG,
    ITEM_SHOP_AP_ITEM_ID_COUNT,
    ITEM_SHOP_AP_ITEM_IDS,
    ITEM_SHOP_LOCATION_NAMES,
    ITEM_SHOP_LOCATION_RAM_BITS,
    ITEM_SHOP_TIER_COUNTS,
    ITEM_SHOP_TRIGGER_IDS,
    KEYITEM_LOCATION_RAM_BITS,
    MERIT_SHOP_LOCATION_RAM_BITS,
    MERIT_SHOP_VANILLA_ENTRIES,
    NANIMON_QUEST_LOCATION_RAM_BITS,
    RAM_ITEM_PARA_KUSEG,
    RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE,
    RECYCLE_SHOP_AP_ITEM_IDS,
    RECYCLE_SHOP_LOCATION_RAM_BITS,
    RECYCLE_SHOP_VANILLA_PRICES,
    REGION_ACCESS_TRIGGER_IDS,
    SECRET_SHOP_AP_ITEM_IDS,
    SECRET_SHOP_LOCATION_NAMES,
    SECRET_SHOP_LOCATION_RAM_BITS,
    SECRET_SHOP_TRIGGER_IDS,
    SHOP_AP_BUILDER_WRAPPER_BYTES,
    SHOP_AP_BUILDER_WRAPPER_OFFSET,
    SHOP_AP_BUILDER_WRAPPER_RAM,
    SHOP_AP_CONFIG_BIN_OFFSET,
    SHOP_AP_CONFIG_RAM,
    SHOP_AP_DISPATCHER_JAL_OFFSET,
    SHOP_AP_DISPATCHER_JAL_VALUE,
    SHOP_AP_DISPATCHER_JAL_VANILLA,
    SHOP_AP_GIVEITEM_EXT_BYTES,
    SHOP_AP_GIVEITEM_EXT_OFFSET,
    SHOP_AP_GIVEITEM_EXT_RAM,
    SHOP_AP_GIVEITEM_JAL_OFFSET,
    SHOP_AP_GIVEITEM_JAL_VALUE,
    SHOP_AP_GIVEITEM_JAL_VANILLA,
    SHOP_AP_MONEY_ARRAY_CAP,
    SHOP_AP_STAGING2_BIN_OFFSET,
    SHOP_AP_STAGING2_RAM,
    SHOP_AP_STAGING2_SIZE,
    SHOP_AP_TRIGGER_IDS,
    SHOP_AP_WORST_VANILLA_ROWS,
    VENDING_LOCATION_RAM_BITS,
    build_shop_ap_config_bytes,
    ext_item_para_slot_bin_offset,
    item_shop_tiered_price,
    secret_shop_tiered_price,
)
from ..options import (
    ItemShopLocations,
    MeritShopLocations,
    RecycleShopLocations,
    SecretShopLocations,
    validate_shop_price_options,
)
from .bases import DigimonWorldTestBase
from .test_item_para_relocation import simulate_hook

# =============================================================================
# Frozen lab expectations (shopsanity_iso.json, ALL THREE NETS GREEN)
# =============================================================================

_LAB_BUILDER_WRAPPER_HEX = (
    "7c928f9309800e3cf067ce251c800c3ccddf8d91830001240800ad310a00a015"
    "000000000a00e1114bffe1250800212c15002014d80001241300e111d9000124"
    "0700e111000000000dea0308000000000000cd9180000a241a00001007000b24"
    "0200cd9149e08991000000000400212df5ff20104050090021504901ae004a25"
    "1000001003000b240100cd9127e089912ae0889110002931ebff201180000831"
    "2ce0899105000b2405000011200029310f000b24020020110000000019000b24"
    "95000a24e0ffa011010001240700a111000000003c94888f000002240000098d"
    "08000ba11300001000000000e0ffbd271c00bfaf1400aaaf0dea030c1800abaf"
    "1400aa8f1800ab8f1c00bf8f2000bd273c94888f000000000000098d08000c91"
    "0000000040080c002148210121608b0108000ca140090a001c800e3c84fbce25"
    "2170c1018c938f8f00002aa10000cc8d020029252a08ec0101002c3825104c00"
    "ffff2ca101004a252000ce25ffff6b25f5ff6015000000000800e00300000000"
)

_LAB_GIVEITEM_EXT_HEX = (
    "80ff81240700282c090000156bff81241000282c080000155bff81241500282c"
    "070000150000000090140308000000000500001008038424030000107b028424"
    "01000010b3028424f0ffbd270c00bfaf7019040c000000000c00bf8f1000bd27"
    "0800e00301000224"
)

_LAB_HOOK_EXT_HEX = (
    "e8ffbd271400bfaff7ba030c000000001280083cdc6908251c80093c70fb2925"
    "00100a2400000b8d0400082500002badfcff4a25fbff4015040029251c80093c"
    "700b292500100a24000020adfcff4a25fdff4015040029250980083c00680825"
    "1c80093c700b2925c0030a2400000b8d0400082500002badfcff4a25fbff4015"
    "040029251180083c4c5a08251c80093c300f292580030a2400000b8d04000825"
    "00002badfcff4a25fbff4015040029251180083c4c5a082580030a24000000ad"
    "fcff4a25fdff4015040008251400bf8f1800bd270800e00300000000"
)

_LAB_DISPATCHER_JAL = 0x0C049E77
_LAB_GIVEITEM_JAL = 0x0C049ED7
# Representative full config (lab rep_cfg): recycle=replace,
# item=coexist, secret=replace.
_LAB_CONFIG_FULL_HEX = "02010200"


# =============================================================================
# Byte fidelity against the lab spec
# =============================================================================


class TestShopsanityByteFidelity(unittest.TestCase):
    def test_builder_wrapper_matches_lab_spec(self) -> None:
        self.assertEqual(SHOP_AP_BUILDER_WRAPPER_BYTES.hex(), _LAB_BUILDER_WRAPPER_HEX)
        self.assertEqual(len(SHOP_AP_BUILDER_WRAPPER_BYTES), 96 * 4)

    def test_giveitem_ext_matches_lab_spec(self) -> None:
        self.assertEqual(SHOP_AP_GIVEITEM_EXT_BYTES.hex(), _LAB_GIVEITEM_EXT_HEX)
        self.assertEqual(len(SHOP_AP_GIVEITEM_EXT_BYTES), 26 * 4)

    def test_hook_ext_matches_lab_spec(self) -> None:
        self.assertEqual(ITEM_PARA_BOOT_HOOK_EXT_BYTES.hex(), _LAB_HOOK_EXT_HEX)
        self.assertEqual(len(ITEM_PARA_BOOT_HOOK_EXT_BYTES), 55 * 4)

    def test_jal_redirect_values(self) -> None:
        self.assertEqual(SHOP_AP_DISPATCHER_JAL_VALUE, _LAB_DISPATCHER_JAL)
        self.assertEqual(SHOP_AP_GIVEITEM_JAL_VALUE, _LAB_GIVEITEM_JAL)
        self.assertEqual(SHOP_AP_DISPATCHER_JAL_VANILLA, 0x0C03EA0D)
        self.assertEqual(SHOP_AP_GIVEITEM_JAL_VANILLA, 0x0C031490)

    def test_config_bytes_for_representative_config(self) -> None:
        self.assertEqual(build_shop_ap_config_bytes(2, 1, 2).hex(), _LAB_CONFIG_FULL_HEX)
        self.assertEqual(build_shop_ap_config_bytes(0, 0, 0), b"\x00\x00\x00\x00")

    def test_layout_addresses(self) -> None:
        self.assertEqual(SHOP_AP_BUILDER_WRAPPER_RAM, 0x801279DC)
        self.assertEqual(SHOP_AP_GIVEITEM_EXT_RAM, 0x80127B5C)
        self.assertEqual(SHOP_AP_CONFIG_RAM, 0x800967F0)
        self.assertEqual(SHOP_AP_STAGING2_RAM, 0x80115A4C)
        self.assertEqual(SHOP_AP_STAGING2_BIN_OFFSET, 0x14D53ED4)
        self.assertEqual(SHOP_AP_STAGING2_SIZE, 896)


# =============================================================================
# Trigger allocation
# =============================================================================


class TestShopsanityTriggerAllocation(unittest.TestCase):
    def test_exact_id_sets(self) -> None:
        self.assertEqual(
            ITEM_SHOP_TRIGGER_IDS, tuple(range(784, 800)) + tuple(range(856, 865)),
        )
        self.assertEqual(SECRET_SHOP_TRIGGER_IDS, tuple(range(865, 877)))
        self.assertEqual(len(SHOP_AP_TRIGGER_IDS), 37)
        self.assertEqual(len(set(SHOP_AP_TRIGGER_IDS)), 37)

    def test_only_audited_free_bands_nothing_at_936(self) -> None:
        for trig in SHOP_AP_TRIGGER_IDS:
            self.assertTrue(784 <= trig <= 799 or 856 <= trig <= 877, trig)
            self.assertLess(trig, 936)
            self.assertLess(
                AP_TRIGGER_ARRAY_BASE + trig // 8,
                RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE,
            )

    def test_pstat_overlap_rule(self) -> None:
        """Triggers >= 800 overlap the pstat byte array; pstat(0..6) are
        engine-used so 800..855 is forbidden forever."""

        for trig in SHOP_AP_TRIGGER_IDS:
            self.assertFalse(800 <= trig <= 855, trig)

    def test_no_collision_with_any_shipped_ram_bit(self) -> None:
        """Every (byte, bit) pair the client or ROM already owns."""

        taken: dict[tuple[int, int], str] = {}
        for family, table in (
            ("chest", DWAP_CHEST_RAM_BITS),
            ("keyitem", KEYITEM_LOCATION_RAM_BITS),
            ("vending", VENDING_LOCATION_RAM_BITS),
            ("recycle", RECYCLE_SHOP_LOCATION_RAM_BITS),
            ("merit", MERIT_SHOP_LOCATION_RAM_BITS),
            ("nanimon", NANIMON_QUEST_LOCATION_RAM_BITS),
            ("arena", ARENA_CUP_LOCATION_RAM_BITS),
            ("boss", BOSS_LOCATION_RAM_BITS),
        ):
            for name, bit in table.items():
                taken[bit] = f"{family}:{name}"
        from ..data.addresses import (
            BIRDRA_FLIGHT_GCANYON_TRIGGER_ID,
            BIRDRAMON_FLIGHT_RAM_BITS,
        )
        for name, bit in BIRDRAMON_FLIGHT_RAM_BITS.items():
            taken[bit] = f"flight:{name}"
        for trig in (*REGION_ACCESS_TRIGGER_IDS.values(), BIRDRA_FLIGHT_GCANYON_TRIGGER_ID):
            taken[(AP_TRIGGER_ARRAY_BASE + trig // 8, trig % 8)] = f"region-gate:{trig}"

        for name, bit in (*ITEM_SHOP_LOCATION_RAM_BITS.items(),
                          *SECRET_SHOP_LOCATION_RAM_BITS.items()):
            self.assertNotIn(bit, taken, f"{name} collides with {taken.get(bit)}")

    def test_ram_bits_follow_settrigger_formula(self) -> None:
        for i, name in enumerate(ITEM_SHOP_LOCATION_NAMES):
            trig = ITEM_SHOP_TRIGGER_IDS[i]
            self.assertEqual(
                ITEM_SHOP_LOCATION_RAM_BITS[name],
                (AP_TRIGGER_ARRAY_BASE + trig // 8, trig % 8),
            )
        for i, name in enumerate(SECRET_SHOP_LOCATION_NAMES):
            trig = SECRET_SHOP_TRIGGER_IDS[i]
            self.assertEqual(
                SECRET_SHOP_LOCATION_RAM_BITS[name],
                (AP_TRIGGER_ARRAY_BASE + trig // 8, trig % 8),
            )

    def test_money_array_cap(self) -> None:
        self.assertEqual(SHOP_AP_MONEY_ARRAY_CAP, 68)
        self.assertEqual(
            SHOP_AP_WORST_VANILLA_ROWS + ITEM_SHOP_AP_ITEM_ID_COUNT, 41,
        )
        self.assertLessEqual(
            SHOP_AP_WORST_VANILLA_ROWS + ITEM_SHOP_AP_ITEM_ID_COUNT,
            SHOP_AP_MONEY_ARRAY_CAP,
        )


# =============================================================================
# Extended boot hook: structure + interpreter replay
# =============================================================================


class TestExtendedBootHook(unittest.TestCase):
    def test_grown_in_place(self) -> None:
        # Prefix (loops 1..3) and epilogue byte-identical to the base
        # 37-word hook; loops 4+5 spliced in between.
        self.assertEqual(
            ITEM_PARA_BOOT_HOOK_EXT_BYTES[:33 * 4], ITEM_PARA_BOOT_HOOK_BYTES[:33 * 4],
        )
        self.assertEqual(
            ITEM_PARA_BOOT_HOOK_EXT_BYTES[51 * 4:], ITEM_PARA_BOOT_HOOK_BYTES[33 * 4:],
        )

    def test_interpreter_replay(self) -> None:
        """Port of the lab Net-1 replay: table = vanilla + seed(30) +
        staging2(28) + zeros; staging re-zeroed; displaced callee first."""

        ram = bytearray(0x200000)
        vanilla = bytes((7 * i + 3) & 0xFF for i in range(4096))
        seed = bytes((11 * i + 5) & 0xFF for i in range(EXT_ITEM_PARA_SEED_SIZE))
        staging = bytes((13 * i + 9) & 0xFF for i in range(SHOP_AP_STAGING2_SIZE))
        vp = RAM_ITEM_PARA_KUSEG & 0x1FFFFF
        sp = EXT_ITEM_PARA_SEED_RAM & 0x1FFFFF
        s2 = SHOP_AP_STAGING2_RAM & 0x1FFFFF
        base = ITEM_PARA_RELOC_BASE_KUSEG & 0x1FFFFF
        end = ITEM_PARA_RELOC_END_KUSEG & 0x1FFFFF
        ram[vp:vp + 4096] = vanilla
        ram[sp:sp + len(seed)] = seed
        ram[s2:s2 + len(staging)] = staging
        # Poison the destination and the arena header just past it.
        ram[base:end + 16] = b"\xEE" * (0x2000 + 16)

        words = list(struct.unpack("<55I", ITEM_PARA_BOOT_HOOK_EXT_BYTES))
        writes, calls = simulate_hook(
            words, ITEM_PARA_BOOT_HOOK_RAM, ram, 0x800EEBDC,
        )

        self.assertEqual(calls, [0x800EEBDC])
        expected = vanilla + seed + staging
        expected += b"\x00" * (0x2000 - len(expected))
        self.assertEqual(bytes(ram[base:end]), expected)
        # Loop 5 restored the staging region's boot invariant.
        self.assertEqual(bytes(ram[s2:s2 + SHOP_AP_STAGING2_SIZE]),
                         b"\x00" * SHOP_AP_STAGING2_SIZE)
        # Write containment: table, stack frame, or the staging re-zero.
        stack_lo = (0x001FFC00 + 0x80000000 - 0x18) & 0x1FFFFF
        for addr, _size in writes:
            in_table = base <= addr < end
            in_stack = stack_lo <= addr < stack_lo + 0x18
            in_staging = s2 <= addr < s2 + SHOP_AP_STAGING2_SIZE
            self.assertTrue(in_table or in_stack or in_staging,
                            f"stray hook write at phys 0x{addr:06X}")
        # The arena header poison must survive.
        self.assertEqual(bytes(ram[end:end + 16]), b"\xEE" * 16)


# =============================================================================
# Patcher token emission (option matrix)
# =============================================================================


def _capture_tokens_ordered(world: Any) -> tuple[list[tuple[int, bytes]], list[Any]]:
    """Run generate_output with a stubbed patch writer; return the
    ordered ``[(offset, data)]`` WRITE-token list and the procedure."""

    captured: dict[str, bytes] = {}
    procedure_holder: list[Any] = []

    def fake_write(self_patch: Any, target: str) -> None:
        with zipfile.ZipFile(target, "w"):
            pass
        captured.update(self_patch.files)
        procedure_holder.append(list(self_patch.procedure))

    with mock.patch.object(
        rom_module.DigimonWorldProcedurePatch, "write", fake_write,
    ), tempfile.TemporaryDirectory() as tmp_dir:
        world.generate_output(tmp_dir)

    blob = captured["token_data.bin"]
    count = int.from_bytes(blob[:4], "little")
    tokens: list[tuple[int, bytes]] = []
    pos = 4
    for _ in range(count):
        token_type = blob[pos]
        offset = int.from_bytes(blob[pos + 1:pos + 5], "little")
        size = int.from_bytes(blob[pos + 5:pos + 9], "little")
        assert token_type == APTokenTypes.WRITE
        tokens.append((offset, blob[pos + 9:pos + 9 + size]))
        pos += 9 + size
    return tokens, procedure_holder[0]


_SHOPSANITY_INFRA_OFFSETS = (
    SHOP_AP_BUILDER_WRAPPER_OFFSET,
    SHOP_AP_GIVEITEM_EXT_OFFSET,
    SHOP_AP_DISPATCHER_JAL_OFFSET,
    SHOP_AP_GIVEITEM_JAL_OFFSET,
    SHOP_AP_CONFIG_BIN_OFFSET,
)


class TestShopsanityTokensAllOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}  # all four shops default off

    def test_no_shopsanity_tokens(self) -> None:
        tokens, procedure = _capture_tokens_ordered(self.world)
        offsets = {off for off, _data in tokens}
        for off in _SHOPSANITY_INFRA_OFFSETS:
            self.assertNotIn(off, offsets)
        # The boot hook stays the base 37-word version.
        hook_writes = [data for off, data in tokens if off == ITEM_PARA_BOOT_HOOK_OFFSET]
        self.assertEqual(hook_writes, [ITEM_PARA_BOOT_HOOK_BYTES])
        # No ext entries anywhere, no staging2 writes.
        for off, _data in tokens:
            self.assertFalse(
                SHOP_AP_STAGING2_BIN_OFFSET <= off < SHOP_AP_STAGING2_BIN_OFFSET + 896,
                f"unexpected staging2 write at 0x{off:X}",
            )
        names = [step[0] for step in procedure]
        self.assertNotIn("relocate_item_desc_ptr", names)


class TestShopsanityTokensFullConfig(DigimonWorldTestBase):
    """The lab's representative config: recycle=replace, item=coexist,
    secret=replace (config 02 01 02 00), merit=coexist on top."""

    options: ClassVar[dict[str, Any]] = {
        "recycle_shop_locations": "replace",
        "item_shop_locations": "coexist",
        "secret_shop_locations": "replace",
        "merit_shop_locations": "coexist",
    }

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _capture_tokens_ordered(self.world)
        self.last: dict[int, bytes] = {}
        for off, data in self.tokens:
            self.last[off] = data

    def test_common_infra_matches_lab_bytes(self) -> None:
        self.assertEqual(
            self.last[SHOP_AP_BUILDER_WRAPPER_OFFSET].hex(), _LAB_BUILDER_WRAPPER_HEX,
        )
        self.assertEqual(
            self.last[SHOP_AP_GIVEITEM_EXT_OFFSET].hex(), _LAB_GIVEITEM_EXT_HEX,
        )
        self.assertEqual(
            self.last[SHOP_AP_DISPATCHER_JAL_OFFSET],
            struct.pack("<I", _LAB_DISPATCHER_JAL),
        )
        self.assertEqual(
            self.last[SHOP_AP_GIVEITEM_JAL_OFFSET],
            struct.pack("<I", _LAB_GIVEITEM_JAL),
        )
        self.assertEqual(self.last[SHOP_AP_CONFIG_BIN_OFFSET].hex(), _LAB_CONFIG_FULL_HEX)

    def test_hook_ext_overwrites_base_hook(self) -> None:
        hook_writes = [
            data for off, data in self.tokens if off == ITEM_PARA_BOOT_HOOK_OFFSET
        ]
        # Base hook first (always-on relocation), ext hook last wins.
        self.assertEqual(hook_writes[0], ITEM_PARA_BOOT_HOOK_BYTES)
        self.assertEqual(hook_writes[-1].hex(), _LAB_HOOK_EXT_HEX)

    def test_ext_entries_for_all_enabled_shops(self) -> None:
        for slot in (*RECYCLE_SHOP_AP_ITEM_IDS, *ITEM_SHOP_AP_ITEM_IDS,
                     *SECRET_SHOP_AP_ITEM_IDS):
            off = ext_item_para_slot_bin_offset(slot)
            entry_writes = [d for o, d in self.tokens if o == off and len(d) == 32]
            self.assertEqual(len(entry_writes), 1, f"slot {slot}")

    def test_item_secret_prices_tiered_and_merit_value_zero(self) -> None:
        for i, slot in enumerate(ITEM_SHOP_AP_ITEM_IDS):
            entry = self.last[ext_item_para_slot_bin_offset(slot)]
            self.assertEqual(struct.unpack_from("<i", entry, 20)[0],
                             item_shop_tiered_price(i))
            # meritValue MUST stay 0 or the slot leaks into the merit scan.
            self.assertEqual(entry[24:26], b"\x00\x00")
        for i, slot in enumerate(SECRET_SHOP_AP_ITEM_IDS):
            entry = self.last[ext_item_para_slot_bin_offset(slot)]
            self.assertEqual(struct.unpack_from("<i", entry, 20)[0],
                             secret_shop_tiered_price(i))
            self.assertEqual(entry[24:26], b"\x00\x00")
        for i, slot in enumerate(RECYCLE_SHOP_AP_ITEM_IDS):
            entry = self.last[ext_item_para_slot_bin_offset(slot)]
            self.assertEqual(struct.unpack_from("<i", entry, 20)[0],
                             RECYCLE_SHOP_VANILLA_PRICES[i])

    def test_merit_coexist_emits_no_vanilla_zero_outs(self) -> None:
        from ..data.addresses import (
            ITEM_PARA_MERIT_VALUE_OFFSET,
            ROM_ITEM_TABLE_ENTRY_SIZE,
            _table_byte_to_bin_flat,
        )
        for vanilla_id, _name, _merit in MERIT_SHOP_VANILLA_ENTRIES:
            if vanilla_id == 117:
                continue  # Amazing rod: zeroed always-on by the v1 patcher
            off = _table_byte_to_bin_flat(
                vanilla_id * ROM_ITEM_TABLE_ENTRY_SIZE + ITEM_PARA_MERIT_VALUE_OFFSET,
            )
            zero_writes = [d for o, d in self.tokens if o == off and d == b"\x00\x00"]
            self.assertEqual(zero_writes, [],
                             f"unexpected coexist zero-out for slot {vanilla_id}")

    def test_relocate_extension_in_procedure(self) -> None:
        names = [step[0] for step in self.procedure]
        self.assertIn("relocate_item_desc_ptr", names)

    def test_pool_backing(self) -> None:
        # All 44 new locations (7 + 14 + 25 + 12 minus none) are backed:
        # itempool exactly fills the unfilled (non-event) locations.
        unfilled = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(unfilled))
        for name in (*ITEM_SHOP_LOCATION_NAMES, *SECRET_SHOP_LOCATION_NAMES):
            self.world.get_location(name)  # raises KeyError on miss


class TestShopsanityTokensMeritOnRecycleOff(DigimonWorldTestBase):
    """Regression: a merit-on / recycle-off seed must leave ext slots
    128..134 zeroed (the old garbage-rows bug must stay dead)."""

    options: ClassVar[dict[str, Any]] = {"merit_shop_locations": "replace"}

    def setUp(self) -> None:
        super().setUp()
        self.tokens, self.procedure = _capture_tokens_ordered(self.world)

    def test_recycle_ext_slots_stay_zeroed(self) -> None:
        # Apply every token that lands in the Cave6 seed block, in
        # order, then check slots 128..134 decode as all-zero entries.
        seed = bytearray(EXT_ITEM_PARA_SEED_SIZE)
        seed_base = EXT_ITEM_PARA_SEED_BIN_OFFSET
        for off, data in self.tokens:
            if seed_base <= off < seed_base + EXT_ITEM_PARA_SEED_SIZE:
                rel = off - seed_base
                seed[rel:rel + len(data)] = data
        for slot in RECYCLE_SHOP_AP_ITEM_IDS:
            rel = (slot - 128) * 32
            self.assertEqual(bytes(seed[rel:rel + 32]), b"\x00" * 32,
                             f"ext slot {slot} not zeroed")

    def test_merit_replace_zero_outs_present(self) -> None:
        from ..data.addresses import (
            ITEM_PARA_MERIT_VALUE_OFFSET,
            ROM_ITEM_TABLE_ENTRY_SIZE,
            _table_byte_to_bin_flat,
        )
        offsets = {off for off, _d in self.tokens}
        for vanilla_id, _name, _merit in MERIT_SHOP_VANILLA_ENTRIES:
            off = _table_byte_to_bin_flat(
                vanilla_id * ROM_ITEM_TABLE_ENTRY_SIZE + ITEM_PARA_MERIT_VALUE_OFFSET,
            )
            self.assertIn(off, offsets, f"missing zero-out for slot {vanilla_id}")

    def test_infra_present_with_all_money_shops_off_in_config(self) -> None:
        last = dict(self.tokens)
        for off in _SHOPSANITY_INFRA_OFFSETS:
            self.assertIn(off, last)
        # Merit is data-only and not in the config word.
        self.assertEqual(last[SHOP_AP_CONFIG_BIN_OFFSET], b"\x00\x00\x00\x00")
        # No item/secret ext entries.
        for slot in (*ITEM_SHOP_AP_ITEM_IDS, *SECRET_SHOP_AP_ITEM_IDS):
            off = ext_item_para_slot_bin_offset(slot)
            self.assertEqual([d for o, d in self.tokens if o == off], [],
                             f"unexpected entry for slot {slot}")


class TestShopsanityRandomizedPrices(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "recycle_shop_locations": "coexist",
        "item_shop_locations": "replace",
        "secret_shop_locations": "coexist",
        "shop_price_mode": "randomized",
        "shop_price_min": 777,
        "shop_price_max": 777,
    }

    def test_all_money_prices_pinned_to_range(self) -> None:
        tokens, _procedure = _capture_tokens_ordered(self.world)
        last = dict(tokens)
        for slot in (*RECYCLE_SHOP_AP_ITEM_IDS, *ITEM_SHOP_AP_ITEM_IDS,
                     *SECRET_SHOP_AP_ITEM_IDS):
            entry = last[ext_item_para_slot_bin_offset(slot)]
            self.assertEqual(struct.unpack_from("<i", entry, 20)[0], 777, slot)


# =============================================================================
# Options: legacy aliases + price validation
# =============================================================================


class TestShopOptionAliases(unittest.TestCase):
    def test_legacy_true_maps_to_replace(self) -> None:
        for cls in (RecycleShopLocations, MeritShopLocations):
            self.assertEqual(cls.from_any(True).value, cls.option_replace)
            self.assertEqual(cls.from_any("true").value, cls.option_replace)

    def test_legacy_false_maps_to_off(self) -> None:
        for cls in (RecycleShopLocations, MeritShopLocations):
            self.assertEqual(cls.from_any(False).value, cls.option_off)
            self.assertEqual(cls.from_any("false").value, cls.option_off)

    def test_numeric_values_pass_through(self) -> None:
        for cls in (RecycleShopLocations, MeritShopLocations,
                    ItemShopLocations, SecretShopLocations):
            self.assertEqual(cls.from_any(0).value, cls.option_off)
            self.assertEqual(cls.from_any(1).value, cls.option_coexist)
            self.assertEqual(cls.from_any(2).value, cls.option_replace)
            self.assertEqual(cls.default, cls.option_off)


class TestShopPriceValidation(unittest.TestCase):
    @staticmethod
    def _options(mode: int, price_min: int, price_max: int) -> SimpleNamespace:
        return SimpleNamespace(
            shop_price_mode=SimpleNamespace(value=mode),
            shop_price_min=SimpleNamespace(value=price_min),
            shop_price_max=SimpleNamespace(value=price_max),
        )

    def test_inverted_range_raises_under_randomized(self) -> None:
        with self.assertRaises(OptionError):
            validate_shop_price_options(self._options(1, 5000, 100), "Tester")

    def test_valid_and_tiered_ranges_pass(self) -> None:
        validate_shop_price_options(self._options(1, 100, 5000), "Tester")
        validate_shop_price_options(self._options(1, 500, 500), "Tester")
        # Tiered mode ignores the range entirely.
        validate_shop_price_options(self._options(0, 5000, 100), "Tester")


# =============================================================================
# Locations + rules
# =============================================================================


class TestShopLocationsPresence(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "item_shop_locations": "coexist",
        "secret_shop_locations": "replace",
    }

    def test_locations_exist_with_expected_ids_and_region(self) -> None:
        from ..locations import LOCATION_NAME_TO_ID
        for i, name in enumerate(ITEM_SHOP_LOCATION_NAMES):
            self.assertEqual(LOCATION_NAME_TO_ID[name], 69_062_000 + i)
            self.assertEqual(
                self.world.get_location(name).parent_region.name, "File City",
            )
        for i, name in enumerate(SECRET_SHOP_LOCATION_NAMES):
            self.assertEqual(LOCATION_NAME_TO_ID[name], 69_063_000 + i)
            self.assertEqual(
                self.world.get_location(name).parent_region.name, "File City",
            )

    def test_secret_shop_names_identify_the_clerk(self) -> None:
        self.assertEqual(SECRET_SHOP_LOCATION_NAMES[0], "Secret Shop (Numemon) #1")
        self.assertEqual(SECRET_SHOP_LOCATION_NAMES[3], "Secret Shop (Mojyamon) #1")
        self.assertEqual(SECRET_SHOP_LOCATION_NAMES[6], "Secret Shop (Mamemon) #1")
        self.assertEqual(SECRET_SHOP_LOCATION_NAMES[11], "Secret Shop (Devimon) #3")


class TestShopLocationsAbsentByDefault(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_locations_absent(self) -> None:
        for name in (*ITEM_SHOP_LOCATION_NAMES, *SECRET_SHOP_LOCATION_NAMES):
            with self.assertRaises(KeyError, msg=f"{name} should not exist"):
                self.world.get_location(name)


class TestItemShopTierRules(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"item_shop_locations": "replace"}

    def test_tier_gating(self) -> None:
        tier1, tier2, _tier3 = ITEM_SHOP_TIER_COUNTS
        self.collect_all_but(["Progressive Item Shop"])
        for name in ITEM_SHOP_LOCATION_NAMES:
            self.assertFalse(self.can_reach_location(name), name)
        shops = self.get_items_by_name("Progressive Item Shop")
        self.assertGreaterEqual(len(shops), 3)

        self.collect(shops[0])  # tier 1
        for i, name in enumerate(ITEM_SHOP_LOCATION_NAMES):
            self.assertEqual(self.can_reach_location(name), i < tier1, name)

        self.collect(shops[1])  # tier 2
        for i, name in enumerate(ITEM_SHOP_LOCATION_NAMES):
            self.assertEqual(self.can_reach_location(name), i < tier1 + tier2, name)

        self.collect(shops[2])  # tier 3
        for name in ITEM_SHOP_LOCATION_NAMES:
            self.assertTrue(self.can_reach_location(name), name)


class TestSecretShopRules(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"secret_shop_locations": "coexist"}

    def test_clerk_pool_gating(self) -> None:
        early = SECRET_SHOP_LOCATION_NAMES[:6]     # Numemon + Mojyamon
        late = SECRET_SHOP_LOCATION_NAMES[6:]      # Mamemon + Devimon
        self.collect_all_but(["Progressive Item Shop", "Progressive Secret Shop"])
        for name in SECRET_SHOP_LOCATION_NAMES:
            self.assertFalse(self.can_reach_location(name), name)

        item_shops = self.get_items_by_name("Progressive Item Shop")
        secret_shops = self.get_items_by_name("Progressive Secret Shop")
        self.assertGreaterEqual(len(secret_shops), 2)

        # Secret x1 alone is not enough — the sewer needs Item Shop x2.
        self.collect(secret_shops[0])
        for name in SECRET_SHOP_LOCATION_NAMES:
            self.assertFalse(self.can_reach_location(name), name)
        self.collect(item_shops[0])
        for name in SECRET_SHOP_LOCATION_NAMES:
            self.assertFalse(self.can_reach_location(name), name)
        self.collect(item_shops[1])
        for name in early:
            self.assertTrue(self.can_reach_location(name), name)
        for name in late:
            self.assertFalse(self.can_reach_location(name), name)

        self.collect(secret_shops[1])
        for name in SECRET_SHOP_LOCATION_NAMES:
            self.assertTrue(self.can_reach_location(name), name)


# =============================================================================
# Client wiring
# =============================================================================


class TestClientWatchMap(unittest.TestCase):
    def test_shop_bits_in_watch_map(self) -> None:
        from ..client import LOCATION_RAM_BITS
        for name, bit in (*ITEM_SHOP_LOCATION_RAM_BITS.items(),
                          *SECRET_SHOP_LOCATION_RAM_BITS.items()):
            self.assertEqual(LOCATION_RAM_BITS.get(name), bit, name)

    def test_recycle_array_reconciler_removed(self) -> None:
        from ..client import DigimonWorldClient
        self.assertFalse(hasattr(DigimonWorldClient, "_reconcile_recycle_shop_array"))
        # The merit sentinel reconciler is still load-bearing.
        self.assertTrue(hasattr(DigimonWorldClient, "_reconcile_merit_shop_sentinel"))


class TestSlotDataModes(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "recycle_shop_locations": "replace",
        "item_shop_locations": "coexist",
        "secret_shop_locations": "replace",
        "merit_shop_locations": "coexist",
    }

    def test_shop_modes_in_slot_data(self) -> None:
        slot_data = self.world.fill_slot_data()
        self.assertEqual(slot_data["recycle_shop_locations"], 2)
        self.assertEqual(slot_data["item_shop_locations"], 1)
        self.assertEqual(slot_data["secret_shop_locations"], 2)
        self.assertEqual(slot_data["merit_shop_locations"], 1)


# =============================================================================
# Vanilla-byte anchors (needs a local SLUS-01032 dump; skipped on CI)
# =============================================================================

_LOCAL_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


@unittest.skipUnless(_LOCAL_BIN.is_file(), "SLUS-01032 dump not present")
class TestShopsanityVanillaAnchors(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._rom = _LOCAL_BIN.open("rb")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._rom.close()

    def _read(self, offset: int, length: int) -> bytes:
        self._rom.seek(offset)
        return self._rom.read(length)

    def test_dispatcher_jal_vanilla_word(self) -> None:
        got = struct.unpack("<I", self._read(SHOP_AP_DISPATCHER_JAL_OFFSET, 4))[0]
        self.assertEqual(got, SHOP_AP_DISPATCHER_JAL_VANILLA)

    def test_giveitem_jal_vanilla_word(self) -> None:
        got = struct.unpack("<I", self._read(SHOP_AP_GIVEITEM_JAL_OFFSET, 4))[0]
        self.assertEqual(got, SHOP_AP_GIVEITEM_JAL_VANILLA)

    def test_staging2_region_all_zero_in_vanilla(self) -> None:
        got = self._read(SHOP_AP_STAGING2_BIN_OFFSET, SHOP_AP_STAGING2_SIZE)
        self.assertEqual(got, b"\x00" * SHOP_AP_STAGING2_SIZE)

    def test_freed_desc_ptr_region_holds_kuseg_pointers(self) -> None:
        # The 512 B the wrappers overwrite hold the 128 vanilla
        # ITEM_DESC_PTR entries — every u32 a plausible kuseg pointer.
        got = self._read(SHOP_AP_BUILDER_WRAPPER_OFFSET, 384)
        got += self._read(SHOP_AP_GIVEITEM_EXT_OFFSET, 104)
        for i in range(0, len(got), 4):
            ptr = struct.unpack_from("<I", got, i)[0]
            self.assertTrue(0x80000000 <= ptr < 0x80200000, hex(ptr))
