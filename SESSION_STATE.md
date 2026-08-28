> **SUPERSEDED (2026-08-23).** This is a 2026-04-30 snapshot from the recruit-visibility arc and
> is kept only as a historical record. The live project state, roadmap and RE requirements are in
> [STATUS.md](STATUS.md).

# Session State — DW1 APWorld

Snapshot 2026-04-30 (end of recruit-visibility arc + first city-loader
expansion). Recruit visibility is **working** for ~26 unique recruits
via the Plan A revised model. ~23 still need patching, identified
via a systematic next step. **READ THIS FIRST when resuming.**

---

## The working contract (Plan A revised)

User-validated 2026-04-30 (Betamon flow):

- **Bit 200+X** = "player completed recruit cutscene". Set by vanilla
  `setTrigger(200+X)` after the recruit dialog. **No client redirect.**
  Read by the **wild-spawn** check at the Digimon's wild encounter
  screen — when set, vanilla skips loading the wild model.
- **Bit 720+X** = "AP delivered ``<X> Recruit``". Set by the client's
  recruit deliverer. Read by the **city-visibility** scripts after
  ROM patches redirect their trigger ID from 200+X → 720+X.

| Event | 200+X | 720+X | Wild | City |
|---|---|---|---|---|
| Fresh save | 0 | 0 | YES | NO |
| After cutscene | 1 (vanilla) | 0 | NO | NO |
| After AP delivery | 1 | 1 (client) | NO | YES |

The split lets the player play vanilla legitimately (cutscene works)
while keeping AP gating on the city/shop appearance. Why this works
where earlier attempts failed: **vanilla DW1 reuses the same bit
(200+X) for both wild and city gates** — no setTrigger redirect or
isTriggerSet wrapper can satisfy both at once. The fix is to leave
the recruit-block alone and ROM-patch the city-side reads to use a
separate bit (720+X) we control.

---

## What's implemented and where

### Code

- **Patch tables** in
  [`worlds/digimon_world/data/addresses.py`](worlds/digimon_world/data/addresses.py):
  - `ROM_FIELD_SPAWN_TRIGGER_PATCHES` — 29 entries across 9 scripts.
    Script-bytecode rewrites of the form `if trigger(200+X) == TRUE
    then SKIP loadDigimon`. Each entry is a 2-byte patch of the
    trigger ID at the start of the 12-byte instruction.
  - `ROM_GETTOPCITY_TRIGGER_PATCHES` — 12 entries in vanilla C
    function `getFileCityTopMap` at RAM `0x800D97DC`. Patches the
    16-bit immediate of `addiu r4, r0, <trigger>` instructions.
- **Patcher integration** in
  [`worlds/digimon_world/rom.py`](worlds/digimon_world/rom.py):
  - `_write_field_spawn_trigger_patches` — writes the 29
    field-spawn patches.
  - `_write_gettopcity_trigger_patches` — writes the 12
    getFileCityTopMap patches.
  Both called from `generate_output`.
- **Client recruit deliverer** in
  [`worlds/digimon_world/client.py`](worlds/digimon_world/client.py)
  `_make_recruit_deliverer`: reads BEATEN_BLOCK byte for the
  Digimon, OR-sets bit 720+X, returns the new byte. Idempotent
  (skips if bit already set).
- **AP location detection** in same client module — `_check_locations`
  reads `LOCATION_RAM_BITS` which now includes `**RECRUIT_RAM_BITS`
  (200+X bits). Fires the location when the cutscene completes.
- **Defensive per-tick enforcement** — `_reconcile_recruits` ORs in
  bit 720+X for every received recruit, doesn't touch the
  recruit-block (vanilla owns it).

### Removed / no longer wired (do not resurrect without strong reason)

- `setTrigger` wrapper redirect (was at vanilla `0x801065C0`).
- `changeMap` wrapper (was at Cave6 `0x80095800`).
- `isTriggerSet` wrapper (briefly tried; broke field-spawn check).
- Per-tick recruit-block toggle (was overwriting bit 200+X).

The byte definitions for these still live in `addresses.py` for
reference but are not called from `generate_output`. The
`TestChangeMapWrapper` test class is `@unittest.skip`'d and can be
deleted.

### Tests

147 passing, 4 skipped. All current behavior is verified; nothing
asserts against the obsolete wrappers.

### Latest test seed

