"""Logic regressions from the 2026-09-07 playtest report.

* Great Canyon locked: the G Canyon Top flight (Birdramon Recruit + Great
  Canyon Region Access) is the modeled entry; unlocked seeds keep the edge
  out of logic (the slot reads Birdramon's vanilla field-recruit bit).
* The ``factorial_gate`` door pair is connected outside ``regions._EDGES``;
  the region-lock pass must still AND the Region Access terms on it.
* Andromon's recruit chain is internal to Factorial Town (scripts
  151/154/180) — no Tropical Jungle / restaurant / 15 PP dependency; same
  for the sewer Nanimon site.
* Merit-priced rows (Amazing Rod Pickup + the Merit Shop rows) need a card
  vending machine in reach — Geko Swamp alone is not enough.
"""

from typing import Any, ClassVar

from ..data.addresses import MERIT_SHOP_LOCATION_NAMES
from ..locations import RECRUIT_PP_REQUIREMENTS
from .bases import DigimonWorldTestBase

_GC_FLIGHT = "File City to Great Canyon"


class TestGreatCanyonFlightLocked(DigimonWorldTestBase):
    # The generic fill test fails ~10 % of seeds under ``region_locking: all``
    # (sphere-1 starvation, pre-existing — measured 2026-09-07 on the old and
    # the new rules alike, STATUS.md §2.5); these classes test rules only.
    run_default_tests = False
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "all",
        "great_canyon_unlock": "shuffled",
    }

    def test_flight_edge_needs_birdramon_and_access(self) -> None:
        self.collect_all_but(["Birdramon Recruit", "Great Canyon Region Access"])
        self.assertFalse(self.can_reach_entrance(_GC_FLIGHT))
        self.collect_by_name("Birdramon Recruit")
        self.assertFalse(self.can_reach_entrance(_GC_FLIGHT))
        self.collect_by_name("Great Canyon Region Access")
        self.assertTrue(self.can_reach_entrance(_GC_FLIGHT))

    def test_flight_is_an_entry_without_the_bridge(self) -> None:
        # No bridge, no other flight that walks back into Great Canyon
        # (Freezeland / Misty Trees), no left-chain walk to Misty Trees
        # (Gear Savanna locked): the flight is the only way in.
        self.collect_all_but([
            "Great Canyon Bridge", "Birdramon Flight: Freezeland", "Birdramon Flight: Misty Trees",
            "Gear Savanna Region Access", "Great Canyon Region Access",
        ])
        self.assertFalse(self.can_reach_region("Great Canyon"))
        self.collect_by_name("Great Canyon Region Access")
        self.assertTrue(self.can_reach_region("Great Canyon"))
        state = self.multiworld.state
        inside = [
            loc for loc in self.multiworld.get_reachable_locations(state, self.player)
            if loc.parent_region.name == "Great Canyon"
        ]
        self.assertTrue(inside, "nothing inside Great Canyon came into logic through the flight")


class TestGreatCanyonFlightUnlocked(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"great_canyon_unlock": "shuffled"}

    def test_flight_edge_stays_out_of_logic(self) -> None:
        all_state = self.multiworld.get_all_state(False)
        entrance = self.multiworld.get_entrance(_GC_FLIGHT, self.player)
        self.assertFalse(entrance.can_reach(all_state))
        # ... while the bridge still opens the region.
        self.assertTrue(self.multiworld.get_region("Great Canyon", self.player).can_reach(all_state))


