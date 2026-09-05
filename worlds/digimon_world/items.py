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

from .data.addresses import (
    AP_RECRUIT_ITEM_DIGIMON,
    RECRUIT_RAM_BITS,
    TECH_MASTERY_SLOTS,
    TECH_NAMES_BY_SLOT,
)
from .regions import LOCKABLE_REGIONS, region_access_item_name

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
# The canonical DW1 key-item list (per user, 2026-05-08) is:
#
#     Blue Flute   — summon Seadramon to Beetle Land
#     Old Fishrod  — fishing
#     Amazing Rod  — better fishing
#     Leomonstone  — Leomon's recruit quest (Stone Tablet)
#     Mansion Key  — enter Grey Lord's Mansion
#     Gear         — Monzaemon / Toy Town questline
#     Rain Plant   — Vegimon recruit quest
#     Frig Key     — Grey Lord's Mansion / refrigerator
#
# **AS Decoder is NOT a key item.** It exists in DW1 but does nothing
# in-game and gates nothing — removed from the item pool 2026-05-08.
#
# All 8 AP-tracked key items are progression items below. Leomonstone
# was added 2026-05-08 to gate Leomon's recruit (Stone Tablet path).
# Steak was originally added on the same date for SkullGreymon's
# recruit but its randomization was reverted: vanilla DW1 spawns Steak
# from the Overdell fridge when Frig Key is used, so the Frig Key item
# alone approximates the SkullGreymon recruit gate.
#
# Note: Leomonstone has a vanilla pickup at the Stone Tablet site in
# Ancestor's Cave, so the ``Has("Leomonstone")`` gate is currently
# bypassable by reaching that site in-game. The bypass will close when
# the v2 "key item spawn randomization" lands (PLAN.md Phase 7).
#
# DV codes mirror DWAP where the item exists there.

_KEY_ITEMS: Final[dict[str, ItemEntry]] = {
    "Mansion Key": ItemEntry(2119, ItemClassification.progression),
    "Gear":        ItemEntry(2120, ItemClassification.progression),
    "Frig Key":    ItemEntry(2123, ItemClassification.progression),
    "Blue Flute":  ItemEntry(2115, ItemClassification.progression),
    "Old Fishrod": ItemEntry(2116, ItemClassification.progression),
    "Amazing rod": ItemEntry(2117, ItemClassification.progression | ItemClassification.useful),
    "Rain Plant":  ItemEntry(2121, ItemClassification.progression),
    "Leomonstone": ItemEntry(2118, ItemClassification.progression),
    # Virtual access item (no real DW1 inventory entry). Delivered as a
    # trigger-array bit-flip via KEYITEM_DELIVERY_RAM_BITS; the patched
    # boulder script in Drill Tunnel reads that bit. dw_code 5000 is
    # outside any real-DW1 / recruit / Birdramon-flight range.
    "Lava Cave Access": ItemEntry(5000, ItemClassification.progression),
    # Bridge unlock items (only included in the pool when the
    # corresponding option is in ``shuffled`` mode). Each pins its
    # bridge-fixed trigger bit on delivery. dw_codes 5001/5002 follow
    # the 5000+ "virtual access item" range.
    "Tropical Jungle Bridge": ItemEntry(5001, ItemClassification.progression),
    "Great Canyon Bridge":    ItemEntry(5002, ItemClassification.progression),
    "Factorial Town Gate":    ItemEntry(5003, ItemClassification.progression),
}

# =============================================================================
# Region Access items (RegionLocking option)
# =============================================================================
#
# One ``<region> Region Access`` AP item per name in
# :data:`worlds.digimon_world.regions.LOCKABLE_REGIONS`. Pure-logic items
# (no in-game effect) — AP placement treats the region's checks as
# unreachable until the item is delivered, but nothing physically gates
# the player from walking in. See :class:`worlds.digimon_world.options.RegionLocking`
# for the full design rationale.
#
# dw_codes follow the 5000+ "virtual access item" range (LCA = 5000,
# TJ Bridge = 5001, GC Bridge = 5002); region-access codes start at 5010
# to leave a small gap for future bridge-style virtual items.
#
# Items are added to the pool selectively — only those whose region is
# in :func:`options.get_locked_regions` ship. The other entries stay in
# :data:`_ITEM_TABLE` (so name-to-id lookups remain stable across
# option combinations) but never enter the itempool. This matches the
# pattern used by Lava Cave Access / Tropical Jungle Bridge / Great
# Canyon Bridge in :func:`create_all_items`.

_REGION_ACCESS_ITEMS: Final[dict[str, ItemEntry]] = {
    region_access_item_name(region): ItemEntry(
        5010 + i, ItemClassification.progression,
    )
    for i, region in enumerate(LOCKABLE_REGIONS)
}
assert len(_REGION_ACCESS_ITEMS) == len(LOCKABLE_REGIONS)

