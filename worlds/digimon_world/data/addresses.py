"""Unified DW1 (SLUS-01032 USA) address manifest.

Two distinct address spaces live in this module:

* **RAM** offsets are MainRAM-relative (``0x00000000``..``0x001FFFFF``) and
  read by the BizHawk client at runtime via the ``MainRAM`` memory domain.
  Sourced from DWAP's ``Addresses.cs``. Use as-is — no KSEG0 translation
  required, since DWAP already records them as MainRAM-relative.

* **ROM** offsets are **flat byte positions** inside the user-supplied
  ``Digimon World (USA).bin`` (Mode2/2352, single-track,
  381,771,936 bytes, SHA-1 ``5611645DA66183E30D11FB6C11A2784FF47E1FDB``).
  Sourced from the standalone Digimon World randomizer's ``digimon/data.py``.
  The patcher converts each flat offset to a sector-aware write using the
  FFT Ivalice Island recipe::

      sector       = offset // SECTOR_SIZE_BYTES        # 0x930
      sector_start = sector * SECTOR_SIZE_BYTES
      data_start   = sector_start + SECTOR_HEADER_BYTES # 0x18
      # writable user-data window is data_start .. data_start + USER_DATA_BYTES (0x800)

  After all writes, EDC must be recomputed for each affected sector
  (see ``references/fft_ivalice_island/worlds/fftii/Rom.py``).

The standalone randomizer wrote flat-BIN bytes without sector awareness or
EDC recomputation. That worked in practice with permissive emulators, but
we follow FFT's correctness pattern — the offsets carry over unchanged.

Sources
-------

* DWAP — ``references/DWAP/source/DWAP/Addresses.cs``
  (RAM map, 21 named entries; one is a known-broken placeholder).
* Standalone randomizer —
  ``references/digimon_world_randomizer/digimon/data.py``
  (ROM offsets and binary layout of structured tables).

This file is the single source of truth. The patcher (Phase 3) and client
(Phase 4) should import from here rather than embed magic numbers locally.

See also
--------

* ``references/DWAP/Apworld/dw1/RecruitDigimon.py`` — DW1 recruit-prerequisite
  graph (51 entries). That is *logic* data, not addresses, and lives outside
  this manifest; it will be consumed by the world's logic / rules layer.
"""

from __future__ import annotations

from typing import Final, NamedTuple

# =============================================================================
# BIN sector geometry (Mode2/2352, FFT pattern)
# =============================================================================

SECTOR_SIZE_BYTES: Final = 0x930    # 2352
SECTOR_HEADER_BYTES: Final = 0x18   # 24
USER_DATA_BYTES: Final = 0x800      # 2048
SECTOR_EDC_ECC_BYTES: Final = 0x118  # 280  (EDC + ECC at sector tail)

ROM_BIN_BYTES: Final = 381_771_936
ROM_BIN_SECTORS: Final = ROM_BIN_BYTES // SECTOR_SIZE_BYTES   # 162_318
ROM_BIN_SHA1: Final = "5611645DA66183E30D11FB6C11A2784FF47E1FDB"


# =============================================================================
# Helper types
# =============================================================================


class StructBlock(NamedTuple):
    """A contiguous ROM data block of fixed-size records.

    :param offset: Flat-BIN offset of the first record.
    :param size: Total bytes covered by the block.
    :param count: Number of records.
    :param record_format: ``struct``-module format string for one record.
    :param exclusion_offsets: Flat-BIN offsets *inside* the block whose
        ``exclusion_size`` bytes must be left untouched (padding, sentinels,
        or special-case records preserved by the standalone randomizer).
    :param exclusion_size: Bytes per exclusion region. Defaults to ``0x130``
        (the value used throughout the standalone randomizer).
    """

    offset: int
    size: int
    count: int
    record_format: str
    exclusion_offsets: tuple[int, ...] = ()
    exclusion_size: int = 0x130


class RecruitmentEntry(NamedTuple):
    """One Digimon's recruit-related ROM offsets.

    :param trigger_offsets: Flat-BIN offsets of in-town behavior triggers
        (where the recruited Digimon's id is checked to decide whether to
        run a town animation, dialogue, etc.).
    :param jijimon_message_offsets: Flat-BIN offsets where Jijimon's
        per-recruit message is gated on the Digimon's id.
    :param name_list_index: Per-recruit ordinal id used by the standalone
        randomizer for name-table lookups. Empirically close to but not
        always equal to ``digimon_id``. Treat as opaque pending verification.
    :param digimon_id: Canonical DW1 Digimon id (matches the digimon-data
        block's record index).
    """

    trigger_offsets: tuple[int, ...]
    jijimon_message_offsets: tuple[int, ...]
    name_list_index: int
    digimon_id: int


# =============================================================================
# RAM (MainRAM) addresses
# =============================================================================
#
# Read with ``await bizhawk.read(ctx, [(addr, size, "MainRAM")])``.

# ----- Player Digimon current battle stats (struct around 0x001557E0) --------

RAM_CURRENT_OFFENSE: Final = 0x001557E0       # u16
RAM_CURRENT_DEFENSE: Final = 0x001557E2       # u16   (DWAP misspells: "Defence")
RAM_CURRENT_SPEED: Final = 0x001557E4         # u16
RAM_CURRENT_BRAINS: Final = 0x001557E6        # u16
RAM_TECHNIQUE_SLOT_1: Final = 0x001557EC      # first slot in the equipped-tech array
RAM_MAX_HP: Final = 0x001557F0                # u16
RAM_MAX_MP: Final = 0x001557F2                # u16

# Bytes per equipped-tech entry (DWAP: ``12 * ByteOffset + 2 * ShortOffset``).
RAM_TECHNIQUE_ENTRY_STRIDE: Final = 12 + 2 * 2

# ----- Inventory and economy ------------------------------------------------
#
# Bank layout (verified live 2026-04-28):
#
#     bank_quantity[item] = ram[RAM_ITEM_BANK_BASE + (item.dw_code - 2000)]
#
# i.e. each item in DWAP's 2000-block (consumables, MISC, DV items, key
# items) has a fixed 1-byte slot at ``RAM_ITEM_BANK_BASE + slot_index``,
# where the byte stores the quantity (0..max) the player has stashed.
# The bank spans exactly 128 bytes (0x001BDF2C..0x001BDFAB) — slots 0
# through 127. Slot 128 lands at :data:`RAM_CARD_LIST_BASE`.
#
# This is the **bank** (offline storage at any in-game bank NPC), NOT
# the personal inventory the player carries. Personal inventory lives
# at a separate, RE-pending address. AP item delivery uses the bank
# because it's a single-write-per-item operation that works regardless
# of where the player is in the game; the player retrieves AP-delivered
# items via any bank visit.
#
# Verified samples 2026-04-28: MP Floppy (dw_code 2004) at 0x1BDF30,
# Meat (dw_code 2038) at 0x1BDF52, Digimushrm (dw_code 2044) at
# 0x1BDF58. Three independent depositions, all match the formula.

RAM_INVENTORY_SIZE: Final = 0x000DD4CE         # current item count (TBD: u8 vs u16)

# Player on-hand inventory: 10 fixed slots. Item ID byte at +i, quantity
# byte at +i+0x1E (0x1E = 30 between IDs and quantities — verified live
# 2026-04-28 by writing test items and watching them appear in the in-game
# menu). Empty slot = ID 0xFF.
RAM_INVENTORY_ITEM_IDS_BASE: Final = 0x0013D474
RAM_INVENTORY_QUANTITIES_BASE: Final = 0x0013D492
RAM_INVENTORY_SLOT_COUNT: Final = 10
RAM_INVENTORY_EMPTY_SLOT_ID: Final = 0xFF

RAM_ITEM_BANK_BASE: Final = 0x001BDF2C         # per-slot bank entries (verified live)
RAM_ITEM_BANK_SIZE: Final = 128                # one byte per slot, 128 slots
RAM_CURRENT_BITS: Final = 0x00134EB8           # u32 LE — money (verified live 2026-04-28)
RAM_MONOCHROME_PROFIT: Final = 0x0013500C      # Monochromon side-business cash

# ----- Recruit / town progress ---------------------------------------------

RAM_PROSPERITY_POINTS: Final = 0x001BE032      # primary recruit-progress metric
RAM_CARD_LIST_BASE: Final = 0x001BDFAC         # collected business-card base
RAM_CHART_BASE: Final = 0x001BE00D             # ?-chart base (recruit-related)

# ----- Starter Digimon ------------------------------------------------------

RAM_STARTER_2: Final = 0x000EE9D0
RAM_STARTER_1: Final = 0x000EE9D8

# ----- Boss / area flags ----------------------------------------------------

RAM_HAS_BEATEN_DRIMOGEMON: Final = 0x001BE130
RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE: Final = 0x001BE042
RAM_MERAMON_TUNNEL_STATE: Final = 0x001BE043
RAM_MERAMON_TUNNEL_DIGGING_STATE: Final = 0x001BE04F

# ----- Per-Digimon technique tables (full-roster learned-tech tables) -------

RAM_TECHNIQUE_TABLE_BASE: Final = 0x0012623C
RAM_LEARNING_CHANCE_TABLE_BASE: Final = 0x00125FA4

# ----- Misc -----------------------------------------------------------------

RAM_LAST_SCRIPT: Final = 0x00134FDC

# ----- DO NOT USE: known-broken DWAP placeholder ----------------------------
#
# DWAP shipped this as ``0x00000000``, never resolved. Its only purpose was a
# function-hook for synchronous recruit detection that consequently never
# installed. Under Option B (BizHawk + flag-poll) we do not install function
# hooks at all; recruit progress is observed through MainRAM bit polling.
# This entry is retained as a marker that the lookup is OPEN and intentionally
# unimplemented — see PLAN.md Q2 "RAM map availability" subquestions.

RAM_RECRUITMENT_FUNCTION_PLACEHOLDER: Final = 0x00000000


# =============================================================================
# RAM — per-location completion-bit / threshold tables (DWAP-ingested)
# =============================================================================
#
# Source: ``references/DWAP/source/DWAP/Resources/{Locations,Chests,Prosperity}.json``.
# These tables map each AP location to a runtime-detectable RAM signal:
#
# * **Recruits and chests** are bit-set checks: the K-th bit at a known byte
#   address flips from 0 to 1 when the in-game event happens. Bit position
#   is little-endian within the byte (bit 0 is the 0x01 mask).
# * **Prosperity NPC gifts** are value-comparisons: a single byte at
#   :data:`RAM_PROSPERITY_POINTS` carries the running prosperity count, and
#   the K-th gift unlocks when ``byte > K - 1``. The N-th-gift logic is
#   ``(RAM_PROSPERITY_POINTS, N)`` meaning "byte must be >= N".
#
# **Validation status (2026-04-28):** ingested verbatim from DWAP's
# Resources directory but **not yet validated against a live BizHawk
# session**. DWAP's recruit-detection runtime hook (``RecruitmentHook.cs``)
# never installed because ``RecruitmentFunctionAddress = 0x00000000``, so
# the bit-poll code path was never exercised in production. The addresses
# here are best-available data, not verified data. Phase 4 v2 should
# validate against 2-3 entries (one recruit, one chest, one prosperity
# threshold) in a live BizHawk session before trusting the rest.
#
# Discrepancy with the standalone randomizer's chest catalog: DWAP ships
# **65** runtime-detectable chests; the standalone's
# :data:`ROM_CHEST_ITEM_OFFSETS` enumerates **73** chest *placement*
# offsets. The 8 extras may be decoy chests, duplicates, or chests DWAP
# missed. Phase 2's location list currently has 73 chests; reconciliation
# is open work and is documented in ``phase_progress.md``.

# Per-recruit completion bits. Keyed by recruit *location* name (the bare
# Digimon name; matches :data:`worlds.digimon_world.locations.RECRUIT_NAMES`).
# Source: DWAP Locations.json.
RECRUIT_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    "Agumon":       (0x001BDFE6, 3),
    "Betamon":      (0x001BDFE6, 4),
    "Greymon":      (0x001BDFE6, 5),
    "Devimon":      (0x001BDFE6, 6),
    "Airdramon":    (0x001BDFE6, 7),
    "Tyrannomon":   (0x001BDFE7, 0),
    "Meramon":      (0x001BDFE7, 1),
    "Seadramon":    (0x001BDFE7, 2),
    "Numemon":      (0x001BDFE7, 3),
    "MetalGreymon": (0x001BDFE7, 4),
    "Mamemon":      (0x001BDFE7, 5),
    "Monzaemon":    (0x001BDFE7, 6),
    "Gabumon":      (0x001BDFE8, 1),
    "Elecmon":      (0x001BDFE8, 2),
    "Kabuterimon":  (0x001BDFE8, 3),
    "Angemon":      (0x001BDFE8, 4),
    "Birdramon":    (0x001BDFE8, 5),
    "Garurumon":    (0x001BDFE8, 6),
    "Frigimon":     (0x001BDFE8, 7),
    "Whamon":       (0x001BDFE9, 0),
    "Vegiemon":     (0x001BDFE9, 1),
    "SkullGreymon": (0x001BDFE9, 2),
    "MetalMamemon": (0x001BDFE9, 3),
    "Vademon":      (0x001BDFE9, 4),
    "Patamon":      (0x001BDFE9, 7),
    "Kunemon":      (0x001BDFEA, 0),
    "Unimon":       (0x001BDFEA, 1),
    "Ogremon":      (0x001BDFEA, 2),
    "Shellmon":     (0x001BDFEA, 3),
    "Centarumon":   (0x001BDFEA, 4),
    "Bakemon":      (0x001BDFEA, 5),
    "Drimogemon":   (0x001BDFEA, 6),
    "Sukamon":      (0x001BDFEA, 7),
    "Andromon":     (0x001BDFEB, 0),
    "Giromon":      (0x001BDFEB, 1),
    "Etemon":       (0x001BDFEB, 2),
    "Biyomon":      (0x001BDFEB, 5),
    "Palmon":       (0x001BDFEB, 6),
    "Monochromon":  (0x001BDFEB, 7),
    "Leomon":       (0x001BDFEC, 0),
    "Coelamon":     (0x001BDFEC, 1),
    "Kokatorimon":  (0x001BDFEC, 2),
    "Kuwagamon":    (0x001BDFEC, 3),
    "Mojyamon":     (0x001BDFEC, 4),
    "Nanimon":      (0x001BDFEC, 5),
    "Megadramon":   (0x001BDFEC, 6),
    "Piximon":      (0x001BDFEC, 7),
    "Digitamamon":  (0x001BDFED, 0),
    "Penguinmon":   (0x001BDFED, 1),
    "Ninjamon":     (0x001BDFED, 2),
}

# Per-chest completion bits, keyed by AP location name. Names follow the
# Phase 5 chest-mapping document (``references/chest_mapping_phase5.md``):
# chests in confirmed or strongly-inferred regions are renamed
# ``Chest: <Area>`` (or ``Chest: <Area> N`` for multiples); chests in
# unverified regions keep their numeric form.
#
# The bit-position mapping itself is unchanged from DWAP's ``Chests.json``;
# we only rename the keys.
DWAP_CHEST_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    # Trigger 650..652 → Mt. Infinity 1..3 (Script ID 50)
    "Chest: Mt. Infinity 1":  (0x001BE01E, 2),
    "Chest: Mt. Infinity 2":  (0x001BE01E, 3),
    "Chest: Mt. Infinity 3":  (0x001BE01E, 4),
    # Trigger 653..657 → Freezeland 1..5 (Script IDs 55, 58, 61, 94)
    "Chest: Freezeland 1":    (0x001BE01E, 5),
    "Chest: Freezeland 2":    (0x001BE01E, 6),
    "Chest: Freezeland 3":    (0x001BE01E, 7),
    "Chest: Freezeland 4":    (0x001BE01F, 0),
    "Chest: Freezeland 5":    (0x001BE01F, 1),
    # Trigger 658..659 → Drill Tunnel 1..2 (Script ID 33)
    "Chest: Drill Tunnel 1":  (0x001BE01F, 2),
    "Chest: Drill Tunnel 2":  (0x001BE01F, 3),
    # Trigger 660..661 → unknown (Script ID 98 — Cherrymon-area dialog)
    "Chest 11":               (0x001BE01F, 4),
    "Chest 12":               (0x001BE01F, 5),
    # Trigger 662..665 → Freezeland 6..9 (Script IDs 99, 94, 97)
    "Chest: Freezeland 6":    (0x001BE01F, 6),
    "Chest: Freezeland 7":    (0x001BE01F, 7),
    "Chest: Freezeland 8":    (0x001BE020, 0),
    "Chest: Freezeland 9":    (0x001BE020, 1),
    # Trigger 666..667 → Drill Tunnel 3..4 (Script IDs 39/122, 110)
    "Chest: Drill Tunnel 3":  (0x001BE020, 2),
    "Chest: Drill Tunnel 4":  (0x001BE020, 3),
    # Trigger 668 → Toy Town (Script ID 145)
    "Chest: Toy Town":        (0x001BE020, 4),
    # Trigger 669..671 → unknown
    "Chest 20":               (0x001BE020, 5),
    "Chest 21":               (0x001BE020, 6),
    "Chest 22":               (0x001BE020, 7),
    # Trigger 672 → Ogre Fortress (Script ID 137)
    "Chest: Ogre Fortress":   (0x001BE021, 0),
    # Trigger 673..675 → unknown (Script ID 125 cluster)
    "Chest 24":               (0x001BE021, 1),
    "Chest 25":               (0x001BE021, 2),
    "Chest 26":               (0x001BE021, 3),
    # Trigger 676 → File City Cards 1 (Script ID 119, Meramon-card NPC)
    "Chest: File City Cards 1": (0x001BE021, 4),
    # Trigger 677..678 → unknown (Script ID 155)
    "Chest 28":               (0x001BE021, 5),
    "Chest 29":               (0x001BE021, 6),
    # Trigger 679 → File City Cards 2 (Script ID 121, Meramon-card NPC)
    "Chest: File City Cards 2": (0x001BE021, 7),
    # Trigger 680..682 → Mt. Infinity 4..6 (Script IDs 160, 161, 170)
    "Chest: Mt. Infinity 4":  (0x001BE022, 0),
    "Chest: Mt. Infinity 5":  (0x001BE022, 1),
    "Chest: Mt. Infinity 6":  (0x001BE022, 2),
    # Trigger 683..685 → unknown
    "Chest 34":               (0x001BE022, 3),
    "Chest 35":               (0x001BE022, 4),
    "Chest 36":               (0x001BE022, 5),
    # Trigger 686 → Mt. Infinity 7 (Script ID 194)
    "Chest: Mt. Infinity 7":  (0x001BE022, 6),
    # Trigger 687..691 → Tower 1..5 (Script IDs 195, 196, 197, 198)
    "Chest: Tower 1":         (0x001BE022, 7),
    "Chest: Tower 2":         (0x001BE023, 0),
    "Chest: Tower 3":         (0x001BE023, 1),
    "Chest: Tower 4":         (0x001BE023, 2),
    "Chest: Tower 5":         (0x001BE023, 3),
    # Trigger 693 → Tropical Jungle (Script ID 13). Live-confirmed
    # 2026-04-29: opening this chest in-game placed the player in the
    # Tropical Jungle screen, contradicting the earlier dialog-based
    # inference of Mt. Panorama (Mamemon recruit dialog). The
    # Mamemon-style cutscene shares Script ID 13 with this Tropical
    # Jungle chest, but the chest itself is in Tropical Jungle.
    "Chest: Tropical Jungle": (0x001BE023, 5),
    # Trigger 694..695 → unknown (Script IDs 31/120)
    "Chest 44":               (0x001BE023, 6),
    "Chest 45":               (0x001BE023, 7),
    # Trigger 696..698 → Great Canyon 1..3 (Script IDs 22/190, Birdramon)
    "Chest: Great Canyon 1":  (0x001BE024, 0),
    "Chest: Great Canyon 2":  (0x001BE024, 1),
    "Chest: Great Canyon 3":  (0x001BE024, 2),
    # Trigger 700..703 → Mt. Infinity 8..11 (Script ID 188)
    "Chest: Mt. Infinity 8":  (0x001BE024, 4),
    "Chest: Mt. Infinity 9":  (0x001BE024, 5),
    "Chest: Mt. Infinity 10": (0x001BE024, 6),
    "Chest: Mt. Infinity 11": (0x001BE024, 7),
    # Trigger 704..705 → unknown (Script ID 53)
    "Chest 53":               (0x001BE025, 0),
    "Chest 54":               (0x001BE025, 1),
    # Trigger 706 → Dragon Eye Lake (Script ID 9, Vending Machine)
    "Chest: Dragon Eye Lake": (0x001BE025, 2),
    # Trigger 707 → Mt. Infinity 12 (Script ID 185)
    "Chest: Mt. Infinity 12": (0x001BE025, 3),
    # Trigger 708..713 → Tower 6..11 (Script IDs 186, 187)
    "Chest: Tower 6":         (0x001BE025, 4),
    "Chest: Tower 7":         (0x001BE025, 5),
    "Chest: Tower 8":         (0x001BE025, 6),
    "Chest: Tower 9":         (0x001BE025, 7),
    "Chest: Tower 10":        (0x001BE026, 0),
    "Chest: Tower 11":        (0x001BE026, 1),
    # Trigger 714..716 → File City Remodel 1..3 (Script ID 156)
    "Chest: File City Remodel 1": (0x001BE026, 2),
    "Chest: File City Remodel 2": (0x001BE026, 3),
    "Chest: File City Remodel 3": (0x001BE026, 4),
}