class TestFactorialDoorUnderRegionLocking(DigimonWorldTestBase):
    # The generic fill test fails ~10 % of seeds under ``region_locking: all``
    # (sphere-1 starvation, pre-existing — measured 2026-09-07 on the old and
    # the new rules alike, STATUS.md §2.5); these classes test rules only.
    run_default_tests = False
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "all",
        "factorial_gate": "always_open",
    }

    def test_door_out_needs_gear_savanna_access(self) -> None:
        self.collect_all_but(["Gear Savanna Region Access"])
        self.assertTrue(self.can_reach_region("Factorial Town"))
        self.assertFalse(self.can_reach_entrance("Factorial Town to Gear Savanna"))
        self.assertFalse(self.can_reach_region("Gear Savanna"))
        self.collect_by_name("Gear Savanna Region Access")
        self.assertTrue(self.can_reach_entrance("Factorial Town to Gear Savanna"))

    def test_door_in_needs_factorial_town_access(self) -> None:
        self.collect_all_but(["Factorial Town Region Access"])
        self.assertTrue(self.can_reach_region("Gear Savanna"))
        self.assertFalse(self.can_reach_entrance("Gear Savanna to Factorial Town"))
        self.assertFalse(self.can_reach_region("Factorial Town"))
        self.collect_by_name("Factorial Town Region Access")
        self.assertTrue(self.can_reach_entrance("Gear Savanna to Factorial Town"))


class TestAndromonChainIsLocal(DigimonWorldTestBase):
    # The generic fill test fails ~10 % of seeds under ``region_locking: all``
    # (sphere-1 starvation, pre-existing — measured 2026-09-07 on the old and
    # the new rules alike, STATUS.md §2.5); these classes test rules only.
    run_default_tests = False
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "all",
        "bridge_unlock": "shuffled",
        "lava_cave_access": "shuffled",
    }

    def test_no_prosperity_gate(self) -> None:
        self.assertEqual(RECRUIT_PP_REQUIREMENTS["Andromon"], 0)

    def test_andromon_and_sewer_nanimon_need_only_factorial_town(self) -> None:
        self.collect_all_but([
            "Tropical Jungle Region Access", "Tropical Jungle Bridge",
            "Ancient Dino Region Region Access", "Birdramon Flight: Ancient Dino Region",
            "Lava Cave Access", "Prosperity Point",
        ])
        self.assertFalse(self.can_reach_region("Tropical Jungle"))
        self.assertFalse(self.can_reach_region("Meramon Tunnel"))
        self.assertTrue(self.can_reach_location("Andromon"))
        self.assertTrue(self.can_reach_location("Nanimon Quest: Factorial Town"))

    def test_still_gated_on_factorial_town(self) -> None:
        self.collect_all_but(["Whamon Recruit", "Factorial Town Region Access"])
        self.assertFalse(self.can_reach_location("Andromon"))
        self.assertFalse(self.can_reach_location("Nanimon Quest: Factorial Town"))


class TestMeritRowsNeedCards(DigimonWorldTestBase):
    # The generic fill test fails ~10 % of seeds under ``region_locking: all``
    # (sphere-1 starvation, pre-existing — measured 2026-09-07 on the old and
    # the new rules alike, STATUS.md §2.5); these classes test rules only.
    run_default_tests = False
    options: ClassVar[dict[str, Any]] = {
        "region_locking": "all",
        "merit_shop_locations": "coexist",
    }

    def test_geko_swamp_alone_is_not_enough(self) -> None:
        # Geko Swamp via Birdramon Flight: Misty Trees and the walk back;
        # neither card machine (Gear Savanna locked, File City shop < T2).
        self.collect_all_but(["Gear Savanna Region Access", "Progressive Item Shop"])
        self.assertTrue(self.can_reach_region("Geko Swamp"))
        self.assertFalse(self.can_reach_region("Card Vending"))
        self.assertFalse(self.can_reach_location("Amazing Rod Pickup"))
        for name in MERIT_SHOP_LOCATION_NAMES:
            self.assertFalse(self.can_reach_location(name), name)
        self.collect_by_name("Gear Savanna Region Access")
        self.assertTrue(self.can_reach_location("Amazing Rod Pickup"))
        for name in MERIT_SHOP_LOCATION_NAMES:
            self.assertTrue(self.can_reach_location(name), name)

    def test_file_city_machine_counts_too(self) -> None:
        self.collect_all_but(["Gear Savanna Region Access"])
        self.assertTrue(self.can_reach_region("Card Vending"))
        self.assertTrue(self.can_reach_location("Amazing Rod Pickup"))
