"""Ground-item randomization for Digimon World 1.

Local randomization of the items that randomly spawn on field maps —
NOT an AP-location feature. Each spot still respawns its (now randomized)
item every map visit per vanilla behavior; nothing is sent to the
multiworld. The shuffle runs at patch-apply time and mutates the
``spawnItem`` opcode's item-id byte for each of the 463 ground-item
spots catalogued by the standalone DW1 randomizer.

Filter behavior is a clean-room reimplementation of meekrhino's
standalone randomizer pool selection (``handler.py:randomizeMapSpawnItems``
and ``Item._getRandomItem`` with ``consumableOnly=True, notQuest=True,
notEvo=True``). The pool-scope toggles (``food_only``, ``match_value``,
``value_cutoff``) mirror its three configurable knobs.

The actual ``ITEM_PARA`` records are read from the user's BIN at apply
time (via :func:`worlds.digimon_world.data.addresses.read_item_table_user_data`)
so the shuffle stays a single source of truth: whatever vanilla price /
sort the canonical ROM has, that's what the filter sees.
"""

from __future__ import annotations

import struct
from random import Random
from typing import Final, NamedTuple

# =============================================================================
# Item-id pool sets (clean-room from meekrhino's Item class)
# =============================================================================
# Source: ``references/digimon_world_randomizer/digimon/handler.py:525-558``.
# These id ranges define which items are eligible to appear in randomized
# pools and how each id classifies for the food / evo / banned filters.

# Items eligible as "consumable" replacements. Same range expression as
# meekrhino's ``Item.consumableItems``.
CONSUMABLE_ITEM_IDS: Final[frozenset[int]] = (
    frozenset(range(0x00, 0x21))
    | frozenset(range(0x26, 0x73))
    | frozenset({0x79, 0x7A, 0x7D, 0x7E, 0x7F})
)

# Quest-item ids (story / progression items that should not get shuffled
# *into* a random pool). Mirrors ``Item.questItems``.
QUEST_ITEM_IDS: Final[frozenset[int]] = (
    frozenset(range(0x73, 0x79)) | frozenset(range(0x7B, 0x7D))
)

# Items the standalone hard-bans because they are gamebreaking or unused.
# Id 0x53 (Electo ring) is also our AP chest sentinel slot — it must
# never be selected as a replacement regardless.
BANNED_ITEM_IDS: Final[frozenset[int]] = frozenset({0x53, 0x72})

# Ids that count as food despite their ITEM_PARA sort byte not being
# ``SORT_FOOD`` (Rain Plant 0x79, Steak 0x7A).
FOOD_EXCEPTION_ITEM_IDS: Final[frozenset[int]] = frozenset({0x79, 0x7A})

SORT_FOOD: Final = 0x02     # ITEM_PARA.sort value for the FOOD class
SORT_STATEVO: Final = 0x04  # ITEM_PARA.sort value for STAT/EVO items

# STATEVO entries with id below this threshold are stat items, not
# evolution items. Above (and including), they're evolution items.
EVO_ITEM_MIN_ID: Final = 0x47


# =============================================================================
# ITEM_PARA record structure
# =============================================================================

ITEM_TABLE_RECORD_FORMAT: Final = "<20sIHHb?2x"
# 20 bytes name (ASCII NUL-padded), price u32, merit u16, sort u16,
# color i8, dropable bool, 2 padding bytes -> 32 bytes total.
ITEM_TABLE_RECORD_SIZE: Final = struct.calcsize(ITEM_TABLE_RECORD_FORMAT)
assert ITEM_TABLE_RECORD_SIZE == 32, ITEM_TABLE_RECORD_SIZE

ITEM_TABLE_ENTRY_COUNT: Final = 128


class ItemProps(NamedTuple):
    """Per-id ITEM_PARA properties used for pool filtering.

    Fields matched to meekrhino's ``Item`` instance attrs:
    ``price`` -> ``self.price``, ``sort`` -> ``self.sort``,
    ``dropable`` -> ``self.dropable``. Name is omitted; the shuffle is
    deterministic without it.
    """

    item_id: int
    price: int
    sort: int
    dropable: bool

    @property
    def is_food(self) -> bool:
        return self.sort == SORT_FOOD or self.item_id in FOOD_EXCEPTION_ITEM_IDS

    @property
    def is_evo(self) -> bool:
        return self.sort == SORT_STATEVO and self.item_id >= EVO_ITEM_MIN_ID

    @property
    def is_consumable(self) -> bool:
        return self.item_id in CONSUMABLE_ITEM_IDS

    @property
    def is_banned(self) -> bool:
        return self.item_id in BANNED_ITEM_IDS


