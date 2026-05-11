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
* **No per-chest rules.** Each chest is in a confirmed in-game region
  (verified via script + screen + room-code on 2026-05-09); the
  region's entrance access rule transitively gates the chest. So
  e.g. a chest in ``Factorial Town`` is reachable iff Whamon Recruit
  is delivered, and a chest in ``Mt. Infinity`` requires 50 PP — no
  per-chest rule is needed on top of the region rule.
* **Final Battle** rule: 50 PP (matches the Tower entrance rule;
  redundant but keeps the goal explicit). AS Decoder used to be part
  of this rule but was removed 2026-05-08 — it does nothing in-game
  and gates nothing.

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

from BaseClasses import ItemClassification, LocationProgressType
from rule_builder.rules import CanReachRegion, Has

from .items import PROSPERITY_PER_ITEM
from .locations import (
    RECRUIT_PP_REQUIREMENTS,
    _CHEST_BY_SLOT,
)

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
    _set_keyitem_pickup_rules(world)
    _apply_pp_cutoffs(world)
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
    # Mt. Infinity / Tower / Back Dimension / Final Battle all share
    # the player's configured threshold (the in-game
    # ``pstat(1) < 50`` literal in Script 210 §51 is patched at
    # generation time to the same value, so AP logic and the in-game
    # gate stay in sync).
    mt_threshold = int(options.prosperity_goal.value)

    # ------- File City direct entries -------
    _set_entrance_rule(world, "File City", "Mt. Infinity", _pp(mt_threshold))
    _set_entrance_rule(world, "File City", "Big Store", _pp(mt_threshold))
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
        _pp(mt_threshold),
    )

    # ------- Sub-area gates -------
    # Drill Tunnel → Leomon Ancestor Cave: 45 PP (matches the
    # Leomonstone Pickup gate; the Stone Tablet sits inside the cave).
    # When ``prosperity_goal < 45`` the player can never trigger
    # the cave entrance in-game (Drimogemon's daily dig is gated on the
    # vanilla 45-PP check). We drop the AP rule so fill can still place
    # filler at the cave's chest location, and ``_apply_pp_cutoffs``
    # below marks that chest EXCLUDED + filler-only.
    if 45 <= mt_threshold:
        _set_entrance_rule(
            world, "Drill Tunnel", "Leomon Ancestor Cave",
            _pp(45),
        )
    # File City → Secret Beach Cave: Whamon Recruit (Whamon transports
    # the player to the beach where the cave is).
    _set_entrance_rule(
        world, "File City", "Secret Beach Cave",
        Has("Whamon Recruit"),
    )
    # File City → Back Dimension: post-game. All four gates are required:
    #
    #   1. ``_pp(prosperity_goal)`` — Mt. Infinity must be open in-game
    #      (same threshold as the Airdramon ambush). Tracks the
    #      ``prosperity_goal`` option so the tracker locks Back
    #      Dimension chests until the player can actually fight
    #      Machinedramon.
    #   2-4. ``CanReachRegion(...)`` over the three physical Back-Dimension
    #      portal regions — Grey Lord's Mansion, Freezeland's Ice
    #      Sanctuary side, and Great Canyon's Ogre Fortress side. The
    #      player must be able to reach **all three** to traverse the
    #      complete Back Dimension (the seven chests are spread across
    #      the regions reached via each portal, so missing any portal
    #      means missing chests).
    #
    # All chests inside are flagged EXCLUDED + filler-only, so this
    # rule is a tracker-correctness gate (locks the chests until all
    # conditions are met) rather than an AP-fill constraint.
    _set_entrance_rule(
        world, "File City", "Back Dimension",
        _pp(mt_threshold)
        & CanReachRegion("Grey Lord's Mansion")
        & CanReachRegion("Freezeland")
        & CanReachRegion("Great Canyon"),
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
    #     are in city. Both Digimon are now bundled into Progressive
    #     Item Shop (T1 = Betamon+Coelamon, T2 = Patamon+Monochromon),
    #     so the rule is ``Has(Progressive Item Shop, count=2)``: T1
    #     provides Betamon, T2 provides Patamon.
    # Either parent satisfies access (AP region access is OR over edges).
    # The "Card Vending" region exists unconditionally; rules and
    # locations only matter when the option is on.
    _set_entrance_rule(
        world, "File City", "Card Vending",
        Has("Progressive Item Shop", count=2),
    )
    # Gear Savanna → Card Vending: free (no rule)

    # Tropical Jungle → Ancient Dino Region: free in AP terms. The
    # vanilla in-game gate is "Centarumon's recruit fight completed"
    # (= wild trigger 236 set), but that fight is itself in Tropical
    # Jungle (Amida Forest), so reaching Tropical Jungle implies the
    # player can do the fight; AP doesn't need an explicit item gate.
    # Centarumon Recruit (the AP item) is required only for the
    # Unimon recruit gate (see ``_unimon_extra``), not for Ancient
    # Dino access.

    # ------- Grey Lord's Mansion (Mansion Key gate) -------
    # Locked sub-area inside Overdell. Holds the 6 mansion-internal
    # chests (slots 1, 2, 3, 5, 6, 7 with current naming
    # ``Chest: Grey Lord's Mansion 4..9``). The 3 unlocked-area chests
    # (slots 4, 53, 54 named ``Grey Lord's Mansion 1..3``) live in
    # Overdell and don't need the key.
    _set_entrance_rule(
        world, "Overdell", "Grey Lord's Mansion",
        Has("Mansion Key"),
    )

    # ------- Reverse-direction rules -------
    # Boulder gate applies in both directions: the only way into the
    # Meramon Tunnel region (which holds Meramon and the Lava Cave
    # chests) is through the boulder, regardless of approach side. With
    # the Mt. Panorama → Meramon Tunnel reverse edge added, AP fill
    # would otherwise consider Meramon Tunnel reachable for free via the
    # Gear Savanna walk-back chain — so we replicate the Lava Cave
    # Access gate here.
    if lava_mode == _LCA_SHUFFLED:
        _set_entrance_rule(
            world, "Meramon Tunnel", "Drill Tunnel",
            Has("Lava Cave Access"),
        )
        _set_entrance_rule(
            world, "Mt. Panorama", "Meramon Tunnel",
            Has("Lava Cave Access"),
        )
    # Beetle Land → Greatlake reverse: same fishing-rod / flute gate as
    # the forward edge (it's the same body of water either way).
    _set_entrance_rule(
        world, "Beetle Land", "Greatlake",
        Has("Old Fishrod") | Has("Amazing rod") | Has("Blue Flute"),
    )


# ---------------------------------------------------------------------------
# Recruit rules
# ---------------------------------------------------------------------------

# Recruits with an extra gate beyond the base PP rule. Each entry's
# value is a callable ``(world) -> Rule`` that returns the *additional*
# rule to AND with the base PP rule. We use a callable so we can build
# ``CanReachRegion(...)`` rules that resolve at rule-attach time.

def _vegimon_extra(_world: DigimonWorldWorld):
    return Has("Rain Plant")


def _skullgreymon_extra(_world: DigimonWorldWorld):
    # SkullGreymon is recruited by entering Grey Lord's Mansion
    # (Mansion Key), feeding him Steak, and having Shellmon already
    # recruited. Steak isn't AP-randomized — vanilla DW1 spawns it from
    # the Overdell fridge when the player uses Frig Key on it — so
    # ``Has("Frig Key")`` is the canonical "the player can obtain
    # Steak" approximation.
    return Has("Mansion Key") & Has("Frig Key") & Has("Shellmon Recruit")


def _monzaemon_extra(_world: DigimonWorldWorld):
    return Has("Gear")


def _leomon_extra(_world: DigimonWorldWorld):
    # Per user (2026-05-08): Leomon's recruit gate is the Leomonstone
    # (Stone Tablet) item, full stop. Prior approximation via
    # ``CanReachRegion("Meramon Tunnel")`` modeled the vanilla pickup
    # site of the Stone Tablet, but with Leomonstone now an AP-tracked
    # progression item the gate is direct.
    return Has("Leomonstone")


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


# Ninjamon's recruit spawn is in Native Forest, but reaching that
# spawn requires (a) crossing the Tropical Jungle bridge first (the
# vanilla in-game path threads through Tropical Jungle to reach
# Ninjamon's hangout), and (b) per the recruitment guide, "Recruit
# a Digimon that opens the Secret Item Shop" — Ninjamon stands in
# the Secret Shop after recruit. The Secret Shop is unlocked
# progressively via ``Progressive Secret Shop`` (see
# ``items.PROGRESSIVE_BUNDLES``); receiving 1 copy is enough.
#
# Only emit the bridge rule when ``bridge_unlock`` is in shuffled
# mode — in vanilla / always_open the ``Tropical Jungle Bridge``
# AP item isn't in the pool, so ``Has`` would never be satisfied
# and the recruit would become permanently unreachable.
def _ninjamon_extra(world: DigimonWorldWorld):
    secret_shop_rule = Has("Progressive Secret Shop")
    if int(world.options.bridge_unlock.value) == _OPT_SHUFFLED:
        return Has("Tropical Jungle Bridge") & secret_shop_rule
    return secret_shop_rule


# Unimon's recruit per the guide: "Recruit and then talk to
# Centarumon in the clinic." Centarumon must be recruited first
# because the player can't enter the Clinic to talk to him until
# he's built it. AP gate: ``Has(Centarumon Recruit)``.
def _unimon_extra(_world: DigimonWorldWorld):
    return Has("Centarumon Recruit")


# Coelamon's recruit fires when his "take you across the water" case
# resolves into "Coelamon joins the city". In shuffled mode the patcher
# rewrites his Section_51 branch target so case 1 ("I'll take you
# across") is dead until trigger 185 — the Tropical Jungle Bridge bit —
# is set (see ``ROM_COELAMON_GATE_OFFSETS`` in addresses.py). Without
# the AP item, the cutscene that fires the recruit location never
# completes, so AP logic must AND the bridge in too even though the
# spawn point is geographically in Native Forest.
#
# In vanilla / always_open mode the bridge bit is set organically (or
# pre-pinned), so no extra rule is needed. Returning ``None`` keeps
# the recruit freely reachable in those modes.
def _coelamon_extra(world: DigimonWorldWorld):
    if int(world.options.bridge_unlock.value) == _OPT_SHUFFLED:
        return Has("Tropical Jungle Bridge")
    return None


# Drimogemon is the in-game source of "Lava Cave Access" — vanilla
# DW1 has him dig the Drill Tunnel boulder open after he's beaten.
# In shuffled mode the boulder gate is rewritten to read trigger 145
# (the AP-controlled Lava Cave Access bit; see
# ``ROM_LAVA_CAVE_GATE_OFFSETS``), and Drimogemon's recruit chain
# threads through the lava-cave side of the tunnel before he joins
# the city. Without the AP item, the encounters that complete his
# recruit cutscene aren't reachable, so logic must require the item
# in shuffled mode.
#
# Vanilla mode keeps the digimon-tier whitelist on the boulder, which
# is the player's responsibility (no AP item exists in the pool), so
# we return ``None`` and leave the recruit freely reachable in logic.
def _drimogemon_extra(world: DigimonWorldWorld):
    if int(world.options.lava_cave_access.value) == _LCA_SHUFFLED:
        return Has("Lava Cave Access")
    return None


_RECRUIT_EXTRA_RULES = {
    # Seadramon dropped 2026-05-09 (recruit cutscene IS Blue Flute pickup).
    # The rod-required rule moved to ``Blue Flute Pickup`` in
    # ``_set_keyitem_pickup_rules``. See addresses.py
    # ``_AP_RECRUIT_EXCLUDED``.
    "Vegiemon":     _vegimon_extra,  # in-repo spelling
    "SkullGreymon": _skullgreymon_extra,
    "Monzaemon":    _monzaemon_extra,
    "Leomon":       _leomon_extra,
    # Ogremon-chain region requirements
    "Ogremon":      _ogremon_extra,
    "Whamon":       _whamon_extra,
    "Shellmon":     _shellmon_extra,
    "Ninjamon":     _ninjamon_extra,
    # Phase 7 (2026-05-09) additions:
    # Unimon's spawn requires talking to Centarumon at the Clinic.
    # Tyrannomon's spawn is in Ancient Dino Region, which is itself
    # gated by Centarumon (see the entrance rule in
    # ``_set_entrance_rules``); no extra rule on the Tyrannomon
    # location needed because the region access already implies it.
    "Unimon":       _unimon_extra,
    # Shuffled-mode option gates: each is a no-op rule in non-shuffled
    # modes (the corresponding AP item isn't in the pool).
    "Coelamon":     _coelamon_extra,
    "Drimogemon":   _drimogemon_extra,
}


def _set_recruit_rules(world: DigimonWorldWorld) -> None:
    """Attach the per-recruit rule to each recruit AP location.

    Base rule: ``Has(Prosperity Point, count=ceil(pp/PROSPERITY_PER_ITEM))``.
    Several recruits have an extra rule ANDed in (see
    ``_RECRUIT_EXTRA_RULES``). Recruits at 0 PP with no extra rule are
    skipped (= no rule = always reachable within their region).

    Recruits whose PP requirement exceeds the configured Mt. Infinity
    threshold get NO PP rule attached — the vanilla in-game gate stays
    at the original PP value, so the player can never trigger the
    recruit no matter what AP delivers; ``_apply_pp_cutoffs`` marks
    those locations EXCLUDED + filler-only so AP fill places only
    filler there.
    """

    mt_threshold = int(world.options.prosperity_goal.value)

    for recruit_name, pp in RECRUIT_PP_REQUIREMENTS.items():
        extra_factory = _RECRUIT_EXTRA_RULES.get(recruit_name)
        if pp <= 0 and extra_factory is None:
            continue
        location = world.get_location(recruit_name)
        # Only attach the PP gate if the player can actually reach that
        # PP threshold in-game.
        rule = _pp(pp) if 0 < pp <= mt_threshold else None
        if extra_factory is not None:
            extra = extra_factory(world)
            # Factory may return None when its rule is option-conditional
            # (e.g. ``_ninjamon_extra`` only adds a rule in shuffled mode).
            if extra is not None:
                rule = extra if rule is None else rule & extra
        if rule is None:
            continue
        world.set_rule(location, rule)


# ---------------------------------------------------------------------------
# Completion condition
# ---------------------------------------------------------------------------

def _set_keyitem_pickup_rules(world: DigimonWorldWorld) -> None:
    """Per-pickup access rules for keyitem AP locations.

    Most keyitem pickups need no extra rule beyond region reach (Old
    Fishrod Pickup, Mansion Key Pickup, Frig Key Pickup, Gear Pickup) —
    region wiring covers the prerequisites. Three have additional
    gates:

    * ``Rain Plant Pickup`` requires Palmon Recruit (the cutscene's
      section gate is ``trigger(76) == false AND trigger(246) == true``,
      and trigger 246 is set on Palmon recruit completion). The day-
      15-of-month requirement isn't an AP item — the player advances
      time by playing — so it isn't modeled here.
    * ``Blue Flute Pickup`` requires a fishing rod (Old Fishrod or
      Amazing Rod) — the Seadramon friendship cutscene only fires
      from hooking him while fishing in Dragon Eye Lake.
    * ``Leomonstone Pickup`` requires 45 Prosperity Points — Leomon's
      Ancestral Cave is gated by Drimogemon's daily dig, which only
      breaks through to the cave once city Prosperity reaches 45."""

    mt_threshold = int(world.options.prosperity_goal.value)

    world.set_rule(world.get_location("Rain Plant Pickup"), Has("Palmon Recruit"))
    world.set_rule(
        world.get_location("Blue Flute Pickup"),
        Has("Old Fishrod") | Has("Amazing rod"),
    )
    # Drop the Leomonstone Pickup gate when the cave is unreachable
    # (threshold < 45). ``_apply_pp_cutoffs`` will mark the location
    # EXCLUDED + filler-only.
    if 45 <= mt_threshold:
        world.set_rule(world.get_location("Leomonstone Pickup"), _pp(45))


# ---------------------------------------------------------------------------
# PP-cutoff cleanup (Phase 9)
# ---------------------------------------------------------------------------

# Vanilla in-game prosperity gate for the Leomon Ancestor Cave entrance
# (Drimogemon's daily dig) and for the Leomonstone Pickup itself. Always
# 45 in-game regardless of the AP option.
_LEOMON_CAVE_PP: int = 45


def _apply_pp_cutoffs(world: DigimonWorldWorld) -> None:
    """Mark locations whose vanilla PP gate exceeds the configured
    Mt. Infinity threshold as EXCLUDED + filler-only.

    The 20% comfort margin in :func:`items.prosperity_point_count`
    intentionally does **not** count toward the cutoff: the player
    asked for "Mt. Infinity at threshold X", which means anything
    vanilla DW1 itself gates above X is permanently inaccessible
    in-game (the AP option only patches the one Mt. Infinity gate at
    Script 210 §51 — the other 45/50 PP gates stay vanilla). Their
    AP rules were already skipped by the per-rule passes above; here
    we restrict their item placement to pure filler so AP fill
    doesn't waste useful or progression items at AP locations the
    player can never trigger.
    """

    mt_threshold = int(world.options.prosperity_goal.value)
    excluded: list[str] = []

    # Recruits whose vanilla PP gate is above the configured threshold.
    for recruit_name, pp in RECRUIT_PP_REQUIREMENTS.items():
        if pp > mt_threshold:
            excluded.append(recruit_name)

    # Leomonstone Pickup + every chest in Leomon Ancestor Cave —
    # both share the in-game 45-PP cave entrance.
    if _LEOMON_CAVE_PP > mt_threshold:
        excluded.append("Leomonstone Pickup")
        excluded.extend(
            chest_name
            for chest_name, region in _CHEST_BY_SLOT.values()
            if region == "Leomon Ancestor Cave"
        )

    for name in excluded:
        try:
            location = world.get_location(name)
        except KeyError:
            continue  # location dropped by an unrelated option
        location.progress_type = LocationProgressType.EXCLUDED
        location.item_rule = (
            lambda item: item.classification == ItemClassification.filler
        )


def _set_completion_condition(world: DigimonWorldWorld) -> None:
    """Final Battle requires the configured Mt. Infinity prosperity
    threshold (default 50). Redundant with the Tower entrance rule but
    kept as the explicit goal gate. AS Decoder used to also be
    required, but it is a no-op DW1 item that gates nothing —
    removed 2026-05-08."""

    mt_threshold = int(world.options.prosperity_goal.value)
    final_battle = world.get_location("Final Battle")
    world.set_rule(final_battle, _pp(mt_threshold))
    world.set_completion_rule(Has("Victory"))


__all__ = ["PROSPERITY_ITEM_NAME", "set_all_rules"]
