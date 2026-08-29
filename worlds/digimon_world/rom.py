"""Phase 3 patcher for the Digimon World 1 APWorld.

Architecture (locked Phase 0, see ``architecture_decision.md``): the
patcher follows the FFT Ivalice Island pattern — :class:`APProcedurePatch`
+ :class:`APTokenMixin`, sector-aware Mode2/2352 writes via
:mod:`.data.edc`, single-track ``.cue`` regeneration. The user supplies
their own legal SLUS-01032 dump; the patch is delivered as a small
``.apdw1`` zip containing a token blob.

What v1 actually patches
========================

The Phase 3 v1 deliverable is an **architecturally complete patcher**
that produces a valid Mode2/2352 BIN/CUE. The token list is intentionally
**minimal**: a single 32-byte WRITE to the ISO9660 Primary Volume
Descriptor (PVD) volume identifier, encoding "AP_DIGIMON_WORLD" plus a
seed-name hash. This serves as a **client-side ROM-validation marker** —
the Phase 4 client reads the volume id back via the Lua connector and
confirms it's connected to a seed-matched ROM.

It does **not** yet:

* rewrite chest contents, recruit tables, or DV items;
* install AP-flag scratch regions inside the live save block;
* install function hooks for chest/item-pickup detection.

Those land once their per-byte ROM offsets in
``worlds.digimon_world.data.addresses`` are individually verified. The
manifest is the source of truth — Phase 3 imports geometry constants
from it but writes only to the PVD volume id, which is canonical
ISO9660 (offset 0x9340) and not game data.

Apply-time pipeline
===================

1. User configures ``host.yaml`` ``digimon_world_options.rom_file`` to
   point at their vanilla ``.bin``.
2. Generate produces a ``<seed>.apdw1`` zip containing
   ``token_data.bin`` + ``archipelago.json``.
3. On launch (or via ``Launcher.py <seed>.apdw1``), the launcher routes
   to the BizHawk client (see :mod:`.components`).
4. Patch-apply reads the user's ``.bin``, SHA-1 verifies it against
   :data:`worlds.digimon_world.data.addresses.ROM_BIN_SHA1`, applies
   the token blob, recalculates EDC for changed sectors, writes
   ``<seed>patched.bin`` and ``<seed>.cue`` next to the source.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
from pathlib import Path
from random import Random
from typing import TYPE_CHECKING, ClassVar

import settings
from worlds.Files import APPatchExtension, APProcedurePatch, APTokenMixin, APTokenTypes

from .data import edc
from .data.addresses import (
    AP_CHEST_SENTINEL_ITEM_ID,
    AP_DESC_STRING_MAX_LEN,
    AP_DESC_STRINGS_BIN_OFFSET,
    AP_ICON_CLUT_BIN_OFFSETS,
    AP_ICON_CLUT_INDEX,
    AP_ICON_ID_TABLE_BASE_ITEM_ID,
    AP_ICON_ID_TABLE_DEFAULT_BYTES,
    AP_ICON_ID_TABLE_OFFSET,
    AP_ITEM_DESC_BIN_OFFSET,
    AP_ITEM_DESC_PTR_BIN_OFFSET,
    AP_ITEM_DESC_PTR_VALUE,
    AP_ITEM_DESC_STRING,
    AP_ITEM_ICON_INDEX,
    AP_ITEM_ICON_TILE_BIN_OFFSETS,
    AP_LOGO_CLUT_BYTES,
    AP_LOGO_TILE_ROW_BYTES,
    ARENA_CUP_NEUTER_VALUES,
    ARENA_CUP_PATCH_SITES,
    BOOT_SEED_HOOK_FORMAT,
    BOOT_SEED_HOOK_PATCH_VALUE,
    BOOT_SEED_HOOK_SITE_OFFSET,
    BRAIN_LEARN_ZERO_REPLACEMENT,
    BRAIN_TIER_ONE_LEARN_CHANCE,
    CARD_TRADE_VALUE_CAP,
    CARD_TRADE_VANILLA_VALUES,
    CHEST_NAME_TO_ROM_OFFSETS,
    DIGIMON_DATA_DROP_ITEM_OFFSET,
    DIGIMON_DATA_MOVES_COUNT,
    DIGIMON_DATA_MOVES_OFFSET,
    DIGIMON_DATA_RECORD_SIZE,
    ELEMENT_MATRIX_DIM,
    EVO_GAIN_FORMAT,
    EVO_GAIN_ROW_SIZE,
    EVO_PATH_FORMAT,
    EVO_PATH_ROW_SIZE,
    EVO_REQ_FORMAT,
    EVO_REQ_ROW_SIZE,
    EXT_ITEM_PARA_SEED_BIN_OFFSET,
    EXT_ITEM_PARA_SEED_SIZE,
    FIELD_RECORD_FORMAT,
    FIELD_RECORD_HP,
    FIELD_RECORD_MOVES,
    FIELD_RECORD_STAT_COUNT,
    FIELD_RECORD_TYPE,
    HEAP_CLAIM_WORD_BIN_OFFSET,
    HEAP_CLAIM_WORD_FORMAT,
    HEAP_CLAIM_WORD_PATCHED,
    ITEM_PARA_BOOT_HOOK_BYTES,
    ITEM_PARA_BOOT_HOOK_EXT_BYTES,
    ITEM_PARA_BOOT_HOOK_OFFSET,
    ITEM_PARA_MERIT_VALUE_OFFSET,
    ITEM_PARA_OVERLAY_WORD_PATCHES,
    ITEM_PARA_READER_WORD_PATCHES,
    ITEM_SHOP_AP_ITEM_ID_BASE,
    ITEM_SHOP_AP_ITEM_IDS,
    ITEM_SHOP_LOCATION_NAMES,
    ITEM_TIM_CLUT_SIZE_BYTES,
    LEARN_CHANCE_MULTIPLIER,
    MERIT_AP_DESC_STRINGS_BIN_OFFSET,
    MERIT_SHOP_AP_ITEM_ID_BASE,
    MERIT_SHOP_DISPATCH,
    MERIT_SHOP_LOCATION_NAMES,
    MERIT_SHOP_VANILLA_ENTRIES,
    MOVE_DATA_PATCH_SPAN,
    MOVE_DATA_RECORD_SIZE,
    RAINBOWHORN_ITEM_ID,
    RAINBOWHORN_NEW_CLUT_INDEX,
    RAINBOWHORN_TILE_BIN_OFFSETS,
    RECYCLE_SHOP_AP_ITEM_ID_BASE,
    RECYCLE_SHOP_AP_ITEM_ID_COUNT,
    RECYCLE_SHOP_LOCATION_NAMES,
    RECYCLE_SHOP_VANILLA_PRICES,
    RELOC_ITEM_DESC_PTR_ADDIU_VALUE,
    RELOC_ITEM_DESC_PTR_LUI_VALUE,
    RELOC_ITEM_DESC_PTR_PATCH_FORMAT,
    RELOC_ITEM_DESC_PTR_PATCH_SITES,
    ROM_AMAZING_ROD_HIDE_BYTES,
    ROM_AMAZING_ROD_HIDE_OFFSET,
    ROM_ANIM_ID_FORMAT,
    ROM_AP_ITEM_DESC_PTR_PATCH_FORMAT,
    ROM_AP_ITEM_ENTRY_BYTES,
    ROM_AP_ITEM_ENTRY_OFFSET,
    ROM_AP_SHOP_BOUGHT_ENTRY_BYTES,
    ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET,
    ROM_AP_SHOP_PRESALE_NAME_BYTES,
    ROM_ARENA_SECTION_51_BASES,
    ROM_BIN_BYTES,
    ROM_BIN_SHA1,
    ROM_BIRDRA_FLIGHT_GCANYON_PATCHES,
    ROM_BIRDRA_FLIGHT_PRICE_OFFSETS,
    ROM_BIRDRA_FLIGHT_PRICE_ZERO,
    ROM_BIRDRA_FLIGHT_TABLE_FORMAT,
    ROM_BIRDRA_FLIGHT_TABLE_PATCHES,
    ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE,
    ROM_BLUE_FLUTE_GIVEITEM_OFFSETS,
    ROM_CHANGEMAP_PATCH_FORMAT,
    ROM_CHANGEMAP_PATCH_OFFSET,
    ROM_CHANGEMAP_PATCH_VALUE,
    ROM_CHANGEMAP_WRAPPER_BYTES,
    ROM_CHANGEMAP_WRAPPER_OFFSET,
    ROM_CHECK_MOVE_OFFSETS,
    ROM_CHEST_GIVEITEM_PATCH_FORMAT,
    ROM_CHEST_GIVEITEM_PATCH_OFFSET,
    ROM_CHEST_GIVEITEM_PATCH_VALUE,
    ROM_CHEST_GIVEITEM_WRAPPER_BYTES,
    ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
    ROM_CHEST_ITEM_FORMAT,
    ROM_CITY_BITMAP_BYTES,
    ROM_CITY_BITMAP_OFFSET,
    ROM_COELAMON_CUTSCENE_REMAP_OFFSETS,
    ROM_COELAMON_CUTSCENE_REMAP_VALUE,
    ROM_COELAMON_GATE_OFFSETS,
    ROM_COELAMON_GATE_VALUE,
    ROM_COMBAT_SITE1_FORMAT,
    ROM_COMBAT_SITE1_OFFSET,
    ROM_COMBAT_SITE1_VALUE,
    ROM_COMBAT_SITE2_FORMAT,
    ROM_COMBAT_SITE2_OFFSET,
    ROM_COMBAT_SITE2_VALUE,
    ROM_COMBAT_SITE3_FORMAT,
    ROM_COMBAT_SITE3_OFFSET,
    ROM_COMBAT_SITE3_VALUE,
    ROM_COMBAT_TR1_OFFSET,
    ROM_COMBAT_TR2_OFFSET,
    ROM_COMBAT_TR3_OFFSET,
    ROM_DIGIMON_DATA,
    ROM_DIGIMON_DATA_OFFSET,
    ROM_DIGIMON_ID_FORMAT,
    ROM_DV_CHIP_TEXT_LENGTH,
    ROM_DV_CHIP_TEXT_PATCHES,
    ROM_ELEMENT_MATRIX_OFFSET,
    ROM_EVO_ITEM_STAT_GAIN_FORMAT,
    ROM_EVO_ITEM_STAT_GAIN_OFFSET,
    ROM_EVO_ITEM_STAT_GAIN_VALUE,
    ROM_EVO_REQUIREMENTS,
    ROM_EVO_STAT_GAINS,
    ROM_EVO_TO_FROM,
    ROM_FIELD_SPAWN_TRIGGER_FORMAT,
    ROM_FIELD_SPAWN_TRIGGER_PATCHES,
    ROM_FIX_LEO_CAVE_FORMAT,
    ROM_FIX_LEO_CAVE_OFFSETS,
    ROM_FIX_LEO_CAVE_VALUE,
    ROM_FIX_MOVE_TO_FORMAT,
    ROM_FIX_MOVE_TO_OFFSETS,
    ROM_FIX_MOVE_TO_VALUE,
    ROM_FIX_ROTATION_FORMAT,
    ROM_FIX_ROTATION_OFFSETS,
    ROM_FIX_ROTATION_VALUE,
    ROM_FIX_TOY_TOWN_FORMAT,
    ROM_FIX_TOY_TOWN_OFFSETS,
    ROM_FIX_TOY_TOWN_VALUE,
    ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE,
    ROM_FRIG_KEY_GIVEITEM_OFFSETS,
    ROM_GACHA_MP_FLOPPY_FIX_BYTES,
    ROM_GACHA_MP_FLOPPY_FIX_OFFSET,
    ROM_GEAR_GIVEITEM_NEUTER_VALUE,
    ROM_GEAR_GIVEITEM_OFFSETS,
    ROM_GETTOPCITY_TRIGGER_FORMAT,
    ROM_GETTOPCITY_TRIGGER_PATCHES,
    ROM_GREAT_CANYON_APPROACH_GATE_OFFSETS,
    ROM_GREAT_CANYON_APPROACH_GATE_VALUE,
    ROM_GREAT_CANYON_CUTSCENE_OFFSETS,
    ROM_GREAT_CANYON_CUTSCENE_VALUE,
    ROM_ICON_CLAMP_PATCH_FORMAT,
    ROM_ICON_CLAMP_PATCH_OFFSET,
    ROM_ICON_CLAMP_PATCH_VALUE,
    ROM_ICON_CLAMP_WRAPPER_BYTES,
    ROM_ICON_CLAMP_WRAPPER_OFFSET,
    ROM_ISTRIGGERSET_PATCH_FORMAT,
    ROM_ISTRIGGERSET_PATCH_OFFSET,
    ROM_ISTRIGGERSET_PATCH_VALUE,
    ROM_ISTRIGGERSET_WRAPPER_BYTES,
    ROM_ISTRIGGERSET_WRAPPER_OFFSET,
    ROM_ITEM_DROPABLE_BYTE_OFFSET,
    ROM_ITEM_TABLE_BASE,
    ROM_ITEM_TABLE_ENTRY_SIZE,
    ROM_LAVA_CAVE_GATE_OFFSETS,
    ROM_LAVA_CAVE_GATE_VALUE,
    ROM_LEARN_MOVE_AND_COMMAND_OFFSET,
    ROM_LEARN_MOVE_AND_COMMAND_WORDS,
    ROM_LEARN_MOVE_OFFSETS,
    ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE,
    ROM_LEOMONSTONE_GIVEITEM_OFFSETS,
    ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE,
    ROM_MANSION_KEY_GIVEITEM_OFFSETS,
    ROM_MAP_ITEM_OFFSETS,
    ROM_MERIT_SCAN_BOUND_FORMAT,
    ROM_MERIT_SCAN_BOUND_OFFSET,
    ROM_MERIT_SCAN_BOUND_VALUE,
    ROM_MERIT_SHOP_EXT_PATCH_FORMAT,
    ROM_MERIT_SHOP_EXT_PATCH_VALUE,
    ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
    ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET,
    ROM_MERIT_SHOP_PATCH_FORMAT,
    ROM_MERIT_SHOP_PATCH_OFFSET,
    ROM_MERIT_SHOP_PATCH_VALUE,
    ROM_MERIT_SHOP_WRAPPER_BYTES,
    ROM_MERIT_SHOP_WRAPPER_OFFSET,
    ROM_MOVE_DATA_OFFSET,
    ROM_OGREMON_SOFTLOCK_FORMAT,
    ROM_OGREMON_SOFTLOCK_OFFSETS,
    ROM_OGREMON_SOFTLOCK_VALUE,
    ROM_OLD_FISHROD_REMAP_OFFSETS,
    ROM_OLD_FISHROD_REMAP_VALUE,
    ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS,
    ROM_PIXIMON_MANUAL_NEUTER_VALUE,
    ROM_PROSPERITY_GOAL_FORMAT,
    ROM_PROSPERITY_GOAL_OFFSETS,
    ROM_QUEST_ITEMS_NOT_DROPABLE,
    ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE,
    ROM_RAIN_PLANT_GIVEITEM_OFFSETS,
    ROM_RECRUITMENT,
    ROM_RECRUITMENT_FORMAT,
    ROM_SETTRIGGER_PATCH_FORMAT,
    ROM_SETTRIGGER_PATCH_OFFSET,
    ROM_SETTRIGGER_PATCH_VALUE,
    ROM_SETTRIGGER_WRAPPER_BYTES,
    ROM_SETTRIGGER_WRAPPER_OFFSET,
    ROM_SKIP_INTRO_FORMAT,
    ROM_SKIP_INTRO_INSIDE_DEST,
    ROM_SKIP_INTRO_INSIDE_OFFSET,
    ROM_SKIP_INTRO_OPCODE,
    ROM_SKIP_INTRO_OUTSIDE_DEST,
    ROM_SKIP_INTRO_OUTSIDE_OFFSET,
    ROM_SPAWN_RATE_FORMAT,
    ROM_SPAWN_RATE_MAMEMON_OFFSETS,
    ROM_SPAWN_RATE_MMAMEMON_OFFSETS,
    ROM_SPAWN_RATE_OTAMAMON_OFFSETS,
    ROM_SPAWN_RATE_PIXIMON_OFFSETS,
    ROM_SPECIAL_EVO,
    ROM_SPECIAL_EVO_TOY_TOWN_GATE_OFFSET,
    ROM_STARTER_CHK_DIGIMON,
    ROM_STARTER_EQUIP_ANIM,
    ROM_STARTER_LEARN_TECH,
    ROM_STARTER_SET_DIGIMON,
    ROM_STARTER_STAT_CHK_DIGIMON,
    ROM_TECH_ID_FORMAT,
    ROM_TECH_LEARN_BATTLE,
    ROM_TECH_LEARN_BATTLE_VANILLA,
    ROM_TECH_LEARN_BRAIN,
    ROM_TECH_LEARN_BRAIN_VANILLA,
    ROM_TECHNIQUE_DATA,
    ROM_TOKOMON_ITEM_OFFSETS,
    ROM_TRANSITION_GATE_HOOK_BYTES,
    ROM_TRANSITION_GATE_WRAPPER_BYTES,
    ROM_UNLOCK_GREYLORD_OFFSETS,
    ROM_UNLOCK_GREYLORD_VALUE,
    ROM_UNLOCK_ICE_OFFSETS,
    ROM_UNLOCK_ICE_VALUE,
    ROM_UNLOCK_TOY_TOWN_FORMAT,
    ROM_UNLOCK_TOY_TOWN_OFFSETS,
    ROM_UNLOCK_TOY_TOWN_VALUE,
    ROM_UNLOCK_TYPE_LOCK_FORMAT,
    ROM_UNRIG_SLOTS_WORD_PATCHES,
    SCRIPT_GATE_PATCHES,
    SECRET_SHOP_AP_ITEM_ID_BASE,
    SECRET_SHOP_AP_ITEM_IDS,
    SECRET_SHOP_LOCATION_NAMES,
    SHOP_AP_BUILDER_WRAPPER_BYTES,
    SHOP_AP_BUILDER_WRAPPER_OFFSET,
    SHOP_AP_CONFIG_BIN_OFFSET,
    SHOP_AP_DISPATCHER_JAL_OFFSET,
    SHOP_AP_DISPATCHER_JAL_VALUE,
    SHOP_AP_GIVEITEM_EXT_BYTES,
    SHOP_AP_GIVEITEM_EXT_OFFSET,
    SHOP_AP_GIVEITEM_JAL_OFFSET,
    SHOP_AP_GIVEITEM_JAL_VALUE,
    SHOP_MODE_REPLACE,
    TOKOMON_GIFT_VALUE_OFFSET,
    TRANSITION_GATE_HOOK_OFFSET,
    TRANSITION_GATE_TABLE_OFFSET,
    TRANSITION_GATE_WRAPPER_OFFSET,
    TRN_GYM_BONUS_WORD_PATCHES,
    VENDING_MACHINES,
    _merit_shop_presale_name_offset,
    _table_byte_to_bin_flat,
    build_ap_desc_string,
    build_ap_item_para_entry,
    build_combat_multiplier_trampolines,
    build_shop_ap_config_bytes,
    build_transition_gate_table,
    card_trade_value_bin_offset,
    encode_set_trigger,
    ext_item_para_slot_bin_offset,
    field_record_bin_offset,
    item_clut_data_bin_offset,
    item_shop_tiered_price,
    item_tim_clut_bin_offsets,
    iter_user_data_chunks,
    maphead_bin_offset,
    read_digimon_table_user_data,
    read_item_table_user_data,
    read_technique_table_user_data,
    script_vm_to_bin_offset,
    secret_shop_tiered_price,
)
from .drops import DropPlan
from .enemies import MOVES_BY_ID, RECORD_INDEX, RECORDS_BY_MAP, SITES_BY_MAP, EnemyPlan
from .evolutions import EvolutionPlan
from .gifts import GiftPlan
from .ground_items import compute_ground_item_replacements
from .starters import (
    LEVEL_CHAMPION,
    LEVEL_FRESH,
    LEVEL_IN_TRAINING,
    LEVEL_ROOKIE,
    LEVEL_ULTIMATE,
    parse_digimon_table,
    parse_tech_table,
    pick_starters,
)
from .technique_lists import ListPlan
from .techniques import TechniquePlan

if TYPE_CHECKING:
    from .options import DigimonWorldOptions, ShopModes
    from .world import DigimonWorldWorld


# =============================================================================
# settings.py-backed host.yaml configuration
# =============================================================================
# AP's settings.UserFilePath natively validates against MD5 hashes only.
# The redump SLUS-01032 dump is documented by SHA-1 in our manifest
# (``worlds.digimon_world.data.addresses.ROM_BIN_SHA1``); rather than
# fabricate or guess an MD5, we leave ``md5s = []`` and run our own
# SHA-1 check inside :meth:`DigimonWorldPatchExtension.verify_rom_hash`.
# Effect: the file path comes from host.yaml; the bytes are validated by
# us at patch-apply time.

GAME_NAME: str = "Digimon World"


class DigimonWorldSettings(settings.Group):
    class RomFile(settings.UserFilePath):
        """File name of the Digimon World 1 (USA, SLUS-01032) BIN."""

        description = "Digimon World 1 (USA) BIN file"
        copy_to = "Digimon World (USA).bin"
        # md5s intentionally empty — see module docstring.

    rom_file: RomFile = RomFile(RomFile.copy_to)


# =============================================================================
# PVD volume id write target
# =============================================================================
# ISO9660 Primary Volume Descriptor at sector 16 (0x9300 from BoF). The
# volume identifier sits at PVD offset 40, i.e. 0x9300 + 0x18 (sector
# header) + 0x28 (PVD offset 40) = 0x9340. This is also where FFT writes
# its rom-name string and is canonical for ISO9660 disc images. The
# field is 32 bytes wide; ISO9660 requires d-characters (A-Z, 0-9, _).

VOLUME_ID_OFFSET: int = 0x9340
VOLUME_ID_LENGTH: int = 32
VOLUME_ID_PREFIX: bytes = b"AP_DIGIMON_WORLD_"


def _build_volume_id(seed_name: str) -> bytes:
    """Construct the 32-byte ASCII volume id for a given seed.

    The first 17 bytes are the fixed prefix ``AP_DIGIMON_WORLD_``. The
    remaining 15 bytes carry an uppercase hex digest of the seed name
    so the AP client can recognize a seed-matched dump. ISO9660
    d-characters only (A-Z, 0-9, _).
    """

    digest = hashlib.sha1(seed_name.encode("ascii", errors="replace")).hexdigest().upper()
    suffix = digest[: VOLUME_ID_LENGTH - len(VOLUME_ID_PREFIX)].encode("ascii")
    body = VOLUME_ID_PREFIX + suffix
    if len(body) > VOLUME_ID_LENGTH:
        body = body[:VOLUME_ID_LENGTH]
    return body.ljust(VOLUME_ID_LENGTH, b" ")


# =============================================================================
# Patch extension (apply-time logic)
# =============================================================================
# AP's procedure machinery (see worlds/Files.py:285-361) drives a list of
# named extension methods, each ``(caller, rom, *args) -> bytes``. We
# define one that hash-checks the source bytes and another that recalcs
# EDC after token application.


def _decode_clut15(raw: bytes) -> tuple[tuple[int, int, int], ...]:
    """Decode one 32-byte PSX 15-bit CLUT into 16 RGB888 triples."""

    colors = struct.unpack(f"<{ITEM_TIM_CLUT_SIZE_BYTES // 2}H", raw)
    return tuple(
        ((c & 0x1F) << 3, ((c >> 5) & 0x1F) << 3, ((c >> 10) & 0x1F) << 3)
        for c in colors
    )


def _nearest_clut_index(
    color: tuple[int, int, int],
    palette: tuple[tuple[int, int, int], ...],
) -> int:
    """Nearest palette index by squared RGB distance.

    Index 0 is excluded — it renders fully transparent on PSX
    hardware, so an opaque source pixel must never map to it.
    """

    return min(
        range(1, len(palette)),
        key=lambda i: (
            (color[0] - palette[i][0]) ** 2
            + (color[1] - palette[i][1]) ** 2
            + (color[2] - palette[i][2]) ** 2
        ),
    )


def _requantize_tile_row(
    row: bytes,
    src_palette: tuple[tuple[int, int, int], ...],
    dst_palette: tuple[tuple[int, int, int], ...],
) -> bytes:
    """Re-index one 8-byte 4bpp tile row from ``src_palette`` to the
    nearest colors of ``dst_palette``. Index 0 (transparent) is
    preserved as-is; low nibble = left pixel."""

    out = bytearray()
    for byte in row:
        lo, hi = byte & 0xF, byte >> 4
        lo = 0 if lo == 0 else _nearest_clut_index(src_palette[lo], dst_palette)
        hi = 0 if hi == 0 else _nearest_clut_index(src_palette[hi], dst_palette)
        out.append(lo | (hi << 4))
    return bytes(out)

class DigimonWorldPatchExtension(APPatchExtension):
    game = GAME_NAME

    @staticmethod
    def verify_rom_hash(caller: APProcedurePatch, rom: bytes) -> bytes:
        """SHA-1 verify the user-supplied BIN against the manifest hash.

        Runs first in the procedure list. Raises :class:`ValueError` on
        mismatch — the user almost certainly has the wrong dump
        (NTSC-J / PAL / different region / corrupt copy).
        """

        if len(rom) != ROM_BIN_BYTES:
            raise ValueError(
                f"Source BIN size {len(rom)} bytes does not match the "
                f"canonical SLUS-01032 dump ({ROM_BIN_BYTES} bytes). "
                f"Wrong dump? Multi-track CUE? See "
                f"worlds.digimon_world.data.addresses.ROM_BIN_BYTES.",
            )
        actual = hashlib.sha1(rom).hexdigest().upper()
        if actual != ROM_BIN_SHA1.upper():
            raise ValueError(
                f"Source BIN SHA-1 {actual} does not match the canonical "
                f"SLUS-01032 dump ({ROM_BIN_SHA1}). The user-supplied ROM "
                f"is the wrong dump or has been modified.",
            )
        return rom

    @staticmethod
    def shuffle_ground_items(
        caller: APProcedurePatch, rom: bytes, params_file: str,
    ) -> bytes:
        """Apply the ground-item shuffle at patch-apply time.

        Reads the JSON params blob written by :func:`write_patch`
        (seed, food_only, match_value, value_cutoff), parses ITEM_PARA
        out of the post-token-application ROM, and rewrites the item-id
        byte at every ``ROM_MAP_ITEM_OFFSETS`` entry to a deterministic
        replacement drawn from the constrained pool.

        Runs **after** ``apply_tokens`` so any AP-controlled writes
        (chest sentinels, "AP ITEM" table entry at slot 83, etc.) are
        already applied — but slot 83 is in :data:`BANNED_ITEM_IDS`
        anyway, so it can never be selected as a replacement.
        """

        params = json.loads(caller.get_file(params_file))
        rng = Random(int(params["seed"]))
        table = read_item_table_user_data(rom)
        replacements = compute_ground_item_replacements(
            rom,
            random=rng,
            food_only=bool(params["food_only"]),
            match_value=bool(params["match_value"]),
            value_cutoff=int(params["value_cutoff"]),
            map_item_offsets=ROM_MAP_ITEM_OFFSETS,
            item_table_user_data=table,
        )
        target = bytearray(rom)
        for offset, new_id in replacements.items():
            target[offset + 1] = new_id
        return bytes(target)

    @staticmethod
    def shuffle_starters(
        caller: APProcedurePatch, rom: bytes, params_file: str,
    ) -> bytes:
        """Apply the starter-Digimon shuffle at patch-apply time.

        Reads the JSON params blob (seed, allowed_levels mask, weakest-
        tech flag), parses DIGIMON_PARA + TECH_PARA from the
        post-token-application ROM, picks two distinct starters and
        their first techs via :func:`pick_starters`, and writes the
        nine starter-related bytes per the
        ``ROM_STARTER_*`` offsets in the manifest.

        Skips the write entirely if the eligible pool is too small
        (degenerate level mask) or if the chosen Digimon has no usable
        damaging tech — in those edge cases the vanilla starter bytes
        are preserved and the player gets the unmodified pick screen.
        """

        params = json.loads(caller.get_file(params_file))
        rng = Random(int(params["seed"]))
        allowed_levels: frozenset[int] = frozenset(int(x) for x in params["allowed_levels"])
        use_weakest = bool(params["use_weakest_tech"])

        digimon_user_data = read_digimon_table_user_data(rom)
        tech_user_data = read_technique_table_user_data(rom)
        digimons = parse_digimon_table(digimon_user_data, ROM_DIGIMON_DATA.count)
        techs = parse_tech_table(tech_user_data, ROM_TECHNIQUE_DATA.count)

        picks = pick_starters(
            digimons, techs,
            random=rng,
            allowed_levels=allowed_levels,
            use_weakest_tech=use_weakest,
        )
        if picks is None:
            return rom  # eligible pool too small — keep vanilla starters

        target = bytearray(rom)
        for slot_index, assignment in enumerate(picks):
            target[ROM_STARTER_SET_DIGIMON[slot_index]] = (
                struct.pack(ROM_DIGIMON_ID_FORMAT, assignment.digimon_id)[0]
            )
            target[ROM_STARTER_CHK_DIGIMON[slot_index]] = (
                struct.pack(ROM_DIGIMON_ID_FORMAT, assignment.digimon_id)[0]
            )
            if assignment.tech_id is not None and assignment.anim_id is not None:
                target[ROM_STARTER_LEARN_TECH[slot_index]] = (
                    struct.pack(ROM_TECH_ID_FORMAT, assignment.tech_id)[0]
                )
                target[ROM_STARTER_EQUIP_ANIM[slot_index]] = (
                    struct.pack(ROM_ANIM_ID_FORMAT, assignment.anim_id)[0]
                )
        # The shared post-pick id-check site uses slot 0's Digimon id,
        # mirroring the standalone (``starterStatChkDigimonOffset`` is
        # only updated for slot 0).
        target[ROM_STARTER_STAT_CHK_DIGIMON] = (
            struct.pack(ROM_DIGIMON_ID_FORMAT, picks[0].digimon_id)[0]
        )
        return bytes(target)

    @staticmethod
    def relocate_item_desc_ptr(caller: APProcedurePatch, rom: bytes) -> bytes:
        """Build the relocated ITEM_DESC_PTR table in Cave6.

        Runs when any of the four shopsanity shop options (recycle /
        merit / item / secret) is not ``off`` — see
        :func:`_assemble_procedure`.

        Reads the 128 vanilla u32 pointer entries from the **original
        source ROM** (via :meth:`get_source_data_with_cache` — the
        shopsanity wrappers overwrite the vanilla desc-ptr .bin region,
        so reading the pristine source is mandatory now, not just
        simpler). Writes them as slots 0..127 of the relocated
        256-entry table at :data:`RELOC_ITEM_DESC_PTR_BIN_OFFSET`.
        Slots 128..134 are overwritten with kuseg pointers into the 7
        recycle-shop AP description strings (region
        :data:`AP_DESC_STRINGS_RAM`); slots 135..148 with kuseg
        pointers into the 14 merit-shop AP description strings (region
        :data:`MERIT_AP_DESC_STRINGS_RAM`); slots 149..185 (item +
        secret shop, shopsanity) with the always-on generic
        "Item from the multiworld" string pointer (no Cave6 space is
        left for 37 more per-slot strings — the lab shipped the same
        generic-pointer decision). Slots 186..255 stay zero.

        If a given shop's option is off, ``apply_tokens`` will not have
        written description bytes into that region — but the slots'
        ITEM_PARA entries also have ``meritValue=0`` (no patcher write),
        so the shop's scan never includes those slots and the
        renderer never dereferences the stale pointers. Safe to
        populate unconditionally.

        Sector-aware on both read and write — the table spans multiple
        Mode2/2352 user-data regions.
        """

        from .data.addresses import (
            AP_DESC_STRING_MAX_LEN,
            AP_DESC_STRINGS_RAM,
            MERIT_AP_DESC_STRINGS_RAM,
            MERIT_SHOP_AP_ITEM_ID_BASE,
            MERIT_SHOP_AP_ITEM_ID_COUNT,
            RECYCLE_SHOP_AP_ITEM_ID_COUNT,
            RELOC_ITEM_DESC_PTR_BIN_OFFSET,
            RELOC_ITEM_DESC_PTR_SIZE,
            VANILLA_ITEM_DESC_PTR_BIN_OFFSET,
            VANILLA_ITEM_DESC_PTR_ENTRIES,
            read_user_data_bytes,
            write_user_data_bytes,
        )

        base_data = caller.get_source_data_with_cache()
        vanilla_bytes = read_user_data_bytes(
            base_data,
            VANILLA_ITEM_DESC_PTR_BIN_OFFSET,
            VANILLA_ITEM_DESC_PTR_ENTRIES * 4,
        )

        table = bytearray(RELOC_ITEM_DESC_PTR_SIZE)
        table[:len(vanilla_bytes)] = vanilla_bytes

        # Recycle-shop AP slots: 128..134 → AP_DESC_STRINGS_RAM region.
        ap_desc_kuseg_base = 0x80000000 | AP_DESC_STRINGS_RAM
        first_ap_slot = VANILLA_ITEM_DESC_PTR_ENTRIES
        for i in range(RECYCLE_SHOP_AP_ITEM_ID_COUNT):
            ptr = ap_desc_kuseg_base + i * AP_DESC_STRING_MAX_LEN
            struct.pack_into("<I", table, (first_ap_slot + i) * 4, ptr)

        # Merit-shop AP slots: 135..148 → MERIT_AP_DESC_STRINGS_RAM region.
        merit_desc_kuseg_base = 0x80000000 | MERIT_AP_DESC_STRINGS_RAM
        for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT):
            ptr = merit_desc_kuseg_base + i * AP_DESC_STRING_MAX_LEN
            slot = MERIT_SHOP_AP_ITEM_ID_BASE + i
            struct.pack_into("<I", table, slot * 4, ptr)

        # Shopsanity slots 149..185 (item + secret shop) → the always-on
        # generic "Item from the multiworld" string. The hover panel of
        # every item/secret AP row reads this one shared string.
        from .data.addresses import AP_ITEM_DESC_RAM
        generic_ptr = 0x80000000 | AP_ITEM_DESC_RAM
        for slot in (*ITEM_SHOP_AP_ITEM_IDS, *SECRET_SHOP_AP_ITEM_IDS):
            struct.pack_into("<I", table, slot * 4, generic_ptr)

        target = bytearray(rom)
        write_user_data_bytes(
            target, RELOC_ITEM_DESC_PTR_BIN_OFFSET, bytes(table),
        )
        return bytes(target)

    @staticmethod
    def requantize_rainbowhorn(caller: APProcedurePatch, rom: bytes) -> bytes:
        """Re-index Rainbowhorn's ITEM.TIM tile from CLUT 22 to CLUT 8.

        Always-on companion of the AP logo icon (see
        :func:`_write_merit_shop_wrapper_tokens` step 7): the token pass
        rewrites CLUT 22 with the AP palette and repoints
        ``ITEM_CLUT_DATA[84]`` at CLUT 8, so Rainbowhorn's pixels must
        be re-indexed against CLUT 8's colors or the horn would render
        in the AP palette's hues. The tile is game data, so it cannot
        ship inside the token blob — instead this step reads the
        pristine tile and both vanilla CLUTs from the **source** ROM
        (:meth:`~worlds.Files.APProcedurePatch.get_source_data_with_cache`)
        and maps every opaque pixel to CLUT 8's nearest color
        (transparent index 0 is preserved). CLUT 8 is the
        least-error vanilla substitute for the horn's gold/khaki tones
        (quantization survey 2026-08-21).

        Runs after ``apply_tokens``; the touched offsets (tile 84's 16
        rows) are disjoint from every token write, so relative order
        does not actually matter.
        """

        source = caller.get_source_data_with_cache()
        target = bytearray(rom)
        # Both on-disc TIM copies are patched; the vanilla CLUTs are
        # byte-identical between them but each copy's tile is read and
        # rewritten with its own copy's palettes for robustness.
        for copy_index, tile_rows in enumerate(RAINBOWHORN_TILE_BIN_OFFSETS):
            src_off = item_tim_clut_bin_offsets(AP_ICON_CLUT_INDEX)[copy_index]
            dst_off = item_tim_clut_bin_offsets(
                RAINBOWHORN_NEW_CLUT_INDEX,
            )[copy_index]
            src_palette = _decode_clut15(         # vanilla CLUT 22
                source[src_off:src_off + ITEM_TIM_CLUT_SIZE_BYTES],
            )
            dst_palette = _decode_clut15(         # vanilla CLUT 8
                source[dst_off:dst_off + ITEM_TIM_CLUT_SIZE_BYTES],
            )

            for offset in tile_rows:
                target[offset:offset + 8] = _requantize_tile_row(
                    source[offset:offset + 8], src_palette, dst_palette,
                )
        return bytes(target)

    @staticmethod
    def recalc_edc(caller: APProcedurePatch, rom: bytes) -> bytes:
        """Run a sector-diff EDC/ECC recalc against the original source.

        ``rom`` here is the post-token-write data. We pull the cached
        original via :meth:`APProcedurePatch.get_source_data_with_cache`
        and recompute EDC/ECC only for sectors that actually changed.
        The first 16 sectors (ISO9660 system area) are never touched —
        per the SOTN/FFT convention.
        """

        base_data = caller.get_source_data_with_cache()
        target = bytearray(rom)
        edc.diff_recalc_in_place(target, base_data, calc_form_2_edc=False)
        return bytes(target)


# =============================================================================
# The patcher itself
# =============================================================================

def _get_base_rom_as_bytes() -> bytes:
    rom_path = DigimonWorldSettings().rom_file
    with open(rom_path, "rb") as infile:
        return infile.read()


class DigimonWorldProcedurePatch(APProcedurePatch, APTokenMixin):
    """The ``.apdw1`` patch produced by :meth:`DigimonWorldWorld.generate_output`.

    Procedure (in order):

    1. ``verify_rom_hash`` — SHA-1 check the source BIN matches the
       canonical SLUS-01032 dump.
    2. ``apply_tokens`` — built-in extension that walks the token blob
       and applies WRITE/COPY/RLE/AND/OR/XOR tokens.
    3. ``requantize_rainbowhorn`` — always-on companion of the AP logo
       icon: re-indexes Rainbowhorn's ITEM.TIM tile (game data, read
       from the source ROM at apply time) against CLUT 8 after the
       token pass rewrote its vanilla CLUT 22 with the AP palette.
    4. ``shuffle_ground_items`` — *optional, per-instance.* Inserted by
       :func:`_assemble_procedure` when the
       :class:`worlds.digimon_world.options.GroundItemRandomization`
       option is on. Reads ``ground_items.json`` for seed and pool
       scope flags, parses ITEM_PARA, rewrites every map-spawn item-id
       byte. Defaults to absent — vanilla ground items unchanged.
    5. ``shuffle_starters`` — *optional, per-instance.* Inserted by
       :func:`_assemble_procedure` when the
       :class:`worlds.digimon_world.options.StarterRandomization`
       option is on. Reads ``starters.json``, parses
       DIGIMON_PARA + TECH_PARA, rewrites the two starter slots'
       Digimon ids and learn-tech / equip-anim bytes.
    6. ``recalc_edc`` — diff-recalc EDC/ECC for any sector whose data
       was touched.
    """

    game: ClassVar[str] = GAME_NAME
    hash = ROM_BIN_SHA1
    patch_file_ending = ".apdw1"
    result_file_ending = ".cue"

    procedure: ClassVar[list[tuple[str, list[str]]]] = [
        ("verify_rom_hash", []),
        ("apply_tokens", ["token_data.bin"]),
        ("requantize_rainbowhorn", []),
        ("recalc_edc", []),
    ]

    @classmethod
    def get_source_data(cls) -> bytes:
        return _get_base_rom_as_bytes()

    def patch(self, target: str) -> None:
        """Apply the patch. Writes ``<base>patched.bin`` + ``<base>.cue``.

        Procedure-driven super().patch() writes a single file at
        ``target``; our overrides rename it to the conventional
        ``<base>patched.bin`` and emit the matching ``.cue``. This
        mirrors FFT's pattern.
        """

        target_path = Path(target)
        base = target_path.with_suffix("")
        bin_path = base.with_name(base.name + "patched").with_suffix(".bin")
        cue_path = base.with_suffix(".cue")

        for stale in (bin_path, cue_path):
            if stale.exists():
                stale.unlink()

        super().patch(str(target_path))
        os.rename(target_path, bin_path)

        cue_text = (
            f'FILE "{bin_path.name}" BINARY\n'
            f'  TRACK 01 MODE2/2352\n'
            f'    INDEX 01 00:00:00\n'
        )
        cue_path.write_text(cue_text, encoding="ascii")


# =============================================================================
# Generation-time helpers (called from write_patch)
# =============================================================================

def _write_recruit_trigger_redirect_tokens(
    patch: DigimonWorldProcedurePatch,
) -> None:
    """Uniformly redirect every script-bytecode reference to a recruit's
    trigger ID (200+digimon_id) onto the corresponding "beaten" trigger
    (720+digimon_id).

    Why: vanilla DW1 reuses the recruit-completion trigger bit at multiple
    sites in script bytecode — the wild-spawn gate ("if trigger(204) ==
    true then skip loadDigimon"), the in-city presence checks ("if NPC
    Betamon is recruited, walk around in city"), the Jijimon dialog
    "have you recruited X" check, and the post-fight ``setTrigger(204)``
    call itself. Without this redirect, AP item delivery of "Betamon
    Recruit" — which writes bit 204 directly — would also flip the
    wild-spawn gate, blocking the fight from ever spawning and thus
    preventing the Betamon AP location from firing.

    Mechanism: rewrite the 2-byte trigger ID at every offset in
    :data:`ROM_RECRUITMENT.trigger_offsets` (the standalone DW1
    randomizer's catalogue of trigger references in script bytecode)
    from ``200+digimon_id`` to ``720+digimon_id``. Net effect on each
    Digimon's script-side semantics:

    * Wild-spawn gate now reads bit 720+id → set only after the player
      actually fights (via the setTrigger wrapper redirecting vanilla's
      post-fight ``setTrigger(200+id)`` to ``setTrigger(720+id)``). AP
      delivery doesn't block wild spawn.
    * In-city presence and dialog checks also redirect to bit 720+id →
      set only after fight; AP delivery has no script-side effect for
      these 40 Digimon. (The 6 with hardcoded compiled-C in-city checks
      — Agumon at 203, Monzaemon at 214, Angemon at 220, Birdramon at
      221, Vegimon at 225, Palmon at 246 — are unaffected by this
      redirect because their checks are in C code, not script bytecode.
      For those 6, AP delivery of the Recruit item still drives in-city
      visibility.)

    Total writes: 642 small ``<H`` writes (40 Digimon, ~16 offsets
    each on average) per generated patch.
    """

    for entry in ROM_RECRUITMENT:
        if not entry.trigger_offsets:
            continue
        beaten_trigger_id = 720 + entry.digimon_id
        trigger_bytes = struct.pack(ROM_RECRUITMENT_FORMAT, beaten_trigger_id)
        for offset in entry.trigger_offsets:
            patch.write_token(APTokenTypes.WRITE, offset, trigger_bytes)


def _write_settrigger_wrapper_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """**DEPRECATED 2026-05-28 -- NOT CALLED BY THE ACTIVE PATCHER.**

    Do NOT reason about this function as if it were live. It is not in
    :meth:`DigimonWorldProcedurePatch.patch`'s call list and the active
    recruit-bit strategy does not depend on a setTrigger wrapper.

    The current active strategy: ``_write_recruit_trigger_redirect_tokens``
    rewrites bytecode-level ``trigger(200+X)`` references to
    ``trigger(720+X)`` directly via the per-Digimon offset table
    :data:`ROM_RECRUITMENT`. No MIPS-level wrapper is installed.

    Multiple debugging sessions have mistaken this function for live
    code and gone down dead-end investigations. Treat as historical
    reference for an earlier design attempt; safe to delete in a
    future cleanup pass.

    Original design notes follow.

    ---

    Install the setTrigger filter wrapper for the recruit split.

    Two parts:

    1. **Wrapper body** at :data:`ROM_SETTRIGGER_WRAPPER_OFFSET` (32
       bytes / 8 MIPS instructions inside SydPatches' Cave6 free-space
       region, immediately after the chest-pickup wrapper). Filters the
       caller's ``a0`` (trigger ID): if in the recruit range 203..258,
       adds 520 to redirect the bit-set into the unused 723..778
       "beaten" range.
    2. **Patch site** at :data:`ROM_SETTRIGGER_PATCH_OFFSET` (8 bytes
       at the vanilla setTrigger function entry, RAM 0x801065c0):
       replace the first two instructions (frame setup + ``sw $ra``)
       with ``j wrapper`` + ``nop``. The wrapper replicates these two
       instructions before jumping back into setTrigger+8.

    Net effect: every code path that would have set a "Digimon X joined
    city" bit (200+i) now instead sets the corresponding "beaten in
    fight" bit (723+i). Vanilla join-city behavior (PP recompute,
    in-city model spawn, etc.) is suppressed — those checks read the
    recruit bit which stays 0 until the AP client writes it directly
    (bypassing the wrapper) on receipt of the matching AP item.
    """

    patch.write_token(
        APTokenTypes.WRITE,
        ROM_SETTRIGGER_WRAPPER_OFFSET,
        ROM_SETTRIGGER_WRAPPER_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_SETTRIGGER_PATCH_OFFSET,
        struct.pack(ROM_SETTRIGGER_PATCH_FORMAT, *ROM_SETTRIGGER_PATCH_VALUE),
    )


def _write_chest_item_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
) -> None:
    """Write the per-chest item byte for every chest.

    Three parts:

    1. **Per-chest item byte.** For each chest's ``spawnChest`` script
       entry (opcode 0x75 + 1-byte item ID), overwrite the item-ID
       byte. The byte comes from ``world.chest_grants`` — either a real
       DW1 internal item id (the chest hands the player that item
       directly via vanilla flow), or
       :data:`AP_CHEST_SENTINEL_ITEM_ID` (vanilla shows "AP ITEM" and
       the chest-pickup wrapper short-circuits the inventory write).
       Chests with multiple ``spawnChest`` placements (Drill Tunnel 3
       has four; six other chests have two) get the same byte at every
       placement so all branches spawn the same item.
    2. **AP ITEM table entry.** A clean 32-byte item-table entry for
       id 129 with the name "AP ITEM", so the chest pickup textbox
       renders cleanly instead of displaying garbage glyphs from
       random adjacent memory.
    3. **Chest-pickup giveItem wrapper.** A 28-byte sentinel-aware
       ``giveItem`` wrapper installed at SydPatches' Cave6 free-space
       region, plus a single ``jal``-target rewrite at the chest
       pickup callsite. Net effect: chests with the AP sentinel byte
       show "AP ITEM", flip the chest's "taken" state, but write
       nothing to the player's inventory; chests with a real item
       behave entirely as in vanilla.
    """

    item_format = ROM_CHEST_ITEM_FORMAT[-1]  # ``B`` — leading ``<`` is for multi-byte
    chest_grants = world.chest_grants
    for chest_name, offsets in CHEST_NAME_TO_ROM_OFFSETS.items():
        grant = chest_grants.get(chest_name)
        item_id = grant.item_byte if grant is not None else AP_CHEST_SENTINEL_ITEM_ID
        item_byte = struct.pack(f"<{item_format}", item_id)
        for offset in offsets:
            patch.write_token(APTokenTypes.WRITE, offset + 1, item_byte)

    # Write our 32-byte "AP ITEM" entry at the sentinel's slot in
    # ITEM_PARA (slot 83 = vanilla "Electo ring", confirmed unused /
    # gamebreaking). Slot 83 sits well inside ITEM_PARA's 128-entry
    # bound, so this write does NOT spill into the adjacent
    # ITEM_DESC_PTR region — that was the slot-129 bug fixed
    # 2026-04-29 by relocating the sentinel from 0x81 to 0x53.
    patch.write_token(
        APTokenTypes.WRITE, ROM_AP_ITEM_ENTRY_OFFSET, ROM_AP_ITEM_ENTRY_BYTES,
    )

    # Install the chestGiveItem wrapper into Cave6 and redirect the
    # chest-pickup ``jal giveItem`` to call it. The wrapper short-
    # circuits when the chest item byte is the AP sentinel; otherwise
    # it tail-calls vanilla giveItem unchanged.
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
        ROM_CHEST_GIVEITEM_WRAPPER_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_CHEST_GIVEITEM_PATCH_OFFSET,
        struct.pack(ROM_CHEST_GIVEITEM_PATCH_FORMAT, ROM_CHEST_GIVEITEM_PATCH_VALUE),
    )


def _write_changemap_wrapper_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """**DEPRECATED 2026-05-28 -- NOT CALLED BY THE ACTIVE PATCHER.**

    Do NOT reason about this function as if it were live. It is not in
    :meth:`DigimonWorldProcedurePatch.patch`'s call list. The active
    recruit-bit redirect happens at bytecode patch time via
    ``_write_recruit_trigger_redirect_tokens``; there is no AP_BITS_MIRROR
    propagation step at screen transition time.

    Multiple debugging sessions have read this function and assumed
    AP_BITS_MIRROR (at RAM ``0x801BDFF0``) is part of the live wire-
    up -- it is not. The arena enforcer (2026-05-28) has since
    repurposed that RAM region for its own snapshot slot
    (:data:`ARENA_ENFORCER_SNAPSHOT_BASE`), confirming the wrapper is
    not in play.

    Safe to delete in a future cleanup pass.

    Original design notes follow.

    ---

    Install the changeMap wrapper for race-free city/field bit sync.

    Three writes:

    1. **Wrapper body** at :data:`ROM_CHANGEMAP_WRAPPER_OFFSET` (80 bytes
       / 20 MIPS instructions in Cave6 free-space). Reads the destination
       map id from ``$a0``, looks it up in the city bitmap, and copies
       either the AP-bits mirror (in city) or the permanent-beaten
       scratch (in field) into the recruit byte block. Then tail-calls
       vanilla's screen-change function at RAM ``0x800D8E64``.
    2. **City bitmap** at :data:`ROM_CITY_BITMAP_OFFSET` (32 bytes,
       immediately after the wrapper). Bit ``i`` of byte ``i//8`` is set
       iff screen id ``i`` is a city screen.
    3. **JAL redirect** at :data:`ROM_CHANGEMAP_PATCH_OFFSET` (4 bytes
       at vanilla RAM ``0x80105C2C``): replace the vanilla
       ``JAL 0x800D8E64`` with ``JAL ROM_CHANGEMAP_WRAPPER_RAM``.

    Net effect: every screen transition runs our wrapper just before
    vanilla loads the new map's scripts. Scripts then read recruit
    bits that already reflect the destination's correct AP/beaten
    state — no race window like the per-tick client toggle has.
    """

    patch.write_token(
        APTokenTypes.WRITE,
        ROM_CHANGEMAP_WRAPPER_OFFSET,
        ROM_CHANGEMAP_WRAPPER_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_CITY_BITMAP_OFFSET,
        ROM_CITY_BITMAP_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_CHANGEMAP_PATCH_OFFSET,
        struct.pack(ROM_CHANGEMAP_PATCH_FORMAT, ROM_CHANGEMAP_PATCH_VALUE),
    )


def _write_gettopcity_trigger_patches(patch: DigimonWorldProcedurePatch) -> None:
    """Rewrite trigger IDs inside vanilla ``getFileCityTopMap``.

    The function (RAM 0x800D97DC) chooses which File City Top variant
    to load based on which Digimon are recruited. Without patching,
    cutscene-completed Digimon (bit 200+X = 1) get added to the plaza
    regardless of AP delivery. Each call reads
    ``isTriggerSet(200+X)`` via an ``addiu r4, r0, <trigger_id>``
    delay-slot instruction; we rewrite the 16-bit immediate field
    from ``200+X`` to ``720+X`` so the C function reads the
    AP-delivered bit instead of the recruit bit.
    """

    for bin_offset, _expected_old, new_trigger in ROM_GETTOPCITY_TRIGGER_PATCHES:
        patch.write_token(
            APTokenTypes.WRITE,
            bin_offset,
            struct.pack(ROM_GETTOPCITY_TRIGGER_FORMAT, new_trigger),
        )


def _write_field_spawn_trigger_patches(patch: DigimonWorldProcedurePatch) -> None:
    """Rewrite per-Digimon field-spawn trigger IDs from 200+X to 720+X.

    Vanilla DW1 gates each Digimon's wild-spawn on
    ``if trigger(200+X) == TRUE then SKIP loadDigimon``, where reading
    trigger 200+X reads the recruit-block. With the changeMap wrapper
    now writing AP_MIRROR (only) to the recruit-block, trigger 200+X
    reflects AP-delivered status, not beaten status — so the field
    check would let beaten-but-not-AP-delivered Digimon respawn.

    This patch rewrites the 16-bit trigger ID bytes inline in the
    script bytecode for each Digimon's wild-spawn check, redirecting
    them to read trigger 720+X (= PERM_BEATEN range, written by the
    setTrigger wrapper after a recruit-completion event). Net effect:
    field-spawn suppression is decoupled from city visibility. Each
    can be driven by its own state.
    """

    for bin_offset, expected_old, new_trigger in ROM_FIELD_SPAWN_TRIGGER_PATCHES:
        del expected_old  # documented for review; the new bytes overwrite
        patch.write_token(
            APTokenTypes.WRITE,
            bin_offset,
            struct.pack(ROM_FIELD_SPAWN_TRIGGER_FORMAT, new_trigger),
        )


def _write_istriggerset_wrapper_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """**DEPRECATED 2026-05-28 -- NOT CALLED BY THE ACTIVE PATCHER.**

    Do NOT reason about this function as if it were live. It is not in
    :meth:`DigimonWorldProcedurePatch.patch`'s call list. Compiled-C
    callers of vanilla ``isTriggerSet`` are NOT redirected via a MIPS
    wrapper. The active recruit-bit strategy redirects at bytecode
    level only (``_write_recruit_trigger_redirect_tokens``), and the
    arena edge case is handled by a client-side enforcer
    (:meth:`DigimonWorldClient._reconcile_arena_enforcer`).

    Multiple debugging sessions have walked through this function and
    assumed ``AP_BITS_MIRROR`` (at RAM ``0x801BDFF0``) is populated and
    read at runtime -- it is not. The mirror was a previous design
    that did not ship.

    Safe to delete in a future cleanup pass.

    Original design notes follow.

    ---

    Install the isTriggerSet wrapper that redirects recruit-bit reads.

    Two writes:

    1. **Wrapper body** at :data:`ROM_ISTRIGGERSET_WRAPPER_OFFSET` (80
       bytes / 20 MIPS instructions in Cave6 free-space, immediately
       after the changeMap wrapper's debug scratch). For trigger IDs
       in the recruit range 203..258, returns the bit at the matching
       offset of ``AP_BITS_MIRROR`` (0x801BDFF0). For any other trigger
       ID, replicates the two replaced instructions (stack-frame setup
       and ``sw $ra``) and jumps to vanilla ``isTriggerSet+8``.
    2. **Patch site** at :data:`ROM_ISTRIGGERSET_PATCH_OFFSET` (8 bytes
       at vanilla ``isTriggerSet`` entry, RAM 0x8010643C): replace the
       first two instructions with ``j wrapper`` + ``nop``.

    Net effect: every vanilla "is X recruited?" query (variant
    selectors, NPC visibility checks, prosperity recompute, etc.) sees
    the AP-authorized answer regardless of the recruit-block scratch
    contents at the moment of the call. This decouples the recruit-bit
    READ semantics (= AP-delivered) from the recruit-block scratch use
    by the changeMap wrapper for field-spawn suppression (= PERM_BEATEN).
    """

    patch.write_token(
        APTokenTypes.WRITE,
        ROM_ISTRIGGERSET_WRAPPER_OFFSET,
        ROM_ISTRIGGERSET_WRAPPER_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_ISTRIGGERSET_PATCH_OFFSET,
        struct.pack(
            ROM_ISTRIGGERSET_PATCH_FORMAT, *ROM_ISTRIGGERSET_PATCH_VALUE,
        ),
    )


def _write_softlock_fix_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Emit the standalone's softlock fix patches.

    Five small ROM patches that prevent specific encounter-order
    softlocks involving Whamon, Drimogemon, Ogremon, and Nanimon.
    Source:
    ``references/digimon_world_randomizer/digimon/data.py:715-733``.
    Applying them unconditionally lets all four Digimon participate in
    the AP location pool.
    """

    fix_rotation = struct.pack(ROM_FIX_ROTATION_FORMAT, ROM_FIX_ROTATION_VALUE)
    for offset in ROM_FIX_ROTATION_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, fix_rotation)

    fix_move_to = struct.pack(ROM_FIX_MOVE_TO_FORMAT, ROM_FIX_MOVE_TO_VALUE)
    for offset in ROM_FIX_MOVE_TO_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, fix_move_to)

    fix_toy_town = struct.pack(ROM_FIX_TOY_TOWN_FORMAT, ROM_FIX_TOY_TOWN_VALUE)
    for offset in ROM_FIX_TOY_TOWN_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, fix_toy_town)

    fix_leo_cave = struct.pack(ROM_FIX_LEO_CAVE_FORMAT, ROM_FIX_LEO_CAVE_VALUE)
    for offset in ROM_FIX_LEO_CAVE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, fix_leo_cave)

    fix_ogremon = struct.pack(ROM_OGREMON_SOFTLOCK_FORMAT, ROM_OGREMON_SOFTLOCK_VALUE)
    for offset in ROM_OGREMON_SOFTLOCK_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, fix_ogremon)


