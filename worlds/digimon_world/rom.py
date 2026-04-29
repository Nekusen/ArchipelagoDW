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
    AP_CHEST_SENTINEL_ITEM_ID,
    CHEST_NAME_TO_ROM_OFFSETS,
    ROM_AP_ITEM_ENTRY_BYTES,
    ROM_AP_ITEM_ENTRY_OFFSET,
    ROM_BIN_BYTES,
    ROM_BIN_SHA1,
    ROM_CHEST_GIVEITEM_PATCH_FORMAT,
    ROM_CHEST_GIVEITEM_PATCH_OFFSET,
    ROM_CHEST_GIVEITEM_PATCH_VALUE,
    ROM_CHEST_GIVEITEM_WRAPPER_BYTES,
    ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
    ROM_CHEST_ITEM_FORMAT,
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
    ROM_RECRUITMENT,
    ROM_RECRUITMENT_FORMAT,
    ROM_SETTRIGGER_PATCH_FORMAT,
    ROM_SETTRIGGER_PATCH_OFFSET,
    ROM_SETTRIGGER_PATCH_VALUE,
    ROM_SETTRIGGER_WRAPPER_BYTES,
    ROM_SETTRIGGER_WRAPPER_OFFSET,
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
    * The 44-byte PP-calc function rewrite from the standalone
      randomizer at :data:`ROM_PP_CALC_PATCH_OFFSET`.
    * Five softlock-fix patches.
    * Per-chest item byte rewrites + chestGiveItem wrapper + chest
      pickup ``jal`` redirect (Phase 5 piece A).
    * setTrigger wrapper installation + entry redirect (Phase 5
      piece C — splits "fight completed" from "Digimon joined city").
    """

    patch = DigimonWorldProcedurePatch(
        player=world.player,
        player_name=world.multiworld.player_name[world.player],
    )

    seed_name = world.multiworld.seed_name
    volume_id = _build_volume_id(f"{seed_name}-{world.player}")
    assert len(volume_id) == VOLUME_ID_LENGTH, (len(volume_id), VOLUME_ID_LENGTH)
    patch.write_token(APTokenTypes.WRITE, VOLUME_ID_OFFSET, volume_id)

    _write_settrigger_wrapper_tokens(patch)
    _write_recruit_trigger_redirect_tokens(patch)
    _write_pp_calc_patch_tokens(patch)
    _write_softlock_fix_tokens(patch)
    _write_chest_item_tokens(patch, world)

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
