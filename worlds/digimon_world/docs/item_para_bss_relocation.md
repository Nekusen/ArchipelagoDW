# ITEM_PARA relocation — .bss/heap approach (post-Path-A)

**Status**: Design only. No code shipped. Probe is ready under
`tools/dw1_bss_probe.lua`; empirical verification of a candidate region
is the next step.

**Context**: Path A (relocate ITEM_PARA into an SLUS exec region at RAM
`0x8009DBC8..0x8009F278`) failed because the chosen 5808-byte "free"
region holds 9 function-pointer constants stored into the dispatch
struct array at `0x80137000..0x801370FF` (fields `+0x0C`, `+0x14`,
`+0x1C` of structs 2/3/6/7). Any `jalr` through those handlers executes
ITEM_PARA data as MIPS instructions and freezes the game. The arena was
the first user-visible failure; ≈3 other game-state secondary handlers
are believed to also be on broken code paths.

See `item_para_relocation.md` for the original Path A design that this
supersedes, and the commit message of `DW1: revert Path A ITEM_PARA
relocation (arena freeze)` for the post-mortem.

## Why .bss/heap is fundamentally different

Path A's failure mode was: the static "no jal targets / no constructed
addresses" probe declared an SLUS-exec region free, but the SLUS .bin
contained data words at other addresses that, when loaded as `u32`, are
function pointers into the region. Static scans miss those.