def _write_lava_cave_gate_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace the boulder script's digimon-ID whitelist with an AP-controlled
    trigger gate.

    Two byte-identical copies of the boulder script live in the BIN; both
    receive the same 28-byte rewrite that turns the original
    ``if pstat(103) != ... then`` whitelist into a single
    ``if trigger(145) == true then 600`` plus 16 bytes of
    ``jumpTo 1376`` filler. See :data:`ROM_LAVA_CAVE_GATE_OFFSETS` and
    :data:`ROM_LAVA_CAVE_GATE_VALUE` for byte layout.
    """

    for offset in ROM_LAVA_CAVE_GATE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_LAVA_CAVE_GATE_VALUE)


def _write_merit_shop_wrapper_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Install the Merit Shop give-item wrapper + AP-shop sentinel
    infrastructure.

    Four sets of writes:

    1. **Wrapper body** at :data:`ROM_MERIT_SHOP_WRAPPER_OFFSET`. The
       wrapper compares each shop purchase's $a0 (item ID) against
       :data:`MERIT_SHOP_DISPATCH`. On match: fires ``setTrigger`` for
       the AP location signal, then memcpy's the
       "AP Item Bought" sentinel (slot 114) over the dispatched slot
       in RAM ITEM_PARA, then ``jr $ra`` (suppresses vanilla
       ``giveItem``). On no match: tail-calls vanilla giveItem.
    2. **Jal hijack** at :data:`ROM_MERIT_SHOP_PATCH_OFFSET` — replaces
       the merit-shop function's ``jal 0x800C5240`` with
       ``jal ROM_MERIT_SHOP_WRAPPER_RAM``.
    3. **AP-shop-bought sentinel entry** at
       :data:`ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET` — rewrites slot 114
       (vanilla "Moon mirror") to the
       ``"AP Item Bought" / meritValue=0`` sentinel that the wrapper
       copies over the dispatched slot post-purchase.
    4. **Per-dispatch presale renames** — for each
       ``(item_id, _) in MERIT_SHOP_DISPATCH``, rewrites that slot's
       name field to ``"AP Item"`` so the pre-purchase shop display
       reads ``AP Item — vanilla_price`` instead of revealing the
       underlying item.
    """

    # 0. Slot 83 ("AP Item") full entry — name + meritValue 300 +
    #    zeros. Always-on (independent of chest_randomization)
    #    because slot 83 is the merit shop's AP-purchase row regardless
    #    of whether chests are randomized. With chest rando OFF, this is
    #    the only path that sets up slot 83; with it ON, the chest
    #    patcher writes the same bytes again (idempotent — harmless
    #    duplicate).
    patch.write_token(
        APTokenTypes.WRITE, ROM_AP_ITEM_ENTRY_OFFSET, ROM_AP_ITEM_ENTRY_BYTES,
    )
    # 1. Wrapper body
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_MERIT_SHOP_WRAPPER_OFFSET,
        ROM_MERIT_SHOP_WRAPPER_BYTES,
    )
    # 2. Jal hijack
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_MERIT_SHOP_PATCH_OFFSET,
        struct.pack(ROM_MERIT_SHOP_PATCH_FORMAT, ROM_MERIT_SHOP_PATCH_VALUE),
    )
    # 3. Slot 114 → "AP Item Bought" sentinel
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET,
        ROM_AP_SHOP_BOUGHT_ENTRY_BYTES,
    )
    # 4. Per-dispatch presale name rewrites (idempotent for slot 83
    #    since it's already named "AP Item" via ROM_AP_ITEM_ENTRY_BYTES;
    #    needed when MERIT_SHOP_DISPATCH includes real-item slots
    #    whose name should display as "AP Item" pre-purchase).
    for item_id, _trigger_id in MERIT_SHOP_DISPATCH:
        patch.write_token(
            APTokenTypes.WRITE,
            _merit_shop_presale_name_offset(item_id),
            ROM_AP_SHOP_PRESALE_NAME_BYTES,
        )
    # 5. Hide vanilla Amazing Rod from the merit shop (zero its
    #    meritValue field so the row scan skips it). Slot 117's name,
    #    icon, and other stats stay vanilla — only its merit-shop
    #    visibility is suppressed.
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_AMAZING_ROD_HIDE_OFFSET,
        ROM_AMAZING_ROD_HIDE_BYTES,
    )
    # 6. AP Item description string in Cave6 free space + redirect
    #    ITEM_DESC_PTR[83] to it, so the merit-shop hover panel reads
    #    "Item from the multiworld" instead of vanilla Electo Ring's
    #    description text.
    patch.write_token(
        APTokenTypes.WRITE,
        AP_ITEM_DESC_BIN_OFFSET,
        AP_ITEM_DESC_STRING,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        AP_ITEM_DESC_PTR_BIN_OFFSET,
        struct.pack(ROM_AP_ITEM_DESC_PTR_PATCH_FORMAT, AP_ITEM_DESC_PTR_VALUE),
    )
    # 7. Archipelago logo over slot 83's icon in ITEM.TIM (Electo Ring
    #    sprite, never seen elsewhere in the game — formerly blanked).
    #    Because the setItemTexture clamp redirects every extended AP
    #    slot (128+) to slot 83, this is the icon every AP shop row
    #    (and the chest sentinel) renders. Four write families:
    #
    #    a. 16 tile-row writes (sector-aware offsets) — the logo pixels.
    #    b. The AP palette over CLUT 22 (single 32-byte write; CLUT 22's
    #       only vanilla consumer is Rainbowhorn, relocated in d.).
    #    c. ITEM_CLUT_DATA[83]: 16 -> 22 so slot 83 renders with the AP
    #       palette.
    #    d. ITEM_CLUT_DATA[84]: 22 -> 8 so Rainbowhorn stops using the
    #       rewritten CLUT. Its tile pixels are requantized to CLUT 8 at
    #       patch-apply time by the ``requantize_rainbowhorn`` procedure
    #       step (they are game data, so they can't ship in the token
    #       blob).
    #
    #    The a. and b. families are written to BOTH on-disc TIM copies
    #    (standalone ITEM.TIM + the embedded ETCTIM.BIN copy the game
    #    actually uploads to VRAM — see the addresses.py section).
    for copy_rows in AP_ITEM_ICON_TILE_BIN_OFFSETS:
        for bin_offset, row_bytes in zip(
            copy_rows, AP_LOGO_TILE_ROW_BYTES, strict=True,
        ):
            patch.write_token(APTokenTypes.WRITE, bin_offset, row_bytes)
    for clut_offset in AP_ICON_CLUT_BIN_OFFSETS:
        patch.write_token(
            APTokenTypes.WRITE, clut_offset, AP_LOGO_CLUT_BYTES,
        )
    patch.write_token(
        APTokenTypes.WRITE,
        item_clut_data_bin_offset(AP_ITEM_ICON_INDEX),
        bytes((AP_ICON_CLUT_INDEX,)),
    )
    patch.write_token(
        APTokenTypes.WRITE,
        item_clut_data_bin_offset(RAINBOWHORN_ITEM_ID),
        bytes((RAINBOWHORN_NEW_CLUT_INDEX,)),
    )


