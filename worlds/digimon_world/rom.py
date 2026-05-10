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
    CHEST_NAME_TO_ROM_OFFSETS,
    ROM_ANIM_ID_FORMAT,
    ROM_AP_ITEM_ENTRY_BYTES,
    ROM_AP_ITEM_ENTRY_OFFSET,
    ROM_BIN_BYTES,
    ROM_BIN_SHA1,
    ROM_BIRDRA_FLIGHT_TABLE_FORMAT,
    ROM_BIRDRA_FLIGHT_TABLE_PATCHES,
    ROM_CHANGEMAP_PATCH_FORMAT,
    ROM_CHANGEMAP_PATCH_OFFSET,
    ROM_CHANGEMAP_PATCH_VALUE,
    ROM_CHANGEMAP_WRAPPER_BYTES,
    ROM_CHANGEMAP_WRAPPER_OFFSET,
    ROM_CHEST_GIVEITEM_PATCH_FORMAT,
    ROM_CHEST_GIVEITEM_PATCH_OFFSET,
    ROM_CHEST_GIVEITEM_PATCH_VALUE,
    ROM_CHEST_GIVEITEM_WRAPPER_BYTES,
    ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
    ROM_CHEST_ITEM_FORMAT,
    ROM_CITY_BITMAP_BYTES,
    ROM_CITY_BITMAP_OFFSET,
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
    ROM_DIGIMON_ID_FORMAT,
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
    ROM_GACHA_MP_FLOPPY_FIX_BYTES,
    ROM_GACHA_MP_FLOPPY_FIX_OFFSET,
    ROM_GETTOPCITY_TRIGGER_FORMAT,
    ROM_GETTOPCITY_TRIGGER_PATCHES,
    ROM_GREAT_CANYON_CUTSCENE_OFFSETS,
    ROM_GREAT_CANYON_CUTSCENE_VALUE,
    ROM_ISTRIGGERSET_PATCH_FORMAT,
    ROM_ISTRIGGERSET_PATCH_OFFSET,
    ROM_ISTRIGGERSET_PATCH_VALUE,
    ROM_ISTRIGGERSET_WRAPPER_BYTES,
    ROM_ISTRIGGERSET_WRAPPER_OFFSET,
    ROM_LAVA_CAVE_GATE_OFFSETS,
    ROM_LAVA_CAVE_GATE_VALUE,
    ROM_MAP_ITEM_OFFSETS,
    ROM_PROSPERITY_GOAL_FORMAT,
    ROM_PROSPERITY_GOAL_OFFSET,
    ROM_OGREMON_SOFTLOCK_FORMAT,
    ROM_OGREMON_SOFTLOCK_OFFSETS,
    ROM_OGREMON_SOFTLOCK_VALUE,
    ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE,
    ROM_BLUE_FLUTE_GIVEITEM_OFFSETS,
    ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE,
    ROM_FRIG_KEY_GIVEITEM_OFFSETS,
    ROM_GEAR_GIVEITEM_NEUTER_VALUE,
    ROM_GEAR_GIVEITEM_OFFSETS,
    ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE,
    ROM_LEOMONSTONE_GIVEITEM_OFFSETS,
    MERIT_SHOP_DISPATCH,
    AP_ITEM_DESC_BIN_OFFSET,
    AP_ITEM_DESC_PTR_BIN_OFFSET,
    AP_ITEM_DESC_PTR_VALUE,
    AP_ITEM_DESC_STRING,
    AP_ITEM_ICON_BLANK_BIN_OFFSETS,
    AP_ITEM_ICON_ROW_BYTES,
    ROM_AMAZING_ROD_HIDE_BYTES,
    ROM_AMAZING_ROD_HIDE_OFFSET,
    ROM_AP_ITEM_DESC_PTR_PATCH_FORMAT,
    ROM_AP_SHOP_BOUGHT_ENTRY_BYTES,
    ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET,
    ROM_AP_SHOP_PRESALE_NAME_BYTES,
    ROM_MERIT_SHOP_PATCH_FORMAT,
    ROM_MERIT_SHOP_PATCH_OFFSET,
    ROM_MERIT_SHOP_PATCH_VALUE,
    ROM_MERIT_SHOP_WRAPPER_BYTES,
    ROM_MERIT_SHOP_WRAPPER_OFFSET,
    _merit_shop_presale_name_offset,
    ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE,
    ROM_MANSION_KEY_GIVEITEM_OFFSETS,
    ROM_OLD_FISHROD_REMAP_OFFSETS,
    ROM_OLD_FISHROD_REMAP_VALUE,
    ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE,
    ROM_RAIN_PLANT_GIVEITEM_OFFSETS,
    ROM_STEAK_SPAWN_NEUTER_OFFSETS,
    ROM_STEAK_SPAWN_NEUTER_VALUE,
    ROM_PP_CALC_PATCH_FORMAT,
    ROM_PP_CALC_PATCH_OFFSET,
    ROM_PP_CALC_PATCH_VALUE,
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
    ROM_STARTER_CHK_DIGIMON,
    ROM_STARTER_EQUIP_ANIM,
    ROM_STARTER_LEARN_TECH,
    ROM_STARTER_SET_DIGIMON,
    ROM_STARTER_STAT_CHK_DIGIMON,
    ROM_TECH_ID_FORMAT,
    ROM_TECHNIQUE_DATA,
    ROM_UNLOCK_GREYLORD_OFFSETS,
    ROM_UNLOCK_GREYLORD_VALUE,
    ROM_UNLOCK_ICE_OFFSETS,
    ROM_UNLOCK_ICE_VALUE,
    ROM_UNLOCK_TOY_TOWN_FORMAT,
    ROM_UNLOCK_TOY_TOWN_OFFSETS,
    ROM_UNLOCK_TOY_TOWN_VALUE,
    ROM_UNLOCK_TYPE_LOCK_FORMAT,
    VENDING_MACHINES,
    build_combat_multiplier_trampolines,
    encode_set_trigger,
    read_digimon_table_user_data,
    read_item_table_user_data,
    read_technique_table_user_data,
)
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

