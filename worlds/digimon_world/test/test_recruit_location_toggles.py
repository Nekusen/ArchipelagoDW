"""Tests for the Frigimon / Mojyamon recruit-location opt-out toggles.

Both options default ON (previous seeds unchanged); turning one OFF
removes ONLY that recruit's AP location. Item-side delivery must be
untouched: Frigimon rides ``Progressive Restaurant`` T2 and Mojyamon
``Progressive Secret Shop`` T1 (see
:data:`worlds.digimon_world.items.PROGRESSIVE_BUNDLES`), and those
Progressive ladders must keep their full copy counts in the pool
regardless of the toggles.
"""

from __future__ import annotations

from typing import Any, ClassVar

from ..items import PROGRESSIVE_BUNDLES
from .bases import DigimonWorldTestBase

# Vanilla bundle tier counts — the delivery-side invariant the toggles
# must never disturb.
_RESTAURANT_TIERS = len(PROGRESSIVE_BUNDLES["Progressive Restaurant"])
_SECRET_SHOP_TIERS = len(PROGRESSIVE_BUNDLES["Progressive Secret Shop"])


class _ToggleAssertionsMixin:
    """Shared assertion helpers. A plain mixin (NOT a TestCase) so the
    test runner doesn't collect it as a fifth, redundant run of the
    WorldTestBase default battery."""

    def _assert_location_present(self: DigimonWorldTestBase, name: str) -> None:
        location = self.world.get_location(name)
        self.assertEqual(location.parent_region.name, "Freezeland")

    def _assert_location_absent(self: DigimonWorldTestBase, name: str) -> None:
        with self.assertRaises(KeyError):
            self.world.get_location(name)

    def _assert_pool_matches_locations(self: DigimonWorldTestBase) -> None:
        """Itempool size tracks the (possibly shrunken) location count."""

        self.assertEqual(
            len(self.multiworld.itempool),
            len(self.multiworld.get_unfilled_locations(self.player)),
        )

    def _assert_delivery_untouched(self: DigimonWorldTestBase) -> None:
        """The Progressive bundles that carry the two recruits' city
        delivery keep their full tier counts in the pool."""

        pool_names = [item.name for item in self.multiworld.itempool]
        self.assertEqual(
            pool_names.count("Progressive Restaurant"), _RESTAURANT_TIERS,
        )
        self.assertEqual(
            pool_names.count("Progressive Secret Shop"), _SECRET_SHOP_TIERS,
        )


class TestRecruitTogglesDefaultOn(_ToggleAssertionsMixin, DigimonWorldTestBase):
    """Defaults: both locations exist — identical to pre-toggle seeds."""

    options: ClassVar[dict[str, Any]] = {}

    def test_both_locations_present(self) -> None:
        self._assert_location_present("Frigimon")
        self._assert_location_present("Mojyamon")

    def test_pool_and_delivery(self) -> None:
        self._assert_pool_matches_locations()
        self._assert_delivery_untouched()


class TestFrigimonLocationOff(_ToggleAssertionsMixin, DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"frigimon_recruit_location": False}

    def test_frigimon_absent_mojyamon_present(self) -> None:
        self._assert_location_absent("Frigimon")
        self._assert_location_present("Mojyamon")

    def test_pool_and_delivery(self) -> None:
        self._assert_pool_matches_locations()
        self._assert_delivery_untouched()


class TestMojyamonLocationOff(_ToggleAssertionsMixin, DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {"mojyamon_recruit_location": False}

    def test_mojyamon_absent_frigimon_present(self) -> None:
        self._assert_location_absent("Mojyamon")
        self._assert_location_present("Frigimon")

    def test_pool_and_delivery(self) -> None:
        self._assert_pool_matches_locations()
        self._assert_delivery_untouched()


class TestBothRecruitLocationsOff(_ToggleAssertionsMixin, DigimonWorldTestBase):
    options: ClassVar[dict[str, Any]] = {
        "frigimon_recruit_location": False,
        "mojyamon_recruit_location": False,
    }

    def test_both_locations_absent(self) -> None:
        self._assert_location_absent("Frigimon")
        self._assert_location_absent("Mojyamon")

    def test_other_freezeland_recruits_survive(self) -> None:
        for name in ("Penguinmon", "Garurumon", "Angemon", "Whamon"):
            self._assert_location_present(name)

    def test_pool_and_delivery(self) -> None:
        self._assert_pool_matches_locations()
        self._assert_delivery_untouched()


# =============================================================================
# Coelamon restoration (2026-08-22)
# =============================================================================


class TestCoelamonLocationRestored(DigimonWorldTestBase):
    """Coelamon's recruit AP location is back (dropped 2026-05-24 over
    the shore-cutscene loop; the ROM now remaps the shore state machine
    to its own trigger 779 — see addresses.py
    ``ROM_COELAMON_CUTSCENE_REMAP_*``). Item-side nothing changes: he
    stays a bundled recruit (city visibility rides ``Progressive Item
    Shop`` T1; no standalone ``Coelamon Recruit`` item)."""

    options: ClassVar[dict[str, Any]] = {}

    def test_location_exists_in_native_forest(self) -> None:
        location = self.world.get_location("Coelamon")
        self.assertEqual(location.parent_region.name, "Native Forest")

    def test_no_standalone_recruit_item(self) -> None:
        pool_names = [item.name for item in self.multiworld.itempool]
        self.assertNotIn("Coelamon Recruit", pool_names)
        self.assertEqual(
            pool_names.count("Progressive Item Shop"),
            len(PROGRESSIVE_BUNDLES["Progressive Item Shop"]),
        )

    def test_reachable_without_bridge_item_in_always_open(self) -> None:
        # bridge_unlock defaults to always_open: trigger 185 is pinned
        # from the start, so the shore cutscene needs no AP item.
        state = self.multiworld.get_all_state(False)
        self.assertTrue(self.world.get_location("Coelamon").can_reach(state))


class TestCoelamonBridgeShuffledLogic(DigimonWorldTestBase):
    """bridge_unlock = shuffled: the shore gate reads trigger 185 and
    the take-across ferry is closed, so the recruit cutscene — and with
    it the AP location — is only reachable after the ``Tropical Jungle
    Bridge`` item is delivered."""

    options: ClassVar[dict[str, Any]] = {"bridge_unlock": 2}

    def test_coelamon_requires_bridge_item(self) -> None:
        self.assertAccessDependency(
            ["Coelamon"],
            [["Tropical Jungle Bridge"]],
            only_check_listed=True,
        )
