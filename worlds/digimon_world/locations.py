"""Location table for the Digimon World 1 APWorld (Phase 4 v7).

Location IDs use DWAP's ``base_id = 69_000_000`` convention, partitioned
the same way:

* ``69_001_xxx`` — chests (65)
* ``69_002_xxx`` — cards (reserved for future, unused in v1)
* ``69_003_xxx`` — start-game / starter pickup (1)
* ``69_004_xxx`` — reserved (was prosperity NPC gifts; gone in v7)
* ``69_005_xxx``..``69_054_xxx`` — recruit checks, one Digimon per 1000-block

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

# Phase 5 piece C: Agumon is dropped from the recruit-location pool.
# His recruit bit is force-set by the client every tick (he's the bank
# NPC and that's a key delivery mechanic — see
# :meth:`worlds.digimon_world.client.DigimonWorldClient._enforce_agumon_recruited`).
# Pre-setting bit 203 also blocks the wild-Agumon-fight spawn, so the
# Agumon AP location can never fire; better to drop it than risk the
# bank breaking.
_RECRUIT_REGIONS: Final[dict[str, str]] = {
    "Betamon":      "Native Forest",
    "Greymon":      "Mt. Panorama",
    "Devimon":      "Mt. Infinity",
    "Airdramon":    "Mt. Infinity",
    "Tyrannomon":   "Mt. Panorama",
    "Meramon":      "Meramon Tunnel",
    "Seadramon":    "Greatlake",
    "Numemon":      "Greatlake",
    "MetalGreymon": "Tower",
    "Mamemon":      "Mt. Panorama",
    "Monzaemon":    "Misty Trees",
    "Gabumon":      "Native Forest",
    "Elecmon":      "Native Forest",
    "Kabuterimon":  "Beetle Land",
    "Angemon":      "Freezeland",
    "Birdramon":    "Great Canyon",
    "Garurumon":    "Freezeland",
    "Frigimon":     "Freezeland",
    "Whamon":       "Greatlake",
    "Vegiemon":     "Native Forest",
    "SkullGreymon": "Overdell",
    "MetalMamemon": "Factorial Town",
    "Vademon":      "Mt. Infinity",
    "Patamon":      "Native Forest",
    "Kunemon":      "Tropical Jungle",
    "Unimon":       "Mt. Panorama",
    "Ogremon":      "Greatlake",
    "Shellmon":     "Greatlake",
    "Centarumon":   "Tropical Jungle",
    "Bakemon":      "Tropical Jungle",
    "Drimogemon":   "Drill Tunnel",
    "Sukamon":      "Native Forest",
    "Andromon":     "Factorial Town",
    "Giromon":      "Factorial Town",
    "Etemon":       "Mt. Infinity",
    "Biyomon":      "Native Forest",
    "Palmon":       "Native Forest",
    "Monochromon":  "Great Canyon",
    "Leomon":       "Mt. Panorama",
    "Coelamon":     "Tropical Jungle",
    "Kokatorimon":  "Misty Trees",
    "Kuwagamon":    "Beetle Land",
    "Mojyamon":     "Freezeland",
    "Nanimon":      "Toy Town",
    "Megadramon":   "Mt. Infinity",
    "Piximon":      "Tropical Jungle",
    "Digitamamon":  "Tower",
    "Penguinmon":   "Sand Bay",
    "Ninjamon":     "Big Store",
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
    "Megadramon": 69_050_000, "Piximon": 69_051_000, "Digitamamon": 69_052_000,
    "Penguinmon": 69_053_000, "Ninjamon": 69_054_000,
}

RECRUIT_NAMES: Final[tuple[str, ...]] = tuple(_RECRUIT_REGIONS)
# Phase 5 piece C: Agumon dropped (see _RECRUIT_REGIONS comment).
assert len(RECRUIT_NAMES) == 49, len(RECRUIT_NAMES)


# =============================================================================
# Recruit PP requirements (Phase 5 logic map)
# =============================================================================
# Per-recruit Prosperity Point gate, supplied by the user. The rule
# applied at each recruit AP location is
# ``Has("Prosperity Point", count=N)`` where N is the value below.
# Recruits at 0 PP have no rule (always logically reachable).

RECRUIT_PP_REQUIREMENTS: Final[dict[str, int]] = {
    # 0 PP (Agumon dropped — see _RECRUIT_REGIONS comment)
    "Palmon": 0,
    "Kunemon": 0,
    "Coelamon": 0,
    "Meramon": 0,
    "Betamon": 0,
    # 6 PP
    "Centarumon": 6,
    "Vegiemon": 6,
    "Drimogemon": 6,
    "Monochromon": 6,
    "Shellmon": 6,
    "Mojyamon": 6,
    "Frigimon": 6,
    "Penguinmon": 6,
    "Birdramon": 6,
    "Elecmon": 6,
    "Patamon": 6,
    "Biyomon": 6,
    "Bakemon": 6,
    "Sukamon": 6,
    # 10 PP
    "Unimon": 10,
    "Whamon": 10,
    "Gabumon": 10,
    "Kokatorimon": 10,
    "Garurumon": 10,
    "Tyrannomon": 10,
    # 15 PP
    "Greymon": 15,
    "Seadramon": 15,
    "Mamemon": 15,
    # 20 PP
    "Numemon": 20,
    "Andromon": 20,
    "MetalMamemon": 20,
    "Giromon": 20,
    "Kabuterimon": 20,
    "Kuwagamon": 20,
    "Angemon": 20,
    "Ogremon": 20,
    "SkullGreymon": 20,
    "Monzaemon": 20,
    "Ninjamon": 20,
    # 45 PP
    "Leomon": 45,
    "Vademon": 45,
    # 50 PP
    "Nanimon": 50,
    "Etemon": 50,
    "Airdramon": 50,
    "Devimon": 50,
    "Megadramon": 50,
    "Digitamamon": 50,
    "Piximon": 50,
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
# Final assembled location table
# =============================================================================

_LOCATION_TABLE: Final[dict[str, LocationEntry]] = {
    **_STARTER_LOCATION,
    **{name: LocationEntry(_RECRUIT_DW_IDS[name], _RECRUIT_REGIONS[name])
       for name in RECRUIT_NAMES},
    **_CHEST_LOCATIONS,
}

LOCATION_NAME_TO_ID: Final[dict[str, int]] = {
    name: entry.id for name, entry in _LOCATION_TABLE.items()
}

LOCATION_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Recruits": set(RECRUIT_NAMES),
    "Chests": set(_CHEST_LOCATIONS),
    "Starter": set(_STARTER_LOCATION),
}


def locations_in_region(region_name: str) -> tuple[str, ...]:
    return tuple(name for name, entry in _LOCATION_TABLE.items() if entry.region == region_name)


def create_all_locations(world: DigimonWorldWorld) -> None:
    """Attach every v1 location to its parent region."""

    by_region: dict[str, dict[str, int | None]] = {}
    for name, entry in _LOCATION_TABLE.items():
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
