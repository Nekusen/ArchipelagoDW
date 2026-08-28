"""Enemy stats, technique and species randomization for Digimon World 1.

All of it is a pure data rewrite of the vanilla disc -- no code hooks:

* Every field Digimon (wild fodder and story boss alike) is a record in its screen's
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
* A record's move bytes are animation slots ``0x2E + k`` into the species' 16-slot technique
  list, so a Digimon can only ever use its own list; "scaling techniques" means choosing the
  entries of that list whose ``MOVE_DATA.power`` fits the intended level.

Lab-validated 2026-08-28 through the three PATCH_PROCESS nets (parser round-trip, live RAM
after a fresh screen load, cold boot from the patched disc), including two real battles
(edited Goburimon stats, substituted Icemon fought to the end).

Two independent options:

**``enemy_randomization``** (off / wild / wild_and_story, plus ``enemy_randomization_tier``) swaps
every wild species on a screen for another fighting species whose model fits the original's
heap budget (and, with ``same_level``, of the same evolution level). ``wild_and_story`` also
swaps story and recruit fights. Non-fighting NPCs, the intro tutorial and cutscene rooms are
never touched.

**``enemy_stats``** decides stats *and* movesets together:

* ``vanilla`` -- records keep their stats. A swapped species receives, from its own list, the
  techniques closest in power to the ones the original record used.
* ``progressive`` -- each region's vanilla difficulty (mean stat budget and mean technique
  power of its wild records) is re-assigned by the region's *logical depth* in this seed (the
  sphere in which it first becomes reachable): the shallowest regions receive the weakest
  vanilla budgets, the deepest the strongest. All records of a region scale by the same
  factor and re-pick their techniques around the region's target power, so a boss stays
  proportionally tougher than the fodder around it. ``enemy_stats_strength`` blends between
  vanilla (0) and the full re-assignment (100).
* ``full_random`` -- every screen borrows the difficulty of a random vanilla screen (stats
  scaled to that screen's budget, so nothing leaves the vanilla range) and its Digimon draw
  random techniques from their lists.

AI weights (priorities) are never changed; a record keeps as many techniques as it had.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from BaseClasses import CollectionState

from .data.addresses import ROM_RECRUITMENT, SCREEN_FILENAMES
from .data.enemy_records import FIELD_RECORDS, MAPHEAD_SITES, MOVES, SPECIES

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


# =============================================================================
# Typed views over the generated tables
# =============================================================================

class Move(NamedTuple):
    id: int
    name: str
    power: int          # damage base; 0 = buff / status-only technique
    mp_cost: int        # stored byte; the game charges mp_cost * 3
    element: int        # 0..6, index into the affinity matrix
    status: int         # 0 none, 1 poison, 2 confusion, 3 stun, 4 flat
    accuracy: int
    status_chance: int  # percent
    range: int
    iframes: int
    distance: int
    unk3: int
    unk4: int
    unk5: int


MOVES_BY_ID: Final[dict[int, Move]] = {row[0]: Move(*row) for row in MOVES}

#: ``technique id -> damage base`` as on the disc. The planners take a ``powers`` table so a seed
#: that randomizes ``MOVE_DATA`` (:mod:`.techniques`) scales enemies by the powers it ships.
VANILLA_POWERS: Final[dict[int, int]] = {move.id: move.power for move in MOVES_BY_ID.values()}


class Species(NamedTuple):
    id: int
    name: str
    level: int
    moves: tuple[int, ...]      # 16 technique ids, 0xFF = empty slot
    heap: int                   # malloc3 footprint of the model, bytes (0 = no model file)
    drop_item: int              # ITEM_PARA id dropped after a won battle ...
    drop_chance: int            # ... with this percent chance

    @property
    def tech_slots(self) -> tuple[int, ...]:
        """Indices ``k`` whose technique exists; a record move byte is ``0x2E + k``."""
        return tuple(k for k, tech in enumerate(self.moves) if tech != 0xFF)

    @property
    def damaging_slots(self) -> tuple[int, ...]:
        """Slots whose technique deals damage (vanilla power > 0)."""
        return self.damaging_slots_for(VANILLA_POWERS)

    def damaging_slots_for(self, powers: dict[int, int]) -> tuple[int, ...]:
        return tuple(k for k in self.tech_slots if self.slot_power(k, powers) > 0)

    def slot_power(self, slot: int, powers: dict[int, int] = VANILLA_POWERS) -> int:
        return powers[self.moves[slot]]

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

    @property
    def move_count(self) -> int:
        """Techniques the record resolves to a real entry of its species list.

        235 vanilla records point some slots past the end of their list (Ogremon clones,
        Monochromon's shop customers ...); ``loadBattleData`` drops those, so a record with
        no valid technique is a non-combat placement and is left alone.
        """
        return len(self.tech_powers())

    def tech_powers(self, species: Species | None = None,
                    powers: dict[int, int] = VANILLA_POWERS) -> tuple[int, ...]:
        """Power of each technique the record uses, in slot order."""
        species = species or SPECIES_BY_ID[self.type]
        return tuple(
            species.slot_power(move - ANIM_MOVE_BASE, powers) for move in self.moves
            if move != NO_MOVE and 0 <= move - ANIM_MOVE_BASE < 16 and species.moves[move - ANIM_MOVE_BASE] != 0xFF
        )


class MapheadSite(NamedTuple):
    map: int
    file_off: int
    kind: int          # 0 = loadDigimon, 1 = setDigimon
    species: int
    slot: int          # -1 for loadDigimon


SPECIES_BY_ID: Final[dict[int, Species]] = {
    row[0]: Species(row[0], row[1], row[2], tuple(bytes.fromhex(row[3])), row[4], row[5], row[6]) for row in SPECIES
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

STATS_VANILLA: Final = 0
STATS_PROGRESSIVE: Final = 1
STATS_FULL_RANDOM: Final = 2


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

#: Regions whose "wild" records are decoration (the baby Digimon strolling around File City)
#: or otherwise never start a field battle: no metrics, no scaling, no substitution there.
NON_COMBAT_REGIONS: Final[frozenset[str]] = frozenset({"File City"})

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


def _combat_screen(map_id: int) -> bool:
    return map_id not in EXCLUDED_SCREENS and screen_region(map_id) not in NON_COMBAT_REGIONS


def _touchable(record: FieldRecord) -> bool:
    return _combat_screen(record.map) and classify_record(record) != CLASS_NPC and record.move_count > 0


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
# Vanilla difficulty metrics
# =============================================================================

class WildMetrics(NamedTuple):
    budget: float                 # mean stat budget of the wild records
    tech_level: float | None      # mean power of the damaging techniques they use (None: none)


class Targets(NamedTuple):
    stat_factor: float            # multiplier applied to every fighter record's stats
    tech_level: float | None      # power the techniques are re-picked around (None: keep)


def _metrics(records: list[FieldRecord], powers: dict[int, int]) -> WildMetrics:
    tech_powers = [p for record in records for p in record.tech_powers(powers=powers) if p > 0]
    return WildMetrics(
        sum(r.budget for r in records) / len(records),
        sum(tech_powers) / len(tech_powers) if tech_powers else None,
    )


def _wild_records() -> list[FieldRecord]:
    return [r for r in RECORDS if _touchable(r) and classify_record(r) == CLASS_WILD
            and screen_region(r.map) is not None]


def region_wild_metrics(powers: dict[int, int] = VANILLA_POWERS) -> dict[str, WildMetrics]:
    """Vanilla wild-record metrics per region (regions with at least one wild record)."""

    groups: dict[str, list[FieldRecord]] = {}
    for record in _wild_records():
        groups.setdefault(screen_region(record.map), []).append(record)   # type: ignore[arg-type]
    return {region: _metrics(records, powers) for region, records in groups.items()}


def screen_wild_metrics(powers: dict[int, int] = VANILLA_POWERS) -> dict[int, WildMetrics]:
    """Vanilla wild-record metrics per screen (screens with at least one wild record)."""

    groups: dict[int, list[FieldRecord]] = {}
    for record in _wild_records():
        groups.setdefault(record.map, []).append(record)
    return {map_id: _metrics(records, powers) for map_id, records in groups.items()}


def region_wild_budgets() -> dict[str, float]:
    return {region: metrics.budget for region, metrics in region_wild_metrics().items()}


# =============================================================================
# Targets: progressive (per region) and full random (per screen)
# =============================================================================

SCALE_FACTOR_MIN: Final = 0.2
SCALE_FACTOR_MAX: Final = 5.0


def _blend(vanilla: float, assigned: float, strength: int) -> float:
    return vanilla + (assigned - vanilla) * strength / 100.0


def plan_region_targets(
    region_depths: dict[str, int], strength: int, powers: dict[int, int] = VANILLA_POWERS,
) -> dict[str, Targets]:
    """Progressive: vanilla difficulty distribution re-assigned by logical depth.

    Regions are ranked by depth (ties broken by vanilla budget so the vanilla order survives
    inside a sphere); rank ``i`` of ``n`` receives the ``i``-th smallest vanilla budget and,
    among the regions that have one, the ``i``-th smallest vanilla technique level.
    ``strength`` (0..100) blends both towards vanilla.
    """

    metrics = region_wild_metrics(powers)
    regions = [region for region in metrics if region in region_depths]
    if len(regions) < 2 or strength <= 0:
        return {}
    ordered = sorted(regions, key=lambda region: (region_depths[region], metrics[region].budget))
    budgets = sorted(metrics[region].budget for region in regions)
    targets: dict[str, Targets] = {}
    for region, budget in zip(ordered, budgets, strict=True):
        raw = budget / metrics[region].budget
        factor = max(SCALE_FACTOR_MIN, min(SCALE_FACTOR_MAX, _blend(1.0, raw, strength)))
        targets[region] = Targets(factor, None)
    with_level = [region for region in ordered if metrics[region].tech_level is not None]
    levels = sorted(metrics[region].tech_level for region in with_level)   # type: ignore[type-var]
    for region, level in zip(with_level, levels, strict=True):
        vanilla_level = metrics[region].tech_level
        assert vanilla_level is not None
        targets[region] = Targets(targets[region].stat_factor, _blend(vanilla_level, level, strength))
    return targets


def plan_full_random_targets(rng: Random, powers: dict[int, int] = VANILLA_POWERS) -> dict[int, Targets]:
    """Full random: every screen borrows the difficulty of a random vanilla screen."""

    metrics = screen_wild_metrics(powers)
    donors = sorted(metrics)
    targets: dict[int, Targets] = {}
    for map_id in sorted(metrics):
        donor = metrics[rng.choice(donors)]
        factor = max(SCALE_FACTOR_MIN, min(SCALE_FACTOR_MAX, donor.budget / metrics[map_id].budget))
        targets[map_id] = Targets(factor, donor.tech_level)
    return targets


def screen_targets_from_regions(region_targets: dict[str, Targets]) -> dict[int, Targets]:
    """Expand per-region targets to every screen with records in those regions."""

    out: dict[int, Targets] = {}
    for map_id in RECORDS_BY_MAP:
        region = screen_region(map_id)
        if region in region_targets and _combat_screen(map_id):
            out[map_id] = region_targets[region]
    return out


# =============================================================================
# Stat and move rewrites
# =============================================================================

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


def plan_stat_overrides(screen_targets: dict[int, Targets]) -> dict[tuple[int, int], tuple[int, ...]]:
    overrides: dict[tuple[int, int], tuple[int, ...]] = {}
    for record in RECORDS:
        target = screen_targets.get(record.map)
        if target is None or abs(target.stat_factor - 1.0) < 1e-9 or not _touchable(record):
            continue
        scaled = scale_stats(record, target.stat_factor)
        if scaled != record.stats:
            overrides[(record.map, record.slot)] = scaled
    return overrides


def _moves_from_slots(slots: list[int]) -> tuple[int, ...]:
    return tuple(ANIM_MOVE_BASE + k for k in slots) + (NO_MOVE,) * (4 - len(slots))


def pick_moves_by_level(
    species: Species, count: int, target: float, powers: dict[int, int] = VANILLA_POWERS,
) -> tuple[int, ...]:
    """The ``count`` damaging techniques of ``species`` closest in power to ``target``
    (deterministic; buffs only fill in when the list runs out of damaging ones)."""

    ranked = sorted(species.damaging_slots_for(powers), key=lambda k: (abs(species.slot_power(k, powers) - target), k))
    chosen = ranked[:count]
    if len(chosen) < count:
        chosen += [k for k in species.tech_slots if k not in chosen][:count - len(chosen)]
    return _moves_from_slots(sorted(chosen))


def pick_moves_equivalent(
    record: FieldRecord, original: Species, substitute: Species, powers: dict[int, int] = VANILLA_POWERS,
) -> tuple[int, ...]:
    """For each technique the record used, the substitute's unused technique closest in power."""

    chosen: list[int] = []
    for power in record.tech_powers(original, powers):
        candidates = [k for k in substitute.tech_slots if k not in chosen]
        if not candidates:
            break
        chosen.append(min(candidates, key=lambda k: (abs(substitute.slot_power(k, powers) - power), k)))
    if not chosen and substitute.tech_slots:
        chosen.append(substitute.tech_slots[0])
    return _moves_from_slots(sorted(chosen))


def pick_moves_random(rng: Random, species: Species, count: int) -> tuple[int, ...]:
    slots = species.tech_slots
    count = max(1, min(count, len(slots)))
    return _moves_from_slots(sorted(rng.sample(slots, count)))


def plan_move_overrides(
    mode: int, rng: Random, final_species: dict[tuple[int, int], int], screen_targets: dict[int, Targets],
    powers: dict[int, int] = VANILLA_POWERS,
) -> dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]]:
    """Movesets for every fighter record whose species or whose screen's technique level changed."""

    overrides: dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for record in RECORDS:
        key = (record.map, record.slot)
        if not _touchable(record):
            # a swapped non-combat placement keeps "no techniques" explicitly: its dead slots
            # could resolve to real entries of the substitute's longer list
            if (key in final_species and final_species[key] != record.type
                    and _combat_screen(record.map) and classify_record(record) != CLASS_NPC):
                overrides[key] = ((NO_MOVE,) * 4, record.prio)
            continue
        species = SPECIES_BY_ID[final_species.get(key, record.type)]
        swapped = species.id != record.type
        target = screen_targets.get(record.map)
        level = target.tech_level if target is not None else None
        count = record.move_count
        if mode == STATS_FULL_RANDOM and target is not None:
            moves = pick_moves_random(rng, species, count)
        elif mode == STATS_PROGRESSIVE and level is not None:
            moves = pick_moves_by_level(species, count, level, powers)
        elif swapped:
            moves = pick_moves_equivalent(record, SPECIES_BY_ID[record.type], species, powers)
        else:
            continue
        if swapped or moves != record.moves:
            overrides[key] = (moves, record.prio)
    return overrides


