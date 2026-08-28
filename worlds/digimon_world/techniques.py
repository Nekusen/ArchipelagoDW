"""Technique data (``MOVE_DATA``) and element-affinity randomization for Digimon World 1.

Both are static SLUS tables, so a seed's changes are plain data writes (no code hooks):

* ``MOVE_DATA`` holds one 16-byte record per technique -- power, MP cost, accuracy, status
  effect and its chance are the fields a seed may rewrite. The table is **global**: the
  partner, every wild Digimon and every boss read the same record for a technique, so
  randomizing it reshapes the whole game's combat rather than one side of it.
* The 7 x 7 element affinity matrix (``MAIN_D_80125F70``) weights a technique's element
  against the target species' first specialty. The battle engine consults it for the enemy
  AI's technique choice and for which techniques the partner can learn from a fight.

The algorithm is a clean-room reimplementation of meekrhino's standalone randomizer
(``handler.py:randomizeTechData`` and ``_randomizeTypeEffectiveness``) with the same
knobs: a *mode* (shuffle vanilla values among the partner-learnable techniques, or
generate new values for every technique) and one toggle per field.

Species technique *lists* (``DIGIMON_DATA.moves[16]``) are not touched here: a Digimon can
only ever use the 16 techniques of its list, and which of them a wild Digimon carries is the
job of :mod:`.enemies`. When ``enemy_stats`` scales enemies by technique power it reads the
powers this module ships (:attr:`TechniquePlan.powers`), so the two compose.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.enemy_records import ELEMENT_MATRIX, MOVES

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


MOVE_COUNT: Final = 122
#: Ids 0..120 are the named techniques the standalone randomizer rewrites (``techDataBlockCount``);
#: id 121 is a nameless internal record and stays vanilla.
RANDOMIZED_MOVE_COUNT: Final = 121
#: Ids below this are the techniques the partner can learn (mastery bitmap, ``technique_rewards``);
#: 58..112 are enemy-only finishers and 113..120 the bubble attacks. Shuffles stay inside this pool.
PARTNER_MOVE_COUNT: Final = 58

DATA_VANILLA: Final = 0
DATA_SHUFFLE: Final = 1
DATA_RANDOM: Final = 2

STATUS_NONE: Final = 0
STATUS_NAMES: Final = ("none", "poison", "confusion", "stun", "flat")
STATUS_EFFECT_IDS: Final = (1, 2, 3, 4)

POWER_CAP: Final = 999
MP_COST_BYTE_CAP: Final = 255
MP_COST_MULTIPLIER: Final = 3        # the game charges mpCost * 3
STATUS_CHANCE_MAX: Final = 70

ELEMENT_DIM: Final = 7
ELEMENT_NAMES: Final = ("Fire", "Battle", "Air", "Nature", "Ice", "Mech", "Filth")
ELEMENT_VALUES: Final = (2, 5, 10, 15, 20)


class TechValues(NamedTuple):
    """The randomizable fields of one ``Move`` record."""

    power: int
    mp_cost: int          # stored byte (x3 in game)
    accuracy: int
    status: int
    status_chance: int


VANILLA_VALUES: Final[dict[int, TechValues]] = {
    row[0]: TechValues(power=row[2], mp_cost=row[3], accuracy=row[6], status=row[5], status_chance=row[7])
    for row in MOVES
}
MOVE_NAMES: Final[dict[int, str]] = {row[0]: row[1] for row in MOVES}


def is_learnable(tech_id: int) -> bool:
    return tech_id < PARTNER_MOVE_COUNT


class TechniquePlan(NamedTuple):
    """Everything the patcher and the spoiler need; built once in ``generate_early``."""

    #: technique id -> new field values (only techniques whose values changed)
    moves: dict[int, TechValues]
    #: the new 7 x 7 matrix, or ``None`` when it stays vanilla
    matrix: tuple[tuple[int, ...], ...] | None

    @property
    def empty(self) -> bool:
        return not self.moves and self.matrix is None

    @property
    def powers(self) -> dict[int, int]:
        """``technique id -> damage base`` as this seed ships it (vanilla where unchanged)."""
        powers = {tech_id: values.power for tech_id, values in VANILLA_VALUES.items()}
        powers.update({tech_id: values.power for tech_id, values in self.moves.items()})
        return powers


EMPTY_PLAN: Final = TechniquePlan({}, None)


def _swap(values: dict[int, TechValues], a: int, b: int, field: str) -> None:
    mine, theirs = values[a], values[b]
    values[a] = mine._replace(**{field: getattr(theirs, field)})
    values[b] = theirs._replace(**{field: getattr(mine, field)})


def _shuffle(rng: Random, values: dict[int, TechValues], *, power: bool, mp_cost: bool, accuracy: bool,
             effect: bool, effect_chance: bool) -> None:
    """Swap each learnable technique's values with a random learnable technique's (self-swaps
    included), then re-roll status effects. Mutates ``values`` in place."""

    learnable = [tech_id for tech_id in sorted(values) if is_learnable(tech_id)]
    damaging = [tech_id for tech_id in learnable if VANILLA_VALUES[tech_id].power > 0]
    for tech_id in learnable:
        if power and values[tech_id].power > 0:
            _swap(values, tech_id, rng.choice(damaging), "power")
        if mp_cost:
            _swap(values, tech_id, rng.choice(learnable), "mp_cost")
        if accuracy:
            _swap(values, tech_id, rng.choice(learnable), "accuracy")
        if effect:
            # about half of the damaging techniques get a status; self-targeting buffs never do
            if values[tech_id].power > 0 and rng.random() < 0.5:
                values[tech_id] = values[tech_id]._replace(status=rng.choice(STATUS_EFFECT_IDS))
            else:
                values[tech_id] = values[tech_id]._replace(status=STATUS_NONE, status_chance=0)
        if effect_chance:
            chance = 0 if values[tech_id].status == STATUS_NONE else rng.randint(1, STATUS_CHANCE_MAX)
            values[tech_id] = values[tech_id]._replace(status_chance=chance)


def _random_accuracy(rng: Random) -> int:
    roll = rng.randint(0, 99)
    if roll < 10:
        return rng.randint(33, 60)
    if roll < 50:
        return rng.randint(50, 80)
    if roll < 90:
        return rng.randint(75, 100)
    return 100


def _randomize(rng: Random, values: dict[int, TechValues], *, power: bool, mp_cost: bool, accuracy: bool) -> None:
    """Generate new values for every technique (enemy-only ones included): power 70..130 % of
    the current value (cap 999), MP cost 10..140 % of the power, accuracy in tiers."""

    for tech_id in sorted(values):
        current = values[tech_id]
        if power:
            current = current._replace(power=min(current.power * rng.randint(70, 130) // 100, POWER_CAP))
        if mp_cost and current.power != 0:
            factor = rng.randint(10, 140)
            mp_cost_byte = min(factor * current.power // (100 * MP_COST_MULTIPLIER), MP_COST_BYTE_CAP)
            current = current._replace(mp_cost=mp_cost_byte)
        if accuracy:
            current = current._replace(accuracy=_random_accuracy(rng))
        values[tech_id] = current


def randomize_technique_data(
    rng: Random, mode: int, *, power: bool, mp_cost: bool, accuracy: bool, effect: bool, effect_chance: bool,
) -> dict[int, TechValues]:
    """The standalone's ``randomizeTechData``: ``shuffle`` swaps vanilla values among the
    partner-learnable techniques; ``random`` does that and then generates new power / MP cost /
    accuracy for all 121 techniques. Returns only the techniques whose values changed."""

    if mode == DATA_VANILLA:
        return {}
    values = {tech_id: VANILLA_VALUES[tech_id] for tech_id in range(RANDOMIZED_MOVE_COUNT)}
    _shuffle(rng, values, power=power, mp_cost=mp_cost, accuracy=accuracy, effect=effect,
             effect_chance=effect_chance)
    if mode == DATA_RANDOM:
        _randomize(rng, values, power=power, mp_cost=mp_cost, accuracy=accuracy)
    return {tech_id: v for tech_id, v in values.items() if v != VANILLA_VALUES[tech_id]}


def randomize_element_matrix(rng: Random) -> tuple[tuple[int, ...], ...]:
    """Every cell of the affinity matrix becomes one of the five vanilla values."""

    return tuple(tuple(rng.choice(ELEMENT_VALUES) for _ in range(ELEMENT_DIM)) for _ in range(ELEMENT_DIM))


def build_technique_plan(world: DigimonWorldWorld) -> TechniquePlan:
    """Resolve the technique options into concrete table rewrites (call from ``generate_early``)."""

    options = world.options
    moves = randomize_technique_data(
        world.random, int(options.technique_data.value),
        power=bool(options.technique_power.value),
        mp_cost=bool(options.technique_mp_cost.value),
        accuracy=bool(options.technique_accuracy.value),
        effect=bool(options.technique_effect.value),
        effect_chance=bool(options.technique_effect_chance.value),
    )
    matrix = randomize_element_matrix(world.random) if options.type_effectiveness else None
    if matrix is not None and matrix == tuple(tuple(row) for row in ELEMENT_MATRIX):
        matrix = None
    return TechniquePlan(moves, matrix)


def describe_values(values: TechValues) -> str:
    """One-line human summary for the spoiler log."""

    text = f"power {values.power}, MP {values.mp_cost * MP_COST_MULTIPLIER}, accuracy {values.accuracy}"
    if values.status != STATUS_NONE:
        text += f", {STATUS_NAMES[values.status]} {values.status_chance}%"
    return text
