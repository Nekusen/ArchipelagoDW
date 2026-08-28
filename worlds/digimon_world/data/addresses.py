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

import struct
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

RAM_INVENTORY_SIZE: Final = 0x0013D4CE         # u8, current inventory capacity
# ^^^ Verified by adjacency: the inventory data block at
# RAM_INVENTORY_ITEM_IDS_BASE (0x0013D474) and RAM_INVENTORY_QUANTITIES_BASE
# (0x0013D492) was live-verified 2026-04-28, and the size byte sits at the
# end of the same 0x0013D4xx block. DWAP's 0x000DD4CE was a transcription
# error inherited prior to verification (a previous TBD comment flagged it).
# The vanilla script-engine `setInventorySize` opcode writes here (game
# default = 10, after first keychain = 20, after fourth Nanimon visit = 30).
# AP's client reconciles this byte to 10 + 10*min(Progressive Keychain
# received count, 2), clamped to [10, 30].
RAM_INVENTORY_MAX_SIZE: Final = 30             # vanilla structural cap
RAM_INVENTORY_DEFAULT_SIZE: Final = 10         # vanilla starting capacity
KEYCHAIN_INVENTORY_PER_ITEM: Final = 10        # each Progressive Keychain bumps by 10
KEYCHAIN_MAX_COPIES: Final = 2                 # vanilla questline gives 2 keychains total

# Player on-hand inventory: 10 fixed slots. Item ID byte at +i, quantity
# byte at +i+0x1E (0x1E = 30 between IDs and quantities — verified live
# 2026-04-28 by writing test items and watching them appear in the in-game
# menu). Empty slot = ID 0xFF.
RAM_INVENTORY_ITEM_IDS_BASE: Final = 0x0013D474
RAM_INVENTORY_QUANTITIES_BASE: Final = 0x0013D492
RAM_INVENTORY_SLOT_COUNT: Final = 10
RAM_INVENTORY_EMPTY_SLOT_ID: Final = 0xFF

# Full-stack quantity for one on-hand inventory slot. Ground truth: the
# shop inventory-fit scan (``build_shop_runtime_list``, VERIFIED decomp
# 2026-08-20, ``work/dw1_re/decomp/build_shop_runtime_list/NOTES.md``)
# treats a held item as mergeable only while its count byte is below
# 0x63, and refuses a purchase when the item is held with a full stack
# even when empty slots remain — vanilla keeps ONE stack per item id.
# The client's inventory-first delivery mirrors these semantics.
RAM_INVENTORY_STACK_CAP: Final = 0x63  # 99

# DW1 internal item id for "Auto Pilot" (consumable that warps the
# player back to File City when used from the on-hand inventory).
# Cross-verified three ways: ITEM_PARA name scan
# (``tools/dw1_scan_recycle_shop_flex.py`` matches ``b"Auto Pilot\x00"``
# at slot 0x16), the recycle-shop stock table (id 0x16, price 300), and
# the items.py catalog ("slot 22 = Auto Pilot — omitted, already in the
# player's starting inventory"). Used by the client's Infinite Auto
# Pilot reconciler (``infinite_auto_pilot`` option).
AUTO_PILOT_ITEM_ID: Final = 0x16  # 22

RAM_ITEM_BANK_BASE: Final = 0x001BDF2C         # per-slot bank entries (verified live)
RAM_ITEM_BANK_SIZE: Final = 128                # one byte per slot, 128 slots
RAM_CURRENT_BITS: Final = 0x00134EB8           # u32 LE — money (verified live 2026-04-28)
RAM_MONOCHROME_PROFIT: Final = 0x0013500C      # Monochromon side-business cash

# ----- Fishing locations ----------------------------------------------------
#
# Fish AP locations work by client-side heuristic: when the player is on a
# fishing screen (MAYO06 / MAYO10, screen IDs 6 and 8 — verified by
# ``checkFishingMap`` in ``references/DW1-SydPatches/src/Fishing.cpp:81``)
# and the inventory count of a fish item increases between two watcher
# ticks, the client fires the corresponding AP location.
#
# Why count-tracking instead of "fish present in inventory while on screen":
# the player can enter MAYO06 / MAYO10 with a fish already in inventory
# (e.g. carried over from the Dragon Eye Lake chest pickup or a prior
# fishing session whose AP location was already fired). The
# already-present-fish case must NOT fire the location.
#
# AP-delivered fish items always land in the **bank** (the inventory-first
# delivery added 2026-08-22 carves the 6 fish ids out as bank-only exactly
# so a foreign-world ``Digiseabass`` delivery cannot inflate the inventory
# count and cause a false fire — see ``client._INVENTORY_BANK_ONLY_IDS``).
# The only real false-positive path is opening the Dragon Eye Lake chest
# while standing on screen 6 or 8 — small enough to accept per user
# direction.
#
# DW1 internal item IDs for the 6 fish (= ``dw_code - 2000`` per the bank
# layout above; verified against ``worlds.digimon_world.items`` slot 62..67):
FISH_LOCATION_INVENTORY_IDS: Final[tuple[tuple[str, int], ...]] = (
    ("Fishing: Digianchovy",  62),
    ("Fishing: Digisnapper",  63),
    ("Fishing: DigiTrout",    64),
    ("Fishing: Black trout",  65),
    ("Fishing: Digicatfish",  66),
    ("Fishing: Digiseabass",  67),
)
FISHING_LOCATION_NAMES: Final[tuple[str, ...]] = tuple(
    name for name, _ in FISH_LOCATION_INVENTORY_IDS
)
# Screen IDs at which DW1 enables fishing (= ``mapId == 6 || mapId == 8``
# in ``Fishing.cpp:checkFishingMap``). MAYO06 / MAYO10 in
# :data:`SCREEN_FILENAMES`. Both screens are part of the AP ``Greatlake``
# region (Dragon Eye Lake cluster).
FISHING_SCREEN_IDS: Final[frozenset[int]] = frozenset({6, 8})

# ----- Recruit / town progress ---------------------------------------------

# = pstat(1) = save block + 0x15A. Vanilla recomputes it in
# ``recalculatePPandArena`` (sum of ``level - 2`` per recruited Digimon,
# Numemon/Sukamon/Nanimon = 1); the client re-asserts the AP value every
# tick. DOOA_REL/MURD_REL also compare it ``>= 50`` hard-coded, but only
# to pick a message. (dw_decomp audit 2026-08-28.)
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

# ----- Machinedramon / Analogman defeated goal trigger ---------------------
#
# Canonical "you beat the base game" flag is **trigger 50** (Analogman
# defeated). It is set exactly once in the entire script dump — at
# `references/digimon_world_randomizer_syd/script/DW1Script.txt:29210`
# (offset 004406), inside Script 184 §51's post-Machinedramon victory
# cutscene, immediately after the textboxes "Analogman is gone." /
# "Peace has returned to File Island." and immediately before the
# `warpTo 237 0 51` (line 29220) that triggers the C-level credits roll
# (`Tamer_tickEnding` → `ENDI_tickEnding` at SLUS 0x80060d00, see
# `references/DW1-SydPatches/SLUS_labels.asm:362-363`).
#
# Translation of trigger 50 via the standard formula
# (``mem[0x001BDFCD + N/8] |= 1 << (N%8)``):
#     byte = 0x001BDFCD + 6 = 0x001BDFD3
#     bit  = 1 << 2 = 0x04
#
# Why this flag and not trigger 202 (the previous estimate):
#   - `setTrigger 202` only appears in NPC apology dialogs at lines
#     10663, 12301, 15998 ("All of a sudden, I passed out. I'm sorry.")
#     — a transient conversational flag, NOT the win-cutscene marker.
#   - Trigger 202 is even `unsetTrigger 202`'d at DW1Script.txt:24113.
#   - Trigger 202's byte (0x001BDFE6) sits inside the changeMap-wrapper
#     clobber range (0x001BDFE6..0x001BDFED), so it would be cleared on
#     every screen transition anyway.
# Trigger 50 has none of these problems: never unset, lives at
# 0x001BDFD3 (outside the wrapper range), and is read 23+ times across
# the script database as the canonical "post-game" gate (Digitamamon
# NG+ spawn, Jijimon "you saved File Island" dialog, Airdramon city
# visibility, etc.). The standalone randomizer documents it identically
# (`references/digimon_world_randomizer_syd/info.txt:260` — "trigger(50)
# aka beat the game").
#
# Save-persistent: the trigger bit-array is serialized to memory card,
# so once `setTrigger 50` fires the bit survives power cycles and
# save/reload. Polling-and-test from `_check_goal` is sufficient.

RAM_MACHINEDRAMON_DEFEATED_BYTE: Final = 0x001BDFD3
RAM_MACHINEDRAMON_DEFEATED_MASK: Final = 0x04

# Story-event trigger bits (single bits inside the unified trigger
# bit-array; see :data:`AP_TRIGGER_ARRAY_BASE`). Format: ``(byte_addr, bit)``.
#
# Tropical Jungle bridge: starts broken; once Coelamon's cutscene + the
# Tropical-Jungle-side scene fire, this bit flips and the bridge becomes
# permanently usable in both directions. Discovered 2026-04-30 via a
# 5-snapshot RAM diff and user-confirmed by RAM-watch poke (forcing the
# bit to 1 from a save before the cutscene immediately enables the bridge).
# Trigger ID 185 under the array's standard formula.
RAM_TROPICAL_JUNGLE_BRIDGE_FIXED: Final = (0x001BDFE4, 1)

# Great Canyon bridge: closed until the player has 6 prosperity AND walks
# onto the unlock spot, which fires a cutscene that flips this bit. Once
# set the bridge stays usable. Discovered 2026-05-01 via a 4-snapshot RAM
# diff (before / after-cutscene / after-leave / after-return). Trigger ID
# 103. Same byte holds at least one other story-event flag (bit 0 fires
# on first entry to Tropical Jungle), so writes must be bit-OR not byte.
RAM_GREAT_CANYON_BRIDGE_UNLOCKED: Final = (0x001BDFD9, 7)

# ----- Key-item flags (trigger-array bits, NOT inventory) -------------------
#
# Some "key items" in DW1 are stored as bits in the trigger array, not as
# entries in the on-hand inventory or the bank. Verified via setTrigger
# bytecode + live snapshot diff 2026-05-01 (see memory note
# `dw1_old_fishrod_flag.md`). The CE-table claim that these live as bytes
# at 0x001BDF20.. is **wrong** for the rod and likely for the other key
# items too — verify each individually before adding to this table.
#
# Bit layout follows the standard trigger formula
# (`mem[0x001BDFCD + N/8] |= 1 << (N % 8)`; see memory note
# `dw1_settrigger_formula.md`). Each entry is `(byte_addr, bit_index)`.
#
# **OLD_FISHROD_FLAG** — trigger 320, set by the rod-give cutscene's
# `setTrigger 320` at script offset 006820 in the Trash Mountain section
# (Section_51 of the Gear Savanna script per
# `references/digimon_world_randomizer/script/DW1Script.txt:23931`). This
# is the script's "rod-given" memory bit (gates whether the cutscene
# replays); it is **not** what the fishing minigame reads. Kept as
# documentation; AP delivery does NOT target this bit.
# **OLD_FISHROD_GATE** — trigger 45, the cutscene's section gate, flipped
# in the same instruction window as 320. **This is what the fishing
# minigame actually checks** to enable the Old Rod
# (`isTriggerSet(45)` in `references/DW1-SydPatches/src/Fishing.cpp:21`).
# AP delivery of the "Old Fishrod" item writes here. **No longer used**
# as the location-check signal: the rod cutscene is patched (see
# :data:`ROM_OLD_FISHROD_REMAP_OFFSETS`) so that completion sets
# trigger 902 (:data:`OLD_FISHROD_LOCATION_BIT`) instead, decoupling
# vanilla cutscene completion from vanilla fishing-enable.
# **AMAZING_ROD_GATE** — trigger 46, the Amazing Rod ownership flag read
# by `getBestFishingRod()` in `Fishing.cpp:20`
# (`isTriggerSet(46) -> GOOD_ROD`). AP delivery of the "Amazing rod"
# item writes here. Trigger 46 lives at byte `0x001BDFCD + 46/8 =
# 0x001BDFD2`, bit `46 % 8 = 6` — same byte as `OLD_FISHROD_GATE`,
# different bit. No vanilla location is wired to this bit yet (no
# "Amazing Rod Pickup" location); future RE work may add one.
OLD_FISHROD_FLAG: Final[tuple[int, int]] = (0x001BDFF5, 0)
OLD_FISHROD_GATE: Final[tuple[int, int]] = (0x001BDFD2, 5)
AMAZING_ROD_GATE: Final[tuple[int, int]] = (0x001BDFD2, 6)

# **OLD_FISHROD_LOCATION_BIT** — trigger 902, allocated bit for the AP
# "Old Fishrod Pickup" location-check signal. The rod cutscene
# (Script 159 Section_51) is patched to set trigger 902 in place of
# trigger 45, AND the section's replay gate is patched to read trigger
# 902. After the patch:
#
# * Cutscene plays -> trigger 902 set (location signal) + trigger 320
#   set (rod-sprite-hidden flag, read by Section_254). Cutscene's gate
#   now reads 902 -> won't replay.
# * Trigger 45 is no longer set by the cutscene -> vanilla
#   fishing-enable path is neutered. AP delivery of the "Old Fishrod"
#   item is the only path to trigger 45 (and thus to fishing).
#
# Trigger 902 lives at byte ``0x001BDFCD + 902/8 = 0x001BE03D``,
# bit ``902 % 8 = 6``. Same byte as the highest vending bits but the
# next free bit (vending uses 890..901 = bits 2..7 of 0x001BE03C plus
# bits 0..5 of 0x001BE03D).
OLD_FISHROD_LOCATION_BIT: Final[tuple[int, int]] = (0x001BE03D, 6)
OLD_FISHROD_LOCATION_TRIGGER_ID: Final = 902

# **MANSION_KEY_LOCATION_BIT** — trigger 110, the section gate set by
# the Mansion Key pickup cutscene at Script 54 Section_81 (cutscene
# end at script offset 442; see DW1Script.txt:11602). Used directly as
# the AP location-check signal — trigger 110 has only three
# references in the entire DW1 script, all in Script 54 (set once at
# cutscene end; read at Section_81 line 140 to gate replay; read at
# Section_254 line 32 to gate sprite-state housekeeping for the
# visible key object). Nothing else reads it, so reusing it as the
# AP signal is safe.
#
# Trigger 110 lives at byte ``0x001BDFCD + 110/8 = 0x001BDFDA``,
# bit ``110 % 8 = 6`` (gap A, the story-event bit range).
MANSION_KEY_LOCATION_BIT: Final[tuple[int, int]] = (0x001BDFDA, 6)
MANSION_KEY_LOCATION_TRIGGER_ID: Final = 110

# **FRIG_KEY_LOCATION_BIT** — trigger 104, set inside the Myotismon
# Frig-Key cutscene (Script 63 Section_5, script offset 238 — see
# DW1Script.txt:12179). Trigger 104 has only three references in the
# entire DW1 script, all in Script 63: set once mid-cutscene; read at
# Section_254 line 12156 (post-event entry boilerplate); read at
# Section_5 line 12175 to gate the first-time-meeting branch.
# Nothing else reads it, so reusing it as the AP signal is safe.
#
# Trigger 104 lives at byte ``0x001BDFCD + 104/8 = 0x001BDFDA``,
# bit ``104 % 8 = 0`` — same byte as Mansion Key but a different bit
# (110 -> bit 6, 104 -> bit 0).
FRIG_KEY_LOCATION_BIT: Final[tuple[int, int]] = (0x001BDFDA, 0)
FRIG_KEY_LOCATION_TRIGGER_ID: Final = 104

# **GEAR_LOCATION_BIT** — trigger 270, set at the end of the Gear
# acquisition cutscene in Toy Town (Script 144 Section_83 at script
# offset 4518 — see DW1Script.txt:22436). The cutscene plays after
# the player defeats WaruMonzaemon. **Unlike Mansion/Frig Key's
# section gates, trigger 270 is NOT isolated** — it has 11
# references across Toy Town scripts (Scripts 139, 140, 142, 143,
# 144, 145) that read it to suppress duplicate WaruMonzaemon
# encounter dialog and gate the Section_254 boilerplate's replay
# checks. Setting trigger 270 IS the correct "Gear obtained" signal,
# so the existing reads continue to work as intended after our
# patch — but be aware that NPC dialog elsewhere in Toy Town can
# also branch on trigger 270 + ``item(120)`` checks. Cosmetic: the
# player will have trigger 270 set but no Gear in inventory until
# AP delivers, so some NPC dialogs may behave as if the Gear is
# "missing despite being obtained" until AP delivery + bank retrieval.
#
# Trigger 270 lives at byte ``0x001BDFCD + 270/8 = 0x001BDFEE``,
# bit ``270 % 8 = 6`` (gap B).
GEAR_LOCATION_BIT: Final[tuple[int, int]] = (0x001BDFEE, 6)
GEAR_LOCATION_TRIGGER_ID: Final = 270

# **RAIN_PLANT_LOCATION_BIT** — trigger 76, set at the end of the Rain
# Plant pickup cutscene at Tanemon's planters in Native Forest
# (Script 162 Section_83 at script offset 6238 — see
# DW1Script.txt:24519). The cutscene fires only when the player
# enters the planter area on the 15th of any month
# (``pstat(106) == 14``) AND has already recruited Palmon
# (``trigger(246) == true``). Trigger 76 has 4 references in the
# entire DW1 script, all in Script 162 — set + read inside the
# Rain Plant section, plus an ``unsetTrigger 76`` on day transitions
# that makes the Rain Plant **renewable** (vanilla DW1 lets the
# player pick up a fresh Rain Plant each month). Renewability is
# fine for AP — the location fires the first time trigger 76 sets
# and AP server-side dedup ignores subsequent re-flips.
#
# Trigger 76 lives at byte ``0x001BDFCD + 76/8 = 0x001BDFD6``,
# bit ``76 % 8 = 4`` (gap A).
RAIN_PLANT_LOCATION_BIT: Final[tuple[int, int]] = (0x001BDFD6, 4)
RAIN_PLANT_LOCATION_TRIGGER_ID: Final = 76

# **BLUE_FLUTE_LOCATION_BIT** — trigger 210, set by the Seadramon
# friendship cutscene (Script 7 Section_82 at script offset 1998 —
# see DW1Script.txt:4734). The cutscene plays when the player hooks
# Seadramon while fishing in Dragon Eye Lake (Greatlake region) and
# selects the "Let's be friends" dialog option. Trigger 210 lives in
# the recruit-bit block (``RECRUIT_RAM_BITS["Seadramon"]``); in
# vanilla DW1 it doubles as Seadramon's "joined city" flag.
#
# **Important context:** Seadramon was an AP recruit until 2026-05-09;
# he's now in :data:`_AP_RECRUIT_EXCLUDED` because he doesn't really
# do anything in town and his recruit cutscene IS the Blue Flute
# pickup event. The single in-game event now fires only the
# ``Blue Flute Pickup`` AP location (no Seadramon recruit location
# anymore). The recruit-bit poll for Seadramon is removed via
# ``client._DROPPED_RECRUITS_BLACKLIST`` so the bit poll happens
# exclusively under this keyitem name.
#
# Trigger 210 lives at byte ``0x001BDFCD + 210/8 = 0x001BDFE7``,
# bit ``210 % 8 = 2`` — same as ``RECRUIT_RAM_BITS["Seadramon"]``.
BLUE_FLUTE_LOCATION_BIT: Final[tuple[int, int]] = (0x001BDFE7, 2)
BLUE_FLUTE_LOCATION_TRIGGER_ID: Final = 210
# Sanity check that BLUE_FLUTE_LOCATION_BIT == RECRUIT_RAM_BITS["Seadramon"]
# is asserted at module-load time below, after RECRUIT_RAM_BITS is defined.

# **LEOMONSTONE_LOCATION_BIT** — trigger 135, set by the Leomonstone
# pickup cutscene at Leomon's Ancestral Cave (deepest chamber of
# Drill Tunnel B3F; Script 109 Section_52 at script offset 676 — see
# DW1Script.txt:17867). The cutscene plays automatically when the
# player enters the cave and approaches the visible stone tablet.
# In vanilla DW1, reaching this cave requires Drimogemon to dig
# through a wall on Drill Tunnel B3F, which only happens after the
# city's Prosperity reaches 45.
#
# Trigger 135 has 4 references — 3 in Script 109 (the cutscene's own
# section gate, the post-pickup obj-visibility gate, and the
# setTrigger), plus 1 in Script 211 (Leomon's NPC dialogue checks if
# the tablet has been found to provide post-pickup context). All
# reads continue to work correctly after our patch since the
# cutscene still sets trigger 135.
#
# Trigger 135 lives at byte ``0x001BDFCD + 135/8 = 0x001BDFDD``,
# bit ``135 % 8 = 7`` (gap A).
LEOMONSTONE_LOCATION_BIT: Final[tuple[int, int]] = (0x001BDFDD, 7)
LEOMONSTONE_LOCATION_TRIGGER_ID: Final = 135

# **AMAZING_ROD_LOCATION_BIT** — trigger 903, set by an injected MIPS
# wrapper that intercepts the Merit Shop's give-item callsite (see
# :data:`ROM_MERIT_SHOP_WRAPPER_*`). Unlike every other key item,
# Amazing Rod has no script-bytecode site we could surgically patch
# — the merit shop's purchase logic lives in the PSX engine code,
# not the script bytecode. The wrapper compares the give-item $a0
# argument against item 117 (Amazing Rod) and, on match, calls
# ``setTrigger(903)`` before tail-calling the vanilla give-item
# function. Trigger 903 is in gap C, byte 0x001BE03D bit 7 — the
# only free bit in that byte (bits 2..5 used by vending 898..901,
# bit 6 by Old Fishrod 902; bits 0..1 are unused — trigger IDs 896
# and 897 reserved historically for the Gear Savanna MP Stand
# sub-vendor slots, which never became AP locations).
AMAZING_ROD_LOCATION_BIT: Final[tuple[int, int]] = (0x001BE03D, 7)
AMAZING_ROD_LOCATION_TRIGGER_ID: Final = 903

# =============================================================================
# Nanimon Quest (keychain) per-site location bits
# =============================================================================
#
# Vanilla DW1's "Nanimon questline" places Nanimon at 5 fixed sites
# across the world. Visiting each one runs a short cutscene that
# advances `pstat(21)` and sets a per-site trigger bit; on the 1st
# visit the cutscene additionally sets trigger 47 (umbrella "got first
# keychain") and writes `setInventorySize 20`, and on the 4th visit
# it sets trigger 48 and writes `setInventorySize 30`. We poll the
# **per-site** bits as AP location signals — one location per Nanimon
# visit. The keychain inventory growth itself is owned by the AP
# client (each Progressive Keychain delivered bumps INVENTORY_SIZE by
# 10), so vanilla's setInventorySize writes get overwritten on the
# next watcher tick.
#
# Sites and triggers, mapped from Scripts 48 / 82 / 109 / 145 / 180 in
# `references/digimon_world_randomizer/script/DW1Script.txt`:
#
#   Script 48  — Ogre Fortress (elevator to Great Canyon)   → trig 334
#   Script 82  — Ancient Dino Region (Meteormon site)       → trig 335
#   Script 109 — Drill Tunnel (Leomon's Stone Tablet, 45PP) → trig 333
#   Script 145 — Toy Town (WaruMonzaemon big/small box)     → trig 337
#   Script 180 — Factorial Town (sick Digimon / sewer)      → trig 336
#
# All 5 bits land in just two bytes — 0x001BDFF6 and 0x001BDFF7 —
# (formula `0x001BDFCD + N/8, bit N%8`). Verified empirically
# 2026-05-13 against a live BizHawk session: visiting the Ancient
# Dino Region Nanimon set 0x001BDFF6 bit 7 (mask 0x80 = trigger 335).
NANIMON_QUEST_OGRE_FORTRESS_BIT: Final[tuple[int, int]] = (0x001BDFF6, 6)
NANIMON_QUEST_OGRE_FORTRESS_TRIGGER_ID: Final = 334

NANIMON_QUEST_ANCIENT_DINO_BIT: Final[tuple[int, int]] = (0x001BDFF6, 7)
NANIMON_QUEST_ANCIENT_DINO_TRIGGER_ID: Final = 335

NANIMON_QUEST_DRILL_TUNNEL_BIT: Final[tuple[int, int]] = (0x001BDFF6, 5)
NANIMON_QUEST_DRILL_TUNNEL_TRIGGER_ID: Final = 333

NANIMON_QUEST_TOY_TOWN_BIT: Final[tuple[int, int]] = (0x001BDFF7, 1)
NANIMON_QUEST_TOY_TOWN_TRIGGER_ID: Final = 337

NANIMON_QUEST_FACTORIAL_TOWN_BIT: Final[tuple[int, int]] = (0x001BDFF7, 0)
NANIMON_QUEST_FACTORIAL_TOWN_TRIGGER_ID: Final = 336

NANIMON_QUEST_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    "Nanimon Quest: Ogre Fortress":        NANIMON_QUEST_OGRE_FORTRESS_BIT,
    "Nanimon Quest: Ancient Dino Region":  NANIMON_QUEST_ANCIENT_DINO_BIT,
    "Nanimon Quest: Drill Tunnel":         NANIMON_QUEST_DRILL_TUNNEL_BIT,
    "Nanimon Quest: Toy Town":             NANIMON_QUEST_TOY_TOWN_BIT,
    "Nanimon Quest: Factorial Town":       NANIMON_QUEST_FACTORIAL_TOWN_BIT,
}
# Sanity: every per-site trigger must derive to its declared byte/bit
# via the setTrigger formula `(0x001BDFCD + N/8, N%8)`.
for _trigger_id, _expected_bit in (
    (NANIMON_QUEST_OGRE_FORTRESS_TRIGGER_ID,   NANIMON_QUEST_OGRE_FORTRESS_BIT),
    (NANIMON_QUEST_ANCIENT_DINO_TRIGGER_ID,    NANIMON_QUEST_ANCIENT_DINO_BIT),
    (NANIMON_QUEST_DRILL_TUNNEL_TRIGGER_ID,    NANIMON_QUEST_DRILL_TUNNEL_BIT),
    (NANIMON_QUEST_TOY_TOWN_TRIGGER_ID,        NANIMON_QUEST_TOY_TOWN_BIT),
    (NANIMON_QUEST_FACTORIAL_TOWN_TRIGGER_ID,  NANIMON_QUEST_FACTORIAL_TOWN_BIT),
):
    _byte = 0x001BDFCD + _trigger_id // 8
    _bit = _trigger_id % 8
    assert (_byte, _bit) == _expected_bit, (
        f"trigger {_trigger_id} derives to ({_byte:#x}, {_bit}) "
        f"but constant says {_expected_bit}"
    )

# =============================================================================
# Boss-defeat location bits (always on)
# =============================================================================
#
# Story-event "boss defeated" flags set by vanilla cutscene scripts after
# the player wins a mandatory boss encounter. The client polls each bit
# as an AP location signal -- no ROM patch needed (the vanilla script
# already calls ``setTrigger`` on cutscene completion).
#
# Meteormon (Script 82 Section_5, offset 002140): set after the post-
# battle "Meteorite Tribe" cutscene resolves and the Meteormon entity
# walks off-screen. The same trigger is read by Script 0 Section_86
# (the KODA07 wild-spawn dispatcher) to suppress respawn.
METEORMON_DEFEATED_TRIGGER_ID: Final = 313
METEORMON_DEFEATED_BIT: Final[tuple[int, int]] = (0x001BDFF4, 1)

BOSS_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    "Meteormon Defeated": METEORMON_DEFEATED_BIT,
}
# Sanity: every boss-defeat trigger must derive to its declared byte/bit
# via the setTrigger formula `(0x001BDFCD + N/8, N%8)`.
for _trigger_id, _expected_bit in (
    (METEORMON_DEFEATED_TRIGGER_ID, METEORMON_DEFEATED_BIT),
):
    _byte = 0x001BDFCD + _trigger_id // 8
    _bit = _trigger_id % 8
    assert (_byte, _bit) == _expected_bit, (
        f"trigger {_trigger_id} derives to ({_byte:#x}, {_bit}) "
        f"but constant says {_expected_bit}"
    )

# ----- Arena cup-win location triggers (always on) --------------------------
#
# Script 214 Section_51 is the post-arena-match handler. On a cup win
# (entry condition ``pstat(255) == 3``) it dispatches on ``pstat(3)`` to
# one of N cup branches and hands out the vanilla prize via ``giveItem``.
# The 5 grade-tier cups occupy ``pstat(3) ∈ {0, 1, 2, 3, 4}`` (Grade D
# Rookie / Grade C Champion / Grade B Champion+ / Grade A Ultimate /
# Grade S Strongest). The patcher swaps each cup's ``giveItem`` opcode
# (primary + inventory-overflow bank-fallback copy) with ``setTrigger N``
# at the AP-allocated trigger below; the client polls the bit and fires
# the cup's 4 AP locations.
#
# Free-bit derivation: gap between Birdramon flight (880-884, bits 0-4
# of 0x001BE03B) and Vending (890-901, starting at bit 2 of 0x001BE03C).
# Triggers 885-889 occupy the 5-bit gap.
#
#   885 -> Grade D (Rookie)
#   886 -> Grade C (Champion)
#   887 -> Grade B (Champion+)
#   888 -> Grade A (Ultimate)
#   889 -> Grade S (Strongest)
#
# Each cup-win bit gates 4 AP locations (per-cup payout = 4 items). All
# 4 share the same trigger and fire on the same RAM transition; AP
# server-side dedup ignores duplicates.
ARENA_CUP_GRADE_D_BIT: Final[tuple[int, int]] = (0x001BE03B, 5)
ARENA_CUP_GRADE_D_TRIGGER_ID: Final = 885

ARENA_CUP_GRADE_C_BIT: Final[tuple[int, int]] = (0x001BE03B, 6)
ARENA_CUP_GRADE_C_TRIGGER_ID: Final = 886

ARENA_CUP_GRADE_B_BIT: Final[tuple[int, int]] = (0x001BE03B, 7)
ARENA_CUP_GRADE_B_TRIGGER_ID: Final = 887

ARENA_CUP_GRADE_A_BIT: Final[tuple[int, int]] = (0x001BE03C, 0)
ARENA_CUP_GRADE_A_TRIGGER_ID: Final = 888

ARENA_CUP_GRADE_S_BIT: Final[tuple[int, int]] = (0x001BE03C, 1)
ARENA_CUP_GRADE_S_TRIGGER_ID: Final = 889

# Per-cup tier + RAM bit + trigger + a PP-progress proxy used by rules.py
# to gate higher-tier cups behind progression milestones. The proxy is
# purely an AP-logic heuristic (the in-game cups are stat- and stage-
# gated, which AP cannot directly model) -- it correlates with how far
# the player typically is when each tier becomes winnable.
ARENA_CUP_TIERS: Final[tuple[tuple[str, tuple[int, int], int, int], ...]] = (
    ("Grade D", ARENA_CUP_GRADE_D_BIT, ARENA_CUP_GRADE_D_TRIGGER_ID,  0),
    ("Grade C", ARENA_CUP_GRADE_C_BIT, ARENA_CUP_GRADE_C_TRIGGER_ID,  0),
    ("Grade B", ARENA_CUP_GRADE_B_BIT, ARENA_CUP_GRADE_B_TRIGGER_ID, 15),
    ("Grade A", ARENA_CUP_GRADE_A_BIT, ARENA_CUP_GRADE_A_TRIGGER_ID, 30),
    ("Grade S", ARENA_CUP_GRADE_S_BIT, ARENA_CUP_GRADE_S_TRIGGER_ID, 45),
)

# 4 AP locations per cup -- the user-specified per-cup payout. All 4
# share the cup's trigger bit; the player gets 4 items on each cup win.
ARENA_CUP_LOCATIONS_PER_TIER: Final = 4

ARENA_CUP_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    f"Arena Cup: {tier} {i}": bit
    for tier, bit, _trig, _pp in ARENA_CUP_TIERS
    for i in range(1, ARENA_CUP_LOCATIONS_PER_TIER + 1)
}
assert len(ARENA_CUP_LOCATION_RAM_BITS) == (
    len(ARENA_CUP_TIERS) * ARENA_CUP_LOCATIONS_PER_TIER
), "arena cup location/RAM bit count mismatch"
# Sanity: every cup trigger must derive to its declared byte/bit via
# `(0x001BDFCD + N/8, N%8)`.
for _trigger_id, _expected_bit in (
    (ARENA_CUP_GRADE_D_TRIGGER_ID, ARENA_CUP_GRADE_D_BIT),
    (ARENA_CUP_GRADE_C_TRIGGER_ID, ARENA_CUP_GRADE_C_BIT),
    (ARENA_CUP_GRADE_B_TRIGGER_ID, ARENA_CUP_GRADE_B_BIT),
    (ARENA_CUP_GRADE_A_TRIGGER_ID, ARENA_CUP_GRADE_A_BIT),
    (ARENA_CUP_GRADE_S_TRIGGER_ID, ARENA_CUP_GRADE_S_BIT),
):
    _byte = 0x001BDFCD + _trigger_id // 8
    _bit = _trigger_id % 8
    assert (_byte, _bit) == _expected_bit, (
        f"arena trigger {_trigger_id} derives to ({_byte:#x}, {_bit}) "
        f"but constant says {_expected_bit}"
    )

# ----- Arena enforcer (client-side, applied on arena lobby screens) --------
#
# DW1 gates higher-tier arena cups on which Digimon are in the city's
# recruit-block (200+X range, byte 0x001BDFE6..0x001BDFED). The
# recruit-bit redirect strategy works for City visibility but the
# arena's cup-tier population logic reads the 200+X bytes directly
# (likely in compiled SLUS code that no easy bytecode patch touches).
#
# Workaround: on arena screens (ROOM13=208, ROOM19=223), the AP client
# enforces the 200+X bits based on how many ``Progressive Arena`` items
# the player has received. On leaving those screens it restores the
# bits to their pre-enforcer values. AP recruit-bit polling is skipped
# while on arena screens (vanilla DW1 never recruits a Digimon on
# screens 208/223, so no real recruit events can be missed).
#
# Tier mapping (cumulative — tier 2 also has tier 1's bits, etc.):
#   T1: nothing extra (Grade D is always available)
#   T2: bytes 1 and 6 of the recruit block (triggers 208..215 + 248..255)
#   T3: every byte 0..7 (full 200..263 range)
#
# Per the user's live testing 2026-05-28: T2 unlocks Grade C, T3 unlocks
# Grade B / A / S.
ARENA_ENFORCER_SCREENS: Final[frozenset[int]] = frozenset({
    208,  # ROOM13 — arena interior
    223,  # ROOM19 — arena lobby (with the static Greymon / Penguinmon NPCs)
})
ARENA_ENFORCER_RECRUIT_BLOCK_BASE: Final = 0x001BDFE6
ARENA_ENFORCER_RECRUIT_BLOCK_SIZE: Final = 8
# Per-tier byte offsets (within the recruit-block) the enforcer sets to
# 0xFF. The enforcer ORs in these bytes; it does NOT clear bits outside
# them (the snapshot/restore on screen exit handles cleanup).
ARENA_ENFORCER_TIER_2_BYTE_OFFSETS: Final[tuple[int, ...]] = (1, 6)
ARENA_ENFORCER_TIER_3_BYTE_OFFSETS: Final[tuple[int, ...]] = (0, 1, 2, 3, 4, 5, 6, 7)

# Persistent snapshot slot. The enforcer mutates the recruit-block while
# the player is on an arena screen; on exit it restores the pre-mutation
# values. If we stored the snapshot only in the Python client, two edge
# cases would corrupt the recruit-block:
#
#  * Save game inside arena -> close game -> reopen -> leave arena.
#    The save file persists the mutated recruit-block bytes; the Python
#    snapshot is gone; restore-on-exit would re-write the *mutated*
#    bytes back, permanently locking the bits set.
#  * Client disconnects mid-arena, player walks out while offline,
#    client reconnects outside the arena. Without persistence, the
#    enforcer can't tell "we mutated bytes and the player left during
#    disconnect" from "normal state, no mutation happened" -- the
#    polluted bytes stay set and `_check_locations` then fires false
#    recruit AP location checks.
#
# Persisting the snapshot in PSX RAM survives both:
#  * Save files include this RAM region, so reload restores the
#    snapshot bytes plus the magic flag.
#  * Disconnect leaves PSX RAM untouched; reconnect sees the magic
#    and handles the restore on the next tick.
#
# Located in the formerly-AP_BITS_MIRROR (deprecated, see user direction
# 2026-05-28) region, which the active client never writes to. Magic
# byte is the next byte (formerly RAM_PERMANENT_BEATEN_SCRATCH_BASE,
# also declared but unused in the active client). Vanilla DW1 leaves
# both regions untouched.
ARENA_ENFORCER_SNAPSHOT_BASE: Final = 0x001BDFF0
ARENA_ENFORCER_SNAPSHOT_SIZE: Final = 8     # same width as recruit-block
ARENA_ENFORCER_MAGIC_ADDR: Final = 0x001BDFF8
ARENA_ENFORCER_MAGIC_VALUE: Final = 0xA5    # snapshot held; clear = no snapshot

# **LAVA_CAVE_ACCESS_FLAG** — trigger 145, AP-controlled. Set when the AP
# delivers the ``Lava Cave Access`` item; read by the patched boulder
# script (Script ID 30, Section_5, script offset 484) to decide whether
# the player can move the rock that gates Drill Tunnel -> Lava Cave (and
# transitively Meramon and Mt. Panorama). Trigger 145 was selected after
# scanning the entire script disassembly for unused trigger IDs — gap-A
# slot, not touched by any vanilla setTrigger / trigger / unsetTrigger
# read, not allocated by any AP table.
# **LAVA_CAVE_ACCESS_GATE** — trigger 120, vanilla "boulder moved" flag,
# set by ``setTrigger 120`` at script offset 001290 in Script ID 30
# Section_5. AP polls this as the location-check signal for the
# ``Drill Tunnel Boulder`` location.
LAVA_CAVE_ACCESS_FLAG: Final[tuple[int, int]] = (0x001BDFDF, 1)
LAVA_CAVE_ACCESS_GATE: Final[tuple[int, int]] = (0x001BDFDC, 0)

# Per-AP-location bits for the key-item AP locations. Mirrors the shape
# of `RECRUIT_RAM_BITS` / `DWAP_CHEST_RAM_BITS`; consumed by the client
# via `LOCATION_RAM_BITS`.
#
# Note: Lava Cave Access / Tropical Jungle Bridge / Great Canyon
# Bridge are AP **items only**, not AP locations (per user direction
# 2026-05-08). They are virtual access items delivered via trigger-
# bit writes — there's no in-world pickup site for them. The
# previous ``Drill Tunnel Boulder`` / ``Tropical Jungle Bridge Fixed``
# / ``Great Canyon Bridge Fixed`` location entries were removed at
# the same time.
KEYITEM_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    # "Old Fishrod Pickup" used to poll OLD_FISHROD_GATE (trigger 45),
    # but trigger 45 is now also the AP delivery target for the rod
    # item — sharing the bit would make AP delivery self-trigger the
    # location. The cutscene is patched to set trigger 902 instead
    # (see ROM_OLD_FISHROD_REMAP_*); we poll that bit.
    "Old Fishrod Pickup":          OLD_FISHROD_LOCATION_BIT,
    # "Mansion Key Pickup" polls trigger 110 (the cutscene's section
    # gate). The two giveItem 119 instructions are neutered (see
    # ROM_MANSION_KEY_GIVEITEM_*); the cutscene's existing setTrigger
    # 110 still fires on completion, but no key enters the player's
    # inventory — only AP delivery puts Mansion Key in the bank.
    "Mansion Key Pickup":          MANSION_KEY_LOCATION_BIT,
    # "Frig Key Pickup" polls trigger 104 (Myotismon Frig-Key
    # cutscene's "first meeting" flag). Trigger 104 is set at script
    # offset 238 (during the cutscene's intro); the two giveItem 123
    # instructions at offsets 670 and 780 are neutered (see
    # ROM_FRIG_KEY_GIVEITEM_*) and rewritten as setTrigger 104
    # (idempotent; the bit was already flipped at offset 238). No key
    # enters the player's inventory — only AP delivery does.
    "Frig Key Pickup":             FRIG_KEY_LOCATION_BIT,
    # "Gear Pickup" polls trigger 270 (Toy Town WaruMonzaemon defeat
    # cutscene's section gate, set at script offset 4518 in Script
    # 144 Section_83). The two giveItem 120 instructions at offsets
    # 4334 and 4476 are neutered (see ROM_GEAR_GIVEITEM_*) and
    # rewritten as setTrigger 270 (idempotent — bit was set at offset
    # 4518 in vanilla anyway). No Gear enters the player's inventory
    # — only AP delivery via bank slot 120 does.
    "Gear Pickup":                 GEAR_LOCATION_BIT,
    # "Rain Plant Pickup" polls trigger 76 (Tanemon planter cutscene
    # in Native Forest, set at script offset 6238 in Script 162
    # Section_83). The single giveItem 121 at offset 6116 is neutered
    # (see ROM_RAIN_PLANT_GIVEITEM_*) and rewritten as setTrigger 76
    # (idempotent — bit was set at offset 6238 in vanilla anyway).
    # No Rain Plant enters the player's inventory — only AP delivery
    # via bank slot 121 does. The cutscene only fires on day 15 of
    # any month and only after Palmon is recruited (trigger 246).
    "Rain Plant Pickup":           RAIN_PLANT_LOCATION_BIT,
    # "Blue Flute Pickup" polls trigger 210 (Seadramon friendship
    # cutscene in Greatlake, set at script offset 1998 in Script 7
    # Section_82). The two giveItem 115 instances are neutered (see
    # ROM_BLUE_FLUTE_GIVEITEM_*) and rewritten as setTrigger 210
    # (idempotent). Trigger 210 is the same bit as Seadramon's recruit
    # flag in vanilla — Seadramon was dropped from AP recruit coverage
    # 2026-05-09 because the cutscene IS the Blue Flute pickup; the
    # bit poll has been moved here.
    "Blue Flute Pickup":           BLUE_FLUTE_LOCATION_BIT,
    # "Leomonstone Pickup" polls trigger 135 (Leomon's Ancestral Cave
    # cutscene in Drill Tunnel B3F, set at script offset 676 in Script
    # 109 Section_52). The seven giveItem 118 1 instances across 3
    # ROM copies + 1 orphan are neutered (see ROM_LEOMONSTONE_GIVEITEM_*)
    # and rewritten as setTrigger 135 (idempotent — bit was set by the
    # cutscene's own setTrigger anyway). No Leomonstone enters the
    # player's inventory — only AP delivery via bank slot 118 does.
    "Leomonstone Pickup":          LEOMONSTONE_LOCATION_BIT,
    # "Amazing Rod Pickup" polls trigger 903 — set by an injected
    # MIPS wrapper that intercepts the Merit Shop's give-item callsite
    # (see ROM_MERIT_SHOP_WRAPPER_*). The wrapper checks the item ID
    # being purchased and, on match for item 117, calls setTrigger(903)
    # before tail-calling vanilla give-item. The wrapper itself is
    # extensible: more (item_id, trigger_id) pairs in
    # MERIT_SHOP_DISPATCH would let other shop items become AP
    # locations too.
    "Amazing Rod Pickup":          AMAZING_ROD_LOCATION_BIT,
}

# Per-AP-item delivery flags for AP-side delivery of key items. Mirrors
# the recruit deliverer pattern: when AP delivers the matching item, set
# this bit in RAM.
KEYITEM_DELIVERY_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    # Rod items target the trigger bits the fishing minigame actually
    # reads (`getBestFishingRod()` in DW1-SydPatches' `Fishing.cpp` checks
    # triggers 45 and 46). Setting trigger 320 — the script's rod-given
    # memory bit — does not enable fishing.
    "Old Fishrod":            OLD_FISHROD_GATE,
    "Amazing rod":            AMAZING_ROD_GATE,
    "Lava Cave Access":       LAVA_CAVE_ACCESS_FLAG,
    "Tropical Jungle Bridge": RAM_TROPICAL_JUNGLE_BRIDGE_FIXED,
    "Great Canyon Bridge":    RAM_GREAT_CANYON_BRIDGE_UNLOCKED,
}

# ----- Birdramon flight destination gates -----------------------------------
#
# Birdramon-Messenger reads a 6-entry destination table embedded in the
# binary. Each destination only appears in his menu when its trigger bit
# is set in the trigger array. Vanilla mapping: G Canyon Top=trig 221
# (Birdramon recruit), Gear Savanna=190, Ancient Dino=188, Freezeland=351,
# Misty Trees=147, Beetle Land=210.
#
# LAYOUT CORRECTED 2026-08-28 (dw_decomp audit). The entry is
# ``{u8 mapId, u8 exitIdx, u16 trigger, u32 cost}`` x 6, at RAM 0x8013024C
# (= .bin 0x14D725C4). The bases recorded below (0x14D725C6 / 0x14B8B698)
# are the TRUE BASE + 2, so ``base + 8*n`` lands on entry n's trigger and
# ``base + 8*n + 2`` on its cost -- which is why every shipped write was
# right while the documented ``<u16 trigger, u32 price, u16 label>`` layout
# was not: the "label" was the NEXT entry's mapId/exitIdx. Vanilla costs
# 1000/1000/1500/2000/2500/2500; destinations GCAN03/GIAS01/KODA00/FRZL06/
# MIST05/BETL01 (exit 9 except BETL01 = 0); a selection writes pstat 247/248.
# Copy 1 (0x14B8B698) is DOOA_REL.BIN's private copy (LBA 147800), not a
# second SLUS copy -- patch both regardless.
#
# We redirect the 5 non-recruit entries' trigger IDs in the table to
# fresh AP-controlled trigger IDs (880-884) at byte 0x001BE03B bits 0-4.
# That byte is in a clearly unused gap region of the trigger array (no
# script references, no other game systems), so the bits live in
# isolation -- AP delivery sets them, callRoutine 10 reads them via the
# patched table, no game-state side effects.
#
# G Canyon Top (vanilla trig 221 = Birdramon recruit) is left
# unpatched: it correctly auto-unlocks when the Birdramon Recruit AP
# item is delivered. So 5 AP items, not 6.
#
# See memory note `dw1_birdramon_flight_gates.md` for the full RE story.

BIRDRAMON_FLIGHT_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    "Birdramon Flight: Gear Savanna":        (0x001BE03B, 0),  # trigger 880
    "Birdramon Flight: Ancient Dino Region": (0x001BE03B, 1),  # trigger 881
    "Birdramon Flight: Freezeland":          (0x001BE03B, 2),  # trigger 882
    "Birdramon Flight: Misty Trees":         (0x001BE03B, 3),  # trigger 883
    "Birdramon Flight: Beetle Land":         (0x001BE03B, 4),  # trigger 884
}

# (offset, new_trigger_id) pairs for the destination-table trigger-id
# rewrites. 5 entries x 2 table copies = 10 patch sites. Format is u16 LE.
ROM_BIRDRA_FLIGHT_TABLE_FORMAT: Final = "<H"
ROM_BIRDRA_FLIGHT_TABLE_PATCHES: Final = (
    # Copy 1 (.bin base 0x14B8B698) -- entry trigger u16 at +1*8, +2*8, ...
    (0x14B8B6A0, 880),  # Gear Savanna       (was trig 190)
    (0x14B8B6A8, 881),  # Ancient Dino       (was trig 188)
    (0x14B8B6B0, 882),  # Freezeland         (was trig 351)
    (0x14B8B6B8, 883),  # Misty Trees        (was trig 147)
    (0x14B8B6C0, 884),  # Beetle Land        (was trig 210)
    # Copy 2 (.bin base 0x14D725C6) -- same offsets relative to the base
    (0x14D725CE, 880),
    (0x14D725D6, 881),
    (0x14D725DE, 882),
    (0x14D725E6, 883),
    (0x14D725EE, 884),
)

# ----- Card-vending location nibbles ----------------------------------------
#
# DW1 stores collectible business-card ownership as a packed nibble counter
# array starting at :data:`RAM_CARD_LIST_BASE` (= ``0x001BDFAC``). Each
# card uses one 4-bit nibble; two cards per byte. ``nibble > 0`` means the
# player has bought the card at least once (the count saturates a bit
# lower in practice but >0 is the canonical "owned" check).
#
# 66 cards span 33 bytes (0x001BDFAC..0x001BDFCC inclusive). The byte
# immediately after, ``0x001BDFCD``, is :data:`AP_TRIGGER_ARRAY_BASE` — no
# overlap with the trigger array.
#
# Struct view (dw_decomp ``ScriptState``, 2026-08-28): this is
# ``cards[33]`` at save + 0xD4. Two neighbours worth knowing: save + 0x00..
# + 0x05 are the card shop's six daily offers (0xFF = empty), and save
# + 0x06..+ 0x53 (0x001BDEDE..0x001BDF2B) are the **recycle-shop stock
# counts**, capped at 99 — the bytes the old Cheat-Engine table mislabelled
# as key-item flags.
#
# Layout cross-referenced with DWAP's
# ``references/DWAP/source/DWAP/Resources/DigimonCards.json``. AP IDs
# ``69_002_000``..``69_002_065`` follow DWAP's wire format so cross-walk
# stays clean for future tooling.
#
# Used by the BizHawk client when the
# :class:`worlds.digimon_world.options.CardLocations` option is on. The
# whole 33-byte block is read once per watcher tick as a single batched
# read.

class _CardNibble(NamedTuple):
    byte_addr: int
    is_upper: bool  # True = high nibble (>>4), False = low nibble (& 0x0F)


def _nibble(byte_addr: int, position: str) -> _CardNibble:
    return _CardNibble(byte_addr, position == "upper")


CARD_LOCATION_NIBBLES: Final[dict[str, _CardNibble]] = {
    "Player Card":         _nibble(0x001BDFAC, "lower"),
    "Phoenixmon Card":     _nibble(0x001BDFAC, "upper"),
    "H-Kabuterimon Card":  _nibble(0x001BDFAD, "lower"),
    "MegaSeadramon Card":  _nibble(0x001BDFAD, "upper"),
    "ShogunGekomon Card":  _nibble(0x001BDFAE, "lower"),
    "Myotismon Card":      _nibble(0x001BDFAE, "upper"),
    "MetalGreymon Card":   _nibble(0x001BDFAF, "lower"),
    "Mamemon Card":        _nibble(0x001BDFAF, "upper"),
    "Monzaemon Card":      _nibble(0x001BDFB0, "lower"),
    "SkullGreymon Card":   _nibble(0x001BDFB0, "upper"),
    "MetalMamemon Card":   _nibble(0x001BDFB1, "lower"),
    "Vademon Card":        _nibble(0x001BDFB1, "upper"),
    "Andromon Card":       _nibble(0x001BDFB2, "lower"),
    "Giromon Card":        _nibble(0x001BDFB2, "upper"),
    "Etemon Card":         _nibble(0x001BDFB3, "lower"),
    "Megadramon Card":     _nibble(0x001BDFB3, "upper"),
    "Piximon Card":        _nibble(0x001BDFB4, "lower"),
    "Digitamamon Card":    _nibble(0x001BDFB4, "upper"),
    "Gekomon Card":        _nibble(0x001BDFB5, "lower"),
    "WaruMonzaemon Card":  _nibble(0x001BDFB5, "upper"),
    "Jijimon Card":        _nibble(0x001BDFB6, "lower"),
    "King of Sukamon Card": _nibble(0x001BDFB6, "upper"),
    "Cherrymon Card":      _nibble(0x001BDFB7, "lower"),
    "Guardromon Card":     _nibble(0x001BDFB7, "upper"),
    "Hagurumon Card":      _nibble(0x001BDFB8, "lower"),
    "Brachiomon Card":     _nibble(0x001BDFB8, "upper"),
    "Greymon Card":        _nibble(0x001BDFB9, "lower"),
    "Devimon Card":        _nibble(0x001BDFB9, "upper"),
    "Airdramon Card":      _nibble(0x001BDFBA, "lower"),
    "Tyrannomon Card":     _nibble(0x001BDFBA, "upper"),
    "Meramon Card":        _nibble(0x001BDFBB, "lower"),
    "Seadramon Card":      _nibble(0x001BDFBB, "upper"),
    "Kabuterimon Card":    _nibble(0x001BDFBC, "lower"),
    "Angemon Card":        _nibble(0x001BDFBC, "upper"),
    "Birdramon Card":      _nibble(0x001BDFBD, "lower"),
    "Garurumon Card":      _nibble(0x001BDFBD, "upper"),
    "Frigimon Card":       _nibble(0x001BDFBE, "lower"),
    "Whamon Card":         _nibble(0x001BDFBE, "upper"),
    "Unimon Card":         _nibble(0x001BDFBF, "lower"),
    "Ogremon Card":        _nibble(0x001BDFBF, "upper"),
    "Shellmon Card":       _nibble(0x001BDFC0, "lower"),
    "Centarumon Card":     _nibble(0x001BDFC0, "upper"),
    "Bakemon Card":        _nibble(0x001BDFC1, "lower"),
    "Drimogemon Card":     _nibble(0x001BDFC1, "upper"),
    "Monochromon Card":    _nibble(0x001BDFC2, "lower"),
    "Leomon Card":         _nibble(0x001BDFC2, "upper"),
    "Coelamon Card":       _nibble(0x001BDFC3, "lower"),
    "Kokatorimon Card":    _nibble(0x001BDFC3, "upper"),
    "Kuwagamon Card":      _nibble(0x001BDFC4, "lower"),
    "Mojyamon Card":       _nibble(0x001BDFC4, "upper"),
    "Ninjamon Card":       _nibble(0x001BDFC5, "lower"),
    "Penguinmon Card":     _nibble(0x001BDFC5, "upper"),
    "Otamamon Card":       _nibble(0x001BDFC6, "lower"),
    "Tentomon Card":       _nibble(0x001BDFC6, "upper"),
    "Yanmamon Card":       _nibble(0x001BDFC7, "lower"),
    "Gotsumon Card":       _nibble(0x001BDFC7, "upper"),
    "Darkrizamon Card":    _nibble(0x001BDFC8, "lower"),
    "ToyAgumon Card":      _nibble(0x001BDFC8, "upper"),
    "DemiMeramon Card":    _nibble(0x001BDFC9, "lower"),
    "Tankmon Card":        _nibble(0x001BDFC9, "upper"),
    "Goburimon Card":      _nibble(0x001BDFCA, "lower"),
    "Numemon Card":        _nibble(0x001BDFCA, "upper"),
    "Vegiemon Card":       _nibble(0x001BDFCB, "lower"),
    "Sukamon Card":        _nibble(0x001BDFCB, "upper"),
    "Nanimon Card":        _nibble(0x001BDFCC, "lower"),
    "Machinedramon Card":  _nibble(0x001BDFCC, "upper"),
}
assert len(CARD_LOCATION_NIBBLES) == 66, len(CARD_LOCATION_NIBBLES)

# Contiguous read window covering every card nibble. The client uses this
# to issue one batched RAM read per tick instead of 66 per-card reads.
CARD_BLOCK_BASE: Final = 0x001BDFAC
CARD_BLOCK_SIZE: Final = 33  # 0x001BDFAC..0x001BDFCC inclusive
assert all(
    CARD_BLOCK_BASE <= nb.byte_addr < CARD_BLOCK_BASE + CARD_BLOCK_SIZE
    for nb in CARD_LOCATION_NIBBLES.values()
)


# ----- Per-Digimon technique tables (full-roster learned-tech tables) -------

RAM_TECHNIQUE_TABLE_BASE: Final = 0x0012623C
RAM_LEARNING_CHANCE_TABLE_BASE: Final = 0x00125FA4


# ----- Technique mastery bitmap (partner save block) -----------------------
#
# Per-partner-Digimon "I have mastered tech N" bitmap. One bit per
# technique slot, packed LSB-first: slot N -> byte
# ``RAM_TECH_MASTERY_BASE + N // 8``, bit ``N % 8``.
#
# Player-masterable range is 56 slots: 0..56 inclusive minus slot 48
# ("Dynamite Kick v2"), a duplicate skipped by DW1's own "Master all
# Techniques" debug script and by DWAP's per-slot lookup table.
# Slots 57..120 are mostly digivolution-finisher techs tied to specific
# Digimon forms and are not mastered through the normal learn path.
#
# Source: DWAP's ``GetTechAddress`` switch
# (``references/DWAP/source/DWAP/Helpers.cs:507``). Live-verified
# 2026-05-11 via ``worlds/digimon_world/tools/dw1_tech_snapshot.lua``
# (snapshots #01/#02 against a Patamon-style starter):
#
#   * Snapshot #01 baseline: only bit 4 of 0x00155801 set, matching
#     slot 12 = "Static Elect" (the starter's initial tech per DWAP's
#     ``staticElectStarters`` list).
#   * Snapshot #02 after the poker pressed B on the 9-tech TEST_LIST:
#     bytes 0x00155800..0x00155805 picked up exactly the 9 expected
#     bits PLUS the preserved starter bit. 1:1 match with the
#     ``slot N -> bit N % 8 of byte BASE + N // 8`` mapping.
#
# **The bit alone is load-bearing**: setting it ORs the technique into
# the partner's active combat moveset (verified in-battle 2026-05-11).
# No separate active-moveset slot table needs to be written. AP item
# delivery is therefore a single OR-write to the right byte/bit, with
# a per-tick reconcile loop in the client to re-assert the bit if it
# gets cleared by partner death/rebirth or digivolution.

RAM_TECH_MASTERY_BASE: Final = 0x00155800

# Duplicate slot that vanilla DW1 itself skips. Never present in a
# mastery write, never appears in :data:`TECH_MASTERY_SLOTS`.
TECH_MASTERY_DUPLICATE_SLOT: Final = 48

# The 56 player-masterable technique slots in canonical (ascending)
# order. Defined as a tuple so the order is stable across runs (an AP
# item's id derives from its position-independent dw_code, but tests
# that iterate the list want deterministic ordering).
TECH_MASTERY_SLOTS: Final[tuple[int, ...]] = tuple(
    s for s in range(0, 57) if s != TECH_MASTERY_DUPLICATE_SLOT
)
assert len(TECH_MASTERY_SLOTS) == 56, len(TECH_MASTERY_SLOTS)

# Display names per slot. Verbatim from the standalone DW1 randomizer
# (``references/digimon_world_randomizer/digimon/data.py:65``). Names
# match in-game spelling exactly (including "Spit Fire" with a space,
# "Static Elect" abbreviated, etc.) so AP item-name strings can be
# read straight off the AP client without cross-referencing.
TECH_NAMES_BY_SLOT: Final[dict[int, str]] = {
    0:  "Fire Tower",       1:  "Prominence Beam", 2:  "Spit Fire",
    3:  "Red Inferno",      4:  "Magma Bomb",      5:  "Heat Laser",
    6:  "Infinity Burn",    7:  "Meltdown",        8:  "Thunder Justice",
    9:  "Spinning Shot",    10: "Electric Cloud",  11: "Megalo Spark",
    12: "Static Elect",     13: "Wind Cutter",     14: "Confused Storm",
    15: "Hurricane",        16: "Giga Freeze",     17: "Ice Statue",
    18: "Winter Blast",     19: "Ice Needle",      20: "Water Blit",
    21: "Aqua Magic",       22: "Aurora Freeze",   23: "Tear Drop",
    24: "Power Crane",      25: "All Range Beam",  26: "Metal Sprinter",
    27: "Pulse Laser",      28: "Delete Program",  29: "DG Dimension",
    30: "Full Potential",   31: "Reverse Prog",    32: "Poison Powder",
    33: "Bug",              34: "Mass Morph",      35: "Insect Plague",
    36: "Charm Perfume",    37: "Poison Claw",     38: "Danger Sting",
    39: "Green Trap",       40: "Tremar",          41: "Muscle Charge",
    42: "War Cry",          43: "Sonic Jab",       44: "Dynamite Kick",
    45: "Counter",          46: "Megaton Punch",   47: "Buster Dive",
    # slot 48 ("Dynamite Kick v2") deliberately omitted — see
    # TECH_MASTERY_DUPLICATE_SLOT.
    49: "Odor Spray",       50: "Poop Spd Toss",   51: "Big Poop Toss",
    52: "Big Rnd Toss",     53: "Poop Rnd Toss",   54: "Rnd Spd Toss",
    55: "Horizontal Kick",  56: "Ult Poop Hell",
}
assert set(TECH_NAMES_BY_SLOT) == set(TECH_MASTERY_SLOTS), (
    sorted(set(TECH_NAMES_BY_SLOT) ^ set(TECH_MASTERY_SLOTS))
)


# Vanilla's own ``learnMove`` @ 0x800E5F14 does NOT write one bit for
# these two techniques — it ORs a two-bit u32 mask into the word at
# 0x00155804, setting a *companion* slot alongside the real one:
#
#   learnMove(0x2C) / learnMove(0x30) -> 0x00011000 -> slots 44 AND 48
#   learnMove(0x37) / learnMove(0x39) -> 0x02800000 -> slots 55 AND 57
#
# Console-verified 2026-08-23 (decomp unit ``learnMove``, 566 vectors
# over 70 distinct ids x 8 starting bitmaps, plus 6 natural vectors).
# This is observable, not cosmetic:
#
#   * ``getNumMasteredMoves`` @ 0x800E3510 is a plain 64-bit popcount
#     over both words (verified: ``popcount(w0, w1) == v0`` on all 232
#     vectors, single-bit inputs at 44/48/55/56/57/63 each return 1),
#     so vanilla learning either technique raises the count by **2**.
#   * ``calculateRequirementScore`` @ 0x800E26B8 gates digivolution on
#     ``*(s16 *)(0x8012AC04 + i) <= (s8) getNumMasteredMoves()``, so the
#     count feeds real progression.
#   * ``hasMove`` is a plain bit test with no special-casing, so
#     ``hasMove(0x30)`` reads bit **48** and ``hasMove(0x39)`` reads bit
#     **57** — an AP grant that set only slot 44 would read back as
#     "not known" through those ids.
#
# Writing only the primary bit therefore left an AP-granted technique
# worth one less mastered move than a naturally-learned one. AP delivery
# mirrors vanilla by setting both bits (see the client's technique
# deliverer and reconcile loop). Note ``forgetMove`` @ 0x800E66E0 never
# clears slot 48 on its own, matching vanilla's asymmetry.
# Vanilla's pairing is SYMMETRIC -- learnMove(0x30) sets 44 as well, and
# learnMove(0x39) sets 55 as well (8 replayed vectors each). This table is
# directional because AP only ever grants the primary of each pair: 48 and 57
# are outside TECH_MASTERY_SLOTS, so they never appear as a delivered slot.
# If either is ever added to TECH_NAMES_BY_SLOT, make this bidirectional.
TECH_MASTERY_COMPANION_SLOTS: Final[dict[int, int]] = {
    44: 48,  # Dynamite Kick   -> the "Dynamite Kick v2" duplicate slot
    55: 57,  # Horizontal Kick -> the slot past the player-masterable range
}


def tech_mastery_bits(slot: int) -> tuple[tuple[int, int], ...]:
    """Return every ``(byte_address, bit_index)`` vanilla sets for ``slot``.

    Usually a single pair, but the two techniques in
    :data:`TECH_MASTERY_COMPANION_SLOTS` get their companion bit too, so an
    AP grant is byte-identical to what DW1's own ``learnMove`` would write.
    """

    bits = [tech_mastery_bit(slot)]
    companion = TECH_MASTERY_COMPANION_SLOTS.get(slot)
    if companion is not None:
        bits.append((RAM_TECH_MASTERY_BASE + companion // 8, companion % 8))
    return tuple(bits)


def tech_mastery_bit(slot: int) -> tuple[int, int]:
    """Return ``(byte_address, bit_index)`` for technique mastery ``slot``.

    This is the *primary* bit only. Callers writing a grant should use
    :func:`tech_mastery_bits`, which also covers the companion slot vanilla
    sets for Dynamite Kick and Horizontal Kick.

    Layout: bit ``slot % 8`` of byte ``RAM_TECH_MASTERY_BASE + slot // 8``.
    Asserts the slot is one of the 56 player-masterable techs — passing
    slot 48 (the duplicate) or anything outside 0..56 raises, since
    those have no defined mastery storage.
    """

    if slot not in TECH_NAMES_BY_SLOT:
        raise ValueError(
            f"tech slot {slot} is not player-masterable (valid: "
            f"{TECH_MASTERY_SLOTS!r})",
        )
    return RAM_TECH_MASTERY_BASE + slot // 8, slot % 8


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
# Source: DWAP Locations.json. Digimon id = trigger - 200; vanilla
# prosperity contribution = ``level - 2`` (Rookie 1 / Champion 2 /
# Ultimate 3) except ids 11/39/53 (Numemon/Sukamon/Nanimon) = 1
# (``recalculatePPandArena``, dw_decomp 2026-08-28).
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

# Sanity: ``BLUE_FLUTE_LOCATION_BIT`` (above) must equal Seadramon's
# recruit bit — they refer to the same in-game event (the Seadramon
# friendship cutscene). Catches drift if either side is edited.
assert BLUE_FLUTE_LOCATION_BIT == RECRUIT_RAM_BITS["Seadramon"], (
    BLUE_FLUTE_LOCATION_BIT, RECRUIT_RAM_BITS["Seadramon"],
)

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
    "Chest: Grey Lord's Mansion 4": (0x001BE01E, 2),
    "Chest: Grey Lord's Mansion 5": (0x001BE01E, 3),
    "Chest: Grey Lord's Mansion 6": (0x001BE01E, 4),
    # Trigger 653..657 → Freezeland 1..5 (Script IDs 55, 58, 61, 94)
    "Chest: Grey Lord's Mansion 1": (0x001BE01E, 5),
    "Chest: Grey Lord's Mansion 7": (0x001BE01E, 6),
    "Chest: Grey Lord's Mansion 8": (0x001BE01E, 7),
    "Chest: Grey Lord's Mansion 9": (0x001BE01F, 0),
    "Chest: Ice Sanctuary 1": (0x001BE01F, 1),
    # Triggers 658-659 (Lava Cave 5, 6) dropped 2026-05-24 — the
    # chests do not exist in any reachable area (suspected debug /
    # cut content). Bits stay vanilla; no AP location polls them.
    # Trigger 660..661 → Ice Sanctuary 2..3 (Script ID 98)
    "Chest: Ice Sanctuary 2": (0x001BE01F, 4),
    "Chest: Ice Sanctuary 3": (0x001BE01F, 5),
    # Trigger 662..665 → Freezeland 6..9 (Script IDs 99, 94, 97)
    "Chest: Ice Sanctuary 4": (0x001BE01F, 6),
    "Chest: Ice Sanctuary 5": (0x001BE01F, 7),
    "Chest: Ice Sanctuary 6": (0x001BE020, 0),
    "Chest: Ice Sanctuary 7": (0x001BE020, 1),
    # Trigger 666 → Great Canyon 1 (Script IDs 39/122; live-confirmed
    # in-game — the chest sits in Great Canyon despite the original
    # "Drill Tunnel" inference from the Tablet/Leomon dialog).
    # Trigger 667 → Leomon Ancestor Cave (Script ID 110, screen 114;
    # "Oh no! I hit something that looks like a Tablet." dialog —
    # the Leomonstone-tablet sub-area, gated by 45 PP).
    "Chest: Great Canyon 1":     (0x001BE020, 2),
    "Chest: Leomon Ancestor Cave": (0x001BE020, 3),
    # Trigger 668 → Toy Mansion / WaruMonzaemon Screen (Script ID 145,
    # screen 151; renamed from "Toy Town" — sub-area is Toy Mansion
    # within Toy Town).
    "Chest: Toy Mansion":     (0x001BE020, 4),
    # Trigger 669..671 → Ogre Fortress 1..3 (live-confirmed in-game)
    "Chest: Ogre Fortress 1": (0x001BE020, 5),
    "Chest: Ogre Fortress 2": (0x001BE020, 6),
    "Chest: Ogre Fortress 3": (0x001BE020, 7),
    # Trigger 672 → Secret Beach Cave (Script ID 137, screen 143;
    # Whamon-gated sub-area).
    "Chest: Secret Beach Cave": (0x001BE021, 0),
    # Trigger 673..675 → Ogre Fortress 4..6 (live-confirmed in-game)
    "Chest: Ogre Fortress 4": (0x001BE021, 1),
    "Chest: Ogre Fortress 5": (0x001BE021, 2),
    "Chest: Ogre Fortress 6": (0x001BE021, 3),
    # Trigger 676 → Lava Cave 1 (Script ID 119; live-confirmed)
    "Chest: Lava Cave 1":     (0x001BE021, 4),
    # Trigger 677..678 → Factorial Town 1, 2 (Script ID 155, screen 161 —
    # Main Building Entrance; "Hey, wait! You can't go through here!"
    # guards. Whamon-gated since the entire Factorial Town is.)
    "Chest: Factorial Town 1": (0x001BE021, 5),
    "Chest: Factorial Town 2": (0x001BE021, 6),
    # Trigger 679 → Lava Cave 2 (Script ID 121; live-confirmed)
    "Chest: Lava Cave 2":     (0x001BE021, 7),
    # Trigger 680..682 → Mt. Infinity 1..3
    "Chest: Mt. Infinity 1":  (0x001BE022, 0),
    "Chest: Mt. Infinity 2":  (0x001BE022, 1),
    "Chest: Mt. Infinity 3":  (0x001BE022, 2),
    # Trigger 683 → Ogre Fortress 7 (live-confirmed in-game)
    "Chest: Ogre Fortress 7": (0x001BE022, 3),
    # Trigger 684..691 → Mt. Infinity 4..11
    "Chest: Mt. Infinity 4":  (0x001BE022, 4),
    "Chest: Mt. Infinity 5":  (0x001BE022, 5),
    "Chest: Mt. Infinity 6":  (0x001BE022, 6),
    "Chest: Mt. Infinity 7":  (0x001BE022, 7),
    "Chest: Mt. Infinity 8":  (0x001BE023, 0),
    "Chest: Mt. Infinity 9":  (0x001BE023, 1),
    "Chest: Mt. Infinity 10": (0x001BE023, 2),
    "Chest: Mt. Infinity 11": (0x001BE023, 3),
    # Trigger 693 → Tropical Jungle (Script ID 13). Live-confirmed
    # 2026-04-29: opening this chest in-game placed the player in the
    # Tropical Jungle screen, contradicting the earlier dialog-based
    # inference of Mt. Panorama (Mamemon recruit dialog). The
    # Mamemon-style cutscene shares Script ID 13 with this Tropical
    # Jungle chest, but the chest itself is in Tropical Jungle.
    "Chest: Tropical Jungle": (0x001BE023, 5),
    # Trigger 694..695 → Lava Cave 3..4 (Script IDs 31/120; live-confirmed
    # in-game — both chests sit in the Lava Cave area, behind the
    # Meramon fight and so behind the Lava Cave Access gate).
    "Chest: Lava Cave 3":     (0x001BE023, 6),
    "Chest: Lava Cave 4":     (0x001BE023, 7),
    # Trigger 696..698 → Mt. Panorama 1..2 + Great Canyon 2
    # (Script IDs 22/190; the first two were live-confirmed in-game to
    # be in Mt. Panorama, despite the original "Birdramon area" dialog
    # inference. Trigger 698 stays as Great Canyon pending verification —
    # renumbered from "3" to "2" once trigger 666 was confirmed as
    # Great Canyon 1.)
    "Chest: Mt. Panorama 1":  (0x001BE024, 0),
    "Chest: Mt. Panorama 2":  (0x001BE024, 1),
    "Chest: Mt. Panorama 3":   (0x001BE024, 2),
    # Trigger 700..703 → Mt. Infinity 8..11 (Script ID 188)
    "Chest: Grey Lord's Mansion 10": (0x001BE024, 4),
    "Chest: Grey Lord's Mansion 11": (0x001BE024, 5),
    "Chest: Grey Lord's Mansion 12": (0x001BE024, 6),
    "Chest: Grey Lord's Mansion 13": (0x001BE024, 7),
    # Trigger 704..705 → unknown (Script ID 53)
    "Chest: Grey Lord's Mansion 2": (0x001BE025, 0),
    "Chest: Grey Lord's Mansion 3": (0x001BE025, 1),
    # Trigger 706 → Dragon Eye Lake (Script ID 9, Vending Machine)
    "Chest: Dragon Eye Lake": (0x001BE025, 2),
    # Trigger 707..713 → Back Dimension 1..7 (Script IDs 185/186/187,
    # screens 226/227/228 — post-game-only area unlocked after defeating
    # Machinedramon. The dialogs identify it: Section_60 of script 185
    # has "What kind of place is this?... In the back of this place...";
    # script 186 has "Get him! I'll stomp you!"; script 187 has
    # "Attack! Aim and fire!". See `dw1_back_dimension.md` memory.)
    "Chest: Back Dimension 1": (0x001BE025, 3),
    "Chest: Back Dimension 2": (0x001BE025, 4),
    "Chest: Back Dimension 3": (0x001BE025, 5),
    "Chest: Back Dimension 4": (0x001BE025, 6),
    "Chest: Back Dimension 5": (0x001BE025, 7),
    "Chest: Back Dimension 6": (0x001BE026, 0),
    "Chest: Back Dimension 7": (0x001BE026, 1),
    # Trigger 714..716 → Factorial Town 3..5 (Script ID 156, screen 162
    # — Remodelling Workshop; "We are going to remodel. The fee is two
    # thous bits." NPC dialog.)
    "Chest: Factorial Town 3": (0x001BE026, 2),
    "Chest: Factorial Town 4": (0x001BE026, 3),
    "Chest: Factorial Town 5": (0x001BE026, 4),
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
    "Chest: Grey Lord's Mansion 4": (0x14000EDC,),
    "Chest: Grey Lord's Mansion 5": (0x14000EE8,),
    "Chest: Grey Lord's Mansion 6": (0x14000EF4,),
    "Chest: Grey Lord's Mansion 1": (0x14005868,),
    "Chest: Grey Lord's Mansion 7": (0x140073E8,),
    "Chest: Grey Lord's Mansion 8": (0x140073F4,),
    "Chest: Grey Lord's Mansion 9": (0x14008F7C,),
    "Chest: Ice Sanctuary 1":     (0x14021168,),
    # Lava Cave 5/6 dropped 2026-05-24 — chests don't exist in any
    # reachable area; ROM offsets stay unpatched (left vanilla so
    # nothing weird happens if the player ever reaches the spawn site
    # via debug means).
    "Chest: Ice Sanctuary 2":     (0x14023624,),
    "Chest: Ice Sanctuary 3":     (0x14023630,),
    "Chest: Ice Sanctuary 4":     (0x14023F54,),
    "Chest: Ice Sanctuary 5":     (0x14023F60,),
    "Chest: Ice Sanctuary 6":     (0x14021174,),
    "Chest: Ice Sanctuary 7":     (0x14022D04,),
    "Chest: Great Canyon 1":      (0x13FFA098, 0x13FFA508, 0x14039338, 0x140396CA),
    "Chest: Leomon Ancestor Cave": (0x14030964,),
    "Chest: Toy Mansion":          (0x1404A6DC,),
    "Chest: Ogre Fortress 1":     (0x13FFD7BC,),
    "Chest: Ogre Fortress 2":     (0x13FFE0F0,),
    "Chest: Ogre Fortress 3":     (0x13FFF35C,),
    "Chest: Secret Beach Cave":    (0x14045424,),
    "Chest: Ogre Fortress 4":     (0x1403AEC4,),
    "Chest: Ogre Fortress 5":     (0x1403AED0,),
    "Chest: Ogre Fortress 6":     (0x1403AEDC,),
    "Chest: Lava Cave 1":         (0x140377A8,),
    "Chest: Factorial Town 1":     (0x140539EC,),
    "Chest: Factorial Town 2":     (0x140539F8,),
    "Chest: Lava Cave 2":         (0x14038A04,),
    "Chest: Mt. Infinity 1":      (0x1405836C,),
    "Chest: Mt. Infinity 2":      (0x14058C9C,),
    "Chest: Mt. Infinity 3":      (0x14067B7C,),
    "Chest: Ogre Fortress 7":     (0x1403AEE8,),
    "Chest: Mt. Infinity 4":      (0x1406970C,),
    "Chest: Mt. Infinity 5":      (0x14073334,),
    "Chest: Mt. Infinity 6":      (0x1407F430,),
    "Chest: Mt. Infinity 7":      (0x1407FD54,),
    "Chest: Mt. Infinity 8":      (0x14080688,),
    "Chest: Mt. Infinity 9":      (0x14080FB4,),
    "Chest: Mt. Infinity 10":     (0x140818F4,),
    "Chest: Mt. Infinity 11":     (0x14081900,),
    "Chest: Tropical Jungle":     (0x13FE6844,),
    "Chest: Lava Cave 3":         (0x13FF4DE8, 0x13FF58AA),
    "Chest: Lava Cave 4":         (0x13FF4DF4, 0x13FF58B6),
    "Chest: Mt. Panorama 1":      (0x13FEE01E, 0x1407BD46),
    "Chest: Mt. Panorama 2":      (0x13FEE02A, 0x1407BD52),
    "Chest: Mt. Panorama 3":      (0x13FEE036, 0x1407BD5E),
    "Chest: Grey Lord's Mansion 10": (0x1407AA94,),
    "Chest: Grey Lord's Mansion 11": (0x1407AAA0,),
    "Chest: Grey Lord's Mansion 12": (0x1407AAAC,),
    "Chest: Grey Lord's Mansion 13": (0x1407AAB8,),
    "Chest: Grey Lord's Mansion 2": (0x14003398,),
    "Chest: Grey Lord's Mansion 3": (0x140033A4,),
    "Chest: Dragon Eye Lake":     (0x13FE3118,),
    "Chest: Back Dimension 1":     (0x14078F1C,),
    "Chest: Back Dimension 2":     (0x14079854,),
    "Chest: Back Dimension 3":     (0x14079848,),
    "Chest: Back Dimension 4":     (0x14079860,),
    "Chest: Back Dimension 5":     (0x1407986C,),
    "Chest: Back Dimension 6":     (0x1407A178,),
    "Chest: Back Dimension 7":     (0x1407A184,),
    "Chest: Factorial Town 3":     (0x1405430C,),
    "Chest: Factorial Town 4":     (0x14054318,),
    "Chest: Factorial Town 5":     (0x14054324,),
}
assert len(CHEST_NAME_TO_ROM_OFFSETS) == 63, len(CHEST_NAME_TO_ROM_OFFSETS)
assert sum(len(v) for v in CHEST_NAME_TO_ROM_OFFSETS.values()) == 71, (
    "expected 71 total ROM offsets (8 duplicate spawn entries)"
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

# ----- Map item spawns (463 entries; <BB) ----------------------------------

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
#
# = ``MOVE_LEARN_CHANCES[58][3]`` @ RAM 0x80125FA4 (dw_decomp 2026-08-28),
# indexed ``[techId][matched-specialty index 0..2]`` and rolled
# ``random(100) < chance`` in ``battleMoveLearning`` — only for techs whose
# ``special`` byte (MOVE_DATA + 9) matches one of the partner's three
# specialties and that appear in the partner's 16-entry move list. (An
# older note placed the chance at 0x80126245 + id*0x10; that is
# ``MOVE_DATA[id].special``, not the chance.)

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
# Vending machine locations (consumable machines — opt-in option)
# =============================================================================
#
# Four vending machine scripts in DW1 sell consumable items. With the
# :class:`worlds.digimon_world.options.VendingLocations` option on,
# each item-purchase becomes its own AP location (12 total). Detection
# is a free trigger bit set by a ``setTrigger N`` opcode that the
# patcher writes over the vanilla ``giveItem`` / ``addStats`` opcode at
# the success branch of each purchase. Bytecode-level surgery:
#
# * vanilla ``giveItem ID 1``  (4 bytes: ``28 00 ID 01``)
#   → patched ``setTrigger N`` (4 bytes: ``1C 00 N_lo N_hi``)
# * vanilla ``addStats CURRENTMP X`` (4 bytes: ``35 07 X_lo X_hi``)
#   → patched ``setTrigger N`` (4 bytes: ``1C 00 N_lo N_hi``)
#
# Net effect: the player still pays bits and sees the result text, but
# no vanilla item is granted. The AP location fires; the AP-placed item
# at that location is delivered to the bank by the standard delivery
# path. Same UX as a chest with an AP-placed item.
#
# Each script has 1-2 byte-identical ROM copies (paired duplicates the
# game loads under different Script IDs, like chests). All copies must
# be patched in lockstep.
#
# Free trigger bits 890..901 land in gap C of the trigger array
# (0x001BE03C bits 2..7 + 0x001BE03D bits 0..5). Adjacent to but does
# not overlap the Birdramon flight bits (trigger 880..884 at
# 0x001BE03B bits 0..4) — see :data:`BIRDRAMON_FLIGHT_RAM_BITS`.
#
# Vanilla menu / preface / result text is left untouched. (An earlier
# Quest/Bonus/Junk text-substitution pass was retired 2026-05-08
# because DW1's script-engine PC-advance is fragile against shortened
# textboxes — substitutions could and did intermittently cause the
# engine to drop out of the script before reaching our setTrigger
# overwrite, suppressing the AP location.)

class _VendingItem(NamedTuple):
    """Per-purchase row for a vending machine."""
    location_name: str           # AP location name
    region: str                  # AP region the location belongs to
    trigger_id: int              # AP-allocated trigger bit (890..901)
    overwrite_offsets: tuple[int, ...]
    """Script-relative byte offsets within the parent script where the
    vanilla ``giveItem``/``addStats`` opcode lives. Each must be
    overwritten with ``setTrigger trigger_id`` (4 bytes). Multiple
    entries cover both the success branch and any inventory-recovery
    branch the vanilla script uses.
    """
    price_offsets: tuple[int, ...]
    """Script-relative byte offsets of the 16-bit LE price immediates
    (used by the optional :class:`worlds.digimon_world.options.RandomizeVendingPrices`
    option in Stage 2 to rewrite the prices). Reserved for future use;
    Stage 1 ships price-randomization as not-yet-implemented.
    """
    vanilla_price: int           # vanilla cost in bits (informational)


class _VendingMachine(NamedTuple):
    """One vending machine: a script with N items and 1-2 ROM copies."""
    label: str                   # short region/name for diagnostics
    region: str                  # AP region (matches existing regions.py)
    script_bases: tuple[int, ...]  # .bin offset of each ROM copy's script base
    items: tuple[_VendingItem, ...]


# Allocated trigger IDs for vending purchases. Gap C of the trigger
# array; immediately after Birdramon flight bits (880..884).
_VENDING_TRIGGER_BASE: Final = 890

VENDING_MACHINES: Final[tuple[_VendingMachine, ...]] = (
    # ---- Script 9 — Greatlake (Dragon Eye Lake): Meat 300, DigiMushroom 600
    _VendingMachine(
        label="Greatlake",
        region="Greatlake",
        script_bases=(0x13FE3108, 0x13FE3108 + 0x96A),
        items=(
            _VendingItem(
                "Vending: Greatlake Meat", "Greatlake",
                trigger_id=890,
                overwrite_offsets=(540, 632),
                price_offsets=(330, 496),
                vanilla_price=300,
            ),
            _VendingItem(
                "Vending: Greatlake DigiMushroom", "Greatlake",
                trigger_id=891,
                overwrite_offsets=(714, 806),
                price_offsets=(414, 640),
                vanilla_price=600,
            ),
        ),
    ),
    # ---- Script 11 — Tropical Jungle: Hund MP 200, Thous MP 1800
    _VendingMachine(
        label="Tropical Jungle",
        region="Tropical Jungle",
        script_bases=(0x13FE5EF8, 0x13FE5EF8 + 0x3E0),
        items=(
            _VendingItem(
                "Vending: Tropical Jungle Hund MP", "Tropical Jungle",
                trigger_id=892,
                overwrite_offsets=(340,),  # addStats CURRENTMP 100
                price_offsets=(330, 346),
                vanilla_price=200,
            ),
            _VendingItem(
                "Vending: Tropical Jungle Thous MP", "Tropical Jungle",
                trigger_id=893,
                overwrite_offsets=(490,),  # addStats CURRENTMP 1000
                price_offsets=(480, 496),
                vanilla_price=1800,
            ),
        ),
    ),
    # ---- Script 71 — Gear Savanna: Special Prizes (Small Recovery 200,
    #      Portable Potty 500). The MP Stand sub-vendor's two slots
    #      (Hund / Thous MP) are not exposed as AP locations — the
    #      in-game machine entries those would have hooked don't exist
    #      in practice, so attaching checks to them was unreachable.
    _VendingMachine(
        label="Gear Savanna",
        region="Gear Savanna",
        script_bases=(0x1400FDA8, 0x1400FDA8 + 0xA44),
        items=(
            _VendingItem(
                "Vending: Gear Savanna Small Recovery", "Gear Savanna",
                trigger_id=894,
                overwrite_offsets=(984,),
                price_offsets=(824, 1130),
                vanilla_price=200,
            ),
            _VendingItem(
                "Vending: Gear Savanna Portable Potty", "Gear Savanna",
                trigger_id=895,
                overwrite_offsets=(1156,),
                price_offsets=(906, 1292),
                vanilla_price=500,
            ),
        ),
    ),
    # ---- Script 78 — Ancient Dino Region: Try gacha (200 bits, random)
    _VendingMachine(
        label="Ancient Dino Region",
        region="Ancient Dino Region",
        script_bases=(0x14015188,),  # single copy
        items=(
            _VendingItem(
                "Vending: Ancient Dino Gacha Meat", "Ancient Dino Region",
                trigger_id=898,
                overwrite_offsets=(3090,),
                price_offsets=(2946, 3046),
                vanilla_price=200,
            ),
            _VendingItem(
                "Vending: Ancient Dino Gacha Small Recovery", "Ancient Dino Region",
                trigger_id=899,
                overwrite_offsets=(3320,),
                price_offsets=(3238,),
                vanilla_price=200,
            ),
            _VendingItem(
                "Vending: Ancient Dino Gacha Steak", "Ancient Dino Region",
                trigger_id=900,
                overwrite_offsets=(3516,),
                price_offsets=(3468,),
                vanilla_price=200,
            ),
            _VendingItem(
                "Vending: Ancient Dino Gacha MP Floppy", "Ancient Dino Region",
                trigger_id=901,
                overwrite_offsets=(3840,),
                price_offsets=(3664,),
                vanilla_price=200,
            ),
        ),
    ),
)

# Flat list of (location_name, byte_addr, bit_index) for client lookup.
# AP_TRIGGER_ARRAY_BASE is defined further down; inline it here.
def _build_vending_location_ram_bits() -> dict[str, tuple[int, int]]:
    _BASE = 0x001BDFCD  # AP_TRIGGER_ARRAY_BASE — declared later
    table: dict[str, tuple[int, int]] = {}
    for machine in VENDING_MACHINES:
        for item in machine.items:
            byte_addr = _BASE + item.trigger_id // 8
            bit_index = item.trigger_id % 8
            table[item.location_name] = (byte_addr, bit_index)
    return table


VENDING_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = _build_vending_location_ram_bits()
assert len(VENDING_LOCATION_RAM_BITS) == 10, len(VENDING_LOCATION_RAM_BITS)

# Ordered list of all vending location names — locations.py imports this
# to build location entries.
VENDING_LOCATION_NAMES: Final[tuple[str, ...]] = tuple(VENDING_LOCATION_RAM_BITS)

# Region for each location — locations.py uses this to attach the
# location to the correct region.
VENDING_LOCATION_REGIONS: Final[dict[str, str]] = {
    item.location_name: item.region
    for machine in VENDING_MACHINES
    for item in machine.items
}

# Sanity: trigger range 890..901 lives in 2 bytes of gap C.
assert all(
    0x001BE03C <= b <= 0x001BE03D for b, _ in VENDING_LOCATION_RAM_BITS.values()
), VENDING_LOCATION_RAM_BITS


# ----- Vending machine helper encoders --------------------------------------
#
# DW1's script-engine opcode constants used by the vending patcher.

VENDING_OPCODE_SETTRIGGER: Final = 0x1C  # 4 bytes: 1C 00 [N_LE]
VENDING_OPCODE_JUMPTO: Final = 0x16      # 4 bytes: 16 00 [target_LE]


def encode_set_trigger(trigger_id: int) -> bytes:
    """Encode a 4-byte ``setTrigger N`` script-engine opcode."""
    return bytes((VENDING_OPCODE_SETTRIGGER, 0x00,
                  trigger_id & 0xFF, (trigger_id >> 8) & 0xFF))


# ----- Ancient Dino "Try" gacha vanilla-bug fix ----------------------------
#
# The MP Floppy outcome (gacha prize 4) is structured differently from the
# other three prizes: its only ``giveItem`` opcode lives inside the
# inventory-full recovery branch, so a player with free inventory space
# (the common case) never gets the item — and the AP setTrigger 901 we
# overwrite at offset 3840 is never reached either. Other three prizes
# (Meat / Small Recovery / Steak) put ``giveItem`` *before* the inventory
# check; their recovery branch is a duplicate write.
#
# Disassembly (DW1Script.txt:14330-14343, Section_81):
#
#     003660 setDialogOwner 255
#     003662 reduceMoney 200
#     003670 showTextbox An MP floppy came out!
#     003726 if trigger(0) == false then 3846   <-- BUG: jumps to endSection
#     003738 ... (inventory-full recovery branch) ...
#     003840 giveItem 4 1                       <-- only reached if inventory full
#     003844 endSection
#
# Fix: replace the 12-byte conditional at offset 3726 with a 4-byte
# unconditional ``jumpTo 3840`` that lands directly on the giveItem (now
# our setTrigger 901 overwrite). The 8 trailing bytes of the original
# conditional become dead code — the engine never reaches them because
# the jumpTo fires first. Skipped: the inventory-full recovery branch's
# ``setTrigger 3 + callRoutine 0/13`` housekeeping, irrelevant for AP
# delivery (the actual item arrives via the bank, not this vending site).
#
# Script base for Ancient Dino is 0x14015188 (single ROM copy). 3840 in
# little-endian u16 = 0x00, 0x0F. Encoding: ``16 00 00 0F``.

_ANCIENT_DINO_SCRIPT_BASE: Final = 0x14015188
_GACHA_MP_FLOPPY_GIVEITEM_OFFSET: Final = 3840

ROM_GACHA_MP_FLOPPY_FIX_OFFSET: Final = _ANCIENT_DINO_SCRIPT_BASE + 3726
ROM_GACHA_MP_FLOPPY_FIX_BYTES: Final = bytes((
    VENDING_OPCODE_JUMPTO, 0x00,
    _GACHA_MP_FLOPPY_GIVEITEM_OFFSET & 0xFF,
    (_GACHA_MP_FLOPPY_GIVEITEM_OFFSET >> 8) & 0xFF,
))


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
# PP-calc patch (Phase 4 v4) — RETIRED 2026-08-28
# =============================================================================
#
# **No longer written by the patcher.** The constants stay for the record.
#
# What this actually was (dw_decomp audit, 2026-08-28): ``0x14D2848C`` is
# RAM 0x800EFA44 = ``recalculatePPandArena`` + 0x2C — the loop that computes
# **prosperity points** (``pstat(1)``), not technique PP. Vanilla
# (``src/main/main.c:406-434``) sums ``DIGIMON_DATA[i].level - 2`` over every
# recruited Digimon (trigger 200+i), with Numemon/Sukamon/Nanimon (ids
# 11/39/53) counting 1. The standalone randomizer's 11-instruction rewrite
# makes the loop read ``DIGIMON_DATA[i].height & 3`` instead — a field the
# standalone SEEDS with a per-Digimon PP value (``handler.py:48-60``). We
# never seeded it, so the patched loop computed garbage; nobody noticed
# because the client's ``_enforce_prosperity`` re-asserts the AP-delivered
# value every tick. The earlier rationale here ("max PP for each technique
# slot") was a misreading of the name. Removing the patch leaves the
# vanilla formula as the fallback the client overrides — strictly better.
# Source of the original bytes: ``references/digimon_world_randomizer/digimon/data.py:709-713``.

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
# Sub-table layout within the array (``0x001BDFCD..0x001BE040``):
#
# * ``0x001BDFCD..0x001BDFE5`` — **gap A** (25 bytes, 200 bits). Story-event
#   trigger bits live here. Confirmed entries:
#   :data:`RAM_TROPICAL_JUNGLE_BRIDGE_FIXED` at ``(0x001BDFE4, 1)``,
#   :data:`RAM_GREAT_CANYON_BRIDGE_UNLOCKED` at ``(0x001BDFD9, 7)``.
#   Note that ``0x001BDFD9`` also holds an unrelated story-event flag
#   in bit 0 (sets on first entry to Tropical Jungle), so multiple
#   independent bits per byte is the norm.
# * ``0x001BDFE6..0x001BDFED`` — :data:`RECRUIT_RAM_BITS` (50 bits over
#   8 bytes; bits 0-2 of ``0x001BDFE6`` and bits 5-6 of ``0x001BDFED``
#   are unassigned).
# * ``0x001BDFEE..0x001BE01D`` — **gap B** (48 bytes, 384 bits). Likely
#   contains many more story-event trigger bits, plus byte-valued state
#   such as :data:`RAM_CHART_BASE` (``0x001BE00D``).
# * ``0x001BE01E..0x001BE026`` — :data:`DWAP_CHEST_RAM_BITS` (65 bits
#   over 9 bytes; the 8 bit gaps in this range are mirrored from DWAP
#   and may be reserved or correspond to chests DWAP missed — see the
#   ``DWAP_CHEST_RAM_BITS`` block above).
# * ``0x001BE027..0x001BE02E`` — :data:`BEATEN_RAM_BITS` (50 bits over
#   8 bytes; same per-Digimon ordering as :data:`RECRUIT_RAM_BITS`).
# * ``0x001BE02F..0x001BE040`` — **gap C** (18 bytes). Contains
#   byte-valued progression state including :data:`RAM_PROSPERITY_POINTS`
#   (``0x001BE032``); residual bits may also be story triggers.
#
# **Methodology for finding new area-unlock flags**: dump the array span
# before and after the gating event using
# ``worlds/digimon_world/tools/dw1_ram_snapshot.lua``, then diff. A
# single-bit 0->1 flip inside one of the gap regions, sticky across map
# transitions, is the signature of a story-event trigger. Cross-check
# the bit isn't already used by chest/recruit/beaten tables before
# trusting the result. Pattern validated on the Tropical Jungle bridge
# (2026-04-30): 5-snapshot diff produced exactly one such candidate,
# user-confirmed by RAM-watch poke.
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
# Lava Cave gate patch (Drill Tunnel boulder)
# =============================================================================
#
# Script ID 30 (the Drimogemon-tunnel/boulder script) gates rock removal
# behind a 28-byte ``if pstat(103) != ... then`` whitelist of digimon IDs
# (Fresh/In-Training/Rookie). The patched bytecode replaces that whole
# 28-byte block with a single ``if trigger(145) == true then 600``
# (jump straight into the rock-moving sequence) followed by 16 bytes of
# ``jumpTo 1376`` filler (unreachable in normal flow; both branches of
# the new if either go to 600 or fall through to the original
# ``jumpTo 1376`` at script offset 512).
#
# When trigger 145 (= :data:`LAVA_CAVE_ACCESS_FLAG`) is unset, the patched
# if falls through and the boulder cutscene fails. When the AP delivers
# the ``Lava Cave Access`` item, the client sets bit 1 of ``0x001BDFDF``
# and the next time the player walks to the boulder, the rock moves.
#
# The boulder script is duplicated in the BIN under two script IDs (same
# pattern as chest scripts that get loaded under multiple Script IDs);
# both copies must be patched. Offsets verified by reading the BIN —
# both contain byte-identical 28-byte rock-check blocks beginning with
# ``19 00 08 00 67 01 48 00 ...``.
#
# Encoding: ``19 00`` = if-statement opcode, ``01 00`` = 1-condition
# count, ``<id_LE>`` = trigger ID (145 = ``91 00``), ``18 00`` = "==
# true" comparator, ``<target_LE>`` = branch target (600 = ``58 02``),
# trailing ``19 00`` = next-instruction marker. ``16 00 <target_LE>`` =
# jumpTo (4 bytes total). 1376 = ``60 05`` LE.

ROM_LAVA_CAVE_GATE_OFFSETS: Final = (
    0x13FF468C,  # Script ID 30 (boulder), Section_5 script-offset 484
    0x13FF4C58,  # Duplicate copy of the same script in the BIN
)
ROM_LAVA_CAVE_GATE_VALUE: Final = bytes((
    # if trigger(145) == true then 600  (12 bytes)
    0x19, 0x00, 0x01, 0x00, 0x91, 0x00, 0x18, 0x00, 0x58, 0x02, 0x19, 0x00,
    # jumpTo 1376 x 4  (16 bytes filler — unreachable in normal flow)
    0x16, 0x00, 0x60, 0x05, 0x16, 0x00, 0x60, 0x05,
    0x16, 0x00, 0x60, 0x05, 0x16, 0x00, 0x60, 0x05,
))


# =============================================================================
# Coelamon take-across gate patch (Tropical Jungle Bridge SHUFFLED mode)
# =============================================================================
#
# Coelamon's Section_51 (Script ID 6, script-offset 586) uses a 16-byte
# 2-condition gate:
#
#     if trigger(185) == false OR trigger(249) == true then 1506
#
# (The trigger-249 read is remapped to trigger 779 by the always-on
# Coelamon recruit-cutscene remap — see ``ROM_COELAMON_CUTSCENE_REMAP_*``
# near the end of this module. The branch-target byte patched here is
# the same statement, different bytes; the two patch families compose.)
#
# Branch target 1506 is the entry to case 1 ("I'll take you across the
# water"), which would let the player reach Tropical Jungle without the
# AP-controlled "Tropical Jungle Bridge" item. To close the bypass we
# rewrite *only the branch target* — 1506 -> 1532 — so the same gate
# now jumps to ``endSection`` (Coelamon does nothing) when the bridge
# bit is unset. Once AP delivers the bridge item, the client OR-pins
# trigger 185, the gate falls through, and case 2 ("Coelamon joins the
# city") fires as in vanilla.
#
# **Offset repair 2026-08-22**: this patch originally shipped with
# offsets 0x13FE0572 / 0x13FE12B6 — a +4 arithmetic slip. Those bytes
# are the ``4F 14`` head of ``moveCameraTo 20 2214 865`` (vm 602, the
# recruit path's FIRST instruction), so the shipped patch left the
# ferry bypass open AND corrupted the recruit cutscene head in
# shuffled mode. The branch-target u16 actually lives at vm 598 = flat
# 0x13FE056E (byte-verified: ``E2 05`` = 1506 there, ``4F 14`` at the
# old offsets). Derivation asserts live next to the cutscene-remap
# constants (they need :func:`script_vm_to_bin_offset`).
#
# "Copy 2" is the slot-tail residue: Script 6's slot tail (vm
# 3092..4095, after the FF 00 terminator @3090) is a stale self-copy
# shifted +3092 — dead code (the section table never points there) but
# disc-loaded with the script's final 2048-byte block; patched for
# hygiene. Patch is emitted only when ``options.bridge_unlock ==
# shuffled``. Always_open mode (185 pinned from the start) keeps the
# unpatched 1506 branch target.

ROM_COELAMON_GATE_OFFSETS: Final = (
    0x13FE056E,  # real gate: Script 6 vm 598 (statement head vm 586 + 12)
    0x13FE12B2,  # dead residue twin: vm 3690 (= 598 + 3092)
)
ROM_COELAMON_GATE_VALUE: Final = bytes((0xFC, 0x05))  # 1532 LE


# =============================================================================
# Old Fishrod cutscene remap (always-on)
# =============================================================================
#
# The rod-give cutscene (Script ID 159, Section_51, script offsets
# 006718..006824 — see DW1Script.txt:23920) sets two trigger bits on
# completion:
#
#     006718 if trigger(45) == true then 6824   <-- replay gate
#     006732..006812 [textbox / animation / sound]
#     006816 setTrigger 45     <-- ALSO the bit `getBestFishingRod()`
#                                  reads to enable Old Rod fishing
#                                  (Fishing.cpp:21).
#     006820 setTrigger 320    <-- script-side "rod-given" memory bit;
#                                  read by Script 159 Section_254 to
#                                  hide the rod sprite on the trash
#                                  heap (DW1Script.txt:23690).
#     006824 endSection
#
# Sharing trigger 45 between "cutscene played" and "rod owned" means
# AP delivery of the Old Fishrod item (which writes trigger 45) would
# self-trigger the AP location and vanilla cutscene completion would
# enable fishing without AP delivery. Both are wrong for AP rando.
#
# Fix: surgical 4-byte rewrite redirecting the cutscene to a fresh
# AP-allocated trigger (902, :data:`OLD_FISHROD_LOCATION_TRIGGER_ID`),
# leaving trigger 45 (the fishing-enable bit) and trigger 320 (the
# sprite-hide bit) alone:
#
#     006718 if trigger(902) == true then 6824   <-- gate now reads 902
#     006816 setTrigger 902                      <-- cutscene now sets 902
#     006820 setTrigger 320                      <-- unchanged
#
# After the patch:
#
# * Cutscene plays -> sets trigger 902 (location signal) + trigger 320
#   (sprite hidden). Gate now reads 902 -> won't replay. Fishing is NOT
#   enabled by the cutscene anymore.
# * AP delivers Old Fishrod -> client writes trigger 45 -> fishing
#   enabled. Trigger 902 is untouched -> location does not self-fire.
#
# Encoded as two 2-byte writes (trigger ID = 902 = 0x0386, LE = ``86 03``):
#
# * Conditional trigger ID: at the conditional's offset 4..5 (the
#   12-byte encoding lays the trigger ID at offset 4-5; same shape as
#   :data:`ROM_LAVA_CAVE_GATE_VALUE`). Script base 0x14056218 + script
#   offset 0x1A3E + 4 = 0x14057C5A.
# * setTrigger trigger ID: at the setTrigger opcode's offset 2..3 (the
#   4-byte encoding lays the trigger ID at offset 2-3; see
#   :func:`encode_set_trigger`). Script base 0x14056218 + script
#   offset 0x1AA0 + 2 = 0x14057CBA.
#
# Single ROM copy (Script 159 unique in the BIN — verified by scanning
# the .bin for the 8-byte signature ``1C 00 2D 00 1C 00 40 01``: one
# hit at 0x14057CB8). Patch is always emitted (no option flag); the
# vanilla cutscene flow is incompatible with AP rando regardless of
# other settings.

ROM_OLD_FISHROD_REMAP_OFFSETS: Final = (
    0x14057C5A,  # if trigger(45) ...   trigger ID byte position
    0x14057CBA,  # setTrigger 45         trigger ID byte position
)
ROM_OLD_FISHROD_REMAP_VALUE: Final = bytes((
    OLD_FISHROD_LOCATION_TRIGGER_ID & 0xFF,
    (OLD_FISHROD_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Mansion Key giveItem neuter (always-on)
# =============================================================================
#
# The Mansion Key pickup cutscene (Script 54, Section_81 — see
# DW1Script.txt:11583-11604) calls ``giveItem 119 1`` twice:
#
#     000140 if trigger(110) == true then 450      <-- replay gate
#     000154..000174 [textbox / animation / sprite housekeeping]
#     000178 giveItem 119 1                        <-- PRIMARY (succeeds when bag has space)
#     000182..000352 [textbox / "I used the Mansion Key!"]
#     000352 if trigger(0) == false then 442       <-- skip retry on success
#     000364..000436 ["I gotta get rid of something" + cleanup]
#     000438 giveItem 119 1                        <-- RETRY (after player frees bag space)
#     000442 setTrigger 110                        <-- gate set
#     000446 jumpTo 452
#     000450 endSection
#     000452 endSection
#
# In AP rando the vanilla giveItem must be neutered — the player
# receives Mansion Key only via AP delivery (item id 119, routed
# inventory-first with bank fallback by the client's
# :func:`_make_item_deliverer`). Both giveItem sites are rewritten
# with ``setTrigger 110`` (same 4-byte length: ``1C 00 6E 00``); the
# cutscene's existing ``setTrigger 110`` at offset 442 becomes
# redundant but harmless. Net effect: the cutscene plays normally
# (textbox, animation, "I found a key!" message) but no item enters
# inventory, and the AP location ``Mansion Key Pickup`` fires when
# trigger 110 transitions 0->1.
#
# Two ROM copies of Script 54 in the .bin (verified by scanning for
# the 4-byte signature ``28 00 77 01``: four hits, paired by the
# script-relative 0x104 byte distance between primary and retry).
# Script 54 base copies: 0x14003CB8 and 0x14004F40 (delta 0x1288).
# Patch is always emitted (no option flag); the vanilla in-game
# Mansion Key grant is incompatible with AP rando.

ROM_MANSION_KEY_GIVEITEM_OFFSETS: Final = (
    0x14003D6A,  # Copy 1 primary  (script-offset 178 = 0xB2)
    0x14003E6E,  # Copy 1 retry    (script-offset 438 = 0x1B6)
    0x14004FF2,  # Copy 2 primary
    0x140050F6,  # Copy 2 retry
)
# Replacement: ``setTrigger 110`` (opcode 0x1C, sub 0x00, trigger ID 110 LE).
ROM_MANSION_KEY_GIVEITEM_NEUTER_VALUE: Final = bytes((
    VENDING_OPCODE_SETTRIGGER, 0x00,
    MANSION_KEY_LOCATION_TRIGGER_ID & 0xFF,
    (MANSION_KEY_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Frig Key giveItem neuter (always-on)
# =============================================================================
#
# The Frig Key cutscene (Myotismon dialog inside Grey Lord's Mansion;
# Script 63 Section_5 — see DW1Script.txt:12166-12222) is a more
# elaborate dialog tree than Mansion Key. Approximate flow:
#
#     000146 if item(122) < 1 then 164      <-- skip Steak handover branch
#     000164 if trigger(104) == false then 238   <-- first meeting?
#     000176..000234 [repeat-visit branch — quick line, no giveItem]
#     000238 setTrigger 104                  <-- AP location signal fires here
#     000242..000496 [intro dialog + meat check]
#     000652..000654 [Myotismon: "Here."]
#     000670 giveItem 123 1                  <-- PRIMARY key give
#     000674..000694 ["A key?" + inventory check]
#     000706..000778 [retry path]
#     000780 giveItem 123 1                  <-- RETRY key give
#     000784 showTextbox I got a Frige Key!
#     000832..001008 [outro]
#     001012 endSection
#
# Both giveItem 123 sites are rewritten with ``setTrigger 104``
# (idempotent — the bit was already set at script offset 238 during
# the cutscene intro). Two ROM copies of Script 63 in the .bin
# (verified by scanning for the 4-byte signature ``28 00 7B 01``:
# four hits, paired by the script-relative 0x6E byte distance
# between primary and retry). Script 63 base copies: 0x1400A1C8
# and 0x1400AC96 (delta 0xACE).
#
# Note: the cutscene's first instruction at offset 146 checks for
# Steak (item 122) — if the player has Steak when first approaching
# Myotismon, the script jumps to the Steak handover path (offset 1014
# onward) and trigger 104 is NEVER set on that visit. Since Steak is
# NOT an AP-tracked item (vanilla DW1 spawns it from the Overdell
# fridge, which itself requires Frig Key), the player cannot reach
# Myotismon with Steak in inventory unless they already have Frig
# Key — so this corner case is unreachable and the cutscene always
# takes the normal first-meeting branch, flipping trigger 104.

ROM_FRIG_KEY_GIVEITEM_OFFSETS: Final = (
    0x1400A466,  # Copy 1 primary  (script-offset 670 = 0x29E)
    0x1400A4D4,  # Copy 1 retry    (script-offset 780 = 0x30C)
    0x1400AF34,  # Copy 2 primary
    0x1400AFA2,  # Copy 2 retry
)
# Replacement: ``setTrigger 104`` (opcode 0x1C, sub 0x00, trigger ID 104 LE).
ROM_FRIG_KEY_GIVEITEM_NEUTER_VALUE: Final = bytes((
    VENDING_OPCODE_SETTRIGGER, 0x00,
    FRIG_KEY_LOCATION_TRIGGER_ID & 0xFF,
    (FRIG_KEY_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Gear giveItem neuter (always-on)
# =============================================================================
#
# The Gear acquisition cutscene (Toy Town, post-WaruMonzaemon defeat;
# Script 144 Section_83 — see DW1Script.txt:21930-22437) uses the same
# 4-byte ``giveItem 120 1`` shape we've seen elsewhere:
#
#     [..., WaruMonzaemon dialogue, Gear hand-off setup ...]
#     004334 giveItem 120 1                    <-- PRIMARY key give
#     004338 if trigger(0) == false then 4480  <-- skip retry on success
#     004350..004474 [retry path: "Oh no, I have too many..." + cleanup]
#     004476 giveItem 120 1                    <-- RETRY key give
#     004482 showTextbox I got a Gear!
#     004518 setTrigger 270                    <-- AP location signal
#     004522 endSection
#
# Both giveItem 120 sites rewritten with ``setTrigger 270``
# (idempotent — the bit is already set at offset 4518 by the
# cutscene's existing setTrigger). One ROM copy of Script 144 in the
# .bin (verified by scanning for the 4-byte signature
# ``28 00 78 01``: only one pair matched the script-relative
# 0x8E byte distance between primary and retry; other unrelated
# matches were filtered out). Script 144 base: 0x1404A928.

ROM_GEAR_GIVEITEM_OFFSETS: Final = (
    0x1404BA16,  # Primary  (script-offset 4334 = 0x10EE)
    0x1404BAA4,  # Retry    (script-offset 4476 = 0x117C)
)
# Replacement: ``setTrigger 270`` (opcode 0x1C, sub 0x00, trigger ID 270 LE).
ROM_GEAR_GIVEITEM_NEUTER_VALUE: Final = bytes((
    VENDING_OPCODE_SETTRIGGER, 0x00,
    GEAR_LOCATION_TRIGGER_ID & 0xFF,
    (GEAR_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Rain Plant giveItem neuter (always-on)
# =============================================================================
#
# Rain Plant is given via a single ``giveItem 121 1`` in the Tanemon
# planter cutscene (Native Forest; Script 162 Section_83 — see
# DW1Script.txt:24504-24520). Pre-conditions: Palmon recruited
# (trigger 246) AND day-15-of-month (``pstat(106) == 14``). Notably
# the cutscene has **no retry path** — if the player's inventory is
# full at giveItem time, the section ends without setting trigger 76,
# and the player has to come back next month.
#
#     006044 if trigger(76) == false AND trigger(246) == true then 6062
#     006062 if pstat(106) == 14 then 6076
#     006076 setDialogOwner 253
#     006078 showTextbox Oh, this is a...
#     006116 giveItem 121 1                  <-- THE ONLY giveItem
#     006120 if trigger(0) == false then 6172  <-- skip success path on inventory-full
#     006132..006170 [inventory-full path: "Too many Items." + endSection]
#     006172 setObjVisibility 72 1
#     006178 showTextbox I got a Rain Plant Fruit!
#     006238 setTrigger 76                    <-- AP location signal
#     006242 endSection
#
# The single giveItem site is rewritten with ``setTrigger 76``
# (idempotent — the bit is set at offset 6238 by the cutscene's own
# setTrigger). One ROM copy of Script 162 in the .bin (verified by
# scanning for the 4-byte signature ``28 00 79 01``: only one hit
# matched the expected ``if trigger(0)`` conditional structure
# following the giveItem; the other was unrelated data). Script 162
# base: 0x14059808.
#
# Note: trigger 76 is **renewable** — Section_254 of Script 162
# `unsetTrigger 76` on each day-15 transition (script offset 24134),
# letting vanilla DW1 spawn a fresh Rain Plant each month. After our
# patch the cutscene still re-runs each month (trigger 76 unsets,
# then resets via our patched giveItem-as-setTrigger), but the AP
# location only fires once thanks to server-side dedup.

ROM_RAIN_PLANT_GIVEITEM_OFFSETS: Final = (
    0x1405AFEC,  # Single ROM copy (Script 162 Section_83, script-offset 6116 = 0x17E4)
)
# Replacement: ``setTrigger 76`` (opcode 0x1C, sub 0x00, trigger ID 76 LE).
ROM_RAIN_PLANT_GIVEITEM_NEUTER_VALUE: Final = bytes((
    VENDING_OPCODE_SETTRIGGER, 0x00,
    RAIN_PLANT_LOCATION_TRIGGER_ID & 0xFF,
    (RAIN_PLANT_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Blue Flute giveItem neuter (always-on)
# =============================================================================
#
# The Blue Flute pickup is part of the Seadramon friendship cutscene
# (Script 7 Section_82 — see DW1Script.txt:4727-4747). The player
# hooks Seadramon while fishing in Dragon Eye Lake, picks the
# "Let's be friends" dialog option, and Seadramon hands over the
# Blue Flute. Approximate flow:
#
#     001998 setTrigger 210                    <-- AP location signal
#     002002 addToPStat 1 2
#     002006 giveItem 115 1                    <-- PRIMARY key give
#     002010 if trigger(0) == false then 2140  <-- skip retry on success
#     002022..002134 [retry path: "Too many Items." + cleanup]
#     002136 giveItem 115 1                    <-- RETRY key give
#     002140 setDialogOwner 255
#     002142 showTextbox I got the Lake Guardian's Blue Flute!
#     ... outro dialog ...
#     002648 setTrigger 49 (selection prompt unrelated)
#
# Both giveItem 115 sites are rewritten with ``setTrigger 210``
# (idempotent — the bit is set at offset 1998 already). Trigger 210
# was Seadramon's recruit bit until 2026-05-09; with Seadramon now in
# :data:`_AP_RECRUIT_EXCLUDED`, the bit is polled exclusively as
# :data:`BLUE_FLUTE_LOCATION_BIT` for the ``Blue Flute Pickup``
# location.
#
# Single ROM copy of Script 7 in the .bin (verified by scanning for
# the 4-byte signature ``28 00 73 01`` and confirming surrounding
# context: setTrigger 210 / addToPStat / "if trigger(0) == false"
# conditional / setDialogOwner 255 / showTextbox "I got the Lake
# Guardian's Blue Flute!" — see commit notes). Two giveItem sites in
# the single copy. The .bin gap between primary (0x13FE1D4E) and
# retry (0x13FE1F00) is wider than the script-relative gap (434 vs
# 130 bytes) because a 2048-B user-data sector boundary sits between
# them — in USER space the disassembler's offsets map 1:1 (see
# :data:`SCRIPT_ARCHIVE_USER_BASE`); flat-offset deltas across sectors
# include the 304 B of header+EDC interleave. We trust the .bin scan
# and patch both sites directly.

ROM_BLUE_FLUTE_GIVEITEM_OFFSETS: Final = (
    0x13FE1D4E,  # Primary (script-offset 2006 in dumper output; preceded by setTrigger 210 + addToPStat)
    0x13FE1F00,  # Retry (followed by setDialogOwner 255 + "I got the Lake Guardian's Blue Flute!" textbox)
)
# Replacement: ``setTrigger 210`` (opcode 0x1C, sub 0x00, trigger ID 210 LE).
ROM_BLUE_FLUTE_GIVEITEM_NEUTER_VALUE: Final = bytes((
    VENDING_OPCODE_SETTRIGGER, 0x00,
    BLUE_FLUTE_LOCATION_TRIGGER_ID & 0xFF,
    (BLUE_FLUTE_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Leomonstone giveItem neuter (always-on)
# =============================================================================
#
# Leomon's Ancestral Cave (deepest chamber of Drill Tunnel B3F) holds
# the Leomonstone — a stone tablet the player picks up via cutscene.
# The cutscene (Script 109 Section_52 — see DW1Script.txt:17834-17869)
# plays automatically on entering the cave with the visible tablet:
#
#     000126 if trigger(135) == true then 682     <-- replay gate
#     000146 showTextbox Hey, there's a stone tablet.
#     000260 playSound 1800
#     000264 setObjVisibility 2 1
#     ... [textboxes about reading the tablet] ...
#     000460 showTextbox Let's take it.
#     000494 giveItem 118 1                       <-- PRIMARY
#     000498 if trigger(0) == false then 604      <-- skip retry on success
#     000510..000598 [retry path: "Oops, I have to throw something away" + cleanup]
#     000600 giveItem 118 1                       <-- RETRY
#     000604 playSound 1792
#     000610 showTextbox I got Leomon's Stone Tablet!
#     000676 setTrigger 135                       <-- AP location signal
#     000680 endSection
#
# Vanilla DW1 also gates ENTRY to this cave on Drimogemon's daily dig
# completing, which in turn requires the city's Prosperity to reach
# 45. AP fill models this via a ``_pp(45)`` rule in
# ``rules._set_keyitem_pickup_rules``.
#
# Three ROM copies of Script 109 in the .bin (verified by scanning
# for the 4-byte signature ``28 00 76 01``: 7 hits in the script
# range, 3 of which are primaries with the expected
# ``if trigger(0) == false then 604`` conditional following, 4 are
# retries with the expected ``setDialogOwner 255 + showTextbox "I got
# Leomon's Stone Tablet!"`` pattern. The 4th retry has no matching
# primary 106 bytes earlier — it's a separate cutscene fragment in
# the same script with a slightly different lead-in. Patching all 7
# sites is safe since the substitution (setTrigger 135) is
# idempotent everywhere it's applied.
#
# Script 109 base offsets:
#   Copy 1: 0x14030028
#   Copy 2: 0x14030504
#   Copy 3: 0x140309DE

ROM_LEOMONSTONE_GIVEITEM_OFFSETS: Final = (
    0x14030216,  # Copy 1 primary  (script-offset 494 = 0x1EE)
    0x14030280,  # Copy 1 retry    (script-offset 600 = 0x258)
    0x140306F2,  # Copy 2 primary
    0x1403075C,  # Copy 2 retry
    0x14030BCC,  # Copy 3 primary
    0x14030C36,  # Copy 3 retry
    0x140316F6,  # Orphan retry — different cutscene fragment in Script 109
)
# Replacement: ``setTrigger 135`` (opcode 0x1C, sub 0x00, trigger ID 135 LE).
ROM_LEOMONSTONE_GIVEITEM_NEUTER_VALUE: Final = bytes((
    VENDING_OPCODE_SETTRIGGER, 0x00,
    LEOMONSTONE_LOCATION_TRIGGER_ID & 0xFF,
    (LEOMONSTONE_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))


# =============================================================================
# Arena cup giveItem neuter (always-on, opt-in for the moment via empty
# Section_51 base table -- see ROM_ARENA_SECTION_51_BASES below).
# =============================================================================
#
# Patch 14 ``giveItem`` call sites in Script 214 Section_51 -- 2 per
# grade tier (primary prize delivery + inventory-full bank fallback)
# plus 4 extras for Grade S's 3 random prize sub-branches. Each site
# becomes ``setTrigger N`` where N is the cup's allocated trigger
# (885..889; see ``ARENA_CUP_*_TRIGGER_ID`` near the top of this file
# for the trigger -> tier mapping).
#
# Pattern matches the existing key-item neuters
# (``_write_leomonstone_neuter_tokens`` etc.): 4-byte in-place opcode
# swap, idempotent.
#
# Script-relative offsets per cup-tier come from
# ``references/digimon_world_randomizer/script/DW1Script.txt`` (Script
# ID 214 § Section_51, ``pstat(3) == 0..4`` dispatch chain).

# (trigger_id, script_relative_offset) per patch site. The .bin offset
# is computed at patch time as ``base + offset`` for each ROM copy in
# :data:`ROM_ARENA_SECTION_51_BASES`.
ARENA_CUP_PATCH_SITES: Final[tuple[tuple[int, int], ...]] = (
    # Grade D (trigger 885, prize Double Floppy / item 7)
    (ARENA_CUP_GRADE_D_TRIGGER_ID,  476),  # primary
    (ARENA_CUP_GRADE_D_TRIGGER_ID,  554),  # inv-overflow bank fallback
    # Grade C (trigger 886, prize Three Sirloins / item 40 x 3)
    (ARENA_CUP_GRADE_C_TRIGGER_ID,  742),
    (ARENA_CUP_GRADE_C_TRIGGER_ID,  820),
    # Grade B (trigger 887, prize Restore Floppy / item 11)
    (ARENA_CUP_GRADE_B_TRIGGER_ID, 1006),
    (ARENA_CUP_GRADE_B_TRIGGER_ID, 1084),
    # Grade A (trigger 888, prize Flaming Mane / item 80)
    (ARENA_CUP_GRADE_A_TRIGGER_ID, 1378),
    (ARENA_CUP_GRADE_A_TRIGGER_ID, 1456),
    # Grade S (trigger 889, 3 random prize sub-branches). The 304-byte
    # offset shift between FB-primary (2008) and FB-bank (2390 instead
    # of the disassembly's 2086) reflects an extra block of bytecode
    # present in the USA SLUS-01032 build but absent from the
    # randomizer's reference disassembly. Verified empirically against
    # `Digimon World (USA).bin` 2026-05-26.
    (ARENA_CUP_GRADE_S_TRIGGER_ID, 1748),  # Metal Part primary
    (ARENA_CUP_GRADE_S_TRIGGER_ID, 1826),  # Metal Part bank
    (ARENA_CUP_GRADE_S_TRIGGER_ID, 2008),  # Fatal Bone primary
    (ARENA_CUP_GRADE_S_TRIGGER_ID, 2390),  # Fatal Bone bank
    (ARENA_CUP_GRADE_S_TRIGGER_ID, 2568),  # Mega Hand primary
    (ARENA_CUP_GRADE_S_TRIGGER_ID, 2646),  # Mega Hand bank
)
assert len(ARENA_CUP_PATCH_SITES) == 14

# ROM copies of Script 214's Section_51 base offset in the .bin.
# Populate by running:
#
#     python -m worlds.digimon_world.tools.dw1_scan_arena_script PATH/TO/DW1.BIN
#
# The scanner verifies each candidate by reproducing all 14 patch sites
# from a single base; only confirmed bases are reported. DW1 sometimes
# carries multiple ROM copies of a single script (vending has 2 of
# most); paste every confirmed base here.
#
# Section_51's .bin offset is NOT computable from the disassembly
# anchor 0xb6800 alone -- it depends on where the script pack lands in
# the BIN's sector layout. The scan is the canonical source of truth.
#
# When this tuple is empty the patcher skips arena patching (the
# Section_51 giveItem opcodes stay vanilla and cup wins never fire AP
# locations); ``test_arena_cup_locations`` still validates the
# Python-side wiring.
ROM_ARENA_SECTION_51_BASES: Final[tuple[int, ...]] = (
    0x140A6DF8,  # SLUS-01032 USA build; verified by tools/dw1_scan_arena_script.py 2026-05-26
)

# Replacement bytecode for each cup tier: ``setTrigger N`` = 4 bytes
# ``(0x1C, 0x00, N_low, N_high)``. Same encoding as the key-item
# neuters above.
ARENA_CUP_NEUTER_VALUES: Final[dict[int, bytes]] = {
    trigger_id: bytes((
        VENDING_OPCODE_SETTRIGGER, 0x00,
        trigger_id & 0xFF,
        (trigger_id >> 8) & 0xFF,
    ))
    for trigger_id in (
        ARENA_CUP_GRADE_D_TRIGGER_ID,
        ARENA_CUP_GRADE_C_TRIGGER_ID,
        ARENA_CUP_GRADE_B_TRIGGER_ID,
        ARENA_CUP_GRADE_A_TRIGGER_ID,
        ARENA_CUP_GRADE_S_TRIGGER_ID,
    )
}
assert all(len(v) == 4 for v in ARENA_CUP_NEUTER_VALUES.values())


# =============================================================================
# Great Canyon cutscene-disable patch (Great Canyon Bridge SHUFFLED mode)
# =============================================================================
#
# Great Canyon's bridge-fix cutscene script (Script ID 36, script-offset
# 614) gates on:
#
#     if trigger(103) == true OR trigger(124) == false then 846
#
# Where 124 is the "6 prosperity reached" prereq. In shuffled mode we
# need the cutscene to never fire (otherwise reaching 6 PP organically
# would set bit 103 without AP delivery, bypassing the gate). The patch
# replaces the second trigger ID with 103, making the gate
#
#     if trigger(103) == true OR trigger(103) == false then 846
#
# i.e. always-true → always jumpTo 846 → cutscene skipped unconditionally.
# The bridge can only be fixed via AP item delivery (client pins bit 103).
#
# Two BIN copies of the script; both trigger-ID bytes patched. Patch
# is emitted only when ``options.great_canyon_unlock == shuffled``.

#
# IF-block byte layout (verified in vanilla BIN 2026-05-10):
#
#   off  bytes  meaning
#   +0   ?? ??  cond1 trigger ID (u16 LE) — vanilla 67 00 = trigger 103
#   +2   ?? ??  cond1 opcode             — vanilla 80 00 (first-position OR)
#   +4   ?? ??  cond2 trigger ID (u16 LE) — vanilla 7c 00 = trigger 124  ← patch target
#   +6   ?? ??  cond2 opcode             — vanilla 18 00 (second-position OR)
#   +8   ?? ??  jumpTo target (u16 LE)   — vanilla 4e 03 = offset 846 (endSection)
#   +10  19 00  jumpTo opcode
#
# The earlier +8 offset overwrote the jumpTo target (turned 846 → 103),
# making the IF jump into the middle of the spawnItem init code in
# Section_254 whenever its condition was met. After AP delivered the
# bridge item the script jumped to garbage instead of skipping the
# cutscene cleanly, leaving the bridge unusable. Verified by decoding
# vanilla vs patched output 2026-05-10.

ROM_GREAT_CANYON_CUTSCENE_OFFSETS: Final = (
    0x13FF8766,  # Copy 1: 0x13FF8762 + 4 (cond2 trigger ID byte position)
    0x13FF8AB8,  # Copy 2: 0x13FF8AB4 + 4
)
ROM_GREAT_CANYON_CUTSCENE_VALUE: Final = bytes((0x67, 0x00))  # trigger 103 LE

# Sections 51/52/53 of Script 36 (= GCAN01, the bridge approach screen)
# each start with ``if trigger(124) == true then <skip-danger>``. If
# the IF fails, the section plays the "Oh no, it's dangerous!" anim
# and forcibly walks the player back to a safe spot before falling
# through to the cutscene gate at offset 614. Trigger 124 is NOT "6 PP
# reached" — it's set by the in-town "Invisible Bridge rumor" NPC
# (script offset 003026 elsewhere, gated on ``pstat(1) >= 6``). So in
# vanilla the player needs both 6 PP AND that NPC dialog before the
# bridge is approachable. In shuffled mode the AP rules
# (:func:`worlds.digimon_world.rules._set_entrance_rules`) gate the
# Tropical Jungle → Great Canyon entrance on ``Has("Great Canyon Bridge")``
# alone — so the in-game gate must follow. Rewriting the cond1 trigger
# ID byte (+0 from IF base) from 124 → 103 makes the AP item the only
# gate. 3 sections × 2 BIN copies = 6 patch sites.
ROM_GREAT_CANYON_APPROACH_GATE_OFFSETS: Final = (
    0x13FF865E,  # Copy 1 Section_51 (script offset 354)
    0x13FF86B4,  # Copy 1 Section_52 (script offset 440)
    0x13FF870A,  # Copy 1 Section_53 (script offset 526)
    0x13FF89B0,  # Copy 2 Section_51
    0x13FF8A06,  # Copy 2 Section_52
    0x13FF8A5C,  # Copy 2 Section_53
)
ROM_GREAT_CANYON_APPROACH_GATE_VALUE: Final = bytes((0x67, 0x00))  # trigger 103 LE


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

AP_ITEM_NAME: Final = b"AP Item"  # 7 bytes, padded to 20 with NULs

# Slot 83 is the universal "AP Item" — both the chest pickup sentinel
# AND the merit shop's AP-purchase row. Sharing one slot means both
# contexts always read the same name. ``meritValue = 300`` puts the
# row in the merit shop (any non-zero value would; 300 is a sensible
# in-game cost). Other stats (sortingValue, value, itemColor,
# dropable, unk) stay zero — they don't affect the chest sentinel
# (chestGiveItem wrapper short-circuits on slot 83 before any of
# those are read) and don't matter for the merit shop's row render.
#
# Field layout (matches dw1.hpp Item struct):
#   bytes  0..19: name (ASCII, NUL-padded)
#   bytes 20..23: value (i32, money price)
#   bytes 24..25: meritValue (i16) ← buyable price for the AP Item row
#   bytes 26..27: sortingValue (i16)
#   byte  28:     itemColor (u8)
#   byte  29:     dropable  (u8)
#   bytes 30..31: unk (u16)
AP_ITEM_MERIT_PRICE: Final = 300

ROM_AP_ITEM_ENTRY_BYTES: Final = (
    AP_ITEM_NAME.ljust(20, b"\x00")
    + b"\x00\x00\x00\x00"                                          # value = 0
    + AP_ITEM_MERIT_PRICE.to_bytes(2, "little", signed=True)       # meritValue
    + b"\x00" * 6                                                  # sortingValue + itemColor + dropable + unk
)
assert len(ROM_AP_ITEM_ENTRY_BYTES) == ROM_ITEM_TABLE_ENTRY_SIZE, len(ROM_AP_ITEM_ENTRY_BYTES)


def _flat_to_user_data(base: int, table_byte_offset: int) -> int:
    """Translate a table-internal byte offset to a sector-aware flat BIN offset.

    Mode2/2352 sector geometry interleaves 24-byte sector headers and
    280-byte EDC/ECC blocks with 2048-byte user-data regions. A flat
    ``base + offset`` walk past one user-data region steps into the
    next sector's EC zone instead of the next sector's user data.

    This helper computes "the byte position N user-data-bytes into the
    stream that begins at ``base``", correctly hopping the EC blocks.
    Caller passes the table's flat-BIN base; ``table_byte_offset`` is
    the user-data byte offset within the table.
    """

    base_sector = base // SECTOR_SIZE_BYTES
    base_pos_in_sector = base - base_sector * SECTOR_SIZE_BYTES
    base_pos_in_user_data = base_pos_in_sector - SECTOR_HEADER_BYTES
    pos = base_pos_in_user_data + table_byte_offset
    sector_advance, pos_within = divmod(pos, USER_DATA_BYTES)
    sector = base_sector + sector_advance
    return sector * SECTOR_SIZE_BYTES + SECTOR_HEADER_BYTES + pos_within


def _table_byte_to_bin_flat(table_byte_offset: int) -> int:
    """Backwards-compat shim — ITEM_PARA-specific sector-hop helper."""

    return _flat_to_user_data(ROM_ITEM_TABLE_BASE, table_byte_offset)


def _decompose_kuseg(addr: int) -> tuple[int, int]:
    """Return ``(lui_hi, addiu_lo)`` such that
    ``lui rN, lui_hi; addiu rN, rN, addiu_lo`` constructs ``addr``.

    The ``addiu`` immediate is sign-extended from 16 bits before being
    added. When ``addr & 0xFFFF`` is >= 0x8000 the sign extension makes
    it negative, so we have to increment the ``lui`` high half by 1 to
    compensate. Standard MIPS toolchain idiom; encoded here so wrapper
    builders can target arbitrary kuseg addresses (including the
    relocated ITEM_PARA at 0x8009DBC8, whose low half 0xDBC8 has bit 15
    set and would otherwise be encoded wrong).
    """

    lo = addr & 0xFFFF
    hi = (addr >> 16) & 0xFFFF
    if lo >= 0x8000:
        hi = (hi + 1) & 0xFFFF
    return hi, lo


def read_user_data_bytes(rom: bytes, base_bin_offset: int, length: int) -> bytes:
    """Read ``length`` bytes of pure user data starting at ``base_bin_offset``.

    Sector-aware: hops Mode2/2352 EDC/ECC blocks via
    :func:`_flat_to_user_data`. ``length`` is measured in user-data
    bytes; the returned ``bytes`` is contiguous (no sector header /
    EC bytes interleaved).
    """

    out = bytearray(length)
    pos = 0
    while pos < length:
        flat = _flat_to_user_data(base_bin_offset, pos)
        sector_index = flat // SECTOR_SIZE_BYTES
        sector_user_end = (
            sector_index * SECTOR_SIZE_BYTES
            + SECTOR_SIZE_BYTES
            - SECTOR_EDC_ECC_BYTES
        )
        chunk = min(sector_user_end - flat, length - pos)
        out[pos:pos + chunk] = rom[flat:flat + chunk]
        pos += chunk
    return bytes(out)


def write_user_data_bytes(rom: bytearray, base_bin_offset: int, data: bytes) -> None:
    """Write ``data`` (pure user-data bytes) starting at ``base_bin_offset``.

    Sector-aware: hops Mode2/2352 EDC/ECC blocks. Mutates ``rom`` in
    place.
    """

    length = len(data)
    pos = 0
    while pos < length:
        flat = _flat_to_user_data(base_bin_offset, pos)
        sector_index = flat // SECTOR_SIZE_BYTES
        sector_user_end = (
            sector_index * SECTOR_SIZE_BYTES
            + SECTOR_SIZE_BYTES
            - SECTOR_EDC_ECC_BYTES
        )
        chunk = min(sector_user_end - flat, length - pos)
        rom[flat:flat + chunk] = data[pos:pos + chunk]
        pos += chunk


def _read_struct_block_user_data(rom: bytes, block: "StructBlock") -> bytes:
    """Extract a ``StructBlock``'s user-data records from a flat BIN.

    Reads ``count * record_size`` bytes of pure user data, hopping
    sector boundaries via :func:`_flat_to_user_data`. The result is a
    contiguous bytes view that can be unpacked with ``record_format``
    at ``i * record_size`` for record ``i``.
    """

    record_size = struct.calcsize(block.record_format)
    user_data_size = block.count * record_size
    out = bytearray(user_data_size)
    pos = 0
    while pos < user_data_size:
        flat = _flat_to_user_data(block.offset, pos)
        sector_index = flat // SECTOR_SIZE_BYTES
        sector_user_end = (
            sector_index * SECTOR_SIZE_BYTES
            + SECTOR_SIZE_BYTES
            - SECTOR_EDC_ECC_BYTES
        )
        chunk = min(sector_user_end - flat, user_data_size - pos)
        out[pos:pos + chunk] = rom[flat:flat + chunk]
        pos += chunk
    return bytes(out)


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


ROM_ITEM_TABLE_ENTRY_COUNT: Final = 0x80  # 128 records in ITEM_PARA

# RAM address where ITEM_PARA is loaded by the BIOS (per SydPatches'
# SLUS_labels.asm). The merit-shop wrapper writes to this RAM region
# at runtime to swap slot N's metadata with the "AP Item Bought"
# sentinel after a purchase. The ROM-side patches (above) only affect
# the disc image; the BIOS reloads the table from disc on each boot,
# so save/reload would revert any RAM-only changes — handled by a
# client-side ticker that pins the sentinel state when the
# corresponding trigger is set.
# Bare Nymashock MainRAM offset (no kuseg prefix), matching the
# convention of every other ``RAM_*`` constant. The wrapper builder
# (which encodes lui/addiu) ORs in the 0x80000000 prefix to recover
# the CPU-visible kuseg address.
RAM_ITEM_PARA: Final = 0x001269DC
RAM_ITEM_PARA_KUSEG: Final = 0x80000000 | RAM_ITEM_PARA


# --- ITEM_PARA 256-slot relocation — primary base (always-on) ---------------
# The full 256-slot ITEM_PARA table is relocated at boot onto the 8 KB
# region RAM 0x801BFB70..0x801C1B70 vacated from the malloc3 arena by a
# one-word heap claim (lab-validated 2026-08-20, three PATCH_PROCESS
# nets incl. a confirming disc boot; see
# ``work/dw1_re/decomp/item_para_reloc/NOTES.md``). All machinery —
# heap-claim word, boot seed hook, .bin-backed ext seed, 24 SLUS + 7
# overlay reader-site patches — lives in the "ITEM_PARA 256-slot
# relocation" section further down (it needs helpers defined later in
# this module). The base constants are declared early because the
# merit-shop wrapper builders below encode addresses inside the
# relocated table.
#
# The region is EXACTLY 256 x 32 B: slots 0..127 are a boot-time copy
# of vanilla-plus-tokens ITEM_PARA (apply_tokens keeps writing slots
# 83/114/117 at the OLD .bin location; the hook copies them over),
# slots 128..255 are the extended range (zeroed, then seeded from the
# .bin-backed ext seed block in Cave6).
ITEM_PARA_RELOC_SLOT_COUNT: Final = 256
ITEM_PARA_RELOC_BASE_KUSEG: Final = 0x801BFB70
# Bare MainRAM offset (no kuseg prefix) — client-side read convention.
ITEM_PARA_RELOC_BASE: Final = ITEM_PARA_RELOC_BASE_KUSEG & 0x001FFFFF
ITEM_PARA_RELOC_EXT_KUSEG: Final = (
    ITEM_PARA_RELOC_BASE_KUSEG + 128 * ROM_ITEM_TABLE_ENTRY_SIZE            # 0x801C0B70
)
ITEM_PARA_RELOC_END_KUSEG: Final = (
    ITEM_PARA_RELOC_BASE_KUSEG
    + ITEM_PARA_RELOC_SLOT_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE                # 0x801C1B70
)
assert ITEM_PARA_RELOC_EXT_KUSEG == 0x801C0B70, hex(ITEM_PARA_RELOC_EXT_KUSEG)
assert ITEM_PARA_RELOC_END_KUSEG == 0x801C1B70, hex(ITEM_PARA_RELOC_END_KUSEG)


# =============================================================================
# Merit-Shop AP "AP Item Bought" sentinel slot (always-on)
# =============================================================================
#
# To give the player a visual "you've already bought this AP location"
# indicator in the Merit Shop, we use a second ITEM_PARA sentinel slot
# (paralleling the existing chest sentinel at slot 83). The merit-shop
# wrapper, on a successful AP-tracked purchase, copies this 32-byte
# entry over the dispatched slot's entry in RAM. The shop's next
# render then displays the new name + price (= 0).
#
# Slot 114 (vanilla "Moon mirror") is documented as "reserved for
# future use" in :ref:`memory dw1_item_table_layout` — safe to
# repurpose here. Choosing 114 keeps the chest sentinel (slot 83)
# uncoupled from the merit-shop sentinel; a player could see both
# sentinel names in different contexts without confusion.
#
# **Pre-purchase rename of dispatched slots** — for each item in
# :data:`MERIT_SHOP_DISPATCH`, we ALSO patch the .bin's slot-N name
# field to "AP Item" (without zeroing the rest of the entry — vanilla
# meritValue and other fields stay). The shop's pre-purchase display
# becomes "AP Item — vanilla_price". After purchase the wrapper
# replaces slot-N entirely with slot 114's contents → "AP Item
# Bought — 0".

AP_SHOP_BOUGHT_SENTINEL_ITEM_ID: Final = 0x72  # 114 = vanilla "Moon mirror"
AP_SHOP_BOUGHT_NAME: Final = b"AP Item Bought"  # 14 bytes, padded to 20 with NULs

# Two sentinels — same name, different visibility:
#
# 1. **ROM sentinel** (:data:`ROM_AP_SHOP_BOUGHT_ENTRY_BYTES`): written
#    to slot 114 at gen time. ``meritValue == 0`` so the merit shop
#    filters it out — we replace the gamebreaking vanilla "Moon
#    mirror" without leaving a visible row.
# 2. **Visible sentinel** (:data:`AP_SHOP_BOUGHT_VISIBLE_BYTES`):
#    written *only* by the client-side reconciler to the *bought*
#    slot. ``meritValue == 0x7FFF`` so the shop renders the row but
#    the player can never afford it (vanilla merit cap is 9999).
#
# Two sentinels are needed because slot 114 (the ROM sentinel) is one
# of the merit shop's hardcoded inventory entries — making slot 114
# visible would make the source of the memcpy show up alongside any
# bought slot, displaying "AP Item Bought" twice. Keeping slot 114
# hidden and using a different visible sentinel for bought slots
# avoids the duplicate.
#
# Field layout (matches dw1.hpp Item struct):
#   bytes  0..19: name (ASCII, NUL-padded)
#   bytes 20..23: value (i32, money price — irrelevant for merit shop)
#   bytes 24..25: meritValue (i16)
#   bytes 26..27: sortingValue (i16)
#   byte  28:     itemColor (u8)
#   byte  29:     dropable  (u8)
#   bytes 30..31: unk (u16)
ROM_AP_SHOP_BOUGHT_ENTRY_BYTES: Final = (
    AP_SHOP_BOUGHT_NAME.ljust(20, b"\x00") + b"\x00" * 12
)
AP_SHOP_BOUGHT_VISIBLE_BYTES: Final = (
    AP_SHOP_BOUGHT_NAME.ljust(20, b"\x00")
    + b"\x00\x00\x00\x00"  # value = 0
    + b"\xFF\x7F"          # meritValue = 32767 (max int16, unaffordable but visible)
    + b"\x00" * 6          # sortingValue + itemColor + dropable + unk
)
assert len(AP_SHOP_BOUGHT_VISIBLE_BYTES) == 32, len(AP_SHOP_BOUGHT_VISIBLE_BYTES)

# --- Post-purchase visible-but-unbuyable meritValue --------------------
# After a merit-shop AP-Item purchase the client-side reconciler bumps
# *just* the meritValue field of the dispatched slot (offset 24-25
# within the 32-byte ITEM_PARA entry) to this value. The shop keeps
# rendering the row (because meritValue != 0), the player can navigate
# to it, but they can never afford it (vanilla merit cap is 9999).
# **Crucially the row's name is left untouched** — for slot 83 that
# means it stays "AP Item" everywhere, including chest pickup
# textboxes where slot 83 is the chest sentinel.
AP_ITEM_BOUGHT_MERIT_VALUE: Final = 0x7FFF  # max int16
AP_ITEM_BOUGHT_MERIT_VALUE_BYTES: Final = (
    AP_ITEM_BOUGHT_MERIT_VALUE.to_bytes(2, "little", signed=True)
)
ITEM_PARA_MERIT_VALUE_OFFSET: Final = 24  # bytes 24..25 of the 32-byte entry
assert len(ROM_AP_SHOP_BOUGHT_ENTRY_BYTES) == ROM_ITEM_TABLE_ENTRY_SIZE, (
    len(ROM_AP_SHOP_BOUGHT_ENTRY_BYTES)
)

ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET: Final = _table_byte_to_bin_flat(
    AP_SHOP_BOUGHT_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE,
)
# Sanity: 32-byte slot must not straddle a sector boundary.
_bought_entry_end = _table_byte_to_bin_flat(
    AP_SHOP_BOUGHT_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE
    + ROM_ITEM_TABLE_ENTRY_SIZE - 1,
)
assert (_bought_entry_end - ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET) == ROM_ITEM_TABLE_ENTRY_SIZE - 1, (
    f"slot 114 entry crosses a sector boundary: "
    f"start=0x{ROM_AP_SHOP_BOUGHT_ENTRY_OFFSET:08X}, end=0x{_bought_entry_end:08X}"
)

# RAM address of slot 114's entry (= source for the runtime memcpy).
# Bare Nymashock offset; the wrapper builder ORs in the kuseg prefix
# when emitting the lui/addiu pair.
AP_SHOP_BOUGHT_SENTINEL_RAM: Final = (
    RAM_ITEM_PARA + AP_SHOP_BOUGHT_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE
)
assert AP_SHOP_BOUGHT_SENTINEL_RAM == 0x0012781C

# Pre-purchase name "AP Item" written into each dispatched slot's name
# field at gen time. Just the name (20 bytes) — leaves the slot's
# original price/sort/etc. intact so the pre-purchase shop display is
# "AP Item — vanilla_price". Currently MERIT_SHOP_DISPATCH only
# contains slot 83, whose name is already "AP Item" via
# :data:`ROM_AP_ITEM_ENTRY_BYTES`, so this rewrite is idempotent for
# slot 83. Kept in place because future MERIT_SHOP_DISPATCH entries
# that target *real* item slots (which we don't want to fully
# overwrite) will need just the name override.
AP_SHOP_PRESALE_NAME: Final = b"AP Item"
ROM_AP_SHOP_PRESALE_NAME_BYTES: Final = AP_SHOP_PRESALE_NAME.ljust(20, b"\x00")
assert len(ROM_AP_SHOP_PRESALE_NAME_BYTES) == 20


# =============================================================================
# Hide vanilla Amazing Rod from the merit shop
# =============================================================================
#
# Vanilla DW1 sells Amazing Rod (slot 117) at the merit shop. With the
# AP Item now living at slot 83, we don't want vanilla Amazing Rod to
# also appear in the shop's row list. The merit shop's row scan
# (function 0x801072C4) walks ITEM_PARA and includes any entry whose
# ``meritValue > 0``. Zeroing slot 117's ``meritValue`` (i16 at
# entry-byte offset 24-25) removes it from the scan without disturbing
# any other field — so the rod's name, icon, description, and money
# ``value`` (used by the regular money shops, if any) all stay vanilla.

# Slot 117's meritValue field at sector-aware .bin offset.
ROM_AMAZING_ROD_HIDE_OFFSET: Final = _table_byte_to_bin_flat(
    117 * ROM_ITEM_TABLE_ENTRY_SIZE + 24,  # offset 24 = meritValue
)
ROM_AMAZING_ROD_HIDE_BYTES: Final = b"\x00\x00"  # meritValue = 0 (i16 LE)


def read_item_table_user_data(rom: bytes) -> bytes:
    """Extract ITEM_PARA's 4 KiB of user data from a flat BIN.

    Convenience wrapper around :func:`_read_struct_block_user_data`
    pinned to :data:`ROM_ITEM_DATA`.
    """

    return _read_struct_block_user_data(rom, ROM_ITEM_DATA)


def read_digimon_table_user_data(rom: bytes) -> bytes:
    """Extract DIGIMON_PARA's user-data records from a flat BIN.

    180 records of 52 bytes each = 9360 bytes. Caller unpacks per-record
    via ``ROM_DIGIMON_DATA.record_format``.
    """

    return _read_struct_block_user_data(rom, ROM_DIGIMON_DATA)


def read_technique_table_user_data(rom: bytes) -> bytes:
    """Extract TECH_PARA's user-data records from a flat BIN.

    121 records of 16 bytes each = 1936 bytes. Caller unpacks via
    ``ROM_TECHNIQUE_DATA.record_format``.
    """

    return _read_struct_block_user_data(rom, ROM_TECHNIQUE_DATA)

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
# Merit Shop give-item wrapper (always-on)
# =============================================================================
#
# The ShogunGekomon Merit Shop in Volume Villa is engine-driven (not
# script-bytecode driven), so we can't use the ``giveItem N → setTrigger N'``
# substitution that worked for the cutscene-style key items. The shop's
# give-item callsite was located by static RE: at .bin flat 0x14D48C04
# (RAM 0x8010BF3C, verified live 2026-05-09 via RAM dump signature scan
# in `worlds/digimon_world/tools/dw1_ram_dump.lua` and a 28-byte unique
# signature match) the merit-shop function does ``jal 0x800C5240`` (the
# vanilla give-item function) with $a0=item_id, $a1=count.
#
# We hijack that jal to point at our wrapper in SydPatches' Cave6 free
# space. The wrapper:
#
#   1. Saves $ra, $a0 (item_id), $a1 (count) to a temporary stack frame.
#   2. For each (item_id, trigger_id) in :data:`MERIT_SHOP_DISPATCH`:
#      compares $a0 to item_id; if equal, calls ``setTrigger(trigger_id)``
#      and restores $a0 from the saved slot afterward.
#   3. Restores $ra and $a1, tears down the frame, and tail-calls
#      vanilla give-item via ``j 0x800C5240`` (NOT jal — the inherited
#      $ra goes back to the merit-shop function, exactly as if the
#      wrapper weren't there).
#
# Per-item dispatch is **extensible**: append entries to
# :data:`MERIT_SHOP_DISPATCH` to wire other Merit-Shop items as AP
# locations. Each entry adds 6 instructions (24 bytes) to the wrapper.
# Cave6 has ~5012 bytes free after our existing wrappers, so all 12
# Merit-Shop items would fit (+288 bytes for 12 entries × 24).
#
# The wrapper sits at RAM 0x80095800 (.bin offset 0x14CC0C88 — sector
# hop required, see ROM_MERIT_SHOP_WRAPPER_OFFSET below), 64 bytes
# past the chest wrapper (28 B used at 0x800957C0) and the
# setTrigger wrapper (32 B at 0x800957DC). 4-byte aligned.
# Caller-saved convention: setTrigger may clobber $a0/$a1, so the
# wrapper saves both around the setTrigger call.

# Each entry = (item_id, trigger_id). The wrapper iterates these in
# order at the give-item callsite. If the in-game item ID matches an
# entry's item_id, the wrapper calls setTrigger(trigger_id) before
# the vanilla give-item runs. Add entries here to extend AP-location
# coverage to other Merit-Shop items.
MERIT_SHOP_DISPATCH: Final[tuple[tuple[int, int], ...]] = (
    # Slot 83 (universal "AP Item" sentinel — also the chest sentinel)
    # is the merit shop's AP-purchase row. Setting trigger 903 fires
    # the AP location ``Amazing Rod Pickup``. Uses slot 83 instead of
    # slot 117 (vanilla Amazing Rod) so the rod's ITEM_PARA entry stays
    # untouched (icon/name/desc preserved for fishing UI etc.). The
    # merit shop scans ITEM_PARA for entries with non-zero
    # ``meritValue``; slot 83 has ``meritValue = AP_ITEM_MERIT_PRICE``
    # (set in :data:`ROM_AP_ITEM_ENTRY_BYTES`), and slot 117 is hidden
    # by zeroing its meritValue (see :data:`ROM_AMAZING_ROD_HIDE_*`).
    (AP_CHEST_SENTINEL_ITEM_ID, AMAZING_ROD_LOCATION_TRIGGER_ID),
)

ROM_MERIT_SHOP_WRAPPER_RAM: Final = 0x80095800
# Bin offset must hop the Mode2/2352 sector boundary at RAM 0x80095800.
# RAM 0x800957C0..0x80095800 fits inside sector 148348's user data; RAM
# 0x80095800 is the first byte of sector 148349's user data. A flat
# ``chest_wrapper_offset + 0x40`` (= 0x14CC0B58) lands inside sector
# 148348's EDC region, which is *never* loaded into RAM as code — the
# wrapper bytes get written to disc but the CPU never executes them, so
# the merit shop's ``jal wrapper`` jumps to whatever uninitialized data
# happens to be at RAM 0x80095800 and the game freezes. The sector-hop
# helper computes the correct destination.
ROM_MERIT_SHOP_WRAPPER_OFFSET: Final = _flat_to_user_data(
    ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
    ROM_MERIT_SHOP_WRAPPER_RAM - ROM_CHEST_GIVEITEM_WRAPPER_RAM,
)
assert ROM_MERIT_SHOP_WRAPPER_OFFSET == 0x14CC0C88, hex(ROM_MERIT_SHOP_WRAPPER_OFFSET)


def _build_merit_shop_wrapper_bytes() -> bytes:
    """Build the merit-shop wrapper's MIPS bytecode from the
    :data:`MERIT_SHOP_DISPATCH` table.

    **Behavior:**

    * Item NOT in dispatch table → fall through to ``j giveItem`` →
      vanilla item delivery happens normally.
    * Item IS in dispatch table → ``setTrigger(trigger_id)`` fires
      (AP location signal) → 32-byte memcpy of slot 114
      ("AP Item Bought" sentinel) over the dispatched slot in RAM
      ITEM_PARA → ``jr $ra`` returns to caller WITHOUT delivering the
      item. After this, the shop's next render shows
      ``AP Item Bought — 0`` for that slot.

    Layout (N = ``len(MERIT_SHOP_DISPATCH)`` → 38 + 7N instructions):

        prologue (4 instrs, 16 B):
            addiu $sp, $sp, -0x10
            sw    $ra, 0x0C($sp)
            sw    $a0, 0x08($sp)
            sw    $a1, 0x04($sp)

        per-entry block (7 instrs, 28 B):
            addiu $at, $0, item_id
            bne   $a0, $at, +5     ; skip 5 instrs if no match
            nop                     ; bne delay slot
            jal   0x801065C0       ; setTrigger(trigger_id)
            addiu $a0, $0, trigger_id  ; jal delay slot
            j     mark_bought      ; on match: copy sentinel + return
            nop                     ; j delay slot

        give_item path (6 instrs, 24 B) — fall-through for unmatched:
            lw    $ra, 0x0C($sp)
            lw    $a0, 0x08($sp)
            lw    $a1, 0x04($sp)
            addiu $sp, $sp, 0x10
            j     0x800C5240       ; tail-call vanilla giveItem
            nop

        mark_bought path (28 instrs, 112 B) — match jumps here:
            lw    $a0, 0x08($sp)   ; restore item_id (clobbered by setTrigger)
            sll   $t2, $a0, 5      ; t2 = item_id * 32
            lui   $t1, 0x801C
            addiu $t1, $t1, 0xFB70 ; t1 = relocated ITEM_PARA base
            addu  $t2, $t2, $t1    ; t2 = RELOC + item_id*32 (dest)
            lui   $t0, 0x801C
            addiu $t0, $t0, 0x09B0 ; t0 = RELOC slot 114 sentinel (source)
            (8 × {lw $t3, +N($t0); sw $t3, +N($t2)}  for N in {0,4,8,...,28})
            lw    $ra, 0x0C($sp)
            lw    $a1, 0x04($sp)
            addiu $sp, $sp, 0x10
            jr    $ra              ; return without item delivery
            nop

    Calling convention: the wrapper preserves $ra/$a1. On the
    fall-through (no match) path it also restores $a0 before
    tail-calling giveItem. On the match path $a0 is restored from
    stack (since setTrigger clobbered it) so we can compute the
    destination ITEM_PARA slot.
    """

    import struct as _struct

    SETTRIGGER_RAM = 0x801065C0
    GIVEITEM_RAM = 0x800C5240
    # ITEM_PARA relocation (always-on): the shop UI reads the RELOCATED
    # table at ITEM_PARA_RELOC_BASE_KUSEG, so the sentinel memcpy must
    # target it — a write to the old table would be invisible. The
    # sentinel source is the relocated slot 114 (seeded at boot from
    # the token-written old-table entry).
    ITEM_PARA_BASE = ITEM_PARA_RELOC_BASE_KUSEG
    SENTINEL_RAM = (
        ITEM_PARA_RELOC_BASE_KUSEG
        + AP_SHOP_BOUGHT_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE       # 0x801C09B0
    )

    n_entries = len(MERIT_SHOP_DISPATCH)
    # mark_bought RAM address = wrapper start + prologue (16) + per-entry
    # blocks (28 * N) + give_item path (24).
    mark_bought_offset = 0x10 + 28 * n_entries + 0x18
    mark_bought_ram = ROM_MERIT_SHOP_WRAPPER_RAM + mark_bought_offset
    j_mark = 0x08000000 | ((mark_bought_ram >> 2) & 0x03FFFFFF)
    j_giveitem = 0x08000000 | ((GIVEITEM_RAM >> 2) & 0x03FFFFFF)
    jal_settrigger = 0x0C000000 | ((SETTRIGGER_RAM >> 2) & 0x03FFFFFF)

    # ITEM_PARA_BASE and SENTINEL_RAM are loaded via lui+addiu. We use
    # :func:`_decompose_kuseg` so the encoding works whether the low
    # half needs sign-extension (relocated base 0x801BFB70: lo 0xFB70
    # >= 0x8000 -> lui hi becomes 0x801C) or not (sentinel 0x801C09B0).
    item_para_hi, item_para_lo = _decompose_kuseg(ITEM_PARA_BASE)
    sentinel_hi, sentinel_lo = _decompose_kuseg(SENTINEL_RAM)

    out = bytearray()

    # --- Prologue -----------------------------------------------------------
    out += _struct.pack("<I", 0x27BDFFF0)  # addiu $sp, $sp, -0x10
    out += _struct.pack("<I", 0xAFBF000C)  # sw    $ra, 0x0C($sp)
    out += _struct.pack("<I", 0xAFA40008)  # sw    $a0, 0x08($sp)
    out += _struct.pack("<I", 0xAFA50004)  # sw    $a1, 0x04($sp)

    # --- Per-entry blocks ---------------------------------------------------
    # bne offset = 5: skip the next 5 instructions (= the 5 instructions
    # after the bne delay slot in this block, landing on the next block's
    # first instruction or the give_item path's first instruction).
    BNE_OFFSET_5 = 0x14810005
    for item_id, trigger_id in MERIT_SHOP_DISPATCH:
        if not (0 <= item_id <= 0xFF):
            raise ValueError(f"item_id {item_id} out of u8 range")
        if not (0 <= trigger_id <= 0xFFFF):
            raise ValueError(f"trigger_id {trigger_id} out of u16 range")
        # addiu $at, $0, item_id
        out += _struct.pack("<I", 0x24010000 | (item_id & 0xFFFF))
        # bne $a0, $at, +5  (no-match: jump to next block / give_item path)
        out += _struct.pack("<I", BNE_OFFSET_5)
        # nop (bne delay slot)
        out += _struct.pack("<I", 0x00000000)
        # jal setTrigger
        out += _struct.pack("<I", jal_settrigger)
        # addiu $a0, $0, trigger_id (jal delay slot)
        out += _struct.pack("<I", 0x24040000 | (trigger_id & 0xFFFF))
        # j mark_bought (match path: copy sentinel + return without giveItem)
        out += _struct.pack("<I", j_mark)
        # nop (j delay slot)
        out += _struct.pack("<I", 0x00000000)

    # --- give_item path (no-match fall-through) ----------------------------
    out += _struct.pack("<I", 0x8FBF000C)  # lw    $ra, 0x0C($sp)
    out += _struct.pack("<I", 0x8FA40008)  # lw    $a0, 0x08($sp)
    out += _struct.pack("<I", 0x8FA50004)  # lw    $a1, 0x04($sp)
    out += _struct.pack("<I", 0x27BD0010)  # addiu $sp, $sp, 0x10
    out += _struct.pack("<I", j_giveitem)  # j     0x800C5240
    out += _struct.pack("<I", 0x00000000)  # nop   (j delay slot)

    # --- mark_bought path (match jumps here) -------------------------------
    # Compute dest = ITEM_PARA + item_id * 32, then memcpy 32 bytes from
    # the AP-shop-bought sentinel into the dispatched slot. Returns
    # without calling vanilla giveItem.
    # (item_para_hi/lo and sentinel_hi/lo were computed above using
    # _decompose_kuseg so the addiu sign-extension is handled correctly.)

    # lw    $a0, 0x08($sp)        — restore item_id (clobbered by setTrigger).
    out += _struct.pack("<I", 0x8FA40008)
    # sll   $t2, $a0, 5            — t2 = item_id * 32 (= entry-byte offset).
    out += _struct.pack("<I", 0x00045140)
    # lui   $t1, item_para_hi      — t1 = ITEM_PARA_BASE upper half.
    out += _struct.pack("<I", 0x3C090000 | item_para_hi)
    # addiu $t1, $t1, item_para_lo — t1 = ITEM_PARA_BASE.
    out += _struct.pack("<I", 0x25290000 | item_para_lo)
    # addu  $t2, $t2, $t1          — t2 = dest = ITEM_PARA + item_id*32.
    out += _struct.pack("<I", 0x01495021)
    # lui   $t0, sentinel_hi       — t0 = SENTINEL_RAM upper half.
    out += _struct.pack("<I", 0x3C080000 | sentinel_hi)
    # addiu $t0, $t0, sentinel_lo  — t0 = source = AP_SHOP_BOUGHT_SENTINEL_RAM.
    out += _struct.pack("<I", 0x25080000 | sentinel_lo)
    # 8 × { lw $t3, +N($t0); sw $t3, +N($t2) }  for N in {0,4,...,28}.
    for off in (0, 4, 8, 12, 16, 20, 24, 28):
        # lw $t3, N($t0)  — opcode 0x23, rs=$t0(8), rt=$t3(11), imm=N
        out += _struct.pack("<I", 0x8D0B0000 | off)
        # sw $t3, N($t2)  — opcode 0x2B, rs=$t2(10), rt=$t3(11), imm=N
        out += _struct.pack("<I", 0xAD4B0000 | off)
    # lw    $ra, 0x0C($sp)
    out += _struct.pack("<I", 0x8FBF000C)
    # lw    $a1, 0x04($sp)
    out += _struct.pack("<I", 0x8FA50004)
    # addiu $sp, $sp, 0x10
    out += _struct.pack("<I", 0x27BD0010)
    # jr    $ra
    out += _struct.pack("<I", 0x03E00008)
    # addiu $v0, $0, 1  (jr delay slot — return success so the merit
    # shop continues normally instead of taking the "no inventory
    # space" failure branch on the AP-Item purchase. Mirrors the chest
    # wrapper's success return at the same shape; vanilla giveItem
    # returns 1 on success, and we want the shop to behave as if the
    # item was successfully delivered even though we deliberately
    # skipped the inventory write.)
    out += _struct.pack("<I", 0x24020001)

    return bytes(out)


ROM_MERIT_SHOP_WRAPPER_BYTES: Final = _build_merit_shop_wrapper_bytes()

# Sanity: 4 prologue + 6 give_item + 28 mark_bought + 7 per dispatch entry.
assert len(ROM_MERIT_SHOP_WRAPPER_BYTES) == (38 + 7 * len(MERIT_SHOP_DISPATCH)) * 4, (
    len(ROM_MERIT_SHOP_WRAPPER_BYTES), len(MERIT_SHOP_DISPATCH),
)


def _merit_shop_presale_name_offset(item_id: int) -> int:
    """Sector-aware .bin offset of slot ``item_id``'s name field within
    ITEM_PARA. Used by the patcher to rename each dispatched slot to
    ``"AP Item"`` at gen time so the pre-purchase shop display reads
    ``AP Item — vanilla_price`` instead of revealing the underlying
    DW1 item."""
    return _table_byte_to_bin_flat(item_id * ROM_ITEM_TABLE_ENTRY_SIZE)


# Patch site: replace the merit-shop function's ``jal 0x800C5240`` with
# ``jal ROM_MERIT_SHOP_WRAPPER_RAM``. Single 4-byte rewrite at the
# in-RAM RAM 0x8010BF3C (= .bin flat 0x14D48C04). The post-jal nop
# delay-slot at offset+4 stays as-is (vanilla nop, matches what we
# need).

ROM_MERIT_SHOP_PATCH_FORMAT: Final = "<I"
ROM_MERIT_SHOP_PATCH_OFFSET: Final = 0x14D48C04
ROM_MERIT_SHOP_PATCH_VALUE: Final = (
    0x0C000000 | ((ROM_MERIT_SHOP_WRAPPER_RAM >> 2) & 0x03FFFFFF)
)
assert ROM_MERIT_SHOP_PATCH_VALUE == 0x0C025600, hex(ROM_MERIT_SHOP_PATCH_VALUE)


# =============================================================================
# AP Item description + icon blank (always-on)
# =============================================================================
#
# DW1 displays an item's description from ``ITEM_DESC_PTR[item_id]`` (in
# the inventory and merit-shop hover panels). For our AP-Item slot
# (item 83 — was Electo Ring, now repurposed as the universal "AP
# Item" sentinel for both chests and the merit shop), the vanilla
# Electo Ring description doesn't fit. We replace it with a generic
# "Item from the multiworld" string allocated in Cave6 free space and
# redirect the ``ITEM_DESC_PTR[83]`` pointer to it.
#
# Similarly the merit shop (and inventory) renders item icons by
# looking up ``ITEM.TIM`` at ``(col=item_id%16, row=item_id/16)`` (per
# ``InventoryUI.cpp:setItemTexture``). For item 83 that's row 5,
# col 3 — Electo Ring's icon. We just zero out the 16x16 region in
# ITEM.TIM so the slot renders blank. Slot 83 is unused in normal
# play (Electo Ring is gamebreaking and unobtainable), so blanking
# its icon doesn't affect anything else.
#
# Slot 117 (Amazing Rod) stays completely untouched — its name,
# description, and icon all remain vanilla, so the fishing UI etc.
# render the rod normally.

# --- Description string + pointer redirect ---------------------------------
AP_ITEM_DESC_STRING: Final = b"Item from the multiworld\x00"  # 25 bytes incl NUL

# Stored in Cave6 free space, immediately after the merit shop wrapper.
# 4-byte aligned (wrapper size is a multiple of 4).
AP_ITEM_DESC_RAM: Final = (
    ROM_MERIT_SHOP_WRAPPER_RAM + len(ROM_MERIT_SHOP_WRAPPER_BYTES)
)
AP_ITEM_DESC_BIN_OFFSET: Final = _flat_to_user_data(
    ROM_CHEST_GIVEITEM_WRAPPER_OFFSET,
    AP_ITEM_DESC_RAM - ROM_CHEST_GIVEITEM_WRAPPER_RAM,
)

# ITEM_DESC_PTR is the 128-entry array of u32 pointers immediately
# after ITEM_PARA in RAM: ITEM_PARA spans 0x801269DC..0x801279DC
# (128 × 32 bytes), so ITEM_DESC_PTR starts at 0x801279DC. Entry 117's
# pointer lives at byte_offset_from_ITEM_PARA = 128*32 + 117*4 = 4564
# (= 0x11D4). We sector-translate via the same helper used for the
# chest sentinel slot rewrites.
AP_ITEM_DESC_PTR_INDEX: Final = 83
AP_ITEM_DESC_PTR_BIN_OFFSET: Final = _table_byte_to_bin_flat(
    128 * ROM_ITEM_TABLE_ENTRY_SIZE + AP_ITEM_DESC_PTR_INDEX * 4,
)
# CPU sees ITEM_DESC_PTR entries as kuseg addresses, so OR in the prefix.
AP_ITEM_DESC_PTR_VALUE: Final = 0x80000000 | AP_ITEM_DESC_RAM
ROM_AP_ITEM_DESC_PTR_PATCH_FORMAT: Final = "<I"

# --- ITEM.TIM: AP logo icon for slot 83 -------------------------------------
#
# The item-icon TIM exists TWICE on the disc, byte-identical in vanilla
# (verified 2026-08-21; every patch below must hit both copies):
#
# * the standalone file ``DIGIMON/ETCDAT/ITEM.TIM`` at LBA 7470
#   (data start = ``LBA * 2352 + 24`` = bin offset 0x010C16B8);
# * a copy embedded inside ``DIGIMON/ETCDAT/ETCTIM.BIN`` (the boot-time
#   UI texture bundle, LBA 7376) at file offset 74592 (bin offset
#   0x010A0538, mid-sector). **This embedded copy is the one the game
#   actually uploads to VRAM** — live evidence 2026-08-21: with only
#   the standalone file patched, a patched-ISO boot still rendered the
#   vanilla Electo Ring icon for slot 83 while the SLUS-side
#   ITEM_CLUT_DATA redirect was verifiably active in RAM, and the
#   vanilla tile bytes existed on disc only in ETCTIM.BIN. (This also
#   means the pre-logo "icon blanking" of the standalone file alone
#   never actually showed in-game.)
#
# TIM layout (both copies; verified against the canonical dump):
#
# * TIM header, 8 bytes: magic ``0x10``, flags ``0x08`` (4bpp + CLUT).
# * CLUT block, 780 bytes: 12-byte block header (u32 length=780,
#   DX=224, DY=488, W=16, H=24) + 24 CLUTs x 16 colors x 2 bytes.
#   Colors are PSX 15-bit (bits 0-4 R, 5-9 G, 10-14 B, bit 15 STP);
#   raw 0x0000 renders fully transparent. The block is uploaded to
#   VRAM at (224, 488), one CLUT per VRAM row.
# * Pixel block: 12-byte header, then 4bpp pixel data at TIM file
#   offset 800 — a 256x128 texture (16 cols x 8 rows of 16x16 icons),
#   128 bytes per scanline, LOW nibble = LEFT pixel. Item N's icon is
#   the 16x16 block at (col*16, row*16), col = N%16, row = N/16.
#
# Icon rendering (``InventoryUI.cpp:setItemTexture`` in
# references/DW1-SydPatches): UV from (col, row) as above; the CLUT is
# ``getClut(0xE0, ITEM_CLUT_DATA[item_id] + 0x1E8)`` — i.e. the
# per-item byte table ``ITEM_CLUT_DATA`` (see further below, after
# ``_slus_ram_to_bin_offset`` is available) selects one of the 24 CLUT
# rows. Because the icon clamp wrapper rewrites ``item_id`` to 83
# *before* the function body runs, extended AP slots (128+) use both
# slot 83's tile AND slot 83's CLUT.
#
# Slot 83 (vanilla Electo Ring, unobtainable, repurposed as the "AP
# Item" sentinel) used to get its tile blanked here. It now gets a
# 16x16 Archipelago logo instead: six colored circles in the AP hex
# ring. Vanilla CLUT 16 (Electo Ring's palette, shared with 5 other
# items) is a monochrome gold ramp, so the logo also needs a palette:
# CLUT 22's sole consumer is item 84 (Rainbowhorn), so the patcher
# moves Rainbowhorn to CLUT 8 (requantizing its pixels at apply time —
# see :meth:`worlds.digimon_world.rom.DigimonWorldPatchExtension.requantize_rainbowhorn`),
# rewrites CLUT 22 with the AP palette below, and repoints
# ``ITEM_CLUT_DATA[83]`` from 16 to 22.

ITEM_TIM_LBA: Final = 7470
ETCTIM_BIN_LBA: Final = 7376
ITEM_TIM_IN_ETCTIM_FILE_OFFSET: Final = 74592
ITEM_TIM_SIZE_BYTES: Final = 17184
ITEM_TIM_PIXEL_DATA_FILE_OFFSET: Final = 800
ITEM_TIM_CLUT_DATA_FILE_OFFSET: Final = 8 + 12  # TIM header + CLUT block header
ITEM_TIM_CLUT_COUNT: Final = 24
ITEM_TIM_CLUT_SIZE_BYTES: Final = 32  # 16 colors x u16

# Flat .bin offset of TIM file byte 0, for each on-disc copy. Order:
# standalone ITEM.TIM first, embedded ETCTIM.BIN copy second.
ITEM_TIM_COPY_BASE_BIN_OFFSETS: Final = (
    ITEM_TIM_LBA * SECTOR_SIZE_BYTES + SECTOR_HEADER_BYTES,
    _flat_to_user_data(
        ETCTIM_BIN_LBA * SECTOR_SIZE_BYTES + SECTOR_HEADER_BYTES,
        ITEM_TIM_IN_ETCTIM_FILE_OFFSET,
    ),
)
assert ITEM_TIM_COPY_BASE_BIN_OFFSETS == (0x010C16B8, 0x010A0538)

AP_ITEM_ICON_INDEX: Final = 83


def item_tim_tile_row_bin_offsets(slot: int) -> tuple[tuple[int, ...], ...]:
    """Per-copy tuples of the 16 per-row .bin offsets for item ``slot``.

    Each icon row is 8 bytes (16 px x 4bpp) at TIM file offset
    ``PIXEL_DATA_OFFSET + (row*16 + r) * 128 + col * 8``. Offsets are
    sector-aware (:func:`_flat_to_user_data` hops the Mode2/2352 EC
    blocks); an assert below guarantees no 8-byte row write straddles a
    sector's user-data window in either copy.
    """

    col, row = slot % 16, slot // 16
    return tuple(
        tuple(
            _flat_to_user_data(
                base,
                ITEM_TIM_PIXEL_DATA_FILE_OFFSET + (row * 16 + r) * 128 + col * 8,
            )
            for r in range(16)
        )
        for base in ITEM_TIM_COPY_BASE_BIN_OFFSETS
    )


def item_tim_clut_bin_offsets(clut_index: int) -> tuple[int, ...]:
    """Per-copy flat .bin offsets of CLUT ``clut_index``'s 32 color bytes."""

    assert 0 <= clut_index < ITEM_TIM_CLUT_COUNT, clut_index
    return tuple(
        _flat_to_user_data(
            base,
            ITEM_TIM_CLUT_DATA_FILE_OFFSET + clut_index * ITEM_TIM_CLUT_SIZE_BYTES,
        )
        for base in ITEM_TIM_COPY_BASE_BIN_OFFSETS
    )


AP_ITEM_ICON_TILE_BIN_OFFSETS: Final = item_tim_tile_row_bin_offsets(
    AP_ITEM_ICON_INDEX,
)
assert len(AP_ITEM_ICON_TILE_BIN_OFFSETS) == 2
assert all(len(rows) == 16 for rows in AP_ITEM_ICON_TILE_BIN_OFFSETS)

# CLUT geometry facts the patcher relies on:
AP_ICON_CLUT_INDEX: Final = 22          # rewritten with the AP palette
RAINBOWHORN_ITEM_ID: Final = 84         # CLUT 22's only vanilla consumer
RAINBOWHORN_NEW_CLUT_INDEX: Final = 8   # requantization target palette

AP_ICON_CLUT_BIN_OFFSETS: Final = item_tim_clut_bin_offsets(AP_ICON_CLUT_INDEX)

RAINBOWHORN_TILE_BIN_OFFSETS: Final = item_tim_tile_row_bin_offsets(
    RAINBOWHORN_ITEM_ID,
)

# No CLUT write (32 B) or tile-row write (8 B) may straddle a sector's
# 2048-byte user-data window, in either copy.
for _clut_index in range(ITEM_TIM_CLUT_COUNT):
    for _off in item_tim_clut_bin_offsets(_clut_index):
        assert (
            SECTOR_HEADER_BYTES
            <= _off % SECTOR_SIZE_BYTES
            <= SECTOR_HEADER_BYTES + USER_DATA_BYTES - ITEM_TIM_CLUT_SIZE_BYTES
        ), hex(_off)
for _rows in (*AP_ITEM_ICON_TILE_BIN_OFFSETS, *RAINBOWHORN_TILE_BIN_OFFSETS):
    for _off in _rows:
        assert (
            SECTOR_HEADER_BYTES
            <= _off % SECTOR_SIZE_BYTES
            <= SECTOR_HEADER_BYTES + USER_DATA_BYTES - 8
        ), hex(_off)
del _clut_index, _rows, _off

# --- The AP logo art --------------------------------------------------------
# Original pixel art (not derived from game assets): six circles on the
# Archipelago hex ring, clockwise from the top: red, orange, yellow,
# green, blue, purple. Each circle is ~5 px with a lower-right shade arc
# and a 1-px white highlight; circles keep >= 1 px of transparent
# spacing so they read at 16x16. Palette channels are multiples of 8
# (exact 15-bit fit; PSX drops the low 3 bits of each channel).

AP_LOGO_PALETTE: Final[tuple[tuple[int, int, int], ...]] = (
    (0, 0, 0),        # 0: transparent (raw 0x0000)
    (16, 16, 24),     # 1: near-black (spare — outlines if ever needed)
    (216, 40, 40),    # 2: red
    (136, 16, 24),    # 3: red shade
    (240, 128, 32),   # 4: orange
    (168, 80, 16),    # 5: orange shade
    (248, 216, 48),   # 6: yellow
    (184, 152, 24),   # 7: yellow shade
    (64, 168, 64),    # 8: green
    (24, 112, 40),    # 9: green shade
    (56, 120, 224),   # 10: blue
    (24, 72, 160),    # 11: blue shade
    (152, 88, 200),   # 12: purple
    (104, 48, 144),   # 13: purple shade
    (240, 240, 240),  # 14: white highlight
    (64, 64, 72),     # 15: grey (spare)
)
assert len(AP_LOGO_PALETTE) == 16
assert AP_LOGO_PALETTE[0] == (0, 0, 0)  # index 0 must stay transparent
assert all(
    0 <= chan <= 255 and chan % 8 == 0
    for color in AP_LOGO_PALETTE for chan in color
)


def _pack_clut15(palette: tuple[tuple[int, int, int], ...]) -> bytes:
    """Pack RGB888 triples into the 32-byte PSX 15-bit CLUT format."""

    out = bytearray()
    for r, g, b in palette:
        out += struct.pack("<H", (r >> 3) | ((g >> 3) << 5) | ((b >> 3) << 10))
    return bytes(out)


AP_LOGO_CLUT_BYTES: Final = _pack_clut15(AP_LOGO_PALETTE)
assert len(AP_LOGO_CLUT_BYTES) == ITEM_TIM_CLUT_SIZE_BYTES

# 16x16 indexed art: one hex digit per pixel (palette index), '.' = 0
# (transparent). Layout: circle centers on a radius-5.3 hex ring around
# (7.5, 7.5), circle radius 2.3.
AP_LOGO_PIXEL_ROWS: Final[tuple[str, ...]] = (
    ".......22.......",
    "......2e22......",
    "......2223......",
    "..ccc.2233.444..",
    ".ceccc.33.4e444.",
    ".ccccd....44445.",
    ".cccd......4455.",
    "...d........5...",
    "...a........6...",
    ".aeaa......e666.",
    ".aaaab....66667.",
    ".aaabb.88.66677.",
    "..abb.8e88.677..",
    "......8889......",
    "......8899......",
    ".......99.......",
)
assert len(AP_LOGO_PIXEL_ROWS) == 16
assert all(len(row) == 16 for row in AP_LOGO_PIXEL_ROWS)


def _pack_tile_rows(rows: tuple[str, ...]) -> tuple[bytes, ...]:
    """Pack indexed pixel-art rows into 4bpp bytes (low nibble = left)."""

    out: list[bytes] = []
    for row in rows:
        indices = [0 if ch == "." else int(ch, 16) for ch in row]
        out.append(bytes(
            indices[i] | (indices[i + 1] << 4) for i in range(0, 16, 2)
        ))
    return tuple(out)


AP_LOGO_TILE_ROW_BYTES: Final = _pack_tile_rows(AP_LOGO_PIXEL_ROWS)
assert len(AP_LOGO_TILE_ROW_BYTES) == 16
assert all(len(row) == 8 for row in AP_LOGO_TILE_ROW_BYTES)


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
# * :data:`AP_RECRUIT_ITEM_DIGIMON` — the 48-element ordered tuple of
#   Digimon names that ship as "<X> Recruit" AP items (everyone except
#   Agumon and Digitamamon). Used by the item table builder and the
#   client's deliverer route registration.
#
# Agumon is excluded because he's the bank NPC (force-recruited by the
# client). Digitamamon is excluded because he's a post-game optional
# goal — accessible only after defeating the final boss + reload —
# and is intentionally not an AP location, so no AP item corresponds.

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

# Coelamon's vanilla recruit-block bit (trigger 249). Pinned to 1 each
# tick by the client (see :meth:`DigimonWorldClient._enforce_coelamon_beaten`)
# so every remaining vanilla reader of bit 249 — the Script 211 hint
# NPC ("An old-timer in the river...") and any engine-side
# recruit-block reads (File City Item Shop "is built" state, Andromon's
# chain per :func:`rules._andromon_extra`) — sees Coelamon as
# recruited, exactly as before the 2026-08-22 restoration.
#
# The pin is SAFE to keep because the shore state machine (Script 6,
# the recruit cutscene + ferry) no longer reads bit 249 at all: the
# always-on cutscene remap (``ROM_COELAMON_CUTSCENE_REMAP_*``) moves
# every Script-6 reference to trigger 779, the AP location signal.
# Pin-immunity was live-verified 2026-08-22 (recruit cutscene fires
# with 249 pre-set; see work/dw1_re/decomp/_coelamon_recruit/NOTES.md).
COELAMON_RECRUIT_BIT: Final[tuple[int, int]] = RECRUIT_RAM_BITS["Coelamon"]

# AP-item Digimon = every recruit *except* Agumon (force-recruited bank
# NPC), Digitamamon (post-game optional goal, not an AP location), and
# the dropped recruits below.
#
# **Dropped 2026-05-08**: Airdramon is excluded from the AP pool because
# its only recruit-bit set site is the endgame Analogman/Mt. Infinity
# cutscene (Script 184 ``setTrigger 207``) — there is no in-town fight
# or chained quest that would make a useful AP location. The name stays
# in :data:`RECRUIT_RAM_BITS` (it's part of the vanilla recruit
# bit-block) but is filtered out everywhere AP cares: no
# ``Airdramon Recruit`` item, no AP location at the cutscene, no bit
# poll in :data:`LOCATION_RAM_BITS`. Airdramon's bytecode reads of
# ``trigger(207)`` are NOT in the visibility-patch tables below — vanilla
# logic stays untouched, so Airdramon appears in town iff vanilla DW1
# would show him.
_AP_RECRUIT_EXCLUDED: Final = frozenset({
    "Agumon", "Digitamamon", "Airdramon",
    # Seadramon: dropped 2026-05-09 — Seadramon doesn't really do
    # anything in town, and his "recruit" cutscene is the same in-game
    # event as obtaining the Blue Flute. Per user direction, the
    # AP-recruit reward goes away; the cutscene fires the new
    # ``Blue Flute Pickup`` keyitem AP location instead (polls the
    # same trigger 210 bit). See addresses.py
    # ``BLUE_FLUTE_LOCATION_BIT``.
    "Seadramon",
    # 2026-05-09 — Phase-7 recruit-bundling rework:
    # Nanimon — per the recruitment guide, Nanimon drops keychains but
    # doesn't actually appear as a city NPC ("doesn't actually join
    # the city"). No AP location, no AP item, no city-visibility bit
    # tracking.
    "Nanimon",
    # Giromon — his in-town effect creates a Jukebox in the Restaurant
    # which **crashes the NTSC (US) build** per the recruitment guide.
    # Effectively non-functional in our target build, so dropping
    # both the AP location and the AP item.
    "Giromon",
    # Coelamon was dropped here 2026-05-24 ("recruit cutscene bugged")
    # and RESTORED 2026-08-22: the bug was the era's global setTrigger
    # wrapper swallowing the cutscene's ``setTrigger 249`` (vanilla
    # guard bit stayed clear -> the positional cutscene looped). The
    # wrapper is long retired; the restored design gives the shore
    # state machine its own AP trigger 779 via the always-on
    # ``ROM_COELAMON_CUTSCENE_REMAP_*`` patch. Coelamon is a BUNDLED
    # recruit (city visibility rides Progressive Item Shop T1; no
    # standalone ``Coelamon Recruit`` item) with an AP location polled
    # at :data:`COELAMON_RECRUIT_LOCATION_BIT` — NOT at his vanilla
    # recruit bit, which the client pins (see
    # :data:`COELAMON_RECRUIT_BIT`).
})
AP_RECRUIT_ITEM_DIGIMON: Final[tuple[str, ...]] = tuple(
    name for name in RECRUIT_RAM_BITS if name not in _AP_RECRUIT_EXCLUDED
)
assert len(AP_RECRUIT_ITEM_DIGIMON) == 44, len(AP_RECRUIT_ITEM_DIGIMON)


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


# ----- Screen ID → MAP filename ---------------------------------------------
#
# DW1 stores each screen's ``.MAP`` filename (10 ASCII bytes) at the start of
# every record in the ``MAP_ENTRIES[255]`` table at RAM ``0x801292D4`` (struct
# layout: ``uint8_t filename[10]; int8_t num8bppImages; int8_t num4bppImages;
# uint8_t flags; uint8_t doorsId; uint8_t toiletId; uint8_t loadingName;``,
# 16 bytes per record — see ``references/DW1-SydPatches/src/extern/dw1.hpp:914``).
#
# These filenames are the **absolute ground truth** for what area each screen
# is — superseding both DWAP's hand-maintained name list (which has stale or
# missing entries — e.g. screen 21 = MIHA03 = Mt. Panorama is labeled
# "Unused, Unknown" by DWAP) and script-text dialog inference (which can
# match across copy-pasted dialogs).
#
# Captured from a live BizHawk RAM dump 2026-05-09 (any save state with the
# table populated; the data never changes between BINs of vanilla USA
# SLUS-01032). Entries 239..246 + 250..252 are blanked (no map at that
# screen ID — likely cut content / placeholders).
#
# **Prefix decode** (Japanese romaji unless noted):
#   * ``MAYO`` — Native Forest (Mayoi no Mori = "forest of wandering")
#   * ``TROP`` — Tropical Jungle
#   * ``MIHA`` — Mt. Panorama (Miharashi-yama = "lookout mountain")
#   * ``TUNN`` — Drill / Meramon Tunnel / Lava Cave
#   * ``GCAN`` — Great Canyon
#   * ``OGRE`` — Ogre Fortress + Secret Beach Cave (the Ogremon files are
#     reused for the secret cave despite the cave being a separate area)
#   * ``YAKA`` — Grey Lord's Mansion (Yakata = "mansion")
#   * ``OMOC`` — Toy Town / Toy Mansion (Omocha = "toy")
#   * ``FACT`` — Factorial Town
#   * ``GOMI`` — Trash Mountain (Gomi = "trash")
#   * ``KODA`` — Ancient Speedy Region (Kodai = "ancient")
#   * ``FRZL`` — Freezeland
#   * ``ICSA`` — Ice Sanctuary
#   * ``BETL`` — Beetle Land
#   * ``LEOM`` — Leomon's Ancestor Cave / Native Forest sub-area
#   * ``MIST`` — Misty Trees
#   * ``GIAS`` — Gear Savanna (Giasabanna)
#   * ``GKYO`` — Geko Swamp
#   * ``TWNA`` / ``TWNB`` — File City Top / Bottom (Town A / Town B)
#   * ``MGEN`` — Mt. Infinity + Back Dimension (Mugen = "infinity"; Back
#     Dimension reuses Mt. Infinity-style maps as MGEN11..MGEN16)
#   * ``ROOM`` — generic interiors (Jijimon's House variants, shops,
#     clinic, restaurant). Notably:
#       - screen 205 = ``ROOM10`` = Jijimon's House Expanded Model
#       - screen 218 = ``ROOM08`` = Jijimon's House Base Model
#       - screen 211 = ``ROOM02`` = Item Keeper
#       - screen 213 = ``ROOM04`` = Centar Clinic
#   * ``TEND`` / ``TOPN`` — Final / Initial cutscene rooms
#   * ``STIC``, ``CHKA``, ``SAIB``, ``TRAI``, ``DGHA`` — minor sub-areas,
#     prefix meaning not yet decoded.

SCREEN_FILENAMES: Final[dict[int, str]] = {
    0: "MAYO01",   1: "MAYO02",   2: "MAYO03",   3: "MAYO04A",  4: "MAYO04B",
    5: "MAYO05",   6: "MAYO06",   7: "MAYO11",   8: "MAYO10",   9: "MAYO08A",
    10: "MAYO08B", 11: "TROP00",  12: "TROP01",  13: "TROP02",  14: "TROP03",
    15: "TROP04",  16: "TROP05",  17: "TROP06",  18: "MIHA00",  19: "MIHA01",
    20: "MIHA02",  21: "MIHA03",  22: "MIHA04A", 23: "MIHA04B", 24: "TUNN01",
    25: "TUNN02",  26: "TUNN03",  27: "TUNN04",  28: "TUNN05",  29: "TUNN06",
    30: "TUNN07",  31: "TUNN08",  32: "TUNN09",  33: "TUNN10",  34: "DGHA01",
    35: "DGHA02",  36: "GCAN01",  37: "GCAN02",  38: "GCAN03",  39: "GCAN04",
    40: "GCAN05",  41: "GCAN06",  42: "GCAN07",  43: "GCAN08_1",44: "GCAN09",
    45: "OGRE00",  46: "OGRE01",  47: "OGRE02",  48: "OGRE03",  49: "GCAN11",
    50: "YAKA01",  51: "YAKA02",  52: "YAKA11A", 53: "YAKA11B", 54: "YAKA12",
    55: "YAKA13",  56: "YAKA14",  57: "YAKA15",  58: "YAKA16",  59: "YAKA17",
    60: "YAKA18",  61: "YAKA21",  62: "YAKA22",  63: "YAKA23",  64: "YAKA24",
    65: "YAKA25",  66: "CHKA01",  67: "SAIB01",  68: "SAIB02",  69: "GIAS00",
    70: "GIAS01",  71: "GIAS02",  72: "GIAS03",  73: "GIAS04",  74: "GIAS05",
    75: "GIAS06A", 76: "GIAS07",  77: "GIAS08",  78: "GIAS09",  79: "KODA00",
    80: "KODA01",  81: "KODA02",  82: "KODA03",  83: "KODA04",  84: "KODA05",
    85: "KODA06",  86: "KODA07",  87: "KODA08",  88: "FRZL01",  89: "FRZL02",
    90: "FRZL03",  91: "FRZL04",  92: "FRZL05",  93: "FRZL06",  94: "FRZL07",
    95: "FRZL08",  96: "FRZL12",  97: "ICSA01",  98: "ICSA02",  99: "ICSA03",
    100: "ICSA04", 101: "ICSA05", 102: "ICSA06", 103: "ICSA07", 104: "ICSA08",
    105: "BETL01", 106: "BETL02", 107: "BETL03", 108: "BETL04", 109: "MAYO00",
    110: "MAYO01_2", 111: "MAYO02_2", 112: "TRAI00", 113: "LEOM01", 114: "LEOM02",
    115: "MIST01", 116: "MIST02", 117: "MIST03", 118: "MIST04", 119: "MIST05",
    120: "MIST06", 121: "MIST07", 122: "TUNN07_2", 123: "TUNN07_3", 124: "TUNN08_2",
    125: "TUNN08_3", 126: "TUNN03_2", 127: "GCAN04_2", 128: "GCAN08_2",
    129: "GCAN10", 130: "OGRE04", 131: "GIAS06B", 132: "FRZL13", 133: "FRZL14",
    134: "FRZL15", 135: "FRZL16", 136: "FRZL17", 137: "FRZL18", 138: "STIC01",
    139: "STIC02", 140: "GKYO01", 141: "GKYO02", 142: "OGRE10", 143: "OGRE11",
    144: "OMOC01", 145: "OMOC02", 146: "OMOC03", 147: "OMOC04", 148: "OMOC05",
    149: "OMOC06", 150: "OMOC07", 151: "OMOC08", 152: "FACT01", 153: "FACT02",
    154: "FACT03", 155: "FACT04", 156: "FACT05", 157: "FACT06", 158: "FACT07",
    159: "FACT08A", 160: "FACT08B", 161: "FACT09", 162: "FACT10", 163: "FACT11A",
    164: "GOMI01", 165: "GOMI02", 166: "MGEN01", 167: "MGEN02", 168: "TWNA02",
    169: "TWNA03", 170: "TWNA04", 171: "TWNA05", 172: "TWNA06", 173: "TWNA07",
    174: "TWNA08", 175: "TWNA09", 176: "TWNA10", 177: "TWNA11", 178: "TWNA12",
    179: "TWNA13", 180: "TWNB01", 181: "TWNB02", 182: "TWNB03", 183: "TWNB04",
    184: "TWNB05", 185: "TWNB06", 186: "TWNB07", 187: "TWNB08", 188: "TWNB09",
    189: "TWNB10", 190: "TWNB11", 191: "TWNB12", 192: "TWNB13", 193: "TWNB14",
    194: "TWNB15", 195: "TWNB16", 196: "TWNB17", 197: "TWNB18", 198: "TWNB19",
    199: "TWNB20", 200: "TWNB21", 201: "TWNB22", 202: "TWNB23", 203: "TWNB24",
    204: "TWNA01", 205: "ROOM10", 206: "ROOM11", 207: "ROOM12", 208: "ROOM13",
    209: "ROOM14", 210: "MGEN03", 211: "ROOM02", 212: "MGEN04", 213: "ROOM04",
    214: "ROOM05A", 215: "ROOM05B", 216: "ROOM06", 217: "ROOM07", 218: "ROOM08",
    219: "MGEN05", 220: "FACT11B", 221: "SAIB03", 222: "MGEN98", 223: "ROOM19",
    224: "YAKA26", 225: "MGEN99", 226: "MGEN11", 227: "MGEN12", 228: "MGEN13",
    229: "MGEN14", 230: "MGEN15", 231: "MGEN16", 232: "YAKA25", 233: "MIHA05",
    234: "MIHA06", 235: "ROOM20", 236: "TEND01", 237: "TEND02", 238: "TOPN01",
    247: "MGEN06", 248: "MGEN07", 249: "MGEN08", 253: "MGEN09", 254: "MGEN10",
}
# Sanity check: every chest screen and every Jijimon's House variant the
# AP world cares about must be in the table.
assert 205 in SCREEN_FILENAMES and SCREEN_FILENAMES[205] == "ROOM10"
assert 218 in SCREEN_FILENAMES and SCREEN_FILENAMES[218] == "ROOM08"


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
# Each entry: (BIN offset of trigger-ID bytes, original ID, redirected ID).
# Original = 200+X (vanilla "X recruited" gate). Redirected = 720+X
# (= our beaten-block bit, set only when AP delivers ``<X> Recruit``).
# After patching: city-visibility scripts read bit 720+X, so the city
# only shows X after AP delivery — independent of cutscene completion.
#
# All offsets verified against the source BIN: each starts with the
# original trigger ID (LE 2 bytes) followed by ``18 00`` opcode bytes.
# Pattern source: ``Section_X`` of various scripts, where the script
# binds the recruit dialog (``setScript dialog X``) then gates the
# load via ``if trigger(200+id) == TRUE then SKIP loadDigimon model``.
ROM_FIELD_SPAWN_TRIGGER_PATCHES: Final = (
    # ====================================================================
    # info.txt MUST-CHANGE — 298 entries across 37 recruits.
    # Wild-spawn / cutscene / story-flow gates (info.txt NO TOUCH list)
    # are NEVER patched — those would softlock recruits with chained
    # quest progression. See memory dw1_wild_spawn_gates_no_patch.md.
    # ====================================================================
    # ----- Betamon (21 sites) -----
    (0x13FD893A, 204, 724),  # 09918   Spawn shop
    (0x13FD8A4A, 204, 724),  # 10190   Spawn shop
    (0x13FE503A, 204, 724),  # 02974   Spawn shop
    (0x13FE581A, 204, 724),  # 00590   Spawn shop
    (0x1402BBE6, 204, 724),  # 01338   Spawn shop
    (0x14059A40, 204, 724),  # 01172   Spawn shop
    (0x1405C40A, 204, 724),  # 00110   Spawn some objects?
    (0x1405C6A2, 204, 724),  # 00774   More shop stuff
    (0x1405CA20, 204, 724),  # 01668   Coelamon intro check
    (0x1405CB42, 204, 724),  # 01958   Coelamon + Betamon intro together
    (0x1405CD5C, 204, 724),  # 02192   Set shop items buyable
    (0x1405E044, 204, 724),  # 06416   Coelamon intro check
    (0x1405E222, 204, 724),  # 06902   Betamon intro
    (0x1405E344, 204, 724),  # 07192   Coelamon + Betamon intro together
    (0x1405E420, 204, 724),  # 07412   Set shop items buyable
    (0x1405E9B0, 204, 724),  # 00340   Spawn shop
    (0x14063CE2, 204, 724),  # 02518   Spawn shop
    (0x1406AB0A, 204, 724),  # 02494   Spawn shop
    (0x1406BC52, 204, 724),  # 02214   Spawn shop
    (0x1406D050, 204, 724),  # 02628   Spawn shop
    (0x1406D7E6, 204, 724),  # 00170   Spawn shop
    # ----- Devimon (6 sites) -----
    (0x13FD9634, 206, 726),  # 12632   Devimon intro
    (0x13FD9718, 206, 726),  # 12860   Devimon hangin out
    (0x13FE44A2, 206, 726),  # 00310   Spawn secret shop
    (0x1406D75C, 206, 726),  # 00032   Spawn secret shop
    (0x1406FE82, 206, 726),  # 02694   Devimon shop intro
    (0x140701D2, 206, 726),  # 03542   Devimon shop intro
    # ----- Tyrannomon (9 sites) -----
    (0x13FD8FF6, 208, 728),  # _214    11338   Tyrannomon intro
    (0x13FD9120, 208, 728),  # _214    11636   Tyrannomon hangin out
    (0x13FD9198, 208, 728),  # _215    11756   Tyrannomon intro
    (0x13FD92C2, 208, 728),  # _215    12056   Tyrannomon hangin out
    (0x1406B3DE, 208, 728),  # _254    00354   Tyrannomon intro as chef
    (0x1406B784, 208, 728),  # _254    01288   Tyrannomon intro as chef alternate
    (0x1406C646, 208, 728),  # _81     00362   Tyrannomon intro as chef
    (0x1406C9E6, 208, 728),  # _81     01290   Tyrannomon intro as chef alternate
    (0x140AD37A, 208, 728),  # _51     00110   Restaurant dialog
    # ----- Meramon (42 sites) -----
    (0x140BA15A, 209, 729),  # _214    11310   Meramon intro
    (0x140BA288, 209, 729),  # _214    11612   Meramon hangin out
    (0x13FD917C, 209, 729),  # _215    11728   Meramon intro
    (0x13FD92AA, 209, 729),  # _215    12030   Meramon hangin out
    (0x13FE5056, 209, 729),  # _52     03002   Show restaurant
    (0x13FE513A, 209, 729),  # _52     03230   Show restaurant
    (0x13FE521E, 209, 729),  # _52     03458   Show restaurant
    (0x13FE5836, 209, 729),  # _52     00618   Show restaurant
    (0x13FE591A, 209, 729),  # _52     00846   Show restaurant
    (0x13FE59FE, 209, 729),  # _52     01074   Show restaurant
    (0x13FE5D4E, 209, 729),  # _51     01366   Show restaurant
    (0x1402BC02, 209, 729),  # _51     01594   Show restaurant
    (0x1402BCE6, 209, 729),  # _51     01822   Show restaurant
    (0x1402BDCA, 209, 729),  # _81     00390   Show restaurant
    (0x1402C5CA, 209, 729),  # _254    00756   Show restaurant
    (0x1402C6AE, 209, 729),  # _51     01200   Show restaurant
    (0x1402C792, 209, 729),  # _51     01428   Show restaurant
    (0x14051FC2, 209, 729),  # _51     01656   Show restaurant
    (0x14052186, 209, 729),  # _254    00534   Show restaurant
    (0x140598A0, 209, 729),  # _51     00368   Show restaurant
    (0x14059A5C, 209, 729),  # _51     00596   Show restaurant
    (0x14059B40, 209, 729),  # _51     00824   Show restaurant
    (0x14059C24, 209, 729),  # _52     02546   Show restaurant
    (0x1405BFAA, 209, 729),  # _52     02774   Show restaurant
    (0x1405C166, 209, 729),  # _52     03002   Show restaurant
    (0x1405C24A, 209, 729),  # _51     02522   Show restaurant
    (0x1405C5B2, 209, 729),  # _51     02750   Show restaurant
    (0x1405E9CC, 209, 729),  # _51     02978   Show restaurant
    (0x1406B2B2, 209, 729),  # _81     00054   Meramon intro as chef
    (0x1406B6C2, 209, 729),  # _81     01094   Meramon intro as chef alternate
    (0x1405EAB0, 209, 729),  # _51     02242   Show restaurant
    (0x1405EB94, 209, 729),  # _51     02470   Show restaurant
    (0x140608AC, 209, 729),  # _51     02698   Show restaurant
    (0x1406C516, 209, 729),  # _81     00058   Meramon intro as chef
    (0x1406C910, 209, 729),  # _81     01076   Meramon intro as chef alternate
    (0x14060990, 209, 729),  # _51     02656   Show restaurant
    (0x14060A74, 209, 729),  # _51     02884   Show restaurant
    (0x14063CFE, 209, 729),  # _51     03114   Show restaurant
    (0x14063DE2, 209, 729),  # _51     00198   Show restaurant
    (0x14063EC6, 209, 729),  # _51     00426   Show restaurant
    (0x1406AB26, 209, 729),  # _51     00654   Show restaurant
    (0x140AD31A, 209, 729),  # _51     00014   Restaurant dialog
    # ----- Numemon (6 sites) -----
    (0x13FD95E0, 211, 731),  # 12548   Numemon intro
    (0x13FD96D0, 211, 731),  # 12788   Numemon hangin out
    (0x13FE44A6, 211, 731),  # 00310   Spawn secret shop       19000000CE004000D3004000FC00
    (0x1406D760, 211, 731),  # 00032   Spawn secret shop       19000000CE004000D3004000D500
    (0x1406FC62, 211, 731),  # 02150   Numemon intro
    (0x1406FFC8, 211, 731),  # 03020   Numemon intro
    # ----- Mamemon (6 sites) -----
    (0x13FD9618, 213, 733),  # 12604   Mamemon intro
    (0x13FD9700, 213, 733),  # 12836   Mamemon hangin out
    (0x13FE44AE, 213, 733),  # 00310   Spawn secret shop
    (0x1406D764, 213, 733),  # 00032   Spawn secret shop
    (0x1406FDDC, 213, 733),  # 02528   Mamemon shop intro
    (0x1407012E, 213, 733),  # 03378   Mamemon shop intro
    # ----- Gabumon (3 sites) -----
    (0x13FD8F0C, 217, 737),  # 11104   Gabumon at treasure hunt
    (0x140672CE, 217, 737),  # 02210   Gabumon treasure hunt results
    (0x14067588, 217, 737),  # 02908   Gabumon treasure hunt results
    # ----- Elecmon (8 sites) -----
    (0x13FD89F0, 218, 738),  # _192    10096   Elecmon intro
    (0x13FD8C72, 218, 738),  # _192    10438   Show elecmon hanging out
    (0x1405997A, 218, 738),  # _162    00974   Show objects (lights?)
    (0x1405C4E6, 218, 738),  # _163    00330   some other object shared with shellmon
    (0x1405C556, 218, 738),  # _163    00442   more objects (night only)
    (0x1405C56A, 218, 738),  # _163    00462   more objects
    (0x1405C596, 218, 738),  # _163    00506   more objetcs (night only)
    (0x1405C5E2, 218, 738),  # _163    00582   more objects
    # ----- Kabuterimon (7 sites) -----
    (0x13FD7A70, 219, 739),  # 06436   Kabuterimon hangin out
    (0x1402DBAC, 219, 739),  # 00064   Revised HP training sign
    (0x1402DE34, 219, 739),  # 00712   Revised MP training sign
    (0x1402E090, 219, 739),  # 01316   Revised OFF training sign
    (0x1402E308, 219, 739),  # 01948   Revised DEF training sign
    (0x1402E6BE, 219, 739),  # 02594   Revised SPD training sign
    (0x1402E900, 219, 739),  # 03172   Revised BRN training sign
    # ----- Garurumon (9 sites) -----
    (0x13FD9012, 222, 742),  # _214    11366   Garurumon intro
    (0x13FD9138, 222, 742),  # _214    11660   Garurumon hangin out
    (0x13FD91B4, 222, 742),  # _215    11784   Garurumon intro
    (0x13FD92DA, 222, 742),  # _215    12078   Garurumon hangin out
    (0x1406B4DA, 222, 742),  # _81     00606   Garurumon intro as chef
    (0x1406B880, 222, 742),  # _81     01540   Garurumon intro as chef alternate
    (0x1406C742, 222, 742),  # _81     00614   Garurumon intro as chef
    (0x1406CADA, 222, 742),  # _81     01534   Garurumon intro as chef alternate
    (0x140AD3C6, 222, 742),  # _51     00186   Restaurant dialog
    # ----- Frigimon (9 sites) -----
    (0x13FD902E, 223, 743),  # _214    11394   Frigimon intro
    (0x13FD9150, 223, 743),  # _214    11684   Frigimon hangin out
    (0x13FD91D0, 223, 743),  # _215    11812   Frigimon intro
    (0x13FD92F2, 223, 743),  # _215    12102   Frigimon hangin out
    (0x1406B5E0, 223, 743),  # _81     00868   Frigimon intro as chef
    (0x1406B99A, 223, 743),  # _81     01822   Frigimon intro as chef alternate
    (0x1406C844, 223, 743),  # _81     00872   Frigimon intro as chef
    (0x1406CC16, 223, 743),  # _81     01850   Frigimon intro as chef alternate
    (0x140AEEAA, 223, 743),  # _51     00014   Restaurant dialog
    # ----- Whamon (3 sites) -----
    (0x13FD86FC, 224, 744),  # 09344   Whamon hangin out
    (0x1405986C, 224, 744),  # 00704   Whamon's dock?
    (0x1405B1FE, 224, 744),  # 06338   Whamon service
    # ----- MetalMamemon (1 sites) -----
    (0x13FD9982, 227, 747),  # 13478   MetalMamemon hangin out in curling
    # ----- Vademon (3 sites) -----
    (0x13FD904E, 228, 748),  # 11426   20% chance Vademon shows up in top (new house)
    (0x13FD91F0, 228, 748),  # 11844   20% chance Vademon shows up in top (new house + palm
    (0x140AEEEA, 228, 748),  # 00078   Restaurant dialog
    # ----- Patamon (23 sites) -----
    (0x13FD8946, 231, 751),  # 09930   Spawn shop
    (0x13FD8A56, 231, 751),  # 10202   Spawn shop
    (0x13FD8FA2, 231, 751),  # 11254   Spawn shop
    (0x13FD931E, 231, 751),  # 12146   In the item shop
    (0x13FD9560, 231, 751),  # 12420   In the item shop
    (0x13FE5016, 231, 751),  # 02938   Spawn shop
    (0x13FE57F6, 231, 751),  # 00554   Spawn shop
    (0x1402BBC2, 231, 751),  # 01302   Spawn shop
    (0x140598D8, 231, 751),  # 00812   Spawn shop
    (0x14059A1C, 231, 751),  # 01136   Spawn shop
    (0x1405C3EA, 231, 751),  # 00078   Spawn shop
    (0x1405C6B0, 231, 751),  # 00788   Spawn shop
    (0x1405C972, 231, 751),  # 01494   Spawn shop
    (0x1405E98C, 231, 751),  # 00304   Spawn shop
    (0x14063CBE, 231, 751),  # 02482   Spawn shop
    (0x1406AAE6, 231, 751),  # 02458   Spawn shop
    (0x1406BC2E, 231, 751),  # 02178   Spawn shop
    (0x1406D02C, 231, 751),  # 02592   Spawn shop
    (0x1406D7C2, 231, 751),  # 00134   Spawn shop
    (0x1406DADE, 231, 751),  # 00930   Patamon intro (makes the shop)
    (0x1406E176, 231, 751),  # 02314   Patamon intro (joins the shop)
    (0x1407056C, 231, 751),  # 00064   Spawn shop
    (0x14072670, 231, 751),  # 07604   Spawn shop
    # ----- Kunemon (8 sites) -----
    (0x13FD89B2, 232, 752),  # 10034   Kunemon hangin out
    (0x13FD8CAE, 232, 752),  # 10498   Kunemon intro
    (0x13FE438C, 232, 752),  # 00032   Remove wall at digimon bridge?
    (0x13FE43B0, 232, 752),  # 00068   Other objects?
    (0x13FE55F0, 232, 752),  # 00036   More objects
    (0x13FE5614, 232, 752),  # 00072   More objects
    (0x1405C50E, 232, 752),  # 00370   More objects
    (0x1405E4C6, 232, 752),  # 07578   Warp between bridge and file city
    # ----- Unimon (23 sites) -----
    (0x13FD894E, 233, 753),  # 09930   Spawn shop
    (0x13FD8A5E, 233, 753),  # 10202   Spawn shop
    (0x13FD8FAA, 233, 753),  # 11254   Spawn shop
    (0x13FD9356, 233, 753),  # 12202   In the item shop
    (0x13FD9590, 233, 753),  # 12468   In the item shop
    (0x13FE501E, 233, 753),  # 02938   Spawn shop
    (0x13FE57FE, 233, 753),  # 00554   Spawn shop
    (0x1402BBCA, 233, 753),  # 01302   Spawn shop
    (0x140598E0, 233, 753),  # 00812   Spawn shop
    (0x14059A24, 233, 753),  # 01136   Spawn shop
    (0x1405C3F2, 233, 753),  # 00078   Spawn shop
    (0x1405C6B8, 233, 753),  # 00788   Spawn shop
    (0x1405C97A, 233, 753),  # 01494   Spawn shop
    (0x1405E994, 233, 753),  # 00304   Spawn shop
    (0x14063CC6, 233, 753),  # 02482   Spawn shop
    (0x1406AAEE, 233, 753),  # 02458   Spawn shop
    (0x1406BC36, 233, 753),  # 02178   Spawn shop
    (0x1406D034, 233, 753),  # 02592   Spawn shop
    (0x1406D7CA, 233, 753),  # 00134   Spawn shop
    (0x1406DDC2, 233, 753),  # 01670   Unimon intro (makes the shop)
    (0x1406E30A, 233, 753),  # 02718   Unimon intro (joins the shop)
    (0x14070574, 233, 753),  # 00064   Spawn shop
    (0x14072678, 233, 753),  # 07604   Spawn shop
    # ----- Ogremon (1 sites) -----
    (0x13FD8BD2, 234, 754),  # 10278   Ogremon chillin
    # ----- Shellmon (6 sites) -----
    (0x13FD898A, 235, 755),  # 09994   Shellmon hangin out
    (0x13FD8BBE, 235, 755),  # 10254   Shellmon intro
    (0x13FD8BF6, 235, 755),  # 10314   Shellmon intro
    (0x1405C496, 235, 755),  # 00250   Show objects
    (0x1405C4EA, 235, 755),  # 00330   Show objects
    (0x1405E4A4, 235, 755),  # 07544   Shellmon news stuff
    # ----- Bakemon (2 sites) -----
    (0x13FD8970, 237, 757),  # 09968   Bakemon intro
    (0x13FD8C4A, 237, 757),  # 10398   Bakemon chillin
    # ----- Drimogemon (2 sites) -----
    (0x14059854, 238, 758),  # 00680   Show some objects
    (0x1405B1E4, 238, 758),  # 06312   Treasure cave
    # ----- Sukamon (1 sites) -----
    (0x13FD87F6, 239, 759),  # 140B9976  09594   Sukamon hangin out
    # ----- Andromon (1 sites) -----
    (0x13FD8780, 240, 760),  # 09476   Andromon chillin
    # ----- Giromon (1 sites) -----
    (0x1405E514, 241, 761),  # 07656   Spawn jukebox
    # ----- Etemon (1 sites) -----
    (0x13FD63CA, 242, 762),  # 01550   Etemon hangin out
    # ----- Biyomon (23 sites) -----
    (0x13FD894A, 245, 765),  # 09930   Spawn shop
    (0x13FD8A5A, 245, 765),  # 10202   Spawn shop
    (0x13FD8FA6, 245, 765),  # 11254   Spawn shop
    (0x13FD933A, 245, 765),  # 12174   In the item shop
    (0x13FD9578, 245, 765),  # 12444   In the item shop
    (0x13FE501A, 245, 765),  # 02938   Spawn shop
    (0x13FE57FA, 245, 765),  # 00554   Spawn shop
    (0x1402BBC6, 245, 765),  # 01302   Spawn shop
    (0x140598DC, 245, 765),  # 00812   Spawn shop
    (0x14059A20, 245, 765),  # 01136   Spawn shop
    (0x1405C3EE, 245, 765),  # 00078   Spawn shop
    (0x1405C6B4, 245, 765),  # 00788   Spawn shop
    (0x1405C976, 245, 765),  # 01494   Spawn shop
    (0x1405E990, 245, 765),  # 00304   Spawn shop
    (0x14063CC2, 245, 765),  # 02482   Spawn shop
    (0x1406AAEA, 245, 765),  # 02458   Spawn shop
    (0x1406BC32, 245, 765),  # 02178   Spawn shop
    (0x1406D030, 245, 765),  # 02592   Spawn shop
    (0x1406D7C6, 245, 765),  # 00134   Spawn shop
    (0x1406DC52, 245, 765),  # 01302   Biyomon intro (makes the shop)
    (0x1406E240, 245, 765),  # 02516   Biyomon intro (joins the shop)
    (0x14070570, 245, 765),  # 00064   Spawn shop
    (0x14072674, 245, 765),  # 07604   Spawn shop
    # ----- Monochromon (23 sites) -----
    (0x13FD8952, 247, 767),  # 09930   Spawn shop
    (0x13FD8A62, 247, 767),  # 10202   Spawn shop
    (0x13FD8FAE, 247, 767),  # 11254   Spawn shop
    (0x13FD9372, 247, 767),  # 12230   In the item shop
    (0x13FD95A8, 247, 767),  # 12492   In the item shop
    (0x13FE5022, 247, 767),  # 02938   Spawn shop
    (0x13FE5802, 247, 767),  # 00554   Spawn shop
    (0x1402BBCE, 247, 767),  # 01302   Spawn shop
    (0x140598E4, 247, 767),  # 00812   Spawn shop
    (0x14059A28, 247, 767),  # 01136   Spawn shop
    (0x1405C3F6, 247, 767),  # 00078   Spawn shop
    (0x1405C6BC, 247, 767),  # 00788   Spawn shop
    (0x1405C97E, 247, 767),  # 01494   Spawn shop
    (0x1405E998, 247, 767),  # 00304   Spawn shop
    (0x14063CCA, 247, 767),  # 02482   Spawn shop
    (0x1406AAF2, 247, 767),  # 02458   Spawn shop
    (0x1406BC3A, 247, 767),  # 02178   Spawn shop
    (0x1406D038, 247, 767),  # 02592   Spawn shop
    (0x1406D7CE, 247, 767),  # 00134   Spawn shop
    (0x1406DF30, 247, 767),  # 02036   Monochromon intro (makes the shop)
    (0x1406E3BE, 247, 767),  # 02898   Monochromon intro (joins the shop)
    (0x14070578, 247, 767),  # 00064   Spawn shop
    (0x1407267C, 247, 767),  # 07604   Spawn shop
    # ----- Leomon (1 sites) -----
    (0x13FD8ED2, 248, 768),  # 11046   Leomon hangin out (birdra room)
    # ----- Coelamon (27 sites) -----
    (0x13FD8FBA, 249, 769),  # 11278   Coelamon hangin out
    (0x13FE503E, 249, 769),  # 02974   Spawn shop
    (0x13FE581E, 249, 769),  # 00590   Spawn shop
    (0x1402BBEA, 249, 769),  # 01338   Spawn shop
    (0x14059A44, 249, 769),  # 01172   Spawn shop
    (0x1405C5FE, 249, 769),  # 00610   Shop stuff...?  In file city
    (0x1405C612, 249, 769),  # 00630    "          "
    (0x1405C626, 249, 769),  # 00650    "          "
    (0x1405C63A, 249, 769),  # 00670    "          "
    (0x1405C64E, 249, 769),  # 00690    "          "
    (0x1405C662, 249, 769),  # 00710    "          "
    (0x1405C676, 249, 769),  # 00730    "          "
    (0x1405C68A, 249, 769),  # 00750    "          "
    (0x1405CA28, 249, 769),  # 01668   Coelamon intro check
    (0x1405CB46, 249, 769),  # 01958   Coelamon + Betamon intro together
    (0x1405CD60, 249, 769),  # 02192   Set shop items buyable
    (0x1405E03C, 249, 769),  # 06416   Coelamon intro check
    (0x1405E22A, 249, 769),  # 06902   Betamon intro
    (0x1405E348, 249, 769),  # 07192   Coelamon + Betamon intro together
    (0x1405E424, 249, 769),  # 07412   Set shop items buyable
    (0x1405E47C, 249, 769),  # 07504   Something to do with the shop
    (0x1405E9B4, 249, 769),  # 00340   Spawn shop
    (0x14063CE6, 249, 769),  # 02518   Spawn shop
    (0x1406AB0E, 249, 769),  # 02494   Spawn shop
    (0x1406BC56, 249, 769),  # 02214   Spawn shop
    (0x1406D054, 249, 769),  # 02628   Spawn shop
    (0x1406D7EA, 249, 769),  # 00170   Spawn shop
    # ----- Kokatorimon (4 sites) -----
    (0x13FD873A, 250, 770),  # 09402   Kokatorimon intro
    (0x13FD87C6, 250, 770),  # 09546   Kokatorimon hangin out
    (0x14059908, 250, 770),  # 00860   Spwan some objects
    (0x1405994A, 250, 770),  # 00926   More objects
    # ----- Kuwagamon (1 sites) -----
    (0x13FD7A82, 251, 771),  # 01375   Kuwagamon in Green Gym
    # ----- Mojyamon (6 sites) -----
    (0x13FD95FC, 252, 772),  # 12576   Mojyamon intro
    (0x13FD96E8, 252, 772),  # 12812   Mojyamon hangin out
    (0x13FE44AA, 252, 772),  # 00310   Spawn secret shop
    (0x1406D768, 252, 772),  # 00032   Spawn secret shop
    (0x1406FD28, 252, 772),  # 02348   Mojyamon shop intro
    (0x1407006E, 252, 772),  # 03186   Mojyamon shop intro
    # ----- Nanimon (1 sites) -----
    (0x13FD8F5A, 253, 773),  # 11182   Nanimon hangin out
    # ----- Piximon (1 sites) -----
    (0x13FD9396, 255, 775),  # 12266   Piximon hangin out
    # ----- Digitamamon (3 sites) -----
    (0x13FD906E, 256, 776),  # 11458   Digitamamon hangin out
    (0x13FD9210, 256, 776),  # 11876   Digitamamon hangin out (with jukebox)
    (0x140AEF36, 256, 776),  # 00154   Restaurant dialog
    # ----- Penguinmon (5 sites) -----
    (0x13FD999E, 257, 777),  # 13506   Penguinmon hangin out (in file city curling arena)
    (0x14063218, 257, 777),  # 00060   Spawn curling arena
    (0x14063250, 257, 777),  # 00116   Some objects in arena
    (0x14095A7E, 257, 777),  # 00134   Some objects in arena
    (0x140632A4, 257, 777),  # 00200   Warp to curling?
    # ----- Ninjamon (1 sites) -----
    (0x13FD95CE, 258, 778),  # 12530   Ninjamon hangin out
    # ====================================================================
    # Birdramon — 32-site full sweep (no info.txt block; user reported
    # 2026-05-01 that Birdramon's building / NPC didn't appear post-AP
    # delivery despite the getFileCityTopMap C-function patches. Each
    # File-City-Top variant script also has its own ``if trigger(221)``
    # NPC-load gates that needed redirecting. Enumerated all
    # ``trigger(221)`` reads in DW1Script.txt and excluded the 3 reads
    # in script 124 (which also contains ``setTrigger 221`` — cutscene
    # flow, must remain bound to bit 221).
    # ====================================================================
    (0x13FDC9E0, 221, 741),  # script 0
    (0x13FDCA40, 221, 741),  # script 0
    (0x13FFEE3E, 221, 741),  # script 47
    (0x13FFEE9E, 221, 741),  # script 47
    (0x1400ABD6, 221, 741),  # script 63
    (0x1400AC36, 221, 741),  # script 63
    (0x14024B14, 221, 741),  # script 100
    (0x14024B74, 221, 741),  # script 100
    (0x1402FBB4, 221, 741),  # script 108
    (0x1402FC14, 221, 741),  # script 108
    (0x14045164, 221, 741),  # script 136
    (0x140451C4, 221, 741),  # script 136
    (0x1404C40E, 221, 741),  # script 146
    (0x1404C46E, 221, 741),  # script 146
    (0x140583C4, 221, 741),  # script 160
    (0x14058424, 221, 741),  # script 160
    (0x1405E590, 221, 741),  # script 163
    (0x1405E5F0, 221, 741),  # script 163
    (0x14061B4E, 221, 741),  # script 165
    (0x14061BAE, 221, 741),  # script 165
    (0x140620B8, 221, 741),  # script 166
    (0x14062118, 221, 741),  # script 166
    (0x14062C28, 221, 741),  # script 167
    (0x14062C88, 221, 741),  # script 167
    (0x1406792C, 221, 741),  # script 169
    (0x1406798C, 221, 741),  # script 169
    (0x1406927C, 221, 741),  # script 171
    (0x140692DC, 221, 741),  # script 171
    (0x14072A06, 221, 741),  # script 178
    (0x14072A66, 221, 741),  # script 178
    (0x140A0306, 221, 741),  # script 211
    (0x140B4BCE, 221, 741),  # script 221
    # ====================================================================
    # Palmon — 72-site full sweep (no info.txt block; user-validated 2026-04-30).
    # The standalone randomizer never randomized Palmon, so info.txt has
    # no MUST-CHANGE block; we enumerated all trigger(246) reads via the
    # script tool and verified each. Palmon is quest-recruited (no fight
    # gate), so the full sweep is safe.
    # ====================================================================
    (0x13FD62D6, 246, 766),
    (0x13FDCA08, 246, 766),
    (0x13FDCA2C, 246, 766),
    (0x13FDCA68, 246, 766),
    (0x13FDCA8C, 246, 766),
    (0x13FFEE66, 246, 766),
    (0x13FFEE8A, 246, 766),
    (0x13FFEEC6, 246, 766),
    (0x13FFEEEA, 246, 766),
    (0x1400ABFE, 246, 766),
    (0x1400AC22, 246, 766),
    (0x1400AC5E, 246, 766),
    (0x1400AC82, 246, 766),
    (0x14024B3C, 246, 766),
    (0x14024B60, 246, 766),
    (0x14024B9C, 246, 766),
    (0x14024BC0, 246, 766),
    (0x1402FBDC, 246, 766),
    (0x1402FC00, 246, 766),
    (0x1402FC3C, 246, 766),
    (0x1402FC60, 246, 766),
    (0x1403AB50, 246, 766),
    (0x1403AB74, 246, 766),
    (0x1403ABB0, 246, 766),
    (0x1403ABD4, 246, 766),
    (0x1404518C, 246, 766),
    (0x140451B0, 246, 766),
    (0x140451EC, 246, 766),
    (0x14045210, 246, 766),
    (0x1404C436, 246, 766),
    (0x1404C45A, 246, 766),
    (0x1404C496, 246, 766),
    (0x1404C4BA, 246, 766),
    (0x140583EC, 246, 766),
    (0x14058410, 246, 766),
    (0x1405844C, 246, 766),
    (0x14058470, 246, 766),
    (0x1405999A, 246, 766),
    (0x140599C2, 246, 766),
    (0x1405ACB0, 246, 766),
    (0x1405AFAC, 246, 766),
    (0x1405E5B8, 246, 766),
    (0x1405E5DC, 246, 766),
    (0x1405E618, 246, 766),
    (0x1405E63C, 246, 766),
    (0x14061B76, 246, 766),
    (0x14061B9A, 246, 766),
    (0x14061BD6, 246, 766),
    (0x14061BFA, 246, 766),
    (0x140620E0, 246, 766),
    (0x14062104, 246, 766),
    (0x14062140, 246, 766),
    (0x14062164, 246, 766),
    (0x14062C50, 246, 766),
    (0x14062C74, 246, 766),
    (0x14062CB0, 246, 766),
    (0x14062CD4, 246, 766),
    (0x14067954, 246, 766),
    (0x14067978, 246, 766),
    (0x140679B4, 246, 766),
    (0x140679D8, 246, 766),
    (0x140692A4, 246, 766),
    (0x140692C8, 246, 766),
    (0x14069304, 246, 766),
    (0x14069328, 246, 766),
    (0x14072A2E, 246, 766),
    (0x14072A52, 246, 766),
    (0x14072A8E, 246, 766),
    (0x14072AB2, 246, 766),
    (0x14097F3A, 246, 766),
    (0x1409F97E, 246, 766),
    (0x140B4266, 246, 766),
    # ====================================================================
    # ROM_RECRUITMENT-derived additional in-town behavior patches.
    # User reported 2026-05-01 that recruits like Kuwagamon weren't
    # appearing in their city slots even after AP delivery; the
    # standalone randomizer's RecruitmentEntry catalog has many more
    # in-town trigger sites than info.txt's MUST-CHANGE block.
    # Verified per-byte against the vanilla BIN.
    # ====================================================================
    # ----- Betamon (9 sites) -----
    (0x13FE5D32, 204, 724),
    (0x1402C5AE, 204, 724),
    (0x1405C14A, 204, 724),
    (0x1405E6C2, 204, 724),
    (0x14060890, 204, 724),
    (0x1406F12E, 204, 724),
    (0x140B4572, 204, 724),
    (0x140B9ABA, 204, 724),
    (0x140B9BCA, 204, 724),
    # ----- Devimon (5 sites) -----
    (0x13FE543A, 206, 726),
    (0x1406F0A4, 206, 726),
    (0x140B6668, 206, 726),
    (0x140BA7B4, 206, 726),
    (0x140BA898, 206, 726),
    # ----- Tyrannomon (53 sites) -----
    (0x13FE505A, 208, 728),
    (0x13FE513E, 208, 728),
    (0x13FE5222, 208, 728),
    (0x13FE583A, 208, 728),
    (0x13FE591E, 208, 728),
    (0x13FE5A02, 208, 728),
    (0x13FE5D52, 208, 728),
    (0x1402BC06, 208, 728),
    (0x1402BCEA, 208, 728),
    (0x1402BDCE, 208, 728),
    (0x1402C5CE, 208, 728),
    (0x1402C6B2, 208, 728),
    (0x1402C796, 208, 728),
    (0x14051FC6, 208, 728),
    (0x1405218A, 208, 728),
    (0x140598A4, 208, 728),
    (0x14059A60, 208, 728),
    (0x14059B44, 208, 728),
    (0x14059C28, 208, 728),
    (0x1405BFAE, 208, 728),
    (0x1405C16A, 208, 728),
    (0x1405C24E, 208, 728),
    (0x1405C5B6, 208, 728),
    (0x1405E9D0, 208, 728),
    (0x1405EAB4, 208, 728),
    (0x1405EB98, 208, 728),
    (0x140608B0, 208, 728),
    (0x14060994, 208, 728),
    (0x14060A78, 208, 728),
    (0x14063D02, 208, 728),
    (0x14063DE6, 208, 728),
    (0x14063ECA, 208, 728),
    (0x1406AB2A, 208, 728),
    (0x1406AC0E, 208, 728),
    (0x1406ACF2, 208, 728),
    (0x1406BC72, 208, 728),
    (0x1406BD56, 208, 728),
    (0x1406BE3A, 208, 728),
    (0x1406C07E, 208, 728),
    (0x1406D070, 208, 728),
    (0x1406D154, 208, 728),
    (0x1406D238, 208, 728),
    (0x1406D484, 208, 728),
    (0x1406D806, 208, 728),
    (0x1406D8EA, 208, 728),
    (0x1406D9CE, 208, 728),
    (0x1406F14E, 208, 728),
    (0x140AEBE2, 208, 728),
    (0x140B47C0, 208, 728),
    (0x140BA176, 208, 728),
    (0x140BA2A0, 208, 728),
    (0x140BA318, 208, 728),
    (0x140BA442, 208, 728),
    # ----- Meramon (21 sites) -----
    (0x13FD8FDA, 209, 729),
    (0x13FD9108, 209, 729),
    (0x1406AC0A, 209, 729),
    (0x1406ACEE, 209, 729),
    (0x1406BC6E, 209, 729),
    (0x1406BD52, 209, 729),
    (0x1406BE36, 209, 729),
    (0x1406BF52, 209, 729),
    (0x1406C362, 209, 729),
    (0x1406D06C, 209, 729),
    (0x1406D150, 209, 729),
    (0x1406D234, 209, 729),
    (0x1406D354, 209, 729),
    (0x1406D802, 209, 729),
    (0x1406D8E6, 209, 729),
    (0x1406D9CA, 209, 729),
    (0x1406F14A, 209, 729),
    (0x140AEB82, 209, 729),
    (0x140B4880, 209, 729),
    (0x140BA2FC, 209, 729),
    (0x140BA42A, 209, 729),
    # ----- Numemon (5 sites) -----
    (0x13FE543E, 211, 731),
    (0x1406F0A8, 211, 731),
    (0x140B5A62, 211, 731),
    (0x140BA760, 211, 731),
    (0x140BA850, 211, 731),
    # ----- Mamemon (5 sites) -----
    (0x13FE5446, 213, 733),
    (0x1406F0AC, 213, 733),
    (0x140B598E, 213, 733),
    (0x140BA798, 213, 733),
    (0x140BA880, 213, 733),
    # ----- Gabumon (2 sites) -----
    (0x140B563C, 217, 737),
    (0x140BA08C, 217, 737),
    # ----- Elecmon (4 sites) -----
    (0x1405C084, 218, 738),
    (0x140B4D44, 218, 738),
    (0x140B9B70, 218, 738),
    (0x140B9DF2, 218, 738),
    # ----- Kabuterimon (6 sites) -----
    (0x1402FECC, 219, 739),
    (0x14030F06, 219, 739),
    (0x140319C6, 219, 739),
    (0x14032398, 219, 739),
    (0x140B5B3A, 219, 739),
    (0x140B8BF0, 219, 739),
    # ----- Garurumon (53 sites) -----
    (0x13FE505E, 222, 742),
    (0x13FE5142, 222, 742),
    (0x13FE5226, 222, 742),
    (0x13FE583E, 222, 742),
    (0x13FE5922, 222, 742),
    (0x13FE5A06, 222, 742),
    (0x13FE5D56, 222, 742),
    (0x1402BC0A, 222, 742),
    (0x1402BCEE, 222, 742),
    (0x1402BDD2, 222, 742),
    (0x1402C5D2, 222, 742),
    (0x1402C6B6, 222, 742),
    (0x1402C79A, 222, 742),
    (0x14051FCA, 222, 742),
    (0x1405218E, 222, 742),
    (0x140598A8, 222, 742),
    (0x14059A64, 222, 742),
    (0x14059B48, 222, 742),
    (0x14059C2C, 222, 742),
    (0x1405BFB2, 222, 742),
    (0x1405C16E, 222, 742),
    (0x1405C252, 222, 742),
    (0x1405C5BA, 222, 742),
    (0x1405E9D4, 222, 742),
    (0x1405EAB8, 222, 742),
    (0x1405EB9C, 222, 742),
    (0x140608B4, 222, 742),
    (0x14060998, 222, 742),
    (0x14060A7C, 222, 742),
    (0x14063D06, 222, 742),
    (0x14063DEA, 222, 742),
    (0x14063ECE, 222, 742),
    (0x1406AB2E, 222, 742),
    (0x1406AC12, 222, 742),
    (0x1406ACF6, 222, 742),
    (0x1406BC76, 222, 742),
    (0x1406BD5A, 222, 742),
    (0x1406BE3E, 222, 742),
    (0x1406C17A, 222, 742),
    (0x1406D074, 222, 742),
    (0x1406D158, 222, 742),
    (0x1406D23C, 222, 742),
    (0x1406D580, 222, 742),
    (0x1406D80A, 222, 742),
    (0x1406D8EE, 222, 742),
    (0x1406D9D2, 222, 742),
    (0x1406F152, 222, 742),
    (0x140AEC2E, 222, 742),
    (0x140B4B26, 222, 742),
    (0x140BA192, 222, 742),
    (0x140BA2B8, 222, 742),
    (0x140BA334, 222, 742),
    (0x140BA45A, 222, 742),
    # ----- Frigimon (52 sites) -----
    (0x13FE5062, 223, 743),
    (0x13FE5146, 223, 743),
    (0x13FE522A, 223, 743),
    (0x13FE5842, 223, 743),
    (0x13FE5926, 223, 743),
    (0x13FE5A0A, 223, 743),
    (0x13FE5D5A, 223, 743),
    (0x1402BC0E, 223, 743),
    (0x1402BCF2, 223, 743),
    (0x1402BDD6, 223, 743),
    (0x1402C5D6, 223, 743),
    (0x1402C6BA, 223, 743),
    (0x1402C79E, 223, 743),
    (0x14051FCE, 223, 743),
    (0x14052192, 223, 743),
    (0x140598AC, 223, 743),
    (0x14059A68, 223, 743),
    (0x14059B4C, 223, 743),
    (0x14059C30, 223, 743),
    (0x1405BFB6, 223, 743),
    (0x1405C172, 223, 743),
    (0x1405C256, 223, 743),
    (0x1405C5BE, 223, 743),
    (0x1405E9D8, 223, 743),
    (0x1405EABC, 223, 743),
    (0x1405EBA0, 223, 743),
    (0x140608B8, 223, 743),
    (0x1406099C, 223, 743),
    (0x14060A80, 223, 743),
    (0x14063D0A, 223, 743),
    (0x14063DEE, 223, 743),
    (0x14063ED2, 223, 743),
    (0x1406AB32, 223, 743),
    (0x1406AC16, 223, 743),
    (0x1406ACFA, 223, 743),
    (0x1406BC7A, 223, 743),
    (0x1406BD5E, 223, 743),
    (0x1406BE42, 223, 743),
    (0x1406C280, 223, 743),
    (0x1406D078, 223, 743),
    (0x1406D15C, 223, 743),
    (0x1406D240, 223, 743),
    (0x1406D80E, 223, 743),
    (0x1406D8F2, 223, 743),
    (0x1406D9D6, 223, 743),
    (0x1406F156, 223, 743),
    (0x140B118C, 223, 743),
    (0x140B4A80, 223, 743),
    (0x140BA1AE, 223, 743),
    (0x140BA2D0, 223, 743),
    (0x140BA350, 223, 743),
    (0x140BA472, 223, 743),
    # ----- Whamon (3 sites) -----
    (0x1405BF76, 224, 744),
    (0x140B57F4, 224, 744),
    (0x140B987C, 224, 744),
    # ----- SkullGreymon (1 sites) -----
    (0x140B68BE, 226, 746),
    # ----- MetalMamemon (2 sites) -----
    (0x140B617C, 227, 747),
    (0x140BAB02, 227, 747),
    # ----- Vademon (4 sites) -----
    (0x140B11CC, 228, 748),
    (0x140B626E, 228, 748),
    (0x140BA1CE, 228, 748),
    (0x140BA370, 228, 748),
    # ----- Patamon (14 sites) -----
    (0x13FE5D0E, 231, 751),
    (0x1402C58A, 231, 751),
    (0x1405BFE2, 231, 751),
    (0x1405C126, 231, 751),
    (0x1405E6A2, 231, 751),
    (0x1406086C, 231, 751),
    (0x1406F10A, 231, 751),
    (0x14072B0A, 231, 751),
    (0x140B507C, 231, 751),
    (0x140B9AC6, 231, 751),
    (0x140B9BD6, 231, 751),
    (0x140BA122, 231, 751),
    (0x140BA49E, 231, 751),
    (0x140BA6E0, 231, 751),
    # ----- Kunemon (8 sites) -----
    (0x13FE5324, 232, 752),
    (0x13FE5348, 232, 752),
    (0x13FE5B08, 232, 752),
    (0x13FE5B2C, 232, 752),
    (0x140B432E, 232, 752),
    (0x140B6C4A, 232, 752),
    (0x140B9B32, 232, 752),
    (0x140B9E2E, 232, 752),
    # ----- Unimon (14 sites) -----
    (0x13FE5D16, 233, 753),
    (0x1402C592, 233, 753),
    (0x1405BFEA, 233, 753),
    (0x1405C12E, 233, 753),
    (0x1405E6AA, 233, 753),
    (0x14060874, 233, 753),
    (0x1406F112, 233, 753),
    (0x14072B12, 233, 753),
    (0x140B4FB8, 233, 753),
    (0x140B9ACE, 233, 753),
    (0x140B9BDE, 233, 753),
    (0x140BA12A, 233, 753),
    (0x140BA4D6, 233, 753),
    (0x140BA710, 233, 753),
    # ----- Ogremon (2 sites) -----
    (0x140B5E82, 234, 754),
    (0x140B9D52, 234, 754),
    # ----- Shellmon (4 sites) -----
    (0x140B4C64, 235, 755),
    (0x140B9B0A, 235, 755),
    (0x140B9D3E, 235, 755),
    (0x140B9D76, 235, 755),
    # ----- Bakemon (3 sites) -----
    (0x140B462E, 237, 757),
    (0x140B9AF0, 237, 757),
    (0x140B9DCA, 237, 757),
    # ----- Drimogemon (2 sites) -----
    (0x1405BF5E, 238, 758),
    (0x140B5568, 238, 758),
    # ----- Sukamon (1 sites) -----
    (0x140B9976, 239, 759),
    # ----- Andromon (2 sites) -----
    (0x140B6990, 240, 760),
    (0x140B9900, 240, 760),
    # ----- Giromon (1 sites) -----
    (0x140B5DE0, 241, 761),
    # ----- Etemon (4 sites) -----
    (0x13FDD278, 242, 762),
    (0x13FE0010, 242, 762),
    (0x140B60CE, 242, 762),
    (0x140B754A, 242, 762),
    # ----- Biyomon (14 sites) -----
    (0x13FE5D12, 245, 765),
    (0x1402C58E, 245, 765),
    (0x1405BFE6, 245, 765),
    (0x1405C12A, 245, 765),
    (0x1405E6A6, 245, 765),
    (0x14060870, 245, 765),
    (0x1406F10E, 245, 765),
    (0x14072B0E, 245, 765),
    (0x140B5132, 245, 765),
    (0x140B9ACA, 245, 765),
    (0x140B9BDA, 245, 765),
    (0x140BA126, 245, 765),
    (0x140BA4BA, 245, 765),
    (0x140BA6F8, 245, 765),
    # ----- Monochromon (14 sites) -----
    (0x13FE5D1A, 247, 767),
    (0x1402C596, 247, 767),
    (0x1405BFEE, 247, 767),
    (0x1405C132, 247, 767),
    (0x1405E6AE, 247, 767),
    (0x14060878, 247, 767),
    (0x1406F116, 247, 767),
    (0x14072B16, 247, 767),
    (0x140B4ED0, 247, 767),
    (0x140B9AD2, 247, 767),
    (0x140B9BE2, 247, 767),
    (0x140BA12E, 247, 767),
    (0x140BA4F2, 247, 767),
    (0x140BA728, 247, 767),
    # ----- Leomon (2 sites) -----
    (0x140B5F30, 248, 768),
    (0x140BA052, 248, 768),
    # ----- Coelamon (8 sites) -----
    (0x13FE5D36, 249, 769),
    (0x1402C5B2, 249, 769),
    (0x1405C14E, 249, 769),
    (0x14060894, 249, 769),
    (0x1406F132, 249, 769),
    (0x140B44C0, 249, 769),
    (0x140B6DDC, 249, 769),
    (0x140BA13A, 249, 769),
    # ----- Kokatorimon (5 sites) -----
    (0x1405C012, 250, 770),
    (0x1405C054, 250, 770),
    (0x140B4E06, 250, 770),
    (0x140B98BA, 250, 770),
    (0x140B9946, 250, 770),
    # ----- Kuwagamon (2 sites) -----
    (0x140B5D3C, 251, 771),
    (0x140B8C02, 251, 771),
    # ----- Mojyamon (5 sites) -----
    (0x13FE5442, 252, 772),
    (0x1406F0B0, 252, 772),
    (0x140B58A4, 252, 772),
    (0x140BA77C, 252, 772),
    (0x140BA868, 252, 772),
    # ----- Nanimon (2 sites) -----
    (0x140B63C6, 253, 773),
    (0x140BA0DA, 253, 773),
    # ----- Piximon (2 sites) -----
    (0x140B600A, 255, 775),
    (0x140BA516, 255, 775),
    # ----- Digitamamon (3 sites) -----
    (0x140B67EE, 256, 776),
    (0x140BA1EE, 256, 776),
    (0x140BA390, 256, 776),
    # ----- Penguinmon (6 sites) -----
    (0x14066374, 257, 777),
    (0x140663AC, 257, 777),
    (0x14066400, 257, 777),
    (0x1409761C, 257, 777),
    (0x140B53E6, 257, 777),
    (0x140BAB1E, 257, 777),
    # ----- Ninjamon (2 sites) -----
    (0x140B573A, 258, 778),
    (0x140BA74E, 258, 778),
    # ====================================================================
    # Vegiemon � 71-site full sweep (no info.txt block; standalone
    # randomizer omitted Vegiemon, so ROM_RECRUITMENT has no entry).
    # User reported 2026-05-01 that Vegiemon was missing from plaza
    # despite AP delivery (and that no screen has Vegiemon without
    # Palmon also recruited). Enumerated all trigger(225) reads in
    # DW1Script.txt; excluded the 2 reads in script 15 (which
    # contains setTrigger 225 � cutscene flow). Each is a 2-byte
    # rewrite of trigger 225 -> 745, verified per-byte against
    # vanilla BIN.
    # ====================================================================
    (0x13FDC9F8, 225, 745),  # script 0
    (0x13FDCA1C, 225, 745),  # script 0
    (0x13FDCA58, 225, 745),  # script 0
    (0x13FDCA7C, 225, 745),  # script 0
    (0x13FFEE56, 225, 745),  # script 47
    (0x13FFEE7A, 225, 745),  # script 47
    (0x13FFEEB6, 225, 745),  # script 47
    (0x13FFEEDA, 225, 745),  # script 47
    (0x1400ABEE, 225, 745),  # script 63
    (0x1400AC12, 225, 745),  # script 63
    (0x1400AC4E, 225, 745),  # script 63
    (0x1400AC72, 225, 745),  # script 63
    (0x14024B2C, 225, 745),  # script 100
    (0x14024B50, 225, 745),  # script 100
    (0x14024B8C, 225, 745),  # script 100
    (0x14024BB0, 225, 745),  # script 100
    (0x1402FBCC, 225, 745),  # script 108
    (0x1402FBF0, 225, 745),  # script 108
    (0x1402FC2C, 225, 745),  # script 108
    (0x1402FC50, 225, 745),  # script 108
    (0x1403AB40, 225, 745),  # script 124
    (0x1403AB64, 225, 745),  # script 124
    (0x1403ABA0, 225, 745),  # script 124
    (0x1403ABC4, 225, 745),  # script 124
    (0x1404517C, 225, 745),  # script 136
    (0x140451A0, 225, 745),  # script 136
    (0x140451DC, 225, 745),  # script 136
    (0x14045200, 225, 745),  # script 136
    (0x1404C426, 225, 745),  # script 146
    (0x1404C44A, 225, 745),  # script 146
    (0x1404C486, 225, 745),  # script 146
    (0x1404C4AA, 225, 745),  # script 146
    (0x140583DC, 225, 745),  # script 160
    (0x14058400, 225, 745),  # script 160
    (0x1405843C, 225, 745),  # script 160
    (0x14058460, 225, 745),  # script 160
    (0x140599B2, 225, 745),  # script 162 offset 1030 — city object visibility
    (0x1405ACC8, 225, 745),  # script 162 offset 5308 — Section_81 multi-cond
    # 0x1405AD10 (script 162 offset 5376) is EXCLUDED. It's Tanemon's
    # NPC dialog gate `if pstat(1) < 10 OR trigger(225) == true then 5540`
    # which controls whether `setTrigger 86` fires to spawn the sprout
    # in Tropical Jungle (TROP03). If we redirect this to trigger 745
    # (AP-delivered), the gate suppresses sprout spawn the moment AP
    # delivers `Vegiemon Recruit` — before the player has actually used
    # the rain plant — so the Rain Plant cutscene location becomes
    # impossible to complete. Vanilla `trigger(225)` only flips after
    # the recruit cutscene fires, which is the correct gate for sprout
    # setup. Reported 2026-05-24.
    (0x1405AF5A, 225, 745),  # script 162 offset 5966 — Vegiemon celebration dialog
    (0x1405E5A8, 225, 745),  # script 163
    (0x1405E5CC, 225, 745),  # script 163
    (0x1405E608, 225, 745),  # script 163
    (0x1405E62C, 225, 745),  # script 163
    (0x14061B66, 225, 745),  # script 165
    (0x14061B8A, 225, 745),  # script 165
    (0x14061BC6, 225, 745),  # script 165
    (0x14061BEA, 225, 745),  # script 165
    (0x140620D0, 225, 745),  # script 166
    (0x140620F4, 225, 745),  # script 166
    (0x14062130, 225, 745),  # script 166
    (0x14062154, 225, 745),  # script 166
    (0x14062C40, 225, 745),  # script 167
    (0x14062C64, 225, 745),  # script 167
    (0x14062CA0, 225, 745),  # script 167
    (0x14062CC4, 225, 745),  # script 167
    (0x14067944, 225, 745),  # script 169
    (0x14067968, 225, 745),  # script 169
    (0x140679A4, 225, 745),  # script 169
    (0x140679C8, 225, 745),  # script 169
    (0x14069294, 225, 745),  # script 171
    (0x140692B8, 225, 745),  # script 171
    (0x140692F4, 225, 745),  # script 171
    (0x14069318, 225, 745),  # script 171
    (0x14072A1E, 225, 745),  # script 178
    (0x14072A42, 225, 745),  # script 178
    (0x14072A7E, 225, 745),  # script 178
    (0x14072AA2, 225, 745),  # script 178
    (0x14097F2A, 225, 745),  # script 207
    (0x1409FDD0, 225, 745),  # script 211
    (0x140B46F0, 225, 745),  # script 221
    # ====================================================================
    # Remaining sweeps for the standalone-omitted recruits, applied
    # 2026-05-01. The standalone randomizer's RecruitmentEntry catalog
    # excluded these recruits explicitly (Greymon, Monzaemon, Angemon,
    # Birdramon, Vegiemon, Palmon, Centarumon) or has no entry at all
    # (Airdramon, Seadramon, MetalGreymon, Megadramon — no in-town
    # behavior, no chained quest). Sweeps enumerate every trigger(N)
    # read in DW1Script.txt, exclude the cutscene-flow script (the
    # one containing setTrigger N), and verify each BIN address.
    # ====================================================================
    # ----- Greymon (115 sites; excluded cutscene script [162] and
    #       arming-gate script [210]) -----
    #
    # Script 210 §51 holds three story-progression gates (offsets 0x138,
    # 0x162, 0x952) that read trigger(205) to decide whether Jijimon
    # arms the Greymon ambush, arms the Airdramon ambush, or shows the
    # Mt. Infinity reminder. Those reads are LEFT VANILLA on purpose:
    # if they were redirected to trigger(725) (= Greymon AP-delivered),
    # then receiving the Greymon Recruit AP item before fighting Greymon
    # would make the gate at 0x138 think Greymon is already recruited,
    # skip ``setTrigger 87``, and the field-spawn ambush in Script 162
    # §57 (gated on ``trigger(87)``) would never fire — softlocking the
    # Greymon AP location and blocking the Airdramon flow downstream.
    # Vanilla reads here mean: AP item drives city visibility (the ~115
    # patches below), but the recruit *fight* is gated on the player
    # actually winning it (vanilla setTrigger 205), exactly as DW1
    # designed. Do not add Script 210 entries to this block.
    (0x13FD8716, 205, 725),  # script 0
    (0x13FE5092, 205, 725),  # script 10
    (0x13FE50B6, 205, 725),  # script 10
    (0x13FE50F2, 205, 725),  # script 10
    (0x13FE5116, 205, 725),  # script 10
    (0x13FE5176, 205, 725),  # script 10
    (0x13FE519A, 205, 725),  # script 10
    (0x13FE51D6, 205, 725),  # script 10
    (0x13FE51FA, 205, 725),  # script 10
    (0x13FE525A, 205, 725),  # script 10
    (0x13FE527E, 205, 725),  # script 10
    (0x13FE52BA, 205, 725),  # script 10
    (0x13FE52DE, 205, 725),  # script 10
    (0x13FE5872, 205, 725),  # script 11
    (0x13FE5896, 205, 725),  # script 11
    (0x13FE58D2, 205, 725),  # script 11
    (0x13FE58F6, 205, 725),  # script 11
    (0x13FE5956, 205, 725),  # script 11
    (0x13FE597A, 205, 725),  # script 11
    (0x13FE59B6, 205, 725),  # script 11
    (0x13FE59DA, 205, 725),  # script 11
    (0x13FE5A3A, 205, 725),  # script 11
    (0x13FE5A5E, 205, 725),  # script 11
    (0x13FE5A9A, 205, 725),  # script 11
    (0x13FE5ABE, 205, 725),  # script 11
    (0x14004C8C, 205, 725),  # script 54
    (0x140292B8, 205, 725),  # script 103
    (0x1402BC3E, 205, 725),  # script 105
    (0x1402BC62, 205, 725),  # script 105
    (0x1402BC9E, 205, 725),  # script 105
    (0x1402BCC2, 205, 725),  # script 105
    (0x1402BD22, 205, 725),  # script 105
    (0x1402BD46, 205, 725),  # script 105
    (0x1402BD82, 205, 725),  # script 105
    (0x1402BDA6, 205, 725),  # script 105
    (0x1402BE06, 205, 725),  # script 105
    (0x1402BE2A, 205, 725),  # script 105
    (0x1402BE66, 205, 725),  # script 105
    (0x1402BE8A, 205, 725),  # script 105
    (0x14043B3A, 205, 725),  # script 135
    (0x1405EA08, 205, 725),  # script 164
    (0x1405EA2C, 205, 725),  # script 164
    (0x1405EA68, 205, 725),  # script 164
    (0x1405EA8C, 205, 725),  # script 164
    (0x1405EAEC, 205, 725),  # script 164
    (0x1405EB10, 205, 725),  # script 164
    (0x1405EB4C, 205, 725),  # script 164
    (0x1405EB70, 205, 725),  # script 164
    (0x1405EBD0, 205, 725),  # script 164
    (0x1405EBF4, 205, 725),  # script 164
    (0x1405EC30, 205, 725),  # script 164
    (0x1405EC54, 205, 725),  # script 164
    (0x14063D3A, 205, 725),  # script 168
    (0x14063D5E, 205, 725),  # script 168
    (0x14063D9A, 205, 725),  # script 168
    (0x14063DBE, 205, 725),  # script 168
    (0x14063E1E, 205, 725),  # script 168
    (0x14063E42, 205, 725),  # script 168
    (0x14063E7E, 205, 725),  # script 168
    (0x14063EA2, 205, 725),  # script 168
    (0x14063F02, 205, 725),  # script 168
    (0x14063F26, 205, 725),  # script 168
    (0x14063F62, 205, 725),  # script 168
    (0x14063F86, 205, 725),  # script 168
    (0x1406AB62, 205, 725),  # script 173
    (0x1406AB86, 205, 725),  # script 173
    (0x1406ABC2, 205, 725),  # script 173
    (0x1406ABE6, 205, 725),  # script 173
    (0x1406AC46, 205, 725),  # script 173
    (0x1406AC6A, 205, 725),  # script 173
    (0x1406ACA6, 205, 725),  # script 173
    (0x1406ACCA, 205, 725),  # script 173
    (0x1406AD2A, 205, 725),  # script 173
    (0x1406AD4E, 205, 725),  # script 173
    (0x1406AD8A, 205, 725),  # script 173
    (0x1406ADAE, 205, 725),  # script 173
    (0x1406BCAA, 205, 725),  # script 174
    (0x1406BCCE, 205, 725),  # script 174
    (0x1406BD0A, 205, 725),  # script 174
    (0x1406BD2E, 205, 725),  # script 174
    (0x1406BD8E, 205, 725),  # script 174
    (0x1406BDB2, 205, 725),  # script 174
    (0x1406BDEE, 205, 725),  # script 174
    (0x1406BE12, 205, 725),  # script 174
    (0x1406BE72, 205, 725),  # script 174
    (0x1406BE96, 205, 725),  # script 174
    (0x1406BED2, 205, 725),  # script 174
    (0x1406BEF6, 205, 725),  # script 174
    (0x1406D0A8, 205, 725),  # script 175
    (0x1406D0CC, 205, 725),  # script 175
    (0x1406D108, 205, 725),  # script 175
    (0x1406D12C, 205, 725),  # script 175
    (0x1406D18C, 205, 725),  # script 175
    (0x1406D1B0, 205, 725),  # script 175
    (0x1406D1EC, 205, 725),  # script 175
    (0x1406D210, 205, 725),  # script 175
    (0x1406D270, 205, 725),  # script 175
    (0x1406D294, 205, 725),  # script 175
    (0x1406D2D0, 205, 725),  # script 175
    (0x1406D2F4, 205, 725),  # script 175
    (0x1406D83E, 205, 725),  # script 176
    (0x1406D862, 205, 725),  # script 176
    (0x1406D89E, 205, 725),  # script 176
    (0x1406D8C2, 205, 725),  # script 176
    (0x1406D922, 205, 725),  # script 176
    (0x1406D946, 205, 725),  # script 176
    (0x1406D982, 205, 725),  # script 176
    (0x1406D9A6, 205, 725),  # script 176
    (0x1406DA06, 205, 725),  # script 176
    (0x1406DA2A, 205, 725),  # script 176
    (0x1406DA66, 205, 725),  # script 176
    (0x1406DA8A, 205, 725),  # script 176
    (0x140766CC, 205, 725),  # script 183
    (0x140A092C, 205, 725),  # script 211
    (0x140B51F6, 205, 725),  # script 221
    # Airdramon: dropped 2026-05-08 from AP coverage (see
    # ``_AP_RECRUIT_EXCLUDED``). Vanilla bytecode for ``trigger(207)``
    # reads is intentionally left UNPATCHED so the in-game cutscene
    # flow (Script 184) drives Airdramon's town visibility on its own,
    # exactly as vanilla DW1 does. Do not add Airdramon entries here.
    # Seadramon: dropped 2026-05-09 from AP coverage (see
    # ``_AP_RECRUIT_EXCLUDED``). Vanilla bytecode for ``trigger(210)``
    # reads is intentionally left UNPATCHED so the in-game cutscene
    # flow (Script 7) drives Seadramon's town visibility on its own,
    # exactly as vanilla DW1 does. Same pattern as Airdramon. The
    # cutscene IS the Blue Flute pickup; trigger 210 is now polled as
    # the ``Blue Flute Pickup`` AP location signal via
    # KEYITEM_LOCATION_RAM_BITS. Do not add Seadramon entries here.
    # ----- MetalGreymon (1 sites; excluded cutscene script [184]) -----
    (0x140B6316, 212, 732),  # script 221
    # ----- Monzaemon (23 sites; excluded cutscene script [140]) -----
    (0x13FD8E96, 214, 734),  # script 0
    (0x13FDC9C4, 214, 734),  # script 0
    (0x13FFEE22, 214, 734),  # script 47
    (0x1400ABBA, 214, 734),  # script 63
    (0x14024AF8, 214, 734),  # script 100
    (0x1402FB98, 214, 734),  # script 108
    (0x1403AB0C, 214, 734),  # script 124
    (0x14045148, 214, 734),  # script 136
    (0x14046696, 214, 734),  # script 139
    (0x1404C3F2, 214, 734),  # script 146
    (0x140583A8, 214, 734),  # script 160
    (0x1405996A, 214, 734),  # script 162
    (0x1405B1AC, 214, 734),  # script 162
    (0x1405E574, 214, 734),  # script 163
    (0x14061B32, 214, 734),  # script 165
    (0x14061FA8, 214, 734),  # script 166
    (0x1406209C, 214, 734),  # script 166
    (0x14062C0C, 214, 734),  # script 167
    (0x14067910, 214, 734),  # script 169
    (0x14069260, 214, 734),  # script 171
    (0x140729EA, 214, 734),  # script 178
    (0x14078732, 214, 734),  # script 184
    (0x140B644A, 214, 734),  # script 221
    # ----- Angemon (21 sites; excluded cutscene script [93]) -----
    (0x13FD8E6A, 220, 740),  # script 0
    (0x13FDC9C0, 220, 740),  # script 0
    (0x13FFEE1E, 220, 740),  # script 47
    (0x1400ABB6, 220, 740),  # script 63
    (0x14024AF4, 220, 740),  # script 100
    (0x1402FB94, 220, 740),  # script 108
    (0x1403AB08, 220, 740),  # script 124
    (0x14045144, 220, 740),  # script 136
    (0x1404C3EE, 220, 740),  # script 146
    (0x140583A4, 220, 740),  # script 160
    (0x14059966, 220, 740),  # script 162
    (0x1405B1A8, 220, 740),  # script 162
    (0x1405E570, 220, 740),  # script 163
    (0x14061B2E, 220, 740),  # script 165
    (0x14062098, 220, 740),  # script 166
    (0x14062C08, 220, 740),  # script 167
    (0x1406790C, 220, 740),  # script 169
    (0x1406925C, 220, 740),  # script 171
    (0x140728B6, 220, 740),  # script 178
    (0x1407872E, 220, 740),  # script 184
    (0x140B54BA, 220, 740),  # script 221
    # ----- Centarumon (64 sites; excluded cutscene script [18]) -----
    (0x13FE507A, 236, 756),  # script 10
    (0x13FE50DA, 236, 756),  # script 10
    (0x13FE515E, 236, 756),  # script 10
    (0x13FE51BE, 236, 756),  # script 10
    (0x13FE5242, 236, 756),  # script 10
    (0x13FE52A2, 236, 756),  # script 10
    (0x13FE585A, 236, 756),  # script 11
    (0x13FE58BA, 236, 756),  # script 11
    (0x13FE593E, 236, 756),  # script 11
    (0x13FE599E, 236, 756),  # script 11
    (0x13FE5A22, 236, 756),  # script 11
    (0x13FE5A82, 236, 756),  # script 11
    (0x13FE9764, 236, 756),  # script 17
    (0x1402BC26, 236, 756),  # script 105
    (0x1402BC86, 236, 756),  # script 105
    (0x1402BD0A, 236, 756),  # script 105
    (0x1402BD6A, 236, 756),  # script 105
    (0x1402BDEE, 236, 756),  # script 105
    (0x1402BE4E, 236, 756),  # script 105
    (0x14059A80, 236, 756),  # script 162
    (0x14059AE0, 236, 756),  # script 162
    (0x14059B64, 236, 756),  # script 162
    (0x14059BC4, 236, 756),  # script 162
    (0x14059C48, 236, 756),  # script 162
    (0x14059CA8, 236, 756),  # script 162
    (0x1405C536, 236, 756),  # script 163
    (0x1405E9F0, 236, 756),  # script 164
    (0x1405EA50, 236, 756),  # script 164
    (0x1405EAD4, 236, 756),  # script 164
    (0x1405EB34, 236, 756),  # script 164
    (0x1405EBB8, 236, 756),  # script 164
    (0x1405EC18, 236, 756),  # script 164
    (0x14063D22, 236, 756),  # script 168
    (0x14063D82, 236, 756),  # script 168
    (0x14063E06, 236, 756),  # script 168
    (0x14063E66, 236, 756),  # script 168
    (0x14063EEA, 236, 756),  # script 168
    (0x14063F4A, 236, 756),  # script 168
    (0x1406AB4A, 236, 756),  # script 173
    (0x1406ABAA, 236, 756),  # script 173
    (0x1406AC2E, 236, 756),  # script 173
    (0x1406AC8E, 236, 756),  # script 173
    (0x1406AD12, 236, 756),  # script 173
    (0x1406AD72, 236, 756),  # script 173
    (0x1406BC92, 236, 756),  # script 174
    (0x1406BCF2, 236, 756),  # script 174
    (0x1406BD76, 236, 756),  # script 174
    (0x1406BDD6, 236, 756),  # script 174
    (0x1406BE5A, 236, 756),  # script 174
    (0x1406BEBA, 236, 756),  # script 174
    (0x1406D090, 236, 756),  # script 175
    (0x1406D0F0, 236, 756),  # script 175
    (0x1406D174, 236, 756),  # script 175
    (0x1406D1D4, 236, 756),  # script 175
    (0x1406D258, 236, 756),  # script 175
    (0x1406D2B8, 236, 756),  # script 175
    (0x1406D826, 236, 756),  # script 176
    (0x1406D886, 236, 756),  # script 176
    (0x1406D90A, 236, 756),  # script 176
    (0x1406D96A, 236, 756),  # script 176
    (0x1406D9EE, 236, 756),  # script 176
    (0x1406DA4E, 236, 756),  # script 176
    (0x1409FB24, 236, 756),  # script 211
    (0x140B43DC, 236, 756),  # script 221
    # ----- Megadramon (3 sites; excluded cutscene script [198]) -----
    (0x13FD8C9E, 254, 774),  # script 0
    (0x13FD8CD6, 254, 774),  # script 0
    (0x13FD9B62, 254, 774),  # script 0
    # ====================================================================
    # Greymon — script 162 visibility-warp reads (12 sites). User reported
    # 2026-05-01 that Greymon's arena building does not appear when entering
    # File City Bottom from the Top side. Cause: script 162 is the master
    # Bottom-plaza variant selector (cascading recruit checks → warpTo
    # 180/181/182/.../188/203). Our earlier blanket exclusion of script 162
    # (because it also contains setTrigger 205) over-skipped these
    # visibility reads. Each pair (181/188, 186/187, 182/185, 183/184,
    # 180/203, 202/...) is the "no-Greymon / with-Greymon" split for a
    # specific Top-plaza walk-out point.
    # ====================================================================
    (0x14059A98, 205, 725),  # script 162 byte 1260
    (0x14059ABC, 205, 725),  # script 162 byte 1296
    (0x14059AF8, 205, 725),  # script 162 byte 1356
    (0x14059B1C, 205, 725),  # script 162 byte 1392
    (0x14059B7C, 205, 725),  # script 162 byte 1488
    (0x14059BA0, 205, 725),  # script 162 byte 1524
    (0x14059BDC, 205, 725),  # script 162 byte 1584
    (0x14059C00, 205, 725),  # script 162 byte 1620
    (0x14059C60, 205, 725),  # script 162 byte 1716
    (0x14059C84, 205, 725),  # script 162 byte 1752
    (0x14059CC0, 205, 725),  # script 162 byte 1812
    (0x14059CE4, 205, 725),  # script 162 byte 1848
)


# =============================================================================
# getFileCityTopMap trigger redirects (Plan A revised — Top City variants)
# =============================================================================
#
# Vanilla DW1's ``getFileCityTopMap`` (RAM 0x800D97DC) is a C function
# that picks which File City Top variant (screen IDs 168..179, 204) to
# load when the player enters File City Top. It branches on
# ``isTriggerSet(200+X)`` for several recruits: Angemon (220),
# Monzaemon (214), Birdramon (221), Vegimon (225), Palmon (246).
# (Identified via the user — works the same way Palmon does.)
#
# Without patching, after a recruit's vanilla cutscene completes
# (200+X = 1) the function picks a variant that *includes* that
# Digimon at the plaza — independent of AP delivery. To gate Top
# City visibility on AP delivery instead, we rewrite the trigger ID
# embedded in each ``addiu r4, r0, <trigger_id>`` instruction (the
# 16-bit immediate field) from ``200+X`` to ``720+X``. After patching,
# each ``isTriggerSet`` call reads the corresponding bit of
# BEATEN_BLOCK (= AP-delivered) instead of the recruit-block.
#
# Each entry: (BIN offset of the ``addiu`` instruction's lower-16-bit
# immediate, original trigger ID, redirected trigger ID). We patch
# the bottom 2 bytes (the immediate field, stored LE) at each offset.

ROM_GETTOPCITY_TRIGGER_FORMAT: Final = "<H"
ROM_GETTOPCITY_TRIGGER_PATCHES: Final = (
    (0x14D0ECC0, 220, 740),  # Angemon
    (0x14D0ECD0, 214, 734),  # Monzaemon
    (0x14D0EE10, 221, 741),  # Birdramon (1st check)
    (0x14D0EE20, 225, 745),  # Vegimon (1st check)
    (0x14D0EE38, 246, 766),  # Palmon (1st check)
    (0x14D0EE58, 225, 745),  # Vegimon (2nd check)
    (0x14D0EE70, 246, 766),  # Palmon (2nd check)
    (0x14D0EE90, 221, 741),  # Birdramon (2nd check)
    (0x14D0EEA0, 225, 745),  # Vegimon (3rd check)
    (0x14D0EEB8, 246, 766),  # Palmon (3rd check)
    (0x14D0EED8, 225, 745),  # Vegimon (4th check)
    (0x14D0EEF0, 246, 766),  # Palmon (4th check)
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
# ENGINE (non-script) readers of 200+X, enumerated from dw_decomp
# 2026-08-28 — this is the complete list, and their patched status:
#
#   * ``recalculatePPandArena``          prosperity        client-overridden
#   * ``getFileCityTopMap`` (map.c:3095) city top map      PATCHED (12 sites = its 12 calls)
#   * ``trn_reward.c:637/643`` (TRN_REL) triggers 219/251  PATCHED 2026-08-28 (-> 739/771,
#                                        = training x6/x5  :data:`TRN_GYM_BONUS_WORD_PATCHES`)
#   * ``dget.c:308-357`` (DGET_REL)      cup entry count   LEFT VANILLA by decision — cup tiers
#                                                          follow the client's arena enforcer
#   * ``dooa.c:1855`` / ``murd.c:755``   214/220 + pstat(1)>=50  message choice only
#   * flight table entry 0               221               PATCHED (-> 878)
#
# Consequence of the two UNPATCHED readers: an AP-delivered Kabuterimon
# or Kuwagamon shows the gym NPC but does not grant the training bonus
# (and vice versa), and tournament entry requirements follow the vanilla
# recruit count. Fix path = immediate-field patches in TRN_REL.BIN like
# the top-map ones; tracked in STATUS.md. The head-wrapper described
# below is defined but never emitted (no call site in rom.py).
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
# Mt. Infinity prosperity gate (Phase 9, 2026-05-10)
# =============================================================================
# Script 210 §51 line 162:
#   ``if trigger(354) == true OR pstat(1) < 50 OR trigger(205) == false then 952``
# This is the Jijimon dialog that arms the Airdramon ambush in File City
# and announces Mt. Infinity. The literal ``50`` is the prosperity
# threshold for opening Mt. Infinity. The ``ProsperityGoal`` AP
# option rewrites this byte at generation time so the in-game gate and
# the AP rules in :mod:`worlds.digimon_world.rules` stay in sync.
#
# Encoding — CORRECTED 2026-08-28 from dw_decomp (the IF evaluator
# ``MAIN_func_801050C0``, ``src/main/script_anim.c:79-165``). Script IF
# primitives are ``[op][pad][args]``, not the ``ID | opcode`` shapes an
# earlier comment guessed. The vanilla block starting at 0x1409E4CA
# decodes as:
#
#   19 00            IF
#   01 00 62 01      trigger(354) == false
#   8A 00 01 32      AND pstat(1) >= 50     <- comparand byte at 0x1409E4D3
#   80 00 CD 00      AND trigger(205) == true
#   18 00 B8 03      jump-if-false -> line 952
#   19 00            (next primitive)
#
# i.e. the gate is ``pstat(1) >= threshold`` (the script dumper printed
# the De Morgan form, which is where the ``<`` reading came from). The
# comparand really is the single byte at 0x1409E4D3, so the shipped patch
# is correct. The ``80 00`` we once read as a ``<`` opcode is the NEXT
# primitive's header — which also explains the 2026-05-10 v1 bug: writing
# 2 LE bytes at 0x1409E4D4 clobbered that header and desynchronised the
# parser, so the gate stopped gating and Jijimon armed Airdramon
# unconditionally. It was a parser desync, not a broken operator.
#
# Two physical copies of this IF block exist in the BIN (the second
# is at 0x1409EE7E, comparand at 0x1409EE83 — same Script 210 logic
# repeated). Both must be patched; only patching one leaves the gate
# vanilla because either copy may be the live one for a given
# screen/script-load path.
#
# We write 1 byte (not 2) at each comparand position so the adjacent
# operator opcode is preserved. Threshold range is 20..100 (fits in 1
# byte; high byte was always 0 in vanilla anyway).

ROM_PROSPERITY_GOAL_OFFSETS: Final[tuple[int, ...]] = (
    0x1409E4D3,  # Script 210 §51 line 162, copy A
    0x1409EE83,  # Script 210 §51 line 162, copy B (duplicate)
)
ROM_PROSPERITY_GOAL_FORMAT: Final = "B"  # 1 unsigned byte (preserves operator opcode at +1)
ROM_PROSPERITY_GOAL_VANILLA: Final = 50  # script's vanilla literal


# =============================================================================
# Combat stat multiplier — three Cave6 trampolines (Phase 5 polish)
# =============================================================================
#
# Source: ``references/DW1-Code/battleStatsGainsAndDrops.asm``. Vanilla
# DW1's end-of-combat stat-gain function (RAM 0x000ECEE8) writes per-stat
# gains to a 6-entry u16 table at RAM 0x13D468..0x13D473 from three sites:
#
#   * RAM 0x000ED014..0x000ED018 — main computed gain (statGain = 1 +
#     (enemyStat * enemyCountFactor - 1) / partnerStatFactor). The store
#     ``sh r3, 0(r2)`` at 0x000ED018 sits in the delay slot of an
#     unconditional ``beq r0, r0, 0x000ED07C`` at 0x000ED014.
#   * RAM 0x000ED078 — chance-based "got 1 stat point" floor in the
#     primary block. r3 is set to literal 1 by 0x000ED070 just before.
#   * RAM 0x000ED204 — same shape as site 2, in the extra-conditions
#     block (HP-loss / attacks-done chance rolls).
#
# We install three small trampolines in Cave6 free-space (immediately
# after the isTriggerSet wrapper, RAM 0x80095900 / BIN 0x14CC0D88 — all
# within sector 148,349). The factor is baked in at patch time from the
# CombatStatMultiplier option. Site 1 needs a multiply (gain * factor);
# sites 2 and 3 always store r3=1, so the trampoline simplifies to
# "store factor".
#
# Patch sites (BIN offsets derived from RAM via the changeMap +
# setTrigger anchors at sector 148,573 / 148,574; battleStats sites land
# in sector 148,524 udpos 20/120/516):
#
#   Site 1 BIN 0x14D2546C  — 8 bytes overwriting beq + sh-delay-slot:
#                            ``j tr1; nop`` (we kill the original
#                            delay-slot store; the trampoline stores
#                            after multiplying).
#   Site 2 BIN 0x14D254D0  — 4 bytes overwriting sh: ``j tr2``. The
#                            trampoline returns to RAM 0x800ED080
#                            (after the natural delay-slot inc which
#                            executes once before the jump fires).
#   Site 3 BIN 0x14D2565C  — same shape as site 2, returning to RAM
#                            0x800ED20C.
#
# Trampoline RAM/BIN slots inside Cave6 sector 148,349:
#   tr1: RAM 0x80095900, BIN 0x14CC0D88, 28 bytes
#   tr2: RAM 0x8009591C, BIN 0x14CC0DA4, 16 bytes
#   tr3: RAM 0x8009592C, BIN 0x14CC0DB4, 16 bytes
#   total 60 bytes; sector 148,349 has ~1.7KB free after isTriggerSet.

ROM_COMBAT_TR1_RAM: Final = 0x80095900
ROM_COMBAT_TR1_OFFSET: Final = 0x14CC0D88
ROM_COMBAT_TR2_RAM: Final = 0x8009591C
ROM_COMBAT_TR2_OFFSET: Final = 0x14CC0DA4
ROM_COMBAT_TR3_RAM: Final = 0x8009592C
ROM_COMBAT_TR3_OFFSET: Final = 0x14CC0DB4

ROM_COMBAT_SITE1_OFFSET: Final = 0x14D2546C  # RAM 0x000ED014 (beq + sh)
ROM_COMBAT_SITE1_FORMAT: Final = "<II"        # j tr1 + nop
ROM_COMBAT_SITE2_OFFSET: Final = 0x14D254D0  # RAM 0x000ED078 (sh)
ROM_COMBAT_SITE2_FORMAT: Final = "<I"         # j tr2
ROM_COMBAT_SITE3_OFFSET: Final = 0x14D2565C  # RAM 0x000ED204 (sh)
ROM_COMBAT_SITE3_FORMAT: Final = "<I"         # j tr3

# Site 1 patch value: ``j ROM_COMBAT_TR1_RAM; nop`` (replaces beq + sh).
# Site 2/3 patch value: ``j tr_X`` (replaces sh; the natural next
# instruction at site 2/3 becomes the j's delay slot — addi for the
# loop counter — which executes exactly once, same as the vanilla
# fall-through it replaces).
ROM_COMBAT_SITE1_VALUE: Final = (
    0x08000000 | ((ROM_COMBAT_TR1_RAM >> 2) & 0x03FFFFFF),
    0x00000000,
)
assert ROM_COMBAT_SITE1_VALUE[0] == 0x08025640, hex(ROM_COMBAT_SITE1_VALUE[0])
ROM_COMBAT_SITE2_VALUE: Final = (
    0x08000000 | ((ROM_COMBAT_TR2_RAM >> 2) & 0x03FFFFFF),
)
assert ROM_COMBAT_SITE2_VALUE[0] == 0x08025647, hex(ROM_COMBAT_SITE2_VALUE[0])
ROM_COMBAT_SITE3_VALUE: Final = (
    0x08000000 | ((ROM_COMBAT_TR3_RAM >> 2) & 0x03FFFFFF),
)
assert ROM_COMBAT_SITE3_VALUE[0] == 0x0802564B, hex(ROM_COMBAT_SITE3_VALUE[0])

# Trampoline return targets (RAM addresses of the instruction the
# trampoline ``j``s back to after storing).
_COMBAT_TR1_RETURN_RAM: Final = 0x800ED07C  # site 1's original beq target
_COMBAT_TR2_RETURN_RAM: Final = 0x800ED080  # one past site 2's delay slot
_COMBAT_TR3_RETURN_RAM: Final = 0x800ED20C  # one past site 3's delay slot


def _build_combat_tr1_bytes(factor: int) -> bytes:
    """Site-1 trampoline: r3 = r3 * factor; sh r3, 0(r2); j back; nop.

    Uses unsigned multiply via ``$t1`` (gain is non-negative and we only
    keep the low 16 bits for the ``sh`` store, so signed/unsigned would
    be equivalent on the bottom-half output anyway). One nop between
    ``multu`` and ``mflo`` for emulator-defensive R3000A spacing — the
    PSX hardware interlocks but older HLE cores have been known to
    elide the stall.
    """

    if not 1 <= factor <= 100:
        raise ValueError(f"Combat multiplier factor must be 1..100, got {factor}")
    j_back = 0x08000000 | ((_COMBAT_TR1_RETURN_RAM >> 2) & 0x03FFFFFF)
    return b"".join(
        val.to_bytes(4, "little") for val in (
            0x34090000 | (factor & 0xFFFF),  # ori   $t1, $0, factor
            0x01230019,                       # multu $t1, $v1
            0x00000000,                       # nop  (mflo defensive spacing)
            0x00001812,                       # mflo  $v1
            0xA4430000,                       # sh    $v1, 0($v0)
            j_back,                            # j     0x800ED07C
            0x00000000,                       # nop  (delay slot of j)
        )
    )


def _build_combat_tr_literal_bytes(factor: int, return_ram: int) -> bytes:
    """Sites 2/3 trampoline: r3 = factor; sh r3, 0(r2); j back; nop.

    The vanilla code at sites 2 and 3 sets r3 = 1 just before the
    store. Multiplying 1 by ``factor`` is the same as overwriting r3
    with ``factor``, so the trampoline skips the multiply entirely.
    """

    if not 1 <= factor <= 100:
        raise ValueError(f"Combat multiplier factor must be 1..100, got {factor}")
    j_back = 0x08000000 | ((return_ram >> 2) & 0x03FFFFFF)
    return b"".join(
        val.to_bytes(4, "little") for val in (
            0x34030000 | (factor & 0xFFFF),  # ori   $v1, $0, factor
            0xA4430000,                       # sh    $v1, 0($v0)
            j_back,                            # j     return_ram
            0x00000000,                       # nop  (delay slot of j)
        )
    )


def build_combat_multiplier_trampolines(factor: int) -> tuple[bytes, bytes, bytes]:
    """Build (tr1, tr2, tr3) trampoline blobs for the combat multiplier."""

    return (
        _build_combat_tr1_bytes(factor),
        _build_combat_tr_literal_bytes(factor, _COMBAT_TR2_RETURN_RAM),
        _build_combat_tr_literal_bytes(factor, _COMBAT_TR3_RETURN_RAM),
    )


# Sanity-check at module load: tr1 is 28 bytes, tr2/tr3 are 16 bytes,
# and all three fit in the 1.7KB free tail of Cave6 sector 148,349.
assert len(_build_combat_tr1_bytes(1)) == 28
assert len(_build_combat_tr_literal_bytes(1, _COMBAT_TR2_RETURN_RAM)) == 16
assert ROM_COMBAT_TR3_OFFSET + 16 < ROM_COMBAT_TR1_OFFSET + 0x800, (
    "Combat trampolines spill out of Cave6 sector 148,349"
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


# ----- Item Stat Gain (ROM-side; mirrors standalone) ------------------------
#
# Source: ``references/digimon_world_randomizer/digimon/handler.py:2429-2438``
# and ``digimon/data.py:197-200``. A single-byte write at BIN offset
# ``0x14CF5AFC`` (value ``0x00``) causes digivolution-item digivolutions
# to grant stat gains and lifetime increases the same way training
# digivolutions do. Vanilla DW1 skips both for item-driven digivolutions.

ROM_EVO_ITEM_STAT_GAIN_OFFSET: Final = 0x14CF5AFC
ROM_EVO_ITEM_STAT_GAIN_VALUE: Final = 0x00
ROM_EVO_ITEM_STAT_GAIN_FORMAT: Final = "<B"


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


# =============================================================================
# Recycle Shop (GIAS06B) — AP randomization (Phase 10)
# =============================================================================
#
# The Recycle Shop in Gear Savanna (Tinmon "Market Manager", screen
# GIAS06B, script 126 §82) sells 7 fixed money-priced items. Unlike the
# merit shop, the inventory is NOT a runtime ITEM_PARA scan; it's an
# engine-managed array reconstructed at shop-open time from scattered
# data we never fully traced. We patch it at runtime via a client poll.
#
# **Architecture (locked, see docs/recycle_shop_implementation_plan.md):**
#
# In-place ITEM_PARA extension via ITEM_DESC_PTR relocation. The
# description-pointer table (128 × u32 at RAM 0x801279DC, immediately
# after ITEM_PARA[0..127]) moves to **Cave6** free RAM (the same
# unused-libgs region that already hosts the chest wrapper, merit shop
# wrapper, combat trampolines, and recycle wrapper). Its freed 1024
# bytes at 0x801279DC become extended ITEM_PARA slots 128..255.
#
# **History note**: an earlier revision targeted "Cave1" at
# RAM 0x800A0A50 per the plan-doc, but that region contains live
# vanilla SLUS code (functions called from many sites across the
# binary, e.g. 0x000B61F0, 0x000D9764, 0x000E3624, 0x000F1534).
# SydPatches can repurpose Cave1 because they ship a complete
# replacement implementation; we cannot. Cave6 is the only region
# verified safe for arbitrary writes against vanilla SLUS-01032,
# and it has ~3 KB free after our existing wrappers + recycle
# shop wrapper.
#
# Slots 128..134 hold the 7 AP shop entries — one per recycle shop row.
# Each entry's name = the multiworld-resolved AP item name truncated to
# 14 chars (resolved at gen time after fill). Each entry's description
# (in the relocated ITEM_DESC_PTR) = "From <player>'s World". Each
# entry's price = the vanilla price of the recycle slot it replaces.
#
# Runtime: client polls every tick. When the recycle shop opens
# (shop_obj at gp-0x6BC4 != NULL with entry_count == 7), the client
# overwrites the 14-byte runtime array at shop_obj.item_list_ptr with
# [128,1, 129,1, ..., 134,1].
#
# A wrapper at the recycle shop's giveItem callsite (RAM 0x800FB410)
# dispatches by item_id. Ids 128..134 fire setTrigger(904 + offset) and
# skip vanilla giveItem so no item enters inventory; AP delivers the
# real reward via the normal path. Money is still deducted (the shop
# logic deducts before the giveItem callsite).
#
# RE source: docs/recycle_shop_implementation_plan.md and the runtime
# probe at tools/dw1_recycle_shop_probe.lua.

# --- RAM addresses (verified live 2026-05-10) -------------------------------
# Bare Nymashock MainRAM offsets (no kuseg prefix) — wrapper builder ORs
# in 0x80000000 when emitting MIPS code.
RAM_RECYCLE_SHOP_OBJ: Final = 0x00088804         # shop_obj struct (32 B)
RAM_RECYCLE_SHOP_LIST_PTR: Final = 0x00088828    # runtime [id,flag]*7 array
RAM_RECYCLE_SHOP_GP_SLOT: Final = 0x00134F68     # gp-0x6BC4 (holds shop_obj ptr)

# shop_obj field offsets — see runtime probe results.
RECYCLE_SHOP_OBJ_LIST_PTR_OFFSET: Final = 0x00     # u32 -> item list
RECYCLE_SHOP_OBJ_ENTRY_COUNT_OFFSET: Final = 0x08  # u8  -> 7 for recycle

# Per-shop count used to fingerprint "is recycle shop open" (the merit
# shop uses a different count and a different shop_obj address).
RECYCLE_SHOP_ENTRY_COUNT: Final = 7

# AP slot range: extends ITEM_PARA in-place at the freed ITEM_DESC_PTR
# location. Slot 128 = the first byte at RAM 0x801279DC; we use slots
# 128..134 (7 entries). Slots 135..143 stay zero (reserved for future
# shop work).
RECYCLE_SHOP_AP_ITEM_ID_BASE: Final = 128
RECYCLE_SHOP_AP_ITEM_ID_COUNT: Final = 7
RECYCLE_SHOP_AP_ITEM_IDS: Final = tuple(
    RECYCLE_SHOP_AP_ITEM_ID_BASE + i
    for i in range(RECYCLE_SHOP_AP_ITEM_ID_COUNT)
)

# AP location triggers — allocated 904..910. Each maps to one shop slot.
#
# **Range justification**: 904..910 are 7 consecutive bits in byte
# 0x001BE03E (= AP_TRIGGER_ARRAY_BASE + 113). Bits 0..6 of that byte
# are unassigned by vanilla DW1 and unused by AP (the prior AP-allocated
# range 890..903 ends at byte 0x001BE03D bit 7). Trigger 911 stays free
# for future expansion (bit 7 of the same byte). The plan-doc's
# original suggestion of 951..957 was rejected because trigger 951
# lands at byte 0x001BE043 = :data:`RAM_MERAMON_TUNNEL_STATE`,
# corrupting the Drimogemon-tunnel state machine.
RECYCLE_SHOP_TRIGGER_BASE: Final = 904
RECYCLE_SHOP_TRIGGER_COUNT: Final = 7
RECYCLE_SHOP_TRIGGER_IDS: Final = tuple(
    RECYCLE_SHOP_TRIGGER_BASE + i for i in range(RECYCLE_SHOP_TRIGGER_COUNT)
)
# Sanity: every trigger lands in byte 0x001BE03E (= AP_TRIGGER_ARRAY_BASE
# + 113, just above the existing AP-allocated band 890..903).
_RECYCLE_TRIG_BYTES = {
    AP_TRIGGER_ARRAY_BASE + (t // 8) for t in RECYCLE_SHOP_TRIGGER_IDS
}
assert _RECYCLE_TRIG_BYTES == {0x001BE03E}, (
    f"Recycle shop triggers spilled out of byte 0x001BE03E: "
    f"{[hex(b) for b in sorted(_RECYCLE_TRIG_BYTES)]}"
)

# Vanilla item IDs / prices of the 7 recycle slots (verified runtime
# probe 2026-05-10). Used to set each AP slot's `value` field so the
# shop displays the same money price as vanilla for that slot.
RECYCLE_SHOP_VANILLA_IDS: Final = (0x01, 0x05, 0x0F, 0x10, 0x11, 0x16, 0x27)
RECYCLE_SHOP_VANILLA_PRICES: Final = (500, 800, 500, 500, 500, 300, 500)
assert len(RECYCLE_SHOP_VANILLA_IDS) == RECYCLE_SHOP_AP_ITEM_ID_COUNT
assert len(RECYCLE_SHOP_VANILLA_PRICES) == RECYCLE_SHOP_AP_ITEM_ID_COUNT

# AP location names (one per slot, in cursor order matching the runtime
# array). locations.py imports this tuple to build the location entries.
RECYCLE_SHOP_LOCATION_NAMES: Final = tuple(
    f"Recycle Shop #{i + 1}"
    for i in range(RECYCLE_SHOP_AP_ITEM_ID_COUNT)
)

# Per-location (byte_addr, bit_index) for the client's bit-poll table.
RECYCLE_SHOP_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    name: (
        AP_TRIGGER_ARRAY_BASE + (RECYCLE_SHOP_TRIGGER_IDS[i] // 8),
        RECYCLE_SHOP_TRIGGER_IDS[i] % 8,
    )
    for i, name in enumerate(RECYCLE_SHOP_LOCATION_NAMES)
}

# --- SLUS RAM <-> bin offset helper -----------------------------------------
# Chest wrapper anchors any SLUS-RAM-relative .bin offset computation.
# Sector-aware (Mode2/2352): always use this helper for arbitrary RAM
# offsets that might cross a 2048-byte user-data boundary.

def _slus_ram_to_bin_offset(ram_addr: int) -> int:
    """Translate a SLUS-RAM address to its sector-aware .bin offset.

    Anchored on :data:`ROM_CHEST_GIVEITEM_WRAPPER_RAM` /
    :data:`ROM_CHEST_GIVEITEM_WRAPPER_OFFSET`, so all addresses inside
    the SLUS exec region (RAM ~0x80090000..0x80140000) round-trip
    correctly regardless of how many sector boundaries lie between
    the anchor and the target.
    """

    delta = ram_addr - ROM_CHEST_GIVEITEM_WRAPPER_RAM
    return _flat_to_user_data(ROM_CHEST_GIVEITEM_WRAPPER_OFFSET, delta)


# --- Cave6 layout: relocated ITEM_DESC_PTR + AP description strings --------
# Cave6 spans RAM 0x800957C0..0x80096BCC (5132 bytes total). Vanilla DW1
# never calls into this region (verified: the first vanilla call past the
# chest wrapper is at 0x80096BCC = the byte right after Cave6 ends — see
# SLUS.asm `0x000b40d4 jal 0x00096bcc`). Existing layout inside Cave6:
#
#   0x800957C0..0x800957DC  chest wrapper (28 B, always-on)
#   0x800957DC..0x800957FC  setTrigger wrapper (32 B, NOT installed but reserved)
#   0x800957FC..0x80095800  4-byte gap
#   0x80095800..0x800958B4  merit shop wrapper (180 B for N=1 dispatch entry,
#                            grows by 28 B per additional dispatch entry)
#   0x800958B4..0x800958CD  AP_ITEM_DESC_STRING (25 B, "Item from the multiworld")
#   0x800958CD..0x80095900  ~51-byte gap
#   0x80095900..0x8009593C  combat trampolines tr1+tr2+tr3 (60 B,
#                            installed only when combat_stat_multiplier > 1)
#   0x80095940..0x8009597C  retired v1 recycle giveItem wrapper slot
#                            (60 B, no longer written — free)
#   0x80095980..0x80095D80  RELOC_ITEM_DESC_PTR (1024 B, opt-in) <- this section
#   0x80095D80..0x80095F40  AP_DESC_STRINGS (448 B, opt-in)       <-
#   0x80095F40..0x80096BCC  tail, claimed piecemeal by later features:
#     - setItemTexture icon-id wrapper 0x80095F40..0x80095F80 (64 B,
#       ALWAYS-ON, grown 2026-08-21 from the 28-B v1 clamp) + per-slot
#       icon-id table 0x80095F80..0x80095FBA (58 B, ALWAYS-ON), then a
#       70 B gap up to 0x80096000. (The retired recycle init-epilogue
#       wrapper used to sit at 0x80095F5C..0x80095FB8 — reclaimed.)
#     - merit AP desc strings 0x80096000..0x80096380 and merit-shop
#       ext wrapper 0x80096380..0x800965BC (both opt-in)
#     - ITEM_PARA boot seed hook 0x800965BC..0x80096650 (148 B,
#       ALWAYS-ON — see the "ITEM_PARA 256-slot relocation" section;
#       occupies the space of the retired merit scan/name teleport
#       wrappers)
#     - transition-gate wrapper + table 0x800966C4..0x800967F0
#       (region-gate section at the bottom of this file), 16 B spare
#       before the sector-148350 boundary at 0x80096800
#     - EXT_ITEM_PARA seed block 0x80096800..0x80096BC0 (960 B = 30
#       slots, ALWAYS-ON zero-fill + opt-in shop entries; reuses the
#       footprint of the retired Cave6 ITEM_PARA ext segment)
#     Remaining free: 0x80096650..0x800966C4 (116 B, formerly the
#     retired merit row/deduct teleport wrappers),
#     0x800967F0..0x80096800 (16 B) and 0x80096BC0..0x80096BCC (12 B).
#
# Recycle-shop usage adds 1472 bytes inside Cave6, well within the
# remaining headroom. An assertion at the bottom of this block enforces
# the upper-bound invariant so any future wrapper that grows past
# 0x80095980 fails loudly at module-load time.
RECYCLE_SHOP_RELOC_TABLE_RAM_BASE: Final = 0x80095980

# Relocated ITEM_DESC_PTR table — 256 entries × u32 = 1024 bytes. The
# patcher copies the vanilla 128-entry pointer block (RAM 0x801279DC)
# verbatim into slots 0..127, fills slots 128..134 with pointers to
# the AP description strings (below), and leaves slots 135..255 zeroed.
RELOC_ITEM_DESC_PTR_RAM: Final = RECYCLE_SHOP_RELOC_TABLE_RAM_BASE     # 0x80095980
RELOC_ITEM_DESC_PTR_ENTRIES: Final = 256
RELOC_ITEM_DESC_PTR_SIZE: Final = RELOC_ITEM_DESC_PTR_ENTRIES * 4      # 1024
RELOC_ITEM_DESC_PTR_BIN_OFFSET: Final = _slus_ram_to_bin_offset(
    RELOC_ITEM_DESC_PTR_RAM,
)

# AP description strings — placed immediately after the relocated
# ITEM_DESC_PTR. Each string lives in a fixed AP_DESC_STRING_MAX_LEN
# byte slot (NUL-padded). Layout: 7 contiguous slots starting at
# RAM 0x80095D80.
AP_DESC_STRING_MAX_LEN: Final = 64
AP_DESC_STRINGS_RAM: Final = (
    RELOC_ITEM_DESC_PTR_RAM + RELOC_ITEM_DESC_PTR_SIZE                  # 0x80095D80
)
AP_DESC_STRINGS_BIN_OFFSET: Final = _slus_ram_to_bin_offset(AP_DESC_STRINGS_RAM)
AP_DESC_STRINGS_TOTAL_SIZE: Final = (
    AP_DESC_STRING_MAX_LEN * RECYCLE_SHOP_AP_ITEM_ID_COUNT              # 448
)

# Hard upper bound: the relocated table + AP desc strings must fit
# inside Cave6's documented end at RAM 0x80096BCC. If a future wrapper
# pushes the recycle shop's start past 0x80095980, OR if the table /
# strings grow past Cave6's end, this assertion fires at module-load
# time and refuses to ship a corrupting patch.
_CAVE6_END_RAM: Final = 0x80096BCC
assert AP_DESC_STRINGS_RAM + AP_DESC_STRINGS_TOTAL_SIZE <= _CAVE6_END_RAM, (
    f"Recycle shop relocated table + desc strings overflow Cave6: "
    f"end = 0x{AP_DESC_STRINGS_RAM + AP_DESC_STRINGS_TOTAL_SIZE:08X}, "
    f"Cave6 ends at 0x{_CAVE6_END_RAM:08X}"
)
# Also verify the table starts above the recycle shop wrapper (which
# also lives in Cave6 at 0x80095940 and is 60 B long).
assert RECYCLE_SHOP_RELOC_TABLE_RAM_BASE >= 0x80095940 + 60, (
    f"Recycle shop relocated table at 0x{RECYCLE_SHOP_RELOC_TABLE_RAM_BASE:08X} "
    f"overlaps the recycle shop wrapper (which ends at 0x8009597C)"
)

# String prefix/suffix for "From <player>'s World".
AP_DESC_PREFIX: Final = b"From "
AP_DESC_SUFFIX: Final = b"'s World"


def build_ap_desc_string(player_name: str) -> bytes:
    """Build the NUL-terminated, NUL-padded description string for one AP slot.

    Length = :data:`AP_DESC_STRING_MAX_LEN`. Player name is truncated
    to fit if necessary; the trailing NUL is always preserved so the
    in-game text renderer halts cleanly.
    """

    name_bytes = player_name.encode("ascii", errors="replace")
    # Reserve 1 byte for the trailing NUL.
    max_name = AP_DESC_STRING_MAX_LEN - len(AP_DESC_PREFIX) - len(AP_DESC_SUFFIX) - 1
    if len(name_bytes) > max_name:
        name_bytes = name_bytes[:max_name]
    body = AP_DESC_PREFIX + name_bytes + AP_DESC_SUFFIX + b"\x00"
    return body.ljust(AP_DESC_STRING_MAX_LEN, b"\x00")


# Sanity: max-length player name should still fit a non-empty body.
assert AP_DESC_STRING_MAX_LEN > len(AP_DESC_PREFIX) + len(AP_DESC_SUFFIX) + 1


# --- Vanilla ITEM_DESC_PTR source location (.bin) --------------------------
# RAM 0x801279DC = the byte immediately after ITEM_PARA[127], where the
# vanilla 128-entry ITEM_DESC_PTR table lives. Sector-aware translation
# via the existing ITEM_PARA helper (the table is contiguous with
# ITEM_PARA in user-data layout).
VANILLA_ITEM_DESC_PTR_RAM: Final = 0x801279DC
VANILLA_ITEM_DESC_PTR_BIN_OFFSET: Final = _table_byte_to_bin_flat(
    ROM_ITEM_TABLE_ENTRY_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE,                # = 0x1000
)
# Number of vanilla ITEM_DESC_PTR entries to copy into the relocated table.
VANILLA_ITEM_DESC_PTR_ENTRIES: Final = ROM_ITEM_TABLE_ENTRY_COUNT          # 128


# --- Extended ITEM_PARA slots (relocated-table seed) ------------------------
# With the always-on 256-slot relocation, extended slots 128..255 live
# at their natural positions inside the relocated table
# (RAM :data:`ITEM_PARA_RELOC_EXT_KUSEG` +). The relocated region is
# NOT .bin-backed, so the patcher stages ext entries in the .bin-backed
# EXT_ITEM_PARA seed block in Cave6 (:data:`EXT_ITEM_PARA_SEED_RAM`,
# defined in the relocation section below); the boot hook copies the
# seed into the relocated table on every boot / soft reset. The freed
# ITEM_DESC_PTR region at 0x801279DC and the retired Cave6 ext segment
# are no longer ext-slot storage.


def ext_item_para_slot_bin_offset(slot: int) -> int:
    """Sector-aware .bin offset of extended ITEM_PARA slot ``slot``.

    Two contiguous segments:

    * ``128..EXT_ITEM_PARA_SEED_SLOT_LAST`` (157) maps to its 32-byte
      entry in the Cave6 EXT_ITEM_PARA seed block
      (:data:`EXT_ITEM_PARA_SEED_BIN_OFFSET` ``+ (slot - 128) * 32``).
      The boot hook copies the whole seed block to
      :data:`ITEM_PARA_RELOC_EXT_KUSEG`, so a write here lands at the
      slot's natural position in the relocated table at runtime. The
      seed block is sector-aligned and 960 B < 2048 B, so the flat add
      never crosses a Mode2/2352 user-data boundary.
    * ``SHOP_AP_STAGING2_SLOT_BASE..SHOP_AP_STAGING2_SLOT_LAST``
      (158..185, shopsanity) maps into the second .bin-backed seed
      block staged at :data:`SHOP_AP_STAGING2_RAM`. The EXTENDED boot
      hook copies it to relocated slots 158..185 and then re-zeroes the
      staging region (it is a runtime-active workspace after boot). The
      whole 896-B run sits inside one sector's user-data window
      (asserted below), so flat adds are safe here too.
    """

    if EXT_ITEM_PARA_SEED_SLOT_BASE <= slot <= EXT_ITEM_PARA_SEED_SLOT_LAST:
        seed_byte_offset = (
            (slot - EXT_ITEM_PARA_SEED_SLOT_BASE) * ROM_ITEM_TABLE_ENTRY_SIZE
        )
        return EXT_ITEM_PARA_SEED_BIN_OFFSET + seed_byte_offset
    if SHOP_AP_STAGING2_SLOT_BASE <= slot <= SHOP_AP_STAGING2_SLOT_LAST:
        staging_byte_offset = (
            (slot - SHOP_AP_STAGING2_SLOT_BASE) * ROM_ITEM_TABLE_ENTRY_SIZE
        )
        return SHOP_AP_STAGING2_BIN_OFFSET + staging_byte_offset
    raise ValueError(
        f"Extended ITEM_PARA slot {slot} out of supported range "
        f"[{EXT_ITEM_PARA_SEED_SLOT_BASE}, {EXT_ITEM_PARA_SEED_SLOT_LAST + 1}) "
        f"u [{SHOP_AP_STAGING2_SLOT_BASE}, {SHOP_AP_STAGING2_SLOT_LAST + 1})"
    )


def build_ap_item_para_entry(
    name: str, price: int, merit_value: int = 0,
) -> bytes:
    """Build a 32-byte ITEM_PARA entry for one AP shop slot.

    Layout (matches dw1.hpp Item struct):

    * bytes  0..19: name (ASCII, NUL-padded, truncated to 14 chars per
      spec — the in-game name field renders 14 chars cleanly; the extra
      6 padding bytes stay zero).
    * bytes 20..23: value (i32 LE, money price — set to ``price``).
    * bytes 24..25: meritValue (i16 LE — set to ``merit_value``).
    * bytes 26..27: sortingValue (0).
    * byte  28:     itemColor (0).
    * byte  29:     dropable (0 — never grants to inventory).
    * bytes 30..31: unk (0).

    The recycle shop passes ``merit_value=0`` (default): it filters its
    runtime array by writing directly to the engine-built [id, flag]
    array, so meritValue is irrelevant. The merit shop passes a non-zero
    ``merit_value`` so its open-time ITEM_PARA scan picks the slot up
    (see :func:`merit_shop_inventory.dw1_merit_inventory`).
    """

    name_bytes = name.encode("ascii", errors="replace")[:14]
    return (
        name_bytes.ljust(20, b"\x00")
        + price.to_bytes(4, "little", signed=True)
        + merit_value.to_bytes(2, "little", signed=True)
        + b"\x00\x00"  # sortingValue
        + b"\x00"      # itemColor
        + b"\x00"      # dropable
        + b"\x00\x00"  # unk
    )


# --- ITEM_DESC_PTR callsite patches ----------------------------------------
# Every ``addiu rN, rN, 0x79DC`` in the SLUS that resolves to ITEM_DESC_PTR.
# All 3 callsites use $r2 (verified against references/DW1-Code/SLUS.asm):
#
#   * RAM 0x000DC648 lui $r2, 0x8012   <- target #1 hi half (inventory desc)
#     RAM 0x000DC64C addiu $r2, $r2, 0x79DC
#   * RAM 0x000FD74C lui $r2, 0x8012   <- target #2 hi half (shop desc panel)
#     RAM 0x000FD754 addiu $r2, $r2, 0x79DC  (an `sll` lives between the two)
#   * RAM 0x000FD76C lui $r2, 0x8012   <- target #3 hi half (shop desc panel)
#     RAM 0x000FD770 addiu $r2, $r2, 0x79DC
#
# We rewrite each pair to load RELOC_ITEM_DESC_PTR_RAM (= 0x80095980):
#   lui   $r2, 0x8009     -> 0x3C028009
#   addiu $r2, $r2, 0x5980 -> 0x24425980
# (low half 0x5980 is positive < 0x8000, no sign-extension issue.)

# Encoding helpers — derived from RELOC_ITEM_DESC_PTR_RAM so the bytes
# stay in sync if the relocated address moves.
_RELOC_HI: Final = (RELOC_ITEM_DESC_PTR_RAM >> 16) & 0xFFFF                 # 0x8009
_RELOC_LO: Final = RELOC_ITEM_DESC_PTR_RAM & 0xFFFF                         # 0x5980
assert _RELOC_LO < 0x8000, (
    f"RELOC low half 0x{_RELOC_LO:04X} would need sign-extension; pick a "
    f"new RELOC_ITEM_DESC_PTR_RAM whose low 16 bits are < 0x8000."
)
# Both encodings target $r2 (rt=2). lui: opcode 0x0F << 26 | rt<<16 | imm
RELOC_ITEM_DESC_PTR_LUI_VALUE: Final = 0x3C020000 | _RELOC_HI               # 0x3C028009
RELOC_ITEM_DESC_PTR_ADDIU_VALUE: Final = 0x24420000 | _RELOC_LO             # 0x24425980

# Per-callsite (lui_bin_offset, addiu_bin_offset) tuples. Each lands in
# the patcher as two 4-byte WRITEs.
RELOC_ITEM_DESC_PTR_PATCH_SITES: Final = (
    # Inventory hover description display
    (_slus_ram_to_bin_offset(0x800DC648), _slus_ram_to_bin_offset(0x800DC64C)),
    # Shop description panel — first reader (lui at 0xFD74C, addiu at 0xFD754
    # with the `sll $r3, $r19, 0x02` instruction interleaved between them)
    (_slus_ram_to_bin_offset(0x800FD74C), _slus_ram_to_bin_offset(0x800FD754)),
    # Shop description panel — second reader (consecutive lui+addiu)
    (_slus_ram_to_bin_offset(0x800FD76C), _slus_ram_to_bin_offset(0x800FD770)),
)
RELOC_ITEM_DESC_PTR_PATCH_FORMAT: Final = "<I"


# --- Recycle-shop give-item wrapper -----------------------------------------
# The wrapper hijacks the vanilla ``jal 0x800C5240`` (giveItem) at the
# recycle shop's give-item callsite (RAM 0x800FB410). Logic:
#
#   1. If $a0 (item_id) is in [128, 134] — i.e. one of our extended AP
#      slots — fire setTrigger(904 + (item_id - 128)) and return $v0=1
#      WITHOUT calling vanilla giveItem. Money was already deducted by
#      the surrounding shop logic before this jal.
#   2. Otherwise tail-call vanilla giveItem so the shop functions
#      normally for any unmatched item ID (defensive — vanilla recycle
#      slots are 0x01..0x27 so this branch is unreachable in practice
#      after the runtime patch, but keeps the wrapper safe if the
#      runtime patch somehow fails).
#
# Wrapper sits in Cave6 free space, after the combat trampolines (which
# end at RAM 0x8009593C). The merit shop wrapper at 0x80095800 + 180 B
# = 0x800958B4 plus AP_ITEM_DESC_STRING (25 B) = 0x800958CD; combat tr1
# starts at 0x80095900 and tr3 ends at 0x8009593C. Place this wrapper
# at 0x80095940 (4-byte aligned, 4-byte gap from combat tr3).
ROM_RECYCLE_SHOP_WRAPPER_RAM: Final = 0x80095940
ROM_RECYCLE_SHOP_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_RECYCLE_SHOP_WRAPPER_RAM,
)


def _build_recycle_shop_wrapper_bytes() -> bytes:
    """Build the recycle-shop giveItem-wrapper MIPS bytecode.

    15 instructions / 60 bytes. See section 2 above for the dispatch
    semantics.

    Layout::

        addiu $at, $a0, -RECYCLE_SHOP_AP_ITEM_ID_BASE   ; at = a0 - 128
        sltiu $t0, $at, RECYCLE_SHOP_AP_ITEM_ID_COUNT   ; t0 = (at < 7)
        beq   $t0, $0, .vanilla                          ; not in AP range
        nop                                              ; bne delay slot
        addiu $sp, $sp, -0x10                            ; (in-range path)
        sw    $ra, 0x0C($sp)
        addiu $a0, $at, RECYCLE_SHOP_TRIGGER_BASE        ; trigger_id = 904 + (a0-128)
        jal   setTrigger
        nop                                              ; jal delay slot
        lw    $ra, 0x0C($sp)
        addiu $sp, $sp, 0x10
        jr    $ra                                        ; return without giveItem
        addiu $v0, $0, 1                                 ; success ($v0=1, jr delay)
      .vanilla:
        j     0x800C5240                                 ; tail-call vanilla giveItem
        nop                                              ; j delay slot
    """

    import struct as _struct

    SETTRIGGER_RAM = 0x801065C0
    GIVEITEM_RAM = 0x800C5240
    jal_settrigger = 0x0C000000 | ((SETTRIGGER_RAM >> 2) & 0x03FFFFFF)
    j_giveitem = 0x08000000 | ((GIVEITEM_RAM >> 2) & 0x03FFFFFF)

    # MIPS branch offset = (target_PC_index - branch_PC_index - 1).
    # The beq is at instruction-index 2; the .vanilla label (j giveItem)
    # is at index 13 — that's 9 in-range-path instructions past the bne
    # delay slot, plus the 4-instruction in-range epilogue (lw, addiu,
    # jr, addiu in delay) for a total of 10 instructions skipped.
    BEQ_OFFSET = 0x11000000 | (10 & 0xFFFF)  # beq $t0, $0, +10

    return b"".join(
        _struct.pack("<I", v) for v in (
            # at = a0 - 128  (sign-extended -128 = 0xFF80)
            0x24810000 | ((-RECYCLE_SHOP_AP_ITEM_ID_BASE) & 0xFFFF),
            # sltiu $t0, $at, COUNT
            0x2C280000 | (RECYCLE_SHOP_AP_ITEM_ID_COUNT & 0xFFFF),
            # beq $t0, $0, .vanilla (skip 10 instrs forward)
            BEQ_OFFSET,
            0x00000000,                                # nop (beq delay slot)
            # In AP range: setTrigger(TRIGGER_BASE + at), then return.
            0x27BDFFF0,                                # addiu $sp, $sp, -0x10
            0xAFBF000C,                                # sw    $ra, 0x0C($sp)
            # addiu $a0, $at, TRIGGER_BASE  (at already = a0 - 128)
            0x24240000 | (RECYCLE_SHOP_TRIGGER_BASE & 0xFFFF),
            jal_settrigger,                            # jal   setTrigger
            0x00000000,                                # nop   (jal delay slot)
            0x8FBF000C,                                # lw    $ra, 0x0C($sp)
            0x27BD0010,                                # addiu $sp, $sp, 0x10
            0x03E00008,                                # jr    $ra
            0x24020001,                                # addiu $v0, $0, 1 (jr delay)
            # .vanilla: tail-call vanilla giveItem
            j_giveitem,                                # j     0x800C5240
            0x00000000,                                # nop   (j delay slot)
        )
    )


ROM_RECYCLE_SHOP_WRAPPER_BYTES: Final = _build_recycle_shop_wrapper_bytes()
assert len(ROM_RECYCLE_SHOP_WRAPPER_BYTES) == 60, len(ROM_RECYCLE_SHOP_WRAPPER_BYTES)


# --- Recycle-shop give-item jal hijack --------------------------------------
# Replace ``jal 0x800C5240`` (= 0x0C031490 LE) at RAM 0x800FB410 with
# ``jal ROM_RECYCLE_SHOP_WRAPPER_RAM``. Single 4-byte rewrite. The
# delay-slot nop at +4 stays as-is.

ROM_RECYCLE_SHOP_PATCH_RAM: Final = 0x800FB410
ROM_RECYCLE_SHOP_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_RECYCLE_SHOP_PATCH_RAM,
)
ROM_RECYCLE_SHOP_PATCH_FORMAT: Final = "<I"
ROM_RECYCLE_SHOP_PATCH_VALUE: Final = (
    0x0C000000 | ((ROM_RECYCLE_SHOP_WRAPPER_RAM >> 2) & 0x03FFFFFF)
)


# --- setItemTexture icon-id wrapper (per-slot icons for ext ITEM_PARA slots) --
# Vanilla ``setItemTexture`` at RAM 0x800E5DFC computes
# ``col = item_id % 16; row = item_id / 16`` and reads a 16x16 tile from
# ITEM.TIM at those grid coordinates. ITEM.TIM is laid out as 16 cols x
# 8 rows of 16x16 tiles (= 128 tiles total, exactly slots 0..127). Our
# extended slots 128..185 map off the texture, so the renderer would
# read garbage pixels for AP shop slot icons.
#
# Fix (v2, 2026-08-21 — supersedes the flat "everything -> slot 83"
# clamp): install a trampoline before ``setItemTexture``'s prologue that
# rewrites any ``item_id`` in 128..185 through the per-slot
# :data:`AP_ICON_ID_TABLE_RAM` byte table (``a1 = table[a1 - 128]``).
# The patcher fills the table at generation time: an ext slot whose
# AP-placed item is THIS world's own bank-deliverable inventory item
# (dw_code 2000..2127) gets that item's real ITEM.TIM tile id, so local
# items keep their native icon in the shop UI; every other slot
# (progressives, money, PP, recruit/technique items, other players'
# items) gets :data:`AP_CHEST_SENTINEL_ITEM_ID` (83) — the AP logo
# tile. Ids >= 186 (impossible) also fall back to 83. Because the
# rewrite happens before the function body, both the tile UV AND the
# ``ITEM_CLUT_DATA`` palette lookup follow the substituted id, so a
# native icon renders with its own palette.
#
# Function layout (vanilla):
#   0x800E5DFC  addiu $sp, $sp, -0x28   <- prologue instr 1 (we hijack)
#   0x800E5E00  sw    $ra, 0x20($sp)    <- prologue instr 2 (becomes nop)
#   0x800E5E04  sw    $s1, 0x1C($sp)    <- where the trampoline returns
#   ...
#
# Wrapper layout (16 instructions / 64 bytes):
#    0  sltiu $t0, $a1, 128        ; vanilla id?
#    1  bne   $t0, $0, .keep
#    2  nop                        ; bne delay slot
#    3  sltiu $t0, $a1, 186        ; inside the ext band?
#    4  beq   $t0, $0, .fallback   ; id >= 186 -> logo
#    5  nop                        ; beq delay slot
#    6  lui   $t1, hi(TABLE)
#    7  addiu $t1, $t1, lo(TABLE)
#    8  addu  $t1, $t1, $a1
#    9  lbu   $a1, -128($t1)       ; a1 = table[a1 - 128]
#   10  beq   $0, $0, .keep
#   11  nop                        ; branch delay; also covers the R3000
#                                  ; load-delay slot of the lbu (a1 is
#                                  ; first read well inside the body)
#   12 .fallback:
#      addiu $a1, $0, 83           ; AP logo tile
#   13 .keep:
#      addiu $sp, $sp, -0x28       ; reproduced instr 1
#   14  j     0x800E5E04           ; return to setItemTexture instr 3
#   15  sw    $ra, 0x20($sp)       ; reproduced instr 2 (j delay slot)
#
# Space claim (Cave6): wrapper 0x80095F40..0x80095F80 (64 B, grown in
# place from the 28-B v1 clamp; starts right after AP_DESC_STRINGS),
# then the 58-B icon-id table 0x80095F80..0x80095FBA. Both fit in the
# window freed by the retired recycle init-epilogue wrapper (the next
# claim, the merit AP desc strings, starts at 0x80096000).

ROM_SET_ITEM_TEXTURE_RAM: Final = 0x800E5DFC
ROM_SET_ITEM_TEXTURE_RETURN_RAM: Final = 0x800E5E04  # instr 3 of setItemTexture
# Vanilla words the entry patch displaces (byte-verified by the ROM-gated
# tests); the wrapper reproduces them before jumping back.
ROM_SET_ITEM_TEXTURE_VANILLA_WORDS: Final = (0x27BDFFD8, 0xAFBF0020)

ROM_ICON_CLAMP_WRAPPER_RAM: Final = (
    AP_DESC_STRINGS_RAM + AP_DESC_STRINGS_TOTAL_SIZE                         # 0x80095F40
)
ROM_ICON_CLAMP_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_ICON_CLAMP_WRAPPER_RAM,
)
ROM_ICON_CLAMP_WRAPPER_LEN: Final = 64  # 16 instructions

# Per-slot icon-id table: ext ids 128..185 -> u8 ITEM.TIM tile id.
AP_ICON_ID_TABLE_BASE_ITEM_ID: Final = 128
AP_ICON_ID_TABLE_SIZE: Final = 58                       # ids 128..185
AP_ICON_ID_TABLE_RAM: Final = (
    ROM_ICON_CLAMP_WRAPPER_RAM + ROM_ICON_CLAMP_WRAPPER_LEN  # 0x80095F80
)
AP_ICON_ID_TABLE_OFFSET: Final = _slus_ram_to_bin_offset(AP_ICON_ID_TABLE_RAM)
AP_ICON_ID_FALLBACK: Final = AP_CHEST_SENTINEL_ITEM_ID  # 83 = AP logo tile


def _build_icon_clamp_wrapper_bytes() -> bytes:
    """Build the setItemTexture icon-id trampoline.

    16 MIPS instructions / 64 bytes. See :data:`ROM_ICON_CLAMP_WRAPPER_RAM`
    block comment for the dispatch shape and delay-slot notes.
    """

    import struct as _struct

    table_hi, table_lo = _decompose_kuseg(AP_ICON_ID_TABLE_RAM)
    j_back = (
        0x08000000 | ((ROM_SET_ITEM_TEXTURE_RETURN_RAM >> 2) & 0x03FFFFFF)
    )
    words = (
        # 0: sltiu $t0, $a1, 128
        0x2CA80000 | (AP_ICON_ID_TABLE_BASE_ITEM_ID & 0xFFFF),
        # 1: bne $t0, $0, .keep (idx 13; offset = 13 - 2 = 11)
        0x1500000B,
        # 2: nop (bne delay slot)
        0x00000000,
        # 3: sltiu $t0, $a1, 186
        0x2CA80000 | (
            (AP_ICON_ID_TABLE_BASE_ITEM_ID + AP_ICON_ID_TABLE_SIZE) & 0xFFFF
        ),
        # 4: beq $t0, $0, .fallback (idx 12; offset = 12 - 5 = 7)
        0x11000007,
        # 5: nop (beq delay slot)
        0x00000000,
        # 6: lui $t1, hi(TABLE)
        0x3C090000 | table_hi,
        # 7: addiu $t1, $t1, lo(TABLE)
        0x25290000 | table_lo,
        # 8: addu $t1, $t1, $a1
        0x01254821,
        # 9: lbu $a1, -128($t1)
        0x91250000 | ((-AP_ICON_ID_TABLE_BASE_ITEM_ID) & 0xFFFF),
        # 10: beq $0, $0, .keep (idx 13; offset = 13 - 11 = 2)
        0x10000002,
        # 11: nop (branch delay; also the lbu load-delay filler)
        0x00000000,
        # 12: .fallback: addiu $a1, $0, 83
        0x24050000 | (AP_ICON_ID_FALLBACK & 0xFFFF),
        # 13: .keep: reproduced setItemTexture instr 1
        ROM_SET_ITEM_TEXTURE_VANILLA_WORDS[0],
        # 14: j 0x800E5E04 (return to setItemTexture instr 3)
        j_back,
        # 15: reproduced instr 2 (j delay slot)
        ROM_SET_ITEM_TEXTURE_VANILLA_WORDS[1],
    )
    return b"".join(_struct.pack("<I", v) for v in words)


ROM_ICON_CLAMP_WRAPPER_BYTES: Final = _build_icon_clamp_wrapper_bytes()
assert len(ROM_ICON_CLAMP_WRAPPER_BYTES) == ROM_ICON_CLAMP_WRAPPER_LEN, (
    len(ROM_ICON_CLAMP_WRAPPER_BYTES)
)

# Default table image: every ext slot renders the AP logo until the
# patcher's gen-time pass substitutes local items' native tile ids.
AP_ICON_ID_TABLE_DEFAULT_BYTES: Final = (
    bytes((AP_ICON_ID_FALLBACK,)) * AP_ICON_ID_TABLE_SIZE
)

# Cave6 bounds re-check — wrapper + table extend past AP_DESC_STRINGS,
# and must stay clear of the merit AP desc strings at 0x80096000.
assert AP_ICON_ID_TABLE_RAM + AP_ICON_ID_TABLE_SIZE <= 0x80096000, (
    f"Icon-id table end 0x{AP_ICON_ID_TABLE_RAM + AP_ICON_ID_TABLE_SIZE:08X} "
    f"collides with the merit AP desc strings at 0x80096000"
)
assert (AP_ICON_ID_TABLE_RAM + AP_ICON_ID_TABLE_SIZE <= _CAVE6_END_RAM), (
    f"Icon-id table end 0x{AP_ICON_ID_TABLE_RAM + AP_ICON_ID_TABLE_SIZE:08X} "
    f"overflows Cave6 end 0x{_CAVE6_END_RAM:08X}"
)

# Patch site: rewrite first 2 instructions of setItemTexture as
# ``j ROM_ICON_CLAMP_WRAPPER_RAM`` + ``nop`` (delay slot). Single 8-byte
# write. The trampoline reproduces the displaced bytes inline before
# returning to instr 3.
ROM_ICON_CLAMP_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_SET_ITEM_TEXTURE_RAM,
)
ROM_ICON_CLAMP_PATCH_FORMAT: Final = "<II"
ROM_ICON_CLAMP_PATCH_VALUE: Final = (
    0x08000000 | ((ROM_ICON_CLAMP_WRAPPER_RAM >> 2) & 0x03FFFFFF),  # j wrapper
    0x00000000,                                                      # nop
)


# --- ITEM_CLUT_DATA redirects (AP logo palette wiring) ----------------------
# ``setItemTexture`` picks each icon's palette via a 128-byte per-item
# table: ``clut = getClut(0xE0, ITEM_CLUT_DATA[item_id] + 0x1E8)``. The
# table lives in the SLUS data segment at RAM 0x80127BDC — immediately
# after ITEM_DESC_PTR (0x801279DC + 128*4), which itself follows
# ITEM_PARA. Single copy in the whole .bin (byte-pattern verified
# 2026-08-21 against the array in
# references/DW1-SydPatches/src/InventoryUI.cpp).
#
# Two one-byte redirects support the AP logo icon (see the "ITEM.TIM:
# AP logo icon" section above for the palette story):
#
# * entry 83 (vanilla 16, the shared gold ramp) -> 22, the CLUT the
#   patcher rewrites with :data:`AP_LOGO_CLUT_BYTES`.
# * entry 84 (Rainbowhorn, vanilla 22 and its sole consumer) -> 8, a
#   gold/khaki vanilla CLUT close to Rainbowhorn's original colors.
#   Its tile is requantized to CLUT 8 at patch-apply time so the horn
#   still renders faithfully.

ITEM_CLUT_DATA_RAM: Final = 0x80127BDC
ITEM_CLUT_DATA_ENTRIES: Final = 128
# Structural cross-check: the table starts right after
# ITEM_PARA (128 x 32 B) + ITEM_DESC_PTR (128 x 4 B).
assert ITEM_CLUT_DATA_RAM == (
    RAM_ITEM_PARA_KUSEG + 128 * ROM_ITEM_TABLE_ENTRY_SIZE + 128 * 4
)
# Vanilla anchor values for the two rewritten entries (ROM-gated tests
# byte-verify these against the source dump before trusting the patch).
ITEM_CLUT_DATA_VANILLA: Final[dict[int, int]] = {
    AP_ITEM_ICON_INDEX: 16,
    RAINBOWHORN_ITEM_ID: 22,
}


def item_clut_data_bin_offset(item_id: int) -> int:
    """Flat .bin offset of ``ITEM_CLUT_DATA[item_id]`` (one byte)."""

    assert 0 <= item_id < ITEM_CLUT_DATA_ENTRIES, item_id
    return _slus_ram_to_bin_offset(ITEM_CLUT_DATA_RAM + item_id)


# --- Recycle-shop array prebuild wrapper (fix UI name flicker) ------------
# The recycle shop's runtime [id, flag] * 7 array at RAM 0x80088828 is
# constructed by the engine when the player picks "I want a recycled
# item" from Tinmon's dialog. The shop UI then captures each row's name
# string from ITEM_PARA[array[i].id] at the moment each row first
# becomes visible — and caches it. Our client-side runtime reconciler
# (DigimonWorldClient._reconcile_recycle_shop_array) writes our AP IDs
# into the array each game-watcher tick (~100 ms cadence), but the
# engine builds the array within ~1 frame of the shop opening, so the
# UI captures vanilla names before our reconciler can intervene. The
# user has to scroll once to refresh each row, which then re-reads
# ITEM_PARA[id] using the freshly-patched array contents and finally
# shows the AP names.
#
# Static RE 2026-05-11 located the construction site:
#
#   Function ``build_shop_runtime_list`` at vanilla RAM 0x800FA834.
#   It's the sole shop-runtime-array writer that uses the canonical
#   gp-relative shop_obj indirection — ``lw r2, -0x6bc4(r28)`` at
#   0x800FA858, then `lw r16, 0(r2)` to load shop_obj.item_list_ptr
#   (= the array address, 0x80088828 when active). It clears
#   entry_count to 0, walks a static items table, and writes
#   [id, flag] pairs to the array (incrementing entry_count for each
#   accepted item). Called from the shop-state dispatcher around
#   0x800FC664+. Its epilogue at RAM 0x800FAA60 (jr $ra; addiu $sp,
#   +0x30) runs after all writes are done.
#
#   An earlier guess targeted ``init_shop_obj`` at 0x800A32F4 (which
#   memcpys a stack-local source to 0x80088804). User testing
#   2026-05-11 showed that patch was ineffective — names didn't
#   refresh. That function evidently isn't on the recycle-shop's
#   open-time call path, or it runs before the actual array writer.
#
# Fix: hijack ``build_shop_runtime_list``'s epilogue to ``j wrapper;
# nop``. The wrapper:
#   1. Reads entry_count from shop_obj+8 (= RAM 0x8008880C). If it's
#      not 7, this isn't the recycle shop variant — skip to the
#      original epilogue (don't break other shops the dispatcher might
#      route through this function).
#   2. If entry_count == 7, overwrites the 14-byte array at
#      RAM 0x80088828 with [128,1, 129,1, ..., 134,1] — our AP IDs.
#      Done synchronously inside the engine's call chain, so the shop
#      UI captures AP names from the very first frame.
#   3. Reproduces the original epilogue (jr $ra; addiu $sp, +0x30).
#
# The client-side reconciler stays as a defensive backstop.

ROM_RECYCLE_SHOP_INIT_RAM: Final = 0x800FA834               # function entry
ROM_RECYCLE_SHOP_INIT_EPILOGUE_RAM: Final = 0x800FAA60      # jr $r31 instr
# Hardcoded sp delta from the function's prologue:
# ``0x800FA834 addiu $r29, $r29, 0xffd0`` -> sp -= 0x30.
_RECYCLE_SHOP_INIT_SP_DELTA: Final = 0x30
# entry_count lives at shop_obj + 8 = 0x8008880C. addiu sign-extends
# 0x880C as -0x77F4, so ``lui 0x8009; addiu 0x880C`` resolves to
# 0x80090000 - 0x77F4 = 0x8008880C. Same trick as the merit shop
# wrapper's ITEM_PARA addressing (low half negative, high half +1).
_RECYCLE_SHOP_OBJ_ENTRY_COUNT_HI: Final = 0x8009
_RECYCLE_SHOP_OBJ_ENTRY_COUNT_LO: Final = 0x880C
_RECYCLE_SHOP_OBJ_ARRAY_OFFSET_FROM_ENTRY_COUNT: Final = 0x1C  # 0x80088828 - 0x8008880C

# RETIRED (2026-05+): no rom.py writer emits this wrapper any more — the
# shopsanity builder wrapper renders the AP rows synchronously instead.
# Its Cave6 region was reclaimed 2026-08-21 by the icon-id table
# (:data:`AP_ICON_ID_TABLE_RAM`); this derived address now points INTO
# that table and must never be written again.
ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM: Final = (
    ROM_ICON_CLAMP_WRAPPER_RAM + len(ROM_ICON_CLAMP_WRAPPER_BYTES)
)
# Round up to 4-byte alignment (the icon clamp wrapper ends at a
# multiple of 4 already, but document the constraint).
assert ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM % 4 == 0, (
    f"ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM 0x{ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM:08X} "
    f"is not 4-byte aligned"
)
ROM_RECYCLE_SHOP_INIT_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM,
)


def _build_recycle_shop_init_wrapper_bytes() -> bytes:
    """Build the recycle-shop init epilogue wrapper.

    23 instructions / 92 bytes. See section above for the dispatch
    semantics.

    Layout::

        # Check entry_count at 0x8008880C
        lui   $t0, 0x8009
        addiu $t0, $t0, 0x880C            ; t0 = 0x8008880C
        lbu   $t1, 0($t0)                 ; t1 = entry_count
        addiu $t2, $0, 7
        bne   $t1, $t2, .skip             ; not recycle shop -> skip
        nop                                ; bne delay slot

        # entry_count == 7. Overwrite the 14-byte array at 0x80088828
        # with [128,1, 129,1, ..., 134,1]. Each entry encodes as a
        # little-endian halfword: low byte = id, high byte = flag = 1.
        addiu $t0, $t0, 0x1C              ; t0 = 0x80088828 (array)
        addiu $t1, $0, 0x0180              ; entry 0 (id=128, flag=1)
        sh    $t1, 0($t0)
        addiu $t1, $0, 0x0181
        sh    $t1, 2($t0)
        ...
        addiu $t1, $0, 0x0186              ; entry 6 (id=134, flag=1)
        sh    $t1, 12($t0)

        .skip:
        # Reproduce the displaced epilogue (was at RAM 0x800FAA60)
        jr    $ra
        addiu $sp, $sp, 0x30               ; jr delay slot
    """

    import struct as _struct

    BASE_ID = RECYCLE_SHOP_AP_ITEM_ID_BASE
    COUNT = RECYCLE_SHOP_AP_ITEM_ID_COUNT
    SP_DELTA = _RECYCLE_SHOP_INIT_SP_DELTA

    # Branch target = .skip = jr $ra at index 21 (counting from 0).
    # The bne is at index 4. MIPS offset = (target - branch - 1) = 16.
    BNE_TO_SKIP = 0x15400000 | (16 & 0xFFFF)  # bne $t2, $0, +16 — see below

    # We compare $t1 (entry_count) to $t2 (=7). bne $t1, $t2, +16:
    # rs=$t1=9, rt=$t2=10. opcode 5. = 0x14 << 26 | 9<<21 | 10<<16 | 16.
    BNE_NEQ_SEVEN = (0x05 << 26) | (9 << 21) | (10 << 16) | 16

    instructions: list[int] = [
        # entry_count check
        0x3C088009,                                        # lui $t0, 0x8009
        0x25080000 | (_RECYCLE_SHOP_OBJ_ENTRY_COUNT_LO    # addiu $t0, $t0, 0x880C
                      & 0xFFFF),
        0x91090000,                                        # lbu $t1, 0($t0)
        0x240A0000 | (RECYCLE_SHOP_ENTRY_COUNT & 0xFFFF),  # addiu $t2, $0, 7
        BNE_NEQ_SEVEN,                                     # bne $t1, $t2, +16
        0x00000000,                                        # nop (bne delay)
        # Slide t0 from entry_count addr to array addr (+0x1C)
        0x25080000 | (_RECYCLE_SHOP_OBJ_ARRAY_OFFSET_FROM_ENTRY_COUNT
                      & 0xFFFF),                           # addiu $t0, $t0, 0x1C
    ]
    # 7 entries: addiu $t1, $0, 0x01<id>; sh $t1, 2*i($t0)
    for i in range(COUNT):
        id_byte = (BASE_ID + i) & 0xFF
        # Little-endian halfword: low byte = id, high byte = flag (1).
        halfword_value = (0x01 << 8) | id_byte
        instructions.append(0x24090000 | halfword_value)   # addiu $t1, $0, halfword
        instructions.append(0xA5090000 | (i * 2))          # sh $t1, (2*i)($t0)

    # .skip: jr $ra; addiu $sp, $sp, 0x48
    instructions.append(0x03E00008)                        # jr $r31
    instructions.append(0x27BD0000 | (SP_DELTA & 0xFFFF))  # addiu $r29, $r29, 0x48

    return b"".join(_struct.pack("<I", v) for v in instructions)


ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES: Final = (
    _build_recycle_shop_init_wrapper_bytes()
)
# 6 setup + 1 slide + 14 writes + 2 epilogue = 23 instructions = 92 bytes.
assert len(ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES) == 92, (
    len(ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES)
)

# Cave6 bounds — wrapper extends past the icon clamp wrapper.
assert (ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM
        + len(ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES) <= _CAVE6_END_RAM), (
    f"Recycle shop init wrapper end "
    f"0x{ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM + len(ROM_RECYCLE_SHOP_INIT_WRAPPER_BYTES):08X} "
    f"overflows Cave6 end 0x{_CAVE6_END_RAM:08X}"
)

# Patch site: rewrite the function's last 8 bytes (jr $r31; addiu $sp, +0x48)
# as ``j wrapper; nop``. The wrapper reproduces the displaced bytes
# inline before returning.
ROM_RECYCLE_SHOP_INIT_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_RECYCLE_SHOP_INIT_EPILOGUE_RAM,
)
ROM_RECYCLE_SHOP_INIT_PATCH_FORMAT: Final = "<II"
ROM_RECYCLE_SHOP_INIT_PATCH_VALUE: Final = (
    0x08000000 | ((ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM >> 2) & 0x03FFFFFF),
    0x00000000,
)


# =============================================================================
# Merit Shop (Volume Villa, ShogunGekomon) — full AP randomization
# =============================================================================
#
# Extends the merit shop from the v1 single-slot AP-Item flow (slot 83 ->
# trigger 903 = ``Amazing Rod Pickup``) to full AP randomization with all
# 14 vanilla merit-shop entries replaced by AP locations. Builds on the
# recycle shop's extended-ITEM_PARA + relocated-ITEM_DESC_PTR
# infrastructure (already shipping in Cave6).
#
# **Architecture (locked):**
#
# The merit shop is engine-driven: on open, the function at
# RAM 0x801072C4 walks ITEM_PARA from id 0 to bound ``< 0x80`` and
# includes any entry whose ``meritValue`` is non-zero. We extend that
# scan to cover slots 128..148 by patching the loop bound at
# RAM 0x00107430 from ``sltiu $r1, $r5, 0x0080`` to
# ``sltiu $r1, $r5, 0x0095`` (= 149). Slots 135..148 hold the 14 AP
# merit-shop entries (one per vanilla merit-shop item); each entry's
# ``meritValue`` is the vanilla merit price of the slot it replaces, so
# the displayed cost is preserved. We zero each vanilla entry's
# ``meritValue`` so the vanilla item rows disappear.
#
# Each AP row's name (in ITEM_PARA[135 + i].name) is the multiworld-
# resolved AP item name truncated to 14 chars. Each row's description
# (via the relocated ITEM_DESC_PTR[135 + i]) is "From <player>'s World".
# A new 14-entry AP description-string region lives at the start of
# Cave6's free zone, AFTER the recycle shop's existing structures.
#
# A wrapper at the merit shop's existing giveItem callsite (RAM
# 0x8010BF3C, already hijacked in v1 to RAM 0x80095800) is *re*-targeted
# when MeritShopLocations is on: the jal hijack is overridden to point
# at an extended-dispatch wrapper at RAM 0x80096338 that handles N=15
# dispatch entries — slot 83 (trigger 903, the v1 ``Amazing Rod Pickup``
# row, kept) plus slots 135..148 (triggers 912..925). Each match fires
# ``setTrigger(trigger_id)`` for the AP signal, then memcpys the slot
# 114 "AP Item Bought" sentinel over the dispatched slot (same dead
# code path as the v1 wrapper — preserved for shape consistency) and
# returns without delivering an item. Money / merits are still deducted
# by the surrounding shop logic before this jal.
#
# The N=1 wrapper at RAM 0x80095800 still ships always-on but is dead
# code when MeritShopLocations is on (the jal override points elsewhere).
# This zero-touches the v1 single-slot flow when the option is off.
#
# **RE source:** docs/merit_shop.md and the static probe at
# tools/dw1_merit_inventory.py. Inventory enumerated via the probe:
# 14 entries (sup.recovery, Sup.restore, 6× Chips, Rainbowhorn, 4× 500-
# merit consumables, Amazing rod) — verified against
# Digimon World (USA).bin SHA-1 5611645D...

# --- AP slot / trigger / location allocations -------------------------------
#
# With the always-on 256-slot relocation, ext slots 128..255 all live
# contiguously inside the relocated table — the historical hard ceiling
# at slot 143 (the item-color table at RAM 0x80127BDC that capped the
# freed-ITEM_DESC_PTR era, verified 2026-05-13) no longer applies. The
# staging ceiling is the .bin-backed EXT_ITEM_PARA seed block: 30 slots
# (128..157). Recycle shop uses 128..134; merit shop uses 135..148;
# 149..157 are headroom for future shops.
MERIT_SHOP_AP_ITEM_ID_BASE: Final = 135
MERIT_SHOP_AP_ITEM_ID_COUNT: Final = 14
MERIT_SHOP_AP_ITEM_IDS: Final = tuple(
    MERIT_SHOP_AP_ITEM_ID_BASE + i
    for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT)
)
# Highest used extended slot (148 = 135 + 13). All 14 slots live at
# their natural positions in the relocated table, staged via the
# EXT_ITEM_PARA seed block. The scan-loop bound patch below uses
# 149 (= 148 + 1) so the scan reaches up through slot 148.
MERIT_SHOP_AP_ITEM_ID_LAST: Final = (
    MERIT_SHOP_AP_ITEM_ID_BASE + MERIT_SHOP_AP_ITEM_ID_COUNT - 1            # 148
)
# Sanity: must come after recycle shop's range (128..134) and stay
# inside the single ext-slot segment supported by
# ext_item_para_slot_bin_offset (seed slots 128..157).
assert MERIT_SHOP_AP_ITEM_ID_BASE == RECYCLE_SHOP_AP_ITEM_ID_BASE + RECYCLE_SHOP_AP_ITEM_ID_COUNT, (
    f"merit-shop slot base 0x{MERIT_SHOP_AP_ITEM_ID_BASE:X} should follow "
    f"recycle-shop end 0x{RECYCLE_SHOP_AP_ITEM_ID_BASE + RECYCLE_SHOP_AP_ITEM_ID_COUNT:X}"
)

# AP location triggers — allocated 912..920 (9 triggers, follows recycle's
# 904..910 with bit 7 of byte 0x001BE03E left free as 911).
#
# **Range justification**: 912..919 = bits 0..7 of byte 0x001BE03F;
# 920 = bit 0 of byte 0x001BE040. Bits 1..7 of byte 0x001BE040 stay
# free for future expansion (921..927). Trigger 928 starts byte
# 0x001BE041, also free. The danger zone begins at byte 0x001BE042
# (:data:`RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE`). All 9 triggers stay
# well clear.
MERIT_SHOP_TRIGGER_BASE: Final = 912
MERIT_SHOP_TRIGGER_COUNT: Final = MERIT_SHOP_AP_ITEM_ID_COUNT
MERIT_SHOP_TRIGGER_IDS: Final = tuple(
    MERIT_SHOP_TRIGGER_BASE + i for i in range(MERIT_SHOP_TRIGGER_COUNT)
)
# Sanity: trigger bytes stay within the unused 0x001BE03F..0x001BE041 gap.
_MERIT_TRIG_BYTES = {
    AP_TRIGGER_ARRAY_BASE + (t // 8) for t in MERIT_SHOP_TRIGGER_IDS
}
assert _MERIT_TRIG_BYTES == {0x001BE03F, 0x001BE040}, (
    f"merit shop triggers spilled out of the 0x001BE03F..0x001BE040 gap: "
    f"{[hex(b) for b in sorted(_MERIT_TRIG_BYTES)]}"
)
assert max(_MERIT_TRIG_BYTES) < RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE, (
    f"merit shop trigger range overflows into RAM_MERAMON_TUNNEL at "
    f"0x{RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE:08X}: max byte "
    f"0x{max(_MERIT_TRIG_BYTES):08X}"
)

# Full vanilla merit-shop inventory — verified 2026-05-13 via
# tools/dw1_merit_inventory probe against Digimon World (USA).bin (SHA-1
# 5611645D...). 14 entries with ``meritValue > 0`` in ITEM_PARA.
#
# Used by the patcher to drive both:
# 1. Per-slot vanilla ``meritValue`` zero-outs (vanilla rows disappear
#    from the shop).
# 2. Per-AP-slot displayed merit price — slot
#    ``MERIT_SHOP_AP_ITEM_ID_BASE + i`` inherits
#    ``MERIT_SHOP_VANILLA_ENTRIES[i][2]`` so the shop shows the same
#    merit cost the vanilla row would have.
#
# All 14 entries become AP slots 135..148 at their natural positions
# in the relocated 256-slot table (staged via the EXT_ITEM_PARA seed
# block, copied in at boot).
#
# Format: ``(slot_id, name_for_docs, vanilla_merit_value)``. The order
# is by slot_id ascending, matching the merit shop's display order
# (since the engine's scan walks ITEM_PARA from id 0 up).
MERIT_SHOP_VANILLA_ENTRIES: Final[tuple[tuple[int, str, int], ...]] = (
    (0x03, "sup.recovery",   20),  # value=2500   -> Merit Shop #1
    (0x0C, "Sup.restore",   100),  # value=9500   -> Merit Shop #2
    (0x17, "Off. Chip",     800),  # value=9999   -> Merit Shop #3
    (0x18, "Def. Chip",     800),  # value=9999   -> Merit Shop #4
    (0x19, "Brain Chip",    800),  # value=9999   -> Merit Shop #5
    (0x1A, "Quick Chip",    800),  # value=9999   -> Merit Shop #6
    (0x1B, "HP Chip",       800),  # value=9999   -> Merit Shop #7
    (0x1C, "MP Chip",       800),  # value=9999   -> Merit Shop #8
    (0x54, "Rainbowhorn",   500),  # value=5000   -> Merit Shop #9
    (0x5B, "Waterbottle",   500),  # value=5000   -> Merit Shop #10  (ext slot 144)
    (0x5D, "Red Shell",     500),  # value=5000   -> Merit Shop #11  (ext slot 145)
    (0x5E, "Hard Scale",    500),  # value=5000   -> Merit Shop #12  (ext slot 146)
    (0x60, "Ice crystal",   500),  # value=5000   -> Merit Shop #13  (ext slot 147)
    (0x75, "Amazing rod",   300),  # value=3000   -> Merit Shop #14  (ext slot 148)
)
assert len(MERIT_SHOP_VANILLA_ENTRIES) == MERIT_SHOP_AP_ITEM_ID_COUNT, (
    len(MERIT_SHOP_VANILLA_ENTRIES), MERIT_SHOP_AP_ITEM_ID_COUNT,
)

# AP location names — index matches MERIT_SHOP_VANILLA_ENTRIES order.
MERIT_SHOP_LOCATION_NAMES: Final = tuple(
    f"Merit Shop #{i + 1}"
    for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT)
)

# Per-location (byte_addr, bit_index) for the client's bit-poll table.
MERIT_SHOP_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    name: (
        AP_TRIGGER_ARRAY_BASE + (MERIT_SHOP_TRIGGER_IDS[i] // 8),
        MERIT_SHOP_TRIGGER_IDS[i] % 8,
    )
    for i, name in enumerate(MERIT_SHOP_LOCATION_NAMES)
}

# --- AP description strings for the 9 merit-shop slots ---------------------
# **Sector alignment**: the patcher's :func:`apply_tokens` writes bytes
# **flat** into the .bin (no sector-hop awareness inside a single token
# write). Mode2/2352 sectors are 2352 bytes with a 24-byte header + 2048
# user-data + 280 EC. A flat write that spans more than one sector's
# user-data region clobbers the EC zone (harmless — recalc_edc rewrites
# it) **and** the next sector's HEADER zone (NOT harmless — corrupts the
# sector sync pattern, making the PSX CD-ROM unable to reliably load
# that sector's user-data; the bytes we *wanted* there never make it
# into RAM at boot).
#
# Concretely: an earlier revision placed the merit AP desc strings at
# RAM 0x80095FB8 (= sector 148349 ud-byte 1976). The 576-byte flat write
# clobbered sector 148350's 24-byte header, so sector 148350 didn't load
# correctly — and the merit extended wrapper, also in sector 148350, ran
# as whatever garbage happened to be at the wrapper's RAM location. The
# game froze on first OK press in the merit shop ("frozen image, audio
# loops" symptom).
#
# Fix: align the merit AP desc strings region to a sector boundary so
# the 576-byte write stays inside one sector. The first sector-boundary
# RAM address in Cave6 *past* the recycle init wrapper (which ends at
# RAM 0x80095FB8) is sector 148350 ud-byte 0 = RAM 0x80096000. That
# leaves a 72-byte gap at 0x80095FB8..0x80096000; acceptable trade-off.
# All subsequent merit-shop pieces stack from 0x80096000 onwards and
# also stay inside sector 148350's 2048-byte ud-region.
MERIT_AP_DESC_STRINGS_RAM: Final = 0x80096000
# 4-byte align (sector-aligned, always a multiple of 4).
assert MERIT_AP_DESC_STRINGS_RAM % 4 == 0, hex(MERIT_AP_DESC_STRINGS_RAM)
MERIT_AP_DESC_STRINGS_BIN_OFFSET: Final = _slus_ram_to_bin_offset(
    MERIT_AP_DESC_STRINGS_RAM,
)
MERIT_AP_DESC_STRINGS_TOTAL_SIZE: Final = (
    AP_DESC_STRING_MAX_LEN * MERIT_SHOP_AP_ITEM_ID_COUNT                     # 576
)
# Sanity: desc strings region must stay inside one Mode2/2352 sector.
# Sector ud-region is 2048 bytes; we start at ud-byte 0 of sector 148350
# and write MERIT_AP_DESC_STRINGS_TOTAL_SIZE bytes.
assert MERIT_AP_DESC_STRINGS_TOTAL_SIZE <= 2048, (
    f"merit AP desc strings size {MERIT_AP_DESC_STRINGS_TOTAL_SIZE} > 2048; "
    f"a single flat token write would cross a sector boundary and corrupt "
    f"the next sector's header"
)

# --- Extended merit-shop wrapper (N=10: slot 83 + slots 135..143) -----------
# Sits in Cave6 after the merit-shop AP description strings. Built with
# the same dispatch shape as :func:`_build_merit_shop_wrapper_bytes` so
# the N=1 wrapper at 0x80095800 stays semantically identical for the
# option-off path; only the dispatch table size changes.
#
# Wrapper size = (38 + 7 * N) * 4 bytes where N = 10 (slot 83 + 9 merit-
# shop AP slots) = (38 + 70) * 4 = 432 bytes.
ROM_MERIT_SHOP_EXT_WRAPPER_RAM: Final = (
    MERIT_AP_DESC_STRINGS_RAM + MERIT_AP_DESC_STRINGS_TOTAL_SIZE             # 0x80096240
)
assert ROM_MERIT_SHOP_EXT_WRAPPER_RAM % 4 == 0, hex(ROM_MERIT_SHOP_EXT_WRAPPER_RAM)
ROM_MERIT_SHOP_EXT_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_SHOP_EXT_WRAPPER_RAM,
)
# Sanity: extended wrapper must stay inside one Mode2/2352 sector
# (apply_tokens does flat writes; crossing a boundary corrupts the
# next sector's header — see MERIT_AP_DESC_STRINGS_RAM block comment).
# Sector ud-region is 2048 bytes; wrapper at RAM 0x80096240 starts at
# sector 148350 ud-byte 576 and runs for 432 bytes = ud-byte 1008 end.
# Both well within the 2048-byte limit.
_MERIT_EXT_WRAPPER_SECTOR_UD_START: Final = (
    ROM_MERIT_SHOP_EXT_WRAPPER_RAM - 0x80096000                              # 576
)
assert (_MERIT_EXT_WRAPPER_SECTOR_UD_START + (38 + 7 * (1 + MERIT_SHOP_AP_ITEM_ID_COUNT)) * 4
        <= 2048), (
    f"extended merit wrapper at ud-byte {_MERIT_EXT_WRAPPER_SECTOR_UD_START} + "
    f"{(38 + 7 * (1 + MERIT_SHOP_AP_ITEM_ID_COUNT)) * 4} bytes would cross a "
    f"sector boundary"
)

# Full N=15 dispatch table = slot 83 (kept as ``Amazing Rod Pickup``) +
# 14 extended slots. Order: slot 83 first (matches the existing N=1
# wrapper's behavior for that slot), then slots 135..148 in ascending
# order matching MERIT_SHOP_VANILLA_ENTRIES / MERIT_SHOP_LOCATION_NAMES.
MERIT_SHOP_EXT_DISPATCH: Final[tuple[tuple[int, int], ...]] = (
    (AP_CHEST_SENTINEL_ITEM_ID, AMAZING_ROD_LOCATION_TRIGGER_ID),
    *(
        (MERIT_SHOP_AP_ITEM_ID_BASE + i, MERIT_SHOP_TRIGGER_BASE + i)
        for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT)
    ),
)
assert len(MERIT_SHOP_EXT_DISPATCH) == 1 + MERIT_SHOP_AP_ITEM_ID_COUNT       # 15


def _build_merit_shop_ext_wrapper_bytes() -> bytes:
    """Build the extended merit-shop wrapper (N=15).

    Identical shape to :func:`_build_merit_shop_wrapper_bytes`, but
    parameterised on :data:`MERIT_SHOP_EXT_DISPATCH` instead of
    :data:`MERIT_SHOP_DISPATCH`. The wrapper lives at
    :data:`ROM_MERIT_SHOP_EXT_WRAPPER_RAM` so the ``j mark_bought``
    target is recomputed for that base.

    Bytecode is decode-verified at module load (see the bottom of this
    block): each emitted u32 must round-trip through the standard
    ``(opcode << 26) | (rs << 21) | (rt << 16) | imm`` decomposition.
    """

    import struct as _struct

    SETTRIGGER_RAM = 0x801065C0
    GIVEITEM_RAM = 0x800C5240
    # ITEM_PARA relocation (always-on): mark_bought targets the
    # RELOCATED table — see the v1 builder's comment. For ext slots
    # 135..148 the destination RELOC + slot*32 is a plain data slot
    # inside the 8 KB table (the old architecture's color-table /
    # desc-ptr clobber hazard is gone).
    ITEM_PARA_BASE = ITEM_PARA_RELOC_BASE_KUSEG
    SENTINEL_RAM = (
        ITEM_PARA_RELOC_BASE_KUSEG
        + AP_SHOP_BOUGHT_SENTINEL_ITEM_ID * ROM_ITEM_TABLE_ENTRY_SIZE       # 0x801C09B0
    )

    n_entries = len(MERIT_SHOP_EXT_DISPATCH)
    # mark_bought RAM address = wrapper start + prologue (16) +
    # per-entry blocks (28 * N) + give_item path (24).
    mark_bought_offset = 0x10 + 28 * n_entries + 0x18
    mark_bought_ram = ROM_MERIT_SHOP_EXT_WRAPPER_RAM + mark_bought_offset
    j_mark = 0x08000000 | ((mark_bought_ram >> 2) & 0x03FFFFFF)
    j_giveitem = 0x08000000 | ((GIVEITEM_RAM >> 2) & 0x03FFFFFF)
    jal_settrigger = 0x0C000000 | ((SETTRIGGER_RAM >> 2) & 0x03FFFFFF)

    # Sign-extension-aware decomposition; the relocated base 0x801BFB70
    # has low half 0xFB70 >= 0x8000, so the lui hi becomes 0x801C.
    item_para_hi, item_para_lo = _decompose_kuseg(ITEM_PARA_BASE)
    sentinel_hi, sentinel_lo = _decompose_kuseg(SENTINEL_RAM)

    out = bytearray()

    # --- Prologue (4 instrs, 16 B) -----------------------------------------
    out += _struct.pack("<I", 0x27BDFFF0)  # addiu $sp, $sp, -0x10
    out += _struct.pack("<I", 0xAFBF000C)  # sw    $ra, 0x0C($sp)
    out += _struct.pack("<I", 0xAFA40008)  # sw    $a0, 0x08($sp)
    out += _struct.pack("<I", 0xAFA50004)  # sw    $a1, 0x04($sp)

    # --- Per-entry blocks (7 instrs / 28 B each) ---------------------------
    BNE_OFFSET_5 = 0x14810005
    for item_id, trigger_id in MERIT_SHOP_EXT_DISPATCH:
        if not (0 <= item_id <= 0xFF):
            raise ValueError(f"item_id {item_id} out of u8 range")
        if not (0 <= trigger_id <= 0xFFFF):
            raise ValueError(f"trigger_id {trigger_id} out of u16 range")
        # addiu $at, $0, item_id
        out += _struct.pack("<I", 0x24010000 | (item_id & 0xFFFF))
        # bne $a0, $at, +5
        out += _struct.pack("<I", BNE_OFFSET_5)
        out += _struct.pack("<I", 0x00000000)  # nop (bne delay slot)
        # jal setTrigger
        out += _struct.pack("<I", jal_settrigger)
        # addiu $a0, $0, trigger_id (jal delay slot)
        out += _struct.pack("<I", 0x24040000 | (trigger_id & 0xFFFF))
        # j mark_bought
        out += _struct.pack("<I", j_mark)
        out += _struct.pack("<I", 0x00000000)  # nop (j delay slot)

    # --- give_item path (6 instrs, 24 B) ----------------------------------
    out += _struct.pack("<I", 0x8FBF000C)  # lw    $ra, 0x0C($sp)
    out += _struct.pack("<I", 0x8FA40008)  # lw    $a0, 0x08($sp)
    out += _struct.pack("<I", 0x8FA50004)  # lw    $a1, 0x04($sp)
    out += _struct.pack("<I", 0x27BD0010)  # addiu $sp, $sp, 0x10
    out += _struct.pack("<I", j_giveitem)  # j     0x800C5240
    out += _struct.pack("<I", 0x00000000)  # nop

    # --- mark_bought path (28 instrs, 112 B) -------------------------------
    # (item_para_hi/lo and sentinel_hi/lo declared above via
    # _decompose_kuseg; reuse here.)

    out += _struct.pack("<I", 0x8FA40008)  # lw $a0, 0x08($sp)
    out += _struct.pack("<I", 0x00045140)  # sll $t2, $a0, 5
    out += _struct.pack("<I", 0x3C090000 | item_para_hi)
    out += _struct.pack("<I", 0x25290000 | item_para_lo)
    out += _struct.pack("<I", 0x01495021)  # addu $t2, $t2, $t1
    out += _struct.pack("<I", 0x3C080000 | sentinel_hi)
    out += _struct.pack("<I", 0x25080000 | sentinel_lo)
    for off in (0, 4, 8, 12, 16, 20, 24, 28):
        out += _struct.pack("<I", 0x8D0B0000 | off)
        out += _struct.pack("<I", 0xAD4B0000 | off)
    out += _struct.pack("<I", 0x8FBF000C)
    out += _struct.pack("<I", 0x8FA50004)
    out += _struct.pack("<I", 0x27BD0010)
    out += _struct.pack("<I", 0x03E00008)
    out += _struct.pack("<I", 0x24020001)

    return bytes(out)


ROM_MERIT_SHOP_EXT_WRAPPER_BYTES: Final = _build_merit_shop_ext_wrapper_bytes()
# 4 prologue + 6 give_item + 28 mark_bought + 7 per dispatch entry.
assert len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) == (
    (38 + 7 * len(MERIT_SHOP_EXT_DISPATCH)) * 4
), (
    len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES), len(MERIT_SHOP_EXT_DISPATCH),
)
# = 572 bytes for N=15.

# Cave6 bounds re-check — extended wrapper extends past the merit AP
# desc strings.
assert (ROM_MERIT_SHOP_EXT_WRAPPER_RAM
        + len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) <= _CAVE6_END_RAM), (
    f"Extended merit-shop wrapper end "
    f"0x{ROM_MERIT_SHOP_EXT_WRAPPER_RAM + len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES):08X} "
    f"overflows Cave6 end 0x{_CAVE6_END_RAM:08X}"
)


# --- Wrapper-bytecode decode-verify (sanity) --------------------------------
# Re-decode every emitted instruction in
# :data:`ROM_MERIT_SHOP_EXT_WRAPPER_BYTES` and confirm a handful of
# load-bearing pieces round-trip correctly. This catches any encoding
# typo before it ships — the recycle shop's prebuild wrapper had to be
# reverted after two encoding bugs slipped through review (see git
# 0xb5b16796).
def _verify_merit_shop_ext_wrapper_bytecode() -> None:
    import struct as _struct

    expected_n = len(MERIT_SHOP_EXT_DISPATCH)
    n_words = len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES) // 4
    words = list(_struct.unpack(f"<{n_words}I", ROM_MERIT_SHOP_EXT_WRAPPER_BYTES))

    # Prologue: 4 instructions starting at index 0.
    assert words[0] == 0x27BDFFF0, hex(words[0])  # addiu $sp, $sp, -0x10
    assert words[1] == 0xAFBF000C, hex(words[1])  # sw $ra, 0x0C($sp)
    assert words[2] == 0xAFA40008, hex(words[2])  # sw $a0, 0x08($sp)
    assert words[3] == 0xAFA50004, hex(words[3])  # sw $a1, 0x04($sp)

    # Per-entry: 7 instructions × N starting at index 4.
    for i, (item_id, trigger_id) in enumerate(MERIT_SHOP_EXT_DISPATCH):
        base = 4 + i * 7
        w_addiu_at = words[base + 0]
        # addiu $at, $0, item_id: opcode 9, rs=0, rt=1, imm=item_id
        opcode = (w_addiu_at >> 26) & 0x3F
        rs = (w_addiu_at >> 21) & 0x1F
        rt = (w_addiu_at >> 16) & 0x1F
        imm = w_addiu_at & 0xFFFF
        assert (opcode, rs, rt, imm) == (9, 0, 1, item_id), (
            f"dispatch[{i}] addiu mismatch: word=0x{w_addiu_at:08X}, "
            f"got (op={opcode}, rs={rs}, rt={rt}, imm={imm}), "
            f"want (op=9, rs=0, rt=1, imm={item_id})"
        )
        # bne $a0, $at, +5: opcode 5, rs=4 ($a0), rt=1 ($at), imm=5
        w_bne = words[base + 1]
        opcode = (w_bne >> 26) & 0x3F
        rs = (w_bne >> 21) & 0x1F
        rt = (w_bne >> 16) & 0x1F
        imm = w_bne & 0xFFFF
        assert (opcode, rs, rt, imm) == (5, 4, 1, 5), (
            f"dispatch[{i}] bne mismatch: word=0x{w_bne:08X}"
        )
        # nop
        assert words[base + 2] == 0
        # jal setTrigger (0x801065C0)
        w_jal = words[base + 3]
        opcode = (w_jal >> 26) & 0x3F
        target = (w_jal & 0x03FFFFFF) << 2
        assert (opcode, target) == (3, 0x801065C0 & 0x0FFFFFFC), (
            f"dispatch[{i}] jal target mismatch: word=0x{w_jal:08X}, "
            f"got target=0x{target:08X}"
        )
        # addiu $a0, $0, trigger_id
        w_addiu_a0 = words[base + 4]
        opcode = (w_addiu_a0 >> 26) & 0x3F
        rs = (w_addiu_a0 >> 21) & 0x1F
        rt = (w_addiu_a0 >> 16) & 0x1F
        imm = w_addiu_a0 & 0xFFFF
        assert (opcode, rs, rt, imm) == (9, 0, 4, trigger_id), (
            f"dispatch[{i}] jal-delay addiu mismatch: word=0x{w_addiu_a0:08X}"
        )
        # j mark_bought
        w_j = words[base + 5]
        opcode = (w_j >> 26) & 0x3F
        target = (w_j & 0x03FFFFFF) << 2
        # mark_bought = wrapper_ram + prologue(16) + per_entry(28*N) + giveitem(24)
        mark_bought_ram = (
            ROM_MERIT_SHOP_EXT_WRAPPER_RAM + 0x10 + 28 * expected_n + 0x18
        )
        assert (opcode, target) == (2, mark_bought_ram & 0x0FFFFFFC), (
            f"dispatch[{i}] j mark_bought mismatch: word=0x{w_j:08X}, "
            f"got target=0x{target:08X}, want 0x{mark_bought_ram & 0x0FFFFFFC:08X}"
        )
        # nop (j delay slot)
        assert words[base + 6] == 0, hex(words[base + 6])

    # give_item path: 6 instructions starting at 4 + 7*N.
    base = 4 + 7 * expected_n
    assert words[base + 0] == 0x8FBF000C, hex(words[base + 0])  # lw $ra
    assert words[base + 1] == 0x8FA40008, hex(words[base + 1])  # lw $a0
    assert words[base + 2] == 0x8FA50004, hex(words[base + 2])  # lw $a1
    assert words[base + 3] == 0x27BD0010, hex(words[base + 3])  # addiu $sp
    # j giveItem (0x800C5240)
    w_jg = words[base + 4]
    opcode = (w_jg >> 26) & 0x3F
    target = (w_jg & 0x03FFFFFF) << 2
    assert (opcode, target) == (2, 0x800C5240 & 0x0FFFFFFC), hex(w_jg)
    assert words[base + 5] == 0  # nop


_verify_merit_shop_ext_wrapper_bytecode()


# =============================================================================
# ITEM_PARA 256-slot relocation (always-on)
# =============================================================================
#
# Successor of BOTH the Path A wholesale relocation (reverted — history
# note below) and the Cave6 multi-segment ext architecture (retired
# 2026-08-21 by this section: the Cave6 ext segment at 0x80096800 and
# the merit scan/name/row/deduct teleport wrappers are gone; the seed
# block below reuses the ext segment's footprint, and the boot seed
# hook reuses the scan/name teleport wrappers' footprint).
#
# Lab-validated 2026-08-20 through all three PATCH_PROCESS nets
# including a confirming build booted from disc into real gameplay:
# ``work/dw1_re/decomp/item_para_reloc/NOTES.md``, spec builder
# ``work/dw1_re/patches/item_para_reloc_spec.py``, allocator invariants
# in ``work/dw1_re/decomp/_scan_flavor_a_region/HEAP_CLAIM_DESIGN.md``
# and ``work/dw1_re/decomp/heap3/NOTES.md``.
#
# Design (three always-on pieces):
#
# 1. **Heap claim (1 word)** — the end-of-bss configuration word at RAM
#    0x80113AB4 (dw_decomp names it ``_end``; ``initializeHeap`` @ 0x800EEBDC
#    computes ``heap = (_end & ~0xF) + 0x10`` and sizes it from
#    ``_stack_addr`` 0x801FFF00 / ``_stack_size`` 0x40, giving the arena end
#    0x801EFF00; ``_heap_size`` @ 0x80113AA8 is unused) moves the malloc3
#    arena base from 0x801BFB64 to 0x801C1B64. Boot then runs ``InitHeap3(0x801C1B70, 0x2E390)``; the
#    arena sentinel at 0x801EFEF8 is unchanged. The vacated region
#    0x801BFB70..0x801C1B70 is EXACTLY 256 x 32 B — the relocated table
#    fills it with zero spare bytes.
# 2. **Boot seed hook** — the claimed region is not .bin-backed, so a
#    Cave6 wrapper seeds it at boot. We hijack master-init
#    FUN_800EE800's FIRST call (``jal 0x800EEBDC`` at RAM 0x800EE80C,
#    delay-slot nop; verified in the .bin). The wrapper makes its own
#    stack frame, calls the displaced callee (which tail-jumps
#    ``InitHeap3`` — captured boot ra 0x800EE814 confirms), then runs
#    three tight loops: copy vanilla+tokens ITEM_PARA (4 KB from
#    0x801269DC — apply_tokens keeps writing slots 83/114/117 at the
#    old location, so the copies carry the AP entries), zero the upper
#    4 KB (slots 128..255), and copy the EXT_ITEM_PARA seed block
#    (960 B from Cave6) over slots 128..157. The zero loop's last
#    store ends at 0x801C1B6C — it never touches the new arena base
#    block header at 0x801C1B70. Re-runs on every disc boot / soft
#    reset (idempotent; the table is runtime-read-only except the
#    merit wrappers' mark_bought sentinel copy).
# 3. **Reader patches (31 sites, 62 words)** — every lui+addiu pair in
#    the game that constructs the vanilla ITEM_PARA address 0x801269DC
#    (+field) is re-based to the relocated table: 24 SLUS sites and 7
#    overlay sites (1 in BTL_REL.BIN — the battle-results "#C1 dropped
#    #C7" item-name render; 6 in FISH_REL.BIN — fishing/bait UI).
#    Census (lab, 2026-08-20): exhaustive scan of the SLUS and ALL 16
#    extracted overlays for lui+addiu / lui+loadstore pairs AND
#    embedded u32 pointer constants into the table range — SLUS =
#    exactly these 24, embedded pointer constants = ZERO anywhere,
#    overlays = exactly these 7 (SHOP_REL is clean; shop machinery
#    lives in the SLUS). All re-based targets fall in the lui
#    sign-extension window, so every patched lui hi-half is 0x801C and
#    every patched addiu low half is 0xFB70 + field. Overlays reload
#    from disc per activation, so the 7 overlay sites are patched at
#    their .bin file offsets.
#
# What this buys: ext slots 128..255 live contiguously at natural
# positions in ONE table — the merit scan-loop bound extends over them
# directly, ext_item_para_slot_bin_offset is a single-segment
# computation into the seed block, and the four Cave6 teleport
# wrappers plus their inline patch sites are retired.

# --- Heap claim --------------------------------------------------------------
HEAP_CLAIM_WORD_RAM: Final = 0x80113AB4
HEAP_CLAIM_WORD_BIN_OFFSET: Final = _slus_ram_to_bin_offset(HEAP_CLAIM_WORD_RAM)
assert HEAP_CLAIM_WORD_BIN_OFFSET == 0x14D51A7C, hex(HEAP_CLAIM_WORD_BIN_OFFSET)
HEAP_CLAIM_WORD_VANILLA: Final = 0x801BFB64
HEAP_CLAIM_WORD_PATCHED: Final = 0x801C1B64
HEAP_CLAIM_WORD_FORMAT: Final = "<I"
# New arena after the claim (documentation; the game derives both from
# the claim word at boot).
ITEM_PARA_RELOC_NEW_ARENA_BASE: Final = 0x801C1B70
ITEM_PARA_RELOC_NEW_ARENA_SIZE: Final = 0x2E390
assert ITEM_PARA_RELOC_END_KUSEG == ITEM_PARA_RELOC_NEW_ARENA_BASE

# --- EXT_ITEM_PARA seed block (Cave6, .bin-backed) ---------------------------
# Reuses the exact footprint of the retired Cave6 ITEM_PARA ext
# segment: sector 148351 ud-bytes 0..959 (RAM 0x80096800..0x80096BC0).
# The patcher ALWAYS writes a 960-byte zero-fill here first (so
# unpopulated ext slots decode as empty entries with meritValue 0 —
# this also closes the merit-only gap where slots 128..134 previously
# read as garbage rows when the recycle option was off), then the shop
# token writers overlay their 32-byte entries via
# :func:`ext_item_para_slot_bin_offset`. The boot hook copies the whole
# block to :data:`ITEM_PARA_RELOC_EXT_KUSEG`.
#
# Staging ceiling: 30 slots (128..157). The relocated table itself has
# room up to slot 255; staging more than 30 ext slots needs a second
# .bin-backed seed source (none is free in Cave6 — next candidate is a
# heap-region extension, deferred until a shop actually needs it).
EXT_ITEM_PARA_SEED_RAM: Final = 0x80096800
EXT_ITEM_PARA_SEED_SLOT_BASE: Final = 128
EXT_ITEM_PARA_SEED_SLOT_COUNT: Final = 30
EXT_ITEM_PARA_SEED_SLOT_LAST: Final = (
    EXT_ITEM_PARA_SEED_SLOT_BASE + EXT_ITEM_PARA_SEED_SLOT_COUNT - 1         # 157
)
EXT_ITEM_PARA_SEED_SIZE: Final = (
    EXT_ITEM_PARA_SEED_SLOT_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE                # 960
)
EXT_ITEM_PARA_SEED_BIN_OFFSET: Final = _slus_ram_to_bin_offset(
    EXT_ITEM_PARA_SEED_RAM,
)
# Bounds: inside Cave6; sector-aligned base (ud-byte 0 of sector
# 148351) so the single flat 960-byte zero-fill token write stays
# inside one 2048-byte user-data region.
assert EXT_ITEM_PARA_SEED_RAM + EXT_ITEM_PARA_SEED_SIZE <= _CAVE6_END_RAM, (
    f"EXT_ITEM_PARA seed overflows Cave6: ends at "
    f"0x{EXT_ITEM_PARA_SEED_RAM + EXT_ITEM_PARA_SEED_SIZE:08X}"
)
assert (EXT_ITEM_PARA_SEED_RAM - 0x80096000) % 2048 == 0, (
    hex(EXT_ITEM_PARA_SEED_RAM)
)
assert EXT_ITEM_PARA_SEED_SIZE <= 2048, EXT_ITEM_PARA_SEED_SIZE
assert MERIT_SHOP_AP_ITEM_ID_LAST <= EXT_ITEM_PARA_SEED_SLOT_LAST, (
    f"merit shop's highest slot {MERIT_SHOP_AP_ITEM_ID_LAST} exceeds the "
    f"seed block's last slot {EXT_ITEM_PARA_SEED_SLOT_LAST}"
)

# --- MIPS word encoders (module-private) -------------------------------------
# Shared by the boot-hook builder and the reader-site patch tables.


def _mips_lui(rt: int, imm: int) -> int:
    return 0x3C000000 | (rt << 16) | (imm & 0xFFFF)


def _mips_addiu(rt: int, rs: int, imm: int) -> int:
    return 0x24000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_lw(rt: int, rs: int, imm: int) -> int:
    return 0x8C000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_sw(rt: int, rs: int, imm: int) -> int:
    return 0xAC000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_bne(rs: int, rt: int, off: int) -> int:
    return 0x14000000 | (rs << 21) | (rt << 16) | (off & 0xFFFF)


def _mips_jal(target: int) -> int:
    return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)


def _mips_jr_ra() -> int:
    return 0x03E00008


# --- Boot seed hook ----------------------------------------------------------
# Hijack site: master-init FUN_800EE800's first call.
BOOT_SEED_HOOK_SITE_RAM: Final = 0x800EE80C
BOOT_SEED_HOOK_SITE_OFFSET: Final = _slus_ram_to_bin_offset(BOOT_SEED_HOOK_SITE_RAM)
BOOT_SEED_HOOK_DISPLACED_CALLEE_RAM: Final = 0x800EEBDC
BOOT_SEED_HOOK_VANILLA_WORD: Final = 0x0C03BAF7            # jal 0x800EEBDC
assert BOOT_SEED_HOOK_VANILLA_WORD == _mips_jal(BOOT_SEED_HOOK_DISPLACED_CALLEE_RAM)
BOOT_SEED_HOOK_FORMAT: Final = "<I"

# Wrapper placement: the space freed by retiring the merit scan+name
# teleport wrappers, immediately after the merit ext wrapper. Always-on
# (the merit ext wrapper before it is opt-in, but its space is reserved
# either way). Stays inside sector 148350's ud-region and clear of the
# transition-gate wrapper at 0x800966C4 (region-gate section below).
ITEM_PARA_BOOT_HOOK_RAM: Final = (
    ROM_MERIT_SHOP_EXT_WRAPPER_RAM + len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES)   # 0x800965BC
)
assert ITEM_PARA_BOOT_HOOK_RAM == 0x800965BC, hex(ITEM_PARA_BOOT_HOOK_RAM)
assert ITEM_PARA_BOOT_HOOK_RAM % 4 == 0
ITEM_PARA_BOOT_HOOK_OFFSET: Final = _slus_ram_to_bin_offset(ITEM_PARA_BOOT_HOOK_RAM)


def _build_item_para_boot_hook_bytes() -> bytes:
    """Build the 37-instruction (148 B) boot seed hook.

    Faithful port of the lab's validated ``assemble_boot_hook`` (Net-1
    interpreter replay + Net-2 live battery + Net-3 disc boot); only
    the seed source (production seed block 0x80096800, 960 B) differs
    from the lab layout (0x80095FE0, 224 B).

    R3000 rules honored: no load consumer in a load-delay slot; branch
    delay slots carry the dst-pointer increments (they execute on every
    iteration including the fall-through last one); jr delay slot nop.
    Registers t0/t1/t2/t3 are caller-saved — free to clobber between
    the displaced call and the return.
    """

    import struct as _struct

    zero, t0, t1, t2, t3, sp, ra = 0, 8, 9, 10, 11, 29, 31

    src_hi, src_lo = _decompose_kuseg(RAM_ITEM_PARA_KUSEG)        # (0x8012, 0x69DC)
    dst_hi, dst_lo = _decompose_kuseg(ITEM_PARA_RELOC_BASE_KUSEG)  # (0x801C, 0xFB70)
    ext_hi, ext_lo = _decompose_kuseg(ITEM_PARA_RELOC_EXT_KUSEG)   # (0x801C, 0x0B70)
    seed_hi, seed_lo = _decompose_kuseg(EXT_ITEM_PARA_SEED_RAM)    # (0x8009, 0x6800)

    words = [
        _mips_addiu(sp, sp, -0x18),                # 0  prologue
        _mips_sw(ra, sp, 0x14),                    # 1
        _mips_jal(BOOT_SEED_HOOK_DISPLACED_CALLEE_RAM),  # 2  displaced first call
        0x00000000,                                # 3  (jal delay slot)
        # loop 1: copy 0x1000 B vanilla+tokens ITEM_PARA -> RELOC base
        _mips_lui(t0, src_hi),                     # 4
        _mips_addiu(t0, t0, src_lo),               # 5  t0 = 0x801269DC
        _mips_lui(t1, dst_hi),                     # 6
        _mips_addiu(t1, t1, dst_lo),               # 7  t1 = 0x801BFB70
        _mips_addiu(t2, zero, 0x1000),             # 8  t2 = byte count
        _mips_lw(t3, t0, 0),                       # 9  L1:
        _mips_addiu(t0, t0, 4),                    # 10 (fills t3 load delay)
        _mips_sw(t3, t1, 0),                       # 11
        _mips_addiu(t2, t2, -4),                   # 12
        _mips_bne(t2, zero, 9 - 14),               # 13 -> L1
        _mips_addiu(t1, t1, 4),                    # 14 (branch delay: dst += 4)
        # loop 2: zero 0x1000 B at RELOC ext (slots 128..255)
        _mips_lui(t1, ext_hi),                     # 15
        _mips_addiu(t1, t1, ext_lo),               # 16 t1 = 0x801C0B70
        _mips_addiu(t2, zero, 0x1000),             # 17
        _mips_sw(zero, t1, 0),                     # 18 L2:
        _mips_addiu(t2, t2, -4),                   # 19
        _mips_bne(t2, zero, 18 - 21),              # 20 -> L2
        _mips_addiu(t1, t1, 4),                    # 21 (branch delay: dst += 4)
        # loop 3: copy the seed block (960 B) Cave6 -> RELOC ext
        _mips_lui(t0, seed_hi),                    # 22
        _mips_addiu(t0, t0, seed_lo),              # 23 t0 = 0x80096800
        _mips_lui(t1, ext_hi),                     # 24
        _mips_addiu(t1, t1, ext_lo),               # 25 t1 = 0x801C0B70
        _mips_addiu(t2, zero, EXT_ITEM_PARA_SEED_SIZE),  # 26
        _mips_lw(t3, t0, 0),                       # 27 L3:
        _mips_addiu(t0, t0, 4),                    # 28 (fills t3 load delay)
        _mips_sw(t3, t1, 0),                       # 29
        _mips_addiu(t2, t2, -4),                   # 30
        _mips_bne(t2, zero, 27 - 32),              # 31 -> L3
        _mips_addiu(t1, t1, 4),                    # 32 (branch delay: dst += 4)
        # epilogue
        _mips_lw(ra, sp, 0x14),                    # 33
        _mips_addiu(sp, sp, 0x18),                 # 34 (fills ra load delay)
        _mips_jr_ra(),                             # 35
        0x00000000,                                # 36 (jr delay slot)
    ]
    assert len(words) == 37, len(words)
    return b"".join(_struct.pack("<I", w) for w in words)


ITEM_PARA_BOOT_HOOK_BYTES: Final = _build_item_para_boot_hook_bytes()
assert len(ITEM_PARA_BOOT_HOOK_BYTES) == 148, len(ITEM_PARA_BOOT_HOOK_BYTES)

# Placement asserts: inside sector 148350's ud-region (ends at RAM
# 0x80096800) and clear of the transition-gate wrapper at 0x800966C4
# (defined in the region-gate section at the bottom of this file; the
# literal is asserted there against this bound too).
_ITEM_PARA_BOOT_HOOK_END_RAM: Final = (
    ITEM_PARA_BOOT_HOOK_RAM + len(ITEM_PARA_BOOT_HOOK_BYTES)                 # 0x80096650
)
assert _ITEM_PARA_BOOT_HOOK_END_RAM <= 0x800966C4, hex(_ITEM_PARA_BOOT_HOOK_END_RAM)
assert _ITEM_PARA_BOOT_HOOK_END_RAM <= 0x80096800, hex(_ITEM_PARA_BOOT_HOOK_END_RAM)

# The jal redirect written over the hijack site.
BOOT_SEED_HOOK_PATCH_VALUE: Final = _mips_jal(ITEM_PARA_BOOT_HOOK_RAM)
assert BOOT_SEED_HOOK_PATCH_VALUE == 0x0C02596F, hex(BOOT_SEED_HOOK_PATCH_VALUE)

# --- SLUS reader sites (24 sites, 48 words) ----------------------------------
# Source: the lab census (dw1_scan_item_para_readers.py re-run
# 2026-08-20; identical to Path A's enumeration). Each row is
# ``(lui_ram, addiu_ram, reg, field_offset)`` for a lui+addiu pair
# constructing ``vanilla ITEM_PARA + field``. Vanilla and patched words
# are derived below and byte-asserted against the shipped .bin by the
# test suite and by dw1_apply_patch-style verification.
_ITEM_PARA_READER_SITES: Final[tuple[tuple[int, int, int, int], ...]] = (
    (0x800AA3AC, 0x800AA3B0, 2, 0x00),
    (0x800AA760, 0x800AA764, 2, 0x00),
    (0x800DAB40, 0x800DAB48, 2, 0x00),
    (0x800DAC10, 0x800DAC18, 2, 0x00),
    (0x800DAD70, 0x800DAD74, 2, 0x00),
    (0x800DB7C8, 0x800DB7D0, 2, 0x1C),
    (0x800DC814, 0x800DC81C, 2, 0x00),
    (0x800DC8E8, 0x800DC8F0, 2, 0x1D),
    (0x800DCAB8, 0x800DCAC0, 5, 0x1A),
    (0x800E4D20, 0x800E4D28, 2, 0x1A),
    (0x800FA8F8, 0x800FA8FC, 2, 0x14),
    (0x800FAAAC, 0x800FAAB4, 5, 0x1D),
    (0x800FB018, 0x800FB020, 2, 0x18),   # merit purchase-deduct meritValue read
    (0x800FB740, 0x800FB744, 2, 0x00),
    (0x800FB75C, 0x800FB760, 2, 0x00),
    (0x800FD034, 0x800FD03C, 2, 0x14),
    (0x800FE7F4, 0x800FE7F8, 2, 0x00),   # merit row-display name read
    (0x800FE874, 0x800FE878, 2, 0x14),   # merit row-display value read
    (0x800FE8FC, 0x800FE900, 2, 0x18),   # merit row-display meritValue read
    (0x800FF01C, 0x800FF024, 2, 0x00),
    (0x800FF0A8, 0x800FF0B0, 2, 0x00),
    (0x80101A4C, 0x80101A54, 2, 0x00),   # name renderer (ex name-teleport site)
    (0x80106D90, 0x80106D98, 5, 0x14),
    (0x8010732C, 0x80107330, 9, 0x18),   # merit scan meritValue base (ex scan-teleport site)
)


def _build_item_para_reader_word_patches() -> tuple[tuple[int, int, int], ...]:
    """Derive the 48 SLUS reader-word patches.

    Returns ``((bin_offset, patched_word, vanilla_word), ...)`` — two
    rows per site (lui then addiu). Uniform hi-half by design: every
    re-based target ``RELOC + field`` falls in the sign-extension
    window, so each patched lui is ``lui reg, 0x801C`` and each patched
    addiu low half is ``0xFB70 + field``.
    """

    rows: list[tuple[int, int, int]] = []
    for lui_ram, addiu_ram, reg, field in _ITEM_PARA_READER_SITES:
        van_hi, van_lo = _decompose_kuseg(RAM_ITEM_PARA_KUSEG + field)
        new_hi, new_lo = _decompose_kuseg(ITEM_PARA_RELOC_BASE_KUSEG + field)
        assert van_hi == 0x8012 and van_lo == 0x69DC + field
        assert new_hi == 0x801C, hex(new_hi)
        rows.append((
            _slus_ram_to_bin_offset(lui_ram),
            _mips_lui(reg, new_hi),
            _mips_lui(reg, van_hi),
        ))
        rows.append((
            _slus_ram_to_bin_offset(addiu_ram),
            _mips_addiu(reg, reg, new_lo),
            _mips_addiu(reg, reg, van_lo),
        ))
    return tuple(rows)


ITEM_PARA_READER_WORD_PATCHES: Final = _build_item_para_reader_word_patches()
assert len(ITEM_PARA_READER_WORD_PATCHES) == 48, len(ITEM_PARA_READER_WORD_PATCHES)

# --- Overlay reader sites (7 sites, 14 words) --------------------------------
# Overlays reload from disc per activation, so these are patched at
# their .bin file offsets (root files at fixed LBAs, Mode2/2352).
# BTL_REL vanilla words were additionally verified LIVE in the resident
# overlay (RAM base 0x80052AE0) during the lab's Net 2.

_OVERLAY_BTL_LBA: Final = 147703
_OVERLAY_FISH_LBA: Final = 147843


def _overlay_file_to_bin(lba: int, file_off: int) -> int:
    """Flat .bin offset of ``file_off`` inside a root file at ``lba``."""

    sector = lba + file_off // 2048
    return sector * SECTOR_SIZE_BYTES + SECTOR_HEADER_BYTES + (file_off % 2048)


# Anchor cross-check: the chest wrapper's known .bin offset must
# reproduce through the LBA formula (SLUS at LBA 148338, 0x800-byte EXE
# header, load base 0x80090800).
_SLUS_LBA: Final = 148338
_SLUS_EXE_HEADER_BYTES: Final = 0x800
_SLUS_LOAD_BASE_RAM: Final = 0x80090800
assert _overlay_file_to_bin(
    _SLUS_LBA,
    ROM_CHEST_GIVEITEM_WRAPPER_RAM - _SLUS_LOAD_BASE_RAM + _SLUS_EXE_HEADER_BYTES,
) == ROM_CHEST_GIVEITEM_WRAPPER_OFFSET

# ``(file, lba, lui_file_off, addiu_file_off, reg, field_offset)``
_ITEM_PARA_OVERLAY_READER_SITES: Final[
    tuple[tuple[str, int, int, int, int, int], ...]
] = (
    ("BTL_REL.BIN", _OVERLAY_BTL_LBA, 0xFED4, 0xFED8, 2, 0x00),
    ("FISH_REL.BIN", _OVERLAY_FISH_LBA, 0x0BA4, 0x0BAC, 2, 0x00),
    ("FISH_REL.BIN", _OVERLAY_FISH_LBA, 0x10DC, 0x10E4, 3, 0x1A),
    ("FISH_REL.BIN", _OVERLAY_FISH_LBA, 0x913C, 0x9140, 2, 0x00),
    ("FISH_REL.BIN", _OVERLAY_FISH_LBA, 0x917C, 0x9180, 2, 0x00),
    ("FISH_REL.BIN", _OVERLAY_FISH_LBA, 0x93F0, 0x93F4, 2, 0x00),
    ("FISH_REL.BIN", _OVERLAY_FISH_LBA, 0x9430, 0x9434, 2, 0x00),
)


def _build_item_para_overlay_word_patches() -> tuple[tuple[str, int, int, int], ...]:
    """Derive the 14 overlay reader-word patches.

    Returns ``((file, bin_offset, patched_word, vanilla_word), ...)``.
    Same lui/addiu re-encoding as the SLUS sites; offsets translated
    through the LBA formula. Each 4-byte word is 4-aligned within its
    2048-byte user-data region, so a flat token write is sector-safe.
    """

    rows: list[tuple[str, int, int, int]] = []
    for fname, lba, lui_off, addiu_off, reg, field in _ITEM_PARA_OVERLAY_READER_SITES:
        van_hi, van_lo = _decompose_kuseg(RAM_ITEM_PARA_KUSEG + field)
        new_hi, new_lo = _decompose_kuseg(ITEM_PARA_RELOC_BASE_KUSEG + field)
        assert new_hi == 0x801C, hex(new_hi)
        for file_off, patched, vanilla in (
            (lui_off, _mips_lui(reg, new_hi), _mips_lui(reg, van_hi)),
            (addiu_off, _mips_addiu(reg, reg, new_lo), _mips_addiu(reg, reg, van_lo)),
        ):
            assert file_off % 4 == 0 and file_off % 2048 <= 2044, hex(file_off)
            rows.append((fname, _overlay_file_to_bin(lba, file_off), patched, vanilla))
    return tuple(rows)


ITEM_PARA_OVERLAY_WORD_PATCHES: Final = _build_item_para_overlay_word_patches()
assert len(ITEM_PARA_OVERLAY_WORD_PATCHES) == 14, len(ITEM_PARA_OVERLAY_WORD_PATCHES)

# Lock the derived offsets to the lab-validated spec values
# (item_para_reloc.json, Net-3 verified in the built image).
_EXPECTED_OVERLAY_BIN_OFFSETS: Final = (
    0x14B6010C, 0x14B60110,                       # BTL_REL.BIN +0xFED4/+0xFED8
    0x14B9F07C, 0x14B9F084,                       # FISH_REL.BIN +0x0BA4/+0x0BAC
    0x14B9F6E4, 0x14B9F6EC,                       # FISH_REL.BIN +0x10DC/+0x10E4
    0x14BA8A44, 0x14BA8A48,                       # FISH_REL.BIN +0x913C/+0x9140
    0x14BA8A84, 0x14BA8A88,                       # FISH_REL.BIN +0x917C/+0x9180
    0x14BA8CF8, 0x14BA8CFC,                       # FISH_REL.BIN +0x93F0/+0x93F4
    0x14BA8D38, 0x14BA8D3C,                       # FISH_REL.BIN +0x9430/+0x9434
)
assert tuple(
    off for _f, off, _p, _v in ITEM_PARA_OVERLAY_WORD_PATCHES
) == _EXPECTED_OVERLAY_BIN_OFFSETS


# =============================================================================
# Cave6 teleport wrappers — RETIRED 2026-08-21
# =============================================================================
#
# The Cave6 multi-segment architecture (ext slots 144..173 in a Cave6
# segment, reached by patching the merit shop's scan / name / row /
# deduct ITEM_PARA readers to "teleport" through per-callsite Cave6
# wrappers) is superseded by the 256-slot relocation above: with one
# contiguous table, the four plain reader-word patches at the same
# sites (0x8010732C scan, 0x80101A4C name, 0x800FE7F4+ row,
# 0x800FB018 deduct — all in _ITEM_PARA_READER_SITES) cover every
# slot 0..255, and the wrappers plus their inline ``j`` patches are
# unnecessary. Constants and builders removed; the wrappers' Cave6
# space is reused by the boot seed hook (scan/name footprint) and
# freed (row/deduct footprint, 0x80096650..0x800966C4). See
# ``docs/item_para_cave6_multisegment.md`` for the historical design.

# =============================================================================
# Path A (ITEM_PARA relocation) — REVERTED 2026-05-13
# =============================================================================
#
# Path A attempted to relocate ITEM_PARA from vanilla 0x801269DC to
# 0x8009DBC8 (a 5808-byte region thought to be free libgs leftover),
# raising the AP-extended-slot ceiling from 16 to 53.
#
# It froze the in-game arena. Post-mortem: the chosen region holds 9
# function pointers stored into the dispatch struct array at RAM
# 0x80137000..0x801370FF (struct fields +0x0C, +0x14, +0x1C of structs
# 2/3/6/7), so jalring through any of those handlers executes our
# ITEM_PARA data as MIPS instructions and crashes. The free-region
# probe (tools/dw1_freeregion_probe.lua) missed this because it only
# watched for writes to the region, not for pointer constants stored
# elsewhere that point into it.
#
# The reader-site census infrastructure
# (tools/dw1_scan_item_para_readers.py, the static analysis in
# docs/item_para_relocation.md) fed directly into the SUCCESSOR that
# shipped 2026-08-21: the always-on 256-slot relocation onto the
# heap-claimed region 0x801BFB70 (section above), whose target is real
# vacated arena space rather than a hoped-for free code region — the
# function-pointer failure mode cannot recur there.


# --- Merit-shop jal-hijack override -----------------------------------------
# When MeritShopLocations is on, override the jal at the existing
# ROM_MERIT_SHOP_PATCH_OFFSET (which v1 set to jal ROM_MERIT_SHOP_WRAPPER_RAM
# = 0x80095800) to instead jal the extended wrapper. This re-writes the
# same 4 bytes the v1 patcher writes; option-on patcher must run AFTER
# the v1 patcher emits its token (token order = insertion order) so the
# override sticks.
ROM_MERIT_SHOP_EXT_PATCH_FORMAT: Final = "<I"
ROM_MERIT_SHOP_EXT_PATCH_VALUE: Final = (
    0x0C000000 | ((ROM_MERIT_SHOP_EXT_WRAPPER_RAM >> 2) & 0x03FFFFFF)
)


# --- Merit-shop scan-loop bound patch ---------------------------------------
# Vanilla DW1 caps the merit-shop ITEM_PARA scan at id < 128 via the
# ``sltiu $r1, $r5, 0x0080`` immediate at RAM 0x00107430. Bump to
# ``sltiu $r1, $r5, 0x0095`` (= 149) so the scan reaches up through
# extended slot 148 (MERIT_SHOP_AP_ITEM_ID_LAST). With the always-on
# 256-slot relocation the scan walks the contiguous relocated table,
# so any bound up to 256 is structurally safe — 149 is simply the
# highest populated merit slot + 1 (unpopulated seed slots decode as
# meritValue 0 and would be skipped anyway).
ROM_MERIT_SCAN_BOUND_RAM: Final = 0x80107430
ROM_MERIT_SCAN_BOUND_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_SCAN_BOUND_RAM,
)
ROM_MERIT_SCAN_BOUND_FORMAT: Final = "<I"
# Encoding: opcode 0x0B (sltiu), rs=5 ($r5/$a1), rt=1 ($at), imm.
_MERIT_SCAN_BOUND_NEW_IMM: Final = MERIT_SHOP_AP_ITEM_ID_LAST + 1            # 149
assert _MERIT_SCAN_BOUND_NEW_IMM < 0x8000, _MERIT_SCAN_BOUND_NEW_IMM
ROM_MERIT_SCAN_BOUND_VALUE: Final = (
    (0x0B << 26) | (5 << 21) | (1 << 16) | _MERIT_SCAN_BOUND_NEW_IMM
)
# Sanity: vanilla bound = 0x2CA10080. New bound = 0x2CA10095 for limit 149.
assert ROM_MERIT_SCAN_BOUND_VALUE == 0x2CA10000 | _MERIT_SCAN_BOUND_NEW_IMM, (
    hex(ROM_MERIT_SCAN_BOUND_VALUE)
)


# =============================================================================
# Region-gate feature (physical enforcement of the ``region_locking`` option)
# =============================================================================
#
# Lab-validated 2026-08-20/21 (three nets each) in
# ``work/dw1_re/decomp/_scan_transition_gate/`` (walk-on MapWarps wrapper +
# gate table) and ``work/dw1_re/decomp/_scan_script_gates/`` (script-class
# gates), spec builders ``work/dw1_re/patches/transition_gate_spec.py`` /
# ``script_gates_spec.py``. This section is the faithful production port:
# same bytes, same addresses, same trigger ids.
#
# Mechanism summary:
#
# * **Walk-on crossings** — MAP_WARPS (0x78 B @ RAM 0x80138730) is rebuilt
#   from disc data on EVERY screen load by loadMapEntities' first action,
#   ``memcpy(0x80138730, buffer, 0x78)`` = the ``jal memcpy`` at RAM
#   0x800A9AA0. Struct (dw_decomp 2026-08-28): four ``i16[10]`` coordinate
#   arrays, then ``u16 targetMap[10]`` @ +0x50 (= 0x80138780) and
#   ``u16 targetExit[10]`` @ +0x64; rebuilt by ``loadMapEntities``
#   @ 0x800A9A68 (the memcpy is its +0x38). The walk-on consumer
#   ``checkMapInteraction`` is still ASM-only upstream, so the loop-back
#   semantics rest on our lab validation, not on C. We redirect that jal into a Cave6 wrapper that calls memcpy
#   with the original args, then walks a gate table of
#   ``{u8 screen, u8 slot, u16 trigger}`` rows (terminator screen=0xFF):
#   for each row matching the mapId being loaded (callee-saved ``s5`` at
#   the callsite), if ``isTriggerSet(trigger)`` is false the row's slot is
#   shorted into a loop-back (``targetMap[slot] = mapId``,
#   ``targetExit[slot] = slot``) — crossing the mouth fades and reloads the
#   same screen at the same mouth. Synchronous, race-free, survives every
#   reload (the self-reload re-runs the wrapper).
# * **Script-class crossings** (market gates, Whamon ferry, Blue Flute
#   pier/ride, Beetle Land return ferry) never consult MAP_WARPS; they are
#   gated by retargeting ONE u16 per flow (a setSelection target / IF jump
#   target / section head) into a small stub written over the script slot's
#   tail residue: ``if trigger(RA) == false then <vanilla decline path>``
#   + ``jumpTo <vanilla continue>``. Blocked behavior is always an existing
#   vanilla path (prompt closes / NPC walks back / section ends).
#
# Region Access trigger ids (one bit per LOCKABLE_REGION; the client sets
# the bit when AP delivers the "<Region> Region Access" item and reconciles
# it every tick):
#
# * 12 walk-on regions sit in the free tail of the historical 880..935 AP
#   pool: 926/927 = byte 0x001BE040 bits 6/7 (after merit 912..925);
#   928..935 = byte 0x001BE041 (documented free); 911 = byte 0x001BE03E
#   bit 7; 896 = byte 0x001BE03D bit 0 (reclaimed from the never-shipped
#   "Gear Savanna MP Stand" vending reservation).
# * 897 Factorial Town = byte 0x001BE03D bit 1 (the vending-skip bit — the
#   last free bit of the historical pool).
# * 879 Beetle Land = byte 0x001BE03A bit 7, OUTSIDE the historical pool
#   (the pool's 13 free bits cover only 13 of the 14 LOCKABLE_REGIONS).
#   Audited clean 2026-08-21: vanilla scripts reference trigger ids only up
#   to 713 (full DW1Script.txt scan); engine-side constant callers of the
#   trigger family (getTriggerOffsets/isTriggerSet/setTrigger/unsetTrigger)
#   max out at trigger 640 with zero uses of 856..879 (4 live RAM images,
#   86 callsites each); zero direct-address accesses to 0x801BE03A and zero
#   save-block-relative +0x162 accesses anywhere in the .bin or resident
#   code. Same audit covers 878 (bit 6, the G Canyon Top flight bit below).
#
# Triggers >= 936 are FORBIDDEN — byte 0x001BE042 is
# :data:`RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE`.

REGION_ACCESS_TRIGGER_IDS: Final[dict[str, int]] = {
    "Ancient Dino Region": 926,
    "Beetle Land":         879,
    "Drill Tunnel":        927,
    "Factorial Town":      897,
    "Freezeland":          928,
    "Gear Savanna":        929,
    "Geko Swamp":          930,
    "Great Canyon":        931,
    "Misty Trees":         932,
    "Mt. Panorama":        933,
    "Native Forest":       934,
    "Overdell":            935,
    "Toy Town":            911,
    "Tropical Jungle":     896,
}

# Per-region (byte, bit) targets for the client's trigger-bit delivery,
# derived via the canonical setTrigger formula
# ``(AP_TRIGGER_ARRAY_BASE + N // 8, N % 8)``.
REGION_ACCESS_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    region: (AP_TRIGGER_ARRAY_BASE + trigger // 8, trigger % 8)
    for region, trigger in REGION_ACCESS_TRIGGER_IDS.items()
}

# --- G Canyon Top flight-slot redirect (region_locking integration) ---------
#
# The 6th Birdramon-Messenger destination (G Canyon Top, table entry 0)
# keeps its vanilla trigger 221 (= Birdramon recruit) in normal seeds — it
# auto-unlocks with the Birdramon Recruit AP item. Under region locking
# with Great Canyon locked that would bypass the Great Canyon Region
# Access item, so the patcher redirects entry 0's trigger u16 (both .bin
# table copies) to a fresh AP bit the client pins on
# ``Birdramon Recruit AND Great Canyon Region Access``.
#
# Trigger 878 = byte 0x001BE03A bit 6 — outside the historical 880..935
# pool, which is fully allocated (flight 880-884, arena cups 885-889,
# vending 890-895 + 898-901, rods 902/903, recycle 904-910, merit 912-925,
# Region Access 896/897/911/926-935). Covered by the same 856..879 audit
# as Beetle Land's 879 (see above). NOTE: the lab handoff suggested id 885
# for this bit; 885 is :data:`ARENA_CUP_GRADE_D_TRIGGER_ID` (shipped), so
# the production allocation moved to 878 — the one renumbering in this port.
# Entry 0's vanilla trigger 221 is one of the six engine readers of the
# recruit bits (see the isTriggerSet-wrapper preamble); rewriting it to 878
# is what decouples the flight from the vanilla Birdramon recruit bit.
BIRDRA_FLIGHT_GCANYON_TRIGGER_ID: Final = 878
BIRDRA_FLIGHT_GCANYON_RAM_BIT: Final[tuple[int, int]] = (
    AP_TRIGGER_ARRAY_BASE + BIRDRA_FLIGHT_GCANYON_TRIGGER_ID // 8,
    BIRDRA_FLIGHT_GCANYON_TRIGGER_ID % 8,
)
assert BIRDRA_FLIGHT_GCANYON_RAM_BIT == (0x001BE03A, 6), BIRDRA_FLIGHT_GCANYON_RAM_BIT

# Flight destination table bases (entry format ``<u16 trigger, u32 price,
# u16 label>``, 6 entries x 8 B, two identical .bin copies). Entry 0 =
# G Canyon Top (vanilla trigger 221; vanilla prices for entries 0..5 are
# 1000/1000/1500/2000/2500/2500 bits — "free" in the older flight notes
# referred to the trigger auto-unlocking with Birdramon's recruit, not
# the fare).
ROM_BIRDRA_FLIGHT_TABLE_BASES: Final[tuple[int, int]] = (0x14B8B698, 0x14D725C6)
# Consistency with the shipped per-entry trigger patches (entry n trigger
# sits at ``base + 8 * n``; the shipped tuples start at entry 1).
assert ROM_BIRDRA_FLIGHT_TABLE_PATCHES[0][0] == ROM_BIRDRA_FLIGHT_TABLE_BASES[0] + 8
assert ROM_BIRDRA_FLIGHT_TABLE_PATCHES[5][0] == ROM_BIRDRA_FLIGHT_TABLE_BASES[1] + 8

# Entry-0 trigger u16 rewrite sites (only written when Great Canyon is
# locked this seed). Vanilla value at both sites: 221 (0xDD 0x00).
ROM_BIRDRA_FLIGHT_GCANYON_PATCHES: Final[tuple[tuple[int, int], ...]] = tuple(
    (base, BIRDRA_FLIGHT_GCANYON_TRIGGER_ID) for base in ROM_BIRDRA_FLIGHT_TABLE_BASES
)
ROM_BIRDRA_FLIGHT_GCANYON_VANILLA_TRIGGER: Final = 221

# --- Flight price zeroing (unconditional QoL, user-confirmed) ---------------
#
# Zero the u32 cost field of all 6 destination entries in BOTH table
# copies. Written unconditionally by the patcher — no option. (An older
# comment claimed G Canyon Top is free in vanilla; it costs 1000 — the
# zeroing here is what makes every flight free. dw_decomp audit 2026-08-28.)
ROM_BIRDRA_FLIGHT_PRICE_OFFSETS: Final[tuple[int, ...]] = tuple(
    base + 8 * entry + 2
    for base in ROM_BIRDRA_FLIGHT_TABLE_BASES
    for entry in range(6)
)
ROM_BIRDRA_FLIGHT_PRICE_ZERO: Final = b"\x00\x00\x00\x00"
# Flat token writes only — none of the 4-byte price writes (nor the 2-byte
# entry-0 trigger writes) may cross a Mode2/2352 user-data boundary
# (header 24 B, user data bytes 24..2071 of each 2352-B sector).
for _off, _ln in (
    *((o, 4) for o in ROM_BIRDRA_FLIGHT_PRICE_OFFSETS),
    *((o, 2) for o, _t in ROM_BIRDRA_FLIGHT_GCANYON_PATCHES),
):
    _pos = _off % 2352
    assert 24 <= _pos and _pos + _ln <= 2072, (
        f"flight-table write at 0x{_off:09X} straddles a sector boundary"
    )
del _off, _ln, _pos


# --- Walk-on transition-gate wrapper + table (Cave6) ------------------------
#
# Cave6 space claim: historically the free gap between the (retired)
# merit purchase-deduct teleport wrapper and the (retired) Cave6
# ITEM_PARA ext segment; today the gap between the ITEM_PARA boot seed
# hook's free tail (hook ends at 0x80096650) and the EXT_ITEM_PARA seed
# block (starts at 0x80096800), fully inside sector 148350's user-data
# window — wrapper 164 B @ 0x800966C4..0x80096768, full table 136 B @
# 0x80096768..0x800967F0, 16 B spare.
TRANSITION_GATE_WRAPPER_RAM: Final = 0x800966C4
assert TRANSITION_GATE_WRAPPER_RAM >= _ITEM_PARA_BOOT_HOOK_END_RAM, (
    "Cave6 layout drifted — the ITEM_PARA boot seed hook overlaps the "
    "transition-gate wrapper"
)
TRANSITION_GATE_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    TRANSITION_GATE_WRAPPER_RAM,
)

# Hook: loadMapEntities' first action is ``jal memcpy`` at 0x800A9AA0
# (vanilla word 0x0C024493 = jal 0x8009124C, verified vs live RAM and the
# .bin). At that callsite s5 = the mapId being loaded (set at 0x800A9A8C,
# callee-saved).
TRANSITION_GATE_HOOK_RAM: Final = 0x800A9AA0
TRANSITION_GATE_HOOK_OFFSET: Final = _slus_ram_to_bin_offset(
    TRANSITION_GATE_HOOK_RAM,
)
TRANSITION_GATE_HOOK_VANILLA_WORD: Final = 0x0C024493
_TRANSITION_GATE_MEMCPY_RAM: Final = 0x8009124C
assert (
    ((TRANSITION_GATE_HOOK_VANILLA_WORD & 0x03FFFFFF) << 2) | 0x80000000
) == _TRANSITION_GATE_MEMCPY_RAM
ROM_TRANSITION_GATE_HOOK_BYTES: Final = struct.pack(
    "<I", 0x0C000000 | ((TRANSITION_GATE_WRAPPER_RAM >> 2) & 0x03FFFFFF),
)

_TRANSITION_GATE_ISTRIGGERSET_RAM: Final = 0x8010643C   # VERIFIED decomp unit
_TRANSITION_GATE_TARGETMAP_RAM: Final = 0x80138780      # MAP_WARPS.targetMap[10]

# File City market clones TWNB01..24 (screens 180..203) share byte-identical
# warp tables; the wrapper canonicalizes s5 in [180, 203] -> 180 for table
# MATCHING only (loop-back writes still store the REAL mapId), so the ROM
# table carries 2 rows for screen 180 instead of 48.
_TWNB_FIRST: Final = 180
_TWNB_LAST: Final = 203
_TWNB_CANONICAL: Final = 180


def _build_transition_gate_wrapper_bytes() -> bytes:
    """Assemble the 41-word post-memcpy transition-gate wrapper.

    Entry (redirected jal): a0=0x80138730, a1=staging buffer, a2=0x78,
    ra=0x800A9AA8, s5=mapId being loaded. Calls memcpy with the original
    args, then walks the gate table at :data:`TRANSITION_GATE_TABLE_RAM`.
    Contract: preserves s*/sp/gp/ra and returns v0 = memcpy's return
    value. o32 frame 0x20 with 16 B home space; R3000 load-delay and
    branch-delay rules honored (annotated below). Byte-identical to the
    lab-validated ``transition_gate.json`` wrapper (Net 1: delay-slot-
    faithful interpreter replay over screens 0..254 x 3 random trigger
    states vs an independent model; Net 2 live; Net 3 disc build).
    """

    zero, at, v0, a0 = 0, 1, 2, 4
    t1, t3, t4, t5 = 9, 11, 12, 13
    s0, s1, s5 = 16, 17, 21
    sp, ra = 29, 31

    def lw(rt: int, rs: int, imm: int) -> int:
        return 0x8C000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def lbu(rt: int, rs: int, imm: int) -> int:
        return 0x90000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def lhu(rt: int, rs: int, imm: int) -> int:
        return 0x94000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def sw(rt: int, rs: int, imm: int) -> int:
        return 0xAC000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def sh(rt: int, rs: int, imm: int) -> int:
        return 0xA4000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def lui(rt: int, imm: int) -> int:
        return 0x3C000000 | (rt << 16) | (imm & 0xFFFF)

    def addiu(rt: int, rs: int, imm: int) -> int:
        return 0x24000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def sltiu(rt: int, rs: int, imm: int) -> int:
        return 0x2C000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)

    def or_(rd: int, rs: int, rt: int) -> int:
        return (rs << 21) | (rt << 16) | (rd << 11) | 0x25

    def sll(rd: int, rt: int, sa: int) -> int:
        return (rt << 16) | (rd << 11) | ((sa & 31) << 6)

    def addu(rd: int, rs: int, rt: int) -> int:
        return (rs << 21) | (rt << 16) | (rd << 11) | 0x21

    def beq(rs: int, rt: int, off: int) -> int:
        return 0x10000000 | (rs << 21) | (rt << 16) | (off & 0xFFFF)

    def bne(rs: int, rt: int, off: int) -> int:
        return 0x14000000 | (rs << 21) | (rt << 16) | (off & 0xFFFF)

    def jr(rs: int) -> int:
        return (rs << 21) | 0x08

    def jal(target: int) -> int:
        return 0x0C000000 | ((target >> 2) & 0x03FFFFFF)

    nop = 0

    t_hi, t_lo = _decompose_kuseg(TRANSITION_GATE_TABLE_RAM)
    tm_hi, tm_lo = _decompose_kuseg(_TRANSITION_GATE_TARGETMAP_RAM)
    twnb_span = _TWNB_LAST - _TWNB_FIRST + 1                # 24

    words = [
        addiu(sp, sp, -0x20),               # 0  prologue
        sw(ra, sp, 0x1C),                   # 1
        sw(s0, sp, 0x18),                   # 2
        sw(s1, sp, 0x14),                   # 3
        jal(_TRANSITION_GATE_MEMCPY_RAM),   # 4  vanilla memcpy(a0,a1,a2)
        nop,                                # 5  (jal delay)
        sw(v0, sp, 0x10),                   # 6  preserve memcpy's return
        or_(s1, s5, zero),                  # 7  s1 = mapId (match key)
        addiu(t1, s5, -_TWNB_FIRST),        # 8  t1 = mapId - 180
        sltiu(at, t1, twnb_span),           # 9  at = mapId in [180, 203]
        beq(at, zero, 2),                   # 10 not a TWNB clone -> L_setup
        nop,                                # 11 (branch delay)
        addiu(s1, zero, _TWNB_CANONICAL),   # 12 TWNB fold: match as 180
        # L_setup (13):
        lui(s0, t_hi),                      # 13 s0 = gate table cursor
        addiu(s0, s0, t_lo),                # 14
        # L_loop (15):
        lbu(t1, s0, 0),                     # 15 t1 = row.screen
        addiu(at, zero, 0xFF),              # 16 (fills t1 load-delay)
        beq(t1, at, 17),                    # 17 terminator -> L_done (35)
        nop,                                # 18 (branch delay)
        bne(t1, s1, 13),                    # 19 row not for this screen -> L_next
        nop,                                # 20 (branch delay)
        lhu(a0, s0, 2),                     # 21 a0 = row.trigger
        jal(_TRANSITION_GATE_ISTRIGGERSET_RAM),  # 22 v0 = isTriggerSet(a0)
        nop,                                # 23 (jal delay)
        bne(v0, zero, 8),                   # 24 item delivered -> vanilla -> L_next
        nop,                                # 25 (branch delay)
        lbu(t3, s0, 1),                     # 26 t3 = row.slot
        lui(t4, tm_hi),                     # 27 (fills t3 load-delay)
        addiu(t4, t4, tm_lo),               # 28 t4 = targetMap base
        sll(t5, t3, 1),                     # 29 t5 = 2*slot
        addu(t4, t4, t5),                   # 30 &targetMap[slot]
        sh(s5, t4, 0),                      # 31 targetMap[slot] = REAL mapId
        sh(t3, t4, 0x14),                   # 32 targetExit[slot] = slot
        # L_next (33):
        beq(zero, zero, -19),               # 33 -> L_loop (15)
        addiu(s0, s0, 4),                   # 34 (branch delay: cursor += 4)
        # L_done (35):
        lw(v0, sp, 0x10),                   # 35 restore memcpy's return
        lw(ra, sp, 0x1C),                   # 36
        lw(s0, sp, 0x18),                   # 37 (fills ra load-delay)
        lw(s1, sp, 0x14),                   # 38 (delay slot = jr, no consumer)
        jr(ra),                             # 39
        addiu(sp, sp, 0x20),                # 40 (jr delay: epilogue)
    ]
    assert len(words) == 41
    return b"".join(struct.pack("<I", w) for w in words)


TRANSITION_GATE_TABLE_RAM: Final = TRANSITION_GATE_WRAPPER_RAM + 41 * 4      # 0x80096768
assert TRANSITION_GATE_TABLE_RAM == 0x80096768, hex(TRANSITION_GATE_TABLE_RAM)
TRANSITION_GATE_TABLE_OFFSET: Final = _slus_ram_to_bin_offset(
    TRANSITION_GATE_TABLE_RAM,
)

ROM_TRANSITION_GATE_WRAPPER_BYTES: Final = _build_transition_gate_wrapper_bytes()
assert len(ROM_TRANSITION_GATE_WRAPPER_BYTES) == 164, (
    len(ROM_TRANSITION_GATE_WRAPPER_BYTES)
)

# The full folded walk-on gate table: one row per gated crossing direction,
# ``(source screen, MapWarps slot, gating region)``. Derived from the
# lab's ``gate_table.json`` (79 raw rows; the 48 byte-identical TWNB01..24
# clone rows are folded into the 2 screen-180 rows — the wrapper's TWNB
# canonicalization covers 181..203). MUST stay sorted by (screen, slot):
# the per-seed encoder emits rows in this order and the full-locked
# encoding is asserted byte-identical to the lab spec by the test suite.
#
# Region names reference :data:`REGION_ACCESS_TRIGGER_IDS` keys (=
# ``regions.LOCKABLE_REGIONS`` entries; cross-checked in regions.py).
TRANSITION_GATE_ROWS: Final[tuple[tuple[int, int, str], ...]] = (
    (7,   0, "Native Forest"),        # MAYO11    s0 -> MAYO02_2 (Drill border)
    (9,   2, "Tropical Jungle"),      # MAYO08A   s2 -> TROP00
    (11,  0, "Native Forest"),        # TROP00    s0 -> MAYO08A
    (17,  1, "Ancient Dino Region"),  # TROP06    s1 -> KODA00
    (18,  0, "Native Forest"),        # MIHA00    s0 -> MAYO02_2 (NF/Mt.P border)
    (22,  1, "Gear Savanna"),         # MIHA04A   s1 -> GIAS00
    (23,  1, "Gear Savanna"),         # MIHA04B   s1 -> GIAS00
    (34,  0, "Overdell"),             # DGHA01    s0 -> DGHA02
    (35,  1, "Tropical Jungle"),      # DGHA02    s1 -> DGHA01
    (36,  1, "Great Canyon"),         # GCAN01    s1 -> GCAN09
    (38,  1, "Freezeland"),           # GCAN03    s1 -> FRZL01
    (39,  1, "Freezeland"),           # GCAN04    s1 -> FRZL01
    (44,  0, "Tropical Jungle"),      # GCAN09    s0 -> GCAN01
    (69,  0, "Mt. Panorama"),         # GIAS00    s0 -> MIHA04A
    (77,  3, "Geko Swamp"),           # GIAS08    s3 -> STIC01
    (79,  0, "Tropical Jungle"),      # KODA00    s0 -> TROP06
    (88,  1, "Great Canyon"),         # FRZL01    s1 -> GCAN04
    (88,  2, "Great Canyon"),         # FRZL01    s2 -> GCAN03
    (95,  1, "Misty Trees"),          # FRZL08    s1 -> MIST07
    (110, 2, "Drill Tunnel"),         # MAYO01_2  s2 -> MAYO11
    (111, 1, "Mt. Panorama"),         # MAYO02_2  s1 -> MIHA00 (NF/Mt.P border)
    (111, 2, "Drill Tunnel"),         # MAYO02_2  s2 -> MAYO11
    (112, 0, "Native Forest"),        # TRAI00    s0 -> MAYO00
    (115, 0, "Geko Swamp"),           # MIST01    s0 -> STIC02
    (119, 2, "Toy Town"),             # MIST05    s2 -> OMOC01
    (121, 2, "Freezeland"),           # MIST07    s2 -> FRZL08
    (127, 1, "Freezeland"),           # GCAN04_2  s1 -> FRZL01
    (138, 0, "Gear Savanna"),         # STIC01    s0 -> GIAS08
    (139, 2, "Misty Trees"),          # STIC02    s2 -> MIST01
    (144, 0, "Misty Trees"),          # OMOC01    s0 -> MIST05
    (156, 1, "Gear Savanna"),         # FACT05    s1 -> GIAS02 (one-way back gate)
    (180, 0, "Native Forest"),        # TWNB01..24 s0 -> MAYO00  [folded x24]
    (180, 2, "Native Forest"),        # TWNB01..24 s2 -> MAYO08A [folded x24]
)
assert len(TRANSITION_GATE_ROWS) == 33, len(TRANSITION_GATE_ROWS)
assert list(TRANSITION_GATE_ROWS) == sorted(TRANSITION_GATE_ROWS), (
    "TRANSITION_GATE_ROWS must stay sorted by (screen, slot)"
)
for _scr, _slot, _region in TRANSITION_GATE_ROWS:
    assert 0 <= _scr < 255 and 0 <= _slot < 10, (_scr, _slot)
    assert _scr not in range(_TWNB_FIRST + 1, _TWNB_LAST + 1), (
        f"screen {_scr}: TWNB clones fold onto {_TWNB_CANONICAL}; individual "
        f"clone rows would be dead weight the wrapper never matches"
    )
    assert _region in REGION_ACCESS_TRIGGER_IDS, _region
del _scr, _slot, _region


def build_transition_gate_table(locked_regions: frozenset[str] | set[str]) -> bytes:
    """Encode the per-seed walk-on gate table.

    Emits only the rows whose gating region is in ``locked_regions``
    (mirroring how ``rules._apply_region_locks`` derives the locked set
    from the ``region_locking`` option), each as
    ``{u8 screen, u8 slot, u16 trigger}``, followed by the 4-byte
    ``0xFF`` terminator. Returns just the terminator when no row is
    locked (the patcher skips installing the hook in that case).
    """

    out = bytearray()
    for screen, slot, region in TRANSITION_GATE_ROWS:
        if region not in locked_regions:
            continue
        out += struct.pack("<BBH", screen, slot, REGION_ACCESS_TRIGGER_IDS[region])
    out += struct.pack("<BBH", 0xFF, 0, 0)
    return bytes(out)


# Layout invariants: wrapper + full table must fit the claimed gap and
# stay inside sector 148350's user-data window (which ends at RAM
# 0x80096800 = the EXT_ITEM_PARA seed base), so both tokens are flat
# single-sector writes.
_TRANSITION_GATE_FULL_TABLE_LEN: Final = (len(TRANSITION_GATE_ROWS) + 1) * 4  # 136
assert (
    TRANSITION_GATE_TABLE_RAM + _TRANSITION_GATE_FULL_TABLE_LEN
    <= EXT_ITEM_PARA_SEED_RAM
), "transition gate table overflows into the EXT_ITEM_PARA seed block"
assert TRANSITION_GATE_WRAPPER_OFFSET % 2352 + len(ROM_TRANSITION_GATE_WRAPPER_BYTES) \
    <= 2072, "transition gate wrapper write straddles a sector boundary"
assert TRANSITION_GATE_TABLE_OFFSET % 2352 + _TRANSITION_GATE_FULL_TABLE_LEN \
    <= 2072, "transition gate table write straddles a sector boundary"
assert TRANSITION_GATE_HOOK_OFFSET % 2352 + 4 <= 2072


# --- Script-class transition gates ------------------------------------------
#
# The script archive lives CONTIGUOUS in the .bin's 2048-B/sector
# user-data space at user base 0x1167E800 (lab structural find,
# byte-verified on five independent sites): script N sits at its archive
# slot (the hex value in DW1Script.txt's ``== Script ID N ==`` headers)
# and script-VM offsets are in-slot byte offsets — the disassembler's
# offset numbering maps 1:1 to user-space bytes (flat-offset deltas
# across sectors are the arithmetic artifact older comments tripped
# over). Script file layout: ``[u16 table_len][{u16 section, u16 off} x N]
# [FF FF][bytecode ...][FF 00 terminator][residue to the 0x800-aligned
# slot end]``. The residue is referenced by nothing (leftovers of
# neighboring builds) and is loaded into RAM with the script whenever it
# shares the script's final 2048-B block — free patch space for the
# gate stubs.
#
# Slot tails claimed by the stubs (all after the FF00 terminator, inside
# the script's final 2048-B block): script 163 @ 7976..8016, script 162
# @ 8780..8796, script 7 @ 3872..3904, script 101 @ 672..688.
SCRIPT_ARCHIVE_USER_BASE: Final = 0x1167E800
_SCRIPT_ARCHIVE_SLOTS: Final[dict[int, int]] = {
    6: 0x9800,      # Coela Point shore (screen 5): Coelamon recruit + ferry
    7: 0xA800,      # Dragon Eye Lake (screen 6): Blue Flute pier + ride offer
    101: 0x45800,   # Beetle Land pad (screen 105): return ferry
    162: 0x73000,   # File City TWNA variants: Whamon ferry dock
    163: 0x75800,   # File City market TWNB variants: west/east gates
    176: 0x84800,   # File City item-shop building interior (screen 216)
}
_SCRIPT_ARCHIVE_SLOT_SIZES: Final[dict[int, int]] = {
    6: 0x1000, 7: 0x1000, 101: 0x800, 162: 0x2800, 163: 0x2000, 176: 0x1800,
}


def script_vm_to_bin_offset(script: int, vm_offset: int) -> int:
    """Translate a script-VM offset to its raw Mode2/2352 .bin offset.

    ``user = SCRIPT_ARCHIVE_USER_BASE + archive_slot + vm_offset`` counts
    2048-byte user-data sectors; the flat offset re-interleaves the
    24-byte sector headers.
    """

    user = SCRIPT_ARCHIVE_USER_BASE + _SCRIPT_ARCHIVE_SLOTS[script] + vm_offset
    return (user // 2048) * 2352 + 24 + user % 2048


def _encode_script_if_trigger_unset(trigger_id: int, target: int) -> bytes:
    """``if trigger(id) == false then jump target`` (12 B single-cond IF).

    Ground-truthed form (clone of Script 163 vm 7592):
    ``19 00 | mode u16 | id u16 | 18 00 | target u16 | 19 00`` with
    mode 0 = jump when the trigger is UNSET.
    """

    return struct.pack("<HHHHHH", 0x0019, 0x0000, trigger_id, 0x0018, target, 0x0019)


def _encode_script_jump_to(target: int) -> bytes:
    """``jumpTo target`` (4 B): ``16 00 | target u16``."""

    return struct.pack("<HH", 0x0016, target)


# ``entityWalkTo 253 -3000 492 false`` — the market west gate's vanilla
# section head, replayed inside stub-W so the unlocked path keeps the
# vanilla walk-out animation.
_SCRIPT_GATE_ENTITY_WALK_WEST: Final = bytes.fromhex("4EFD48F4EC010000")


class ScriptGatePatch(NamedTuple):
    """One script-archive byte rewrite of the region-gate family."""

    script: int
    vm_offset: int
    data: bytes
    vanilla: bytes | None   # retarget sites only; stubs overwrite residue
    note: str


# Script-class gate patches, grouped by the LOCKABLE_REGION whose lock
# state enables them (the patcher emits a group iff its region is locked
# this seed). Every u16 target below is a vanilla VM offset inside the
# same script (decline/continue paths verified in the lab replay + live).
#
# Blocked behaviors are all graceful vanilla paths: the market gates end
# their section (player stays at the mouth; the east gate additionally
# needs Kunemon in town to be visually open — its vanilla trigger-232 IF
# is untouched and composes with the AP recruit remap); Whamon's
# "Factorial Town" choice behaves like "Nowhere"; the flute prompts close
# like "I won't play" / "Don't play"; the ride offer behaves like
# "No, maybe later".
SCRIPT_GATE_PATCHES: Final[dict[str, tuple[ScriptGatePatch, ...]]] = {
    "Native Forest": (
        # A-west: S51 entry head (entityWalkTo) -> jumpTo stub-W
        # (bytes 7568..7571 become dead).
        ScriptGatePatch(
            163, 7564, _encode_script_jump_to(7976), bytes.fromhex("4EFD48F4"),
            "market west gate: S51 head -> stub-W",
        ),
        # A-east: S53 "if trigger(232) == true then 7592" jump target -> stub-E.
        ScriptGatePatch(
            163, 7586, struct.pack("<H", 8000), struct.pack("<H", 7592),
            "market east gate: S53 IF target -> stub-E",
        ),
        # stub-W: if !NF-RA -> endSection@7576; else vanilla walk + jumpTo
        # the warpTo-109 continuation @7572.
        ScriptGatePatch(
            163, 7976,
            _encode_script_if_trigger_unset(
                REGION_ACCESS_TRIGGER_IDS["Native Forest"], 7576,
            ) + _SCRIPT_GATE_ENTITY_WALK_WEST + _encode_script_jump_to(7572),
            None,
            "stub-W over Script 163 slot-tail residue",
        ),
        # stub-E: if !NF-RA -> endSection@7590; else jumpTo the vanilla
        # bridge-variant IF @7592.
        ScriptGatePatch(
            163, 8000,
            _encode_script_if_trigger_unset(
                REGION_ACCESS_TRIGGER_IDS["Native Forest"], 7590,
            ) + _encode_script_jump_to(7592),
            None,
            "stub-E over Script 163 slot-tail residue",
        ),
        # C3: Beetle Land RETURN ferry (Script 101 S81 "Play" selection
        # target 242 -> stub-R), gated on Native Forest RA per user ruling
        # (the return re-enters Native Forest territory). A player who
        # FLIES into Beetle Land without NF RA cannot use the return
        # ferry; the sanctioned escape is the Auto Pilot item (warps to
        # File City) — accepted trap, documented in the player guide.
        ScriptGatePatch(
            101, 192, struct.pack("<H", 672), struct.pack("<H", 242),
            "Beetle Land return ferry: S81 selection[0] -> stub-R",
        ),
        # stub-R: if !NF-RA -> "Don't play" endSection@238; else jumpTo
        # the vanilla delay + warpTo-6 ride @242.
        ScriptGatePatch(
            101, 672,
            _encode_script_if_trigger_unset(
                REGION_ACCESS_TRIGGER_IDS["Native Forest"], 238,
            ) + _encode_script_jump_to(242),
            None,
            "stub-R over Script 101 slot-tail residue",
        ),
    ),
    "Factorial Town": (
        # B: Whamon ferry S55 setSelection target[0] ("Factorial Town")
        # 6864 -> stub-B. The ferry is the ONLY script entrance into
        # Factorial Town (lab-exhaustive scan); flight has its own gate.
        ScriptGatePatch(
            162, 6766, struct.pack("<H", 8780), struct.pack("<H", 6864),
            "Whamon ferry: S55 selection[0] -> stub-B",
        ),
        # stub-B: if !FT-RA -> "Nowhere" path@6872; else jumpTo warpTo-152
        # @6864.
        ScriptGatePatch(
            162, 8780,
            _encode_script_if_trigger_unset(
                REGION_ACCESS_TRIGGER_IDS["Factorial Town"], 6872,
            ) + _encode_script_jump_to(6864),
            None,
            "stub-B over Script 162 slot-tail residue",
        ),
    ),
    "Beetle Land": (
        # C1: Blue Flute pier S81 setSelection target[0] ("I'll play")
        # 246 -> stub-C1.
        ScriptGatePatch(
            7, 184, struct.pack("<H", 3872), struct.pack("<H", 246),
            "flute pier: S81 selection[0] -> stub-C1",
        ),
        # C2: post-friendship ride offer S82 setSelection target[0]
        # ("Yeah, I'll go") 3600 -> stub-C2. Without this the ride offer
        # is unconditional — Beetle Land reachable without any item.
        ScriptGatePatch(
            7, 2656, struct.pack("<H", 3888), struct.pack("<H", 3600),
            "ride offer: S82 selection[0] -> stub-C2",
        ),
        # stub-C1: if !BL-RA -> "I won't play" endSection@244; else jumpTo
        # the summon cutscene @246.
        ScriptGatePatch(
            7, 3872,
            _encode_script_if_trigger_unset(
                REGION_ACCESS_TRIGGER_IDS["Beetle Land"], 244,
            ) + _encode_script_jump_to(246),
            None,
            "stub-C1 over Script 7 slot-tail residue",
        ),
        # stub-C2: if !BL-RA -> "No, maybe later"@3784; else jumpTo the
        # ride @3600.
        ScriptGatePatch(
            7, 3888,
            _encode_script_if_trigger_unset(
                REGION_ACCESS_TRIGGER_IDS["Beetle Land"], 3784,
            ) + _encode_script_jump_to(3600),
            None,
            "stub-C2 over Script 7 slot-tail residue",
        ),
    ),
}

# Structural invariants: retarget payloads keep their vanilla length, no
# write leaves its script slot, and no write crosses a 2048-B sector
# user-data boundary (script tokens are flat single-sector writes).
for _patches in SCRIPT_GATE_PATCHES.values():
    for _p in _patches:
        if _p.vanilla is not None:
            assert len(_p.data) == len(_p.vanilla), _p.note
        assert _p.vm_offset + len(_p.data) <= _SCRIPT_ARCHIVE_SLOT_SIZES[_p.script], _p.note
        _user = SCRIPT_ARCHIVE_USER_BASE + _SCRIPT_ARCHIVE_SLOTS[_p.script] + _p.vm_offset
        assert _user % 2048 + len(_p.data) <= 2048, (
            f"script-gate write crosses a sector boundary: {_p.note}"
        )
del _patches, _p, _user


# --- Region-gate trigger-allocation invariants ------------------------------
#
# The 14 Region Access ids + the G Canyon Top flight bit must stay
# disjoint from every other shipped trigger allocation. Collected from
# the live manifest constants, not hardcoded lists, so any future
# reallocation trips this at module-load time.

def _trigger_id_of(ram_bit: tuple[int, int]) -> int:
    byte_addr, bit_index = ram_bit
    return (byte_addr - AP_TRIGGER_ARRAY_BASE) * 8 + bit_index


_REGION_GATE_TAKEN_TRIGGERS: frozenset[int] = frozenset(
    # Birdramon flight destination bits 880..884 (table trigger rewrites).
    {new_id for _off, new_id in ROM_BIRDRA_FLIGHT_TABLE_PATCHES}
    # Arena cup-win bits 885..889.
    | {trig for _tier, _bit, trig, _pp in ARENA_CUP_TIERS}
    # Vending purchase bits (890..895 + 898..901).
    | {item.trigger_id for machine in VENDING_MACHINES for item in machine.items}
    # Rod pickup-location bits 902/903.
    | {
        _trigger_id_of(OLD_FISHROD_LOCATION_BIT),
        _trigger_id_of(AMAZING_ROD_LOCATION_BIT),
    }
    # Recycle-shop purchase bits 904..910 and merit-shop bits 912..925.
    | set(RECYCLE_SHOP_TRIGGER_IDS)
    | set(MERIT_SHOP_TRIGGER_IDS)
)

_REGION_GATE_NEW_TRIGGERS: frozenset[int] = frozenset(
    REGION_ACCESS_TRIGGER_IDS.values()
) | {BIRDRA_FLIGHT_GCANYON_TRIGGER_ID}

assert len(REGION_ACCESS_TRIGGER_IDS) == 14
assert len(_REGION_GATE_NEW_TRIGGERS) == 15, "region-gate trigger ids must be distinct"
assert not (_REGION_GATE_NEW_TRIGGERS & _REGION_GATE_TAKEN_TRIGGERS), (
    f"region-gate trigger collision: "
    f"{sorted(_REGION_GATE_NEW_TRIGGERS & _REGION_GATE_TAKEN_TRIGGERS)}"
)
for _trig in _REGION_GATE_NEW_TRIGGERS:
    # Hard ceiling: nothing at or past byte 0x001BE042 (Meramon-tunnel
    # Drimogemon state bytes).
    assert (
        AP_TRIGGER_ARRAY_BASE + _trig // 8 < RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE
    ), f"trigger {_trig} lands in the danger zone"
    # Outside the recruit isTriggerSet-wrapper intercept range (203..258)
    # and above the vanilla-script ceiling (713) / engine-constant ceiling
    # (640, audited 2026-08-21).
    assert not 203 <= _trig <= 258, _trig
    assert _trig > 713, _trig
del _trig


# =============================================================================
# Shopsanity — File City item shop + Secret Shop + per-shop 3-mode config
# =============================================================================
#
# Lab-validated 2026-08-21 (three nets) in
# ``work/dw1_re/decomp/_scan_shopsanity/NOTES.md``, spec builder
# ``work/dw1_re/patches/shopsanity_spec.py``. This section is the faithful
# production port: same bytes, same addresses, same trigger ids.
#
# Mechanism summary:
#
# * **One screen-gated AP builder wrapper** at the money-shop dispatcher
#   callsite (``jal build_shop_runtime_list`` @ 0x800FC6AC). Gates on the
#   current screen: 131 = recycle, 181..188 / 216 = item shop (stall /
#   building), 217 = secret shop; anything else (incl. the Arena-Lobby
#   general shop) and the recycle buy-back dialog (trigger 3 set) fall to
#   vanilla. Per-shop mode from the 4-byte config
#   ``[recycle, item, secret, spare]`` (0 = off, 1 = coexist, 2 = replace):
#   coexist calls the vanilla builder then appends AP ``[id, flag]`` pairs,
#   replace emits only AP pairs. Flag = money >= relocated-table price.
#   Item-shop AP row count = 5/15/25 keyed on the Progressive Item Shop
#   tier-marker BEATEN bits (Betamon 724 / Patamon 751 / Biyomon 765);
#   secret pool = the on-duty clerk's 3 slots keyed on pstat(24).
# * **Extended giveItem wrapper** at the money-shop buy callsite
#   (``jal giveItem`` @ 0x800FB410): AP ids fire their purchase trigger and
#   return v0=1 with no inventory delivery (the shop already deducted
#   money); everything else tail-jumps vanilla giveItem. Supersedes the
#   retired v1 single-range recycle wrapper at 0x80095940 (that Cave6
#   region is freed for future use) and the retired recycle init-epilogue
#   wrapper (the builder wrapper renders AP rows synchronously).
# * **Code space**: the freed vanilla ITEM_DESC_PTR region
#   0x801279DC..0x80127BDC (512 B — dead code space once the desc-ptr
#   relocation redirects all three reader callsites to Cave6). Builder
#   wrapper 384 B @ 0x801279DC, giveItem ext 104 B @ 0x80127B5C, 24 B
#   spare.
# * **Ext seed staging**: item slots 149..157 fill the Cave6 seed block
#   (now 30/30 full: recycle 7 + merit 14 + item 9); slots 158..185 stage
#   in a second .bin-backed block at RAM 0x80115A4C (a 4216-B zero-init
#   run; boot-order audited — only the BIOS EXE loader touches it before
#   the hook site). The EXTENDED boot hook (55 words, grown in place at
#   :data:`ITEM_PARA_BOOT_HOOK_RAM`) adds loop 4 (staging -> relocated
#   slots 158..185) and loop 5 (re-zero staging, restoring the region's
#   boot invariant before its runtime owner initializes).
# * **Merit modes are data-only**: replace = the shipped 14 vanilla
#   meritValue zero-outs; coexist = omit them (no new bytes). Merit is
#   NOT in the config word — its callsite (0x8010BF3C) has its own
#   shipped ext wrapper.
#
# Trigger allocation (audit: ``work/dw1_re/scan_trigger_free_pool.txt``):
#
#   ids 149..164 -> trigger id+635 = 784..799 (bytes 0x1BE02F/0x1BE030)
#   ids 165..185 -> trigger id+691 = 856..876 (bytes 0x1BE038..0x1BE03A b0-4)
#   877 = Piximon Training Manual location (see ``PIXIMON_MANUAL_*`` at
#   the end of this module); 878/879 = region-gate bits (above).
#
# **The >=800-is-pstat rule**: trigger ids >= 800 overlap the byte-valued
# pstat array (``pstat(N)`` lives at 0x1BE031+N, i.e. triggers 800+8N ..
# 807+8N). pstat(0)..pstat(6) are engine-used (readPStat/writePStat
# constant-caller census, plus pstat(0) observed dynamically nonzero), so
# triggers 800..855 are OFF LIMITS forever. Bytes 0x1BE038+ (pstat 7+)
# audited free: vanilla scripts max out at trigger 713, engine constants
# at 640, zero direct-address or save-block-relative accesses.
#
# CAVEAT on that audit's METHOD (2026-08-22, `scriptvm` decomp unit).
# ``readPStat`` @ 0x801062E0 / ``writePStat`` @ 0x80106474 are
# ``*(u8 *)(*(u32 *)0x80134FB8 + target + 0x159)`` -- the offset 0x159 off
# the save-block pointer is what makes 0x1BE031 the pstat base, so that
# part is now derived from code rather than inferred. But live vector
# capture over the intro plus the shop/ferry/arena savestates observed
# targets **0, 2, 6, 28, 29, 30, 31, 103, 245, 247, 248 and 254** -- i.e.
# the constant-caller census above materially UNDER-counted the range,
# because plenty of callers pass a computed target (``dailyPStatTrigger``
# walks pstat 29-32; pstat(103) is the partner species; the 245-254 band
# is engine bookkeeping). The census's *conclusion* for the bytes AP
# actually claims still holds -- pstat 7, 8 and 9 (triggers 856..879) were
# never touched in any captured vector -- but the *method* is not
# sufficient on its own. Before claiming any further pstat byte, capture
# vectors rather than grepping for constants. Coverage caveat: 11 distinct
# targets over one capture session is not an exhaustive enumeration.
#
# STRUCTURAL CONFIRMATION (dw_decomp audit 2026-08-28): ``ScriptState``
# (``include/dw/script.h``) is ``... triggers[100] @ +0xF5, pstats[256]
# @ +0x159, stack[8] @ +0x259``, size 0x29C — so the overlap is a struct
# fact, not an inference. Engine constant pstat set from the C: {0..6,
# 121, 122 (curling), 200, 243..250, 254, 255}; pstat(250) is used as an
# INDIRECT index (``script_instr64.c:324-331``); pstat(0) is the time
# speed (forced to 3 in dialog). AP's claimed band pstat 7..16 (triggers
# 856..935) is clean under both the live capture and the C census.

ITEM_SHOP_AP_ITEM_ID_BASE: Final = 149
ITEM_SHOP_AP_ITEM_ID_COUNT: Final = 25
ITEM_SHOP_AP_ITEM_IDS: Final = tuple(
    ITEM_SHOP_AP_ITEM_ID_BASE + i for i in range(ITEM_SHOP_AP_ITEM_ID_COUNT)
)
# Progressive Item Shop tier composition: T1 = first 5 slots, T2 = +10,
# T3 = +10 (lab: T1 = ids 149..153, T2 = +154..163, T3 = +164..173).
ITEM_SHOP_TIER_COUNTS: Final[tuple[int, int, int]] = (5, 10, 10)
assert sum(ITEM_SHOP_TIER_COUNTS) == ITEM_SHOP_AP_ITEM_ID_COUNT

SECRET_SHOP_AP_ITEM_ID_BASE: Final = 174
SECRET_SHOP_AP_ITEM_ID_COUNT: Final = 12
SECRET_SHOP_AP_ITEM_IDS: Final = tuple(
    SECRET_SHOP_AP_ITEM_ID_BASE + i for i in range(SECRET_SHOP_AP_ITEM_ID_COUNT)
)
# On-duty clerk c (pstat(24)) sells ids 174+3c .. 176+3c.
SECRET_SHOP_CLERKS: Final[tuple[str, ...]] = (
    "Numemon", "Mojyamon", "Mamemon", "Devimon",
)
SECRET_SHOP_ITEMS_PER_CLERK: Final = 3
assert len(SECRET_SHOP_CLERKS) * SECRET_SHOP_ITEMS_PER_CLERK == SECRET_SHOP_AP_ITEM_ID_COUNT

assert ITEM_SHOP_AP_ITEM_ID_BASE == MERIT_SHOP_AP_ITEM_ID_LAST + 1
assert SECRET_SHOP_AP_ITEM_ID_BASE == ITEM_SHOP_AP_ITEM_IDS[-1] + 1
# The setItemTexture icon-id table must span exactly the ext id band
# (recycle 128..134 + merit 135..148 + item 149..173 + secret 174..185).
assert AP_ICON_ID_TABLE_BASE_ITEM_ID == RECYCLE_SHOP_AP_ITEM_ID_BASE
assert (
    AP_ICON_ID_TABLE_BASE_ITEM_ID + AP_ICON_ID_TABLE_SIZE - 1
    == SECRET_SHOP_AP_ITEM_IDS[-1]
)

# --- Purchase-location triggers ----------------------------------------------

SHOP_AP_TRIGGER_OFFSET_A: Final = 635          # ids 149..164 -> 784..799
SHOP_AP_TRIGGER_RANGE_A: Final = (149, 164)
SHOP_AP_TRIGGER_OFFSET_B: Final = 691          # ids 165..185 -> 856..876
SHOP_AP_TRIGGER_RANGE_B: Final = (165, 185)


def shop_ap_trigger_for_slot(slot: int) -> int:
    """AP purchase trigger id for ext ITEM_PARA slot ``slot`` (149..185)."""

    if SHOP_AP_TRIGGER_RANGE_A[0] <= slot <= SHOP_AP_TRIGGER_RANGE_A[1]:
        return slot + SHOP_AP_TRIGGER_OFFSET_A
    if SHOP_AP_TRIGGER_RANGE_B[0] <= slot <= SHOP_AP_TRIGGER_RANGE_B[1]:
        return slot + SHOP_AP_TRIGGER_OFFSET_B
    raise ValueError(f"slot {slot} has no shopsanity trigger")


ITEM_SHOP_TRIGGER_IDS: Final = tuple(
    shop_ap_trigger_for_slot(slot) for slot in ITEM_SHOP_AP_ITEM_IDS
)
SECRET_SHOP_TRIGGER_IDS: Final = tuple(
    shop_ap_trigger_for_slot(slot) for slot in SECRET_SHOP_AP_ITEM_IDS
)
assert ITEM_SHOP_TRIGGER_IDS == tuple(range(784, 800)) + tuple(range(856, 865))
assert SECRET_SHOP_TRIGGER_IDS == tuple(range(865, 877))

ITEM_SHOP_LOCATION_NAMES: Final = tuple(
    f"Item Shop #{i + 1}" for i in range(ITEM_SHOP_AP_ITEM_ID_COUNT)
)
# Clerk-identifiable secret-shop names: the pool shown in-game is the
# on-duty clerk's; players can leave + re-enter to rotate clerks.
SECRET_SHOP_LOCATION_NAMES: Final = tuple(
    f"Secret Shop ({clerk}) #{j + 1}"
    for clerk in SECRET_SHOP_CLERKS
    for j in range(SECRET_SHOP_ITEMS_PER_CLERK)
)

ITEM_SHOP_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    name: (
        AP_TRIGGER_ARRAY_BASE + ITEM_SHOP_TRIGGER_IDS[i] // 8,
        ITEM_SHOP_TRIGGER_IDS[i] % 8,
    )
    for i, name in enumerate(ITEM_SHOP_LOCATION_NAMES)
}
SECRET_SHOP_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    name: (
        AP_TRIGGER_ARRAY_BASE + SECRET_SHOP_TRIGGER_IDS[i] // 8,
        SECRET_SHOP_TRIGGER_IDS[i] % 8,
    )
    for i, name in enumerate(SECRET_SHOP_LOCATION_NAMES)
}

# --- Per-shop mode config ----------------------------------------------------
# 4 bytes ``[recycle, item, secret, spare]`` in the 16-B Cave6 gap between
# the transition-gate table (ends 0x800967F0) and the EXT_ITEM_PARA seed
# block (starts 0x80096800). Gen-time data token; the builder wrapper
# reads it at runtime.

SHOP_MODE_OFF: Final = 0
SHOP_MODE_COEXIST: Final = 1
SHOP_MODE_REPLACE: Final = 2

SHOP_AP_CONFIG_RAM: Final = 0x800967F0
SHOP_AP_CONFIG_BIN_OFFSET: Final = _slus_ram_to_bin_offset(SHOP_AP_CONFIG_RAM)
assert TRANSITION_GATE_TABLE_RAM + _TRANSITION_GATE_FULL_TABLE_LEN <= SHOP_AP_CONFIG_RAM
assert SHOP_AP_CONFIG_RAM + 4 <= EXT_ITEM_PARA_SEED_RAM
# 4-byte write must not straddle the Mode2/2352 user-data window.
assert 24 <= SHOP_AP_CONFIG_BIN_OFFSET % 2352 <= 2072 - 4


def build_shop_ap_config_bytes(recycle_mode: int, item_mode: int, secret_mode: int) -> bytes:
    """The 4-byte SHOP_AP_CONFIG payload ``[recycle, item, secret, 0]``."""

    for mode in (recycle_mode, item_mode, secret_mode):
        assert mode in (SHOP_MODE_OFF, SHOP_MODE_COEXIST, SHOP_MODE_REPLACE), mode
    return bytes((recycle_mode, item_mode, secret_mode, 0))


# --- Second seed block staging (slots 158..185) ------------------------------

SHOP_AP_STAGING2_RAM: Final = 0x80115A4C
SHOP_AP_STAGING2_SLOT_BASE: Final = 158
SHOP_AP_STAGING2_SLOT_COUNT: Final = 28
SHOP_AP_STAGING2_SLOT_LAST: Final = (
    SHOP_AP_STAGING2_SLOT_BASE + SHOP_AP_STAGING2_SLOT_COUNT - 1             # 185
)
SHOP_AP_STAGING2_SIZE: Final = (
    SHOP_AP_STAGING2_SLOT_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE                  # 896
)
SHOP_AP_STAGING2_BIN_OFFSET: Final = _slus_ram_to_bin_offset(SHOP_AP_STAGING2_RAM)
assert SHOP_AP_STAGING2_BIN_OFFSET == 0x14D53ED4, hex(SHOP_AP_STAGING2_BIN_OFFSET)
assert SHOP_AP_STAGING2_SLOT_BASE == EXT_ITEM_PARA_SEED_SLOT_LAST + 1
assert SHOP_AP_STAGING2_SLOT_LAST == SECRET_SHOP_AP_ITEM_IDS[-1]
# The whole 896-B run must sit inside one sector's user-data window so the
# per-slot flat adds in ext_item_para_slot_bin_offset never cross EDC/header
# bytes.
assert 24 <= SHOP_AP_STAGING2_BIN_OFFSET % 2352
assert SHOP_AP_STAGING2_BIN_OFFSET % 2352 + SHOP_AP_STAGING2_SIZE <= 2072

# --- MIPS word encoders (shopsanity-local complements of the shared set) -----


def _mips_lbu(rt: int, rs: int, imm: int) -> int:
    return 0x90000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_sb(rt: int, rs: int, imm: int) -> int:
    return 0xA0000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_andi(rt: int, rs: int, imm: int) -> int:
    return 0x30000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_xori(rt: int, rs: int, imm: int) -> int:
    return 0x38000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_sltiu(rt: int, rs: int, imm: int) -> int:
    return 0x2C000000 | (rs << 21) | (rt << 16) | (imm & 0xFFFF)


def _mips_slt(rd: int, rs: int, rt: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x2A


def _mips_or(rd: int, rs: int, rt: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x25


def _mips_addu(rd: int, rs: int, rt: int) -> int:
    return (rs << 21) | (rt << 16) | (rd << 11) | 0x21


def _mips_sll(rd: int, rt: int, sa: int) -> int:
    return (rt << 16) | (rd << 11) | (sa << 6) | 0x00


def _mips_beq(rs: int, rt: int, off: int) -> int:
    return 0x10000000 | (rs << 21) | (rt << 16) | (off & 0xFFFF)


def _mips_j(target: int) -> int:
    return 0x08000000 | ((target >> 2) & 0x03FFFFFF)


def _mips_jr(rs: int) -> int:
    return (rs << 21) | 0x08


def _resolve_mips_labels(body: list) -> list[int]:
    """Two passes: collect label indices, then encode symbolic branches.

    Entry forms (faithful port of the lab spec builder's resolver):

    * plain ``int`` — an already-encoded word;
    * ``(label, entry)`` with ``label: str`` — defines ``label`` at this
      index; ``entry`` is itself a plain word or a symbolic branch;
    * ``(kind, rs, rt, label)`` with ``kind in {"beq", "bne"}`` — a
      symbolic branch to ``label``.
    """

    labels: dict[str, int] = {}
    flat: list = []
    for entry in body:
        if isinstance(entry, tuple) and isinstance(entry[0], str) and len(entry) == 2:
            labels[entry[0]] = len(flat)
            flat.append(entry[1])
        else:
            flat.append(entry)
    out: list[int] = []
    for idx, entry in enumerate(flat):
        if isinstance(entry, tuple):
            kind, rs, rt, label = entry
            off = labels[label] - (idx + 1)
            out.append(
                _mips_beq(rs, rt, off) if kind == "beq" else _mips_bne(rs, rt, off)
            )
        else:
            out.append(entry)
    return out


# --- AP builder wrapper ------------------------------------------------------
# Callsite + callee facts (verified in the source .bin by the lab Net 1):
# the money-shop dispatcher calls build_shop_runtime_list (0x800FA834, the
# VERIFIED decomp unit) via ``jal`` at 0x800FC6AC; the buy path calls
# giveItem (0x800C5240) via ``jal`` at 0x800FB410 (the same site the
# retired v1 recycle wrapper hijacked). setTrigger = 0x801065C0.

_SHOP_BUILD_RUNTIME_LIST_RAM: Final = 0x800FA834
assert _SHOP_BUILD_RUNTIME_LIST_RAM == ROM_RECYCLE_SHOP_INIT_RAM
_SHOP_GIVEITEM_RAM: Final = 0x800C5240
_SHOP_SETTRIGGER_RAM: Final = 0x801065C0

# gp-relative runtime state ($gp = 0x8013BB2C): current screen u8,
# shop_obj ptr, money s32.
_SHOP_SCREEN_GP_OFF: Final = -0x6D84           # 0x80134DA8
_SHOP_SHOPOBJ_GP_OFF: Final = -0x6BC4          # 0x80134F68
_SHOP_MONEY_GP_OFF: Final = -0x6C74            # 0x80134EB8
assert 0x8013BB2C + _SHOP_SHOPOBJ_GP_OFF == 0x80000000 | RAM_RECYCLE_SHOP_GP_SLOT
assert 0x8013BB2C + _SHOP_MONEY_GP_OFF == 0x80000000 | RAM_CURRENT_BITS

_SHOP_TRIG0_ADDR: Final = 0x80000000 | AP_TRIGGER_ARRAY_BASE   # trigger 3 = bit 3
_SHOP_PSTAT24_ADDR: Final = 0x801BE049
# Progressive Item Shop tier markers = the BEATEN bits of the tier-1/2/3
# marker Digimon (Betamon 724 / Patamon 751 / Biyomon 765).
_SHOP_TIER_MARKERS: Final[tuple[tuple[int, int], ...]] = tuple(
    (0x80000000 | byte_addr, 1 << bit)
    for byte_addr, bit in (
        BEATEN_RAM_BITS["Betamon"],
        BEATEN_RAM_BITS["Patamon"],
        BEATEN_RAM_BITS["Biyomon"],
    )
)
assert _SHOP_TIER_MARKERS == (
    (0x801BE027, 0x10), (0x801BE02A, 0x80), (0x801BE02C, 0x20),
)
# Relocated-table price field: value i32 @ entry+20.
_SHOP_PRICE_BASE: Final = ITEM_PARA_RELOC_BASE_KUSEG + 20      # 0x801BFB84


def _shop_neg16(addr: int) -> int:
    """imm such that ``lui 0x801C`` + sign-extended imm == addr."""

    return addr - 0x801C0000


def _build_shop_ap_builder_wrapper_bytes() -> bytes:
    """The 96-word screen-gated AP builder wrapper (lab-validated).

    Faithful port of the lab's ``assemble_builder_wrapper`` (Net-1: 752
    interpreter-replay cases of the ACTUAL assembled words vs an
    independent model; Net-2 live battery; Net-3 disc boot). Do not
    restructure — the byte-fidelity test pins the exact output.
    """

    zero, at, v0 = 0, 1, 2
    t0, t1, t2, t3, t4, t5, t6, t7 = 8, 9, 10, 11, 12, 13, 14, 15
    gp, sp, ra = 28, 29, 31

    (beta_addr, beta_mask), (pata_addr, pata_mask), (biyo_addr, biyo_mask) = _SHOP_TIER_MARKERS
    cfg_hi, cfg_lo = _decompose_kuseg(SHOP_AP_CONFIG_RAM)

    l_van, l_rec, l_sec, l_itm, l_td = "van", "rec", "sec", "itm", "td"
    l_have, l_rep, l_co, l_emit, l_loop = "have", "rep", "co", "emit", "loop"

    body: list = [
        _mips_lbu(t7, gp, _SHOP_SCREEN_GP_OFF),        # 0  screen
        _mips_lui(t6, cfg_hi),                         # 1  (t7 delay)
        _mips_addiu(t6, t6, cfg_lo),                   # 2  t6 = &config
        _mips_lui(t4, 0x801C),                         # 3  t4 = hi base
        _mips_lbu(t5, t4, _shop_neg16(_SHOP_TRIG0_ADDR)),   # 4  trigger byte 0
        _mips_addiu(at, zero, 131),                    # 5  (t5 delay)
        _mips_andi(t5, t5, 0x08),                      # 6  trigger 3 (buy-back)
        ("bne", t5, zero, l_van),                      # 7
        _mips_nop(),                                   # 8  (delay)
        ("beq", t7, at, l_rec),                        # 9
        _mips_addiu(at, t7, -181),                     # 10 (delay)
        _mips_sltiu(at, at, 8),                        # 11 stall band 181..188
        ("bne", at, zero, l_itm),                      # 12
        _mips_addiu(at, zero, 216),                    # 13 (delay)
        ("beq", t7, at, l_itm),                        # 14
        _mips_addiu(at, zero, 217),                    # 15 (delay)
        ("beq", t7, at, l_sec),                        # 16
        _mips_nop(),                                   # 17 (delay)
        (l_van, _mips_j(_SHOP_BUILD_RUNTIME_LIST_RAM)),  # 18 tail-jump, ra intact
        _mips_nop(),                                   # 19 (delay)
        (l_rec, _mips_lbu(t5, t6, 0)),                 # 20 mode = config[0]
        _mips_addiu(t2, zero, RECYCLE_SHOP_AP_ITEM_ID_BASE),   # 21 (t5 delay)
        ("beq", zero, zero, l_have),                   # 22
        _mips_addiu(t3, zero, RECYCLE_SHOP_AP_ITEM_ID_COUNT),  # 23 count (delay)
        (l_sec, _mips_lbu(t5, t6, 2)),                 # 24 mode = config[2]
        _mips_lbu(t1, t4, _shop_neg16(_SHOP_PSTAT24_ADDR)),    # 25 pstat(24)
        _mips_nop(),                                   # 26 (t1 delay)
        _mips_sltiu(at, t1, 4),                        # 27
        ("beq", at, zero, l_van),                      # 28 invalid clerk -> vanilla
        _mips_sll(t2, t1, 1),                          # 29 (delay) 2*clerk
        _mips_addu(t2, t2, t1),                        # 30 3*clerk
        _mips_addiu(t2, t2, SECRET_SHOP_AP_ITEM_ID_BASE),      # 31 base = 174+3c
        ("beq", zero, zero, l_have),                   # 32
        _mips_addiu(t3, zero, SECRET_SHOP_ITEMS_PER_CLERK),    # 33 count (delay)
        (l_itm, _mips_lbu(t5, t6, 1)),                 # 34 mode = config[1]
        _mips_lbu(t1, t4, _shop_neg16(beta_addr)),     # 35 Betamon beaten byte
        _mips_lbu(t0, t4, _shop_neg16(pata_addr)),     # 36 Patamon beaten byte
        _mips_andi(t1, t1, beta_mask),                 # 37
        ("beq", t1, zero, l_van),                      # 38 tier 0 -> vanilla
        _mips_andi(t0, t0, pata_mask),                 # 39 (delay)
        _mips_lbu(t1, t4, _shop_neg16(biyo_addr)),     # 40 Biyomon beaten byte
        _mips_addiu(t3, zero, 5),                      # 41 count = 5 (t1 delay)
        ("beq", t0, zero, l_td),                       # 42
        _mips_andi(t1, t1, biyo_mask),                 # 43 (delay)
        _mips_addiu(t3, zero, 15),                     # 44 count = 15
        ("beq", t1, zero, l_td),                       # 45
        _mips_nop(),                                   # 46 (delay)
        _mips_addiu(t3, zero, 25),                     # 47 count = 25
        (l_td, _mips_addiu(t2, zero, ITEM_SHOP_AP_ITEM_ID_BASE)),   # 48 base = 149
        (l_have, ("beq", t5, zero, l_van)),            # 49 mode 0 -> off
        _mips_addiu(at, zero, 1),                      # 50 (delay)
        ("beq", t5, at, l_co),                         # 51
        _mips_nop(),                                   # 52 (delay)
        (l_rep, _mips_lw(t0, gp, _SHOP_SHOPOBJ_GP_OFF)),       # 53 shop_obj
        _mips_addiu(v0, zero, 0),                      # 54 result = 0 (t0 delay)
        _mips_lw(t1, t0, 0),                           # 55 cursor = array base
        _mips_sb(t3, t0, 8),                           # 56 entry_count = count
        ("beq", zero, zero, l_emit),                   # 57
        _mips_nop(),                                   # 58 (delay)
        (l_co, _mips_addiu(sp, sp, -0x20)),            # 59
        _mips_sw(ra, sp, 0x1C),                        # 60
        _mips_sw(t2, sp, 0x14),                        # 61
        _mips_jal(_SHOP_BUILD_RUNTIME_LIST_RAM),       # 62
        _mips_sw(t3, sp, 0x18),                        # 63 (jal delay — pre-call)
        _mips_lw(t2, sp, 0x14),                        # 64
        _mips_lw(t3, sp, 0x18),                        # 65
        _mips_lw(ra, sp, 0x1C),                        # 66
        _mips_addiu(sp, sp, 0x20),                     # 67
        _mips_lw(t0, gp, _SHOP_SHOPOBJ_GP_OFF),        # 68 shop_obj
        _mips_nop(),                                   # 69 (t0 delay)
        _mips_lw(t1, t0, 0),                           # 70 array base
        _mips_lbu(t4, t0, 8),                          # 71 vanilla entry_count
        _mips_nop(),                                   # 72 (t4 delay)
        _mips_sll(at, t4, 1),                          # 73
        _mips_addu(t1, t1, at),                        # 74 cursor = base + 2*count
        _mips_addu(t4, t4, t3),                        # 75
        _mips_sb(t4, t0, 8),                           # 76 entry_count += AP count
        (l_emit, _mips_sll(at, t2, 5)),                # 77 id*32
        _mips_lui(t6, 0x801C),                         # 78
        _mips_addiu(t6, t6, _shop_neg16(_SHOP_PRICE_BASE)),    # 79 0x801BFB84
        _mips_addu(t6, t6, at),                        # 80 &price[base id]
        _mips_lw(t7, gp, _SHOP_MONEY_GP_OFF),          # 81 money
        (l_loop, _mips_sb(t2, t1, 0)),                 # 82 *cursor = id
        _mips_lw(t4, t6, 0),                           # 83 price
        _mips_addiu(t1, t1, 2),                        # 84 (t4 delay)
        _mips_slt(at, t7, t4),                         # 85 money < price
        _mips_xori(t4, at, 1),                         # 86 flag
        _mips_or(v0, v0, t4),                          # 87
        _mips_sb(t4, t1, -1),                          # 88 cursor[-1] = flag
        _mips_addiu(t2, t2, 1),                        # 89
        _mips_addiu(t6, t6, 32),                       # 90
        _mips_addiu(t3, t3, -1),                       # 91
        ("bne", t3, zero, l_loop),                     # 92
        _mips_nop(),                                   # 93 (delay)
        _mips_jr(ra),                                  # 94
        _mips_nop(),                                   # 95 (delay)
    ]
    words = _resolve_mips_labels(body)
    assert len(words) == 96, len(words)
    return b"".join(struct.pack("<I", w & 0xFFFFFFFF) for w in words)


def _mips_nop() -> int:
    return 0


def _build_shop_ap_giveitem_ext_bytes() -> bytes:
    """The 26-word extended giveItem range-dispatch wrapper (lab-validated).

    ids 128..134 -> setTrigger(id+776) [904..910, shipped recycle range],
    ids 149..164 -> setTrigger(id+635) [784..799],
    ids 165..185 -> setTrigger(id+691) [856..876],
    else tail-jump vanilla giveItem. AP ids return v0=1 with no delivery.
    """

    zero, at, v0, a0 = 0, 1, 2, 4
    t0, sp, ra = 8, 29, 31
    l_fr, l_fa, l_fb, l_fire = "fr", "fa", "fb", "fire"

    range_a_len = SHOP_AP_TRIGGER_RANGE_A[1] - SHOP_AP_TRIGGER_RANGE_A[0] + 1
    range_b_len = SHOP_AP_TRIGGER_RANGE_B[1] - SHOP_AP_TRIGGER_RANGE_B[0] + 1

    body: list = [
        _mips_addiu(at, a0, -RECYCLE_SHOP_AP_ITEM_ID_BASE),        # 0
        _mips_sltiu(t0, at, RECYCLE_SHOP_AP_ITEM_ID_COUNT),        # 1
        ("bne", t0, zero, l_fr),                                   # 2  128..134
        _mips_addiu(at, a0, -SHOP_AP_TRIGGER_RANGE_A[0]),          # 3  (delay)
        _mips_sltiu(t0, at, range_a_len),                          # 4
        ("bne", t0, zero, l_fa),                                   # 5  149..164
        _mips_addiu(at, a0, -SHOP_AP_TRIGGER_RANGE_B[0]),          # 6  (delay)
        _mips_sltiu(t0, at, range_b_len),                          # 7
        ("bne", t0, zero, l_fb),                                   # 8  165..185
        _mips_nop(),                                               # 9  (delay)
        _mips_j(_SHOP_GIVEITEM_RAM),                               # 10 vanilla
        _mips_nop(),                                               # 11 (delay)
        (l_fr, ("beq", zero, zero, l_fire)),                       # 12
        _mips_addiu(a0, a0, RECYCLE_SHOP_TRIGGER_BASE - RECYCLE_SHOP_AP_ITEM_ID_BASE),  # 13
        (l_fa, ("beq", zero, zero, l_fire)),                       # 14
        _mips_addiu(a0, a0, SHOP_AP_TRIGGER_OFFSET_A),             # 15 (delay)
        (l_fb, ("beq", zero, zero, l_fire)),                       # 16
        _mips_addiu(a0, a0, SHOP_AP_TRIGGER_OFFSET_B),             # 17 (delay)
        (l_fire, _mips_addiu(sp, sp, -0x10)),                      # 18
        _mips_sw(ra, sp, 0x0C),                                    # 19
        _mips_jal(_SHOP_SETTRIGGER_RAM),                           # 20
        _mips_nop(),                                               # 21 (delay)
        _mips_lw(ra, sp, 0x0C),                                    # 22
        _mips_addiu(sp, sp, 0x10),                                 # 23
        _mips_jr(ra),                                              # 24
        _mips_addiu(v0, zero, 1),                                  # 25 (delay)
    ]
    words = _resolve_mips_labels(body)
    assert len(words) == 26, len(words)
    return b"".join(struct.pack("<I", w & 0xFFFFFFFF) for w in words)


# --- Wrapper placement (freed vanilla ITEM_DESC_PTR region) ------------------
# Layout of the freed 512-B region at 0x801279DC (dead once the desc-ptr
# relocation is installed — which the patcher does whenever ANY shop mode
# is != off):
#
#   0x801279DC..0x80127B5C  AP builder wrapper (384 B = 96 words)
#   0x80127B5C..0x80127BC4  extended giveItem wrapper (104 B = 26 words)
#   0x80127BC4..0x80127BDC  24 B spare

SHOP_AP_BUILDER_WRAPPER_RAM: Final = VANILLA_ITEM_DESC_PTR_RAM               # 0x801279DC
SHOP_AP_BUILDER_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    SHOP_AP_BUILDER_WRAPPER_RAM,
)
SHOP_AP_BUILDER_WRAPPER_BYTES: Final = _build_shop_ap_builder_wrapper_bytes()
assert len(SHOP_AP_BUILDER_WRAPPER_BYTES) == 384

SHOP_AP_GIVEITEM_EXT_RAM: Final = SHOP_AP_BUILDER_WRAPPER_RAM + 0x180        # 0x80127B5C
SHOP_AP_GIVEITEM_EXT_OFFSET: Final = _slus_ram_to_bin_offset(SHOP_AP_GIVEITEM_EXT_RAM)
SHOP_AP_GIVEITEM_EXT_BYTES: Final = _build_shop_ap_giveitem_ext_bytes()
assert len(SHOP_AP_GIVEITEM_EXT_BYTES) == 104

_SHOP_AP_FREED_REGION_END_RAM: Final = SHOP_AP_BUILDER_WRAPPER_RAM + 512     # 0x80127BDC
assert SHOP_AP_BUILDER_WRAPPER_RAM + len(SHOP_AP_BUILDER_WRAPPER_BYTES) <= SHOP_AP_GIVEITEM_EXT_RAM
assert SHOP_AP_GIVEITEM_EXT_RAM + len(SHOP_AP_GIVEITEM_EXT_BYTES) <= _SHOP_AP_FREED_REGION_END_RAM

# --- Callsite jal redirects --------------------------------------------------

SHOP_AP_DISPATCHER_JAL_RAM: Final = 0x800FC6AC
SHOP_AP_DISPATCHER_JAL_OFFSET: Final = _slus_ram_to_bin_offset(SHOP_AP_DISPATCHER_JAL_RAM)
SHOP_AP_DISPATCHER_JAL_VANILLA: Final = 0x0C03EA0D           # jal build_shop_runtime_list
assert SHOP_AP_DISPATCHER_JAL_VANILLA == _mips_jal(_SHOP_BUILD_RUNTIME_LIST_RAM)
SHOP_AP_DISPATCHER_JAL_VALUE: Final = _mips_jal(SHOP_AP_BUILDER_WRAPPER_RAM)
assert SHOP_AP_DISPATCHER_JAL_VALUE == 0x0C049E77, hex(SHOP_AP_DISPATCHER_JAL_VALUE)

SHOP_AP_GIVEITEM_JAL_RAM: Final = 0x800FB410
SHOP_AP_GIVEITEM_JAL_OFFSET: Final = _slus_ram_to_bin_offset(SHOP_AP_GIVEITEM_JAL_RAM)
SHOP_AP_GIVEITEM_JAL_VANILLA: Final = 0x0C031490             # jal giveItem
assert SHOP_AP_GIVEITEM_JAL_VANILLA == _mips_jal(_SHOP_GIVEITEM_RAM)
SHOP_AP_GIVEITEM_JAL_VALUE: Final = _mips_jal(SHOP_AP_GIVEITEM_EXT_RAM)
assert SHOP_AP_GIVEITEM_JAL_VALUE == 0x0C049ED7, hex(SHOP_AP_GIVEITEM_JAL_VALUE)
# Same callsite the retired v1 recycle wrapper hijacked — the ext wrapper
# subsumes it (and the .bin offset is byte-identical).
assert SHOP_AP_GIVEITEM_JAL_OFFSET == ROM_RECYCLE_SHOP_PATCH_OFFSET

# --- Extended boot hook (55 words) -------------------------------------------


def _build_item_para_boot_hook_ext_bytes() -> bytes:
    """The EXTENDED 55-word boot seed hook (lab-validated).

    = the always-on 37-word hook (:func:`_build_item_para_boot_hook_bytes`)
    with two extra loops spliced in before the epilogue:

    * loop 4: copy the second seed block (896 B) from the staging region
      at :data:`SHOP_AP_STAGING2_RAM` over relocated slots 158..185;
    * loop 5: re-zero the staging region (restore the boot invariant —
      the region is a runtime-active workspace whose owner starts
      strictly after the hook site; boot-order evidence in the lab
      NOTES).

    Emitted (over the base hook token) whenever ANY shop mode != off.
    """

    zero, t0, t1, t2, t3 = 0, 8, 9, 10, 11

    base_words = list(struct.unpack("<37I", ITEM_PARA_BOOT_HOOK_BYTES))
    s2_hi, s2_lo = _decompose_kuseg(SHOP_AP_STAGING2_RAM)          # (0x8011, 0x5A4C)
    seed2_dst = ITEM_PARA_RELOC_BASE_KUSEG + SHOP_AP_STAGING2_SLOT_BASE * ROM_ITEM_TABLE_ENTRY_SIZE
    assert seed2_dst == 0x801C0F30, hex(seed2_dst)
    dst_hi, dst_lo = _decompose_kuseg(seed2_dst)                   # (0x801C, 0x0F30)

    words = [
        *base_words[:33],
        # loop 4: staging2 (896 B) -> RELOC slots 158..185
        _mips_lui(t0, s2_hi), _mips_addiu(t0, t0, s2_lo),          # 33,34
        _mips_lui(t1, dst_hi), _mips_addiu(t1, t1, dst_lo),        # 35,36
        _mips_addiu(t2, zero, SHOP_AP_STAGING2_SIZE),              # 37
        _mips_lw(t3, t0, 0),                                       # 38 L4:
        _mips_addiu(t0, t0, 4),                                    # 39 (t3 delay)
        _mips_sw(t3, t1, 0),                                       # 40
        _mips_addiu(t2, t2, -4),                                   # 41
        _mips_bne(t2, zero, 38 - 43),                              # 42 -> L4
        _mips_addiu(t1, t1, 4),                                    # 43 (delay)
        # loop 5: re-zero the staging region (restore boot invariant)
        _mips_lui(t0, s2_hi), _mips_addiu(t0, t0, s2_lo),          # 44,45
        _mips_addiu(t2, zero, SHOP_AP_STAGING2_SIZE),              # 46
        _mips_sw(zero, t0, 0),                                     # 47 L5:
        _mips_addiu(t2, t2, -4),                                   # 48
        _mips_bne(t2, zero, 47 - 50),                              # 49 -> L5
        _mips_addiu(t0, t0, 4),                                    # 50 (delay)
        *base_words[33:],
    ]
    assert len(words) == 55, len(words)
    return b"".join(struct.pack("<I", w) for w in words)


ITEM_PARA_BOOT_HOOK_EXT_BYTES: Final = _build_item_para_boot_hook_ext_bytes()
assert len(ITEM_PARA_BOOT_HOOK_EXT_BYTES) == 220
# Grown in place: same prefix (loops 1..3) and same epilogue as the base
# hook, still clear of the transition-gate wrapper at 0x800966C4.
assert ITEM_PARA_BOOT_HOOK_EXT_BYTES[:33 * 4] == ITEM_PARA_BOOT_HOOK_BYTES[:33 * 4]
assert ITEM_PARA_BOOT_HOOK_EXT_BYTES[51 * 4:] == ITEM_PARA_BOOT_HOOK_BYTES[33 * 4:]
assert (
    ITEM_PARA_BOOT_HOOK_RAM + len(ITEM_PARA_BOOT_HOOK_EXT_BYTES)
    <= TRANSITION_GATE_WRAPPER_RAM
), hex(ITEM_PARA_BOOT_HOOK_RAM + len(ITEM_PARA_BOOT_HOOK_EXT_BYTES))

# --- Money-shop array capacity -----------------------------------------------
# The money shop's runtime [id, flag] array (0x80088828) holds AT MOST 68
# pairs — the next struct (the merit list_obj) starts at 0x800888B0. The
# lab probed the 68-row boundary end-to-end (renders, scrolls, purchases,
# zero spill). Planned worst case: 16 vanilla rows (item building,
# pstat(26)=4 + Unimon bonus) + 25 AP rows = 41.

SHOP_AP_MONEY_ARRAY_CAP: Final = 68
SHOP_AP_WORST_VANILLA_ROWS: Final = 16
assert SHOP_AP_WORST_VANILLA_ROWS + ITEM_SHOP_AP_ITEM_ID_COUNT <= SHOP_AP_MONEY_ARRAY_CAP

# --- Tiered price defaults (lab NOTES) ---------------------------------------
# Used by the patcher's ``tiered`` price mode. Recycle keeps its vanilla
# money prices (RECYCLE_SHOP_VANILLA_PRICES); merit keeps its vanilla
# merit prices (price options never touch merit).


def item_shop_tiered_price(index: int) -> int:
    """Tiered default price for item-shop slot index 0..24 (T1/T2/T3)."""

    assert 0 <= index < ITEM_SHOP_AP_ITEM_ID_COUNT
    if index < ITEM_SHOP_TIER_COUNTS[0]:
        return 500
    if index < ITEM_SHOP_TIER_COUNTS[0] + ITEM_SHOP_TIER_COUNTS[1]:
        return 1000
    return 2000


def secret_shop_tiered_price(index: int) -> int:
    """Tiered default price for secret-shop slot index 0..11 (per clerk)."""

    assert 0 <= index < SECRET_SHOP_AP_ITEM_ID_COUNT
    return 1000 * (index // 3 + 1) + 100 * (index % 3)


# --- Shopsanity trigger-allocation audit -------------------------------------
# Same shape as the region-gate audit above: derived from the live
# manifest constants so any future reallocation trips at module load.

SHOP_AP_TRIGGER_IDS: Final = ITEM_SHOP_TRIGGER_IDS + SECRET_SHOP_TRIGGER_IDS
assert len(SHOP_AP_TRIGGER_IDS) == len(set(SHOP_AP_TRIGGER_IDS)) == 37

for _trig in SHOP_AP_TRIGGER_IDS:
    # Only the two audited-free bands.
    assert 784 <= _trig <= 799 or 856 <= _trig <= 877, _trig
    # The >=800-is-pstat rule: pstat(0)..pstat(6) bytes = triggers
    # 800..855 are engine-owned. Nothing at or past byte 0x001BE042.
    assert not 800 <= _trig <= 855, _trig
    assert _trig < 936, _trig
    assert (
        AP_TRIGGER_ARRAY_BASE + _trig // 8 < RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE
    ), _trig
    # Outside the recruit intercept band and above the script ceiling.
    assert not 203 <= _trig <= 258, _trig
    assert _trig > 713, _trig
    # Disjoint from every shipped allocation (incl. region gates).
    assert _trig not in _REGION_GATE_TAKEN_TRIGGERS, _trig
    assert _trig not in _REGION_GATE_NEW_TRIGGERS, _trig
del _trig


# =============================================================================
# Card-trade value multiplier (QoL, option-gated data rewrite)
# =============================================================================
#
# ShogunGekomon's Merit Shop trades Digimon cards for Merit Points via a
# static per-card value table in the SLUS data segment. Lab-mapped and
# live-proven 2026-08-20 (``work/dw1_re/decomp/_scratch_merit_card_trade/
# CARD_TRADE_NOTES.md``): the value flows table -> gp-scratch
# (0x8013500C) -> ``merits += value`` with **no transform** and only a
# post-add cap at 9999 (``slti at, v0, 0x2710`` @ 0x8010BE54). A live
# whole-column poke to 777 produced a "777points" dialog and a 777-merit
# deposit end to end, so rewriting the value column is sufficient to
# scale card-trade earnings.
#
# Table geometry (byte-verified against the source .bin 2026-08-21):
#
# * Base: RAM ``0x8012FFDA`` = .bin flat ``0x14D72222`` (pinned through
#   :func:`_slus_ram_to_bin_offset` below).
# * 65 entries x 4 bytes: ``(value_i16 @ +0, cardRef_i16 @ +2)``. The
#   value is read ``lh`` with an ``index * 4`` addressing pattern; the
#   cardRef halfword is never touched by this patch.
# * Entry 0 is a zero-value placeholder row; entries 1..64 carry the 64
#   tradeable cards' values in the vanilla distribution
#   ``100 x5, 30 x20, 10 x25, 5 x10, 1 x4``.
# * The table ends at entry 64: the next two user bytes are ``00 00``
#   alignment padding, then a 4-byte-aligned pointer array begins at RAM
#   ``0x801300E0`` (first pointer 0x80134554) — a clean structural
#   terminator, so 65 is the whole table.
# * A Mode2/2352 sector boundary splits the table between entries 9 and
#   10 (38 user bytes remain in the base sector). Per-entry offsets are
#   therefore computed sector-aware; no 2-byte value halfword ever
#   straddles a boundary (audited at module load below).
#
# The patcher (:func:`worlds.digimon_world.rom._write_card_trade_multiplier_tokens`)
# multiplies each nonzero vanilla value by the ``card_trade_multiplier``
# option, clamped to :data:`CARD_TRADE_VALUE_CAP` (the merit counter's own
# in-game cap, so a higher table value could never show anyway). Zero
# rows are skipped — 0 x K = 0, no token needed.

CARD_TRADE_VALUE_TABLE_RAM: Final = 0x8012FFDA
CARD_TRADE_VALUE_TABLE_BIN_OFFSET: Final = 0x14D72222
assert CARD_TRADE_VALUE_TABLE_BIN_OFFSET == _slus_ram_to_bin_offset(
    CARD_TRADE_VALUE_TABLE_RAM,
), hex(_slus_ram_to_bin_offset(CARD_TRADE_VALUE_TABLE_RAM))

CARD_TRADE_ENTRY_STRIDE: Final = 4
CARD_TRADE_TABLE_ENTRIES: Final = 65
CARD_TRADE_VALUE_CAP: Final = 9999  # merit counter's own in-game cap

# The vanilla value column, extracted once from the canonical SLUS-01032
# dump (entry order = table order). Tests re-verify this against the
# source .bin on machines that have it (auto-skip elsewhere).
CARD_TRADE_VANILLA_VALUES: Final[tuple[int, ...]] = (
    (0,) + (100,) * 5 + (30,) * 20 + (10,) * 25 + (5,) * 10 + (1,) * 4
)
assert len(CARD_TRADE_VANILLA_VALUES) == CARD_TRADE_TABLE_ENTRIES
assert sum(CARD_TRADE_VANILLA_VALUES) == 1404  # 500 + 600 + 250 + 50 + 4


def card_trade_value_bin_offset(index: int) -> int:
    """Sector-aware .bin offset of table entry ``index``'s value halfword."""

    assert 0 <= index < CARD_TRADE_TABLE_ENTRIES, index
    return _slus_ram_to_bin_offset(
        CARD_TRADE_VALUE_TABLE_RAM + index * CARD_TRADE_ENTRY_STRIDE,
    )


# Boundary audit: the sector hop lands between entries 9 and 10 (flat
# delta 4 + 304 interleave bytes), and no value halfword straddles a
# user-data window edge.
assert card_trade_value_bin_offset(9) == CARD_TRADE_VALUE_TABLE_BIN_OFFSET + 36
assert card_trade_value_bin_offset(10) == CARD_TRADE_VALUE_TABLE_BIN_OFFSET + 40 + 304
for _i in range(CARD_TRADE_TABLE_ENTRIES):
    _off = card_trade_value_bin_offset(_i)
    assert 24 <= _off % 2352 <= 2072 - 2, (_i, hex(_off))
del _i, _off


# =============================================================================
# Piximon Training Manual location (opt-in) — Script 176 §82 giveItem neuter
# =============================================================================
#
# Piximon occasionally visits the File City item-shop building (screen
# 216, Script 176). The visit is rolled by the screen loader (Script 0
# §216): priority goes to a recruited-but-unintroduced staffer, else a
# 2-in-10 random Piximon visit — requires trigger 255 (Piximon
# recruited), loads his model, and sets the **transient** trigger 69
# (§51 ``unsetTrigger 69`` clears it again on every screen entry). See
# ``work/dw1_re/decomp/_scan_item_shop_versions/NOTES.md``.
#
# His dialog (Script 176 Section_82, gated on trigger 69) sells one
# Training Manual (item 33) for a flat 50,000 Bits, outside the shop
# stock engine. Flow (DW1Script.txt:27966..27995, byte-verified):
#
#     003646 if trigger(69) == true then 3660      <-- visit gate
#     004244 setSelection 4282 4544                <-- Buy / Don't buy
#     004282 if getMoney < 50000 then 4308         <-- "not enough bits" path
#     004298 reduceMoney 50000
#     004304 jumpTo 4372
#     004372 giveItem 33 1                         <-- THE single give site
#     004376 if trigger(0) == false then 4480      <-- give-failed check
#     004388..004478 [full-inventory path: "you have lots of stuff",
#                     addMoney 50000 refund, endSection]
#     004480 playSound 1280 + "I got a Training Manual!" textbox
#
# Unlike the Blue Flute cutscene there is NO retry giveItem — the
# failure branch refunds the 50,000 Bits instead. One give site total,
# confirmed by an exhaustive user-space scan of the source .bin for the
# ``28 00 21 01`` opcode: 8 hits, exactly one in script context (the
# archive-slot site below; the other 7 are unrelated code/data). The
# vending-pattern swap (``giveItem`` -> ``setTrigger 877``) keeps the
# payment, fires the AP location, and delivers no vanilla Manual; the
# stale-``trigger(0)`` follow-up check picks the success textbox in the
# normal case (same accepted semantics as the shipped Blue Flute patch).
#
# Trigger 877 was the audited spare of the shopsanity band (856..877,
# byte 0x001BE03A bit 5) — see the allocation comment in the shopsanity
# section and the audit asserts below.

PIXIMON_MANUAL_LOCATION_NAME: Final = "Piximon's Training Manual"
PIXIMON_MANUAL_TRIGGER_ID: Final = 877
PIXIMON_MANUAL_LOCATION_BIT: Final[tuple[int, int]] = (
    AP_TRIGGER_ARRAY_BASE + PIXIMON_MANUAL_TRIGGER_ID // 8,
    PIXIMON_MANUAL_TRIGGER_ID % 8,
)
assert PIXIMON_MANUAL_LOCATION_BIT == (0x001BE03A, 5), PIXIMON_MANUAL_LOCATION_BIT

# Client poll table (merged into ``client.LOCATION_RAM_BITS``). Polling
# is unconditional — with the option off the ROM keeps vanilla
# ``giveItem 33`` and trigger 877 is never set, and the server filters
# out ids that don't exist in the seed anyway.
PIXIMON_MANUAL_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    PIXIMON_MANUAL_LOCATION_NAME: PIXIMON_MANUAL_LOCATION_BIT,
}

PIXIMON_MANUAL_GIVEITEM_SCRIPT: Final = 176
PIXIMON_MANUAL_GIVEITEM_VM_OFFSET: Final = 4372
ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS: Final = (
    script_vm_to_bin_offset(
        PIXIMON_MANUAL_GIVEITEM_SCRIPT, PIXIMON_MANUAL_GIVEITEM_VM_OFFSET,
    ),
)
# Pin the derived offset to the byte-verified literal so an archive-slot
# regression trips loudly at module load.
assert ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS == (0x1406EAAC,), (
    tuple(hex(_o) for _o in ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS)
)

# Vanilla bytes at the site (``giveItem 33 1``) and the 4-byte
# replacement (``setTrigger 877``).
ROM_PIXIMON_MANUAL_GIVEITEM_VANILLA: Final = bytes((0x28, 0x00, 33, 0x01))
ROM_PIXIMON_MANUAL_NEUTER_VALUE: Final = encode_set_trigger(PIXIMON_MANUAL_TRIGGER_ID)
assert ROM_PIXIMON_MANUAL_NEUTER_VALUE == bytes((0x1C, 0x00, 0x6D, 0x03))
assert len(ROM_PIXIMON_MANUAL_NEUTER_VALUE) == len(ROM_PIXIMON_MANUAL_GIVEITEM_VANILLA)

# Containment + boundary audit: the write stays inside Script 176's
# archive slot and inside one Mode2/2352 user-data window.
assert (
    PIXIMON_MANUAL_GIVEITEM_VM_OFFSET + len(ROM_PIXIMON_MANUAL_NEUTER_VALUE)
    <= _SCRIPT_ARCHIVE_SLOT_SIZES[PIXIMON_MANUAL_GIVEITEM_SCRIPT]
)
assert 24 <= ROM_PIXIMON_MANUAL_GIVEITEM_OFFSETS[0] % 2352 <= 2072 - 4

# Trigger-allocation audit (same shape as the shopsanity/region-gate
# audits): trigger 877 must stay inside the audited-free band and
# disjoint from every shipped allocation.
assert 856 <= PIXIMON_MANUAL_TRIGGER_ID <= 877
assert not 800 <= PIXIMON_MANUAL_TRIGGER_ID <= 855
assert PIXIMON_MANUAL_TRIGGER_ID < 936
assert (
    AP_TRIGGER_ARRAY_BASE + PIXIMON_MANUAL_TRIGGER_ID // 8
    < RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE
)
assert not 203 <= PIXIMON_MANUAL_TRIGGER_ID <= 258
assert PIXIMON_MANUAL_TRIGGER_ID > 713
assert PIXIMON_MANUAL_TRIGGER_ID not in _REGION_GATE_TAKEN_TRIGGERS
assert PIXIMON_MANUAL_TRIGGER_ID not in _REGION_GATE_NEW_TRIGGERS
assert PIXIMON_MANUAL_TRIGGER_ID not in SHOP_AP_TRIGGER_IDS


# =============================================================================
# Coelamon recruit-cutscene remap (always-on) — restores the Coelamon location
# =============================================================================
#
# Coelamon's shore screen (Script ID 6, MAYO05 "Coela Point", screen 5)
# is a positional state machine over the bridge bit (185) and, in
# vanilla, Coelamon's recruit bit (249):
#
#     S254 000120 if trigger(185)==false OR trigger(249)==true then 200
#     S254 000202 if hour<15 OR hour>19 OR trigger(249)==true then 286
#     S51  000586 if trigger(185)==false OR trigger(249)==true then 1506
#          000602..001504  recruit cutscene -> setTrigger 249 @1496,
#                          addToPStat 1 2 @1500 (+2 PP), endSection
#          001506..001532  ferry guard: hour window OR 249 -> endSection
#          001534..003088  ferry cutscene -> setTrigger 96, warpTo 12 4
#
# History: Coelamon was dropped 2026-05-24 because the era's global
# setTrigger wrapper redirected the cutscene's ``setTrigger 249`` into
# the beaten range — bit 249 stayed clear, the guards never saw the
# recruit, and the cutscene re-fired on every zone touch (inescapable
# loop). The wrapper is retired, but bit 249 can no longer serve the
# shore machine at all: the client pins it every tick (see
# :data:`COELAMON_RECRUIT_BIT`), which would make the cutscene
# permanently unreachable instead.
#
# Fix (the shipped Old-Fishrod / vending pattern — remap BOTH the
# guard reads and the setTrigger to a fresh AP bit, leaving the
# vanilla bit to the AP side): rewrite all five trigger-249 references
# in Script 6 to trigger 779 (:data:`COELAMON_RECRUIT_LOCATION_TRIGGER_ID`).
# After the patch the shore runs on its own persistent "shore cutscene
# done" bit:
#
# * No bridge: Coelamon ferries the player across (hour 15..19), does
#   NOT set 779 — the ferry is not the location.
# * Bridge built, first visit: recruit cutscene plays once, sets 779
#   (the AP location signal) and grants +2 PP as in vanilla.
# * 779 set: shore quiet forever (no loop; save-block persistent).
# * The client pin of 249 and Progressive Item Shop T1's beaten-bit
#   delivery (769) cannot fire or block the location.
#
# All three behaviors + pin-immunity + the bridge-SHUFFLED composition
# with :data:`ROM_COELAMON_GATE_OFFSETS` were live-verified and
# disc-load-verified 2026-08-22 (three nets green; see
# ``work/dw1_re/decomp/_coelamon_recruit/NOTES.md``).
#
# The five id-byte sites (all ``F9 00`` -> ``0B 03``) plus the three
# dead residue twins (Script 6's slot tail vm 3092..4095 is a stale
# self-copy shifted +3092; disc-loaded with the final 2048-byte block,
# never executed — patched for hygiene). The setTrigger (vm 1498) and
# ferry-guard (vm 1520) sites sit past the stale copy's reach and are
# single-copy (full-.bin user-space census, 2026-08-22). Always
# emitted — the vanilla flow is incompatible with the client pin
# regardless of other options.

COELAMON_RECRUIT_LOCATION_TRIGGER_ID: Final = 779
COELAMON_RECRUIT_LOCATION_BIT: Final[tuple[int, int]] = (
    AP_TRIGGER_ARRAY_BASE + COELAMON_RECRUIT_LOCATION_TRIGGER_ID // 8,
    COELAMON_RECRUIT_LOCATION_TRIGGER_ID % 8,
)
assert COELAMON_RECRUIT_LOCATION_BIT == (0x001BE02E, 3), COELAMON_RECRUIT_LOCATION_BIT

# Client poll table (merged into ``client.LOCATION_RAM_BITS``). The key
# must equal the AP location name — the recruit location is named plain
# "Coelamon" like every other recruit location. The bit lives OUTSIDE
# the arena-enforcer recruit-block window (0x001BDFE6..0x001BDFED), so
# the enforcer's 0xFF fill can never false-fire it.
COELAMON_RECRUIT_LOCATION_RAM_BITS: Final[dict[str, tuple[int, int]]] = {
    "Coelamon": COELAMON_RECRUIT_LOCATION_BIT,
}

_COELAMON_REMAP_SCRIPT: Final = 6
# vm offsets of the trigger-id bytes: S254 gate cond2, S254 hour-gate
# cond3, S51 gate cond2, S51 setTrigger operand, S51 ferry-guard cond3,
# then the dead residue twins of the three low-vm sites (+3092).
_COELAMON_REMAP_VM_OFFSETS: Final = (128, 214, 594, 1498, 1520, 3220, 3306, 3686)
ROM_COELAMON_CUTSCENE_REMAP_OFFSETS: Final = tuple(
    script_vm_to_bin_offset(_COELAMON_REMAP_SCRIPT, _vm)
    for _vm in _COELAMON_REMAP_VM_OFFSETS
)
# Pin the derived offsets to the byte-verified literals so an
# archive-slot regression trips loudly at module load.
assert ROM_COELAMON_CUTSCENE_REMAP_OFFSETS == (
    0x13FE0398, 0x13FE03EE, 0x13FE056A, 0x13FE08F2, 0x13FE0908,
    0x13FE10DC, 0x13FE1132, 0x13FE12AE,
), tuple(hex(_o) for _o in ROM_COELAMON_CUTSCENE_REMAP_OFFSETS)

# Vanilla bytes at every site (trigger id 249 LE) and the 2-byte
# replacement (trigger id 779 LE).
ROM_COELAMON_CUTSCENE_REMAP_VANILLA: Final = bytes((0xF9, 0x00))
ROM_COELAMON_CUTSCENE_REMAP_VALUE: Final = bytes((
    COELAMON_RECRUIT_LOCATION_TRIGGER_ID & 0xFF,
    (COELAMON_RECRUIT_LOCATION_TRIGGER_ID >> 8) & 0xFF,
))
assert ROM_COELAMON_CUTSCENE_REMAP_VALUE == bytes((0x0B, 0x03))

# The take-across gate patch (bridge-SHUFFLED mode) targets the same
# S51 gate statement — branch-target bytes at vm 598 / residue twin
# 3690. Derivation asserts for the repaired literals (see the offset
# repair note at :data:`ROM_COELAMON_GATE_OFFSETS`).
assert ROM_COELAMON_GATE_OFFSETS == (
    script_vm_to_bin_offset(_COELAMON_REMAP_SCRIPT, 598),
    script_vm_to_bin_offset(_COELAMON_REMAP_SCRIPT, 3690),
), tuple(hex(_o) for _o in ROM_COELAMON_GATE_OFFSETS)
# Disjointness: the two families write different bytes of the slot.
assert not set(ROM_COELAMON_GATE_OFFSETS) & set(ROM_COELAMON_CUTSCENE_REMAP_OFFSETS)

# Containment + boundary audit: every write stays inside Script 6's
# archive slot and inside one Mode2/2352 user-data window.
for _vm in (*_COELAMON_REMAP_VM_OFFSETS, 598, 3690):
    assert _vm + 2 <= _SCRIPT_ARCHIVE_SLOT_SIZES[_COELAMON_REMAP_SCRIPT], _vm
    _off = script_vm_to_bin_offset(_COELAMON_REMAP_SCRIPT, _vm)
    assert 24 <= _off % 2352 <= 2072 - 2, (_vm, hex(_off))
del _vm, _off

# Trigger-allocation audit (same shape as the shopsanity / Piximon
# audits): 779 sits in the audited-clean gap right above the beaten
# remap band (203..258 + 520 -> 723..778) and below the shopsanity
# band A (784..799); byte 0x1BE02E is inside the statically-verified
# vanilla-unused span 0x1BE027..0x1BE02E.
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID > 713          # script ceiling
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID > 716          # chest-bit ceiling
assert not 203 <= COELAMON_RECRUIT_LOCATION_TRIGGER_ID <= 258
assert not 723 <= COELAMON_RECRUIT_LOCATION_TRIGGER_ID <= 778
assert not 784 <= COELAMON_RECRUIT_LOCATION_TRIGGER_ID <= 799
assert not 800 <= COELAMON_RECRUIT_LOCATION_TRIGGER_ID <= 855
assert not 856 <= COELAMON_RECRUIT_LOCATION_TRIGGER_ID <= 935
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID < 936
assert (
    AP_TRIGGER_ARRAY_BASE + COELAMON_RECRUIT_LOCATION_TRIGGER_ID // 8
    < RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE
)
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID != PIXIMON_MANUAL_TRIGGER_ID
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID not in _REGION_GATE_TAKEN_TRIGGERS
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID not in _REGION_GATE_NEW_TRIGGERS
assert COELAMON_RECRUIT_LOCATION_TRIGGER_ID not in SHOP_AP_TRIGGER_IDS


# =============================================================================
# Field Digimon records (.MAP) and the MAPHEAD species loader
# =============================================================================
#
# Verified 2026-08-28 (dw_decomp ``src/main/tamer.c:loadMapEntities``,
# Ghidra exports of ``loadMapDigimon`` 0x800B5D0C / ``scriptSetDigimon``
# 0x800B6118 / ``loadMMD`` 0x800A1F68 / ``handleBattleStart`` 0x800E847C,
# and a lab run through the three PATCH_PROCESS nets incl. two battles):
#
# * Every Digimon a screen can host -- wild fodder and story bosses alike
#   -- is a record in the screen's ``.MAP`` file, right after the
#   0x78-byte MAP_WARPS block: ``s16 count`` then per record 0x22 s16 of
#   fields, 8 s16 of AI data and ``N x 3`` s16 waypoints (``N`` = s16
#   index 0x21).  ``loadMapDigimon`` copies each record into
#   ``MAP_DIGIMON_TABLE[slot]`` (type, position, AI) and
#   ``NPC_ENTITIES[slot]`` (stats, moveset, bits) when the screen loads;
#   ``BTL_initializeCombat`` then takes the fight's stats from
#   ``NPC_ENTITIES`` verbatim (``INITIAL_COMBAT_STATS`` row ``i``).
#   Rewriting a record's stat / move words on disc therefore changes
#   that fight and nothing else -- no code involved.
# * A record's species is its ``type`` (index 0) **and** the operands of
#   the ``loadDigimon XX`` (``46 XX``) / ``setDigimon XX slot autotalk``
#   (``47 XX ss aa``) opcodes in the screen's section of MAPHEAD.SCN:
#   ``scriptSetDigimon`` only places the entity when the operand equals
#   ``MAP_DIGIMON_TABLE[slot].typeId``.  MAPHEAD.SCN is a separate disc
#   file, read ONCE at boot into :data:`RAM_MAPHEAD_DATA`
#   (``initializeScripts``; ``getScript(0)`` returns that buffer, never
#   the script archive's dead slot-0 copy) -- so a savestate keeps the
#   boot copy and lab tests of a MAPHEAD patch need a cold boot or a
#   RAM poke (``dw1_warp_state.py --poke``).
# * Models: ``loadMMD`` malloc3's the whole ``\CHDAT\MMD{id/30}\{name}.MMD``
#   file (rounded up to 2 KB) and keeps it for the screen's lifetime;
#   at most :data:`NPC_MODEL_SLOTS` distinct NPC species can be loaded
#   at once.  A substitute species is safe when its model needs no
#   more heap than the original's (the per-screen footprint then never
#   exceeds vanilla) -- see ``data/enemy_records.py`` ``SPECIES[].heap``.
# * Move bytes are animation ids ``0x2E + k`` selecting slot ``k`` of
#   ``DIGIMON_DATA[type].moves[16]`` (``entityGetTechFromAnim``); a
#   substitute's moveset must be re-picked from its own list.

RAM_MAP_DIGIMON_TABLE: Final = 0x0013CB50        # MapDigimonEntity[8]; typeId s16 @+0, pos s16 x/y/z @+0xA8
RAM_MAP_DIGIMON_TABLE_STRIDE: Final = 0xC4
RAM_NPC_ENTITIES: Final = 0x00155828             # NPCEntity[8]
RAM_NPC_ENTITY_STRIDE: Final = 0x68
# NPCEntity.stats: BaseStats @+0x38 = off, def, spd, brn (s16), movesPrio[4],
# moves[4], hp, mp; CurrentStats @+0x4C = curHP, curMP; chargeMode @+0x56;
# bits s16 @+0x60; scriptId u8 @+0x65.
RAM_NPC_ENTITY_STATS_OFFSET: Final = 0x38
RAM_NPC_ENTITY_BITS_OFFSET: Final = 0x60
RAM_LOADED_DIGIMON_MODELS: Final = 0x001BE7EC    # i32[8], -1 = free (scriptLoadModel / scriptUnloadModel)
RAM_INITIAL_COMBAT_STATS: Final = 0x0013D610     # s16[4][6] hp, mp, off, def, spd, brn; row 0 = partner
RAM_ENEMY_COUNT: Final = 0x00134D6C              # s16, set by loadBattleData
RAM_GAME_STATE: Final = 0x00134F0A               # i8: 0 field, non-zero from startBattle until it returns
RAM_ENTITY_TABLE: Final = 0x0012F344             # Entity *[10]: 0 tamer, 1 partner, 2.. = NPC slot + 2
RAM_DIGIMON_DATA: Final = 0x0012CEB4             # DigimonPara[180] x 52 B; moves[16] @+35
RAM_MAPHEAD_DATA: Final = 0x001B1D30             # boot-resident MAPHEAD.SCN (0x61A8 B); file offsets 1:1
NPC_MODEL_SLOTS: Final = 5

MAPHEAD_SCN_LBA: Final = 142982                  # /SCN/MAPHEAD.SCN
MAPHEAD_SCN_SIZE: Final = 24686
MAPHEAD_OP_LOAD_DIGIMON: Final = 0x46            # 46 XX
MAPHEAD_OP_SET_DIGIMON: Final = 0x47             # 47 XX slot autotalk

# ``.MAP`` Digimon record field indices (s16 units from the record start).
FIELD_RECORD_TYPE: Final = 0x00
FIELD_RECORD_HP: Final = 0x0B
FIELD_RECORD_MP: Final = 0x0C
FIELD_RECORD_CUR_HP: Final = 0x0D
FIELD_RECORD_CUR_MP: Final = 0x0E
FIELD_RECORD_OFF: Final = 0x0F
FIELD_RECORD_DEF: Final = 0x10
FIELD_RECORD_SPD: Final = 0x11
FIELD_RECORD_BRN: Final = 0x12
FIELD_RECORD_BITS: Final = 0x13
FIELD_RECORD_CHARGE: Final = 0x14
FIELD_RECORD_MOVES: Final = 0x16                 # 4 s16: anim ids 0x2E + k, 0xFF = none
FIELD_RECORD_PRIO: Final = 0x1A                  # 4 s16: AI weights for the four moves
FIELD_RECORD_WAYPOINTS: Final = 0x21
FIELD_RECORD_HEAD_WORDS: Final = 0x22
FIELD_RECORD_TAIL_WORDS: Final = 8
FIELD_RECORD_STAT_COUNT: Final = 9               # hp .. bits, contiguous from FIELD_RECORD_HP
FIELD_RECORD_FORMAT: Final = "<h"


def field_record_bin_offset(record_bin_offset: int, word_index: int) -> int:
    """Flat .bin offset of s16 field ``word_index`` of the record whose first byte is at
    ``record_bin_offset`` (sector-aware: a record may straddle a 2048-B user-data boundary)."""

    return _flat_to_user_data(record_bin_offset, word_index * 2)


def maphead_bin_offset(file_offset: int) -> int:
    """Flat .bin offset of byte ``file_offset`` of MAPHEAD.SCN (== its offset in
    :data:`RAM_MAPHEAD_DATA`, and the offset the script disassembly prints)."""

    assert 0 <= file_offset < MAPHEAD_SCN_SIZE, file_offset
    return (MAPHEAD_SCN_LBA + file_offset // USER_DATA_BYTES) * SECTOR_SIZE_BYTES \
        + SECTOR_HEADER_BYTES + file_offset % USER_DATA_BYTES


# Self-check against the standalone randomizer's documented Gabumon
# enemy-stat anchor (``data.py: gabuPatchWrites``, MIST06.MAP): our
# record for that Gabumon starts at 0x0A7EEA76 and its HP word must land
# on the randomizer's 0x0A7EEA8C.
assert field_record_bin_offset(0x0A7EEA76, FIELD_RECORD_HP) == 0x0A7EEA8C
assert maphead_bin_offset(1158) == (MAPHEAD_SCN_LBA + 1158 // 2048) * 2352 + 24 + 1158 % 2048


# =============================================================================
# Green Gym training bonus follows AP-delivered recruits (TRN_REL.BIN)
# =============================================================================
#
# ``TRN_calculateTrainingMultiplier`` (dw_decomp ``src/trn/trn_reward.c:637``
# and ``:643``, byte-matching) grants the x6/5 training bonus when
# ``isTriggerSet(219)`` (Kabuterimon's vanilla recruit bit; HP / Defense /
# Speed machines) or ``isTriggerSet(251)`` (Kuwagamon's; MP / Offense /
# Brains machines) is set. Under Plan A revised an AP-delivered recruit
# sets the mirror bit 720 + X instead, so these two reads are redirected
# to 739 / 771 like every city-visibility reader. Both sites are
# ``addiu $a0, $zero, imm`` in the delay slot of ``jal isTriggerSet``
# (0x0C04190F); the new immediates fit the signed 16-bit field.
#
# Lab-validated 2026-08-28 through the three PATCH_PROCESS nets (7 real
# training sessions over ``training_gym.state`` + an 84/84 in-situ sweep
# of all six modes, then two sessions on the overlay loaded from the
# patched disc). Intended behaviour change: the vanilla bit alone no
# longer grants the bonus. TRN_REL.BIN is loaded by the gym script
# (``MAIN_func_800D9360`` -> ``loadDynamicLibrary(10)``), not by the map
# loader, so the patch is a plain overlay-file write. Notes:
# ``work/dw1_re/decomp/trn_gym_bonus/NOTES.md``.

_OVERLAY_TRN_LBA: Final = 148248                 # /TRN_REL.BIN, 27604 B
_TRN_GYM_BONUS_SITES: Final = (                  # (file_off, vanilla trigger, redirected trigger)
    (0x18F8, 219, 739),  # Kabuterimon: HP / Defense / Speed machines
    (0x1944, 251, 771),  # Kuwagamon: MP / Offense / Brains machines
)
TRN_GYM_BONUS_WORD_PATCHES: Final[tuple[tuple[int, int, int], ...]] = tuple(
    (_overlay_file_to_bin(_OVERLAY_TRN_LBA, off), _mips_addiu(4, 0, new), _mips_addiu(4, 0, old))
    for off, old, new in _TRN_GYM_BONUS_SITES
)  # ((bin_offset, patched_word, vanilla_word), ...)
assert TRN_GYM_BONUS_WORD_PATCHES == (
    (0x14C88920, 0x240402E3, 0x240400DB),
    (0x14C8896C, 0x24040303, 0x240400FB),
), TRN_GYM_BONUS_WORD_PATCHES
for _off, _old, _new in _TRN_GYM_BONUS_SITES:
    assert _new == _old + 520, (_old, _new)   # BEATEN mirror band: trigger 200+X -> 720+X
    assert _off % 4 == 0 and (_overlay_file_to_bin(_OVERLAY_TRN_LBA, _off) - 24) % 2352 + 4 <= 2048
del _off, _old, _new


# =============================================================================
# Technique data, element matrix and species drops (static SLUS tables)
# =============================================================================
#
# Three tables the standalone randomizer has rewritten for years, all inside
# the SLUS image (so a patch is a plain data write, no code hooks):
#
# * ``MOVE_DATA`` (dw_decomp ``include/dw/move.h``): 122 x 16 B ``Move``
#   records -- ``i32 distance, i16 power, u8 mpCost, iframes, range,
#   special, status, accuracy, statusChance, 3 unknown``. The battle
#   charges ``mpCost * 3`` (``battle_main.c:2575``), rolls
#   ``random(100) < accuracy`` variants (``:1997``) and applies ``status``
#   when ``random(100) < statusChance`` (``:2039``). The first 121 are named
#   (MOVE_NAMES); id 121 is a nameless internal entry, never rewritten.
# * ``MAIN_D_80125F70``: the 7 x 7 element affinity matrix
#   ``[move.special][species.special[0]]``, values 2 / 5 / 10 / 15 / 20 that
#   ``BTL_calculateElementBonus`` (and its STD / VS twins) map to 1 / 3 / 5 /
#   7 / 10. Read by the enemy AI weights and the partner's battle-learn filter.
# * ``DIGIMON_DATA[type].dropItem / dropChance`` (bytes 33 / 34 of the 52-B
#   ``DigimonPara``): ``battleStatsGainsAndDrops`` rolls
#   ``random(100) < dropChance`` per beaten enemy (``battle_ui.c:178``).
#
# The offsets derive from the SLUS load base through
# :func:`_slus_ram_to_bin_offset` and are asserted against the standalone's
# independently measured constants (``data.py``: ``techDataBlockOffset``,
# ``typeEffectivenessOffset``, ``digimonDataBlockOffset``).

RAM_MOVE_DATA: Final = 0x0012623C
MOVE_DATA_RECORD_SIZE: Final = 16
MOVE_DATA_COUNT: Final = 122
MOVE_DATA_FORMAT: Final = "<ihBBBBBBBBBB"
MOVE_DATA_POWER_OFFSET: Final = 4          # i16
MOVE_DATA_MP_COST_OFFSET: Final = 6        # u8, charged x3
MOVE_DATA_STATUS_OFFSET: Final = 10        # u8: 0 none, 1 poison, 2 confusion, 3 stun, 4 flat
MOVE_DATA_ACCURACY_OFFSET: Final = 11      # u8
MOVE_DATA_STATUS_CHANCE_OFFSET: Final = 12  # u8, percent
#: The contiguous span a technique rewrite touches: power .. statusChance (iframes, range and
#: special in between are copied from vanilla).
MOVE_DATA_PATCH_SPAN: Final = (MOVE_DATA_POWER_OFFSET, MOVE_DATA_STATUS_CHANCE_OFFSET + 1)
ROM_MOVE_DATA_OFFSET: Final = _slus_ram_to_bin_offset(0x80000000 | RAM_MOVE_DATA)
assert ROM_MOVE_DATA_OFFSET == ROM_TECHNIQUE_DATA.offset == 0x14D66DF4, hex(ROM_MOVE_DATA_OFFSET)
assert struct.calcsize(MOVE_DATA_FORMAT) == MOVE_DATA_RECORD_SIZE

RAM_ELEMENT_MATRIX: Final = 0x00125F70
ELEMENT_MATRIX_DIM: Final = 7
ELEMENT_MATRIX_VALUES: Final = (2, 5, 10, 15, 20)
ROM_ELEMENT_MATRIX_OFFSET: Final = _slus_ram_to_bin_offset(0x80000000 | RAM_ELEMENT_MATRIX)
assert ROM_ELEMENT_MATRIX_OFFSET == 0x14D669F8, hex(ROM_ELEMENT_MATRIX_OFFSET)

DIGIMON_DATA_RECORD_SIZE: Final = 52
DIGIMON_DATA_COUNT: Final = 180
DIGIMON_DATA_DROP_ITEM_OFFSET: Final = 33   # u8 ITEM_PARA id
DIGIMON_DATA_DROP_CHANCE_OFFSET: Final = 34  # u8 percent
ROM_DIGIMON_DATA_OFFSET: Final = _slus_ram_to_bin_offset(0x80000000 | RAM_DIGIMON_DATA)
assert ROM_DIGIMON_DATA_OFFSET == ROM_DIGIMON_DATA.offset == 0x14D6E9DC, hex(ROM_DIGIMON_DATA_OFFSET)
assert struct.calcsize(ROM_DIGIMON_DATA.record_format) == DIGIMON_DATA_RECORD_SIZE


def move_data_bin_offset(tech_id: int, field_offset: int = 0) -> int:
    """Sector-aware .bin offset of byte ``field_offset`` of ``MOVE_DATA[tech_id]``."""

    assert 0 <= tech_id < MOVE_DATA_COUNT and 0 <= field_offset < MOVE_DATA_RECORD_SIZE, (tech_id, field_offset)
    return _flat_to_user_data(ROM_MOVE_DATA_OFFSET, tech_id * MOVE_DATA_RECORD_SIZE + field_offset)


def element_matrix_bin_offset(row: int, col: int) -> int:
    """Sector-aware .bin offset of ``MAIN_D_80125F70[row][col]``."""

    assert 0 <= row < ELEMENT_MATRIX_DIM and 0 <= col < ELEMENT_MATRIX_DIM, (row, col)
    return _flat_to_user_data(ROM_ELEMENT_MATRIX_OFFSET, row * ELEMENT_MATRIX_DIM + col)


def digimon_data_bin_offset(species_id: int, field_offset: int = 0) -> int:
    """Sector-aware .bin offset of byte ``field_offset`` of ``DIGIMON_DATA[species_id]``."""

    assert 0 <= species_id < DIGIMON_DATA_COUNT and 0 <= field_offset < DIGIMON_DATA_RECORD_SIZE, (
        species_id, field_offset)
    return _flat_to_user_data(ROM_DIGIMON_DATA_OFFSET, species_id * DIGIMON_DATA_RECORD_SIZE + field_offset)


def iter_user_data_chunks(base_bin_offset: int, table_offset: int, data: bytes):
    """Yield ``(flat_bin_offset, chunk)`` pairs that write ``data`` at user-data byte
    ``table_offset`` of the block at ``base_bin_offset`` without crossing a Mode2/2352
    user-data boundary -- the shape a WRITE token needs."""

    pos = 0
    while pos < len(data):
        flat = _flat_to_user_data(base_bin_offset, table_offset + pos)
        sector_user_end = (flat // SECTOR_SIZE_BYTES) * SECTOR_SIZE_BYTES + SECTOR_SIZE_BYTES - SECTOR_EDC_ECC_BYTES
        chunk = min(sector_user_end - flat, len(data) - pos)
        yield flat, data[pos:pos + chunk]
        pos += chunk


# The standalone's per-block sector exclusions are exactly the records these
# helpers split: the technique block hops one boundary (inside id 0x5C's
# record) and the Digimon block five.
assert move_data_bin_offset(0x5C, 0) < 0x14D673B8 < move_data_bin_offset(0x5C, 15), hex(move_data_bin_offset(0x5C))
assert any(
    digimon_data_bin_offset(i, 0) < 0x14D6EB28 < digimon_data_bin_offset(i, 51) for i in range(DIGIMON_DATA_COUNT)
)


# =============================================================================
# NPC gifts (Tokomon items, Bug / Seadramon technique teaches) and the
# standalone randomizer's remaining QoL patches
# =============================================================================
#
# All sites below are the standalone's (``data.py``), re-read from the vanilla
# disc on 2026-08-29; the vanilla bytes recorded here are what the disc holds
# and what the disc-gated test in ``test/test_gifts.py`` re-checks.

# ----- Tokomon's six ``giveItem`` opcodes (``28 00 item count``) -------------
TOKOMON_GIFT_OPCODE: Final = 0x28
TOKOMON_GIFT_VALUE_OFFSET: Final = 2                 # item byte, then count byte
TOKOMON_GIFT_VANILLA: Final[tuple[tuple[int, int], ...]] = (
    (0, 3),    # sm.recovery x3
    (38, 3),   # Meat x3
    (4, 3),    # sm.rec.floppy x3  (item 4)
    (11, 1),   # item 11 x1
    (13, 2),   # item 13 x2
    (14, 1),   # item 14 x1
)
assert len(TOKOMON_GIFT_VANILLA) == len(ROM_TOKOMON_ITEM_OFFSETS)

# ----- Bug (Beetle Land) and Seadramon technique teaches --------------------
# ``learnMove tech`` (``2D tech``) at ROM_LEARN_MOVE_OFFSETS, guarded by a
# ``22 00 tech 00`` "already known?" check whose operand sits at
# ROM_CHECK_MOVE_OFFSETS. Both bytes carry the technique id.
TECH_GIFT_LEARN_OPCODE: Final = 0x2D
TECH_GIFT_VANILLA: Final = (33, 21, 18, 16)          # Bug, Seadramon 1 / 2 / 3
assert len(TECH_GIFT_VANILLA) == len(ROM_LEARN_MOVE_OFFSETS) == len(ROM_CHECK_MOVE_OFFSETS)

# ----- Quest items droppable (ITEM_PARA ``dropable`` byte) ------------------
ROM_ITEM_DROPABLE_BYTE_OFFSET: Final = 29             # ItemPara +0x1D
ROM_QUEST_ITEMS_NOT_DROPABLE: Final = (115, 116, 117, 118, 119, 120, 123, 124)

# ----- Technique learn chances --------------------------------------------
# ``MOVE_LEARN_CHANCES[58][3]`` (SLUS, ``ROM_TECH_LEARN_BATTLE``) and the
# brain-training table (TRN_REL.BIN, ``ROM_TECH_LEARN_BRAIN``: 8 tiers x 3
# specialty matches), both as the disc holds them.
ROM_TECH_LEARN_BATTLE_VANILLA: Final = bytes.fromhex(
    "19100b110a051e160f140c07160e091c130d0f08000e06000d0900160e0a20130f120d082415111a100d0f0b070c0800"
    "110a050f0800140c071e0f08140a05160e090e06001e160f281e16100d00231b121c150d140e0a0f0c0019110b20180f"
    "1a130e0c0800170f0c18100d120c091c16101b140f0e0a00120800130908160f0a1a130e18110c140b08150d09100700"
    "18110c180e09170d080f0a050b0800150c07140b0619100a09070019100a"
)
ROM_TECH_LEARN_BRAIN_VANILLA: Final = bytes.fromhex("000f0a190d08160b071409051208020f07000c06000a0500")
assert len(ROM_TECH_LEARN_BATTLE_VANILLA) == 58 * 3 and len(ROM_TECH_LEARN_BRAIN_VANILLA) == 8 * 3
BRAIN_TIER_ONE_LEARN_CHANCE: Final = 30               # standalone ``learnTierOne``: row 0, byte 0 (vanilla 0)
LEARN_CHANCE_MULTIPLIER: Final = 2                    # standalone ``upLearnChance`` ...
BRAIN_LEARN_ZERO_REPLACEMENT: Final = 5               # ... and its floor for brain cells that were 0
assert max(ROM_TECH_LEARN_BATTLE_VANILLA) * LEARN_CHANCE_MULTIPLIER <= 0xFF
assert (ROM_TECH_LEARN_BRAIN.offset - 24) % 2352 + len(ROM_TECH_LEARN_BRAIN_VANILLA) <= 2048

# ----- Unrigged bonus-try slots (TRN_REL.BIN / TRN_REL2.BIN) ----------------
# ``(bin offset, patched word, vanilla word)``: one instruction per training
# slots function short-circuits the rigging logic (standalone ``slots``).
ROM_UNRIG_SLOTS_WORD_PATCHES: Final[tuple[tuple[int, int, int], ...]] = (
    (ROM_UNRIG_SLOTS_OFFSET, 0x08023A1E, 0x108100BA),
    (ROM_UNRIG_SLOTS_2_OFFSET, 0x08023494, 0x108100BA),
)

# ----- Learn a move and a command in one brain session (TRN_REL.BIN) --------
ROM_LEARN_MOVE_AND_COMMAND_WORDS: Final = (0x10000065, 0x00001021)
ROM_LEARN_MOVE_AND_COMMAND_VANILLA_WORDS: Final = (0x00001021, 0x2A410064)

# ----- DV chip descriptions (28-byte NUL-padded strings) --------------------
ROM_DV_CHIP_TEXT_LENGTH: Final = 28
ROM_DV_CHIP_TEXT_PATCHES: Final[tuple[tuple[int, bytes, bytes], ...]] = (  # (offset, patched, vanilla)
    (ROM_DV_CHIP_A_OFFSET, b"Boosts Off+Brains by 100", b"Boost Off. Pwr+Brains +100"),
    (ROM_DV_CHIP_D_OFFSET, b"Boosts Def+Speed by 100", b"Boost Def. Pwr+Speed +100"),
    (ROM_DV_CHIP_E_OFFSET, b"Boosts HP+MP by 1000", b"Boost Off. Pwr+Speed +1000"),
)
for _off, _new, _old in ROM_DV_CHIP_TEXT_PATCHES:
    assert len(_new) <= 26 and len(_old) <= 26 and (_off - 24) % 2352 + ROM_DV_CHIP_TEXT_LENGTH <= 2048, hex(_off)
for _off, _new, _old in ROM_UNRIG_SLOTS_WORD_PATCHES:
    assert _off % 4 == 0 and (_off - 24) % 2352 + 4 <= 2048, hex(_off)
assert (ROM_LEARN_MOVE_AND_COMMAND_OFFSET - 24) % 2352 + 8 <= 2048
for _off in ROM_TOKOMON_ITEM_OFFSETS:
    assert (_off - 24) % 2352 + 4 <= 2048, hex(_off)
for _off in ROM_LEARN_MOVE_OFFSETS:
    assert (_off - 24) % 2352 + 2 <= 2048, hex(_off)
del _off, _new, _old
