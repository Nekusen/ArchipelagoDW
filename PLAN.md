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
| `worlds/_bizhawk/` + `worlds/pokemon_emerald/` | BizHawk emulator (mostly GBA/N64/SNES/NES) — PSX core (Nymashock) is **proven in production by FFT Ivalice Island, SOTN, and Ape Escape** | Entire client/connector stack: socket-based JSON-RPC to a bundled Lua script ([data/lua/connector_bizhawk_generic.lua](data/lua/connector_bizhawk_generic.lua)), `BizHawkClient` base class, `BizHawkClientContext`, automatic Lua injection on launcher start, `APProcedurePatch + APTokenMixin` for binary patching, `bsdiff4` already a pinned dependency, Launcher integration via `SuffixIdentifier(".apxxx")`. | — |
| `worlds/tww/` | GameCube / Dolphin via [dolphin-memory-engine](https://pypi.org/project/dolphin-memory-engine/) | Pattern for **disc-based** games: AP only emits a `.aptww` zip with plando data; ISO patching is delegated to an external tool ([wwrando](https://github.com/tanjo3/wwrando)) the user runs once. Memory-only client (no ROM file reread). Bitfield polling for location checks at ~10 Hz. Item-delivery via a "queue array" RAM region the game consumes. DeathLink via writing the health address. | Library-specific (dolphin-memory-engine has no PS1 analogue). External-tool model is conceptually portable but adds a maintenance burden of a separate repo. |
| `worlds/kh1/` | Originally suspected to be PS2/emulator; **actually targets the PC release** (Steam/EGS) via OpenKH + Lua mods | File-based IPC pattern (game writes `send<ID>`, client polls). Decoupled "patch = JSON config", external tool applies. Slot data as flat `.cfg` files. | Not an emulator world; not directly applicable to a PS1 disc target. Useful only as a reminder that "patch" can mean "config bundle" rather than binary delta. |
| `references/fft_ivalice_island/` (FFT Ivalice Island, branch `origin/finalfantasytactics`, world at `worlds/fftii/`) | PS1 USA via BizHawk + Nymashock | **Highest-priority reference** for our project. `Rom.py` shows `APProcedurePatch + APTokenMixin` with a bsdiff4 base patch, token-list overlay, sector-aware Mode2/2352 writes, and `ErrorRecalculator` for EDC recomputation. `Client.py` shows a clean `BizHawkClient` subclass with `system = "PSX"`, an `items_received`-counter dispatch pattern that's robust to game-loop interference, and a flag-poll location-detection model. Setup uses the **generic** Lua connector — no game-specific Lua. See [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 3. | Some of the on-disk size is built around bsdiff4 patches we'd have to author ourselves; we cannot copy any of the game-specific tables. |
| `references/sotn_archipelago/` (SOTN, world at `worlds/sotn/`, custom Lua at `data/lua/connector_sotn.lua`) | PS1 USA via BizHawk + Nymashock + a **custom** Lua connector | Worked example of a custom-Lua design when per-frame positional / event-context detection and real-time anti-cheat write-back are needed. Demonstrates that a world can ship with **no ROM patcher at all**. See [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 4. | **Not a multi-track-BIN/CUE reference** — the previous `CLAUDE.md` characterization is wrong. SOTN does not patch the ROM and grep across its Lua, client, and world for `cue/track/audio/sector` returns zero matches. |
| `references/DWAP/` (the existing unstable DW1 APWorld) | Targets PS1 via an external **C#** client built on `Archipelago.Core` | RAM address map for DW1 USA (21 named addresses in [Addresses.cs:9-48](references/DWAP/source/DWAP/Addresses.cs)); option taxonomy; recruit-prerequisite graph (51 entries in [RecruitDigimon.py:11-63](references/DWAP/Apworld/dw1/RecruitDigimon.py)). | Cannot inherit the runtime — it depends on closed-source `Archipelago.Core`. Should NOT inherit the recruit-detection design — `RecruitmentFunctionAddress = 0x00000000` at [Addresses.cs:46](references/DWAP/source/DWAP/Addresses.cs) means the hook never installs and recruit checks cannot fire at runtime. See [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 1. |
| `references/digimon_world_randomizer/` (standalone non-AP randomizer) | Direct `.bin` patching | Complete catalog of DW1 ROM offsets (digimon data, evolution to/from, evolution stat gains, technique data, tech learn chances, 79 chest items, ~300 map item spawns, recruitment triggers, Tokomon gifts, Seadramon teach, special-evolution overrides — all cited in [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.2). Bug-fix / softlock catalog (Toy Town, Greylord, EntityMoveTo, etc.). Implicit progression-logic notes for use in Phase 2 `rules.py`. | No sector-aware writing, no EDC/ECC recalculation, no multi-track CUE handling. Treat as a catalog reference, not a patcher reference. |

### Cross-cutting findings

- **PS1 + BizHawk + Nymashock + APProcedurePatch is proven in production.** FFT Ivalice
  Island, SOTN, and Ape Escape all ship on this stack. Q1 (originally BLOCKING) is downgraded
  accordingly; see Open Questions below.
- **The previous community DW1 APWorld is `references/DWAP/`.** It is checked out under the
  `references/` study area as of this revision. Q4 (originally about whether such an
  implementation exists) is closed; see Open Questions.
- **`references/DWAP/source/DWAP/Addresses.cs` provides 21 named RAM addresses** for the live
  game state (inventory base, prosperity points, technique table, Drimogemon-defeated flag,
  Meramon tunnel sub-state, starter slots, and so on). One of those entries —
  `RecruitmentFunctionAddress = 0x00000000` at [Addresses.cs:46](references/DWAP/source/DWAP/Addresses.cs) —
  is the unset placeholder that prevents DWAP's only function-hook from installing.
- **`references/digimon_world_randomizer/digimon/data.py` provides the ROM-offset side**:
  digimon data block (0x14D6E9DC), evolution to/from (0x14D6CE04), evolution stat gains,
  technique data (0x14D66DF4), tech learn (battle 0x14D66A2C, brain 0x14C8E58C), 79 chest
  item offsets, ~300 map item spawns, recruitment trigger tables (51 entries), Tokomon gifts,
  Seadramon teach, special-evolution overrides. The DWAP RAM map and the standalone
  randomizer's ROM map together cover most of what we need; **see [REFERENCES_NOTES.md](REFERENCES_NOTES.md)**
  for the full citations and a section-by-section cross-reference.
- **Patching libraries available:** `bsdiff4` (pinned, used by ~10 worlds — fine for tens of
  MB, expensive for ~700 MB PS1 ISOs), an in-tree IPS parser (`worlds/cvcotm/rom.py`,
  `worlds/sm/`, `worlds/smz3/`), and `APProcedurePatch + APTokenMixin` (token-driven byte
  writes) used by Pokemon Emerald and FFT. FFT's `Rom.py` combines a small bsdiff4 base
  patch (option-selected) with token-list writes and sector-aware ENTD edits — that pattern
  fits a multi-hundred-MB PSX ISO without shipping per-seed bsdiffs of the whole disc.
- **Disc-image patching IS a solved pattern, just not via TWW's external-tool route.** FFT's
  `Rom.py` shows the in-tree path: load the user's vanilla `.bin` from a host.yaml setting,
  apply tokens + sector-aware writes in memory, run `ErrorRecalculator` for EDC, write the
  patched `.bin` and a regenerated `.cue`. Magic numbers (Mode2/2352): `sector_size = 0x930`,
  `data_size = 0x800`, `header_size = 0x18`, `ec_size = 0x118`. We can copy this approach
  directly.

---

## b. Architecture options (ranked, awaiting human pick)

The previous version of this section presented a single recommendation
(BizHawk + token-list, with PCSX-Redux as a fallback) before the four
reference projects were available. With the references now studied,
four concrete options exist. They are ranked by my read of the
evidence, but the choice is the user's. Justifications cite
[REFERENCES_NOTES.md](REFERENCES_NOTES.md).

### Ranking summary (most to least favored)

**B > C > D > A.**

- **B** inherits the most working code from a production-stable PS1 USA
  reference (FFT Ivalice Island).
- **C** is the controlled escalation from B if DW1 surfaces an event
  class that the generic Lua connector cannot handle.
- **D** is only useful if B and C both turn out to be unworkable, which
  the production references make unlikely.
- **A** is last because DWAP's two largest evidenced flaws (the unset
  function-hook address; the closed-source `Archipelago.Core`) cannot
  be fixed without either reverse-engineering an upstream library or
  reproducing it from scratch — at which point the cost equals or
  exceeds Option B with much less in-tree leverage.

### Option B — BizHawk + Nymashock + APProcedurePatch + generic Lua (FFT path)

Match the FFT Ivalice Island pattern verbatim where it generalizes.

**Pros**
- Drop-in reuse of the in-tree `_bizhawk` framework: the `BizHawkClient`
  subclass pattern, `_bizhawk` JSON-RPC, automatic Lua injection on
  Launcher start, `Files.APProcedurePatch + APTokenMixin`, the bundled
  `data/lua/connector_bizhawk_generic.lua`, `bsdiff4` already pinned,
  and `SuffixIdentifier(".apdw1")` Launcher integration.
- Production proof: FFT, SOTN, and Ape Escape all run on
  BizHawk + Nymashock.
- FFT's [Rom.py](references/fft_ivalice_island/) provides the magic
  numbers we need for Mode2/2352 sector-aware writes
  (sector 0x930, data 0x800, header 0x18, ec 0x118) and the
  `ErrorRecalculator` post-step recipe for EDC recomputation.
- DW1's location semantics are mostly RAM flag bytes
  (`HasBeatenDrimogemon = 0x001BE130`, `ProsperityPoints = 0x001BE032`,
  `ItemBankBaseAddress = 0x001BDF2C`, `MeramonTunnel_*`), which fits
  the bitfield-poll model the generic Lua supports cleanly.
- FFT's `items_received`-counter dispatch pattern (per category:
  inventory write, bitfield OR, byte add, etc.) is robust to game-loop
  interference. We can copy the shape and adapt to DW1's address map.

**Cons**
- We have to author at least one bsdiff4 base patch (FFT ships two
  pre-built ones — vanilla-jobs and ap-jobs) if we want to do mass ROM
  changes that are awkward as token writes. For a chest/item/recruit
  scope this may not be needed.
- DW1's day-cycle / time-of-day loop (the defining mechanic) might
  surface event classes that the generic Lua cannot detect with a
  bitfield poll alone. If so, we'd graduate to Option C.
- We inherit FFT's complexity in the patcher (sector decomposition,
  EDC recalc) — these are real implementation cost even if the
  building blocks are clear.

