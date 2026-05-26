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
      via Mansion Key + Frig Key; Steak drops from the Overdell
      fridge on the vanilla path).
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
    * ``Tower`` — endgame; 50 PP from Mt. Infinity.
    * ``Factorial Town`` — Andromon/Giromon/MetalMamemon/Numemon. The
      only entry is Whamon's ferry from File City after Whamon Recruit.
    * ``Card Vending`` — synthetic region holding the 66 card-vending AP
      locations when :class:`worlds.digimon_world.options.CardLocations`
      is on. Two physical machines exist in DW1: one in Gear Savanna
      (free-on-region-access) and one in File City (Betamon + Patamon
      Recruit prereq). The synthetic region has both as parents so a
      card location is reachable as long as either machine is.
    * ``Leomon Ancestor Cave`` — sub-area off Drill Tunnel, gated by
      45 PP. Holds one chest.
    * ``Secret Beach Cave`` — Whamon-gated beach sub-area. Holds one
      chest.
    * ``Back Dimension`` — post-game-only area unlocked after defeating
      Machinedramon. Holds 7 chests, all flagged
      ``LocationProgressType.EXCLUDED`` so AP fill never sends
      progression there. See :data:`worlds.digimon_world.locations`
      and the ``dw1_back_dimension`` memory note for design rationale.

Edges are declared here without rules; access rules are attached in
:mod:`.rules`. ``Menu``, ``File City``, and ``Native Forest`` are
unconditional from the start.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from BaseClasses import Region

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


# Regions that can be locked behind a "<region> Region Access" AP item
# when :class:`worlds.digimon_world.options.RegionLocking` is on.
#
# Each name here MUST also appear in :data:`REGION_NAMES`. Order in this
# tuple defines a stable order for option valid_keys, item names, and
# generation tests; do NOT reorder casually.
#
# Excluded from this list (and why):
#   * ``Menu`` — synthetic AP origin.
#   * ``File City`` — always-reachable hub; locking would softlock.
#   * ``Greatlake`` — barely any content; per user feedback it's a
#     transit region, not worth a slot.
#   * ``Meramon Tunnel`` — sub-area of Drill Tunnel reached via the
#     boulder; the Drill Tunnel lock already gates this entire chain
#     and the Lava Cave Access boulder gate handles the inner step.
#   * ``Mt. Infinity``, ``Big Store``, ``Tower`` — hard-gated by the
#     prosperity threshold; adding a Region Access would just delay
#     endgame without changing sphere distribution.
#   * ``Grey Lord's Mansion`` — already gated by Mansion Key (AP item).
#   * ``Leomon Ancestor Cave`` — 1-chest sub-area, 45 PP gated.
#   * ``Secret Beach Cave`` — 1-chest sub-area, Whamon-gated.
#   * ``Back Dimension`` — post-game, all chests EXCLUDED + filler-only.
#   * ``Card Vending`` — synthetic; physical machines live in Gear
#     Savanna and File City.
LOCKABLE_REGIONS: Final[tuple[str, ...]] = (
    "Native Forest",
    "Tropical Jungle",
    "Overdell",
    "Ancient Dino Region",
    "Beetle Land",
    "Great Canyon",
    "Freezeland",
    "Drill Tunnel",
    "Mt. Panorama",
    "Gear Savanna",
    "Geko Swamp",
    "Misty Trees",
    "Toy Town",
    "Factorial Town",
)


