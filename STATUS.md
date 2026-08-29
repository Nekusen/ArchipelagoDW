# Digimon World 1 (PS1) APWorld — Project Status and Roadmap

**Snapshot date: 2026-08-29.** Branch `digimon-world-ps1`, `world_version 0.6.0`.

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
| YAML options | 80, in 5 option groups |
| World test suite | **1144 passed**, 4 skipped, 10532 subtests, ~18 s with `-n auto` (one class is disc-gated: it re-checks vanilla bytes when `Digimon World (USA).bin` sits at the repo root) |
| Lint | `ruff` at a 322-finding baseline (303 pre-existing + the two census tools' CLI prints, T201, like the other lab tools) |
| Commits ahead of `main` | 114 |
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

- **`enemy_stats`** (`vanilla` / `progressive` / `full_random`) — `progressive` re-assigns each
  region's vanilla stat budget **and technique power** by the region's sphere depth in the seed
  (same factor for a region's bosses; `enemy_stats_strength` blends towards vanilla);
  `full_random` gives every screen the difficulty of a random vanilla screen and random
  techniques from each species' list.
- **`enemy_randomization`** (`wild` / `wild_and_story`, `same_level` / `any`) — per-screen species
  swaps drawn from fighters whose model fits the original's heap budget; stats kept, movesets
  re-picked from the substitute's technique list.

Data: `data/enemy_records.py` (989 records, 180 species with model sizes, 1177 MAPHEAD sites —
generated by `tools/dw1_enemy_census.py`, scan proven against the reference disassembly);
module `enemies.py`; spoiler lists factors and swaps. Unit + generation tests in
`test/test_enemies.py`.

Same day, by the `dw1-patch` agent: the **Green Gym bonus now follows AP-delivered recruits**
(`TRN_GYM_BONUS_WORD_PATCHES`, always-on; the vanilla bit alone no longer grants it). Cup entry was
deliberately left on the client's arena enforcer (user decision).

**2026-08-29 — standalone-randomizer parity batch.** After an agent audit of the "what can be
randomized vs. what we do" table (all rows held; corrections: the element matrix is read by the
*partner's* auto-battle AI `BTL_selectPartnerMove`, not the enemy AI; Birdramon flight is a SLUS
table; lifetime is code, not data), every remaining *randomization* feature of meekrhino's
standalone was reimplemented clean-room with its own option set:

- **Technique data** — `technique_data` (vanilla / shuffle / randomized) with `technique_power`,
  `technique_mp_cost`, `technique_accuracy`, `technique_effect`, `technique_effect_chance`;
  **`type_effectiveness`** (the 7×7 element matrix). Module `techniques.py`; `MOVE_DATA` is
  global, so `enemy_stats` now scales enemies by the powers a seed ships (`TechniquePlan.powers`
  threads through `enemies.py`).
- **Enemy drops** — `enemy_drop_items`, `enemy_drop_rates`, `enemy_drops_match_value`,
  `enemy_drops_value_cutoff` (`DIGIMON_DATA.dropItem/dropChance`). Module `drops.py`.
- **NPC gifts** — `tech_gifts` (Bug + Seadramon's three teaches) and `tokomon_gifts` /
  `tokomon_gifts_consumable_only`. Module `gifts.py`.
- **The standalone's QoL patches that had no equivalent** — `quest_items_droppable`,
  `increase_learn_chance`, `brain_training_tier_one`, `unrig_slots`, `learn_move_and_command`,
  `fix_dv_chip_text` (default on). Vanilla bytes of every site pinned in `addresses.py` and
  re-checked on the disc by `test/test_gifts.py` when the vanilla `.bin` is present.

All of it is data (SLUS tables, script bytes, two overlay words); validated by a real-disc round
trip — one seed with every option on, patched onto the vanilla `.bin`, every spoiler line re-read
from the patched tables (121 techniques, 49 matrix cells, 180 drops, 10 gift sites, all patch
sites). `tools/dw1_enemy_census.py --emit-python` now also emits the full `MOVE_DATA` rows,
`ITEMS` and `ELEMENT_MATRIX`. Not ported (by design): recruit-identity shuffle (recruits are AP
items), the intro hash, the "Woah!" joke, `happyVending` (conflicts with `vending_locations`),
the Giromon jukebox truncation (the client blacklists Giromon instead) and the forced starter
(`starter.Digimon`).

**Same day, second commit — digivolution randomization** (the last standalone block):
`digivolution_randomization` (the natural tree: In-Training 2 Rookies, Rookie 4-6 Champions,
Champion 1-2 Ultimates; Fresh pairs are hard-coded in `getFreshEvolutionTarget` and stay),
`digivolution_obtain_all`, `digivolution_requirements` (rolled *after* the tree so a "from X"
bonus names a real predecessor; Devimon joins the tree and gets real stat gains) and
`special_digivolutions` (the 15 `ROM_SPECIAL_EVO` sites; Toy Town follows the suit's new
result). Module `evolutions.py`, tables `EVO_PATHS` / `EVO_REQUIREMENTS` / `EVO_GAINS` in
`enemy_records.py`. The option carries a **warning**: Greylord's Mansion (Virus), Ice Sanctuary
(Vaccine) and Toy Town (Monzaemon) are partner-gated, so a random tree can make those checks
slow or lucky unless `type_lock_unlocks` (default on) removes the gates — the player's call.
Interplay handled: the Toy Town gate byte (0x140479ED) is one of the Monzaemon special-evo
sites *and* sits inside the unlock's 4-byte write; the writer skips it when the unlock is on and
runs before the unlock tokens. Round trip green with all four options on. **User decision
(2026-08-29):** playing without `type_lock_unlocks` is the player's problem, but the seed must
stay *possible* — so every Fresh line of a randomized tree is guaranteed a natural path to at
least one Vaccine and one Virus species (`evolutions._guarantee_types`, a Champion of the
missing type added to one of the line's Rookies), and Numemon needs no guarantee (it is every
Rookie's fallback digivolution, `getRookieEvolutionTarget`). Same commit: **`enemy_technique_weights`**
(the AI-weight candidate from the table — a random split of 100 over each fighter record's
carried techniques; `enemies.random_weights`).

**Same day, from the assembly (agent, `work/dw1_re/decomp/damage_formula/NOTES.md`):**
`BTL_calculateDamage` **does** read the element matrix — every hit is scaled by
`Σ MATRIX[move.special][defender.special[i]] / 30` over the defender's three specialties
(`STD_calculateDamage` is byte-identical), so `type_effectiveness` is a real damage option, not
just AI weighting (docstring corrected; cells must stay in {2, 5, 10, 15, 20} because
`BTL_calculateElementBonus` has no default case — they do). `EVL_applyEvolution` applies a gains
row as `new = (cur + gain) / 2` below the gain, `cur + gain / 10` above, **except** the scale
path (targets Devimon / Numemon / Sukamon / Nanimon / Fresh / In-Training, or out of Sukamon)
where the `brains` column is an `int8` multiplier ×10 — so the standalone's Devimon gains row
(…, 200) wraps negative there; our Devimon override was removed (Devimon keeps the partner's
stats, ×1.0). New option **`digivolution_stat_gains`** randomizes the additive rows inside the
vanilla envelope of each level (never the scale rows, never `targetDigimon`).

**Same day, later — autonomous research batch (four static agents + the lab).** User decisions:
no Giromon / jukebox fix, no forced starter, meat farm and Mojyamon trades are not locations,
entrance shuffle **by region**; everything else researched and, where it turned out to be data,
shipped:

- **`species_technique_lists`** — the `.MMD` animation census (new `tools/dw1_mmd_census.py`,
  `work/dw1_re/decomp/mmd_census/NOTES.md`) settled the open question: a model carries an
  animation for exactly its populated slots (140 species exact, MegaSeadramon / Machinedramon one
  spare, Kuwagamon clone 169 none), so lists can only be re-filled **in place**. The option
  re-draws every populated slot inside its class (normal / finisher / bubble) and element, so the
  partner keeps learning from battle and brain training; `enemy_stats` reads the shuffled lists
  (`ListPlan.species_table` threaded through `enemies.py`). Module `technique_lists.py`.
- **`partner_raising`** — `RAISE_DATA` readers pinned per field (agent, dw_decomp + Ghidra
  exports of the ASM-only partner functions; `work/dw1_re/decomp/raise_bgm/NOTES.md`): favourite
  food, sleep schedule (0..5), home region (0..8), training aptitude (0..3) and birth weight of
  every Rookie+ partner species; the care economy is left alone. Module `raising.py`.
- **`bgm_shuffle`** (areas / screens / chaos) — the `playBGM` byte is the font id, fonts stream
  from `FAALL.VHB` on change (unknown font = silence, never a crash), 261 sites in MAPHEAD.SCN
  (23 forced-mode sites left alone, the 5 story-script sites too). Module `music.py`; the
  jukebox table gives the spoiler names.
- **`enemies.screen_region` corrected** on 18 screens against the lab's validated region map
  (Drill / Meramon Tunnel split, the Green Gym is File City, GOMI is Gear Savanna, ...).
- **Entrance shuffle by region — design ready, not implemented** (agent,
  `work/dw1_re/decomp/entrance_shuffle/NOTES.md`, extraction script `dw1_map_warps_dump.py` ->
  `map_warps.tsv` / `region_edges.tsv`): 241 screens, 288 live walk-on warps, 98 cross-region
  edges of which 22 strict two-way mouth pairs; recommended v1 pool = 15 two-way pairs on 13 field
  borders (10 pure `MapWarps` rewrites, 5 with one script side), coupled, through AP's generic
  ER; ferries / flights / Mt. Infinity / Back Dimension / town doors excluded. Effort ~10-14
  days (patcher 3-4, logic 3-4, validation 3-5). **Parked by the user (2026-08-29, later):**
  even at region granularity the logic rewrite is too large for now — kept as a future
  improvement; the design, the extraction script and its TSVs stay in `work/`.
- **Two findings on shipped code from the same research** (see §2.3): five `TRANSITION_GATE_ROWS`
  sit on warp slots with no trigger tile (their departures are script exits), so Ancient Dino and
  Mt. Panorama region access is physically unenforced and three more borders leak on one mouth —
  fix = five script stubs of the shipped `SCRIPT_GATE_PATCHES` shape; and two vanilla routes are
  missing from `regions.py` (GIAS02 -> FACT05 iron door, post-story MAYO11 <-> MIHA04B shortcut).

**Same day — in-game AP notifications shipped** (`in_game_notifications`, default on; `dw1-patch`
agent through the three nets plus negative tests, `work/dw1_re/decomp/notifications/NOTES.md`).
Mechanism: the client writes a message into a 68-byte RAM mailbox in Cave6 (flag + 64-byte text)
and a 28-word render callback spliced into the empty render slot of the file-read-queue world
object (the site the standalone's custom tick hook used, `initializeFileReadQueue`'s
`lui`/`addiu` pair) shows it through the game's own area-name banner — `addMapNameObject(239)`
with `MAP_ENTRIES[239].loadingName = 66` and `MAP_NAME_PTR[66] = &mailbox.text` — for 150 frames,
only while the tamer is idle on the field (`GAME_STATE == 0 && TAMER_STATE == 0 &&
IS_SCRIPT_PAUSED == 1`); a menu, dialog, battle, warp or pickup removes the banner and re-arms
the flag so the message is shown again later. The "Woah!" pickup box was investigated first and
rejected (a blocking three-line UI flow, ~70 words). Client side (`client.NotificationQueue`):
"Got: <item> [from <player>]" on every delivered item, "Sent: <item>" on every `ItemSend` this
player finds for another world, sanitised to the renderer's glyph set / 26-char width rule, one
message at a time when the flag reads 0, bursts summarised. `IS_SCRIPT_PAUSED`
(0x80134FF4) turns out to be misnamed: 1 = no script running.

**Same day, later — the banner moved to the top of the screen** (user decision: the centre is too
invasive; `dw1-patch` agent through the three nets, NOTES.md §10). The vanilla loading banner
must stay centred, so `renderMapName` is untouched: the two words of `addMapNameObject` that
build the render pointer it hands to `addObject` now point at `renderMapNameAp`, a 29-word
Cave6 dispatcher in two fragments (the gap after the AP item-description string + the retired
recycle giveItem slot) — any real screen tail-jumps to vanilla `renderMapName`; screen 239
composites the mailbox text with `renderString` at y = -112 (lines 8..20), clear of the clock
HUD for any message up to 30 characters. Live: short and 27-char messages at the top, a vanilla
map change mid-fade still centred, dialog / menu / pickup deferrals unchanged, cold boot on
`notification_top.bin`; `addresses.py` builds the words from `NOTIFY_TOP_Y` /
`NOTIFY_TOP_X_MODE` and pins both lab word sets plus the vanilla dead code under the two
fragments (disc-gated test); a real-disc round trip confirmed the four new sites. **After
seeing the captures the user picked the right-aligned variant** (`NOTIFY_TOP_X_MODE =
"right"`: the composited rect ends ~8 px from the right edge, a corner toast; four immediates
differ from the centre words, net 1 + net 2 live, round trip re-run) and asked that "Sent"
name the receiver: the client now shows `Sent: <item> to <player>` (the `ItemSend` packet's
`receiving` slot), dropping the name — never the item — when the 26-char rule would not hold,
symmetric with `Got: <item> from <player>`. Facts learned: the callback runs once per 30 Hz game loop
(150 iterations ≈ 5 s), and **Cave6 is now code-full** (4 + 12 + 12 B left) — the next code
feature goes through the heap claim. The dormant `isTriggerSet` head-wrapper constant overlaps
fragment 1; a test keeps its writer uncalled.

**Same day — the five dead region-gate rows FIXED** (`dw1-patch` agent, three nets; notes
`work/dw1_re/decomp/gate_fix/NOTES.md`, spec `patches/gate_fix.json`): seven script-class gates
of the shipped `SCRIPT_GATE_PATCHES` shape — 24 writes, 12 stubs in the slot-tail residue of
scripts 8 / 18 / 24 / 44 / 66 / 84, no Cave6 space — now enforce the Drill Tunnel mouth
(MAYO11 S52, Native Forest RA), the Ancient Dino exit strips (TROP06 S68..S73, incl. the
post-Centarumon walk-out), the Great Canyon bridge exit (GCAN09 S51, Tropical Jungle RA), the
Mt. Panorama mouth (GIAS00 S51), the Great Canyon mouth (FRZL01 S51), and the two Drill Tunnel
<-> Mt. Panorama prompt shortcuts (MAYO11 S53 "Let's go thru!", MIHA04B S51 "Go") that
`regions.py` never modelled. Blocked flows are silent vanilla paths (the strips do nothing, the
prompts behave like their decline). Live: all seven flows blocked with the RA bit clear and
crossed with it set over seven new savestates; cold boot on `gate_fix_test.bin`. The five dead
walk-on rows stay in the table (harmless, annotated). New module-load invariants: no script-gate
span may contain a `ROM_MAP_ITEM_OFFSETS` site or its `+1` byte (the ground-item shuffle writes
there after `apply_tokens` — one stub had to move), and gate groups sharing a script stay
disjoint. Of the two unmodelled vanilla routes, GIAS02 -> FACT05 (iron door) needs trigger 328
set only inside Factorial Town, itself behind the FT-RA-gated ferry (transitively gated, no
stub); the DT <-> Mt.P shortcut is gated here. A suspected Lava Cave boulder *bypass* through
that shortcut was **retracted the same day** (user + manifest check): the prompts read the
*vanilla* bit 238 — the `isTriggerSet` head-wrapper in `addresses.py` is defined but never
emitted, and Drimogemon's four per-site read patches are all city scripts — and Drimogemon is
physically behind the boulder, so the shortcut can never open without `Lava Cave Access`. No
second IF is needed; as a logic edge it would add nothing (same requirement as the Meramon
Tunnel route, plus an Ogremon-fled state logic cannot know).

**Technique objective, remaining (set 2026-08-28):** the *data* half shipped above; still open
are the two RE questions in §2.3 / §3.5 — does the element matrix enter `BTL_calculateDamage`,
and can species technique lists gain slots (`.MMD` animation census) — and the species-list
shuffle they gate.

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
| **BizHawk validation session** | One play session on the real client against `work/dw1_re/BIZHAWK_SESSION_CHECKLIST.md` — now also the 2026-08-29 options (technique data, drops, gifts, QoL patches, digivolution, species lists, raising, music, notifications, the five re-gated borders). | Closes the August batches. May generate corrective work. |
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
| **Entrance shuffle by region — PARKED (user decision 2026-08-29, future improvement)** | `MapWarps` per `.MAP` (walk-on) + script `warpTo` sites; graph and pool in `work/dw1_re/decomp/entrance_shuffle/NOTES.md`; AP side = generic ER (`disconnect_entrance_for_randomization` + `randomize_entrances(coupled=True)`), rules stay bound to the physical mouth, region-lock post-pass after ER. Also found: `changeMap` performs no variant remap (all variant selection is script-side) and two vanilla routes are missing from `regions.py` (GIAS02 §51 -> FACT05 iron door; post-story MAYO11 §53 <-> MIHA04B §51). | Validation is emulator-bound (3-5 days of the estimate). | PARKED: ~10-14 days if resumed (patcher 3-4, logic + tests 3-4, client 0.5-1, validation 3-5) — the logic re-keying is the part the user judged too large for now. If resumed: candidates to add = the DT <-> Mt.P prompt shortcut (B16, needs its Ogremon-fled clause neutralised in the two stubs) and the Seadramon ferry; B11/B12 only after checking MAYO02_2 pre-story. |
| ~~**Region-locking dead gate rows**~~ **FIXED 2026-08-29** (seven script-class gates, `_SCRIPT_GATE_FIX_PATCHES` in `addresses.py`, 24 writes validated through the three nets) | See §1.1. The suspected Lava Cave boulder bypass through the DT <-> Mt.P shortcut was a false alarm (the prompts read the vanilla recruit bit; Drimogemon sits behind the boulder). | `gate_fix_map{7,17,17_cent,23,44,69,88}.state` (vanilla) + `gate_fix_n3_map{69,7}.state` (patched) in `work/dw1_re/`. | None. `regions.py` edges for the shortcut would add no reachability (same requirement as the Meramon Tunnel route). |
| ~~**In-game check notifications**~~ **SHIPPED 2026-08-29** (`in_game_notifications`) | Not the dialog line-buffer route after all: the area-name banner path (`addMapNameObject` / `renderMapName`, all C) driven from a spliced render callback in Cave6; see §1.1. | `notification_field.state` (centre variant) and `notification_top_field.state` (shipped top variant, on `notification_top.bin`) exist for regressions. | Done — at the top of the screen since the same day (§1.1). A *boxed* banner would need the UI-box flow (~70 words) on heap-claimed RAM; not requested. |
| ~~**Enemy-stat scaling by sphere**~~ **SHIPPED 2026-08-28** as `enemy_stats: progressive` | Turned out to be data: every field Digimon is a `.MAP` record (`loadMapDigimon`, Ghidra export) that the battle copies verbatim (`BTL_initializeCombat`); no code hook. | Validated: `enemy_poc_map2.state`, `enemy_poc_battle.state` (edited record fought) | Done in the lab (3 nets). **Open**: the user's BizHawk pass, and whether the default policy (vanilla region budgets re-assigned by sphere depth, one factor per region so bosses stay proportionally tougher) is the balance they want. |
| ~~**Species technique lists**~~ **SHIPPED 2026-08-29** as `species_technique_lists` (in-place, class- and element-preserving) | Settled by the `.MMD` animation census: lists cannot grow (a model carries animations for exactly its populated slots; only MegaSeadramon / Machinedramon have one spare), so the option re-fills slots in place. The element matrix is a damage multiplier (sum of the defender-specialty cells / 30, read from the BTL / STD assembly) and the partner AI's ranking key. | None. Runtime check in the user's BizHawk pass (a wild Digimon using a swapped technique; brain training / battle learning of a swapped partner technique). | Provenance only: a VERIFIED replay of `BTL_calculateDamage` against the three battle states. |
| ~~**Digivolution randomization**~~ **SHIPPED 2026-08-29** (`digivolution_randomization` + obtain-all / requirements / special) | Tree `EVO_PATHS_DATA[62]` (`EvolutionPath{from[5], to[6]}`, 0x8012B66C, walked by `evolution.c:60-230`; Fresh -> In-Training hard-coded in `getFreshEvolutionTarget`), requirements `EVO_REQ_DATA[63]` (`evl.h:47-62`, scored by `calculateRequirementScore` `evolution.c:303-411`), gains `EVO_GAINS_DATA[66]` (applied in `EVL_applyEvolution` 0x80063350, ASM-only — only Devimon's row is rewritten), special evolutions = SLUS immediates in `handleSpecialEvolutions` (`evolution.c:231-300`) + script bytes (`ROM_SPECIAL_EVO`). Pure data; no AP-logic change — the option warns that the three partner-gated areas become luck without `type_lock_unlocks`. | None. Runtime validation pending in the user's BizHawk pass (a natural digivolution under random requirements, a death digivolution, the suit). | Open follow-up only: `EVL_applyEvolution` decomp if the gains table is ever randomized beyond Devimon. |
| ~~**Wild-digimon randomization**~~ **SHIPPED 2026-08-28** as `enemy_randomization` | Species = record type + MAPHEAD.SCN `loadDigimon`/`setDigimon` operands (`scriptSetDigimon` guard); models are malloc3'd whole (`loadMMD`), so swaps are heap-budgeted. | Validated: `enemy_poc_map0.state`, `enemy_poc_icemon_battle.state` (Icemon swap fought to the end) | Done for `wild`; `wild_and_story` ships **untested in a story cutscene** (a substitute may lack a scripted animation). Heap slack beyond size-neutral swaps unmeasured. |
| **Fishing locations (expansion)** | `src/fish/` (95 % in C). The 6 `FISH_REL` ITEM_PARA readers our relocation patched can now be read in C. | `fishing.state` — **still needed**: the relocation's FISH_REL readers have never been *exercised*; the lab has no fishing state | MEDIUM |
| **Digivolution (v2 scope)** | `calculateRequirementScore`, `getNumMasteredMoves`, `hasDigimonRaised` in `src/main/evolution.c` / `script_common.c`; requirement table `EVO_REQ_DATA` @ 0x8012ABEC | `digivolve_accepted.state`, `species_raised.state` — for validating an AP digivolution item, not for RE | MEDIUM. The "ever raised" flag (trigger 512+form) can **veto** a digivolution whose stat requirements are met — an AP digivolution item must account for it. |
| **Post-game heap margin** | None — measurement only | `mt_infinity.state`, `back_dimension.state` | LOW. The 8 KB ITEM_PARA claim sits 0x408 bytes above the glyph ring; late-game allocations unmeasured. |
| **Gekomon / Whamon / Ogremon** | Script-section RE once the user's text arrives | — | MEDIUM each |
| **Recruit-bit readers in overlays** (found 2026-08-28) | `src/trn/trn_reward.c:637,643` — Kabuterimon/Kuwagamon (triggers 219/251) grant the ×6/×5 training bonus; `src/dget/dget.c:308-357` — tournament entry counts recruits over triggers 200..310. Both read the **vanilla** bits, so an AP-delivered recruit shows the gym NPC but does not grant the bonus, and cup entry follows the vanilla count. | `training_gym.state`, `arena_lobby.state` (exists) | **Decided and done 2026-08-28**: TRN **shipped** (always-on `TRN_GYM_BONUS_WORD_PATCHES`: the two `addiu` immediates in `TRN_REL.BIN` now read 739 / 771; three nets incl. 7 real sessions + an 84/84 mode sweep, `work/dw1_re/decomp/trn_gym_bonus/`); DGET **no** (cup tiers stay attached to Progressive Arena only, which the client's arena enforcer already guarantees — the vanilla count reader stays). |

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
- **Cave6 is code-full** (2026-08-29): 4 + 12 + 12 B left after the top-banner renderer; any new
  resident code must be claimed from the heap (the ITEM_PARA claim word, `0x80113AB4`).
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

1. **`BTL_calculateDamage` (BTL overlay 0x8005BEB8) — first target of the technique-data
   objective (§2.3).** ASM-only upstream, so it needs the pipeline: import `BTL_REL.BIN`
   (disc LBA 147703) into the Ghidra project at the address in dw_decomp `config/btl.yaml`
   (the lab's first overlay import), export, capture vectors from the three battle states,
   replay. **Answered 2026-08-29 by reading the overlay assembly** (rabbitizer over
   `BTL_REL.BIN`, `work/dw1_re/decomp/damage_formula/NOTES.md`): the matrix is a damage
   multiplier (Σ of the three defender-specialty cells / 30), `STD_calculateDamage` is
   byte-identical. What remains is only provenance: a VERIFIED replay of the pseudocode
   against the three battle states.
2. ~~**`.MMD` animation-table census**~~ done 2026-08-29 (`tools/dw1_mmd_census.py`): lists cannot
   grow; `species_technique_lists` shipped on that basis.
3. **Audit shipped assumptions against the C** — every `addresses.py` comment that says
   "inferred" or "static-census-derived" is now checkable (in progress 2026-08-28; the
   flight-table, IF-grammar and PP-calc rows are done).
4. ~~Wave-2 lab tooling: parse `include/dw/*.h` into a Ghidra data-type archive~~ done
   2026-08-28 (`DW1ImportHeaders.java`, 1827 types; typed globals applied).
5. Other ASM-only functions still worth our pipeline: `0x800E5B50` (104 callers),
   `unlearnMove`.
6. Re-capture `renderString` with the 0xE10 window (config change only) to convert 446 skips.
7. **Open user decision**: contribute our three verified models for functions still ASM-only
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
| ✅ `enemy_poc_battle.state`, `enemy_poc_icemon_battle.state` (captured 2026-08-28, unattended: warp + tamer teleport) | A field battle that has just started against a patched record / a substituted species; with `battle_pending.state`, the vector source for `BTL_calculateDamage` | Enemy stats (shipped); **technique-data objective** (next) | Done |
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
| Lab savestates (gitignored) | `work/dw1_re/*.state` (49; `debug_warp.state` is the teleport hub) |
| Savestate on any screen, unattended | `worlds/digimon_world/tools/dw1_warp_state.py --map <id> --out <name>` |
| Capture-session log (gitignored) | `work/dw1_re/session_2026-08-28_savestates.md` |
| BizHawk validation checklist (gitignored) | `work/dw1_re/BIZHAWK_SESSION_CHECKLIST.md` |
| Agents | `.claude/agents/{dw1-decomp,dw1-patch}.md` |
| Historical plan / reference notes | `PLAN.md`, `REFERENCES_NOTES.md` |
