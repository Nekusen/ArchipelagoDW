"""Access rules for the Digimon World 1 APWorld (Phase 6).

Rule layout
===========

* **Entrance rules** are attached per-edge in :func:`_set_entrance_rules`.
  Most edges are mode-independent; three are mode-gated by the
  :class:`worlds.digimon_world.options.BridgeUnlock`,
  :class:`worlds.digimon_world.options.GreatCanyonUnlock`, and
  :class:`worlds.digimon_world.options.LavaCaveAccess` options.
* **Per-recruit rules** are attached in :func:`_set_recruit_rules`.
  Base rule = ``Has(Prosperity Point, count=ceil(pp/2))`` from
  :data:`RECRUIT_PP_REQUIREMENTS`. Five recruits have extra rules
  layered on top (Seadramon, Vegimon, SkullGreymon, Monzaemon, Leomon).
* **No per-chest rules.** Per the Phase 6 user direction, chests are
  treated as always available — the in-game region the chest lives in
  may not actually be reachable yet, but AP fill ignores that for now.
* **Final Battle** rule: AS Decoder + 50 PP (matches the Tower
  entrance rule; redundant but keeps the goal explicit).

PP scaling
==========

Each shipped ``Prosperity Point`` AP item delivers
:data:`worlds.digimon_world.items.PROSPERITY_PER_ITEM` (= 2) PP.
``items_needed = ceil(pp_needed / PROSPERITY_PER_ITEM)``. We round up
per the user's spec — a 15-PP gate becomes a 16-PP / 8-item gate.
"""

from __future__ import annotations

from math import ceil
from typing import TYPE_CHECKING

from rule_builder.rules import CanReachRegion, Has

from .items import PROSPERITY_PER_ITEM
from .locations import RECRUIT_PP_REQUIREMENTS

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


PROSPERITY_ITEM_NAME = "Prosperity Point"

# BridgeUnlock / GreatCanyonUnlock option values (kept here as named
# constants for readability when reading entrance rules).
_OPT_ALWAYS_OPEN = 0
_OPT_VANILLA = 1
_OPT_SHUFFLED = 2

# LavaCaveAccess values (no always_open mode).
_LCA_VANILLA = 0
_LCA_SHUFFLED = 1


def _items_needed(pp_needed: int) -> int:
    """Translate an in-game PP threshold to the AP-item count."""

    return ceil(pp_needed / PROSPERITY_PER_ITEM)


def _pp(pp_needed: int) -> Has:
    """Convenience: PP-threshold rule."""

    return Has(PROSPERITY_ITEM_NAME, count=_items_needed(pp_needed))


def _set_entrance_rule(world: DigimonWorldWorld, source: str, target: str, rule) -> None:
    """Attach an access rule to the entrance ``source → target``."""

    entrance = world.multiworld.get_entrance(f"{source} to {target}", world.player)
    world.set_rule(entrance, rule)


def set_all_rules(world: DigimonWorldWorld) -> None:
    _set_entrance_rules(world)
    _set_recruit_rules(world)
    _set_completion_condition(world)


# ---------------------------------------------------------------------------
# Entrance rules
# ---------------------------------------------------------------------------

