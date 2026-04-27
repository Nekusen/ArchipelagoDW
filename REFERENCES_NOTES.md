# Reference projects — extraction notes

These are the findings from a study pass over the four projects under
`references/`. Every claim is cited as `<path>:<line>` so you can verify
without re-reading the clones.

The four references are not equally informative for the DW1 APWorld
architecture decision:

- **FFT Ivalice Island** is the highest-value reference. Its architecture
  (BizHawk + Nymashock + APProcedurePatch + the generic Lua connector) is
  exactly the path we should evaluate first.
- **SOTN** is **not** the multi-track-BIN/CUE reference that
  `references/README.md` and `CLAUDE.md` claim it is. SOTN does not patch
  the ROM at all; its grep score for `cue|track|audio|sector` across the
  Lua, the Python client, and `worlds/sotn/` is **zero matches**. Its real
  value is as a custom-Lua case study. See section 4 and section 5.
- **DWAP** has a smoking-gun bug at `Addresses.cs:46` that explains the
  bulk of its instability without further speculation:
  `RecruitmentFunctionAddress = 0x00000000`. Combined with
  `RecruitmentHook.cs:27-44`, this means the recruit-detection hook can
  never install. Recruit checks cannot fire at runtime.
- The **standalone randomizer** is the canonical catalog of DW1 ROM
  offsets and softlock fixes, but it does no sector-aware writing and no
  EDC/ECC recalculation. Its `.bin`-as-flat-bytestream approach is a
  shortcut we should not blindly inherit.

Citation conventions:

- DWAP: `references/DWAP/...:line`.
- Standalone randomizer: `references/digimon_world_randomizer/...:line`.
- FFT: `worlds/fftii/...:line`. **The world is on
  `references/fft_ivalice_island` branch `origin/finalfantasytactics`,
  not `main`.** Read via `git show origin/finalfantasytactics:<path>`.
- SOTN: `references/sotn_archipelago/...:line` (paths relative to the
  clone root: `SOTNClient.py` is at the root, the world is at
  `worlds/sotn/`, the Lua is at `data/lua/connector_sotn.lua`).

---

## 1. DWAP

### 1.1 Apworld layout

`references/DWAP/Apworld/dw1/`:

| File | Role |
| --- | --- |
| `__init__.py:31-381` | World subclass; six regions (Menu, Start Game, Cards, Prosperity, Digimon, Chests); hard-coded recruitment rules at lines ~270-315; `generate_output` (329-381) writes everything to `slot_data` for the C# client to consume. **No ROM patching at all.** |
| `Items.py:38-274` | 6 categories: Consumable=0, Misc=1, Event=2, Recruit=3, Skip=4, DV=5, Soul=6. Recruit IDs 1000-1049, Soul IDs 4000-4049. |
| `Locations.py:64-300` | 51 digimon recruits (69005000-69054000), 66 cards (69002000-69002065), 100 prosperity checks (69004000-69004099), 1 test chest (69001000). |
| `Options.py:7-81` | 9 options: Goal, RequiredProsperity, EarlyStatCap, ProgressiveStatCaps, GuaranteedItems, ExpMultiplier, RandomStarter, RandomTechniques, FastDrimogemon, EasyMonochromon. |
| `RecruitDigimon.py:11-63` | 51-entry table: `(name, prosperity_value, digimon_requirements, prosperity_requirement, requires_soul)`. Recruitment is modeled as a **static prerequisite graph**, not a state machine; iterative satisfiability check (10 iterations max) at `__init__.py:183-239`. |
| `docs/` | Setup notes; not architecturally interesting. |

### 1.2 C# runtime architecture

