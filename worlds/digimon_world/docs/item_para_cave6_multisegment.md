# Cave6 multi-segment ITEM_PARA

**Status**: implemented (2026-05-13). Adds 30 ITEM_PARA slots (144..173)
to the AP-extension range, lifting the previous 16-slot ceiling
without relocating any existing data.

**Background**: see `item_para_relocation.md` for the original
"relocate ITEM_PARA wholesale" design (Path A) and
`item_para_bss_relocation.md` for the .bss/heap alternative. Path A
was reverted because its destination region held function-pointer
constants stored as raw u32 in the SLUS .bin's dispatch struct array.
This document describes the third approach actually shipped: **don't
relocate, segment**.

## Problem

Pre-Cave6-multisegment, ITEM_PARA had **143 usable slots**:

* Slots 0..127: vanilla ITEM_PARA at RAM `0x801269DC` (4096 B).
* Slots 128..143: freed ITEM_DESC_PTR region at RAM `0x801279DC`
  (512 B, contiguous with vanilla — the scan loops just walk past
  the vanilla boundary).
* Slot 144 collides with the per-item color table at RAM
  `0x80127BDC` — writing slot 144's ITEM_PARA entry corrupts the
  color table, which the merit shop's post-purchase refresh then
  re-reads, freezing the game.

Recycle Shop (7 AP slots) + Merit Shop (originally planned 14 AP
slots) = 21 slots, but only 16 fit. So Merit Shop shipped with 9
slots and 5 of its 14 vanilla entries had their `meritValue` zeroed
without becoming AP locations — a behaviour loss vs. the original
spec.

## Approach: a second segment in Cave6

```
                                Discontinuous in RAM.
                                Same logical ITEM_PARA table.
                                ──────────────────────────────────
RAM 0x801269DC ─ vanilla ITEM_PARA[0..127]   (4096 B)
RAM 0x801279DC ─ freed-DESC ITEM_PARA[128..143] (512 B)
RAM 0x80127BDC ─ ⛔ item color table
   ...
RAM 0x80096800 ─ Cave6 ITEM_PARA[144..173]   (960 B)
```

The merit-shop scan loop is patched to **teleport** when its
iteration counter reaches 144 — instead of reading the color table,
it jumps to the Cave6 ext base. Vanilla scan code for slots 0..143 is
unchanged.

## The three on-ROM artifacts

### 1. Cave6 ITEM_PARA ext segment

`CAVE6_ITEM_PARA_EXT_RAM = 0x80096800` (Mode2/2352 sector boundary,
inside sector 148351's user-data region). 30 slots × 32 B = 960 B.
The whole segment is contained within one sector so `apply_tokens`
flat writes can't cross a sector header.

Slot allocation:

* **Slots 144..148** (5 slots) → Merit Shop AP locations 10..14.
* **Slots 149..173** (25 slots) → reserved for future shops
  (File City regular shop, Secret shops, etc.). Each future shop
  writes its slots' ITEM_PARA entries directly via
  `ext_item_para_slot_bin_offset(slot_id)`.

### 2. Merit-scan teleport wrapper

`CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM = 0x800965BC`, 64 B (16 MIPS
instructions). Sits just past the merit-shop EXT wrapper in Cave6.

Pseudo-code:

```c
if (slot_id < 144)
    r10 = vanilla_ITEM_PARA + 0x18 + r7;   // r7 = slot_id * 32
else
    r10 = CAVE6_ITEM_PARA_EXT + (slot_id - 144) * 32 + 0x18;
j ROM_MERIT_SCAN_RETURN_RAM;               // = 0x80107338 (lhu)
```

Key implementation details:

* Uses unconditional `j`, not `jal` — no `$ra` clobber, no need to
  save the scan function's own return address.
* Returns to `0x80107338` (the `lhu r8, 0x0000(r10)` immediately
  after the 3 instructions we patched away).
* Sign-extension correct: Cave6 ext low half `0x6800` is `< 0x8000`,
  so the `addiu` reconstructs `0x80096800` without the hi adjustment
  that bit Path A.

### 3. Scan-base inline patch

At `ROM_MERIT_SCAN_BASE_PATCH_RAM = 0x8010732C` (the merit-shop scan
loop's per-iteration pointer-construction sequence), replace 12 bytes:

```
0x10732C  lui   r9, 0x8012        →  j  CAVE6_MERIT_SCAN_TELEPORT_WRAPPER_RAM
0x107330  addiu r9, r9, 0x69f4    →  nop
0x107334  addu  r10, r9, r7       →  nop
```

The wrapper does the work the 3 original instructions used to do,
plus the slot-144 teleport.

### Scan-loop bound bump

`ROM_MERIT_SCAN_BOUND_OFFSET` already rewrites the `sltiu $r1, $r5,
0x80` immediate at `0x80107430`; the new value is `0x95` (= 149) so
the scan covers slots 0..148.

## Sector-alignment table

Cave6 spans two Mode2/2352 sectors: 148350 (ud-region
`0x80096000..0x80096800`) and 148351 (`0x80096800..0x80097000`).
The Cave6-multisegment layout, in order:

| RAM | Item | Size | Sector |
|---|---|---|---|
| `0x80096000..0x80096380` | MERIT_AP_DESC_STRINGS (14 × 64 B) | 896 B | 148350 |
| `0x80096380..0x800965BC` | merit EXT wrapper (15-entry dispatch, 572 B) | 572 B | 148350 |
| `0x800965BC..0x800965FC` | merit-scan teleport wrapper | 64 B | 148350 |
| `0x800965FC..0x80096800` | gap (reserved) | 516 B | 148350 |
| `0x80096800..0x80096BC0` | Cave6 ITEM_PARA ext segment (30 slots) | 960 B | 148351 |
| `0x80096BC0..0x80096BCC` | Cave6 tail | 12 B | 148351 |

Every artefact stays within one sector — no flat write crosses a
sector boundary, so `apply_tokens` is safe without
`write_user_data_bytes` workarounds.

## Test coverage

Added in `test_merit_shop_extended.py`:

* `TestCave6MultiSegment` — segment placement, helper routing, wrapper
  bytecode decode-verify, scan-base patch correctness.
* `TestCave6MultiSegmentPatcherOn` — patcher emits the teleport
  wrapper bytes, the scan-base patch, and slot 144..148 ITEM_PARA
  entries.
* `TestCave6MultiSegmentPatcherOff` — none of those tokens fire when
  the option is off.

Plus expanded merit-shop tests for 14 slots / 14 triggers / 15-entry
dispatch.

## Future work

* **Empirical playthrough verification** — confirm the merit shop
  with 14 AP slots runs cleanly through purchase, hover, post-shop
  refresh, and save/reload. Existing 9-slot behavior is the regression
  baseline.
* **Wire future shops into slots 149..173** — each new shop writes
  its ITEM_PARA entries via `ext_item_para_slot_bin_offset(slot_id)`
  and patches its own scan-loop. If a new shop's scan logic differs
  from merit-shop's, it may need its own teleport wrapper variant.
* **Move to .bss/heap when 30 slots aren't enough** — the
  `item_para_bss_relocation.md` design remains the long-term answer
  for unbounded capacity.