# Bit gaps (intentional, mirrored from DWAP):
#   - 0x001BE023 bit 4 — between "Chest 42" (bit 3) and "Chest 43" (bit 5).
#   - 0x001BE024 bit 3 — between "Chest 48" (bit 2) and "Chest 49" (bit 4).
# These bits may be reserved or correspond to chests not yet mapped by DWAP.


# =============================================================================
# Per-chest spawnChest ROM-offset map (Phase 5)
# =============================================================================
#
# Cross-reference table mapping each DWAP chest name to the flat-BIN offsets
# of its ``spawnChest`` script-bytecode entries (one entry per ROM
# placement; six chests have duplicate entries because their map screen
# is loaded under two different Script IDs, and one chest — Drill Tunnel
# 3 — has four spawn entries spanning Script IDs 39, 122, plus two more
# duplicates). Item-byte writes must hit *every* entry so all branches
# spawn the same item.
#
# Construction: each ``spawnChest`` opcode in the script bytecode is a
# 12-byte record: opcode (1) + item id (1) + posX (4 LE) + posY (2 LE)
# + rotation (2 LE) + trigger id (2 LE). The trigger id at byte offset
# +10 is the bit-array trigger that DWAP records in
# :data:`DWAP_CHEST_RAM_BITS`. Reverse-mapping trigger -> chest name
# yields this table. Source for the 73 raw offsets:
# ``references/digimon_world_randomizer/digimon/data.py:232``.
# Source for the trigger -> chest-name mapping: this module's
# :data:`DWAP_CHEST_RAM_BITS` (the formula is
# ``trigger = (offset - 0x001BDFCD) * 8 + bit``). Cross-checked against
# ``references/chest_mapping_phase5.md``.
#
# Use case: the per-chest "vanilla-grant for own-slot DW1-representable
# items" feature (Phase 5 piece A). The patcher decides per-chest
# whether to write the AP sentinel ID (chest shows "AP ITEM" + nothing
# given) or the real DW1 internal item ID (chest grants the real item
# directly via vanilla flow).

CHEST_NAME_TO_ROM_OFFSETS: Final[dict[str, tuple[int, ...]]] = {
    "Chest: Mt. Infinity 1":      (0x14000EDC,),
    "Chest: Mt. Infinity 2":      (0x14000EE8,),
    "Chest: Mt. Infinity 3":      (0x14000EF4,),
    "Chest: Freezeland 1":        (0x14005868,),
    "Chest: Freezeland 2":        (0x140073E8,),
    "Chest: Freezeland 3":        (0x140073F4,),
    "Chest: Freezeland 4":        (0x14008F7C,),
    "Chest: Freezeland 5":        (0x14021168,),
    "Chest: Drill Tunnel 1":      (0x13FF6978,),
    "Chest: Drill Tunnel 2":      (0x13FF6984,),
    "Chest 11":                   (0x14023624,),
    "Chest 12":                   (0x14023630,),
    "Chest: Freezeland 6":        (0x14023F54,),
    "Chest: Freezeland 7":        (0x14023F60,),
    "Chest: Freezeland 8":        (0x14021174,),
    "Chest: Freezeland 9":        (0x14022D04,),
    "Chest: Drill Tunnel 3":      (0x13FFA098, 0x13FFA508, 0x14039338, 0x140396CA),
    "Chest: Drill Tunnel 4":      (0x14030964,),
    "Chest: Toy Town":            (0x1404A6DC,),
    "Chest 20":                   (0x13FFD7BC,),
    "Chest 21":                   (0x13FFE0F0,),
    "Chest 22":                   (0x13FFF35C,),
    "Chest: Ogre Fortress":       (0x14045424,),
    "Chest 24":                   (0x1403AEC4,),
    "Chest 25":                   (0x1403AED0,),
    "Chest 26":                   (0x1403AEDC,),
    "Chest: File City Cards 1":   (0x140377A8,),
    "Chest 28":                   (0x140539EC,),
    "Chest 29":                   (0x140539F8,),
    "Chest: File City Cards 2":   (0x14038A04,),
    "Chest: Mt. Infinity 4":      (0x1405836C,),
    "Chest: Mt. Infinity 5":      (0x14058C9C,),
    "Chest: Mt. Infinity 6":      (0x14067B7C,),
    "Chest 34":                   (0x1403AEE8,),
    "Chest 35":                   (0x1406970C,),
    "Chest 36":                   (0x14073334,),
    "Chest: Mt. Infinity 7":      (0x1407F430,),
    "Chest: Tower 1":             (0x1407FD54,),
    "Chest: Tower 2":             (0x14080688,),
    "Chest: Tower 3":             (0x14080FB4,),
    "Chest: Tower 4":             (0x140818F4,),
    "Chest: Tower 5":             (0x14081900,),
    "Chest: Tropical Jungle":     (0x13FE6844,),
    "Chest 44":                   (0x13FF4DE8, 0x13FF58AA),
    "Chest 45":                   (0x13FF4DF4, 0x13FF58B6),
    "Chest: Great Canyon 1":      (0x13FEE01E, 0x1407BD46),
    "Chest: Great Canyon 2":      (0x13FEE02A, 0x1407BD52),
    "Chest: Great Canyon 3":      (0x13FEE036, 0x1407BD5E),
    "Chest: Mt. Infinity 8":      (0x1407AA94,),
    "Chest: Mt. Infinity 9":      (0x1407AAA0,),
    "Chest: Mt. Infinity 10":     (0x1407AAAC,),
    "Chest: Mt. Infinity 11":     (0x1407AAB8,),
    "Chest 53":                   (0x14003398,),
    "Chest 54":                   (0x140033A4,),
    "Chest: Dragon Eye Lake":     (0x13FE3118,),
    "Chest: Mt. Infinity 12":     (0x14078F1C,),
    "Chest: Tower 6":             (0x14079854,),
    "Chest: Tower 7":             (0x14079848,),
    "Chest: Tower 8":             (0x14079860,),
    "Chest: Tower 9":             (0x1407986C,),
    "Chest: Tower 10":            (0x1407A178,),
    "Chest: Tower 11":            (0x1407A184,),
    "Chest: File City Remodel 1": (0x1405430C,),
    "Chest: File City Remodel 2": (0x14054318,),
    "Chest: File City Remodel 3": (0x14054324,),
}
assert len(CHEST_NAME_TO_ROM_OFFSETS) == 65, len(CHEST_NAME_TO_ROM_OFFSETS)
assert sum(len(v) for v in CHEST_NAME_TO_ROM_OFFSETS.values()) == 73, (
    "expected 73 total ROM offsets (8 duplicate spawn entries)"
)
assert set(CHEST_NAME_TO_ROM_OFFSETS) == set(DWAP_CHEST_RAM_BITS), (
    "chest-name set must match DWAP_CHEST_RAM_BITS exactly"
)


# =============================================================================
# ROM (BIN) — randomizable item placements
# =============================================================================

# ----- Chest items (79 entries; <BB = item_id, qty) ------------------------

ROM_CHEST_ITEM_FORMAT: Final = "<BB"
ROM_CHEST_ITEM_OFFSETS: Final = (
    0x13FE3118, 0x13FE6844, 0x13FEE01E, 0x13FEE02A, 0x13FEE036, 0x13FF4DE8, 0x13FF4DF4, 0x13FF6978,
    0x13FF6984, 0x13FFA098, 0x13FFD7BC, 0x13FFE0F0, 0x13FFF35C, 0x14000EDC, 0x14000EE8, 0x14000EF4,
    0x14003398, 0x140033A4, 0x14005868, 0x140073E8, 0x140073F4, 0x14008F7C, 0x14021168, 0x14021174,
    0x14022D04, 0x14023624, 0x14023630, 0x14023F54, 0x14023F60, 0x14030964, 0x140377A8, 0x13FF58AA,
    0x13FF58B6, 0x14038A04, 0x13FFA508, 0x14039338, 0x140396CA, 0x1403AEC4, 0x1403AED0, 0x1403AEDC,
    0x1403AEE8, 0x14045424, 0x1404A6DC, 0x140539EC, 0x140539F8, 0x1405430C, 0x14054318, 0x14054324,
    0x1405836C, 0x14058C9C, 0x14067B7C, 0x1406970C, 0x14073334, 0x14078F1C, 0x14079848, 0x14079854,
    0x14079860, 0x1407986C, 0x1407A178, 0x1407A184, 0x1407AA94, 0x1407AAA0, 0x1407AAAC, 0x1407AAB8,
    0x1407BD46, 0x1407BD52, 0x1407BD5E, 0x1407F430, 0x1407FD54, 0x14080688, 0x14080FB4, 0x140818F4,
    0x14081900,
)

# ----- Map item spawns (340 entries; <BB) ----------------------------------

ROM_MAP_ITEM_FORMAT: Final = "<BB"
ROM_MAP_ITEM_OFFSETS: Final = (
    0x13FE2800, 0x1407B400, 0x1400D002, 0x13FED804, 0x13FE6CF4, 0x13FEA008, 0x14031C0A, 0x13FEF40C,
    0x13FEE002, 0x1404140E, 0x13FED694, 0x1402C958, 0x1401C812, 0x14010814, 0x1407B416, 0x13FEE018,
    0x13FFAA04, 0x13FED81A, 0x1403C15A, 0x13FEA01E, 0x14031C20, 0x13FEF422, 0x14041424, 0x1401C828,
    0x1401DD5C, 0x1401082A, 0x1407B42C, 0x1400D02E, 0x14011030, 0x13FEA034, 0x1407C35E, 0x1400C836,
    0x1400E838, 0x13FE3AB4, 0x1404143A, 0x13FEC03C, 0x13FDE40A, 0x13FFD040, 0x13FF7C42, 0x13FEC444,
    0x14011046, 0x13FEA04A, 0x1400C84C, 0x1400E84E, 0x13FEA0B8, 0x13FEC052, 0x13FDD856, 0x13FECD64,
    0x13FEC45A, 0x1401105C, 0x140330BA, 0x1403785E, 0x13FEA060, 0x13FDD862, 0x1400E864, 0x13FEC068,
    0x13FFD06C, 0x13FEC470, 0x14011968, 0x14011072, 0x14037874, 0x1400C6CA, 0x13FEA076, 0x14033078,
    0x1400C6E0, 0x13FEC07E, 0x13FF88C0, 0x1401AC82, 0x13FF7C16, 0x14015088, 0x13FEA08C, 0x1403688E,
    0x1400D018, 0x14036EB4, 0x13FF8894, 0x13FEC16E, 0x14034098, 0x1402C0C4, 0x1401509E, 0x1401AF70,
    0x13FEA0A2, 0x140368A4, 0x1401C0A8, 0x140175E6, 0x13FF88AA, 0x14032572, 0x140340AE, 0x13FFB8B4,
    0x13FE10B8, 0x14035478, 0x140368BA, 0x13FE2CDE, 0x13FE7ACA, 0x1401C0BE, 0x13FEC0C0, 0x140160C2,
    0x140340C4, 0x140114C6, 0x140190C8, 0x1401CA9E, 0x13FFB8CA, 0x13FE10CE, 0x140368D0, 0x14014978,
    0x1401C0D4, 0x140314CE, 0x13FEC0D6, 0x140360D8, 0x13FDD878, 0x140340DA, 0x140114DC, 0x13FDD57A,
    0x140200DE, 0x1403DCD0, 0x13FEA0E4, 0x13FEC0EC, 0x140360EE, 0x1402C0F0, 0x140114F2, 0x140200F4,
    0x13FEA0FA, 0x1401ECB8, 0x1401402A, 0x14041558, 0x13FDF102, 0x14036104, 0x1401F71C, 0x13FEED08,
    0x13FF7C2C, 0x13FE6D0A, 0x13FEA10E, 0x14031510, 0x140160D8, 0x1407BD14, 0x13FEC118, 0x13FFC584,
    0x1402C0DA, 0x13FEED1E, 0x1400D920, 0x13FED830, 0x13FE8922, 0x14041D24, 0x1401476E, 0x13FFCD26,
    0x1402C92C, 0x13FDFA32, 0x13FDF12E, 0x13FEA0CE, 0x1401DD88, 0x13FE3134, 0x13FE6CDE, 0x1400D936,
    0x13FE8938, 0x14035C34, 0x14041D3A, 0x13FFC13C, 0x13FF818A, 0x1407BD40, 0x1407BAE0, 0x1402C942,
    0x1403C144, 0x14032546, 0x1403E148, 0x1400FDE0, 0x13FE314A, 0x1401494C, 0x14041D50, 0x13FEF438,
    0x13FFC152, 0x1401498E, 0x13FF8558, 0x140312E4, 0x13FEC15A, 0x1403255C, 0x1403815E, 0x13FECD90,
    0x14014962, 0x13FDD564, 0x13FFBC62, 0x13FFC168, 0x13FF756C, 0x13FF856E, 0x1401DD72, 0x14038174,
    0x13FE9178, 0x13FECD7A, 0x1401197E, 0x13FDD840, 0x13FF7582, 0x14041584, 0x1400D2B4, 0x13FE7188,
    0x13FDF0EC, 0x13FFB18A, 0x13FE918E, 0x13FDD590, 0x13FF7598, 0x1401B594, 0x140160EE, 0x13FDD596,
    0x13FE1598, 0x13FFC59A, 0x13FDD59C, 0x1404159A, 0x13FE719E, 0x1402D7B2, 0x13FFB1A0, 0x1401BEF0,
    0x14014758, 0x140365A4, 0x140339A8, 0x1402D79C, 0x1401B5AA, 0x13FEECF2, 0x13FDFA48, 0x13FDD5B2,
    0x13FE71B4, 0x13FF81B6, 0x140134F4, 0x140365BA, 0x14035C4A, 0x140339BE, 0x1401E5C0, 0x13FF81A0,
    0x13FDD5C8, 0x13FFBC4C, 0x13FED1CA, 0x13FF81CC, 0x140175D0, 0x13FF8E94, 0x140339D4, 0x1403658E,
    0x140421D8, 0x140175A4, 0x140162FA, 0x13FED1E0, 0x13FDF6DA, 0x13FE25E8, 0x1402B6FC, 0x1401E5EC,
    0x140421EE, 0x13FED1F6, 0x140314FA, 0x14042204, 0x13FFD056, 0x13FF9206, 0x1400FE0C, 0x13FEC102,
    0x1401BEDA, 0x13FFAA1A, 0x13FF921C, 0x1400FE22, 0x13FDF706, 0x13FDD85C, 0x14019DB2, 0x13FEF230,
    0x1407BD08, 0x13FF9232, 0x13FDE7B4, 0x1401350A, 0x1400EBB2, 0x13FE6860, 0x1401B75E, 0x1400E244,
    0x13FEF246, 0x13FE68A2, 0x13FF9248, 0x1401CA88, 0x14031ED8, 0x1400C862, 0x13FE038A, 0x1407BD0E,
    0x1400E25A, 0x1402D25C, 0x140175BA, 0x13FDFA5E, 0x1401DA60, 0x13FE8D10, 0x13FF8E68, 0x1403CA6C,
    0x1400E270, 0x1401CA72, 0x13FDFA74, 0x1401DA76, 0x1401FF14, 0x1403A27E, 0x13FF97C0, 0x1403CA82,
    0x1402CE86, 0x1400D288, 0x1401AC6C, 0x1401DA8C, 0x14012290, 0x13FDF118, 0x1403A294, 0x1402CE9C,
    0x13FE3A9E, 0x1402CE70, 0x13FDDE9E, 0x140122A6, 0x13FED6AA, 0x13FFCEA8, 0x14011B1C, 0x13FF8EAA,
    0x14031EAC, 0x1402D272, 0x14012F8A, 0x13FE7AB4, 0x140312B8, 0x140122BC, 0x13FFCEBE, 0x13FED6C0,
    0x13FE6D20, 0x14031EC2, 0x1401BEC4, 0x13FE6876, 0x1400FDF6, 0x1407BACA, 0x140312CE, 0x13FF72D0,
    0x14025478, 0x1403548E, 0x13FFCED4, 0x1400FAD8, 0x13FEC6DA, 0x14036EE0, 0x140162E4, 0x13FE8D26,
    0x13FF72E6, 0x1401FF2A, 0x1400FAEE, 0x1404156E, 0x13FEC6F0, 0x1402B728, 0x1407BAB4, 0x13FF887E,
    0x14036EF6, 0x140312FA, 0x13FF72FC, 0x13FE732A, 0x14010700, 0x1400FB04, 0x1401E5D6, 0x13FEC706,
    0x13FE6308, 0x13FF852C, 0x13FF9B0C, 0x14016310, 0x140251D8, 0x1402B712, 0x13FE7314, 0x13FEC12E,
    0x14010716, 0x1400FB1A, 0x13FDF71C, 0x13FE631E, 0x13FFA9D8, 0x13FFB320, 0x14032530, 0x1403C322,
    0x14016326, 0x13FE5F28, 0x1400DF2A, 0x1401B774, 0x1401F732, 0x14014040, 0x13FDDE88, 0x14011B32,
    0x1401ECE4, 0x13FFB336, 0x1403C338, 0x13FEED34, 0x14036ECA, 0x13FF8E7E, 0x13FE5F3E, 0x13FE7340,
    0x14036578, 0x1401AF44, 0x13FE0348, 0x13FE108C, 0x1401F706, 0x13FF9B4E, 0x13FF9B38, 0x1407C352,
    0x1400C6B4, 0x1403308E, 0x1400DF56, 0x1407C358, 0x1401AF5A, 0x13FE035E, 0x140314E4, 0x13FDD88E,
    0x13FE5370, 0x13FE0374, 0x13FEC094, 0x1403377C, 0x1401ECCE, 0x1400DF40, 0x14039C8C, 0x14014784,
    0x13FE5386, 0x1401E388, 0x1400CFEC, 0x1407C38A, 0x13FF8542, 0x14035462, 0x1403544C, 0x1401AC98,
    0x14033792, 0x13FF9794, 0x13FFA9EE, 0x13FF97D6, 0x13FEC144, 0x1401479A, 0x1400EB9C, 0x13FEF25C,
    0x1401E39E, 0x14012FA0, 0x140150B4, 0x14035C60, 0x1403D3A6, 0x140337A8, 0x1403E604, 0x1401F748,
    0x13FE688C, 0x13FDD82A, 0x1401E3B4, 0x1400D29E, 0x14012FB6, 0x1403EFB8, 0x14031BF4, 0x1403D3BC,
    0x13FEED4A, 0x13FEDFC0, 0x13FDEBC4, 0x1407BA9E, 0x1401ECFA, 0x1400EBC8, 0x1400D94C, 0x13FDE7CA,
    0x13FE10A2, 0x14011508, 0x13FEDFD6, 0x13FE43D8, 0x140330A4, 0x13FDEBDA, 0x13FE9FDC, 0x13FDF6F0,
    0x1400EBDE, 0x13FDE7E0, 0x13FF7C00, 0x14039CA2, 0x1407B3EA, 0x13FEDFEC, 0x13FE43EE, 0x13FDEBF0,
    0x13FE9FF2, 0x13FDE3F4, 0x1400D272, 0x140413F8, 0x13FFBC78, 0x1401C7FC, 0x13FEC0AA,
)