# =============================================================================
# Species substitution
# =============================================================================

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


def plan_substitutions(
    rng: Random, include_story: bool, same_level: bool,
) -> tuple[dict[tuple[int, int], int], dict[tuple[int, int], int]]:
    """Returns ``(map, original species) -> substitute`` and ``(map, slot) -> final species``."""

    substitutions: dict[tuple[int, int], int] = {}
    final_species: dict[tuple[int, int], int] = {}
    for map_id in sorted(RECORDS_BY_MAP):
        if not _combat_screen(map_id) or map_id not in SITES_BY_MAP:
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
                final_species[(record.map, record.slot)] = substitute.id
    return substitutions, final_species


# =============================================================================
# Plan
# =============================================================================

class EnemyPlan(NamedTuple):
    """Everything the patcher needs; built once in ``post_fill``."""

    #: ``(map, slot) -> nine stat words`` (hp, mp, cur_hp, cur_mp, off, def, spd, brn, bits)
    stat_overrides: dict[tuple[int, int], tuple[int, ...]]
    #: ``(map, original species) -> substitute species``
    substitutions: dict[tuple[int, int], int]
    #: ``(map, slot) -> (moves4, prio4)``
    move_overrides: dict[tuple[int, int], tuple[tuple[int, ...], tuple[int, ...]]]
    #: region -> depth (progressive only), for the spoiler / tests
    region_depths: dict[str, int]
    #: region -> targets (progressive) for the spoiler
    region_targets: dict[str, Targets]
    #: screen -> targets (full random) for the spoiler
    screen_targets: dict[int, Targets]

    @property
    def empty(self) -> bool:
        return not (self.stat_overrides or self.substitutions or self.move_overrides)


