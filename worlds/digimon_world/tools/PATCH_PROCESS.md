# DW1 Patch-Test Process

Standing procedure to design, test and confirm a ROM patch with **one** confirming .bin
build, iterating everything else in seconds. Proven end-to-end 2026-08-20 on the Recycle
Shop PoC (results in [NEXT_PATCH_TEST_PLAN.md](NEXT_PATCH_TEST_PLAN.md); worked example
spec builder in `work\dw1_re\patches\build_recycle_poc_spec.py`). Companion to
[DECOMP_PROCESS.md](DECOMP_PROCESS.md) (which produces the verified understanding patches
are designed from) and [TOOLING.md](TOOLING.md) (the lab itself). Follow the phrasing
convention in [AGENT_VOCABULARY.md](AGENT_VOCABULARY.md).

**Why this exists**: an AP ROM patch is just bytes that land in RAM at load time. The same
bytes applied as live-RAM pokes over a savestate reproduce the effect in seconds — so all
iteration happens pre-ISO, and the .bin build is a one-shot confirmation, not a debug loop.
On the PoC, live-RAM iteration 1 disproved a design-breaking wrong assumption (a function
believed shop-exclusive was the generic money-shop builder) that would previously have
burned several build+hand-test cycles.

## The tool: one spec drives every net

`worlds\digimon_world\tools\dw1_apply_patch.py`. Spec = JSON:

```json
{ "name": "my-patch",
  "patches": [
    { "ram": "0x80095F40", "words": [ 2406222724, ... ], "note": "wrapper code" },
    { "ram": "0x801279DC", "hex": "0102...",             "note": "data blob"    },
    { "bin": "0x14B8B698", "hex": "dd00",                "note": "raw bin"      } ] }
```

`ram` = KSEG0 or physical main-RAM address (SLUS-image-resident for ISO mode); `bin` =
flat .bin offset (addresses.py convention; ISO mode only). `words` = u32 list (LE-encoded
— convenient for MIPS), `hex` = byte string. Modes:

| Mode | What it does |
| --- | --- |
| `show spec.json` | Resolve every entry (RAM, phys, bin offset) without writing. |
| `apply spec.json` | Poke live PCSX-Redux RAM over REST. |
| `verify spec.json` | Read live RAM back, diff against the spec (works equally on poked RAM and on a freshly booted patched ISO). |
| `to-iso spec.json src.bin dst.bin` | Patched copy: sector-aware Mode2/2352 writes + EDC/ECC diff-recalc via `data/edc.py`. |

