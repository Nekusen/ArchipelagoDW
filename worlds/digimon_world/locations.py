"""Location table for the Digimon World 1 APWorld (Phase 2: full v1 list).

Location IDs use DWAP's ``base_id = 69_000_000`` convention, partitioned
the same way:

* ``69_001_xxx`` — chests
* ``69_002_xxx`` — cards (not used in v1; reserved for future)
* ``69_003_xxx`` — start-game / starter pickup
* ``69_004_xxx`` — prosperity NPC gifts
* ``69_005_xxx``..``69_054_xxx`` — recruit checks (one Digimon per 1000-block)

Locked v1 MVP scope: chests + NPC gifts + starter + recruitment.

The 73 chest IDs match the standalone randomizer's chest count
(``references/digimon_world_randomizer/digimon/data.py:232-243``); chests
are distributed across DW1 regions by approximate map-zone (see
:mod:`.regions`). The exact chest-to-region assignment is a Phase 3
deliverable when the patcher correlates each chest's ROM offset with its
in-game placement; the v1 stub assignment here is plausible but not
authoritative.

The 25 NPC-gift checkpoints sample the DWAP 100-entry prosperity table
at logic-relevant thresholds: 1, 2, 3, 5, 10, 15, 20, 25, 30, 35, 40, 45,
50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100, plus 6 (the DWAP "or
Meramon" gate threshold) and 12.
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
# Recruit locations
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


# =============================================================================
# Chest list (65 entries, DWAP naming, all in File City)
# =============================================================================
# Names and IDs adopt DWAP's ``Resources/Chests.json`` verbatim. Each
# chest is named ``Chest N`` for N in 1..65, except slot 55 which is
# DWAP's specially-named ``Chest: Dragon Eye Lake``. AP IDs are zero-
# indexed (Chest 1 = 69_001_000, Chest 2 = 69_001_001, ...,
# Chest 65 = 69_001_064; Chest: Dragon Eye Lake at slot 55 = 69_001_054).
#
# **Region assignment is provisional**: v1 places every chest in
# ``File City`` so they're unconditionally reachable from AP's logic
# perspective. The player still has to traverse DW1 in-game to actually
# open each chest, but AP fill won't gate progression items behind the
# wrong region's access rule (which would be the failure mode of an
# *incorrect* chest→region assignment). Once each chest's true in-game
# location is identified — see Phase 4 v2.1 in ``phase_progress.md`` —
# entries should be moved into their proper region.
#
# Source for the names: DWAP Chests.json. Source for the runtime bits
# (used by :data:`worlds.digimon_world.client.LOCATION_RAM_BITS`):
# :data:`worlds.digimon_world.data.addresses.DWAP_CHEST_RAM_BITS`.

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
# NPC-gift / prosperity locations (25)
# =============================================================================
# Each gift is the K-th gift in DWAP's 100-entry table; we keep DWAP's
# numerical id (69_004_000 + K - 1) and name ("K Prosperity"). The PP
# threshold gate ``Has("Prosperity Point", count=K)`` is set in
# :mod:`.rules`.

# PP thresholds capped at 50 because that is the highest threshold any v1
# rule actually gates on (Mt. Infinity → Tower, Big Store, the 50-PP
# recruit cluster). Maximum reachable PP under v1's "1 PP per location"
# model is 50 recruits + len(thresholds) gifts; thresholds above 50 would
# be unreachable even in all_state because PP is bounded by the number of
# PP-granting locations themselves. If Phase 2 verification work changes
# the per-recruit prosperity_value to match DWAP's RecruitDigimon table
# (1, 2, 3 per recruit), this list can grow back toward 100.
PROSPERITY_THRESHOLDS: Final[tuple[int, ...]] = (
    1, 2, 3, 5, 6, 10, 12, 15, 20, 25, 30, 35, 40, 45, 50,
)

_PROSPERITY_LOCATIONS: Final[dict[str, LocationEntry]] = {
    f"{k} Prosperity": LocationEntry(69_004_000 + k - 1, "File City")
    for k in PROSPERITY_THRESHOLDS
}

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
    **_PROSPERITY_LOCATIONS,
}

# Recruit location names use the bare Digimon name; this is the AP-side
# label. e.g. "Agumon" is the *location*; "Agumon Soul" is the *item*.

LOCATION_NAME_TO_ID: Final[dict[str, int]] = {
    name: entry.id for name, entry in _LOCATION_TABLE.items()
}

LOCATION_NAME_GROUPS: Final[dict[str, set[str]]] = {
    "Recruits": set(RECRUIT_NAMES),
    "Chests": set(_CHEST_LOCATIONS),
    "Prosperity": set(_PROSPERITY_LOCATIONS),
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
# Prosperity-event location names
# =============================================================================
# Each recruit + each NPC gift gets a sibling "PP from <name>" event whose
# locked item is "Prosperity Point". Names are produced here so both
# :func:`create_events` (which creates the locations) and the rule-setter in
# :mod:`.rules` (which applies the rule mirrored from the parent location)
# agree on the spelling.

def prosperity_event_name(parent_label: str) -> str:
    return f"PP from {parent_label}"


def _pp_event_targets() -> tuple[tuple[str, str, str], ...]:
    """Return ``(event_name, parent_label, region_name)`` for each PP event."""

    recruit_targets = [
        (prosperity_event_name(r), r, _RECRUIT_REGIONS[r])
        for r in RECRUIT_NAMES
    ]
    gift_targets = [
        (prosperity_event_name(f"{k} Prosperity"), f"{k} Prosperity", "File City")
        for k in PROSPERITY_THRESHOLDS
    ]
    return tuple(recruit_targets + gift_targets)


PP_EVENT_TARGETS: Final[tuple[tuple[str, str, str], ...]] = _pp_event_targets()


def create_events(world: DigimonWorldWorld) -> None:
    """Create the Victory event and every Prosperity Point event.

    AP forbids creating new locations during ``set_rules``; per-location
    rules for these events are attached later in :mod:`.rules`.
    """

    from . import items as items_module

    world.get_region("Tower").add_event(
        "Final Battle",
        "Victory",
        location_type=DigimonWorldLocation,
        item_type=items_module.DigimonWorldItem,
    )

    for event_name, _parent_label, region_name in PP_EVENT_TARGETS:
        world.get_region(region_name).add_event(
            event_name,
            "Prosperity Point",
            location_type=DigimonWorldLocation,
            item_type=items_module.DigimonWorldItem,
        )