# =============================================================================
# Bank-item catalog — unified table for non-key, non-recruit items
# =============================================================================
#
# Phase 8 (2026-05-09) rework: replaces the old separate ``_DV_ITEMS``
# (useful) + ``_CONSUMABLES`` (filler) tables. Every shippable bank
# item now lives in a single catalog keyed by display name → dw_code.
# The classification is set per-item: 5 explicit useful items, the
# rest are filler. dw_code = 2000 + ITEM_PARA slot.
#
# **Items intentionally omitted:**
#
# * Slot 22 (Auto Pilot) — already in the player's starting
#   inventory; shipping it in the AP pool would be redundant filler.
# * Slot 32 (Port. potty) — vending-machine reward; not in AP pool.
# * Slot 50 (Gold Acorn) — niche "sells for high price" item; out
#   of the design.
# * Slot 48 Blue apple, slot 54 Pricklypear, slot 68 Moldy Meat,
#   slot 69 Happymushrm — niche / risky / trap-shaped flavor items
#   the user opted out of.
# * Slot 83 (Electo ring) — repurposed as
#   ``AP_CHEST_SENTINEL_ITEM_ID`` (the in-game "AP ITEM"
#   placeholder); underlying vanilla item is unused / crashes the
#   game.
# * Slot 114 (Moon mirror) — repurposed as
#   ``AP_SHOP_BOUGHT_SENTINEL_ITEM_ID`` ("AP Item Bought"); same
#   reason.
# * Slots 111-113 (Red Ruby, Beetlepearl, Coral charm) — "Mega"-tier
#   digivolution items omitted to keep the Ultimate-tier filler
#   list coherent (those items lead to extra-high-tier evolutions
#   that are mostly-cosmetic / post-game).
# * Slots 125-127 (Giga Hand, Noble Mane, Metalbanana) — used for
#   the AP items_received counter scratch state per
#   ``dw1_counter_safe_address.md``.
# * Slot 124 (AS Decoder) — vanilla key item that gates nothing
#   (the "Final Battle requires AS Decoder" rule was removed
#   2026-05-08); not worth shipping.
#
# Slots 83 and 114 are also banned from ground-item randomization
# via ``ground_items.BANNED_ITEM_IDS``.

# Items the user explicitly tagged as ``useful``: meaningful in-game
# effect that AP fill should prefer placing at non-EXCLUDED locations.
_USEFUL_ITEM_NAMES: Final[frozenset[str]] = frozenset({
    "Trn. manual",   # better training
    "Rest pillow",   # more recovery during rest
    "Health shoe",   # walking boosts HP/MP
    "Enemy repel",   # repel wild encounters
    "Enemy bell",    # attract wild encounters
})

# Single source of truth for non-key bank items. Names match the
# in-game ITEM_PARA strings exactly (preserves "Sup.restore" with
# the period, "Hispeed dsk" abbreviation, etc.). Order in this
# table is by ITEM_PARA slot so cross-reference with the BIN is
# trivial.
_BANK_ITEMS: Final[dict[str, ItemEntry]] = {
    name: ItemEntry(
        code,
        ItemClassification.useful if name in _USEFUL_ITEM_NAMES
        else ItemClassification.filler,
    )
    for name, code in (
        # ----- Heals (slots 0..14) -----
        ("SM Recovery",   2000), ("Med Recovery",  2001),
        ("Lrg Recovery",  2002), ("Sup Recovery",  2003),
        ("MP Floppy",     2004), ("Medium MP",     2005),
        ("Large MP",      2006), ("Double flop",   2007),
        ("Various",       2008), ("Omnipotent",    2009),
        ("Protection",    2010), ("Restore",       2011),
        ("Sup.restore",   2012), ("Bandage",       2013),
        ("Medicine",      2014),
        # ----- Battle-stat disks (slots 15..21) -----
        ("Off. Disk",     2015), ("Def. Disk",     2016),
        ("Hispeed dsk",   2017), ("Omni Disk",     2018),
        ("S.Off.disk",    2019), ("S.Def.disk",    2020),
        ("S.speed.disk",  2021),
        # slot 22 = Auto Pilot — omitted (already in starting inventory)
        # ----- Permanent stat-boost chips (slots 23..31) -----
        ("Off. Chip",     2023), ("Def. Chip",     2024),
        ("Brain Chip",    2025), ("Quick Chip",    2026),
        ("HP Chip",       2027), ("MP Chip",       2028),
        ("DV Chip A",     2029), ("DV Chip D",     2030),
        ("DV Chip E",     2031),
        # slot 32 = Port. potty — vending reward, omitted
        # ----- Useful (slots 33..37) -----
        ("Trn. manual",   2033), ("Rest pillow",   2034),
        ("Enemy repel",   2035), ("Enemy bell",    2036),
        ("Health shoe",   2037),
        # ----- Food (slots 38..47) -----
        ("Meat",          2038), ("Giant Meat",    2039),
        ("Sirloin",       2040), ("Supercarrot",   2041),
        ("Hawk radish",   2042), ("Spiny green",   2043),
        ("Digimushrm",    2044), ("Ice mushrm",    2045),
        ("Deluxmushrm",   2046), ("Digipine",      2047),
        # slot 48 = Blue apple — omitted (niche)
        # ----- Berries / fruits (slots 49..55) -----
        ("Red Berry",     2049),
        # slot 50 = Gold Acorn — omitted (sells for high price; niche)
        ("Big Berry",     2051), ("Sweet Nut",     2052),
        ("Super veggy",   2053),
        # slot 54 = Pricklypear — omitted (niche)
        ("Orange bana",   2055),
        # ----- Permanent stat-boost berries (slots 56..61) -----
        ("Power fruit",   2056), ("Power Ice",     2057),
        ("Speed Leaf",    2058), ("Sage Fruit",    2059),
        ("Muscle Yam",    2060), ("Calm berry",    2061),
        # ----- Fish (slots 62..67) -----
        ("Digianchovy",   2062), ("Digisnapper",   2063),
        ("DigiTrout",     2064), ("Black trout",   2065),
        ("Digicatfish",   2066), ("Digiseabass",   2067),
        # slot 68 = Moldy Meat, slot 69 = Happymushrm — both omitted
        # ----- Special (slot 70) -----
        ("Chain melon",   2070),
        # ----- DV items, Champion-tier (slots 71..98) -----
        ("Grey Claws",    2071), ("Fireball",      2072),
        ("Flamingwing",   2073), ("Iron Hoof",     2074),
        ("Mono Stone",    2075), ("Steel drill",   2076),
        ("White Fang",    2077), ("Black Wing",    2078),
        ("Spike Club",    2079), ("Flamingmane",   2080),
        ("White Wing",    2081), ("Torn tatter",   2082),
        # slot 83 = Electo ring (sentinel) — omitted
        ("Rainbowhorn",   2084), ("Rooster",       2085),
        ("Unihorn",       2086), ("Horn helmet",   2087),
        ("Scissor jaw",   2088), ("Fertilizer",    2089),
        ("Koga laws",     2090), ("Waterbottle",   2091),
        ("North Star",    2092), ("Red Shell",     2093),
        ("Hard Scale",    2094), ("Bluecrystal",   2095),
        ("Ice crystal",   2096), ("Hair grower",   2097),
        ("Sunglasses",    2098),
        # ----- DV items, Ultimate-tier (slots 99..110) -----
        ("Metal part",    2099), ("Fatal Bone",    2100),
        ("Cyber part",    2101), ("Mega Hand",     2102),
        ("Silver ball",   2103), ("Metal armor",   2104),
        ("Chainsaw",      2105), ("Small spear",   2106),
        ("X Bandage",     2107), ("Ray Gun",       2108),
        ("Gold banana",   2109), ("Mysty Egg",     2110),
        # slots 111-113 (Red Ruby, Beetlepearl, Coral charm) — Mega
        # tier, omitted from filler distribution to keep tiers
        # coherent
        # slot 114 = Moon mirror (sentinel) — omitted
    )
}