`references/DWAP/source/DWAP/` is an Avalonia + .NET app built on
ArsonAssassin's separate `Archipelago.Core` library
(https://github.com/ArsonAssassin/Archipelago.Core, **not** in the clone).
All emulator memory R/W goes through `Archipelago.Core` abstractions
(`Memory.WriteByte`, `Memory.Write`, `FunctionHook`); the DWAP source
itself contains no process-attach / handle-acquire / IPC code.

- `Randomiser.cs:11-78` — seeded RNG. Implements `Generate()` for starter
  randomization and `ShuffleAndWriteTechniques()`. Memory writes are
  **direct, sequential, unsynchronized**.
- `Hook/RecruitmentHook.cs:11-74` — function hook intended to fire on
  recruit-attempt. Constructed at line 29 with
  `IntPtr functionAddress = (nint)Addresses.RecruitmentFunctionAddress`.
- `RecruitmentEventArgs.cs` — event payload `{ DigimonId }` only.
- `StarterRandomisation.cs` — small enum + helpers.
- `DigimonStage.cs:9-16` — 0-indexed enum `{baby=0, intraining=1,
  rookie=2, champion=3, ultimate=4}`. Mismatches the standalone
  randomizer's 1-indexed encoding (see 5.1).
- `ItemType.cs:9-18` — mirrors Python categories exactly.
- `RandomiserOptions.cs` — runtime mirror of options for the C# side.

The C# client receives slot data directly from the Archipelago server
(via the standard Archipelago client protocol implemented in
`Archipelago.Core`), not from any patched ROM.

### 1.3 Memory map (`Addresses.cs:9-48`)

All values are **RAM** addresses (PSX main memory, not ROM offsets):

| Name | Address | Use |
| --- | --- | --- |
| LastScript | 0x00134FDC | Script execution pointer |
| MaxHp / MaxMp | 0x001557F0 / 0x001557F2 | Current digimon HP/MP cap |
| CurrentOffense / Defence / Speed / Brains | 0x001557E0 / 0x001557E2 / 0x001557E4 / 0x001557E6 | Live stats |
| InventorySize | 0x000DD4CE | Item count |
| ItemBankBaseAddress | 0x001BDF2C | Inventory start (50 items) |
| CurrentBits | 0x00134EB8 | Money |
| Starter1 / Starter2 | 0x000EE9D8 / 0x000EE9D0 | Starter slots |
| TechniqueSlot1 | 0x001557EC | Active technique 1 |
| TechniqueStartAddress | 0x0012623C | Technique data table |
| LearningChanceStartAddress | 0x00125FA4 | Learning-chance table |
| MonochromeProfitAddress | 0x0013500C | Monochromon minigame state |
| HasBeatenDrimogemon | 0x001BE130 | Drimogemon-defeated flag |
| MeramonTunnel_State / _DrimogemonState / _DiggingState | 0x001BE043 / 0x001BE042 / 0x001BE04F | Tunnel sub-state |
| CardStartAddress | 0x001bdfac | Card-deck table |
| ChartStartAddress | 0x001be00d | Town-map exploration flags |
| ProsperityPoints | 0x001BE032 | Current prosperity |
| **RecruitmentFunctionAddress** | **0x00000000** | **NEVER SET — see 1.5** |

These are useful as a starting RAM map. They tell us nothing about
**ROM offsets** (see 2.2 for that side of the story).

### 1.4 Hooks — `RecruitmentHook.cs`

Only one hook file exists. It targets a single function address and
fires `DigimonRecruited` when the function is hit:

```text
Hook/RecruitmentHook.cs:27-29
  IntPtr functionAddress = (nint)Addresses.RecruitmentFunctionAddress;
  _hook = new FunctionHook(functionAddress, OnRecruitmentAttempt,
                           hookSize: 5,
                           executeOriginalInstructions: false);
```

`OnRecruitmentAttempt` (lines 52-72) extracts a digimon id and a
recruited flag from the hook context. The comment on line 56 reads
`// Guesses for now`. There are no other hooks for chest pickup, item
acquisition, prosperity change, or anything else; the design relies on
either function-hooks (if more were ever installed) or memory polling
inside `Archipelago.Core` (which we cannot see).

### 1.5 Evidence-based instability assessment

Each of the following is grounded in a citation, not speculation.

1. **`RecruitmentFunctionAddress = 0x00000000`** at `Addresses.cs:46`.
   `_hook.Install()` at `RecruitmentHook.cs:32` will fail; line 41 logs
   `"Failed to install recruitment hook"` and execution continues. **At
   runtime, no recruit detection ever fires.** Any seed that randomizes
   recruits cannot send a single recruit-location check back to the
   server beyond the starter. This is the largest architectural defect
   visible without running the code.
2. **Unsynchronized direct memory writes**: `Randomiser.cs:55-74` writes
   to technique addresses with no queue, no acknowledgment, no read-back
   verification. The PSX game loop can rewrite the same bytes; race
   conditions are unmitigated. Contrast with FFT's design (3.3) which
   uses an `items_received` counter and per-category atomic writes that
   the game loop cannot stomp.
3. **Hard-coded rules in the World subclass** — `__init__.py:267-315`
   contains 51 manual recruit rules. Adding a new randomizable system
   requires editing rule code, not data tables. Contrast with FFT
   (`worlds/fftii/data/logic/topologies/*.py`), which keeps logic in
   data modules.
4. **Closed-source dependency**: `Archipelago.Core` is not in the
   clone. Its emulator-attach mechanism is opaque; behavior across
   DuckStation / PCSX / BizHawk versions is unverifiable. Any
   instability traceable to attach-by-process-name vs. fixed-handle
   resolution etc. cannot be assessed from the source we have.

These four points, especially (1), explain "why DWAP is unstable"
without any need for behavioral hand-waving.

---

## 2. Standalone randomizer (`digimon_world_randomizer`)

### 2.1 Pipeline shape

`references/digimon_world_randomizer/digimon_randomize.py` is the
top-level entry. It:

1. Reads a JSON config (general / digimon / techs / starter / recruit /
   evolution / items / patches sections).
2. Loads the user's `.bin` into memory via `DigimonWorldHandler` —
   single bytearray of the entire file.
3. Calls `randomizeDigimonData()`, `randomizeTechData()`,
   `randomizeStarterDigimon()`, `randomizeRecruitment()`,
   `randomizeEvolutions()`, `randomizeChestItems()`,
   `randomizeMapItems()`, `randomizeSeadramon()`, `applyPatch()`.
4. Writes the modified `.bin` back to disk, single pass.

Output: a modified `.bin`, no patch artifact. The user replaces their
file in-place (and presumably backs up first).

### 2.2 Randomizable systems catalog (ROM offsets)

All cited from `references/digimon_world_randomizer/digimon/data.py`.

| System | data.py lines | ROM offset / range | Record format |
| --- | --- | --- | --- |
| Digimon data block | 617-631 | 0x14D6E9DC, size 0x2A80, count 0xB4 | `<20sihh23Bx` |
| Evolution To/From | 633-638 | 0x14D6CE04, blockSize 0x3DA, count 0x3E | `<11B`; 5 sources + 6 destinations per digimon |
| Evolution stat gains | 645-649 | 0x14D6CA68, blockSize 0x39C | `<6HH` |
| Technique data | 571-581 | 0x14D66DF4, blockSize 0x8C0, count 0x79 | `<3H8Bxx` |
| Tech learn (battle) | 583-593 | 0x14D66A2C, blockSize 0x1DE, count 0x3A | `<BBB` |
| Tech learn (brain training) | 595-604 | 0x14C8E58C, blockSize 0x18, count 0x08 | `<BBB` |
| Tech tier list | 606-615 | 0x14C8E554, blockSize 0x38, count 0x07 | `<8B` |
| Chest items | 229-243 | 79 hardcoded offsets in 0x13FE3118-0x14081900 | `<BB` (id, qty) |
| Map item spawns | 245-307 | ~300 offsets in 0x13FE2800-0x140FECFA | `<BB` |
| Tokomon gifts | 540-550 | 6 offsets at 0x14071064-0x14071078 | `<BxBB` |
| Seadramon teach | 552-569 | 4 learn + 4 check offsets | `<2B` / `<B` |
| Special-evolution overrides | 504-538 | 14 offsets | `<B` |
| Recruitment triggers | 309-502 | 51 offset tuples in 0x14059A40-0x140B9BDA | `<H` |
| Starter digimon | 189-192 | (constraint, not direct offset) | `<B` |

This catalog is **the** value of the standalone randomizer. DWAP has
zero ROM offsets; together they form a complete picture for DW1.

### 2.3 BIN handling — what's NOT here

`references/digimon_world_randomizer/digimon/handler.py`:

- Reads `.bin` as a flat bytearray; writes it back as a flat bytearray.
- **No CUE parsing.** No multi-track awareness. The user is expected to
  hand it the data track only or a single-track ISO.
- **No sector-aware writing.** Offsets are absolute byte positions
  inside the `.bin`.
- **No PSX EDC/ECC recalculation.** If the original sectors had ECC the
  randomizer trusts it as-is; if a patch crosses a sector boundary the
  ECC for that sector is now stale. This works for DW1 in practice
  (otherwise the project would not have shipped) but it is not a
  correctness guarantee.

For our purposes: **we cannot inherit the standalone's patcher
verbatim if we ever need sector-correct writes.** FFT's
`Mode2/2352`-aware approach (3.2) is the model we'd use instead.

### 2.4 Bug-fix / softlock catalog

| Issue | data.py / handler.py line | Mechanism |
| --- | --- | --- |
| Toy Town softlock | data.py:508-509 | `unlockToyTownValue = 0x015D0001` written to `0x140479EA` via `applyPatch('unlock')` |
| Greylord / Ice Sanctuary type lock | data.py:198-218 | `unlockGreylordValue = 1226`, `unlockIceValue = 60` |
| Stat gain on evolution items | data.py:197-200 | `evoItemPatchValue = 0x00` to `evoItemPatchOffset = 0x14CF5AFC` |
| Tier-1 brain-training tech learn rate | data.py:221-224 | `tierOneTechLearnValue = 0x28` to `0x14C8E58C` (40% chance) |
| EntityMoveTo softlocks | handler.py (softlock) | 4 movement-related patches |
| Rotation softlock | handler.py (softlock) | One movement patch |
| Leomon Cave Nanimon softlock | data.py:484 | Recruit-tuple has empty Jijimon-action list |
| Ogremon 2 / Ogremon 3 mutual-exclusion softlock | comment-only in data.py | Note that prior implementations prevent both being active simultaneously; current implementation status unclear |

### 2.5 Implicit progression logic — access-rule notes for Phase 2

The standalone randomizer does not encode AP-style access rules
explicitly. The progression is encoded indirectly via recruit-trigger
lists (data.py:309-502) and DW1's gameplay constraints. From a careful
read of those tables and the recruitment table in DWAP
`RecruitDigimon.py:11-63`, the implicit gates are:

1. **Agumon (starter)** — always available. Root of the recruit graph.
2. **Early Rookies** (Betamon, Kunemon, Palmon, Elecmon, Patamon,
   Biyomon, Sukamon) — require Agumon, prosperity ≥ 1.
3. **Meramon** — requires `EarlyStatCap` or equivalent, Agumon, plus
   either Coelamon or Betamon. Source: DWAP `__init__.py:276`.
4. **Whamon** — requires prosperity ≥ 6 OR Meramon, Agumon. Source:
   DWAP `__init__.py:290`.
5. **Numemon** — Whamon + Agumon + prosperity ≥ 6.
6. **Giromon, Andromon** — Whamon + Numemon + Agumon + prosperity ≥ 6.
7. **Drimogemon** — Meramon + Agumon, plus the runtime flag at
   `0x001BE130` flipping (i.e. the actual fight has been won). DWAP
   exposes `fast_drimogemon` to bypass; the standalone patches via
   `applyPatch('softlock')`.
8. **Greymon** — prosperity ≥ 15 (Meramon must be recruited first to
   reach that level under default progression).
9. **Late Champions / Ultimates** (Piximon, SkullGreymon, Ninjamon,
   Devimon, Leomon, Etemon, Megadramon, Airdramon, Digitamamon) —
   prosperity ≥ 50.
10. **Vademon** — prosperity ≥ 45, Meramon, Shellmon.
11. **Toy Town access** — depends on Monzaemon special-evolution and
    the unlock-patch at `0x140479EA`. In an AP context this becomes a
    Region with an entrance gated on the appropriate item / event.

When we begin `worlds/digimon_world/rules.py` we should encode these
rules in Rule Builder syntax (`Has(...) | HasAll(...)`), not lambdas,
per `CLAUDE.md`'s style guidance.

### 2.6 Patcher technique

- Format: raw byte writes to `.bin` offsets. Not bsdiff, not IPS, not
  PPF, not xdelta.
- Output: a fully-rewritten `.bin` (one per seed).
- No verification (no MD5 check, no EDC recalculation, no sector
  reassembly).

This is exactly what we should NOT inherit if we want a clean,
shippable patcher.

---

## 3. FFT Ivalice Island

The world lives at `worlds/fftii/` on
`references/fft_ivalice_island` branch `origin/finalfantasytactics`.
This is the highest-value reference; its architecture is the one we
should evaluate first for DW1.

### 3.1 World package layout

```text
worlds/fftii/
├─ __init__.py          # World subclass; lifecycle hooks; slot data; settings
├─ Rom.py               # APProcedurePatch + APTokenMixin patcher
├─ Client.py            # BizHawkClient subclass
├─ Items.py             # builds item_table from data/*.py
├─ Locations.py         # builds all_locations from data/logic/topologies/*
├─ Logic.py             # lambda-based logic_rule()
├─ Options.py           # dataclass with option groups
├─ ErrorRecalc.py       # PSX EDC block recalculation post-patch
├─ archipelago.json     # manifest (game name, version 0.3.0, authors)
├─ data/
│  ├─ items.py          # zodiac stones, jobs, characters, etc.
│  ├─ locations.py      # story battles, sidequests, recruits, jobs, ...
│  ├─ memory.py         # RAM addresses + ROM/CD identifiers
│  ├─ text.py           # PSX text encoding for victory messages
│  └─ logic/
│     ├─ Connection.py   # destination + requirement list
│     ├─ FFTRegion.py    # region container
│     ├─ FFTLocation.py  # custom location with battle-level + reqs
│     ├─ Requirement.py  # AND (items_needed) + OR (other_requirements)
│     ├─ Requirements.py # subclasses (HasMurondPass, ...)
│     ├─ JobUnlocks.py   # job-unlock condition dict
│     ├─ Monsters.py     # poach data + RegionAccessRequirement
│     ├─ regions/*.py    # FFTRegion subclasses (one per region)
│     └─ topologies/*.py # mutate region instances to attach connections + locations
├─ docs/                # setup, faq, how-to-play, known issues, references
├─ enemyrando/          # 17 files; ENTD-level enemy mutation
├─ patchersuite/        # Sector.py, ENTDEntry.py, Unit.py
├─ fftiiapjobs.bsdiff4
├─ fftiivanillajobs.bsdiff4
└─ test/                # unit tests
```

The clean separation between `data/logic/regions/` (structure) and
`data/logic/topologies/` (content) is worth copying for DW1 — it lets
adding a new region not collide with adding a new connection.

### 3.2 `Rom.py` — the APProcedurePatch shape (verified)

I directly read this file. The class declaration is

```text
worlds/fftii/Rom.py:38-40 (FinalFantasyTacticsIIPatchExtension)
worlds/fftii/Rom.py:381-396 (FinalFantasyTacticsIIProcedurePatch)
class FinalFantasyTacticsIIProcedurePatch(APProcedurePatch, APTokenMixin):
    hash = "b156ba386436d20fd5ed8d37bab6b624"  # MD5 of vanilla .bin
    patch_file_ending = ".apfftii"
    result_file_ending = ".cue"
    procedure = [("patch_bin", ["patch_file.json"])]
```

The procedure points at one method `patch_bin()` (lines 159-186) that:

1. Loads the user's vanilla `.bin` via
   `get_settings().fftii_options.rom_file` (line 32).
2. Reads the embedded `patch_file.json` (a token bundle generated by
   `generate_output()`).
3. Selects a pre-built bsdiff4 file by option:
   `fftiiapjobs.bsdiff4` if `patch_dict["APJobs"] == 1`,
   else `fftiivanillajobs.bsdiff4` (lines 162-167).
4. Applies the bsdiff4 to the ISO (`bsdiff4.patch(iso, base_patch)`).
5. OR's option flag bits into specific bytes (`RareBattles`,
   `Sidequests`, `FinalBattles`, `EXPMultiplier`, `JPMultiplier`, ...).
