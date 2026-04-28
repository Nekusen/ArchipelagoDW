"""Access rules for the Digimon World 1 APWorld (Phase 4 v7).

Recruit AP locations have no logical prereqs — every recruit location
is treated as logically reachable. The player has to traverse the world
in-game the long way around, but AP fill won't gate progression items
behind recruit-chain prereqs that the world model doesn't track.

What this module sets:

* The completion condition: Final Battle requires AS Decoder + 50
  ``Prosperity Point`` items. ``Prosperity Point`` is a real AP item in
  v7 (50 copies in the pool); the in-game prosperity counter is
  enforced client-side from the count of received items.

* No per-location prereqs beyond Final Battle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rule_builder.rules import Has

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


PROSPERITY_ITEM_NAME = "Prosperity Point"


def set_all_rules(world: DigimonWorldWorld) -> None:
    _set_completion_condition(world)


def _set_completion_condition(world: DigimonWorldWorld) -> None:
    """Final Battle requires AS Decoder + 50 Prosperity Points; the
    Victory event is the AP win condition."""

    final_battle = world.get_location("Final Battle")
    world.set_rule(
        final_battle,
        Has("AS Decoder") & Has(PROSPERITY_ITEM_NAME, count=50),
    )
    world.set_completion_rule(Has("Victory"))


__all__ = ["PROSPERITY_ITEM_NAME", "set_all_rules"]
