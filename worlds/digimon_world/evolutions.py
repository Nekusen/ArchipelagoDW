"""Digivolution randomization for Digimon World 1: the natural tree, its requirements and the
special evolutions.

All three live in static SLUS data (:mod:`.data.enemy_records`: ``EVO_PATHS``,
``EVO_REQUIREMENTS``, ``EVO_GAINS``) plus a handful of code immediates / script bytes for the
special evolutions (``ROM_SPECIAL_EVO``), so a seed's changes are plain data writes.

How the game uses them (dw_decomp ``src/main/evolution.c``):

* Fresh -> In-Training is hard-coded (``getFreshEvolutionTarget``); the table rows of the four
  Fresh species only feed the digivolution chart, so they stay vanilla here.
* In-Training / Rookie / Champion walk their row's ``to[6]`` and pick the target whose
  requirements score >= 3 (care mistakes, weight +-5, stats, one bonus condition), Rookies and
  Champions preferring the target with the best average of the stats it requires.
* The special evolutions are direct: a death at Champion becomes Bakemon / Devimon /
  SkullGreymon / Phoenixmon, the Numemon suit gives Monzaemon (and opens Toy Town), etc.

The algorithm is a clean-room reimplementation of meekrhino's standalone randomizer
(``handler.py:randomizeEvolutions`` / ``randomizeEvolutionRequirements`` /
``randomizeSpecialEvolutions`` / ``updateEvolutionStats``) with its four knobs. Two deliberate
differences: Fresh rows are left alone (the game never reads them), and requirements are rolled
*after* the tree so a "current Digimon is X" bonus names a real predecessor.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.addresses import ROM_SPECIAL_EVO
from .data.enemy_records import EVO_GAINS, EVO_PATHS, EVO_REQUIREMENTS, SPECIES

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


LEVEL_FRESH: Final = 1
LEVEL_IN_TRAINING: Final = 2
LEVEL_ROOKIE: Final = 3
LEVEL_CHAMPION: Final = 4
LEVEL_ULTIMATE: Final = 5
LEVEL_NAMES: Final = {1: "Fresh", 2: "In-Training", 3: "Rookie", 4: "Champion", 5: "Ultimate"}

NONE: Final = -1
PATH_ROW_COUNT: Final = 62          # species 1..62
REQ_ROW_COUNT: Final = 63           # species 0..62
GAIN_ROW_COUNT: Final = 66          # species 0..65

SPECIES_NAME: Final[dict[int, str]] = {row[0]: row[1] for row in SPECIES}
SPECIES_LEVEL: Final[dict[int, int]] = {row[0]: row[2] for row in SPECIES}
SPECIES_TYPE: Final[dict[int, int]] = {row[0]: row[7] for row in SPECIES}

TYPE_DATA: Final = 1
TYPE_VACCINE: Final = 2
TYPE_VIRUS: Final = 3
#: Types the partner must have to enter a type-locked area (Ice Sanctuary: Vaccine, Greylord's
#: Mansion: Virus). Every Fresh line of a randomized tree is guaranteed to reach one of each, so a
#: seed played without ``type_lock_unlocks`` stays possible (Toy Town's Numemon needs no
#: guarantee: it is the Rookie fallback digivolution, reachable from any Rookie by design).
GUARANTEED_TYPES: Final = (TYPE_VACCINE, TYPE_VIRUS)

#: The partner-capable species (the standalone's ``playableDigimon``): 62 (WereGarurumon, level 0
#: in DIGIMON_DATA) is not one of them.
PARTNER_SPECIES_IDS: Final = (*range(1, 62), 63, 64, 65)
DEVIMON: Final = 6
#: Special-evolution-only species: never a natural target ...
NEVER_NATURAL_TARGETS: Final = frozenset({32, 11, 39, 53, 28, 63, 64, 65})   # Kunemon, Numemon, Sukamon,
#: ... and the three that have no requirements row at all.                     # Nanimon, Vademon, Panjyamon,
SPECIAL_ONLY_SPECIES: Final = frozenset({63, 64, 65})                          # Gigadramon, MetalEtemon
#: Species whose requirements row is cleared instead of rolled.
NO_REQUIREMENT_SPECIES: Final = frozenset({32, 11, 39, 53, 28, 62})

#: Slot order in which the game / standalone fill a row's ``to`` and ``from`` lists.
TO_FILL_ORDER: Final = (2, 3, 1, 4, 0, 5)
FROM_FILL_ORDER: Final = (2, 1, 3, 0, 4)
#: Natural targets per source level: (min, max).
TARGET_COUNTS: Final = {LEVEL_IN_TRAINING: (2, 2), LEVEL_ROOKIE: (4, 6), LEVEL_CHAMPION: (1, 2)}

FLAG_MAX_BATTLES: Final = 0x01
FLAG_MAX_CARE: Final = 0x10

#: ``EVL_applyEvolution`` (EVL overlay, read from its assembly 2026-08-29) applies a gains row in
#: one of two ways. *Additive* rows (Rookie / Champion / Ultimate targets): per stat,
#: ``new = (cur + gain) / 2`` when the stat is below the gain, else ``cur + gain / 10``, then the
#: 9999 / 999 clamp. *Scale* rows -- targets Devimon, Numemon, Sukamon, Nanimon, every Fresh /
#: In-Training target, and any evolution out of Sukamon -- ignore the five stat columns and use
#: the ``brains`` column as an ``int8`` multiplier x10 (10 = keep the stats). So Devimon's row
#: must never get "real" gains (the standalone's 1500/2000/.../200 row wraps to a negative
#: multiplier there), and only additive rows are ever randomized.
SCALE_PATH_SPECIES: Final = frozenset({DEVIMON, 11, 39, 53})
GAIN_COLUMNS: Final = ("HP", "MP", "Off", "Def", "Spd", "Brn")


class EvoPath(NamedTuple):
    frm: tuple[int, ...]        # 5 predecessors, -1 = empty
    to: tuple[int, ...]         # 6 natural targets, -1 = empty

    @property
    def targets(self) -> tuple[int, ...]:
        return tuple(t for t in self.to if t != NONE)

    @property
    def sources(self) -> tuple[int, ...]:
        return tuple(s for s in self.frm if s != NONE)


class EvoRequirements(NamedTuple):
    digimon: int        # bonus: current species is this one
    hp: int             # in tens
    mp: int             # in tens
    offense: int
    defense: int
    speed: int
    brain: int
    care: int           # care mistakes (min, or max with FLAG_MAX_CARE)
    weight: int         # +-5
    discipline: int     # bonus
    happiness: int      # bonus
    battles: int        # bonus (min, or max with FLAG_MAX_BATTLES)
    techs: int          # bonus: mastered techniques
    flags: int

    @property
    def stats(self) -> tuple[int, ...]:
        return (self.hp, self.mp, self.offense, self.defense, self.speed, self.brain)


NO_REQUIREMENTS: Final = EvoRequirements(*([NONE] * 13), 0)

VANILLA_PATHS: Final[dict[int, EvoPath]] = {
    index + 1: EvoPath(tuple(row[:5]), tuple(row[5:])) for index, row in enumerate(EVO_PATHS)
}
VANILLA_REQUIREMENTS: Final[dict[int, EvoRequirements]] = {
    index: EvoRequirements(*row) for index, row in enumerate(EVO_REQUIREMENTS)
}
VANILLA_GAINS: Final[dict[int, tuple[int, ...]]] = {index: tuple(row[:6]) for index, row in enumerate(EVO_GAINS)}


def species_of_level(level: int, exclude_special: bool = False) -> list[int]:
    return [
        species for species in PARTNER_SPECIES_IDS
        if SPECIES_LEVEL[species] == level and not (exclude_special and species in SPECIAL_ONLY_SPECIES)
    ]


def natural_targets(source_level: int, requirements_randomized: bool) -> list[int]:
    """Species one level up that a natural digivolution may lead to."""

    return [
        species for species in species_of_level(source_level + 1)
        if species not in NEVER_NATURAL_TARGETS and (species != DEVIMON or requirements_randomized)
    ]


class _Tree:
    def __init__(self) -> None:
        self.to: dict[int, list[int]] = {species: [NONE] * 6 for species in VANILLA_PATHS}
        self.frm: dict[int, list[int]] = {species: [NONE] * 5 for species in VANILLA_PATHS}

    def count(self, species: int) -> int:
        return sum(1 for target in self.to[species] if target != NONE)

    def add(self, species: int, target: int) -> None:
        for slot in TO_FILL_ORDER:
            if self.to[species][slot] == target:
                return
            if self.to[species][slot] == NONE:
                self.to[species][slot] = target
                return

    def update_from(self, species: int) -> None:
        sources = [source for source in sorted(self.to) if species in self.to[source]]
        for index, slot in enumerate(FROM_FILL_ORDER):
            self.frm[species][slot] = sources[index] if index < len(sources) else NONE

    def paths(self) -> dict[int, EvoPath]:
        return {species: EvoPath(tuple(self.frm[species]), tuple(self.to[species])) for species in self.to}


def reachable_from(paths: dict[int, EvoPath], species: int) -> set[int]:
    """Every species a partner starting as ``species`` can become by natural digivolution."""

    seen: set[int] = set()
    stack = [species]
    while stack:
        current = stack.pop()
        for target in (paths[current].targets if current in paths else ()):
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


def _guarantee_types(rng: Random, tree: _Tree, requirements_randomized: bool) -> None:
    """Make every Fresh line reach at least one species of each :data:`GUARANTEED_TYPES` by
    adding a Champion of the missing type to one of the line's Rookies (freeing that Rookie's
    last-filled slot if it is full, preferring a target that keeps another source)."""

    for fresh in species_of_level(LEVEL_FRESH):
        for wanted in GUARANTEED_TYPES:
            paths = tree.paths()
            reachable = reachable_from(paths, fresh)
            if any(SPECIES_TYPE[species] == wanted for species in reachable):
                continue
            rookies = sorted(species for species in reachable if SPECIES_LEVEL[species] == LEVEL_ROOKIE)
            candidates = [c for c in natural_targets(LEVEL_ROOKIE, requirements_randomized)
                          if SPECIES_TYPE[c] == wanted]
            if not rookies or not candidates:
                continue
            fewest = min(tree.count(r) for r in rookies)
            rookie = rng.choice([r for r in rookies if tree.count(r) == fewest])
            if tree.count(rookie) >= 6:
                sources = {t: [s for s in tree.to if t in tree.to[s]] for t in tree.to[rookie] if t != NONE}
                spare = [slot for slot in reversed(TO_FILL_ORDER)
                         if tree.to[rookie][slot] != NONE and len(sources[tree.to[rookie][slot]]) > 1]
                slot = spare[0] if spare else next(s for s in reversed(TO_FILL_ORDER) if tree.to[rookie][s] != NONE)
                tree.to[rookie][slot] = NONE
            tree.add(rookie, rng.choice(candidates))


def _assign_each_target_once(rng: Random, tree: _Tree, sources: list[int], pool: list[int]) -> None:
    """Obtain-all: give every target in ``pool`` at least one random source."""

    remaining = list(pool)
    while remaining:
        source = rng.choice(sources)
        before = tree.count(source)
        tree.add(source, remaining[0])
        if tree.count(source) > before:
            remaining.pop(0)


def randomize_tree(rng: Random, obtain_all: bool, requirements_randomized: bool) -> dict[int, EvoPath]:
    """New ``to`` / ``from`` lists for species 1..62; only rows that differ from vanilla are returned."""

    tree = _Tree()
    for species in species_of_level(LEVEL_FRESH):          # hard-coded in the game; keep the chart honest
        for target in VANILLA_PATHS[species].targets:
            tree.add(species, target)
    if 62 in VANILLA_PATHS:                                  # WereGarurumon: special-only, chart row stays
        tree.to[62] = list(VANILLA_PATHS[62].to)
        tree.frm[62] = list(VANILLA_PATHS[62].frm)

    pool = natural_targets(LEVEL_IN_TRAINING, requirements_randomized)
    for species in species_of_level(LEVEL_IN_TRAINING):
        tree.update_from(species)
        while tree.count(species) < TARGET_COUNTS[LEVEL_IN_TRAINING][1]:
            target = rng.choice(pool)
            tree.add(species, target)
            if obtain_all:
                pool.remove(target)

    rookies = species_of_level(LEVEL_ROOKIE)
    if obtain_all:
        _assign_each_target_once(rng, tree, rookies, natural_targets(LEVEL_ROOKIE, requirements_randomized))
    pool = natural_targets(LEVEL_ROOKIE, requirements_randomized)
    for species in rookies:
        wanted = rng.randint(*TARGET_COUNTS[LEVEL_ROOKIE])
        tree.update_from(species)
        while tree.count(species) < wanted:
            tree.add(species, rng.choice(pool))
    _guarantee_types(rng, tree, requirements_randomized)

    champions = species_of_level(LEVEL_CHAMPION, exclude_special=True)
    if obtain_all:
        _assign_each_target_once(rng, tree, champions, natural_targets(LEVEL_CHAMPION, requirements_randomized))
    pool = natural_targets(LEVEL_CHAMPION, requirements_randomized)
    for species in champions:
        wanted = rng.randint(*TARGET_COUNTS[LEVEL_CHAMPION])
        tree.update_from(species)
        while tree.count(species) < wanted:
            tree.add(species, rng.choice(pool))

    for species in species_of_level(LEVEL_ULTIMATE, exclude_special=True):
        tree.update_from(species)
    for species in rookies:                       # a guarantee pass may have re-targeted a Rookie
        tree.update_from(species)

    return {species: path for species, path in tree.paths().items() if path != VANILLA_PATHS[species]}


def random_stat_requirements(rng: Random, level: int) -> tuple[int, ...]:
    """Rookies: three stats flagged 1 (the partner's highest stat must be one of them).
    Champions: 1-4 stats at 100 (HP / MP 1000). Ultimates: 4-6 stats at 200-500, or 300-700
    three times in ten."""

    requirements = [NONE] * 6
    choices = [0, 1, 2, 3, 4, 5]
    if level == LEVEL_ROOKIE:
        count, values = 3, lambda: 1
    elif level == LEVEL_CHAMPION:
        count, values = rng.randint(1, 4), lambda: 100
    else:
        count = rng.randint(4, 6)
        hard = rng.randint(0, 99) > 70
        values = (lambda: rng.randint(3, 7) * 100) if hard else (lambda: rng.randint(2, 5) * 100)
    for _ in range(count):
        stat = rng.choice(choices)
        choices.remove(stat)
        requirements[stat] = values()
    return tuple(requirements)


def _roll_requirements(rng: Random, species: int, level: int, predecessor: int) -> EvoRequirements:
    stats = random_stat_requirements(rng, level)
    if level == LEVEL_ROOKIE:
        # care >= 0, techs >= 0 and battles >= -2 are always met: a Rookie only needs its stats
        return EvoRequirements(predecessor, *stats, care=0, weight=15, discipline=NONE, happiness=NONE,
                               battles=-2, techs=0, flags=0)
    ultimate = level == LEVEL_ULTIMATE
    max_care = rng.choice((True, False))
    if ultimate:
        care = rng.randint(0, 15) if max_care else rng.randint(5, 15)
        weight = rng.randint(1, 14) * 5
        techs = rng.randint(21, 50)
    else:
        care = rng.randint(0, 6) if max_care else rng.randint(2, 6)
        weight = rng.randint(1, 10) * 5
        techs = rng.randint(10, 35)
    bonus_count = 1
    discipline, battles, digimon, max_battles = NONE, NONE, NONE, False
    if rng.randint(0, 99) < 10:
        discipline = rng.randint(90, 100) if ultimate else rng.randint(50, 95)
        bonus_count += 1
    if rng.randint(0, 99) < 10:
        discipline = rng.randint(90, 100) if ultimate else rng.randint(45, 85)
        bonus_count += 1
    if rng.randint(0, 99) < 30:
        max_battles = rng.choice((True, False))
        if ultimate:
            battles = rng.randint(0, 15) if max_battles else rng.randint(5, 20) * 5
        else:
            battles = rng.randint(2, 15)
        bonus_count += 1
    if rng.randint(0, 99) < 10 or bonus_count < 2:
        digimon = predecessor
        bonus_count += 1
    flags = (FLAG_MAX_BATTLES if max_battles else 0) | (FLAG_MAX_CARE if max_care else 0)
    return EvoRequirements(digimon, *stats, care=care, weight=weight, discipline=discipline, happiness=NONE,
                           battles=battles, techs=techs, flags=flags)


def randomize_requirements(rng: Random, paths: dict[int, EvoPath]) -> dict[int, EvoRequirements]:
    """New requirement rows for species 0..62 (``paths`` = the final tree, vanilla where unchanged);
    only rows that differ from vanilla are returned."""

    out: dict[int, EvoRequirements] = {}
    for species in range(REQ_ROW_COUNT):
        level = SPECIES_LEVEL[species]
        if species not in PARTNER_SPECIES_IDS or level < LEVEL_ROOKIE or species in NO_REQUIREMENT_SPECIES:
            out[species] = NO_REQUIREMENTS
        else:
            predecessor = paths[species].frm[FROM_FILL_ORDER[0]] if species in paths else NONE
            out[species] = _roll_requirements(rng, species, level, predecessor)
    return {species: reqs for species, reqs in out.items() if reqs != VANILLA_REQUIREMENTS[species]}


SPECIAL_EVOLUTION_NAMES: Final = (
    "Monzaemon (Numemon suit / Toy Town)", "Giromon", "MetalMamemon", "Bakemon", "SkullGreymon", "Phoenixmon",
    "Devimon", "Airdramon", "Ninjamon", "Monochromon", "Kunemon", "Coelamon", "Nanimon", "Vademon", "Sukamon",
)
assert len(SPECIAL_EVOLUTION_NAMES) == len(ROM_SPECIAL_EVO)


def randomize_special_evolutions(rng: Random) -> dict[int, int]:
    """Each special evolution's result becomes a random partner species of the same level (never
    the vanilla result, never the source); ``ROM_SPECIAL_EVO`` index -> new species."""

    out: dict[int, int] = {}
    for index, (_offsets, target, source) in enumerate(ROM_SPECIAL_EVO):
        pool = [species for species in species_of_level(SPECIES_LEVEL[target]) if species not in (target, source)]
        out[index] = rng.choice(pool)
    return out


def additive_gain_species() -> list[int]:
    """Species whose gains row takes the additive path (Rookie+ targets outside the scale set)."""

    return [species for species in VANILLA_GAINS
            if SPECIES_LEVEL[species] >= LEVEL_ROOKIE and species not in SCALE_PATH_SPECIES]


def gain_envelope(level: int) -> tuple[tuple[int, int], ...]:
    """Per column, the vanilla ``(min, max)`` over the additive rows of that level."""

    rows = [VANILLA_GAINS[s] for s in additive_gain_species() if SPECIES_LEVEL[s] == level]
    return tuple((min(row[c] for row in rows), max(row[c] for row in rows)) for c in range(6))


def randomize_gains(rng: Random) -> dict[int, tuple[int, ...]]:
    """New six-column gains for every additive row, uniform inside the vanilla envelope of the
    target's level (HP / MP to the nearest 10, the rest to the nearest 5). Scale-path rows and
    the ``targetDigimon`` word are never touched."""

    out: dict[int, tuple[int, ...]] = {}
    envelopes = {level: gain_envelope(level) for level in (LEVEL_ROOKIE, LEVEL_CHAMPION, LEVEL_ULTIMATE)}
    for species in additive_gain_species():
        envelope = envelopes[SPECIES_LEVEL[species]]
        row = []
        for column, (low, high) in enumerate(envelope):
            step = 10 if column < 2 else 5
            value = rng.randint(low, high)
            row.append(max(low, min(high, round(value / step) * step)))
        if tuple(row) != VANILLA_GAINS[species]:
            out[species] = tuple(row)
    return out


class EvolutionPlan(NamedTuple):
    #: species -> new tree row (species 1..62)
    paths: dict[int, EvoPath]
    #: species -> new requirements row (species 0..62)
    requirements: dict[int, EvoRequirements]
    #: species -> six stat gains (additive rows only)
    gains: dict[int, tuple[int, ...]]
    #: ``ROM_SPECIAL_EVO`` index -> new result species
    special: dict[int, int]

    @property
    def empty(self) -> bool:
        return not (self.paths or self.requirements or self.gains or self.special)


EMPTY_PLAN: Final = EvolutionPlan({}, {}, {}, {})


def build_evolution_plan(world: DigimonWorldWorld) -> EvolutionPlan:
    """Resolve the digivolution options into concrete table rewrites (call from ``generate_early``)."""

    options = world.options
    rng = world.random
    paths: dict[int, EvoPath] = {}
    requirements: dict[int, EvoRequirements] = {}
    special: dict[int, int] = {}
    if options.digivolution_randomization:
        requirements_on = bool(options.digivolution_requirements.value)
        paths = randomize_tree(rng, bool(options.digivolution_obtain_all.value), requirements_on)
        if requirements_on:
            requirements = randomize_requirements(rng, {**VANILLA_PATHS, **paths})
        if options.special_digivolutions:
            special = randomize_special_evolutions(rng)
    gains = randomize_gains(rng) if options.digivolution_stat_gains else {}
    return EvolutionPlan(paths, requirements, gains, special)


def describe_gains(gains: tuple[int, ...]) -> str:
    return " / ".join(f"{label} +{value}" for label, value in zip(GAIN_COLUMNS, gains, strict=True))


def describe_path(species: int, path: EvoPath) -> str:
    targets = ", ".join(SPECIES_NAME[t] for t in path.targets) or "-"
    return f"{SPECIES_NAME[species]} -> {targets}"


def describe_requirements(reqs: EvoRequirements) -> str:
    if reqs == NO_REQUIREMENTS:
        return "none"
    labels = ("HP", "MP", "Off", "Def", "Spd", "Brn")
    parts = []
    flagged = [(label, value) for label, value in zip(labels, reqs.stats, strict=True) if value != NONE]
    if flagged and all(value == 1 for _, value in flagged):          # Rookie rule: best stat among these
        parts.append("highest stat among " + " / ".join(label for label, _ in flagged))
    elif flagged:
        parts.append("stats >= " + " / ".join(
            f"{label} {value * 10 if label in ('HP', 'MP') else value}" for label, value in flagged))
    if reqs.care != NONE:
        parts.append(f"care mistakes {'<=' if reqs.flags & FLAG_MAX_CARE else '>='} {reqs.care}")
    if reqs.weight != NONE:
        parts.append(f"weight {reqs.weight}+-5")
    bonus = []
    if reqs.digimon != NONE:
        bonus.append(f"from {SPECIES_NAME.get(reqs.digimon, reqs.digimon)}")
    if reqs.discipline != NONE:
        bonus.append(f"discipline >= {reqs.discipline}")
    if reqs.happiness != NONE:
        bonus.append(f"happiness >= {reqs.happiness}")
    if reqs.battles != NONE:
        bonus.append(f"battles {'<=' if reqs.flags & FLAG_MAX_BATTLES else '>='} {reqs.battles}")
    if reqs.techs != NONE:
        bonus.append(f"techniques >= {reqs.techs}")
    if bonus:
        parts.append("bonus: " + " | ".join(bonus))
    return "; ".join(parts)