6. Sector-aware writes the per-location victory text via
   `write_text_to_location()` (lines 44-65). Sector layout is **PSX
   Mode2/2352**:
   - `sector_size = 0x930` (2352 bytes)
   - `data_size = 0x800` (2048 bytes)
   - `header_size = 0x18` (24 bytes)
   - `ec_size = 0x118` (280 bytes ECC)
   The writer skips header+ECC zones, jumping to `data_end + other_size`
   when crossing a sector boundary. **These are the magic numbers we'll
   need if DW1 also uses Mode2/2352.**
7. Decomposes the ENTD region (battle-formation table) at
   `entd_start = 0x0875FD30`, four copies of 40 sectors each, into
   `Sector` instances; mutates units via `RandomizedUnitFactory`;
   reassembles header + data + ECC; blits back into the ISO.
8. Writes ROM-name (20-byte UTF-8) and seed-hash (LE u16) tokens into
   well-known RAM addresses.
9. The post-patch step in `Rom.py:375-396` runs `ErrorRecalculator`
   (in `ErrorRecalc.py`) to recompute EDC blocks across the patched
   sectors, then emits a `.cue` file referencing the patched `.bin`.

### 3.3 `Client.py` — the BizHawkClient subclass

```text
worlds/fftii/Client.py:48-51
class FinalFantasyTacticsIvaliceIslandClient(BizHawkClient):
    game = "Final Fantasy Tactics Ivalice Island"
    system = "PSX"
    patch_suffix = ".apfftii"
```

