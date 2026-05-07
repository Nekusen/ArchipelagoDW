"""Logic tests for the Digimon World 1 APWorld (Phase 4 v7).

Recruits are AP locations again (50 spawn-point checks) but no longer
ship as items. ``Prosperity Point`` is the only recruit-progression-
adjacent AP item; 50 copies fill the 50-PP goal gate.

Tests:

* Item-pool / location-count balance.
* Recruit AP locations exist for all 50 Digimon.
* No ``X Recruit`` items in the pool.
* Final-Battle endgame requires AS Decoder + 50 Prosperity Points.
* The closed-shuffle ``recruit_remap`` is shaped right.
"""

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
        """Phase 6: 48 ``X Recruit`` items ship (everyone except Agumon
        and Digitamamon — both intentionally not in the AP pool)."""

        from ..data.addresses import AP_RECRUIT_ITEM_DIGIMON
        from ..items import ITEM_NAME_TO_ID

        recruit_names = [n for n in ITEM_NAME_TO_ID if n.endswith(" Recruit")]
        self.assertEqual(len(recruit_names), 48, recruit_names)
        self.assertNotIn("Agumon Recruit", ITEM_NAME_TO_ID)
        self.assertNotIn("Digitamamon Recruit", ITEM_NAME_TO_ID)
        for digimon in AP_RECRUIT_ITEM_DIGIMON:
            self.assertIn(f"{digimon} Recruit", ITEM_NAME_TO_ID)

    def test_prosperity_point_in_pool(self) -> None:
        """Phase 5 piece C: 25 Prosperity Point items in the pool, each
        worth ``PROSPERITY_PER_ITEM`` (= 2) PP at delivery."""

        from ..items import (
            PROSPERITY_PER_ITEM,
            PROSPERITY_POINT_COUNT,
            PROSPERITY_POINT_NAME,
        )

        pp_items = [
            item for item in self.multiworld.itempool
            if item.name == PROSPERITY_POINT_NAME
        ]
        self.assertEqual(len(pp_items), PROSPERITY_POINT_COUNT)
        # Total PP shipped should match the goal threshold (50).
        self.assertEqual(PROSPERITY_POINT_COUNT * PROSPERITY_PER_ITEM, 50)

    # ------------------------------------------------------------------
    # Endgame
    # ------------------------------------------------------------------

    def test_final_battle_requires_as_decoder_and_pp(self) -> None:
        """Final Battle event needs AS Decoder + 50 Prosperity Points."""

        self.assertAccessDependency(
            ["Final Battle"],
            [["AS Decoder", "Prosperity Point"]],
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

    options: ClassVar[dict[str, Any]] = {"vending_locations": True}

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

    def test_textbox_fits_within_slot(self) -> None:
        from ..data.addresses import build_vending_textbox

        # "Quest!" + null-terminator at content time → 1A 00 [Quest!] 0D 00.
        # Fullwidth Quest! = 12 bytes; opcode = 2; CR/null = 2 → 16 bytes
        # of payload. Padded to 38.
        payload = build_vending_textbox("Quest!", 38)
        self.assertEqual(len(payload), 38)
        self.assertEqual(payload[:2], b"\x1A\x00")  # showTextbox opcode
        # 12 fullwidth bytes for "Quest!" + 2 bytes CR/null.
        self.assertIn(b"\x82\x70", payload)  # fullwidth 'Q'

    def test_textbox_overflow_raises(self) -> None:
        from ..data.addresses import build_vending_textbox

        # Force overflow: a 100-char content cannot fit in a 24-byte slot.
        with self.assertRaises(ValueError):
            build_vending_textbox("X" * 100, 24)


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

    options: ClassVar[dict[str, Any]] = {"recruit_randomization": False}

    def test_each_recruit_self_locked(self) -> None:
        from ..data.addresses import AP_RECRUIT_ITEM_DIGIMON

        for digimon in AP_RECRUIT_ITEM_DIGIMON:
            location = self.multiworld.get_location(digimon, self.player)
            self.assertIsNotNone(
                location.item, f"{digimon} location should be pre-filled",
            )
            self.assertEqual(
                location.item.name, f"{digimon} Recruit",
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