# ----- Tokomon item gifts (6 entries; <BxBB) -------------------------------

ROM_TOKOMON_ITEM_FORMAT: Final = "<BxBB"
ROM_TOKOMON_ITEM_OFFSETS: Final = (
    0x14071064, 0x14071068, 0x1407106C,
    0x14071070, 0x14071074, 0x14071078,
)

# ----- Tech-gift learn-and-check offsets (Bug + Seadramon teach) ----------

ROM_LEARN_MOVE_FORMAT: Final = "<2B"
ROM_LEARN_MOVE_OFFSETS: Final = (
    0x14029E3E,   # Bug
    0x13FE219A,   # Seadramon 1
    0x13FE21E4,   # Seadramon 2
    0x13FE2232,   # Seadramon 3
)

ROM_CHECK_MOVE_FORMAT: Final = "<B"
ROM_CHECK_MOVE_OFFSETS: Final = (
    0x14029B32,   # Bug
    0x13FE2192,   # Seadramon 1
    0x13FE21DC,   # Seadramon 2
    0x13FE222A,   # Seadramon 3
)


# =============================================================================
# ROM (BIN) — recruitment town triggers
# =============================================================================
#
# Each Digimon's tuple lists every place in ROM where its id is checked for
# in-town behavior or Jijimon dialogue. Entries the standalone randomizer
# commented out (Greymon, Monzaemon, Angemon, Birdramon, Vegiemon, Palmon,
# Centarumon) are preserved as Python comments below — the standalone
# excluded them either because they have no in-town behavior, no Jijimon
# message, or because the underlying check is not reliably instrumentable.

ROM_RECRUITMENT_FORMAT: Final = "<H"

ROM_RECRUITMENT: Final = (
    RecruitmentEntry(
        trigger_offsets=(
            0x14059A40, 0x1405CA20, 0x1405CB42, 0x1405E344, 0x1406AB0A, 0x1405E6C2, 0x14060890, 0x1405C40A,
            0x1405E222, 0x1402C5AE, 0x1405E044, 0x13FE581A, 0x13FD893A, 0x1405CD5C, 0x13FE503A, 0x1405E420,
            0x1406D050, 0x1405C6A2, 0x1402BBE6, 0x1406D7E6, 0x14063CE2, 0x1406BC52, 0x1406F12E, 0x1405E9B0,
            0x13FE5D32, 0x140B4572, 0x13FD8A4A, 0x140B9ABA, 0x1405C14A, 0x140B9BCA,
        ),
        jijimon_message_offsets=(0x13FE9066, 0x13FE9BC8),
        name_list_index=204,
        digimon_id=0x04,  # Betamon
    ),
    # ( ( 0x140B51F6, ), 205 ),  # Greymon — omitted by standalone randomizer
    RecruitmentEntry(
        trigger_offsets=(
            0x1406FE82, 0x1406F0A4, 0x140B6668, 0x13FE44A2, 0x140BA898, 0x140701D2, 0x140BA7B4, 0x13FD9718,
            0x13FD9634, 0x13FE543A, 0x1406D75C,
        ),
        jijimon_message_offsets=(),
        name_list_index=206,
        digimon_id=0x06,  # Devimon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FE5A02, 0x1406D806, 0x14063D02, 0x1406AC0E, 0x140BA318, 0x1406B784, 0x13FE591E, 0x13FD9120,
            0x13FE5222, 0x1402BC06, 0x14059C28, 0x1406AB2A, 0x1406D238, 0x1406BE3A, 0x13FE513E, 0x140BA442,
            0x14059B44, 0x1406C646, 0x1406F14E, 0x13FE5D52, 0x1406D154, 0x1406BD56, 0x1402C5CE, 0x13FE505A,
            0x13FE583A, 0x14059A60, 0x1406C9E6, 0x1405C16A, 0x1406D070, 0x1406BC72, 0x140BA176, 0x14060A78,
            0x140AD37A, 0x1402BCEA, 0x1406C07E, 0x1406D484, 0x1405218A, 0x13FD9198, 0x14060994, 0x1402C796,
            0x1405EB98, 0x140BA2A0, 0x140598A4, 0x1405BFAE, 0x140608B0, 0x1402C6B2, 0x1405EAB4, 0x1405C5B6,
            0x140B47C0, 0x13FD92C2, 0x14051FC6, 0x14063ECA, 0x1402BDCE, 0x1405E9D0, 0x1405C24E, 0x1406B3DE,
            0x140AEBE2, 0x14063DE6, 0x1406D8EA, 0x1406ACF2, 0x13FD8FF6, 0x1406D9CE,
        ),
        jijimon_message_offsets=(0x1401727C,),
        name_list_index=208,
        digimon_id=0x08,  # Tyrannomon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x1406D802, 0x13FD9108, 0x1406AC0A, 0x1402BC02, 0x1406C910, 0x1406C516, 0x140AD31A, 0x13FE521E,
            0x14059C24, 0x1406AB26, 0x140BA42A, 0x1405C5B2, 0x1406D234, 0x1406BE36, 0x13FE513A, 0x14059B40,
            0x13FE5836, 0x1406F14A, 0x13FE5D4E, 0x1406D150, 0x1406BD52, 0x1406D354, 0x13FE5056, 0x140BA15A,
            0x14059A5C, 0x1406C362, 0x1402BCE6, 0x1405C166, 0x1406D06C, 0x1406BC6E, 0x14060A74, 0x13FD917C,
            0x140B4880, 0x140AEB82, 0x14052186, 0x140BA288, 0x1406B6C2, 0x14060990, 0x1402C792, 0x1405EB94,
            0x13FE591A, 0x140598A0, 0x13FD92AA, 0x140608AC, 0x1402C6AE, 0x1405EAB0, 0x1406B2B2, 0x1405C24A,
            0x14051FC2, 0x14063EC6, 0x1406D9CA, 0x1405E9CC, 0x1402BDCA, 0x13FD8FDA, 0x1402C5CA, 0x14063DE2,
            0x1406D8E6, 0x1406BF52, 0x1406ACEE, 0x13FE59FE, 0x140BA2FC, 0x1405BFAA, 0x14063CFE,
        ),
        jijimon_message_offsets=(0x13FF55CA,),
        name_list_index=209,
        digimon_id=0x09,  # Meramon
    ),
    RecruitmentEntry(
        trigger_offsets=(),
        jijimon_message_offsets=(),
        name_list_index=210,
        digimon_id=0x0A,  # Seadramon — does nothing in town, no Jijimon message
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x1406D760, 0x13FD95E0, 0x1406FC62, 0x13FE44A6, 0x1406FFC8, 0x140B5A62, 0x140BA760, 0x140BA850,
            0x1406F0A8, 0x13FD96D0, 0x13FE543E,
        ),
        jijimon_message_offsets=(0x140745F6,),
        name_list_index=211,
        digimon_id=0x0B,  # Numemon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FD9700, 0x140BA880, 0x1406D764, 0x13FE5446, 0x1406F0AC, 0x1407012E, 0x13FE44AE, 0x140BA798,
            0x140B598E, 0x13FD9618, 0x1406FDDC,
        ),
        jijimon_message_offsets=(0x13FED010, 0x13FED476, 0x13FEDAB0, 0x1404CF06, 0x1404D9D0),
        name_list_index=213,
        digimon_id=0x0D,  # Mamemon
    ),
    # ( ( 0x140B644A, ), 214, 0x0E ),  # Monzaemon — omitted by standalone
    RecruitmentEntry(
        trigger_offsets=(0x14067588, 0x13FD8F0C, 0x140BA08C, 0x140672CE, 0x140B563C),
        jijimon_message_offsets=(
            0x14036030, 0x14036C76, 0x1403729C, 0x14037C1A, 0x1403851A, 0x14038FB0, 0x14039AE2,
        ),
        name_list_index=217,
        digimon_id=0x11,  # Gabumon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FD89F0, 0x1405C5E2, 0x140B4D44, 0x1405C556, 0x1405C4E6, 0x1405C56A, 0x13FD8C72, 0x140B9B70,
            0x140B9DF2, 0x1405C596, 0x1405C084, 0x1405997A,
        ),
        jijimon_message_offsets=(0x1400DCD6,),
        name_list_index=218,
        digimon_id=0x12,  # Elecmon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x1402E900, 0x140B8BF0, 0x14030F06, 0x140319C6, 0x1402E308, 0x1402FECC, 0x1402DBAC, 0x1402E090,
            0x1402DE34, 0x14032398, 0x13FD7A70, 0x140B5B3A, 0x1402E6BE,
        ),
        jijimon_message_offsets=(0x140294CC,),
        name_list_index=219,
        digimon_id=0x13,  # Kabuterimon
    ),
    # ( ( 0x140B54BA, ), 220, 0x14 ),  # Angemon  — omitted by standalone
    # ( ( 0x140B4BCE, ), 221, 0x15 ),  # Birdramon — omitted by standalone
    RecruitmentEntry(
        trigger_offsets=(
            0x1406B880, 0x13FE5A06, 0x1406D80A, 0x13FD9012, 0x140AEC2E, 0x1406CADA, 0x13FE5922, 0x14063D06,
            0x13FE5226, 0x14059C2C, 0x1406AB2E, 0x140BA334, 0x13FD9138, 0x140608B4, 0x1406D23C, 0x1402BC0A,
            0x13FE583E, 0x1406C742, 0x14059B48, 0x1405EAB8, 0x1406F152, 0x13FE5D56, 0x1406D158, 0x1406BD5A,
            0x13FE505E, 0x14059A64, 0x1406AC12, 0x1405C16E, 0x1406D9D2, 0x1406D074, 0x1406BE3E, 0x1406BC76,
            0x140BA45A, 0x1406C17A, 0x14060A7C, 0x1406D580, 0x13FE5142, 0x1405218E, 0x140BA192, 0x1402BCEE,
            0x14060998, 0x1402C79A, 0x1405EB9C, 0x140598A8, 0x1405BFB2, 0x13FD91B4, 0x1402C6B6, 0x140BA2B8,
            0x1405C5BA, 0x140AD3C6, 0x14051FCA, 0x14063ECE, 0x1402C5D2, 0x1405E9D4, 0x13FD92DA, 0x140B4B26,
            0x14063DEA, 0x1406B4DA, 0x1402BDD2, 0x1406D8EE, 0x1405C252, 0x1406ACF6,
        ),
        jijimon_message_offsets=(0x1401F5FE,),
        name_list_index=222,
        digimon_id=0x16,  # Garurumon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x14060A80, 0x1406C280, 0x140BA472, 0x1402BDD6, 0x14063D0A, 0x140B118C, 0x13FE5842, 0x1406D80E,
            0x14052192, 0x13FD902E, 0x1406CC16, 0x1406B99A, 0x1406099C, 0x13FE5D5A, 0x1402C79E, 0x1405EBA0,
            0x13FE5926, 0x140AEEAA, 0x140598AC, 0x1405C172, 0x140BA1AE, 0x14059C30, 0x1406AB32, 0x1405BFB6,
            0x140608B8, 0x1402C6BA, 0x1405EABC, 0x13FE5A0A, 0x1405C5BE, 0x1406D240, 0x1406BE42, 0x1406C844,
            0x13FE5146, 0x1402C5D6, 0x1402BCF2, 0x14059B4C, 0x1405C256, 0x14051FCE, 0x140BA350, 0x14063ED2,
            0x1406AC16, 0x1402BC0E, 0x1406F156, 0x1405E9D8, 0x140B4A80, 0x1406D15C, 0x1406ACFA, 0x1406BD5E,
            0x1406B5E0, 0x13FD9150, 0x13FE5062, 0x1406D9D6, 0x14063DEE, 0x14059A68, 0x1406D8F2, 0x13FD91D0,
            0x1406D078, 0x13FD92F2, 0x1406BC7A, 0x140BA2D0, 0x13FE522A,
        ),
        jijimon_message_offsets=(0x14040D2E,),
        name_list_index=223,
        digimon_id=0x17,  # Frigimon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x140B57F4, 0x13FD86FC, 0x1405BF76, 0x140B987C, 0x1405986C, 0x1405B1FE,
        ),
        jijimon_message_offsets=(0x1404507C,),
        name_list_index=224,
        digimon_id=0x18,  # Whamon
    ),
    # ( ( 0x140B46F0, ), 225, 0x19 ),  # Vegiemon — omitted by standalone
    RecruitmentEntry(
        trigger_offsets=(0x140B68BE,),
        jijimon_message_offsets=(),
        name_list_index=226,
        digimon_id=0x1A,  # SkullGreymon — does nothing except tournament
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FD9982, 0x140B617C, 0x140BAB02),
        jijimon_message_offsets=(0x1404CEFC, 0x1404D9C6),
        name_list_index=227,
        digimon_id=0x1B,  # MetalMamemon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FD91F0, 0x140BA370, 0x13FD904E, 0x140AEEEA, 0x140B11CC, 0x140B626E, 0x140BA1CE,
        ),
        jijimon_message_offsets=(0x13FEEC54, 0x1407C2BE, 0x1407CCDC),
        name_list_index=228,
        digimon_id=0x1C,  # Vademon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x140B9BD6, 0x1406086C, 0x1402C58A, 0x1405E98C, 0x1402BBC2, 0x13FE5D0E, 0x13FE5016, 0x14059A1C,
            0x140BA49E, 0x140BA122, 0x13FD8946, 0x1405C126, 0x1406D02C, 0x1406BC2E, 0x1405C6B0, 0x13FD931E,
            0x1406F10A, 0x14072B0A, 0x14063CBE, 0x13FD9560, 0x1406D7C2, 0x13FE57F6, 0x140B9AC6, 0x1405E6A2,
            0x13FD8A56, 0x140598D8, 0x1406DADE, 0x140BA6E0, 0x1405BFE2, 0x1406AAE6, 0x1405C3EA, 0x1407056C,
            0x14072670, 0x1405C972, 0x1406E176, 0x140B507C, 0x13FD8FA2,
        ),
        jijimon_message_offsets=(0x1400E69C,),
        name_list_index=231,
        digimon_id=0x1F,  # Patamon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x1405E4C6, 0x13FE5B08, 0x140B6C4A, 0x13FE438C, 0x1405C50E, 0x13FE5614, 0x13FD8CAE, 0x140B9E2E,
            0x13FE43B0, 0x13FE5324, 0x13FE5B2C, 0x13FD89B2, 0x140B432E, 0x13FE55F0, 0x13FE5348, 0x140B9B32,
        ),
        jijimon_message_offsets=(0x13FDE31A,),
        name_list_index=232,
        digimon_id=0x20,  # Kunemon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FD9356, 0x1406E30A, 0x13FD9590, 0x1406F112, 0x1405E994, 0x13FE5D16, 0x13FE501E, 0x14059A24,
            0x1405E6AA, 0x1405C12E, 0x1406D034, 0x140B9BDE, 0x1406BC36, 0x140B4FB8, 0x14060874, 0x1406D7CA,
            0x1406DDC2, 0x14063CC6, 0x1402BBCA, 0x140B9ACE, 0x1405C6B8, 0x13FD894E, 0x140BA4D6, 0x1402C592,
            0x13FD8A5E, 0x140598E0, 0x140BA710, 0x1405BFEA, 0x14072B12, 0x1406AAEE, 0x13FD8FAA, 0x1405C3F2,
            0x14070574, 0x14072678, 0x1405C97A, 0x140BA12A, 0x13FE57FE,
        ),
        jijimon_message_offsets=(0x13FEE4D6, 0x13FEF912, 0x13FF0B34, 0x1407B97C),
        name_list_index=233,
        digimon_id=0x21,  # Unimon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FD8BD2, 0x140B9D52, 0x140B5E82),
        jijimon_message_offsets=(0x13FF193E,),
        name_list_index=234,
        digimon_id=0x22,  # Ogremon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FD8BF6, 0x1405E4A4, 0x140B9D76, 0x13FD8BBE, 0x1405C4EA, 0x140B9B0A, 0x1405C496, 0x140B4C64,
            0x13FD898A, 0x140B9D3E,
        ),
        jijimon_message_offsets=(0x1403967A, 0x14039A0C),
        name_list_index=235,
        digimon_id=0x23,  # Shellmon
    ),
    # ( ( 0x140B43DC, ), 236, 0x24 ),  # Centarumon — omitted by standalone
    RecruitmentEntry(
        trigger_offsets=(0x13FD8970, 0x140B9AF0, 0x13FD8C4A, 0x140B9DCA, 0x140B462E),
        jijimon_message_offsets=(0x13FF7FB2, 0x13FF8C34, 0x13FF95B0, 0x13FF9EBA),
        name_list_index=237,
        digimon_id=0x25,  # Bakemon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x140B5568, 0x14059854, 0x1405B1E4, 0x1405BF5E),
        jijimon_message_offsets=(0x13FF6416, 0x13FF6E38, 0x13FF7912),
        name_list_index=238,
        digimon_id=0x26,  # Drimogemon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FD87F6, 0x140B9976),
        jijimon_message_offsets=(),
        name_list_index=239,
        digimon_id=0x27,  # Sukamon — no Jijimon message
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FD8780, 0x140B9900, 0x140B6990),
        jijimon_message_offsets=(0x1404FAA2, 0x140519FA),
        name_list_index=240,
        digimon_id=0x28,  # Andromon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x140B5DE0, 0x1405E514),
        jijimon_message_offsets=(0x14052A40, 0x14052D5C),
        name_list_index=241,
        digimon_id=0x29,  # Giromon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FDD278, 0x13FE0010, 0x13FD63CA, 0x140B754A, 0x140B60CE),
        jijimon_message_offsets=(0x13FDF51C, 0x13FDFE62),
        name_list_index=242,
        digimon_id=0x2A,  # Etemon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x14072B0E, 0x1405E990, 0x13FE5D12, 0x13FE501A, 0x13FD8A5A, 0x14059A20, 0x14060870, 0x1406D7C6,
            0x140BA126, 0x1405C12A, 0x140B5132, 0x1406D030, 0x1406BC32, 0x1405C6B4, 0x13FD933A, 0x140B9ACA,
            0x1406E240, 0x14063CC2, 0x1402BBC6, 0x13FD894A, 0x13FD9578, 0x1406DC52, 0x1406F10E, 0x1402C58E,
            0x140B9BDA, 0x140598DC, 0x140BA4BA, 0x1405E6A6, 0x1405BFE6, 0x1406AAEA, 0x1405C3EE, 0x14070570,
            0x14072674, 0x1405C976, 0x13FD8FA6, 0x140BA6F8, 0x13FE57FA,
        ),
        jijimon_message_offsets=(0x1400F8E0,),
        name_list_index=245,
        digimon_id=0x2D,  # Biyomon
    ),
    # ( ( 0x140B4266, ), 246, 0x2E ),  # Palmon — omitted by standalone
    RecruitmentEntry(
        trigger_offsets=(
            0x13FE5802, 0x14072B16, 0x13FD8FAE, 0x1406F116, 0x1405E998, 0x13FE5D1A, 0x13FE5022, 0x14059A28,
            0x140BA4F2, 0x1405E6AE, 0x1406DF30, 0x1405C132, 0x1406BC3A, 0x1405C6BC, 0x1406E3BE, 0x1402C596,
            0x14063CCA, 0x140B9BE2, 0x1406D7CE, 0x140B4ED0, 0x14060878, 0x13FD8952, 0x1402BBCE, 0x13FD8A62,
            0x13FD95A8, 0x140598E4, 0x140B9AD2, 0x1405BFEE, 0x140BA728, 0x1406AAF2, 0x140BA12E, 0x1405C3F6,
            0x14070578, 0x1407267C, 0x13FD9372, 0x1405C97E,
        ),
        jijimon_message_offsets=(0x14000BDC,),
        name_list_index=247,
        digimon_id=0x2F,  # Monochromon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x140B5F30, 0x13FD8ED2, 0x140BA052),
        jijimon_message_offsets=(0x140128F0,),
        name_list_index=248,
        digimon_id=0x30,  # Leomon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x1405C63A, 0x1405C68A, 0x1406AB0E, 0x1405C612, 0x14060894, 0x13FE581E, 0x1405E424, 0x1405C626,
            0x1405CA28, 0x1405E22A, 0x1402C5B2, 0x1406F132, 0x1405E9B4, 0x13FE5D36, 0x13FD8FBA, 0x1405E03C,
            0x13FE503E, 0x140B44C0, 0x14059A44, 0x1405CB46, 0x1405E348, 0x1405C64E, 0x1406D054, 0x1405C14E,
            0x1406BC56, 0x140B6DDC, 0x140BA13A, 0x1405CD60, 0x1405C662, 0x14063CE6, 0x1406D7EA, 0x1405C676,
            0x1405E47C, 0x1402BBEA, 0x1405C5FE,
        ),
        jijimon_message_offsets=(0x13FE08B0,),
        name_list_index=249,
        digimon_id=0x31,  # Coelamon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x140B9946, 0x13FD87C6, 0x14059908, 0x1405994A, 0x1405C012, 0x1405C054, 0x140B4E06, 0x13FD873A,
            0x140B98BA,
        ),
        jijimon_message_offsets=(0x14032E4A,),
        name_list_index=250,
        digimon_id=0x32,  # Kokatorimon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FD7A82, 0x140B5D3C, 0x140B8C02),
        jijimon_message_offsets=(0x1402A706,),
        name_list_index=251,
        digimon_id=0x33,  # Kuwagamon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FE5442, 0x140B58A4, 0x1406FD28, 0x140BA77C, 0x13FE44AA, 0x13FD96E8, 0x1407006E, 0x1406F0B0,
            0x1406D768, 0x140BA868, 0x13FD95FC,
        ),
        jijimon_message_offsets=(0x1403CE4E, 0x1403D17C, 0x1403D788, 0x1403DAB6, 0x1403E04E),
        name_list_index=252,
        digimon_id=0x34,  # Mojyamon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x13FD8F5A, 0x140BA0DA, 0x140B63C6),
        jijimon_message_offsets=(),
        name_list_index=253,
        digimon_id=0x35,  # Nanimon
    ),
    RecruitmentEntry(
        trigger_offsets=(),
        jijimon_message_offsets=(),
        name_list_index=254,
        digimon_id=0x36,  # Megadramon — does nothing, no Jijimon message
    ),
    RecruitmentEntry(
        trigger_offsets=(0x140B600A, 0x13FD9396, 0x140BA516),
        jijimon_message_offsets=(0x13FE6B1A, 0x13FE6F98, 0x13FE75D6),
        name_list_index=255,
        digimon_id=0x37,  # Piximon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x13FD9210, 0x140BA390, 0x13FD906E, 0x140AEF36, 0x140B67EE, 0x140BA1EE,
        ),
        jijimon_message_offsets=(0x140774C8, 0x140788B0),
        name_list_index=256,
        digimon_id=0x38,  # Digitamamon
    ),
    RecruitmentEntry(
        trigger_offsets=(
            0x14066400, 0x140BAB1E, 0x140632A4, 0x140B53E6, 0x140663AC, 0x14063250, 0x14066374, 0x14095A7E,
            0x14063218, 0x1409761C, 0x13FD999E,
        ),
        jijimon_message_offsets=(0x14096804,),
        name_list_index=257,
        digimon_id=0x39,  # Penguinmon
    ),
    RecruitmentEntry(
        trigger_offsets=(0x140B573A, 0x13FD95CE, 0x140BA74E),
        jijimon_message_offsets=(0x13FE4AD6,),
        name_list_index=258,
        digimon_id=0x3A,  # Ninjamon
    ),
)


