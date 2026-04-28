"""Access rules for the Digimon World 1 APWorld (Phase 2: full v1 logic).

Sources

The rule cluster here transcribes the **DWAP-baseline** logic from
``references/dw1_recruitment_logic.md`` §B (the "deployed-but-flawed
baseline" — flawed because DWAP's *runtime* never fires, not because
the logic itself is known-wrong). Where the community recruitment
flowchart and DWAP disagree (``dw1_recruitment_logic.md`` §C), this
module follows DWAP and leaves a comment pointing at the discrepancy
for Phase 2 verification work.

Prosperity model

DW1's prosperity counter is a derived in-game number that increments on
recruit and on certain NPC sidequests. AP-side, we model it as a
``"Prosperity Point"`` event item attached to:

* every recruit location (via :func:`_attach_prosperity_event`), and
* every NPC-gift / "K Prosperity" location (also via
  :func:`_attach_prosperity_event`).

The N-th NPC gift's location rule is then ``Has("Prosperity Point",
count=N)``; recruit gates that use prosperity in DWAP (e.g. Greymon at
15, Vademon at 45, the 50-PP cluster) translate the same way. Each
location grants exactly one prosperity point; the per-recruit
prosperity_value (1, 2, 3) from DWAP's ``RecruitDigimon.py`` is **not**
honored in v1, so the effective prosperity scale is "number of
PP-granting locations completed" rather than "DW1 in-game prosperity".
This is documented in ``phase_progress.md``.

Region access

The flat-hub region graph from :mod:`.regions` means most regions hang
directly off File City. Their access rules encode whichever recruit
chain or item gate the in-game progression demands.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rule_builder.rules import Has, HasAll, HasAny, Rule

from . import locations as locations_module

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


# =============================================================================
# Reusable rule fragments
# =============================================================================
# DWAP's "(6 PP OR Meramon)" appears 14 times; defining it once keeps the
# recruit table below readable.

PROSPERITY_ITEM_NAME = "Prosperity Point"


def _has_pp(count: int) -> Rule:
    return Has(PROSPERITY_ITEM_NAME, count=count)


def _has_meramon_or_pp(threshold: int = 6) -> Rule:
    return Has("Meramon Soul") | _has_pp(threshold)


# =============================================================================
# Per-recruit access rules (DWAP-baseline)
# =============================================================================
# Keyed by the recruit *location* name (matches :data:`locations.RECRUIT_NAMES`).
# Greymon and MetalGreymon are intentionally non-soul (per DWAP); the rule
# just needs the upstream recruit + prosperity. The "Agumon" recruit is
# always reachable from File City — its rule is ``None`` here (no extra
# constraint beyond File City reachability).
#
# When a rule is ``None``, the recruit is reachable as soon as its region is.

def _recruit_rules() -> dict[str, Rule | None]:
    pp = _has_pp
    pp6_or_mera = _has_meramon_or_pp

    return {
        # File City (always reachable from Menu).
        "Agumon": None,

        # Native Forest (early Rookies; "(6 PP OR Meramon)" cluster).
        "Betamon": Has("Betamon Soul"),
        "Gabumon": Has("Gabumon Soul") & pp6_or_mera(),
        "Elecmon": Has("Elecmon Soul") & pp6_or_mera(),
        "Patamon": Has("Patamon Soul") & pp6_or_mera(),
        "Biyomon": Has("Biyomon Soul") & pp6_or_mera(),
        "Sukamon": Has("Sukamon Soul") & pp6_or_mera(),
        "Palmon": Has("Palmon Soul"),
        "Vegiemon": Has("Vegiemon Soul") & Has("Palmon Soul"),

        # Tropical Jungle.
        "Coelamon": Has("Coelamon Soul"),
        "Centarumon": Has("Centarumon Soul"),
        "Bakemon": Has("Bakemon Soul") & pp6_or_mera(),
        "Kunemon": Has("Kunemon Soul"),
        # DWAP: Piximon needs >=3 statcaps (option-gated). v1 has no
        # statcap option; reduce to "always reachable in Tropical Jungle".
        "Piximon": Has("Piximon Soul"),

        # Greatlake (fishing-rod gated by region rule; recruits also need
        # their souls or the recruit-graph prereqs).
        "Seadramon": Has("Seadramon Soul"),
        "Whamon": Has("Whamon Soul") & pp6_or_mera(),
        "Numemon": Has("Numemon Soul") & Has("Whamon Soul"),
        "Shellmon": Has("Shellmon Soul") & pp6_or_mera(),
        "Ogremon": Has("Ogremon Soul") & Has("Whamon Soul") & pp6_or_mera(),

        # Meramon Tunnel — the "Coelamon OR Betamon" prereq comes from DWAP.
        "Meramon": Has("Meramon Soul") & (Has("Coelamon Soul") | Has("Betamon Soul")),

        # Mt. Panorama.
        "Greymon": pp(15),
        "Tyrannomon": Has("Tyrannomon Soul") & Has("Centarumon Soul"),
        "Unimon": Has("Unimon Soul") & Has("Centarumon Soul") & Has("Meramon Soul"),
        "Mamemon": Has("Mamemon Soul") & Has("Meramon Soul"),
        "Leomon": Has("Leomon Soul") & Has("Meramon Soul") & pp(50),

        # Misty Trees.
        "Monzaemon": Has("Monzaemon Soul") & pp6_or_mera(),
        "Kokatorimon": Has("Kokatorimon Soul") & pp6_or_mera(),

        # Beetle Land (also region-gated on Seadramon).
        "Kabuterimon": Has("Kabuterimon Soul") & Has("Seadramon Soul"),
        "Kuwagamon": Has("Kuwagamon Soul") & Has("Seadramon Soul"),

        # Drill Tunnel.
        "Drimogemon": Has("Drimogemon Soul") & Has("Meramon Soul"),

        # Sand Bay (region-gated on Whamon).
        "Penguinmon": Has("Penguinmon Soul") & pp6_or_mera(),

        # Factorial Town.
        "Andromon": Has("Andromon Soul") & Has("Whamon Soul") & Has("Numemon Soul"),
        "Giromon": Has("Giromon Soul") & Has("Whamon Soul") & Has("Numemon Soul"),
        "MetalMamemon": Has("MetalMamemon Soul") & Has("Whamon Soul"),

        # Toy Town.
        "Nanimon": Has("Nanimon Soul") & HasAll("Numemon Soul", "Leomon Soul", "Tyrannomon Soul"),

        # Freezeland.
        "Frigimon": Has("Frigimon Soul") & pp6_or_mera(),
        "Mojyamon": Has("Mojyamon Soul") & pp6_or_mera(),
        "Garurumon": Has("Garurumon Soul") & pp6_or_mera(),
        "Angemon": Has("Angemon Soul") & pp6_or_mera(),

        # Great Canyon.
        "Birdramon": Has("Birdramon Soul") & pp6_or_mera(),
        "Monochromon": Has("Monochromon Soul") & pp6_or_mera(),

        # Mt. Infinity (the late-game prosperity cluster).
        "Vademon": Has("Vademon Soul") & Has("Meramon Soul") & Has("Shellmon Soul") & pp(45),
        "SkullGreymon": Has("SkullGreymon Soul") & pp(50),
        "Devimon": Has("Devimon Soul") & pp(50),
        "Airdramon": Has("Airdramon Soul") & pp(50),
        "Etemon": Has("Etemon Soul") & pp(50),
        "Megadramon": Has("Megadramon Soul") & pp(50),

        # Big Store (50 PP).
        "Ninjamon": Has("Ninjamon Soul") & pp(50),

        # Tower (endgame).
        "MetalGreymon": pp(50),
        "Digitamamon": Has("Digitamamon Soul") & pp(50),
    }


# =============================================================================
# Region-entrance access rules
# =============================================================================
# Many DW1 areas are gated on key items (fishing rod, AS Decoder, etc.) or
# on completing a recruit chain that the in-game story drives. The rules
# below sit on the entrance from File City (or the relevant predecessor)
# into each gated region.

def _entrance_rules() -> dict[tuple[str, str], Rule]:
    pp = _has_pp
    pp6_or_mera = _has_meramon_or_pp

    return {
        # Fishing rod gates Greatlake (Seadramon's recruit + the Whamon
        # swallow access route).
        ("File City", "Greatlake"): Has("old fishrod") | Has("Amazing rod"),
        # Meramon Tunnel itself opens off File City but the Meramon recruit
        # has its own rule; the Tunnel region is accessible without items.
        # Mt. Panorama, Misty Trees, Factorial Town, Drill Tunnel all need
        # Meramon to be recruitable per the flowchart "Meramon encountered"
        # gate — collapsed here to "Has Meramon Soul OR 6 PP".
        ("File City", "Mt. Panorama"): pp6_or_mera(),
        ("File City", "Misty Trees"): pp6_or_mera(),
        ("File City", "Factorial Town"): pp6_or_mera(),
        ("File City", "Drill Tunnel"): pp6_or_mera() & Has("Gear"),
        # Post-Seadramon swim chain.
        ("Greatlake", "Beetle Land"): Has("Seadramon Soul"),
        ("Greatlake", "Sand Bay"): Has("Whamon Soul"),
        # Misty Trees branches.
        ("Misty Trees", "Toy Town"): Has("Mansion Key"),
        ("Misty Trees", "Freezeland"): Has("Frig Key"),
        # Yuramon Quest path → Great Canyon → alt Freezeland route.
        ("Greatlake", "Great Canyon"): pp(6) & Has("Shellmon Soul"),
        ("Great Canyon", "Freezeland"): Has("Frig Key"),
        # Late-game.
        ("File City", "Mt. Infinity"): pp(45),
        ("File City", "Big Store"): pp(50),
        ("Mt. Infinity", "Tower"): Has("AS Decoder") & pp(50),
    }


# =============================================================================
# Top-level entry point
# =============================================================================

def set_all_rules(world: DigimonWorldWorld) -> None:
    _set_entrance_rules(world)
    _set_recruit_rules(world)
    _set_prosperity_gift_rules(world)
    _set_completion_condition(world)


def _set_entrance_rules(world: DigimonWorldWorld) -> None:
    for (source, target), rule in _entrance_rules().items():
        world.set_rule(world.get_entrance(f"{source} to {target}"), rule)


def _set_recruit_rules(world: DigimonWorldWorld) -> None:
    for recruit_name, rule in _recruit_rules().items():
        if rule is not None:
            world.set_rule(world.get_location(recruit_name), rule)
            # Mirror the rule onto the pre-created PP event sibling.
            world.set_rule(
                world.get_location(locations_module.prosperity_event_name(recruit_name)),
                rule,
            )


def _set_prosperity_gift_rules(world: DigimonWorldWorld) -> None:
    """The K-th gift unlocks at Has("Prosperity Point", count=K)."""

    for k in locations_module.PROSPERITY_THRESHOLDS:
        gift_label = f"{k} Prosperity"
        gate_rule = _has_pp(k)
        world.set_rule(world.get_location(gift_label), gate_rule)
        world.set_rule(
            world.get_location(locations_module.prosperity_event_name(gift_label)),
            gate_rule,
        )


def _set_completion_condition(world: DigimonWorldWorld) -> None:
    """Final Battle requires reaching the Tower (region rule already enforces
    the prosperity + AS Decoder chain). Completion is the Victory event."""

    final_battle = world.get_location("Final Battle")
    # Nominally redundant with the Mt. Infinity → Tower entrance rule, but
    # cheap insurance against a future region-graph refactor.
    world.set_rule(final_battle, Has("AS Decoder") & _has_pp(50))
    world.set_completion_rule(Has("Victory"))


__all__ = ["PROSPERITY_ITEM_NAME", "set_all_rules"]
# HasAny imported for future use in Phase 2+ refinements; silence "unused".
_unused = HasAny
