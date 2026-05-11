"""Generate the PopTracker pack JSONs from current world data.

Run from repo root::

    python -m worlds.digimon_world.tools.gen_poptracker

Outputs:

* ``poptracker/Digimon-World-1-AP-PopTracker-Pack/items/items.json``
* ``poptracker/Digimon-World-1-AP-PopTracker-Pack/locations/locations.json``

Keep this script as the single source of truth for the tracker pack.
Hand-edits to the generated JSONs will be overwritten on the next run.

Scope (v0.2): chests + recruits + keyitem pickups, gated by progression
items. Cards / vending / recycle-shop locations and per-seed options
(card_locations, vending_locations, etc.) are not modeled yet.

Logic assumes the player will manually mirror seed options for the
mode-gated items (Tropical Jungle Bridge, Great Canyon Bridge,
Lava Cave Access). In shuffled mode those are AP items; in
vanilla / always_open the player toggles them on at game start.
"""

from __future__ import annotations

import json
from pathlib import Path

from worlds.digimon_world.items import (
    _BIRDRAMON_FLIGHT_ITEMS,
    _INDIVIDUAL_RECRUIT_CLASSIFICATIONS,
    _KEY_ITEMS,
    _PROGRESSIVE_ITEMS,
    PROGRESSIVE_BUNDLES,
    PROGRESSIVE_COUNTS,
)
from worlds.digimon_world.locations import (
    _CHEST_BY_SLOT,
    _KEYITEM_LOCATIONS,
    _RECRUIT_REGIONS,
    RECRUIT_PP_REQUIREMENTS,
)

# ---------------------------------------------------------------------------
# Region pin coordinates on file_island.png (1500x1300)
# ---------------------------------------------------------------------------

REGION_PINS: dict[str, tuple[int, int]] = {
    "File City":              (770,  680),
    "Native Forest":          (800,  850),
    "Tropical Jungle":        (1180, 700),
    "Overdell":               (1050, 580),
    "Grey Lord's Mansion":    (980,  460),
    "Ancient Dino Region":    (1200, 600),
    "Greatlake":              (700,  950),
    "Beetle Land":            (380,  1000),
    "Great Canyon":           (1290, 380),
    "Freezeland":             (890,  200),
    "Drill Tunnel":           (610,  760),
    "Meramon Tunnel":         (530,  745),
    "Leomon Ancestor Cave":   (555,  815),
    "Mt. Panorama":           (520,  650),
    "Gear Savanna":           (280,  540),
    "Geko Swamp":             (390,  380),
    "Misty Trees":            (470,  280),
    "Toy Town":               (510,  200),
    "Factorial Town":         (220,  460),
    "Mt. Infinity":           (640,  400),
    "Tower":                  (660,  320),
    "Big Store":              (790,  540),
    "Secret Beach Cave":      (1080, 1050),
    "Back Dimension":         (660,  460),
}


# ---------------------------------------------------------------------------
# Item-code naming
# ---------------------------------------------------------------------------

def code_for_item(name: str) -> str:
    """PopTracker code identifier for a given AP item name."""

    return (
        name.lower()
        .replace(" ", "_")
        .replace(":", "")
        .replace(".", "")
        .replace("'", "")
        .replace("-", "_")
    )


def code_for_recruit_item(digimon: str) -> str:
    return "recruit_" + code_for_item(digimon)


def code_for_flight_item(name: str) -> str:
    # name = "Birdramon Flight: Gear Savanna"
    dest = name.split(":", 1)[1].strip()
    return "flight_" + code_for_item(dest)


def code_for_progressive(name: str) -> str:
    # "Progressive Item Shop" -> "prog_item_shop"
    return "prog_" + code_for_item(name.removeprefix("Progressive ").strip())


# ---------------------------------------------------------------------------
# Region-reach rules (PopTracker access_rules string syntax)
# ---------------------------------------------------------------------------
#
# Rules are inserted on each AP location. We use Lua helper functions
# defined in scripts/logic.lua (one per region) so the access_rules
# stay compact and the region graph lives in one place.
#
# A child location's full rule = "$reach_<region>" + per-location extras.

REGION_LUA_FUNCS = {region: "reach_" + code_for_item(region) for region in REGION_PINS}


# ---------------------------------------------------------------------------
# Per-recruit extra rules (mirrors rules.py _RECRUIT_EXTRA_RULES)
# ---------------------------------------------------------------------------