# =============================================================================
# ROM (BIN) — special evolution overrides
# =============================================================================
#
# Each tuple: (offsets_to_patch, evolution_target_id, evolution_source_id).
# Used when a Digimon's normal evolution rules are bypassed by a story event
# (Toy Town entry, jukebox unlock, etc.).

ROM_SPECIAL_EVO_FORMAT: Final = "<B"

ROM_SPECIAL_EVO: Final = (
    ((0x140466BF, 0x14046693, 0x14046841, 0x13FD8065, 0x140479ED), 0x0E, 0x0B),  # Monzaemon / Toy Town
    ((0x14054503,), 0x29, 0x0D),  # Giromon
    ((0x14054589,), 0x1B, 0x0D),  # MetalMamemon
    ((0x140A2E11,), 0x25, 0x03),  # Bakemon
    ((0x140A2E5D,), 0x1A, 0x0C),  # SkullGreymon
    ((0x140A2EA9,), 0x3B, 0x32),  # Phoenixmon
    ((0x140A2EFB,), 0x06, 0x14),  # Devimon
    ((0x14D19FEC,), 0x07, 0x0A),  # Airdramon
    ((0x14D1A01C,), 0x3A, 0x19),  # Ninjamon
    ((0x14D1A054,), 0x2F, 0x26),  # Monochromon
    ((0x14D1A0AC,), 0x20, 0x02),  # Kunemon
    ((0x14D1A0F8,), 0x31, 0x18),  # Coelamon
    ((0x14D1A114,), 0x35, 0x35),  # Nanimon
    ((0x14D1A148,), 0x1C, 0x1C),  # Vademon
    ((0x14CD7578, 0x14CD7584), 0x27, 0x27),  # Sukamon
)


# =============================================================================
# ROM (BIN) — structured data blocks
# =============================================================================

# ----- Item data (0x80 entries; <20s I H H b ? 2x) -------------------------

ROM_ITEM_DATA = StructBlock(
    offset=0x14D676C4,
    size=0x1260,
    count=0x80,
    record_format="<20sIHHb?2x",
    exclusion_offsets=(
        0x14D67CE8,  # in Red Berry
        0x14D68618,  # in Coral charm
    ),
)

# ----- Digimon data (0xB4 entries; <20s i h h 23B x) -----------------------

ROM_DIGIMON_DATA = StructBlock(
    offset=0x14D6E9DC,
    size=0x2A80,
    count=0xB4,
    record_format="<20sihh23Bx",
    exclusion_offsets=(
        0x14D6EB28,  # in Devimon
        0x14D6F458,  # in Biyomon
        0x14D6FD88,  # in Piddomon
        0x14D706B8,  # in Master Tyrannomon
        0x14D70FE8,  # in Biyomon
    ),
)

# ----- Evolution to/from (0x3E entries; <11B) ------------------------------

ROM_EVO_TO_FROM = StructBlock(
    offset=0x14D6CE04,
    size=0x3DA,
    count=0x3E,
    record_format="<11B",
    exclusion_offsets=(0x14D6CF98,),  # in to-Bakemon row 3-4
)

# ----- Evolution stat gains (0x42 entries; <6H H) --------------------------

ROM_EVO_STAT_GAINS = StructBlock(
    offset=0x14D6CA68,
    size=0x39C,
    count=0x42,
    record_format="<6HH",
)

# ----- Evolution requirements (0x3F entries; <11H h 2H) --------------------

ROM_EVO_REQUIREMENTS = StructBlock(
    offset=0x14D6C254,
    size=0x814,
    count=0x3F,
    record_format="<11Hh2H",
    exclusion_offsets=(0x14D6C668,),  # in Bakemon
)

# ----- Technique data (0x79 entries; <3H 8B xx) ----------------------------

ROM_TECHNIQUE_DATA = StructBlock(
    offset=0x14D66DF4,
    size=0x8C0,
    count=0x79,
    record_format="<3H8Bxx",
    exclusion_offsets=(0x14D673B8,),
)

# ----- Technique battle-learn chance (0x3A entries; <BBB) ------------------

ROM_TECH_LEARN_BATTLE = StructBlock(
    offset=0x14D66A2C,
    size=0x1DE,
    count=0x3A,
    record_format="<BBB",
    exclusion_offsets=(0x14D66A88,),
)

# ----- Technique brain-learn chance (0x08 entries; <BBB) -------------------

ROM_TECH_LEARN_BRAIN = StructBlock(
    offset=0x14C8E58C,
    size=0x18,
    count=0x08,
    record_format="<BBB",
)

# ----- Technique tier list (0x07 entries; <8B) -----------------------------

ROM_TECH_TIER_LIST = StructBlock(
    offset=0x14C8E554,
    size=0x38,
    count=0x07,
    record_format="<8B",
)

# ----- Track names (Giromon jukebox; variable-length) ----------------------

ROM_TRACK_NAME_BLOCK_OFFSET: Final = 0x14D717E8
ROM_TRACK_NAME_BLOCK_SIZE: Final = 0x738
ROM_TRACK_NAME_EXCLUSION_OFFSETS: Final = (0x14D71918,)  # in "Lava Cave Theme"
ROM_TRACK_NAME_EXCLUSION_SIZE: Final = 0x130


# =============================================================================
# ROM (BIN) — starter Digimon plumbing
# =============================================================================
#
# ``starterSetDigimonOffset`` writes the chosen starter id; the matching
# ``starterChkDigimonOffset`` is the id-check whose hit-result selects the
# starter's initial technique (``starterLearnTechOffset``) and equipped
# animation (``starterEquipAnimOffset``). The two parallel tuples cover
# the two starter slots.

ROM_STARTER_SET_DIGIMON: Final = (0x14D271C0, 0x14D271B8)
ROM_STARTER_CHK_DIGIMON: Final = (0x14CD1D24, 0x14CD1D44)
ROM_STARTER_LEARN_TECH: Final = (0x14CD1D40, 0x14CD1D60)
ROM_STARTER_EQUIP_ANIM: Final = (0x14CD1D30, 0x14CD1D50)
ROM_STARTER_STAT_CHK_DIGIMON: Final = 0x1407E2C5

ROM_DIGIMON_ID_FORMAT: Final = "<B"
ROM_TECH_ID_FORMAT: Final = "<B"
ROM_ANIM_ID_FORMAT: Final = "<B"

# Starter rookies (digimon ids the standalone allows as starter candidates).
STARTER_ROOKIES: Final = (0x03, 0x04, 0x11, 0x12, 0x1F, 0x20, 0x2D, 0x2E, 0x39)


# =============================================================================
# ROM (BIN) — type effectiveness, generic offsets
# =============================================================================

ROM_TYPE_EFFECTIVENESS_OFFSET: Final = 0x14D669F8
ROM_TYPE_EFFECTIVENESS_FORMAT: Final = "B"

# Location of the script blob inside the binary (used by the standalone for
# in-line text edits).
ROM_SCRIPT_OFFSET: Final = 0x13FD5809

# "Woah!" item-pickup banner string slot.
ROM_WOAH_PATCH_OFFSET: Final = 0x14D76EF4
ROM_WOAH_PATCH_FORMAT: Final = "<10s"

# Evolution-item patch (single byte) — disables the +stats-from-item gating.
ROM_EVO_ITEM_PATCH_OFFSET: Final = 0x14CF5AFC

# Tier 1 brain-training tech-learn offset (also used by the standalone's
# overall tech-learn rebalancing).
ROM_TIER_ONE_TECH_LEARN_OFFSET: Final = 0x14C8E58C

# Hash-into-Jijimon target for seed-identification text.
ROM_INTRO_HASH_OFFSET: Final = 0x140BD212

# Intro-scene skip jumps (paired with their destination ids).
ROM_INTRO_SKIP_OUTSIDE_OFFSET: Final = 0x1407DA20  # just after "Welcome to Digimon World"
ROM_INTRO_SKIP_OUTSIDE_DEST: Final = 2306
ROM_INTRO_SKIP_INSIDE_OFFSET: Final = 0x1407E44C   # just after "I invited you here\nto save us"
ROM_INTRO_SKIP_INSIDE_DEST: Final = 5108


# =============================================================================
# ROM (BIN) — softlock and progression-fix anchors
# =============================================================================
#
# These are write targets the standalone randomizer applies for known
# softlocks. They are kept here as *addresses*; the patch values themselves
# live in the patcher's payload (Phase 3) so this manifest stays content-free.

ROM_FIX_ROTATION_SOFTLOCK_OFFSETS: Final = (0x14CE72C0, 0x14CE7464)
ROM_FIX_ENTITY_MOVE_TO_SOFTLOCK_OFFSETS: Final = (0x14CDB140, 0x14CDB19C)
ROM_FIX_TOY_TOWN_SOFTLOCK_OFFSETS: Final = (0x14049DD8, 0x1404A2EA)
ROM_FIX_LEOMON_CAVE_NANIMON_SOFTLOCK_OFFSETS: Final = (
    0x14030380, 0x14030444, 0x14030D36, 0x14030DFA,
    0x140317F6, 0x140318BA, 0x140321C8, 0x1403228C,
)

ROM_OGREMON2_NANIMON_SOFTLOCK_OFFSETS: Final = (0x13FD689A, 0x140B7A1A)

# Recruit-spawn rate offsets, addressed per Digimon. Patch values live in
# the patcher's payload.
ROM_SPAWN_RATE_MAMEMON_OFFSETS: Final = (0x13FD678F, 0x140B790F)
ROM_SPAWN_RATE_PIXIMON_OFFSETS: Final = (0x13FD64DB, 0x13FDD389, 0x13FE0121, 0x140B765B)
ROM_SPAWN_RATE_MMAMEMON_OFFSETS: Final = (0x13FD831F, 0x140B949F)
ROM_SPAWN_RATE_OTAMAMON_OFFSETS: Final = (0x13FD7F47, 0x140B90C7)

# Type-locked-area unlocks.
ROM_UNLOCK_GREYLORD_OFFSETS: Final = (0x13FF808E,)
ROM_UNLOCK_ICE_OFFSETS: Final = (0x1401D130, 0x1401D2A8)
ROM_UNLOCK_TOY_TOWN_OFFSETS: Final = (0x140479EA,)

# Evolution-target unify hack and reset-button / custom-tick function.
ROM_EVO_TARGET_UNIFY_HACK_OFFSETS: Final = (0x14CD7520, 0x14D19A14, 0x14D19A20, 0x14D19A2C)
ROM_CUSTOM_TICK_FUNCTION_OFFSET: Final = 0x14D19A70
ROM_CUSTOM_TICK_HOOK_OFFSET: Final = 0x14D1A388

