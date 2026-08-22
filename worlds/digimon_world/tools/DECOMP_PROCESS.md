# DW1 Function Decomp — Standard Process

Standardized pipeline to decompile one DW1 (SLUS-01032) function into verified, portable C.
Established 2026-08-20 with the trigger-family pilot (`isTriggerSet` / `getTriggerOffsets` /
`setTrigger` / `unsetTrigger`). Infrastructure: see [TOOLING.md](TOOLING.md). When the goal of
a decomp is a ROM patch, the follow-on procedure is [PATCH_PROCESS.md](PATCH_PROCESS.md).

**Verification bar**: a function is DONE when its C reimplementation replays 100% of the call
vectors captured from the real game (emulator differential testing). Reading-level Ghidra
pseudo-C is a *draft*, never a deliverable.

**When the game state needed for capture is unavailable**, the unit is still worth doing: write
and cross-check the model, record it as `PROVISIONAL` in the ledger, and add a row to
[SAVESTATE_REQUESTS.md](SAVESTATE_REQUESTS.md) naming the state that would unblock it. A
PROVISIONAL model is a draft with the reasoning banked, not a result — never build a shipped
patch on one without saying so out loud.

**Repo hygiene (hard rule)**: decompiled C, vectors, and every game-derived artifact live under
`work\dw1_re\decomp\` (gitignored — the fork is public). Only process tooling and docs are
committed.

## Pipeline

### Step 1 — Locate and scope the unit

- Resolve name/address in `work\dw1_re\slus_symbols.txt` (from `references/DW1-Code/memoryMap.txt`)
  or the Ghidra project. Only SLUS functions (`0x80090800..0x80135000`) are in the project today;
  overlay functions need the overlay imported first (not yet standardized).
- The decomp unit is the function **plus its non-library callee closure**: follow `refs.txt`
  CALLEES recursively; game callees (FUN_* or Syd-named) join the unit or must already be done;
  PsyQ callees (memcpy, rand, …) are stubbed with libc equivalents in the C.

### Step 2 — Export the static bundle

```powershell
powershell -File worlds\digimon_world\tools\dw1_ghidra.ps1 -ReadOnly -Script DW1ExportFunc.java <HEXADDR> work\dw1_re\decomp\<name>
```

Produces `decomp.c` (Ghidra pseudo-C + Syd's signature comment), `listing.asm`, `refs.txt`
(callers / callees / data refs).

`DW1ExportFunc.java` accepts **several `<hexAddr> <outDir>` pairs in one invocation** — always
use that for a multi-function unit. A headless startup costs far more than an export (10
functions in one run take about as long as one), and it sidesteps the serialization rule below
entirely. **Serialize Ghidra runs** — the project database is single-writer; never run two
headless invocations concurrently.

`DW1FunctionStats.java <out.tsv>` writes a census of every function (address, name, size,
instruction count, caller/callee counts). Use it to size an effort or pick targets by call
frequency — the most-called functions are usually the highest-leverage units.

### Step 3 — Understand and cross-check

- Read `decomp.c` against `listing.asm`. Identify data dependencies from `refs.txt` DATA REFS.
- Cross-check semantics against `references/DW1-Code/` (Syd's C-style transcriptions), the
  project's own knowledge (`data/addresses.py`, memory notes), and live RAM
  (`work\dw1_re\redux_smoke_ram.bin` or a fresh REST dump) for pointer/table values.
- Record any *structural insight* (e.g. "trigger array = `*(0x80134FB8)+0xF5`, not a constant")
  in the function's `NOTES.md` — these upgrade the project's memory map.

### Step 4 — Capture call vectors from the real game

- Write `work\dw1_re\dw1_vector_config.lua` describing the unit's functions: entry args are
  always captured; declare `pre`/`post` memory regions (inputs the function reads / outputs it
  writes) and `deref` specs for pointer out-params (see header of
  [dw1_redux_vectors.lua](dw1_redux_vectors.lua)).
- A region addresses memory in one of three ways: `addr` (static), `reg` (the value of that
  register at entry) or `ptr` (the u32 stored at that static address, read when the region is
  dumped). **`reg` and `ptr` regions are what make pointer-walking functions verifiable** — a
  script PC, a save-block base or a runtime table moves at runtime, so a static `addr` cannot
  reach it. The JSON key is the *resolved* address, and the replay harness reloads each region
  there, so the model sees exactly the bytes the real function saw.
- Give a hot function a `max` so it cannot eat the whole `max_total` budget. Without it a
  function with 100 callers will starve the rest of the unit within seconds.
- **Size the windows generously and check the skip count afterwards.** A window that is too
  short does not fail — it silently produces `skip`s, which is how the `scriptvm` run 1 missed
  every pstat index above 0xA6 (they reach 254). If a function reports skips, widen and recapture
  before declaring the unit done.
- Launch: `powershell -File worlds\digimon_world\tools\dw1_redux_launch.ps1 -Script worlds\digimon_world\tools\dw1_redux_vectors.lua`
- Progress: `python dw1_redux_api.py lua "return PCSX.WebServer.Handlers.vecstat()"`; the
  `autoplay = true` masher (START/X) gets from title into the opening. When enough vectors
  accumulated (aim ≥100 spread over the unit; niche functions may need targeted play or a
  savestate), quit via `python dw1_redux_api.py quit`. Result: `work\dw1_re\vectors.jsonl`.
- **One emulator session at a time** (fixed REST port), and **one controller of that session**:
  never leave a background poller that ends in `quit` running while you keep driving the session
  (a stale poller killed a capture run mid-intro on 2026-08-20).
- Getting into gameplay: prefer loading `work\dw1_re\postintro.state` (Lua:
  `PCSX.loadSaveState(Support.File.open('postintro.state'))`). Starting a NEW game instead
  requires launching with `-FreshCards`: **DW1 auto-saves to the memory card the moment the
  game is created**, and on the next boot an occupied slot blocks the "create game" flow at the
  START SLOT screen (it looks frozen — it is rejecting the occupied slot, not hung). From a
  cold boot, the intro has two name-entry screens that blind mashing cannot pass (cursor starts
  on OK with an empty name). Drive them with eyes: `dw1_redux_input.lua` (`dw1_press`) +
  `dw1_redux_screenshot.py` after each press. Working recipe: on the grid press RIGHT, CROSS
  (types a char), RIGHT (wraps to Back), DOWN (OK), CROSS, then CROSS on the Yes/No dialog.
- For value diversity beyond what play produces, mutate the watched state via
  `dw1_redux_api.py poke` — but only after saving any savestate you care about; mutated flags
  can derail scripts.
- Caveats: capture assumes non-recursive functions; CPU breakpoints don't see DMA writes.
- **Savestate loads do not disturb armed Lua breakpoints**, so touring the state library in one
  session is the cheapest way to diversify vectors. `dw1_masher('x')` advances dialogs hands-off.
- Where the traffic is: ordinary free-roam runs almost **no** script bytecode. The intro cutscene
  is by far the densest source, followed by dialog-open shop states and screen transitions. If a
  script-side counter is not moving, the problem is usually the game state, not the harness.

Game-behavior facts for scripted play (user-confirmed 2026-08-20):

- Savestates in `work\dw1_re\` (user-placed; recruit/prosperity state VARIES per state —
  peek before assuming; e.g. `freeroam` has ZERO recruit bits, `shop_secret` has all 50):
  - `freeroam.state` — File City free-roam at Jijimon's door (prefer over `postintro.state`,
    which is mid-cutscene).
  - Shops: `shop_item_city.state` (building interior, screen 216, CROSS talks),
    `shop_item_city_v1.state` (outdoor stall, screen 181, ONLY Betamon+Coelamon recruited,
    Buy/Sell menu open), `shop_secret.state` (sewer, screen 217, all-50 save, Numemon at
    the counter), `shop_secret_v1.state` (T1-only Numemon+Mojyamon, menu open, Mojyamon),
    `shop_recycle.state` (Tinmon, Gear Savanna, screen 131, dialog open),
    `shop_merit.state` (ShogunGekomon, Volume Villa, screen 141, dialog open).
  - `zone_transition.state` — field edge, walk LEFT to cross (anti-stuck spot).
  - Regression collection (2026-08-20 session, all on `session_checkpoint.state`'s prep:
    god-mode 999/9999, 9,999,999 Bits, arena family + Birdramon + Agumon recruited,
    6 flight triggers, Grey Claws slot 6, Digianchovy slot 7):
    - `session_checkpoint.state` — reload instead of redoing the prep.
    - `battle_pending.state` — close menu → Agumon (first fight) collides → CROSS through
      dialog → real-time battle. In-battle item use: TRIANGLE (item menu) → CROSS (first
      item) → CROSS ("Use") — be quick, god-mode ends fights fast.
    - `arena_lobby.state` (receptionist dialog; fights are SCHEDULED — sign up, wait for
      the hour) and `arena_fight.state` (at the door at fight time; walk UP to enter).
      **Redux caveat: the arena fight runs, but the post-fight exit transition hangs
      deterministically in PCSX-Redux** (BIOS-event busy-wait at 0x800C8F98; fine on
      BizHawk/Duckstation). Don't expect to return to the city; `arena_hang_repro.state`
      preserves the hang for autopsy.
    - `curling_penguinmon.state` — Penguinmon dialog open, inventory scroll pre-positioned
      on Digianchovy: CROSS confirms. Starting curling REQUIRES giving a Fish (ids 62-67).
    - `flight_birdramon.state` — Birdramon destination menu open (pick + confirm). Note:
      Birdramon's perch needs AGUMON recruited in addition to Birdramon's own bit +
      flight triggers.
    - `digivolve_ready.state` — cursor on Grey Claws (id 71): CROSS = Use → Champion
      digivolution. Discipline can make the partner REJECT the item (not consumed):
      reload and retry until accepted.
    - `savepoint_jijimon.state` (save menu open) and `savepoint_sleep.state` (SLEEP
      selected, digimon sleepy) — the two memcard-write paths.
    - `poop_pending.state` — menu open; close + walk LEFT = toilet, or wait = poops on
      the spot (two care-path cases).
    - `cutscene_pending.state` — close menu + walk RIGHT triggers Coelamon's cutscene
      (time-of-day-gated — the screen polls the hour; bonus: the cutscene warps regions).
- **The lab runs the VANILLA ISO — no AP ROM patches.** AP RAM state that "works 100% in the
  randomizer" often depends on the patcher rewriting the ROM; those values won't apply here. Use
  vanilla values. Confirmed case: Birdramon flight destinations. The AP delivers flight unlocks
  as trigger bits 880-884 (0x1BE03B) which only work because the patcher redirects Birdramon's
  destination table to read them; on the vanilla ISO you must set the ORIGINAL triggers instead
  — Gear Savanna=190, Ancient Dino=188, Freezeland=351, Misty Trees=147, Beetle Land=210,
  G Canyon Top=221 (setTrigger formula: byte 0x1BDFCD + N//8, bit N%8). The same caution applies
  to the shops themselves: the lab shows the vanilla Recycle/Merit shop code, which is exactly
  what we want to decompile.
- Recycle Shop (Tinmon, Gear Savanna) dialog: opening options are "I want a regular item"
  (-> normal Buy/Sell/Leave menu — the path we care about), "I want a recycled item" (buy-back
  of sold items; unused for RE), "Next time" (cancel).
- Merit Shop (ShogunGekomon, Volume Villa, screen 141): pays in **Merit Points**, not Bits.
  Merit Points come from trading Digimon Cards. Dialog options: "Show a Digimon card" (trade
  cards for Merit Points), "Use Merit points" (the actual shop — priority for RE), "See ya".
  QoL angle worth analyzing: raising the Merit Points a card is worth (earning them is very
  tedious in vanilla). The "Show a Digimon card" menu is a scrolling list of ALL card slots
  ordered by an internal card value (not by which you own), so owned cards can appear far down
  and the top may look empty — when testing, give a high count of ALL cards at once so owned
  cards are visible without scrolling.
- The partner's Sleep command only works when the digimon is sleepy (internal, time-of-day- and
  species-dependent); the button renders slightly darkened when unavailable.
- Item "Use" can be silently REJECTED (no discipline — random — or item has no effect): a brief
  animation plays (not detectable via screenshots) and the item is NOT consumed. To provoke a
  guaranteed inventory change, use the item menu's drop/toss option instead — it never gets
  rejected.

### Step 5 — Reimplement in portable C

`work\dw1_re\decomp\<unit>\<unit>.c`, style rules:

- Model RAM as `uint8_t *ram` + explicit little-endian `ld/st` helpers; addresses stay KSEG0.
- Keep original names and document original addresses in the header comment.
- `stdint.h` types; reproduce original semantics *exactly*, including degenerate edge cases
  (byte-wrap shift counters, signed div idioms, overflow) — faithfulness beats cleanliness.
- Stub PsyQ callees with libc; game callees must be part of the unit (call them directly).

### Step 6 — Verify by replay

- `test_main.c`: stdio driver — reads one request line per vector, sets up the RAM state from
  the captured `pre` regions, calls the function, prints outputs (see triggers pilot).
- `verify.py`: feeds every vector from `vectors.jsonl` through the driver and compares against
  the captured `v0`/`deref`/`post`. Vectors whose captured window doesn't cover the call are
  counted `skip`, never silently dropped.
- Build & run:

```bash
export PATH="/c/opt/tools/w64devkit/bin:$PATH"
gcc -O2 -Wall -Wextra -o <unit>_test.exe <unit>.c test_main.c
python verify.py            # exit 0 + "VERDICT: OK" required
```

- Any mismatch = the C is wrong (or the vector capture was misconfigured). Fix and rerun;
  never relax the comparison.

### Step 7 — Record

- `work\dw1_re\decomp\<unit>\NOTES.md`: what the function does, structural insights, vector
  coverage (how many, which paths, what was skipped and why), date.
- Update the ledger `work\dw1_re\decomp\LEDGER.md` (status table of all units). If the unit is
  `PROVISIONAL`, add the matching row to [SAVESTATE_REQUESTS.md](SAVESTATE_REQUESTS.md) in the
  same pass — a PROVISIONAL row with no request row is a dead end nobody can pick up later.
- Session hygiene: archive `work\dw1_re\vectors.jsonl` into the unit dir (the next capture
  session truncates it). Screenshots default to overwriting `work\dw1_re\screen_now.png`; if
  you wrote extra captures under other names, delete them when the session ends.
- If the function revealed addresses/structures relevant to the APWorld, propagate to
  `data/addresses.py` comments or project memory as usual.

## Complexity tiers

| Tier | Traits | Extra steps |
| --- | --- | --- |
| T1 | Pure/leaf, few data refs (trigger family) | none — pipeline as-is |
| T2 | Reads static tables (ITEM_PARA readers) | dump the tables once into the bundle; harness loads them |
| T3 | Deep callee closure / struct-heavy | decomp callees first (bottom-up); define structs in Ghidra as you learn them |
| T4 | Overlay code, DMA/IRQ/timing-sensitive | overlay import into Ghidra required; vector capture may need custom regions or CdRead hooks |

## Known gotchas

- `$gp = 0x8013BB2C` is already set program-wide in the Ghidra project; if a decomp still shows
  `Ramffffxxxx` pseudo-symbols, re-analysis is missing.
- Ghidra's signedness guesses are the #1 source of silent bugs — the vector replay catches them,
  which is why the bar is 100% replay, not review.
- The REST `eval` endpoint truncates >~180-byte URLs; `dw1_redux_api.py` auto-falls back to the
  `run` file handler — always use the client, not raw curl.
- Emulator process is `pcsx-redux.main`; close with `dw1_redux_api.py quit`.
- Trigger array (and likely the whole save block) is reached via `*(0x80134FB8)`, not constants.

## Batch mode (agents + workflow)

The `dw1-decomp` agent (`.claude/agents/dw1-decomp.md`) runs this pipeline for one unit given
its bundle; the `dw1-decomp-batch` workflow (`.claude/workflows/dw1-decomp-batch.js`)
orchestrates: a serial *prepare* stage (all Ghidra exports + one shared vector-capture session)
followed by parallel per-unit *implement* agents. Serialization rules above are why prepare is
a single stage.
