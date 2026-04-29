"""Access rules for the Digimon World 1 APWorld (Phase 5 piece C).

Per-recruit and per-chest PP gates are sourced from
:data:`worlds.digimon_world.locations.RECRUIT_PP_REQUIREMENTS` and
:data:`CHEST_PP_REQUIREMENTS`. The values in those tables are in
**in-game PP units**.

Phase 5 piece C: each shipped ``Prosperity Point`` item delivers
:data:`worlds.digimon_world.items.PROSPERITY_PER_ITEM` (= 2) PP. AP
logic gating uses Has(item, count=N) where N is *items needed* (not
PP needed). To translate: ``items_needed = ceil(pp_needed /
PROSPERITY_PER_ITEM)``. Per the user's spec we round up — a 15-PP
gate becomes a "16 PP / 8 items" gate (the worse case for the
player), preserving the gate's intent under integer division.

Final Battle stays at AS Decoder + 50 PP, which equals all 25 PP
items in the pool.
"""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from rule_builder.rules import Has

from .items import PROSPERITY_PER_ITEM
from .locations import CHEST_PP_REQUIREMENTS, RECRUIT_PP_REQUIREMENTS

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


PROSPERITY_ITEM_NAME = "Prosperity Point"


def _items_needed(pp_needed: int) -> int:
    """Translate an in-game PP threshold to the AP-item count."""

    return ceil(pp_needed / PROSPERITY_PER_ITEM)


def set_all_rules(world: DigimonWorldWorld) -> None:
    _set_recruit_rules(world)
    _set_chest_rules(world)
    _set_completion_condition(world)


def _set_recruit_rules(world: DigimonWorldWorld) -> None:
    """Attach the PP gate to each recruit AP location.

    Recruits with a 0-PP gate are skipped (no rule = always reachable).
    """

    for recruit_name, pp in RECRUIT_PP_REQUIREMENTS.items():
        if pp <= 0:
            continue
        location = world.get_location(recruit_name)
        world.set_rule(location, Has(PROSPERITY_ITEM_NAME, count=_items_needed(pp)))


def _set_chest_rules(world: DigimonWorldWorld) -> None:
    """Attach the per-chest PP gate. Each chest's gate is the minimum
    PP across recruits in the same in-game region (see
    :data:`worlds.digimon_world.locations.CHEST_PP_REQUIREMENTS`).
    Chests with a 0-PP gate (no inferred region or region with 0-PP
    recruits) are skipped.
    """

    for chest_name, pp in CHEST_PP_REQUIREMENTS.items():
        if pp <= 0:
            continue
        location = world.get_location(chest_name)
        world.set_rule(location, Has(PROSPERITY_ITEM_NAME, count=_items_needed(pp)))


def _set_completion_condition(world: DigimonWorldWorld) -> None:
    """Final Battle requires AS Decoder + 50 in-game PP (all 25 PP
    items). The Victory event is the AP win condition."""

    final_battle = world.get_location("Final Battle")
    world.set_rule(
        final_battle,
        Has("AS Decoder") & Has(PROSPERITY_ITEM_NAME, count=_items_needed(50)),
    )
    world.set_completion_rule(Has("Victory"))


__all__ = ["PROSPERITY_ITEM_NAME", "set_all_rules"]
