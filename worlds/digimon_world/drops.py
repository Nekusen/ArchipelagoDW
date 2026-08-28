"""Enemy item-drop randomization for Digimon World 1.

``DIGIMON_DATA[type].dropItem`` / ``dropChance`` decide what a beaten Digimon leaves behind:
after a won battle ``battleStatsGainsAndDrops`` rolls ``random(100) < dropChance`` per enemy
and hands out ``dropItem``. Both are bytes of a static SLUS table, so a seed's changes are
plain data writes.

The pool and the drop-rate ladder are a clean-room reimplementation of meekrhino's standalone
randomizer (``handler.py:randomizeDigimonData``): replacement items are consumables that are
neither quest nor evolution items (nor the AP chest sentinel), optionally kept on the same side
of a price cutoff as the vanilla drop; drop rates move a step or two along the vanilla ladder,
species that never dropped anything get a rate, and 100 % drops stay 100 %.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.enemy_records import ITEMS, SPECIES
from .ground_items import ItemProps

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


ITEM_PROPS: Final[dict[int, ItemProps]] = {
    row[0]: ItemProps(item_id=row[0], price=row[2], sort=row[3], dropable=row[4]) for row in ITEMS
}
ITEM_NAMES: Final[dict[int, str]] = {row[0]: row[1] for row in ITEMS}

#: The vanilla drop-rate ladder (every species' ``dropChance`` is one of these, 0 or 100).
DROP_RATE_LADDER: Final = (1, 5, 10, 20, 25, 30, 40, 50)
#: Ladder padded at both ends so a rate can move up to two steps either way; the padding
#: makes the extremes stickier, as in the standalone.
_DROP_RATE_CHOICES: Final = (1, 1, 1, 5, 10, 20, 25, 30, 40, 50, 50, 50)
ALWAYS_DROP: Final = 100
NEVER_DROP: Final = 0


class DropPlan(NamedTuple):
    #: species id -> (drop item, drop chance) for every species whose values changed
    overrides: dict[int, tuple[int, int]]

    @property
    def empty(self) -> bool:
        return not self.overrides


EMPTY_PLAN: Final = DropPlan({})


def drop_item_pool(vanilla_item: int, match_value: bool, cutoff: int) -> list[int]:
    """Replacement candidates for a species whose vanilla drop is ``vanilla_item``."""

    vanilla_cheap = ITEM_PROPS[vanilla_item].price < cutoff
    return [
        props.item_id for props in ITEM_PROPS.values()
        if props.is_consumable and props.dropable and not props.is_evo and not props.is_banned
        and (not match_value or (props.price < cutoff) == vanilla_cheap)
    ]


def randomize_drop_rate(rng: Random, rate: int) -> int:
    if rate == NEVER_DROP:
        return rng.choice(DROP_RATE_LADDER)
    if rate == ALWAYS_DROP:
        return rate
    index = DROP_RATE_LADDER.index(rate) + 2
    return rng.choice(_DROP_RATE_CHOICES[index - 2:index + 3])


def randomize_drops(
    rng: Random, *, items: bool, rates: bool, match_value: bool, cutoff: int,
) -> dict[int, tuple[int, int]]:
    """New ``(drop item, drop chance)`` per species (all 180 entries, as the standalone does);
    only species whose values changed are returned."""

    overrides: dict[int, tuple[int, int]] = {}
    for row in SPECIES:
        species_id, vanilla_item, vanilla_rate = row[0], row[5], row[6]
        item, rate = vanilla_item, vanilla_rate
        if items:
            item = rng.choice(drop_item_pool(vanilla_item, match_value, cutoff))
        if rates:
            rate = randomize_drop_rate(rng, vanilla_rate)
        if (item, rate) != (vanilla_item, vanilla_rate):
            overrides[species_id] = (item, rate)
    return overrides


def build_drop_plan(world: DigimonWorldWorld) -> DropPlan:
    """Resolve the drop options into concrete table rewrites (call from ``generate_early``)."""

    options = world.options
    items = bool(options.enemy_drop_items.value)
    rates = bool(options.enemy_drop_rates.value)
    if not items and not rates:
        return EMPTY_PLAN
    return DropPlan(randomize_drops(
        world.random, items=items, rates=rates,
        match_value=bool(options.enemy_drops_match_value.value),
        cutoff=int(options.enemy_drops_value_cutoff.value),
    ))