def _write_leomonstone_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace all 7 ``giveItem 118 1`` calls in Script 109 with
    ``setTrigger 135``.

    Same shape as the other key-item neuters: vanilla Leomonstone
    delivery bypassed; only AP delivery (bank slot 118) puts the
    Leomonstone in the player's hands. The cutscene's existing
    ``setTrigger 135`` at script offset 676 stays in place; the
    substituted setTrigger calls are idempotent.

    Three ROM copies of Script 109's Leomonstone cutscene
    (Section_52) plus one orphan retry give 7 .bin sites total.
    Substituting setTrigger 135 at every site is safe regardless of
    cutscene context — the bit is the canonical "Leomonstone obtained"
    flag and setting it once is enough; further sets are no-ops.

    See :data:`ROM_LEOMONSTONE_GIVEITEM_OFFSETS` /
    :data:`ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_LEOMONSTONE_GIVEITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE)


def _write_blue_flute_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace both ``giveItem 115 1`` calls in Script 7 Section_82
    (Seadramon friendship cutscene) with ``setTrigger 210``.

    Same shape as the other key-item neuters: vanilla Blue Flute
    delivery bypassed; only AP delivery (bank slot 115) puts the Blue
    Flute in the player's hands. The cutscene's existing
    ``setTrigger 210`` at script offset 1998 stays in place; the
    substituted setTrigger calls are idempotent.

    Note: trigger 210 is the same bit that was previously used as the
    Seadramon recruit signal — Seadramon was dropped from AP recruit
    coverage 2026-05-09 because the recruit cutscene IS the Blue
    Flute pickup. The bit is now polled exclusively as
    ``Blue Flute Pickup`` in ``KEYITEM_LOCATION_RAM_BITS``;
    ``client._DROPPED_RECRUITS_BLACKLIST`` excludes Seadramon from
    the recruit-bit poll path.

    Single ROM copy of Script 7 = 2 .bin offsets.

    See :data:`ROM_BLUE_FLUTE_GIVEITEM_OFFSETS` /
    :data:`ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_BLUE_FLUTE_GIVEITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE)


