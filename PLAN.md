# Digimon World 1 (PS1) APWorld — Plan

Working branch: `digimon-world-ps1`. Target package: `worlds/digimon_world/`. Target build:
Digimon World 1 USA, **SLUS-01032** (exact SHA-256 to be confirmed — see Open Question Q3).

This document is the output of the exploration phase. No production code has been written yet.

---

## a. Summary of findings

### Archipelago world API (relevant slices)

- A world is a Python package under `worlds/<name>/` with an `__init__.py` defining a
  `World` subclass auto-discovered by `AutoWorldRegister`.
- Lifecycle (driven by [Main.py](Main.py)):
  `generate_early` → `create_regions` → `create_items` → `set_rules` → `pre_fill` → `fill` →
  `post_fill` → `generate_output`. After `create_items` you cannot add/remove items, locations,
  or regions.
- Per-game options live in an `options.py` dataclass that subclasses `PerGameCommonOptions`.
  Static, machine-local config (e.g. ROM path) lives in [settings.py](settings.py)-backed
  `host.yaml` settings, not options.
- IDs: locations and items must each be unique within the world, kept in `1..2**31-1`. IDs ≤ 0
  are globally reserved.
- `state.can_reach_*` from an `Entrance` access rule **must** be paired with
  `multiworld.register_indirect_condition(...)` or generation can become non-deterministic.
- Events (id `None`) are real during generation and must be placed with
  `Location.place_locked_item(...)`. Standard goal: a `Victory` event +
  `multiworld.completion_condition[self.player] = lambda state: state.has("Victory", self.player)`.
- For shippable `.apworld` zips: relative imports for intra-world code, absolute for everything
  else. Filenames must be lowercase. Metadata in `archipelago.json`. Ship via Launcher's
  "Build APWorlds" component so `version`/`compatible_version` are filled correctly.
- Tests: world-local `test/` package with a `WorldTestBase` subclass picks up the entire
  generic suite (reachability, fill, IDs, options, manifests). Aim for sub-second tests.
  The repo is test-runner-agnostic — no `@pytest.mark.parametrize`, use `test/param.py`
  helpers.
- Style: 120-col, double-quoted strings, modern type annotations
  (`dict[str, int | None]`), reST docstrings on new core code.

### Reference worlds studied