**Complexity**: Medium. Most novel work is the patcher (Phase 3) and the
RAM-flag mapping (an RE deliverable). Client and world skeleton are
straightforward if we follow FFT's structure.

**DW1-specific interactions**
- Multi-track CUE: handle exactly like FFT — patch only the data track,
  copy the audio track verbatim, regenerate `.cue`. Magic numbers from
  FFT's `Rom.py` apply directly if SLUS-01032 is Mode2/2352.
- In-game clock cadence: handled by sticky set-once flag bytes (write
  AP-flag bits the game won't clear); avoid ephemeral counters.
- Save format: AP-flag scratch region must live inside the live save
  block so it survives save/load; collision risk with the game's own
  checksum is the main hazard.
- Recruit state machines: detected by polling the recruit-completion
  RAM bits (DW1 likely has them — the standalone randomizer treats
  recruitment as static so the bits exist somewhere, just unmapped by
  DWAP). If a recruit transition has no stable bit, escalate to C.

### Option C — BizHawk + Nymashock + APProcedurePatch + game-specific `connector_digimon_world.lua` (SOTN-style escalation from B)

Same as B except the Lua connector is game-specific. Only choose if B
cannot detect a material cohort of events.

**Pros**
- Per-frame in-game-event detection with positional / context awareness
  (SOTN's relic-proximity, cutscene XY pattern).
- Real-time write-back / anti-cheat semantics (SOTN's deny-relic
  pattern).
- DW1's day cycle could in principle drive a Lua-side day-tick handler
  if needed.

**Cons**
- We maintain a game-specific Lua in addition to the world. Two-layer
  changes when DW1 internals shift.
- Loses the auto-injection benefit of the generic connector — the user
  has to load our Lua manually or we have to add wiring.
- SOTN's pre-`_bizhawk` client architecture is older than FFT's; we'd
  follow FFT's `BizHawkClient` shape with our own Lua, which is a path
  no in-tree reference takes (B = generic Lua + new client; SOTN =
  custom Lua + old-style client; we'd want custom Lua + new-style
  client).

**Complexity**: Medium-high. All of B's complexity plus a Lua module to
write and maintain.

**DW1-specific interactions**
- Multi-track CUE: same as B (patch only the data track).
- In-game clock cadence: this is where C earns its keep — Lua can
  observe day rollover frame-precisely if needed.
- Save format: same as B.
- Recruit state machines: Lua can detect recruit transitions across
  frames if there's no stable RAM bit, by watching the in-game state
  variables that drive the transition.

### Option D — Fallback only: PCSX-Redux + custom Lua + Python client over WebSocket

Reach for this only if B and C are demonstrated unworkable.

**Pros**
- PCSX-Redux has first-class Lua + GDB stub + JSON-WebSocket
  scripting, and is more accurate than Nymashock.
- Useful for RE work regardless — its debugger and watch tooling
  speed up address discovery.

**Cons**
- Smaller PSX-emulator user base; users who already installed BizHawk
  for other AP games would have to install another emulator just for
  DW1.
- We write a brand-new `client.py` (not `BizHawkClient`-shaped), a new
  Lua, and a new transport. Significant net-new work.
- Setup tutorial gets more complex (an extra emulator install).

**Complexity**: High. Roughly all of C plus a new transport and
client-base.

**DW1-specific interactions**
- Multi-track CUE: PCSX-Redux's CD-ROM scripting may differ from
  BizHawk's. Worth verifying separately if we go this path.
- Other interactions are similar to C.

### Option A — Continue the C# / `Archipelago.Core` path (DWAP route)

Match DWAP's existing architecture (Python apworld + external C#
runtime built on `Archipelago.Core`).

**Pros**
- Some of DWAP's code can be salvaged: option taxonomy, recruit
  prerequisite graph, item/location IDs.
- The author's `Archipelago.Core` may eventually mature into a useful
  generic emulator-attach library.

**Cons**
- Closed-source dependency we cannot audit
  (`https://github.com/ArsonAssassin/Archipelago.Core` is not in this
  clone). Behavior across DuckStation / PCSX / BizHawk versions is
  unverifiable.
- DWAP's only function-hook is broken: `RecruitmentFunctionAddress = 0x00000000`
  at [references/DWAP/source/DWAP/Addresses.cs:46](references/DWAP/source/DWAP/Addresses.cs).
  Fixing this requires an RE deliverable (find the actual function
  address) AND a redesign — function-hooks are version-fragile, while
  flag-poll (B/C) is not.
- No ROM patching at all today. Adding one requires re-deriving FFT's
  patcher work in C#.
- Direct unsynchronized memory writes in
  [references/DWAP/source/DWAP/Randomiser.cs](references/DWAP/source/DWAP/Randomiser.cs)
  are race-prone. Adopting FFT's `items_received`-counter pattern in
  C# is feasible but is net-new work.
- Two-language stack (Python apworld + C# runtime) doubles the
  contributor onboarding cost compared to B/C.

**Complexity**: High. The visible source is small but the unseen
dependency is the actual cost.

**DW1-specific interactions**: largely the same as B at the game level,
but the runtime-level guarantees we'd inherit are weaker.

### Client implementation (under Option B, the favored option)

- Live in `worlds/digimon_world/client.py` and inherit from
  `worlds._bizhawk.client.BizHawkClient`. Mirror FFT's
  [Client.py](references/fft_ivalice_island/) pattern.
- Required class vars: `system = "PSX"`, `game = "Digimon World"`,
  `patch_suffix = ".apdw1"`.
- Implement `validate_rom()` (read game-id string at the standard
  ISO9660 PVD location, then check a slot ROM-name we wrote into a
  known RAM offset during patching) and `game_watcher()`
  (memory poll loop with FFT's three-pathway split: bitfield diffs for
  major locations, recruit checks, item-flag checks).
- Reuse the bundled `data/lua/connector_bizhawk_generic.lua`. **No
  custom Lua under Option B.** (Switch to C only if a discovered event
  class makes that necessary.)
- Item-receive: copy FFT's `items_received` counter + per-category
  atomic dispatch pattern. Categories for DW1 are likely: consumable
  (write to inventory bank at 0x001BDF2C, capped at slot count),
  recruit-soul (bitfield OR), money (4-byte add to `CurrentBits =
  0x00134EB8`), technique (write into the technique table at
  0x0012623C).
- Slot authentication: write the slot name as ASCII bytes into a known
  RAM location during patching; client reads it back via
  `validate_rom`.

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

### Item-receive / location-check hooks — **flag-poll + counter-driven dispatch (FFT pattern)**

Mechanism modeled on FFT Ivalice Island
([REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 3.3), with concrete addresses
**TBD** as part of the Phase 0 RAM-map cross-reference:

- **Location checks**: poll the live save block's flag region at ~10 Hz; diff against the
  last-seen snapshot; emit `LocationChecks` for any newly-set bits. Reuse existing in-game
  flags (recruitment state, prosperity points, area-unlock bits, boss-defeated bits like
  `HasBeatenDrimogemon = 0x001BE130`) where they exist 1:1 with AP location IDs. Locations
  that have no stable RAM trace (e.g. some chest pickups) become a Phase 3 RE deliverable:
  either find a derived state we can read, or — only if necessary — install a
  one-instruction hook to set an AP-flag bit during patching.
- **Item receive (FFT pattern)**: a 2-byte LE `items_received` counter at a known RAM
  address tracks how many items the client has applied. The client compares it against
  `len(ctx.items_received)` and dispatches the next item by category — gear → write to
  inventory bank at `ItemBankBaseAddress = 0x001BDF2C` (capped at slot count); recruit-soul
  → bitfield OR; money → 4-byte add to `CurrentBits = 0x00134EB8`; technique → write into
  the technique table at `TechniqueStartAddress = 0x0012623C` — then increments the
  counter. The counter pattern is robust to game-loop interference (FFT validates this in
  production); the queue-and-drainer pattern from earlier drafts is no longer recommended
  because it requires a patched in-game routine, which we should avoid unless we discover
  a category of items that genuinely cannot be applied as direct writes.
- **Goal completion**: poll a known "ending reached" flag in the live save block — DW1
  almost certainly has one (the game tracks completion). If not, fall back to polling the
  ending-cutscene trigger room id. Send `StatusUpdate(GoalComplete)` on first set.

The hard part is **finding the addresses** and **mapping recruit/event RAM bits 1:1
to AP location IDs**. DWAP's address map ([REFERENCES_NOTES.md](REFERENCES_NOTES.md)
section 1.3) and the standalone randomizer's ROM-offset catalog
([REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.2) cover most of the surface.
Gaps to close: the recruit-completion bit per Digimon (likely exists in save state but not
enumerated by either reference), and the AP-flag scratch region inside the live save
block.

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

**Goal:** lock the remaining decisions and verify the residual risks before
any code is written.

- Confirm the canonical MD5 / SHA-256 for the SLUS-01032 redump.org "good" dump.
  FFT uses an MD5 in [Rom.py](references/fft_ivalice_island/) checked at host.yaml load
  time via a `Settings` declaration — copy the pattern.
- Run the BizHawk + Nymashock smoke test (one line, no longer make-or-break):
  load any PS1 game, load `data/lua/connector_bizhawk_generic.lua`, read 4 bytes at
  System Bus 0x80000000, confirm sensible bytes. Expected to pass; FFT, SOTN, and
  Ape Escape all run on this stack.
- Verify whether SLUS-01032 is multi-track BIN/CUE (audio tracks present?) and whether
  it is Mode2/2352. Both affect the patcher's track-aware logic. FFT's magic numbers
  (`sector_size = 0x930`, `data_size = 0x800`, `header_size = 0x18`, `ec_size = 0x118`)
  apply directly if Mode2/2352 holds.
- Lock in the architecture choice (Option A / B / C / D from section b). Recommend B
  unless the human prefers otherwise.
- Decide MVP scope (Q5).
- Cross-reference the DWAP RAM addresses ([REFERENCES_NOTES.md](REFERENCES_NOTES.md)
  section 1.3) and the standalone randomizer ROM offsets
  ([REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.2) into a unified DW1 address
  manifest. This is a lookup pass, not RE work; it produces the data file Phase 3 will
  consume.

Exit criteria: architecture choice locked, ISO identity confirmed, MVP scope agreed,
unified DW1 address manifest exists in (yet-uncreated) `worlds/digimon_world/data/`.

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

1. **Q1 — BizHawk PSX-core viability. ANSWERED (no longer blocking).** FFT Ivalice Island,
   SOTN, and Ape Escape all run on BizHawk + Nymashock in production
   ([REFERENCES_NOTES.md](REFERENCES_NOTES.md) sections 3 and 4). The remaining smoke test
   is a one-line confirmation: open BizHawk, load any PS1 game, load
   `data/lua/connector_bizhawk_generic.lua`, run a tiny Python script that reads 4 bytes
   at System Bus 0x80000000, confirm sensible output. **Phase 0 deliverable, but does
   not block planning.**
2. **Q2 — RAM map availability. PARTIALLY ANSWERED.** DWAP exposes 21 named addresses in
   [Addresses.cs:9-48](references/DWAP/source/DWAP/Addresses.cs) including
   `ItemBankBaseAddress = 0x001BDF2C`, `ProsperityPoints = 0x001BE032`,
   `HasBeatenDrimogemon = 0x001BE130`, `MeramonTunnel_*`, `Starter1/Starter2`,
   `TechniqueStartAddress = 0x0012623C`, `LearningChanceStartAddress = 0x00125FA4`. The
   standalone randomizer adds the full ROM-offset catalog ([data.py](references/digimon_world_randomizer/digimon/data.py)
   and [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.2). Open subquestions:
   - The recruit-event entry point that DWAP left as `0x00000000` — needed only if we choose
     Option C (synchronous recruit detection) over Option B (poll-based).
   - The AP-flag scratch region inside DW1's live save block (must survive save/load,
     must not collide with the game's checksum).
   - The exact recruit-completion bit per Digimon (likely exists since DW1 itself tracks
     recruits in save state; not enumerated by either DWAP or the standalone).
3. **Q3 (still pending) — Source ISO identity.** Which exact dump are we targeting?
   redump.org SLUS-01032 is the canonical answer, but the SHA-256 / MD5 of the user's
   actual file on disk is needed for the patcher's hash check. FFT uses an MD5 in
   `Rom.py` (`hash = "b156ba386436d20fd5ed8d37bab6b624"`) checked at host.yaml load time
   via a `Settings` declaration. Are we supporting only USA, or also EU / JP later?
   (Recommendation: USA only for v1, document EU / JP as future work.)
4. **Q4 — Prior APWorld inheritance. ANSWERED.** The previous community implementation is
   DWAP, now under [references/DWAP/](references/DWAP/) for study. Findings:
   - Memory map: 21 RAM addresses, useful starting point for Option B's RAM-flag mapping.
   - Recruit prerequisite graph: 51 entries in
     [RecruitDigimon.py](references/DWAP/Apworld/dw1/RecruitDigimon.py), useful for
     [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.5's progression notes.
   - Cannot inherit the C# runtime (closed-source `Archipelago.Core` dependency).
   - Should NOT inherit the recruit-detection design — `RecruitmentFunctionAddress = 0x00000000`
     at [Addresses.cs:46](references/DWAP/source/DWAP/Addresses.cs) means the hook never
     installs. Use flag-poll instead (Option B).
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

- **BizHawk + Nymashock is now proven** by FFT, SOTN, and Ape Escape. The Q1 risk is
  largely retired; only a one-line smoke test remains.
- **PS1 ISO patching has a precedent we can follow now.** FFT's
  [Rom.py](references/fft_ivalice_island/) shows the in-tree pattern: load the user's
  vanilla `.bin` from a host.yaml setting, apply tokens + sector-aware writes in memory,
  run an `ErrorRecalculator` step for EDC, write the patched `.bin` and a regenerated
  `.cue`. Mode2/2352 magic numbers from FFT's `Rom.py`: `sector_size = 0x930`,
  `data_size = 0x800`, `header_size = 0x18`, `ec_size = 0x118`. Whether SLUS-01032 is
  Mode2/2352 specifically is to be confirmed, but the magic numbers are FFT-tested and
  ready.
- **Standalone randomizer's `.bin`-as-flat-bytestream approach is a cautionary tale.** It
  does no sector-aware writing and no EDC/ECC recalculation
  ([REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.3). It works in practice for DW1
  with permissive emulators but is not a correctness guarantee. We should NOT inherit
  this shortcut — copy FFT's `ErrorRecalculator` pattern instead.
- **Multi-track CUE files** can desync if we regenerate the `.cue` incorrectly. FFT
  regenerates a single-track `.cue` referencing only the patched `.bin`; if SLUS-01032
  ships with audio tracks we need a multi-track `.cue` regeneration step we will have to
  author. Whether SLUS-01032 has audio tracks is a five-minute check (Q9).
- **The DWAP recruit-hook gap** is the highest-priority RE deliverable IF and only if we
  choose Option C (custom Lua + synchronous recruit detection). Under Option B
  (flag-poll), it is replaced by an enumerate-the-recruit-bits task that's strictly
  easier.
- **DWAP's direct-write race condition** (unsynchronized memory writes in
  [Randomiser.cs:55-74](references/DWAP/source/DWAP/Randomiser.cs)) is a pattern we
  should avoid. Copy FFT's `items_received` counter + per-category atomic dispatch
  pattern instead.
- **`bsdiff4` over a 700 MB ISO** would be painful for per-seed patches. FFT solves this
  by shipping pre-built bsdiff4 base patches (one per option-set) inside the world
  package, then layering token writes per seed. We can copy this pattern if we ever need
  mass ROM changes that are awkward as token writes.

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
- [worlds/pokemon_emerald/](worlds/pokemon_emerald/) — in-tree reference for the
  `BizHawkClient` + `APProcedurePatch` pattern (GBA, but transferable shape).
- [worlds/tww/](worlds/tww/) — reference for the disc-image / external-patcher mental model.
- [BaseClasses.py](BaseClasses.py), [worlds/AutoWorld.py](worlds/AutoWorld.py) — required reading.
- [rule_builder/](rule_builder/) — preferred logic-rule style for new worlds.
- [Options.py](Options.py), [settings.py](settings.py) — option/setting bases.
- [test/bases.py](test/bases.py), [test/general/](test/general/) — test infrastructure.

Reference projects to study (under `references/`, study-only — see
[REFERENCES_NOTES.md](REFERENCES_NOTES.md)):

- **`references/fft_ivalice_island/`** at branch `origin/finalfantasytactics`,
  world at `worlds/fftii/`. **Highest priority.** PS1 USA on
  BizHawk + Nymashock + APProcedurePatch + the generic Lua connector. Full anatomy in
  [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 3.
- **`references/sotn_archipelago/`** with the world at `worlds/sotn/`, custom Lua at
  `data/lua/connector_sotn.lua`, and the older client at the clone-root
  `SOTNClient.py`. Used for the custom-Lua case study, NOT for multi-track BIN/CUE
  reasoning ([REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 4).
- **`references/DWAP/`** for the DW1 RAM map and the recruit prerequisite graph; do not
  inherit the C# runtime. See [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 1.
- **`references/digimon_world_randomizer/`** for the DW1 ROM-offset catalog,
  bug-fix / softlock list, and implicit progression notes. See
  [REFERENCES_NOTES.md](REFERENCES_NOTES.md) section 2.
