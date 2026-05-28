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
# AP items delivered by the server land in the **bank**, not the inventory
# (see ``RAM_ITEM_BANK_BASE`` above), so a foreign-world ``Digiseabass``
# delivery cannot cause a false fire. The only real false-positive path is
# opening the Dragon Eye Lake chest while standing on screen 6 or 8 — small
# enough to accept per user direction.
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
# Birdramon-Messenger reads a 6-entry destination table (`<u16 trigger,
# u32 price, u16 label_id>`) embedded in the binary at .bin offsets
# 0x14B8B698 and 0x14D725CE (two identical copies). Each destination
# only appears in his menu when its trigger bit is set in the trigger
# array. Vanilla mapping: G Canyon Top=trig 221 (Birdramon recruit),
# Gear Savanna=190, Ancient Dino=188, Freezeland=351, Misty Trees=147,
# Beetle Land=210.
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


def tech_mastery_bit(slot: int) -> tuple[int, int]:
    """Return ``(byte_address, bit_index)`` for technique mastery ``slot``.

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
# Branch target 1506 is the entry to case 1 ("I'll take you across the
# water"), which would let the player reach Tropical Jungle without the
# AP-controlled "Tropical Jungle Bridge" item. To close the bypass we
# rewrite *only the branch target* — 1506 -> 1532 — so the same gate
# now jumps to ``endSection`` (Coelamon does nothing) when the bridge
# bit is unset. Once AP delivers the bridge item, the client OR-pins
# trigger 185, the gate falls through, and case 2 ("Coelamon joins the
# city") fires as in vanilla.
#
# Two BIN copies of the script; both target bytes patched. Patch is
# emitted only when ``options.bridge_unlock == shuffled``.
# Vanilla mode (and always_open mode, where 185 is pinned from the
# start anyway) keep the unpatched 1506 branch target.

ROM_COELAMON_GATE_OFFSETS: Final = (
    0x13FE0572,  # Copy 1: 0x13FE0566 + 12 (target byte position in if-stmt)
    0x13FE12B6,  # Copy 2: 0x13FE12AA + 12
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
# receives Mansion Key only via AP delivery (bank slot 119, routed by
# :func:`_make_bank_deliverer`). Both giveItem sites are rewritten
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
# 130 bytes); the disassembler's offset numbering for this script's
# textboxes does not map 1:1 to .bin byte offsets. We trust the .bin
# scan and patch both sites directly.

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
            lui   $t1, 0x8012
            addiu $t1, $t1, 0x69DC ; t1 = ITEM_PARA base
            addu  $t2, $t2, $t1    ; t2 = ITEM_PARA + item_id*32 (dest)
            lui   $t0, 0x8012
            addiu $t0, $t0, 0x781C ; t0 = AP_SHOP_BOUGHT_SENTINEL_RAM (source)
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
    # MIPS lui/addiu encoding needs the CPU-visible kuseg address; the
    # bare RAM_ITEM_PARA / AP_SHOP_BOUGHT_SENTINEL_RAM constants are
    # for client-side bizhawk.read calls (which use bare offsets).
    ITEM_PARA_BASE = 0x80000000 | RAM_ITEM_PARA
    SENTINEL_RAM = 0x80000000 | AP_SHOP_BOUGHT_SENTINEL_RAM

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
    # half needs sign-extension (e.g. relocated ITEM_PARA at
    # 0x8009DBC8) or not (e.g. vanilla 0x801269DC).
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

# --- ITEM.TIM icon blanking ------------------------------------------------
#
# ITEM.TIM is a separate file in the disc filesystem
# (``DIGIMON/ETCDAT/ITEM.TIM``). Its data starts at LBA 7470 in the
# .bin (= ``LBA * 2352 + 24`` = bin offset 0x010C16B8). The TIM
# header is 8 bytes; the CLUT block is 780 bytes (24 CLUTs × 16
# colors × 2 bytes + 12-byte block header); the pixel block header is
# 12 bytes. So pixel data starts at TIM file offset 800 (= 0x320).
#
# Pixel data is 4bpp (2 pixels per byte), arranged as a 256x128
# texture (16 cols × 8 rows of 16x16 icons). Each scanline is
# 256 / 2 = 128 bytes. Item N's icon occupies the 16x16 block at
# pixel coords (col*16, row*16) where col = N%16, row = N/16.
#
# For each of the 16 rows of the icon, the 8 bytes (= 16 px wide × 4bpp)
# live at file offset:
#   PIXEL_DATA_OFFSET + (row*16 + r) * 128 + col * 8
# for r in 0..15. We sector-translate each row offset to a .bin offset
# (file offsets cross sector boundaries every 2048 bytes of user data).

ITEM_TIM_LBA: Final = 7470
ITEM_TIM_PIXEL_DATA_FILE_OFFSET: Final = 800

AP_ITEM_ICON_INDEX: Final = 83
AP_ITEM_ICON_ROW_BYTES: Final = bytes(8)  # 16 transparent pixels per icon row


def _ap_item_icon_blank_offsets() -> tuple[int, ...]:
    """Per-row .bin offsets for item 117's 16 icon rows (16x16 4bpp).

    Sector-aware: each row's 8-byte chunk lives at a different sector
    when the surrounding scanline crosses a 2048-byte user-data
    boundary.
    """

    col = AP_ITEM_ICON_INDEX % 16
    row = AP_ITEM_ICON_INDEX // 16
    out: list[int] = []
    for r in range(16):
        scanline_pixel_offset = (row * 16 + r) * 128 + col * 8
        file_offset = ITEM_TIM_PIXEL_DATA_FILE_OFFSET + scanline_pixel_offset
        sector_advance, byte_in_sector = divmod(file_offset, USER_DATA_BYTES)
        out.append(
            (ITEM_TIM_LBA + sector_advance) * SECTOR_SIZE_BYTES
            + SECTOR_HEADER_BYTES + byte_in_sector,
        )
    return tuple(out)


AP_ITEM_ICON_BLANK_BIN_OFFSETS: Final = _ap_item_icon_blank_offsets()
assert len(AP_ITEM_ICON_BLANK_BIN_OFFSETS) == 16


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

# Coelamon's "in city / shop is open" recruit-block bit. Pinned to 1
# each tick by the client (see :meth:`DigimonWorldClient._enforce_coelamon_beaten`)
# because Coelamon's recruit cutscene is bugged and was dropped from
# the AP pool (see :data:`_AP_RECRUIT_EXCLUDED`). The File City Item
# Shop is gated on this bit in vanilla DW1 — pinning it makes the
# game treat the shop as built, removing the need for an AP-side
# workaround (e.g. an "Item Shop Built" logic gate or a synthetic AP
# location). Andromon's recruit chain (per :func:`rules._andromon_extra`)
# normally depends on the shop being open; the pin makes that always
# true so AP logic doesn't need an explicit term for it.
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
    # 2026-05-24 — Coelamon dropped from AP pool. His recruit cutscene
    # is bugged in our current build (per user direction); rather than
    # invest in a fix, treat his slot as unreachable for now. The name
    # stays in :data:`RECRUIT_RAM_BITS` (vanilla recruit-block layout),
    # but is filtered out everywhere AP cares: no ``Coelamon Recruit``
    # item, no AP location, no bit poll. Vanilla bytecode reads of
    # ``trigger(249)`` are left in the visibility-patch tables so the
    # city still behaves correctly if the player triggers his cutscene
    # via vanilla flow.
    "Coelamon",
})
AP_RECRUIT_ITEM_DIGIMON: Final[tuple[str, ...]] = tuple(
    name for name in RECRUIT_RAM_BITS if name not in _AP_RECRUIT_EXCLUDED
)
assert len(AP_RECRUIT_ITEM_DIGIMON) == 43, len(AP_RECRUIT_ITEM_DIGIMON)


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
# Slot layout — verified against the live BIN 2026-05-10. IF primitives
# are 4 bytes each, but ``trigger(N) == X`` and ``pstat(N) <op> V`` use
# DIFFERENT encodings:
#
#   trigger(N) == true    -> ID(u16-LE) | 0x008A  (4 bytes)
#   trigger(N) == false   -> ID(u16-LE) | 0x0018  (4 bytes)
#   pstat(N) < V          -> ID(u8) | V(u8) | 0x0080  (4 bytes; ``<`` opcode)
#
# Concretely for line 162 (vanilla bytes ``62 01 8A 00 01 32 80 00 CD
# 00 18 00 B8 03``):
#
#   0x1409E4CE..D1: trigger(354) == true  -> 62 01 8A 00
#   0x1409E4D2:     pstat ID byte         = 0x01 (pstat 1 = prosperity)
#   0x1409E4D3:     comparand byte        = 0x32 (= 50 vanilla)  ← patch target
#   0x1409E4D4..D5: ``<`` operator opcode = 80 00
#   0x1409E4D6..D9: trigger(205) == false -> CD 00 18 00
#   0x1409E4DA..DB: jump target           = B8 03 (= line 952)
#
# **Earlier inferred encoding was wrong**: the 2026-05-10 v1 patch
# wrote 2 LE bytes at 0x1409E4D4, which corrupted the operator opcode
# instead of moving the threshold. With ``<`` clobbered the gate did
# not gate prosperity at all and Jijimon armed Airdramon unconditionally.
# Verified against vanilla bytes by isolating the unique 14-byte
# IF-block sequence and confirming the comparand byte sits at
# offset +5 from the IF block start.
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
#   0x80095940..0x8009597C  recycle shop giveItem wrapper (60 B, opt-in)
#   0x80095980..0x80095D80  RELOC_ITEM_DESC_PTR (1024 B, opt-in) <- this section
#   0x80095D80..0x80095F40  AP_DESC_STRINGS (448 B, opt-in)       <-
#   0x80095F40..0x80096BCC  ~3.1 KB free for future expansion
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


# --- Extended ITEM_PARA region ----------------------------------------------
# The freed bytes at the original ITEM_DESC_PTR location become extended
# ITEM_PARA slots 128..255. We populate slots 128..134; slots 135..255
# stay whatever the vanilla data happened to be (we don't depend on them).
EXT_ITEM_PARA_RAM: Final = VANILLA_ITEM_DESC_PTR_RAM                       # 0x801279DC
EXT_ITEM_PARA_BIN_OFFSET: Final = VANILLA_ITEM_DESC_PTR_BIN_OFFSET


def ext_item_para_slot_bin_offset(slot: int) -> int:
    """Sector-aware .bin offset of extended ITEM_PARA slot ``slot``.

    Two contiguous segments are supported:

    * **slots 128..143** — freed ITEM_DESC_PTR region (vanilla
      ITEM_PARA's natural extension; 16 slots). Reached by the
      vanilla scan loop just by bumping its bound past 128.
    * **slots 144..173** — :data:`CAVE6_ITEM_PARA_EXT_RAM` (Cave6 ext
      segment; 30 slots). Reached by the merit-shop scan loop after
      patching it to teleport via
      :data:`CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM`.

    Slots 144..173 in the Cave6 segment are NOT contiguous with vanilla
    ITEM_PARA in RAM, but any consumer of this helper is just resolving
    a .bin offset to write a slot's 32-byte entry — the segment-routing
    is handled here transparently.
    """

    if 128 <= slot < CAVE6_ITEM_PARA_EXT_SLOT_BASE:
        return _table_byte_to_bin_flat(slot * ROM_ITEM_TABLE_ENTRY_SIZE)
    if CAVE6_ITEM_PARA_EXT_SLOT_BASE <= slot <= CAVE6_ITEM_PARA_EXT_SLOT_LAST:
        cave6_byte_offset = (slot - CAVE6_ITEM_PARA_EXT_SLOT_BASE) * ROM_ITEM_TABLE_ENTRY_SIZE
        return CAVE6_ITEM_PARA_EXT_BIN_OFFSET + cave6_byte_offset
    raise ValueError(
        f"Extended ITEM_PARA slot {slot} out of supported range "
        f"[128, {CAVE6_ITEM_PARA_EXT_SLOT_LAST + 1})"
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


# --- setItemTexture clamp wrapper (icon fix for extended ITEM_PARA slots) --
# Vanilla ``setItemTexture`` at RAM 0x800E5DFC computes
# ``col = item_id % 16; row = item_id / 16`` and reads a 16x16 tile from
# ITEM.TIM at those grid coordinates. ITEM.TIM is laid out as 16 cols x
# 8 rows of 16x16 tiles (= 128 tiles total, exactly slots 0..127). Our
# extended slots 128..134 map to col=0..6, row=8 — OFF the texture, so
# the renderer reads garbage pixels for AP shop slot icons.
#
# Fix: install a small trampoline before ``setItemTexture``'s prologue
# that clamps any ``item_id >= 128`` to slot 83 (the universal "AP Item"
# slot whose icon is already blanked in ITEM.TIM via
# :data:`AP_ITEM_ICON_BLANK_BIN_OFFSETS`). After the clamp, the
# trampoline reproduces the displaced first 2 instructions of
# ``setItemTexture`` and ``j``s back into the function body.
#
# Function layout (vanilla):
#   0x800E5DFC  addiu $sp, $sp, -0x28   <- prologue instr 1 (we hijack)
#   0x800E5E00  sw    $ra, 0x20($sp)    <- prologue instr 2 (becomes nop)
#   0x800E5E04  sw    $s1, 0x1C($sp)    <- where the trampoline returns
#   ...
#
# Wrapper layout (7 instructions / 28 bytes):
#   sltiu $t0, $a1, RECYCLE_SHOP_AP_ITEM_ID_BASE  ; t0 = (item < 128) ? 1 : 0
#   bne   $t0, $0, .keep
#   nop                                            ; bne delay slot
#   addiu $a1, $0, AP_CHEST_SENTINEL_ITEM_ID       ; clamp: item = 83
#  .keep:
#   addiu $sp, $sp, -0x28                          ; reproduced instr 1
#   j     0x800E5E04                               ; jump back to instr 3
#   sw    $ra, 0x20($sp)                           ; reproduced instr 2
#                                                  ; (delay slot of j)
#
# Wrapper sits in Cave6 immediately after AP_DESC_STRINGS (which ends at
# RAM 0x80095F40). 4-byte aligned. ~3.1 KB of Cave6 still free after.

ROM_SET_ITEM_TEXTURE_RAM: Final = 0x800E5DFC
ROM_SET_ITEM_TEXTURE_RETURN_RAM: Final = 0x800E5E04  # instr 3 of setItemTexture

ROM_ICON_CLAMP_WRAPPER_RAM: Final = (
    AP_DESC_STRINGS_RAM + AP_DESC_STRINGS_TOTAL_SIZE                         # 0x80095F40
)
ROM_ICON_CLAMP_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_ICON_CLAMP_WRAPPER_RAM,
)


def _build_icon_clamp_wrapper_bytes() -> bytes:
    """Build the setItemTexture clamp trampoline.

    7 MIPS instructions / 28 bytes. See :data:`ROM_ICON_CLAMP_WRAPPER_RAM`
    block comment for the dispatch shape.
    """

    import struct as _struct

    j_back = (
        0x08000000 | ((ROM_SET_ITEM_TEXTURE_RETURN_RAM >> 2) & 0x03FFFFFF)
    )
    return b"".join(
        _struct.pack("<I", v) for v in (
            # sltiu $t0, $a1, 128
            0x2CA80000 | (RECYCLE_SHOP_AP_ITEM_ID_BASE & 0xFFFF),
            # bne $t0, $0, +2  (skip the clamp instructions if in-range)
            0x15000002,
            # nop (bne delay slot)
            0x00000000,
            # addiu $a1, $0, 83  (clamp: a1 = AP chest sentinel slot)
            0x24050000 | (AP_CHEST_SENTINEL_ITEM_ID & 0xFFFF),
            # addiu $sp, $sp, -0x28  (reproduced setItemTexture instr 1)
            0x27BDFFD8,
            # j 0x800E5E04  (return to setItemTexture instr 3)
            j_back,
            # sw $ra, 0x20($sp)  (reproduced instr 2 — j delay slot)
            0xAFBF0020,
        )
    )


ROM_ICON_CLAMP_WRAPPER_BYTES: Final = _build_icon_clamp_wrapper_bytes()
assert len(ROM_ICON_CLAMP_WRAPPER_BYTES) == 28, len(ROM_ICON_CLAMP_WRAPPER_BYTES)

# Cave6 bounds re-check — wrapper extends past AP_DESC_STRINGS.
assert (ROM_ICON_CLAMP_WRAPPER_RAM + len(ROM_ICON_CLAMP_WRAPPER_BYTES)
        <= _CAVE6_END_RAM), (
    f"Icon clamp wrapper end "
    f"0x{ROM_ICON_CLAMP_WRAPPER_RAM + len(ROM_ICON_CLAMP_WRAPPER_BYTES):08X} "
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

ROM_RECYCLE_SHOP_INIT_WRAPPER_RAM: Final = (
    ROM_ICON_CLAMP_WRAPPER_RAM + len(ROM_ICON_CLAMP_WRAPPER_BYTES)           # 0x80095F5C
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
# **Hard ceiling**: the freed ITEM_DESC_PTR region at vanilla RAM
# ``0x801279DC..0x80127BDC`` is 512 bytes = exactly 16 ITEM_PARA slots
# (128..143). Beyond slot 143, RAM ``0x80127BDC`` hosts an item-color /
# palette-index table read by ``setItemTexture`` at ``0x000E5E80..
# 0x000E5E8C`` (verified 2026-05-13 against references/DW1-Code/SLUS.asm).
# Writing extended ITEM_PARA entries past slot 143 corrupts that table —
# the merit-shop ``mark_bought`` memcpy at runtime then doubles the
# damage with every purchase, causing the post-purchase refresh to
# freeze the game. Recycle shop uses 7 of the 16 (128..134); merit shop
# uses the remaining 9 (135..143).
MERIT_SHOP_AP_ITEM_ID_BASE: Final = 135
MERIT_SHOP_AP_ITEM_ID_COUNT: Final = 14
MERIT_SHOP_AP_ITEM_IDS: Final = tuple(
    MERIT_SHOP_AP_ITEM_ID_BASE + i
    for i in range(MERIT_SHOP_AP_ITEM_ID_COUNT)
)
# Highest used extended slot (148 = 135 + 13). Slots 135..143 live in
# the freed ITEM_DESC_PTR region (contiguous with vanilla ITEM_PARA);
# slots 144..148 live in the Cave6 ext segment reached via the
# merit-scan teleport wrapper. The scan-loop bound patch below uses
# 149 (= 148 + 1) so the scan reaches up through slot 148.
MERIT_SHOP_AP_ITEM_ID_LAST: Final = (
    MERIT_SHOP_AP_ITEM_ID_BASE + MERIT_SHOP_AP_ITEM_ID_COUNT - 1            # 148
)
# Sanity: must come after recycle shop's range (128..134) and stay
# inside the unified extended-slot range supported by ext_item_para_slot_bin_offset
# (freed ITEM_DESC_PTR for 128..143 + Cave6 ext for 144..173).
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
# All 14 entries become AP slots: slots 135..143 sit in the freed
# ITEM_DESC_PTR region (contiguous with vanilla); slots 144..148 sit in
# the Cave6 ext segment, reached via the merit-scan teleport wrapper.
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
    (0x5B, "Waterbottle",   500),  # value=5000   -> Merit Shop #10  (Cave6 ext slot 144)
    (0x5D, "Red Shell",     500),  # value=5000   -> Merit Shop #11  (Cave6 ext slot 145)
    (0x5E, "Hard Scale",    500),  # value=5000   -> Merit Shop #12  (Cave6 ext slot 146)
    (0x60, "Ice crystal",   500),  # value=5000   -> Merit Shop #13  (Cave6 ext slot 147)
    (0x75, "Amazing rod",   300),  # value=3000   -> Merit Shop #14  (Cave6 ext slot 148)
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
    ITEM_PARA_BASE = 0x80000000 | RAM_ITEM_PARA
    SENTINEL_RAM = 0x80000000 | AP_SHOP_BOUGHT_SENTINEL_RAM

    n_entries = len(MERIT_SHOP_EXT_DISPATCH)
    # mark_bought RAM address = wrapper start + prologue (16) +
    # per-entry blocks (28 * N) + give_item path (24).
    mark_bought_offset = 0x10 + 28 * n_entries + 0x18
    mark_bought_ram = ROM_MERIT_SHOP_EXT_WRAPPER_RAM + mark_bought_offset
    j_mark = 0x08000000 | ((mark_bought_ram >> 2) & 0x03FFFFFF)
    j_giveitem = 0x08000000 | ((GIVEITEM_RAM >> 2) & 0x03FFFFFF)
    jal_settrigger = 0x0C000000 | ((SETTRIGGER_RAM >> 2) & 0x03FFFFFF)

    # Sign-extension-aware decomposition; works for both vanilla
    # (0x801269DC, low half 0x69DC < 0x8000) and relocated
    # (0x8009DBC8, low half 0xDBC8 >= 0x8000) bases.
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
# Cave6 ITEM_PARA extension segment (slots 144..173)
# =============================================================================
#
# Lifts the 16-slot extended-ITEM_PARA ceiling by adding a SECOND
# extension segment in Cave6, just past the merit-shop EXT wrapper.
# Reached via the merit-scan teleport wrapper below.
#
# **Why not extend the existing freed-ITEM_DESC_PTR region?** The freed
# region at 0x801279DC..0x80127BDC is exactly 512 bytes (slots 128..143).
# Slot 144 would start at 0x80127BDC where the per-item color table
# lives — clobbering it crashes the merit-shop refresh after any
# purchase. See the block comment near MERIT_SHOP_AP_ITEM_ID_BASE.
#
# **Why not relocate ITEM_PARA wholesale (Path A)?** Path A tried that
# and froze the arena because the chosen "free" SLUS-exec region held
# function-pointer constants stored as raw u32 in the 0x80137000
# dispatch struct array. See the Path A revert block below.
#
# **This approach (Cave6 multi-segment)**: keep slots 0..143 where they
# are (vanilla ITEM_PARA + naturally-contiguous freed-DESC region), and
# put slots 144..173 in Cave6. The merit-shop scan loop is patched to
# **teleport** its iteration pointer when slot_id reaches 144 — instead
# of reading garbage from the color table, it jumps to the Cave6 ext
# base. See :data:`CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM`.
#
# **Layout inside Cave6** (sector 148351, ud-bytes 0..2047):
#
#   0x80096800..0x80096BC0   ITEM_PARA ext segment (30 slots × 32 B)
#   0x80096BC0..0x80096BCC   tail (12 B, unused)
#
# Why 0x80096800 specifically: Mode2/2352 sector boundary. Cave6's first
# sector ends at 0x80096800; placing the segment AT that boundary keeps
# it inside one sector — :func:`apply_tokens` does flat writes and
# crossing sector boundaries corrupts the next sector header (see the
# MERIT_AP_DESC_STRINGS_RAM block comment for the prior incident).
# 30 slots × 32 B = 960 B fits in the 2048-byte sector ud-region with
# 1088 B to spare for future shops.
#
# **Slot allocation**:
#   - Slots 144..148: Merit Shop AP slots 10..14 (this commit).
#   - Slots 149..173: reserved for future shops (File City regular
#     shop, Secret shops, etc.).
#
# **Sector-boundary alignment**: each individual 32-byte slot write
# stays inside the sector since 32 << 2048. Future shops can write to
# any slot in 144..173 via :func:`ext_item_para_slot_bin_offset`.

CAVE6_ITEM_PARA_EXT_RAM: Final = 0x80096800
CAVE6_ITEM_PARA_EXT_SLOT_BASE: Final = 144
CAVE6_ITEM_PARA_EXT_SLOT_COUNT: Final = 30
CAVE6_ITEM_PARA_EXT_SLOT_LAST: Final = (
    CAVE6_ITEM_PARA_EXT_SLOT_BASE + CAVE6_ITEM_PARA_EXT_SLOT_COUNT - 1       # 173
)
CAVE6_ITEM_PARA_EXT_SIZE: Final = (
    CAVE6_ITEM_PARA_EXT_SLOT_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE               # 960
)
CAVE6_ITEM_PARA_EXT_BIN_OFFSET: Final = _slus_ram_to_bin_offset(
    CAVE6_ITEM_PARA_EXT_RAM,
)
# Bounds: must fit inside Cave6 and inside one 2048-byte sector.
assert CAVE6_ITEM_PARA_EXT_RAM + CAVE6_ITEM_PARA_EXT_SIZE <= _CAVE6_END_RAM, (
    f"Cave6 ITEM_PARA ext overflow: ends at "
    f"0x{CAVE6_ITEM_PARA_EXT_RAM + CAVE6_ITEM_PARA_EXT_SIZE:08X}, "
    f"Cave6 ends at 0x{_CAVE6_END_RAM:08X}"
)
# Sector 148351's ud-region: 0x80096800..0x80097000 (2048 B). The whole
# ext segment must stay within this single sector.
assert CAVE6_ITEM_PARA_EXT_RAM + CAVE6_ITEM_PARA_EXT_SIZE <= 0x80097000, (
    f"Cave6 ITEM_PARA ext crosses sector 148351 boundary at 0x80097000"
)
assert MERIT_SHOP_AP_ITEM_ID_LAST <= CAVE6_ITEM_PARA_EXT_SLOT_LAST, (
    f"merit shop's highest slot {MERIT_SHOP_AP_ITEM_ID_LAST} exceeds Cave6 "
    f"ext capacity (last slot {CAVE6_ITEM_PARA_EXT_SLOT_LAST})"
)


# =============================================================================
# Merit-scan teleport wrapper (Cave6, conditional on MeritShopLocations)
# =============================================================================
#
# The merit-shop ITEM_PARA scan loop iterates over slot_id 0..N-1
# (with N bumped from 128 to 149 by ROM_MERIT_SCAN_BOUND_*). Per
# iteration the original code at PC 0x80107... computes
#   r10 = ITEM_PARA + r7        (r7 = slot_id * 32)
# via the 3-instruction sequence at PCs 0x0010732C..0x00107334:
#
#   0x0010732C  lui   r9, 0x8012
#   0x00107330  addiu r9, r9, 0x69f4    ; r9 = vanilla ITEM_PARA + 0x18
#   0x00107334  addu  r10, r9, r7       ; r10 = ITEM_PARA + r7 + 0x18
#
# This fails for slot_id >= 144 because slot 144's natural ITEM_PARA
# address is 0x80127BDC (= start of the per-item color table) and
# higher slots walk further into the color table — corruption.
#
# Patch: replace those 3 instructions with ``j teleport_wrapper; nop;
# nop``. The wrapper computes r10 = ITEM_PARA[slot_id].meritValue based
# on whether slot_id is in the freed-DESC range (< 144) or the Cave6
# ext range (>= 144), then ``j 0x80107338`` (= the original ``lhu``
# instruction after the patched 3) to return to the scan loop body.
#
# No ``$ra`` clobber: we use unconditional ``j``, not ``jal``. The
# scan loop's own ``jr $ra`` at function end stays intact.

CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM: Final = (
    ROM_MERIT_SHOP_EXT_WRAPPER_RAM + len(ROM_MERIT_SHOP_EXT_WRAPPER_BYTES)
)
assert CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM % 4 == 0, hex(
    CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM
)
CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM,
)

# The 3-instruction patch site in the merit scan loop body.
ROM_MERIT_SCAN_BASE_PATCH_RAM: Final = 0x8010732C
ROM_MERIT_SCAN_BASE_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_SCAN_BASE_PATCH_RAM,
)
# Return target inside the scan loop body (the ``lhu`` instruction
# immediately after the 3 patched instructions).
ROM_MERIT_SCAN_RETURN_RAM: Final = 0x80107338


def _build_merit_scan_teleport_wrapper_bytes() -> bytes:
    """Build the 16-instruction (64 B) teleport wrapper.

    Returns bytes ready for an apply_tokens ``WRITE`` at
    :data:`CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_OFFSET`. The wrapper
    expects scan-loop registers in their original meanings:
      * r5 = slot_id  (loop counter, 0..148)
      * r7 = slot_id * 32  (byte offset into vanilla ITEM_PARA)

    On exit (via unconditional ``j``):
      * r10 = address of the current slot's ``meritValue`` halfword
        (= base + 0x18, where base is vanilla 0x801269DC or Cave6 ext
        :data:`CAVE6_ITEM_PARA_EXT_RAM`).
      * r9, r1 are clobbered (temp-use).
      * Control returns to :data:`ROM_MERIT_SCAN_RETURN_RAM`.
    """

    import struct as _struct

    # Encode ``j ROM_MERIT_SCAN_RETURN_RAM`` once — used twice.
    j_return = 0x08000000 | (
        (ROM_MERIT_SCAN_RETURN_RAM >> 2) & 0x03FFFFFF
    )

    # Cave6 ext base low/high. CAVE6_ITEM_PARA_EXT_RAM = 0x80096800;
    # low half = 0x6800 < 0x8000, no sign-extension needed.
    cave6_hi = (CAVE6_ITEM_PARA_EXT_RAM >> 16) & 0xFFFF                       # 0x8009
    cave6_lo = CAVE6_ITEM_PARA_EXT_RAM & 0xFFFF                               # 0x6800
    assert cave6_lo < 0x8000, hex(cave6_lo)

    threshold = CAVE6_ITEM_PARA_EXT_SLOT_BASE                                 # 144 = 0x90

    out = bytearray()

    # offset 0x00 — sltiu r1, r5, threshold (r1 = r5 < 144)
    out += _struct.pack("<I", (0x0B << 26) | (5 << 21) | (1 << 16) | threshold)
    # offset 0x04 — beq r1, r0, +6 (skip vanilla path -> ext_path at 0x20)
    out += _struct.pack("<I", (0x04 << 26) | (1 << 21) | (0 << 16) | 6)
    # offset 0x08 — nop (branch delay slot)
    out += _struct.pack("<I", 0x00000000)

    # Vanilla path: r10 = 0x801269F4 + r7
    # offset 0x0C — lui r9, 0x8012
    out += _struct.pack("<I", 0x3C098012)
    # offset 0x10 — addiu r9, r9, 0x69F4
    out += _struct.pack("<I", 0x252969F4)
    # offset 0x14 — addu r10, r9, r7
    out += _struct.pack("<I", 0x01275021)
    # offset 0x18 — j ROM_MERIT_SCAN_RETURN_RAM
    out += _struct.pack("<I", j_return)
    # offset 0x1C — nop (delay slot)
    out += _struct.pack("<I", 0x00000000)

    # Ext path: r10 = CAVE6_EXT + (r5 - 144) * 32 + 0x18
    # offset 0x20 — addi r9, r5, -144   (signed imm = 0xFF70)
    out += _struct.pack("<I", (0x08 << 26) | (5 << 21) | (9 << 16) | 0xFF70)
    # offset 0x24 — sll r9, r9, 5       (* 32)
    out += _struct.pack("<I", (0 << 26) | (0 << 21) | (9 << 16) | (9 << 11) | (5 << 6))
    # offset 0x28 — lui r1, cave6_hi
    out += _struct.pack("<I", (0x0F << 26) | (0 << 21) | (1 << 16) | cave6_hi)
    # offset 0x2C — addiu r1, r1, cave6_lo
    out += _struct.pack("<I", (0x09 << 26) | (1 << 21) | (1 << 16) | cave6_lo)
    # offset 0x30 — addu r10, r1, r9
    out += _struct.pack("<I", (0 << 26) | (1 << 21) | (9 << 16) | (10 << 11) | (0 << 6) | 0x21)
    # offset 0x34 — addiu r10, r10, 0x18
    out += _struct.pack("<I", (0x09 << 26) | (10 << 21) | (10 << 16) | 0x18)
    # offset 0x38 — j ROM_MERIT_SCAN_RETURN_RAM
    out += _struct.pack("<I", j_return)
    # offset 0x3C — nop (delay slot)
    out += _struct.pack("<I", 0x00000000)

    return bytes(out)


ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES: Final = _build_merit_scan_teleport_wrapper_bytes()
assert len(ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES) == 64, (
    len(ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES)
)

# Cave6 layout assertion: teleport wrapper must stay inside sector
# 148350's ud-region (ends at RAM 0x80096800).
assert (CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM
        + len(ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES)
        <= 0x80096800), (
    f"merit-scan teleport wrapper "
    f"0x{CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM:08X}.."
    f"0x{CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM + len(ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES):08X} "
    f"crosses Cave6 sector 148350 boundary at 0x80096800"
)


# =============================================================================
# Merit-shop NAME teleport wrapper (Cave6, conditional on MeritShopLocations)
# =============================================================================
#
# Independent from the scan teleport. The merit shop renders each row's
# name via a SEPARATE codepath at PC 0x80101A4C..0x00101A58 (= the
# 22nd ITEM_PARA reader from tools/dw1_scan_item_para_readers.py). It
# computes the name address as
#   r5 = ITEM_PARA + slot_id * 32
# via
#   0x00101A4C  lui r2, 0x8012
#   0x00101A50  sll r3, r5, 5         (r5 = slot_id in, r3 = slot*32)
#   0x00101A54  addiu r2, r2, 0x69DC
#   0x00101A58  addu r5, r2, r3       (r5 = name addr out)
# then jal's a text renderer with r5 as the string pointer.
#
# For slot_id >= 144 (Cave6 ext) this naively reads from RAM
# 0x80127BDC — the per-item color table — and the text renderer
# treats palette bytes as ASCII (visible as triangles / corrupt text
# in the merit shop UI; bug reported 2026-05-13 against the Cave6
# multi-segment release).
#
# Fix: patch the same 3 instructions with ``j name_wrapper; nop; nop``,
# wrapper computes r5 = ITEM_PARA-or-CAVE6_EXT + slot_offset, then
# ``j`` back to 0x80101A5C (the next instruction, ``addu r18, r5, r0``).
# Same return-via-``j`` approach as the scan wrapper — no $ra clobber.

CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM: Final = (
    CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM
    + len(ROM_MERIT_SCAN_TELEPORT_WRAPPER_BYTES)
)
assert CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM % 4 == 0, hex(
    CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM
)
CAVE6_MERIT_NAME_TELEPORT_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM,
)

# The 3-instruction patch site in the name-renderer's pointer setup.
ROM_MERIT_NAME_PATCH_RAM: Final = 0x80101A4C
ROM_MERIT_NAME_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_NAME_PATCH_RAM,
)
# Return target = the instruction immediately after the patch site
# (``addu r18, r5, r0`` that copies r5 into r18 before the text renderer
# jal at 0x80101A60).
ROM_MERIT_NAME_RETURN_RAM: Final = 0x80101A5C


def _build_merit_name_teleport_wrapper_bytes() -> bytes:
    """Build the 16-instruction (64 B) name-renderer teleport wrapper.

    Input: r5 = slot_id (the merit shop's current row's item id, already
    ``andi r5, r5, 0xFF``-masked by the original 0x00101A48).
    Output: r5 = name field address inside ITEM_PARA[slot_id]
    (== ITEM_PARA_base[slot_id] + 0; the text renderer reads bytes 0..19
    as the ASCII name string).

    Layout (16 words, 64 B). Vanilla path occupies words 3..7; ext path
    occupies words 9..14. The ``j`` instructions' delay slots are
    explicit nops at offsets 0x20 and 0x3C — no overlap with the
    ext_path entry label at 0x24.

    Clobbers r1, r2, r3, r5 (same set the original 3 instructions
    clobber, plus r1 for the threshold compare). r4, r16, r17, r18,
    $sp are preserved.
    """

    import struct as _struct

    j_return = 0x08000000 | (
        (ROM_MERIT_NAME_RETURN_RAM >> 2) & 0x03FFFFFF
    )

    cave6_hi = (CAVE6_ITEM_PARA_EXT_RAM >> 16) & 0xFFFF                       # 0x8009
    cave6_lo = CAVE6_ITEM_PARA_EXT_RAM & 0xFFFF                               # 0x6800

    threshold = CAVE6_ITEM_PARA_EXT_SLOT_BASE                                 # 144

    out = bytearray()

    # offset 0x00 — sltiu r1, r5, threshold
    out += _struct.pack("<I", (0x0B << 26) | (5 << 21) | (1 << 16) | threshold)
    # offset 0x04 — beq r1, r0, +7 (ext_path target = 0x04 + 4 + 7*4 = 0x24)
    out += _struct.pack("<I", (0x04 << 26) | (1 << 21) | (0 << 16) | 7)
    # offset 0x08 — nop (branch delay slot)
    out += _struct.pack("<I", 0x00000000)

    # Vanilla path (offsets 0x0C..0x20): r5 = vanilla ITEM_PARA + slot*32
    # offset 0x0C — sll r3, r5, 5
    out += _struct.pack("<I", (0 << 26) | (0 << 21) | (5 << 16) | (3 << 11) | (5 << 6))
    # offset 0x10 — lui r2, 0x8012
    out += _struct.pack("<I", 0x3C028012)
    # offset 0x14 — addiu r2, r2, 0x69DC
    out += _struct.pack("<I", 0x244269DC)
    # offset 0x18 — addu r5, r2, r3
    out += _struct.pack("<I", (0 << 26) | (2 << 21) | (3 << 16) | (5 << 11) | (0 << 6) | 0x21)
    # offset 0x1C — j ROM_MERIT_NAME_RETURN_RAM
    out += _struct.pack("<I", j_return)
    # offset 0x20 — nop (j delay slot)
    out += _struct.pack("<I", 0x00000000)

    # Ext path (offsets 0x24..0x3C): r5 = CAVE6_EXT + (slot - 144) * 32
    # offset 0x24 — addi r3, r5, -144  (signed imm = 0xFF70)
    out += _struct.pack("<I", (0x08 << 26) | (5 << 21) | (3 << 16) | 0xFF70)
    # offset 0x28 — sll r3, r3, 5
    out += _struct.pack("<I", (0 << 26) | (0 << 21) | (3 << 16) | (3 << 11) | (5 << 6))
    # offset 0x2C — lui r2, cave6_hi
    out += _struct.pack("<I", (0x0F << 26) | (0 << 21) | (2 << 16) | cave6_hi)
    # offset 0x30 — addiu r2, r2, cave6_lo
    out += _struct.pack("<I", (0x09 << 26) | (2 << 21) | (2 << 16) | cave6_lo)
    # offset 0x34 — addu r5, r2, r3
    out += _struct.pack("<I", (0 << 26) | (2 << 21) | (3 << 16) | (5 << 11) | (0 << 6) | 0x21)
    # offset 0x38 — j ROM_MERIT_NAME_RETURN_RAM
    out += _struct.pack("<I", j_return)
    # offset 0x3C — nop (j delay slot)
    out += _struct.pack("<I", 0x00000000)

    return bytes(out)


# The 3-instruction patch at ROM_MERIT_SCAN_BASE_PATCH_RAM:
#   j   CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM
#   nop
#   nop
# Total 12 bytes. Emitted as a single token write when MeritShopLocations
# is on.
def _build_merit_scan_base_patch_bytes() -> bytes:
    import struct as _struct
    j_wrapper = 0x08000000 | (
        (CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM >> 2) & 0x03FFFFFF
    )
    return (
        _struct.pack("<I", j_wrapper)
        + _struct.pack("<I", 0x00000000)
        + _struct.pack("<I", 0x00000000)
    )


ROM_MERIT_SCAN_BASE_PATCH_BYTES: Final = _build_merit_scan_base_patch_bytes()
assert len(ROM_MERIT_SCAN_BASE_PATCH_BYTES) == 12


ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES: Final = _build_merit_name_teleport_wrapper_bytes()
assert len(ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES) == 64, (
    len(ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES)
)

# Cave6 layout assertion: name teleport wrapper must stay inside sector
# 148350's ud-region (ends at RAM 0x80096800).
assert (CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM
        + len(ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES)
        <= 0x80096800), (
    f"merit-name teleport wrapper "
    f"0x{CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM:08X}.."
    f"0x{CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM + len(ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES):08X} "
    f"crosses Cave6 sector 148350 boundary at 0x80096800"
)


def _build_merit_name_patch_bytes() -> bytes:
    """3-instruction patch at ROM_MERIT_NAME_PATCH_RAM (= 0x80101A4C):
    ``j CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM; nop; nop``.
    """

    import struct as _struct
    j_wrapper = 0x08000000 | (
        (CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM >> 2) & 0x03FFFFFF
    )
    return (
        _struct.pack("<I", j_wrapper)
        + _struct.pack("<I", 0x00000000)
        + _struct.pack("<I", 0x00000000)
    )


ROM_MERIT_NAME_PATCH_BYTES: Final = _build_merit_name_patch_bytes()
assert len(ROM_MERIT_NAME_PATCH_BYTES) == 12


# =============================================================================
# Merit-shop ROW-DISPLAY function teleport wrapper (Cave6, conditional)
# =============================================================================
#
# The merit shop's per-row display function (entered at SLUS PC
# 0x000FE704) reads ITEM_PARA[slot] THREE times per row via a shared
# offset register r17:
#
#   0x000FE7F0  sll  r3, r2, 5         r3 = slot * 32 (r2 = slot_id arg)
#   0x000FE7F4  lui  r2, 0x8012        \\
#   0x000FE7F8  addiu r2, r2, 0x69DC    > r2 = vanilla ITEM_PARA;
#   0x000FE7FC  addu r5, r2, r3         / r5 = name addr (= base + r3)
#   0x000FE800  addu r17, r3, r0       r17 = slot * 32 (saved for siblings)
#   ...
#   0x000FE874  lui r2, 0x8012; addiu r2, r2, 0x69F0; addu r2, r2, r17
#                                      r2 = vanilla.value (= money field)
#   ...
#   0x000FE8FC  lui r2, 0x8012; addiu r2, r2, 0x69F4; addu r2, r2, r17
#                                      r2 = vanilla.meritValue
#
# For slot_id >= 144, every one of these reads lands in the per-item
# color table at RAM 0x80127BDC and the displayed name + value + merit
# price are all garbage (triangles + nonsense numbers — bug reported
# 2026-05-13 against the Cave6 multi-segment release; the earlier
# 0x101A4C name-teleport didn't fix it because the merit shop uses
# THIS function, not the one at 0x101A4C).
#
# **The r17-offset trick**: instead of patching all three reader
# callsites, patch ONLY the first one (0x000FE7F4) with a wrapper that
# for slot >= 144 sets r17 = (slot - 144)*32 + (CAVE6 - vanilla). Then
# the downstream sibling reads — which do ``r2 = vanilla_base + field;
# addu r2, r2, r17`` — automatically land in Cave6:
#
#   r2 + r17 = (vanilla_base + field) + ((slot - 144)*32 + (cave6 - vanilla))
#            = cave6 + (slot - 144)*32 + field
#
# One wrapper fixes name + value + merit reads in a single shot. The
# vanilla path leaves r17 = slot*32 unchanged, so slot < 144 rows
# render exactly as before.

CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM: Final = (
    CAVE6_MERIT_NAME_TELEPORT_WRAPPER_RAM
    + len(ROM_MERIT_NAME_TELEPORT_WRAPPER_BYTES)
)
assert CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM % 4 == 0, hex(
    CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM
)
CAVE6_MERIT_ROW_TELEPORT_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM,
)

# Patch site = 4 instructions at PC 0x000FE7F4 (lui through addu r17),
# keeping the preceding ``sll r3, r2, 5`` at 0x000FE7F0 intact.
ROM_MERIT_ROW_PATCH_RAM: Final = 0x800FE7F4
ROM_MERIT_ROW_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_ROW_PATCH_RAM,
)
ROM_MERIT_ROW_RETURN_RAM: Final = 0x800FE804


def _build_merit_row_teleport_wrapper_bytes() -> bytes:
    """Build the unified row-display teleport wrapper.

    Layout (17 instructions, 68 B):

      offset 0x00  sltiu r1, r2, 0x90
      offset 0x04  beq   r1, r0, +7         (target = ext_path at 0x24)
      offset 0x08  nop                      (branch delay)
      offset 0x0C  addu  r17, r3, r0        ; vanilla: r17 = slot*32
      offset 0x10  lui   r2, 0x8012
      offset 0x14  addiu r2, r2, 0x69DC
      offset 0x18  addu  r5, r2, r17        ; r5 = vanilla + slot*32
      offset 0x1C  j     ROW_RETURN
      offset 0x20  nop                      ; j delay
      offset 0x24  lui   $at, 0xFFF7        ; ext: $at = -0x913DC
      offset 0x28  addiu $at, $at, 0xEC24   ;     (= cave6 - vanilla - 144*32)
      offset 0x2C  addu  r17, r3, $at       ; r17 = slot*32 - 0x913DC
                                            ;     = (slot-144)*32 + (cave6-vanilla)
      offset 0x30  lui   r2, 0x8012
      offset 0x34  addiu r2, r2, 0x69DC
      offset 0x38  addu  r5, r2, r17        ; r5 = cave6 + (slot-144)*32
      offset 0x3C  j     ROW_RETURN
      offset 0x40  nop                      ; j delay
    """

    import struct as _struct

    # Constant for the ext path: cave6_base - vanilla_base - 144*32
    # = 0x80096800 - 0x801269DC - 0x1200 = -0x913DC = 0xFFF6EC24 (u32).
    # Encoded as ``lui $at, 0xFFF7; addiu $at, $at, 0xEC24`` because the
    # low half 0xEC24 sign-extends to -0x13DC; (0xFFF7 << 16) - 0x13DC
    # = 0xFFF70000 - 0x13DC = 0xFFF6EC24. ✓
    ext_hi = 0xFFF7
    ext_lo = 0xEC24

    j_return = 0x08000000 | (
        (ROM_MERIT_ROW_RETURN_RAM >> 2) & 0x03FFFFFF
    )
    threshold = CAVE6_ITEM_PARA_EXT_SLOT_BASE                                  # 144

    out = bytearray()

    # 0x00 sltiu r1, r2, 0x90
    out += _struct.pack("<I", (0x0B << 26) | (2 << 21) | (1 << 16) | threshold)
    # 0x04 beq r1, r0, +7 (-> ext_path at offset 0x24)
    out += _struct.pack("<I", (0x04 << 26) | (1 << 21) | (0 << 16) | 7)
    # 0x08 nop (branch delay)
    out += _struct.pack("<I", 0x00000000)

    # Vanilla path (0x0C..0x20)
    # 0x0C addu r17, r3, r0       (rs=3, rt=0, rd=17, funct=0x21)
    out += _struct.pack("<I", (0 << 26) | (3 << 21) | (0 << 16) | (17 << 11) | (0 << 6) | 0x21)
    # 0x10 lui r2, 0x8012
    out += _struct.pack("<I", 0x3C028012)
    # 0x14 addiu r2, r2, 0x69DC
    out += _struct.pack("<I", 0x244269DC)
    # 0x18 addu r5, r2, r17        (rs=2, rt=17, rd=5, funct=0x21)
    out += _struct.pack("<I", (0 << 26) | (2 << 21) | (17 << 16) | (5 << 11) | (0 << 6) | 0x21)
    # 0x1C j ROW_RETURN
    out += _struct.pack("<I", j_return)
    # 0x20 nop (j delay)
    out += _struct.pack("<I", 0x00000000)

    # Ext path (0x24..0x40)
    # 0x24 lui $at, ext_hi
    out += _struct.pack("<I", (0x0F << 26) | (0 << 21) | (1 << 16) | ext_hi)
    # 0x28 addiu $at, $at, ext_lo
    out += _struct.pack("<I", (0x09 << 26) | (1 << 21) | (1 << 16) | ext_lo)
    # 0x2C addu r17, r3, $at        (rs=3, rt=1, rd=17, funct=0x21)
    out += _struct.pack("<I", (0 << 26) | (3 << 21) | (1 << 16) | (17 << 11) | (0 << 6) | 0x21)
    # 0x30 lui r2, 0x8012
    out += _struct.pack("<I", 0x3C028012)
    # 0x34 addiu r2, r2, 0x69DC
    out += _struct.pack("<I", 0x244269DC)
    # 0x38 addu r5, r2, r17
    out += _struct.pack("<I", (0 << 26) | (2 << 21) | (17 << 16) | (5 << 11) | (0 << 6) | 0x21)
    # 0x3C j ROW_RETURN
    out += _struct.pack("<I", j_return)
    # 0x40 nop (j delay)
    out += _struct.pack("<I", 0x00000000)

    return bytes(out)


ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES: Final = _build_merit_row_teleport_wrapper_bytes()
assert len(ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES) == 68, (
    len(ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES)
)

# Cave6 layout: row teleport wrapper must stay inside sector 148350.
assert (CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM
        + len(ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES)
        <= 0x80096800), (
    f"merit-row teleport wrapper "
    f"0x{CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM:08X}.."
    f"0x{CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM + len(ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES):08X} "
    f"crosses Cave6 sector 148350 boundary at 0x80096800"
)


def _build_merit_row_patch_bytes() -> bytes:
    """3-instruction patch at ROM_MERIT_ROW_PATCH_RAM:
    ``j wrapper; nop; nop``. Only 3 words = 12 bytes (not 4) because:

    * Word 4 of the original sequence (``addu r17, r3, r0`` at PC
      0x000FE800) is SKIPPED by the wrapper's ``j 0x000FE804`` return,
      so it doesn't need to be neutralised — leaving it intact has no
      effect at runtime.
    * Writing a 4th word here would spill into sector 148558's EDC
      region (sector user-data ends at .bin 0x14D394B8 = patch start
      + 12). ``apply_tokens`` writes flatly and crossing the user-data
      boundary loses the 4th word, which is exactly the bug observed
      on 2026-05-13. Keeping the patch at 12 bytes stays inside
      sector 148558's user-data window.
    """

    import struct as _struct
    j_wrapper = 0x08000000 | (
        (CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM >> 2) & 0x03FFFFFF
    )
    return (
        _struct.pack("<I", j_wrapper)
        + _struct.pack("<I", 0x00000000)
        + _struct.pack("<I", 0x00000000)
    )


ROM_MERIT_ROW_PATCH_BYTES: Final = _build_merit_row_patch_bytes()
assert len(ROM_MERIT_ROW_PATCH_BYTES) == 12


# =============================================================================
# Merit-shop PURCHASE-DEDUCT teleport wrapper (Cave6, conditional)
# =============================================================================
#
# The merit shop's purchase pipeline reads the slot's ``meritValue``
# AGAIN — separate from the scan loop and the row-display function —
# in the function around PC 0x000FAFB0..0x000FB068. At 0x000FB018 it
# computes ``r2 = ITEM_PARA + slot*32 + 0x18`` via vanilla addressing,
# then ``lhu`` reads the meritValue and stores it to ``-0x6B20(r28)``,
# which the state-machine later subtracts from the player's merit
# counter (the deduct itself happens at PC 0x0010BF18).
#
# For slot >= 144 this read lands in the per-item color table at
# RAM 0x80127BDC and returns whatever palette byte happens to be at
# ``0x80127BDC + (slot-128)*32 + 0x18``. In testing on 2026-05-13 the
# user reported deducted values in the 3000..6000 range for Cave6
# ext slots (matching color-table reads of 3588 / 1036 / 5900 / 5892
# / 5910 for slots 144..148), with merit going negative and the UI
# corrupting after purchase.
#
# Fix: teleport the same way the scan / row-display readers do.
# Replace the 4 instructions at 0x000FB018..0x000FB024 with
# ``j wrapper; nop; nop; nop``. Wrapper computes
# ``r2 = ITEM_PARA[slot].meritValue address`` (vanilla base for
# slot < 144, Cave6 ext base for slot >= 144), then ``j 0x800FB028``
# returns to the original ``lhu`` instruction.

CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM: Final = (
    CAVE6_MERIT_ROW_TELEPORT_WRAPPER_RAM
    + len(ROM_MERIT_ROW_TELEPORT_WRAPPER_BYTES)
)
assert CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM % 4 == 0, hex(
    CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM
)
CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_OFFSET: Final = _slus_ram_to_bin_offset(
    CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM,
)

ROM_MERIT_DEDUCT_PATCH_RAM: Final = 0x800FB018
ROM_MERIT_DEDUCT_PATCH_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_DEDUCT_PATCH_RAM,
)
# Return target = the ``lhu r2, 0x0000(r2)`` immediately after the
# four patched instructions.
ROM_MERIT_DEDUCT_RETURN_RAM: Final = 0x800FB028


def _build_merit_deduct_teleport_wrapper_bytes() -> bytes:
    """Build the 17-instruction (68 B) deduct-path teleport wrapper.

    Input: r5 = slot_id.
    Output: r2 = address of ITEM_PARA[slot].meritValue (correctly
    routed to vanilla base for slot < 144 or Cave6 ext base for
    slot >= 144). r3 is also written but the caller doesn't depend
    on its post-wrapper value.

    Clobbers r1, r2, r3.
    """

    import struct as _struct

    j_return = 0x08000000 | (
        (ROM_MERIT_DEDUCT_RETURN_RAM >> 2) & 0x03FFFFFF
    )
    cave6_hi = (CAVE6_ITEM_PARA_EXT_RAM >> 16) & 0xFFFF                       # 0x8009
    cave6_lo = CAVE6_ITEM_PARA_EXT_RAM & 0xFFFF                               # 0x6800
    threshold = CAVE6_ITEM_PARA_EXT_SLOT_BASE                                  # 144

    out = bytearray()

    # 0x00 sltiu r1, r5, 0x90
    out += _struct.pack("<I", (0x0B << 26) | (5 << 21) | (1 << 16) | threshold)
    # 0x04 beq r1, r0, +7  (-> ext_path at offset 0x24)
    out += _struct.pack("<I", (0x04 << 26) | (1 << 21) | (0 << 16) | 7)
    # 0x08 nop (branch delay)
    out += _struct.pack("<I", 0x00000000)

    # Vanilla path (0x0C..0x20): r2 = vanilla ITEM_PARA + slot*32 + 0x18
    # 0x0C sll r3, r5, 5
    out += _struct.pack("<I", (0 << 26) | (0 << 21) | (5 << 16) | (3 << 11) | (5 << 6))
    # 0x10 lui r2, 0x8012
    out += _struct.pack("<I", 0x3C028012)
    # 0x14 addiu r2, r2, 0x69F4   (vanilla ITEM_PARA + 0x18 = meritValue base)
    out += _struct.pack("<I", 0x244269F4)
    # 0x18 addu r2, r2, r3
    out += _struct.pack("<I", (0 << 26) | (2 << 21) | (3 << 16) | (2 << 11) | (0 << 6) | 0x21)
    # 0x1C j ROM_MERIT_DEDUCT_RETURN_RAM
    out += _struct.pack("<I", j_return)
    # 0x20 nop (j delay)
    out += _struct.pack("<I", 0x00000000)

    # Ext path (0x24..0x40): r2 = CAVE6_EXT + (slot-144)*32 + 0x18
    # 0x24 addi r3, r5, -144  (signed imm = 0xFF70)
    out += _struct.pack("<I", (0x08 << 26) | (5 << 21) | (3 << 16) | 0xFF70)
    # 0x28 sll r3, r3, 5
    out += _struct.pack("<I", (0 << 26) | (0 << 21) | (3 << 16) | (3 << 11) | (5 << 6))
    # 0x2C lui r2, cave6_hi
    out += _struct.pack("<I", (0x0F << 26) | (0 << 21) | (2 << 16) | cave6_hi)
    # 0x30 addiu r2, r2, cave6_lo
    out += _struct.pack("<I", (0x09 << 26) | (2 << 21) | (2 << 16) | cave6_lo)
    # 0x34 addu r2, r2, r3
    out += _struct.pack("<I", (0 << 26) | (2 << 21) | (3 << 16) | (2 << 11) | (0 << 6) | 0x21)
    # 0x38 addiu r2, r2, 0x18    (+ meritValue offset)
    out += _struct.pack("<I", (0x09 << 26) | (2 << 21) | (2 << 16) | 0x18)
    # 0x3C j ROM_MERIT_DEDUCT_RETURN_RAM
    out += _struct.pack("<I", j_return)
    # 0x40 nop (j delay)
    out += _struct.pack("<I", 0x00000000)

    return bytes(out)


ROM_MERIT_DEDUCT_TELEPORT_WRAPPER_BYTES: Final = _build_merit_deduct_teleport_wrapper_bytes()
assert len(ROM_MERIT_DEDUCT_TELEPORT_WRAPPER_BYTES) == 68, (
    len(ROM_MERIT_DEDUCT_TELEPORT_WRAPPER_BYTES)
)

# Cave6 layout: deduct wrapper must stay inside sector 148350.
assert (CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM
        + len(ROM_MERIT_DEDUCT_TELEPORT_WRAPPER_BYTES)
        <= 0x80096800), (
    f"merit-deduct teleport wrapper "
    f"0x{CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM:08X}.."
    f"0x{CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM + len(ROM_MERIT_DEDUCT_TELEPORT_WRAPPER_BYTES):08X} "
    f"crosses Cave6 sector 148350 boundary at 0x80096800"
)


def _build_merit_deduct_patch_bytes() -> bytes:
    """4-instruction patch at ROM_MERIT_DEDUCT_PATCH_RAM:
    ``j wrapper; nop; nop; nop``. Replaces the 4 address-construction
    instructions before the ``lhu`` so the wrapper computes the merit
    field address with the right base for Cave6 ext slots.
    """

    import struct as _struct
    j_wrapper = 0x08000000 | (
        (CAVE6_MERIT_DEDUCT_TELEPORT_WRAPPER_RAM >> 2) & 0x03FFFFFF
    )
    return (
        _struct.pack("<I", j_wrapper)
        + _struct.pack("<I", 0x00000000)
        + _struct.pack("<I", 0x00000000)
        + _struct.pack("<I", 0x00000000)
    )


ROM_MERIT_DEDUCT_PATCH_BYTES: Final = _build_merit_deduct_patch_bytes()
assert len(ROM_MERIT_DEDUCT_PATCH_BYTES) == 16


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
# The infrastructure (tools/dw1_scan_item_para_readers.py, the static
# analysis in docs/item_para_relocation.md, test_item_para_relocation.py)
# is retained for re-use whenever we pick a real safe region. Current
# AP ceiling is back to slot 143 (= freed-ITEM_DESC_PTR region only):
# 7 recycle + 9 merit = exact fit.


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
# ``sltiu $r1, $r5, 0x0090`` (= 144) so the scan reaches up through
# extended slot 143 (MERIT_SHOP_AP_ITEM_ID_LAST). Don't push past 144 —
# slots 144..255 are NOT safe to scan (the per-item color table at
# RAM 0x80127BDC sits where slot-144's ITEM_PARA entry would start).
ROM_MERIT_SCAN_BOUND_RAM: Final = 0x80107430
ROM_MERIT_SCAN_BOUND_OFFSET: Final = _slus_ram_to_bin_offset(
    ROM_MERIT_SCAN_BOUND_RAM,
)
ROM_MERIT_SCAN_BOUND_FORMAT: Final = "<I"
# Encoding: opcode 0x0B (sltiu), rs=5 ($r5/$a1), rt=1 ($at), imm.
_MERIT_SCAN_BOUND_NEW_IMM: Final = MERIT_SHOP_AP_ITEM_ID_LAST + 1            # 144
assert _MERIT_SCAN_BOUND_NEW_IMM < 0x8000, _MERIT_SCAN_BOUND_NEW_IMM
ROM_MERIT_SCAN_BOUND_VALUE: Final = (
    (0x0B << 26) | (5 << 21) | (1 << 16) | _MERIT_SCAN_BOUND_NEW_IMM
)
# Sanity: vanilla bound = 0x2CA10080. New bound = 0x2CA10090 for limit 144.
assert ROM_MERIT_SCAN_BOUND_VALUE == 0x2CA10000 | _MERIT_SCAN_BOUND_NEW_IMM, (
    hex(ROM_MERIT_SCAN_BOUND_VALUE)
)