`output/AP_58314424703745817898.zip` — includes both patch tables
(field-spawn 29 + getFileCityTopMap 12). Run via:

```
tar -xf output\AP_58314424703745817898.zip -C output\
venv\Scripts\python.exe MultiServer.py output\AP_58314424703745817898.zip
venv\Scripts\python.exe Launcher.py "output\AP_58314424703745817898_P1_Player1.apdw1"
```

---

## Recruits — current coverage

**Patched (26 unique, working contract):**

Field-spawn pattern (`setScript A B; ... if trigger(200+X) == TRUE
then SKIP loadDigimon`):
- Betamon (verified live), Greymon, Meramon, Gabumon, Elecmon,
  Kabuterimon, Frigimon, Whamon, Vegiemon, Patamon, Kunemon,
  Centarumon, Bakemon, Drimogemon, Sukamon, Giromon, Etemon,
  Biyomon, Palmon, Monochromon, Kokatorimon, Kuwagamon, Penguinmon.

getFileCityTopMap (C function — picks Top City variant):
- Angemon, Monzaemon, Birdramon. (Plus Vegimon and Palmon, already
  in field-spawn list.)

**Missing (23 unique, not yet covered):**

| Trigger | Digimon | Likely path |
|---|---|---|
| 206 | Devimon | Arena Lobby loader? |
| 207 | Airdramon | Arena Lobby loader? |
| 208 | Tyrannomon | File City Bottom shopkeeper — look for `getFileCityBottomMap` analogue |
| 210 | Seadramon | Quest-driven (Greatlake) |
| 211 | Numemon | Factory quest |
| 212 | MetalGreymon | Arena Lobby NPC |
| 213 | Mamemon | Drill Tunnel rare |
| 222 | Garurumon | Wild — re-search loose pattern |
| 226 | SkullGreymon | Mansion quest |
| 227 | MetalMamemon | Factory |
| 228 | Vademon | Postgame Big Store |
| 233 | Unimon | Mt Panorama wild — re-search loose pattern |
| 234 | Ogremon | Quest chain |
| 235 | Shellmon | Wild — re-search loose pattern |
| 240 | Andromon | Factory |
| 248 | Leomon | Tower / Hero quest |
| 249 | **Coelamon** | **Known broken** (Item Shop). Many references in Section_192 loader, Script 163, dialog scripts |
| 252 | Mojyamon | Freezeland quest |
| 253 | Nanimon | Trash Mountain |
| 254 | Megadramon | Mt Infinity |
| 255 | Piximon | Piximon's Shrine |
| 256 | Digitamamon | Postgame restaurant |
| 258 | Ninjamon | Bridge / Etemon area |

---

## Next concrete steps (when resuming)

**Priority order:**

1. **Wait for user's full-roster test results** from
   `AP_58314424703745817898.zip`. They'll tell us which of the 26
   patched recruits actually behave correctly in-game (Betamon
   already verified). Any that don't work need additional patch
   sites (Section_192 common-loader gates may be missing).

2. **Find `getFileCityBottomMap` (or analogue)**. The
   `getFileCityTopMap` function at RAM `0x800D97DC` covers the Top
   plaza (screens 168..179, 204). There's almost certainly a sibling
   for the Bottom plaza (screens 180..203, 0xB4/0xB5 the user
   tested). That function would gate Coelamon, Tyrannomon, possibly
   Bakemon/Vegimon/etc. via `isTriggerSet(200+X)` calls. **The user
   confirmed `getFileCityTopMap` was the pattern for Birdramon-type
   recruits — same hint applies for Coelamon/Tyrannomon-type.**
   Search starting points:
   - `references/DW1-SydPatches/src/Map.cpp` — has the SydPatches
     reimpl of `getFileCityTopMap` at line 1711. Look nearby for a
     similar function for Bottom.
   - `references/DW1-Code/SLUS.asm` — search for functions with
     similar pattern (multiple `jal isTriggerSet` followed by
     branches and screen-id assignments). Start from `0x800D97DC`
     and look for adjacent functions in the same area.