- **`validate_rom`** (lines 58-78): reads CD volume name `"SCUS_942.21"`
  (11 bytes at `0x9304`, the standard ISO9660 PVD location) AND the
  slot ROM-name from a fixed RAM offset. If the ROM-name is zeroed,
  `validate_rom` returns False (unpaired slot). Sets
  `ctx.items_handling = 0b111` and `ctx.want_slot_data = True`.
- **`game_watcher`** (lines 81-102): polls in three pathways per tick:
  1. `check_major_locations()` — bitfield diff at `event_flags_location`
     (0x05791C, 0x224 bytes).
  2. `check_poaches()` — bitfield diff at `poaching_flags_location`.
  3. `check_job_unlocks()` — read unit stats at 0x057F74, unpack nybbles
     for per-unit job levels, evaluate `JobUnlocks` conditions.
- **Item-receive** (lines 105-172): a 2-byte LE counter at
  `items_received_low/high` (0x578CE / 0x578CF) tracks how many items
  have been applied. The loop checks
  `if items_received_count < len(ctx.items_received)` and dispatches by
  item category (gear → inventory write; gil → 4-byte add; zodiac
  stones → 2-byte bitfield OR; jobs → bitfield OR; characters →
  event-flag OR; JP → per-job add; Ramza form → two-flag OR; progressive
  shop → byte increment, capped 15). Each dispatch increments the
  counter so the game loop can't double-apply.
