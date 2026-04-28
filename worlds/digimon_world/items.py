"""Item table for the Digimon World 1 APWorld (Phase 4 v6: AP-recruit-free).

Item IDs use DWAP's ``base_id = 690_000`` convention from
``references/DWAP/Apworld/dw1/Items.py`` (an item's AP id is
``ITEM_ID_BASE + dw_code``). Keeping the same offset preserves
cross-walk-ability with DWAP-era seeds for items that overlap.

DWAP's ``dw_code`` namespace partitions:

* ``1000``-block — reserved (DWAP recruit-completion items).
* ``2000``-block — consumables, MISC, DV items.
* ``3000``-block — progressive / bits.
* ``4000``-block — reserved (was recruit items in earlier phases).

Recruit handling
================

Recruits are NOT AP items in this revision. After live testing showed
the trigger-remap mechanism couldn't decouple "encounter completed"
from "Digimon joins city" without much deeper RE work (see
``phase_progress.md``), recruits were moved out of the AP loop:

* No ``"X Recruit"`` items exist in the pool.
* No AP locations exist for fighting Digimon.
* The patcher still ships a closed-shuffle ``recruit_remap`` that
  vanilla-style remaps which Digimon recruits at which spawn point
  (the standalone DW1 randomizer's well-tested behavior).

Net effect: the player still sees a randomized recruit roster as they
explore the world, but it's resolved entirely in-ROM. AP carries
chests, prosperity gifts, and the starter only.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from BaseClasses import Item, ItemClassification

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


ITEM_ID_BASE: Final = 690_000


class DigimonWorldItem(Item):
    game = "Digimon World"


class ItemEntry(NamedTuple):
    dw_code: int
    classification: ItemClassification


# =============================================================================
# Progression keys
# =============================================================================
# Mansion Key, Gear, Frig Key, AS Decoder, Blue Flute, old fishrod, Amazing rod,
# Rain Plant — eight items the v1 logic in :mod:`.rules` actually gates on.
# DV codes mirror DWAP where the item exists there.

_KEY_ITEMS: Final[dict[str, ItemEntry]] = {
    "Mansion Key": ItemEntry(2119, ItemClassification.progression),
    "Gear":        ItemEntry(2120, ItemClassification.progression),
    "Frig Key":    ItemEntry(2123, ItemClassification.progression),
    "AS Decoder":  ItemEntry(2124, ItemClassification.progression),
    "Blue Flute":  ItemEntry(2115, ItemClassification.progression),
    "old fishrod": ItemEntry(2116, ItemClassification.progression),
    "Amazing rod": ItemEntry(2117, ItemClassification.progression | ItemClassification.useful),
    "Rain Plant":  ItemEntry(2121, ItemClassification.progression),
}

# =============================================================================
# DV (digivolution) items
# =============================================================================
# Pool ballast for v1. Digivolution randomization is deferred to v2; until
# then these are filler|useful but not progression. Codes mirror DWAP's
# 2071-2114 range.

_DV_ITEMS: Final[dict[str, ItemEntry]] = {
    name: ItemEntry(code, ItemClassification.useful) for name, code in (
        ("Grey Claws", 2071), ("Fireball", 2072), ("Flamingwing", 2073),
        ("Iron Hoof", 2074), ("Mono Stone", 2075), ("Steel drill", 2076),
        ("White Fang", 2077), ("Black Wing", 2078), ("Spike Club", 2079),
        ("Flamingmane", 2080), ("White Wing", 2081), ("Torn tatter", 2082),
        ("Electo ring", 2083), ("Rainbowhorn", 2084), ("Rooster", 2085),
        ("Unihorn", 2086), ("Horn helmet", 2087), ("Scissor jaw", 2088),
        ("Fertilizer", 2089), ("Koga laws", 2090), ("Waterbottle", 2091),
        ("North Star", 2092), ("Red Shell", 2093), ("Hard Scale", 2094),
        ("Bluecrystal", 2095), ("Ice crystal", 2096), ("Hair grower", 2097),
        ("Sunglasses", 2098), ("Metal part", 2099), ("Fatal Bone", 2100),
    )
}

# =============================================================================
# Consumables
# =============================================================================
# Standard food / recovery / disk items. All filler classification.

_CONSUMABLES: Final[dict[str, ItemEntry]] = {
    name: ItemEntry(code, ItemClassification.filler) for name, code in (
        ("SM Recovery", 2000), ("Med Recovery", 2001), ("Lrg Recovery", 2002),
        ("Sup Recovery", 2003), ("MP Floppy", 2004), ("Medium MP", 2005),
        ("Large MP", 2006), ("Various", 2008),
        ("Protection", 2010), ("Restore", 2011),
        ("Sup.restore", 2012), ("Medicine", 2014),
        ("Off. Disk", 2015), ("Def. Disk", 2016), ("Hispeed dsk", 2017),
        ("Omni Disk", 2018),
        ("Off. Chip", 2023),
        ("Brain Chip", 2025),
        ("HP Chip", 2027), ("MP Chip", 2028), ("Meat", 2038),
        ("Sirloin", 2040), ("Supercarrot", 2041),
        ("Hawk radish", 2042), ("Spiny green", 2043),
    )
}

# =============================================================================
# Bits (currency)
# =============================================================================
# DWAP keeps two denominations.

_BITS: Final[dict[str, ItemEntry]] = {
    "1000 Bits": ItemEntry(3001, ItemClassification.filler),
    "5000 Bits": ItemEntry(3002, ItemClassification.filler),
}

# =============================================================================
# Prosperity Point — AP-controlled in-game prosperity
# =============================================================================
# In-game prosperity is enforced client-side: every watcher tick the
# client writes the count of received ``Prosperity Point`` items to
# :data:`worlds.digimon_world.data.addresses.RAM_PROSPERITY_POINTS`.
# Any vanilla DW1 attempt to bump prosperity is overwritten on the next
# tick. AP is the single source of truth for prosperity progression.
#
# The pool ships exactly :data:`PROSPERITY_POINT_COUNT` copies of the
# item — comfortably above the 50 Final-Battle goal gate so logic has
# room to place them.

PROSPERITY_POINT_NAME: Final = "Prosperity Point"
PROSPERITY_POINT_COUNT: Final = 50

_PROSPERITY: Final[dict[str, ItemEntry]] = {
    PROSPERITY_POINT_NAME: ItemEntry(3003, ItemClassification.progression),
}


# =============================================================================
# Final assembled item table
# =============================================================================

_ITEM_TABLE: Final[dict[str, ItemEntry]] = {
    **_KEY_ITEMS,
    **_DV_ITEMS,
    **_CONSUMABLES,
    **_BITS,
    **_PROSPERITY,
}

ITEM_NAME_TO_ID: Final[dict[str, int]] = {
    name: ITEM_ID_BASE + entry.dw_code for name, entry in _ITEM_TABLE.items()
}

ITEM_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Progression Keys": set(_KEY_ITEMS),
    "DV Items": set(_DV_ITEMS),
    "Consumables": set(_CONSUMABLES),
    "Bits": set(_BITS),
    "Prosperity": set(_PROSPERITY),
}

FILLER_ITEM_NAME: Final = "1000 Bits"


# =============================================================================
# Itempool construction
# =============================================================================
# Pool composition: one copy each of the explicit items in :data:`_ITEM_TABLE`,
# plus :data:`PROSPERITY_POINT_COUNT - 1` extra copies of ``Prosperity Point``
# (the table already includes one). Pad with filler to the unfilled-location
# count.


def create_item(world: DigimonWorldWorld, name: str) -> DigimonWorldItem:
    entry = _ITEM_TABLE[name]
    return DigimonWorldItem(name, entry.classification, ITEM_NAME_TO_ID[name], world.player)


def create_all_items(world: DigimonWorldWorld) -> None:
    """Submit the v1 itempool, padding to the unfilled-location count."""

    itempool: list[Item] = [world.create_item(name) for name in _ITEM_TABLE]
    # _ITEM_TABLE contributes one ``Prosperity Point``; ship the rest.
    itempool.extend(
        world.create_item(PROSPERITY_POINT_NAME)
        for _ in range(PROSPERITY_POINT_COUNT - 1)
    )
    needed = len(world.multiworld.get_unfilled_locations(world.player)) - len(itempool)
    itempool.extend(world.create_filler() for _ in range(max(needed, 0)))
    world.multiworld.itempool += itempool
