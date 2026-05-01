"""Item table for the Digimon World 1 APWorld (Phase 5 piece C: recruits as AP items).

Item IDs use DWAP's ``base_id = 690_000`` convention from
``references/DWAP/Apworld/dw1/Items.py`` (an item's AP id is
``ITEM_ID_BASE + dw_code``). Keeping the same offset preserves
cross-walk-ability with DWAP-era seeds for items that overlap.

DWAP's ``dw_code`` namespace partitions:

* ``1000``-block — recruit-completion items (Phase 5 piece C: 49
  ``"<Digimon> Recruit"`` items, one per recruitable Digimon except
  Agumon — Agumon is force-recruited by the client because he's the
  bank NPC). Each entry's dw_code is ``1000 + digimon_id``.
* ``2000``-block — consumables, MISC, DV items.
* ``3000``-block — progressive / bits.
* ``4000``-block — reserved (was souls in earlier phases).

Recruit handling (Phase 5 piece C)
==================================

The player can fight any recruitable Digimon to fire its AP location
(detected via the redirected "beaten" trigger bit installed by the
``setTrigger`` wrapper in :mod:`worlds.digimon_world.data.addresses`).
Whoever placed the corresponding ``"<X> Recruit"`` item at some AP
location holds the ability to grant join-city — Digimon X stays
out-of-city until that AP item is delivered, at which point the
client writes ``setTrigger(200+digimon_id)`` directly.

Agumon is special: he handles the in-city bank (a key delivery
mechanic), so the client always force-sets his recruit bit on
connect — he's "in city" from the start regardless of when the
player completes the Agumon-fight cutscene. The Agumon AP location
still fires from the beaten bit on completion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from BaseClasses import Item, ItemClassification

from .data.addresses import AP_RECRUIT_ITEM_DIGIMON, RECRUIT_RAM_BITS

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
# Mansion Key, Gear, Frig Key, AS Decoder, Blue Flute, Old Fishrod, Amazing rod,
# Rain Plant — eight items the v1 logic in :mod:`.rules` actually gates on.
# DV codes mirror DWAP where the item exists there.

_KEY_ITEMS: Final[dict[str, ItemEntry]] = {
    "Mansion Key": ItemEntry(2119, ItemClassification.progression),
    "Gear":        ItemEntry(2120, ItemClassification.progression),
    "Frig Key":    ItemEntry(2123, ItemClassification.progression),
    "AS Decoder":  ItemEntry(2124, ItemClassification.progression),
    "Blue Flute":  ItemEntry(2115, ItemClassification.progression),
    "Old Fishrod": ItemEntry(2116, ItemClassification.progression),
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
# client writes ``ProsperityPoint count * PROSPERITY_PER_ITEM`` to
# :data:`worlds.digimon_world.data.addresses.RAM_PROSPERITY_POINTS`.
# Any vanilla DW1 attempt to bump prosperity is overwritten on the next
# tick. AP is the single source of truth for prosperity progression.
#
# Phase 5 piece C: each ``Prosperity Point`` item is worth 2 PP. With
# :data:`PROSPERITY_POINT_COUNT` = 25, the pool delivers exactly 50 PP
# (matching the Final-Battle goal gate). PP-gated logic in
# :mod:`worlds.digimon_world.rules` rounds the in-game PP threshold up
# to the nearest even multiple, so a "15 PP gate" becomes a "16 PP
# gate" requiring 8 of the 25 items.

PROSPERITY_POINT_NAME: Final = "Prosperity Point"
PROSPERITY_POINT_COUNT: Final = 25
PROSPERITY_PER_ITEM: Final = 2

_PROSPERITY: Final[dict[str, ItemEntry]] = {
    PROSPERITY_POINT_NAME: ItemEntry(3003, ItemClassification.progression),
}


# =============================================================================
# Recruit items (Phase 5 piece C)
# =============================================================================
# One "<Digimon> Recruit" item per recruitable Digimon except Agumon
# (49 items). Each is keyed at dw_code = 1000 + digimon_id, where
# digimon_id is the Digimon's in-ROM id (recoverable from the recruit
# trigger as ``trigger - 200``). Progression-classified because they
# unlock in-city behavior (PP/model/roster) for that Digimon and AP
# logic gates downstream content on cumulative-PP via the recruit's
# vanilla level-based contribution... except this APWorld suppresses
# that contribution via the setTrigger wrapper redirection. The
# recruits remain progression because future logic (per-recruit gates
# beyond PP) may want them, and a `Has("<X> Recruit")` rule is
# unambiguous.


def _digimon_id_from_recruit_bit(byte_addr: int, bit: int) -> int:
    """Recover digimon_id from the in-ROM recruit-completion bit pair."""

    trigger_id = (byte_addr - 0x001BDFCD) * 8 + bit
    return trigger_id - 200


_RECRUIT_ITEMS: Final[dict[str, ItemEntry]] = {
    f"{name} Recruit": ItemEntry(
        1000 + _digimon_id_from_recruit_bit(*RECRUIT_RAM_BITS[name]),
        ItemClassification.progression,
    )
    for name in AP_RECRUIT_ITEM_DIGIMON
}
assert len(_RECRUIT_ITEMS) == 49, len(_RECRUIT_ITEMS)


# =============================================================================
# Final assembled item table
# =============================================================================

_ITEM_TABLE: Final[dict[str, ItemEntry]] = {
    **_KEY_ITEMS,
    **_DV_ITEMS,
    **_CONSUMABLES,
    **_BITS,
    **_PROSPERITY,
    **_RECRUIT_ITEMS,
}

ITEM_NAME_TO_ID: Final[dict[str, int]] = {
    name: ITEM_ID_BASE + entry.dw_code for name, entry in _ITEM_TABLE.items()
}


# =============================================================================
# DW1-internal item-id mapping (Phase 5 piece A — vanilla-grant chests)
# =============================================================================
# DW1's in-ROM item table indexes by 1-byte ID in 0..127. DWAP's 2000-block
# preserves this 1:1 — ``dw1_internal_id = dw_code - 2000``. Items in
# other blocks (3000 = bits/prosperity, 1000/4000 = reserved) are
# AP-only and have no DW1 internal representation; for them the helper
# returns ``None``.
#
# Used by :mod:`worlds.digimon_world.chest_assignments` to decide
# per-chest whether the AP-placed item can be granted via the vanilla
# chest-pickup flow (real DW1 internal id) or must use the
# ``AP_CHEST_SENTINEL_ITEM_ID`` fallback (showing "AP ITEM" with no
# in-game item; the client delivers the real AP item to the player's
# bank instead).

_DW1_INTERNAL_ITEM_BLOCK_BASE: Final = 2000
_DW1_INTERNAL_ITEM_BLOCK_SIZE: Final = 128


def dw1_internal_item_id(item_name: str) -> int | None:
    """Return the DW1 in-ROM item id for ``item_name``, or ``None`` if
    the item is AP-only and has no vanilla chest representation.
    """

    entry = _ITEM_TABLE.get(item_name)
    if entry is None:
        return None
    slot = entry.dw_code - _DW1_INTERNAL_ITEM_BLOCK_BASE
    if 0 <= slot < _DW1_INTERNAL_ITEM_BLOCK_SIZE:
        return slot
    return None

ITEM_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Progression Keys": set(_KEY_ITEMS),
    "DV Items": set(_DV_ITEMS),
    "Consumables": set(_CONSUMABLES),
    "Bits": set(_BITS),
    "Prosperity": set(_PROSPERITY),
    "Recruits": set(_RECRUIT_ITEMS),
}


def digimon_id_for_recruit_item(item_name: str) -> int | None:
    """Return ``digimon_id`` for a ``"<Digimon> Recruit"`` item name, or ``None``.

    Used by the client's recruit deliverer to compute the recruit
    trigger ID (= 200 + digimon_id) and write it directly to the
    trigger array, bypassing the setTrigger wrapper.
    """

    entry = _RECRUIT_ITEMS.get(item_name)
    if entry is None:
        return None
    return entry.dw_code - 1000

FILLER_ITEM_NAME: Final = "1000 Bits"


# =============================================================================
# Itempool construction
# =============================================================================
# Pool composition (Phase 5 piece C):
#
# 1. **Progression** (mandatory; every entry shipped exactly once
#    unless noted): 8 keys + 49 recruit items + ``PROSPERITY_POINT_COUNT``
#    Prosperity Points = 82 items.
# 2. **Useful** (DV items, 30): shipped one each, trimmed if optional
#    space runs out.
# 3. **Filler** (consumables + bits, 27): shipped one each, trimmed if
#    optional space runs out.
# 4. **Padding** (generic filler, only when total < location count):
#    extra copies of :data:`FILLER_ITEM_NAME` to fill remaining slots.
#
# When mandatory + optional > location count (the typical case once
# recruits joined the pool — 82 + 57 = 139 vs ~116 locations), we trim
# from the *back* of the optional list (filler before useful, since
# consumables tend to be more redundant than DV items).


def create_item(world: DigimonWorldWorld, name: str) -> DigimonWorldItem:
    entry = _ITEM_TABLE[name]
    return DigimonWorldItem(name, entry.classification, ITEM_NAME_TO_ID[name], world.player)


def create_all_items(world: DigimonWorldWorld) -> None:
    """Submit the Phase 5 piece C itempool sized to the location count."""

    locations_count = len(world.multiworld.get_unfilled_locations(world.player))

    # Mandatory items (progression).
    mandatory: list[Item] = []
    mandatory.extend(world.create_item(name) for name in _KEY_ITEMS)
    mandatory.extend(world.create_item(name) for name in _RECRUIT_ITEMS)
    mandatory.extend(
        world.create_item(PROSPERITY_POINT_NAME)
        for _ in range(PROSPERITY_POINT_COUNT)
    )

    if len(mandatory) > locations_count:
        raise ValueError(
            f"Mandatory items ({len(mandatory)}) exceed unfilled locations "
            f"({locations_count}); reduce PROSPERITY_POINT_COUNT or expand "
            f"the location pool.",
        )

    # Optional items, in priority order: DV items (useful) before
    # consumables/bits (filler).
    optional: list[Item] = []
    optional.extend(world.create_item(name) for name in _DV_ITEMS)
    optional.extend(world.create_item(name) for name in _CONSUMABLES)
    optional.extend(world.create_item(name) for name in _BITS)

    pool = list(mandatory)
    pool.extend(optional[: max(0, locations_count - len(pool))])

    # Pad with generic filler if the explicit table didn't reach the
    # location count (shouldn't happen with current numbers, but keep
    # the safety net so future location-pool growth doesn't error out).
    while len(pool) < locations_count:
        pool.append(world.create_filler())

    assert len(pool) == locations_count, (len(pool), locations_count)
    world.multiworld.itempool += pool