def _write_rain_plant_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace the single ``giveItem 121 1`` in Script 162 Section_83
    (Tanemon planter cutscene in Native Forest) with ``setTrigger 76``.

    Same shape as the Mansion / Frig / Gear neuters: vanilla Rain Plant
    delivery bypassed; only AP delivery (bank slot 121) puts the Rain
    Plant in the player's hands. The cutscene's existing
    ``setTrigger 76`` at script offset 6238 stays in place; the
    substituted setTrigger at offset 6116 is idempotent.

    Note: the cutscene only fires on the 15th of any in-game month
    (``pstat(106) == 14``) AND only after Palmon is recruited
    (``trigger(246) == true``). Trigger 76 is **renewable** — Section_254
    of Script 162 ``unsetTrigger 76`` on each day-15 transition, so
    vanilla DW1 lets the player pick up a fresh Rain Plant each
    month. Renewability is a non-issue for AP: the location fires
    once on the first 0->1 transition and AP server-side dedup
    ignores subsequent re-flips.

    Single ROM copy of Script 162 = 1 .bin offset.

    See :data:`ROM_RAIN_PLANT_GIVEITEM_OFFSETS` /
    :data:`ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_RAIN_PLANT_GIVEITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE)


def _write_arena_cup_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace each cup's vanilla prize ``giveItem`` in Script 214
    Section_51 with ``setTrigger N`` so the 5 grade-tier cup wins
    (Grade D/C/B/A/S) fire AP location checks.

    Same shape as the key-item neuters: 4-byte in-place opcode swap,
    idempotent. The patcher iterates over every ROM copy of Section_51
    declared in :data:`ROM_ARENA_SECTION_51_BASES`; for each copy and
    each of the 14 patch sites in :data:`ARENA_CUP_PATCH_SITES`, it
    writes the cup's ``setTrigger N`` (4 bytes) over the vanilla
    ``giveItem`` opcode at ``base + script_relative_offset``.

    Grade S has 3 random prize sub-branches (Metal Part / Fatal Bone /
    Mega Hand on ``pstat(110) ∈ {0, 1, 2}``); all 3 sub-branches'
    giveItem sites share trigger 889 since any of them firing means
    Grade S was won.

    When :data:`ROM_ARENA_SECTION_51_BASES` is empty (the locator
    hasn't been run yet) this function is a no-op — generation still
    succeeds, but cup wins won't fire AP locations in-game.
    """

    for section_base in ROM_ARENA_SECTION_51_BASES:
        for trigger_id, script_offset in ARENA_CUP_PATCH_SITES:
            patch.write_token(
                APTokenTypes.WRITE,
                section_base + script_offset,
                ARENA_CUP_NEUTER_VALUES[trigger_id],
            )


def _write_gear_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace both ``giveItem 120 1`` calls in Script 144 Section_83
    (Toy Town WaruMonzaemon defeat → Gear hand-off cutscene) with
    ``setTrigger 270``.

    Same shape as the Mansion / Frig Key neuters: vanilla Gear delivery
    bypassed; only AP delivery (bank slot 120) puts the Gear in the
    player's hands. The cutscene's existing ``setTrigger 270`` at
    script offset 4518 stays in place; the substituted setTrigger calls
    at offsets 4334 and 4476 are idempotent.

    Note: trigger 270 is read by 6 other Toy Town scripts (139, 140,
    142, 143, 145) as a "Gear obtained" flag — those reads still work
    correctly. Some NPC dialog branches also check ``item(120)``;
    after this patch the player has trigger 270 set but no Gear in
    inventory until AP delivers, so a few NPC dialogs may behave as
    if the Gear is "missing despite being obtained" — cosmetic only,
    not progression-blocking.

    See :data:`ROM_GEAR_GIVEITEM_OFFSETS` /
    :data:`ROM_GEAR_GIVEITEM_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_GEAR_GIVEITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_GEAR_GIVEITEM_NEUTER_VALUE)


def _write_frig_key_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace both ``giveItem 123 1`` calls in Script 63 Section_5
    (Myotismon Frig-Key dialog) with ``setTrigger 104``.

    Same shape as the Mansion Key neuter: vanilla Frig Key delivery
    bypassed; only AP delivery (item id 123, inventory-first with bank
    fallback via the client's ``_make_item_deliverer``) puts the key
    in the player's hands.
    The cutscene's existing ``setTrigger 104`` at script offset 238
    stays in place, so trigger 104 still flips at the cutscene's
    intro — the substituted setTrigger calls at offsets 670 and 780
    are idempotent.

    See :data:`ROM_FRIG_KEY_GIVEITEM_OFFSETS` /
    :data:`ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_FRIG_KEY_GIVEITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE)


def _write_mansion_key_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace both ``giveItem 119 1`` calls in Script 54 Section_81 with
    ``setTrigger 110``.

    The vanilla Mansion Key cutscene gives the player the key in their
    inventory; in AP rando the key must come exclusively through AP
    delivery (item id 119, inventory-first with bank fallback via the
    client's ``_make_item_deliverer``). Both
    giveItem sites — primary (script offset 178) and inventory-full
    retry (script offset 438) — are rewritten across two ROM copies =
    4 sites total. The cutscene's existing ``setTrigger 110`` at offset
    442 stays in place; the substituted setTrigger calls are
    idempotent.

    See :data:`ROM_MANSION_KEY_GIVEITEM_OFFSETS` /
    :data:`ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_MANSION_KEY_GIVEITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE)