3. **Audit Section_192 common loader (Script 0 lines 9910–10594)**.
   This file-city common loader has many `if trigger(200+X)` gates
   we did NOT patch. Some are simple (line 9918 Betamon `if
   trigger(204) == false`), some are compound (line 9968 Bakemon `if
   trigger(77) == true OR trigger(237) == false`). Need to:
   - Compute BIN offsets for each (use the helper below).
   - For simple gates: 2-byte patch as usual.
   - For compound gates: identify the byte offset of each trigger ID
     within the instruction. Format research needed — bytes around
     line 24830 of Script 163 (Coelamon compound: `f9 00 88 00 2b
     02 18 00 76 02 19 00 57 00 6c 01`) suggest:
     - bytes 0..1: first trigger ID
     - bytes 2..3: combinator/op flags
     - bytes 4..5: pstat ID? (compound only)
     - bytes 6..7: more flags
     - bytes 8..9: branch target
     - …
     Verify by examining a known compound condition's bytes and
     cross-referencing the disassembly.

4. **Quest-driven recruits (~13 of the missing)**. Their visibility
   may not be gated by a single `trigger(200+X)` read at all —
   instead controlled by a quest-progression sequence. For these,
   patching may not even be needed if the quest itself is gated
   behind AP recruit delivery. Defer until specific complaints.

---

## Where things live — quick reference

### Code
- `worlds/digimon_world/data/addresses.py` —
  - `ROM_FIELD_SPAWN_TRIGGER_PATCHES` (script bytecode patches, 29 entries)
  - `ROM_GETTOPCITY_TRIGGER_PATCHES` (C-function patches, 12 entries)
  - All other ROM offset constants
- `worlds/digimon_world/rom.py` — patcher; helpers
  `_write_field_spawn_trigger_patches`,
  `_write_gettopcity_trigger_patches` are called from
  `generate_output`.
- `worlds/digimon_world/client.py` —
  - `LOCATION_RAM_BITS = {**DWAP_CHEST_RAM_BITS, **RECRUIT_RAM_BITS}`
    (poll bit 200+X for cutscene completion)
  - `_make_recruit_deliverer` (writes bit 720+X on AP delivery)
  - `_reconcile_recruits` (defensive per-tick OR-set of bit 720+X)
  - `_enforce_agumon_recruited` (pin bit 203 — Agumon bank NPC)

### References
- DW1 reverse-engineered: `references/DW1-Code/`
  - `memoryMap.txt` — function index
  - `SLUS.asm` — full disassembly (168K lines)
  - `getTriggerOffsets.asm`, `isTriggerSet.asm`, `setTrigger.asm`
- Vanilla `getFileCityTopMap` at RAM `0x800D97DC`. SydPatches
  reimpl: `references/DW1-SydPatches/src/Map.cpp:1711`.
- DW1 script bytecode: `references/digimon_world_randomizer/script/DW1Script.txt`
- Per-recruit BIN-offset catalog: `references/digimon_world_randomizer/info.txt`
  (search for `triggers:` headers — has `MUST CHANGE` lists per recruit)
- DWAP screen names: `references/DWAP/source/DWAP/Helpers.cs`
  (`new DigimonMap(id, screen_name, region)`)

### Debug Lua
- `output/check_triggers.lua` — focused trigger watcher (Betamon,
  Coelamon, etc.) — primary tool for verifying the contract.
- `output/debug_recruit_state.lua` — full recruit/beaten-block
  watcher with named decode.
- `output/check_trigger_base.lua` — one-shot dump of trigger array
  base pointer (verifies `*(0x80134FB8) == 0x801BDED8`).
- `output/dump_bitmap.lua` — obsolete (CITY_BITMAP from removed
  changeMap wrapper).

### Memory (Claude project)
- `dw1_plan_a_revised.md` — **READ FIRST** for recruit-visibility
  context.
- `dw1_psx_mips_gotchas.md` — load-delay slot, alignment rules.
- `dw1_recruitment_paths.md` — not all recruits are fight-triggered.
- `dw1_changemap_wrapper.md` — marked SUPERSEDED; historical only.
- `phase_progress.md` — phase tracking (Phase 5 in progress).

---

## Helpers (for adding new patches)

### Script-bytecode BIN offset

