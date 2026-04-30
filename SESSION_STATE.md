# Session State — DW1 APWorld

Snapshot taken 2026-04-30 at end of long debugging session. Captures what
works, what doesn't, the bug we're chasing, and the next concrete step.

---

## Overall project state

Branch: `digimon-world-ps1`. Most of Phase 5 polish is in:

- **Working**: chest randomization, recruit-fight detection, item delivery,
  AP location pool (~190 locations), item pool (~250 items including 49
  Recruits + 25 Prosperity Points + bank items + bits), goal logic, dynamic
  city toggle (3-bit recruit model), all 5 QoL options (Fast Drimogemon,
  Easy Monochromon, Skip Intro, Type-Lock Unlocks, Spawn Rate Boost),
  Stat Gain Multiplier option. 151 tests pass.
- **Currently broken**: the changeMap ROM-patch wrapper (see below).
- **Not yet started**: recruit-randomization option toggle in `rules.py`
  (per PLAN.md pending logic rework section).

Recent commits visible from `git log --oneline -10` are pre-changeMap-wrapper.
Everything from Stat Gain Multiplier onwards is still uncommitted on the
working tree.

The seed YAML at [Players/Digimon World.yaml](Players/Digimon%20World.yaml)
has `stat_gain_multiplier: 5` and a plando that places Palmon Recruit at
"Chest: Dragon Eye Lake".

---

## The bug we're chasing

**Symptom**: after defeating Betamon and Coelamon (without receiving their
AP Recruit items), they appear in city. The AP-delivered set is correct
(only Agumon force-set + Drimogemon Recruit which was actually delivered),
but the recruit-bit block (`0x001BDFE6`) flickers between `{Agumon}`
(correct, set by client toggle) and `{Agumon, Betamon, Coelamon}` (beaten
state, set by changeMap wrapper).

**Architecture being attempted**: a ROM-patch wrapper installed at the
SydPatches-known scriptTickChangeMap call site (vanilla RAM `0x80105C2C`,
JAL target `0x800D8E64`). The wrapper:

1. Reads `$a0` (assumed to be destination map id).
2. Looks it up in a 32-byte CITY_SCREENS bitmap.
3. Picks source = AP_BITS_MIRROR (in city) or PERM_BEATEN (in field).
4. Copies 8 bytes from source to recruit block.
5. Tail-calls vanilla scriptTickChangeMap.

This SHOULD set the right bits before vanilla loads the new map's
scripts. No race window. **But the wrapper appears to treat city screens
as field**, hence picks PERM_BEATEN and writes beaten state to recruit
block.

---

## Bisect history (what we tried and what each told us)

All bisect builds exist as `output/AP_*.zip`. The relevant addresses /
constants live in
[worlds/digimon_world/data/addresses.py](worlds/digimon_world/data/addresses.py)
under the "changeMap wrapper" section.

| Step | What | Result | What we learned |
|---|---|---|---|
| Probe 1 | `event.onmemoryread` hook on recruit + beaten blocks | PCs at `0x80091Cxx`-`0x80091Fxx`, `0x800Cxxxx`, `0x800Bxxxx`, NEVER at `0x801064xx` | `isTriggerSet` is **NOT** the read path — script bytecode interpreter and game scripts inline the bit checks. So we can't wrap `isTriggerSet`. |
| Probe 2 | Disassembly of vanilla call at `0x80105C2C` | `JAL 0x800D8E64`. Function has standard MIPS prologue. | Vanilla's scriptTickChangeMap is at `0x800D8E64`, takes `$a0`, `$a1`, `$a2` args. |
| Step A — minimal | wrapper = just `j 0x800D8E64; nop` | Game boots normally | JAL redirect works; minimal wrapper is fine. |
| Step B — full overwrite (LW/SW) | LW src, SW recruit, no city detection | Game hangs at city load | Initial assumption: clobbering vanilla intro state. |
| Step C — merge (LW/SW) with masks | preserve unowned bits in bytes 0/7 | Hangs | Same — assumed write content was the issue. |
| Step D — identity (LW/SW) | LW recruit, SW back unchanged | Hangs | False isolation: SHOULD have been a no-op but still hung. |
| **KEY INSIGHT** | LW/SW require 4-byte alignment. Recruit block at `0x001BDFE6` is 2-byte aligned but **NOT 4-byte aligned** (`0xE6 mod 4 == 2`). LW/SW raises Address Error → CPU hangs. | This is why Steps B/C/D all hung. |
| Step E — identity (LW/SW + NOPs) | added load-delay NOPs | Still hangs | NOPs alone aren't enough; alignment is the deeper issue. |
| Step F — identity (LHU/SH + NOPs) | LHU/SH require only 2-byte alignment | **Game boots** | Confirmed alignment was the bug. |
| Step G — full overwrite from AP_MIRROR (LHU/SH + NOPs, no city detection) | always writes AP_MIRROR contents to recruit block | Game boots | Vanilla doesn't actively use bits 200-202/259-263 during intro; we don't need merge logic. |
| **Step H — current** — full wrapper with bitmap lookup + source select | bitmap[$a0 >> 3] >> ($a0 & 7) & 1 → in_city, then source select | Game boots, but Betamon/Coelamon appear in city → wrapper picking wrong source | $a0 may not be the destination map id. |