- **Goal completion** (lines 174-180): presence of
  Graveyard-of-Airships-2 location id in `ctx.locations_checked` →
  send `ClientStatus.CLIENT_GOAL`.
- **DeathLink**: not implemented.

### 3.4 World subclass (`__init__.py`)

Lifecycle hooks populated: `stage_assert_generate`,
`stage_write_spoiler_header`, `create_regions`, `create_items`,
`set_rules` (lines 344-370 — pure lambda-based via `LogicObject`,
**not** Rule Builder), `fill_slot_data` (423-446),
`generate_output` (builds `patch_dict` JSON, packages into
APProcedurePatch, writes `.apfftii`), and `modify_multidata`.

Slot data is rich — 11 fields including `zodiac_stones_required`,
`poach_hints`, `poach_database` — pre-computed on the generation side
to avoid expensive client-side discovery (3.3).

### 3.5 Setup flow (user-facing)

From `worlds/fftii/docs/multiworld_en.md` and `how_to_play.md`:

1. Install BizHawk (with Nymashock PSX core).
2. Install the Archipelago Launcher.
3. Provide a vanilla USA `.bin` (MD5 `b156ba386436d20fd5ed8d37bab6b624`).
4. Configure YAML; submit to host; receive `.apfftii`.
5. Double-click `.apfftii` → patcher reads `host.yaml`'s `rom_file`,
   produces `<name>patched.bin` + `<name>patched.cue`.
