"""NPC gift randomization for Digimon World 1: Tokomon's starter items and the techniques the
Beetle Land Bug and Seadramon teach.

Neither is an AP location -- these are the standalone randomizer's ``tokomon`` and
``techGifts`` features, reimplemented clean-room (``handler.py:randomizeTokomonItems`` /
``randomizeTechGifts``): six ``giveItem`` opcodes in Tokomon's script get a random item and
count, and the four ``learnMove`` sites (plus their "already known" check byte) get a random
partner-learnable technique. All of it is script-byte data.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.addresses import ROM_LEARN_MOVE_OFFSETS, ROM_TOKOMON_ITEM_OFFSETS, TECH_GIFT_VANILLA, TOKOMON_GIFT_VANILLA
from .drops import ITEM_PROPS
from .techniques import PARTNER_MOVE_COUNT

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


TECH_GIFT_SITE_NAMES: Final = ("Beetle Land (Bug)", "Seadramon 1", "Seadramon 2", "Seadramon 3")
TOKOMON_GIFT_COUNT_MAX: Final = 3
TOKOMON_VALUABLE_PRICE: Final = 1000


class GiftPlan(NamedTuple):
    #: site index (``ROM_LEARN_MOVE_OFFSETS`` order) -> technique id, changed sites only
    tech_gifts: dict[int, int]
    #: site index (``ROM_TOKOMON_ITEM_OFFSETS`` order) -> (item, count), changed sites only
    tokomon_gifts: dict[int, tuple[int, int]]

    @property
    def empty(self) -> bool:
        return not self.tech_gifts and not self.tokomon_gifts


EMPTY_PLAN: Final = GiftPlan({}, {})


def randomize_tech_gifts(rng: Random) -> dict[int, int]:
    """Each teach site gets a random partner-learnable technique."""

    out: dict[int, int] = {}
    for site in range(len(ROM_LEARN_MOVE_OFFSETS)):
        tech = rng.randrange(PARTNER_MOVE_COUNT)
        if tech != TECH_GIFT_VANILLA[site]:
            out[site] = tech
    return out


def tokomon_item_pool(consumable_only: bool) -> list[int]:
    """Items Tokomon may hand out: never quest or digivolution items (nor the AP sentinel);
    with ``consumable_only`` also nothing like Enemy Repel or Training Manual."""

    return [
        props.item_id for props in ITEM_PROPS.values()
        if props.dropable and not props.is_evo and not props.is_banned
        and (not consumable_only or props.is_consumable)
    ]


def _tokomon_count(rng: Random, price: int) -> int:
    """1..3 copies; a second roll makes valuable items less likely to come in bulk and cheap
    ones less likely to come alone."""

    count = rng.randint(1, TOKOMON_GIFT_COUNT_MAX)
    if price >= TOKOMON_VALUABLE_PRICE and count > 1:
        count = rng.randint(1, TOKOMON_GIFT_COUNT_MAX)
    elif price < TOKOMON_VALUABLE_PRICE and count == 1:
        count = rng.randint(1, TOKOMON_GIFT_COUNT_MAX)
    return count


def randomize_tokomon_gifts(rng: Random, consumable_only: bool) -> dict[int, tuple[int, int]]:
    pool = tokomon_item_pool(consumable_only)
    out: dict[int, tuple[int, int]] = {}
    for site in range(len(ROM_TOKOMON_ITEM_OFFSETS)):
        item = rng.choice(pool)
        gift = (item, _tokomon_count(rng, ITEM_PROPS[item].price))
        if gift != TOKOMON_GIFT_VANILLA[site]:
            out[site] = gift
    return out


def build_gift_plan(world: DigimonWorldWorld) -> GiftPlan:
    """Resolve the gift options into concrete script-byte rewrites (call from ``generate_early``)."""

    options = world.options
    tech_gifts = randomize_tech_gifts(world.random) if options.tech_gifts else {}
    tokomon = (
        randomize_tokomon_gifts(world.random, bool(options.tokomon_gifts_consumable_only.value))
        if options.tokomon_gifts else {}
    )
    return GiftPlan(tech_gifts, tokomon)