Author specs with a **builder script** in `work\dw1_re\patches\` (gitignored): a small
Python file with a mini MIPS assembler (copy the helpers from
`build_recycle_poc_spec.py`) that loads `data/addresses.py` + `data/edc.py` through a
synthetic `dw1data` package (NEVER `import worlds....` directly — that triggers the
Archipelago world auto-discovery). Reuse shipped byte-builders from addresses.py
(`build_ap_item_para_entry`, wrapper constants, ...) instead of re-encoding them.

## Pipeline

### Step 1 — Know the code first

Designing patches from guesswork is the failure mode this whole process replaces. The
target's code must be known exactly, from one of two sources:

- **dw_decomp** (since 2026-08-28, the usual case): resolve the target with
  `python worlds\digimon_world\tools\dw1_decomp_xref.py --lookup 0x<ADDR>`. If it is in C in
  `references\dw_decomp\`, that C is byte-matching — read it, cite `file:line` in the design,
  and treat it as the "verified understanding" this step used to demand. Still capture the
  vanilla words of every site you redirect (net 2 checks them).
- **A VERIFIED unit of our own** ([DECOMP_PROCESS.md](DECOMP_PROCESS.md)) when the target is an
  `ASM stub` upstream, or when the design hinges on *runtime* facts a static decomp cannot
  give (which values actually flow through the site, what a real save exercises).

### Step 2 — Design, and model the design in C

Write the patched behavior as a small C function next to the unit's verified C (see
`build_shop_runtime_list_ap.c`), mirroring the intended MIPS 1:1. Design rules for the
MIPS itself:

- Leaf wrappers: caller-saved regs only (`at, v0, a*, t*`); never clobber `s*`/`ra`.
- **R3000 load-delay slot**: the instruction after any `lw/lbu/lhu` must not consume the
  loaded register.
- Branch/jump delay slots are executed; branch offset = `target_index - (branch_index+1)`.
- New code goes in Cave6 free space — check the current layout comment in
  `data/addresses.py` ("Cave6 layout") and claim your range there when the patch ships.
- Redirecting a callsite: verify the vanilla word first (peek it; e.g. a `jal X` word is
  `0x0C000000 | ((X >> 2) & 0x3FFFFFF)`) and record it in the spec note.
- Prefer gates on hard state (current screen u8 at gp-0x6D84 = `0x80134DA8`) over
  fingerprints like entry counts — the PoC found a shipped client fingerprint
  (entry_count==7) that can clobber vanilla shops.

### Step 3 — Net 1: replay the C model

Feed the unit's captured vectors' `pre` states through the patched C model and compare
against an **independent** Python computation of the design (see `verify_ap.py` in the
recycle unit). Sub-second; catches logic slips (flag inversions, off-by-ones) before any
emulator time.

### Step 4 — Net 2: live RAM over a savestate

1. Launch the lab, ideally with evidence watchpoints armed
   (`dw1_redux_launch.ps1 -Script dw1_redux_watch.lua` + `dw1_watch_config.lua`).
2. Load the relevant savestate (see DECOMP_PROCESS.md for the savestate inventory), then
   `dw1_apply_patch.py apply` — **a savestate load restores vanilla RAM, so re-apply
   after every load**.
3. Drive the event with `dw1_press` + screenshots; verify with peeks of the output state
   and the watch log. Iterate here — this is the loop.
4. **Negative tests**: run the surrounding features that must stay vanilla (on the PoC:
   the other money shops under the same patch). A patch is not done when it works; it is
   done when everything else still works.

### Step 5 — Net 3: one confirming build

```
python worlds\digimon_world\tools\dw1_apply_patch.py to-iso <spec> "Digimon World (USA).bin" work\dw1_re\<name>.bin
```

Boot it (`dw1_redux_launch.ps1 -Iso <abs path>`), wait past the boot, then
`dw1_apply_patch.py verify` — every entry OK proves the sector-aware translation and EDC
recalc delivered the exact tested bytes through a natural disc load. (Savestates are
useless on the built ISO — they restore vanilla RAM over the patched code.)

### Step 6 — Record

- NOTES.md in the unit's decomp dir (design, iterations, what each net caught).
- If the patch is heading to production: constants into `data/addresses.py` (+ Cave6
  layout comment), tokens into `rom.py`, and remove any client-side mechanism it
  replaces. Update project memory.

## Session recipes and gotchas (hard-won on the PoC)

- `dw1_redux_api.py ping` exits 0 even when the connection fails — wait for the literal
  `pong` output, never the exit code.
- Launch scripts and ISOs with **absolute paths**: background shells do not keep the repo
  CWD, and the launcher fails silently fast (check the task output on any "REST never
  came up").
- One emulator session at a time; one controller of that session; close with
  `dw1_redux_api.py quit` (process is `pcsx-redux.main`).
- Menu navigation that works: single `dw1_press({'CROSS'}, 40)` per step, ~2.5-3 s apart,
  screenshot between steps when unsure. For repeated event captures, reload the savestate
  each cycle instead of trying to back out through menus (a stray press exits the whole
  flow and desyncs the choreography).
- The watch-log `value` column is the byte BEFORE the write lands.
- VRAM screenshots show noise during FMV/MDEC playback — cosmetic, the game is fine.
- Money/stat/trigger pokes: addresses and vanilla-vs-AP caveats in DECOMP_PROCESS.md
  ("the lab runs the VANILLA ISO").