def _write_old_fishrod_remap_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Redirect Script 159 Section_51's trigger 45 references to trigger 902.

    Decouples "vanilla rod cutscene played" (now trigger 902, the AP
    location signal) from "rod owned" (still trigger 45, the bit the
    fishing minigame reads). Without this patch the two share trigger
    45, so AP delivery of the Old Fishrod item self-triggers the
    location and vanilla cutscene completion enables fishing without AP.

    See :data:`ROM_OLD_FISHROD_REMAP_OFFSETS` /
    :data:`ROM_OLD_FISHROD_REMAP_VALUE` for byte layout. Two 2-byte
    writes (single ROM copy of Script 159).
    """

    for offset in ROM_OLD_FISHROD_REMAP_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_OLD_FISHROD_REMAP_VALUE)


def _write_coelamon_gate_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Redirect Coelamon Section_51's first-gate branch target.

    Closes the Tropical Jungle Bridge bypass: without this, in shuffled
    mode the player could visit Coelamon, take vanilla case 1 across to
    TJ, walk the bridge cutscene tile, and set trigger 185 organically —
    bypassing the AP gate entirely. The 2-byte target rewrite makes the
    same gate redirect to ``endSection`` so case 1 never fires; case 2
    (Coelamon joins city) still works once trigger 185 is set by AP item
    delivery. See :data:`ROM_COELAMON_GATE_OFFSETS` /
    :data:`ROM_COELAMON_GATE_VALUE`.

    Offsets repaired 2026-08-22 (the original shipment was +4 off and
    corrupted the recruit-cutscene head instead of moving the branch
    target — see the offset-repair note in ``data/addresses.py``).
    Composes with :func:`_write_coelamon_cutscene_remap_tokens`, which
    rewrites the same statement's trigger-id bytes (disjoint offsets,
    asserted in the manifest).
    """

    for offset in ROM_COELAMON_GATE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_COELAMON_GATE_VALUE)


def _write_coelamon_cutscene_remap_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Remap Script 6's five trigger-249 references to trigger 779.

    The Coelamon shore state machine (recruit cutscene, ferry, and the
    shore-spawn guards) vanilla-reads and sets recruit bit 249 — but
    under AP the client pins bit 249 every tick (item-shop / hint-NPC
    compatibility), which would leave the recruit cutscene permanently
    unreachable; and historically the location looped when 249 stayed
    unmarked. Rewriting every Script-6 reference (four guard reads +
    the ``setTrigger`` operand, plus three dead residue twins) to the
    fresh AP trigger 779 gives the shore its own persistent "cutscene
    done" bit: the cutscene fires once (bridge built), sets 779 = the
    ``Coelamon`` AP location signal, and never re-fires. The pre-bridge
    ferry and the +2 PP grant stay vanilla. Same decoupling shape as
    :func:`_write_old_fishrod_remap_tokens`. Always-on. See
    :data:`ROM_COELAMON_CUTSCENE_REMAP_OFFSETS` /
    :data:`ROM_COELAMON_CUTSCENE_REMAP_VALUE`.
    """

    for offset in ROM_COELAMON_CUTSCENE_REMAP_OFFSETS:
        patch.write_token(
            APTokenTypes.WRITE, offset, ROM_COELAMON_CUTSCENE_REMAP_VALUE,
        )


def _write_prosperity_goal_token(
    patch: DigimonWorldProcedurePatch, threshold: int,
) -> None:
    """Patch the ``pstat(1) < 50`` literal in Script 210 §51 line 162.

    This is the gate Jijimon checks before announcing the Mt. Infinity
    entrance and arming the Airdramon ambush. Rewriting the comparand
    moves the in-game gate to the player's configured prosperity
    threshold; the ``prosperity_goal`` option also drives the
    matching AP rules in :mod:`.rules` and the
    ``Prosperity Point`` pool size in :mod:`.items`, so all three
    sides agree.

    The comparand is a single byte (vanilla ``0x32`` = 50) sitting at
    offset +1 inside the 4-byte ``pstat(N) <op> V`` IF primitive; the
    next 2 bytes (``80 00``) are the ``<`` operator opcode and must be
    preserved. Two duplicate copies of the IF block exist in the BIN —
    both are patched so either script-load path sees the new threshold.
    See :data:`ROM_PROSPERITY_GOAL_OFFSETS` for the verified encoding.
    """

    payload = struct.pack(ROM_PROSPERITY_GOAL_FORMAT, threshold)
    for offset in ROM_PROSPERITY_GOAL_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, payload)


def _write_great_canyon_cutscene_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Disable the Great Canyon bridge-fix cutscene.

    Closes the Great Canyon Bridge bypass: without this, reaching 6
    prosperity organically would let the vanilla cutscene fire and set
    trigger 103, bypassing the AP gate. The 2-byte rewrite replaces the
    second condition's trigger ID (124) with the same trigger ID as the
    first (103), making the gate ``if 103==true OR 103==false`` —
    always-true, always-skip-cutscene. The bridge can then only be
    fixed via AP item delivery.
    """

    for offset in ROM_GREAT_CANYON_CUTSCENE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_GREAT_CANYON_CUTSCENE_VALUE)
    # Sections 51/52/53 of Script 36 (the bridge approach screen) gate
    # the danger animation on trigger 124 — set only by the in-town
    # "Invisible Bridge rumor" NPC, which the player may never reach
    # (or may have skipped past) once their game state has advanced.
    # Redirect the gate to trigger 103 so the AP item alone is enough.
    for offset in ROM_GREAT_CANYON_APPROACH_GATE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_GREAT_CANYON_APPROACH_GATE_VALUE)


# =============================================================================
# QoL patcher helpers (Phase 5 polish; opt-in via player options)
# =============================================================================

def _write_region_gate_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
) -> None:
    """Physically enforce ``region_locking`` in the ROM (lab-validated).

    Emits per-seed gate data for exactly the regions that
    :func:`options.get_locked_regions` reports as locked — the same
    derivation :func:`rules._apply_region_locks` uses — so the ROM
    gates and the AP logic stay in lockstep. No-op when nothing is
    locked.

    Three token families (all addresses/bytes from the region-gate
    section of :mod:`.data.addresses`; see the lab NOTES in
    ``work/dw1_re/decomp/_scan_transition_gate`` + ``_scan_script_gates``
    for the three-net validation story):

    1. **Walk-on gates** — the Cave6 post-memcpy wrapper, the per-seed
       gate table (only rows whose gating region is locked), and the
       ``jal`` redirect at loadMapEntities' memcpy callsite. Blocked
       crossings loop back to the same mouth (normal fade, no message);
       the wrapper re-runs on every screen load, so the gate survives
       all reloads. Skipped entirely when the filtered table has no
       rows (e.g. only Beetle Land / Factorial Town locked — both are
       script-entry-only regions).
    2. **Script-class gates** — the market west/east gates + Beetle Land
       return ferry (Native Forest), the Whamon ferry (Factorial Town),
       and the Blue Flute pier + post-friendship ride (Beetle Land).
       Each locked region's group rewrites one-or-two u16 jump targets
       into stubs placed over script slot-tail residue; blocked flows
       take existing vanilla decline paths.
    3. **G Canyon Top flight redirect** — when Great Canyon is locked,
       entry 0 of both flight-table copies is re-triggered from the
       vanilla 221 (Birdramon recruit) to the AP bit 878, which the
       client pins on ``Birdramon Recruit AND Great Canyon Region
       Access``.
    """

    from .options import get_locked_regions

    locked = get_locked_regions(world.options)
    if not locked:
        return

    # 1. Walk-on wrapper + per-seed table + hook.
    table_bytes = build_transition_gate_table(locked)
    if len(table_bytes) > 4:  # more than the bare terminator
        patch.write_token(
            APTokenTypes.WRITE,
            TRANSITION_GATE_WRAPPER_OFFSET,
            ROM_TRANSITION_GATE_WRAPPER_BYTES,
        )
        patch.write_token(
            APTokenTypes.WRITE, TRANSITION_GATE_TABLE_OFFSET, table_bytes,
        )
        patch.write_token(
            APTokenTypes.WRITE,
            TRANSITION_GATE_HOOK_OFFSET,
            ROM_TRANSITION_GATE_HOOK_BYTES,
        )

    # 2. Script-class gates for the locked regions that have them.
    for region, gate_patches in SCRIPT_GATE_PATCHES.items():
        if region not in locked:
            continue
        for entry in gate_patches:
            patch.write_token(
                APTokenTypes.WRITE,
                script_vm_to_bin_offset(entry.script, entry.vm_offset),
                entry.data,
            )

    # 3. G Canyon Top flight-slot trigger redirect.
    if "Great Canyon" in locked:
        for offset, new_trigger_id in ROM_BIRDRA_FLIGHT_GCANYON_PATCHES:
            patch.write_token(
                APTokenTypes.WRITE,
                offset,
                struct.pack(ROM_BIRDRA_FLIGHT_TABLE_FORMAT, new_trigger_id),
            )


def _write_birdra_flight_table_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Redirect Birdramon-Messenger flight gate triggers to AP-controlled bits.

    Vanilla DW1's destination table (at .bin offsets 0x14B8B698 and a
    duplicate at 0x14D725CE) lists 6 entries of (trigger, price, label).
    Five of those triggers are story flags with multi-purpose use --
    setting them via AP delivery would fire downstream behaviors
    (cutscenes, NPC unlocks, dialog branches). Trigger 147 (Misty Trees)
    is heavily multi-purpose (16 references); trigger 210 (Beetle Land)
    has a complex prosperity-gated reference; etc.

    Solution: rewrite each non-recruit entry's trigger ID to point at a
    fresh, isolated AP-controlled bit (triggers 880..884 at
    `0x001BE03B` bits 0..4). callRoutine 10 reads these new bits via the
    patched table; AP delivery sets them via the standard keyitem-bit
    deliverer (no game-state side effects since the original story flags
    are untouched).

    G Canyon Top (entry 0, vanilla trigger 221 = Birdramon recruit) is
    intentionally left unpatched: it correctly auto-unlocks when the
    Birdramon Recruit AP item lands. That's why there are 5 patches
    per table copy, not 6.

    See `dw1_birdramon_flight_gates.md` and the `BIRDRAMON_FLIGHT_RAM_BITS`
    block in `addresses.py` for the full mapping.
    """

    for offset, new_trigger_id in ROM_BIRDRA_FLIGHT_TABLE_PATCHES:
        patch.write_token(
            APTokenTypes.WRITE,
            offset,
            struct.pack(ROM_BIRDRA_FLIGHT_TABLE_FORMAT, new_trigger_id),
        )

    # QoL (unconditional, user-confirmed 2026-08-21): zero the u32 price
    # field of all 6 destination entries in BOTH table copies (vanilla
    # fares 1000..2500 bits). The engine handles price 0, so every
    # flight becomes free once its trigger bit is delivered.
    for offset in ROM_BIRDRA_FLIGHT_PRICE_OFFSETS:
        patch.write_token(
            APTokenTypes.WRITE, offset, ROM_BIRDRA_FLIGHT_PRICE_ZERO,
        )


def _write_item_stat_gain_token(patch: DigimonWorldProcedurePatch) -> None:
    """Make digivolution-item digivolutions grant stat/lifetime gains.

    Source: ``references/digimon_world_randomizer/digimon/handler.py:2429-2438``
    and ``digimon/data.py:197-200``. A single-byte ``0x00`` write at
    BIN offset ``0x14CF5AFC`` flips an item-driven-digivolution branch
    so it follows the same stat-gain + lifetime-bump path that training
    digivolutions take. Vanilla DW1 skips both for item digivolutions.
    """

    patch.write_token(
        APTokenTypes.WRITE,
        ROM_EVO_ITEM_STAT_GAIN_OFFSET,
        struct.pack(ROM_EVO_ITEM_STAT_GAIN_FORMAT, ROM_EVO_ITEM_STAT_GAIN_VALUE),
    )


def _write_skip_intro_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace two intro-textbox sequences with ``jumpTo`` opcodes.

    Source: ``references/digimon_world_randomizer/digimon/handler.py:2576-2591``.
    Each ``jumpTo`` is a 4-byte instruction: opcode 0x16, padding 0x00,
    destination as a little-endian u16. The destinations skip past the
    bulk of Jijimon's intro dialogue while preserving the title card
    and partner-pick prompt.
    """

    outside = struct.pack(
        ROM_SKIP_INTRO_FORMAT, ROM_SKIP_INTRO_OPCODE, ROM_SKIP_INTRO_OUTSIDE_DEST,
    )
    patch.write_token(APTokenTypes.WRITE, ROM_SKIP_INTRO_OUTSIDE_OFFSET, outside)

    inside = struct.pack(
        ROM_SKIP_INTRO_FORMAT, ROM_SKIP_INTRO_OPCODE, ROM_SKIP_INTRO_INSIDE_DEST,
    )
    patch.write_token(APTokenTypes.WRITE, ROM_SKIP_INTRO_INSIDE_OFFSET, inside)


def _write_type_lock_unlock_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Remove the type-gate checks on Greylord's Mansion, Ice Sanctuary,
    and Toy Town.

    Source: ``references/digimon_world_randomizer/digimon/handler.py:2629-2652``.
    Three independent patches, each rewriting the type-check jump with
    a fall-through value so any partner Digimon can enter.

    NOTE (logic): the AP rules currently don't model these as
    type-gated regions, so removing the gate has no immediate logic
    impact. When the recruit-randomization logic rework lands, both
    the rules and this option's interaction with them need a second
    look — with this option on, recruit-derived progression that
    currently routes through the gated regions becomes accessible
    earlier than the rules expect.
    """

    greylord = struct.pack(ROM_UNLOCK_TYPE_LOCK_FORMAT, ROM_UNLOCK_GREYLORD_VALUE)
    for offset in ROM_UNLOCK_GREYLORD_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, greylord)

    ice = struct.pack(ROM_UNLOCK_TYPE_LOCK_FORMAT, ROM_UNLOCK_ICE_VALUE)
    for offset in ROM_UNLOCK_ICE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ice)

    toy_town = struct.pack(ROM_UNLOCK_TOY_TOWN_FORMAT, ROM_UNLOCK_TOY_TOWN_VALUE)
    for offset in ROM_UNLOCK_TOY_TOWN_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, toy_town)


def _write_spawn_rate_boost_tokens(
    patch: DigimonWorldProcedurePatch, percent: int,
) -> None:
    """Boost the encounter chance for Mamemon, Piximon, MetalMamemon,
    and Otamamon.

    Source: ``references/digimon_world_randomizer/digimon/handler.py:2520-2559``.
    The first three Digimon use a 0..99 RNG comparison — write
    ``percent - 1`` so that ``rng < value`` is true ``percent``% of the
    time. Otamamon uses a 0..2 RNG — write ``floor(percent / 33)`` to
    map the same percentage onto its smaller scale.
    """

    percent = max(1, min(100, percent))
    large = percent - 1
    small = percent // 33

    large_bytes = struct.pack(ROM_SPAWN_RATE_FORMAT, large)
    for offsets in (
        ROM_SPAWN_RATE_MAMEMON_OFFSETS,
        ROM_SPAWN_RATE_PIXIMON_OFFSETS,
        ROM_SPAWN_RATE_MMAMEMON_OFFSETS,
    ):
        for offset in offsets:
            patch.write_token(APTokenTypes.WRITE, offset, large_bytes)

    small_bytes = struct.pack(ROM_SPAWN_RATE_FORMAT, small)
    for offset in ROM_SPAWN_RATE_OTAMAMON_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, small_bytes)


def _write_combat_multiplier_tokens(
    patch: DigimonWorldProcedurePatch, factor: int,
) -> None:
    """Install the combat stat-gain trampolines and patch the three sites.

    No-op when ``factor <= 1`` — vanilla behavior. Otherwise: writes
    three small trampoline blobs into Cave6 free-space (immediately
    after the isTriggerSet wrapper) and rewrites the three ``sh`` /
    ``beq+sh`` sites in vanilla ``battleStatsGainsAndDrops`` to
    ``j <trampoline>``. See the block comment in ``addresses.py`` for
    the full address derivation.
    """

    if factor <= 1:
        return

    tr1, tr2, tr3 = build_combat_multiplier_trampolines(factor)
    patch.write_token(APTokenTypes.WRITE, ROM_COMBAT_TR1_OFFSET, tr1)
    patch.write_token(APTokenTypes.WRITE, ROM_COMBAT_TR2_OFFSET, tr2)
    patch.write_token(APTokenTypes.WRITE, ROM_COMBAT_TR3_OFFSET, tr3)
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_COMBAT_SITE1_OFFSET,
        struct.pack(ROM_COMBAT_SITE1_FORMAT, *ROM_COMBAT_SITE1_VALUE),
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_COMBAT_SITE2_OFFSET,
        struct.pack(ROM_COMBAT_SITE2_FORMAT, *ROM_COMBAT_SITE2_VALUE),
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_COMBAT_SITE3_OFFSET,
        struct.pack(ROM_COMBAT_SITE3_FORMAT, *ROM_COMBAT_SITE3_VALUE),
    )


# =============================================================================
# Vending-machine patcher
# =============================================================================
#
# For each ``_VendingItem`` in :data:`VENDING_MACHINES`, the patcher
# overwrites the vanilla success-branch ``giveItem`` / ``addStats`` opcode
# with ``setTrigger N`` — N is the AP-allocated trigger bit for that
# location. The overwrite happens at every ``script_base + offset`` for
# every ROM copy of the script. Vanilla menu / result / preface text is
# left intact: the player still sees the vanilla item name on screen,
# but the AP location fires and AP delivers whatever it placed at that
# location to the player's bank.
#
# An earlier "Quest/Bonus/Junk" text-substitution pass was retired
# 2026-05-08 because DW1's script-engine PC-advance is fragile against
# shortened textbox content — substitutions could (and did, intermittently)
# cause the engine to drop out of the script before reaching our
# ``setTrigger`` overwrite, suppressing the AP location ping.
#
# Plus: the Ancient Dino "Try" gacha needs an extra 4-byte ROM patch to
# fix a vanilla DW1 scripting bug where the MP Floppy outcome's
# ``giveItem`` is gated behind the inventory-full recovery branch (so
# the player gets the announcement textbox but never the item, and our
# trigger 901 never fires either). See
# :data:`ROM_GACHA_MP_FLOPPY_FIX_OFFSET` for the fix details.


def _write_vending_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
) -> None:
    """Write all vending-machine tokens for the seed.

    Per machine: at every ``base + overwrite_offset`` for every ROM
    copy of the script, replace the vanilla ``giveItem`` /
    ``addStats`` opcode with a 4-byte ``setTrigger N`` pointing at
    that purchase's AP-allocated trigger bit.

    For the Ancient Dino "Try" gacha, also emits the 4-byte
    :data:`ROM_GACHA_MP_FLOPPY_FIX_BYTES` patch at
    :data:`ROM_GACHA_MP_FLOPPY_FIX_OFFSET` — without this patch, only
    3 of the 4 gacha prizes were detectable by AP (vanilla DW1 bug;
    see addresses.py block comment for the script-flow analysis).
    """

    multiworld = world.multiworld
    player = world.player

    for machine in VENDING_MACHINES:
        # Probe one location per machine to see whether this slot has
        # vending locations enabled. ``get_location`` raises KeyError
        # when the option is off — skip the machine in that case.
        try:
            multiworld.get_location(machine.items[0].location_name, player)
        except KeyError:
            return  # option off — no vending locations exist for this slot

        for base in machine.script_bases:
            for item in machine.items:
                trigger_bytes = encode_set_trigger(item.trigger_id)
                for off in item.overwrite_offsets:
                    patch.write_token(APTokenTypes.WRITE, base + off, trigger_bytes)

    # Vanilla DW1 gacha-prize-4 fix — applied unconditionally when
    # vending locations are on, since trigger 901 is otherwise
    # unreachable for the MP Floppy outcome.
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_GACHA_MP_FLOPPY_FIX_OFFSET,
        ROM_GACHA_MP_FLOPPY_FIX_BYTES,
    )


def _write_card_trade_multiplier_tokens(
    patch: DigimonWorldProcedurePatch, multiplier: int,
) -> None:
    """Scale the Merit Shop's per-card trade-value table.

    Option-gated (``card_trade_multiplier`` > 1). For each of the 65
    entries of the static card-value table at .bin
    :data:`CARD_TRADE_VALUE_TABLE_BIN_OFFSET` (RAM ``0x8012FFDA``),
    overwrite the ``value_i16`` halfword with
    ``min(vanilla * multiplier, CARD_TRADE_VALUE_CAP)``. Zero-value
    placeholder rows are skipped (0 x K = 0 — no token needed) and the
    ``cardRef`` halfword at entry offset +2 is never touched.

    Offsets come from :func:`card_trade_value_bin_offset`, which is
    sector-aware — a Mode2/2352 boundary splits the table between
    entries 9 and 10. Live proof of the mechanism (whole-column poke
    -> boosted dialog + boosted merit deposit) is on record in
    ``work/dw1_re/decomp/_scratch_merit_card_trade/CARD_TRADE_NOTES.md``.
    """

    if multiplier <= 1:
        return  # vanilla — caller gates on this too; defensive
    for index, vanilla in enumerate(CARD_TRADE_VANILLA_VALUES):
        if vanilla == 0:
            continue  # placeholder rows stay zero
        boosted = min(vanilla * multiplier, CARD_TRADE_VALUE_CAP)
        patch.write_token(
            APTokenTypes.WRITE,
            card_trade_value_bin_offset(index),
            struct.pack("<h", boosted),
        )


def _write_piximon_manual_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace Script 176 §82's single ``giveItem 33 1`` (Piximon's
    Training Manual sale in the File City item-shop building) with
    ``setTrigger 877``.

    Option-gated (``piximon_manual_location``). Same shape as the
    vending-machine neuters: the player still pays the 50,000 Bits and
    sees the vanilla dialog, but no Training Manual is delivered — the
    AP location fires via trigger 877 and the AP-placed item arrives
    through the standard delivery path instead.

    Unlike the Blue Flute cutscene, §82 has no retry ``giveItem`` —
    its give-failed branch refunds the payment instead — so one .bin
    site covers the whole flow (exhaustive user-space scan on record;
    see the ``PIXIMON_MANUAL_*`` block in :mod:`.data.addresses`).
    """

    for offset in ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS:
        patch.write_token(
            APTokenTypes.WRITE, offset, ROM_PIXIMON_MANUAL_NEUTER_VALUE,
        )


