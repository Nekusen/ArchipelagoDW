"""Location table for the Digimon World 1 APWorld (Phase 4 v7).

Location IDs use DWAP's ``base_id = 69_000_000`` convention, partitioned
the same way:

* ``69_001_xxx`` — chests (65)
* ``69_002_xxx`` — cards (66, opt-in via :class:`worlds.digimon_world.options.CardLocations`)
* ``69_003_xxx`` — start-game / starter pickup (1)
* ``69_004_xxx`` — reserved (was prosperity NPC gifts; gone in v7)
* ``69_005_xxx``..``69_054_xxx`` — recruit checks, one Digimon per 1000-block
* ``69_055_xxx`` — vending machines (12, opt-in via :class:`worlds.digimon_world.options.VendingLocations`)
* ``69_056_xxx`` — recycle shop slots (7, opt-in via :class:`worlds.digimon_world.options.RecycleShopLocations`)
* ``69_057_xxx`` — merit shop slots (14, opt-in via :class:`worlds.digimon_world.options.MeritShopLocations`)
* ``69_058_xxx`` — fishing fish catches (6, opt-in via :class:`worlds.digimon_world.options.FishingLocations`)
* ``69_059_xxx`` — Nanimon Quest sites (5, always on)
* ``69_060_xxx`` — Arena Cup grade-tier wins (20 = 5 tiers x 4 checks, always on)

Locked v1 MVP scope: chests + recruits + starter. NPC-gift "K Prosperity"
locations are gone — prosperity is now a real AP item shipped in the
pool, with the in-game prosperity counter enforced client-side from the
count of delivered ``Prosperity Point`` items.

Recruit AP locations cover all 50 Digimon. The shuffleable subset (38)
gets a closed-shuffle trigger remap at patch time so the player sees a
randomized recruit roster as they explore. The 12 non-shuffleable
Digimon retain vanilla recruits. AP detection of "encounter completed"
works the same way for both groups: poll the vanilla recruit-bit byte.

Each recruit AP location is named after the spawn-point Digimon. AP
fires the location when that spawn's encounter is won, regardless of
which Digimon trigger-remap actually puts in city.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, NamedTuple

from BaseClasses import ItemClassification, Location, LocationProgressType

from .data.addresses import (
    ARENA_CUP_LOCATIONS_PER_TIER,
    ARENA_CUP_TIERS,
    CARD_LOCATION_NIBBLES,
    FISHING_LOCATION_NAMES,
    MERIT_SHOP_LOCATION_NAMES,
    NANIMON_QUEST_LOCATION_RAM_BITS,
    RECYCLE_SHOP_LOCATION_NAMES,
    VENDING_LOCATION_NAMES,
    VENDING_LOCATION_REGIONS,
)

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


class DigimonWorldLocation(Location):
    game = "Digimon World"


class LocationEntry(NamedTuple):
    id: int
    region: str


# =============================================================================
# Recruit locations (50)
# =============================================================================
# Order and per-Digimon AP-id offsets follow DWAP's
# Locations.py:69-118 (e.g. Agumon = 69_005_000, Betamon = 69_006_000, ...,
# Ninjamon = 69_054_000). Region assignment reflects the recruitment-flowchart
# transcription in references/dw1_recruitment_logic.md and DW1 map knowledge.

# Phase 6 region assignments (cross-checked vs almarsguides + community
# guides; see references/recruit_logic_phase5.md and the Phase 6 design
# doc).
#
# Two recruits are dropped from the AP location pool:
#
# * **Agumon** — bank NPC, force-recruited by the client. Pre-setting his
#   bit blocks the wild-Agumon-fight spawn, so the AP location can never
#   fire. See ``client.DigimonWorldClient._enforce_agumon_recruited``.
# * **Digitamamon** — post-game optional goal (only reachable after
#   defeating Machinedramon + reload + return to final chamber). Per
#   user direction: not an AP location.
#
# Names match :data:`addresses.RECRUIT_RAM_BITS` keys exactly (note the
# in-repo spelling "Vegiemon" — the in-game item table uses that form).
_RECRUIT_REGIONS: Final[dict[str, str]] = {
    # Airdramon (formerly a "File City" recruit) was dropped 2026-05-08
    # — see addresses.py ``_AP_RECRUIT_EXCLUDED``. Greymon is back in
    # the AP pool with his original 15-PP File-City placement.
    # File City
    "Greymon":      "File City",
    # Native Forest
    "Palmon":       "Native Forest",
    "Kunemon":      "Native Forest",
    # Coelamon dropped 2026-05-24 — his recruit cutscene is bugged in
    # the current build and the fix would be too costly. See
    # addresses.py ``_AP_RECRUIT_EXCLUDED``.
    # Seadramon dropped 2026-05-09 (the cutscene IS the Blue Flute
    # pickup; he doesn't really do anything in town). See addresses.py
    # ``_AP_RECRUIT_EXCLUDED``. The cutscene now fires the
    # ``Blue Flute Pickup`` keyitem AP location instead.
    "Ninjamon":     "Native Forest",
    "Etemon":       "Native Forest",
    # Tropical Jungle
    "Betamon":      "Tropical Jungle",
    "Vegiemon":     "Tropical Jungle",
    "Centarumon":   "Tropical Jungle",
    "Piximon":      "Tropical Jungle",
    # Overdell
    "Bakemon":      "Overdell",
    "SkullGreymon": "Overdell",
    # Ancient Dino Region
    "Tyrannomon":   "Ancient Dino Region",
    # Beetle Land
    "Kabuterimon":  "Beetle Land",
    "Kuwagamon":    "Beetle Land",
    # Great Canyon
    "Birdramon":    "Great Canyon",
    "Monochromon":  "Great Canyon",
    "Shellmon":     "Great Canyon",
    "Ogremon":      "Great Canyon",
    # Freezeland
    "Frigimon":     "Freezeland",
    "Mojyamon":     "Freezeland",
    "Penguinmon":   "Freezeland",
    "Garurumon":    "Freezeland",
    "Angemon":      "Freezeland",
    "Whamon":       "Freezeland",
    # Drill Tunnel
    "Drimogemon":   "Drill Tunnel",
    # Meramon Tunnel
    "Meramon":      "Meramon Tunnel",
    # Mt. Panorama
    "Unimon":       "Mt. Panorama",
    "Mamemon":      "Mt. Panorama",
    "Vademon":      "Mt. Panorama",
    # Gear Savanna
    "Patamon":      "Gear Savanna",
    "Biyomon":      "Gear Savanna",
    "Elecmon":      "Gear Savanna",
    "Sukamon":      "Gear Savanna",
    "Leomon":       "Gear Savanna",
    # Misty Trees
    "Gabumon":      "Misty Trees",
    "Kokatorimon":  "Misty Trees",
    # Toy Town
    "Monzaemon":    "Toy Town",
    # Nanimon dropped 2026-05-09 (per the recruitment guide, Nanimon
    # drops keychains but never actually joins the city as an NPC).
    # Factorial Town
    "Numemon":      "Factorial Town",
    "Andromon":     "Factorial Town",
    # Giromon dropped 2026-05-09 — his Restaurant Jukebox effect
    # crashes the NTSC (US) build per the guide.
    "MetalMamemon": "Factorial Town",
    # Mt. Infinity recruits dropped 2026-05-27 — all three (Devimon,
    # Megadramon, MetalGreymon) get their recruit bits set by the
    # post-Machinedramon state machine, NOT by reachable natural-route
    # encounters under the default Machinedramon goal. See addresses.py
    # ``_AP_RECRUIT_EXCLUDED`` for the chronology evidence. Kept commented
    # below for future post-game goal modes.
    # "Devimon":      "Mt. Infinity",
    # "Megadramon":   "Mt. Infinity",
    # "MetalGreymon": "Mt. Infinity",
}

_RECRUIT_DW_IDS: Final[dict[str, int]] = {
    "Betamon": 69_006_000, "Greymon": 69_007_000,
    "Devimon": 69_008_000, "Airdramon": 69_009_000, "Tyrannomon": 69_010_000,
    "Meramon": 69_011_000, "Seadramon": 69_012_000, "Numemon": 69_013_000,
    "MetalGreymon": 69_014_000, "Mamemon": 69_015_000, "Monzaemon": 69_016_000,
    "Gabumon": 69_017_000, "Elecmon": 69_018_000, "Kabuterimon": 69_019_000,
    "Angemon": 69_020_000, "Birdramon": 69_021_000, "Garurumon": 69_022_000,
    "Frigimon": 69_023_000, "Whamon": 69_024_000, "Vegiemon": 69_025_000,
    "SkullGreymon": 69_026_000, "MetalMamemon": 69_027_000, "Vademon": 69_028_000,
    "Patamon": 69_029_000, "Kunemon": 69_030_000, "Unimon": 69_031_000,
    "Ogremon": 69_032_000, "Shellmon": 69_033_000, "Centarumon": 69_034_000,
    "Bakemon": 69_035_000, "Drimogemon": 69_036_000, "Sukamon": 69_037_000,
    "Andromon": 69_038_000, "Giromon": 69_039_000, "Etemon": 69_040_000,
    "Biyomon": 69_041_000, "Palmon": 69_042_000, "Monochromon": 69_043_000,
    "Leomon": 69_044_000, "Coelamon": 69_045_000, "Kokatorimon": 69_046_000,
    "Kuwagamon": 69_047_000, "Mojyamon": 69_048_000, "Nanimon": 69_049_000,
    "Megadramon": 69_050_000, "Piximon": 69_051_000,
    # 69_052_000 reserved (was Digitamamon — now dropped)
    "Penguinmon": 69_053_000, "Ninjamon": 69_054_000,
}

RECRUIT_NAMES: Final[tuple[str, ...]] = tuple(_RECRUIT_REGIONS)
# 50 vanilla recruits minus Agumon (force-recruited bank NPC), minus
# Digitamamon (post-game optional goal), minus Airdramon (dropped
# 2026-05-08), minus Seadramon (dropped 2026-05-09 — recruit cutscene
# is the Blue Flute pickup), minus Nanimon and Giromon (dropped
# 2026-05-09 — Nanimon never joins the city, Giromon's Jukebox crashes
# the NTSC build), minus Coelamon (dropped 2026-05-24 — recruit cutscene
# is bugged in the current build, fix deferred), minus all 3 Mt. Infinity
# recruits Devimon/Megadramon/MetalGreymon (dropped 2026-05-27 — their
# recruit bits get set post-Machinedramon, after the goal would have
# already fired). See addresses.py ``_AP_RECRUIT_EXCLUDED``.
assert len(RECRUIT_NAMES) == 40, len(RECRUIT_NAMES)


# =============================================================================
# Recruit PP requirements (Phase 5 logic map)
# =============================================================================
# Per-recruit Prosperity Point gate, supplied by the user. The rule
# applied at each recruit AP location is
# ``Has("Prosperity Point", count=N)`` where N is the value below.
# Recruits at 0 PP have no rule (always logically reachable).

RECRUIT_PP_REQUIREMENTS: Final[dict[str, int]] = {
    # 0 PP — most recruits (Agumon, Digitamamon dropped from pool entirely)
    "Palmon": 0,
    "Kunemon": 0,
    # Coelamon dropped 2026-05-24 — see _RECRUIT_REGIONS comment.
    # Seadramon dropped 2026-05-09 — see _RECRUIT_REGIONS comment.
    "Betamon": 0,
    "Vegiemon": 0,
    "Centarumon": 0,
    "Piximon": 0,
    "Bakemon": 0,
    "Tyrannomon": 0,
    "Kabuterimon": 0,
    "Kuwagamon": 0,
    "Birdramon": 0,
    "Monochromon": 0,
    "Shellmon": 0,
    "Ogremon": 0,
    "Frigimon": 0,
    "Mojyamon": 0,
    "Penguinmon": 0,
    "Garurumon": 0,
    "Angemon": 0,
    "Whamon": 0,
    "Drimogemon": 0,
    "Meramon": 0,
    "Unimon": 0,
    "Mamemon": 0,
    "Patamon": 0,
    "Biyomon": 0,
    "Elecmon": 0,
    "Sukamon": 0,
    "Gabumon": 0,
    "Kokatorimon": 0,
    "Monzaemon": 0,
    "Nanimon": 0,
    "Numemon": 0,
    "Giromon": 0,
    "MetalMamemon": 0,
    # 15 PP
    "Greymon": 15,
    # Andromon: vanilla in-game gate is technically 0 PP, but practically
    # the recruit requires 4 specific File City buildings whose collective
    # PP cost lands around 15. Modeled as a 15 PP gate so
    # ``_apply_pp_cutoffs`` correctly excludes Andromon when
    # ``prosperity_goal < 15``.
    "Andromon": 15,
    # 40 PP
    "SkullGreymon": 40,
    # 45 PP
    "Leomon": 45,
    "Vademon": 45,
    # 50 PP
    # "Airdramon": 50,  # dropped 2026-05-08
    "Etemon": 50,
    "Ninjamon": 50,
    # Mt. Infinity recruits dropped 2026-05-27 — see _RECRUIT_REGIONS
    # comment. PP gates kept commented out for the future post-game
    # goal mode.
    # "Devimon": 50,
    # "Megadramon": 50,
    # "MetalGreymon": 50,
}


# =============================================================================
# Chest list (65 entries, region-aware naming)
# =============================================================================
# Names follow the chest-mapping document
# (``references/chest_mapping_phase5.md``). DWAP slot indices 1..65 are
# preserved as AP IDs (``69_001_000`` + slot-1) so the wire format stays
# stable. Each slot has been verified against script + screen + DWAP
# label + room-code (BIN MAP filename) as of the 2026-05-09 audit;
# every chest gets a descriptive ``Chest: <Area> [N]`` name, no
# bare ``Chest N`` placeholders remain.
#
# The region used here is the **chest's in-game region**. AP framework
# inherits the region's entrance access rule onto every location inside
# it (see :func:`create_all_locations` + the entrance rules in
# :mod:`.rules`), so each chest's reachability is exactly its region's
# reachability.

# slot 1..65 → (chest name, in-game region or None)
#
# As of the 2026-05-09 audit (script + screen + DWAP + dialog cross-
# reference; see the chest workflow in this module's docstring), every
# chest has a confirmed region. The ``None`` sentinel is kept for any
# future regression where a new chest is added before its location is
# verified — in that case AP fill restricts placement to filler via
# ``LocationProgressType.EXCLUDED`` (see :func:`create_all_locations`).
#
# Chests in :data:`_POSTGAME_CHEST_REGIONS` are also flagged EXCLUDED:
# they're reachable in AP logic but only after the player has already
# beaten Machinedramon, by which point under the default goal the seed
# is already complete and the player has no incentive to return.
_CHEST_BY_SLOT: Final[dict[int, tuple[str, str | None]]] = {
    1:  ("Chest: Grey Lord's Mansion 4",  "Grey Lord's Mansion"),
    2:  ("Chest: Grey Lord's Mansion 5",  "Grey Lord's Mansion"),
    3:  ("Chest: Grey Lord's Mansion 6",  "Grey Lord's Mansion"),
    4:  ("Chest: Grey Lord's Mansion 1",  "Overdell"),
    5:  ("Chest: Grey Lord's Mansion 7",  "Grey Lord's Mansion"),
    6:  ("Chest: Grey Lord's Mansion 8",  "Grey Lord's Mansion"),
    7:  ("Chest: Grey Lord's Mansion 9",  "Grey Lord's Mansion"),
    8:  ("Chest: Ice Sanctuary 1",        "Freezeland"),
    # Slots 9 and 10 (Lava Cave 5 / 6) were removed 2026-05-24 — the
    # in-game chests do not exist in any reachable area (suspected
    # debug / cut content). Slot numbers are preserved as gaps so the
    # wire-format IDs (69_001_008 / 69_001_009) stay reserved and the
    # remaining chests keep their stable IDs.
    11: ("Chest: Ice Sanctuary 2",        "Freezeland"),
    12: ("Chest: Ice Sanctuary 3",        "Freezeland"),
    13: ("Chest: Ice Sanctuary 4",        "Freezeland"),
    14: ("Chest: Ice Sanctuary 5",        "Freezeland"),
    15: ("Chest: Ice Sanctuary 6",        "Freezeland"),
    16: ("Chest: Ice Sanctuary 7",        "Freezeland"),
    17: ("Chest: Great Canyon 1",         "Great Canyon"),
    18: ("Chest: Leomon Ancestor Cave",   "Leomon Ancestor Cave"),
    19: ("Chest: Toy Mansion",            "Toy Town"),
    20: ("Chest: Ogre Fortress 1",        "Great Canyon"),
    21: ("Chest: Ogre Fortress 2",        "Great Canyon"),
    22: ("Chest: Ogre Fortress 3",        "Great Canyon"),
    23: ("Chest: Secret Beach Cave",      "Secret Beach Cave"),
    24: ("Chest: Ogre Fortress 4",        "Great Canyon"),
    25: ("Chest: Ogre Fortress 5",        "Great Canyon"),
    26: ("Chest: Ogre Fortress 6",        "Great Canyon"),
    27: ("Chest: Lava Cave 1",            "Meramon Tunnel"),
    28: ("Chest: Factorial Town 1",       "Factorial Town"),
    29: ("Chest: Factorial Town 2",       "Factorial Town"),
    30: ("Chest: Lava Cave 2",            "Meramon Tunnel"),
    31: ("Chest: Mt. Infinity 1",         "Mt. Infinity"),
    32: ("Chest: Mt. Infinity 2",         "Mt. Infinity"),
    33: ("Chest: Mt. Infinity 3",         "Mt. Infinity"),
    34: ("Chest: Ogre Fortress 7",        "Great Canyon"),
    35: ("Chest: Mt. Infinity 4",         "Mt. Infinity"),
    36: ("Chest: Mt. Infinity 5",         "Mt. Infinity"),
    37: ("Chest: Mt. Infinity 6",         "Mt. Infinity"),
    38: ("Chest: Mt. Infinity 7",         "Mt. Infinity"),
    39: ("Chest: Mt. Infinity 8",         "Mt. Infinity"),
    40: ("Chest: Mt. Infinity 9",         "Mt. Infinity"),
    41: ("Chest: Mt. Infinity 10",        "Mt. Infinity"),
    42: ("Chest: Mt. Infinity 11",        "Mt. Infinity"),
    43: ("Chest: Tropical Jungle",        "Tropical Jungle"),
    44: ("Chest: Lava Cave 3",            "Meramon Tunnel"),
    45: ("Chest: Lava Cave 4",            "Meramon Tunnel"),
    46: ("Chest: Mt. Panorama 1",         "Mt. Panorama"),
    47: ("Chest: Mt. Panorama 2",         "Mt. Panorama"),
    48: ("Chest: Mt. Panorama 3",         "Mt. Panorama"),
    49: ("Chest: Grey Lord's Mansion 10", "Grey Lord's Mansion"),
    50: ("Chest: Grey Lord's Mansion 11", "Grey Lord's Mansion"),
    51: ("Chest: Grey Lord's Mansion 12", "Grey Lord's Mansion"),
    52: ("Chest: Grey Lord's Mansion 13", "Grey Lord's Mansion"),
    53: ("Chest: Grey Lord's Mansion 2",  "Overdell"),
    54: ("Chest: Grey Lord's Mansion 3",  "Overdell"),
    55: ("Chest: Dragon Eye Lake",        "Greatlake"),
    56: ("Chest: Back Dimension 1",       "Back Dimension"),
    57: ("Chest: Back Dimension 2",       "Back Dimension"),
    58: ("Chest: Back Dimension 3",       "Back Dimension"),
    59: ("Chest: Back Dimension 4",       "Back Dimension"),
    60: ("Chest: Back Dimension 5",       "Back Dimension"),
    61: ("Chest: Back Dimension 6",       "Back Dimension"),
    62: ("Chest: Back Dimension 7",       "Back Dimension"),
    63: ("Chest: Factorial Town 3",       "Factorial Town"),
    64: ("Chest: Factorial Town 4",       "Factorial Town"),
    65: ("Chest: Factorial Town 5",       "Factorial Town"),
}
# 63 = 65 - 2 (slots 9, 10 = Lava Cave 5, 6 removed 2026-05-24; chests
# don't exist in any reachable area).
assert len(_CHEST_BY_SLOT) == 63
assert len({name for name, _ in _CHEST_BY_SLOT.values()}) == 63, "duplicate chest names"

# Confirmed chests live in their actual in-game region so AP region
# access drives the per-chest reachability rule (e.g. a chest in
# ``Mt. Panorama`` requires Lava Cave Access transitively, a chest in
# ``Grey Lord's Mansion`` requires Mansion Key, etc.). Unconfirmed
# chests (region = None) fall back to ``File City`` (always reachable
# from start) and are flagged ``LocationProgressType.EXCLUDED`` in
# :func:`create_all_locations` so they only ever hold filler / useful
# / trap items — fill never sends progression to a chest whose
# physical location hasn't been verified.
_CHEST_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_001_000 + _slot - 1, region or "File City")
    for _slot, (name, region) in _CHEST_BY_SLOT.items()
}

CHEST_NAMES: Final[tuple[str, ...]] = tuple(_CHEST_LOCATIONS)
assert len(CHEST_NAMES) == 63, len(CHEST_NAMES)

# Regions whose chests are only reachable post-game (after Machinedramon
# defeat). Their chests are flagged ``LocationProgressType.EXCLUDED`` so
# AP fill never places progression items there — under the default
# Machinedramon goal the player wins before they'd ever return.
_POSTGAME_CHEST_REGIONS: Final[frozenset[str]] = frozenset({
    "Back Dimension",
})


# =============================================================================
# Key-item pickups
# =============================================================================
# Currently wired: Old Fishrod (Trash Mountain in Gear Savanna), Mansion
# Key (Grey Lord's Mansion foyer — placed in Overdell because the
# pickup site is in a non-key-gated area), Frig Key (Myotismon dialog
# inside Grey Lord's Mansion proper, gated on Mansion Key by region
# wiring), Gear (Toy Town WaruMonzaemon defeat cutscene), Rain Plant
# (Tanemon planter in Native Forest, gated on Palmon Recruit and
# day-15 timer), Blue Flute (Seadramon friendship cutscene from
# fishing in Greatlake; replaces the dropped Seadramon recruit
# location), Leomonstone (Leomon's Ancestral Cave in Drill Tunnel
# B3F, gated on Prosperity 45 since the cave entrance only opens
# after Drimogemon digs through). Only Amazing Rod remains to be
# wired up.
#
# Steak is NOT an AP location: vanilla DW1 spawns Steak from the
# Overdell fridge interaction (gated on Frig Key) and it is left
# entirely on the vanilla path.
#
# Note: ``Lava Cave Access``, ``Tropical Jungle Bridge`` and
# ``Great Canyon Bridge`` are AP **items** but **not AP locations**
# (per user direction 2026-05-08). They are virtual access items
# delivered to the player via trigger-bit writes — there is no
# in-world "pickup site" for them. The previous ``Drill Tunnel
# Boulder`` / ``Tropical Jungle Bridge Fixed`` / ``Great Canyon
# Bridge Fixed`` locations were dropped at the same time.
_KEYITEM_LOCATIONS: Final[dict[str, LocationEntry]] = {
    "Old Fishrod Pickup":            LocationEntry(69_004_000, "Gear Savanna"),
    "Mansion Key Pickup":            LocationEntry(69_004_004, "Overdell"),
    "Frig Key Pickup":               LocationEntry(69_004_005, "Grey Lord's Mansion"),
    "Gear Pickup":                   LocationEntry(69_004_007, "Toy Town"),
    "Rain Plant Pickup":             LocationEntry(69_004_008, "Native Forest"),
    "Blue Flute Pickup":             LocationEntry(69_004_009, "Greatlake"),
    "Leomonstone Pickup":            LocationEntry(69_004_010, "Drill Tunnel"),
    # Volume Villa is reached after defeating Otamamon in Geko Swamp;
    # we model it as part of the Geko Swamp region. Merit Shop's
    # 300-Merit cost isn't modeled in AP rules — Merit is earned by
    # trading cards, which the player can do once at the shop.
    "Amazing Rod Pickup":            LocationEntry(69_004_011, "Geko Swamp"),
}


# =============================================================================
# Card-vending locations (66, opt-in)
# =============================================================================
# DW1's two card vending machines (Gear Savanna, post-Betamon+Patamon
# File City) sell 66 unique Digimon cards. Vanilla DW1 tracks card
# ownership as a packed nibble counter at
# :data:`worlds.digimon_world.data.addresses.RAM_CARD_LIST_BASE`. The
# client watches that block and fires the corresponding AP location the
# first time a card's nibble flips from 0.
#
# IDs follow DWAP's wire format (69_002_000 + index). Region is the
# synthetic "Card Vending" region declared in :mod:`.regions`; access
# rules are wired in :mod:`.rules`.
#
# Inclusion is gated on :class:`worlds.digimon_world.options.CardLocations`;
# see :func:`create_all_locations`.

_CARD_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_002_000 + i, "Card Vending")
    for i, name in enumerate(CARD_LOCATION_NIBBLES)
}
assert len(_CARD_LOCATIONS) == 66, len(_CARD_LOCATIONS)

CARD_NAMES: Final[tuple[str, ...]] = tuple(_CARD_LOCATIONS)


# =============================================================================
# Vending-machine locations (12, opt-in)
# =============================================================================
# Each location lives in the in-game region of its physical machine
# (Greatlake / Tropical Jungle / Gear Savanna / Ancient Dino Region).
# Region access rules already exist for each via the entrance rules in
# :mod:`.regions` / :mod:`.rules`, so no new edges are needed — the
# location is reachable when its parent region is reachable.
#
# IDs land in the previously-reserved ``69_055_xxx`` slot.

_VENDING_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_055_000 + i, VENDING_LOCATION_REGIONS[name])
    for i, name in enumerate(VENDING_LOCATION_NAMES)
}
assert len(_VENDING_LOCATIONS) == 10, len(_VENDING_LOCATIONS)


# =============================================================================
# Recycle-shop locations (7, opt-in)
# =============================================================================
# Tinmon's Recycle Shop in Gear Savanna (screen GIAS06B). 7 fixed
# rows; each becomes its own AP location when
# :class:`worlds.digimon_world.options.RecycleShopLocations` is on.
# Region = ``Gear Savanna`` so the existing region access rule
# governs reachability (gated on Bridge access etc.).
#
# Inclusion / patch wiring is documented in
# :mod:`worlds.digimon_world.data.addresses` under
# ``RECYCLE_SHOP_*`` and in :func:`rom._write_recycle_shop_tokens`.

_RECYCLE_SHOP_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_056_000 + i, "Gear Savanna")
    for i, name in enumerate(RECYCLE_SHOP_LOCATION_NAMES)
}
assert len(_RECYCLE_SHOP_LOCATIONS) == 7, len(_RECYCLE_SHOP_LOCATIONS)


# =============================================================================
# Merit-shop locations (14, opt-in)
# =============================================================================
# ShogunGekomon's Merit Shop in Volume Villa. 14 fixed merit-priced
# rows; each becomes its own AP location when
# :class:`worlds.digimon_world.options.MeritShopLocations` is on. Region
# = ``Geko Swamp`` (Volume Villa is modeled as part of Geko Swamp per
# the existing ``Amazing Rod Pickup`` placement). The v1
# ``Amazing Rod Pickup`` row at slot 83 stays as a 15th AP merit-shop
# row but is NOT one of these 14 — it's preserved separately as an
# always-on key-item AP location at trigger 903.
#
# Inclusion / patch wiring is documented in
# :mod:`worlds.digimon_world.data.addresses` under ``MERIT_SHOP_*`` and
# in :func:`rom._write_merit_shop_locations_tokens`.

_MERIT_SHOP_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_057_000 + i, "Geko Swamp")
    for i, name in enumerate(MERIT_SHOP_LOCATION_NAMES)
}
assert len(_MERIT_SHOP_LOCATIONS) == 14, len(_MERIT_SHOP_LOCATIONS)


# =============================================================================
# Fishing locations (6, opt-in)
# =============================================================================
# Each of DW1's 6 catchable fish (Digianchovy / Digisnapper / DigiTrout /
# Black trout / Digicatfish / Digiseabass) is an AP location when
# :class:`worlds.digimon_world.options.FishingLocations` is on. Region is
# ``Greatlake`` — both fishing screens (MAYO06 / MAYO10 per
# :data:`worlds.digimon_world.data.addresses.SCREEN_FILENAMES`) belong to
# the Dragon Eye Lake cluster, which the AP region graph models as
# Greatlake. The region's entrance rule already gates on Native Forest
# access; per-location rod requirements are layered on top in
# :mod:`.rules`.
#
# IDs land in the previously-reserved ``69_058_xxx`` block.

_FISHING_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_058_000 + i, "Greatlake")
    for i, name in enumerate(FISHING_LOCATION_NAMES)
}
assert len(_FISHING_LOCATIONS) == 6, len(_FISHING_LOCATIONS)


# =============================================================================
# Nanimon Quest locations (5, always on)
# =============================================================================
# Vanilla DW1 places "Nanimon" at 5 fixed sites across the world; each
# visit fires a short cutscene that increments ``pstat(21)`` and sets a
# per-site trigger bit (333-337). The 1st visit additionally writes
# ``setInventorySize 20`` and the 4th writes ``setInventorySize 30``,
# but in AP the keychain progression is owned by the
# ``Progressive Keychain`` item (the client reconciles
# :data:`worlds.digimon_world.data.addresses.RAM_INVENTORY_SIZE` to
# ``10 + 10 * received_keychains``). Each per-site trigger becomes its
# own AP location check.
#
# Region assignment mirrors the in-game site location (cross-checked
# 2026-05-13 against vanilla script content):
#
#   Ogre Fortress       — elevator screen leading to Great Canyon
#   Ancient Dino Region — Meteormon meteorite site
#   Drill Tunnel        — Leomon Ancestor Cave (gated on 45 PP)
#   Toy Town            — WaruMonzaemon big/small box room
#   Factorial Town      — sick Digimon / sewer scene
#
# RAM-bit mapping lives in
# :data:`addresses.NANIMON_QUEST_LOCATION_RAM_BITS`; the names below
# must match exactly so the client's `_check_locations` can resolve
# location_name → id.

_NANIMON_QUEST_REGIONS: Final[dict[str, str]] = {
    "Nanimon Quest: Ogre Fortress":        "Great Canyon",
    "Nanimon Quest: Ancient Dino Region":  "Ancient Dino Region",
    "Nanimon Quest: Drill Tunnel":         "Drill Tunnel",
    "Nanimon Quest: Toy Town":             "Toy Town",
    "Nanimon Quest: Factorial Town":       "Factorial Town",
}
assert set(_NANIMON_QUEST_REGIONS) == set(NANIMON_QUEST_LOCATION_RAM_BITS), (
    "Nanimon Quest region table must match the RAM-bit table"
)

_NANIMON_QUEST_LOCATIONS: Final[dict[str, LocationEntry]] = {
    name: LocationEntry(69_059_000 + i, region)
    for i, (name, region) in enumerate(_NANIMON_QUEST_REGIONS.items())
}
assert len(_NANIMON_QUEST_LOCATIONS) == 5, len(_NANIMON_QUEST_LOCATIONS)


# =============================================================================
# Arena Cup locations (20 = 5 tiers x 4 checks, always on)
# =============================================================================
# DW1's Battle Arena (south File City) runs 5 grade-tier tournaments
# (Grade D / C / B / A / S — Rookie / Champion / Champion+ / Ultimate /
# Strongest). Each cup win gates 4 AP location checks via the cup's
# allocated trigger bit (885..889; see
# :data:`worlds.digimon_world.data.addresses.ARENA_CUP_TIERS`). The
# patcher rewrites the in-game prize ``giveItem`` opcodes in Script
# 214 § Section_51 to ``setTrigger N`` instead -- the vanilla prize
# never enters the player's inventory; AP delivers 4 items per cup
# from the seed pool instead.
#
# All 20 locations live in the ``File City`` region (the arena's
# physical home). PP-based access rules per tier are layered in
# :mod:`.rules` -- they're an AP-logic proxy for the actual in-game
# difficulty (which scales with partner stage/stats; not directly
# modellable in AP).

_ARENA_CUP_LOCATIONS: Final[dict[str, LocationEntry]] = {
    f"Arena Cup: {tier} {i}": LocationEntry(
        69_060_000 + tier_index * ARENA_CUP_LOCATIONS_PER_TIER + (i - 1),
        "File City",
    )
    for tier_index, (tier, _bit, _trig, _pp) in enumerate(ARENA_CUP_TIERS)
    for i in range(1, ARENA_CUP_LOCATIONS_PER_TIER + 1)
}
assert len(_ARENA_CUP_LOCATIONS) == 20, len(_ARENA_CUP_LOCATIONS)

ARENA_CUP_NAMES: Final[tuple[str, ...]] = tuple(_ARENA_CUP_LOCATIONS)


# =============================================================================
# Final assembled location table
# =============================================================================

_LOCATION_TABLE: Final[dict[str, LocationEntry]] = {
    **{name: LocationEntry(_RECRUIT_DW_IDS[name], _RECRUIT_REGIONS[name])
       for name in RECRUIT_NAMES},
    **_CHEST_LOCATIONS,
    **_KEYITEM_LOCATIONS,
    **_CARD_LOCATIONS,
    **_VENDING_LOCATIONS,
    **_RECYCLE_SHOP_LOCATIONS,
    **_MERIT_SHOP_LOCATIONS,
    **_FISHING_LOCATIONS,
    **_NANIMON_QUEST_LOCATIONS,
    **_ARENA_CUP_LOCATIONS,
}

LOCATION_NAME_TO_ID: Final[dict[str, int]] = {
    name: entry.id for name, entry in _LOCATION_TABLE.items()
}

LOCATION_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Recruits": set(RECRUIT_NAMES),
    "Chests": set(_CHEST_LOCATIONS),
    "Key Items": set(_KEYITEM_LOCATIONS),
    "Cards": set(_CARD_LOCATIONS),
    "Vending": set(_VENDING_LOCATIONS),
    "Recycle Shop": set(_RECYCLE_SHOP_LOCATIONS),
    "Merit Shop": set(_MERIT_SHOP_LOCATIONS),
    "Fishing": set(_FISHING_LOCATIONS),
    "Nanimon Quest": set(_NANIMON_QUEST_LOCATIONS),
    "Arena Cup": set(_ARENA_CUP_LOCATIONS),
}


def locations_in_region(region_name: str) -> tuple[str, ...]:
    return tuple(name for name, entry in _LOCATION_TABLE.items() if entry.region == region_name)


def create_all_locations(world: DigimonWorldWorld) -> None:
    """Attach every v1 location to its parent region.

    Card and vending locations are option-gated; everything else is
    unconditional.
    """

    skip_locations: set[str] = set()
    # CardLocations: opt-in, default off. When off, the 66 card AP
    # locations are excluded from the pool.
    if not int(world.options.card_locations.value):
        skip_locations.update(_CARD_LOCATIONS)
    # VendingLocations: opt-in, default off. When off, the 12 vending
    # machine AP locations are excluded from the pool.
    if not int(world.options.vending_locations.value):
        skip_locations.update(_VENDING_LOCATIONS)
    # RecycleShopLocations: opt-in, default off. When off, the 7
    # recycle shop AP locations are excluded from the pool.
    if not int(world.options.recycle_shop_locations.value):
        skip_locations.update(_RECYCLE_SHOP_LOCATIONS)
    # MeritShopLocations: opt-in, default off. When off, the 14
    # merit shop AP locations are excluded from the pool.
    if not int(world.options.merit_shop_locations.value):
        skip_locations.update(_MERIT_SHOP_LOCATIONS)
    # FishingLocations: opt-in, default off. When off, the 6 fishing
    # AP locations are excluded from the pool.
    if not int(world.options.fishing_locations.value):
        skip_locations.update(_FISHING_LOCATIONS)
    # ChestRandomization: default ON. When OFF, the 65 chest AP
    # locations are excluded from the pool — chests retain vanilla
    # items and don't fire AP checks.
    if not int(world.options.chest_randomization.value):
        skip_locations.update(_CHEST_LOCATIONS)
    # ArenaLocations: opt-in Choice (off / exclude_s / all), default off.
    # 'off' skips all 20 cup-win AP locations. 'exclude_s' skips the 4
    # Grade S locations (16 remain). 'all' keeps all 20. Per-tier access
    # rules are applied in rules.py (gated on Progressive Arena count).
    _arena_opt = int(world.options.arena_locations.value)
    if _arena_opt == 0:  # off
        skip_locations.update(_ARENA_CUP_LOCATIONS)
    elif _arena_opt == 1:  # exclude_s
        skip_locations.update(n for n in _ARENA_CUP_LOCATIONS
                              if n.startswith("Arena Cup: Grade S"))

    by_region: dict[str, dict[str, int | None]] = {}
    for name, entry in _LOCATION_TABLE.items():
        if name in skip_locations:
            continue
        by_region.setdefault(entry.region, {})[name] = entry.id
    for region_name, names_with_ids in by_region.items():
        world.get_region(region_name).add_locations(names_with_ids, DigimonWorldLocation)

    # Two classes of chest get :data:`LocationProgressType.EXCLUDED`,
    # restricting placement to filler / useful / trap:
    #
    # * **Unconfirmed chests** (``region is None``): we don't know their
    #   real in-game location yet, so AP fill might place a progression
    #   item the player can't actually reach when logic predicts they
    #   should. (As of 2026-05-09 every chest has a confirmed region —
    #   this branch is kept for any future regressions.)
    # * **Post-game-only regions** (``Back Dimension``): these chests
    #   are reachable in AP logic, but only after the player has
    #   defeated Machinedramon. Under the default ``machinedramon``
    #   goal the player wins at that moment and has no incentive to
    #   return for chests; placing progression here would leak
    #   progression items into a region most players will never visit.
    for chest_name, region in _CHEST_BY_SLOT.values():
        if chest_name in skip_locations:
            continue
        if region is None or region in _POSTGAME_CHEST_REGIONS:
            location = world.get_location(chest_name)
            location.progress_type = LocationProgressType.EXCLUDED
            # Post-game chests get a tighter rule: pure filler only,
            # not even ``useful``. Players who reach Back Dimension
            # have already cleared the seed under the default goal,
            # so any non-filler item placed here is effectively
            # wasted. ``ItemClassification.filler`` is the zero value
            # of the IntFlag, so this matches items with no
            # classification flags set.
            if region in _POSTGAME_CHEST_REGIONS:
                location.item_rule = (
                    lambda item: item.classification == ItemClassification.filler
                )


# =============================================================================
# Final-Battle event
# =============================================================================
# The endgame is gated on the AP-PP item count (50 PP = 25 items). PP
# is a real AP item now, not an event item — so we no longer create
# per-location PP-grant events. AS Decoder used to also be part of the
# gate, but it is a no-op DW1 item that gates nothing — removed
# 2026-05-08.

def create_events(world: DigimonWorldWorld) -> None:
    """Create the Victory event."""

    from . import items as items_module

    world.get_region("Tower").add_event(
        "Final Battle",
        "Victory",
        location_type=DigimonWorldLocation,
        item_type=items_module.DigimonWorldItem,
    )