def _set_entrance_rules(world: DigimonWorldWorld) -> None:
    """Attach per-edge access rules.

    Edges declared in :mod:`.regions` get their rules here. Edges
    without an entry below are unconditional (free).
    """

    options = world.options
    bridge_mode = int(options.bridge_unlock.value)              # 0/1/2
    canyon_mode = int(options.great_canyon_unlock.value)        # 0/1/2
    lava_mode = int(options.lava_cave_access.value)             # 0/1

    # ------- File City direct entries -------
    _set_entrance_rule(world, "File City", "Mt. Infinity", _pp(50))
    _set_entrance_rule(world, "File City", "Big Store", _pp(50))
    _set_entrance_rule(world, "File City", "Factorial Town", Has("Whamon Recruit"))

    # Birdramon flights — alt entry from File City. Each requires
    # Birdramon Recruit (the menu only opens once Birdramon is in city)
    # AND the corresponding Birdramon Flight item.
    flight_targets = (
        ("Misty Trees",          "Birdramon Flight: Misty Trees"),
        ("Gear Savanna",         "Birdramon Flight: Gear Savanna"),
        ("Ancient Dino Region",  "Birdramon Flight: Ancient Dino Region"),
        ("Freezeland",           "Birdramon Flight: Freezeland"),
        ("Beetle Land",          "Birdramon Flight: Beetle Land"),
    )
    for region, flight_item in flight_targets:
        _set_entrance_rule(
            world, "File City", region,
            Has("Birdramon Recruit") & Has(flight_item),
        )

    # ------- Mt. Infinity → Tower (endgame) -------
    _set_entrance_rule(
        world, "Mt. Infinity", "Tower",
        Has("AS Decoder") & _pp(50),
    )

    # ------- Left chain -------
    # Native Forest → Drill Tunnel: free (no rule)
    # Drill Tunnel → Meramon Tunnel: mode-gated
    if lava_mode == _LCA_SHUFFLED:
        _set_entrance_rule(
            world, "Drill Tunnel", "Meramon Tunnel",
            Has("Lava Cave Access"),
        )
    # vanilla mode: free (Champion partner is player problem; no AP rule)
    # Meramon Tunnel → Mt. Panorama: free
    # Mt. Panorama → Gear Savanna: free
    # Gear Savanna → Geko Swamp: free
    # Geko Swamp → Misty Trees: free
    # Misty Trees → Toy Town: free

    # ------- Right chain -------
    # Native Forest → Tropical Jungle: mode-gated
    if bridge_mode == _OPT_SHUFFLED:
        _set_entrance_rule(
            world, "Native Forest", "Tropical Jungle",
            Has("Tropical Jungle Bridge"),
        )
    # vanilla / always_open: free (Coelamon escort or pre-fixed bridge)

    # Tropical Jungle → Overdell: free
    # Tropical Jungle → Ancient Dino Region: free
    # Native Forest → Greatlake: free

    # Greatlake → Beetle Land: rod path or AP-delivered Blue Flute
    _set_entrance_rule(
        world, "Greatlake", "Beetle Land",
        Has("Old Fishrod") | Has("Amazing rod") | Has("Blue Flute"),
    )

    # Greatlake → Great Canyon: mode-gated
    if canyon_mode == _OPT_SHUFFLED:
        _set_entrance_rule(
            world, "Greatlake", "Great Canyon",
            Has("Great Canyon Bridge"),
        )
    elif canyon_mode == _OPT_VANILLA:
        _set_entrance_rule(world, "Greatlake", "Great Canyon", _pp(6))
    # always_open: free

    # Great Canyon → Freezeland: free
    # Freezeland → Misty Trees: free

    # ------- Card vending (opt-in CardLocations) -------
    # Two physical machines:
    #   * Gear Savanna machine — reachable when Gear Savanna is reachable.
    #     No extra rule on this entrance.
    #   * File City machine — only opens after both Betamon and Patamon
    #     are in city. Player gets each Digimon "in city" by receiving
    #     the corresponding ``<Name> Recruit`` AP item, so the rule is
    #     ``Has(Betamon Recruit) & Has(Patamon Recruit)``.
    # Either parent satisfies access (AP region access is OR over edges).
    # The "Card Vending" region exists unconditionally; rules and
    # locations only matter when the option is on.
    _set_entrance_rule(
        world, "File City", "Card Vending",
        Has("Betamon Recruit") & Has("Patamon Recruit"),
    )
    # Gear Savanna → Card Vending: free (no rule)


# ---------------------------------------------------------------------------
# Recruit rules
# ---------------------------------------------------------------------------

# Recruits with an extra gate beyond the base PP rule. Each entry's
# value is a callable ``(world) -> Rule`` that returns the *additional*
# rule to AND with the base PP rule. We use a callable so we can build
# ``CanReachRegion(...)`` rules that resolve at rule-attach time.

def _seadramon_extra(_world: DigimonWorldWorld):
    return Has("Old Fishrod") | Has("Amazing rod")


def _vegimon_extra(_world: DigimonWorldWorld):
    return Has("Rain Plant")


