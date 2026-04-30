# Session State — DW1 APWorld

Snapshot 2026-04-30. The "recruit visibility" debugging arc is closed.
Plan A revised is the working model — user-validated for Betamon and
rolled out to ~24 unique recruits. Captures the working contract,
where things live, and what's still pending.

---

## Overall project state

Branch: `digimon-world-ps1`. Phase 5 polish is essentially in.

- **Working**: chest randomization, recruit-fight detection, item
  delivery, AP location pool (~190 locations), item pool (~250 items
  including 49 Recruits + 25 Prosperity Points + bank items + bits),
  goal logic, all 5 QoL options (Fast Drimogemon, Easy Monochromon,
  Skip Intro, Type-Lock Unlocks, Spawn Rate Boost), Stat Gain
  Multiplier option. **147 tests pass**, 4 skipped (the
  `TestChangeMapWrapper` family is now obsolete and can be deleted).
- **Working — recruit visibility (Plan A revised)**: cutscene
  completion sets bit 200+X (vanilla); AP delivery sets bit 720+X
  (client deliverer); per-Digimon ROM patches make the city
  visibility scripts read trigger 720+X instead of 200+X. See
  [`docs/recruit_visibility.md`](docs/recruit_visibility.md) and
  [`worlds/digimon_world/data/addresses.py`](worlds/digimon_world/data/addresses.py)
  → `ROM_FIELD_SPAWN_TRIGGER_PATCHES` for the patch table.
- **Not yet patched**: ~26 recruits don't have a script-bytecode gate
  matching our search pattern — Devimon, Airdramon, Tyrannomon,
  Seadramon, Numemon, MetalGreymon, Mamemon, Monzaemon, Angemon,
  Birdramon, Garurumon, SkullGreymon, MetalMamemon, Vademon, Unimon,
  Ogremon, Shellmon, Andromon, Leomon, Coelamon, Mojyamon, Nanimon,
  Megadramon, Piximon, Digitamamon, Ninjamon. They're either
  quest-driven or use a compound-condition gate we haven't located.
  Awaiting user test reports on which specifically misbehave.
- **Not yet started**: recruit-randomization option toggle in
  `rules.py` (per PLAN.md pending logic rework section).

The seed YAML at [Players/Digimon World.yaml](Players/Digimon%20World.yaml)
has `stat_gain_multiplier: 5` and a plando placing Palmon Recruit at
"Chest: Dragon Eye Lake".

---

## The contract that works (Plan A revised)

**Bit semantics — split per Digimon X**:

- Bit 200+X = "player completed recruit cutscene" (vanilla owns it).
- Bit 720+X = "AP delivered ``<X> Recruit``" (client owns it).

**Behavior table** (verified for Betamon, expected for all patched):

| Event | 200+X | 720+X | Wild | City |
|---|---|---|---|---|
| Fresh save | 0 | 0 | YES | NO |
| After cutscene | 1 (vanilla) | 0 | NO | NO |
| After AP delivery | 1 | 1 (client) | NO | YES |

**Why it works**: vanilla DW1 reuses one bit (200+X) for two
semantics — "wild spawn gate" AND "city visibility gate". Setting
that bit hides the wild Digimon AND shows the city one,
simultaneously. AP wants those decoupled. The split is achieved by:

1. Letting vanilla set bit 200+X normally (no `setTrigger` redirect).
   Wild-spawn check still reads 200+X → wild correctly hides after
   cutscene.
2. Routing AP-Recruit deliveries to bit 720+X (a previously-unused
   trigger range).
3. ROM-patching each per-Digimon city-visibility script bytecode to
   read trigger 720+X instead of 200+X. After patching, city only
   shows X when AP has delivered.

**Patch site shape**: each city visibility gate is a 12-byte script
instruction laid out as
`<trig_LE 2B> 18 00 <branch_target_LE 2B> 19 00 ?? ?? ?? ??`. We
rewrite only the first 2 bytes (trigger ID) from `200+X` LE to
`720+X` LE. The patcher uses a flat-BIN write through
`apply_tokens`. Found 29 such sites across Scripts 0, 17, 30, 49,
131, 135, 159, 162, 163.

---

## Architecture changes from previous attempts

What we **removed** during this arc (do not resurrect without a very
specific reason — they conflict with Plan A revised):

- **`setTrigger` wrapper** (was at vanilla `0x801065C0`, redirected
  writes 203..258 → 723..778). Disabling restored vanilla cutscene
  semantics (bit 200+X gets set legitimately). Wrapper bytes still
  live in `addresses.py:ROM_SETTRIGGER_WRAPPER_BYTES` for reference,
  but `_write_settrigger_wrapper_tokens` is no longer called from
  `generate_output`.