A region that is **not loaded from the .bin at all** cannot have this
problem. Bytes there at runtime are whatever the kernel boot stub /
libgs runtime initialised them to (typically zero for .bss, or
allocator-managed if it's heap). No `.bin` u32 can point into a region
that doesn't exist in `.bin`.

The catch: the region must also not be **runtime-used** as a buffer
(sound mixer, render queue, allocator arena, file-load destination, …).
That has to be verified empirically per candidate.

## Target RAM map

DW1's .bin-backed SLUS exec spans approximately
`0x80090800..0x80134FFC` (660 KB code + data). Everything above
`0x80135000` is `.bss` / runtime / heap / stack.

Static scan of all SLUS+overlay `lui+addiu` pairs constructing
addresses in `0x80135000..0x80200000` (run 2026-05-13) found these
**fully-empty 4 KB pages** — no `.bin` code constructs an address
landing in them:

| Window | Size | Notes |
|---|---|---|
| `0x8015E000..0x80185000` | **156 KB** | largest empty span; primary candidate |
| `0x80188000..0x801A0000` | 96 KB | second candidate |
| `0x801A2000..0x801AF000` | 52 KB | smaller, less margin |
| `0x801B2000..0x801B7000` | 20 KB | tight |

Static-only evidence is necessary but not sufficient (same lesson as
Path A) — runtime allocator can carve any of these regions for itself.
The probe below empirically rules out runtime use.

## Architecture (Flavor A — "boot-time seed into .bss")

```
.bin (Cave6 free space):    [extended ITEM_PARA seed: 5808 B of slot data]
                                        │
                                        │ memcpy at boot
                                        ▼
RAM ~0x80160000 (in 156 KB window):   [extended ITEM_PARA at runtime]
                                        ▲
SLUS 24 reader callsites ────────►   patched to load this base
```

Three concrete pieces of patching:

1. **Seed block** — 5808 bytes (= 181 ITEM_PARA slots × 32 B) of
   pre-built ITEM_PARA data stored as raw bytes inside the SLUS `.bin`,
   in Cave6 or an adjacent free region. Generated at apply-token time:
   the patcher copies vanilla slots 0..127 from `0x801269DC`, overlays
   AP-modified slots (83 "AP Item", 114 sentinel, 117 Amazing Rod, plus
   shop extension slots 128..143/180), and writes the combined block
   into the Cave6 seed location.

2. **Bootstrap hook** — a small (≈20-instruction) wrapper installed in
   Cave6 that runs once early in SLUS boot. It memcpys the seed from
   the Cave6 storage location into the target RAM region. The wrapper
   is reached by hijacking a single `jal` near the start of `main()`
   (specific site TBD; standard pattern is to insert just after the
   libgs init call but before any ITEM_PARA reader runs).

3. **24 reader patches** — the same 24 SLUS callsites previously
   enumerated by `tools/dw1_scan_item_para_readers.py`, each with their
   `lui $rN, 0x8012; addiu $rN, $rN, 0x69DC+field` pair rewritten to
   `lui $rN, NEW_HI; addiu $rN, $rN, NEW_LO+field`. The encoding logic
   (`_decompose_kuseg`) handles the sign-extension case if `NEW_LO >=
   0x8000`, so the target RAM can be anywhere.

This is the same shape as Path A's *patcher logic*; only the **target
RAM** changes — from inside the SLUS exec to inside .bss.

## Probe design

`tools/dw1_bss_probe.lua` does three things:

1. **Pre-fill** the candidate region with the pattern `0xDEADBEEF` at
   script start. This pattern:
   - Decodes as `lwc1` (FPU load) on MIPS — the PSX R3000 has no FPU,
     so executing it raises a CPU exception (visible crash).
   - Read as a pointer it points at `0xDEADBEEF` in kseg2 — derefing
     crashes (also visible).
   - Read as data (a value, count, index) it's an obviously-bogus
     number; most realistic uses crash too.
   - Compresses well in a hex dump for visual verification.

2. **Poll** every 60 frames (1 second). If any byte in the region has
   changed from `0xDEADBEEF` the probe logs a `WRITE DETECTED` entry
   with the offset, refreshes its snapshot, and continues. So we catch
   stores as they happen.

3. **Survive playthrough**. The probe keeps running while the player
   exercises the game. The PASS condition is: after a full comprehensive
   playthrough, no writes detected **and** the game never crashed.

The probe is **destructive on purpose**: pre-filling with `0xDEADBEEF`
turns *any* runtime use of the region into an immediate visible failure.
That's what we need, because the failure modes Path A's polling-only
probe missed were silent reads/executes. Anyone reading our pattern
as code or as a pointer crashes.

### Test plan checklist (run while the probe is loaded)

Verify each item works (or makes the probe scream). If anything is
skipped, the candidate is not cleared for that situation.

- [ ] Boot to title screen (no crash, no writes)
- [ ] New file → File City → Jijimon's house
- [ ] Walk around outside, visit every File City building you can
- [ ] Save the game; reload
- [ ] One wild battle (any field digimon)
- [ ] In-battle "use item" (open inventory, use anything)
- [ ] Open the item shop (regular shop)
- [ ] Open the merit shop (Volume Villa, ShogunGekomon)
- [ ] Open the recycle shop (if File City has it open by now)
- [ ] One digivolution (intentional or by stat threshold)
- [ ] **Arena fight** (Greymon's arena building, or Beetle Land bridge)
- [ ] Penguinmon curling (loads KAR_REL overlay)
- [ ] Birdramon flight (loads flight UI)
- [ ] One map transition into a never-visited region (Native Forest,
      Tropical Jungle, Mt. Infinity entrance if available)
- [ ] Trigger any cutscene you haven't seen
- [ ] Optional: end-game / Machinedramon / post-game (if accessible)

The probe logs heartbeats every 10 seconds so you know it's alive.

### Picking a candidate region

The script's top has `REGION_BASE_BARE` and `REGION_SIZE` constants —
edit those before loading the script in BizHawk Lua Console. Default
is `0x00160000`, size 8192 bytes (centred in the 156 KB window above).

Recommended starting candidates, ordered by margin:

1. `0x80160000..0x80162000` (8 KB, default; centred in 156 KB window)
2. `0x80170000..0x80172000` (8 KB, deeper in the same window)
3. `0x80190000..0x80192000` (8 KB, in the second window)

Pick one, probe it through the checklist. If clean: that region passes
empirically. If not: pick the next candidate and re-probe.

## Open questions for the implementation phase

1. **Where in Cave6 does the 5808-byte seed live?** Current Cave6
   layout is mostly full (wrappers + tables). The seed needs a
   contiguous 5808-byte slice — may require relocating one of the
   smaller wrappers, or extending into adjacent unused .bin space.
2. **What's the bootstrap hijack site?** Need to find a single `jal`
   in the SLUS init path that runs after libgs is up but before any
   `lui 0x8012; addiu 0x69DC` reader fires. Candidate-hunt is its own
   small RE exercise.
3. **Does the bootstrap need to re-run on save-state reload?** PSX
   save-state restores RAM verbatim, so probably no — the .bss region
   stays populated. Boot-from-disc always re-runs the bootstrap.
4. **Sector alignment of the seed block.** The seed crosses
   Mode2/2352 sector boundaries; use `read_user_data_bytes` /
   `write_user_data_bytes` per the existing Cave6 conventions.
5. **Slot 144..180 contents.** Future shops can write directly to
   those slots in the seed block via a token writer, since the seed
   block is just a Cave6 `.bin` region.

## When to revisit

- Once a candidate region passes the probe checklist cleanly.
- Have at least one independent re-run by a different tester to rule
  out probe artefacts.
- Document the verified region as `RAM_ITEM_PARA_BSS_TARGET` in
  `data/addresses.py` and start the patcher implementation.
