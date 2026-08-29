"""Partner raising-parameter randomization for Digimon World 1.

``RAISE_DATA[66]`` (SLUS 0x801225BC, 28 bytes per species) holds the partner-side constants of
every species: meal hours, the energy meter, the toilet timer, the favourite food, the sleep
schedule, the home region, the training aptitude and the birth weight. The game reads the table
at use time (birth, digivolution, every wake-up), so a patched disc takes effect at once.

This option rewrites only the **mild, discoverable** fields of every Rookie+ partner species:

* ``favoriteFood`` -- the food that makes the partner happiest (any of the 33 food items);
* ``sleepCycle`` -- one of the six Rookie+ sleep schedules (never the baby rows, never past the
  eight-row schedule table);
* ``favoredRegion`` -- the home biome that trades a little happiness and tiredness per hour on
  its screens (the nine region ids the ``.MAP`` files use);
* ``trainingType`` -- which stats train 10 % better / worse (0..3; the -20 % "joke" value the
  three failure species carry is never dealt);
* ``defaultWeight`` -- the birth / digivolution weight, inside the level's vanilla band.

The care economy (energy, meals, toilet) is left alone: it feeds care mistakes, and through them
digivolution and lifetime. Source of the field semantics: ``work/dw1_re/decomp/raise_bgm/NOTES.md``
(dw_decomp + Ghidra exports of the ASM-only partner functions, 2026-08-29).
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.enemy_records import RAISE_DATA
from .drops import ITEM_NAMES
from .evolutions import LEVEL_CHAMPION, LEVEL_ROOKIE, LEVEL_ULTIMATE, PARTNER_SPECIES_IDS, SPECIES_LEVEL, SPECIES_NAME

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


#: ITEM_PARA ids the game treats as food (``partnerHandleFoodFeed``); every vanilla favourite is one.
FOOD_IDS: Final = tuple(range(38, 71))
#: ``favoredRegion`` ids as the ``.MAP`` liked / disliked lists use them.
REGION_NAMES: Final = {
    0: "Drill Tunnel / Ancient Dino Region",
    1: "Freezeland",
    2: "Ice Sanctuary",
    3: "Factorial Town",
    4: "Tropical Jungle / Great Canyon / Geko Swamp",
    5: "Mt. Panorama / Gear Savanna",
    6: "Overdell / Grey Lord's Mansion",
    7: "Beetle Land",
    8: "Native Forest / File City",
}
#: ``trainingType`` -> which stats train at 110 % (the complementary pair trains at 90 %).
TRAINING_TYPES: Final = {0: "even", 1: "Offense / Speed", 2: "MP / Brains", 3: "HP / Defense"}
#: Rookie+ rows of the sleep-schedule table (rows 6 / 7 are the Fresh / In-Training rows).
SLEEP_SCHEDULES: Final = {0: "16:00-01:00", 1: "19:00-04:00", 2: "22:00-07:00", 3: "02:00-11:00", 4: "07:00-16:00",
                          5: "10:00-19:00"}
WEIGHT_BANDS: Final = {LEVEL_ROOKIE: (10, 20), LEVEL_CHAMPION: (10, 40), LEVEL_ULTIMATE: (5, 50)}


class RaiseRow(NamedTuple):
    """The five contiguous bytes at ``RAISE_DATA_PATCH_SPAN``."""

    favorite_food: int
    sleep_cycle: int
    favored_region: int
    training_type: int
    default_weight: int


VANILLA_RAISE: Final[dict[int, RaiseRow]] = {
    species: RaiseRow(*row[14:19]) for species, row in enumerate(RAISE_DATA)
}


def raisable_species() -> list[int]:
    """Rookie+ partner species (the babies keep their fixed schedules and no favourite)."""

    return [species for species in PARTNER_SPECIES_IDS
            if species in VANILLA_RAISE and SPECIES_LEVEL[species] >= LEVEL_ROOKIE]


def randomize_raising(rng: Random) -> dict[int, RaiseRow]:
    """New rows for every Rookie+ partner species; only changed rows are returned."""

    out: dict[int, RaiseRow] = {}
    for species in raisable_species():
        row = RaiseRow(
            favorite_food=rng.choice(FOOD_IDS),
            sleep_cycle=rng.randrange(len(SLEEP_SCHEDULES)),
            favored_region=rng.randrange(len(REGION_NAMES)),
            training_type=rng.randrange(len(TRAINING_TYPES)),
            default_weight=rng.randint(*WEIGHT_BANDS[SPECIES_LEVEL[species]]),
        )
        if row != VANILLA_RAISE[species]:
            out[species] = row
    return out


class RaisePlan(NamedTuple):
    #: species -> new row (changed species only)
    overrides: dict[int, RaiseRow]

    @property
    def empty(self) -> bool:
        return not self.overrides


EMPTY_PLAN: Final = RaisePlan({})


def build_raise_plan(world: DigimonWorldWorld) -> RaisePlan:
    """Resolve the option into concrete row rewrites (call from ``generate_early``)."""

    if not world.options.partner_raising:
        return EMPTY_PLAN
    return RaisePlan(randomize_raising(world.random))


def describe_row(row: RaiseRow) -> str:
    return (f"likes {ITEM_NAMES.get(row.favorite_food, row.favorite_food)}, home {REGION_NAMES[row.favored_region]}, "
            f"trains {TRAINING_TYPES[row.training_type]}, sleeps {SLEEP_SCHEDULES.get(row.sleep_cycle, '?')}, "
            f"weight {row.default_weight}")


def species_name(species: int) -> str:
    return SPECIES_NAME[species]
