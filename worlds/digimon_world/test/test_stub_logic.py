"""Phase 2 logic tests for the Digimon World 1 APWorld.

These checks complement the generic suite in :mod:`test.general` by
asserting v1-specific invariants that come straight from the rule
cluster in :mod:`worlds.digimon_world.rules`. They are written against
the DWAP-baseline transcription documented in
``references/dw1_recruitment_logic.md`` §B; if Phase 2's verification
work updates the rules, these tests should move with them.
"""

from typing import Any, ClassVar

from .bases import DigimonWorldTestBase


class TestPhase2Logic(DigimonWorldTestBase):
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

    # ------------------------------------------------------------------
    # Region gating
    # ------------------------------------------------------------------

    def test_fishing_rod_gates_greatlake(self) -> None:
        """Without a fishing rod, Greatlake (Seadramon) is unreachable."""

        self.assertAccessDependency(
            ["Seadramon", "Whamon"],
            [["old fishrod"], ["Amazing rod"]],
            only_check_listed=True,
        )

    def test_seadramon_gates_beetle_land(self) -> None:
        """Beetle Land recruits need Seadramon-soul."""

        self.assertAccessDependency(
            ["Kabuterimon", "Kuwagamon"],
            [["Seadramon Soul", "old fishrod", "Kabuterimon Soul", "Kuwagamon Soul"]],
            only_check_listed=True,
        )

    def test_gear_gates_drill_tunnel(self) -> None:
        """Drimogemon's Drill Tunnel needs the Gear key item."""

        self.assertAccessDependency(
            ["Drimogemon"],
            [["Gear", "Meramon Soul", "Drimogemon Soul",
              "Coelamon Soul"]],
            only_check_listed=True,
        )

    # ------------------------------------------------------------------
    # Recruit graph gating (DWAP-baseline)
    # ------------------------------------------------------------------

    def test_meramon_requires_coelamon_or_betamon(self) -> None:
        """DWAP §B: Meramon needs Agumon AND ≥1 statcap (skipped in v1) AND
        (Coelamon OR Betamon). v1 tests the Coelamon/Betamon disjunction."""

        self.assertAccessDependency(
            ["Meramon"],
            [["Meramon Soul", "Coelamon Soul"], ["Meramon Soul", "Betamon Soul"]],
            only_check_listed=True,
        )

    def test_whamon_chain_for_andromon(self) -> None:
        """Andromon needs Whamon + Numemon souls (DWAP)."""

        self.assertAccessDependency(
            ["Andromon"],
            [["Andromon Soul", "Whamon Soul", "Numemon Soul",
              "Seadramon Soul", "old fishrod"]],
            only_check_listed=True,
        )

    def test_nanimon_recruit_chain(self) -> None:
        """Nanimon needs Numemon + Leomon + Tyrannomon souls (DWAP)."""

        self.assertAccessDependency(
            ["Nanimon"],
            [["Nanimon Soul", "Numemon Soul", "Leomon Soul", "Tyrannomon Soul",
              "Whamon Soul", "Seadramon Soul", "old fishrod",
              "Centarumon Soul", "Meramon Soul", "Coelamon Soul",
              "Mansion Key"]],
            only_check_listed=True,
        )

    # ------------------------------------------------------------------
    # Endgame
    # ------------------------------------------------------------------

    def test_final_battle_requires_as_decoder(self) -> None:
        """Final Battle event needs the AS Decoder key item."""

        self.assertAccessDependency(
            ["Final Battle"],
            [["AS Decoder"]],
            only_check_listed=True,
        )
