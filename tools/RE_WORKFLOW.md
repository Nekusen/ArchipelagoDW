# DW1 RAM-bit RE workflow

DWAP shipped a per-recruit RAM-bit table at
`references/DWAP/source/DWAP/Resources/Locations.json`, but its runtime
hook never installed (`RecruitmentFunctionAddress = 0x00000000`) so the
bit-poll path was **never exercised in production**. Initial validation
against `0x001BDFE6` (Agumon) showed no byte change on recruitment, so
the addresses are wrong (or the bit indices are wrong). We need to find
the real ones live.

The two scripts in this directory implement a snapshot-pair workflow
that does the work in 5-10 minutes per event:

- `tools/ram_logger.lua` — runs inside BizHawk, captures a labelled
  768-byte snapshot of the live save block on every F8 press.
- `tools/parse_ram_log.py` — pairs adjacent snapshots and prints the
  byte-level + bit-level differences.

You play DW1, press F8 right before each event, trigger the event, F8
right after. After capturing a few pairs, send me the log and I'll
update the address tables.

---

## Setup (once)

1. Open BizHawk + Nymashock and load your vanilla `Digimon World (USA).bin`
   (no AP patch — we want to map base-game RAM, not patched RAM).
2. Open **Tools > Lua Console**.
3. **File > Open Script…** → select `tools/ram_logger.lua`.
4. The Lua Console should print:
   ```
   [ram_logger] Loaded. Press F8 to capture a snapshot of 0x001BDF00..0x001BE1FF (768 bytes) into dw1_ram_log.txt.
   ```
5. The log file `dw1_ram_log.txt` will appear in BizHawk's working
   directory (next to `EmuHawk.exe` on most installs). Locate it before
   starting so you can find it later.

## Capturing one event

For each in-game event we want to map:

1. **Get to the moment just before the event triggers.** For a recruit:
   navigate the player to the Digimon's overworld location and stop
   right before approaching them. For a chest: walk up to it but don't
   open. For prosperity: just play normally — prosperity ticks happen
   automatically.
2. **Press F8.** The Lua Console logs `[ram_logger] MARKER NNN at frame F`.
   Note the marker number.
3. **Trigger the event.** Recruit the Digimon. Open the chest. Whatever.
4. **Wait for any cutscene/animation to finish.** RAM mutates a lot
   during animations; we want the post-stable state.
5. **Press F8 again.** That's the "after" snapshot.

You can chain multiple events. Press F8 before/after each. The pair
diff is always between marker N and marker N+1.

## Producing diffs

Once you have at least two snapshots:

```
python tools/parse_ram_log.py path/to/dw1_ram_log.txt
```

You'll see output like:

```
# 4 snapshots loaded; emitting 3 pair-diffs.

--- DIFF: MARKER 001 -> MARKER 002 (frames 12345 -> 18900) ---
  0x001BDF6E: 0x00 -> 0x01  (bit 0 set; byte +1)
  0x001BE032: 0x00 -> 0x01  (bit 0 set; byte +1)

--- DIFF: MARKER 002 -> MARKER 003 (frames 18900 -> 25400) ---
  ...
```

The line `0x001BDF6E: 0x00 -> 0x01 (bit 0 set)` is exactly the format
we'd plug into `RECRUIT_RAM_BITS["Agumon"] = (0x001BDF6E, 0)`.

## What to capture for the first round

I'd like **one snapshot pair per event**, in this order:

1. **Baseline** (before anything happens).
2. **Recruit Agumon** (the easiest reachable recruit — usually the
   starter event).
3. **Recruit one other early Digimon** (Betamon or Palmon — both
   listed by DWAP at the same byte but different bits).
4. **One chest pickup** (any chest; the bit should land somewhere in
   the `0x001BE01E..0x001BE026` range per DWAP's data).
5. **First prosperity tick** (the byte at `0x001BE032` should
   increment, and DWAP has this address with high confidence — it's
   the same address used by the in-game UI to display prosperity).

That gives 5 snapshots = 4 diff pairs (baseline→Agumon,
Agumon→other recruit, that→chest, that→prosperity). It's enough to
either confirm the rest of DWAP's table by extrapolation or rebuild
from scratch.

If you want to capture more events in the same session, no problem —
the more pairs we have, the more we can validate at once.

## Sending the log back

Just paste the **`parse_ram_log.py` output** into the chat. The full
log file is also fine but the parsed output is much shorter and shows
the same information. If a diff has many bytes changing, that's
useful too — sometimes the noise tells us the in-game clock byte or
animation counter we'd want to filter out.

## Notes

- **Don't worry about saving / save state.** RAM-diff doesn't care
  about saves. Just play.
- **Don't worry if a diff has many byte changes.** Recruit cutscenes
  touch background timers, music state, etc. The signal we want is
  always a single bit going 0→1 at one address. Multi-byte changes
  are fine to glance over — most are noise.
- **If a diff shows _zero_ byte changes,** the snapshot region missed
  the relevant bit. Tell me; I'll widen the region in the Lua script.
- **If F8 conflicts with a BizHawk binding,** edit
  `tools/ram_logger.lua` line `local HOTKEY = "F8"` to your preferred
  key. BizHawk's Lua API recognises `"F1".."F12"`, `"A".."Z"`,
  `"0".."9"`, etc.
- **The log file is plain text and grows by ~2 KB per snapshot.** No
  cleanup needed; just delete it between sessions if it gets long.
