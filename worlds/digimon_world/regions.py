"""Region graph for the Digimon World 1 APWorld (Phase 2: full map).

The graph is **mostly flat** — File City is the hub, every outer area is
a direct entrance off it. That works because DW1 is fundamentally a hub
game: you always return to the city. Inter-area sequencing is encoded
via *access rules* on the entrances rather than a deep region tree.

Where the in-game map *forces* a sequencing — e.g. you must go through
the Meramon Tunnel to reach the area beyond, or you only reach Sand Bay
after Whamon swallows you — those are explicit Entrance children
(``Beetle Land`` is a child of ``Greatlake`` because you reach it via
the Whamon-mediated swim, etc.). The cluster of Phase-2 access rules
lives in :mod:`.rules`.

Region inventory (matches the assignments in :mod:`.locations`):

* ``Menu`` — AP origin.
* ``File City`` — hub. Agumon recruit, Start Game, prosperity gifts,
  general chests.
* ``Native Forest`` — Phase 1 Rookie cluster (Betamon, Gabumon,
  Elecmon, Patamon, Biyomon, Sukamon, Palmon, Vegiemon).
* ``Tropical Jungle`` — Coelamon, Centarumon, Bakemon, Kunemon, Piximon.
* ``Greatlake`` — fishing-rod gated. Seadramon, Whamon, Numemon,
  Shellmon, Ogremon. Source for the Whamon-swallow access route to
  ``Beetle Land`` and ``Sand Bay``.
* ``Meramon Tunnel`` — Meramon recruit; gateway to many "post-Meramon"
  areas via the access-rule cluster in :mod:`.rules`.
* ``Mt. Panorama`` — Greymon, Tyrannomon, Unimon, Mamemon, Leomon.
* ``Misty Trees`` — Cherrymon route to Monzaemon and Kokatorimon.
* ``Beetle Land`` — Kabuterimon, Kuwagamon (post-Seadramon).
* ``Drill Tunnel`` — Drimogemon recruit.
* ``Sand Bay`` — Penguinmon (post-Whamon).
* ``Factorial Town`` — Andromon, Giromon, MetalMamemon (post-Whamon
  chain).
* ``Toy Town`` — Nanimon (multi-area gate).
* ``Freezeland`` — Frigimon, Mojyamon, Garurumon, Angemon.
* ``Great Canyon`` — Birdramon, Monochromon.
* ``Mt. Infinity`` — late-game cluster: Vademon, SkullGreymon, Devimon,
  Airdramon, Etemon, Megadramon. Also feeds the Tower.
* ``Big Store`` — Ninjamon shop (50 PP gate).
* ``Tower`` — endgame; MetalGreymon, Digitamamon, Final Battle event.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from BaseClasses import Region

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


REGION_NAMES: Final[tuple[str, ...]] = (
    "Menu",
    "File City",
    "Native Forest",
    "Tropical Jungle",
    "Greatlake",
    "Meramon Tunnel",
    "Mt. Panorama",
    "Misty Trees",
    "Beetle Land",
    "Drill Tunnel",
    "Sand Bay",
    "Factorial Town",
    "Toy Town",
    "Freezeland",
    "Great Canyon",
    "Mt. Infinity",
    "Big Store",
    "Tower",
    "Overdell",
)


# Edges. Rules are attached in :mod:`.rules`; here we just declare
# adjacency. ``Menu`` and ``File City`` are unconditional. Everything
# else gets a rule attached after creation.

_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("Menu", "File City"),
    # File City connects directly to the immediately-explorable cluster.
    ("File City", "Native Forest"),
    ("File City", "Tropical Jungle"),
    ("File City", "Greatlake"),
    ("File City", "Meramon Tunnel"),
    # Post-Meramon cluster (rule = HasMeramonAccess).
    ("File City", "Mt. Panorama"),
    ("File City", "Misty Trees"),
    ("File City", "Factorial Town"),
    ("File City", "Drill Tunnel"),
    # Post-Seadramon (Whamon swallow / fishing-rod chain).
    ("Greatlake", "Beetle Land"),
    ("Greatlake", "Sand Bay"),
    # Misty Trees → Cherrymon → Toy Town / Freezeland.
    ("Misty Trees", "Toy Town"),
    ("Misty Trees", "Freezeland"),
    # Yuramon Quest / Shellmon → Great Canyon (alt path to Freezeland too).
    ("Greatlake", "Great Canyon"),
    ("Great Canyon", "Freezeland"),
    # Late-game: Mt. Infinity behind 45 PP + recruits; Big Store behind 50 PP.
    ("File City", "Mt. Infinity"),
    ("File City", "Big Store"),
    # Tower is endgame; gated on the 50-PP cluster + Mt. Infinity progress.
    ("Mt. Infinity", "Tower"),
    # Overdell Cemetery & Grey Lord's Mansion (SkullGreymon area).
    ("File City", "Overdell"),
)


def create_and_connect_regions(world: DigimonWorldWorld) -> None:
    create_all_regions(world)
    connect_regions(world)


def create_all_regions(world: DigimonWorldWorld) -> None:
    multiworld, player = world.multiworld, world.player
    multiworld.regions += [Region(name, player, multiworld) for name in REGION_NAMES]


def connect_regions(world: DigimonWorldWorld) -> None:
    for source, target in _EDGES:
        world.get_region(source).connect(
            world.get_region(target), f"{source} to {target}",
        )