# Update-PP-calculation function rewrite anchor.
ROM_REWRITE_PP_OFFSET: Final = 0x14D2848C

# "Unrigged" tournament-slot patches in TRN_REL.BIN / TRN_REL2.BIN.
ROM_UNRIG_SLOTS_OFFSET: Final = 0x14C8DB10
ROM_UNRIG_SLOTS_2_OFFSET: Final = 0x14C941F8

# Tier-1-tech learn-and-command anchor.
ROM_LEARN_MOVE_AND_COMMAND_OFFSET: Final = 0x14C8821C

# DV-chip text replacements.
ROM_DV_CHIP_A_OFFSET: Final = 0x14D65F10  # 28 chars
ROM_DV_CHIP_D_OFFSET: Final = 0x14D65F2C  # 28 chars
ROM_DV_CHIP_E_OFFSET: Final = 0x14D65F48  # 28 chars

# Dragon Eye Lake vending machine string + price patches.
ROM_HAPPY_MUSHROOM_VEND_TEXT_1_OFFSET: Final = 0x13FE31C8
ROM_HAPPY_MUSHROOM_VEND_TEXT_2_OFFSET: Final = 0x13FE3300
ROM_HAPPY_MUSHROOM_VEND_PRICE_1_OFFSET: Final = 0x13FE3252
ROM_HAPPY_MUSHROOM_VEND_PRICE_2_OFFSET: Final = 0x13FE32F8
ROM_HAPPY_MUSHROOM_VEND_TRAIL_OFFSETS: Final = (0x13FE3326, 0x13FE3338, 0x13FE3382)

# Gabumon enemy-stats overwrite anchors (patch values are in the standalone's
# data.py and live in the patcher's payload).
ROM_GABU_PATCH_OFFSETS: Final = (
    0x0A7EEA8C,  # CurrentHP
    0x0A7EEA8E,  # CurrentMP
    0x0A7EEA90,  # MaxHP
    0x0A7EEA92,  # MaxMP
    0x0A7EEA94,  # Offense
    0x0A7EEA96,  # Defense
    0x0A7EEA98,  # Speed
    0x0A7EEA9A,  # Brains
    0x0A7EEA9C,  # Bits
)


# =============================================================================
# Recruit trigger remap data (Phase 4 v4 — full table)
# =============================================================================
#
# DW1's "recruit-cutscene-and-roster" trigger at each recruit spawn point
# reads a 2-byte little-endian "trigger ID" from a fixed ROM offset. The
# trigger ID is the index into the game's recruit table; the table maps
# trigger IDs to Digimon. By rewriting trigger IDs at spawn-point offsets,
# we change *which Digimon's recruit cutscene + city-roster effects fire*
# at each spot — without touching any code.
#
# **Important empirical finding (2026-04-28 live smoke test):** Swapping
# the trigger ID at Betamon's spawn-point offsets to Coelamon's trigger ID
# produced this behavior in-game:
#
#   * The wild encounter at Betamon's spawn point still spawned **Betamon**
#     (the encounter geometry/sprite key is independent of the recruit
#     trigger). The player fights Betamon.
#   * After winning, the recruit cutscene + city-roster effect that fires
#     is **Coelamon's** — Coelamon shows up in File City, not Betamon.
#
# This separates "fight done" (always vanilla, governed by encounter
# geometry) from "in city" (controlled by trigger ID), which is exactly
# the AP semantics the world wants:
#
#   * Walking to Digimon X's spawn → X's encounter fires → AP location
#     "X Recruit" sends.
#   * Receiving AP item "Y Recruit" → Y joins File City (delivered via
#     RAM bit set, see :data:`RECRUIT_RAM_BITS`).
#
# Trigger-remap is therefore the patch-side mechanism that decouples
# the two states; AP delivery handles the runtime side.
#
# Source for offsets and trigger IDs: standalone Digimon World randomizer
# at ``references/digimon_world_randomizer/digimon/data.py:309-502``
# (recruitOffsets table). Each entry there is
# ``( (trigger_offsets...), (name_offsets...), trigger_id, digimon_id )``.
# We carry only the trigger offsets and trigger ID — name strings are
# DEFERRED groundwork (the standalone's name-byte writes require RE'ing
# DW1's text encoding via ``scrutil.encode``, which is out of scope for
# this phase). When a Digimon's encounter is remapped, the on-screen
# name during the recruit cutscene will read the *vanilla* Digimon's
# name; AP-side messaging via the AP location text and item text covers
# the player-facing label gap until name-string writes land.
#
# Entries with empty trigger lists in the standalone (Seadramon, Megadramon
# — "does nothing in town and has no Jijimon message") are excluded here:
# there's nothing to remap for them.
#
# Entries the standalone left commented-out (Greymon, Monzaemon, Angemon,
# Birdramon, Vegiemon, Centarumon, Palmon) are partial-RE: only one
# trigger offset known. The standalone authors couldn't safely shuffle
# them. We mirror that decision via :data:`SHUFFLE_EXCLUDED_RECRUITS`.

ROM_RECRUIT_TRIGGER_FORMAT: Final = "<H"  # little-endian u16


class RecruitTriggerEntry(NamedTuple):
    """One row of the recruit trigger remap table.

    :param trigger_id: 2-byte little-endian ID written at each offset.
    :param trigger_offsets: ROM offsets where vanilla DW1 stores this
        Digimon's trigger ID. Sector-aware writes (FFT recipe) handle
        cross-sector positioning at patch time.
    :param name_offsets: ROM offsets where the Digimon's display name
        is stored as encoded bytes. Tracked for groundwork; not yet
        written by the patcher (text-encoding RE deferred).
    """

    trigger_id: int
    trigger_offsets: tuple[int, ...]
    name_offsets: tuple[int, ...]


ROM_RECRUIT_TRIGGERS: Final[dict[str, RecruitTriggerEntry]] = {
    "Betamon": RecruitTriggerEntry(
        trigger_id=204,
        trigger_offsets=(
            0x14059A40, 0x1405CA20, 0x1405CB42, 0x1405E344, 0x1406AB0A, 0x1405E6C2,
            0x14060890, 0x1405C40A, 0x1405E222, 0x1402C5AE, 0x1405E044, 0x13FE581A,
            0x13FD893A, 0x1405CD5C, 0x13FE503A, 0x1405E420, 0x1406D050, 0x1405C6A2,
            0x1402BBE6, 0x1406D7E6, 0x14063CE2, 0x1406BC52, 0x1406F12E, 0x1405E9B0,
            0x13FE5D32, 0x140B4572, 0x13FD8A4A, 0x140B9ABA, 0x1405C14A, 0x140B9BCA,
        ),
        name_offsets=(0x13FE9066, 0x13FE9BC8),
    ),
    "Devimon": RecruitTriggerEntry(
        trigger_id=206,
        trigger_offsets=(
            0x1406FE82, 0x1406F0A4, 0x140B6668, 0x13FE44A2, 0x140BA898, 0x140701D2,
            0x140BA7B4, 0x13FD9718, 0x13FD9634, 0x13FE543A, 0x1406D75C,
        ),
        name_offsets=(),
    ),
    "Tyrannomon": RecruitTriggerEntry(
        trigger_id=208,
        trigger_offsets=(
            0x13FE5A02, 0x1406D806, 0x14063D02, 0x1406AC0E, 0x140BA318, 0x1406B784,
            0x13FE591E, 0x13FD9120, 0x13FE5222, 0x1402BC06, 0x14059C28, 0x1406AB2A,
            0x1406D238, 0x1406BE3A, 0x13FE513E, 0x140BA442, 0x14059B44, 0x1406C646,
            0x1406F14E, 0x13FE5D52, 0x1406D154, 0x1406BD56, 0x1402C5CE, 0x13FE505A,
            0x13FE583A, 0x14059A60, 0x1406C9E6, 0x1405C16A, 0x1406D070, 0x1406BC72,
            0x140BA176, 0x14060A78, 0x140AD37A, 0x1402BCEA, 0x1406C07E, 0x1406D484,
            0x1405218A, 0x13FD9198, 0x14060994, 0x1402C796, 0x1405EB98, 0x140BA2A0,
            0x140598A4, 0x1405BFAE, 0x140608B0, 0x1402C6B2, 0x1405EAB4, 0x1405C5B6,
            0x140B47C0, 0x13FD92C2, 0x14051FC6, 0x14063ECA, 0x1402BDCE, 0x1405E9D0,
            0x1405C24E, 0x1406B3DE, 0x140AEBE2, 0x14063DE6, 0x1406D8EA, 0x1406ACF2,
            0x13FD8FF6, 0x1406D9CE,
        ),
        name_offsets=(0x1401727C,),
    ),
    "Meramon": RecruitTriggerEntry(
        trigger_id=209,
        trigger_offsets=(
            0x1406D802, 0x13FD9108, 0x1406AC0A, 0x1402BC02, 0x1406C910, 0x1406C516,
            0x140AD31A, 0x13FE521E, 0x14059C24, 0x1406AB26, 0x140BA42A, 0x1405C5B2,
            0x1406D234, 0x1406BE36, 0x13FE513A, 0x14059B40, 0x13FE5836, 0x1406F14A,
            0x13FE5D4E, 0x1406D150, 0x1406BD52, 0x1406D354, 0x13FE5056, 0x140BA15A,
            0x14059A5C, 0x1406C362, 0x1402BCE6, 0x1405C166, 0x1406D06C, 0x1406BC6E,
            0x14060A74, 0x13FD917C, 0x140B4880, 0x140AEB82, 0x14052186, 0x140BA288,
            0x1406B6C2, 0x14060990, 0x1402C792, 0x1405EB94, 0x13FE591A, 0x140598A0,
            0x13FD92AA, 0x140608AC, 0x1402C6AE, 0x1405EAB0, 0x1406B2B2, 0x1405C24A,
            0x14051FC2, 0x14063EC6, 0x1406D9CA, 0x1405E9CC, 0x1402BDCA, 0x13FD8FDA,
            0x1402C5CA, 0x14063DE2, 0x1406D8E6, 0x1406BF52, 0x1406ACEE, 0x13FE59FE,
            0x140BA2FC, 0x1405BFAA, 0x14063CFE,
        ),
        name_offsets=(0x13FF55CA,),
    ),
    "Numemon": RecruitTriggerEntry(
        trigger_id=211,
        trigger_offsets=(
            0x1406D760, 0x13FD95E0, 0x1406FC62, 0x13FE44A6, 0x1406FFC8, 0x140B5A62,
            0x140BA760, 0x140BA850, 0x1406F0A8, 0x13FD96D0, 0x13FE543E,
        ),
        name_offsets=(0x140745F6,),
    ),
    "Mamemon": RecruitTriggerEntry(
        trigger_id=213,
        trigger_offsets=(
            0x13FD9700, 0x140BA880, 0x1406D764, 0x13FE5446, 0x1406F0AC, 0x1407012E,
            0x13FE44AE, 0x140BA798, 0x140B598E, 0x13FD9618, 0x1406FDDC,
        ),
        name_offsets=(0x13FED010, 0x13FED476, 0x13FEDAB0, 0x1404CF06, 0x1404D9D0),
    ),
    "Gabumon": RecruitTriggerEntry(
        trigger_id=217,
        trigger_offsets=(
            0x14067588, 0x13FD8F0C, 0x140BA08C, 0x140672CE, 0x140B563C,
        ),
        name_offsets=(
            0x14036030, 0x14036C76, 0x1403729C, 0x14037C1A, 0x1403851A, 0x14038FB0,
            0x14039AE2,
        ),
    ),
    "Elecmon": RecruitTriggerEntry(
        trigger_id=218,
        trigger_offsets=(
            0x13FD89F0, 0x1405C5E2, 0x140B4D44, 0x1405C556, 0x1405C4E6, 0x1405C56A,
            0x13FD8C72, 0x140B9B70, 0x140B9DF2, 0x1405C596, 0x1405C084, 0x1405997A,
        ),
        name_offsets=(0x1400DCD6,),
    ),
    "Kabuterimon": RecruitTriggerEntry(
        trigger_id=219,
        trigger_offsets=(
            0x1402E900, 0x140B8BF0, 0x14030F06, 0x140319C6, 0x1402E308, 0x1402FECC,
            0x1402DBAC, 0x1402E090, 0x1402DE34, 0x14032398, 0x13FD7A70, 0x140B5B3A,
            0x1402E6BE,
        ),
        name_offsets=(0x140294CC,),
    ),
    "Garurumon": RecruitTriggerEntry(
        trigger_id=222,
        trigger_offsets=(
            0x1406B880, 0x13FE5A06, 0x1406D80A, 0x13FD9012, 0x140AEC2E, 0x1406CADA,
            0x13FE5922, 0x14063D06, 0x13FE5226, 0x14059C2C, 0x1406AB2E, 0x140BA334,
            0x13FD9138, 0x140608B4, 0x1406D23C, 0x1402BC0A, 0x13FE583E, 0x1406C742,
            0x14059B48, 0x1405EAB8, 0x1406F152, 0x13FE5D56, 0x1406D158, 0x1406BD5A,
            0x13FE505E, 0x14059A64, 0x1406AC12, 0x1405C16E, 0x1406D9D2, 0x1406D074,
            0x1406BE3E, 0x1406BC76, 0x140BA45A, 0x1406C17A, 0x14060A7C, 0x1406D580,
            0x13FE5142, 0x1405218E, 0x140BA192, 0x1402BCEE, 0x14060998, 0x1402C79A,
            0x1405EB9C, 0x140598A8, 0x1405BFB2, 0x13FD91B4, 0x1402C6B6, 0x140BA2B8,
            0x1405C5BA, 0x140AD3C6, 0x14051FCA, 0x14063ECE, 0x1402C5D2, 0x1405E9D4,
            0x13FD92DA, 0x140B4B26, 0x14063DEA, 0x1406B4DA, 0x1402BDD2, 0x1406D8EE,
            0x1405C252, 0x1406ACF6,
        ),
        name_offsets=(0x1401F5FE,),
    ),
    "Frigimon": RecruitTriggerEntry(
        trigger_id=223,
        trigger_offsets=(
            0x14060A80, 0x1406C280, 0x140BA472, 0x1402BDD6, 0x14063D0A, 0x140B118C,
            0x13FE5842, 0x1406D80E, 0x14052192, 0x13FD902E, 0x1406CC16, 0x1406B99A,
            0x1406099C, 0x13FE5D5A, 0x1402C79E, 0x1405EBA0, 0x13FE5926, 0x140AEEAA,
            0x140598AC, 0x1405C172, 0x140BA1AE, 0x14059C30, 0x1406AB32, 0x1405BFB6,
            0x140608B8, 0x1402C6BA, 0x1405EABC, 0x13FE5A0A, 0x1405C5BE, 0x1406D240,
            0x1406BE42, 0x1406C844, 0x13FE5146, 0x1402C5D6, 0x1402BCF2, 0x14059B4C,
            0x1405C256, 0x14051FCE, 0x140BA350, 0x14063ED2, 0x1406AC16, 0x1402BC0E,
            0x1406F156, 0x1405E9D8, 0x140B4A80, 0x1406D15C, 0x1406ACFA, 0x1406BD5E,
            0x1406B5E0, 0x13FD9150, 0x13FE5062, 0x1406D9D6, 0x14063DEE, 0x14059A68,
            0x1406D8F2, 0x13FD91D0, 0x1406D078, 0x13FD92F2, 0x1406BC7A, 0x140BA2D0,
            0x13FE522A,
        ),
        name_offsets=(0x14040D2E,),
    ),
    "Whamon": RecruitTriggerEntry(
        trigger_id=224,
        trigger_offsets=(
            0x140B57F4, 0x13FD86FC, 0x1405BF76, 0x140B987C, 0x1405986C, 0x1405B1FE,
        ),
        name_offsets=(0x1404507C,),
    ),
    "SkullGreymon": RecruitTriggerEntry(
        trigger_id=226,
        trigger_offsets=(0x140B68BE,),
        name_offsets=(),
    ),
    "MetalMamemon": RecruitTriggerEntry(
        trigger_id=227,
        trigger_offsets=(0x13FD9982, 0x140B617C, 0x140BAB02),
        name_offsets=(0x1404CEFC, 0x1404D9C6),
    ),
    "Vademon": RecruitTriggerEntry(
        trigger_id=228,
        trigger_offsets=(
            0x13FD91F0, 0x140BA370, 0x13FD904E, 0x140AEEEA, 0x140B11CC, 0x140B626E,
            0x140BA1CE,
        ),
        name_offsets=(0x13FEEC54, 0x1407C2BE, 0x1407CCDC),
    ),
    "Patamon": RecruitTriggerEntry(
        trigger_id=231,
        trigger_offsets=(
            0x140B9BD6, 0x1406086C, 0x1402C58A, 0x1405E98C, 0x1402BBC2, 0x13FE5D0E,
            0x13FE5016, 0x14059A1C, 0x140BA49E, 0x140BA122, 0x13FD8946, 0x1405C126,
            0x1406D02C, 0x1406BC2E, 0x1405C6B0, 0x13FD931E, 0x1406F10A, 0x14072B0A,
            0x14063CBE, 0x13FD9560, 0x1406D7C2, 0x13FE57F6, 0x140B9AC6, 0x1405E6A2,
            0x13FD8A56, 0x140598D8, 0x1406DADE, 0x140BA6E0, 0x1405BFE2, 0x1406AAE6,
            0x1405C3EA, 0x1407056C, 0x14072670, 0x1405C972, 0x1406E176, 0x140B507C,
            0x13FD8FA2,
        ),
        name_offsets=(0x1400E69C,),
    ),
    "Kunemon": RecruitTriggerEntry(
        trigger_id=232,
        trigger_offsets=(
            0x1405E4C6, 0x13FE5B08, 0x140B6C4A, 0x13FE438C, 0x1405C50E, 0x13FE5614,
            0x13FD8CAE, 0x140B9E2E, 0x13FE43B0, 0x13FE5324, 0x13FE5B2C, 0x13FD89B2,
            0x140B432E, 0x13FE55F0, 0x13FE5348, 0x140B9B32,
        ),
        name_offsets=(0x13FDE31A,),
    ),
    "Unimon": RecruitTriggerEntry(
        trigger_id=233,
        trigger_offsets=(
            0x13FD9356, 0x1406E30A, 0x13FD9590, 0x1406F112, 0x1405E994, 0x13FE5D16,
            0x13FE501E, 0x14059A24, 0x1405E6AA, 0x1405C12E, 0x1406D034, 0x140B9BDE,
            0x1406BC36, 0x140B4FB8, 0x14060874, 0x1406D7CA, 0x1406DDC2, 0x14063CC6,
            0x1402BBCA, 0x140B9ACE, 0x1405C6B8, 0x13FD894E, 0x140BA4D6, 0x1402C592,
            0x13FD8A5E, 0x140598E0, 0x140BA710, 0x1405BFEA, 0x14072B12, 0x1406AAEE,
            0x13FD8FAA, 0x1405C3F2, 0x14070574, 0x14072678, 0x1405C97A, 0x140BA12A,
            0x13FE57FE,
        ),
        name_offsets=(0x13FEE4D6, 0x13FEF912, 0x13FF0B34, 0x1407B97C),
    ),
    "Ogremon": RecruitTriggerEntry(
        trigger_id=234,
        trigger_offsets=(0x13FD8BD2, 0x140B9D52, 0x140B5E82),
        name_offsets=(0x13FF193E,),
    ),
    "Shellmon": RecruitTriggerEntry(
        trigger_id=235,
        trigger_offsets=(
            0x13FD8BF6, 0x1405E4A4, 0x140B9D76, 0x13FD8BBE, 0x1405C4EA, 0x140B9B0A,
            0x1405C496, 0x140B4C64, 0x13FD898A, 0x140B9D3E,
        ),
        name_offsets=(0x1403967A, 0x14039A0C),
    ),
    "Bakemon": RecruitTriggerEntry(
        trigger_id=237,
        trigger_offsets=(
            0x13FD8970, 0x140B9AF0, 0x13FD8C4A, 0x140B9DCA, 0x140B462E,
        ),
        name_offsets=(0x13FF7FB2, 0x13FF8C34, 0x13FF95B0, 0x13FF9EBA),
    ),
    "Drimogemon": RecruitTriggerEntry(
        trigger_id=238,
        trigger_offsets=(0x140B5568, 0x14059854, 0x1405B1E4, 0x1405BF5E),
        name_offsets=(0x13FF6416, 0x13FF6E38, 0x13FF7912),
    ),
    "Sukamon": RecruitTriggerEntry(
        trigger_id=239,
        trigger_offsets=(0x13FD87F6, 0x140B9976),
        name_offsets=(),
    ),
    "Andromon": RecruitTriggerEntry(
        trigger_id=240,
        trigger_offsets=(0x13FD8780, 0x140B9900, 0x140B6990),
        name_offsets=(0x1404FAA2, 0x140519FA),
    ),
    "Giromon": RecruitTriggerEntry(
        trigger_id=241,
        trigger_offsets=(0x140B5DE0, 0x1405E514),
        name_offsets=(0x14052A40, 0x14052D5C),
    ),
    "Etemon": RecruitTriggerEntry(
        trigger_id=242,
        trigger_offsets=(0x13FDD278, 0x13FE0010, 0x13FD63CA, 0x140B754A, 0x140B60CE),
        name_offsets=(0x13FDF51C, 0x13FDFE62),
    ),
    "Biyomon": RecruitTriggerEntry(
        trigger_id=245,
        trigger_offsets=(
            0x14072B0E, 0x1405E990, 0x13FE5D12, 0x13FE501A, 0x13FD8A5A, 0x14059A20,
            0x14060870, 0x1406D7C6, 0x140BA126, 0x1405C12A, 0x140B5132, 0x1406D030,
            0x1406BC32, 0x1405C6B4, 0x13FD933A, 0x140B9ACA, 0x1406E240, 0x14063CC2,
            0x1402BBC6, 0x13FD894A, 0x13FD9578, 0x1406DC52, 0x1406F10E, 0x1402C58E,
            0x140B9BDA, 0x140598DC, 0x140BA4BA, 0x1405E6A6, 0x1405BFE6, 0x1406AAEA,
            0x1405C3EE, 0x14070570, 0x14072674, 0x1405C976, 0x13FD8FA6, 0x140BA6F8,
            0x13FE57FA,
        ),
        name_offsets=(0x1400F8E0,),
    ),
    "Monochromon": RecruitTriggerEntry(
        trigger_id=247,
        trigger_offsets=(
            0x13FE5802, 0x14072B16, 0x13FD8FAE, 0x1406F116, 0x1405E998, 0x13FE5D1A,
            0x13FE5022, 0x14059A28, 0x140BA4F2, 0x1405E6AE, 0x1406DF30, 0x1405C132,
            0x1406BC3A, 0x1405C6BC, 0x1406E3BE, 0x1402C596, 0x14063CCA, 0x140B9BE2,
            0x1406D7CE, 0x140B4ED0, 0x14060878, 0x13FD8952, 0x1402BBCE, 0x13FD8A62,
            0x13FD95A8, 0x140598E4, 0x140B9AD2, 0x1405BFEE, 0x140BA728, 0x1406AAF2,
            0x140BA12E, 0x1405C3F6, 0x14070578, 0x1407267C, 0x13FD9372, 0x1405C97E,
        ),
        name_offsets=(0x14000BDC,),
    ),
    "Leomon": RecruitTriggerEntry(
        trigger_id=248,
        trigger_offsets=(0x140B5F30, 0x13FD8ED2, 0x140BA052),
        name_offsets=(0x140128F0,),
    ),
    "Coelamon": RecruitTriggerEntry(
        trigger_id=249,
        trigger_offsets=(
            0x1405C63A, 0x1405C68A, 0x1406AB0E, 0x1405C612, 0x14060894, 0x13FE581E,
            0x1405E424, 0x1405C626, 0x1405CA28, 0x1405E22A, 0x1402C5B2, 0x1406F132,
            0x1405E9B4, 0x13FE5D36, 0x13FD8FBA, 0x1405E03C, 0x13FE503E, 0x140B44C0,
            0x14059A44, 0x1405CB46, 0x1405E348, 0x1405C64E, 0x1406D054, 0x1405C14E,
            0x1406BC56, 0x140B6DDC, 0x140BA13A, 0x1405CD60, 0x1405C662, 0x14063CE6,
            0x1406D7EA, 0x1405C676, 0x1405E47C, 0x1402BBEA, 0x1405C5FE,
        ),
        name_offsets=(0x13FE08B0,),
    ),
    "Kokatorimon": RecruitTriggerEntry(
        trigger_id=250,
        trigger_offsets=(
            0x140B9946, 0x13FD87C6, 0x14059908, 0x1405994A, 0x1405C012, 0x1405C054,
            0x140B4E06, 0x13FD873A, 0x140B98BA,
        ),
        name_offsets=(0x14032E4A,),
    ),
    "Kuwagamon": RecruitTriggerEntry(
        trigger_id=251,
        trigger_offsets=(0x13FD7A82, 0x140B5D3C, 0x140B8C02),
        name_offsets=(0x1402A706,),
    ),
    "Mojyamon": RecruitTriggerEntry(
        trigger_id=252,
        trigger_offsets=(
            0x13FE5442, 0x140B58A4, 0x1406FD28, 0x140BA77C, 0x13FE44AA, 0x13FD96E8,
            0x1407006E, 0x1406F0B0, 0x1406D768, 0x140BA868, 0x13FD95FC,
        ),
        name_offsets=(0x1403CE4E, 0x1403D17C, 0x1403D788, 0x1403DAB6, 0x1403E04E),
    ),
    "Nanimon": RecruitTriggerEntry(
        trigger_id=253,
        trigger_offsets=(0x13FD8F5A, 0x140BA0DA, 0x140B63C6),
        name_offsets=(),
    ),
    "Piximon": RecruitTriggerEntry(
        trigger_id=255,
        trigger_offsets=(0x140B600A, 0x13FD9396, 0x140BA516),
        name_offsets=(0x13FE6B1A, 0x13FE6F98, 0x13FE75D6),
    ),
    "Digitamamon": RecruitTriggerEntry(
        trigger_id=256,
        trigger_offsets=(
            0x13FD9210, 0x140BA390, 0x13FD906E, 0x140AEF36, 0x140B67EE, 0x140BA1EE,
        ),
        name_offsets=(0x140774C8, 0x140788B0),
    ),
    "Penguinmon": RecruitTriggerEntry(
        trigger_id=257,
        trigger_offsets=(
            0x14066400, 0x140BAB1E, 0x140632A4, 0x140B53E6, 0x140663AC, 0x14063250,
            0x14066374, 0x14095A7E, 0x14063218, 0x1409761C, 0x13FD999E,
        ),
        name_offsets=(0x14096804,),
    ),
    "Ninjamon": RecruitTriggerEntry(
        trigger_id=258,
        trigger_offsets=(0x140B573A, 0x13FD95CE, 0x140BA74E),
        name_offsets=(0x13FE4AD6,),
    ),
}

