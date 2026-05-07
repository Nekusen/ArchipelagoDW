"""Region graph for the Digimon World 1 APWorld (Phase 6).

The graph reflects the **actual in-game geography** with two halves
that meet at Misty Trees but cannot cross through Misty Trees in AP
logic — flying via Birdramon is the only way to switch sides.

Region inventory (22 regions):

* ``Menu`` — AP origin.
* ``File City`` — hub. Greymon, Airdramon. Birdra Transport opens here
  after Birdramon Recruit.
* ``Native Forest`` — entry to both halves; sub-points include Coela
  Point (Coelamon), Dragon Eye Lake (Seadramon), Digimon Bridge
  (Ninjamon at night), Tree House (Etemon).
* **Right side (Tropical Jungle chain)**:

    * ``Tropical Jungle`` — gated by the TJ-bridge mode option.
    * ``Overdell`` — Bakemon, plus Grey Lord's Mansion (SkullGreymon
      via Mansion Key + Frig Key + Steak from Freezeland).
    * ``Ancient Dino Region`` — Tyrannomon.
    * ``Greatlake`` (= Dragon Eye Lake cluster) — fishing region.
    * ``Beetle Land`` — only via Blue Flute / rod path or
      Birdramon Flight.
    * ``Great Canyon`` — gated by the GC-bridge mode option.
    * ``Freezeland`` — recruits cluster, chains into Misty Trees.

* **Left side (Drill Tunnel chain)**:

    * ``Drill Tunnel`` — Drimogemon.
    * ``Meramon Tunnel`` — Meramon; gated by Lava Cave Access mode.
    * ``Mt. Panorama`` — Unimon, Mamemon, Vademon.
    * ``Gear Savanna`` — Patamon, Biyomon, Elecmon, Sukamon, Leomon.
    * ``Geko Swamp`` — junction approach for Misty Trees.

* **Junction & terminals**:

    * ``Misty Trees`` — Gabumon, Kokatorimon. Reachable via Freezeland
      (right), Geko Swamp (left), or Birdramon Flight: Misty Trees.
    * ``Toy Town`` — Monzaemon, Nanimon. From Misty Trees.
    * ``Mt. Infinity`` — Devimon, Megadramon, MetalGreymon. 50-PP gate
      from File City.
    * ``Big Store`` — late-game shop. 50-PP gate.
    * ``Tower`` — endgame; AS Decoder + 50 PP from Mt. Infinity.
    * ``Factorial Town`` — Andromon/Giromon/MetalMamemon/Numemon. The
      only entry is Whamon's ferry from File City after Whamon Recruit.
    * ``Card Vending`` — synthetic region holding the 66 card-vending AP
      locations when :class:`worlds.digimon_world.options.CardLocations`
      is on. Two physical machines exist in DW1: one in Gear Savanna
      (free-on-region-access) and one in File City (Betamon + Patamon
      Recruit prereq). The synthetic region has both as parents so a
      card location is reachable as long as either machine is.

Edges are declared here without rules; access rules are attached in
:mod:`.rules`. ``Menu``, ``File City``, and ``Native Forest`` are
unconditional from the start.
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
    # Right side
    "Tropical Jungle",
    "Overdell",
    "Ancient Dino Region",
    "Greatlake",
    "Beetle Land",
    "Great Canyon",
    "Freezeland",
    # Left side
    "Drill Tunnel",
    "Meramon Tunnel",
    "Mt. Panorama",
    "Gear Savanna",
    "Geko Swamp",
    # Junction & terminals
    "Misty Trees",
    "Toy Town",
    "Mt. Infinity",
    "Big Store",
    "Tower",
    "Factorial Town",
    # Synthetic — populated only when CardLocations is on
    "Card Vending",
)


# Edges. Rules are attached in :mod:`.rules`; here we just declare
# adjacency. Multiple edges into the same target are interpreted as OR
# by AP region access (any reachable parent grants access).

_EDGES: Final[tuple[tuple[str, str], ...]] = (
    ("Menu", "File City"),
    # File City direct entries
    ("File City", "Native Forest"),
    ("File City", "Mt. Infinity"),       # 50 PP
    ("File City", "Big Store"),          # 50 PP
    ("File City", "Factorial Town"),     # Whamon Recruit
    # Birdramon flights — alternative entry from File City
    ("File City", "Misty Trees"),        # Has(BR Recruit) & Has(Flight: Misty Trees)
    ("File City", "Gear Savanna"),       # Has(BR Recruit) & Has(Flight: Gear Savanna)
    ("File City", "Ancient Dino Region"),  # Has(BR Recruit) & Has(Flight: Ancient Dino)
    ("File City", "Freezeland"),         # Has(BR Recruit) & Has(Flight: Freezeland)
    ("File City", "Beetle Land"),        # Has(BR Recruit) & Has(Flight: Beetle Land)
    # Mt. Infinity terminal
    ("Mt. Infinity", "Tower"),           # AS Decoder + 50 PP
    # Left chain: Native Forest → Drill Tunnel → Meramon Tunnel → Mt. Panorama → ...
    ("Native Forest", "Drill Tunnel"),
    ("Drill Tunnel", "Meramon Tunnel"),  # Mode-gated (Lava Cave Access)
    ("Meramon Tunnel", "Mt. Panorama"),
    ("Mt. Panorama", "Gear Savanna"),
    ("Gear Savanna", "Geko Swamp"),
    ("Geko Swamp", "Misty Trees"),
    ("Misty Trees", "Toy Town"),
    # Right chain: Native Forest → Tropical Jungle / Greatlake → ...
    ("Native Forest", "Tropical Jungle"),  # Mode-gated (TJ Bridge)
    ("Tropical Jungle", "Overdell"),
    ("Tropical Jungle", "Ancient Dino Region"),
    ("Native Forest", "Greatlake"),
    ("Greatlake", "Beetle Land"),        # Has(rod) | Has(Blue Flute)
    ("Greatlake", "Great Canyon"),       # Mode-gated (GC Bridge)
    ("Great Canyon", "Freezeland"),
    ("Freezeland", "Misty Trees"),
    # Card vending — multi-parent. Either machine reaches the synthetic
    # region. Rules attached in :mod:`.rules`.
    ("Gear Savanna", "Card Vending"),    # free; Gear Savanna access alone
    ("File City",    "Card Vending"),    # Has(Betamon Recruit) & Has(Patamon Recruit)
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
