"""Species technique-list randomization for Digimon World 1.

Every species carries a 16-slot technique list (``DIGIMON_DATA[type].moves[16]``, SLUS
0x8012CEB4 + type * 52 + 35). A Digimon plays slot ``k`` through animation ``0x2E + k`` of its
model, and the `.MMD` census of 2026-08-29 (``work/dw1_re/decomp/mmd_census/NOTES.md``) showed
that a model carries an animation for exactly its populated slots — so a list can only ever be
re-filled **in place**, never grow (the animation is per slot; effect, projectile, sound and hit
timing follow the technique id).

The randomization keeps every structural property the engine relies on:

* the populated slots stay populated (slot 0 is the reincarnation default, ``moves[0] = 0x2E``);
* a slot keeps its **class** -- normal technique (id < 58), enemy finisher (58..112) or bubble
  attack (113..120) -- because field records point their 4th move at the finisher slot and the
  versus mode needs one finisher-class id per species;
* a slot keeps its **element**, so the partner can still learn the technique in battle (the
  learn filter only accepts techniques whose element matches one of the species' specialties)
  and brain training (per-specialty tier lists) keeps finding entries;
* no technique appears twice in a list;
* H-Kabuterimon's slot 14 is hard-wired in ``entityGetTechFromAnim`` and stays vanilla, and the
  Kuwagamon story clone whose model has no technique animations is left alone.

Wild Digimon use whatever now sits in their slots; ``enemy_stats`` reads the shuffled lists
through :attr:`ListPlan.species_table` so its power-based picks stay meaningful.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.enemy_records import MOVES
from .enemies import NO_MOVE, SPECIES_BY_ID, Species
from .techniques import MOVE_NAMES, PARTNER_MOVE_COUNT, VANILLA_VALUES

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


LIST_SLOTS: Final = 16
FINISHER_FIRST: Final = PARTNER_MOVE_COUNT     # 58
BUBBLE_FIRST: Final = 113
BUBBLE_LAST: Final = 120
#: H-Kabuterimon: ``entityGetTechFromAnim`` returns technique 0x70 for its slot 14 whatever the list says.
HARDWIRED_SLOTS: Final[dict[int, tuple[int, ...]]] = {60: (14,)}
#: The Kuwagamon story clone (TRAI00 / BETL04) whose model has no technique animations at all.
EXCLUDED_SPECIES: Final = frozenset({169})

CLASS_NORMAL: Final = 0
CLASS_FINISHER: Final = 1
CLASS_BUBBLE: Final = 2

ELEMENT_OF: Final[dict[int, int]] = {row[0]: row[4] for row in MOVES}


def tech_class(tech_id: int) -> int:
    if tech_id < FINISHER_FIRST:
        return CLASS_NORMAL
    if tech_id < BUBBLE_FIRST:
        return CLASS_FINISHER
    return CLASS_BUBBLE


def candidate_pool(tech_id: int) -> list[int]:
    """Techniques that may replace ``tech_id``: same class, same element (bubbles never move)."""

    cls = tech_class(tech_id)
    if cls == CLASS_BUBBLE:
        return [tech_id]
    return [
        other for other in sorted(VANILLA_VALUES)
        if other <= BUBBLE_LAST and tech_class(other) == cls and ELEMENT_OF[other] == ELEMENT_OF[tech_id]
    ]


def shuffleable_species() -> list[int]:
    """Species with a real technique list: partner-capable or field fighters with a model."""

    return [
        species.id for species in SPECIES_BY_ID.values()
        if species.fights and species.id not in EXCLUDED_SPECIES
    ]


def randomize_list(rng: Random, species: Species) -> tuple[int, ...]:
    """A new 16-slot list for ``species``: each populated slot re-drawn inside its class and
    element, without repeats (falls back to the vanilla technique when the pool is exhausted)."""

    new = list(species.moves)
    taken: set[int] = set()
    for slot, tech_id in enumerate(species.moves):
        if tech_id == NO_MOVE or slot in HARDWIRED_SLOTS.get(species.id, ()):
            taken.add(tech_id)
            continue
        pool = [t for t in candidate_pool(tech_id) if t not in taken]
        choice = rng.choice(pool) if pool else tech_id
        new[slot] = choice
        taken.add(choice)
    return tuple(new)


def randomize_lists(rng: Random) -> dict[int, tuple[int, ...]]:
    """New lists for every shuffleable species; only changed lists are returned."""

    out: dict[int, tuple[int, ...]] = {}
    for species_id in shuffleable_species():
        species = SPECIES_BY_ID[species_id]
        new = randomize_list(rng, species)
        if new != species.moves:
            out[species_id] = new
    return out


class ListPlan(NamedTuple):
    #: species id -> new 16-slot list (changed species only)
    lists: dict[int, tuple[int, ...]]

    @property
    def empty(self) -> bool:
        return not self.lists

    @property
    def species_table(self) -> dict[int, Species]:
        """The species view the enemy planner must use: vanilla, with the shuffled lists applied."""
        table = dict(SPECIES_BY_ID)
        for species_id, moves in self.lists.items():
            table[species_id] = table[species_id]._replace(moves=moves)
        return table


EMPTY_PLAN: Final = ListPlan({})


def build_list_plan(world: DigimonWorldWorld) -> ListPlan:
    """Resolve the option into concrete list rewrites (call from ``generate_early``)."""

    if not world.options.species_technique_lists:
        return EMPTY_PLAN
    return ListPlan(randomize_lists(world.random))


def describe_list(moves: tuple[int, ...]) -> str:
    return ", ".join(MOVE_NAMES[t] for t in moves if t != NO_MOVE)
