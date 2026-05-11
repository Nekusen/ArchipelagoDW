# Merit Shop — Architecture & Implementation Reference

This document captures everything we learned about DW1's ShogunGekomon
merit shop while wiring up the v1 "AP Item" purchase flow, plus the
plan for extending it to full shop randomization.

Read this first before touching shop-related code in a future session.

---

## STATUS — extended-ITEM_PARA now exists (2026-05-11)

**Section 6 of this doc (the "scaling beyond ~12" analysis) is now
mostly outdated.** The recycle shop work shipped 2026-05-11 built
out the **Option 1 — Extend ITEM_PARA** infrastructure from §6a.
The pieces relevant to merit shop scaling that already exist:

- ITEM_DESC_PTR has been **relocated** to RAM `0x80095980` (in
  Cave6). Vanilla slots 0..127 are copied verbatim from the
  source ROM by the `relocate_item_desc_ptr` procedure
  extension; AP slots 128+ have their own pointers populated at
  gen time.
- Three vanilla `lui+addiu` callsites that loaded the original
  ITEM_DESC_PTR base are patched (verified in
  `references/DW1-Code/SLUS.asm`: all three use `$r2`). Listed
  in `addresses.py:RELOC_ITEM_DESC_PTR_PATCH_SITES`.
- Extended ITEM_PARA slot writes work — slots 128..134 are
  populated with AP item names and prices for the recycle shop.
  Same mechanism extends to slots 135+ (currently unused).
- `setItemTexture` at vanilla RAM `0x800E5DFC` is wrapped to
  clamp `id >= 128 → slot 83` (already-blanked icon). So any
  extended slot displays as the blank "AP Item" icon.
