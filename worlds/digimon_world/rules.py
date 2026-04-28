"""Access rules for the Digimon World 1 APWorld (Phase 5).

Per-recruit Prosperity Point gates are sourced from
:data:`worlds.digimon_world.locations.RECRUIT_PP_REQUIREMENTS`. Recruits
not in the map (Mamemon, MetalGreymon) intentionally receive no rule —
the user will assign their gate later. Recruits at 0 PP also receive
no rule (always logically reachable from their region).

Final Battle stays at AS Decoder + 50 Prosperity Points.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rule_builder.rules import Has

from .locations import RECRUIT_PP_REQUIREMENTS

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


PROSPERITY_ITEM_NAME = "Prosperity Point"


def set_all_rules(world: DigimonWorldWorld) -> None:
    _set_recruit_rules(world)
    _set_completion_condition(world)


def _set_recruit_rules(world: DigimonWorldWorld) -> None:
    """Attach the user-supplied PP gate to each recruit AP location.

    Recruits with a 0-PP gate are skipped (no rule = always reachable).
    """

    for recruit_name, pp in RECRUIT_PP_REQUIREMENTS.items():
        if pp <= 0:
            continue
        location = world.get_location(recruit_name)
        world.set_rule(location, Has(PROSPERITY_ITEM_NAME, count=pp))


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
