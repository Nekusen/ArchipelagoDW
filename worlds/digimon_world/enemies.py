"""Enemy stat scaling and species randomization for Digimon World 1.

Both features are pure data rewrites of the vanilla disc -- no code hooks:

* Every field Digimon (wild fodder and story bosses alike) is a record in its screen's
  ``.MAP`` file (:mod:`.data.enemy_records`). ``loadMapDigimon`` copies the record into
  ``NPC_ENTITIES`` when the screen loads and the battle engine takes stats and moveset from
  there verbatim, so rewriting the nine stat words / four move bytes of a record changes
  that one fight and nothing else.
* Which species stands in a record is the record's ``type`` plus the ``loadDigimon`` /
  ``setDigimon`` operands in the boot-resident MAPHEAD.SCN section for that screen
  (``scriptSetDigimon`` refuses to place an entity whose operand does not match the record
  type). Rewriting all of them in lockstep substitutes the species; the model comes from the
  species' ``.MMD`` (malloc3'd whole, so the substitute must not need more heap than the
  original) and its techniques from ``DIGIMON_DATA``.

Lab-validated 2026-08-28 through the three PATCH_PROCESS nets (parser round-trip, live RAM
after a fresh screen load, cold boot from the patched disc), including two real battles
(edited Goburimon stats, substituted Icemon fought to the end).

**Scaling policy ("progressive balancing")** -- ``enemy_scaling: vanilla_curve``: each region's
vanilla difficulty (mean stat budget of its wild records) is re-assigned by the region's
*logical depth* in this seed (the sphere in which it first becomes reachable): the shallowest
regions receive the weakest vanilla budgets, the deepest the strongest, interpolating over the
vanilla distribution. All records of a region scale by the same factor, so a boss stays
proportionally tougher than the fodder around it. ``enemy_scaling_strength`` blends between
vanilla (0) and the full re-assignment (100).

**Randomization policy** -- ``enemy_randomization: wild`` swaps every wild species on a screen
for another fighting species whose model fits the original's heap budget (and, with
``enemy_randomization_tier: same_level``, of the same evolution level), keeping the record's
stats and re-picking its moveset from the substitute's technique list. ``wild_and_story`` also
swaps story and recruit fights. Non-fighting NPCs, the intro tutorial and cutscene rooms are
never touched.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from BaseClasses import CollectionState

from .data.addresses import ROM_RECRUITMENT, SCREEN_FILENAMES
from .data.enemy_records import FIELD_RECORDS, MAPHEAD_SITES, SPECIES

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


# =============================================================================
# Typed views over the generated tables
# =============================================================================

class Species(NamedTuple):
    id: int
    name: str
    level: int
    moves: tuple[int, ...]      # 16 technique ids, 0xFF = empty slot
    heap: int                   # malloc3 footprint of the model, bytes (0 = no model file)

    @property
    def tech_slots(self) -> tuple[int, ...]:
        """Indices ``k`` whose technique exists; a record move byte is ``0x2E + k``."""
        return tuple(k for k, tech in enumerate(self.moves) if tech != 0xFF)

    @property
    def fights(self) -> bool:
        return self.heap > 0 and any(t not in (0xFF, 0x00) for t in self.moves)


class FieldRecord(NamedTuple):
    map: int
    slot: int
    bin_off: int
    type: int
    hp: int
    mp: int
    cur_hp: int
    cur_mp: int
    off: int
    defense: int
    spd: int
    brn: int
    bits: int
    moves: tuple[int, int, int, int]
    prio: tuple[int, int, int, int]
    script: int

    @property
    def stats(self) -> tuple[int, ...]:
        """The nine contiguous stat words, in on-disc order (hp .. bits)."""
        return (self.hp, self.mp, self.cur_hp, self.cur_mp, self.off, self.defense, self.spd, self.brn,
                self.bits)

    @property
    def budget(self) -> float:
        """A scalar difficulty measure comparable across records."""
        return (self.hp + self.mp / 2) / 10 + self.off + self.defense + self.spd + self.brn


class MapheadSite(NamedTuple):
    map: int
    file_off: int
    kind: int          # 0 = loadDigimon, 1 = setDigimon
    species: int
    slot: int          # -1 for loadDigimon


SPECIES_BY_ID: Final[dict[int, Species]] = {
    row[0]: Species(row[0], row[1], row[2], tuple(bytes.fromhex(row[3])), row[4]) for row in SPECIES
}
RECORDS: Final[tuple[FieldRecord, ...]] = tuple(
    FieldRecord(*row[:13], tuple(row[13:17]), tuple(row[17:21]), row[21]) for row in FIELD_RECORDS
)
RECORD_INDEX: Final[dict[tuple[int, int], FieldRecord]] = {(r.map, r.slot): r for r in RECORDS}
RECORDS_BY_MAP: Final[dict[int, tuple[FieldRecord, ...]]] = {}
for _rec in RECORDS:
    RECORDS_BY_MAP[_rec.map] = (*RECORDS_BY_MAP.get(_rec.map, ()), _rec)
SITES: Final[tuple[MapheadSite, ...]] = tuple(MapheadSite(*row) for row in MAPHEAD_SITES)
SITES_BY_MAP: Final[dict[int, tuple[MapheadSite, ...]]] = {}
for _site in SITES:
    SITES_BY_MAP[_site.map] = (*SITES_BY_MAP.get(_site.map, ()), _site)
del _rec, _site

ANIM_MOVE_BASE: Final = 0x2E
NO_MOVE: Final = 0xFF
STAT_CAP_HP_MP: Final = 9999
STAT_CAP_OTHER: Final = 999
BITS_CAP: Final = 9999


# =============================================================================
# Record classification
# =============================================================================

#: Species ids that AP recruit logic is built around (``ROM_RECRUITMENT``); their field
#: records are the recruit fights. Never touched by ``enemy_randomization: wild``.
RECRUIT_SPECIES_IDS: Final[frozenset[int]] = frozenset(entry.digimon_id for entry in ROM_RECRUITMENT)

#: Story bosses whose species id sits in the wild-species range: Machinedramon (final boss and
#: Back-Dimension rematches), WaruSeadramon (Secret Beach Cave), Meteormon (Meteorite Tribe),
#: WaruMonzaemon (Toy Town).
STORY_BOSS_SPECIES: Final[frozenset[int]] = frozenset({70, 112, 113, 115})

#: Species ids >= this are the game's NPC / story clones (``DIGIMON_DATA`` duplicates a
#: recruit's model under a second id for its quest fight or its town role).
CLONE_SPECIES_BASE: Final = 120

#: Screens whose fights are scripted tutorials or cutscene rooms: MAYO00 (the intro battle),
#: the Sukamon quest variants of Native Forest, and the ending / opening rooms.
EXCLUDED_SCREENS: Final[frozenset[int]] = frozenset({109, 110, 111, 236, 237, 238})

CLASS_WILD: Final = "wild"
CLASS_STORY: Final = "story"
CLASS_NPC: Final = "npc"


def classify_record(record: FieldRecord) -> str:
    """``wild`` (fodder), ``story`` (recruit / boss fight) or ``npc`` (never fights)."""

    species = SPECIES_BY_ID[record.type]
    if not species.fights:
        return CLASS_NPC
    if (record.type in RECRUIT_SPECIES_IDS or record.type in STORY_BOSS_SPECIES
            or record.type >= CLONE_SPECIES_BASE):
        return CLASS_STORY
    return CLASS_WILD


# =============================================================================
# Screen -> AP region
# =============================================================================

_PREFIX_REGIONS: Final[dict[str, str]] = {
    "MAYO": "Native Forest",
    "TROP": "Tropical Jungle",
    "MIHA": "Mt. Panorama",
    "TUNN": "Drill Tunnel",
    "DGHA": "Overdell",              # graveyard fodder: Tsukaimon / Soulmon / Darkrizamon
    "GCAN": "Great Canyon",
    "OGRE": "Great Canyon",          # Ogre Fortress sits inside the canyon
    "YAKA": "Grey Lord's Mansion",
    "SAIB": "Grey Lord's Mansion",   # SkullGreymon's basement
    "CHKA": "Back Dimension",        # the Machinedramon rematch entrance
    "GIAS": "Gear Savanna",
    "KODA": "Ancient Dino Region",
    "FRZL": "Freezeland",
    "ICSA": "Freezeland",            # Ice Sanctuary
    "BETL": "Beetle Land",
    "TRAI": "Beetle Land",           # Kabuterimon / Kuwagamon
    "LEOM": "Leomon Ancestor Cave",
    "MIST": "Misty Trees",
    "STIC": "Geko Swamp",            # Gekomon / Otamamon
    "GKYO": "Geko Swamp",
    "OMOC": "Toy Town",
    "FACT": "Factorial Town",
    "GOMI": "Factorial Town",        # Trash Mountain
    "MGEN": "Mt. Infinity",
    "TWNA": "File City",
    "TWNB": "File City",
    "ROOM": "File City",
}
_SCREEN_REGION_OVERRIDES: Final[dict[int, str]] = {
    6: "Greatlake", 8: "Greatlake",                       # the two fishing screens
    30: "Meramon Tunnel", 31: "Meramon Tunnel", 33: "Meramon Tunnel",
    122: "Meramon Tunnel", 123: "Meramon Tunnel", 124: "Meramon Tunnel",
    125: "Meramon Tunnel", 126: "Meramon Tunnel",
    142: "Secret Beach Cave", 143: "Secret Beach Cave",
    225: "Tower",                                         # MGEN99: the Machinedramon summit
    226: "Back Dimension", 227: "Back Dimension", 228: "Back Dimension",
    229: "Back Dimension", 230: "Back Dimension", 231: "Back Dimension",
}


def screen_region(map_id: int) -> str | None:
    """AP region a screen belongs to, or ``None`` for cutscene rooms / unmapped screens."""

    if map_id in _SCREEN_REGION_OVERRIDES:
        return _SCREEN_REGION_OVERRIDES[map_id]
    name = SCREEN_FILENAMES.get(map_id, "")
    return _PREFIX_REGIONS.get(name[:4])


# =============================================================================
# Logical depth (sphere of first reachability) per region
# =============================================================================

def compute_region_depths(world: DigimonWorldWorld) -> dict[str, int]:
    """Sphere index in which each of this player's regions first becomes reachable.

    Walks the filled multiworld exactly like :meth:`MultiWorld.get_spheres`, recording the
    reachable region set after each sphere's items are collected. Depth 0 = reachable with
    the starting inventory alone. Regions that never become reachable are absent.
    """

    multiworld, player = world.multiworld, world.player
    state = CollectionState(multiworld)
    remaining = set(multiworld.get_filled_locations())
    depths: dict[str, int] = {}
    sphere_index = 0
    while True:
        state.update_reachable_regions(player)
        for region in state.reachable_regions[player]:
            depths.setdefault(region.name, sphere_index)
        sphere = {location for location in remaining if location.can_reach(state)}
        if not sphere:
            break
        for location in sphere:
            state.collect(location.item, True, location)
        remaining -= sphere
        sphere_index += 1
    return depths


# =============================================================================
# Plans
# =============================================================================

class EnemyPlan(NamedTuple):
    """Everything the patcher needs; built once in ``post_fill``."""

    #: ``(map, slot) -> nine stat words`` (hp, mp, cur_hp, cur_mp, off, def, spd, brn, bits)
    stat_overrides: dict[tuple[int, int], tuple[int, ...]]
    #: ``(map, original species) -> substitute species``
    substitutions: dict[tuple[int, int], int]
    #: ``(map, slot) -> (moves4, prio4)`` for records whose species changed
    move_overrides: dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]]
    #: region -> depth, for the spoiler / tests
    region_depths: dict[str, int]
    #: region -> scale factor actually applied
    region_factors: dict[str, float]

    @property
    def empty(self) -> bool:
        return not (self.stat_overrides or self.substitutions or self.move_overrides)


EMPTY_PLAN: Final = EnemyPlan({}, {}, {}, {}, {})

SCALE_FACTOR_MIN: Final = 0.2
SCALE_FACTOR_MAX: Final = 5.0


def _clamp(value: float, low: int, high: int) -> int:
    return max(low, min(high, round(value)))


def scale_stats(record: FieldRecord, factor: float) -> tuple[int, ...]:
    hp = _clamp(record.hp * factor, 1, STAT_CAP_HP_MP)
    mp = _clamp(record.mp * factor, 1, STAT_CAP_HP_MP)
    return (
        hp, mp,
        min(hp, _clamp(record.cur_hp * factor, 1, STAT_CAP_HP_MP)),
        min(mp, _clamp(record.cur_mp * factor, 1, STAT_CAP_HP_MP)),
        _clamp(record.off * factor, 1, STAT_CAP_OTHER),
        _clamp(record.defense * factor, 1, STAT_CAP_OTHER),
        _clamp(record.spd * factor, 1, STAT_CAP_OTHER),
        _clamp(record.brn * factor, 1, STAT_CAP_OTHER),
        _clamp(record.bits * factor, 0, BITS_CAP),
    )


def region_wild_budgets() -> dict[str, float]:
    """Vanilla mean wild-record budget per region (regions with at least one wild record)."""

    totals: dict[str, list[float]] = {}
    for record in RECORDS:
        if record.map in EXCLUDED_SCREENS or classify_record(record) != CLASS_WILD:
            continue
        region = screen_region(record.map)
        if region is not None:
            totals.setdefault(region, []).append(record.budget)
    return {region: sum(values) / len(values) for region, values in totals.items()}


def plan_region_factors(region_depths: dict[str, int], strength: int) -> dict[str, float]:
    """Scale factor per region: vanilla budget distribution re-assigned by logical depth.

    Regions are ranked by depth (ties broken by vanilla budget so the vanilla order survives
    inside a sphere); rank ``i`` of ``n`` receives the ``i``-th smallest vanilla region budget.
    ``strength`` (0..100) blends the resulting factor towards 1.0.
    """

    budgets = region_wild_budgets()
    regions = [region for region in budgets if region in region_depths]
    if len(regions) < 2 or strength <= 0:
        return {}
    ordered = sorted(regions, key=lambda region: (region_depths[region], budgets[region]))
    targets = sorted(budgets[region] for region in regions)
    factors: dict[str, float] = {}
    for region, target in zip(ordered, targets, strict=True):
        raw = target / budgets[region]
        blended = 1.0 + (raw - 1.0) * strength / 100.0
        factors[region] = max(SCALE_FACTOR_MIN, min(SCALE_FACTOR_MAX, blended))
    return factors


def plan_stat_overrides(region_factors: dict[str, float]) -> dict[tuple[int, int], tuple[int, ...]]:
    overrides: dict[tuple[int, int], tuple[int, ...]] = {}
    for record in RECORDS:
        if record.map in EXCLUDED_SCREENS or classify_record(record) == CLASS_NPC:
            continue
        factor = region_factors.get(screen_region(record.map) or "")
        if factor is None or abs(factor - 1.0) < 1e-9:
            continue
        scaled = scale_stats(record, factor)
        if scaled != record.stats:
            overrides[(record.map, record.slot)] = scaled
    return overrides


def substitute_pool(original: Species, same_level: bool) -> list[Species]:
    """Fighting, non-story species whose model fits the original's heap budget."""

    return [
        species for species in SPECIES_BY_ID.values()
        if species.fights
        and species.id != original.id
        and species.id < CLONE_SPECIES_BASE
        and species.id not in RECRUIT_SPECIES_IDS
        and species.id not in STORY_BOSS_SPECIES
        and species.heap <= original.heap
        and (not same_level or species.level == original.level)
    ]


