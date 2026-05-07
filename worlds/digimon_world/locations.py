"""Location table for the Digimon World 1 APWorld (Phase 4 v7).

Location IDs use DWAP's ``base_id = 69_000_000`` convention, partitioned
the same way:

* ``69_001_xxx`` — chests (65)
* ``69_002_xxx`` — cards (66, opt-in via :class:`worlds.digimon_world.options.CardLocations`)
* ``69_003_xxx`` — start-game / starter pickup (1)
* ``69_004_xxx`` — reserved (was prosperity NPC gifts; gone in v7)
* ``69_005_xxx``..``69_054_xxx`` — recruit checks, one Digimon per 1000-block
* ``69_055_xxx`` — vending machines (12, opt-in via :class:`worlds.digimon_world.options.VendingLocations`)

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

from BaseClasses import Location

from .data.addresses import (
    CARD_LOCATION_NIBBLES,
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
    # File City
    "Greymon":      "File City",
    "Airdramon":    "File City",
    # Native Forest
    "Palmon":       "Native Forest",
    "Kunemon":      "Native Forest",
    "Coelamon":     "Native Forest",
    "Seadramon":    "Native Forest",
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
    "Nanimon":      "Toy Town",
    # Factorial Town
    "Numemon":      "Factorial Town",
    "Andromon":     "Factorial Town",
    "Giromon":      "Factorial Town",
    "MetalMamemon": "Factorial Town",
    # Mt. Infinity
    "Devimon":      "Mt. Infinity",
    "Megadramon":   "Mt. Infinity",
    "MetalGreymon": "Mt. Infinity",
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
# Phase 6: 50 vanilla recruits minus Agumon (force-recruited bank NPC)
# minus Digitamamon (post-game optional goal).
assert len(RECRUIT_NAMES) == 48, len(RECRUIT_NAMES)


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
    "Coelamon": 0,
    "Seadramon": 0,
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
    "Andromon": 0,
    "Giromon": 0,
    "MetalMamemon": 0,
    # 15 PP
    "Greymon": 15,
    # 40 PP
    "SkullGreymon": 40,
    # 45 PP
    "Leomon": 45,
    "Vademon": 45,
    # 50 PP
    "Airdramon": 50,
    "Etemon": 50,
    "Ninjamon": 50,
    "Devimon": 50,
    "Megadramon": 50,
    "MetalGreymon": 50,
}


# =============================================================================
# Chest list (65 entries, Phase 5 region-aware naming)
# =============================================================================
# Names follow the chest-mapping document
# (``references/chest_mapping_phase5.md``). DWAP slot indices 1..65 are
# preserved as AP IDs (``69_001_000`` + slot-1) so the wire format stays
# stable. Each slot is renamed to ``Chest: <Area> [N]`` for chests in
# confirmed/strongly-inferred regions, or kept as ``Chest N`` for the
# 17 chests whose region is not yet verified.
#
# The region used here is the **chest's in-game region**, which informs
# the per-chest PP gate (= min PP across recruits in that region; see
# :data:`CHEST_PP_REQUIREMENTS`).

# slot 1..65 → (chest name, in-game region)
_CHEST_BY_SLOT: Final[dict[int, tuple[str, str]]] = {
    1:  ("Chest: Mt. Infinity 1",        "Mt. Infinity"),
    2:  ("Chest: Mt. Infinity 2",        "Mt. Infinity"),
    3:  ("Chest: Mt. Infinity 3",        "Mt. Infinity"),
    4:  ("Chest: Freezeland 1",          "Freezeland"),
    5:  ("Chest: Freezeland 2",          "Freezeland"),
    6:  ("Chest: Freezeland 3",          "Freezeland"),
    7:  ("Chest: Freezeland 4",          "Freezeland"),
    8:  ("Chest: Freezeland 5",          "Freezeland"),
    9:  ("Chest: Drill Tunnel 1",        "Drill Tunnel"),
    10: ("Chest: Drill Tunnel 2",        "Drill Tunnel"),
    11: ("Chest 11",                     None),  # unknown region
    12: ("Chest 12",                     None),
    13: ("Chest: Freezeland 6",          "Freezeland"),
    14: ("Chest: Freezeland 7",          "Freezeland"),
    15: ("Chest: Freezeland 8",          "Freezeland"),
    16: ("Chest: Freezeland 9",          "Freezeland"),
    17: ("Chest: Drill Tunnel 3",        "Drill Tunnel"),
    18: ("Chest: Drill Tunnel 4",        "Drill Tunnel"),
    19: ("Chest: Toy Town",              "Toy Town"),
    20: ("Chest 20",                     None),
    21: ("Chest 21",                     None),
    22: ("Chest 22",                     None),
    23: ("Chest: Ogre Fortress",         "Great Canyon"),  # Ogre Fortress is Great Canyon's sub-area
    24: ("Chest 24",                     None),
    25: ("Chest 25",                     None),
    26: ("Chest 26",                     None),
    27: ("Chest: File City Cards 1",     "File City"),
    28: ("Chest 28",                     None),
    29: ("Chest 29",                     None),
    30: ("Chest: File City Cards 2",     "File City"),
    31: ("Chest: Mt. Infinity 4",        "Mt. Infinity"),
    32: ("Chest: Mt. Infinity 5",        "Mt. Infinity"),
    33: ("Chest: Mt. Infinity 6",        "Mt. Infinity"),
    34: ("Chest 34",                     None),
    35: ("Chest 35",                     None),
    36: ("Chest 36",                     None),
    37: ("Chest: Mt. Infinity 7",        "Mt. Infinity"),
    38: ("Chest: Tower 1",               "Tower"),
    39: ("Chest: Tower 2",               "Tower"),
    40: ("Chest: Tower 3",               "Tower"),
    41: ("Chest: Tower 4",               "Tower"),
    42: ("Chest: Tower 5",               "Tower"),
    43: ("Chest: Tropical Jungle",       "Tropical Jungle"),
    44: ("Chest 44",                     None),
    45: ("Chest 45",                     None),
    46: ("Chest: Great Canyon 1",        "Great Canyon"),
    47: ("Chest: Great Canyon 2",        "Great Canyon"),
    48: ("Chest: Great Canyon 3",        "Great Canyon"),
    49: ("Chest: Mt. Infinity 8",        "Mt. Infinity"),
    50: ("Chest: Mt. Infinity 9",        "Mt. Infinity"),
    51: ("Chest: Mt. Infinity 10",       "Mt. Infinity"),
    52: ("Chest: Mt. Infinity 11",       "Mt. Infinity"),
    53: ("Chest 53",                     None),
    54: ("Chest 54",                     None),
    55: ("Chest: Dragon Eye Lake",       "Native Forest"),
    56: ("Chest: Mt. Infinity 12",       "Mt. Infinity"),
    57: ("Chest: Tower 6",               "Tower"),
    58: ("Chest: Tower 7",               "Tower"),
    59: ("Chest: Tower 8",               "Tower"),
    60: ("Chest: Tower 9",               "Tower"),
    61: ("Chest: Tower 10",              "Tower"),
    62: ("Chest: Tower 11",              "Tower"),
    63: ("Chest: File City Remodel 1",   "File City"),
    64: ("Chest: File City Remodel 2",   "File City"),
    65: ("Chest: File City Remodel 3",   "File City"),
}
assert len(_CHEST_BY_SLOT) == 65
assert len({name for name, _ in _CHEST_BY_SLOT.values()}) == 65, "duplicate chest names"

# AP-side, every chest still resides in File City (region access for
# chests is governed by the PP gate alone in v7+). The "in-game region"
# stored above is used only for the PP-gate computation in
# :data:`CHEST_PP_REQUIREMENTS`.
_CHEST_LOCATIONS: Final[dict[str, LocationEntry]] = {
    _CHEST_BY_SLOT[_slot][0]: LocationEntry(69_001_000 + _slot - 1, "File City")
    for _slot in range(1, 66)
}

CHEST_NAMES: Final[tuple[str, ...]] = tuple(_CHEST_LOCATIONS)
assert len(CHEST_NAMES) == 65, len(CHEST_NAMES)


def _build_chest_pp_requirements() -> dict[str, int]:
    """Per-chest PP gate, derived from ``min(recruit PP) across the
    chest's in-game region``. Chests with no inferred region get 0 PP
    (always reachable in logic).
    """

    # Group recruit PPs by region.
    recruits_by_region: dict[str, list[int]] = {}
    for recruit_name, pp in RECRUIT_PP_REQUIREMENTS.items():
        recruits_by_region.setdefault(_RECRUIT_REGIONS[recruit_name], []).append(pp)

    out: dict[str, int] = {}
    for chest_name, region in _CHEST_BY_SLOT.values():
        if region is None or region not in recruits_by_region:
            out[chest_name] = 0
        else:
            out[chest_name] = min(recruits_by_region[region])
    return out


CHEST_PP_REQUIREMENTS: Final[dict[str, int]] = _build_chest_pp_requirements()


# =============================================================================
# Starter pickup (1)
# =============================================================================

_STARTER_LOCATION: Final[dict[str, LocationEntry]] = {
    "Start Game": LocationEntry(69_003_000, "File City"),
}


# =============================================================================
# Key-item pickups
# =============================================================================
# v1: just the Old Fishrod (Trash Mountain in Gear Savanna). Future
# additions (Mansion Key, Blue Flute, Amazing Rod, Leomonstone, ...) will
# go here once their flag addresses are verified the same way the rod's
# was — the CE-table values are unreliable, see memory note
# `dw1_keyitem_flag_block.md`.
_KEYITEM_LOCATIONS: Final[dict[str, LocationEntry]] = {
    "Old Fishrod Pickup":            LocationEntry(69_004_000, "Gear Savanna"),
    "Drill Tunnel Boulder":          LocationEntry(69_004_001, "Drill Tunnel"),
    "Tropical Jungle Bridge Fixed":  LocationEntry(69_004_002, "Tropical Jungle"),
    "Great Canyon Bridge Fixed":     LocationEntry(69_004_003, "Great Canyon"),
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
assert len(_VENDING_LOCATIONS) == 12, len(_VENDING_LOCATIONS)


# =============================================================================
# Final assembled location table
# =============================================================================

_LOCATION_TABLE: Final[dict[str, LocationEntry]] = {
    **_STARTER_LOCATION,
    **{name: LocationEntry(_RECRUIT_DW_IDS[name], _RECRUIT_REGIONS[name])
       for name in RECRUIT_NAMES},
    **_CHEST_LOCATIONS,
    **_KEYITEM_LOCATIONS,
    **_CARD_LOCATIONS,
    **_VENDING_LOCATIONS,
}

LOCATION_NAME_TO_ID: Final[dict[str, int]] = {
    name: entry.id for name, entry in _LOCATION_TABLE.items()
}

LOCATION_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Recruits": set(RECRUIT_NAMES),
    "Chests": set(_CHEST_LOCATIONS),
    "Starter": set(_STARTER_LOCATION),
    "Key Items": set(_KEYITEM_LOCATIONS),
    "Cards": set(_CARD_LOCATIONS),
    "Vending": set(_VENDING_LOCATIONS),
}


def locations_in_region(region_name: str) -> tuple[str, ...]:
    return tuple(name for name, entry in _LOCATION_TABLE.items() if entry.region == region_name)


def create_all_locations(world: DigimonWorldWorld) -> None:
    """Attach every v1 location to its parent region.

    Some locations are conditional on player options:

    * ``Drill Tunnel Boulder`` only exists in ``shuffled`` mode for
      :class:`worlds.digimon_world.options.LavaCaveAccess`. In vanilla
      mode the gate stays as the original digimon-stage whitelist and
      there's no AP location/item pair for it.
    """

    skip_locations: set[str] = set()
    if int(world.options.lava_cave_access.value) == 0:  # 0 = vanilla
        skip_locations.add("Drill Tunnel Boulder")
    # BridgeUnlock / GreatCanyonUnlock: 0=always_open, 1=vanilla, 2=shuffled.
    # The AP location only exists in shuffled (=2).
    if int(world.options.bridge_unlock.value) != 2:
        skip_locations.add("Tropical Jungle Bridge Fixed")
    if int(world.options.great_canyon_unlock.value) != 2:
        skip_locations.add("Great Canyon Bridge Fixed")
    # CardLocations: opt-in, default off. When off, the 66 card AP
    # locations are excluded from the pool.
    if not int(world.options.card_locations.value):
        skip_locations.update(_CARD_LOCATIONS)
    # VendingLocations: opt-in, default off. When off, the 12 vending
    # machine AP locations are excluded from the pool.
    if not int(world.options.vending_locations.value):
        skip_locations.update(_VENDING_LOCATIONS)
    # ChestRandomization: default ON. When OFF, the 65 chest AP
    # locations are excluded from the pool — chests retain vanilla
    # items and don't fire AP checks.
    if not int(world.options.chest_randomization.value):
        skip_locations.update(_CHEST_LOCATIONS)

    by_region: dict[str, dict[str, int | None]] = {}
    for name, entry in _LOCATION_TABLE.items():
        if name in skip_locations:
            continue
        by_region.setdefault(entry.region, {})[name] = entry.id
    for region_name, names_with_ids in by_region.items():
        world.get_region(region_name).add_locations(names_with_ids, DigimonWorldLocation)


# =============================================================================
# Final-Battle event
# =============================================================================
# The endgame is gated on ``AS Decoder`` + the AP-PP item count (50). PP
# is a real AP item now, not an event item — so we no longer create
# per-location PP-grant events.

def create_events(world: DigimonWorldWorld) -> None:
    """Create the Victory event."""

    from . import items as items_module

    world.get_region("Tower").add_event(
        "Final Battle",
        "Victory",
        location_type=DigimonWorldLocation,
        item_type=items_module.DigimonWorldItem,
    )