- AP description strings ("From `<player>'s World`") live in
  Cave6 at RAM `0x80095D80+`, 64-byte slots — extending to more
  AP shop entries is just allocating more 64-byte slots (Cave6
  has ~3 KB free after the recycle shop's 1.5 KB usage).

**Net effect**: the **only remaining work for full merit shop AP
randomization** is the merit-shop-specific bits — extending
`MERIT_SHOP_DISPATCH` to cover all ~12 vanilla items, allocating
trigger IDs, possibly patching the merit shop's scan-loop bound at
RAM `0x00107430` (`sltiu $r1, $r5, 0x0080`) to scan beyond 128 if
we use extended slots, and the per-AP-item ITEM_PARA writes (with
non-zero `meritValue` so the scan picks them up).

The "merit-shop wrapper" referenced throughout this doc is at
RAM `0x80095800` (Cave6) and is `_build_merit_shop_wrapper_bytes()`
in `addresses.py`. Its size scales as `(38 + 7N) × 4 = 28N + 152`
bytes for N dispatch entries; for N=12 that's 320 bytes,
comfortably inside Cave6's free space.

See [recycle_shop_implementation_plan.md](recycle_shop_implementation_plan.md)
top-of-file STATUS section for the working extended-ITEM_PARA
constants block in `addresses.py` and the wrong-guess corrections
to avoid (Cave1 is NOT free RAM; init_shop_obj at `0x800A32F4`
is NOT the recycle array writer; the actual writer is at
`0x800FA834`).

---

## 1. The merit shop's runtime architecture

### 1a. There is no hardcoded item list

This is the **single most important finding**. We assumed DW1 stored the
shop's inventory as a `(item_id, price)` array somewhere in ROM — it
does not.

Every time the shop opens, a function at RAM `0x801072C4` walks the
**entire 128-entry `ITEM_PARA` table** and includes any entry whose
`meritValue > 0` in the displayed list. The "list" is literally a
runtime filter on `ITEM_PARA`.

Disassembly of the relevant loop (`references/DW1-Code/SLUS.asm:121548`):

```asm
0x0010732C lui   $r9, 0x8012
0x00107330 addiu $r9, $r9, 0x69F4    ; $r9 = 0x801269F4 = ITEM_PARA + 0x18 (meritValue field offset)
0x00107334 addu  $r10, $r9, $r7      ; stride into ITEM_PARA
0x00107338 lhu   $r8, 0x0000($r10)   ; read meritValue (i16)
0x0010733C nop
0x00107340 beq   $r8, $r0, 0x00107424 ; skip if meritValue == 0
... [add (item_id, can_buy_flag) to runtime buffer] ...
0x0010742C addi  $r7, $r7, 0x20      ; stride += 32 (next ITEM_PARA entry)
0x00107430 sltiu $r1, $r5, 0x0080    ; loop while item_id < 128
0x00107434 bne   $r1, $r0, 0x0010732C
```

### 1b. The runtime list structure

The function builds a buffer pointed to by `[$gp - 0x6BC0]`. Each shop
slot in the buffer is **2 bytes**:

```
buffer header:
  +0x00: u32 pointer to entries
  +0x08: u8 entry count

entries (one pair per shop item):
  byte N+0: item_id (u8)
  byte N+1: status flag (u8)
              0 = can't buy (insufficient merits OR inventory has no slot)
              1 = can buy   (affordable AND fits in inventory)
```

The status flag is computed at scan time from current merits + current
inventory state. **Item name, price, icon, description are NOT stored
in the list** — they're looked up live from `ITEM_PARA[item_id]`,
`ITEM_DESC_PTR[item_id]`, and `ITEM.TIM` whenever the shop renders a
row.

### 1c. The merit shop function

Main function: RAM `0x8010BC10` (.bin offset region around `0x14D48xxx`,
sector-hop dependent).

The function is a state machine driven by the variable at
`$gp - 0x6B32` (16 states, sltiu 0x0E gate). The jal-giveItem callsite
is at `0x8010BF3C`:

```asm
0x0010BF3C jal 0x000C5240   ; jal giveItem (we hijack this)
0x0010BF40 nop                ; delay slot — untouched
0x0010BF44 addiu r2, r0, 3   ; transition to state 3 after purchase
```

### 1d. Other relevant globals

- `$gp = 0x8013BB2C` (per SydPatches `SLUS_labels.asm`).
- Selected item ID at runtime: `$gp - 0x6BB4 = 0x80135078` (read at
  `0x0010BF30: lbu r4, -0x6bb4(r28)` right before the jal).
- Current merit count (i16): `$gp - 0x6B68 = 0x80134FC4`. Hard cap
  9999 enforced at `0x0010BE54: slti r1, r2, 0x2710`.

---

## 2. The wrapper hijack pattern (v1 / current state)

### 2a. Wrapper installation

Replace the merit shop's `jal giveItem` at `0x8010BF3C` with a `jal`
into a custom wrapper sitting in SydPatches' Cave6 free-space region.

**Patch site** (`addresses.py:ROM_MERIT_SHOP_PATCH_OFFSET = 0x14D48C04`):
- 4-byte rewrite of the jal instruction.
- New value: `jal 0x80095800` = `0x0C025600` LE.

**Wrapper location**:
- RAM `0x80095800` (= `ROM_MERIT_SHOP_WRAPPER_RAM`).
- .bin offset `0x14CC0C88` — **REQUIRES SECTOR HOP**, do NOT compute
  flat from the chest wrapper offset. Use `_flat_to_user_data()`.
- The merit-shop wrapper crosses the 2048-byte user-data boundary at
  the start of sector 148349. A flat `chest_wrapper_offset + 0x40`
  lands inside sector 148348's EDC region (never loaded as code).
  This was the 30-minute "wrapper freeze" bug.

### 2b. Wrapper behavior

For each `(item_id, trigger_id)` in `MERIT_SHOP_DISPATCH`:

1. Save `$ra`, `$a0`, `$a1` to a 16-byte stack frame.
2. If `$a0 == item_id`: call vanilla `setTrigger(trigger_id)`, then
   skip the vanilla `giveItem` call (don't add anything to inventory).
3. Else: tail-call vanilla `giveItem` so the shop functions normally
   for unmatched items.
4. Return with `$v0 = 1` (success). The merit shop doesn't actually
   check `$v0` based on the disasm, but matching the chest wrapper's
   convention.

The wrapper builder is `_build_merit_shop_wrapper_bytes()` in
`addresses.py:3700+`. Wrapper size formula: `(38 + 7*N) * 4` bytes where
N is `len(MERIT_SHOP_DISPATCH)`.

### 2c. The `mark_bought` mystery

The wrapper has a `mark_bought` code path (28 instructions / 112 bytes)
that's supposed to memcpy slot 114 → slot N after `setTrigger`. **It
empirically never executes** despite the bytes being correct (verified
by RAM dump byte-for-byte). We tested with a marker write into the
first instruction of `mark_bought` and the marker byte never changed
post-purchase. The `j mark_bought` encoding is correct (`0x08025611` →
RAM `0x80095844`), `setTrigger(903)` does fire (verified via the
trigger byte going from 0 to 0x80 at frame 95658). Why execution
diverges between the `jal setTrigger` return and the `j mark_bought`
target — unknown.

**Workaround**: the client-side reconciler does the post-purchase work
instead. `mark_bought` in the wrapper is dead code. When you have time,
you can simplify the wrapper to drop it (~28 instructions / 112 bytes
recoverable in Cave6).

---

## 3. The client-side reconciler

`client.py:_reconcile_merit_shop_sentinel`. Runs every game-watcher
tick.

**Surgical 2-byte write** to the dispatched slot's `meritValue` field:

1. Read trigger byte for `trigger_id` (1 byte) + slot's current
   `meritValue` (2 bytes at offset 24-25 within the 32-byte ITEM_PARA
   entry).
2. If trigger set AND meritValue ≠ `0x7FFF` (= 32767, the
   "unaffordable post-purchase" value), write `0x7FFF`.
3. Otherwise no-op.

**Why only 2 bytes**: writing the entire 32-byte entry (the previous
"sentinel" approach) would overwrite the slot's name, which causes
problems if the slot is shared with another use case (e.g., slot 83 is
also the chest sentinel, and chest pickups read its name for the
"Found X!" textbox).

**Why bare addresses**: All client-side `bizhawk.read` / `bizhawk.write`
calls use `DOMAIN_MAIN_RAM = "MainRAM"` which expects bare Nymashock
offsets (no `0x80000000` kuseg prefix). The wrapper-builder code in
`addresses.py` ORs in the prefix for its own MIPS encoding. Hidden
gotcha that bit us — see the `RAM_ITEM_PARA` constant comment.

**Probe length detail**: An earlier version of the reconciler used a
4-byte probe to compare slot N's name to the sentinel's name. That
probe always matched on `"AP I"` (both `"AP Item"` and `"AP Item
Bought"` share those bytes), so the reconciler never wrote anything.
The new design avoids the issue by comparing the `meritValue` field
directly (which has clean 0/300/0x7FFF distinct values).

---

## 4. The current slot allocation (v1, 1 AP item)

Three "AP-related" ITEM_PARA slots:

| Slot | Vanilla item | Current state | Purpose |
|---|---|---|---|
| 83 | Electo Ring | name `"AP Item"`, `meritValue=300`, all other fields 0 | **Universal "AP Item"** — chest sentinel + merit shop AP-purchase row |
| 114 | Moon Mirror | name `"AP Item Bought"`, `meritValue=0`, all other fields 0 | Hide vanilla Moon Mirror (gamebreaking) from merit shop. Also was wrapper memcpy source (now dead code) |
| 117 | Amazing Rod | only `meritValue` zeroed; everything else vanilla | Hide vanilla Amazing Rod from merit shop while preserving rod for fishing UI |

**Post-purchase state** (live, written by reconciler):
- Slot 83: `meritValue` becomes `0x7FFF` = 32767 (visible row, unbuyable).
- Slot 83's name **stays** `"AP Item"` — chest pickups still show
  "Found AP Item!" cleanly.

**Visible result in merit shop**:
- 4 vanilla rows: Waterbottle, Red Shell, Hard Scale, Ice crystal at 500 each.
- 1 AP row: `AP Item — 300` (buyable) → after purchase → `AP Item — 32767` (visible, unbuyable).

---

## 5. Helper / cosmetic patches around the AP-Item slot

### 5a. Description redirect

DW1 displays an item's description from `ITEM_DESC_PTR[item_id]` (a
128-entry u32 pointer table living right after ITEM_PARA in RAM at
`0x801279DC`). The merit shop's hover panel reads it for the
highlighted row.

We allocate a string `"Item from the multiworld\0"` (25 bytes) in
Cave6 free space immediately after the merit-shop wrapper, and patch
`ITEM_DESC_PTR[83]` to point at it.

Constants: `AP_ITEM_DESC_*` in `addresses.py`.

### 5b. Icon blanking

Item icons live in `ITEM.TIM`, a separate file in the disc filesystem
at `DIGIMON/ETCDAT/ITEM.TIM`. The file's data starts at LBA 7470 = bin
offset `0x010C16B8`.

TIM format breakdown:
- 8-byte header (magic `10 00 00 00` + flags `08 00 00 00` for 4bpp + CLUT)
- 780-byte CLUT block (24 CLUTs × 16 colors × 2 bytes + 12-byte block header)
- 12-byte pixel block header
- 16384-byte pixel data starting at TIM file offset 800

Pixel layout: 256 px × 128 px texture, 4bpp (2 px per byte). Arranged
as a 16-col × 8-row grid of 16x16 icons. Item N's icon is at pixel
coords `(N%16 * 16, N/16 * 16)`. For slot 83: col 3, row 5 → top-left
pixel at (48, 80). 16 rows × 8 bytes = 128 bytes per icon.

We blank slot 83's 16x16 region by writing 8 zero bytes per row × 16
rows. Each row is in a different file offset; sector-aware translation
required (the icon spans across 2-3 sectors due to the 2048-byte user
data limit per sector).

Constants: `ITEM_TIM_*`, `AP_ITEM_ICON_*` in `addresses.py`.

### 5c. The chest sentinel name unification

Slot 83's name was `"AP ITEM"` (uppercase) in the chest patcher. We
renamed it to `"AP Item"` (mixed case) for visual consistency with the
merit shop. This shows up in chest pickup textboxes as "Found AP
Item!" instead of "Found AP ITEM!".

---

## 6. The constraints scaling forces

When we tried to scale this from 1 AP item to N, the user asked the
question that drove the architectural pivot: **can we have multiple AP
items per shop?**

The bottleneck:
- Each shop slot needs a **unique `ItemType` ID** because the renderer
  looks up name/icon by item_id and the wrapper dispatches by `$a0 ==
  item_id`.
- ITEM_PARA has exactly 128 slots. Most are real items the player
  uses; only ~3 are truly unused (slots 83, 114, 124 — Electo Ring,
  Moon Mirror, AS Decoder). Plus ~9 key-item slots whose original ID
  doesn't matter in our randomizer (rods, keys, Steak, Gear, etc., all
  delivered via trigger bits — the items themselves never enter
  inventory).