# Backward-compatible aliases used by other modules / tests.
_DV_ITEMS: Final[dict[str, ItemEntry]] = {
    name: entry for name, entry in _BANK_ITEMS.items()
    if 2071 <= entry.dw_code <= 2110
}
_CONSUMABLES: Final[dict[str, ItemEntry]] = {
    name: entry for name, entry in _BANK_ITEMS.items()
    if entry.dw_code < 2071 and name not in _USEFUL_ITEM_NAMES
}
_USEFUL_ITEMS: Final[dict[str, ItemEntry]] = {
    name: entry for name, entry in _BANK_ITEMS.items()
    if name in _USEFUL_ITEM_NAMES
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
# Phase 9 (2026-05-10): each ``Prosperity Point`` item is worth 3 PP.
# Pool size is sized by :func:`prosperity_point_count` from the player's
# ``prosperity_goal`` option (default 50 → 21 items, range
# 20–100 → 7–40 items). PP-gated logic in
# :mod:`worlds.digimon_world.rules` rounds the in-game PP threshold up
# to the nearest multiple of 3, so a "15 PP gate" becomes a "15 PP
# gate" requiring 5 items, and the Mt. Infinity gate (``threshold``)
# requires ``ceil(threshold / 3)`` items.

PROSPERITY_POINT_NAME: Final = "Prosperity Point"
# Phase 9 (2026-05-10): pool count is dynamic — sized to the player's
# ``prosperity_goal`` option via :func:`prosperity_point_count`.
# Each AP-delivered Prosperity Point item still bumps the in-game
# prosperity counter by ``PROSPERITY_PER_ITEM`` = 3.
PROSPERITY_PER_ITEM: Final = 3
PROSPERITY_OVERHEAD_FACTOR: Final = 1.2


def prosperity_point_count(threshold: int) -> int:
    """Return the AP pool size for ``Prosperity Point`` given a
    Mt. Infinity threshold.

    Sized as ``ceil(ceil(threshold / 3) * 1.2)`` — enough copies to
    reach the threshold (each item = 3 PP) plus a 20% comfort margin
    rounded up. AP fill needs the slack so the player isn't gated on
    every single PP copy being collected; this is the standard
    AP-game pattern for goal-threshold items.

    Locations whose vanilla PP gate exceeds the (un-margined)
    threshold are unreachable in-game; :func:`worlds.digimon_world.
    rules.set_all_rules` marks them EXCLUDED + filler-only and drops
    their PP gate from AP logic, so they don't pull the player into
    needing extra PP they can never collect.
    """

    import math

    return math.ceil(math.ceil(threshold / PROSPERITY_PER_ITEM) * PROSPERITY_OVERHEAD_FACTOR)

_PROSPERITY: Final[dict[str, ItemEntry]] = {
    PROSPERITY_POINT_NAME: ItemEntry(3003, ItemClassification.progression),
}


# =============================================================================
# Progressive Keychain — Nanimon-questline inventory expansion
# =============================================================================
# In vanilla DW1, completing the Nanimon questline grants two
# "Dimensional Key Chains" that bump the player's inventory size from
# 10 → 20 → 30 slots. AP turns this into a shuffled item: each
# Progressive Keychain received bumps the in-game inventory capacity
# by ``KEYCHAIN_INVENTORY_PER_ITEM`` (= 10), clamped at the vanilla
# structural max ``RAM_INVENTORY_MAX_SIZE`` (= 30). Two copies ship in
# the AP pool, classification ``useful`` — more inventory is a
# meaningful convenience but doesn't gate any AP logic.
#
# Client-side: :meth:`DigimonWorldClient._reconcile_keychain_inventory`
# pins :data:`RAM_INVENTORY_SIZE` to ``10 + 10 * min(received_count, 2)``
# every watcher tick. Vanilla's ``setInventorySize 20/30`` opcodes that
# fire during Nanimon site visits are clobbered on the next tick (brief
# 1-tick flicker, no UX issue — no item-pickup window during the
# cutscene).
#
# AP-side: 5 Nanimon Quest locations (one per Nanimon site) are checked
# via per-site setTrigger bits (333-337). Keychain items in the pool
# (2) < locations added (5), so the questline produces +3 net checks.

KEYCHAIN_ITEM_NAME: Final = "Progressive Keychain"
KEYCHAIN_COPIES_IN_POOL: Final = 2

_KEYCHAIN_ITEMS: Final[dict[str, ItemEntry]] = {
    KEYCHAIN_ITEM_NAME: ItemEntry(8000, ItemClassification.useful),
}


# =============================================================================
# Recruit items — individual + Progressive-bundled
# =============================================================================
#
# Phase 7 (2026-05-09) recruit-bundling rework. Per the recruitment
# guide and a per-Digimon role audit, only a handful of Digimon do
# things meaningful enough to warrant being individual progression
# items in AP. The bulk fall into one of six town-feature ladders:
# Item Shop, Secret Shop, Restaurant, Arena, Green Gym, Treasure Hunt.
# Those Digimon's individual ``<X> Recruit`` items are removed from
# the pool — their in-town visibility is unlocked instead by collecting
# the corresponding ``Progressive <Feature>`` item. Each Progressive
# delivery sets the BEATEN bits (720+X) for the Digimon in its tier;
# patched city-visibility scripts read those bits, so the bundled
# Digimon appear in town as the player progresses each ladder.
#
# Cross-reference: :data:`PROGRESSIVE_BUNDLES` (below) defines the per-
# Progressive-item tier table. The client's
# :meth:`_reconcile_recruits` reads it each tick to OR in the right
# bits.
#
# Individual recruit-item classifications are derived from the audit
# in the project memory note (the list below mirrors that). 18
# Digimon retain individual ``<X> Recruit`` AP items; the other 26
# (in :data:`_BUNDLED_RECRUITS`) are bundled into Progressive ladders.

# Individual classifications (dw_code base 1000 + digimon_id).
#
# Progression: gates AP logic in our world (see rules.py).
# Useful: does something meaningful in town but doesn't gate AP logic.
# Filler: in-town effect is purely cosmetic / "patrols the city".
_INDIVIDUAL_RECRUIT_CLASSIFICATIONS: Final[dict[str, ItemClassification]] = {
    # Progression — referenced in access rules
    "Whamon":      ItemClassification.progression,
    "Birdramon":   ItemClassification.progression,
    "Palmon":      ItemClassification.progression,
    "Shellmon":    ItemClassification.progression,
    "Centarumon":  ItemClassification.progression,
    # Useful — meaningful in-town role, no AP gate
    "Vegiemon":    ItemClassification.useful,
    "Kunemon":     ItemClassification.useful,
    "Etemon":      ItemClassification.useful,
    "Angemon":     ItemClassification.useful,
    "Ninjamon":    ItemClassification.useful,
    # Filler — "patrols the city" / "stands doing nothing"
    "Bakemon":     ItemClassification.filler,
    "Sukamon":     ItemClassification.filler,
    "Leomon":      ItemClassification.filler,
    "Andromon":    ItemClassification.filler,
    "Kokatorimon": ItemClassification.filler,
    "Monzaemon":   ItemClassification.filler,
    "Elecmon":     ItemClassification.filler,
    "Ogremon":     ItemClassification.filler,
}
assert len(_INDIVIDUAL_RECRUIT_CLASSIFICATIONS) == 18, len(_INDIVIDUAL_RECRUIT_CLASSIFICATIONS)

# Bundled Digimon — these have no individual ``<X> Recruit`` AP item.
# Their BEATEN bits (= city visibility) are set when the corresponding
# Progressive ladder item is delivered. See :data:`PROGRESSIVE_BUNDLES`.
_BUNDLED_RECRUITS: Final[frozenset[str]] = frozenset({
    name for name in AP_RECRUIT_ITEM_DIGIMON
    if name not in _INDIVIDUAL_RECRUIT_CLASSIFICATIONS
})
# 26 bundled recruits (Coelamon restored 2026-08-22 — his AP location
# is back, city visibility still rides Progressive Item Shop T1; he has
# no standalone ``Coelamon Recruit`` item, like every bundled recruit).
assert len(_BUNDLED_RECRUITS) == 26, len(_BUNDLED_RECRUITS)


def _digimon_id_from_recruit_bit(byte_addr: int, bit: int) -> int:
    """Recover digimon_id from the in-ROM recruit-completion bit pair."""

    trigger_id = (byte_addr - 0x001BDFCD) * 8 + bit
    return trigger_id - 200


# Individual AP items for the 18 non-bundled recruits.
_RECRUIT_ITEMS: Final[dict[str, ItemEntry]] = {
    f"{name} Recruit": ItemEntry(
        1000 + _digimon_id_from_recruit_bit(*RECRUIT_RAM_BITS[name]),
        classification,
    )
    for name, classification in _INDIVIDUAL_RECRUIT_CLASSIFICATIONS.items()
}
assert len(_RECRUIT_ITEMS) == 18, len(_RECRUIT_ITEMS)


# =============================================================================
# Progressive recruit-bundle items
# =============================================================================
#
# Each Progressive item ships N copies in the pool. When the Nth copy
# is received, all bundled Digimon up through tier N have their
# BEATEN bits set (idempotent OR-write — already-set bits stay set).
# This bundles many "this Digimon joined the city" recruit-bit grants
# behind a smaller number of meaningful progression items.
#
# Tier composition follows the recruitment guide's "what does this
# Digimon do" audit. Item Shop tiers were split so each tier mixes a
# Digimon that "creates the shop" (early-game accessible) with one
# that "joins the shop" (later). Secret Shop / Restaurant pair Digimon
# with similar accessibility. Arena tier 1 must be Greymon alone —
# vanilla DW1 won't open the Arena Lobby until Greymon is recruited.
# Green Gym and Treasure Hunt are 1-Digimon-per-tier because each
# only has 2 contributing Digimon.

PROGRESSIVE_BUNDLES: Final[dict[str, tuple[tuple[str, ...], ...]]] = {
    "Progressive Item Shop": (
        ("Betamon", "Coelamon"),                  # T1: shop creators
        ("Patamon", "Monochromon"),               # T2: shop joiners
        ("Biyomon", "Unimon", "Piximon"),         # T3: late-game + Piximon
    ),
    "Progressive Secret Shop": (
        ("Numemon", "Mojyamon"),                  # T1
        ("Mamemon", "Devimon"),                   # T2
    ),
    "Progressive Restaurant": (
        ("Meramon", "Tyrannomon"),                # T1: early chefs
        ("Frigimon", "Garurumon"),                # T2: Freezeland chefs
        ("Vademon", "Digitamamon"),               # T3: late + post-game
    ),
    "Progressive Arena": (
        # 3-tier ladder. Per the user's live testing 2026-05-28, the
        # arena cup-tier visibility responds to specific 200+X recruit-
        # block bits, which the client-side arena enforcer
        # (see :data:`worlds.digimon_world.data.addresses.ARENA_ENFORCER_*`)
        # sets while the player is on an arena screen. The Digimon listed
        # per tier still ship their normal recruit-bit (720+X) delivery
        # so they appear as File City NPCs as before; the new role is
        # gating the cup-tier AP locations and driving the enforcer.
        #
        # AP location gating in rules.py:
        #   Grade D AP locations -> Has("Progressive Arena", 1)
        #   Grade C AP locations -> Has("Progressive Arena", 2)
        #   Grade B/A/S AP locs  -> Has("Progressive Arena", 3)
        ("Greymon",),                                                  # T1: creates the Arena -> Grade D
        ("SkullGreymon", "Penguinmon"),                                # T2: Champion contestants -> Grade C
        ("MetalMamemon", "Megadramon", "MetalGreymon"),                # T3: Ultimates -> Grade B/A/S
    ),
    "Progressive Green Gym": (
        ("Kabuterimon",),                         # T1
        ("Kuwagamon",),                           # T2
    ),
    "Progressive Treasure Hunt": (
        ("Drimogemon",),                          # T1: creates shop
        ("Gabumon",),                             # T2: rare-find boost
    ),
}

_PROGRESSIVE_ITEMS: Final[dict[str, ItemEntry]] = {
    "Progressive Item Shop":      ItemEntry(6001, ItemClassification.progression),
    "Progressive Secret Shop":    ItemEntry(6002, ItemClassification.progression),
    "Progressive Restaurant":     ItemEntry(6003, ItemClassification.progression),
    "Progressive Arena":          ItemEntry(6004, ItemClassification.progression),
    "Progressive Green Gym":      ItemEntry(6005, ItemClassification.progression),
    "Progressive Treasure Hunt":  ItemEntry(6006, ItemClassification.progression),
}
assert set(_PROGRESSIVE_ITEMS) == set(PROGRESSIVE_BUNDLES), (
    "Progressive item table and bundle table must have the same keys"
)

# Pool-copy counts: ship one copy per tier.
PROGRESSIVE_COUNTS: Final[dict[str, int]] = {
    name: len(tiers) for name, tiers in PROGRESSIVE_BUNDLES.items()
}

# Sanity: every bundled Digimon must appear in exactly one tier of
# exactly one Progressive ladder.
_bundle_members = {
    name for tiers in PROGRESSIVE_BUNDLES.values() for tier in tiers for name in tier
}
# Digitamamon is in _AP_RECRUIT_EXCLUDED (post-game) but appears in
# Progressive Restaurant T3 as a side-flag — subtract him before the
# equality check. (Coelamon was in this subtraction while dropped
# 2026-05-24..2026-08-22; he is a regular bundled recruit again.)
assert _bundle_members - {"Digitamamon"} == _BUNDLED_RECRUITS, (
    f"Bundle membership mismatch: in-bundles={sorted(_bundle_members)}, "
    f"_BUNDLED_RECRUITS={sorted(_BUNDLED_RECRUITS)}"
)


# =============================================================================
# Birdramon flight destination items
# =============================================================================
# Each item unlocks one of Birdramon-Messenger's flight destinations. The
# vanilla destination table (6 entries) is patcher-rewritten so the gate
# triggers point at AP-controlled bits in `0x001BE03B` (trigger array gap
# region); see `data.addresses.BIRDRAMON_FLIGHT_RAM_BITS` and
# `ROM_BIRDRA_FLIGHT_TABLE_PATCHES`. G Canyon Top (vanilla trig 221 =
# Birdramon recruit) is left unpatched so it auto-unlocks with the
# Birdramon Recruit item -- that's why there are 5 of these and not 6.
#
# Phase 6: Promoted to **progression**. Each flight provides an
# alternative entrance to its destination region (in addition to the
# walking path), and AP rules treat the flight as a real
# progression-item gate. With both bridges in shuffled mode, several
# walking paths are AP-item-gated, so the flight items become the
# multiworld's only path to certain regions for many fills. See
# rules.py entrance rules and `dw1_birdramon_flight_gates` memory.
#
# Each flight requires Birdramon Recruit to function (the flight menu
# only opens once Birdramon is in the city).

_BIRDRAMON_FLIGHT_ITEMS: Final[dict[str, ItemEntry]] = {
    name: ItemEntry(4000 + i, ItemClassification.progression)
    for i, name in enumerate((
        "Birdramon Flight: Gear Savanna",
        "Birdramon Flight: Ancient Dino Region",
        "Birdramon Flight: Freezeland",
        "Birdramon Flight: Misty Trees",
        "Birdramon Flight: Beetle Land",
    ))
}
assert len(_BIRDRAMON_FLIGHT_ITEMS) == 5, len(_BIRDRAMON_FLIGHT_ITEMS)


# =============================================================================
# Technique mastery items
# =============================================================================
#
# One ``"Tech: <name>"`` item per player-masterable technique (56 entries
# total; slot 48 is the duplicate DW1 itself skips — see
# :data:`worlds.digimon_world.data.addresses.TECH_MASTERY_DUPLICATE_SLOT`).
# dw_code = 7000 + slot, in a previously-free range (1000 recruits, 2000
# bank, 3000 bits/PP, 4000 flights, 5000 virtual keys, 6000 progressives).
#
# All entries are always *defined* in the table so AP IDs stay stable
# across seeds. Only a per-seed subset of 20-30 actually enters the
# pool via :func:`choose_technique_pool` — see :func:`create_all_items`.
#
# Classification: ``useful``. Mastery is meaningful in combat (the bit
# adds the tech to the partner's active moveset, verified live
# 2026-05-11), but no AP-side logic gates on these items — they don't
# need to be ``progression``.

TECHNIQUE_ITEM_PREFIX: Final = "Tech: "
TECHNIQUE_ITEM_DW_CODE_BASE: Final = 7000


def _technique_item_name(slot: int) -> str:
    return TECHNIQUE_ITEM_PREFIX + TECH_NAMES_BY_SLOT[slot]


_TECHNIQUE_ITEMS: Final[dict[str, ItemEntry]] = {
    _technique_item_name(slot): ItemEntry(
        TECHNIQUE_ITEM_DW_CODE_BASE + slot,
        ItemClassification.useful,
    )
    for slot in TECH_MASTERY_SLOTS
}
assert len(_TECHNIQUE_ITEMS) == 56, len(_TECHNIQUE_ITEMS)


def technique_slot_for_item(item_name: str) -> int | None:
    """Return the tech slot id for a ``"Tech: <name>"`` item, or ``None``.

    Used by the client's deliverer factory and reconcile loop to map an
    AP-received item back to the mastery bit it should set.
    """

    entry = _TECHNIQUE_ITEMS.get(item_name)
    if entry is None:
        return None
    return entry.dw_code - TECHNIQUE_ITEM_DW_CODE_BASE


def choose_technique_pool(rng) -> list[str]:
    """Pick the per-seed subset of technique item names to ship.

    Sized as ``rng.randint(20, 30)`` and sampled uniformly from
    :data:`_TECHNIQUE_ITEMS` so each seed gets a different mix even
    with the same ``technique_rewards`` setting. Returns names in
    ``TECH_MASTERY_SLOTS`` order (ascending slot id) for deterministic
    iteration; callers that need a shuffled order should shuffle
    themselves.
    """

    count = rng.randint(20, 30)
    chosen_slots = rng.sample(list(TECH_MASTERY_SLOTS), count)
    chosen_slots.sort()
    return [_technique_item_name(s) for s in chosen_slots]


# =============================================================================
# Final assembled item table
# =============================================================================

_ITEM_TABLE: Final[dict[str, ItemEntry]] = {
    **_KEY_ITEMS,
    **_REGION_ACCESS_ITEMS,
    **_BANK_ITEMS,
    **_BITS,
    **_PROSPERITY,
    **_KEYCHAIN_ITEMS,
    **_RECRUIT_ITEMS,
    **_BIRDRAMON_FLIGHT_ITEMS,
    **_PROGRESSIVE_ITEMS,
    **_TECHNIQUE_ITEMS,
}
# Sanity: _BANK_ITEMS subsumes both _DV_ITEMS and _CONSUMABLES + _USEFUL_ITEMS,
# so the older aliased dicts must be subsets of the assembled table.
assert set(_DV_ITEMS) <= set(_ITEM_TABLE)
assert set(_CONSUMABLES) <= set(_ITEM_TABLE)
assert set(_USEFUL_ITEMS) <= set(_ITEM_TABLE)

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
    "Useful": set(_USEFUL_ITEMS),
    "Bits": set(_BITS),
    "Prosperity": set(_PROSPERITY),
    "Keychains": set(_KEYCHAIN_ITEMS),
    "Recruits": set(_RECRUIT_ITEMS),
    "Techniques": set(_TECHNIQUE_ITEMS),
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

# =============================================================================
# Filler distribution
# =============================================================================
#
# Phase 8 (2026-05-09) per-seed filler shaping. Filler slots in the AP
# pool are filled by sampling from named buckets in fixed proportions:
#
# * 15% — DV item to a Champion-tier digivolution (slots 71-98)
# * 10% — DV item to an Ultimate-tier digivolution (slots 99-110)
# * 10% — special pickups: Chain melon, Digiseabass
# * 20% — permanent stat-boost items: chips + permanent-effect berries
# * 10% — money: 1000 Bits or 5000 Bits
# * 35% — "mixed bag": battle-stat disks, heals, food, fish
#
# Per-bucket contents come straight from :data:`_BANK_ITEMS` /
# :data:`_BITS`. The proportions are quotas, not per-slot probabilities:
# :func:`build_filler_pool` rounds the targets to integers, randomly
# repairs rounding drift, then samples names within each bucket. This
# keeps the *shape* of every seed predictable while still randomizing
# which specific items appear.
#
# Items not in any bucket are intentionally never shipped as filler
# (Auto Pilot, Port. potty, Gold Acorn, etc., per the omissions
# documented at :data:`_BANK_ITEMS`).

_FILLER_DV_CHAMPION: Final[tuple[str, ...]] = tuple(
    name for name, entry in _BANK_ITEMS.items()
    if 2071 <= entry.dw_code <= 2098
)
_FILLER_DV_ULTIMATE: Final[tuple[str, ...]] = tuple(
    name for name, entry in _BANK_ITEMS.items()
    if 2099 <= entry.dw_code <= 2110
)
_FILLER_SPECIAL: Final[tuple[str, ...]] = ("Chain melon", "Digiseabass")
_FILLER_PERM_STAT_BOOST: Final[tuple[str, ...]] = (
    # Chips (slots 23..31)
    "Off. Chip", "Def. Chip", "Brain Chip", "Quick Chip", "HP Chip",
    "MP Chip", "DV Chip A", "DV Chip D", "DV Chip E",
    # Permanent stat-boost berries (slots 56..61)
    "Power fruit", "Power Ice", "Speed Leaf", "Sage Fruit", "Muscle Yam",
    "Calm berry",
)
_FILLER_MONEY: Final[tuple[str, ...]] = ("1000 Bits", "5000 Bits")
_FILLER_MIXED: Final[tuple[str, ...]] = (
    # Heals (slots 0..14)
    "SM Recovery", "Med Recovery", "Lrg Recovery", "Sup Recovery",
    "MP Floppy", "Medium MP", "Large MP", "Double flop",
    "Various", "Omnipotent", "Protection", "Restore",
    "Sup.restore", "Bandage", "Medicine",
    # Battle-stat disks (slots 15..21)
    "Off. Disk", "Def. Disk", "Hispeed dsk", "Omni Disk",
    "S.Off.disk", "S.Def.disk", "S.speed.disk",
    # Food (slots 38..47)
    "Meat", "Giant Meat", "Sirloin", "Supercarrot", "Hawk radish",
    "Spiny green", "Digimushrm", "Ice mushrm", "Deluxmushrm", "Digipine",
    # Non-permanent berries (slots 49..55, minus the perm-boost ones)
    "Red Berry", "Big Berry", "Sweet Nut", "Super veggy", "Orange bana",
    # Fish (slots 62..67) — Digiseabass is in _FILLER_SPECIAL, so skip it
    "Digianchovy", "Digisnapper", "DigiTrout", "Black trout", "Digicatfish",
)

# (bucket, weight) — weights must sum to 1.0.
FILLER_DISTRIBUTION: Final[tuple[tuple[tuple[str, ...], float], ...]] = (
    (_FILLER_DV_CHAMPION,     0.15),
    (_FILLER_DV_ULTIMATE,     0.10),
    (_FILLER_SPECIAL,         0.10),
    (_FILLER_PERM_STAT_BOOST, 0.20),
    (_FILLER_MONEY,           0.10),
    (_FILLER_MIXED,           0.35),
)
assert abs(sum(w for _, w in FILLER_DISTRIBUTION) - 1.0) < 1e-9
# Every item in every bucket must be a real shippable AP item.
for _bucket, _ in FILLER_DISTRIBUTION:
    for _name in _bucket:
        assert _name in _BANK_ITEMS or _name in _BITS, _name


def build_filler_pool(rng, count: int) -> list[str]:
    """Build a shuffled list of ``count`` filler item names whose bucket
    proportions track :data:`FILLER_DISTRIBUTION`.

    Rounding drift (e.g., ``count * 0.15`` is non-integer) is repaired by
    bumping or trimming buckets at random until ``sum(targets) == count``.
    Within each bucket the name is picked uniformly with replacement, so
    duplicates within a bucket are expected and intentional (filler
    diversity is a side effect, not a guarantee).
    """

    if count <= 0:
        return []
    targets: list[list] = [
        [bucket, int(round(count * weight))]
        for bucket, weight in FILLER_DISTRIBUTION
    ]
    delta = count - sum(t[1] for t in targets)
    while delta > 0:
        targets[rng.randrange(len(targets))][1] += 1
        delta -= 1
    while delta < 0:
        idx = rng.randrange(len(targets))
        if targets[idx][1] > 0:
            targets[idx][1] -= 1
            delta += 1
    pool: list[str] = []
    for bucket, target in targets:
        for _ in range(target):
            pool.append(rng.choice(bucket))
    rng.shuffle(pool)
    return pool


def pick_random_filler(rng) -> str:
    """Return a single filler item name sampled from
    :data:`FILLER_DISTRIBUTION`. Used by ``World.get_filler_item_name``
    so AP-internal filler insertions follow the same shape."""

    bucket = rng.choices(
        [b for b, _ in FILLER_DISTRIBUTION],
        weights=[w for _, w in FILLER_DISTRIBUTION],
        k=1,
    )[0]
    return rng.choice(bucket)


# Stable fallback. Used by :data:`FILLER_ITEM_NAME` consumers that need a
# single deterministic name (e.g., test fixtures); all real pool insertion
# now goes through :func:`build_filler_pool`.
FILLER_ITEM_NAME: Final = "1000 Bits"


# =============================================================================
# Itempool construction
# =============================================================================
# Pool composition (Phase 8):
#
# 1. **Mandatory** (progression + flight unlocks + Progressive bundles
#    + Prosperity Points). Always shipped one copy per item except
#    Prosperity Point and Progressive items (multi-copy).
# 2. **Useful** (the 5 ``_USEFUL_ITEMS``). Shipped one copy each.
# 3. **Filler** — fills any remaining capacity via
#    :func:`build_filler_pool`, which respects
#    :data:`FILLER_DISTRIBUTION` proportions per seed.


def get_bootstrap_items(world: DigimonWorldWorld) -> tuple[str, ...]:
    """Items that should be pre-collected (start_inventory) for this
    world, computed from the options.

    Single source of truth for :meth:`world.DigimonWorldWorld.generate_early`
    (which calls ``push_precollected`` for each name) and
    :func:`create_all_items` (which skips these from the pool to avoid
    double-shipping). Order doesn't matter; the caller treats it as a set.

    Only fires when ``region_locking == all``. Under ``off`` and
    ``custom``, the player walks out of File City through whatever
    isn't locked and no bootstrap is needed.

    Per-:class:`options.StartingRegion` kit:

    * ``native_forest`` → ``("Native Forest Region Access",)`` —
      vanilla-style start, walks File City → Native Forest.
    * ``gear_savanna``, ``ancient_dino_region``, ``freezeland``,
      ``misty_trees``, ``beetle_land`` → ``("Birdramon Recruit",
      "Birdramon Flight: <region>", "<region> Region Access")`` —
      fly in via Birdra-Messenger.
    * ``great_canyon`` → ``("Birdramon Recruit", "Great Canyon Region
      Access")`` — no separate Flight item ("G Canyon Top" auto-
      unlocks on Birdramon Recruit, per :data:`worlds.digimon_world.data.addresses.BIRDRAMON_FLIGHT_RAM_BITS`).
    * ``factorial_town`` → ``("Whamon Recruit", "Factorial Town
      Region Access")`` — Whamon's ferry, asymmetric with Birdramon.
    """

    from .options import RegionLocking, get_starting_region_name

    if int(world.options.region_locking.value) != RegionLocking.option_all:
        return ()

    region = get_starting_region_name(world.options)
    access = region_access_item_name(region)

    if region == "Native Forest":
        return (access,)
    if region == "Great Canyon":
        # G Canyon Top auto-unlocks on Birdramon Recruit; no Flight item.
        return ("Birdramon Recruit", access)
    if region == "Factorial Town":
        # Whamon ferry, not Birdramon.
        return ("Whamon Recruit", access)
    # The remaining 5 Birdramon-flight destinations.
    return ("Birdramon Recruit", f"Birdramon Flight: {region}", access)


def create_item(world: DigimonWorldWorld, name: str) -> DigimonWorldItem:
    entry = _ITEM_TABLE[name]
    return DigimonWorldItem(name, entry.classification, ITEM_NAME_TO_ID[name], world.player)


def create_all_items(world: DigimonWorldWorld) -> None:
    """Submit the Phase 8 itempool sized to the location count."""

    locations_count = len(world.multiworld.get_unfilled_locations(world.player))

    # Several "virtual access" key items only ship in their corresponding
    # ``shuffled`` mode; in other modes (vanilla / always_open) the gate
    # is handled differently and there's no AP item/location pair.
    skip_keys: set[str] = set()
    if int(world.options.lava_cave_access.value) == 0:  # 0 = vanilla
        skip_keys.add("Lava Cave Access")
    # BridgeUnlock / GreatCanyonUnlock: 0=always_open, 1=vanilla, 2=shuffled.
    # The AP item only exists in shuffled (=2).
    if int(world.options.bridge_unlock.value) != 2:
        skip_keys.add("Tropical Jungle Bridge")
    if int(world.options.great_canyon_unlock.value) != 2:
        skip_keys.add("Great Canyon Bridge")
    # FactorialGateUnlock: same encoding; the door item only exists in
    # shuffled (=2) — always_open pins the bit client-side instead.
    if int(world.options.factorial_gate.value) != 2:
        skip_keys.add("Factorial Town Gate")

    pool: list[Item] = []
    # Compute the bootstrap set once — anything in it is pre-collected
    # (start_inventory) and must NOT also be shipped in the pool. The
    # set may contain Region Access items, Birdramon Recruit, Birdramon
    # Flight: <region> entries, and/or Whamon Recruit depending on the
    # ``starting_region`` option (and only when ``region_locking == all``).
    from .options import get_locked_regions
    bootstrap = set(get_bootstrap_items(world))

    pool.extend(world.create_item(name) for name in _KEY_ITEMS if name not in skip_keys)
    # Region Access items — one per locked region under the
    # ``region_locking`` option, MINUS bootstrap. Empty set under ``off``;
    # full :data:`LOCKABLE_REGIONS` under ``all`` (minus bootstrap);
    # the user's subset under ``custom``.
    for region in get_locked_regions(world.options):
        name = region_access_item_name(region)
        if name in bootstrap:
            continue
        pool.append(world.create_item(name))
    # Recruit items are always shuffled into the multiworld pool, except
    # any that the bootstrap kit pre-collected (Birdramon / Whamon for
    # the non-Native-Forest StartingRegion kits). The
    # ``recruit_randomization`` option was removed 2026-05-24 — its
    # "off" mode (self-locked recruits) was incompatible with Progressive
    # ladder items and other Phase 7+ randomization features.
    pool.extend(
        world.create_item(name) for name in _RECRUIT_ITEMS if name not in bootstrap
    )
    pool.extend(
        world.create_item(name) for name in _BIRDRAMON_FLIGHT_ITEMS
        if name not in bootstrap
    )
    pp_count = prosperity_point_count(int(world.options.prosperity_goal.value))
    pool.extend(
        world.create_item(PROSPERITY_POINT_NAME)
        for _ in range(pp_count)
    )
    # Progressive recruit-bundle items — ship one copy per tier per
    # ladder. Each delivery sets the BEATEN bits for the Digimon in
    # tier ``count`` (handled by ``_reconcile_recruits`` in the client).
    for name, copies in PROGRESSIVE_COUNTS.items():
        pool.extend(world.create_item(name) for _ in range(copies))

    # Progressive Keychain — 2 fixed copies, useful. Each delivery
    # bumps the in-game inventory cap by 10 (client reconciles
    # RAM_INVENTORY_SIZE each tick from the received count). The
    # questline contributes 5 AP locations against these 2 items.
    pool.extend(
        world.create_item(KEYCHAIN_ITEM_NAME)
        for _ in range(KEYCHAIN_COPIES_IN_POOL)
    )

    if len(pool) > locations_count:
        raise ValueError(
            f"Mandatory items ({len(pool)}) exceed unfilled locations "
            f"({locations_count}); lower prosperity_goal, expand "
            f"the location pool, or reduce some of the other mandatory "
            f"item categories.",
        )

    # Useful items — one copy each. If the seed is too small to fit
    # them all, drop from the back of the table; tests/the resolver
    # treat the useful set as best-effort, not mandatory.
    for name in _USEFUL_ITEMS:
        if len(pool) >= locations_count:
            break
        pool.append(world.create_item(name))

    # Technique items — when ``technique_rewards`` is set to
    # ``ap_items``, ship one copy of each of the per-seed random subset
    # picked by :func:`choose_technique_pool` (20-30 names). Like the
    # generic useful set, treated as best-effort: if the seed is too
    # small to fit them all, drop trailing entries.
    if int(world.options.technique_rewards.value) == 1:  # ap_items
        for name in choose_technique_pool(world.random):
            if len(pool) >= locations_count:
                break
            pool.append(world.create_item(name))

    # Fill the rest with the proportional filler distribution.
    remaining = locations_count - len(pool)
    pool.extend(
        world.create_item(name)
        for name in build_filler_pool(world.random, remaining)
    )

    assert len(pool) == locations_count, (len(pool), locations_count)
    world.multiworld.itempool += pool