def _write_item_para_relocation_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Install the always-on ITEM_PARA 256-slot relocation.

    Lab-validated design (``work/dw1_re/decomp/item_para_reloc/``): the
    full ITEM_PARA table is rebuilt at boot inside the 8 KB region
    vacated from the malloc3 arena. Five sets of writes, all
    option-independent (the shop token writers later overlay their ext
    entries into the seed block via
    :func:`ext_item_para_slot_bin_offset`):

    1. **Heap-claim word** at :data:`HEAP_CLAIM_WORD_BIN_OFFSET` —
       moves the arena base one word so boot runs
       ``InitHeap3(0x801C1B70, 0x2E390)``, vacating
       0x801BFB70..0x801C1B70 (exactly 256 x 32 B).
    2. **Boot seed hook body** at :data:`ITEM_PARA_BOOT_HOOK_OFFSET`
       (Cave6, 148 B) — calls the displaced master-init callee, copies
       vanilla+tokens ITEM_PARA (4 KB), zeros the upper 4 KB, copies
       the EXT_ITEM_PARA seed block (960 B) over slots 128..157. The
       copy happens at RUNTIME on every boot / soft reset — there is
       no patch-apply-time table copy step.
    3. **Jal redirect** at :data:`BOOT_SEED_HOOK_SITE_OFFSET` —
       replaces master-init's first ``jal 0x800EEBDC`` with
       ``jal ITEM_PARA_BOOT_HOOK_RAM``.
    4. **Seed-block zero-fill** (960 B) at
       :data:`EXT_ITEM_PARA_SEED_BIN_OFFSET` — unpopulated ext slots
       decode as empty entries (meritValue 0). MUST be emitted before
       the recycle/merit ext entry tokens (token order = insertion
       order); :func:`write_patch` calls this writer first.
    5. **31 reader sites, 62 words** — 24 SLUS lui/addiu pairs
       (:data:`ITEM_PARA_READER_WORD_PATCHES`) and 7 overlay pairs
       (:data:`ITEM_PARA_OVERLAY_WORD_PATCHES`, plain .bin-offset
       tokens into BTL_REL.BIN / FISH_REL.BIN user data) re-based from
       vanilla 0x801269DC to the relocated table.
    """

    # 1. Heap-claim word.
    patch.write_token(
        APTokenTypes.WRITE,
        HEAP_CLAIM_WORD_BIN_OFFSET,
        struct.pack(HEAP_CLAIM_WORD_FORMAT, HEAP_CLAIM_WORD_PATCHED),
    )

    # 2. Boot seed hook body (Cave6).
    patch.write_token(
        APTokenTypes.WRITE,
        ITEM_PARA_BOOT_HOOK_OFFSET,
        ITEM_PARA_BOOT_HOOK_BYTES,
    )

    # 3. Master-init first-jal redirect.
    patch.write_token(
        APTokenTypes.WRITE,
        BOOT_SEED_HOOK_SITE_OFFSET,
        struct.pack(BOOT_SEED_HOOK_FORMAT, BOOT_SEED_HOOK_PATCH_VALUE),
    )

    # 4. EXT_ITEM_PARA seed-block zero-fill (sector-aligned single
    #    flat write; shop writers overlay entries afterwards).
    patch.write_token(
        APTokenTypes.WRITE,
        EXT_ITEM_PARA_SEED_BIN_OFFSET,
        b"\x00" * EXT_ITEM_PARA_SEED_SIZE,
    )

    # 5. Reader-site word patches (SLUS + overlays).
    for bin_offset, patched_word, _vanilla_word in ITEM_PARA_READER_WORD_PATCHES:
        patch.write_token(
            APTokenTypes.WRITE, bin_offset, struct.pack("<I", patched_word),
        )
    for _fname, bin_offset, patched_word, _vanilla_word in ITEM_PARA_OVERLAY_WORD_PATCHES:
        patch.write_token(
            APTokenTypes.WRITE, bin_offset, struct.pack("<I", patched_word),
        )


def _resolve_placed_item(
    world: DigimonWorldWorld, location_name: str,
) -> tuple[str, str] | None:
    """``(ap_item_name, owner_player_name)`` for a filled AP location.

    Returns ``None`` when the location doesn't exist (option off —
    callers gate already, defensive only). An unfilled location falls
    back to the generic "AP Item" name owned by this world's player.
    """

    multiworld = world.multiworld
    try:
        location = multiworld.get_location(location_name, world.player)
    except KeyError:
        return None
    placed = location.item
    if placed is None:
        return "AP Item", multiworld.player_name[world.player]
    return placed.name, multiworld.player_name[placed.player]


def _build_ap_icon_id_table(world: DigimonWorldWorld) -> bytes:
    """Per-ext-slot ITEM.TIM tile ids for the setItemTexture icon wrapper.

    One byte per extended ITEM_PARA slot 128..185, consumed in-game by
    the icon-id wrapper (``a1 = table[a1 - 128]``, see
    :data:`worlds.digimon_world.data.addresses.AP_ICON_ID_TABLE_RAM`):

    * If the slot's AP location holds THIS world's own bank-deliverable
      inventory item (dw_code 2000..2127), the byte is that item's real
      DW1 item id — the shop row shows the item's native icon.
    * Anything else — another player's item, an AP-only abstraction
      (Progressive ladders, Bits, Prosperity Points, recruit /
      technique / virtual-access items), an unfilled location, or a
      shop whose option is off — keeps the default
      :data:`AP_ICON_ID_FALLBACK` (83), the Archipelago logo tile.
    """

    from .items import dw1_internal_item_id

    table = bytearray(AP_ICON_ID_TABLE_DEFAULT_BYTES)
    slot_families: tuple[tuple[int, tuple[str, ...]], ...] = (
        (RECYCLE_SHOP_AP_ITEM_ID_BASE, RECYCLE_SHOP_LOCATION_NAMES),
        (MERIT_SHOP_AP_ITEM_ID_BASE, MERIT_SHOP_LOCATION_NAMES),
        (ITEM_SHOP_AP_ITEM_ID_BASE, ITEM_SHOP_LOCATION_NAMES),
        (SECRET_SHOP_AP_ITEM_ID_BASE, SECRET_SHOP_LOCATION_NAMES),
    )
    for base_id, location_names in slot_families:
        for i, location_name in enumerate(location_names):
            try:
                location = world.multiworld.get_location(
                    location_name, world.player,
                )
            except KeyError:
                continue  # shop option off — the slot is never rendered
            item = location.item
            if item is None or item.player != world.player:
                continue
            internal_id = dw1_internal_item_id(item.name)
            if internal_id is None:
                continue
            table[base_id + i - AP_ICON_ID_TABLE_BASE_ITEM_ID] = internal_id
    return bytes(table)


def _write_ap_icon_id_table_tokens(
    patch: DigimonWorldProcedurePatch, world: DigimonWorldWorld,
) -> None:
    """Emit the 58-byte per-slot icon-id table.

    Companion of the icon-id wrapper written by
    :func:`_write_shopsanity_common_tokens` step 6, gated the same way
    (any shop mode != off). Placement-dependent, so it needs the filled
    multiworld (``write_patch`` runs from ``generate_output``, after
    fill).
    """

    patch.write_token(
        APTokenTypes.WRITE,
        AP_ICON_ID_TABLE_OFFSET,
        _build_ap_icon_id_table(world),
    )


def _resolve_shop_prices(world: DigimonWorldWorld) -> dict[int, int]:
    """Per-ext-slot money price for the recycle / item / secret AP rows.

    * ``shop_price_mode: tiered`` — recycle keeps its vanilla prices;
      item shop rows follow :func:`item_shop_tiered_price` (500 / 1000 /
      2000 by tier); secret shop rows follow
      :func:`secret_shop_tiered_price` (1000..3200 by clerk).
    * ``shop_price_mode: randomized`` — each slot rolls uniformly in
      ``[shop_price_min, shop_price_max]`` from the world RNG
      (deterministic per seed).

    Merit slots (135..148) are intentionally absent — merit prices are
    merit-currency and always stay vanilla.
    """

    options = world.options
    randomized = int(options.shop_price_mode.value) == 1
    price_min = int(options.shop_price_min.value)
    price_max = int(options.shop_price_max.value)

    prices: dict[int, int] = {}
    for i in range(RECYCLE_SHOP_AP_ITEM_ID_COUNT):
        prices[RECYCLE_SHOP_AP_ITEM_ID_BASE + i] = RECYCLE_SHOP_VANILLA_PRICES[i]
    for i, slot in enumerate(ITEM_SHOP_AP_ITEM_IDS):
        prices[slot] = item_shop_tiered_price(i)
    for i, slot in enumerate(SECRET_SHOP_AP_ITEM_IDS):
        prices[slot] = secret_shop_tiered_price(i)
    if randomized:
        for slot in prices:
            prices[slot] = world.random.randint(price_min, price_max)
    return prices


def _write_shopsanity_common_tokens(
    patch: DigimonWorldProcedurePatch,
    modes: ShopModes,
) -> None:
    """Shopsanity infrastructure, emitted whenever ANY shop mode != off.

    Lab-validated 2026-08-21 (``work/dw1_re/decomp/_scan_shopsanity``,
    three nets). Seven sets of writes:

    1. **EXTENDED boot seed hook** (55 words) over the always-on
       37-word hook at :data:`ITEM_PARA_BOOT_HOOK_OFFSET` — adds loop 4
       (second seed block 0x80115A4C -> relocated slots 158..185) and
       loop 5 (re-zero the staging region, restoring its boot
       invariant). Token order: must be emitted AFTER
       :func:`_write_item_para_relocation_tokens` so these bytes
       overwrite the base hook token.
    2. **AP builder wrapper** (96 words) at the freed vanilla
       ITEM_DESC_PTR region 0x801279DC + the **dispatcher jal
       redirect** at 0x800FC6AC. Screen-gated per-shop-mode row
       emission (see the Shopsanity section of ``data.addresses``).
    3. **Extended giveItem wrapper** (26 words) at 0x80127B5C + the
       **giveItem jal redirect** at 0x800FB410. Supersedes the retired
       v1 recycle giveItem wrapper (same callsite) and handles all AP
       id ranges (128..134 / 149..164 / 165..185).
    4. **Per-shop mode config** (4 bytes ``[recycle, item, secret, 0]``)
       at :data:`SHOP_AP_CONFIG_BIN_OFFSET`.
    5. **3 ITEM_DESC_PTR callsite patches** — the freed region now
       holds code, so ALL desc-ptr readers must be re-based to the
       relocated Cave6 table (previously only emitted for the recycle
       shop; merit-only seeds relied on never dereferencing).
    6. **Icon-id wrapper + entry patch** — icon lookups with item_id in
       128..185 are rewritten through the per-slot icon-id table (local
       placed items keep their native tile; everything else renders the
       AP logo at slot 83). The table bytes are emitted separately by
       :func:`_write_ap_icon_id_table_tokens` (same gating, needs the
       filled multiworld).

    The merit shop's own machinery (ext wrapper, scan bound, jal at
    0x8010BF3C) stays in :func:`_write_merit_shop_locations_tokens` —
    merit is data-only with respect to this infrastructure and is NOT
    in the config word.
    """

    # 1. Extended boot hook (overwrites the base 37-word hook token).
    patch.write_token(
        APTokenTypes.WRITE,
        ITEM_PARA_BOOT_HOOK_OFFSET,
        ITEM_PARA_BOOT_HOOK_EXT_BYTES,
    )

    # 2. Builder wrapper + dispatcher jal redirect.
    patch.write_token(
        APTokenTypes.WRITE,
        SHOP_AP_BUILDER_WRAPPER_OFFSET,
        SHOP_AP_BUILDER_WRAPPER_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        SHOP_AP_DISPATCHER_JAL_OFFSET,
        struct.pack("<I", SHOP_AP_DISPATCHER_JAL_VALUE),
    )

    # 3. Extended giveItem wrapper + jal redirect.
    patch.write_token(
        APTokenTypes.WRITE,
        SHOP_AP_GIVEITEM_EXT_OFFSET,
        SHOP_AP_GIVEITEM_EXT_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        SHOP_AP_GIVEITEM_JAL_OFFSET,
        struct.pack("<I", SHOP_AP_GIVEITEM_JAL_VALUE),
    )

    # 4. Per-shop mode config (merit not included — data-only modes).
    patch.write_token(
        APTokenTypes.WRITE,
        SHOP_AP_CONFIG_BIN_OFFSET,
        build_shop_ap_config_bytes(modes.recycle, modes.item, modes.secret),
    )

    # 5. ITEM_DESC_PTR callsite patches (3 sites, both halves of each).
    lui_bytes = struct.pack(
        RELOC_ITEM_DESC_PTR_PATCH_FORMAT, RELOC_ITEM_DESC_PTR_LUI_VALUE,
    )
    addiu_bytes = struct.pack(
        RELOC_ITEM_DESC_PTR_PATCH_FORMAT, RELOC_ITEM_DESC_PTR_ADDIU_VALUE,
    )
    for lui_offset, addiu_offset in RELOC_ITEM_DESC_PTR_PATCH_SITES:
        patch.write_token(APTokenTypes.WRITE, lui_offset, lui_bytes)
        patch.write_token(APTokenTypes.WRITE, addiu_offset, addiu_bytes)

    # 6. setItemTexture icon-id wrapper + entry patch — icon lookups
    #    with item_id in 128..185 are rewritten through the per-slot
    #    icon-id table at :data:`AP_ICON_ID_TABLE_RAM` (local placed
    #    items keep their native tile; everything else renders the AP
    #    logo tile at slot 83). The table contents are emitted by
    #    :func:`_write_ap_icon_id_table_tokens` (needs fill results);
    #    here only the code + entry hijack are written.
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_ICON_CLAMP_WRAPPER_OFFSET,
        ROM_ICON_CLAMP_WRAPPER_BYTES,
    )
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_ICON_CLAMP_PATCH_OFFSET,
        struct.pack(ROM_ICON_CLAMP_PATCH_FORMAT, *ROM_ICON_CLAMP_PATCH_VALUE),
    )


def _write_recycle_shop_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
    prices: dict[int, int],
) -> None:
    """Recycle Shop per-seed data tokens (mode != off).

    Two sets of writes:

    1. **Extended ITEM_PARA entries (slots 128..134)** in the
       EXT_ITEM_PARA seed block (via
       :func:`ext_item_para_slot_bin_offset`; the boot hook copies the
       block into the relocated table at natural slot positions). One
       32-byte entry per AP shop slot, carrying the
       multiworld-resolved AP item name (truncated to 14 chars) and
       the slot's price per the ``shop_price_mode`` option.
    2. **AP description strings** at :data:`AP_DESC_STRINGS_BIN_OFFSET`
       (Cave6). One 64-byte NUL-padded ``"From <player>'s World"``
       slot per row; the relocated ITEM_DESC_PTR (built by
       :meth:`relocate_item_desc_ptr`) references these.

    The v1 runtime machinery this writer used to install — the 60-B
    giveItem wrapper @ 0x80095940, its jal hijack, and the
    entry_count==7 init-epilogue wrapper — was retired 2026-08-21: the
    shopsanity builder wrapper + extended giveItem wrapper
    (:func:`_write_shopsanity_common_tokens`) subsume all three, and
    the client's runtime array reconciler is gone with them.
    """

    for i, location_name in enumerate(RECYCLE_SHOP_LOCATION_NAMES):
        resolved = _resolve_placed_item(world, location_name)
        if resolved is None:
            return  # option off — defensive, callers gate already
        ap_item_name, owner_name = resolved

        slot_id = RECYCLE_SHOP_AP_ITEM_ID_BASE + i
        patch.write_token(
            APTokenTypes.WRITE,
            ext_item_para_slot_bin_offset(slot_id),
            build_ap_item_para_entry(ap_item_name, prices[slot_id]),
        )
        patch.write_token(
            APTokenTypes.WRITE,
            AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN,
            build_ap_desc_string(owner_name),
        )


def _write_item_shop_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
    prices: dict[int, int],
) -> None:
    """Item-shop per-seed data tokens (mode != off).

    One 32-byte ext ITEM_PARA entry per AP row (slots 149..173) with
    the multiworld-resolved AP item name and the slot's price per the
    ``shop_price_mode`` option. ``meritValue`` stays 0 (the default of
    :func:`build_ap_item_para_entry`) — a non-zero value would leak
    the slot into the merit shop's scan. Slots 149..157 land in the
    Cave6 seed block, 158..173 in the second staging block (routing
    via :func:`ext_item_para_slot_bin_offset`). Hover descriptions use
    the shared generic pointer (see :meth:`relocate_item_desc_ptr`).
    """

    for i, location_name in enumerate(ITEM_SHOP_LOCATION_NAMES):
        resolved = _resolve_placed_item(world, location_name)
        if resolved is None:
            return  # option off — defensive, callers gate already
        ap_item_name, _owner_name = resolved
        slot_id = ITEM_SHOP_AP_ITEM_ID_BASE + i
        patch.write_token(
            APTokenTypes.WRITE,
            ext_item_para_slot_bin_offset(slot_id),
            build_ap_item_para_entry(ap_item_name, prices[slot_id]),
        )


def _write_secret_shop_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
    prices: dict[int, int],
) -> None:
    """Secret-shop per-seed data tokens (mode != off).

    One 32-byte ext ITEM_PARA entry per AP row (slots 174..185, all in
    the second staging block), same shape as
    :func:`_write_item_shop_tokens`.
    """

    for i, location_name in enumerate(SECRET_SHOP_LOCATION_NAMES):
        resolved = _resolve_placed_item(world, location_name)
        if resolved is None:
            return  # option off — defensive, callers gate already
        ap_item_name, _owner_name = resolved
        slot_id = SECRET_SHOP_AP_ITEM_ID_BASE + i
        patch.write_token(
            APTokenTypes.WRITE,
            ext_item_para_slot_bin_offset(slot_id),
            build_ap_item_para_entry(ap_item_name, prices[slot_id]),
        )


def _write_merit_shop_locations_tokens(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
    *,
    replace: bool,
) -> None:
    """Write all Merit Shop AP-randomization tokens for the seed.

    Merit modes are data-only (lab-validated): ``replace`` emits the 14
    vanilla-item meritValue zero-outs (set 3 below) so the vanilla rows
    disappear; ``coexist`` omits exactly those tokens and everything
    else is identical — vanilla rows stay purchasable through the ext
    wrapper's fall-through, next to the AP rows (28-row list validated
    in the lab). Slot 117 (Amazing rod) stays zeroed always-on either
    way, via :func:`_write_merit_shop_wrapper_tokens`.

    Six sets of writes (only when
    :class:`worlds.digimon_world.options.MeritShopLocations` is on):

    1. **Extended ITEM_PARA entries (slots 135..148)** — one 32-byte
       entry per of the 14 AP merit-shop slots, carrying the
       multiworld-resolved AP item name (truncated to 14 chars) and
       the vanilla ``meritValue`` of the corresponding entry in
       :data:`MERIT_SHOP_VANILLA_ENTRIES` (so the merit-shop scan
       picks it up at the same displayed price). The helper
       :func:`ext_item_para_slot_bin_offset` routes every ext slot to
       the EXT_ITEM_PARA seed block, which the always-on boot hook
       copies into the relocated table (slots at natural positions).
    2. **AP description strings** at
       :data:`MERIT_AP_DESC_STRINGS_BIN_OFFSET`. 14 x 64-byte NUL-padded
       slots holding ``"From <player>'s World"``. The relocated
       ITEM_DESC_PTR (built later by :meth:`relocate_item_desc_ptr`)
       references these.
    3. **Vanilla-item meritValue zero-outs** — for **all 14** entries in
       :data:`MERIT_SHOP_VANILLA_ENTRIES`, write ``meritValue = 0`` to
       its ITEM_PARA entry so every vanilla merit-shop row disappears.
       Slot 117 (Amazing rod) is already zeroed by the always-on v1
       :func:`_write_merit_shop_wrapper_tokens`; this duplicate write
       is idempotent. (These land in the OLD table region — the boot
       hook copies slots 0..127 from there, so they carry over.)
    4. **Extended wrapper bytes** at
       :data:`ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET` — 572-byte MIPS
       sequence that dispatches 15 entries (slot 83 → trigger 903 +
       slots 135..148 → triggers 912..925).
    5. **Jal-hijack override** at the existing
       :data:`ROM_MERIT_SHOP_PATCH_OFFSET`. The v1 always-on patcher
       writes ``jal ROM_MERIT_SHOP_WRAPPER_RAM`` (= 0x80095800) at this
       offset; we re-write it to
       ``jal ROM_MERIT_SHOP_EXT_WRAPPER_RAM``. Token order is insertion
       order so this token must be emitted **after**
       :func:`_write_merit_shop_wrapper_tokens` runs.
    6. **Scan-loop bound patch** at
       :data:`ROM_MERIT_SCAN_BOUND_OFFSET` — single 4-byte rewrite
       changing ``sltiu $r1, $r5, 0x80`` to ``sltiu $r1, $r5, 0x95`` so
       the merit-shop ITEM_PARA scan reaches slot 148. With the
       relocated contiguous table this is the ONLY scan change needed —
       the Cave6 scan/name/row/deduct teleport wrappers of the retired
       multi-segment architecture are gone (their reader sites are
       re-based by the always-on
       :func:`_write_item_para_relocation_tokens`).

    The 256-entry relocated ITEM_DESC_PTR table populates slots 135..148
    in the :meth:`DigimonWorldPatchExtension.relocate_item_desc_ptr`
    procedure step, which is added to the procedure by
    :func:`_assemble_procedure` whenever this token writer is invoked
    (or when the recycle-shop token writer runs — the extension is
    idempotent for both).
    """

    # 1. Extended ITEM_PARA entries + 2. AP description strings.
    for i, location_name in enumerate(MERIT_SHOP_LOCATION_NAMES):
        resolved = _resolve_placed_item(world, location_name)
        if resolved is None:
            return  # option off — defensive, callers gate already
        ap_item_name, owner_name = resolved

        slot_id = MERIT_SHOP_AP_ITEM_ID_BASE + i
        _vanilla_id, _vanilla_name, vanilla_merit = MERIT_SHOP_VANILLA_ENTRIES[i]
        # In-game testing 2026-05-13: the merit shop's purchase deduct
        # path reads the ``value`` field (offset 0x14, 4 bytes) and
        # subtracts that from the player's merit counter — NOT the
        # ``meritValue`` field (offset 0x18) that the UI displays. So
        # the displayed price is purely cosmetic; the actual cost is
        # ``value``. For vanilla items this happens to work because
        # ``value`` is just a larger version of ``meritValue`` (e.g.
        # Rainbowhorn shows 500 merit, deducts 5000).
        #
        # For our AP entries we mirror the displayed cost: set both
        # fields to ``vanilla_merit`` so the player pays exactly the
        # number they see. (We can't match vanilla's value-is-10x-merit
        # convention because that would charge the player 10x the
        # displayed merit price, surprising and harsh.)
        entry_bytes = build_ap_item_para_entry(
            ap_item_name,
            price=vanilla_merit,
            merit_value=vanilla_merit,
        )
        patch.write_token(
            APTokenTypes.WRITE,
            ext_item_para_slot_bin_offset(slot_id),
            entry_bytes,
        )

        desc_bytes = build_ap_desc_string(owner_name)
        patch.write_token(
            APTokenTypes.WRITE,
            MERIT_AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN,
            desc_bytes,
        )

    # 3. Vanilla-item meritValue zero-outs (14 sites) — replace mode
    #    only. Coexist keeps the vanilla rows visible and purchasable.
    if replace:
        zero_merit = b"\x00\x00"
        for vanilla_id, _name, _merit in MERIT_SHOP_VANILLA_ENTRIES:
            merit_byte_offset = (
                vanilla_id * ROM_ITEM_TABLE_ENTRY_SIZE
                + ITEM_PARA_MERIT_VALUE_OFFSET
            )
            patch.write_token(
                APTokenTypes.WRITE,
                _table_byte_to_bin_flat(merit_byte_offset),
                zero_merit,
            )

    # 4. Extended wrapper bytes.
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET,
        ROM_MERIT_SHOP_EXT_WRAPPER_BYTES,
    )

    # 5. Override the v1 jal hijack at ROM_MERIT_SHOP_PATCH_OFFSET so it
    #    points at the extended wrapper instead of the N=1 wrapper. Token
    #    order matters: _write_merit_shop_wrapper_tokens (always-on)
    #    emits its jal token first; this token over-writes it.
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_MERIT_SHOP_PATCH_OFFSET,
        struct.pack(ROM_MERIT_SHOP_EXT_PATCH_FORMAT, ROM_MERIT_SHOP_EXT_PATCH_VALUE),
    )

    # 6. Scan-loop bound patch. (The retired multi-segment
    #    architecture's teleport-wrapper tokens — steps 7..14 of the
    #    old writer — are gone: the always-on relocation's plain
    #    reader-word patches cover the scan/name/row/deduct sites for
    #    every slot in the contiguous relocated table.)
    patch.write_token(
        APTokenTypes.WRITE,
        ROM_MERIT_SCAN_BOUND_OFFSET,
        struct.pack(ROM_MERIT_SCAN_BOUND_FORMAT, ROM_MERIT_SCAN_BOUND_VALUE),
    )


def _write_trn_gym_bonus_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Green Gym bonus reads the AP recruit mirror bits (739 / 771) instead of
    the vanilla 219 / 251 — two ``addiu`` immediates in TRN_REL.BIN. Always-on;
    see :data:`TRN_GYM_BONUS_WORD_PATCHES`."""

    for bin_offset, patched_word, _vanilla_word in TRN_GYM_BONUS_WORD_PATCHES:
        patch.write_token(APTokenTypes.WRITE, bin_offset, struct.pack("<I", patched_word))


