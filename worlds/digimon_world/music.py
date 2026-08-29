"""Per-screen background-music randomization for Digimon World 1.

Every screen section of the boot-resident MAPHEAD.SCN issues ``setPStat 245 mode`` followed by
``playBGM font`` (``5D font``). The byte **is** the music font (1..33); ``handleMusicOverride``
turns the mode into the variant -- 0 = day / night pair, 1 = the day track only, 2..10 = a forced
(font, variant) where the byte is inert. ``playMusic`` streams the font from ``FAALL.VHB`` on
every change, so any field font can play on any screen; an unknown byte only means silence, so
nothing here can crash the game. Source: ``work/dw1_re/decomp/raise_bgm/NOTES.md`` (2026-08-29).

Three flavours: ``areas`` permutes the field fonts among the areas that use them (every screen
that played the Canyon theme now plays one other theme -- the vanilla one-font-per-area feel is
kept), ``screens`` gives every screen its own draw, ``chaos`` adds the looping battle themes to
the draw. The four one-shot arena jingle fonts (29..32) are never dealt, forced-mode sites are
left alone, and the five ``playBGM`` opcodes that live in story scripts stay vanilla.
"""

from __future__ import annotations

from random import Random
from typing import TYPE_CHECKING, Final, NamedTuple

from .data.addresses import SCREEN_FILENAMES
from .data.enemy_records import BGM_SITES, BGM_TRACKS

if TYPE_CHECKING:
    from .world import DigimonWorldWorld


class BgmSite(NamedTuple):
    section: int    # MAPHEAD section id == screen id
    vm: int         # in-file offset of the ``5D`` opcode; the font byte is at ``vm + 1``
    font: int
    mode: int


SITES: Final[tuple[BgmSite, ...]] = tuple(BgmSite(*row) for row in BGM_SITES)
TRACK_NAMES: Final[dict[tuple[int, int], str]] = {(font, variant): name for font, variant, name in BGM_TRACKS}

FIELD_FONTS: Final = tuple(range(1, 29))
BATTLE_FONT: Final = 33
JINGLE_FONTS: Final = (29, 30, 31, 32)
MODE_DAY_NIGHT: Final = 0
MODE_DAY_ONLY: Final = 1

SHUFFLE_OFF: Final = 0
SHUFFLE_AREAS: Final = 1
SHUFFLE_SCREENS: Final = 2
SHUFFLE_CHAOS: Final = 3


def track_name(font: int, variant: int = 0) -> str:
    return TRACK_NAMES.get((font, variant)) or TRACK_NAMES.get((font, 0)) or f"font {font}"


def eligible_sites() -> list[int]:
    """Indices into :data:`SITES` whose byte the game actually plays: day / night or day-only
    modes with a field font."""

    return [index for index, site in enumerate(SITES)
            if site.mode in (MODE_DAY_NIGHT, MODE_DAY_ONLY) and site.font in FIELD_FONTS]


def randomize_music(rng: Random, mode: int) -> dict[int, int]:
    """``site index -> new font`` for every eligible site whose font changes."""

    if mode == SHUFFLE_OFF:
        return {}
    pool = list(FIELD_FONTS) + ([BATTLE_FONT] if mode == SHUFFLE_CHAOS else [])
    eligible = eligible_sites()
    new_font: dict[int, int] = {}
    if mode == SHUFFLE_AREAS:
        fonts_in_use = sorted({SITES[index].font for index in eligible})
        mapping = dict(zip(fonts_in_use, rng.sample(pool, len(fonts_in_use)), strict=True))
        for index in eligible:
            new_font[index] = mapping[SITES[index].font]
    else:
        per_section: dict[int, int] = {}
        for index in eligible:
            section = SITES[index].section
            if section not in per_section:
                per_section[section] = rng.choice(pool)
            new_font[index] = per_section[section]
    return {index: font for index, font in new_font.items() if font != SITES[index].font}


class BgmPlan(NamedTuple):
    #: site index -> new font (changed sites only)
    overrides: dict[int, int]
    mode: int

    @property
    def empty(self) -> bool:
        return not self.overrides


EMPTY_PLAN: Final = BgmPlan({}, SHUFFLE_OFF)


def build_bgm_plan(world: DigimonWorldWorld) -> BgmPlan:
    """Resolve the option into concrete MAPHEAD byte rewrites (call from ``generate_early``)."""

    mode = int(world.options.bgm_shuffle.value)
    return BgmPlan(randomize_music(world.random, mode), mode)


def describe_plan(plan: BgmPlan) -> list[str]:
    """Spoiler lines: one per vanilla theme under ``areas``, one per screen otherwise."""

    if plan.mode == SHUFFLE_AREAS:
        mapping: dict[int, int] = {}
        for index, font in plan.overrides.items():
            mapping.setdefault(SITES[index].font, font)
        return [f"{track_name(old)} -> {track_name(new)}" for old, new in sorted(mapping.items())]
    lines = []
    for index, font in sorted(plan.overrides.items()):
        site = SITES[index]
        screen = SCREEN_FILENAMES.get(site.section, f"section {site.section}")
        lines.append(f"{screen}: {track_name(site.font)} -> {track_name(font)}")
    return lines