6. Open the `.cue` in BizHawk.
7. Tools → Lua Console → load
   `data/lua/connector_bizhawk_generic.lua` (the **generic** connector,
   not a game-specific one).
8. Connect via the Archipelago client; play.

### 3.6 `enemyrando/` and `patchersuite/`

- `enemyrando/` (17 files) — battle-roster mutation. Reads vanilla
  units from ENTD, maps to randomized destination jobs/sprites under a
  seeded `Random`, applies via `RandomizedUnitFactory`. Includes
  poach-discovery and hint pre-computation. Skippable for our purposes.
- `patchersuite/` (4 files) —
  - `Sector.py` splits/reassembles 2352-byte sectors.
  - `ENTDEntry.py` parses and mutates 24-unit battle-formation records.
  - `Unit.py` parses individual unit fields (job, sprite, gender).
  - `__init__.py` exposes the API.

These are the building blocks of any sector-aware patcher; if DW1
needs Mode2/2352-correct writing, this is the pattern to copy.

---

## 4. SOTN Archipelago

### 4.1 World package layout

`references/sotn_archipelago/worlds/sotn/`:

| File | Role |
| --- | --- |
| `__init__.py:24-51` | World subclass; populates `create_regions`, `create_items`, `set_rules`. **No `generate_output` override**. |
| `Items.py:14-56` | 41 items in ID range 620000-621000: relics (Soul of Bat, Echo of Bat, the five Vlad pieces, ...), progressive equipment, Life Max Up filler. |
| `Locations.py:16-26` | 53 locations in two ID groups: 135000-135040 (normal castle) and 140000-140016 (inverted castle). |
| `Regions.py:8-42` | 27 regions with conditional entrances; metroidvania-standard item-as-key + relic-as-ability + area-locks. |
| `Logic.py` | Rule helpers (e.g. `can_fly`, `can_double_jump`, `can_save_richter`). |
| `Options.py` | Standard option dataclass. |
| `docs/sotn-en.md` | Setup; warns against pre-existing saves (line 32-35). |

The flat-files-at-root layout (no `data/`, no nested `logic/`) is much
simpler than FFT's organization. Suitable for smaller scopes; less
useful for scopes with many regions.

### 4.2 No ROM patching

`worlds/sotn/__init__.py` has no `generate_output` override and no
patch class anywhere in the world package. SOTN ships nothing
ROM-side. All state hand-off is Archipelago-server → client (TCP) →
Lua → game RAM.

### 4.3 Custom Lua connector (`data/lua/connector_sotn.lua`)

This is the central artifact and the reason this reference exists in
the study set. The Lua opens its own TCP server on
`localhost:52980` (line 406) and runs a per-frame loop using
`emu.frameadvance()` (lines 367, 374, 377, 379, 407, 412, 414, 428).

What it does that the generic connector cannot:

1. **Per-frame in-game-event detection** with game-context awareness:
   - **Bosses** (lines 233-248): RAM addresses → defeated boss state;
     maps to location IDs.
   - **Relics by proximity** (lines 251-284): reads player XY + room id
     + tolerance radius; checks proximity to hardcoded relic spawn
     points. **Sends the location check the frame the player walks
     into the spawn.**
   - **Cutscenes by XY** (lines 287-305): triggers on story beats
     (meet Maria, see Evil Richter) when player position matches.
   - **Prologue safety** (lines 308-320): special path if Lua was
     loaded after prologue began.
