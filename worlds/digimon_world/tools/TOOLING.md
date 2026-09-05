# DW1 Reverse-Engineering Tooling

Automated RE lab for the Digimon World 1 APWorld. The player-facing clients stay on
BizHawk/Duckstation — everything here is workbench-only. Set up 2026-08-19; everything below was
downloaded, installed and smoke-tested autonomously (no manual steps pending except where noted).

## Installed tools (all portable)

| Tool | Where | Version | Notes |
| --- | --- | --- | --- |
| PCSX-Redux | `C:\opt\tools\pcsx-redux\` | nightly 25006.20260812.2 (2026-08-12) | SHA1-verified zip from the official distrib.app channel. Also ships `exe2elf`, `exe2iso`, `ps1-packer`, `psyq-obj-parser`. |
| PCSX-Redux docs (offline mirror) | `C:\opt\tools\pcsx-redux\docs-mirror\` | snapshot 2026-08-19 | `.html` + extracted `.txt` of the Lua/debugger/REST docs. |
| Ghidra | `C:\opt\tools\ghidra\ghidra_12.1.2_PUBLIC\` | 12.1.2 | 12.1.2 (not 12.1.3) chosen to match the newest ghidra_psx_ldr release. Needs `JAVA_HOME=C:\opt\java\Java21` (already on the machine). |
| ghidra_psx_ldr | `...\Ghidra\Extensions\ghidra_psx_ldr\` | 2026.07.08 build for 12.1.2 | PSX EXE loader + PsyQ signatures + `.gdt` type archives + a PSX SYM importer script. |
| Download cache | `C:\opt\tools\_downloads\` | — | The original zips, in case a reinstall is needed. |

## Workbench directory: `work\dw1_re\` (gitignored)

Game-derived artifacts and per-session state. Never committed. Contains:

- `SLUS_010.32` — boot executable extracted from the .bin (see `dw1_iso_extract.py`).
- `ghidra\DW1.gpr` — analyzed Ghidra project: language `PSX:LE:32`, SLUS loaded at its real base
  `0x80090800` (entry `0x800A4240`), ~1785 functions. Named coverage: 623 PsyQ library functions
  (signatures) + 262 game functions imported from `references/DW1-Code/memoryMap.txt` (SLUS
  section, applied 2026-08-19 with plate comments carrying Syd's signatures). The runtime
  `$gp = 0x8013BB2C` (crt0 loads it from `0x80113A64`) is set program-wide, so gp-relative
  accesses decompile to absolute `DAT_8013xxxx` addresses. Open with
  `C:\opt\tools\ghidra\ghidra_12.1.2_PUBLIC\ghidraRun.bat` (set `JAVA_HOME=C:\opt\java\Java21`
  first) or drive headless via `support\analyzeHeadless.bat`.
- `slus_symbols.txt` — the extracted `ADDR name signature` table used for that import
  (regenerable from `references/DW1-Code/memoryMap.txt`).
- `pcsx.json` — PCSX-Redux portable settings (the launcher runs redux with CWD here, so `-portable`
  state lands in this folder). The launcher pre-seeds `emulator.Debug.WebServer/Debug/GdbServer`.
- `redux_smoke_ram.bin` / `redux_smoke.state` / `dw1_watch_log.txt` / dumps — session outputs.

## The scripts (this directory)

| Script | Role |
| --- | --- |
| `dw1_redux_launch.ps1` | One-command launch: seeds `pcsx.json`, chains Lua bootstrap + optional harness script, starts redux with `-interpreter -debugger -iso <bin> -fastboot -run -portable`. Flags: `-Script <lua>`, `-Gdb`, `-Paused`, `-Iso <path>`. |
| `dw1_redux_bootstrap.lua` | Loaded on every launch. Registers REST handlers `/api/v1/lua/{ping,quit,eval,run}` — arbitrary Lua from Python, so watchpoints can be armed/disarmed mid-session without restarting. `eval` takes `?code=` (redux rejects URLs over ~256 bytes); `run` executes a file from the CWD, which `dw1_redux_api.py` uses automatically for longer code. Verified end-to-end 2026-08-19. |
| `dw1_redux_watch.lua` | Watchpoint harness ("who touches this byte?"). Reads `dw1_watch_config.lua` from `work\dw1_re` (falls back to the trigger array). Each hit logs `cycles, name, type, width, addr, pc, ra, value` to `dw1_watch_log.txt`. Feed the `pc` to Ghidra. |
| `dw1_redux_smoke.lua` | Boot → wait ~25 s → dump 2MB RAM + savestate → quit. Validated 2026-08-19 (markers `MAYO/MGEN/OGRE` found in the dump). |
| `dw1_redux_api.py` | Python driver for the REST API (stdlib only). `status/dump/peek/poke/pause/resume/reset/symbols/lua/quit/ping/check-dump`. `peek` reads through Lua (`getMemPtr`) — the raw-RAM GET ships all 2 MB and crashed live sessions. Offsets are physical (BizHawk `MainRAM` convention, same as `data/addresses.py`). |
| `dw1_iso_extract.py` | List/extract root files from the .bin (ISO9660 over Mode2/2352). Already used to pull `SLUS_010.32`; the overlays (`SHOP_REL.BIN`, `BTL_REL.BIN`, `STD_REL.BIN`, …) are one command away. |
| `dw1_redux_vectors.lua` | Call-vector capture for decomp verification (config-driven Exec breakpoints logging args/memory/returns as JSONL). See [DECOMP_PROCESS.md](DECOMP_PROCESS.md). |
| `dw1_redux_input.lua` | Scripted play: `dw1_press({'RIGHT','CROSS'})` timed tap queue + `dw1_masher('x'/'title')`. Installable live via `dw1_redux_api.py lua "Support.extra.dofile(...)"`. |
| `dw1_redux_screenshot.py` | The "eyes": `PCSX.GPU.takeScreenShot()` through the Lua endpoint → PNG (16/24-bit). Safe while the game runs. `--vram x y w h` keeps the raw VRAM REST path for texture pages — parked emulator only, it segfaults live sessions. |
| `dw1_ghidra.ps1` | Standard headless Ghidra wrapper (JAVA_HOME, project, script path handled). |
| `ghidra_scripts/DW1ExportFunc.java` | Exports one function's decomp.c + listing.asm + refs.txt bundle for the decomp pipeline. |
| `ghidra_scripts/DW1ImportSymbols.java` | Imports dw_decomp's `config/symbols*.txt` into the project (primary names where Ghidra had `FUN_`/`DAT_`, secondary labels otherwise). Writes the project — run WITHOUT `-ReadOnly`, serialized. Applied 2026-08-28 (6648 symbols). |
| `ghidra_scripts/DW1FunctionStats.java` | Whole-program function census (address, name, size, callers, callees) to a TSV — the decomp coverage denominator. |
| `ghidra_scripts/DW1ImportHeaders.java` | Parses dw_decomp's `include/dw/*.h` into the program's data-type manager, resolving PsyQ types (`POLY_FT4`, `DVECTOR`, ...) from the psx-loader's `psyq350.gdt` instead of parsing PsyQ headers; `<libgte.h>` etc. resolve to empty stubs in `work/dw1_re/ghidra_stub_includes/` (`setjmp.h` stub must define `jmp_buf`). Applied 2026-08-28: 48/48 headers, 1827 types. |
| `ghidra_scripts/DW1ApplyExternTypes.java` | Applies those types to the globals: every `extern <Type> NAME[dims];` in `include/dw/` sets the data type at NAME's address; unsized `[]` arrays take their length from `symbols.txt` sizes. After this the decompiler renders `PARTNER_ENTITY.learnedMoves[1]` instead of a raw pointer deref. Run after the two imports above. |
| `dw1_hub_rebuild.py` | **Rebuilds the teleport hub `debug_warp.state` from a cold boot, unattended** (title -> new game -> intro mash -> debug NPC set -> Mr. Warp's menu -> save -> self-test). See "Rebuilding the lab from nothing" below. |
| `dw1_warp_state.py` | **Unattended savestate on any screen.** Loads the `debug_warp.state` hub (debug map, Mr. Warp open), pokes the resident script 164's warp byte (+1941 at 0x1B9ED8) to the target map id, presses CROSS twice through a self-removing Vsync listener, waits until `CURRENT_SCREEN` (0x134DA8) matches, then saves. `--god`, `--set-trigger N`, `--poke ADDR:HEX` (the hub's `warpTo` operand bytes sit at 0x1B9ED8+1940 = `4B 12 00 FF`: `--poke 0x1BA66E:<exit>` selects the landing exit slot, e.g. the arrival-only spawn of a dead slot = the far mouth of a screen) (applied after the hub state loads -- the way to test a MAPHEAD.SCN patch, whose boot-resident copy at 0x1B1D30 every savestate restores). Validated 2026-08-28 on screens 141, 6, 0 and 2. |
| `dw1_enemy_census.py` | **Every field Digimon on the disc.** Parses each screen's `.MAP` entity records (species, position, hp/mp/off/def/spd/brn/bits, 4 move anim-ids + priorities, script id) into `work\dw1_re\enemy_census.tsv`; `--map N` prints one screen; `--bin` reads a patched disc (net-1 round-trip for record patches); `--emit-python` regenerates the world's `data/enemy_records.py` (full `MOVE_DATA` rows, species table with model heap sizes and drops, `ITEM_PARA` names/prices/sort/dropable, the 7x7 element matrix, the three digivolution tables, records, MAPHEAD `loadDigimon`/`setDigimon` sites); `--check-dump` proves the MAPHEAD opcode scan against the reference disassembly (1177/1177 on 2026-08-28). Needs `work\dw1_re\iso_files.json` (ISO file table) and `SLUS_010.32`. |
| `dw1_mmd_census.py` | **Animation tables of every species' `.MMD` model.** Resolves `\CHDAT\MMDn\{code}.MMD` per species, reads the animation offset table (`mmd + u32[1]`, table-relative offsets, 0 = absent, length = first offset / 4) and reports, per species, how many technique ids `0x2E..0x3D` carry an animation versus how many list slots `DIGIMON_DATA` populates -> `work\dw1_re\mmd_census.tsv`; `--species N` dumps one table. Result (2026-08-29): lists can only be re-filled **in place** (140 species exact, MegaSeadramon / Machinedramon one spare slot, Kuwagamon clone 169 none) — the basis of `species_technique_lists`. |
| `dw1_decomp_xref.py` | Bridge from our address manifest to dw_decomp: for any RAM address, its dw_decomp symbol (+offset), and for functions whether it is in C (which file) or an `INCLUDE_ASM` stub. `--lookup` for one address; `-o DW_DECOMP_XREF.md` regenerates the committed table. |
| `dw1_apply_patch.py` | One patch spec (JSON), three nets: `apply` (live-RAM pokes), `verify` (readback diff — works on poked RAM and on a booted patched ISO), `to-iso` (sector-aware .bin build + EDC recalc). See [PATCH_PROCESS.md](PATCH_PROCESS.md). |
| `DECOMP_PROCESS.md` | The standardized function-decomp pipeline (pilot-proven; agent + workflow available). |
| `PATCH_PROCESS.md` | The standardized patch-test loop built on top of the decomp output (PoC-proven; `dw1-patch` agent available). |

Also portable in `C:\opt\tools\`: **w64devkit 2.9.1** (`w64devkit\bin\gcc.exe`, host gcc for verifying
decompiled C — prepend its bin to PATH so gcc finds `as`).

## Address conventions

- PSX main RAM: 2 MiB, mirrored at `0x00000000` (KUSEG) / `0x80000000` (KSEG0) / `0xA0000000` (KSEG1).
- Project canonical form (addresses.py, BizHawk `MainRAM`, redux REST `offset=`): **physical** `0x001BDFCD`.
- Redux Lua breakpoints and Ghidra listing: **KSEG0** `0x801BDFCD`. `dw1_redux_watch.lua` accepts
  either and normalizes; `dw1_redux_api.py` is physical-only.

## Workflows

1. **Unknown data → address** ("which byte holds X?"): snapshot + diff. Either the existing BizHawk
   flow (`dw1_ram_snapshot.lua` + `dw1_ram_diff.py`, still canonical) or headless via redux REST:
   `python dw1_redux_api.py dump a.bin` → provoke event (savestates help) → `dump b.bin` → diff.
2. **Known data → code** ("who reads/writes this byte?"): watchpoint. Launch with
   `-Script dw1_redux_watch.lua` (or arm live via `dw1_redux_api.py lua "..."`), provoke the event
   once, read `pc`/`ra` from `dw1_watch_log.txt`. No snapshot grinding, no manual RAM Search.
3. **Code → understanding**: open `work\dw1_re\ghidra\DW1.gpr`, jump to the `pc`. PsyQ library calls
   are already named; cross-check identity against `references/DW1-Code/memoryMap.txt`.
4. **Symbols → emulator**: export a Ghidra `Name address` map and
   `python dw1_redux_api.py symbols file.map` — the redux disassembler then shows real names.
5. **Overlays**: the per-mode code (`SHOP_REL.BIN` etc.) is not part of the SLUS image. Extract with
   `dw1_iso_extract.py`, import into the Ghidra project as raw MIPS at the load address documented in
   `references/DW1-Code/memoryMap.txt`, analyze with the same PsyQ setup.

## Deliberately not installed

- **gdb-multiarch / Ghidra live-debug bridge**: the Lua watchpoint + REST `eval` path covers the
  find-code doctrine without it, and a portable Windows gdb-multiarch means dragging in MSYS2.
  Escalate only if a workflow genuinely needs source-level stepping from Ghidra; redux's own
  debugger UI (`-Paused`, breakpoint panes) covers interactive needs meanwhile. The `-Gdb` launcher
  flag already exposes the server on port 3333 for any external gdb.

## Known quirks

- **Lab facts from the 2026-08-29 patch missions** (Gekomon splice, Ogremon chain guards):
  - PCSX-Redux with the debugger on **pauses itself on an invalid memory access**; a paused
    emulator makes every later savestate load look dead (black screen, `TAMER_STATE` 6, CPU parked
    in `CdReadSync`/`VSync`). Check `execution-flow` (`"running": false`) before blaming a state,
    and resume *after* loading the next state.
  - Teleporting the tamer needs BOTH `PositionData.location` (posData + 0x78, authoritative) and
    `Entity.anim.locX/locZ` (what the renderer/collision read) written in one tick; a second
    teleport on the same live screen desyncs the walking state (turns, never translates).
  - NPC talk is collision-based, not proximity-based (`entityCheckCollision` steps the tamer
    forward and returns the `ENTITY_TABLE` index hit; `TALKED_TO_ENTITY` 0x134C9C names it): move
    the NPC onto the tamer to drive one specific dialog.
  - Screen change without walking: `TARGET_MAP` 0x134DE0 + `CURRENT_EXIT` 0x134DAA +
    `TAMER_STATE` 0x134C91 = 5 (substate 0) runs vanilla `tickChangeMap` — a real disc reload.
  - Post-battle results are three boxes, each waiting for a CROSS *edge* with
    `POLLED_INPUT == 0x40` exactly; a driver that stops pressing while `GAME_STATE != 0` stalls in
    state 2. God-mode states pop the award box on load (`TAMER_STATE` 20); one CROSS dismisses it.
  - The engine's `setTrigger` store is at pc 0x801065E8 (ra 0x801065D4) — a reusable write-
    watchpoint anchor for trigger provenance. `NPC_ENTITIES` keeps stale records of earlier
    screens: "placed" = the `ENTITY_TABLE[slot+2]` pointer is non-NULL.
  - MAPHEAD.SCN is boot-resident at 0x1B1D30: poke `0x1B1D30 + file offset` BEFORE the screen
    loads (hub-derived states restore the boot copy). Rotation: `_atan(dz, dx)`, +z = 2048.

- **Lab facts from the 2026-08-30 → 09-01 missions** (free flights, client gates,
  factorial gate):
  - **Pin `pcsx.json` `pads[*].PadType = 2` (Keyboard) — never 0 (Auto).** Auto merges any
    host controller into emulated pad 1; a drifting device held phantom UP+LEFT for two whole
    missions and fabricated "game bugs" (a fake arrival soft-lock, an immobile pocket, a
    warp bounce loop) plus Mr.-Warp cursor drift that got `dw1_warp_state.py` wrongly blamed.
    Preflight every session: sample `POLLED_INPUT` 0x134EE4 a few times — a constant nonzero
    read (especially a high nibble) means phantom pad; stop everything and fix the config
    first. Enum: 0 = Auto, 1 = Controller, 2 = Keyboard. The workbench `pcsx.json` is pinned.
  - Pad driving: `pad().setOverride(...)`/`clearOverride(...)` are **dot-called** with the
    button as first arg (the colon form throws). On the title menu keep taps <= 0.1 s —
    auto-repeat kicks in at ~5 frames and DOWN+CROSS lands on the DELETE GAME row.
  - **DG.SCN slot 0 is a DEAD byte-identical copy of MAPHEAD.SCN**: `getScript(0)` always
    returns the boot-resident copy, so a "script 0" .bin offset in 0x13FD5DB8..0x13FDD528
    does nothing at runtime. Disc patches target MAPHEAD.SCN's own footprint (LBA 142982,
    file offset == VM offset); live pokes go to 0x1B1D30 + vm. MAPHEAD also carries
    engine-only section ids >= 255 (1245 = Auto Pilot City-Top ladder, 1246 partner-death,
    1250-1253), reachable only via `callScriptSection`; the running section id is stored
    u8-truncated at 0x134FE4.
  - Robust position read: `STORED_TAMER_POS` 0x138720 — the 0x15576C entity chain goes NULL
    during transitions (bites `dw1_gate_fix_live.py player_pos`). Robust scripted crossing:
    poke the runtime MAP_WARPS tables (0x138780/0x138794) and plant collision cell 110
    under the pair. Savestates taken < 30 s after a warp can freeze the walk-in mid-flight —
    gate saves on position stability plus a pad probe.
  - Repeated full-RAM REST dumps plus savestate/pause churn kill the emulator silently (the
    known 2026-08-28 class); use region dumps (`work\dw1_re\cg_regdump.lua` pattern) for
    state comparisons.
  - Forged `callScriptSection` calls sometimes initialize the VM but never tick — reload the
    state and retry. An invalid context (script needing a live map, forged from the naming
    screen) can leave the CPU in the BIOS: reboot the emulator, don't trust the session. When
    an in-situ call hijacks a gp-relative global, stop on an Exec breakpoint at the park loop
    and restore the global immediately — a wall-clock sleep lets the live screen's own code
    scribble through the hijacked pointer.
  - Net-1 upgrade: `work\dw1_re\decomp\free_flight\r3000.py` is a reusable MIPS-I
    interpreter that replays the actual SLUS instruction words with stubbed callees — the
    cheapest way to make net 1 validate *bytes* rather than a hand model.

- **User-driven (live) sessions, rules from three crashes on 2026-08-28**: no per-frame Lua
  listeners (`dw1_redux_input.lua`) while the user plays, no REST data GETs (`/cpu/ram/raw`,
  `/gpu/vram/raw`), and wrap `PCSX.createSaveState()` in `pauseEmulator()`/`resumeEmulator()`.
  Lua evals were fine throughout. Scripted lab sessions (nobody at the pad) may use the
  harness listeners as before.

- First launch of a **fresh** workbench dir would normally start with the web server off; the
  launcher's `pcsx.json` pre-seed avoids that. If REST ever refuses connections, check
  `work\dw1_re\pcsx.json` has `emulator.Debug.WebServer: true` and relaunch.
- `pcsx-redux.exe` is a GUI app: PowerShell does not block on it, and `print()` from Lua only
  reaches the console/logfile reliably for scripts that also write their own files. Treat files in
  `work\dw1_re` as the source of truth for harness output.
- The REST server listens on localhost:8080 with no auth, and `eval` executes arbitrary Lua —
  workbench convenience by design; don't expose the port.
- `pcsx-redux.exe` is only a launcher wrapper: the real process is **`pcsx-redux.main`** (plus a
  `crashpad_handler`). Prefer the graceful `python dw1_redux_api.py quit`; if you must force-kill,
  target `pcsx-redux.main` — `taskkill /IM pcsx-redux.exe` kills the wrapper and leaves the
  emulator window open.
- Stability (observed 2026-08-20 during vector capture): `pcsx-redux.main` died silently twice,
  both right after full-RAM REST reads (`/api/v1/cpu/ram/raw`) while Exec breakpoints were
  armed. Mitigations: avoid full-RAM `dump`/`peek` mid-capture (peek fetches the whole 2MB),
  archive `vectors.jsonl` often (it flushes per write, so nothing is lost), keep capture
  sessions short. Two more silent deaths later the same day (one after a VRAM screenshot with
  Exec breakpoints armed, one idle with only a write watch): while ANY breakpoint is armed,
  prefer small targeted reads via Lua `PCSX.getMemPtr()` in an `eval` over REST peeks, and
  keep screenshots sparse.
- Pad-override input timing (`dw1_redux_input.lua`): short taps (the default 8-frame hold)
  reliably initiate dialogs / confirm, but MENU navigation (cursor movement) responds better
  to ~0.35 s holds — pass a larger `hold` in the press queue when moving through menus.
- Stability, extended (2026-08-20 play session): the emulator also crashed with ZERO
  breakpoints armed while a Lua Vsync poller read ~20 KB/s via `getMemPtr` — for long live
  play sessions run NO persistent Lua at all and touch REST only while the player is parked
  (savestate saves, small peeks). Never live-toggle subsystem settings
  (`PCSX.settings.spu.UseNullSync = true` crashed it instantly); no reliable turbo/speed-up
  exists in this nightly. Known emulation bug: DW1's post-arena-fight exit transition hangs
  deterministically (BIOS-event busy-wait, ra=0x800C8F98) — works on BizHawk/Duckstation.
- Keyboard pad bindings (from `pcsx.json` `Keyboard_Pad*`): X=CROSS, S=TRIANGLE, D=CIRCLE,
  Z=SQUARE.
- Long-lived Lua pollers must RE-FETCH `PCSX.getMemPtr()` inside the poll loop — a pointer
  captured once at script load can go stale across internal reallocation (observed
  2026-08-20: canary probe reading stale memory).
- **Crash root cause found (2026-08-22)**: the REST raw-RAM endpoint IGNORES the `size`
  parameter and always returns the full 2 MB per call — `dw1_redux_api.py peek` therefore
  transfers 2 MB every time, which reliably crashes `pcsx-redux.main` mid-play. Read via
  small Lua `getMemPtr` loops in an `eval` instead; keep REST `peek`/`dump` for parked,
  breakpoint-free moments only.
- Reusable in-situ call harness: `work\dw1_re\dw1_call_harness.lua` (pause → forge
  GPR/pc, park ra at a scratch address → resume → read v0/memory). Judge results by
  v0+memory effects, never by the paused pc (often mid-vblank at 0x80000080).

## Rebuilding the lab from nothing (proven 2026-09-05, after the loss of `work/`)

`work/` is gitignored and was wiped once (see STATUS.md). Everything in it is regenerable in
under an hour from the repo, the game image at the repo root and the references:

| Piece | How | Time |
| --- | --- | --- |
| `work\dw1_re\SLUS_010.32` | `python worlds\digimon_world\tools\dw1_iso_extract.py extract SLUS_010.32 work\dw1_re` | seconds |
| Ghidra project `work\dw1_re\ghidra\DW1.gpr` | `analyzeHeadless work\dw1_re\ghidra DW1 -import work\dw1_re\SLUS_010.32 -scriptPath worlds\digimon_world\tools\ghidra_scripts` (the psx loader autodetects the PS-X EXE; ~1 min of analysis), then `dw1_ghidra.ps1 -Script DW1ImportSymbols.java <all references\dw_decomp\config\symbols*.txt>`, `-Script DW1ImportHeaders.java references\dw_decomp\include <ext>\data\psyq340.gdt`, `-Script DW1ApplyExternTypes.java references\dw_decomp\include\dw`. Expected: ~1773 functions, ~9200 symbols (1154 FUN_ renamed, 6800 data labels), 46/48 headers (script.h/btl.h fail to parse, known), 143 extern types. | 5 min |
| `pcsx.json`, `boot.lua`, memcards | created by `dw1_redux_launch.ps1` (`-FreshCards` before ANY new game: a NEW GAME occupies its save slot the moment it is created, and the START SLOT screen then refuses slot 1). **Then pin `pads[*].PadType = 2`** and relaunch: the default `0` (Auto) merges a drifting host controller into pad 1 and the title-menu cursor wanders (phantom pad). | 1 min |
| `debug_warp.state` (the teleport hub) | `python worlds\digimon_world\tools\dw1_hub_rebuild.py` — cold boot -> NEW GAME -> CROSS masher through the intro (name defaults to `AAAAAA`) -> outside Jijimon's house (map 204, script 164) -> debug NPC set -> Mr. Warp's menu -> save; ends with a `dw1_warp_state.py` self-test. | ~8 min |
| Every other field savestate | `dw1_warp_state.py --map <id> --out <name> [--god] [--set-trigger N] [--poke ADDR:HEX]` from the hub. `work\dw1_re\SAVESTATE_REBUILD.md` lists the recipes and the few states that need a human at the pad. | 20 s each |

Facts the hub rebuild relies on (all live-verified 2026-09-05):

- The debug NPC set is loaded by **MAPHEAD Section_204** (`setScript 164 204`) only when triggers 54
  AND 55 are both clear **at the moment map 204 loads** (`if trigger(55) == false` -> `if trigger(54)
  == true` -> else `setDigimon 117/30/117/117` into slots 0-3). A fresh game leaves 54 set (byte
  `0x1BDFD3` = 0x40), so: write 0, walk UP into the house (218), walk DOWN back out. Inside the
  house the resident script is 178 (193 during the intro); the debug NPCs stand outside, around the
  house, which is what "the debug NPCs render outside" meant.
- The intro visits map 204 twice (a brief "He arrived!" beat on 204, then the opening on 238, the
  house on 218, then 204 for real): "screen 204 + script 164" is only the end once no script runs
  any more (`IS_SCRIPT_PAUSED` 0x134FF4 == 1, the name is inverted) with the masher off.
- Door cells fire on ENTRY only: you spawn on the house door cell, so to leave you step away
  (~1 s) and walk back onto the arrival coordinates; holding DOWN alone never exits.
- Mr. Warp = NPC slot 0 of that set, script 164 **Section_5** (his talk: stat presets, a colour test
  box, the date, "I'm Mr. Warp", then `Near / Far away / Very far away`; the `Near` list is
  `warpTo 18 / 12 / 24` at +1940/+1944/+1948, which is the byte `dw1_warp_state.py` pokes).
  Jijimon's debug dialog (Giromon room / Toy deepest / Fight check / Last Battle) is Section_54.
- **NPC-move talk trick**: NPC talk is collision-based, so write the NPC's
  `PositionData.location.x/z` (posData+0x78/+0x80) AND `Entity.anim.locX/locZ` (entity+0x10/+0x18,
  value = coordinate << 15) to the tamer's position (+60 on x) and tap CROSS. Works from any distance.
  Tamer entity `0x15576C` (+4 = PositionData*), NPC entities `0x155828`, 8 x 0x68 bytes, `scriptId`
  at +0x65, `autotalk` +0x66, `isOnMap` +0x34.
- Reading RAM: only small Lua `getMemPtr()` evals. **Range-check every pointer before indexing** — an
  index past 2 MB (stale NPC `posData` on an unused slot) segfaults the emulator instantly.
- Pad: `setOverride/clearOverride` from a self-removing Vsync listener; 8-frame taps are enough. In
  the house, DOWN walks out through the door you came in by; outside, directions map to world axes
  as LEFT = -x, RIGHT = +x, DOWN+LEFT = (-x,-z), DOWN+RIGHT = (+x,-z), UP+LEFT = (-x,+z).
- Screen ids used by the regenerated states: item shop 216, secret shop 217, recycle 131, merit /
  Gekomon 141, gym 112, fishing 6, curling 134, arena 205, Birdramon Messenger 207 (ROOM12; the flight list needs his dialog open), Factorial gate 71/156,
  Mt. Infinity 219, Machinedramon 225, Back Dimension 226, opening 238, Jijimon's house 218.
