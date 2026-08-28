# Digimon World 1 (PS1) APWorld — Project Status and Roadmap

**Snapshot date: 2026-08-28.** Branch `digimon-world-ps1`, `world_version 0.6.0`.

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
| YAML options | 51, in 5 option groups |
| World test suite | **1035 passed**, 4 skipped, 9304 subtests, ~15 s with `-n auto` |
| Lint | `ruff` at a stable 303-finding baseline (pre-existing; no new findings introduced) |
| Commits ahead of `main` | 93 |
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

**2026-08-28 — dw_decomp adopted** (`1ed5e9a4`). A community **byte-matching** decompilation of
this exact build ([jype0/dw_decomp](https://github.com/jype0/dw_decomp), MIT) is now the primary
reading source for game code: ~87 % of all functions in C, all 15 overlays included, 72 structs.
Bridge from our addresses to its names: `tools/dw1_decomp_xref.py` / `tools/DW_DECOMP_XREF.md`;
its symbols are imported into the Ghidra project. Most of §3's "decomp programme" is thereby
reframed — see §3.1. The psxrecomp-based PC port is **parked** pending its author's appeal.

**2026-08-28 — audit and lab session.** Two audits against dw_decomp's C: zero discrepancies in
our replay models; in the manifest, 8 claims confirmed, 6 corrected, one shipped patch retired
(`ROM_PP_CALC_PATCH`, `dfe692db`) and one gameplay inconsistency queued (§2.3, recruit-bit readers
in overlays). The Ghidra project now carries dw_decomp's symbols, all 72 structs and 154 typed
globals. A user session captured six savestates (§4) and produced **`dw1_warp_state.py`**: an
unattended savestate on any of the 255 screens via the debug map (`2870fe07`). Lab tooling
hardened after three emulator crashes (`peek` and screenshots now go through Lua).

**2026-08-28 — enemy data model verified; two features shipped.** Reading dw_decomp plus four
Ghidra exports (`loadMapDigimon`, `scriptSetDigimon`, `handleBattleStart`, `loadMMD`) settled how
fights are defined: every field Digimon — wild fodder and story boss alike — is a record in its
screen's `.MAP` file (nine stat words, four move anim-ids with AI weights, bits), copied verbatim
into `NPC_ENTITIES` on screen load and into the battle's `INITIAL_COMBAT_STATS`; the species is
the record type plus the `loadDigimon`/`setDigimon` operands of the boot-resident MAPHEAD.SCN.
Both requested features are therefore **pure data patches** (no engine hook), lab-validated
through the three nets including two real battles on a patched disc:

- **`enemy_scaling`** ("progressive balancing") — each region's vanilla stat budget is
  re-assigned by the region's sphere depth in the seed, same factor for a region's bosses;
  `enemy_scaling_strength` blends towards vanilla.
- **`enemy_randomization`** (`wild` / `wild_and_story`, `same_level` / `any`) — per-screen species
  swaps drawn from fighters whose model fits the original's heap budget; stats kept, movesets
  re-picked from the substitute's technique list.

Data: `data/enemy_records.py` (989 records, 180 species with model sizes, 1177 MAPHEAD sites —
generated by `tools/dw1_enemy_census.py`, scan proven against the reference disassembly);
module `enemies.py`; spoiler lists factors and swaps. Unit + generation tests in
`test/test_enemies.py`.

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
| **Savestate batch** | The states in [SAVESTATE_REQUESTS.md](worlds/digimon_world/tools/SAVESTATE_REQUESTS.md) — see §4. **First sitting done 2026-08-28** (6 states incl. the `debug_warp` teleport hub); Medium rows remain | Patch validation in the real game (fishing, training, post-game heap margin) |
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

Since 2026-08-28 the "decomp required" column mostly reads "read this dw_decomp file" — the
code is known; what remains is design, patching, and **runtime validation**, which is what the
savestates are now for.

| Item | Code source (dw_decomp unless noted) | Savestates required | Effort |
| --- | --- | --- | --- |
| **In-game check notifications** | Dialog page/box driver `MAIN_func_800FF0FC` and renderer `drawString2` in `src/main/script_common.c` — **in C, nothing left to decompile**. | `dialog_columns.state` — now for *testing* an injected string that uses the tab/column codes, not for understanding them | **MEDIUM → LOW-MEDIUM**: design + one patch. Low-risk route is a line-buffer substitution at `0x801BE174 + row*0x40`, not a renderer hook. |
| ~~**Enemy-stat scaling by sphere**~~ **SHIPPED 2026-08-28** as `enemy_scaling` | Turned out to be data: every field Digimon is a `.MAP` record (`loadMapDigimon`, Ghidra export) that the battle copies verbatim (`BTL_initializeCombat`); no code hook. | Validated: `enemy_poc_map2.state`, `enemy_poc_battle.state` (edited record fought) | Done in the lab (3 nets). **Open**: the user's BizHawk pass, and whether the default policy (vanilla region budgets re-assigned by sphere depth, one factor per region so bosses stay proportionally tougher) is the balance they want. |
| ~~**Wild-digimon randomization**~~ **SHIPPED 2026-08-28** as `enemy_randomization` | Species = record type + MAPHEAD.SCN `loadDigimon`/`setDigimon` operands (`scriptSetDigimon` guard); models are malloc3'd whole (`loadMMD`), so swaps are heap-budgeted. | Validated: `enemy_poc_map0.state`, `enemy_poc_icemon_battle.state` (Icemon swap fought to the end) | Done for `wild`; `wild_and_story` ships **untested in a story cutscene** (a substitute may lack a scripted animation). Heap slack beyond size-neutral swaps unmeasured. |
| **Fishing locations (expansion)** | `src/fish/` (95 % in C). The 6 `FISH_REL` ITEM_PARA readers our relocation patched can now be read in C. | `fishing.state` — **still needed**: the relocation's FISH_REL readers have never been *exercised*; the lab has no fishing state | MEDIUM |
| **Digivolution (v2 scope)** | `calculateRequirementScore`, `getNumMasteredMoves`, `hasDigimonRaised` in `src/main/evolution.c` / `script_common.c`; requirement table `EVO_REQ_DATA` @ 0x8012ABEC | `digivolve_accepted.state`, `species_raised.state` — for validating an AP digivolution item, not for RE | MEDIUM. The "ever raised" flag (trigger 512+form) can **veto** a digivolution whose stat requirements are met — an AP digivolution item must account for it. |
| **Post-game heap margin** | None — measurement only | `mt_infinity.state`, `back_dimension.state` | LOW. The 8 KB ITEM_PARA claim sits 0x408 bytes above the glyph ring; late-game allocations unmeasured. |
| **Gekomon / Whamon / Ogremon** | Script-section RE once the user's text arrives | — | MEDIUM each |
| **Recruit-bit readers in overlays** (found 2026-08-28) | `src/trn/trn_reward.c:637,643` — Kabuterimon/Kuwagamon (triggers 219/251) grant the ×6/×5 training bonus; `src/dget/dget.c:308-357` — tournament entry counts recruits over triggers 200..310. Both read the **vanilla** bits, so an AP-delivered recruit shows the gym NPC but does not grant the bonus, and cup entry follows the vanilla count. | `training_gym.state`, `arena_lobby.state` (exists) | **Decided 2026-08-28**: TRN yes (AP recruits grant the gym bonus — immediate patch in `TRN_REL.BIN`, in flight through the `dw1-patch` agent); DGET **no** (cup tiers stay attached to Progressive Arena only, which the client's arena enforcer already guarantees — leave the vanilla count reader alone). |

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
- **2026-08-28 audit of `addresses.py` against dw_decomp** (`work/dw1_re/decomp/_dw_decomp_audit/REPORT.md`):
  14 claims, 8 confirmed, 6 corrected. Two mattered beyond comments: the `ROM_PP_CALC_PATCH`
  copied from the standalone randomizer rewrote the **prosperity** loop to read a field only the
  standalone seeds — it computed garbage that the client's `_enforce_prosperity` masked; **retired
  the same day** (vanilla formula is the fallback now). And the two unpatched recruit-bit readers
  in overlays (row in §2.3). Doc-level corrections: the flight-table layout (bytes were right, the
  documented layout wasn't), the script IF-primitive grammar behind `prosperity_goal` (patch
  right, comment wrong), the tech-learn chance table (`MOVE_LEARN_CHANCES[58][3]` @ 0x80125FA4,
  not `0x80126245`), and `0x80134E30` is a partner-sequence sync bit, not "script running".
- `SESSION_STATE.md` at the repo root is a 2026-04-30 snapshot and is superseded by this file.

---

## 3. The decomp programme

### 3.1 Purpose and bar

**Since 2026-08-28: read dw_decomp first.** `references/dw_decomp/` is byte-matching (CI `cmp`s
the rebuilt SLUS + all 15 overlays against the originals), so any function present there as C is
known to the bit. Resolve an address with `tools/dw1_decomp_xref.py --lookup`; if it is in C,
read it — decompiling it again is wasted work. Of the 34 functions this project has cared
about, 27 are in C there; 6 are still `INCLUDE_ASM` stubs (`build_shop_runtime_list`,
`build_merit_shop_list`, `dailyPStatTrigger` — all three already VERIFIED by us —
`startAnimation`, `unlearnMove`, `0x800E5B50`).

What our own pipeline is still for: (a) the ASM-only remainder, (b) **verifying patches** —
a static decomp says what the code is, only replay says what the game does with it at runtime,
(c) runtime questions (which values actually flow, which branches a real save exercises).
The bar for those is unchanged: **100 % replay of emulator-captured call vectors** against a
portable C model. Process: [DECOMP_PROCESS.md](worlds/digimon_world/tools/DECOMP_PROCESS.md);
agents `dw1-decomp` / `dw1-patch`; output stays in gitignored `work/dw1_re/decomp/`.

Study-only policy: read, learn, cite `file:line`; never copy their C into the world package.
Their names are not ours (their `renderString` is our `FUN_800E5B50`) — resolve by address.

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

These numbers measure *our* replay-verified models and are now a secondary metric. The primary
one is dw_decomp's: **2406 functions in C vs 369 ASM stubs = 86.7 %** of the whole game (main
82.8 %, overlays 89.5 %), byte-exact. Our 31 add runtime evidence on top of that for the
functions our patches touch.

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

### 3.4 Overlays — gap closed as a source, open only as a capture target

dw_decomp has C and symbol files for all 15 overlays (`src/btl`, `src/fish`, `src/trn`, …, with
load addresses in `config/<overlay>.yaml`), so battle internals, fishing and training are now
**readable**. Importing an overlay into our Ghidra project is only needed to *vector-capture* an
overlay function that is ASM-only upstream — a rare case, and no longer on any roadmap path.

### 3.5 Next targets

1. **Audit shipped assumptions against the C** — every `addresses.py` comment that says
   "inferred" or "static-census-derived" is now checkable (in progress 2026-08-28).
2. **Wave-2 lab tooling**: parse `include/dw/*.h` into a Ghidra data-type archive so decompiler
   views use their structs; overlay import only if a capture ever needs it.
3. ASM-only functions still worth our pipeline: `startAnimation` (96 callers), `0x800E5B50`
   (104), `unlearnMove`.
4. Re-capture `renderString` with the 0xE10 window (config change only) to convert 446 skips.
5. **Open user decision**: contribute our three verified models for functions still ASM-only
   upstream (`dailyPStatTrigger` with the card-duplicate bug documented, the two shop builders).

---

## 4. Savestate requirements, mapped to goals

The full queue with capture instructions is
[SAVESTATE_REQUESTS.md](worlds/digimon_world/tools/SAVESTATE_REQUESTS.md). Each row there is a
5-minute job; this table is the *why*.

**Re-triaged 2026-08-28.** With dw_decomp every branch these states were requested for has been
read in byte-matching C and agrees with our models, so **none is needed for understanding**. A
state now buys either *patch validation* (exercising a shipped or planned patch in the real
game) or *provenance* (upgrading a PARTIAL ledger row with natural vectors). Priorities reflect
that.

| Savestate | Buys | Advances (roadmap) | Priority |
| --- | --- | --- | --- |
| ✅ `fishing.state` (captured 2026-08-28) | Exercises the 6 relocated `FISH_REL` ITEM_PARA readers (never run live) | Fishing locations; ITEM_PARA residual check | **High** (validation) |
| ✅ `training_gym.state` (captured 2026-08-28) | Runtime evidence for the stat-gain routines (`src/trn/` is in C) | TRN gym-bonus patch | **High** (validation) |
| ✅ `enemy_poc_battle.state`, `enemy_poc_icemon_battle.state` (captured 2026-08-28, unattended: warp + tamer teleport) | A field battle that has just started against a patched record / a substituted species | Enemy scaling + randomization (shipped) | Done |
| `post_battle_learn.state` | Natural evidence for the companion-bit fix | Technique-learn confidence | Low (validation) |
| `digivolve_accepted.state` | Validation of a future AP digivolution item; `getNumMasteredMoves` → VERIFIED | Digivolution v2 | Medium (validation) |
| `dialog_columns.state` | Testing an injected notification string that uses the column codes | **In-game notifications** | Medium (validation) |
| ✅ `mt_infinity.state`, `back_dimension.state` (captured 2026-08-28) | Post-game heap-margin measurement | Heap safety of the ITEM_PARA claim | Medium |
| ✅ `machinedramon.state` (captured 2026-08-28) | Ending path, trigger 50 | Goal robustness | Medium |
| `card_trade.state` | Card-value path live | Card multiplier (shipped on static analysis + one live check) | Medium |
| `species_raised.state` | `hasDigimonRaised` → VERIFIED | — (the flag's semantics are C-confirmed) | Low (provenance) |
| `script_vm_cold_start.state` | `callScriptSection` → VERIFIED | — (all 43 stores C-confirmed) | Low (provenance) |
| `long_text.state`, `numeric_ui.state` | `renderCharacter` / `convertAsciiToJis` corners | — (C-confirmed) | Low (provenance) |
| `rebirth.state`, `piximon_shop.state` | Mastery survival across rebirth; Piximon check | QoL confidence | Low |

**2026-08-28 session: both High rows and the three post-game rows are captured**, plus a
`debug_warp.state` teleport hub (debug map, Mr. Warp open; poke the resident script's warp byte to
reach any map). Remaining: `post_battle_learn`, `digivolve_accepted`, `dialog_columns`,
`card_trade` (Medium) and the provenance-only rows.

Not savestate problems (do not capture for these): battle internals (overlay import), the arena
exit hang (PCSX-Redux only), Gekomon / Whamon / Ogremon (need text).

---

## 5. Dependency map

```
                     ┌──────────────────────┐
  user session ─────►│ BizHawk validation   │──► release-validated 0.6.x ──► Phase 5 docs ──► WebWorld
                     └──────────────────────┘                                                    └──► .apworld

  dw_decomp (read) ─► code known for every item ──┐
                                                  ├──► notifications (design + patch; dialog_columns to test)
  user savestates ──► runtime validation ─────────┤
                                                  ├──► enemy-stat scaling (training_gym + user policy)
  user text ────────► Gekomon / Whamon / Ogremon  │
                                                  ├──► fishing locations (fishing.state to exercise FISH_REL)
                                                  │
                                                  └──► digivolution v2 (digivolve_accepted + species_raised)
```

Since 2026-08-28 the code side of every RE item is covered by reading dw_decomp; the only shared
dependency left is the **savestate batch**, and its role changed from "verify our models" to
"validate our patches in the real game". Everything in §2.2 is independent of it.

---

## 6. Where things live

| What | Where |
| --- | --- |
| Address manifest (single source of truth) | `worlds/digimon_world/data/addresses.py` |
| Game code (reading source) | `references/dw_decomp/` (gitignored clone; pinned `04cef877`) — bridge: `tools/dw1_decomp_xref.py`, table `tools/DW_DECOMP_XREF.md` |
| Process docs | `worlds/digimon_world/tools/{DECOMP_PROCESS,PATCH_PROCESS,TOOLING,AGENT_VOCABULARY}.md` |
| Savestate queue | `worlds/digimon_world/tools/SAVESTATE_REQUESTS.md` |
| Decomp ledger + units (gitignored) | `work/dw1_re/decomp/LEDGER.md`, `work/dw1_re/decomp/<unit>/` |
| Function census (gitignored) | `work/dw1_re/function_census.tsv` |
| Lab savestates (gitignored) | `work/dw1_re/*.state` (32; `debug_warp.state` is the teleport hub) |
| Savestate on any screen, unattended | `worlds/digimon_world/tools/dw1_warp_state.py --map <id> --out <name>` |
| Capture-session log (gitignored) | `work/dw1_re/session_2026-08-28_savestates.md` |
| BizHawk validation checklist (gitignored) | `work/dw1_re/BIZHAWK_SESSION_CHECKLIST.md` |
| Agents | `.claude/agents/{dw1-decomp,dw1-patch}.md` |
| Historical plan / reference notes | `PLAN.md`, `REFERENCES_NOTES.md` |