if TYPE_CHECKING:
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
    3. ``shuffle_ground_items`` — *optional, per-instance.* Inserted by
       :func:`_assemble_procedure` when the
       :class:`worlds.digimon_world.options.GroundItemRandomization`
       option is on. Reads ``ground_items.json`` for seed and pool
       scope flags, parses ITEM_PARA, rewrites every map-spawn item-id
       byte. Defaults to absent — vanilla ground items unchanged.
    4. ``shuffle_starters`` — *optional, per-instance.* Inserted by
       :func:`_assemble_procedure` when the
       :class:`worlds.digimon_world.options.StarterRandomization`
       option is on. Reads ``starters.json``, parses
       DIGIMON_PARA + TECH_PARA, rewrites the two starter slots'
       Digimon ids and learn-tech / equip-anim bytes.
    5. ``recalc_edc`` — diff-recalc EDC/ECC for any sector whose data
       was touched.
    """

    game: ClassVar[str] = GAME_NAME
    hash = ROM_BIN_SHA1
    patch_file_ending = ".apdw1"
    result_file_ending = ".cue"

    procedure: ClassVar[list[tuple[str, list[str]]]] = [
        ("verify_rom_hash", []),
        ("apply_tokens", ["token_data.bin"]),
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
    """Install the setTrigger filter wrapper for the recruit split.

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


def _write_pp_calc_patch_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Emit the PP-calc function rewrite from the standalone randomizer.

    Vanilla DW1's PP-lookup function is incompatible with arbitrary
    recruit assignment: a remapped Digimon can land in an evolution
    slot that produces 0-PP techniques. The standalone replaces the
    function with a flat-addressed version that's stable under
    remapping. We always write the patch, regardless of which recruits
    are remapped — it's a strict superset of vanilla behavior on the
    unshuffled subset, since the function still derives PP from the
    same Digimon parameter table.
    """

    patch_bytes = struct.pack(ROM_PP_CALC_PATCH_FORMAT, *ROM_PP_CALC_PATCH_VALUE)
    patch.write_token(APTokenTypes.WRITE, ROM_PP_CALC_PATCH_OFFSET, patch_bytes)


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
    """Install the changeMap wrapper for race-free city/field bit sync.

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
    """Install the isTriggerSet wrapper that redirects recruit-bit reads.

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
    # 7. Blank slot 83's icon in ITEM.TIM (Electo Ring sprite, never
    #    seen elsewhere in the game). 16 row writes, sector-aware.
    for bin_offset in AP_ITEM_ICON_BLANK_BIN_OFFSETS:
        patch.write_token(
            APTokenTypes.WRITE,
            bin_offset,
            AP_ITEM_ICON_ROW_BYTES,
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


def _write_steak_spawn_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace the ``spawnItem 122 48 32`` in Script 35 Section_254 with a
    ``jumpTo 150`` (lands on the section's terminal ``endSection``).

    Unlike the rod / Mansion / Frig Key cutscenes, vanilla DW1 hands the
    player Steak by spawning it as a map item rather than via a
    ``giveItem`` opcode. Section_254 of the Overdell map (Script 35)
    spawns Steak at coordinates (48, 32) when ``trigger(348) ==
    true AND trigger(128) == false`` — i.e. when the player has used
    the fridge (with Frig Key) but hasn't yet given the Steak to
    Myotismon.

    In AP rando, vanilla Steak is bypassed: only AP delivery (bank
    slot 122 via :func:`_make_bank_deliverer`) puts Steak in the
    player's hands. The 6-byte ``spawnItem`` is rewritten as 4-byte
    ``jumpTo 150`` + 2-byte unreachable filler — execution skips
    over the spawn and ends the section. Trigger 348 (set by the
    fridge cutscene itself, not by us) remains the AP location signal.

    See :data:`ROM_STEAK_SPAWN_NEUTER_OFFSETS` /
    :data:`ROM_STEAK_SPAWN_NEUTER_VALUE` for byte layout.
    """

    for offset in ROM_STEAK_SPAWN_NEUTER_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_STEAK_SPAWN_NEUTER_VALUE)


