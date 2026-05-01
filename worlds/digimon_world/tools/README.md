# Digimon World 1 — RE / debug tools

This directory holds **all DW1-specific tooling** used during reverse
engineering, hypothesis testing, and QA. Every BizHawk Lua script
auto-detects the PSX core (Nymashock or Octoshock); pick whichever
emulator core you prefer and the scripts adapt.

## Naming convention

- All filenames prefixed with `dw1_`.
- Lua scripts: `dw1_<role>.lua` (e.g. `dw1_ram_snapshot.lua`).
- Python helpers: `dw1_<role>.py` (e.g. `dw1_ram_diff.py`).
- Snapshot captures: `dw1_ram_snapshot_NN.txt` (numbered, written
  by the snapshot script). These are working artifacts; commit them
  only when they document a specific finding worth preserving.
- Generated logs go alongside the script that produced them. Delete
  freely between sessions.

All DW1 RE tools live in this directory (`worlds/digimon_world/tools/`).
The repo-root `tools/` directory holds different tooling (apworld
build helpers, recruit-patch generators) and is not part of this
workflow.

## The canonical RE workflow: snapshot → diff

When you need to find what RAM byte/bit changes during an in-game
event (NPC give, area unlock, cutscene, item pickup, recruit, …)
this is the **first thing to try**. It works in 5–10 minutes per
event and was the path that successfully pinned the Old Fishrod flag
(trigger 320 = `0x001BDFF5` bit 0) on 2026-05-01 after BizHawk's
`event.onmemoryexecute` and `event.onmemorywrite` callbacks both
came up empty under Octoshock.

### Setup (once)

1. Open BizHawk and load the running DW1 ISO. Either Nymashock or
   Octoshock works.
2. **Tools → Lua Console → Open Script** → select
   `dw1_ram_snapshot.lua`.
3. The Lua Console should print the loaded banner with the auto-
   detected domain and an in-emulator HUD overlay showing the
   snapshot count.

### Capturing one event

1. Get to the moment **just before** the event triggers (right
   before approaching the NPC, before opening the chest, before
   stepping onto the unlock spot, …).
2. Press **P in the emulator window** (not the Lua Console) to take
   the "before" snapshot.
3. Trigger the event in-game.
4. Wait for any cutscene/animation to finish — RAM mutates a lot
   during animations; we want the post-stable state.
5. Press **P again** to take the "after" snapshot.

You can chain multiple events in one session — the script writes a
new numbered file every press. Output files land in BizHawk's
working directory by default (or set `OUTPUT_DIR` near the top of
the script).

### Diffing snapshots

Pass the captured files to `dw1_ram_diff.py`:

```
python worlds/digimon_world/tools/dw1_ram_diff.py \
    dw1_ram_snapshot_01.txt dw1_ram_snapshot_02.txt
```

The default mode surfaces "sticky-flip" bytes (a byte that changed
once and stayed put through subsequent snapshots — the classic
event-flag signature). Other modes:

- `--gaps-only` — restrict to trigger-array addresses NOT already
  accounted for by recruit / chest / beaten subtables (i.e. story-
  event flags in the gap regions).
- `--pattern AABB` — show only addresses whose byte values follow
  this exact pattern label across the snapshots.
- `--all-patterns` — show every address that changed at all (noisier
  but useful when sticky-flip isn't what you're hunting).

The line you're looking for is the single-bit XOR delta:

```
0x001BDFF5: 00 -> 01   [single bit: bit 0, mask 0x01]
```

That's `byte_addr` and `bit_index`/`mask` — exactly the format that
plugs into `data/addresses.py` (e.g. `OLD_FISHROD_FLAG = (0x001BDFF5, 0)`).

### Why snapshots beat write/execute hooks

BizHawk's `event.onmemorywrite` and `event.onmemoryexecute` callbacks
are unreliable across PSX cores — they silently no-op under
Nymashock for the addresses we tested, and on Octoshock the
non-System-Bus domains can confuse the hook installation. Snapshots
work everywhere; if the byte changes during the event, polling
sees it. The tradeoff is that you lose the "which PC instruction
wrote this byte" information — but for the flag-discovery half
of the workflow, the byte/bit pair is what you need.

If you do need the writing PC (e.g. for a ROM-bytecode patch site),
the script bytecode disassembly in
`references/digimon_world_randomizer/script/DW1Script.txt` is
usually the fastest path: search for the relevant text or trigger
ID, the surrounding bytecode shows you what's happening.

## Related tools

### `dw1_ram_diff.py`
Snapshot-pair / multi-snapshot analyzer. See the workflow above.
Default mode does sticky-flip detection across N snapshots; useful
both for two-snapshot before/after pairs and for longer sequences
where you want to see which bytes are persistently event-flagged
vs scratch noise.

### `dw1_bit_poker.lua`
Hypothesis tester. Edit the `bits` table at the top to specify the
addresses you want to toggle, then press the configured keys in the
emulator to flip them on/off. Live HUD shows current bit values.
Useful for "if I force this bit on, does the gate open?" experiments
**after** the snapshot tool has identified candidate addresses.

### `dw1_debug_enable.lua` / `dw1_debug_disable.lua`
QA accelerator. One-shot scripts that flip the two trigger bits
gating DW1's hidden developer debug menu (Mr. Warp / Mr.
Digivolution / max-stat / time-skip / Last-Battle warp). Load,
walk into Jijimon's House to access the menu, run the disable
script to revert. See memory note `dw1_debug_menu.md`.

### Reference snapshot captures
`dw1_ram_snapshot_01..04.txt` are historical captures preserved as
test inputs for `dw1_ram_diff.py` and as documentation of the
trigger-array layout discovered during the early Phase 0–4 work.
Don't rely on their values for current state; re-capture if you
need fresh data.
