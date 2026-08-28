# Digimon World 1 (PS1) APWorld — Project Status and Roadmap

**Snapshot date: 2026-08-23.** Branch `digimon-world-ps1`, HEAD `b774d899`, `world_version 0.6.0`.

This is the live status document. [PLAN.md](PLAN.md) is the historical exploration record and
[CLAUDE.md](CLAUDE.md) carries the working conventions; neither is updated for day-to-day state —
this file is. Its purpose is to answer three questions at a glance: **where the project is**, **what
is left and what blocks it**, and **what reverse-engineering (decomp + savestates) each remaining
goal requires**.

---

## 1. Where the project is

**The world is functionally complete and playable.** Generation, ROM patcher, two emulator clients
and the Launcher integration all exist and are exercised by the test suite and the RE lab. The
project moved out of "build the world" and into **feature expansion + polish + verification** on
2026-08-22.

| Measure | Value |
| --- | --- |
| World version | 0.6.0 (`minimum_ap_version` 0.6.7) |
| Locations / items | 279 / 217 |
| YAML options | 47, in 5 option groups |
| World test suite | **1001 passed**, 4 skipped, 9181 subtests, ~15 s with `-n auto` |
| Lint | `ruff` at a stable 303-finding baseline (pre-existing; no new findings introduced) |
| Commits ahead of `main` | 81 |
| Decomp coverage | **31 / 1120** SLUS game functions verified — 2.8 % by count, **14.5 % of static call sites** |

### 1.1 What is shipped

**Core (v1, 2026-04/05)** — chest, NPC-gift, starter and recruitment checks; prosperity-point
locations; item delivery through the in-game bank with an `items_received` counter; recruit
visibility via the "Plan A revised" split (vanilla bit 200+X for the cutscene, AP bit 720+X for the
city); two goals (Machinedramon / prosperity threshold); Birdramon flight, Great Canyon and Lava
Cave gates; arena locations with a Progressive Arena ladder; technique rewards; ground-item and
starter randomization; the debug-menu and god-mode QA accelerators.

**Architecture** — BizHawk + Nymashock + `APProcedurePatch` + the generic Lua connector (the FFT
Ivalice Island pattern), plus a separate DuckStation client sharing an `EmulatorAdapter`
abstraction. PCSX-Redux + Ghidra form the RE lab (not player-facing). The single address manifest
is [worlds/digimon_world/data/addresses.py](worlds/digimon_world/data/addresses.py).

**2026-08 expansion batch** (every item lab-validated through the three PATCH_PROCESS nets and
disc-boot byte-verified):

- Physical **region-gate** enforcement for `region_locking` — walk-on loop-back wrapper, 12
  script-class gates, Birdramon-flight gating; flight fares zeroed as QoL.
- **ITEM_PARA relocation** to a contiguous 256-slot table on heap-claimed RAM (ceiling 173 → 255).
- **Shopsanity** — per-shop off / coexist / replace for all four shops, tiered or randomized prices.
- **Card-trade multiplier** and the **Piximon Training Manual** check.
- QoL: recruit-location opt-outs, the Archipelago logo item icon, chest-delivery hardening,
  inventory-first item delivery, infinite Auto Pilot, and the Coelamon recruit-loop fix.

**2026-08-22/23 decomp campaign** — see §3. One shipped-code bug found and fixed on the way: AP
technique grants now set the companion mastery bit vanilla sets (`d8048b33`).

### 1.2 Verification state

| Layer | State |
| --- | --- |
| Generation logic | Test suite green; generic AP suite green |
| Patcher | Sector-aware writes + EDC recalculation; every patch has a C-model net, a live-RAM net and one confirming ISO build |
| Client | Unit-tested deliverers/reconcilers; end-to-end smoke passed 2026-04-28 |
| **Human validation of the August batch** | **NOT DONE** — checklist at `work/dw1_re/BIZHAWK_SESSION_CHECKLIST.md`. This is the one thing standing between "lab-validated" and "release-validated". |

---

## 2. Roadmap

Grouped by **what blocks each item**, because that is what decides the order.

### 2.1 Blocked on the user

| Item | What is needed | Why it matters |
| --- | --- | --- |
| **BizHawk validation session** | One play session on the real client against the checklist (region gates, four shops, ITEM_PARA residuals, card ×8, Piximon; late-game heap margin as a separate save) | Closes the August batch. May generate corrective work. |
| **Savestate batch** | The states in [SAVESTATE_REQUESTS.md](worlds/digimon_world/tools/SAVESTATE_REQUESTS.md) — see §4 | Converts every PARTIAL decomp unit to VERIFIED and unlocks whole subsystems (fishing, training) the lab cannot reach today |
| **Gekomon recruit** | The vanilla recruit method, as text | New recruit; needs bit/visibility RE afterwards |
| **Whamon / Ogremon quest softlocks** | Reproduction recipes, as text | Script state-machine RE + guard patches |
| **Logic review** | The user's own pass over `rules.py` | — |

