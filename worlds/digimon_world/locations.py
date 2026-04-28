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

_RECRUIT_REGIONS: Final[dict[str, str]] = {
    "Agumon":       "File City",
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
    "SkullGreymon": "Mt. Infinity",
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
    "Agumon": 69_005_000, "Betamon": 69_006_000, "Greymon": 69_007_000,
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
assert len(RECRUIT_NAMES) == 50, len(RECRUIT_NAMES)


# =============================================================================
# Chest list (65 entries, DWAP naming, all in File City)
# =============================================================================
# Names and IDs adopt DWAP's ``Resources/Chests.json`` verbatim. Each
# chest is named ``Chest N`` for N in 1..65, except slot 55 which is
# DWAP's specially-named ``Chest: Dragon Eye Lake``. AP IDs are zero-
# indexed (Chest 1 = 69_001_000, Chest 2 = 69_001_001, ...,
# Chest 65 = 69_001_064; Chest: Dragon Eye Lake at slot 55 = 69_001_054).

DWAP_CHEST_NAME_AT_SLOT_55: Final = "Chest: Dragon Eye Lake"


def _chest_name_for_slot(slot: int) -> str:
    """Return DWAP's name for the K-th chest (1-indexed)."""

    return DWAP_CHEST_NAME_AT_SLOT_55 if slot == 55 else f"Chest {slot}"


_CHEST_LOCATIONS: Final[dict[str, LocationEntry]] = {
    _chest_name_for_slot(_slot): LocationEntry(69_001_000 + _slot - 1, "File City")
    for _slot in range(1, 66)
}

CHEST_NAMES: Final[tuple[str, ...]] = tuple(_CHEST_LOCATIONS)
assert len(CHEST_NAMES) == 65, len(CHEST_NAMES)


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