**Total realistically repurposable: ~12 unique IDs**, enough for one
mid-sized shop or a handful of small ones — **not enough for full
shop rando across multiple shops**.

### 6a. Three options for scaling beyond ~12

**Option 1 — Extend ITEM_PARA (the right answer for shop rando):**
- Allocate a 256-entry (or 512-entry) ITEM_PARA in unused RAM. Cave6
  has ~5 KB free; bigger free regions exist elsewhere in RAM
  (~0x80100000+ has gaps).
- Patch every `lui + addiu` pair that references the old ITEM_PARA
  base (`0x801269DC`) to point at the new base. There are ~10-30 such
  callsites across the SLUS — RE work needed.
- Patch the merit shop's loop bound: change the `sltiu $r1, $r5,
  0x80` immediate to a larger value (e.g., 0x100 for 256 entries).
- Same treatment for `ITEM_DESC_PTR` (extend the array, redirect
  pointers).
- ITEM.TIM only has 128 16x16 tiles. Either build a second TIM and
  patch `setItemTexture` to conditionally dispatch on `item_id >= 128`,
  or have the extended slots share existing icons (e.g., all extended
  AP items use slot 83's blank icon).

  Estimated effort: **4-8 hours focused**, mostly RE to find all
  ITEM_PARA callsites. Cleanest long-term answer.

**Option 2 — Patch the merit shop loop to scan a custom table.**
Hijack the `lui $r9, 0x8012; addiu $r9, $r9, 0x69F4` to point at a
custom `(item_id, meritValue)` array we maintain in free RAM. The
renderer still uses `ITEM_PARA[item_id]` for name/icon, so the IDs in
our custom array must still be valid ITEM_PARA entries — meaning we
still need ~12 distinct IDs. Doesn't solve scaling, just decouples
shop layout from ITEM_PARA `meritValue`. Useful for *placement*
flexibility but not *capacity*.

**Option 3 — Custom shop renderer.** Replace the entire merit-shop
function with our own MIPS code that reads from a custom shop config
(item_id + name pointer + icon pointer + price). Each shop entry
becomes fully self-contained. Heaviest lift. **8-16 hours.** Probably
not worth it vs. Option 1.

---

## 7. Generalization: regular money shops likely use the same pattern

We only verified the merit shop's runtime architecture, but the
SydPatches asm has multiple `jal giveItem` callsites:

```asm
.org 0x800fb410   ; ?
.org 0x80102e6c   ; chest pickup (we hijacked separately)
.org 0x80108798   ; ? (regular shop?)
.org 0x8010896c   ; ? (regular shop?)
.org 0x80108b68   ; ? (regular shop?)
.org 0x8010bf3c   ; merit shop (we hijacked)
.org 0x8010c648   ; ?
```

The 4 callsites in `0x80108xxx` are likely the regular money-driven
shops (Centarumon's, Whamon's, etc.). They probably use the same
"scan ITEM_PARA, filter by `value` (i32 at offset 20-23)" pattern that
the merit shop uses for `meritValue` (i16 at offset 24-25).

When you tackle full shop rando, **first verify** the regular shops
use the same architecture by:
1. Disassembling around each `0x80108xxx` callsite to find the scan
   function called by each shop.
2. Looking for the same `lui $r?, 0x8012; addiu $r?, $r?, 0x69??` +
   `lhu/lw` + `beq $r?, $r0, ...` pattern.
3. Confirming the offset they read (24/25 for meritValue, 20-23 for
   money value).

If the pattern holds: **each shop is just a different filter byte/word
on the same ITEM_PARA scan**. Shop rando becomes "patch the meritValue
/ value of each ITEM_PARA entry to the desired shop layout".

---

## 8. Reverse-engineering recipe (replicable)

How we found these things — useful for future shop work.

### 8a. Find the ITEM.TIM file in the bin

```python
# Find directory entry for ITEM.TIM
needle = b'ITEM.TIM;1'
idx = data.find(needle)
# ISO9660 directory record header is at idx-33 (name length is at idx-1 = 10).
# Bytes at idx-31..idx-27 = LBA u32 LE.
# File data starts at LBA * 2352 + 24 (sector header).
```

Worked first try. Same approach for any other named file in the disc.

### 8b. Find a function's hardcoded data references

Search the function's disasm for `lui $rN, 0x80??; addiu $rN, $rN,
0xXXXX` pairs and resolve to RAM addresses. The merit shop scan was
found this way (`lui $r9, 0x8012; addiu $r9, $r9, 0x69F4` =
`0x801269F4` = ITEM_PARA + 0x18 = meritValue offset).

### 8c. Find dynamic data structures via $gp offsets

DW1 uses MIPS `$gp` for global data. SydPatches docs $gp =
`0x8013BB2C`. Any `lhu/lbu/lw/sw $rN, -0xXXXX($r28)` in disasm reads
from `$gp - 0xXXXX`. The merit count (`-0x6B68 = 0x80134FC4`),
selected item (`-0x6BB4 = 0x80135078`), and the shop list pointer
(`-0x6BC0 = 0x8013506C`) were all found this way.

### 8d. Verify findings with live Lua probes

Before patching, write a Lua HUD probe that displays the relevant
bytes live and watch them change during the in-game scenario. Saves
hours of "I think this is the address" speculation. Pattern in
`tools/dw1_keyitem_bank_probe.lua`.

---

## 9. Pitfalls we hit (don't repeat them)

### 9a. Sector-hop bin offsets

The PSX bin is Mode 2/2352: each 2352-byte sector has a 24-byte header,
2048 bytes of user data, and 280 bytes of EDC/ECC. **A flat
`bin_offset + N` walk past 2048 bytes of user data steps into the next
sector's EDC zone**, which is never loaded as code.

Use the `_flat_to_user_data(base, table_byte_offset)` helper for ANY
write that crosses or might cross a sector boundary. The merit-shop
wrapper bug (~30 min to find) was a flat `chest_wrapper_offset + 0x40`
that landed in EDC.

### 9b. Two RAM addressing conventions

Client-side `bizhawk.read/write` against `MainRAM` domain expects
**bare** offsets like `0x001269DC`. MIPS `lui+addiu` instruction
encoding needs the **kuseg-prefixed** form `0x801269DC`. Same physical
RAM, different conventions.

Convention used in this codebase: `RAM_*` constants are **bare**. The
wrapper builder ORs in `0x80000000` when emitting MIPS code. Don't
copy a `0x80...` address into a Lua probe or `bizhawk.read` call
without stripping the prefix.

### 9c. Octoshock vs Nymashock domains

- Nymashock: domain `"MainRAM"`, bare offsets.
- Octoshock: no `MainRAM` domain — uses `"System Bus"` with
  kuseg-prefixed addresses.

The AP client is hardcoded to `DOMAIN_MAIN_RAM = "MainRAM"`. **The
client doesn't run on Octoshock** — every read/write silently fails
the wrong-domain check and returns nothing. Lua scripts can be made
core-agnostic via `pick_ram_domain()` (see `tools/dw1_keyitem_bank_probe.lua`).

### 9d. The reconciler's name-prefix collision

Comparing the first 4 bytes of slot N to a "sentinel" string was a
trap because both `"AP Item"` and `"AP Item Bought"` share `"AP I"`.
Always verify your "is the slot in the target state?" check
distinguishes the two states by the bytes that actually differ.

### 9e. The wrapper's `mark_bought` doesn't run

Documented elsewhere in this file. The wrapper's MIPS bytes are
verified correct in RAM, `setTrigger` returns to the right `$ra`,
the `j mark_bought` encoding is correct — and `mark_bought` still
never executes. Don't waste time chasing this; use the client-side
reconciler instead.

---

## 10. Files / constants reference

### 10a. addresses.py

| Symbol | Purpose |
|---|---|
| `MERIT_SHOP_DISPATCH` | Tuple of `(item_id, trigger_id)` pairs the wrapper matches against |
| `AP_CHEST_SENTINEL_ITEM_ID` (= 83) | The universal "AP Item" slot |
| `AP_ITEM_NAME` (= b"AP Item") | The shared name written to slot 83 |
| `AP_ITEM_MERIT_PRICE` (= 300) | Initial buyable merit price for slot 83 |
| `ROM_AP_ITEM_ENTRY_BYTES` | 32-byte ITEM_PARA entry written to slot 83 at gen time |
| `ROM_AP_ITEM_ENTRY_OFFSET` | Sector-aware bin offset for slot 83's entry |
| `AP_ITEM_BOUGHT_MERIT_VALUE` (= 0x7FFF) | Post-purchase meritValue (max int16) |
| `AP_ITEM_BOUGHT_MERIT_VALUE_BYTES` | 2-byte LE encoding of the above |
| `ITEM_PARA_MERIT_VALUE_OFFSET` (= 24) | Byte offset of meritValue within an ITEM_PARA entry |
| `ROM_AMAZING_ROD_HIDE_OFFSET` | Sector-aware bin offset of slot 117's meritValue (where we write 0) |
| `ROM_MERIT_SHOP_WRAPPER_OFFSET` (= 0x14CC0C88) | Sector-aware bin offset of the wrapper code |
| `ROM_MERIT_SHOP_WRAPPER_RAM` (= 0x80095800) | Wrapper's RAM load address |
| `ROM_MERIT_SHOP_PATCH_OFFSET` (= 0x14D48C04) | Bin offset of the jal hijack |
| `ROM_MERIT_SHOP_PATCH_VALUE` | The new jal instruction (LE u32) |
| `_build_merit_shop_wrapper_bytes()` | Generates the wrapper MIPS code from MERIT_SHOP_DISPATCH |
| `AP_ITEM_DESC_*` | Description string + ITEM_DESC_PTR redirect |
| `AP_ITEM_ICON_*` | Slot 83 icon-blanking constants |
| `ITEM_TIM_LBA` (= 7470) | LBA of ITEM.TIM in the disc filesystem |
| `ITEM_TIM_PIXEL_DATA_FILE_OFFSET` (= 800) | Offset of pixel data within the TIM file |
| `_flat_to_user_data(base, offset)` | The sector-aware bin offset translator |

### 10b. rom.py

| Function | Role |
|---|---|
| `_write_merit_shop_wrapper_tokens()` | Emits all the merit-shop-related patcher writes (always-on). Includes slot 83 ITEM_PARA entry, wrapper body, jal hijack, slot 114 sentinel, presale name rewrites, slot 117 hide patch, description string + redirect, icon blanking. |

### 10c. client.py

| Method / Symbol | Role |
|---|---|
| `_reconcile_merit_shop_sentinel()` | Per-tick reconciler. Bumps slot 83's meritValue to 0x7FFF when trigger 903 is set. |
| `AP_ITEM_BOUGHT_MERIT_VALUE_BYTES` | Imported from addresses.py for the reconciler write. |
| `ITEM_PARA_MERIT_VALUE_OFFSET` | Imported for offset math. |

### 10d. tools/

| Tool | Use |
|---|---|
| `dw1_keyitem_bank_probe.lua` | Pattern for a HUD probe that displays live RAM byte values. Adapt for shop work. |
| `dw1_ram_dump.lua` | Dump 2 MiB of RAM for byte-signature scanning. Useful to find static data tables. |
| `dw1_merit_shop_pc_locator.lua` | Watches PC during shop interaction. Useful for finding shop function callers. |

---

## 11. Recommended next steps for full shop rando

1. **Verify the regular shops use the same ITEM_PARA-scan architecture.**
   Disassemble the 4 jal-giveItem callsites in `0x80108xxx`, find the
   loops, confirm they filter on `value` (offset 20-23) the same way
   the merit shop filters on `meritValue` (offset 24-25). Should take
   ~30 min.

2. **Extend ITEM_PARA.** Allocate a 256-entry table in free RAM,
   migrate the existing 128 entries, patch the ~10-30 `lui+addiu`
   callsites that reference `0x801269DC`. **This is the gating step
   for shop rando capacity.**

3. **Extend ITEM_DESC_PTR similarly.** The 128-entry pointer array
   right after ITEM_PARA needs the same treatment.

4. **Decide icon strategy for extended slots.** Easiest: have all
   extended AP-item slots (id 128+) share slot 83's blank icon by
   patching `setItemTexture` to clamp `item_id >= 128 → 83` for the
   col/row computation. Better: build a second TIM with AP-themed icons
   per shop slot.

5. **Per-shop wrapper hijacks.** Each of the regular-shop jal-giveItem
   callsites needs its own wrapper hijack (or one shared wrapper that
   dispatches based on the calling shop). Pattern is the same as the
   merit shop's.

6. **Per-slot AP location triggers.** Each shop slot gets a unique
   trigger ID. Allocate a contiguous range like 904..950 for shop
   locations. Update `MERIT_SHOP_DISPATCH` (or a per-shop equivalent)
   with the full mapping.

7. **Reconciler updates.** The current reconciler iterates
   `MERIT_SHOP_DISPATCH`; this scales fine to N entries. May want to
   bundle the per-tick reads (currently 2 per dispatch entry — could
   be one large multi-block read).

8. **Test infrastructure.** Add tests for:
   - Each shop's ITEM_PARA entries get the right meritValue / value at
     gen time.
   - Reconciler correctly bumps post-purchase state for any active
     trigger in the dispatch table.
   - Buying any shop slot fires its specific AP location.