def _write_field_record_words(
    patch: DigimonWorldProcedurePatch, record_bin_offset: int, first_word: int, values: tuple[int, ...],
) -> None:
    """Write consecutive s16 fields of a ``.MAP`` Digimon record, sector-aware.

    Fields are 2-byte aligned inside the file, so a single word never straddles a
    Mode2/2352 user-data boundary; runs of words that stay inside one sector are
    merged into one token.
    """

    run_start = field_record_bin_offset(record_bin_offset, first_word)
    run = bytearray()
    for index, value in enumerate(values):
        flat = field_record_bin_offset(record_bin_offset, first_word + index)
        if flat != run_start + len(run):
            patch.write_token(APTokenTypes.WRITE, run_start, bytes(run))
            run_start, run = flat, bytearray()
        run += struct.pack(FIELD_RECORD_FORMAT, value)
    patch.write_token(APTokenTypes.WRITE, run_start, bytes(run))


def _write_enemy_tokens(patch: DigimonWorldProcedurePatch, plan: EnemyPlan) -> None:
    """Enemy stat scaling + species randomization — pure data writes.

    * Scaled records: the nine contiguous stat words (hp .. bits).
    * Substituted species: the record ``type`` word, the four move words and
      four priority words of every record of that species on the screen, and
      the operand byte of every ``loadDigimon`` / ``setDigimon`` opcode for
      that species in the screen's MAPHEAD.SCN section (the game refuses to
      place an entity whose opcode operand disagrees with the record type).
    """

    for (map_id, slot), stats in sorted(plan.stat_overrides.items()):
        assert len(stats) == FIELD_RECORD_STAT_COUNT, (map_id, slot, stats)
        _write_field_record_words(patch, RECORD_INDEX[(map_id, slot)].bin_off, FIELD_RECORD_HP, tuple(stats))
    for (map_id, slot), (moves, prio) in sorted(plan.move_overrides.items()):
        assert len(moves) == 4 and len(prio) == 4, (map_id, slot, moves, prio)
        _write_field_record_words(
            patch, RECORD_INDEX[(map_id, slot)].bin_off, FIELD_RECORD_MOVES, tuple(moves) + tuple(prio),
        )
    for (map_id, species), substitute in sorted(plan.substitutions.items()):
        for record in RECORDS_BY_MAP[map_id]:
            if record.type == species:
                _write_field_record_words(patch, record.bin_off, FIELD_RECORD_TYPE, (substitute,))
        for site in SITES_BY_MAP.get(map_id, ()):
            if site.species == species:
                patch.write_token(
                    APTokenTypes.WRITE, maphead_bin_offset(site.file_off + 1), bytes([substitute]),
                )


def _write_user_data_tokens(
    patch: DigimonWorldProcedurePatch, base_bin_offset: int, table_offset: int, data: bytes,
) -> None:
    """WRITE tokens for ``data`` at user-data byte ``table_offset`` of the SLUS block that
    starts at ``base_bin_offset``, split wherever a Mode2/2352 sector boundary falls."""

    for flat, chunk in iter_user_data_chunks(base_bin_offset, table_offset, data):
        patch.write_token(APTokenTypes.WRITE, flat, chunk)


def _write_technique_tokens(patch: DigimonWorldProcedurePatch, plan: TechniquePlan) -> None:
    """Technique data + element matrix randomization — pure data writes into the SLUS.

    * Every changed ``MOVE_DATA`` record: the ``power .. statusChance`` span (bytes 4..12),
      with the untouched ``iframes`` / ``range`` / ``special`` bytes in between copied from
      vanilla.
    * The whole 7 x 7 affinity matrix when it changed.
    """

    start, end = MOVE_DATA_PATCH_SPAN
    for tech_id, values in sorted(plan.moves.items()):
        vanilla = MOVES_BY_ID[tech_id]
        span = struct.pack(
            "<hBBBBBBB", values.power, values.mp_cost, vanilla.iframes, vanilla.range, vanilla.element,
            values.status, values.accuracy, values.status_chance,
        )
        assert len(span) == end - start, len(span)
        _write_user_data_tokens(patch, ROM_MOVE_DATA_OFFSET, tech_id * MOVE_DATA_RECORD_SIZE + start, span)
    if plan.matrix is not None:
        assert len(plan.matrix) == ELEMENT_MATRIX_DIM and all(len(row) == ELEMENT_MATRIX_DIM for row in plan.matrix)
        _write_user_data_tokens(patch, ROM_ELEMENT_MATRIX_OFFSET, 0, bytes(v for row in plan.matrix for v in row))


def _write_drop_tokens(patch: DigimonWorldProcedurePatch, plan: DropPlan) -> None:
    """Enemy drop randomization — the ``dropItem`` / ``dropChance`` byte pair of every changed
    ``DIGIMON_DATA`` record."""

    for species_id, (item, chance) in sorted(plan.overrides.items()):
        _write_user_data_tokens(
            patch, ROM_DIGIMON_DATA_OFFSET, species_id * DIGIMON_DATA_RECORD_SIZE + DIGIMON_DATA_DROP_ITEM_OFFSET,
            bytes((item, chance)),
        )


def _write_species_list_tokens(patch: DigimonWorldProcedurePatch, plan: ListPlan) -> None:
    """Species technique-list randomization — the 16 ``moves`` bytes of every changed
    ``DIGIMON_DATA`` record."""

    for species_id, moves in sorted(plan.lists.items()):
        assert len(moves) == DIGIMON_DATA_MOVES_COUNT, (species_id, moves)
        _write_user_data_tokens(
            patch, ROM_DIGIMON_DATA_OFFSET, species_id * DIGIMON_DATA_RECORD_SIZE + DIGIMON_DATA_MOVES_OFFSET,
            bytes(moves),
        )


def _write_gift_tokens(patch: DigimonWorldProcedurePatch, plan: GiftPlan) -> None:
    """NPC gift randomization — script-byte writes.

    * Technique teaches: the ``learnMove`` operand and the "already known?" check
      operand of each changed site both get the new technique id.
    * Tokomon: the item and count bytes of each changed ``giveItem``.
    """

    for site, tech in sorted(plan.tech_gifts.items()):
        patch.write_token(APTokenTypes.WRITE, ROM_LEARN_MOVE_OFFSETS[site] + 1, bytes([tech]))
        patch.write_token(APTokenTypes.WRITE, ROM_CHECK_MOVE_OFFSETS[site], bytes([tech]))
    for site, (item, count) in sorted(plan.tokomon_gifts.items()):
        patch.write_token(
            APTokenTypes.WRITE, ROM_TOKOMON_ITEM_OFFSETS[site] + TOKOMON_GIFT_VALUE_OFFSET, bytes((item, count)),
        )


