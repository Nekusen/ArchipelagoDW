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

    def test_no_recruit_items(self) -> None:
        """No ``X Recruit`` items ship in v7."""

        from ..items import ITEM_NAME_TO_ID
        for name in ITEM_NAME_TO_ID:
            self.assertFalse(
                name.endswith(" Recruit"),
                f"{name} should not exist in v7",
            )

    def test_prosperity_point_in_pool(self) -> None:
        """Prosperity Point is shipped in the pool."""

        from ..items import PROSPERITY_POINT_COUNT, PROSPERITY_POINT_NAME

        pp_items = [
            item for item in self.multiworld.itempool
            if item.name == PROSPERITY_POINT_NAME
        ]
        self.assertEqual(len(pp_items), PROSPERITY_POINT_COUNT)

    # ------------------------------------------------------------------
    # Recruit shuffle
    # ------------------------------------------------------------------

    def test_recruit_remap_covers_shuffleable(self) -> None:
        """Closed shuffle covers every shuffleable Digimon, with values
        also drawn from the same set."""

        from ..data.addresses import SHUFFLE_INCLUDED_RECRUITS

        remap = self.world.recruit_remap
        self.assertEqual(set(remap.keys()), set(SHUFFLE_INCLUDED_RECRUITS))
        for partner in remap.values():
            self.assertIn(partner, SHUFFLE_INCLUDED_RECRUITS)

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