# All Digimon for which the recruit trigger lives at known ROM offsets and
# can therefore be remapped. Excludes:
#   * "Greymon" (trigger 205, 1 offset known) — partial-RE in standalone.
#   * "Seadramon" (trigger 210) — vanilla "does nothing in town".
#   * "Monzaemon" (trigger 214, 1 offset known) — partial-RE.
#   * "Angemon" (trigger 220, 1 offset known) — partial-RE.
#   * "Birdramon" (trigger 221, 1 offset known) — partial-RE.
#   * "Vegiemon" (trigger 225, 1 offset known) — partial-RE.
#   * "MetalGreymon" (trigger 229) — Megadramon-only token in standalone, no entry.
#   * "Centarumon" (trigger 236, 1 offset known) — partial-RE.
#   * "Palmon" (trigger 246, 1 offset known) — partial-RE.
#   * "Megadramon" (trigger 254) — vanilla "does nothing".
SHUFFLEABLE_RECRUITS: Final[frozenset[str]] = frozenset(ROM_RECRUIT_TRIGGERS.keys())

# Recruits that the standalone DW1 randomizer flagged as softlock-prone:
# their unique cutscenes/quests have edge cases where the player gets
# stuck if the encounter is fired out of expected sequence. We unblock
# them by applying the standalone's softlock-fix MIPS patches (see
# ``ROM_FIX_*`` constants below) — once those land, all four are
# shuffleable.
SOFTLOCK_RISK_RECRUITS: Final[frozenset[str]] = frozenset({
    "Whamon",
    "Drimogemon",
    "Ogremon",
    "Nanimon",
})

# Final shuffle pool — what AP can both ship as items and route to recruit
# locations. With softlock fixes applied this is identical to
# :data:`SHUFFLEABLE_RECRUITS`.
SHUFFLE_INCLUDED_RECRUITS: Final[frozenset[str]] = SHUFFLEABLE_RECRUITS


# =============================================================================
# PP-calc patch (Phase 4 v4)
# =============================================================================
#
# Vanilla DW1 derives a Digimon's max PP for each technique slot from a
# table whose layout is incompatible with arbitrary-recruit assignment:
# remapping a Digimon to a different evolution slot can produce 0-PP
# techniques. The standalone DW1 randomizer rewrites the PP-lookup
# function to use a flat addressing scheme that's stable under
# remapping. Source: ``references/digimon_world_randomizer/digimon/data.py:709-713``.
#
# The 11 32-bit MIPS instructions below replace the vanilla function at
# ``ROM_PP_CALC_PATCH_OFFSET``. The values are stored ">I" (big-endian)
# in the standalone — DW1's instructions live in ROM in MIPS forward
# byte order, which on a little-endian PSX means each instruction word
# in ROM is the big-endian render of the encoded instruction. We follow
# the standalone's format exactly.

ROM_PP_CALC_PATCH_OFFSET: Final = 0x14D2848C
ROM_PP_CALC_PATCH_FORMAT: Final = ">IIIIIIIIIII"  # 11 big-endian u32 instructions
ROM_PP_CALC_PATCH_VALUE: Final = (
    0x0F19040C, 0xFFFF6432, 0x1E004010, 0x00000000, 0x1380023C, 0xCECE4224,
    0x21105200, 0x00004290, 0x03004230, 0x21885100, 0x16000010,
)


# =============================================================================
# Trigger array geometry (informational)
# =============================================================================
# DW1's recruit/chest/story-flag bitfield is a contiguous array starting
# at :data:`AP_TRIGGER_ARRAY_BASE`. The script-engine opcode
# ``setTrigger N`` (0x1C) ORs bit ``(N % 8)`` of byte ``base + (N // 8)``.
# Verified 2026-04-28 by decoding 8 recruit bits in :data:`RECRUIT_RAM_BITS`
# from their trigger IDs (203..258).
#
# We don't use this constant directly anywhere in the patcher today, but
# it documents the relationship for future RE work.

AP_TRIGGER_ARRAY_BASE: Final = 0x001BDFCD


# =============================================================================
# Standalone-derived softlock fix patches (Phase 4 v5)
# =============================================================================
#
# The standalone DW1 randomizer ships a small set of MIPS-instruction
# patches that fix specific softlock paths exposed by recruit shuffling.
# Source: ``references/digimon_world_randomizer/digimon/data.py:715-733``.
#
# Applying these unconditionally lets us include Whamon, Drimogemon,
# Ogremon, and Nanimon in the shuffleable pool. Without them, those
# four are gated out of the AP location pool because their vanilla
# encounter chains can softlock when triggered out of expected order.

ROM_FIX_ROTATION_FORMAT: Final = "B"
ROM_FIX_ROTATION_VALUE: Final = 0x0D
ROM_FIX_ROTATION_OFFSETS: Final = (0x14CE72C0, 0x14CE7464)

ROM_FIX_MOVE_TO_FORMAT: Final = "<I"
ROM_FIX_MOVE_TO_VALUE: Final = 0x10400006
ROM_FIX_MOVE_TO_OFFSETS: Final = (0x14CDB140, 0x14CDB19C)

ROM_FIX_TOY_TOWN_FORMAT: Final = ">I"
ROM_FIX_TOY_TOWN_VALUE: Final = 0x31FCA302
ROM_FIX_TOY_TOWN_OFFSETS: Final = (0x14049DD8, 0x1404A2EA)

ROM_FIX_LEO_CAVE_FORMAT: Final = "B"
ROM_FIX_LEO_CAVE_VALUE: Final = 0x3B
ROM_FIX_LEO_CAVE_OFFSETS: Final = (
    0x14030380, 0x14030444, 0x14030D36, 0x14030DFA,
    0x140317F6, 0x140318BA, 0x140321C8, 0x1403228C,
)

ROM_OGREMON_SOFTLOCK_FORMAT: Final = "<H"
ROM_OGREMON_SOFTLOCK_VALUE: Final = 235
ROM_OGREMON_SOFTLOCK_OFFSETS: Final = (0x13FD689A, 0x140B7A1A)


# =============================================================================
# Chest item replacement (Phase 4 v9)
# =============================================================================
#
# DW1 stores each chest's reward as a 2-byte ``spawnChest`` script entry:
# byte 0 = opcode (``0x75``), byte 1 = 1-byte item ID. Source for the
# offset table:
# ``references/digimon_world_randomizer/digimon/data.py:230-243``
# (``chestItemOffsets``).
#
# The standalone enumerated **73** chest entries — slightly more than
# DWAP's 65-named chest list. The extra 8 entries are mid-cutscene or
# secondary chest spawns we don't track as AP locations. Patching all
# 73 is safe: AP only reacts to the 65 we have detection bits for; the
# rest just become AP-sentinel grants the player won't notice.
#
# Replacement strategy: write item ID :data:`AP_CHEST_SENTINEL_ITEM_ID`
# (83 = ``0x53``) at every chest's item byte. ID 83 corresponds to
# vanilla "Electo ring" — confirmed unused / crash-on-use per the
# standalone Digimon World randomizer (which excludes Electro Ring and
# Moon Mirror from its chest pool, marking them gamebreaking) and live
# user verification 2026-04-29. We overwrite slot 83's entry in
# ITEM_PARA with our "AP ITEM" name so the chest "Found ..." textbox
# renders cleanly. Slot 83 is well inside ITEM_PARA's 128 x 32 byte
# region, so writing 32 bytes there does NOT spill into the adjacent
# ITEM_DESC_PTR table (the slot-129 bug).
#
# Companion behavior: the AP client wipes any inventory slot containing
# ID 83 each tick (defensive belt-and-suspenders pairing with the
# chestGiveItem wrapper). Net effect: chest opens, "AP ITEM" briefly
# appears in inventory if any pickup path bypasses the wrapper, next
# tick it's gone. The AP location fires from the chest-bit signal
# independent of item delivery, so detection is unaffected.
#
# Reserved for future use: ID 114 (= ``0x72``, vanilla "Moon mirror") is
# also unused / gamebreaking and is the next available unused slot if
# we ever need a second sentinel-style item.

AP_CHEST_SENTINEL_ITEM_ID: Final = 0x53  # 83 — vanilla "Electo ring", unused/gamebreaking

ROM_CHEST_ITEM_FORMAT: Final = "B"
ROM_CHEST_ITEM_VALUE: Final = AP_CHEST_SENTINEL_ITEM_ID

# We also write a real 32-byte item-table entry at slot 129 so DW1's
# chest-pickup textbox displays a clean "Found AP ITEM" message instead
# of garbled glyphs from random adjacent memory. Entry layout (32 bytes):
#
#   bytes 0..19 : name (ASCII, NUL-padded, max 19 chars + 1 NUL)
#   bytes 20..31: stats (price u32, then misc fields)
#
# We zero the stats — the item should have no real use; the client
# wipes it from inventory within ~100ms anyway. If DW1 happens to call
# the item's use-handler with all-zero stats, worst case is a no-op or
# a brief glitch; the wipe makes such interaction nearly impossible.

ROM_ITEM_TABLE_BASE: Final = 0x14D676C4
ROM_ITEM_TABLE_ENTRY_SIZE: Final = 32

AP_ITEM_NAME: Final = b"AP ITEM"  # 7 bytes, padded to 20 with NULs

# 32 bytes: name (20) padded with NULs + 12 zero bytes for stats
ROM_AP_ITEM_ENTRY_BYTES: Final = (
    AP_ITEM_NAME.ljust(20, b"\x00") + b"\x00" * 12
)
assert len(ROM_AP_ITEM_ENTRY_BYTES) == ROM_ITEM_TABLE_ENTRY_SIZE, len(ROM_AP_ITEM_ENTRY_BYTES)


def _table_byte_to_bin_flat(table_byte_offset: int) -> int:
    """Translate a table-internal byte offset to a sector-aware flat BIN offset.

    The item-data table starts at flat BIN ``ROM_ITEM_TABLE_BASE`` (sector
    148639, user-data position 500) and continues for ``0x1260`` bytes
    of user data. Because the BIN includes Mode2/2352 sector headers
    (24 bytes) and EC blocks (280 bytes) interspersed, naive
    ``base + offset`` arithmetic skips into EC zones for entries past
    the first ~48. This helper hops over sector boundaries correctly.
    """

    base_sector = ROM_ITEM_TABLE_BASE // SECTOR_SIZE_BYTES
    base_pos_in_sector = ROM_ITEM_TABLE_BASE - base_sector * SECTOR_SIZE_BYTES
    base_pos_in_user_data = base_pos_in_sector - SECTOR_HEADER_BYTES
    pos = base_pos_in_user_data + table_byte_offset
    sector_advance, pos_within = divmod(pos, USER_DATA_BYTES)
    sector = base_sector + sector_advance
    return sector * SECTOR_SIZE_BYTES + SECTOR_HEADER_BYTES + pos_within