### 2.2 Ready now — no RE, no user input

| Item | Scope |
| --- | --- |
| **Phase 5 player docs** | `docs/setup_en.md` + `docs/en_Digimon World.md` in AP's format. None exist yet; the 7 files in `worlds/digimon_world/docs/` are internal RE notes and are `.apignore`d. |
| **WebWorld** | No `WebWorld` subclass exists. `option_groups` is defined in `options.py` but wired to nothing; presets absent. |
| **Region-locking option integration** | Today a randomized locked set cannot be combined with a starting region except by hand. Needs a proper option plus the sphere-0-empty guard (`custom` + Native Forest locked = unfillable). |
| **Card-shop duplicate fix (optional QoL)** | One-word ROM patch at `0x800FC3DC` (`0x02301021` → `0x02231021`). Address-targeted only — the same word appears twice more in the function. |
| **Packaging** | `.apworld` rebuild via the Launcher's "Build APWorlds" once the above land. |

### 2.3 Needs RE — with its requirements

| Item | Decomp units required | Savestates required | Effort |
| --- | --- | --- | --- |
| **In-game check notifications** | `FUN_800FF0FC` @ 0x800FF288 (dialog page/box driver). `dialogRenderString` already modelled. | `dialog_columns.state` (the 7 control codes a notification would use are asm-derived only) | **MEDIUM** — downgraded from "riskiest item in the backlog" on 2026-08-23: the low-risk route is a line-buffer substitution at `0x801BE174 + row*0x40`, not a renderer hook. |
| **Enemy-stat scaling by sphere** | Training stat-gain routines; `battleStatsGainsAndDrops` @ 0x800ECEE8 (in `BTL_REL` — see overlay gap in §3.3) | `training_gym.state`, `post_battle_learn.state` | HIGH (MEDIUM as scaling-only). Also needs the user's scaling-policy design. |
| **Wild-digimon randomization** | `BTL_REL` overlay import + the encounter/moveset tables the standalone randomizer catalogues | `battle_pending.state` exists; overlay import is the blocker | HIGH. Needs user design. |
| **Fishing locations (expansion)** | `FISH_REL` overlay import; 6 ITEM_PARA readers there are static-verified only | `fishing.state` — **the lab has no fishing state at all** | MEDIUM |
| **Digivolution (v2 scope)** | `calculateRequirementScore` @ 0x800E26B8 (requirement table at 0x8012ABEC, stride 0x1C); `hasDigimonRaised` finishing | `digivolve_accepted.state`, `species_raised.state` | MEDIUM. Note the "ever raised" flag (trigger 512+form) can **veto** a digivolution whose stat requirements are met — an AP digivolution item must account for it. |
| **Post-game heap margin** | None — measurement only | `mt_infinity.state`, `back_dimension.state` | LOW. The 8 KB ITEM_PARA claim sits 0x408 bytes above the glyph ring; late-game allocations unmeasured. |
| **Gekomon / Whamon / Ogremon** | Script-section RE once the user's text arrives | — | MEDIUM each |

### 2.4 v2 location sources (from PLAN.md §Phase 7, still unscheduled)

Key-item spawns as locations · renewable item spawns (first pickup = check + item) · fishing
milestones · recruit-list audit · item-pool polish. Explicitly rejected: techniques as *both* items
and locations.

### 2.5 Known issues and debt

- `test_fill` fails on some random seeds under `region_locking: all` (pre-existing, not the batch).
- Merit-shop `mark_bought` faults; the client reconciler is load-bearing. One unreproduced
  greyed-out-row sighting in Volume Villa.
- **Trigger-bit budget is nearly exhausted**: 780..783 are the last audited-free bits; ids ≥ 800
  overlap the pstat array and are off limits. Any new flag needs a claim decision first.
- The `>=800-is-pstat` audit's *method* (static constant-caller census) under-counted the pstat
  range — live capture saw targets up to 254. Its conclusion for the bytes AP claims still holds;
  future claims must be vector-captured, not grepped.
- `0x80134FE4` stores only `sectionId & 0xFF` while live section ids reach 1228 — nothing in RAM
  holds the authoritative section id.