def region_access_item_name(region: str) -> str:
    """Canonical AP-item name for ``region``'s region-locking gate.

    Centralized so :mod:`.items`, :mod:`.rules`, and the option set's
    ``valid_keys`` all agree on the spelling.
    """

    return f"{region} Region Access"


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
    # Locked sub-area inside Overdell — Mansion-Key gated
    "Grey Lord's Mansion",
    # Locked sub-area off Drill Tunnel — Leomon's Ancestor Cave entrance,
    # gated by 45 PP (matches the Leomonstone Pickup gate, since the
    # Stone Tablet sits inside the cave). Holds one chest.
    "Leomon Ancestor Cave",
    # Whamon-gated sub-area accessible from the Whamon-transport beach
    # cluster. Holds one chest.
    "Secret Beach Cave",
    # Post-game-only area unlocked after defeating Machinedramon. The
    # in-game entrance reuses one of {Ogre Fortress, Ice Sanctuary,
    # Grey Lord's Mansion} per save; for AP logic we abstract that
    # into a single region gated on the same Final-Battle threshold
    # plus reachability of any of those three. All 7 chests here are
    # flagged ``LocationProgressType.EXCLUDED`` because under the default
    # Machinedramon goal the player wins as soon as they beat
    # Machinedramon and has no incentive to return for post-game chests.
    "Back Dimension",
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
    ("Mt. Infinity", "Tower"),           # 50 PP
    # Left chain: Native Forest → Drill Tunnel → Meramon Tunnel → Mt. Panorama → ...
    ("Native Forest", "Drill Tunnel"),
    ("Drill Tunnel", "Meramon Tunnel"),  # Mode-gated (Lava Cave Access)
    ("Meramon Tunnel", "Mt. Panorama"),
    ("Mt. Panorama", "Gear Savanna"),
    ("Gear Savanna", "Geko Swamp"),
    ("Geko Swamp", "Misty Trees"),
    ("Misty Trees", "Toy Town"),
    # Drill Tunnel sub-area: Leomon Ancestor Cave (PP 45)
    ("Drill Tunnel", "Leomon Ancestor Cave"),
    # Secret Beach Cave has two parallel entrances:
    #   * File City → SBC via Whamon Recruit (Whamon the bank NPC ferries
    #     the player to his cave once he's joined).
    #   * Freezeland → SBC free — Whamon the wild NPC stands at the
    #     Freezeland beach and ferries the player to SBC regardless of
    #     recruit status (the recruit fight HAPPENS in SBC, so the
    #     transport must work pre-recruit).
    # AP region access treats parallel edges as OR; one path is enough.
    ("File City", "Secret Beach Cave"),    # Has(Whamon Recruit)
    ("Freezeland", "Secret Beach Cave"),   # free
    # Post-game Back Dimension entrance from File City
    ("File City", "Back Dimension"),       # 50 PP + reach (GLM | Freezeland | Great Canyon)
    # Right chain: Native Forest → Tropical Jungle / Greatlake → ...
    ("Native Forest", "Tropical Jungle"),  # Mode-gated (TJ Bridge)
    ("Tropical Jungle", "Overdell"),
    ("Overdell", "Grey Lord's Mansion"),  # Has(Mansion Key)
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

    # ====================================================================
    # Reverse edges — walking back through the geography
    # ====================================================================
    # In-game DW1 lets the player walk back through any region transition
    # they've already crossed. AP region traversal is one-way per edge,
    # so we declare the reverse explicitly. Most reverses are free; only
    # the boulder gate (Lava Cave Access) binds in both directions and
    # only the rod/flute requirement applies to Beetle Land both ways.
    # Bridge gates (TJ Bridge / GC Bridge) only apply on the forward
    # edge per user direction — Birdramon flight bypasses are intended
    # to provide alternative routes that don't require the bridge.
    ("Native Forest", "File City"),
    ("Mt. Infinity", "File City"),
    ("Big Store", "File City"),
    ("Factorial Town", "File City"),
    ("Tower", "Mt. Infinity"),
    # Left chain reverses
    ("Drill Tunnel", "Native Forest"),
    ("Meramon Tunnel", "Drill Tunnel"),     # Lava Cave Access (boulder)
    ("Mt. Panorama", "Meramon Tunnel"),     # Lava Cave Access (boulder)
    ("Gear Savanna", "Mt. Panorama"),
    ("Geko Swamp", "Gear Savanna"),
    ("Misty Trees", "Geko Swamp"),
    ("Toy Town", "Misty Trees"),
    # Sub-area reverses (free — once you can enter, you can leave)
    ("Leomon Ancestor Cave", "Drill Tunnel"),
    ("Secret Beach Cave", "File City"),
    ("Secret Beach Cave", "Freezeland"),    # free reverse (Whamon ferries back)
    ("Back Dimension", "File City"),
    # Right chain reverses
    ("Tropical Jungle", "Native Forest"),
    ("Overdell", "Tropical Jungle"),
    ("Grey Lord's Mansion", "Overdell"),  # free reverse (key already obtained to enter)
    ("Ancient Dino Region", "Tropical Jungle"),
    ("Greatlake", "Native Forest"),
    ("Beetle Land", "Greatlake"),           # rod | Blue Flute (same as forward)
    ("Great Canyon", "Greatlake"),
    ("Freezeland", "Great Canyon"),
    ("Misty Trees", "Freezeland"),
)


assert set(LOCKABLE_REGIONS).issubset(REGION_NAMES), (
    "LOCKABLE_REGIONS contains names that aren't real regions: "
    f"{set(LOCKABLE_REGIONS) - set(REGION_NAMES)}"
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