def _extras_for_recruit(digimon: str) -> list[str]:
    """List of additional access-rule clauses (AND-joined) for a recruit."""

    extras: list[str] = []
    pp = RECRUIT_PP_REQUIREMENTS.get(digimon, 0)
    if pp > 0:
        extras.append(f"$has_pp|{pp}")
    if digimon == "Vegiemon":
        extras.append(code_for_item("Rain Plant"))
    elif digimon == "SkullGreymon":
        extras += [
            code_for_item("Mansion Key"),
            code_for_item("Frig Key"),
            code_for_recruit_item("Shellmon"),
        ]
    elif digimon == "Monzaemon":
        extras.append(code_for_item("Gear"))
    elif digimon == "Leomon":
        extras.append(code_for_item("Leomonstone"))
    elif digimon == "Ogremon":
        extras.append("$reach_freezeland")
    elif digimon == "Whamon":
        extras.append("$reach_great_canyon")
    elif digimon == "Shellmon":
        extras.append("$reach_freezeland")
    elif digimon == "Unimon":
        extras.append(code_for_recruit_item("Centarumon"))
    elif digimon == "Ninjamon":
        # secret-shop tier 1 + bridge (shuffled-mode optimistic)
        extras += [
            code_for_progressive("Progressive Secret Shop"),
            code_for_item("Tropical Jungle Bridge"),
        ]
    elif digimon == "Coelamon":
        extras.append(code_for_item("Tropical Jungle Bridge"))
    elif digimon == "Drimogemon":
        extras.append(code_for_item("Lava Cave Access"))
    return extras


# ---------------------------------------------------------------------------
# Per-keyitem-pickup extras (mirrors rules.py _set_keyitem_pickup_rules)
# ---------------------------------------------------------------------------

KEYITEM_EXTRAS: dict[str, list[str]] = {
    "Rain Plant Pickup":  [code_for_recruit_item("Palmon")],
    "Blue Flute Pickup":  [],  # OR rule handled in build_access_rule
    "Leomonstone Pickup": ["$has_pp|45"],
}

# Locations that have an OR in their rule — represented as multiple
# alternative rule strings (PopTracker treats array elements as OR).
KEYITEM_OR_RULES: dict[str, list[str]] = {
    "Blue Flute Pickup": [
        code_for_item("Old Fishrod"),
        code_for_item("Amazing rod"),
    ],
}


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------

PIN_IMG = "images/items/jijimon.png"
PIN_OPENED_IMG = "images/items/jijimon_opened.png"
ITEM_IMG = "images/items/jijimon.png"


def build_access_rule(region: str, extras: list[str]) -> list[str]:
    """Build the PopTracker access_rules array.

    Returns a list of strings. Each string is a comma-separated AND
    conjunction; the outer list is OR'd by PopTracker.
    """

    base = f"${REGION_LUA_FUNCS[region]}"
    if extras:
        return [", ".join([base, *extras])]
    return [base]


def build_keyitem_access_rule(pickup_name: str, region: str) -> list[str]:
    """Build keyitem access_rules, including special OR cases."""

    base = f"${REGION_LUA_FUNCS[region]}"
    extras = KEYITEM_EXTRAS.get(pickup_name, [])
    or_terms = KEYITEM_OR_RULES.get(pickup_name)
    if or_terms:
        return [", ".join([base, t, *extras]) for t in or_terms]
    return build_access_rule(region, extras)


def gen_items() -> list[dict]:
    """Build the items.json contents."""

    items: list[dict] = []

    # --- Key items (toggles) ---
    for name in _KEY_ITEMS:
        items.append(
            {
                "name": name,
                "type": "toggle",
                "img": ITEM_IMG,
                "codes": code_for_item(name),
            },
        )

    # --- Birdramon flights (toggles) ---
    for name in _BIRDRAMON_FLIGHT_ITEMS:
        items.append(
            {
                "name": name,
                "type": "toggle",
                "img": ITEM_IMG,
                "codes": code_for_flight_item(name),
            },
        )

    # --- Individual recruits (toggles) ---
    for digimon in _INDIVIDUAL_RECRUIT_CLASSIFICATIONS:
        items.append(
            {
                "name": f"{digimon} Recruit",
                "type": "toggle",
                "img": ITEM_IMG,
                "codes": code_for_recruit_item(digimon),
            },
        )

    # --- Progressives ---
    for prog_name in _PROGRESSIVE_ITEMS:
        copies = PROGRESSIVE_COUNTS[prog_name]
        base_code = code_for_progressive(prog_name)
        stages: list[dict] = [
            {
                "img": ITEM_IMG,
                "codes": base_code,
                "inherit_codes": False,
            },
        ]
        for tier in range(1, copies + 1):
            stages.append(
                {
                    "img": ITEM_IMG,
                    "codes": f"{base_code}_{tier}",
                    "inherit_codes": False,
                },
            )
        items.append(
            {
                "name": prog_name,
                "type": "progressive",
                "codes": base_code,
                "allow_disabled": False,
                "stages": stages,
            },
        )

    # --- Prosperity counter (consumable) ---
    items.append(
        {
            "name": "Prosperity Point",
            "type": "consumable",
            "img": ITEM_IMG,
            "codes": "prosperity_point",
            "max_quantity": 100,
            "increment": 1,
            "decrement": 1,
            "initial_quantity": 0,
        },
    )

    return items