2. **Real-time anti-cheat write-back loop** (lines 153-156, 176-186):
   if the player grabs a relic that AP has not granted, the Lua writes
   0 back to the relic ownership byte the same frame, denying the grab.
3. **Game-zone-aware item-distribution gating** (lines 359-366): items
   are cached and not delivered if `zone == 6300` (prologue), to avoid
   inserting items before the player has real control.
4. **Dracula HP underflow detection** for victory (lines 323-339).

A generic JSON-RPC connector that exposes only `read_*` / `write_*`
RAM operations could not implement (1)-(3) cleanly without the Python
client polling at very high frequency, which is impractical over the
JSON-RPC transport.

### 4.4 SOTNClient.py (the older client pattern)

`SOTNClient.py` lives at the **clone root**, not in `worlds/sotn/`. It
is a `CommonContext` subclass (pre-`_bizhawk` framework) — older than
the FFT pattern. It opens a TCP socket on `localhost:52980` to talk
**to the Lua** (the Lua is the server, the Python is the client). The
protocol is plain JSON over the socket: client sends
`{"items": [item_id, ...]}`; Lua sends back
`{"locations": [...], "victory": bool, "player": "SOTN"}`.

Slot auth is purely textual (no ROM hash check). Read/write timeouts
are 5s/1.5s.

### 4.5 Multi-track BIN/CUE handling — there is none

I directly grep'd the entire SOTN clone for
`cue|track|audio|sector|multi.?track`:

- `data/lua/connector_sotn.lua`: zero matches except line 406's TCP
  `socket.bind`.
- `SOTNClient.py`: zero matches.
- `worlds/sotn/`: zero matches.

The `.gitignore` has `*.BIN` and `*.cue` lines so users don't commit
their ROM, but no code processes either file format.

**SOTN is not a multi-track-BIN/CUE reference.** The
`references/README.md` and `CLAUDE.md` characterizations on this point
are wrong. The user is expected to load a vanilla disc (BIN+CUE pair
or single BIN) directly into BizHawk; the Lua and client never touch
the disc image.

### 4.6 Trade-offs vs. FFT (generic vs. game-specific Lua)

| Dimension | FFT (generic Lua) | SOTN (custom Lua) |
| --- | --- | --- |
| Location detection | RAM bitfield diff polled by Python client | Per-frame Lua-side checks (bosses, relics, cutscenes, prologue) |
| Anti-cheat / state guards | None needed (location checks are bytes that the game itself sets) | Required (relic grab denial; prologue caching) |
| Patch payload | Heavy (`Rom.py`, ENTDEntry, sectors, EDC) | None (game runs vanilla) |
| Maintenance burden | Patcher is a real artifact you maintain across game versions | Lua-side game-specific code in addition to the world |
| When is it the right call? | Game where checks correspond to flag bytes the game sets and items can be applied by writing bytes the game won't stomp | Game where checks need positional / event context the generic connector can't expose |

For DW1, most events DWAP cared about (recruit flags, prosperity,
chest pickups) are RAM flag bytes. The generic-Lua model fits, unless
we discover a cohort of events that don't leave a stable trace.

---

## 5. Cross-cutting findings

### 5.1 DWAP vs. standalone randomizer fact comparison

Both projects make claims about DW1 internals. Most "disagreements" are
the same fact in two encodings; only one is a real fact-level
disagreement.

| Fact | DWAP | Standalone | Status |
| --- | --- | --- | --- |
| RAM addresses | 21 listed (Addresses.cs:16-46) | None (operates on ROM offsets) | Different scopes; **union** is the useful map |
| ROM offsets | None | Full catalog (data.py — see 2.2) | Different scopes; **union** is the useful map |
| Recruitment count | 51 (RecruitDigimon.py:11-63) | 50 trigger entries (data.py:309-502) | Same data; standalone excludes Agumon (in-town starter, not a recruit-trigger entry). No conflict. |
| Drimogemon gate | Runtime flag at `0x001BE130` + `fast_drimogemon` option | Static recruit-trigger override + softlock patch | Same gate, different layer (runtime vs. ROM). No conflict in fact. |
| Toy Town softlock | `fast_drimogemon` option (Options.py:46-48) | Unlock-patch `0x015D0001` to `0x140479EA` (data.py:508-509) | Same softlock acknowledged. Different fix mechanism. No conflict in fact. |
| Stage encoding | 0-indexed enum (`DigimonStage.cs:9-16`) | 1-indexed hex (`data.py:28-34`) | Same five stages, different encoding. No conflict in fact. |
| Item-type taxonomy | 7 categories (ItemType.cs:9-18) | Not present (handler operates on offsets) | Only DWAP has it (apworld-specific). |
| Recruitment model | Static prerequisite graph (no time gates) | Static prerequisite triggers (no time gates) | **Agree**: both flatten DW1's actual day-by-day recruit state machine into a static graph. Whether that's accurate to the game is an open question (see 5.4). |

