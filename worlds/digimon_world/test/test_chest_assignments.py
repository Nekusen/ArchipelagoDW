"""Tests for the per-chest grant decision (Phase 5 piece A).

Exercise :func:`worlds.digimon_world.chest_assignments.build_chest_grants`
under the three relevant scenarios:

* AP placed an own-slot, DW1-representable item at the chest -> chest
  spawns the real DW1 item (vanilla flow); ``vanilla_grant`` is True.
* AP placed an own-slot AP-only item (3000-block: bits, prosperity)
  at the chest -> chest spawns the sentinel ID; ``vanilla_grant`` is False.
* AP placed another player's item at the chest -> chest spawns the
  sentinel ID; ``vanilla_grant`` is False.

All three paths route correctly without further fill plumbing because
the test forges :class:`Location.item` directly. This bypasses the AP
fill algorithm but exercises the only thing
:func:`build_chest_grants` actually depends on.
"""

from typing import Any, ClassVar

from BaseClasses import Item, ItemClassification

from .. import chest_assignments
from ..data.addresses import AP_CHEST_SENTINEL_ITEM_ID
from ..items import DigimonWorldItem, dw1_internal_item_id
from .bases import DigimonWorldTestBase


def _force_place(world: Any, chest_name: str, item: Item) -> None:
    """Bypass fill — set a chest's ``Location.item`` directly."""

    location = world.get_location(chest_name)
    location.item = item
    location.event = item.advancement


class TestChestGrants(DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {}
    run_default_tests = False  # keep this test class focused

    def test_own_2000_block_item_grants_directly(self) -> None:
        # Place "Meat" (dw_code 2038 -> dw1_id 38) at a chest.
        meat = DigimonWorldItem(
            "Meat", ItemClassification.filler,
            self.world.item_name_to_id["Meat"], self.world.player,
        )
        _force_place(self.world, "Chest: Grey Lord's Mansion 1", meat)

        grants = chest_assignments.build_chest_grants(self.world)
        grant = grants["Chest: Grey Lord's Mansion 1"]

        self.assertTrue(grant.vanilla_grant)
        self.assertEqual(grant.item_byte, dw1_internal_item_id("Meat"))
        self.assertEqual(grant.item_byte, 38)

    def test_own_3000_block_item_uses_sentinel(self) -> None:
        # Prosperity Point (dw_code 3003) has no DW1 internal id.
        pp = DigimonWorldItem(
            "Prosperity Point", ItemClassification.progression,
            self.world.item_name_to_id["Prosperity Point"], self.world.player,
        )
        _force_place(self.world, "Chest: Grey Lord's Mansion 1", pp)

        grants = chest_assignments.build_chest_grants(self.world)
        grant = grants["Chest: Grey Lord's Mansion 1"]

        self.assertFalse(grant.vanilla_grant)
        self.assertEqual(grant.item_byte, AP_CHEST_SENTINEL_ITEM_ID)

    def test_other_player_item_uses_sentinel(self) -> None:
        # Foreign item: a DW1-named "Meat" but owned by player 99.
        foreign = DigimonWorldItem(
            "Meat", ItemClassification.filler,
            self.world.item_name_to_id["Meat"], 99,
        )
        _force_place(self.world, "Chest: Grey Lord's Mansion 1", foreign)

        grants = chest_assignments.build_chest_grants(self.world)
        grant = grants["Chest: Grey Lord's Mansion 1"]

        self.assertFalse(grant.vanilla_grant)
        self.assertEqual(grant.item_byte, AP_CHEST_SENTINEL_ITEM_ID)

    def test_unfilled_chest_defaults_to_sentinel(self) -> None:
        # No fill, no manual placement -> location.item is None.
        grants = chest_assignments.build_chest_grants(self.world)
        for grant in grants.values():
            self.assertFalse(grant.vanilla_grant)
            self.assertEqual(grant.item_byte, AP_CHEST_SENTINEL_ITEM_ID)
        self.assertEqual(len(grants), 63)
