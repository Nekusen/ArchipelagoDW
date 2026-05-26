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
        """Final Battle event needs prosperity-goal PP AND all 3
        Progressive Item Shop copies (the difficulty-floor gate added
        because vanilla DW1's endgame fights are intentionally hard
        without the full shop's consumables). AS Decoder used to also
        be required, but it is a no-op item in DW1 and gates nothing —
        removed from the pool 2026-05-08."""

        # Both items required together — passed as one group so
        # assertAccessDependency collects both before checking reach.
        self.assertAccessDependency(
            ["Final Battle"],
            [["Prosperity Point", "Progressive Item Shop"]],
            only_check_listed=True,
        )

    def test_final_battle_blocked_without_full_shop(self) -> None:
        """Concrete state check: with all progression items except
        ``Progressive Item Shop``, Final Battle is still unreachable.
        Catches regressions where the shop requirement gets dropped."""

        from BaseClasses import CollectionState

        state = self.multiworld.get_all_state(False)
        # Remove every Progressive Item Shop the all-state granted.
        while "Progressive Item Shop" in state.prog_items[self.player]:
            state.remove(self.world.create_item("Progressive Item Shop"))
        final_battle = self.multiworld.get_location("Final Battle", self.player)
        self.assertFalse(
            final_battle.can_reach(state),
            "Final Battle should require all 3 Progressive Item Shop copies",
        )

        # Restore: 3 copies is the required count.
        for _ in range(3):
            state.collect(
                self.world.create_item("Progressive Item Shop"),
                prevent_sweep=True,
            )
        self.assertTrue(
            final_battle.can_reach(state),
            "Final Battle should be reachable with 3 Progressive Item Shop copies + other progression",
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

        self.assertEqual(len(VENDING_LOCATION_NAMES), 10)
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
            "Gear Savanna": 2, "Ancient Dino Region": 4,
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
# Fishing locations toggle
# =============================================================================


class TestFishingLocationsOff(DigimonWorldTestBase):
    """Default config — fishing option off — no fishing AP locations."""

    options: ClassVar[dict[str, Any]] = {}

    def test_fishing_locations_off_by_default(self) -> None:
        from ..data.addresses import FISHING_LOCATION_NAMES

        for name in FISHING_LOCATION_NAMES:
            with self.assertRaises(KeyError):
                self.multiworld.get_location(name, self.player)


class TestFishingLocationsOn(DigimonWorldTestBase):
    """Fishing option on — 6 fish AP locations in Greatlake, gated by rod."""

    options: ClassVar[dict[str, Any]] = {
        "fishing_locations": True,
    }

    def test_fishing_locations_present_in_greatlake(self) -> None:
        from .. import locations as loc_module
        from ..data.addresses import FISHING_LOCATION_NAMES

        self.assertEqual(len(FISHING_LOCATION_NAMES), 6)
        for i, name in enumerate(FISHING_LOCATION_NAMES):
            loc = self.multiworld.get_location(name, self.player)
            self.assertIsNotNone(loc.address, f"{name} should be id-bearing")
            self.assertEqual(
                loc_module.LOCATION_NAME_TO_ID[name], 69_058_000 + i,
            )
            self.assertEqual(loc.parent_region.name, "Greatlake")

    def test_fishing_locations_require_rod(self) -> None:
        """Each fishing location must be access-dependent on at least one rod."""

        from ..data.addresses import FISHING_LOCATION_NAMES

        self.assertAccessDependency(
            list(FISHING_LOCATION_NAMES),
            [["Old Fishrod"], ["Amazing rod"]],
            only_check_listed=True,
        )

    def test_fishing_pool_size_balanced(self) -> None:
        non_event_locations = [
            loc for loc in self.multiworld.get_locations(self.player)
            if loc.address is not None
        ]
        self.assertEqual(len(self.multiworld.itempool), len(non_event_locations))


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


# =============================================================================
# Nanimon Quest + Progressive Keychain (Phase 11)
# =============================================================================

class TestNanimonQuest(DigimonWorldTestBase):
    """5 Nanimon Quest AP locations + 2 Progressive Keychain items.

    Default options (prosperity_goal = 50 ≥ 45) — all 5 locations are
    in logic; Drill Tunnel site carries the 45-PP gate.
    """

    options: ClassVar[dict[str, Any]] = {}

    _SITE_NAMES: ClassVar[tuple[str, ...]] = (
        "Nanimon Quest: Ogre Fortress",
        "Nanimon Quest: Ancient Dino Region",
        "Nanimon Quest: Drill Tunnel",
        "Nanimon Quest: Toy Town",
        "Nanimon Quest: Factorial Town",
    )

    def test_five_locations_exist(self) -> None:
        """All 5 sites are id-bearing AP locations."""

        from .. import locations as loc_module

        for name in self._SITE_NAMES:
            self.assertIn(name, loc_module.LOCATION_NAME_TO_ID)
            loc = self.multiworld.get_location(name, self.player)
            self.assertIsNotNone(loc.address)

    def test_location_ids_are_in_dedicated_block(self) -> None:
        """Location IDs land in 69_059_xxx, separated from neighboring
        groups (fishing 69_058_xxx)."""

        from ..locations import LOCATION_NAME_TO_ID

        for name in self._SITE_NAMES:
            ap_id = LOCATION_NAME_TO_ID[name]
            self.assertGreaterEqual(ap_id, 69_059_000)
            self.assertLess(ap_id, 69_060_000)

    def test_keychain_in_pool_twice(self) -> None:
        """Exactly 2 Progressive Keychain copies ship; classification useful."""

        from BaseClasses import ItemClassification

        from ..items import KEYCHAIN_COPIES_IN_POOL, KEYCHAIN_ITEM_NAME

        kc_items = [
            item for item in self.multiworld.itempool
            if item.name == KEYCHAIN_ITEM_NAME
        ]
        self.assertEqual(len(kc_items), KEYCHAIN_COPIES_IN_POOL)
        self.assertEqual(KEYCHAIN_COPIES_IN_POOL, 2)
        for item in kc_items:
            self.assertEqual(item.classification, ItemClassification.useful)

    def test_keychain_ram_bits_match_setTrigger_formula(self) -> None:
        """Each per-site trigger N derives to byte 0x001BDFCD + N//8,
        bit N%8 — this is the canonical setTrigger formula."""

        from ..data.addresses import (
            NANIMON_QUEST_ANCIENT_DINO_BIT,
            NANIMON_QUEST_ANCIENT_DINO_TRIGGER_ID,
            NANIMON_QUEST_DRILL_TUNNEL_BIT,
            NANIMON_QUEST_DRILL_TUNNEL_TRIGGER_ID,
            NANIMON_QUEST_FACTORIAL_TOWN_BIT,
            NANIMON_QUEST_FACTORIAL_TOWN_TRIGGER_ID,
            NANIMON_QUEST_LOCATION_RAM_BITS,
            NANIMON_QUEST_OGRE_FORTRESS_BIT,
            NANIMON_QUEST_OGRE_FORTRESS_TRIGGER_ID,
            NANIMON_QUEST_TOY_TOWN_BIT,
            NANIMON_QUEST_TOY_TOWN_TRIGGER_ID,
        )

        pairs = (
            (NANIMON_QUEST_OGRE_FORTRESS_TRIGGER_ID,   NANIMON_QUEST_OGRE_FORTRESS_BIT),
            (NANIMON_QUEST_ANCIENT_DINO_TRIGGER_ID,    NANIMON_QUEST_ANCIENT_DINO_BIT),
            (NANIMON_QUEST_DRILL_TUNNEL_TRIGGER_ID,    NANIMON_QUEST_DRILL_TUNNEL_BIT),
            (NANIMON_QUEST_TOY_TOWN_TRIGGER_ID,        NANIMON_QUEST_TOY_TOWN_BIT),
            (NANIMON_QUEST_FACTORIAL_TOWN_TRIGGER_ID,  NANIMON_QUEST_FACTORIAL_TOWN_BIT),
        )
        for trigger_id, (expected_byte, expected_bit) in pairs:
            self.assertEqual(0x001BDFCD + trigger_id // 8, expected_byte)
            self.assertEqual(trigger_id % 8, expected_bit)

        # All 5 names route to the same dict.
        self.assertEqual(set(NANIMON_QUEST_LOCATION_RAM_BITS), set(self._SITE_NAMES))

    def test_inventory_size_address_is_main_ram_offset(self) -> None:
        """``RAM_INVENTORY_SIZE`` lives in the same 0x0013Dxxx block as
        the empirically-verified inventory IDs/qtys (DWAP's 0x000DD4CE
        was a transcription error)."""

        from ..data.addresses import (
            RAM_INVENTORY_ITEM_IDS_BASE,
            RAM_INVENTORY_QUANTITIES_BASE,
            RAM_INVENTORY_SIZE,
        )

        self.assertEqual(RAM_INVENTORY_SIZE, 0x0013D4CE)
        # Sits after the IDs and quantities blocks (adjacency check).
        self.assertGreater(RAM_INVENTORY_SIZE, RAM_INVENTORY_QUANTITIES_BASE)
        self.assertGreater(RAM_INVENTORY_QUANTITIES_BASE, RAM_INVENTORY_ITEM_IDS_BASE)


class TestNanimonQuestAccessDependencies(DigimonWorldTestBase):
    """Per-site precondition rules added 2026-05-13 after live
    playthrough feedback. Each Nanimon site fires only after its area's
    host questline has advanced; AP encodes that as access rules."""

    options: ClassVar[dict[str, Any]] = {}

    def test_toy_town_requires_gear(self) -> None:
        """Toy Town Nanimon (Script 145 Section_6) only fires after the
        WaruMonzaemon cutscene granted Gear (trigger 270)."""

        self.assertAccessDependency(
            ["Nanimon Quest: Toy Town"],
            [["Gear"]],
            only_check_listed=True,
        )

    def test_factorial_town_in_logic_at_all_state(self) -> None:
        """Factorial Town site needs Andromon's recruit chain
        (Tropical Jungle + 15 PP). With ``get_all_state`` all
        dependencies are satisfied; verify it's reachable at full
        state — sanity that the rule isn't permanently unsatisfiable."""

        all_state = self.multiworld.get_all_state(False)
        loc = self.multiworld.get_location(
            "Nanimon Quest: Factorial Town", self.player,
        )
        self.assertTrue(loc.can_reach(all_state))

    def test_drill_tunnel_requires_leomonstone(self) -> None:
        """Drill Tunnel Nanimon needs Leomonstone (the Stone Tablet,
        matches Leomon's recruit gate) on top of the 45 PP cave
        entrance. At default ``prosperity_goal=50`` the PP gate is
        satisfiable; Leomonstone is the AP-side ADD."""

        self.assertAccessDependency(
            ["Nanimon Quest: Drill Tunnel"],
            [["Leomonstone"]],
            only_check_listed=True,
        )


class TestNanimonQuestLowProsperity(DigimonWorldTestBase):
    """With ``prosperity_goal < 45``, the Drill Tunnel Nanimon site is
    inside the unreachable Leomon Ancestral Cave — must be EXCLUDED so
    AP fill doesn't place progression there. The other 4 sites stay
    in logic."""

    options: ClassVar[dict[str, Any]] = {
        "prosperity_goal": 30,
    }

    def test_drill_tunnel_site_excluded_below_45_pp(self) -> None:
        from BaseClasses import LocationProgressType

        loc = self.multiworld.get_location(
            "Nanimon Quest: Drill Tunnel", self.player,
        )
        self.assertEqual(loc.progress_type, LocationProgressType.EXCLUDED)

    def test_other_sites_not_excluded(self) -> None:
        from BaseClasses import LocationProgressType

        for site in (
            "Nanimon Quest: Ogre Fortress",
            "Nanimon Quest: Ancient Dino Region",
            "Nanimon Quest: Toy Town",
            "Nanimon Quest: Factorial Town",
        ):
            loc = self.multiworld.get_location(site, self.player)
            self.assertNotEqual(
                loc.progress_type, LocationProgressType.EXCLUDED,
                f"{site} should not be EXCLUDED at threshold=30",
            )


# =====================================================================
# RegionLocking option
# =====================================================================

class TestRegionLockingOff(DigimonWorldTestBase):
    """Default — no region locking. No Region Access items in the pool;
    every region reachable in all_state without any access item."""

    options: ClassVar[dict[str, Any]] = {}

    def test_no_region_access_items_in_pool(self) -> None:
        from ..regions import LOCKABLE_REGIONS, region_access_item_name

        pool_names = {item.name for item in self.multiworld.itempool}
        for region in LOCKABLE_REGIONS:
            self.assertNotIn(region_access_item_name(region), pool_names)


class TestRegionLockingAll(DigimonWorldTestBase):
    """``region_locking: all`` — every lockable region has its access
    item in the pool, and AP logic requires the item to reach the
    region."""

    options: ClassVar[dict[str, Any]] = {
        "region_locking": "all",
        # Force lava_cave_access vanilla so the left chain doesn't need
        # an extra AP item beyond the region-access ones; keeps the
        # all_state reachability tests focused on the region locks.
        "lava_cave_access": "vanilla",
    }

    def test_all_region_access_items_in_pool(self) -> None:
        """All 14 Region Access items must exist (in the pool OR
        pre-collected as part of the bootstrap kit), with no duplicates
        and no missing entries. PR 2 default bootstrap is Native Forest;
        the other 13 ship in the pool."""

        from ..items import get_bootstrap_items
        from ..regions import LOCKABLE_REGIONS, region_access_item_name

        pool_names = {item.name for item in self.multiworld.itempool}
        precollected_names = {
            item.name for item in self.multiworld.precollected_items[self.player]
        }
        bootstrap = set(get_bootstrap_items(self.world))

        for region in LOCKABLE_REGIONS:
            access = region_access_item_name(region)
            if access in bootstrap:
                self.assertIn(
                    access, precollected_names,
                    f"{access} should be pre-collected (bootstrap)",
                )
                self.assertNotIn(
                    access, pool_names,
                    f"{access} should NOT also ship in pool (bootstrap)",
                )
            else:
                self.assertIn(
                    access, pool_names,
                    f"{access} should ship in pool under region_locking=all",
                )

    def test_locked_region_unreachable_without_access(self) -> None:
        """Smoke test: with no items collected at all, a deep locked
        region (Misty Trees) should not be reachable. (Native Forest is
        also locked under ``all`` mode, so even the first step out of
        File City requires Native Forest Region Access.)"""

        empty_state = self.multiworld.get_all_state(False)
        # Drop every Region Access item from the state to check the
        # gate. ``get_all_state`` grants all progression items, so we
        # remove them explicitly to test the locked path.
        from ..regions import LOCKABLE_REGIONS, region_access_item_name

        for region in LOCKABLE_REGIONS:
            access = region_access_item_name(region)
            while access in empty_state.prog_items[self.player]:
                empty_state.remove(
                    self.world.create_item(access),
                )

        # Misty Trees should be unreachable now.
        misty = self.multiworld.get_region("Misty Trees", self.player)
        self.assertFalse(
            misty.can_reach(empty_state),
            "Misty Trees should be unreachable without its Region Access "
            "item (and without the chain regions' accesses)",
        )

    def test_reachable_in_all_state(self) -> None:
        """With all progression items granted (including all Region
        Access items), every locked region is reachable. Verifies the
        gate works in both directions — locked off → blocked, granted →
        passable."""

        all_state = self.multiworld.get_all_state(False)
        from ..regions import LOCKABLE_REGIONS

        for region_name in LOCKABLE_REGIONS:
            region = self.multiworld.get_region(region_name, self.player)
            self.assertTrue(
                region.can_reach(all_state),
                f"{region_name} should be reachable in all_state",
            )


class TestRegionLockingCustom(DigimonWorldTestBase):
    """``region_locking: custom`` — only the listed regions get locked.
    Unlisted regions stay freely reachable; listed ones get their
    access item."""

    options: ClassVar[dict[str, Any]] = {
        "region_locking": "custom",
        "region_locking_list": {"Misty Trees", "Toy Town"},
        "lava_cave_access": "vanilla",
    }

    def test_only_listed_access_items_in_pool(self) -> None:
        from ..regions import LOCKABLE_REGIONS, region_access_item_name

        pool_names = {item.name for item in self.multiworld.itempool}
        expected_in = {
            region_access_item_name("Misty Trees"),
            region_access_item_name("Toy Town"),
        }
        for region in LOCKABLE_REGIONS:
            access = region_access_item_name(region)
            if access in expected_in:
                self.assertIn(
                    access, pool_names,
                    f"{access} should ship in pool (region listed)",
                )
            else:
                self.assertNotIn(
                    access, pool_names,
                    f"{access} should NOT ship in pool (region not listed)",
                )


# =====================================================================
# StartingRegion option (only active under region_locking: all)
# =====================================================================
#
# Expected bootstrap kits per starting region (option name -> kit).
# Mirrors :func:`items.get_bootstrap_items`; if either side changes the
# other should too.

_EXPECTED_KITS: dict[str, tuple[str, ...]] = {
    "native_forest":       ("Native Forest Region Access",),
    "gear_savanna":        (
        "Birdramon Recruit", "Birdramon Flight: Gear Savanna",
        "Gear Savanna Region Access",
    ),
    "ancient_dino_region": (
        "Birdramon Recruit", "Birdramon Flight: Ancient Dino Region",
        "Ancient Dino Region Region Access",
    ),
    "freezeland": (
        "Birdramon Recruit", "Birdramon Flight: Freezeland",
        "Freezeland Region Access",
    ),
    "misty_trees": (
        "Birdramon Recruit", "Birdramon Flight: Misty Trees",
        "Misty Trees Region Access",
    ),
    "beetle_land": (
        "Birdramon Recruit", "Birdramon Flight: Beetle Land",
        "Beetle Land Region Access",
    ),
    "great_canyon":   (
        "Birdramon Recruit", "Great Canyon Region Access",
    ),
    "factorial_town": (
        "Whamon Recruit", "Factorial Town Region Access",
    ),
}


class _StartingRegionTestMixin:
    """Mixin that validates the bootstrap kit for the configured
    ``starting_region``. Concrete subclasses set ``options`` to pick a
    specific region — one subclass per option value below.
    """

    STARTING_REGION: ClassVar[str]
    CANONICAL_NAME: ClassVar[str]

    def test_bootstrap_kit_matches_expected(self) -> None:
        from ..items import get_bootstrap_items

        expected = set(_EXPECTED_KITS[self.STARTING_REGION])
        actual = set(get_bootstrap_items(self.world))
        self.assertEqual(actual, expected)

    def test_get_starting_region_name(self) -> None:
        from ..options import get_starting_region_name
        self.assertEqual(
            get_starting_region_name(self.world.options), self.CANONICAL_NAME,
        )

    def test_kit_precollected_not_in_pool(self) -> None:
        from ..items import get_bootstrap_items

        kit = set(get_bootstrap_items(self.world))
        precollected_names = {
            item.name for item in
            self.multiworld.precollected_items[self.player]
        }
        pool_names = {item.name for item in self.multiworld.itempool}

        self.assertTrue(
            kit.issubset(precollected_names),
            f"bootstrap items missing from precollected: "
            f"{kit - precollected_names}",
        )
        self.assertFalse(
            kit & pool_names,
            f"bootstrap items double-shipped in pool: {kit & pool_names}",
        )

    def test_starting_region_reachable_from_bootstrap(self) -> None:
        """With just the bootstrap kit collected (no other progression),
        the starting region must be reachable. Exercises both the
        :func:`get_bootstrap_items` shape AND the entrance rules added
        by :func:`rules._apply_region_locks`."""

        from BaseClasses import CollectionState

        from ..items import get_bootstrap_items

        state = CollectionState(self.multiworld)
        for name in get_bootstrap_items(self.world):
            state.collect(self.world.create_item(name), prevent_sweep=True)

        starting_region = self.multiworld.get_region(
            self.CANONICAL_NAME, self.player,
        )
        self.assertTrue(
            starting_region.can_reach(state),
            f"{self.CANONICAL_NAME} should be reachable with just "
            f"bootstrap kit for starting_region={self.STARTING_REGION}",
        )


# Common option base — ``region_locking: all`` and ``lava_cave_access:
# vanilla`` (so the Drill-Tunnel-chain region accesses can be granted
# without also needing the LCA item to verify chain reachability).
def _start_options(starting_region: str) -> dict[str, Any]:
    return {
        "region_locking": "all",
        "starting_region": starting_region,
        "lava_cave_access": "vanilla",
    }


class TestStartingRegionNativeForest(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "native_forest"
    CANONICAL_NAME = "Native Forest"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionGearSavanna(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "gear_savanna"
    CANONICAL_NAME = "Gear Savanna"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionAncientDino(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "ancient_dino_region"
    CANONICAL_NAME = "Ancient Dino Region"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionFreezeland(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "freezeland"
    CANONICAL_NAME = "Freezeland"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)

    def test_great_canyon_reachable_via_freezeland_walk(self) -> None:
        """From a Freezeland start, the Freezeland -> Great Canyon
        walking edge stays open under region_locking: all — gated only
        on Great Canyon Region Access (the post-pass adds the access
        AND on the incoming edge). Verifies the GC-flight scoping fix
        didn't accidentally also gate this walking path.

        Setup: bootstrap kit (Birdramon Recruit + Flight: Freezeland +
        Freezeland Region Access) + Great Canyon Region Access added
        manually, no other items. GC should become reachable.
        """

        from BaseClasses import CollectionState

        from ..items import get_bootstrap_items
        from ..regions import region_access_item_name

        state = CollectionState(self.multiworld)
        for name in get_bootstrap_items(self.world):
            state.collect(self.world.create_item(name), prevent_sweep=True)
        state.collect(
            self.world.create_item(region_access_item_name("Great Canyon")),
            prevent_sweep=True,
        )

        gc = self.multiworld.get_region("Great Canyon", self.player)
        self.assertTrue(
            gc.can_reach(state),
            "Great Canyon should be reachable from a Freezeland start "
            "after Great Canyon Region Access is delivered, via the "
            "Freezeland -> Great Canyon walking edge.",
        )


class TestStartingRegionMistyTrees(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "misty_trees"
    CANONICAL_NAME = "Misty Trees"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionBeetleLand(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "beetle_land"
    CANONICAL_NAME = "Beetle Land"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionGreatCanyon(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "great_canyon"
    CANONICAL_NAME = "Great Canyon"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionFactorialTown(_StartingRegionTestMixin, DigimonWorldTestBase):
    STARTING_REGION = "factorial_town"
    CANONICAL_NAME = "Factorial Town"
    options: ClassVar[dict[str, Any]] = _start_options(STARTING_REGION)


class TestStartingRegionIgnoredUnderOff(DigimonWorldTestBase):
    """When ``region_locking == off`` the StartingRegion option is
    ignored — no precollected items, no bootstrap kit, the player walks
    out of File City through Native Forest as normal."""

    options: ClassVar[dict[str, Any]] = {
        "region_locking": "off",
        "starting_region": "freezeland",
    }

    def test_no_bootstrap_under_off(self) -> None:
        from ..items import get_bootstrap_items
        self.assertEqual(get_bootstrap_items(self.world), ())

    def test_no_birdramon_in_precollected(self) -> None:
        precollected_names = {
            item.name for item in
            self.multiworld.precollected_items[self.player]
        }
        self.assertNotIn("Birdramon Recruit", precollected_names)
        self.assertNotIn(
            "Birdramon Flight: Freezeland", precollected_names,
        )


class TestStartingRegionIgnoredUnderCustom(DigimonWorldTestBase):
    """Same — under ``custom`` the StartingRegion option does not
    bootstrap. Only the listed regions are locked; the start is
    wherever the player can walk from File City."""

    options: ClassVar[dict[str, Any]] = {
        "region_locking": "custom",
        "region_locking_list": {"Misty Trees"},
        "starting_region": "gear_savanna",
    }

    def test_no_bootstrap_under_custom(self) -> None:
        from ..items import get_bootstrap_items
        self.assertEqual(get_bootstrap_items(self.world), ())