```python
SECTOR_SIZE = 0x930
SECTOR_HEADER = 0x18
USER_DATA = 0x800
SCRIPT_REGION_BASE_SECTOR = 142589
SCRIPT_REGION_BASE_USERDATA_POS = 4

def script_byte_to_flat_bin(script_byte_offset_in_region):
    pos = SCRIPT_REGION_BASE_USERDATA_POS + script_byte_offset_in_region
    sa, pw = divmod(pos, USER_DATA)
    sector = SCRIPT_REGION_BASE_SECTOR + sa
    return sector * SECTOR_SIZE + SECTOR_HEADER + pw

# Per-script bases (script-region byte offset, hex):
SCRIPT_BASES = {
    0: 0x800, 17: 0x11800, 30: 0x1B000, 49: 0x25000,
    131: 0x5C800, 135: 0x5F000, 159: 0x70000, 160: 0x72000,
    162: 0x73000, 163: 0x75800,
    # Add more from `== Script ID N == HEX` headers in DW1Script.txt.
}
```

### SLUS-loaded RAM → flat BIN (for C-function patches)

```python
ANCHOR_RAM = 0x80102E6C  # known: chest patch site
ANCHOR_BIN = 0x14D3E5D4  # verified working
SLUS_RAM_BASE = 0x80010000

def slus_ram_to_bin(ram_addr):
    offset = ram_addr - SLUS_RAM_BASE
    sa, pw = divmod(offset, USER_DATA)
    anchor_offset = ANCHOR_RAM - SLUS_RAM_BASE
    anchor_sa, anchor_pw = divmod(anchor_offset, USER_DATA)
    sector_zero_bin = ANCHOR_BIN - anchor_sa * SECTOR_SIZE - anchor_pw
    return sector_zero_bin + sa * SECTOR_SIZE + pw
```

### Always cross-check

After computing any new BIN offset:
```python
with open("Digimon World (USA).bin", "rb") as f:
    f.seek(bin_offset)
    print(f.read(16).hex())
```
For script-bytecode `if trigger(N) == TRUE then` patches, expect
bytes `<N_LE> 18 00 <branch_LE> 19 00 ...`. For `addiu r4, r0,
<N>` C-code patches, expect bytes `<N_LE> 04 24`.

---

## Key RAM addresses

- `RECRUIT_BLOCK` (8 bytes, 2-byte aligned): `0x801BDFE6`. Bits
  200..263 of trigger array. Read by both wild-spawn (vanilla) and
  city-visibility (vanilla, BUT we've redirected the city reads to
  720+X via ROM patches).
- `BEATEN_BLOCK` (8 bytes): `0x801BE027`. Bits 720..783. Set by
  client recruit deliverer = "AP delivered ``<X> Recruit``". Read
  by city-visibility scripts after our patches.
- `CURRENT_SCREEN`: byte at `0x80134DA8`.
- `ITEMS_RECEIVED_COUNTER`: 3 bytes (magic ``0xA5`` + u16 LE counter)
  at `0x801BDF20..0x801BDF22`. Pre-bank scratch region; outside the
  bank UI display range, the card-vending nibble array, and the
  trigger bit-array. See the comment block on
  ``ITEMS_RECEIVED_COUNTER_ADDR`` in ``client.py`` for the relocation
  history (previously ``0x001BDFA9`` = bank slots 125-127, displayed
  as phantom Giga Hand / Noble Mane in the bank UI; before that
  ``0x001BDFEE`` = trigger 274 clobber zone).
- Vanilla `setTrigger`: RAM `0x801065C0`.
- Vanilla `isTriggerSet`: RAM `0x8010643C`.
- Vanilla `scriptTickChangeMap`: RAM `0x800D8E64`.
- Vanilla `getFileCityTopMap`: RAM `0x800D97DC`.
- Trigger-array base pointer: 32-bit value at `0x80134FB8` →
  `0x801BDED8`. Trigger N's byte = `*(0x80134FB8) + 0xF5 + N/8`,
  bit = `N & 7`.

---

## Behavioral note for resuming Claude

The user is testing seeds frequently. **When asking the user to
test, ALWAYS paste the full unzip + MultiServer + Launcher block**
(see memory `testing_commands.md`). Use the format:

```
tar -xf output\<seed>.zip -C output\
venv\Scripts\python.exe MultiServer.py output\<seed>.zip
venv\Scripts\python.exe Launcher.py "output\<seed>_P1_Player1.apdw1"
```

The user has confirmed Betamon works under Plan A revised. Do NOT
re-investigate the Plan A revised model; trust it. If a missing
recruit misbehaves, the work is to **find its specific gate** —
either via `getFileCityBottomMap` discovery or Section_192 common
loader audit, NOT to rethink the contract.
