"""Logic tests for the Digimon World 1 APWorld (Phase 4 v7).

Recruits are AP locations again (50 spawn-point checks) but no longer
ship as items. ``Prosperity Point`` is the only recruit-progression-
adjacent AP item; 50 copies fill the 50-PP goal gate.

Tests:

* Item-pool / location-count balance.
* Recruit AP locations exist for all 50 Digimon.
* No ``X Recruit`` items in the pool.
* Final-Battle endgame requires 50 Prosperity Points (AS Decoder
  used to be part of the rule but is a no-op item; removed 2026-05-08).
* The closed-shuffle ``recruit_remap`` is shaped right.
* Filler-distribution shape (Phase 8) — ``build_filler_pool`` produces
  exactly ``count`` items in roughly the expected per-bucket proportion.
"""

import random
import unittest
from typing import Any, ClassVar

from .bases import DigimonWorldTestBase


class TestPhase4Logic(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Pool/location balance
    # ------------------------------------------------------------------

    def test_itempool_size_matches_location_count(self) -> None:
        """Item pool exactly fills the non-event locations."""

        non_event_locations = [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
        ]
        self.assertEqual(len(self.multiworld.itempool), len(non_event_locations))

    def test_recruit_count(self) -> None:
        """All 50 DW1 recruits are present as real (id-bearing) locations."""

        from .. import locations as loc_module

        for recruit_name in loc_module.RECRUIT_NAMES:
            loc = self.multiworld.get_location(recruit_name, self.player)
            self.assertIsNotNone(loc.address, f"{recruit_name} should be id-bearing")

    def test_no_k_prosperity_locations(self) -> None:
        """K Prosperity locations were removed in v7."""

        from .. import locations as loc_module
        for name in loc_module.LOCATION_NAME_TO_ID:
            self.assertFalse(
                name.endswith(" Prosperity"),
                f"{name} should not exist in v7",
            )

    # ------------------------------------------------------------------
    # Item pool shape
    # ------------------------------------------------------------------

    def test_recruit_items_present(self) -> None:
        """18 individual ``X Recruit`` items ship after the Phase 7
        bundle rework (5 progression + 5 useful + 8 filler). The
        other 26 recruit-bit-managed Digimon are bundled into the
        6 ``Progressive <Feature>`` ladder items. See
        ``items.PROGRESSIVE_BUNDLES`` and ``_BUNDLED_RECRUITS``."""

        from ..items import ITEM_NAME_TO_ID, PROGRESSIVE_BUNDLES

        recruit_names = [n for n in ITEM_NAME_TO_ID if n.endswith(" Recruit")]
        self.assertEqual(len(recruit_names), 18, recruit_names)
        for excluded in ("Agumon Recruit", "Digitamamon Recruit",
                         "Airdramon Recruit", "Seadramon Recruit",
                         "Nanimon Recruit", "Giromon Recruit"):
            self.assertNotIn(excluded, ITEM_NAME_TO_ID)
        # Individual progression recruits remain present.
        for kept in ("Whamon Recruit", "Birdramon Recruit",
                     "Palmon Recruit", "Shellmon Recruit",
                     "Centarumon Recruit"):
            self.assertIn(kept, ITEM_NAME_TO_ID)
        # Bundled Digimon do NOT have individual items.
        for bundled in ("Betamon Recruit", "Patamon Recruit",
                        "Greymon Recruit", "Numemon Recruit",
                        "Drimogemon Recruit", "Kabuterimon Recruit"):
            self.assertNotIn(bundled, ITEM_NAME_TO_ID)
        # All 6 Progressive ladder items are present.
        for prog_name in PROGRESSIVE_BUNDLES:
            self.assertIn(prog_name, ITEM_NAME_TO_ID)

    def test_prosperity_point_in_pool(self) -> None:
        """Phase 9: pool size is ``prosperity_point_count(threshold)``,
        sized to the player's ``prosperity_goal`` option (default
        50 → 21 items). Each item is worth ``PROSPERITY_PER_ITEM`` (= 3)
        PP at delivery."""

        from ..items import (
            PROSPERITY_PER_ITEM,
            PROSPERITY_POINT_NAME,
            prosperity_point_count,
        )

        threshold = int(self.multiworld.worlds[self.player].options.prosperity_goal.value)
        expected = prosperity_point_count(threshold)
        pp_items = [
            item for item in self.multiworld.itempool
            if item.name == PROSPERITY_POINT_NAME
        ]
        self.assertEqual(len(pp_items), expected)
        # Total shipped PP must be at least the configured threshold.
        # (Comfort margin from PROSPERITY_OVERHEAD_FACTOR pushes us above.)
        self.assertGreaterEqual(expected * PROSPERITY_PER_ITEM, threshold)

    # ------------------------------------------------------------------
    # Endgame
    # ------------------------------------------------------------------

    def test_final_battle_requires_pp(self) -> None:
        """Final Battle event needs 50 Prosperity Points. AS Decoder
        used to also be required, but it is a no-op item in DW1 and
        gates nothing — removed from the pool 2026-05-08."""

        self.assertAccessDependency(
            ["Final Battle"],
            [["Prosperity Point"]],
            only_check_listed=True,
        )

    # ------------------------------------------------------------------
    # Card vending option
    # ------------------------------------------------------------------

    def test_card_locations_off_by_default(self) -> None:
        """The 66 card AP locations are NOT created when the option is off."""

        from .. import locations as loc_module

        for card_name in loc_module.CARD_NAMES:
            with self.assertRaises(KeyError):
                self.multiworld.get_location(card_name, self.player)


class TestPhase4LogicCardsOn(DigimonWorldTestBase):
    """Card-vending option turned on — generation must still succeed and
    the 66 card AP locations must be reachable from Gear Savanna."""

    options: ClassVar[dict[str, Any]] = {"card_locations": True}

    def test_card_count(self) -> None:
        """All 66 cards land as id-bearing AP locations."""

        from .. import locations as loc_module

        self.assertEqual(len(loc_module.CARD_NAMES), 66)
        for card_name in loc_module.CARD_NAMES:
            loc = self.multiworld.get_location(card_name, self.player)
            self.assertIsNotNone(loc.address, f"{card_name} should be id-bearing")

    def test_card_ids_match_dwap_wire_format(self) -> None:
        """Card AP IDs sit in DWAP's reserved 69_002_000 + index slot."""

        from .. import locations as loc_module

        for i, card_name in enumerate(loc_module.CARD_NAMES):
            self.assertEqual(
                loc_module.LOCATION_NAME_TO_ID[card_name],
                69_002_000 + i,
            )

    def test_card_pool_size_is_balanced(self) -> None:
        """Item pool still exactly fills non-event locations with the
        66 extra card locations added."""

        non_event_locations = [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
        ]
        self.assertEqual(len(self.multiworld.itempool), len(non_event_locations))


class TestPhase4LogicCardsAccess(DigimonWorldTestBase):
    """Verify cards are not in logic until either (a) Gear Savanna is
    reachable or (b) both Betamon and Patamon Recruit have been received.

    Without any progression items, Gear Savanna is reachable via the
    left chain (Native Forest → Drill Tunnel → Meramon Tunnel → Mt.
    Panorama → Gear Savanna), gated only by ``Lava Cave Access`` in
    shuffled mode (default). So we force Lava Cave Access into vanilla
    mode (= no AP gate) here, which makes Gear Savanna freely reachable
    from start, and then verify a sample card location is reachable.
    The Betamon+Patamon File City alternative is exercised by the
    same access rule mechanically — a card location's reachability
    OR-combines the two parents.
    """

    options: ClassVar[dict[str, Any]] = {
        "card_locations": True,
        "lava_cave_access": "vanilla",
    }

    def test_card_reachable_from_gear_savanna(self) -> None:
        """A card location is logically reachable once Gear Savanna is."""

        from .. import locations as loc_module

        sample = loc_module.CARD_NAMES[0]
        loc = self.multiworld.get_location(sample, self.player)
        # all_state grants every progression item; the location must be
        # reachable in that maximal state.
        all_state = self.multiworld.get_all_state(False)
        self.assertTrue(
            loc.can_reach(all_state),
            f"{sample} should be reachable in all_state",
        )


class TestPhase4LogicVendingOff(DigimonWorldTestBase):
    """Default config — vending option off — adds no vending locations."""

    options: ClassVar[dict[str, Any]] = {}

    def test_vending_locations_off_by_default(self) -> None:
        from ..data.addresses import VENDING_LOCATION_NAMES

        for name in VENDING_LOCATION_NAMES:
            with self.assertRaises(KeyError):
                self.multiworld.get_location(name, self.player)


class TestPhase4LogicVendingOn(DigimonWorldTestBase):
    """Vending option on — generation must succeed and 12 locations appear
    in their respective regions (Greatlake / Tropical Jungle / Gear
    Savanna / Ancient Dino Region). Lava cave is left in shuffled mode
    so the deeper regions need their AP item; the vending locations
    naturally inherit those region access rules.
    """

    # Cards on too — the 35 unconfirmed chests are now EXCLUDED, which
    # leaves the default config slightly short on non-EXCLUDED slots
    # for all 87 mandatory progression items. Cards add 66 progression-
    # eligible locations and let fill complete.
    options: ClassVar[dict[str, Any]] = {
        "vending_locations": True,
        "card_locations": True,
    }

    def test_vending_count(self) -> None:
        from ..data.addresses import VENDING_LOCATION_NAMES

        self.assertEqual(len(VENDING_LOCATION_NAMES), 12)
        for name in VENDING_LOCATION_NAMES:
            loc = self.multiworld.get_location(name, self.player)
            self.assertIsNotNone(loc.address, f"{name} should be id-bearing")

    def test_vending_ids_are_in_69055_block(self) -> None:
        from .. import locations as loc_module
        from ..data.addresses import VENDING_LOCATION_NAMES

        for i, name in enumerate(VENDING_LOCATION_NAMES):
            self.assertEqual(
                loc_module.LOCATION_NAME_TO_ID[name], 69_055_000 + i,
            )

    def test_vending_pool_size_balanced(self) -> None:
        non_event_locations = [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
        ]
        self.assertEqual(len(self.multiworld.itempool), len(non_event_locations))

    def test_vending_regions_match_machine_layout(self) -> None:
        from ..data.addresses import VENDING_LOCATION_REGIONS

        expected = {
            "Greatlake": 2, "Tropical Jungle": 2,
            "Gear Savanna": 4, "Ancient Dino Region": 4,
        }
        actual: dict[str, int] = {}
        for region in VENDING_LOCATION_REGIONS.values():
            actual[region] = actual.get(region, 0) + 1
        self.assertEqual(expected, actual)


class TestVendingTextEncoder(DigimonWorldTestBase):
    """Encoder + textbox builder unit tests (no fill required)."""

    options: ClassVar[dict[str, Any]] = {}

    def test_encode_set_trigger_format(self) -> None:
        from ..data.addresses import encode_set_trigger

        # Trigger 890 = 0x037A LE → "1C 00 7A 03"
        self.assertEqual(encode_set_trigger(890), bytes((0x1C, 0x00, 0x7A, 0x03)))

    def test_vending_script_bases_self_consistent(self) -> None:
        """Sanity check each machine's script_base by deriving it two
        independent ways from the per-item ``overwrite_offsets``.

        Each ``_VendingItem.overwrite_offsets`` lists ROM-script offsets
        of vanilla ``giveItem``/``addStats`` opcodes. We assert that all
        offsets fall inside [0, 0x1000] (a single script bank) — a wrong
        ``script_base`` typically produces offsets that are far off.
        It's a cheap regression net for the kind of typo that previously
        caused two machines (script 71 and 78) to write tokens at
        offsets 32-64 bytes off and silently break the in-game flow.
        """
        from ..data.addresses import VENDING_MACHINES

        for machine in VENDING_MACHINES:
            for item in machine.items:
                for off in item.overwrite_offsets:
                    self.assertGreater(off, 0, f"{machine.label}: bogus offset")
                    self.assertLess(
                        off, 0x1000,
                        f"{machine.label}: offset {off} >= 0x1000 (overshoots a single script)",
                    )


# =============================================================================
# Chest randomization toggle
# =============================================================================


class TestChestRandomizationOff(DigimonWorldTestBase):
    """ChestRandomization off — chest AP locations are excluded entirely.

    Pairs with ``card_locations: True`` so the seed has enough non-chest
    locations to absorb the 87 mandatory items (8 keys minus 2 bridge
    options that are always_open by default = 6 keys, plus 48 recruits
    + 5 Birdramon flights + 25 PP). Without an additional location
    source the seed can't fit those mandatory items — the existing
    pool-sizing assert in :func:`items.create_all_items` would fire.
    """

    options: ClassVar[dict[str, Any]] = {
        "chest_randomization": False,
        "card_locations": True,
    }

    def test_no_chest_locations(self) -> None:
        from .. import locations as loc_module

        for chest_name in loc_module.CHEST_NAMES:
            with self.assertRaises(KeyError):
                self.multiworld.get_location(chest_name, self.player)

    def test_pool_size_balanced_without_chests(self) -> None:
        non_event_locations = [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
        ]
        # Pool size must equal location count.
        self.assertEqual(len(self.multiworld.itempool), len(non_event_locations))


# =============================================================================
# Recruit randomization toggle
# =============================================================================


class TestRecruitRandomizationOff(DigimonWorldTestBase):
    """RecruitRandomization off — every <Name> Recruit item is locked at
    the matching recruit AP location."""

    # Cards on for fill capacity (see TestPhase4LogicVendingOn rationale).
    options: ClassVar[dict[str, Any]] = {
        "recruit_randomization": False,
        "card_locations": True,
    }

    def test_each_recruit_self_locked(self) -> None:
        from ..data.addresses import AP_RECRUIT_ITEM_DIGIMON
        from ..items import ITEM_NAME_TO_ID

        for digimon in AP_RECRUIT_ITEM_DIGIMON:
            recruit_item_name = f"{digimon} Recruit"
            if recruit_item_name not in ITEM_NAME_TO_ID:
                # Bundled recruit (Phase 7 rework — see
                # ``items.PROGRESSIVE_BUNDLES``): no individual
                # ``<X> Recruit`` item exists, so the AP location
                # stays unlocked and AP fill places whatever it
                # wants. Verify it's NOT pre-filled with a recruit
                # item, which would indicate a regression.
                location = self.multiworld.get_location(digimon, self.player)
                if location.item is not None:
                    self.assertFalse(
                        location.item.name.endswith(" Recruit"),
                        f"bundled {digimon} location should not be "
                        f"pre-filled with a recruit item",
                    )
                continue
            location = self.multiworld.get_location(digimon, self.player)
            self.assertIsNotNone(
                location.item, f"{digimon} location should be pre-filled",
            )
            self.assertEqual(
                location.item.name, recruit_item_name,
                f"{digimon} location should hold its own recruit item, "
                f"got {location.item.name}",
            )
            self.assertEqual(location.item.player, self.player)
            self.assertTrue(
                location.locked,
                f"{digimon} recruit item should be locked",
            )

    def test_no_recruit_items_in_multiworld_pool(self) -> None:
        recruit_items_in_pool = [
            item for item in self.multiworld.itempool
            if item.name.endswith(" Recruit") and item.player == self.player
        ]
        self.assertEqual(
            recruit_items_in_pool, [],
            "no <Name> Recruit items should remain in the pool",
        )

    def test_pool_size_matches_unfilled_locations(self) -> None:
        # 48 recruit locations are pre-filled; pool should match remaining.
        unfilled = self.multiworld.get_unfilled_locations(self.player)
        self.assertEqual(len(self.multiworld.itempool), len(unfilled))


# =============================================================================
# Filler distribution (Phase 8)
# =============================================================================


class TestFillerDistribution(unittest.TestCase):
    """``build_filler_pool`` enforces the per-seed proportion contract:

    * exactly ``count`` items returned (rounding drift repaired).
    * every item is a real shippable AP filler item.
    * for large ``count``, observed bucket frequencies are close to the
      configured weights.
    * deterministic for a given RNG seed.
    """

    def test_pool_size_matches_count(self) -> None:
        from ..items import build_filler_pool

        rng = random.Random(0xDEAD_BEEF)
        for count in (0, 1, 7, 13, 49, 100, 423):
            pool = build_filler_pool(rng, count)
            self.assertEqual(len(pool), count, count)

    def test_pool_contents_are_known_items(self) -> None:
        from ..items import ITEM_NAME_TO_ID, build_filler_pool

        rng = random.Random(42)
        pool = build_filler_pool(rng, 200)
        for name in pool:
            self.assertIn(name, ITEM_NAME_TO_ID, name)

    def test_observed_proportions_track_weights(self) -> None:
        from ..items import FILLER_DISTRIBUTION, build_filler_pool

        rng = random.Random(0xC0FFEE)
        count = 10_000
        pool = build_filler_pool(rng, count)
        # Map each item back to its bucket index for tallying.
        bucket_index_by_item: dict[str, int] = {}
        for i, (bucket, _) in enumerate(FILLER_DISTRIBUTION):
            for name in bucket:
                bucket_index_by_item[name] = i

        observed = [0] * len(FILLER_DISTRIBUTION)
        for name in pool:
            observed[bucket_index_by_item[name]] += 1

        for i, (_, weight) in enumerate(FILLER_DISTRIBUTION):
            actual = observed[i] / count
            self.assertAlmostEqual(
                actual, weight, places=2,
                msg=f"bucket {i} observed={actual:.3f} expected={weight}",
            )

    def test_deterministic_for_fixed_seed(self) -> None:
        from ..items import build_filler_pool

        rng_a = random.Random(1234)
        rng_b = random.Random(1234)
        self.assertEqual(
            build_filler_pool(rng_a, 64),
            build_filler_pool(rng_b, 64),
        )


# =============================================================================
# Mt. Infinity prosperity option (Phase 9)
# =============================================================================


class TestProsperityPointCount(unittest.TestCase):
    """``prosperity_point_count`` rounds ``ceil(threshold / 3) * 1.2``
    upward, matching the user-spec margin."""

    def test_known_thresholds(self) -> None:
        from ..items import prosperity_point_count

        # User-spec example: 50 → ceil(17 * 1.2) = ceil(20.4) = 21.
        self.assertEqual(prosperity_point_count(50), 21)
        # Range bounds and a couple of intermediate values.
        self.assertEqual(prosperity_point_count(20), 9)    # ceil( 7 * 1.2) =  9
        self.assertEqual(prosperity_point_count(30), 12)   # ceil(10 * 1.2) = 12
        self.assertEqual(prosperity_point_count(45), 18)   # ceil(15 * 1.2) = 18
        self.assertEqual(prosperity_point_count(100), 41)  # ceil(34 * 1.2) = 41

    def test_monotonic_with_threshold(self) -> None:
        from ..items import prosperity_point_count

        prev = 0
        for thresh in range(20, 101):
            count = prosperity_point_count(thresh)
            self.assertGreaterEqual(count, prev, thresh)
            prev = count

    def test_count_covers_threshold(self) -> None:
        """Each item delivers 3 PP; ``count * 3`` must always meet or
        exceed the threshold so the in-game gate can be reached."""

        from ..items import (
            PROSPERITY_PER_ITEM,
            prosperity_point_count,
        )

        for thresh in range(20, 101):
            count = prosperity_point_count(thresh)
            self.assertGreaterEqual(
                count * PROSPERITY_PER_ITEM, thresh, thresh,
            )


class TestProsperityGoalLow(DigimonWorldTestBase):
    """With a low ``prosperity_goal`` (below 45), recruits gated above
    the threshold (45/50 PP) get marked EXCLUDED + filler-only and
    their PP rules dropped. The PP pool sizes to the threshold only —
    no floor at 50."""

    options: ClassVar[dict[str, Any]] = {
        "prosperity_goal": 30,
    }

    def test_pool_count_matches_threshold(self) -> None:
        from ..items import (
            PROSPERITY_POINT_NAME,
            prosperity_point_count,
        )

        pp_items = [
            item for item in self.multiworld.itempool
            if item.name == PROSPERITY_POINT_NAME
        ]
        # 30 PP threshold → ceil(10 * 1.2) = 12 items. No 50-PP floor.
        self.assertEqual(len(pp_items), prosperity_point_count(30))
        self.assertEqual(len(pp_items), 12)

    def test_unreachable_recruits_marked_excluded(self) -> None:
        from BaseClasses import LocationProgressType

        for unreachable in ("Etemon", "Ninjamon", "Devimon",
                            "Megadramon", "MetalGreymon",
                            "Leomon", "Vademon", "SkullGreymon"):
            loc = self.multiworld.get_location(unreachable, self.player)
            self.assertEqual(
                loc.progress_type, LocationProgressType.EXCLUDED,
                f"{unreachable} should be EXCLUDED at threshold=30",
            )

    def test_leomonstone_pickup_excluded(self) -> None:
        from BaseClasses import LocationProgressType

        loc = self.multiworld.get_location("Leomonstone Pickup", self.player)
        self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED)

    def test_leomon_ancestor_cave_chest_excluded(self) -> None:
        from BaseClasses import LocationProgressType

        loc = self.multiworld.get_location(
            "Chest: Leomon Ancestor Cave", self.player,
        )
        self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED)


class TestProsperityGoalHigh(DigimonWorldTestBase):
    """With a high ``prosperity_goal`` (80), the pool grows past the
    default 21 items but no recruits are excluded (all vanilla gates
    ≤ 80)."""

    options: ClassVar[dict[str, Any]] = {
        "prosperity_goal": 80,
        # Cards on so the larger PP pool fits.
        "card_locations": True,
    }

    def test_pool_count_grows_with_threshold(self) -> None:
        from ..items import (
            PROSPERITY_POINT_NAME,
            prosperity_point_count,
        )

        pp_items = [
            item for item in self.multiworld.itempool
            if item.name == PROSPERITY_POINT_NAME
        ]
        # 80 PP threshold → ceil(27 * 1.2) = 33 items.
        self.assertEqual(len(pp_items), prosperity_point_count(80))
        self.assertGreater(len(pp_items), prosperity_point_count(50))
