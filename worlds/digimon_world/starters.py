"""Starter Digimon randomization for Digimon World 1.

Picks the two starter Digimon at patch-apply time, optionally with a
specific evolution-level filter and a "weakest tech" rule for choosing
each starter's first equipped technique. Mirrors the standalone DW1
randomizer's ``randomizeStarters`` (see
``references/digimon_world_randomizer/digimon/handler.py``,
clean-room).

Five ROM writes per starter slot (see
:data:`worlds.digimon_world.data.addresses.ROM_STARTER_SET_DIGIMON`
and friends):

* the starter's Digimon id (used at "Pick your partner" time),
* an id-check site that gates which starter-tech-equip path runs,
* the tech-id the chosen path teaches, and
* the equipped-tech animation slot.

Plus one extra global "starter for stat-trigger" id-check site shared
between the two starters.

The shuffle parses both DIGIMON_PARA (to find each candidate's level
and per-Digimon tech list) and TECH_PARA (to know which techs are
damaging / non-finisher / non-bubble, i.e. learnable). All metadata
is read from the live ROM at apply time, so the shuffle stays a
single source of truth — no static price/level lookup to maintain.
"""

from __future__ import annotations

import struct
from random import Random
from typing import Final, NamedTuple

# =============================================================================
# Static metadata (clean-room from meekrhino's Digimon / Tech classes)
# =============================================================================
# Source: ``references/digimon_world_randomizer/digimon/handler.py:25, 602-604``.

# Digimon ids that are valid as a player's partner. Anything outside this
# set is an enemy / NPC / placeholder slot in DIGIMON_PARA.
PLAYABLE_DIGIMON_IDS: Final[frozenset[int]] = (
    frozenset(range(0x01, 0x3E)) | frozenset({0x3F, 0x40, 0x41})
)

# Tech ids that are "finisher" moves — too strong / cinematic to be a
# viable starter tech in vanilla.
FINISHER_TECH_IDS: Final[frozenset[int]] = frozenset(range(0x3A, 0x71))

# Tech ids 0x71..0x78 are "Bubble" duplicates — placeholder fresh / in-
# training attacks that aren't really learnable in the meekrhino sense.
BUBBLE_TECH_IDS: Final[frozenset[int]] = frozenset(range(0x71, 0x79))

# 0x2D is "Counter", which has its own special handling in vanilla and
# isn't a sensible starter tech (it's reactive, not offensive).
COUNTER_TECH_ID: Final = 0x2D

# DW1 Digimon level enum. Matches the byte stored at DIGIMON_PARA's
# ``level`` field; the standalone uses these to gate playability.
LEVEL_FRESH: Final = 0x01
LEVEL_IN_TRAINING: Final = 0x02
LEVEL_ROOKIE: Final = 0x03
LEVEL_CHAMPION: Final = 0x04
LEVEL_ULTIMATE: Final = 0x05

ALL_LEVELS: Final = (
    LEVEL_FRESH, LEVEL_IN_TRAINING, LEVEL_ROOKIE, LEVEL_CHAMPION, LEVEL_ULTIMATE,
)

# Sentinel value DW1 uses in tech-list slots to mean "no tech".
NO_TECH_ID: Final = 0xFF

# DW1's animation-id table places the 16 tech-slot animations at
# contiguous bytes ``0x2E..0x3D``. Tech slot N (1-based) maps to
# animation byte ``0x2E + (N - 1)``. Source:
# ``references/digimon_world_randomizer/digimon/util.py:181-195``.
TECH_SLOT_ANIM_BASE: Final = 0x2E


def tech_slot_to_anim_id(slot_one_based: int) -> int:
    """Encode a 1-based tech-slot index as the equip-animation byte.

    Mirrors meekrhino's ``digimon/util.py:techSlotAnimID``. Slot 1 ->
    0x2E, slot 2 -> 0x2F, ..., slot 16 -> 0x3D.

    Earlier (buggy) implementation used ``1 + (slot - 1) * 0x10`` which
    encoded into a wrong animation range — symptom was a phantom equipped
    tech that wasn't in the partner's learned list. Fixed 2026-05-08.
    """

    if not 1 <= slot_one_based <= 16:
        raise ValueError(f"tech slot must be 1..16, got {slot_one_based}")
    return TECH_SLOT_ANIM_BASE + (slot_one_based - 1)


