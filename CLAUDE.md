# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository overview

This is a fork of [ArchipelagoMW/Archipelago](https://github.com/ArchipelagoMW/Archipelago)
(remotes: `origin` = `Nekusen/ArchipelagoDW`, `upstream` = `ArchipelagoMW/Archipelago`).
Default branch for PRs upstream is `main`. Archipelago is a multiworld randomizer framework: the core
generates and serves a "multiworld" composed of one or more game-specific "worlds" living in [worlds/](worlds/).

Python 3.11 – 3.13 are the supported versions (CI runs 3.11.2, 3.12, 3.13). Worlds must keep working on the
oldest supported version.

## Common commands

Most workflows assume the working directory is the repo root.

| Task | Command |
| --- | --- |
| Install / update deps (uses pinned [requirements.txt](requirements.txt)) | `python ModuleUpdate.py --yes` |
| Generate `host.yaml` if missing | `python Launcher.py --update_settings` |
| Run the launcher (entry to clients, "Generate Template Options", "Build APWorlds", etc.) | `python Launcher.py` |
| Generate a multiworld from yamls in `Players/` | `python Generate.py` |
| Host a generated multiworld locally | `python MultiServer.py path/to/AP_xxx.zip` (add `--log_network` to debug protocol) |
| Run the WebHost site locally | `python WebHost.py` (copy [docs/webhost configuration sample.yaml](docs/webhost%20configuration%20sample.yaml) to `config.yaml` to override) |
| Run all tests | `pytest` |
| Run tests in parallel | `pytest -n auto` (or `-n12`) |
| Run one world's tests | `pytest worlds/<world>/test` |
| Run a single test | `pytest worlds/<world>/test/test_foo.py::TestClass::test_method` |
| Lint | `ruff check` (config in [ruff.toml](ruff.toml), 120-col, `target-version = py311`) |
| Type-check | `mypy` (uses [mypy.ini](mypy.ini); custom stubs live in [typings/](typings/)) |
| Build a frozen distribution | `python setup.py build_exe` (Linux AppImage: also `python setup.py bdist_appimage`) |
| Build `.apworld` zips for distribution | `python Launcher.py "Build APWorlds"` (output: `build/apworlds/`) |

[pytest.ini](pytest.ini) sets `testpaths = test worlds`, so `pytest` from the root picks up both core tests
and any `test_*.py` inside any world's `test/` package.

CI is wired in [.github/workflows/unittests.yml](.github/workflows/unittests.yml) and runs `pytest -n auto`
plus a separate `test/hosting/__main__.py` job that exercises live hosting.

## Big-picture architecture

### Top-level entry points

The repo root is full of single-file entry points; they do not form a package. Key ones:

- [Generate.py](Generate.py) — reads yaml files in `Players/`, drives the generation pipeline, writes
  the multiworld archive (`AP_*.zip`) to `output/`.
- [Main.py](Main.py) — orchestrates one generation: instantiates each player's `World`, runs the world
  lifecycle hooks (`generate_early` → `create_regions` → `create_items` → `set_rules` → `pre_fill` →
  `fill` → `post_fill` → `generate_output`), then calls [Fill.py](Fill.py) to place items.
- [MultiServer.py](MultiServer.py) — async websocket server that hosts a generated multiworld and
  speaks the protocol described in [docs/network protocol.md](docs/network%20protocol.md).
- [Launcher.py](Launcher.py) — Tk-style GUI dispatcher. Worlds register `Component`s via
  [worlds/LauncherComponents.py](worlds/LauncherComponents.py); the Launcher discovers them at runtime.
- [WebHost.py](WebHost.py) — boots the Flask app under [WebHostLib/](WebHostLib/) (the `archipelago.gg`
  site, including generation queue, room hosting, and tracking).
- [BaseClasses.py](BaseClasses.py) — `MultiWorld`, `Region`, `Entrance`, `Location`, `Item`,
  `CollectionState`. Read this before touching anything cross-world.
- [Options.py](Options.py) — base option types (`Toggle`, `Choice`, `Range`, `OptionSet`, …) plus
  `PerGameCommonOptions`. Worlds extend this dataclass.
- [settings.py](settings.py) — `host.yaml`-backed user-machine settings (ROM paths, etc.). Different
  from per-generation options.
- [NetUtils.py](NetUtils.py) — protocol enums and packet helpers shared by server, clients, and webhost.

### Worlds

Each game lives in [worlds/](worlds/) as its own Python package. The package is auto-discovered through
the `AutoWorldRegister` metaclass in [worlds/AutoWorld.py](worlds/AutoWorld.py); simply defining a class
inheriting from `World` with a `game = "..."` attribute registers it. There is no manual registry.

A typical world package contains: `__init__.py` (the `World` subclass), `options.py`, `items.py`,
`locations.py`, `regions.py`, `rules.py`, optionally `client.py`, and a `test/` package whose
`bases.py` defines a `WorldTestBase` subclass (see [docs/tests.md](docs/tests.md)).

Worlds intended to be shipped as separate `.apworld` zip files must use **relative imports for
intra-world code** (`from .options import ...`) and absolute imports for everything outside. See
[docs/apworld specification.md](docs/apworld%20specification.md) for the metadata file format
(`archipelago.json`).

When extending the engine, two utilities matter:

- **Rule Builder** ([rule_builder/](rule_builder/), docs in [docs/rule builder.md](docs/rule%20builder.md)):
  newer worlds prefer composable `Has(...) | HasAll(...)` rules over lambdas. Use the bitwise `&` / `|`
  operators (boolean `and`/`or` are explicitly disallowed). Worlds can inherit from
  `CachedRuleBuilderWorld` to opt in to lazy evaluation/caching.
- **Entrance randomization** ([entrance_rando.py](entrance_rando.py), docs in
  [docs/entrance randomization.md](docs/entrance%20randomization.md)).

### Important world-implementation gotchas

- Item and location IDs must be unique within a world. They share a numeric namespace per world but can
  overlap across games. Keep IDs in `1 .. 2**31 - 1`.
- IDs ≤ 0 are reserved globally — don't use them.
- An access rule on an `Entrance` that calls `state.can_reach_*` **must** be paired with
  `multiworld.register_indirect_condition(...)` or generation can become non-deterministic. Set
  `World.explicit_indirect_conditions = False` only if you are deliberately accepting the perf hit.
- Events ("fake" items/locations with `id=None`) are real during generation; place them with
  `Location.place_locked_item(...)` before fill. The standard goal pattern is a `Victory` event item
  + `multiworld.completion_condition[self.player] = lambda state: state.has("Victory", self.player)`.
- After `create_items` finishes, items and regions must not be added to the multiworld (use
  `get_pre_fill_items` if you need to place items in `pre_fill`).

### Tests

[test/](test/) holds shared infrastructure:

- [test/bases.py](test/bases.py) — `WorldTestBase` and helpers like `assertAccessDependency`.
- [test/general/](test/general/) — generic tests (reachability, fill, IDs, options, manifests, …) that
  run against **every** registered world. New worlds get these for free; don't break them.
- [test/param.py](test/param.py) — Archipelago is test-runner-agnostic. Do not use
  `@pytest.mark.parametrize`; use the helpers here. Use `unittest.subTest` for cheap parametrization but
  prefer per-method tests when individual timing/parallelism matters.
- [test/hosting/](test/hosting/) — exercised by a separate CI job, not via plain `pytest`.

Goal: individual tests under one second so `pytest -n auto` parallelizes well. For very expensive
"fuzz" generation, gate it behind `@unittest.skipIf(env-var-not-set)` rather than running it on every CI
run.

## Style notes that aren't obvious

These come from [docs/style.md](docs/style.md) and the ruff config and override defaults:

- 120 character line limit (Python, Markdown, everything).
- Double-quote strings; single quotes inside f-strings (`f"like {d['k']}"`).
- Prefer modern type annotations (`dict[str, int | None]`, not `Dict[str, Optional[int]]`) for new
  code.
- `assert False` is intentional and used as a release-time-eliminated invariant, so ruff's `B011` is
  disabled. Don't replace these with `raise`.
- Local imports (inside functions) are accepted and sometimes necessary — `PLC0415` is disabled.
- Keep `open(..., "r")` explicit; `UP015` is disabled on purpose.
- New core classes/methods should have reST-style docstrings; world code is held to a softer bar but
  must be internally consistent.

## Working with this fork

- `upstream/main` is the canonical Archipelago history. New PRs targeting upstream should rebase on it.
- This fork's working branches (e.g. `digimon-world-ps1`) typically host an in-progress `.apworld`
  living under [worlds/](worlds/). When adding a new world, also wire up generic tests by giving it a
  `test/` package with a `WorldTestBase` subclass — without this the generic test suite still runs
  against the world but you'll have no game-specific coverage.
- Shipping a world separately: package with the Launcher's "Build APWorlds" component rather than
  zipping by hand, so the `archipelago.json` metadata (`version`, `compatible_version`) is filled in
  correctly. Filenames must be lowercase or frozen Python will fail to import.


## Project: Digimon World 1 (PS1) APWorld

- **Goal**: build a stable Archipelago world for Digimon World 1 (PS1, USA build).
  A previous community implementation exists but is unstable; this project is a
  rewrite from scratch.
- **Working branch**: `digimon-world-ps1`
- **World package location** (target): `worlds/digimon_world/`
- **Live status, roadmap and RE requirements**: [STATUS.md](STATUS.md) — read it first when
  resuming. The summary below is a snapshot; STATUS.md is the file that gets updated.
- **Current status** (2026-08-22): fully functional world, `world_version 0.6.0`.
  Core generation/patcher/client are complete and the v1 feature set is
  in; the project is now in a feature-expansion + polish phase. The 2026-08
  implementation batch shipped, all lab-validated through the three
  PATCH_PROCESS nets and disc-boot byte-verified, and committed on
  `digimon-world-ps1`:
    - Physical **region-gate** enforcement for `region_locking` (walk-on
      loop-back wrapper + 12 script-class gates + Birdramon-flight gating;
      flight fares zeroed as QoL).
    - **ITEM_PARA relocation** to a contiguous 256-slot table on
      heap-claimed RAM (ext ceiling 173 → 255; merit teleports retired).
    - **Shopsanity** — per-shop off/coexist/replace for all four shops
      (item/secret/recycle/merit) + tiered-or-randomized pricing.
    - **Card-trade multiplier** and the **Piximon Training Manual** check.
    - QoL: recruit-location opt-out toggles, the **Archipelago logo** item
      icon, chest delivery hardening, inventory-first item delivery,
      **infinite Auto Pilot**, and the **Coelamon** recruit-loop fix
      (location restored to the pool).
  Remaining (see the `dw1-backlog` / `dw1-impl-batch-design` memories):
  the user's BizHawk validation session, Phase 5 setup docs, the
  region-locking option-integration pass, and deferred big features
  (enemy randomization, in-game notifications).
- **2026-08-29**: standalone-randomizer parity batch — every remaining
  randomization feature of `references/digimon_world_randomizer` reimplemented
  clean-room with its own options: `technique_data` (+ five field toggles) and
  `type_effectiveness` (`techniques.py`), enemy drops (`drops.py`), Bug/Seadramon
  technique gifts + Tokomon gifts (`gifts.py`), and six QoL patch toggles
  (quest items droppable, learn chance ×2, brain tier 1, unrig slots, learn
  move+command, DV chip text). All data patches, validated by a real-disc
  round trip (spoiler ↔ patched tables). Second commit the same day:
  **digivolution randomization** (`evolutions.py`: tree / obtain-all /
  requirements / special digivolutions, with a warning about the three
  partner-gated areas vs `type_lock_unlocks`; every Fresh line is guaranteed
  a Vaccine and a Virus path so the seed stays possible),
  `enemy_technique_weights` (AI weights) and `digivolution_stat_gains`
  (additive gains rows only — `EVL_applyEvolution` read from the overlay
  ASM: Devimon/Numemon/Sukamon/Nanimon/Fresh/In-Training rows are a scale
  path where `brains` is an int8 multiplier, never touch them). Same ASM
  reading settled that the element matrix **is a damage multiplier**
  (Σ of the three defender-specialty cells / 30). Later the same day, from
  four static research agents: `species_technique_lists` (the `.MMD`
  census proved lists can only be re-filled in place — `technique_lists.py`),
  `partner_raising` (`raising.py`), `bgm_shuffle` (`music.py`), 18
  `screen_region` fixes, and a **region-level entrance-shuffle design**
  (parked by the user the same day, STATUS §2.3) that also exposed **five dead
  region-gate rows** (script-tile exits) — **fixed the same day** with seven
  script-class gates (`_SCRIPT_GATE_FIX_PATCHES`, three nets). **In-game AP
  notifications shipped** (`in_game_notifications`: Cave6 mailbox + render
  callback on the game's area-name banner, three nets; client
  `NotificationQueue`). **Pending the user's decision** (STATUS §2.1):
  the BizHawk validation pass and the top-centre vs top-right banner
  choice. **Decided later the same day**: the entrance shuffle is
  **parked** as a future improvement (the logic rewrite is too large even
  by region; design + data stay in `work/`); the notification banner
  is **shipped at the top of the screen** (`renderMapNameAp` dispatcher in
  Cave6 — now code-full — vanilla loading banner untouched, three nets); a
  suspected Lava Cave boulder bypass through the
  Drill Tunnel <-> Mt. Panorama shortcut was retracted (the prompts read
  the vanilla recruit bit; Drimogemon sits behind the boulder). Not
  ported: recruit-identity
  shuffle, intro hash, happyVending, jukebox truncation, forced starter.
  Table audit corrected one claim: the element matrix is read by the
  **partner's** auto-battle AI, not the enemy AI. Remaining technique
  objective = `BTL_calculateDamage` decomp + `.MMD` census + species-list
  shuffle.
- **2026-08-28**: jype0's byte-matching `dw_decomp` adopted as the reading
  source for game code (see References); its symbols, structs and typed
  globals are in the Ghidra project. Audits against it found no model
  discrepancies, retired one bogus shipped patch (`ROM_PP_CALC_PATCH`) and
  queued the unpatched recruit-bit readers in `TRN_REL`/`DGET_REL`. Six lab
  savestates captured; `tools/dw1_warp_state.py` produces a savestate on
  any screen unattended. Same day: the **enemy data model** was verified
  (every field Digimon is a `.MAP` record + MAPHEAD.SCN operands — no code
  hooks needed) and shipped as `enemy_stats` (stats + techniques re-balanced by
  sphere depth) and `enemy_randomization` (species substitution, heap-
  budgeted), lab-validated through the three nets incl. real battles;
  data table `data/enemy_records.py`, module `enemies.py`. The Green Gym
  bonus now follows AP recruits (`TRN_GYM_BONUS_WORD_PATCHES`). **Next
  objective (agreed the same day): randomize technique data (`MOVE_DATA`)
  and species technique lists** — first steps are the `BTL_calculateDamage`
  decomp (BTL overlay, first overlay import into Ghidra) and a static
  `.MMD` animation-table census; see STATUS.md §2.3 / §3.5 and the
  `dw1-technique-data` memory. Full detail: [STATUS.md](STATUS.md).
- **Architecture** (locked): BizHawk + Nymashock + APProcedurePatch +
  generic Lua connector — the FFT Ivalice Island pattern. A DuckStation
  client also ships. PCSX-Redux is the RE-lab emulator (not player-facing).
  The unified RAM/ROM address manifest lives at
  [worlds/digimon_world/data/addresses.py](worlds/digimon_world/data/addresses.py)
  and is the **single source of truth** — the patcher (`rom.py`) and
  client (`client.py`) import from there, never from `references/` directly.
- **Patch-test loop**: the standardized fast iteration flow — prototype in
  decompiled C, iterate as live-RAM pokes over a savestate, then one
  confirming ISO build — is documented in
  [worlds/digimon_world/tools/PATCH_PROCESS.md](worlds/digimon_world/tools/PATCH_PROCESS.md),
  driven by `tools/dw1_apply_patch.py` (one spec drives live-RAM
  apply/verify and sector-aware ISO builds) and run by the `dw1-patch` agent.
- **RE lab**: PCSX-Redux + Ghidra workbench for automated reverse engineering
  (watchpoints, REST-driven RAM access, analyzed SLUS project). Tools live in
  `C:\opt\tools\`, harness scripts and the full guide in
  [worlds/digimon_world/tools/TOOLING.md](worlds/digimon_world/tools/TOOLING.md).
  Game-derived artifacts go to `work/` (gitignored), never into the repo.
- **Function decomp**: **read `references/dw_decomp/` first** (resolve any
  address with `tools/dw1_decomp_xref.py --lookup`); ~87 % of the game is
  byte-matching C there. Our own pipeline in
  [worlds/digimon_world/tools/DECOMP_PROCESS.md](worlds/digimon_world/tools/DECOMP_PROCESS.md)
  (bar: 100% replay of emulator-captured call vectors) remains for ASM-only
  functions, patch verification and runtime questions. Batch via the
  `dw1-decomp` agent + `dw1-decomp-batch` workflow. Decomp output stays in
  `work/` — never commit it.
- **Conventions**:
  - All code, identifiers, commit messages, and committed documentation in
    English.
  - Conversational comments and ad-hoc notes with the human collaborator may
    be in Spanish.
  - Follow the repo-wide style notes above (120-col, double quotes, modern
    type annotations).

### References

Reference projects are available locally under `references/` (read-only,
study material — do not modify, copy verbatim, or import code from these
into the world package):

- **`references/DWAP/`** — existing unstable Archipelago world for Digimon
  World 1, by ArsonAssassin (MIT license).
  Repo: https://github.com/ArsonAssassin/DWAP
  Architecture: non-standard. Python apworld in `Apworld/dw1/`, but the
  runtime client is in **C#** under `source/`, built on the author's
  separate `Archipelago.Core` .NET library
  (https://github.com/ArsonAssassin/Archipelago.Core).
  Primary value: memory addresses, item and location IDs already mapped
  for DW1 USA, and a catalogue of architectural choices that may be
  contributing to instability (evidence-based assessment expected — do
  not speculate).

- **`references/digimon_world_randomizer/`** — non-AP standalone
  randomizer for DW1, by meekrhino. Last release Feb 2021. No explicit
  LICENSE file — treat as study-only, do not copy code verbatim.
  Repo: https://github.com/meekrhino/digimon_world_randomizer
  Primary value: complete catalogue of what is randomizable in DW1 and
  where in the .bin each item lives; .bin patching approach refined over
  5+ years; game-specific quirks and bug workarounds (Toy Town access,
  Whamon recruit, Drimogemon fight, softlocks, etc.); implicit progression
  logic that translates into AP `rules.py`.

- **`references/fft_ivalice_island/`** — Final Fantasy Tactics: Ivalice
  Island APWorld, by Rosalie-A. Listed as **Stable** in the community
  Playable Worlds sheet, with extensive wiki documentation.
  Repo: https://github.com/Rosalie-A/Archipelago (full Archipelago fork;
  the world lives under `worlds/` — locate it on first read).
  Wiki: https://github.com/Rosalie-A/Archipelago/wiki
  Architecture: BizHawk + Nymashock PSX core + **APProcedurePatch**
  (`.apfftii` files) + the standard `connector_bizhawk_generic.lua`.
  User supplies a legal USA ISO; client patches it on first run.
  Primary value: highest-priority architectural reference. PS1 USA,
  state-heavy RPG, BizHawk-based, well documented. Most directly
  comparable to the DW1 target.

- **`references/sotn_archipelago/`** — Castlevania: Symphony of the Night
  APWorld, by AdmiralTryhard.
  Repo: https://github.com/AdmiralTryhard/SOTNArchipelago
  Docs: `worlds/sotn/docs/sotn-en.md` inside the clone.
  Architecture: BizHawk 2.9.1 + Nymashock PSX core + a **custom
  game-specific Lua connector** (`connector_sotn.lua`) instead of the
  generic one. **Does NOT patch the ROM at runtime** — the world ships
  with no patcher (verified by grepping for `cue/track/audio/sector`).
  Primary value: case study for the custom-Lua design path (Option C
  escalation from our locked Option B). Useful if DW1 surfaces an
  event class the generic connector cannot detect; **not** a
  multi-track BIN/CUE reference (DW1 is single-track per Phase 0).
  Note: there exists at least one other community SOTN AP
  implementation; this is one of two.

- **`references/dw_decomp/`** — jype0's **byte-matching** decompilation of
  SLUS-01032 (MIT; CI `cmp`s the rebuilt SLUS + all 15 overlays against the
  originals and is green). ~87 % of all functions in C, all overlays covered,
  72 structs. **Adopted 2026-08-28 as the primary reading source for game
  code** — read its C before decompiling anything yourself; our
  vector-capture/replay pipeline remains for ASM-only functions and for
  verifying patches. Bridge from our addresses to its names:
  `worlds/digimon_world/tools/dw1_decomp_xref.py` →
  `tools/DW_DECOMP_XREF.md`. Its names are NOT ours (their `renderString` is
  our `FUN_800E5B50`); go through the xref. Its symbols are imported into the
  Ghidra project (primary where Ghidra had `FUN_`/`DAT_`, secondary
  otherwise). Study-only policy still applies: do not copy its C into the
  world package.

- **`references/psxrecomp/`** — the static PSX recompiler behind the
  (now-vanished) Digimon World PC port. **Parked** pending the port author's
  appeal; kept for the AP-on-recomp feasibility notes (trusted-plugin API,
  `mod_function_entry_funcs` hooks, TCP debug server compiled out of release
  builds). PolyForm Noncommercial, alpha — not a target.

#### Notes for Claude when studying references

- The PS1 + BizHawk + Nymashock + APProcedurePatch architecture is
  already proven in production by FFT Ivalice Island, this SOTN
  implementation, and Ape Escape. Treat that path as the established
  pattern, not an unknown to validate from scratch.
- Cross-reference findings between projects when possible. Where DWAP
  and the standalone randomizer disagree on something (e.g. an address
  or a randomizable system's identity), flag it as an open question
  rather than picking one silently.
- See `references/README.md` for any additional per-clone notes the
  human collaborator added.