ROM_AP_ITEM_ENTRY_OFFSET: Final = _table_byte_to_bin_flat(
    AP_CHEST_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE,
)
# Sanity: a 32-byte entry must not straddle a sector boundary, otherwise
# the apply_tokens flat write would clobber a sector header / EC region.
_entry_end = _table_byte_to_bin_flat(
    AP_CHEST_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE
    + ROM_ITEM_TABLE_ENTRY_SIZE - 1,
)
assert (_entry_end - ROM_AP_ITEM_ENTRY_OFFSET) == ROM_ITEM_TABLE_ENTRY_SIZE - 1, (
    f"AP ITEM entry crosses a sector boundary: "
    f"start=0x{ROM_AP_ITEM_ENTRY_OFFSET:08X}, end=0x{_entry_end:08X}"
)

# Each entry below is the ROM offset of the chest's spawnChest opcode
# (byte 0). The item-ID byte we want to overwrite lives at offset+1.
ROM_CHEST_ITEM_OFFSETS: Final = (
    0x13FE3118, 0x13FE6844, 0x13FEE01E, 0x13FEE02A, 0x13FEE036, 0x13FF4DE8,
    0x13FF4DF4, 0x13FF6978, 0x13FF6984, 0x13FFA098, 0x13FFD7BC, 0x13FFE0F0,
    0x13FFF35C, 0x14000EDC, 0x14000EE8, 0x14000EF4, 0x14003398, 0x140033A4,
    0x14005868, 0x140073E8, 0x140073F4, 0x14008F7C, 0x14021168, 0x14021174,
    0x14022D04, 0x14023624, 0x14023630, 0x14023F54, 0x14023F60, 0x14030964,
    0x140377A8, 0x13FF58AA, 0x13FF58B6, 0x14038A04, 0x13FFA508, 0x14039338,
    0x140396CA, 0x1403AEC4, 0x1403AED0, 0x1403AEDC, 0x1403AEE8, 0x14045424,
    0x1404A6DC, 0x140539EC, 0x140539F8, 0x1405430C, 0x14054318, 0x14054324,
    0x1405836C, 0x14058C9C, 0x14067B7C, 0x1406970C, 0x14073334, 0x14078F1C,
    0x14079848, 0x14079854, 0x14079860, 0x1407986C, 0x1407A178, 0x1407A184,
    0x1407AA94, 0x1407AAA0, 0x1407AAAC, 0x1407AAB8, 0x1407BD46, 0x1407BD52,
    0x1407BD5E, 0x1407F430, 0x1407FD54, 0x14080688, 0x14080FB4, 0x140818F4,
    0x14081900,
)
assert len(ROM_CHEST_ITEM_OFFSETS) == 73, len(ROM_CHEST_ITEM_OFFSETS)


# =============================================================================
# Chest-pickup giveItem wrapper (Phase 5 piece A)
# =============================================================================
#
# Sentinel-aware ``giveItem`` wrapper installed at SydPatches' "Cave6"
# free-space region (RAM 0x800957C0..0x80096BCC, identified as unused
# libgs functions — verified self-contained: every jal/j into Cave6 in
# vanilla originates from inside Cave6).
#
# Behavior: if the caller's first argument (``$a0``, the item ID) equals
# :data:`AP_CHEST_SENTINEL_ITEM_ID` (83 / 0x53 = vanilla "Electo ring",
# overwritten with "AP ITEM" via :data:`ROM_AP_ITEM_ENTRY_BYTES`), the
# wrapper returns 1 ("success") without touching inventory. Otherwise
# it tail-calls vanilla ``giveItem`` (RAM 0x800C5240) with arguments
# unchanged. Net effect: chests holding the sentinel display "AP ITEM"
# via the patched item table entry, the chest's "taken" state still
# flips (vanilla treats the wrapper's return as success), and no item
# lands in the player's inventory. AP delivers the *real* AP-fill item
# separately to the player's bank via the client's deliverer routes.
#
# Wrapper byte layout (28 bytes / 7 MIPS instructions, all little-endian):
#
#   addiu $at, $0, 83      0x24010053   load sentinel constant (Electo ring)
#   beq   $a0, $at, +3     0x10810003   if item == 83 -> jr $ra branch
#   nop                    0x00000000   delay slot
#   j     0x800C5240       0x08031490   tail-call vanilla giveItem
#   nop                    0x00000000   delay slot of j
#   jr    $ra              0x03E00008   sentinel return path
#   addiu $v0, $0, 1       0x24020001   delay slot: $v0 = 1 (true)

ROM_CHEST_GIVEITEM_WRAPPER_RAM: Final = 0x800957C0
ROM_CHEST_GIVEITEM_WRAPPER_OFFSET: Final = 0x14CC0B18
ROM_CHEST_GIVEITEM_WRAPPER_BYTES: Final = bytes((
    0x53, 0x00, 0x01, 0x24,  # addiu $at, $0, 83
    0x03, 0x00, 0x81, 0x10,  # beq   $a0, $at, +3
    0x00, 0x00, 0x00, 0x00,  # nop (delay slot)
    0x90, 0x14, 0x03, 0x08,  # j     0x800C5240 (giveItem)
    0x00, 0x00, 0x00, 0x00,  # nop (delay slot of j)
    0x08, 0x00, 0xE0, 0x03,  # jr    $ra
    0x01, 0x00, 0x02, 0x24,  # addiu $v0, $0, 1 (delay slot of jr)
))
assert len(ROM_CHEST_GIVEITEM_WRAPPER_BYTES) == 28, len(ROM_CHEST_GIVEITEM_WRAPPER_BYTES)

# Patch site: replace the chest-pickup ``jal giveItem`` (vanilla
# ``0x0C031490`` = ``jal 0x800C5240``) at vanilla RAM 0x80102E6C with
# ``jal ROM_CHEST_GIVEITEM_WRAPPER_RAM`` (= ``0x0C0255F0``). This is
# the only ``jal giveItem`` callsite in the SLUS whose success path
# calls ``unsetTrigger(0)`` and failure path calls ``setTrigger(0)`` —
# the unique fingerprint of the chest-take script-bytecode opcode
# handler (vanilla equivalent of SydPatches' ``Tamer_tickTakeChest``
# state 2).

ROM_CHEST_GIVEITEM_PATCH_FORMAT: Final = "<I"
ROM_CHEST_GIVEITEM_PATCH_OFFSET: Final = 0x14D3E5D4
ROM_CHEST_GIVEITEM_PATCH_VALUE: Final = (
    0x0C000000 | ((ROM_CHEST_GIVEITEM_WRAPPER_RAM >> 2) & 0x03FFFFFF)
)
assert ROM_CHEST_GIVEITEM_PATCH_VALUE == 0x0C0255F0, hex(ROM_CHEST_GIVEITEM_PATCH_VALUE)


# =============================================================================
# setTrigger wrapper for recruit-fight/recruit-join split (Phase 5 piece C)
# =============================================================================
#
# Vanilla DW1 sets a "Digimon X has joined city" trigger bit at trigger ID
# ``200 + digimon_id`` (range 203..258 for digimon_ids 3..58). Setting that
# bit kicks off all of joining: PP recompute via :func:`recalculatePPandArena`,
# in-city model spawn, business cards, dialogs, etc. The bit is set by
# script bytecode (post-fight cutscenes, NPC dialog, plot triggers — there
# is no ``setTrigger(200+i)`` in compiled C code).
#
# To split "fight completed" (an AP location signal) from "Digimon joins
# city" (an AP item reward), we wrap the vanilla ``setTrigger`` function
# (RAM 0x801065c0) with a small filter installed in SydPatches' Cave6
# free-space region (immediately after :data:`ROM_CHEST_GIVEITEM_WRAPPER_*`):
#
# * If the caller's first argument (``$a0``, the trigger ID) lies in
#   the recruit range 203..258, the wrapper adds 520 to it, redirecting
#   the bit-set to the **beaten** range 723..778. Vanilla join effects
#   (PP, model spawn, etc.) read trigger 200+i and stay off.
# * Otherwise ``$a0`` is unchanged.
# * The wrapper then continues with vanilla ``setTrigger``'s body
#   (replicating its replaced first two instructions: stack frame setup
#   and saving ``$ra``).
#
# AP detection polls the **beaten** bits (bytes 0x001BE027..0x001BE02E,
# fully unused by vanilla — verified statically: no ``jal setTrigger /
# unsetTrigger / isTriggerSet`` callsite in vanilla SLUS uses an
# immediate >= 717, and the highest known dynamic-loop trigger ID is
# 253 from the recruit-iteration loop). AP item delivery (the
# "<Digimon> Recruit" item) writes the recruit bit ``200+i`` directly
# via ``bizhawk.write`` — bypassing the wrapper.
#
# Wrapper byte layout (32 bytes / 8 MIPS instructions, little-endian):
#
#   addiu $at, $a0, -203      0x2481FF35   r1 = a0 - 203
#   sltiu $t0, $at, 56          0x2C280038   t0 = (r1 < 56) ? 1 : 0
#   beq   $t0, $0, +2 -> next  0x11000002   skip the redirect if not in range
#   nop                         0x00000000   delay slot
#   addiu $a0, $a0, 520         0x24840208   redirect: 203..258 -> 723..778
#   addiu $sp, $sp, -32         0x27BDFFE0   original setTrigger instr 1
#   j     0x801065C8            0x08041972   jump to setTrigger+8 to continue
#   sw    $ra, 16($sp)          0xAFBF0010   original setTrigger instr 2 (delay slot)

ROM_SETTRIGGER_WRAPPER_RAM: Final = 0x800957DC
ROM_SETTRIGGER_WRAPPER_OFFSET: Final = 0x14CC0B34
ROM_SETTRIGGER_WRAPPER_BYTES: Final = bytes((
    0x35, 0xFF, 0x81, 0x24,  # addiu $at, $a0, -203
    0x38, 0x00, 0x28, 0x2C,  # sltiu $t0, $at, 56
    0x02, 0x00, 0x00, 0x11,  # beq   $t0, $0, +2
    0x00, 0x00, 0x00, 0x00,  # nop (delay slot)
    0x08, 0x02, 0x84, 0x24,  # addiu $a0, $a0, 520
    0xE0, 0xFF, 0xBD, 0x27,  # addiu $sp, $sp, -32  (orig instr 1)
    0x72, 0x19, 0x04, 0x08,  # j     0x801065C8
    0x10, 0x00, 0xBF, 0xAF,  # sw    $ra, 16($sp)  (orig instr 2, delay slot)
))
assert len(ROM_SETTRIGGER_WRAPPER_BYTES) == 32, len(ROM_SETTRIGGER_WRAPPER_BYTES)

# Patch site: replace vanilla ``setTrigger``'s first 2 instructions
# (``addiu $sp,$sp,-32`` + ``sw $ra,16($sp)``) with ``j wrapper`` + ``nop``.
# 8 bytes at ROM offset 0x14D42578 (RAM 0x801065C0).

ROM_SETTRIGGER_PATCH_FORMAT: Final = "<II"
ROM_SETTRIGGER_PATCH_OFFSET: Final = 0x14D42578
ROM_SETTRIGGER_PATCH_VALUE: Final = (
    0x08000000 | ((ROM_SETTRIGGER_WRAPPER_RAM >> 2) & 0x03FFFFFF),  # j wrapper
    0x00000000,                                                      # nop
)
assert ROM_SETTRIGGER_PATCH_VALUE[0] == 0x080255F7, hex(ROM_SETTRIGGER_PATCH_VALUE[0])


# =============================================================================
# Recruit-bit RAM addresses (per-Digimon, Phase 5 piece C)
# =============================================================================
#
# :data:`RECRUIT_RAM_BITS` (above) maps each Digimon to the byte/bit of its
# vanilla "joined city" recruit bit. The setTrigger wrapper redirects these
# at the source — vanilla never sets them after fight. Three derived maps:
#
# * :data:`BEATEN_RAM_BITS` — the (byte, bit) of each Digimon's redirected
#   "beaten in fight" bit. The AP client polls these for fight-completion
#   detection (the LocationCheck signal).
# * :data:`AGUMON_RECRUIT_BIT` — Agumon is the bank NPC and a key game
#   mechanic; the player must always have him in city for AP item delivery
#   to work. The client force-sets this bit on connection so Agumon joins
#   immediately, regardless of when the Agumon-fight cutscene actually
#   triggers in the player's run. Note: the Agumon-fight AP location still
#   fires from the beaten bit when the player completes that cutscene; we
#   only suppress the join-city redirect for Agumon by pre-setting the bit.
# * :data:`AP_RECRUIT_ITEM_DIGIMON` — the 49-element ordered tuple of
#   Digimon names that ship as "<X> Recruit" AP items (everyone except
#   Agumon). Used by the item table builder and the client's deliverer
#   route registration.

_BEATEN_TRIGGER_OFFSET: Final = 520


def _ram_bit_after_offset(byte_addr: int, bit: int, trigger_offset: int) -> tuple[int, int]:
    """Apply the wrapper's offset to a (byte, bit) pair, returning the new pair."""

    trigger_id = (byte_addr - 0x001BDFCD) * 8 + bit
    new_id = trigger_id + trigger_offset
    new_byte, new_bit = divmod(new_id, 8)
    return (0x001BDFCD + new_byte, new_bit)


BEATEN_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    name: _ram_bit_after_offset(byte, bit, _BEATEN_TRIGGER_OFFSET)
    for name, (byte, bit) in RECRUIT_RAM_BITS.items()
}

# Sanity-check that no beaten byte overlaps the prosperity counter or
# any chest bit we already use.
_beaten_bytes = {byte for byte, _ in BEATEN_RAM_BITS.values()}
_chest_bytes = {byte for byte, _ in DWAP_CHEST_RAM_BITS.values()}
assert max(_beaten_bytes) < 0x001BE032, (
    f"Beaten range overflows into RAM_PROSPERITY_POINTS at 0x001BE032: "
    f"max byte 0x{max(_beaten_bytes):08X}"
)
assert _beaten_bytes.isdisjoint(_chest_bytes), (
    f"Beaten range overlaps chest bits: {_beaten_bytes & _chest_bytes}"
)

AGUMON_RECRUIT_BIT: Final[tuple[int, int]] = RECRUIT_RAM_BITS["Agumon"]

# AP-item Digimon = every recruit *except* Agumon (Agumon is force-recruited
# by the client because he's the bank NPC).
AP_RECRUIT_ITEM_DIGIMON: Final[tuple[str, ...]] = tuple(
    name for name in RECRUIT_RAM_BITS if name != "Agumon"
)
assert len(AP_RECRUIT_ITEM_DIGIMON) == 49, len(AP_RECRUIT_ITEM_DIGIMON)


# =============================================================================
# changeMap wrapper (Phase 5 polish — race-free city/field bit sync)
# =============================================================================
#
# Vanilla DW1's screen-change function lives at RAM 0x800D8E64 (verified
# 2026-04-29 via Lua probe at the SydPatches-documented call site
# 0x80105C2C). When the player crosses a screen boundary, the function
# is called with $a0 = destination map id, then runs the new map's
# scripts which read recruit bits (0x001BDFE6 block) inline.
#
# We hook this call by replacing the JAL at 0x80105C2C with JAL to a
# wrapper installed in Cave6 free-space. The wrapper:
#   1. Looks up whether $a0 is a city screen via a precomputed bitmap
#      at :data:`ROM_CITY_BITMAP_RAM`.
#   2. Copies an 8-byte source block to the recruit byte block:
#      - in city: source = AP-bits mirror (0x001BDFF0)
#      - in field: source = permanent-beaten scratch (0x001BDFF8)
#   3. Tail-calls vanilla 0x800D8E64.
#
# Because the copy runs synchronously *before* vanilla loads the new
# map's scripts, vanilla scripts read the correct bit values at the
# moment they need them. No race window like the per-tick toggle has.
#
# The two source blocks are maintained by the AP client each tick:
#   - AP-bits mirror = OR of (received Recruit items, Agumon bit always)
#   - Permanent-beaten = OR of (current beaten block, Agumon bit always)
# Agumon's bit is always set so the bank NPC stays in city.

# Cave6 layout after our existing wrappers (BIN offset of each):
#   0x14CC0B18  chest wrapper (28 bytes, RAM 0x800957C0..DC)
#   0x14CC0B34  setTrigger wrapper (32 bytes, RAM 0x800957DC..FC)
#   0x14CC0B54  4-byte gap (rest of sector 148348)
#   0x14CC0C88  changeMap wrapper (128 bytes, RAM 0x80095800..80)
#   0x14CC0D08  city screens bitmap (32 bytes, RAM 0x80095880..A0)
# The 4-byte gap is unavoidable: setTrigger ends at sector 148348 ud-pos
# 2044 and there's only room for 4 more bytes in that sector. We jump
# to the start of the next sector for the wrapper's first instruction
# so the whole wrapper + bitmap fits in one sector (148349).

ROM_CHANGEMAP_WRAPPER_RAM: Final = 0x80095800
ROM_CHANGEMAP_WRAPPER_OFFSET: Final = 0x14CC0C88

# Permanent-beaten scratch — same byte/bit layout as the recruit block.
# Maintained by the client each tick: bit X = (Digimon X has ever been
# beaten in the wild) OR (X == Agumon). Vanilla never reads/writes this
# range — it's in the unused-trigger gap right after the AP-bits mirror.
RAM_PERMANENT_BEATEN_SCRATCH_BASE: Final = 0x001BDFF8
RAM_PERMANENT_BEATEN_SCRATCH_SIZE: Final = 8

# AP-bits mirror is already declared in client.py (AP_BITS_MIRROR_BASE
# = 0x001BDFF0). The wrapper uses it as the in-city source. We restate
# its address here so the wrapper bytes can encode it.
_AP_BITS_MIRROR_RAM: Final = 0x801BDFF0  # virtual = MainRAM 0x001BDFF0
_PERM_BEATEN_RAM: Final = 0x801BDFF8     # virtual = MainRAM 0x001BDFF8

# Confirm adjacency — wrapper relies on (PERM_BEATEN - AP_MIRROR == 8)
# for the conditional-source trick.
assert _PERM_BEATEN_RAM - _AP_BITS_MIRROR_RAM == 8, (
    "AP_BITS_MIRROR and PERMANENT_BEATEN must be adjacent 8-byte blocks "
    "for the changeMap wrapper's conditional-source arithmetic to work",
)