- `SESSION_STATE.md` at the repo root is a 2026-04-30 snapshot and is superseded by this file.

---

## 3. The decomp programme

### 3.1 Purpose and bar

Decomp is **instrumental, not a completeness goal**: functions are decompiled because a patch or a
feature needs their exact semantics. The bar is **100 % replay of emulator-captured call vectors**
against a portable C model — reading-level pseudo-C is a draft, never a deliverable. Process:
[DECOMP_PROCESS.md](worlds/digimon_world/tools/DECOMP_PROCESS.md); agents `dw1-decomp` /
`dw1-patch`; output stays in gitignored `work/dw1_re/decomp/` (public fork).

Statuses: `VERIFIED` (bar met) · `PARTIAL` (replayed clean, but a branch or input class is
knowingly uncovered — always paired with a savestate request) · `PROVISIONAL` (modelled, not
replayed; blocked on capture) · `FAILED` / `BLOCKED`.

### 3.2 Coverage

Denominator from a Ghidra census (`DW1FunctionStats.java` → `work/dw1_re/function_census.tsv`):
`SLUS_010.32` has 1794 functions; after removing the GTE macro segment, 70 BIOS thunks and 400 PsyQ
signature matches, **1120 are game code** (339 KB). The **16 overlays are not in the Ghidra project
and are outside this denominator** (§3.3).

| Metric | 2026-08-22 (start) | 2026-08-23 |
| --- | --- | --- |
| Functions verified | 11 | **31** |
| By count | 0.98 % | **2.77 %** |
| By code bytes | 0.40 % | 1.64 % |
| **By static call sites** | ~5 % | **14.45 %** (788 / 5454) |

The call-site number is the one that reflects strategy: hot, foundational functions first.

### 3.3 Ledger (17 units)

| Unit | Status | Replay | Note |
| --- | --- | --- | --- |
| triggers (4 fn) | VERIFIED | 3342/0 | Trigger array = `*(0x80134FB8) + 0xF5` |
| random | VERIFIED | 159/0 | BIOS LCG, seed @ 0x85EC |
| getItemCount | VERIFIED | 342/0 | |
| build_shop_runtime_list | VERIFIED | 16/0 | Generic money-shop builder |
| build_merit_shop_list | VERIFIED | 18/0 | |
| heap3 (3 fn) | VERIFIED | 118/0 | Arena starts at 0x1BFB70 |
| item_para_reloc | 3 NETS GREEN | patch mission | |
| scriptvm (9 fn) | VERIFIED | 8842/0 | pstat = save+0x159, indices to 254; one streamed script slot |
| isKeyDown | VERIFIED | 2741/0 | Not self-consuming; 0x80135024 is a one-hot edge latch |
| hasDigimonRaised | **PARTIAL** | 2866/0 | Trigger 512+X is "ever raised", NOT recruit; `v0==1` never seen |
| scriptIdToEntityId | VERIFIED | 588/0 | Entity records @ 0x80155828 stride 0x68; mastery bitmap = partner record +0x58 |
| dailyPStatTrigger | VERIFIED | 33/0 | **Vanilla bug**: duplicate-card check is dead code (21.6 % of days) |
| learnMove | VERIFIED | 6 nat + 560 syn | Two-bit companion masks for Dynamite/Horizontal Kick; no bounds check |
| getNumMasteredMoves | **PARTIAL** | 0 nat + 232 syn | Plain 64-bit popcount; all vectors synthetic |
| callScriptSection (+1) | **PARTIAL** | 366/0 | VM context block confirmed; 43/58 stores invisible mid-dialog |
| renderString (+4) | **PARTIAL** | 20280/0 | Menus/HUD only; glyph DMA ring @ 0x801BE958 |
| dialogRenderString (+2) | **PARTIAL** | 2609/0 | **The** dialog renderer; 7/13 control codes unexercised |

Every PARTIAL is replay-clean; the status names an input class the lab could not produce. §4 maps
each to the state that closes it.

### 3.4 Standing tooling gap: overlays

`BTL_REL`, `FISH_REL`, `TRN_REL` and the other 13 overlays are **not imported into Ghidra**. That
single gap blocks battle internals, fishing and training — three of the roadmap's RE items. The
import itself is tooling work (raw MIPS at the documented load address, `dw1_iso_extract.py`), not
capture work; DECOMP_PROCESS.md tier T4 describes it as "not yet standardized". It should be the
first RE task of the next campaign because so much hangs off it.

### 3.5 Next targets (autonomous, no savestate needed)