# =============================================================================
# DIGIMON_PARA / TECH_PARA record layout
# =============================================================================
# Sources: ``digimon/data.py``: ``digimonDataFormat = '<20sihh23Bx'``
# and ``techDataFormat = '<3H8Bxx'``.

DIGIMON_RECORD_FORMAT: Final = "<20sihh23Bx"
DIGIMON_RECORD_SIZE: Final = struct.calcsize(DIGIMON_RECORD_FORMAT)
assert DIGIMON_RECORD_SIZE == 52, DIGIMON_RECORD_SIZE
DIGIMON_TECH_LIST_LEN: Final = 16  # each digimon has 16 tech-list slots

TECH_RECORD_FORMAT: Final = "<3H8Bxx"
TECH_RECORD_SIZE: Final = struct.calcsize(TECH_RECORD_FORMAT)
assert TECH_RECORD_SIZE == 16, TECH_RECORD_SIZE


class DigimonProps(NamedTuple):
    """Per-id DIGIMON_PARA properties used for starter selection."""

    digimon_id: int
    level: int                # 0x01 FRESH .. 0x05 ULTIMATE
    tech_list: tuple[int, ...]  # 16 tech ids; NO_TECH_ID = empty slot

    @property
    def is_playable(self) -> bool:
        return self.digimon_id in PLAYABLE_DIGIMON_IDS


class TechProps(NamedTuple):
    """Per-id TECH_PARA properties used for starter-tech selection."""

    tech_id: int
    power: int   # u16 base damage; 0 means non-damaging

    @property
    def is_damaging(self) -> bool:
        return self.power > 0

    @property
    def is_finisher(self) -> bool:
        return self.tech_id in FINISHER_TECH_IDS

    @property
    def is_learnable(self) -> bool:
        return not self.is_finisher and self.tech_id not in BUBBLE_TECH_IDS


def parse_digimon_table(table_user_data: bytes, count: int) -> list[DigimonProps]:
    """Parse DIGIMON_PARA user data into per-id property records."""

    expected = count * DIGIMON_RECORD_SIZE
    if len(table_user_data) != expected:
        raise ValueError(
            f"digimon table user data must be {expected} bytes, got {len(table_user_data)}",
        )
    out: list[DigimonProps] = []
    for i in range(count):
        rec = table_user_data[
            i * DIGIMON_RECORD_SIZE:(i + 1) * DIGIMON_RECORD_SIZE
        ]
        unpacked = struct.unpack(DIGIMON_RECORD_FORMAT, rec)
        # Layout (after 20s name + i + h + h):
        #   index 4  -> type
        #   index 5  -> level
        #   index 6..8  -> spec[3]
        #   index 9  -> item
        #   index 10 -> drop_rate
        #   index 11..26 -> tech[16]
        level = unpacked[5]
        tech_list = tuple(unpacked[11:11 + DIGIMON_TECH_LIST_LEN])
        out.append(
            DigimonProps(digimon_id=i, level=int(level), tech_list=tech_list),
        )
    return out


def parse_tech_table(table_user_data: bytes, count: int) -> list[TechProps]:
    """Parse TECH_PARA user data into per-id property records."""

    expected = count * TECH_RECORD_SIZE
    if len(table_user_data) != expected:
        raise ValueError(
            f"tech table user data must be {expected} bytes, got {len(table_user_data)}",
        )
    out: list[TechProps] = []
    for i in range(count):
        rec = table_user_data[
            i * TECH_RECORD_SIZE:(i + 1) * TECH_RECORD_SIZE
        ]
        unpacked = struct.unpack(TECH_RECORD_FORMAT, rec)
        # Layout: (unkn1 u16, aiDist u16, power u16, mp3 u8, itime u8,
        #          range u8, spec u8, effect u8, accuracy u8, effChance u8, unkn2 u8).
        out.append(TechProps(tech_id=i, power=int(unpacked[2])))
    return out


# =============================================================================
# Selection
# =============================================================================

def eligible_starter_ids(
    digimons: list[DigimonProps],
    *,
    allowed_levels: frozenset[int],
) -> list[int]:
    """Return the list of Digimon ids eligible to spawn as a starter.

    A Digimon must (a) have an id in :data:`PLAYABLE_DIGIMON_IDS` and
    (b) carry one of the levels in ``allowed_levels``. Mirrors
    :meth:`DigimonWorldHandler.getPlayableDigimonByLevel` aggregated
    across the requested levels.
    """

    return [
        d.digimon_id for d in digimons
        if d.is_playable and d.level in allowed_levels
    ]