ROM_CHANGEMAP_WRAPPER_BYTES: Final = b"".join(
    val.to_bytes(4, "little") for val in (
        # SIMPLIFIED WRAPPER (Plan A): always copy AP_BITS_MIRROR into
        # the recruit-block at every screen transition. No city/field
        # branching — recruit-block now has a single, consistent
        # semantic ("which Digimon has AP delivered Recruit for"), and
        # field-spawn suppression is handled by ROM-patching individual
        # field-spawn scripts to read trigger 720+X (PERM_BEATEN range)
        # instead of trigger 200+X.

        # Source = AP_BITS_MIRROR (0x801BDFF0)
        0x3C0B801B,  # lui   $t3, 0x801B
        0x356BDFF0,  # ori   $t3, $t3, 0xDFF0

        # Dest = recruit-block (0x801BDFE6)
        0x3C0C801B,  # lui   $t4, 0x801B
        0x358CDFE6,  # ori   $t4, $t4, 0xDFE6

        # Copy 8 bytes via 4 LHU/SH pairs
        0x956D0000,  # lhu   $t5, 0($t3)
        0x00000000,  # nop  (load delay)
        0xA58D0000,  # sh    $t5, 0($t4)
        0x956D0002,  # lhu   $t5, 2($t3)
        0x00000000,  # nop
        0xA58D0002,  # sh    $t5, 2($t4)
        0x956D0004,  # lhu   $t5, 4($t3)
        0x00000000,  # nop
        0xA58D0004,  # sh    $t5, 4($t4)
        0x956D0006,  # lhu   $t5, 6($t3)
        0x00000000,  # nop
        0xA58D0006,  # sh    $t5, 6($t4)

        # Tail-call vanilla scriptTickChangeMap
        0x08036399,  # j     0x800D8E64
        0x00000000,  # nop
    )
)
assert len(ROM_CHANGEMAP_WRAPPER_BYTES) == 72, len(ROM_CHANGEMAP_WRAPPER_BYTES)


# City-screens bitmap — 32 bytes covering screen IDs 0..255. Bit (id %
# 8) of byte (id // 8) is set iff that screen ID is "in city" by our
# definition. Generated from the same set the client uses (mirrored
# verbatim from `client.py:CITY_SCREENS`). Sourced from DWAP's full
# screen->region table.

ROM_CITY_BITMAP_RAM: Final = 0x80095880
ROM_CITY_BITMAP_OFFSET: Final = 0x14CC0D08

_CITY_SCREENS_FOR_BITMAP: Final[frozenset[int]] = frozenset({
    *range(168, 209),     # File City Top + Bottom + Jijimon + Birdra + Arena lobby
    211,                  # Item Keeper
    *range(213, 219),     # Centar Clinic, Restaurants, Shops, Jijimon Base
    223,                  # Arena Lobby (with MetalGreymon/Airdramon)
    236, 237, 238,        # File City Top cutscene variants
})

def _build_city_bitmap() -> bytes:
    bm = bytearray(32)
    for screen in _CITY_SCREENS_FOR_BITMAP:
        bm[screen >> 3] |= 1 << (screen & 7)
    return bytes(bm)

ROM_CITY_BITMAP_BYTES: Final = _build_city_bitmap()
assert len(ROM_CITY_BITMAP_BYTES) == 32, len(ROM_CITY_BITMAP_BYTES)


# JAL-replacement at the vanilla call site. Vanilla had
# JAL 0x800D8E64 (= 0x0C036399) at RAM 0x80105C2C; we replace it with
# JAL ROM_CHANGEMAP_WRAPPER_RAM (= 0x0C025600).

ROM_CHANGEMAP_PATCH_FORMAT: Final = "<I"
ROM_CHANGEMAP_PATCH_OFFSET: Final = 0x14D41AB4
ROM_CHANGEMAP_PATCH_VALUE: Final = (
    0x0C000000 | ((ROM_CHANGEMAP_WRAPPER_RAM >> 2) & 0x03FFFFFF)
)
assert ROM_CHANGEMAP_PATCH_VALUE == 0x0C025600, hex(ROM_CHANGEMAP_PATCH_VALUE)


# =============================================================================
# Field-spawn trigger ID redirects (Plan A — per-Digimon)
# =============================================================================
#
# Vanilla DW1 gates each Digimon's wild-spawn on `if trigger(200+X)`,
# where X is the digimon's recruit ID. We need the wild-spawn to be
# suppressed when the player has *beaten* the Digimon (regardless of
# AP delivery), but we want the *city visibility* and *variant
# selector* to read AP-delivered status. The recruit-block (which
# trigger 200+X reads from) is now always AP_MIRROR, so reading
# trigger 200+X for the field check no longer suppresses respawn.
#
# Fix: ROM-patch the trigger-ID bytes inside the script bytecode of
# each Digimon's wild-spawn `if` to use trigger 720+X (= PERM_BEATEN
# range, set by the setTrigger wrapper redirect). This makes the
# field-spawn check read the beaten flag directly.
#
# Each entry below is a (BIN offset, original trigger ID, new trigger
# ID) tuple. Only Betamon for now — once verified, the rest of the 56
# recruits get added.

ROM_FIELD_SPAWN_TRIGGER_FORMAT: Final = "<H"
ROM_FIELD_SPAWN_TRIGGER_PATCHES: Final = (
    # Betamon: Section_15 (his wild encounter screen) line 1978
    # `if trigger(204) == TRUE then SKIP loadDigimon` → use trigger 724.
    # info.txt:758 marks this as "Recruitable Betamon".
    (0x13FD6576, 204, 724),
)


# =============================================================================
# isTriggerSet wrapper — recruit-bit read redirect (Phase 5 piece D)
# =============================================================================
#
# Vanilla DW1 reads the recruit-block byte at trigger ID ``200 + i`` (i.e.
# trigger 203..258 for the 56 recruitable Digimon) via ``isTriggerSet``
# (RAM 0x8010643C). Many vanilla scripts call this — variant selectors
# at city boundaries, NPC visibility checks, ``recalculatePPandArena``
# (prosperity), etc.
#
# We *want* every vanilla "is X recruited?" query to see the AP-authorized
# answer (= AP_BITS_MIRROR), regardless of whatever the recruit-block
# currently holds. The recruit-block is dual-purposed by the changeMap
# wrapper (writes AP_MIRROR in city, PERM_BEATEN in field) for spawn
# suppression in field — meaning that during the field-tile-warp script
# that runs *just before* a city transition, ``isTriggerSet(200+X)``
# would see the PERM_BEATEN value (X has been beaten) and pick the
# wrong city variant.
#
# The fix is to install a tiny wrapper at the head of vanilla
# ``isTriggerSet`` that, for trigger IDs in the recruit range 203..258,
# reads the bit from ``AP_BITS_MIRROR`` (RAM 0x801BDFF0) directly and
# returns it. For all other trigger IDs, the wrapper falls through to
# vanilla ``isTriggerSet`` body unchanged.
#
# This makes the recruit-bit READ semantics consistent: vanilla always
# sees AP-delivered status, regardless of what the recruit-block scratch
# happens to contain at the moment of the call. The recruit-block can
# now safely double as the field-spawn-suppression scratch (PERM_BEATEN)
# without poisoning city-variant selection.
#
# We replace the first 2 instructions of vanilla ``isTriggerSet`` with
# ``j wrapper; nop``. The wrapper does its range check without touching
# the stack, returns directly via ``jr $ra`` for the AP_MIRROR path,
# and for the fall-through path replicates the two replaced instructions
# (``addiu $sp, -32``, ``sw $ra, 16($sp)``) before jumping to
# ``isTriggerSet+8`` (= 0x80106444).
#
# Wrapper byte layout (80 bytes / 20 MIPS instructions, all little-endian):
#
#   addiu $at, $a0, -203    0x2481FF35    at = a0 - 203
#   sltiu $t0, $at, 56      0x2C280038    t0 = (at < 56) ? 1 : 0
#   beq   $t0, $0, +13      0x1100000D    if not in range, jump to ORIG
#   nop                     0x00000000    delay slot of beq
#   # AP_MIRROR path:
#   addiu $at, $at, 3       0x24210003    at = at + 3 = a0 - 200 (= X)
#   srl   $t1, $at, 3       0x000148C2    t1 = X / 8           (byte offset)
#   andi  $t2, $at, 7       0x302A0007    t2 = X & 7           (bit index)
#   lui   $t3, 0x801B       0x3C0B801B
#   ori   $t3, $t3, 0xDFF0  0x356BDFF0    t3 = AP_BITS_MIRROR base
#   addu  $t3, $t3, $t1     0x01695821    t3 = &AP_BITS_MIRROR[byte]
#   lbu   $t3, 0($t3)       0x916B0000    t3 = byte value
#   nop                     0x00000000    load-delay slot
#   srlv  $t3, $t3, $t2     0x014B5806    t3 = byte >> bit
#   andi  $v0, $t3, 1       0x31620001    v0 = (t3 & 1)
#   jr    $ra               0x03E00008    return
#   nop                     0x00000000    delay slot of jr
#   # ORIG path: replicate replaced instructions, jump to vanilla body+8
#   addiu $sp, $sp, -32     0x27BDFFE0
#   sw    $ra, 16($sp)      0xAFBF0010
#   j     0x80106444        0x08041911    isTriggerSet+8
#   nop                     0x00000000    delay slot of j

ROM_ISTRIGGERSET_WRAPPER_RAM: Final = 0x800958B0
ROM_ISTRIGGERSET_WRAPPER_OFFSET: Final = 0x14CC0D38
ROM_ISTRIGGERSET_WRAPPER_BYTES: Final = b"".join(
    val.to_bytes(4, "little") for val in (
        # Range check
        0x2481FF35,  # addiu $at, $a0, -203
        0x2C280038,  # sltiu $t0, $at, 56
        0x1100000D,  # beq   $t0, $0, +13   ; ORIG
        0x00000000,  # nop
        # AP_MIRROR path
        0x24210003,  # addiu $at, $at, 3    ; at = a0 - 200
        0x000148C2,  # srl   $t1, $at, 3
        0x302A0007,  # andi  $t2, $at, 7
        0x3C0B801B,  # lui   $t3, 0x801B
        0x356BDFF0,  # ori   $t3, $t3, 0xDFF0
        0x01695821,  # addu  $t3, $t3, $t1
        0x916B0000,  # lbu   $t3, 0($t3)
        0x00000000,  # nop  (load delay)
        0x014B5806,  # srlv  $t3, $t3, $t2
        0x31620001,  # andi  $v0, $t3, 1
        0x03E00008,  # jr    $ra
        0x00000000,  # nop  (delay slot)
        # ORIG path: replicate replaced instructions + jump to body+8
        0x27BDFFE0,  # addiu $sp, $sp, -32
        0xAFBF0010,  # sw    $ra, 16($sp)
        0x08041911,  # j     0x80106444
        0x00000000,  # nop  (delay slot)
    )
)
assert len(ROM_ISTRIGGERSET_WRAPPER_BYTES) == 80, len(ROM_ISTRIGGERSET_WRAPPER_BYTES)

# Patch site: replace the first 2 instructions of vanilla isTriggerSet
# (RAM 0x8010643C..0x80106443) with `j wrapper; nop`.
# Vanilla 0x8010643C: addiu $sp, $sp, -32  (replaced)
# Vanilla 0x80106440: sw    $ra, 0x10($sp) (replaced)
# We place these two equivalent instructions inside the wrapper's ORIG
# path so the original semantics are preserved when the wrapper falls
# through.

ROM_ISTRIGGERSET_PATCH_FORMAT: Final = "<II"
ROM_ISTRIGGERSET_PATCH_OFFSET: Final = 0x14D423F4
ROM_ISTRIGGERSET_PATCH_VALUE: Final = (
    # j ROM_ISTRIGGERSET_WRAPPER_RAM (delay-slot nop follows)
    0x08000000 | ((ROM_ISTRIGGERSET_WRAPPER_RAM >> 2) & 0x03FFFFFF),
    0x00000000,  # nop (delay slot of j)
)
assert ROM_ISTRIGGERSET_PATCH_VALUE[0] == 0x0802562C, hex(
    ROM_ISTRIGGERSET_PATCH_VALUE[0],
)


# =============================================================================
# Phase 5 polish — QoL options
# =============================================================================
# Per-option constants used by ``rom.py`` (patcher-side ROM writes) and
# ``client.py`` (RAM-side per-tick enforcement). Source attribution and
# explanations live alongside each block.

# ----- Fast Drimogemon (client-side; mirrors DWAP) --------------------------
#
# Source: ``references/DWAP/source/DWAP/App.axaml.cs:417-428`` and
# ``Addresses.cs:36-39``. Once the player beats Drimogemon (HasBeaten bit
# set), the client writes three single-byte flags to mark the Lava Cave
# tunnel as already dug and the dig pile as empty, collapsing the 10-day
# in-game wait. Idempotent: writes only fire when the current values
# differ from target.

RAM_HAS_BEATEN_DRIMOGEMON: Final = 0x001BE130        # u8 — read; 1 = beaten
RAM_MERAMON_TUNNEL_DRIMO_STATE: Final = 0x001BE042   # u8 — write 2 (talked)
RAM_MERAMON_TUNNEL_STATE: Final = 0x001BE043         # u8 — write 10 (dug)
RAM_MERAMON_TUNNEL_DIGGING_STATE: Final = 0x001BE04F  # u8 — write 5 (empty)

FAST_DRIMOGEMON_DRIMO_STATE_TARGET: Final = 2
FAST_DRIMOGEMON_TUNNEL_STATE_TARGET: Final = 10
FAST_DRIMOGEMON_DIGGING_STATE_TARGET: Final = 5


# ----- Easy Monochromon (client-side; mirrors DWAP) --------------------------
#
# Source: ``references/DWAP/source/DWAP/App.axaml.cs:413-415``. While the
# player is on the Monochromon business map (id 49 = 0x31), pin the
# profit counter to 4000 so the trade resolves immediately. The
# RAM_MONOCHROME_PROFIT address (0x0013500C) is already declared above.

EASY_MONOCHROMON_MAP_ID: Final = 49           # only act when on this map
EASY_MONOCHROMON_PROFIT_TARGET: Final = 4000  # u32 LE


# ----- Stat Gain Multiplier (client-side; mirrors DWAP) ----------------------
#
# Source: ``references/DWAP/source/DWAP/App.axaml.cs:348-355``. Vanilla
# DW1 stores a stat-gain multiplier and a stat cap in three adjacent
# fields. Writing all three each tick (and only when option > 1) bumps
# training speed by the chosen factor.
#
# Layout (verified against DWAP's writes):
#   0x001384AC : 1 byte — stat-cap-unlock flag, set to 63 (0x3F)
#   0x001384AE : u16 LE — multiplier (DWAP writes ``factor * 10``)
#   0x001384B0 : u16 LE — stat cap, set to 9999

RAM_STAT_CAP_FLAG: Final = 0x001384AC
RAM_STAT_GAIN_MULT: Final = 0x001384AE
RAM_STAT_CAP: Final = 0x001384B0
STAT_CAP_FLAG_TARGET: Final = 63       # 0x3F
STAT_CAP_TARGET: Final = 9999          # u16 LE


# ----- Skip Intro (ROM-side; mirrors standalone) -----------------------------
#
# Source: ``references/digimon_world_randomizer/digimon/handler.py:2576-2591``
# and ``digimon/data.py:694-698``. Two ``jumpTo`` opcodes inserted at the
# end of the welcome textbox sequence and the "I invited you here" line,
# fast-forwarding past the dialogue. Each jumpTo is a 4-byte instruction
# (``<BxH``: opcode 0x16, padding 0x00, dest u16 LE).

ROM_SKIP_INTRO_OUTSIDE_OFFSET: Final = 0x1407DA20
ROM_SKIP_INTRO_OUTSIDE_DEST: Final = 2306         # u16
ROM_SKIP_INTRO_INSIDE_OFFSET: Final = 0x1407E44C
ROM_SKIP_INTRO_INSIDE_DEST: Final = 5108          # u16
ROM_SKIP_INTRO_FORMAT: Final = "<BxH"             # opcode 0x16 + pad + dest
ROM_SKIP_INTRO_OPCODE: Final = 0x16               # vanilla DW1 ``jumpTo`` opcode


# ----- Type-Lock Unlocks (ROM-side; mirrors standalone) ----------------------
#
# Source: ``references/digimon_world_randomizer/digimon/handler.py:2629-2652``
# and ``digimon/data.py:752-762``. Three independent patches:
#
# * **Greylord's Mansion** — overwrite the type-check jump with a plain
#   value at one offset.
# * **Ice Sanctuary** — same idea, two offsets.
# * **Toy Town** — a 4-byte rewrite at one offset.

ROM_UNLOCK_TYPE_LOCK_FORMAT: Final = "<H"

ROM_UNLOCK_GREYLORD_VALUE: Final = 1226
ROM_UNLOCK_GREYLORD_OFFSETS: Final = (0x13FF808E,)

ROM_UNLOCK_ICE_VALUE: Final = 60
ROM_UNLOCK_ICE_OFFSETS: Final = (0x1401D130, 0x1401D2A8)

ROM_UNLOCK_TOY_TOWN_FORMAT: Final = "<I"
ROM_UNLOCK_TOY_TOWN_VALUE: Final = 0x015D0001
ROM_UNLOCK_TOY_TOWN_OFFSETS: Final = (0x140479EA,)


# ----- Spawn Rate boost (ROM-side; mirrors standalone) -----------------------
#
# Source: ``references/digimon_world_randomizer/digimon/handler.py:2520-2559``
# and ``digimon/data.py:770-774``. Each rare-spawn Digimon's encounter
# check site stores a single byte that the engine compares against a
# random roll. Mamemon/Piximon/MetalMamemon use a 0..99 RNG (we write
# ``percent - 1``); Otamamon uses a 0..2 RNG (we write
# ``floor(percent / 33)``).

ROM_SPAWN_RATE_FORMAT: Final = "<B"
ROM_SPAWN_RATE_MAMEMON_OFFSETS: Final = (0x13FD678F, 0x140B790F)
ROM_SPAWN_RATE_PIXIMON_OFFSETS: Final = (
    0x13FD64DB, 0x13FDD389, 0x13FE0121, 0x140B765B,
)
ROM_SPAWN_RATE_MMAMEMON_OFFSETS: Final = (0x13FD831F, 0x140B949F)
ROM_SPAWN_RATE_OTAMAMON_OFFSETS: Final = (0x13FD7F47, 0x140B90C7)