1. **Overlay import** (§3.4) — unblocks three roadmap items.
2. `FUN_800FF0FC` — the dialog page/box driver; the last piece for notifications.
3. `calculateRequirementScore` @ 0x800E26B8 — digivolution gating, requirement table.
4. `playSound` (151 callers), `startAnimation` (96), `FUN_800E5B50` (104) — highest remaining
   call-site leverage.
5. Re-capture `renderString` with the 0xE10 window (config change only) to convert 446 skips.

---

## 4. Savestate requirements, mapped to goals

The full queue with capture instructions is
[SAVESTATE_REQUESTS.md](worlds/digimon_world/tools/SAVESTATE_REQUESTS.md). Each row there is a
5-minute job; this table is the *why*.

| Savestate | Closes (decomp) | Advances (roadmap) | Priority |
| --- | --- | --- | --- |
| `post_battle_learn.state` | `learnMove` natural class | Regression evidence for the shipped companion-bit fix; enemy-stat scaling | **High** |
| `digivolve_accepted.state` | `getNumMasteredMoves` → VERIFIED; `calculateRequirementScore` capture | Digivolution v2 | **High** |
| `species_raised.state` | `hasDigimonRaised` → VERIFIED | Digivolution v2 (the veto flag) | **High** |
| `fishing.state` | FISH_REL readers (after overlay import) | Fishing locations; ITEM_PARA residual check | **High** |
| `training_gym.state` | Stat-gain routines | Enemy-stat scaling | **High** |
| `dialog_columns.state` | `dialogRenderString` → VERIFIED | **In-game notifications** | Medium |
| `script_vm_cold_start.state` | `callScriptSection` → VERIFIED (43 invisible stores; cache-miss path) | Every script-bytecode patch | Medium |
| `mt_infinity.state`, `back_dimension.state` | — | Post-game heap-margin measurement | Medium |
| `machinedramon.state` | Ending path, trigger 50 | Goal robustness | Medium |
| `card_trade.state` | Card-value path | Card multiplier (shipped on static analysis + one live check) | Medium |
| `long_text.state` | `renderCharacter` 0xF4 clamps | — | Low |
| `numeric_ui.state` | `convertAsciiToGameChar` punctuation runs | — | Low |
| `rebirth.state`, `piximon_shop.state` | Mastery survival across rebirth; Piximon check | QoL confidence | Low |

**One sitting covers all of it.** Rule of thumb from the lab: stop one input short of the event.

Not savestate problems (do not capture for these): battle internals (overlay import), the arena
exit hang (PCSX-Redux only), Gekomon / Whamon / Ogremon (need text).

---

## 5. Dependency map

```
                     ┌──────────────────────┐
  user session ─────►│ BizHawk validation   │──► release-validated 0.6.x ──► Phase 5 docs ──► WebWorld
                     └──────────────────────┘                                                    └──► .apworld

  user savestates ──► PARTIAL units → VERIFIED ──┐
                                                  ├──► notifications (needs FUN_800FF0FC + dialog_columns)
  overlay import ───► BTL/FISH/TRN decomp ────────┤
                                                  ├──► enemy-stat scaling (needs training_gym + user policy)
  user text ────────► Gekomon / Whamon / Ogremon  │
                                                  ├──► fishing locations (needs fishing.state)
                                                  │
                                                  └──► digivolution v2 (digivolve_accepted + species_raised)
```

Two things are on every path: the **savestate batch** and the **overlay import**. Everything in
§2.2 is independent of both and can proceed at any time.

---

## 6. Where things live

| What | Where |
| --- | --- |
| Address manifest (single source of truth) | `worlds/digimon_world/data/addresses.py` |
| Process docs | `worlds/digimon_world/tools/{DECOMP_PROCESS,PATCH_PROCESS,TOOLING,AGENT_VOCABULARY}.md` |
| Savestate queue | `worlds/digimon_world/tools/SAVESTATE_REQUESTS.md` |
| Decomp ledger + units (gitignored) | `work/dw1_re/decomp/LEDGER.md`, `work/dw1_re/decomp/<unit>/` |
| Function census (gitignored) | `work/dw1_re/function_census.tsv` |
| Lab savestates (gitignored) | `work/dw1_re/*.state` (26 today) |
| BizHawk validation checklist (gitignored) | `work/dw1_re/BIZHAWK_SESSION_CHECKLIST.md` |
| Agents | `.claude/agents/{dw1-decomp,dw1-patch}.md` |
| Historical plan / reference notes | `PLAN.md`, `REFERENCES_NOTES.md` |