def _skullgreymon_extra(_world: DigimonWorldWorld):
    # Mansion Key (mansion access) + Frig Key (refrigerator) + reach
    # Freezeland (where the refrigerator lives). All three are AP-
    # tracked progression items / regions.
    return Has("Mansion Key") & Has("Frig Key") & CanReachRegion("Freezeland")


def _monzaemon_extra(_world: DigimonWorldWorld):
    return Has("Gear")


def _leomon_extra(_world: DigimonWorldWorld):
    # Force the Stone-Tablet path: even if the player took the
    # Birdramon Flight: Gear Savanna shortcut, they need to traverse
    # Drill Tunnel + Meramon Tunnel to reach Ancestor's Cave for the
    # Stone Tablet. Modeling reach(Meramon Tunnel) covers that whole
    # left-chain prerequisite.
    return CanReachRegion("Meramon Tunnel")


# Ogremon's 4-battle chain spans 3 regions: Great Canyon (Battle 1),
# Great Canyon / Ogre Fortress sub-area (Battle 2), Freezeland /
# Whamon's Secret Beach Cave (Battle 3), Drill Tunnel (Battle 4 —
# final, joins). Drill Tunnel is always reachable; Great Canyon is
# Ogremon's home region (already implicit via region access). The
# explicit gate we need is **Freezeland** for Battle 3.
def _ogremon_extra(_world: DigimonWorldWorld):
    return CanReachRegion("Freezeland")


# Whamon's recruit chain requires Ogremon defeated at Ogre Fortress
# (Battle 2 — Great Canyon sub-area), then traveling to his cave from
# Freezeland (Battle 3). Reaching Freezeland via the right chain
# already requires Great Canyon, but the **Birdramon Flight:
# Freezeland** bypass would skip Great Canyon, leaving Battles 1+2
# unreachable. Force Great Canyon explicitly.
def _whamon_extra(_world: DigimonWorldWorld):
    return CanReachRegion("Great Canyon")


# Shellmon's recruit chain: defeat Ogremon at Ogre Fortress (Battle 2,
# Great Canyon sub-area), then go to Freezeland SW to find Shellmon
# and talk. Shellmon's home region is Great Canyon (the cry-for-help
# triggers there), but the actual recruit happens in Freezeland.
def _shellmon_extra(_world: DigimonWorldWorld):
    return CanReachRegion("Freezeland")


_RECRUIT_EXTRA_RULES = {
    "Seadramon":    _seadramon_extra,
    "Vegiemon":     _vegimon_extra,  # in-repo spelling
    "SkullGreymon": _skullgreymon_extra,
    "Monzaemon":    _monzaemon_extra,
    "Leomon":       _leomon_extra,
    # Ogremon-chain region requirements
    "Ogremon":      _ogremon_extra,
    "Whamon":       _whamon_extra,
    "Shellmon":     _shellmon_extra,
}


def _set_recruit_rules(world: DigimonWorldWorld) -> None:
    """Attach the per-recruit rule to each recruit AP location.

    Base rule: ``Has(Prosperity Point, count=ceil(pp/2))``. Five
    recruits have an extra rule ANDed in (see ``_RECRUIT_EXTRA_RULES``).
    Recruits at 0 PP with no extra rule are skipped (= no rule = always
    reachable within their region).
    """

    for recruit_name, pp in RECRUIT_PP_REQUIREMENTS.items():
        extra_factory = _RECRUIT_EXTRA_RULES.get(recruit_name)
        if pp <= 0 and extra_factory is None:
            continue
        location = world.get_location(recruit_name)
        rule = _pp(pp) if pp > 0 else None
        if extra_factory is not None:
            extra = extra_factory(world)
            rule = extra if rule is None else rule & extra
        world.set_rule(location, rule)


# ---------------------------------------------------------------------------
# Completion condition
# ---------------------------------------------------------------------------

def _set_completion_condition(world: DigimonWorldWorld) -> None:
    """Final Battle requires AS Decoder + 50 PP (= all 25 PP items).
    Redundant with the Tower entrance rule but kept as the explicit
    goal gate."""

    final_battle = world.get_location("Final Battle")
    world.set_rule(final_battle, Has("AS Decoder") & _pp(50))
    world.set_completion_rule(Has("Victory"))


__all__ = ["PROSPERITY_ITEM_NAME", "set_all_rules"]
