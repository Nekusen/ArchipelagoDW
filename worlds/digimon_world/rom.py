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
import os
import struct
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

import settings
from worlds.Files import APPatchExtension, APProcedurePatch, APTokenMixin, APTokenTypes

from .data import edc
from .data.addresses import (
    ROM_AP_ITEM_ENTRY_BYTES,
    ROM_AP_ITEM_ENTRY_OFFSET,
    ROM_BIN_BYTES,
    ROM_BIN_SHA1,
    ROM_CHEST_ITEM_FORMAT,
    ROM_CHEST_ITEM_OFFSETS,
    ROM_CHEST_ITEM_VALUE,
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
    ROM_OGREMON_SOFTLOCK_FORMAT,
    ROM_OGREMON_SOFTLOCK_OFFSETS,
    ROM_OGREMON_SOFTLOCK_VALUE,
    ROM_PP_CALC_PATCH_FORMAT,
    ROM_PP_CALC_PATCH_OFFSET,
    ROM_PP_CALC_PATCH_VALUE,
    ROM_RECRUIT_TRIGGER_FORMAT,
    ROM_RECRUIT_TRIGGERS,
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
       and applies WRITE/COPY/RLE/AND/OR/XOR tokens. v1 has exactly one
       token: a 32-byte WRITE to the PVD volume id.
    3. ``recalc_edc`` — diff-recalc EDC/ECC for any sector whose data
       was touched. With v1's single 32-byte write at sector 16, this
       runs in milliseconds: only sector 16 differs.
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

def _write_recruit_remap_tokens(
    patch: DigimonWorldProcedurePatch,
    remap: dict[str, str],
) -> None:
    """Emit closed-shuffle trigger writes for each shuffleable recruit spawn.

    ``remap`` is keyed by the spawn-point Digimon and valued by its
    closed-shuffle partner Digimon. The patcher writes the partner's
    vanilla trigger ID at all of the spawn's ROM offsets, so completing
    the spawn's encounter sets the partner's recruit bit (visual
    randomization in-game).

    Identity entries (``X -> X``) emit no tokens — the vanilla bytes
    already carry the right trigger ID.
    """

    for spawn_name, partner_name in remap.items():
        if spawn_name == partner_name:
            continue
        spawn_entry = ROM_RECRUIT_TRIGGERS[spawn_name]
        partner_entry = ROM_RECRUIT_TRIGGERS[partner_name]
        trigger_bytes = struct.pack(
            ROM_RECRUIT_TRIGGER_FORMAT, partner_entry.trigger_id,
        )
        for offset in spawn_entry.trigger_offsets:
            patch.write_token(APTokenTypes.WRITE, offset, trigger_bytes)


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


def _write_chest_item_tokens(patch: DigimonWorldProcedurePatch) -> None:
    """Replace every chest's vanilla reward with the AP sentinel item.

    Two parts:

    1. For each chest's ``spawnChest`` script entry (opcode 0x75 + 1-byte
       item ID), overwrite the item-ID byte to the AP sentinel
       (id 129). AP-routed items remain the meaningful chest reward;
       the in-game pickup is a transient placeholder we wipe in the
       next client tick.
    2. Write a clean 32-byte item-table entry for id 129 with the name
       "AP ITEM" so the chest pickup textbox renders cleanly instead of
       displaying garbage glyphs from random adjacent memory.
    """

    item_byte = struct.pack(ROM_CHEST_ITEM_FORMAT, ROM_CHEST_ITEM_VALUE)
    for offset in ROM_CHEST_ITEM_OFFSETS:
        patch.write_token(APTokenTypes.WRITE, offset + 1, item_byte)

    patch.write_token(
        APTokenTypes.WRITE, ROM_AP_ITEM_ENTRY_OFFSET, ROM_AP_ITEM_ENTRY_BYTES,
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


# =============================================================================
# Generation-time helper (called from world.py:generate_output)
# =============================================================================

def write_patch(world: DigimonWorldWorld, output_directory: str) -> None:
    """Build and write a ``.apdw1`` for the current player slot.

    Tokens written:

    * 32 bytes at :data:`VOLUME_ID_OFFSET` — the AP-marked volume id.
    * One ``<H`` write per ROM offset in
      :data:`worlds.digimon_world.data.addresses.ROM_RECRUIT_TRIGGERS`
      for every recruit whose ``world.recruit_remap`` assignment differs
      from vanilla.
    * The 44-byte PP-calc function rewrite from the standalone
      randomizer at :data:`ROM_PP_CALC_PATCH_OFFSET`.
    """

    patch = DigimonWorldProcedurePatch(
        player=world.player,
        player_name=world.multiworld.player_name[world.player],
    )

    seed_name = world.multiworld.seed_name
    volume_id = _build_volume_id(f"{seed_name}-{world.player}")
    assert len(volume_id) == VOLUME_ID_LENGTH, (len(volume_id), VOLUME_ID_LENGTH)
    patch.write_token(APTokenTypes.WRITE, VOLUME_ID_OFFSET, volume_id)

    _write_recruit_remap_tokens(patch, world.recruit_remap)
    _write_pp_calc_patch_tokens(patch)
    _write_softlock_fix_tokens(patch)
    _write_chest_item_tokens(patch)

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