def _format_section_name(ap_name: str, extras: list[str]) -> str:
    """Annotate a section name with its extra (per-check) requirements.

    PopTracker sections share the parent Location's ``access_rules``;
    they cannot carry their own. Per-AP-check rules from rules.py
    (e.g. Greymon's 15 PP gate, SkullGreymon's Mansion Key) are
    surfaced as a `[ ... ]` suffix on the section name so the player
    can see them in the popup.
    """

    if not extras:
        return ap_name

    def _pretty(token: str) -> str:
        if token.startswith("$has_pp|"):
            return token.split("|", 1)[1] + " PP"
        if token.startswith("$reach_"):
            return "reach " + token[len("$reach_"):].replace("_", " ").title()
        # plain item-code reference
        return token.replace("_", " ").title()

    notes = ", ".join(_pretty(t) for t in extras)
    return f"{ap_name}  [{notes}]"


def gen_locations() -> list[dict]:
    """Build the locations.json contents.

    One Location per region, pinned at the region's (x, y). Each AP
    check in the region is a *section* of that Location — the popup
    lists "Region Name" on top with each section as a tick-mark below.

    Sections share the parent Location's ``access_rules``, so the
    parent rule is just region-reach (``$reach_<region>``). Per-check
    extra requirements (PP gates, key items, prerequisite recruits)
    are surfaced as a `[ ... ]` suffix on the section name — they are
    advisory text the player reads, not enforced gates in the tracker.
    """

    by_region: dict[str, list[dict]] = {region: [] for region in REGION_PINS}

    # Recruits
    for digimon, region in _RECRUIT_REGIONS.items():
        extras = _extras_for_recruit(digimon)
        by_region.setdefault(region, []).append(
            {"name": _format_section_name(digimon, extras)},
        )

    # Chests
    for _slot, (chest_name, region) in _CHEST_BY_SLOT.items():
        region = region or "File City"
        by_region.setdefault(region, []).append(
            {"name": chest_name},
        )

    # Keyitem pickups
    for pickup_name, entry in _KEYITEM_LOCATIONS.items():
        region = entry.region
        extras = KEYITEM_EXTRAS.get(pickup_name, [])
        # OR rules surface as a single combined note.
        or_terms = KEYITEM_OR_RULES.get(pickup_name)
        note_extras: list[str] = list(extras)
        if or_terms:
            joined = " or ".join(t.replace("_", " ").title() for t in or_terms)
            note_extras.insert(0, f"$_or:{joined}")
        # Custom-format pass for the synthetic $_or token.
        def _fmt(t: str) -> str:
            if t.startswith("$_or:"):
                return t[len("$_or:"):]
            return t

        formatted_name = _format_section_name(
            pickup_name,
            [_fmt(t) for t in note_extras],
        )
        by_region.setdefault(region, []).append(
            {"name": formatted_name},
        )

    locations: list[dict] = []
    for region, (x, y) in REGION_PINS.items():
        sections = by_region.get(region, [])
        sections.sort(key=lambda s: s["name"])
        locations.append(
            {
                "name": region,
                "access_rules": [f"${REGION_LUA_FUNCS[region]}"],
                "chest_unopened_img": PIN_IMG,
                "chest_opened_img": PIN_OPENED_IMG,
                "map_locations": [{"map": "file_island", "x": x, "y": y}],
                "sections": sections,
            },
        )

    return locations


def main() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    pack = repo_root / "poptracker" / "Digimon-World-1-AP-PopTracker-Pack"
    items_path = pack / "items" / "items.json"
    locations_path = pack / "locations" / "locations.json"

    items_path.parent.mkdir(parents=True, exist_ok=True)
    locations_path.parent.mkdir(parents=True, exist_ok=True)

    items = gen_items()
    locations = gen_locations()

    with items_path.open("w", encoding="utf-8") as fh:
        json.dump(items, fh, indent=2)
        fh.write("\n")

    with locations_path.open("w", encoding="utf-8") as fh:
        json.dump(locations, fh, indent=2)
        fh.write("\n")

    print(f"Wrote {items_path} ({len(items)} items)")
    print(f"Wrote {locations_path} ({len(locations)} regions, "
          f"{sum(len(loc['sections']) for loc in locations)} section checks)")


if __name__ == "__main__":
    main()