| World | Console / runtime | What we can reuse | What we cannot |
|---|---|---|---|
| `worlds/_bizhawk/` + `worlds/pokemon_emerald/` | BizHawk emulator (mostly GBA/N64/SNES/NES) — **BizHawk has a PSX core (Nymashock) but no current AP world uses it** | Entire client/connector stack: socket-based JSON-RPC to a bundled Lua script ([data/lua/connector_bizhawk_generic.lua](data/lua/connector_bizhawk_generic.lua)), `BizHawkClient` base class, `BizHawkClientContext`, automatic Lua injection on launcher start, `APProcedurePatch + APTokenMixin` for binary patching, `bsdiff4` already a pinned dependency, Launcher integration via `SuffixIdentifier(".apxxx")`. | PSX core path is unproven. We would be the first AP world to drive BizHawk's Nymashock core. |
| `worlds/tww/` | GameCube / Dolphin via [dolphin-memory-engine](https://pypi.org/project/dolphin-memory-engine/) | Pattern for **disc-based** games: AP only emits a `.aptww` zip with plando data; ISO patching is delegated to an external tool ([wwrando](https://github.com/tanjo3/wwrando)) the user runs once. Memory-only client (no ROM file reread). Bitfield polling for location checks at ~10 Hz. Item-delivery via a "queue array" RAM region the game consumes. DeathLink via writing the health address. | Library-specific (dolphin-memory-engine has no PS1 analogue). External-tool model is conceptually portable but adds a maintenance burden of a separate repo. |
| `worlds/kh1/` | Originally suspected to be PS2/emulator; **actually targets the PC release** (Steam/EGS) via OpenKH + Lua mods | File-based IPC pattern (game writes `send<ID>`, client polls). Decoupled "patch = JSON config", external tool applies. Slot data as flat `.cfg` files. | Not an emulator world; not directly applicable to a PS1 disc target. Useful only as a reminder that "patch" can mean "config bundle" rather than binary delta. |

### Cross-cutting findings

- **No existing AP world targets PS1.** Repo grep finds zero hits for PS1, PSX, Octoshock,
  Nymashock, PCSX, DuckStation, `.cue`, `.bin` (in PS1 sense), or `.iso` (only `.bin` from the
  Atari 2600 Adventure world).
- **No prior Digimon code in this repo.** `CLAUDE.md` references a "previous community
  implementation" that is **not** in this tree.
- **Patching libraries available:** `bsdiff4` (pinned, used by ~10 worlds — fine for tens of
  MB, expensive for ~700 MB PS1 ISOs), an in-tree IPS parser (`worlds/cvcotm/rom.py`,
  `worlds/sm/`, `worlds/smz3/`), and `APProcedurePatch + APTokenMixin` (token-driven byte
  writes) used by Pokemon Emerald and others. **`xdelta` is not currently a dependency.**
- **Disc-image patching is not a solved problem in this repo.** TWW outsources it to an
  external tool; everyone else patches small ROMs.

---

## b. Architecture recommendation

The high-level shape mirrors the **Pokemon Emerald + BizHawk** pattern with two important
disc-specific adaptations: (1) a token-list patcher tailored to a multi-hundred-MB ISO,
applied at apply-time rather than over-the-wire bsdiff, and (2) a PSX core sanity check
prior to committing to BizHawk.

### Emulator target — **leading: BizHawk (Nymashock PSX core); fallback: PCSX-Redux**

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **BizHawk + Nymashock** | Reuses the entire `_bizhawk/` stack (Lua connector auto-injected, JSON-RPC, `BizHawkClient` base class). Already cross-platform. Single emulator users already install for other AP games. | PSX core is community-maintained and less accurate than DuckStation. **No AP world has driven this core in production**, so memory-domain access via the connector is unverified. Possible audio/save-state quirks. | **Lead choice** because of leverage. Validate during Phase 0 with a smoke test. |
| **PCSX-Redux** | First-class Lua scripting + GDB stub + JSON over WebSocket, very debugger-friendly, accurate. | Smaller user base; would require a brand-new `client.py` style (not BizHawk-shaped). User has to install one more emulator. | **Fallback** if BizHawk's Nymashock proves unworkable. We'd need a custom Lua connector and a fresh Python client; substantial new work. |
| **DuckStation** | Most popular modern PS1 emulator; great UX. | No first-class scripting / IPC. Memory access would require either a libretro core (RetroArch shim) or an out-of-process memory injector. | **Not recommended** — too much glue code per OS. |
| **ePSXe / others** | — | Abandoned / no scripting. | Reject. |

**Decision:** target BizHawk first, contingent on the Phase-0 smoke test (Q1). If
Nymashock can't expose the PSX RAM domain through the existing JSON-RPC connector, fall
back to PCSX-Redux with a small dedicated Lua connector.

### Client implementation — **Python in-tree, `BizHawkClient` subclass**

- Live in `worlds/digimon_world/client.py` and inherit from
  `worlds._bizhawk.client.BizHawkClient`.
- Required class vars: `system = "PSX"`, `game = "Digimon World"`,
  `patch_suffix = ".apdw1"`.
- Implement `validate_rom()` (read game-id string at a known address) and `game_watcher()`
  (memory poll loop).
- Reuse the bundled `data/lua/connector_bizhawk_generic.lua` — **no custom Lua needed if
  BizHawk's PSX domain works through the generic JSON-RPC contract.** Otherwise a thin
  `connector_psx.lua` may be required (TBD via Q1).
- Slot authentication: store slot name as ASCII bytes in an unused chunk of the patched ISO
  (e.g. tail of the data track) and have the client read it back at connect time.

If the BizHawk path fails, the same `client.py` can be re-targeted to PCSX-Redux's WebSocket
API by swapping the transport — most of the protocol logic (poll, diff, send LocationChecks,
write item queue) stays unchanged.

### Patching strategy — **`APProcedurePatch + APTokenMixin` over a user-supplied ISO**

| Option | Pros | Cons | Verdict |
|---|---|---|---|
| **APTokenMixin token list (RECOMMENDED)** | Pure byte-level writes; tiny patch file (~tens of KB); fast to apply; fits the surgical-edit nature of randomization (item-table writes, area-flag tweaks); pattern proven in Pokemon Emerald/CV64. | Requires us to know exact addresses for everything we want to change. Up-front RE cost. | **Lead choice.** |
| `bsdiff4` over the full ISO | Zero-RE: snapshot a "vanilla" and "edited" ISO, diff. Already a repo dependency. | PS1 ISOs are 500–700 MB. `bsdiff4` over images that size is RAM-hungry and slow at apply time, and we'd be shipping a full ISO-shaped diff per seed. Pattern doesn't scale to thousands of variant seeds. | Reject as primary; usable for a one-shot "base patch" layer if we ever ship a vanilla→randomizer-base diff. |
| `xdelta3` | Better than `bsdiff4` on big files. | Net-new dependency, OS-specific binaries. | Reject unless we have a strong reason. |
| PPF | PS1-community standard; existing tools. | Not used anywhere in the repo. Would have to write or vendor a PPF applier. | Reject. |

**Apply-time pipeline:**

1. User configures `host.yaml` with the path to their **vanilla SLUS-01032** ISO/BIN.
2. Generation produces `slot.apdw1` — a zip containing `archipelago.json`, a token blob, and
   any plando/slot data the client needs. **No copy of the ISO is shipped.**
3. Launcher (or the client on first launch) sees the `.apdw1`, reads `host.yaml` for the
   ISO path, **hash-checks the source ISO against the canonical SHA-256**, applies the token
   blob to a copy of the data track, writes `<seed>.bin` next to the source. `.cue` is
   either copied verbatim or regenerated.
4. User boots the patched BIN/CUE in BizHawk; the AP client attaches.

**Multi-track caveat:** PS1 BIN/CUE images can include audio tracks. **All edits must be
confined to the data track** (track 1) — token offsets are relative to that track only.
Audio tracks (if present) are passed through untouched.

### Item-receive / location-check hooks — **bitfield poll + queue array**

Mechanism (modeled on TWW + Pokemon Emerald), with concrete addresses **TBD**:

- **Location checks**: a small block of "AP flag" bytes inserted into a known unused area of
  Digimon World's RAM-resident save block. The client polls this block at ~10 Hz, diffs
  against the last-seen snapshot, and emits `LocationChecks` for any newly-set bits.
  - Where possible, **reuse existing in-game flags** (recruitment state, area-unlock bits,
    boss-defeated bits) by mapping them 1:1 to AP location IDs.
  - Where the game has no flag (e.g. picking up an item from a chest that doesn't normally
    leave a trace), patch a one-instruction hook in the chest-handler routine to set our
    AP-flag bit when the chest is touched.
- **Item receive**: a small `pending_item` queue (e.g. 16 slots) at a fixed RAM address.
  The client writes incoming items into the queue; a patched in-game routine — installed
  by the same patch — drains the queue each frame and applies the corresponding effect
  (add to inventory, set a recruitment flag, etc.).
- **Goal completion**: dedicated "victory" RAM byte set by a hook in the ending-cutscene
  trigger or end-credits routine. Client sees it set, sends `StatusUpdate(GoalComplete)`.

This is straightforward in PS1's flat memory model. The hard part is **finding the
addresses and identifying clean hook sites** (Open Questions Q1, Q2, Q5).

### Output container

- File extension: `.apdw1`
- Format: zip (per `Files.py`'s `APPlayerContainer` / `APProcedurePatch`)
- Contents: `archipelago.json` (manifest), `tokens.bin` (token blob), `slot_data.json`
  (mirror of fill_slot_data so the client can reuse it offline), optional `plando.json`.
- Launcher integration: `LauncherComponents.Component(..., file_identifier=
  SuffixIdentifier(".apdw1"))` so double-clicking the file launches the client (which
  handles patch-apply on first run).

---

## c. Proposed phases

Each phase has a small, demonstrable deliverable. Phases 0–2 require no emulator/RAM work
and can begin as soon as the open questions in (d) are answered.

### Phase 0 — Pre-flight (no AP code)

**Goal:** answer the make-or-break questions before committing to the architecture.

- Confirm the canonical SHA-256 for SLUS-01032 redump.org "good" dump.
- Smoke-test BizHawk + Nymashock with the existing
  `data/lua/connector_bizhawk_generic.lua` script: can we read/write arbitrary RAM
  addresses through the JSON-RPC contract? **If yes**, the BizHawk path is viable. **If no**,
  pivot to PCSX-Redux.
- Inventory the user's existing notes / RAM map / prior unstable APWorld code for DW1.
  Even if we don't reuse it, having known-good RAM addresses for save flags and inventory
  removes weeks of RE.
- Decide MVP scope (Q5).

Exit criteria: emulator target locked in, RAM-map availability assessed, MVP scope agreed.

### Phase 1 — World skeleton (generation only)

**Goal:** a generable but unplayable world that passes the generic test suite.

- Create `worlds/digimon_world/` with `__init__.py` (`World` subclass), `options.py`
  (minimal — say a `goal` choice and a `death_link` toggle), `items.py`, `locations.py`,
  `regions.py`, `rules.py`, and `test/__init__.py` + `test/bases.py`.
- Stub: ~10 items, ~10 locations, 2-3 regions, a Victory event, a trivial completion
  condition. Enough to make `pytest worlds/digimon_world` pass and `python Generate.py`
  succeed with a default yaml.
- No client, no patcher. `generate_output` may be a no-op stub.

Exit criteria: `pytest worlds/digimon_world/test` passes; the generic suite
(`test/general/`) passes against the stub world.

### Phase 2 — Full logic

**Goal:** complete item pool, complete location list, real region graph and access rules.

- Enumerate all randomized items (likely: items, equipment, stat-up tickets, area passes,
  recruitment unlocks; some events for digivolution gates).
- Enumerate locations (chests, NPC gifts, recruitment events, boss drops, training
  milestones — exact taxonomy depends on Q5).
- Build the region graph from File City outward, mirroring DW1's map.
- Encode access rules. Default to Rule Builder (`Has(...) | HasAll(...)`) for new code per
  CLAUDE.md guidance; lambdas only where Rule Builder is awkward.
- Add per-feature unit tests (`assertAccessDependency`, etc.) for the trickier gates.

Exit criteria: full-pool generation succeeds; logic tests cover the major progression gates;
spoiler logs look sane.

### Phase 3 — Patcher

**Goal:** AP can produce a `.apdw1` and apply it to a vanilla ISO into a playable BIN/CUE.

- Implement `DigimonWorldProcedurePatch(APProcedurePatch, APTokenMixin)` in `rom.py`.
- Implement `generate_output()` to populate the token list with: item-table rewrites,
  starting-inventory writes, slot-name string, AP-hook patches (install hooks for chest
  handlers, item-pickup routine, etc.).
- Wire the host.yaml `rom_file` setting and the SHA-256 hash check.
- Wire `LauncherComponents.Component(..., file_identifier=SuffixIdentifier(".apdw1"))`.
- Smoke test: produce a `.apdw1` from a stub seed, apply it, boot the patched BIN/CUE,
  visually verify nothing is broken.

Exit criteria: patched BIN/CUE boots in BizHawk, vanilla content largely intact, AP hooks
detectable in RAM (even if no client is reading them yet).

### Phase 4 — Client

**Goal:** end-to-end multiworld run.

- Implement `client.py` (`BizHawkClient` subclass): `validate_rom`, `game_watcher`,
  authentication via slot-name read.
- Implement the location-poll loop (diff against snapshot, send `LocationChecks`).
- Implement the item-receive queue write.
- Implement `StatusUpdate(GoalComplete)` on victory flag.
- (Optional) DeathLink via a health-or-equivalent address.

Exit criteria: a single-player solo seed can be played from start to finish, with all
location checks landing on the server and items received from a self-link being applied
in-game.

### Phase 5 — Polish

- Setup docs (`docs/setup_en.md`) with an end-to-end "from a fresh BizHawk install" walkthrough.
- Game info doc (`docs/en_Digimon World.md`).
- Options polish: presets, descriptions, option groups.
- Web-host considerations (if we want this on archipelago.gg eventually — see Q7).
- WorldTestBase fuzz tests gated behind an env var per CLAUDE.md guidance.

### Phase 6 — Packaging and distribution

- `archipelago.json` with `world_version`, `authors`, `minimum_ap_version`.
- Build via `python Launcher.py "Build APWorlds" -- "Digimon World"`.
- Ship the `.apworld` zip from this fork's releases.

---

## d. Open questions

Roughly ordered by how much they block Phase 1.

1. **Q1 (BLOCKING) — BizHawk PSX-core viability.** Will the existing generic Lua connector
   expose Nymashock's RAM domain via JSON-RPC? Concretely: open BizHawk, load any PS1 game,
   load `data/lua/connector_bizhawk_generic.lua`, run a tiny Python script that calls
   `read(System Bus, 0x80000000, 4)`, and confirm we get sensible bytes back. If this works,
   the BizHawk path is locked in. If not, we pivot to PCSX-Redux. Needs the user (or me, with
   permission) to actually run the test.
2. **Q2 (BLOCKING) — RAM map availability.** Does the user have a RAM map for DW1 USA
   (save-block layout, inventory addresses, area/recruitment/event flags), or do we need
   to dump and reverse-engineer them? This single answer changes Phase 0–4 scope by weeks.
   Useful upstream sources to check: the previous unstable APWorld referenced in
   [CLAUDE.md](CLAUDE.md#L150), GameHacking.org, DataCrystal, the DW1 speedrunning community.
3. **Q3 (BLOCKING) — Source ISO identity.** Which exact dump are we targeting?
   redump.org SLUS-01032 is the canonical answer, but I want the SHA-256 the user
   actually has on disk so the patcher's hash check matches. Are we supporting only USA, or
   also EU/JP later? (Recommendation: USA only for v1, document EU/JP as future work.)
4. **Q4 — Prior APWorld inheritance.** Where does the "previous community implementation"
   live, and may we read it for RAM addresses, location taxonomy, and bug history? Even if
   we throw away the code, the bug list is gold.
5. **Q5 — MVP scope.** What is "minimum viable" for v1?
   - Item randomization only (chests, NPC gifts, shops)?
   - + Recruitment randomization (which Digimon you can convince to join the city)?
   - + Digivolution randomization (which Digimon → which evolutions)?
   - + Starter randomization?
   - I'd recommend "chests + NPC gifts + starter" for v1, with recruitment / digivolution
     gated behind options for v2. Want the user's call.
6. **Q6 — DeathLink, Item-Links, Hints.** Any opinion, or accept defaults? DeathLink in DW1
   is non-trivial (the game does not auto-respawn); recommend deferring.
7. **Q7 — Distribution target.** Is this destined for the upstream `archipelago.gg` site
   eventually, or is fork-only / self-host distribution acceptable? Affects how much
   energy goes into webhost integration, options presets, tutorial polish.
8. **Q8 — Docs language.** [CLAUDE.md](CLAUDE.md#L168) says committed docs are English and
   conversational notes can be Spanish. Confirm: setup tutorials are English-only at v1?
9. **Q9 — Multi-track BIN/CUE handling.** Does SLUS-01032 ship with audio tracks, or is it a
   single-track data ISO? Affects the patcher's track-aware logic. (Likely single data track,
   but worth a five-minute check.)

---

## e. Risks and unknowns

### DW1-specific

- **Heavy state machines.** DW1's defining mechanic is its 24-hour-clock care/training
  /digivolution loop. Many "items" in the game (food, training equipment) feed into this
  loop in non-linear ways; randomizing item pickups may produce unwinnable states (e.g.
  starvation, evolution dead-ends). Mitigation: keep critical care items local-only or
  early-sphere via item classification, build access rules around recruitment milestones
  rather than raw items.
- **Recruitment is a long state machine.** Each Digimon-recruit event in DW1 requires
  multiple in-game days of state changes. AP location checks tied to recruitment may need
  to settle over many frames; we must avoid double-firing as the state transitions.
- **Save format is non-trivial.** DW1 writes to PS1 memory cards (`.mcd`) regularly. Our
  AP-flag bytes need a stable home **inside** the live save block so they survive save/load
  cycles, and we must not collide with checksums the game may compute over its save area.
- **Game writes back over inventory.** Items received from AP that we write into the
  inventory must coexist with the game's own inventory mutations. Our item-queue approach
  (let the patched in-game routine apply items, rather than the client writing the
  inventory directly) sidesteps this, but the queue handler has to be carefully tested.
- **Fast in-game time can outrun our 10 Hz polling.** DW1 has a clock that ticks faster than
  wall-clock; if a check fires and clears in fewer than 100 ms, we miss it. Mitigation:
  use sticky "set-once" flag bytes, never bytes the game also clears.

### Tooling-specific

- **BizHawk's Nymashock PSX core has not been exercised by any AP world.** Q1 is the
  litmus test. If the JSON-RPC connector cannot reach the PSX system bus, the whole
  BizHawk path collapses.
- **PS1 ISO patching has zero precedent in this repo.** Our token-list approach is sound
  in principle but unproven at this size class. First end-to-end patch + boot test is a
  meaningful milestone.
- **Multi-track CUE files** can desync if we regenerate the `.cue` incorrectly. Safer to
  copy the user's `.cue` verbatim and only emit a new `.bin` for the data track.
- **`bsdiff4` over a 700 MB ISO** would be painful even if we wanted to avoid token-driven
  patching. Treat it as a non-option for the per-seed patch and reserve it (if at all) for
  a one-shot "vanilla → randomizer-base" delta if we ever ship one.

### Process-specific

- **Generic test suite runs against new worlds for free.** A broken `create_items` count or
  unreachable region will break the global suite, not just our tests. We must keep the
  skeleton green from Phase 1 onward.
- **Ship as `.apworld`.** Per [CLAUDE.md](CLAUDE.md#L143), package via Launcher's
  "Build APWorlds" so `archipelago.json` is correct. **Filenames must be lowercase** or
  frozen Python fails to import.

---

## f. Verification plan (how we'll know each phase landed)

- **Phase 0:** screenshot of a Python REPL session reading 4 bytes from PS1 RAM through the
  generic BizHawk connector, OR a recorded decision to switch to PCSX-Redux.
- **Phase 1:** `pytest worlds/digimon_world` and `pytest test/general` both green;
  `python Generate.py` produces an `AP_*.zip` from a default yaml.
- **Phase 2:** Spoiler log for a representative seed reads sensibly; targeted access-rule
  tests pass.
- **Phase 3:** A patched `<seed>.bin/.cue` boots in BizHawk, vanilla content reachable,
  AP-hook RAM bytes visible at the expected addresses.
- **Phase 4:** Solo seed playthrough — every check fires once and exactly once on the AP
  server, every received item is applied in-game, the goal flag triggers
  `StatusUpdate(GoalComplete)`.
- **Phase 5:** Setup doc walks an unfamiliar tester from "I just installed BizHawk" to
  "I'm playing a seed" without contacting the author.
- **Phase 6:** `Launcher.py "Build APWorlds" -- "Digimon World"` produces a working
  lowercase `digimon_world.apworld` that loads on a clean Archipelago install.

---

## g. Critical files we'll be writing or referencing

To be created (Phase 1+):

- `worlds/digimon_world/__init__.py` — `World` subclass + Launcher component registration.
- `worlds/digimon_world/options.py` — options dataclass.
- `worlds/digimon_world/items.py`, `locations.py`, `regions.py`, `rules.py` — generation logic.
- `worlds/digimon_world/client.py` — `BizHawkClient` subclass (Phase 4).
- `worlds/digimon_world/rom.py` — `APProcedurePatch` + token-list builder (Phase 3).
- `worlds/digimon_world/data/` — token templates, hook payloads, RAM-map constants.
- `worlds/digimon_world/test/__init__.py`, `test/bases.py`, `test/test_*.py`.
- `worlds/digimon_world/docs/setup_en.md`, `docs/en_Digimon World.md`.
- `worlds/digimon_world/archipelago.json`.

Existing files we'll lean on:

- [worlds/_bizhawk/__init__.py](worlds/_bizhawk/__init__.py),
  [worlds/_bizhawk/client.py](worlds/_bizhawk/client.py),
  [worlds/_bizhawk/context.py](worlds/_bizhawk/context.py) — client framework.
- [data/lua/connector_bizhawk_generic.lua](data/lua/connector_bizhawk_generic.lua) — emulator-side script.
- [worlds/Files.py](worlds/Files.py) — `APProcedurePatch`, `APTokenMixin`, `APPlayerContainer`.
- [worlds/pokemon_emerald/](worlds/pokemon_emerald/) — best in-tree reference for the pattern we're imitating.
- [worlds/tww/](worlds/tww/) — reference for the disc-image / external-patcher mental model.
- [BaseClasses.py](BaseClasses.py), [worlds/AutoWorld.py](worlds/AutoWorld.py) — required reading.
- [rule_builder/](rule_builder/) — preferred logic-rule style for new worlds.
- [Options.py](Options.py), [settings.py](settings.py) — option/setting bases.
- [test/bases.py](test/bases.py), [test/general/](test/general/) — test infrastructure.
