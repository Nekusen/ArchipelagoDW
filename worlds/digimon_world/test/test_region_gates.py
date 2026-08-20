"""Region-gate feature tests (physical enforcement of ``region_locking``).

Covers the production port of the lab-validated 2026-08-20/21 specs
(``work/dw1_re/patches/transition_gate_spec.py`` / ``script_gates_spec.py``,
three nets each):

* Byte-for-byte reproduction of the validated wrapper / gate table /
  hook / script-gate payloads for the full-locked case. The expectation
  literals below are frozen copies of the lab ``transition_gate.json`` /
  ``script_gates.json`` outputs — do not regenerate them from the
  production builders (that would make the test a tautology).
* Trigger-id allocation invariants (uniqueness, hard ceiling, no
  collisions with any shipped allocation).
* Per-seed gate-table filtering (locked subset -> subset of rows).
* Patcher token emission across ``region_locking`` states.
* New logic: Native Forest <-> Mt. Panorama edges, the Ninjamon
  secret-shop fix, and the Beetle Land return-ferry Native-Forest gate.
* Client-side pinning of the region-gate trigger bits.
* Vanilla-byte anchors read from a local SLUS-01032 dump (skipped when
  the dump isn't present, e.g. on CI).
"""

from __future__ import annotations

import asyncio
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from worlds.Files import APTokenTypes

from .. import client as client_module
from .. import rom as rom_module
from ..data.addresses import (
    AP_TRIGGER_ARRAY_BASE,
    ARENA_CUP_TIERS,
    BIRDRA_FLIGHT_GCANYON_RAM_BIT,
    BIRDRA_FLIGHT_GCANYON_TRIGGER_ID,
    MERIT_SHOP_TRIGGER_IDS,
    RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE,
    RECYCLE_SHOP_TRIGGER_IDS,
    REGION_ACCESS_RAM_BITS,
    REGION_ACCESS_TRIGGER_IDS,
    ROM_BIRDRA_FLIGHT_GCANYON_PATCHES,
    ROM_BIRDRA_FLIGHT_GCANYON_VANILLA_TRIGGER,
    ROM_BIRDRA_FLIGHT_PRICE_OFFSETS,
    ROM_BIRDRA_FLIGHT_PRICE_ZERO,
    ROM_BIRDRA_FLIGHT_TABLE_PATCHES,
    ROM_TRANSITION_GATE_HOOK_BYTES,
    ROM_TRANSITION_GATE_WRAPPER_BYTES,
    SCRIPT_GATE_PATCHES,
    TRANSITION_GATE_HOOK_OFFSET,
    TRANSITION_GATE_HOOK_VANILLA_WORD,
    TRANSITION_GATE_ROWS,
    TRANSITION_GATE_TABLE_OFFSET,
    TRANSITION_GATE_WRAPPER_OFFSET,
    build_transition_gate_table,
    script_vm_to_bin_offset,
)
from ..items import ITEM_NAME_TO_ID
from ..regions import LOCKABLE_REGIONS, region_access_item_name
from .bases import DigimonWorldTestBase

# =============================================================================
# Frozen lab expectations (transition_gate.json / script_gates.json)
# =============================================================================

_LAB_WRAPPER_HEX = (
    "e0ffbd271c00bfaf1800b0af1400b1af9344020c000000001000a2af2588a002"
    "4cffa9261800212d0200201000000000b40011240980103c6867102600000992"
    "ff00012411002111000000000d00311500000000020004960f19040c00000000"
    "080040140000000001000b9214800c3c80878c2540680b0021608d01000095a5"
    "14008ba5edff0010040010261000a28f1c00bf8f1800b08f1400b18f0800e003"
    "2000bd27"
)

_LAB_FULL_TABLE_HEX = (
    "0700a603090280030b00a60311019e031200a6031601a1031701a1032200a703"
    "230180032401a3032601a0032701a0032c0080034500a5034d03a2034f008003"
    "5801a3035802a3035f01a4036e029f036f01a5036f029f037000a6037300a203"
    "77028f037902a0037f01a0038a00a1038b02a4039000a4039c01a103b400a603"
    "b402a603ff000000"
)