**Real fact-level disagreement count: zero.** The differences are
mostly different-perspective-on-same-fact. The `RecruitmentFunctionAddress`
field is unique to DWAP; the standalone has no need for it because it
patches the ROM rather than hooking the runtime.

### 5.2 DWAP vs. FFT/SOTN architectural divergences

| Dimension | DWAP | FFT | SOTN |
| --- | --- | --- | --- |
| Client process | External C# Avalonia app | In-process Python `BizHawkClient` | In-process Python `CommonContext` (older) |
| Emulator transport | `Archipelago.Core` (closed-source) | `_bizhawk` JSON-RPC + generic Lua | Custom TCP socket + custom Lua |
| ROM patching | None | bsdiff4 + token-list + sector-aware ENTD + EDC recalc | None |
| Event detection | Function hook at fixed address (**unset**) | RAM bitfield diff (3.3 step 6) | Per-frame Lua poll with positional logic |
| Item delivery | Direct memory writes, unsynchronized | `items_received` counter + per-category atomic writes | Per-frame Lua write-back with anti-cheat |
| Slot auth | Slot-name passed via standard AP protocol | Slot-name written to RAM by patcher; client reads it back | Slot-name typed by user |

The DWAP-vs-FFT/SOTN divergences that are most plausibly load-bearing
for DWAP's instability:

1. **Function-hook vs. flag-poll for event detection.** Function hooks
   require a known, version-stable function address. FFT and SOTN both
   poll RAM flags. Polling tolerates address drift and per-version
   game changes; hooking does not. DWAP's chosen address
   (`0x00000000`) is an extreme case that proves the failure mode.
2. **Direct unsynchronized writes vs. counter-driven atomic dispatch.**
   FFT's `items_received` counter pattern is robust to game-loop
   interference; DWAP's direct writes are not.
3. **Closed-source emulator transport.** FFT's `_bizhawk` framework is
   in-tree and inspectable; `Archipelago.Core` is not.

### 5.3 Generic Lua vs. custom Lua — decision criteria for DW1

Choose generic if:
- All randomized location checks correspond to RAM flag bits the game
  itself sets at pickup / event time.
- All randomized items can be applied by writing bytes the game-loop
  will not immediately overwrite (or by using FFT's
  counter-and-atomic-write pattern).
- No anti-cheat write-back is needed because either the player can't
  reach an item early, or reaching it early is harmless.

Choose custom Lua if:
- A material number of checks need positional / event-context detection
  (XY proximity, dialogue triggers, frame-precise events).
- Per-frame anti-cheat write-back is needed (e.g. the game hands the
  player a permanent ability that AP wants to gate).
- The patcher cost is undesirable (SOTN's case — they accept "no
  patching, but custom Lua" as the trade-off).

For DW1 specifically: most of DWAP's address map is flag bytes
(`HasBeatenDrimogemon`, `ProsperityPoints`, `MeramonTunnel_*`, item
slots in `ItemBankBaseAddress`). The generic-Lua model is the
default-favored choice. The only credible reason to escalate to a
custom Lua would be DW1's day-cycle / time-of-day loop introducing a
cohort of events without stable RAM-flag traces — which we cannot
confirm without doing RE work in BizHawk.

### 5.4 SOTN reference characterization correction

The `references/README.md` claims SOTN is the
"PS1 multi-track BIN/CUE reference." The
"Notes for Claude" section in `CLAUDE.md` repeats this. **The code
does not support that claim.** SOTN's actual contribution to the
study is:

1. A working example of a custom Lua connector + pre-`_bizhawk`
   client.
2. A worked example of per-frame in-game-event detection with
   anti-cheat semantics.
3. A demonstration that an Archipelago world can ship without any ROM
   patcher at all.

These are useful, but not what the project notes promise. Recommend
updating `references/README.md` and the SOTN entry in `CLAUDE.md` to
match the code-supported description.

### 5.5 What is still unknown after the read

1. **MVP scope (PLAN.md Q5).** Cannot be answered from references; a
   user decision.
2. **Whether DW1 needs sector-correct (Mode2/2352) writes** vs. flat
   `.bin` writes. The standalone randomizer used flat writes
   successfully but the codebase shows no EDC awareness — we don't
   know if its outputs would survive a stricter emulator. FFT's
   approach is the safe default.
3. **The recruit-event hook site that DWAP left as `0x00000000`.** A
   real RE deliverable if we ever need synchronous recruit detection.
   For a flag-poll approach we don't need it.
4. **Multi-track CUE handling for SLUS-01032.** No reference answers
   this. We'd need to inspect a clean dump.