def _write_evolution_tokens(patch: DigimonWorldProcedurePatch, plan: EvolutionPlan, type_lock_unlocks: bool) -> None:
    """Digivolution randomization — data writes into the three SLUS tables plus the
    special-evolution bytes.

    * ``EVO_PATHS_DATA`` rows (11 bytes, species 1..62) for every changed tree row.
    * ``EVO_REQ_DATA`` rows (the 27 meaningful bytes; the pad stays) for every changed
      requirements row.
    * ``EVO_GAINS_DATA`` gains (the six words; the target word stays) for every changed row.
    * One byte per special-evolution site. The Toy Town gate's Monzaemon byte is left alone
      when ``type_lock_unlocks`` is on: that option's 4-byte write covers it and removes the
      gate altogether (the standalone's ``toyTownWorkaround``).
    """

    for species, path in sorted(plan.paths.items()):
        row = struct.pack(EVO_PATH_FORMAT, *path.frm, *path.to)
        _write_user_data_tokens(patch, ROM_EVO_TO_FROM.offset, (species - 1) * EVO_PATH_ROW_SIZE, row)
    for species, reqs in sorted(plan.requirements.items()):
        row = struct.pack(EVO_REQ_FORMAT, *reqs)
        _write_user_data_tokens(patch, ROM_EVO_REQUIREMENTS.offset, species * EVO_REQ_ROW_SIZE, row)
    for species, gains in sorted(plan.gains.items()):
        row = struct.pack(EVO_GAIN_FORMAT, *gains)
        _write_user_data_tokens(patch, ROM_EVO_STAT_GAINS.offset, species * EVO_GAIN_ROW_SIZE, row)
    for index, target in sorted(plan.special.items()):
        offsets, _vanilla, _source = ROM_SPECIAL_EVO[index]
        for offset in offsets:
            if offset == ROM_SPECIAL_EVO_TOY_TOWN_GATE_OFFSET and type_lock_unlocks:
                continue
            patch.write_token(APTokenTypes.WRITE, offset, bytes([target]))


def brain_learn_table(tier_one: bool, increase: bool) -> bytes:
    """The brain-training learn-chance table (8 tiers x 3) after the two options that touch it,
    applied in the standalone's order: tier-1 unlock first, then the doubling (0 -> 5)."""

    table = bytearray(ROM_TECH_LEARN_BRAIN_VANILLA)
    if tier_one:
        table[0] = BRAIN_TIER_ONE_LEARN_CHANCE
    if increase:
        table = bytearray(
            min(v * LEARN_CHANCE_MULTIPLIER, 0xFF) if v else BRAIN_LEARN_ZERO_REPLACEMENT for v in table
        )
    return bytes(table)


def _write_standalone_patch_tokens(patch: DigimonWorldProcedurePatch, options: DigimonWorldOptions) -> None:
    """The standalone randomizer's remaining QoL patches, each behind its own toggle.

    Sources: ``references/digimon_world_randomizer/digimon/handler.py`` ``_applyPatchAllowDrop``
    (2441), ``_applyPatchLearnTierOne`` (2464), ``_applyPatchLearnChance`` (2473),
    ``_applyPatchUnrigSlots`` (2594), ``_applyPatchLearnMoveAndCommand`` (2756),
    ``_applyPatchDVChipDescription`` (2769). All are data or single-word rewrites at the
    standalone's offsets; the vanilla bytes are pinned in ``data/addresses.py``.
    """

    if options.quest_items_droppable:
        for item_id in ROM_QUEST_ITEMS_NOT_DROPABLE:
            table_offset = item_id * ROM_ITEM_TABLE_ENTRY_SIZE + ROM_ITEM_DROPABLE_BYTE_OFFSET
            _write_user_data_tokens(patch, ROM_ITEM_TABLE_BASE, table_offset, b"\x01")
    if options.increase_learn_chance:
        doubled = bytes(min(v * LEARN_CHANCE_MULTIPLIER, 0xFF) for v in ROM_TECH_LEARN_BATTLE_VANILLA)
        _write_user_data_tokens(patch, ROM_TECH_LEARN_BATTLE.offset, 0, doubled)
    if options.brain_training_tier_one or options.increase_learn_chance:
        table = brain_learn_table(bool(options.brain_training_tier_one), bool(options.increase_learn_chance))
        _write_user_data_tokens(patch, ROM_TECH_LEARN_BRAIN.offset, 0, table)
    if options.unrig_slots:
        for offset, word, _vanilla in ROM_UNRIG_SLOTS_WORD_PATCHES:
            patch.write_token(APTokenTypes.WRITE, offset, struct.pack("<I", word))
    if options.learn_move_and_command:
        words = struct.pack("<II", *ROM_LEARN_MOVE_AND_COMMAND_WORDS)
        patch.write_token(APTokenTypes.WRITE, ROM_LEARN_MOVE_AND_COMMAND_OFFSET, words)
    if options.fix_dv_chip_text:
        for offset, text, _vanilla in ROM_DV_CHIP_TEXT_PATCHES:
            patch.write_token(APTokenTypes.WRITE, offset, text.ljust(ROM_DV_CHIP_TEXT_LENGTH, b"\x00"))


def _write_ground_item_params(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
) -> None:
    """Stage the ground-item-shuffle params blob in the patch zip.

    Generation does **not** read the source BIN; per-spot vanilla item
    ids and ITEM_PARA prices are read from the local ROM at apply time
    by :meth:`DigimonWorldPatchExtension.shuffle_ground_items`. This
    helper just writes the seed + scope-flag JSON to the zip — the
    procedure step itself is added later by :func:`_assemble_procedure`.
    """

    options = world.options
    params = {
        "seed": world.random.getrandbits(64),
        "food_only": bool(int(options.ground_items_food_only.value)),
        "match_value": bool(int(options.ground_items_match_value.value)),
        "value_cutoff": int(options.ground_items_value_cutoff.value),
    }
    patch.write_file("ground_items.json", json.dumps(params).encode("ascii"))


_LEVEL_OPTION_TO_LEVEL_BYTE = (
    ("starter_allow_fresh", LEVEL_FRESH),
    ("starter_allow_in_training", LEVEL_IN_TRAINING),
    ("starter_allow_rookie", LEVEL_ROOKIE),
    ("starter_allow_champion", LEVEL_CHAMPION),
    ("starter_allow_ultimate", LEVEL_ULTIMATE),
)


def _write_starter_params(
    patch: DigimonWorldProcedurePatch,
    world: DigimonWorldWorld,
) -> None:
    """Stage the starter-shuffle params blob in the patch zip.

    Collapses the five level-toggle options into a single
    ``allowed_levels`` list (DW1 level-byte values 0x01..0x05) for the
    apply-time picker. The picker also receives the seed and the
    weakest-tech flag.
    """

    options = world.options
    allowed_levels = [
        level_byte
        for option_name, level_byte in _LEVEL_OPTION_TO_LEVEL_BYTE
        if int(getattr(options, option_name).value)
    ]
    params = {
        "seed": world.random.getrandbits(64),
        "allowed_levels": allowed_levels,
        "use_weakest_tech": bool(int(options.starter_use_weakest_tech.value)),
    }
    patch.write_file("starters.json", json.dumps(params).encode("ascii"))


def _assemble_procedure(
    patch: DigimonWorldProcedurePatch,
    *,
    shuffle_ground_items: bool,
    shuffle_starters: bool,
    relocate_item_desc_ptr: bool,
) -> None:
    """Mutate the per-instance procedure to include opt-in extension steps.

    Order: ``verify_rom_hash`` -> ``apply_tokens`` ->
    ``requantize_rainbowhorn`` (always-on) ->
    ``relocate_item_desc_ptr`` (if any shop mode != off) -> any opt-in
    shufflers in declaration order -> ``recalc_edc``.

    The shufflers operate independently (one rewrites map-spawn item
    bytes, the other rewrites starter bytes) and don't touch each
    other's target offsets, so their relative order doesn't matter.

    ``relocate_item_desc_ptr`` runs **after** ``apply_tokens`` so the
    AP description strings (written by token) are already in place,
    and **before** the shufflers so any reads they do via
    :func:`read_item_table_user_data` still see the freshly-written
    extended ITEM_PARA entries (slots 128..134) — though in practice
    the shufflers cap at slot 127 so this ordering is defensive.
    """

    extensions: list[tuple[str, list[str]]] = []
    if relocate_item_desc_ptr:
        extensions.append(("relocate_item_desc_ptr", []))
    if shuffle_ground_items:
        extensions.append(("shuffle_ground_items", ["ground_items.json"]))
    if shuffle_starters:
        extensions.append(("shuffle_starters", ["starters.json"]))
    if not extensions:
        return  # default class-level procedure already correct
    patch.procedure = [
        ("verify_rom_hash", []),
        ("apply_tokens", ["token_data.bin"]),
        # Always-on AP-logo companion (also in the class-level default
        # procedure): re-indexes Rainbowhorn's tile to CLUT 8.
        ("requantize_rainbowhorn", []),
        *extensions,
        ("recalc_edc", []),
    ]


# =============================================================================
# Generation-time helper (called from world.py:generate_output)
# =============================================================================

def write_patch(world: DigimonWorldWorld, output_directory: str) -> None:
    """Build and write a ``.apdw1`` for the current player slot.

    Tokens written:

    * 32 bytes at :data:`VOLUME_ID_OFFSET` — the AP-marked volume id.
    * Five softlock-fix patches. (The standalone randomizer's PP-calc
      rewrite is no longer written — it patched the *prosperity* loop to
      read a field only the standalone seeds; retired 2026-08-28.)
    * Per-chest item byte rewrites + chestGiveItem wrapper + chest
      pickup ``jal`` redirect (Phase 5 piece A).
    * setTrigger wrapper installation + entry redirect (Phase 5
      piece C — splits "fight completed" from "Digimon joined city").
    * Option-gated QoL patches (skip intro, type-lock unlocks, spawn
      rate boost). The two RAM-side QoL options (fast Drimogemon, easy
      Monochromon) are enforced by the client via slot_data flags;
      they do not write tokens here.
    """

    patch = DigimonWorldProcedurePatch(
        player=world.player,
        player_name=world.multiworld.player_name[world.player],
    )

    seed_name = world.multiworld.seed_name
    volume_id = _build_volume_id(f"{seed_name}-{world.player}")
    assert len(volume_id) == VOLUME_ID_LENGTH, (len(volume_id), VOLUME_ID_LENGTH)
    patch.write_token(APTokenTypes.WRITE, VOLUME_ID_OFFSET, volume_id)

    # Plan A revised (per user observation):
    #   - Cutscene end → bit 200+X = 1 (vanilla; we don't redirect).
    #   - AP delivery → bit 720+X = 1 (client writes BEATEN_BLOCK).
    #   - Per-Digimon city-visibility ROM patches make the city gate
    #     read trigger 720+X instead of 200+X. So city is gated on
    #     "AP delivered", wild is gated on "cutscene completed".
    # The setTrigger wrapper and changeMap wrapper are no longer needed.
    _write_recruit_trigger_redirect_tokens(patch)
    _write_softlock_fix_tokens(patch)
    # ChestRandomization off: chests retain vanilla items + vanilla
    # giveItem flow, so the patcher emits no chest-related tokens.
    if int(world.options.chest_randomization.value):
        _write_chest_item_tokens(patch, world)
    _write_field_spawn_trigger_patches(patch)  # Plan A: per-Digimon
    _write_gettopcity_trigger_patches(patch)  # Plan A: Top City variants
    _write_birdra_flight_table_tokens(patch)
    # Region-gate enforcement — no-op unless region_locking locks
    # something this seed. Must run AFTER _write_birdra_flight_table_tokens
    # so the Great-Canyon entry-0 trigger redirect isn't clobbered
    # (token order = insertion order; the two families write disjoint
    # offsets today, but keep the ordering contract anyway).
    _write_region_gate_tokens(patch, world)
    _write_old_fishrod_remap_tokens(patch)  # always-on; decouples cutscene from rod ownership
    _write_coelamon_cutscene_remap_tokens(patch)  # always-on; shore machine -> trigger 779
    _write_mansion_key_neuter_tokens(patch)  # always-on; vanilla key give -> AP location signal
    _write_frig_key_neuter_tokens(patch)  # always-on; same shape as Mansion Key
    _write_gear_neuter_tokens(patch)  # always-on; same shape as Mansion/Frig Key
    _write_rain_plant_neuter_tokens(patch)  # always-on; single-site giveItem -> setTrigger
    _write_blue_flute_neuter_tokens(patch)  # always-on; same shape as Mansion/Frig/Gear
    _write_leomonstone_neuter_tokens(patch)  # always-on; 7 sites across 3 ROM copies + orphan
    _write_arena_cup_neuter_tokens(patch)  # always-on; 14 sites x N copies (no-op until ROM_ARENA_SECTION_51_BASES is set)
    _write_merit_shop_wrapper_tokens(patch)  # always-on; engine-hook for Merit-Shop purchases
    _write_trn_gym_bonus_tokens(patch)  # always-on; gym bonus follows AP recruits (TRN_REL immediates)
    # ITEM_PARA 256-slot relocation — always-on (heap claim + boot seed
    # hook + reader re-bases + seed zero-fill). Must run BEFORE the
    # recycle/merit writers so their ext-entry tokens overwrite the
    # seed zero-fill (token order = insertion order).
    _write_item_para_relocation_tokens(patch)
    if int(world.options.lava_cave_access.value) != 0:  # 0 = vanilla
        _write_lava_cave_gate_tokens(patch)
    # Bridge shuffled-mode patches (option value 2 = shuffled).
    if int(world.options.bridge_unlock.value) == 2:
        _write_coelamon_gate_tokens(patch)
    if int(world.options.great_canyon_unlock.value) == 2:
        _write_great_canyon_cutscene_tokens(patch)
    # Mt. Infinity prosperity threshold — always-on (writes the same 50
    # at default, otherwise the configured threshold).
    _write_prosperity_goal_token(
        patch, int(world.options.prosperity_goal.value),
    )

    options = world.options
    # Digivolution randomization — resolved in generate_early. Must run
    # BEFORE _write_type_lock_unlock_tokens: the Toy Town unlock's 4-byte
    # write covers the Monzaemon special-evolution gate byte (the writer
    # also skips that site when the unlock is on).
    if not world.evolution_plan.empty:
        _write_evolution_tokens(patch, world.evolution_plan, bool(options.type_lock_unlocks))
    if options.skip_intro:
        _write_skip_intro_tokens(patch)
    if options.item_stat_gain:
        _write_item_stat_gain_token(patch)
    if options.type_lock_unlocks:
        _write_type_lock_unlock_tokens(patch)
    _write_spawn_rate_boost_tokens(patch, int(options.spawn_rate_boost.value))
    _write_combat_multiplier_tokens(
        patch, int(options.combat_stat_multiplier.value),
    )
    if int(options.vending_locations.value):
        _write_vending_tokens(patch, world)
    # Card-trade merit multiplier — pure QoL data rewrite; 1 = vanilla
    # table, no tokens.
    if int(options.card_trade_multiplier.value) > 1:
        _write_card_trade_multiplier_tokens(
            patch, int(options.card_trade_multiplier.value),
        )
    # Piximon's Training Manual location — opt-in §82 giveItem neuter.
    if int(options.piximon_manual_location.value):
        _write_piximon_manual_tokens(patch)
    # Enemy stat scaling / species randomization — resolved in post_fill
    # (needs the finished placement for the sphere walk); no tokens when
    # both options are off.
    if not world.enemy_plan.empty:
        _write_enemy_tokens(patch, world.enemy_plan)
    # Technique data / element matrix and enemy drops — resolved in
    # generate_early (static SLUS tables, no placement dependency).
    if not world.technique_plan.empty:
        _write_technique_tokens(patch, world.technique_plan)
    if not world.drop_plan.empty:
        _write_drop_tokens(patch, world.drop_plan)
    if not world.list_plan.empty:
        _write_species_list_tokens(patch, world.list_plan)
    if not world.gift_plan.empty:
        _write_gift_tokens(patch, world.gift_plan)

    # Shopsanity (recycle / item / secret / merit, each off | coexist |
    # replace). The common infrastructure — extended boot hook, builder
    # wrapper, extended giveItem wrapper, config, desc-ptr callsites,
    # icon clamp — is emitted whenever ANY shop mode != off; each
    # enabled shop then adds its per-seed ext ITEM_PARA entries. Must
    # run AFTER _write_item_para_relocation_tokens (the extended hook
    # token overwrites the base hook token; ext entries overwrite the
    # seed zero-fill) and, for merit, AFTER
    # _write_merit_shop_wrapper_tokens (jal-hijack override site).
    from .options import get_shop_modes
    shop_modes = get_shop_modes(options)
    if shop_modes.any_enabled:
        _write_shopsanity_common_tokens(patch, shop_modes)
        # Per-slot icon-id table for the setItemTexture wrapper —
        # placement-dependent (local items keep their native shop icon;
        # AP abstractions and other players' items show the AP logo).
        # Gated with the wrapper: ext ids never render without
        # shopsanity, so a table without its consumer would be inert.
        _write_ap_icon_id_table_tokens(patch, world)
        prices = _resolve_shop_prices(world)
        if shop_modes.recycle:
            _write_recycle_shop_tokens(patch, world, prices)
        if shop_modes.item:
            _write_item_shop_tokens(patch, world, prices)
        if shop_modes.secret:
            _write_secret_shop_tokens(patch, world, prices)
        if shop_modes.merit:
            _write_merit_shop_locations_tokens(
                patch, world, replace=shop_modes.merit == SHOP_MODE_REPLACE,
            )

    # The standalone's QoL patches — after every table writer above so the
    # quest-item ``dropable`` bytes land on top of any full-entry ITEM_PARA
    # token (token order = insertion order).
    _write_standalone_patch_tokens(patch, options)

    do_shuffle_ground_items = bool(int(options.randomize_ground_items.value))
    do_shuffle_starters = bool(int(options.randomize_starter.value))
    if do_shuffle_ground_items:
        _write_ground_item_params(patch, world)
    if do_shuffle_starters:
        _write_starter_params(patch, world)
    _assemble_procedure(
        patch,
        shuffle_ground_items=do_shuffle_ground_items,
        shuffle_starters=do_shuffle_starters,
        relocate_item_desc_ptr=shop_modes.any_enabled,
    )

    patch.write_file("token_data.bin", patch.get_token_binary())

    out = Path(output_directory) / f"{world.multiworld.get_out_file_name_base(world.player)}.apdw1"
    patch.write(str(out))


__all__ = [
    "GAME_NAME",
    "VOLUME_ID_LENGTH",
    "VOLUME_ID_OFFSET",
    "VOLUME_ID_PREFIX",
    "DigimonWorldPatchExtension",
    "DigimonWorldProcedurePatch",
    "DigimonWorldSettings",
    "write_patch",
]
