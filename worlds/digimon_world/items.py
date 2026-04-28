"""Item table for the Digimon World 1 APWorld (Phase 2: full v1 pool).

Item IDs use DWAP's ``base_id = 690_000`` convention from
``references/DWAP/Apworld/dw1/Items.py`` (an item's AP id is
``ITEM_ID_BASE + dw_code``). Keeping the same offset preserves
cross-walk-ability with DWAP-era seeds for items that overlap.

DWAP's ``dw_code`` namespace partitions:

* ``1000``-block — recruit-completion items (kept in DWAP, **deliberately
  unused here**: this world models recruitment via location checks plus
  a "Recruit: X Soul" pool item, not a separate "X Recruited" pool item).
* ``2000``-block — consumables, MISC, DV items.
* ``3000``-block — progressive / bits.
* ``4000``-block — souls (one per recruitable Digimon).

Locked v1 MVP scope (see ``mvp_scope.md`` memory): chests + NPC gifts +
starter + recruitment. Digivolution randomization deferred to v2, so the
``DV`` items are present only as filler/useful pool ballast — they don't
gate logic. DeathLink deferred. ``Progressive Stat Cap`` from DWAP's
3000-block is **not** in the v1 pool because it is a digivolution-system
item.

Souls for Greymon and MetalGreymon are intentionally absent: per
``dw1_recruitment_logic.md`` and DWAP's ``RecruitDigimon.py``, both
recruits are unlocked via prosperity (15 PP and 50 PP respectively) plus
a recruit-chain prereq, not via soul items. Their AP locations therefore
have non-soul AP items shuffled onto them by fill.
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
# Recruit souls
# =============================================================================
# Soul items track DWAP's 4000-block. Each soul's ``dw_code`` is
# ``4000 + recruit-index`` from DWAP's RecruitDigimon order (preserved here so
# AP IDs match DWAP's). Greymon (4002) and MetalGreymon (4009) soul codes
# are reserved (skipped) so the namespace doesn't shift.

_SOUL_NAMES: Final[tuple[str, ...]] = (
    "Agumon", "Betamon", "Devimon", "Airdramon", "Tyrannomon",
    "Meramon", "Seadramon", "Numemon", "Mamemon", "Monzaemon",
    "Gabumon", "Elecmon", "Kabuterimon", "Angemon", "Birdramon",
    "Garurumon", "Frigimon", "Whamon", "Vegiemon", "SkullGreymon",
    "MetalMamemon", "Vademon", "Patamon", "Kunemon", "Unimon",
    "Ogremon", "Shellmon", "Centarumon", "Bakemon", "Drimogemon",
    "Sukamon", "Andromon", "Giromon", "Etemon", "Biyomon",
    "Palmon", "Monochromon", "Leomon", "Coelamon", "Kokatorimon",
    "Kuwagamon", "Mojyamon", "Nanimon", "Megadramon", "Piximon",
    "Digitamamon", "Penguinmon", "Ninjamon",
)

# DWAP soul-code mapping. Source: references/DWAP/Apworld/dw1/Items.py:224-273.
_SOUL_DW_CODES: Final[dict[str, int]] = {
    "Agumon": 4000, "Betamon": 4001, "Devimon": 4003, "Airdramon": 4004,
    "Tyrannomon": 4005, "Meramon": 4006, "Seadramon": 4007, "Numemon": 4008,
    "Mamemon": 4010, "Monzaemon": 4011, "Gabumon": 4012, "Elecmon": 4013,
    "Kabuterimon": 4014, "Angemon": 4015, "Birdramon": 4016, "Garurumon": 4017,
    "Frigimon": 4018, "Whamon": 4019, "Vegiemon": 4020, "SkullGreymon": 4021,
    "MetalMamemon": 4022, "Vademon": 4023, "Patamon": 4024, "Kunemon": 4025,
    "Unimon": 4026, "Ogremon": 4027, "Shellmon": 4028, "Centarumon": 4029,
    "Bakemon": 4030, "Drimogemon": 4031, "Sukamon": 4032, "Andromon": 4033,
    "Giromon": 4034, "Etemon": 4035, "Biyomon": 4036, "Palmon": 4037,
    "Monochromon": 4038, "Leomon": 4039, "Coelamon": 4040, "Kokatorimon": 4041,
    "Kuwagamon": 4042, "Mojyamon": 4043, "Nanimon": 4044, "Megadramon": 4045,
    "Piximon": 4046, "Digitamamon": 4047, "Penguinmon": 4048, "Ninjamon": 4049,
}

_SOUL_ITEMS: Final[dict[str, ItemEntry]] = {
    f"{name} Soul": ItemEntry(_SOUL_DW_CODES[name], ItemClassification.progression)
    for name in _SOUL_NAMES
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
        ("Large MP", 2006), ("Double flop", 2007), ("Various", 2008),
        ("Omnipotent", 2009), ("Protection", 2010), ("Restore", 2011),
        ("Sup.restore", 2012), ("Bandage", 2013), ("Medicine", 2014),
        ("Off. Disk", 2015), ("Def. Disk", 2016), ("Hispeed dsk", 2017),
        ("Omni Disk", 2018), ("S.Off.disk", 2019), ("S.Def.disk", 2020),
        ("S.speed.disk", 2021), ("Auto Pilot", 2022), ("Off. Chip", 2023),
        ("Def. Chip", 2024), ("Brain Chip", 2025), ("Quick Chip", 2026),
        ("HP Chip", 2027), ("MP Chip", 2028), ("Meat", 2038),
        ("Giant Meat", 2039), ("Sirloin", 2040), ("Supercarrot", 2041),
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
# Final assembled item table
# =============================================================================

_ITEM_TABLE: Final[dict[str, ItemEntry]] = {
    **_KEY_ITEMS,
    **_SOUL_ITEMS,
    **_DV_ITEMS,
    **_CONSUMABLES,
    **_BITS,
}

ITEM_NAME_TO_ID: Final[dict[str, int]] = {
    name: ITEM_ID_BASE + entry.dw_code for name, entry in _ITEM_TABLE.items()
}

ITEM_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Recruit Souls": set(_SOUL_ITEMS),
    "Progression Keys": set(_KEY_ITEMS),
    "DV Items": set(_DV_ITEMS),
    "Consumables": set(_CONSUMABLES),
    "Bits": set(_BITS),
}

FILLER_ITEM_NAME: Final = "1000 Bits"


# =============================================================================
# Itempool construction
# =============================================================================
# Total non-event location count is fixed by :mod:`.locations`. We seed the
# pool with exactly the items defined above (149 entries), which by design
# matches the location count. If a future option changes the location
# count, the residual is filled with :func:`get_filler_item_name` calls.


def create_item(world: DigimonWorldWorld, name: str) -> DigimonWorldItem:
    entry = _ITEM_TABLE[name]
    return DigimonWorldItem(name, entry.classification, ITEM_NAME_TO_ID[name], world.player)


def create_all_items(world: DigimonWorldWorld) -> None:
    """Submit the v1 itempool (149 items)."""

    itempool: list[Item] = [world.create_item(name) for name in _ITEM_TABLE]
    needed = len(world.multiworld.get_unfilled_locations(world.player)) - len(itempool)
    itempool.extend(world.create_filler() for _ in range(max(needed, 0)))
    world.multiworld.itempool += itempool
