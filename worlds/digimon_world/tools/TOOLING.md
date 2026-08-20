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
| `dw1_redux_api.py` | Python driver for the REST API (stdlib only). `status/dump/peek/poke/pause/resume/reset/symbols/lua/quit/ping/check-dump`. Offsets are physical (BizHawk `MainRAM` convention, same as `data/addresses.py`). |
| `dw1_iso_extract.py` | List/extract root files from the .bin (ISO9660 over Mode2/2352). Already used to pull `SLUS_010.32`; the overlays (`SHOP_REL.BIN`, `BTL_REL.BIN`, `STD_REL.BIN`, …) are one command away. |
| `dw1_redux_vectors.lua` | Call-vector capture for decomp verification (config-driven Exec breakpoints logging args/memory/returns as JSONL). See [DECOMP_PROCESS.md](DECOMP_PROCESS.md). |
| `dw1_redux_input.lua` | Scripted play: `dw1_press({'RIGHT','CROSS'})` timed tap queue + `dw1_masher('x'/'title')`. Installable live via `dw1_redux_api.py lua "Support.extra.dofile(...)"`. |
| `dw1_redux_screenshot.py` | The "eyes": REST VRAM dump → PNG of the visible 320x240 framebuffer. Pair with scripted input for screens that can't be blind-mashed (name entry). |
| `dw1_ghidra.ps1` | Standard headless Ghidra wrapper (JAVA_HOME, project, script path handled). |
| `ghidra_scripts/DW1ExportFunc.java` | Exports one function's decomp.c + listing.asm + refs.txt bundle for the decomp pipeline. |
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