_LAB_HOOK_WORD = 0x0C0259B1

# (flat .bin offset, payload hex) for all 12 script-gate writes.
_LAB_SCRIPT_GATE_ENTRIES: frozenset[tuple[int, str]] = frozenset({
    (0x01405E4B4, "1600281f"),
    (0x01405E4CA, "401f"),
    (0x01405E650, "19000000a6031800981d19004efd48f4ec0100001600941d"),
    (0x01405E668, "19000000a6031800a61d19001600a81d"),
    (0x01405B3A6, "4c22"),
    (0x01405BCB4, "1900000081031800d81a19001600d01a"),
    (0x013FE1630, "200f"),
    (0x013FE2108, "300f"),
    (0x013FE25C8, "190000006f031800f40019001600f600"),
    (0x013FE25D8, "190000006f031800c80e19001600100e"),
    (0x014025258, "a002"),
    (0x014025438, "19000000a6031800ee0019001600f200"),
})

_ALL_LOCKED = frozenset(LOCKABLE_REGIONS)


# =============================================================================
# Byte fidelity against the lab specs
# =============================================================================


class TestRegionGateByteFidelity(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_wrapper_bytes_match_lab_spec(self) -> None:
        self.assertEqual(
            ROM_TRANSITION_GATE_WRAPPER_BYTES.hex(), _LAB_WRAPPER_HEX,
        )
        self.assertEqual(len(ROM_TRANSITION_GATE_WRAPPER_BYTES), 164)

    def test_full_locked_table_matches_lab_spec(self) -> None:
        table = build_transition_gate_table(_ALL_LOCKED)
        self.assertEqual(table.hex(), _LAB_FULL_TABLE_HEX)
        self.assertEqual(len(table), (len(TRANSITION_GATE_ROWS) + 1) * 4)

    def test_hook_bytes_match_lab_spec(self) -> None:
        self.assertEqual(
            ROM_TRANSITION_GATE_HOOK_BYTES, struct.pack("<I", _LAB_HOOK_WORD),
        )
        # Vanilla word decodes to jal memcpy (0x8009124C).
        self.assertEqual(TRANSITION_GATE_HOOK_VANILLA_WORD, 0x0C024493)

    def test_script_gate_entries_match_lab_spec(self) -> None:
        produced = {
            (script_vm_to_bin_offset(entry.script, entry.vm_offset),
             entry.data.hex())
            for patches in SCRIPT_GATE_PATCHES.values()
            for entry in patches
        }
        self.assertEqual(produced, set(_LAB_SCRIPT_GATE_ENTRIES))


# =============================================================================
# Trigger allocation
# =============================================================================


class TestRegionGateTriggerAllocation(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_one_trigger_per_lockable_region(self) -> None:
        self.assertEqual(set(REGION_ACCESS_TRIGGER_IDS), set(LOCKABLE_REGIONS))
        self.assertEqual(len(REGION_ACCESS_TRIGGER_IDS), 14)

    def test_trigger_ids_unique_including_gcanyon_bit(self) -> None:
        ids = list(REGION_ACCESS_TRIGGER_IDS.values())
        ids.append(BIRDRA_FLIGHT_GCANYON_TRIGGER_ID)
        self.assertEqual(len(ids), len(set(ids)))

    def test_trigger_ids_below_danger_zone(self) -> None:
        for trig in (*REGION_ACCESS_TRIGGER_IDS.values(),
                     BIRDRA_FLIGHT_GCANYON_TRIGGER_ID):
            self.assertLess(trig, 936)
            self.assertLess(
                AP_TRIGGER_ARRAY_BASE + trig // 8,
                RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE,
            )

    def test_no_collision_with_shipped_allocations(self) -> None:
        """The full shipped set: flight table rewrites 880-884, arena
        cups 885-889, vending 890-895 + 898-901, rods 902/903, recycle
        904-910, merit 912-925. In particular trigger 885 (the lab
        handoff's suggested G Canyon Top bit) is
        ``ARENA_CUP_GRADE_D_TRIGGER_ID`` — the production bit moved to
        878, and this test pins that collision forever."""

        from ..data.addresses import VENDING_MACHINES
        taken: set[int] = set()
        taken.update(new_id for _off, new_id in ROM_BIRDRA_FLIGHT_TABLE_PATCHES)
        taken.update(trig for _tier, _bit, trig, _pp in ARENA_CUP_TIERS)
        taken.update(
            item.trigger_id
            for machine in VENDING_MACHINES for item in machine.items
        )
        taken.update({902, 903})
        taken.update(RECYCLE_SHOP_TRIGGER_IDS)
        taken.update(MERIT_SHOP_TRIGGER_IDS)

        new = set(REGION_ACCESS_TRIGGER_IDS.values())
        new.add(BIRDRA_FLIGHT_GCANYON_TRIGGER_ID)
        self.assertFalse(new & taken, sorted(new & taken))
        self.assertIn(885, taken)
        self.assertEqual(BIRDRA_FLIGHT_GCANYON_TRIGGER_ID, 878)

    def test_trigger_ids_outside_recruit_wrapper_intercept(self) -> None:
        """The shipped isTriggerSet wrapper redirects reads of triggers
        203..258 to the AP recruit mirror; a Region Access bit in that
        band would be shadowed."""

        for trig in (*REGION_ACCESS_TRIGGER_IDS.values(),
                     BIRDRA_FLIGHT_GCANYON_TRIGGER_ID):
            self.assertFalse(203 <= trig <= 258, trig)

    def test_ram_bits_follow_settrigger_formula(self) -> None:
        for region, trig in REGION_ACCESS_TRIGGER_IDS.items():
            self.assertEqual(
                REGION_ACCESS_RAM_BITS[region],
                (AP_TRIGGER_ARRAY_BASE + trig // 8, trig % 8),
            )
        self.assertEqual(BIRDRA_FLIGHT_GCANYON_RAM_BIT, (0x001BE03A, 6))


# =============================================================================
# Per-seed table filtering
# =============================================================================


class TestRegionGateTableFiltering(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_empty_locked_set_yields_terminator_only(self) -> None:
        self.assertEqual(build_transition_gate_table(frozenset()).hex(), "ff000000")

    def test_script_only_regions_yield_no_walk_on_rows(self) -> None:
        """Beetle Land and Factorial Town have no walk-on border rows —
        both are script-entry-only (ferries); their enforcement lives in
        SCRIPT_GATE_PATCHES."""

        table = build_transition_gate_table({"Beetle Land", "Factorial Town"})
        self.assertEqual(table.hex(), "ff000000")
        for region in ("Beetle Land", "Factorial Town"):
            self.assertFalse(
                any(row_region == region for _s, _sl, row_region in TRANSITION_GATE_ROWS),
            )
            # ... but both DO have script-class gates.
            self.assertIn(region, SCRIPT_GATE_PATCHES)

    def test_single_region_subset(self) -> None:
        table = build_transition_gate_table({"Toy Town"})
        # Exactly one Toy Town row: MIST05 (119) slot 2, trigger 911.
        self.assertEqual(
            table,
            struct.pack("<BBH", 119, 2, 911) + struct.pack("<BBH", 0xFF, 0, 0),
        )

    def test_subset_rows_are_ordered_subset_of_full_table(self) -> None:
        full = build_transition_gate_table(_ALL_LOCKED)
        full_rows = [full[i:i + 4] for i in range(0, len(full) - 4, 4)]
        for locked in ({"Native Forest"}, {"Freezeland", "Great Canyon"},
                       {"Drill Tunnel", "Mt. Panorama", "Gear Savanna"}):
            sub = build_transition_gate_table(locked)
            sub_rows = [sub[i:i + 4] for i in range(0, len(sub) - 4, 4)]
            self.assertTrue(set(sub_rows).issubset(set(full_rows)), locked)
            # Order preserved: filter the full table by membership.
            self.assertEqual(
                sub_rows, [r for r in full_rows if r in set(sub_rows)], locked,
            )


# =============================================================================
# Patcher token emission
# =============================================================================


def _capture_tokens(world: Any) -> set[tuple[int, bytes]]:
    """Run generate_output with a stubbed patch writer; return the
    ``(offset, data)`` set of all WRITE tokens."""

    captured: dict[str, bytes] = {}

    def fake_write(self_patch: Any, target: str) -> None:
        with zipfile.ZipFile(target, "w"):
            pass
        captured.update(self_patch.files)

    with mock.patch.object(
        rom_module.DigimonWorldProcedurePatch, "write", fake_write,
    ), tempfile.TemporaryDirectory() as tmp_dir:
        world.generate_output(tmp_dir)

    blob = captured["token_data.bin"]
    count = int.from_bytes(blob[:4], "little")
    tokens: set[tuple[int, bytes]] = set()
    pos = 4
    for _ in range(count):
        token_type = blob[pos]
        offset = int.from_bytes(blob[pos + 1:pos + 5], "little")
        size = int.from_bytes(blob[pos + 5:pos + 9], "little")
        assert token_type == APTokenTypes.WRITE
        tokens.add((offset, blob[pos + 9:pos + 9 + size]))
        pos += 9 + size
    return tokens


class TestRegionGateTokensLockingOff(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"region_locking": "off"}

    def test_no_gate_tokens_but_prices_zeroed(self) -> None:
        tokens = _capture_tokens(self.world)
        offsets = {off for off, _data in tokens}
        self.assertNotIn(TRANSITION_GATE_WRAPPER_OFFSET, offsets)
        self.assertNotIn(TRANSITION_GATE_TABLE_OFFSET, offsets)
        self.assertNotIn(TRANSITION_GATE_HOOK_OFFSET, offsets)
        for lab_off, _hex in _LAB_SCRIPT_GATE_ENTRIES:
            self.assertNotIn(lab_off, offsets)
        for gc_off, _trig in ROM_BIRDRA_FLIGHT_GCANYON_PATCHES:
            self.assertNotIn(gc_off, offsets)
        # Flight price zeroing is unconditional QoL — present even with
        # region locking off.
        for price_off in ROM_BIRDRA_FLIGHT_PRICE_OFFSETS:
            self.assertIn((price_off, ROM_BIRDRA_FLIGHT_PRICE_ZERO), tokens)


class TestRegionGateTokensLockingAll(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"region_locking": "all"}

    def setUp(self) -> None:
        # Pin the seed: ``region_locking: all`` configs are tight enough
        # that some random seeds fail WorldTestBase's inherited
        # ``test_fill`` (pre-existing, documented in test_stub_logic's
        # _StartingRegionTestMixin; verified 2026-08-21 that failing
        # seed 60623866515897472426 also fails with the pre-region-gate
        # logic graph, so the gate feature is not causal).
        if self.auto_construct:
            self.world_setup(seed=42)

    def test_full_locked_tokens_match_lab_specs(self) -> None:
        tokens = _capture_tokens(self.world)
        self.assertIn(
            (TRANSITION_GATE_WRAPPER_OFFSET, ROM_TRANSITION_GATE_WRAPPER_BYTES),
            tokens,
        )
        self.assertIn(
            (TRANSITION_GATE_TABLE_OFFSET, bytes.fromhex(_LAB_FULL_TABLE_HEX)),
            tokens,
        )
        self.assertIn(
            (TRANSITION_GATE_HOOK_OFFSET, ROM_TRANSITION_GATE_HOOK_BYTES),
            tokens,
        )
        for lab_off, lab_hex in _LAB_SCRIPT_GATE_ENTRIES:
            self.assertIn((lab_off, bytes.fromhex(lab_hex)), tokens)
        for gc_off, new_trig in ROM_BIRDRA_FLIGHT_GCANYON_PATCHES:
            self.assertIn((gc_off, struct.pack("<H", new_trig)), tokens)
        for price_off in ROM_BIRDRA_FLIGHT_PRICE_OFFSETS:
            self.assertIn((price_off, ROM_BIRDRA_FLIGHT_PRICE_ZERO), tokens)


class TestRegionGateTokensCustomToyTown(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "custom",
        "region_locking_list": {"Toy Town"},
    }

    def test_only_toy_town_row_no_script_or_flight_tokens(self) -> None:
        tokens = _capture_tokens(self.world)
        offsets = {off for off, _data in tokens}
        self.assertIn(
            (TRANSITION_GATE_TABLE_OFFSET,
             build_transition_gate_table({"Toy Town"})),
            tokens,
        )
        self.assertIn(TRANSITION_GATE_WRAPPER_OFFSET, offsets)
        self.assertIn(TRANSITION_GATE_HOOK_OFFSET, offsets)
        for lab_off, _hex in _LAB_SCRIPT_GATE_ENTRIES:
            self.assertNotIn(lab_off, offsets)
        for gc_off, _trig in ROM_BIRDRA_FLIGHT_GCANYON_PATCHES:
            self.assertNotIn(gc_off, offsets)


class TestRegionGateTokensCustomBeetleLand(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "custom",
        "region_locking_list": {"Beetle Land"},
    }

    def test_script_gates_only_no_walk_on_hook(self) -> None:
        """A locked set with no walk-on rows must not install the
        wrapper or redirect the memcpy jal — the walk-on machinery would
        be dead weight."""

        tokens = _capture_tokens(self.world)
        offsets = {off for off, _data in tokens}
        self.assertNotIn(TRANSITION_GATE_WRAPPER_OFFSET, offsets)
        self.assertNotIn(TRANSITION_GATE_TABLE_OFFSET, offsets)
        self.assertNotIn(TRANSITION_GATE_HOOK_OFFSET, offsets)
        expected = {
            (script_vm_to_bin_offset(e.script, e.vm_offset), e.data)
            for e in SCRIPT_GATE_PATCHES["Beetle Land"]
        }
        for entry in expected:
            self.assertIn(entry, tokens)
        # No Native Forest / Factorial Town script gates.
        for region in ("Native Forest", "Factorial Town"):
            for e in SCRIPT_GATE_PATCHES[region]:
                self.assertNotIn(
                    script_vm_to_bin_offset(e.script, e.vm_offset), offsets,
                )


# =============================================================================
# Logic: new edges and rule fixes
# =============================================================================


class TestNativeForestMtPanoramaEdgeShuffledLava(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"lava_cave_access": "shuffled"}

    def test_edges_exist_both_directions(self) -> None:
        for name in ("Native Forest to Mt. Panorama",
                     "Mt. Panorama to Native Forest"):
            self.multiworld.get_entrance(name, self.player)  # raises if absent

    def test_forward_edge_needs_lava_cave_access(self) -> None:
        """Rule = Has(Lava Cave Access) & CanReach(Drill Tunnel). From
        an empty state Drill Tunnel is reachable (free from Native
        Forest), so the Lava Cave Access item is the binding term."""

        self.assertFalse(self.can_reach_entrance("Native Forest to Mt. Panorama"))
        self.collect_by_name("Lava Cave Access")
        self.assertTrue(self.can_reach_entrance("Native Forest to Mt. Panorama"))


class TestNativeForestMtPanoramaEdgeVanillaLava(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"lava_cave_access": "vanilla"}

    def test_forward_edge_free_in_vanilla_mode(self) -> None:
        """Vanilla boulder mode has no AP item; the edge only carries
        CanReach(Drill Tunnel), satisfied from scratch."""

        self.assertTrue(self.can_reach_entrance("Native Forest to Mt. Panorama"))


class TestNinjamonSecretShopRule(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def test_ninjamon_needs_two_progressive_item_shops(self) -> None:
        """The Secret Shop's only physical entrance is through the
        second item shop, so Ninjamon requires
        ``Has("Progressive Item Shop", count=2)`` on top of the
        Progressive Secret Shop term."""

        self.collect_all_but(["Progressive Item Shop"])
        self.assertFalse(self.can_reach_location("Ninjamon"))
        shops = self.get_items_by_name("Progressive Item Shop")
        self.assertGreaterEqual(len(shops), 2)
        self.collect(shops[0])
        self.assertFalse(self.can_reach_location("Ninjamon"))
        self.collect(shops[1])
        self.assertTrue(self.can_reach_location("Ninjamon"))


class TestBeetleLandReturnFerryGate(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "custom",
        "region_locking_list": {"Native Forest"},
    }
    # ``custom`` locking of Native Forest is a PRE-EXISTING option sharp
    # edge: unlike ``all`` there is no bootstrap kit, so sphere 0 is
    # empty (File City has no zero-requirement locations) and the
    # generic empty-state/fill tests cannot pass. This class only
    # exercises the return-ferry rule on a manually driven state.
    run_default_tests = False

    def test_greatlake_not_reachable_via_flown_beetle_land(self) -> None:
        """With Native Forest locked, the in-game Beetle Land return
        ferry declines without Native Forest Region Access (lab C3
        gate). Logic must match: flying into Beetle Land (Birdramon
        Recruit + Flight) with the Blue Flute must NOT make Greatlake
        reachable until NF Region Access arrives."""

        self.collect_all_but([region_access_item_name("Native Forest")])
        self.assertTrue(self.can_reach_region("Beetle Land"))
        self.assertFalse(self.can_reach_region("Greatlake"))
        self.collect_by_name(region_access_item_name("Native Forest"))
        self.assertTrue(self.can_reach_region("Greatlake"))


# =============================================================================
# Client: region-gate bit pinning
# =============================================================================


class _FakeItem:
    def __init__(self, item_id: int) -> None:
        self.item = item_id


class _FakeItemNames:
    _by_id: ClassVar[dict[int, str]] = {
        ap_id: name for name, ap_id in ITEM_NAME_TO_ID.items()
    }

    def lookup_in_game(self, item_id: int, _game: str) -> str:
        return self._by_id[item_id]


class _FakeGateCtx:
    def __init__(self, received: list[str]) -> None:
        self.bizhawk_ctx = object()
        self.game = "Digimon World"
        self.items_received = [_FakeItem(ITEM_NAME_TO_ID[n]) for n in received]
        self.item_names = _FakeItemNames()


class TestRegionGateBitReconciler(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    def _run_reconciler(
        self,
        *,
        locked: frozenset[str],
        received: list[str],
        initial_ram: dict[int, int],
    ) -> dict[int, int]:
        """Run one reconciler tick against a fake RAM byte map; return
        the post-tick byte map."""

        ram = dict(initial_ram)
        client = client_module.DigimonWorldClient()
        client._locked_regions = locked
        ctx = _FakeGateCtx(received)

        async def fake_read(_bizhawk_ctx: Any, requests: list[Any]) -> list[bytes]:
            return [bytes([ram.get(addr, 0)]) for addr, _size, _dom in requests]

        async def fake_write(_bizhawk_ctx: Any, writes: list[Any]) -> None:
            for addr, values, _dom in writes:
                ram[addr] = values[0]

        with mock.patch.object(client_module.bizhawk, "read", fake_read), \
                mock.patch.object(client_module.bizhawk, "write", fake_write):
            asyncio.get_event_loop().run_until_complete(
                client._reconcile_region_gate_bits(ctx),
            )
        return ram

    @staticmethod
    def _bit(ram: dict[int, int], ram_bit: tuple[int, int]) -> int:
        byte_addr, bit_index = ram_bit
        return (ram.get(byte_addr, 0) >> bit_index) & 1

    def test_flight_bit_held_down_until_destination_access_arrives(self) -> None:
        from ..data.addresses import BIRDRAMON_FLIGHT_RAM_BITS
        locked = frozenset({"Freezeland", "Great Canyon"})
        flight_fl = BIRDRAMON_FLIGHT_RAM_BITS["Birdramon Flight: Freezeland"]

        # Stale save state: every gate byte starts at 0xFF.
        dirty = dict.fromkeys(range(1826874, 1826882), 255)

        ram = self._run_reconciler(
            locked=locked,
            received=["Birdramon Recruit", "Birdramon Flight: Freezeland"],
            initial_ram=dirty,
        )
        # Flight item received but Freezeland is locked without its
        # Region Access -> bit pinned OFF. Same for the RA bits and the
        # G Canyon Top composite.
        self.assertEqual(self._bit(ram, flight_fl), 0)
        self.assertEqual(self._bit(ram, REGION_ACCESS_RAM_BITS["Freezeland"]), 0)
        self.assertEqual(self._bit(ram, REGION_ACCESS_RAM_BITS["Great Canyon"]), 0)
        self.assertEqual(self._bit(ram, BIRDRA_FLIGHT_GCANYON_RAM_BIT), 0)
        # Unlocked regions' RA bits are never touched (stale 1 survives).
        self.assertEqual(self._bit(ram, REGION_ACCESS_RAM_BITS["Toy Town"]), 1)

        ram = self._run_reconciler(
            locked=locked,
            received=[
                "Birdramon Recruit",
                "Birdramon Flight: Freezeland",
                region_access_item_name("Freezeland"),
                region_access_item_name("Great Canyon"),
            ],
            initial_ram={},
        )
        self.assertEqual(self._bit(ram, flight_fl), 1)
        self.assertEqual(self._bit(ram, REGION_ACCESS_RAM_BITS["Freezeland"]), 1)
        # G Canyon Top: Birdramon Recruit AND Great Canyon RA -> ON.
        self.assertEqual(self._bit(ram, BIRDRA_FLIGHT_GCANYON_RAM_BIT), 1)

    def test_flight_bit_unconditional_when_destination_not_locked(self) -> None:
        from ..data.addresses import BIRDRAMON_FLIGHT_RAM_BITS
        flight_mt = BIRDRAMON_FLIGHT_RAM_BITS["Birdramon Flight: Misty Trees"]
        ram = self._run_reconciler(
            locked=frozenset(),
            received=["Birdramon Flight: Misty Trees"],
            initial_ram={},
        )
        self.assertEqual(self._bit(ram, flight_mt), 1)
        # G Canyon Top bit untouched when Great Canyon isn't locked.
        self.assertEqual(self._bit(ram, BIRDRA_FLIGHT_GCANYON_RAM_BIT), 0)

    def test_noop_before_slot_data(self) -> None:
        client = client_module.DigimonWorldClient()
        self.assertIsNone(client._locked_regions)
        ctx = _FakeGateCtx([])
        called = False

        async def fake_read(_bizhawk_ctx: Any, _requests: list[Any]) -> list[bytes]:
            nonlocal called
            called = True
            return []

        with mock.patch.object(client_module.bizhawk, "read", fake_read):
            asyncio.get_event_loop().run_until_complete(
                client._reconcile_region_gate_bits(ctx),
            )
        self.assertFalse(called)


# =============================================================================
# Vanilla-byte anchors (needs a local SLUS-01032 dump; skipped on CI)
# =============================================================================

_LOCAL_BIN = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"


@unittest.skipUnless(_LOCAL_BIN.is_file(), "SLUS-01032 dump not present")
class TestRegionGateVanillaAnchors(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls._rom = _LOCAL_BIN.open("rb")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._rom.close()
        super().tearDownClass()

    def _read(self, offset: int, length: int) -> bytes:
        self._rom.seek(offset)
        return self._rom.read(length)

    def test_hook_site_vanilla_word(self) -> None:
        got = struct.unpack("<I", self._read(TRANSITION_GATE_HOOK_OFFSET, 4))[0]
        self.assertEqual(got, TRANSITION_GATE_HOOK_VANILLA_WORD)

    def test_script_retarget_sites_vanilla_bytes(self) -> None:
        for patches in SCRIPT_GATE_PATCHES.values():
            for entry in patches:
                if entry.vanilla is None:
                    continue  # stubs overwrite dead slot-tail residue
                got = self._read(
                    script_vm_to_bin_offset(entry.script, entry.vm_offset),
                    len(entry.vanilla),
                )
                self.assertEqual(got, entry.vanilla, entry.note)

    def test_flight_table_entry0_vanilla_trigger(self) -> None:
        for offset, _new in ROM_BIRDRA_FLIGHT_GCANYON_PATCHES:
            got = struct.unpack("<H", self._read(offset, 2))[0]
            self.assertEqual(got, ROM_BIRDRA_FLIGHT_GCANYON_VANILLA_TRIGGER)