def _write_frig_key_neuter_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace both ``giveItem 123 1`` calls in Script 63 Section_5
    (Myotismon Frig-Key dialog) with ``setTrigger 104``.

    Same shape as the Mansion Key neuter: vanilla Frig Key delivery
    bypassed; only AP delivery (bank slot 123 via
    :func:`_make_bank_deliverer`) puts the key in the player's hands.
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
    delivery (bank slot 119 via :func:`_make_bank_deliverer`). Both
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
    """

    for offset in ROM_COELAMON_GATE_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset, ROM_COELAMON_GATE_VALUE)


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

    The slot is a 16-bit LE comparand (vanilla ``32 00`` = 50). We
    write the threshold the same way; values 20..100 fit in 1 byte so
    the high byte is always 0.
    """

    patch.write_token(
        APTokenTypes.WRITE,
        ROM_PROSPERITY_GOAL_OFFSET,
        struct.pack(ROM_PROSPERITY_GOAL_FORMAT, threshold),
    )


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


# =============================================================================
# QoL patcher helpers (Phase 5 polish; opt-in via player options)
# =============================================================================

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
) -> None:
    """Mutate the per-instance procedure to include opt-in shuffle steps.

    Order: ``verify_rom_hash`` -> ``apply_tokens`` -> any opt-in
    shufflers in declaration order -> ``recalc_edc``. The shufflers
    operate independently (one rewrites map-spawn item bytes, the
    other rewrites starter bytes) and don't touch each other's
    target offsets, so their relative order doesn't matter.
    """

    extensions: list[tuple[str, list[str]]] = []
    if shuffle_ground_items:
        extensions.append(("shuffle_ground_items", ["ground_items.json"]))
    if shuffle_starters:
        extensions.append(("shuffle_starters", ["starters.json"]))
    if not extensions:
        return  # default class-level procedure already correct
    patch.procedure = [
        ("verify_rom_hash", []),
        ("apply_tokens", ["token_data.bin"]),
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
    * The 44-byte PP-calc function rewrite from the standalone
      randomizer at :data:`ROM_PP_CALC_PATCH_OFFSET`.
    * Five softlock-fix patches.
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
    _write_pp_calc_patch_tokens(patch)
    _write_softlock_fix_tokens(patch)
    # ChestRandomization off: chests retain vanilla items + vanilla
    # giveItem flow, so the patcher emits no chest-related tokens.
    if int(world.options.chest_randomization.value):
        _write_chest_item_tokens(patch, world)
    _write_field_spawn_trigger_patches(patch)  # Plan A: per-Digimon
    _write_gettopcity_trigger_patches(patch)  # Plan A: Top City variants
    _write_birdra_flight_table_tokens(patch)
    _write_old_fishrod_remap_tokens(patch)  # always-on; decouples cutscene from rod ownership
    _write_mansion_key_neuter_tokens(patch)  # always-on; vanilla key give -> AP location signal
    _write_frig_key_neuter_tokens(patch)  # always-on; same shape as Mansion Key
    _write_steak_spawn_neuter_tokens(patch)  # always-on; spawn-replacement (6-byte patch)
    _write_gear_neuter_tokens(patch)  # always-on; same shape as Mansion/Frig Key
    _write_rain_plant_neuter_tokens(patch)  # always-on; single-site giveItem -> setTrigger
    _write_blue_flute_neuter_tokens(patch)  # always-on; same shape as Mansion/Frig/Gear
    _write_leomonstone_neuter_tokens(patch)  # always-on; 7 sites across 3 ROM copies + orphan
    _write_merit_shop_wrapper_tokens(patch)  # always-on; engine-hook for Merit-Shop purchases
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
    if options.skip_intro:
        _write_skip_intro_tokens(patch)
    if options.type_lock_unlocks:
        _write_type_lock_unlock_tokens(patch)
    _write_spawn_rate_boost_tokens(patch, int(options.spawn_rate_boost.value))
    _write_combat_multiplier_tokens(
        patch, int(options.combat_stat_multiplier.value),
    )
    if int(options.vending_locations.value):
        _write_vending_tokens(patch, world)

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