def pick_moveset(rng: Random, record: FieldRecord, species: Species) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Moves for ``record`` after it becomes ``species``: as many techniques as it had, drawn
    from the substitute's list; AI weights are kept."""

    count = sum(1 for move in record.moves if move != NO_MOVE)
    slots = species.tech_slots
    count = max(1, min(count, len(slots)))
    chosen = sorted(rng.sample(slots, count))
    moves = tuple(ANIM_MOVE_BASE + k for k in chosen) + (NO_MOVE,) * (4 - count)
    return moves, record.prio


def plan_substitutions(
    rng: Random, include_story: bool, same_level: bool,
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]]]:
    substitutions: dict[tuple[int, int], int] = {}
    move_overrides: dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for map_id in sorted(RECORDS_BY_MAP):
        if map_id in EXCLUDED_SCREENS or map_id not in SITES_BY_MAP:
            continue
        records = RECORDS_BY_MAP[map_id]
        for species_id in sorted({record.type for record in records}):
            group = [record for record in records if record.type == species_id]
            kinds = {classify_record(record) for record in group}
            if CLASS_NPC in kinds or (CLASS_STORY in kinds and not include_story):
                continue
            pool = substitute_pool(SPECIES_BY_ID[species_id], same_level)
            if not pool:
                continue
            substitute = rng.choice(sorted(pool, key=lambda species: species.id))
            substitutions[(map_id, species_id)] = substitute.id
            for record in group:
                move_overrides[(record.map, record.slot)] = pick_moveset(rng, record, substitute)
    return substitutions, move_overrides


def build_enemy_plan(world: DigimonWorldWorld) -> EnemyPlan:
    """Resolve both options into concrete record / MAPHEAD rewrites (call from ``post_fill``)."""

    options = world.options
    scaling = int(options.enemy_scaling.value)
    randomization = int(options.enemy_randomization.value)
    if not scaling and not randomization:
        return EMPTY_PLAN

    region_depths: dict[str, int] = {}
    region_factors: dict[str, float] = {}
    stat_overrides: dict[tuple[int, int], tuple[int, ...]] = {}
    if scaling:
        region_depths = compute_region_depths(world)
        region_factors = plan_region_factors(region_depths, int(options.enemy_scaling_strength.value))
        stat_overrides = plan_stat_overrides(region_factors)

    substitutions: dict[tuple[int, int], int] = {}
    move_overrides: dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]] = {}
    if randomization:
        substitutions, move_overrides = plan_substitutions(
            world.random,
            include_story=randomization >= 2,
            same_level=int(options.enemy_randomization_tier.value) == 0,
        )
    return EnemyPlan(stat_overrides, substitutions, move_overrides, region_depths, region_factors)