- **`changeMap` wrapper** (was at Cave6 `0x80095800`, copied
  AP_BITS_MIRROR / PERM_BEATEN to recruit-block on every screen
  transition). Disabling let vanilla manage the recruit-block. The
  wrapper bytes still live in
  `addresses.py:ROM_CHANGEMAP_WRAPPER_BYTES` but are not installed.
  The `TestChangeMapWrapper` test class in
  `test/test_patcher.py` is `@unittest.skip`'d and can be deleted.
- **Per-tick recruit-block toggle** in
  `client.py:_reconcile_recruits` was rewritten. It no longer touches
  the recruit-block (vanilla owns it now); it simply OR-pins bit
  720+X for any AP-delivered recruit (defensive).
- **`isTriggerSet` wrapper** experiment (briefly tried to redirect
  reads of 200+X to AP-mirror reads). Removed entirely — the
  approach broke field-spawn suppression because the same function
  serves both the wild-spawn check and city-variant selectors.
  `addresses.py:ROM_ISTRIGGERSET_*` constants remain defined but
  unused.

What we **kept**:

- **Chest-pickup `giveItem` wrapper** (still installed; Cave6
  `0x800957C0`). Independent of the recruit work.
- **Chest sentinel item slot** at item ID 83 ("Electo ring") → "AP
  ITEM" entry. Independent of the recruit work.
- **`_enforce_agumon_recruited`** per-tick pin of bit 203 (Agumon's
  bank-NPC visibility). Defensive; cheap.
- **PP-calc patch**, **softlock fixes** (Whamon, Drimogemon,
  Ogremon, Nanimon, Toy Town), **chest item table**.
- **All 5 QoL ROM patches** + Stat Gain Multiplier RAM enforcer.

---

## Where to find things

### Code

- **Patch table** for recruit-visibility ROM rewrites:
  [`worlds/digimon_world/data/addresses.py`](worlds/digimon_world/data/addresses.py)
  → `ROM_FIELD_SPAWN_TRIGGER_PATCHES`.
- **Patcher integration**:
  [`worlds/digimon_world/rom.py`](worlds/digimon_world/rom.py)
  → `_write_field_spawn_trigger_patches`, called from
  `generate_output`.
- **Client recruit deliverer** (writes bit 720+X on AP delivery):
  [`worlds/digimon_world/client.py`](worlds/digimon_world/client.py)
  → `_make_recruit_deliverer`.
- **Client location detection** (polls bit 200+X for cutscene
  completion):
  [`worlds/digimon_world/client.py`](worlds/digimon_world/client.py)
  → `_check_locations` reading `LOCATION_RAM_BITS` =
  `RECRUIT_RAM_BITS`.
- **Defensive 720+X enforcement** per tick:
  [`worlds/digimon_world/client.py`](worlds/digimon_world/client.py)
  → `_reconcile_recruits`.

### References

- DW1 reverse-engineered code: `references/DW1-Code/` (memoryMap,
  per-function `.asm` decomps, full SLUS disassembly).
- DW1 script bytecode dump:
  `references/digimon_world_randomizer/script/DW1Script.txt`.
- Standalone randomizer's per-recruit BIN-offset catalog:
  `references/digimon_world_randomizer/info.txt` (search for
  `triggers:` headers).