def parse_item_table(table_user_data: bytes) -> list[ItemProps]:
    """Parse the 4 KiB of ITEM_PARA user data into a per-id property list.

    Caller is responsible for first running
    :func:`worlds.digimon_world.data.addresses.read_item_table_user_data`
    to extract the user-data bytes from the raw BIN (since ITEM_PARA
    straddles sector boundaries).
    """

    expected = ITEM_TABLE_ENTRY_COUNT * ITEM_TABLE_RECORD_SIZE
    if len(table_user_data) != expected:
        raise ValueError(
            f"item table user data must be {expected} bytes, got {len(table_user_data)}",
        )
    items: list[ItemProps] = []
    for i in range(ITEM_TABLE_ENTRY_COUNT):
        rec = table_user_data[
            i * ITEM_TABLE_RECORD_SIZE:(i + 1) * ITEM_TABLE_RECORD_SIZE
        ]
        _name, price, _merit, sort, _color, dropable = struct.unpack(
            ITEM_TABLE_RECORD_FORMAT, rec,
        )
        items.append(
            ItemProps(
                item_id=i,
                price=int(price),
                sort=int(sort),
                dropable=bool(dropable),
            ),
        )
    return items


# =============================================================================
# Pool selection
# =============================================================================

def eligible_replacement_ids(
    items: list[ItemProps],
    *,
    vanilla: ItemProps,
    food_only: bool,
    match_value: bool,
    value_cutoff: int,
) -> list[int]:
    """Return the list of item ids eligible to replace ``vanilla``.

    Mirrors meekrhino's ``_getRandomItem`` for the map-item context:
    ``consumableOnly=True``, ``notEvo=True``, ``notQuest=True`` (i.e.
    must be ``dropable``), plus the optional ``foodOnly`` /
    ``matchValueOf`` constraints exposed as YAML options.

    ``food_only`` only fires when the **vanilla** item at the spot is
    itself food — same conditional as meekrhino's
    ``fo = foodOnly and self.itemData[id].isFood``. So a non-food
    vanilla can still be replaced with any consumable.
    """

    fo = food_only and vanilla.is_food
    candidates: list[int] = []
    for it in items:
        if it.is_banned:
            continue
        if not it.is_consumable:
            continue
        if it.is_evo:
            continue
        if not it.dropable:  # meekrhino's notQuest filter
            continue
        if fo and not it.is_food:
            continue
        if match_value and (it.price < value_cutoff) != (vanilla.price < value_cutoff):
            continue
        candidates.append(it.item_id)
    return candidates


# =============================================================================
# Apply-time shuffle entry point
# =============================================================================

def compute_ground_item_replacements(
    rom: bytes,
    *,
    random: Random,
    food_only: bool,
    match_value: bool,
    value_cutoff: int,
    map_item_offsets: tuple[int, ...],
    item_table_user_data: bytes,
) -> dict[int, int]:
    """Compute per-offset replacement item ids for every ground-item spot.

    For each offset in ``map_item_offsets``, reads the vanilla item id
    from ``rom[offset + 1]`` (byte 0 is the ``spawnItem`` opcode 0x74,
    byte 1 is the item id), builds the candidate pool with
    :func:`eligible_replacement_ids`, and picks one uniformly via
    ``random.choice``.

    Iteration order over ``map_item_offsets`` is the iteration order of
    the input tuple; pair with a deterministically-seeded :class:`Random`
    for reproducibility.

    Returns a mapping ``offset -> new_item_id``. Caller writes the new
    id at ``offset + 1`` (preserving the opcode byte).
    """

    items = parse_item_table(item_table_user_data)
    replacements: dict[int, int] = {}
    for offset in map_item_offsets:
        vanilla_id = rom[offset + 1]
        if vanilla_id >= ITEM_TABLE_ENTRY_COUNT:
            continue  # shouldn't happen on canonical ROM
        vanilla = items[vanilla_id]
        candidates = eligible_replacement_ids(
            items,
            vanilla=vanilla,
            food_only=food_only,
            match_value=match_value,
            value_cutoff=value_cutoff,
        )
        if not candidates:
            continue  # filter is so tight nothing fits — skip this spot
        replacements[offset] = random.choice(candidates)
    return replacements


__all__ = [
    "BANNED_ITEM_IDS",
    "CONSUMABLE_ITEM_IDS",
    "EVO_ITEM_MIN_ID",
    "FOOD_EXCEPTION_ITEM_IDS",
    "ITEM_TABLE_ENTRY_COUNT",
    "ITEM_TABLE_RECORD_FORMAT",
    "ITEM_TABLE_RECORD_SIZE",
    "QUEST_ITEM_IDS",
    "SORT_FOOD",
    "SORT_STATEVO",
    "ItemProps",
    "compute_ground_item_replacements",
    "eligible_replacement_ids",
    "parse_item_table",
]