def pick_starter_tech(
    digimon: DigimonProps,
    techs: list[TechProps],
    *,
    random: Random,
    use_weakest: bool,
) -> tuple[int, int] | None:
    """Pick the (tech_id, slot_one_based) for ``digimon``'s starter tech.

    With ``use_weakest`` on (matches meekrhino's default), iterate the
    Digimon's tech list in slot order and pick the first slot whose
    tech is damaging, non-finisher, and not Counter — i.e. the lowest
    *tier* learnable damaging tech the Digimon can use. With it off,
    pick a uniformly-random damaging non-finisher non-Counter tech
    from the Digimon's tech list (also matches meekrhino).

    Returns ``None`` if the Digimon has no eligible tech in its list
    (degenerate case, e.g. a Fresh whose only tech is Bubble). Caller
    should leave the existing starterLearnTech bytes untouched in
    that case.
    """

    eligible_slots: list[tuple[int, int]] = []  # (tech_id, slot_one_based)
    for slot_index, tech_id in enumerate(digimon.tech_list):
        if tech_id == NO_TECH_ID or tech_id >= len(techs):
            continue
        tech = techs[tech_id]
        if tech.is_finisher or tech.tech_id == COUNTER_TECH_ID:
            continue
        if not tech.is_damaging:
            continue
        eligible_slots.append((tech_id, slot_index + 1))

    if not eligible_slots:
        return None
    if use_weakest:
        return eligible_slots[0]  # earliest slot = lowest tier
    return random.choice(eligible_slots)


class StarterAssignment(NamedTuple):
    """Result of one starter-slot pick: id, tech-id, animation-byte.

    ``tech_id`` and ``anim_id`` are ``None`` when the chosen Digimon
    has no eligible damaging tech — caller should skip writing the
    learn-tech / equip-anim sites for that slot.
    """

    digimon_id: int
    tech_id: int | None
    anim_id: int | None


def pick_starters(
    digimons: list[DigimonProps],
    techs: list[TechProps],
    *,
    random: Random,
    allowed_levels: frozenset[int],
    use_weakest_tech: bool,
) -> tuple[StarterAssignment, StarterAssignment] | None:
    """Pick both starter assignments at once.

    Two distinct Digimon are drawn from the eligible pool (any Digimon
    matching ``allowed_levels`` and being playable). Each gets its own
    starter tech via :func:`pick_starter_tech`.

    Returns ``None`` if the eligible pool has fewer than two members
    (the caller leaves vanilla starters untouched in that case).
    """

    pool = eligible_starter_ids(digimons, allowed_levels=allowed_levels)
    if len(pool) < 2:
        return None
    first_id = random.choice(pool)
    second_id = random.choice([d for d in pool if d != first_id])

    def _assign(digimon_id: int) -> StarterAssignment:
        tech_pick = pick_starter_tech(
            digimons[digimon_id], techs,
            random=random, use_weakest=use_weakest_tech,
        )
        if tech_pick is None:
            return StarterAssignment(
                digimon_id=digimon_id, tech_id=None, anim_id=None,
            )
        tech_id, slot_one_based = tech_pick
        return StarterAssignment(
            digimon_id=digimon_id,
            tech_id=tech_id,
            anim_id=tech_slot_to_anim_id(slot_one_based),
        )

    return _assign(first_id), _assign(second_id)


__all__ = [
    "ALL_LEVELS",
    "BUBBLE_TECH_IDS",
    "COUNTER_TECH_ID",
    "DIGIMON_RECORD_FORMAT",
    "DIGIMON_RECORD_SIZE",
    "DIGIMON_TECH_LIST_LEN",
    "FINISHER_TECH_IDS",
    "LEVEL_CHAMPION",
    "LEVEL_FRESH",
    "LEVEL_IN_TRAINING",
    "LEVEL_ROOKIE",
    "LEVEL_ULTIMATE",
    "NO_TECH_ID",
    "PLAYABLE_DIGIMON_IDS",
    "TECH_RECORD_FORMAT",
    "TECH_RECORD_SIZE",
    "TECH_SLOT_ANIM_BASE",
    "DigimonProps",
    "StarterAssignment",
    "TechProps",
    "eligible_starter_ids",
    "parse_digimon_table",
    "parse_tech_table",
    "pick_starter_tech",
    "pick_starters",
    "tech_slot_to_anim_id",
]