Two MIPS gotchas burned into memory now:
1. **PSX R3000 has a 1-instruction load delay slot**: `LW $rt; X $rt` — X
   sees the OLD value. Need a NOP or unrelated instruction between.
2. **LW/SW require 4-byte alignment**; LH/LHU/SH require 2-byte. The
   recruit block at `0x001BDFE6` is 2-byte aligned but not 4-byte. **Use
   LHU/SH for the recruit block, LW/SW for AP_MIRROR/PERM_BEATEN scratches
   (they're at 0x001BDFF0/0x001BDFF8, both 4-byte aligned).**

---

## Current focus

We just installed an **instrumented wrapper** (in the same address layout
as the broken full wrapper) that writes `$a0` and `$a1` to a debug scratch
at `0x800958A0` / `0x800958A4` on every wrapper invocation.

The `output/debug_recruit_state.lua` was extended to read those scratch
addresses and print them as `wrapper $a0=0x...  $a1=0x...` on each state
change.

**Next test seed**:
[output/AP_29198163804748226946.zip](output/AP_29198163804748226946.zip)

```cmd
tar -xf output\AP_29198163804748226946.zip -C output\
venv\Scripts\python.exe MultiServer.py output\AP_29198163804748226946.zip
venv\Scripts\python.exe Launcher.py "output\AP_29198163804748226946_P1_Player1.apdw1"
```

User is asked to:
1. Reload `output/debug_recruit_state.lua` in BizHawk.
2. Walk transitions (city sub-screen → city sub-screen, field → city, etc.).
3. Paste log lines that include `wrapper $a0=` annotation.

**What we're testing for**:

| Pattern in $a0 | Diagnosis |
|---|---|
| `$a0` matches destination (entering 0xB5 → `$a0` = 0xB5) | Wrapper input is correct, bug is elsewhere (re-examine MIPS encoding, bitmap content). |
| `$a0` matches source (entering 0xB5 from 0x6D → `$a0` = 0x6D) | Switch wrapper to use `$a1` (likely the destination), or read CURRENT_SCREEN_ADDR after vanilla updates it. |
| `$a0` huge / sign-extended garbage | Different problem; the call site loads halfword + sra; possibly negative values cause bitmap index overflow. |
| `$a0` always 0 or sentinel | Function called for non-screen-change reasons; our wrapper hooks the wrong call site. |

---

## Key addresses (frozen 2026-04-30)

- `RECRUIT_BLOCK` (8 bytes, 2-byte aligned, **NOT 4-byte aligned**):
  RAM `0x801BDFE6`. Holds bits 200..263 in trigger array.
- `AP_BITS_MIRROR` (8 bytes, 4-byte aligned): RAM `0x801BDFF0`. Client
  writes this each tick = AP-delivered Recruit set OR Agumon force-bit.
- `PERM_BEATEN` (8 bytes, 4-byte aligned): RAM `0x801BDFF8`. Client writes
  this each tick = beaten block | Agumon force-bit.
- `BEATEN_BLOCK` (8 bytes): RAM `0x801BE027`. Set by setTrigger wrapper
  when player wins a wild fight (bit 720+X).
- `CURRENT_SCREEN`: byte at RAM `0x80134DA8`. The player's current map id.
- `ITEMS_RECEIVED_COUNTER`: u16 LE at RAM `0x801BDFEE`.
- `CITY_BITMAP`: 32 bytes at RAM `0x80095880` (BIN `0x14CC0D08`). Bit
  `id mod 8` of byte `id / 8` is set iff `id` is a city screen. Source set
  at [data/addresses.py](worlds/digimon_world/data/addresses.py)
  `_CITY_SCREENS_FOR_BITMAP`.
- `WRAPPER_DEBUG_SCRATCH`: 8 bytes at RAM `0x800958A0`. Wrapper writes
  `$a0` to `[A0]`, `$a1` to `[A4]` on every entry (instrumented build only).
- `ROM_CHANGEMAP_WRAPPER_RAM`: `0x80095800` (Cave6 free-space). 128 bytes
  allocated. JAL redirect at `0x80105C2C` points here.
- Vanilla scriptTickChangeMap entry: RAM `0x800D8E64`. Wrapper tail-calls
  this via `J 0x800D8E64`.

Cave6 wrapper layout in RAM:
```
0x800957C0..DC  chest wrapper             (28 bytes, established)
0x800957DC..FC  setTrigger wrapper        (32 bytes, established)
0x800957FC..00  4-byte gap (sector boundary fall-out)
0x80095800..7F  changeMap wrapper         (128 bytes — current bisect)
0x80095880..9F  city bitmap               (32 bytes)
0x800958A0..A7  wrapper debug scratch     (8 bytes — instrumented build)
```

---

## Files modified (uncommitted from `git log -1` perspective)

- [worlds/digimon_world/data/addresses.py](worlds/digimon_world/data/addresses.py) — ChangeMap wrapper bytes, CITY_BITMAP, RAM_PERMANENT_BEATEN_SCRATCH_*, all the QoL constants, stat-multiplier addresses
- [worlds/digimon_world/rom.py](worlds/digimon_world/rom.py) — `_write_changemap_wrapper_tokens`, all QoL writers
- [worlds/digimon_world/client.py](worlds/digimon_world/client.py) — permanent-beaten scratch maintenance, Agumon-force-set in AP_MIRROR, all QoL enforcers, slot_data flags
- [worlds/digimon_world/world.py](worlds/digimon_world/world.py) — `fill_slot_data` extended with QoL flags
- [worlds/digimon_world/options.py](worlds/digimon_world/options.py) — 5 QoL options + `StatGainMultiplier`
- [worlds/digimon_world/test/test_patcher.py](worlds/digimon_world/test/test_patcher.py) — TestQoL classes; `TestChangeMapWrapper` is `@unittest.skip`'d during bisect (re-enable once fix lands)
- [PLAN.md](PLAN.md) — pending-logic-rework note for `type_lock_unlocks` × recruit-randomization
- [Players/Digimon World.yaml](Players/Digimon%20World.yaml) — `stat_gain_multiplier: 5` + Palmon plando

Test count: 151 passing, 4 skipped (TestChangeMapWrapper × 4 tests, all
disabled during bisect).

---

## When session resumes

Read this file first. Then ask the user for the log output of the
instrumented seed (`output/AP_29198163804748226946`). The `wrapper $a0=`
field tells us the next step.

If `$a0` is the source not the destination, the fix is one MIPS instruction
in the wrapper: change `srl $t0, $a0, 3` and `andi $t1, $a0, 7` to use `$a1`
instead. (Or read `CURRENT_SCREEN_ADDR` directly via `LBU` from the wrapper,
but the disassembly showed CURRENT_SCREEN may not yet be updated when the
wrapper fires.)

Once the fix is in:

1. Remove the instrumentation (the 3 `lui/sw/sw` lines at the top of the
   wrapper) and recompute the wrapper to 32-instruction = 128 bytes.
2. Remove the wrapper-debug-scratch lines from `debug_recruit_state.lua`.
3. Re-enable `TestChangeMapWrapper` in `test_patcher.py` (remove the
   `@unittest.skip` decorator).
4. Live-verify: defeat 2 recruits, walk to city, confirm only AP-delivered
   ones appear, no flickering.
5. Save key learnings as memory entries (PSX MIPS gotchas; the wrapper
   architecture).
6. Commit and offer to push.