EMPTY_PLAN: Final = EnemyPlan({}, {}, {}, {}, {}, {})


def build_enemy_plan(world: DigimonWorldWorld) -> EnemyPlan:
    """Resolve both options into concrete record / MAPHEAD rewrites (call from ``post_fill``)."""

    options = world.options
    mode = int(options.enemy_stats.value)
    randomization = int(options.enemy_randomization.value)
    if mode == STATS_VANILLA and not randomization:
        return EMPTY_PLAN
    rng = world.random
    # a seed that randomizes MOVE_DATA scales enemies by the powers it ships, not the vanilla ones
    powers = world.technique_plan.powers

    substitutions: dict[tuple[int, int], int] = {}
    final_species: dict[tuple[int, int], int] = {}
    if randomization:
        substitutions, final_species = plan_substitutions(
            rng, include_story=randomization >= 2,
            same_level=int(options.enemy_randomization_tier.value) == 0,
        )

    region_depths: dict[str, int] = {}
    region_targets: dict[str, Targets] = {}
    screen_targets: dict[int, Targets] = {}
    if mode == STATS_PROGRESSIVE:
        region_depths = compute_region_depths(world)
        region_targets = plan_region_targets(region_depths, int(options.enemy_stats_strength.value), powers)
        screen_targets = screen_targets_from_regions(region_targets)
    elif mode == STATS_FULL_RANDOM:
        screen_targets = plan_full_random_targets(rng, powers)

    stat_overrides = plan_stat_overrides(screen_targets)
    move_overrides = plan_move_overrides(mode, rng, final_species, screen_targets, powers)
    return EnemyPlan(stat_overrides, substitutions, move_overrides, region_depths, region_targets,
                     screen_targets if mode == STATS_FULL_RANDOM else {})