- DWAP (existing C# AP world):
  `references/DWAP/source/DWAP/Helpers.cs` for screen-id → name
  mappings (`new DigimonMap(...)`).

### Debug tools

- `output/debug_recruit_state.lua` — recruit-block / beaten-block
  watcher with named-decode of which Digimon's bits are set.
- `output/check_triggers.lua` — focused watcher for specific trigger
  IDs (200+X / 720+X). Useful for verifying the contract holds for
  any recruit.
- `output/check_trigger_base.lua` — one-shot dump of the trigger
  array base pointer (verifies `*(0x80134FB8) == 0x801BDED8`).
- `output/dump_bitmap.lua` — one-shot dump of the (now-unused)
  CITY_BITMAP that the obsolete changeMap wrapper used.

### BIN offset math

For converting script-byte offsets to flat-BIN offsets (needed when
adding a new patch site):

```python
SECTOR_SIZE = 0x930
SECTOR_HEADER = 0x18
USER_DATA = 0x800
SCRIPT_REGION_BASE_SECTOR = 142589
SCRIPT_REGION_BASE_USERDATA_POS = 4

def script_byte_to_flat_bin(script_byte_offset):
    pos = SCRIPT_REGION_BASE_USERDATA_POS + script_byte_offset
    sa, pw = divmod(pos, USER_DATA)
    sector = SCRIPT_REGION_BASE_SECTOR + sa
    return sector * SECTOR_SIZE + SECTOR_HEADER + pw

# Per-script base = script-region byte offset, from
# `== Script ID N == HEX` headers in DW1Script.txt (HEX is hex):
SCRIPT_BASES = {
    0: 0x800, 17: 0x11800, 30: 0x1B000, 49: 0x25000,
    131: 0x5C800, 135: 0x5F000, 159: 0x70000, 160: 0x72000,
    162: 0x73000, 163: 0x75800,
}
```

Always cross-check by reading the source BIN at the computed offset
— the bytes should start with `<trigger_id_LE> 18 00` for an
`if trigger(N) == TRUE` pattern.

---

## Key RAM addresses

- `RECRUIT_BLOCK` (8 bytes, 2-byte aligned): RAM `0x801BDFE6`. Bits
  200..263 of vanilla's trigger array. Read by wild-spawn checks
  (vanilla) and city-visibility checks (vanilla pre-patch / AP-mirror
  in patched build).
- `BEATEN_BLOCK` (8 bytes): RAM `0x801BE027`. Bits 720..783. Set by
  the client recruit deliverer (= "AP delivered ``<X> Recruit``").
  Read by city-visibility scripts after our ROM patch.
- `CURRENT_SCREEN`: byte at RAM `0x80134DA8`.
- `ITEMS_RECEIVED_COUNTER`: u16 LE at RAM `0x801BDFEE`.
- `AP_BITS_MIRROR` (8 bytes, 4-byte aligned): RAM `0x801BDFF0`. Was
  used by the obsolete changeMap wrapper; no longer maintained by
  the per-tick toggle.
- `PERM_BEATEN_SCRATCH` (8 bytes, 4-byte aligned): RAM `0x801BDFF8`.
  Same — obsolete.
- Vanilla `setTrigger` entry: RAM `0x801065C0`.
- Vanilla `isTriggerSet`: RAM `0x8010643C`.
- Vanilla `scriptTickChangeMap`: RAM `0x800D8E64`.
- Vanilla trigger-array base pointer: 32-bit value at RAM
  `0x80134FB8`. Dereferences to `0x801BDED8`. Trigger N's byte =
  `*(0x80134FB8) + 0xF5 + N/8`, bit = `N & 7`.

---

## Pending — find the missing 26 recruits

The current 29-entry patch table covers ~24 unique recruits. The
remaining recruits don't have a `setScript A B; ... if trigger(200+X)
== TRUE then SKIP` pattern at their wild encounter screen — they're
either quest-driven (Whamon-via-Ogremon3, Vademon postgame, etc.)
or their city-visibility check uses a different bytecode pattern
(possibly the compound-condition form we saw at File City Bottom
loader entries — script byte 9918, 10190, etc.).

Approach when revisiting:

1. User reports which specific recruit misbehaves (visible in city
   without AP delivery, OR not visible despite AP delivery).
2. Search `references/digimon_world_randomizer/script/DW1Script.txt`
   for `trigger(200+X)` references for that Digimon. Some patterns:
   - Single-trigger if-then (12 bytes): we already handle these.
   - Compound `if trigger(A) == false AND/OR trigger(B) ...`: our
     patch table doesn't yet handle these. The trigger ID still
     lives at the start, but the surrounding bytes differ — verify
     before patching.
   - File-city-bottom loader entries (Section_192 lines 9918,
     10190): these are the "common loader" gates. We didn't patch
     these, but they may also need redirecting.
3. Compute the BIN offset and add to
   `ROM_FIELD_SPAWN_TRIGGER_PATCHES`.

For Coelamon specifically: he's known to have a recruit cutscene at
script-byte 1508 of some script (per `info.txt:791`). The standalone
randomizer marks several Coelamon offsets as NO TOUCH (00120, 00202,
00586, 01508, 01386). Likely one of the 0058X-range entries is the
city visibility — needs investigation.

---

## Memory entries (for future Claude sessions)

Stored in `~/.claude/projects/c--opt-dev-AP-ArchipelagoDW/memory/`:

- **`dw1_plan_a_revised.md`** — The working model. Read first when
  resuming recruit-visibility work.
- **`dw1_psx_mips_gotchas.md`** — Load-delay slot, alignment rules.
  Still relevant if writing new ROM-patch wrappers.
- **`dw1_recruitment_paths.md`** — Not all recruits are
  fight-triggered; some are dialog/quest. Treat 720+X as "AP
  delivered" not specifically "beaten".
- **`dw1_changemap_wrapper.md`** — Marked superseded; kept for
  historical context only.
- **`dw1_chest_sentinel_wipe.md`** — Chest pickup quirk; still
  relevant for the chest-wrapper architecture.
- **`dw1_item_table_layout.md`** — ITEM_PARA layout (128 entries ×
  32 bytes).
- **`testing_commands.md`** — Standard unzip + MultiServer + Launcher
  test sequence.
- **`phase_progress.md`** — Phase tracking.
