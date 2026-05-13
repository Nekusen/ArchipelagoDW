# ITEM_PARA Relocation (Path A) — architecture & how to extend

**Status:** shipped 2026-05-13. Always-on. The foundation for every
current AP shop randomization (recycle, merit) and every future one
(File City Normal Shop, Secret Shop, etc.).

Read this before adding any new shop AP randomization. It documents
the post-relocation memory layout, the patcher infrastructure, and
the constraints to respect when adding new extended ITEM_PARA slots.

---

## TL;DR

Vanilla DW1's ITEM_PARA table at RAM `0x801269DC` is hardcoded to 128
entries (32 bytes each = 4096 bytes). To add more than 16 AP-extended
slots — the original ceiling of the freed `ITEM_DESC_PTR` region — we
moved the whole table to a Cave6-style libgs-leftover region at RAM
`0x8009DBC8..0x8009F278` (5808 bytes = 181 slots).

**Result:** AP-extended slots can now occupy IDs 128..180 (53 slots),
not just 128..143. That's enough headroom for File City Normal Shop
(3 subshops × ~5 items) + Secret Shop + several future shops without
re-running this RE.

**Vanilla slot data is COPIED, not overwritten.** apply_tokens still
writes AP modifications to the **OLD vanilla locations** (slot 83
"AP Item", slot 114 "AP Item Bought", slot 117 Amazing-rod hide,
slots 128..143 from the freed ITEM_DESC_PTR region). A post-token
procedure extension named `relocate_item_para` then reads the 4608
post-token bytes for slots 0..143 and writes them to the new RAM
location. Patcher code for the existing shops needed **zero changes**
beyond the wrapper builders' sign-extension handling.

---

## Memory layout (post-relocation)

```
RAM 0x80010000 ─── SLUS exec start ───────────────────────────────┐
                                                                  │
RAM 0x801269DC ─── (vanilla ITEM_PARA, still present but DEAD ────┤  loaded
                   no readers; bytes are duplicated to the new    │  from
                   location at apply time)                        │  .bin
                                                                  │
RAM 0x801279DC ─── (vanilla ITEM_DESC_PTR slot, now relocated to  │  at
                   Cave6; bytes are duplicated to new ITEM_PARA   │  boot
                   slots 128..143)                                │
                                                                  │
RAM 0x80127BDC ─── per-item color table (untouched, readers       │
                   already clamp via icon-clamp wrapper)          │
                                                                  │
... more vanilla data ...                                         │
                                                                  │
RAM 0x8009DBC8 ─── ITEM_PARA relocated (5808 B = 181 slots) ──────┤
RAM 0x8009DBC8     slot 0   ← copied vanilla "sm.recovery" etc.   │
RAM 0x8009DBE8     slot 1                                         │
...                                                               │
RAM 0x8009E5C8     slot 56  (last vanilla "real" item)            │
...                                                               │
RAM 0x8009E628     slot 83  ← AP-modified "AP Item" sentinel      │
...                                                               │
RAM 0x8009EA08     slot 114 ← AP-modified "AP Item Bought"        │
...                                                               │
RAM 0x8009EB10     slot 117 ← Amazing-rod hide (meritValue=0)     │
...                                                               │
RAM 0x8009E1C8     slot 128 ← recycle shop AP entry #1            │
...                                                               │
RAM 0x8009E2C8     slot 134 ← recycle shop AP entry #7            │
RAM 0x8009E2E8     slot 135 ← merit shop AP entry #1              │
...                                                               │
RAM 0x8009E3A8     slot 143 ← merit shop AP entry #9              │
RAM 0x8009E3C8     slot 144 ← FREE for new shops                  │
...                                                               │
RAM 0x8009F278     end of relocated ITEM_PARA (slot 181 wouldn't  │
                   fit; max valid slot id is 180)                 │
                                                                  │
... more SLUS code ...                                            │
                                                                  │
RAM 0x80140000 ─── SLUS exec end (approximate) ───────────────────┘
```

**Practical implication:** slots 144..180 are currently zero-initialized
(via the libgs-filler bytes that were originally in the .bin at the
new region; meritValue happens to be zero for those bytes, so they
don't appear in shops). Future shops can write AP data directly to
slots 144..180's NEW .bin offset.

---

## Files / code touched

| File | What changed |
|---|---|
| [worlds/digimon_world/data/addresses.py](../data/addresses.py) | `RAM_ITEM_PARA` value flipped to `0x0009DBC8`; original kept as `RAM_ITEM_PARA_VANILLA`. Added `_decompose_kuseg` helper (sign-extension-aware lui/addiu decomposition). Refactored both merit wrappers (v1 + ext) to use `_decompose_kuseg`. New constants block `ITEM_PARA_RELOC_*`. New `ITEM_PARA_RELOC_READER_SITES` (24 entries). New `build_item_para_reloc_patch_tokens()` helper. |
| [worlds/digimon_world/rom.py](../rom.py) | New `DigimonWorldPatchExtension.relocate_item_para` (post-`apply_tokens` extension). New `_write_item_para_relocation_tokens` (writes the 48 reader-site patches, always-on). Default class-level `procedure` now includes `relocate_item_para` between `apply_tokens` and `recalc_edc`. `_assemble_procedure` preserves the relocation step. |
| [worlds/digimon_world/tools/dw1_scan_item_para_readers.py](../tools/dw1_scan_item_para_readers.py) | Static analyzer used to enumerate the 24 reader sites. Re-run if SLUS.asm gets re-disassembled. |
| [worlds/digimon_world/tools/dw1_freeregion_probe.lua](../tools/dw1_freeregion_probe.lua) | BizHawk probe to empirically verify a candidate free RAM region. Used to validate `0x8009DBC8..0x8009F278` before shipping Path A. |
| [worlds/digimon_world/test/test_item_para_relocation.py](../test/test_item_para_relocation.py) | 39 tests covering constants, sign-extension decomposition, the 24-site patch builder, token emission (options on + off), procedure wiring, and an end-to-end roundtrip against the real .bin. |

---

## How the relocation works at apply time

1. **`verify_rom_hash`** — confirms the user's .bin is SLUS-01032 USA.
2. **`apply_tokens`** — writes every token: AP item entries (slot 83,
   114, 117 in vanilla ITEM_PARA + slots 128..143 in the freed
   ITEM_DESC_PTR region), the 48 reader-site patches (rewriting the
   low 2 bytes of each `lui` and `addiu` instruction at the 24
   call sites), all existing shop tokens (recycle + merit wrappers,
   AP description strings, scan-bound patches, etc.).
3. **`relocate_item_para`** *(new, always-on)* — reads 4608
   contiguous post-token bytes from vanilla ITEM_PARA's .bin offset
   (`ITEM_PARA_VANILLA_BIN_OFFSET = 0x14D676C4`); writes them to the
   relocated location (`ITEM_PARA_RELOC_BIN_OFFSET = 0x14CCA350`).
   Sector-aware on both read and write — the region spans multiple
   Mode2/2352 user-data sections.
4. **`relocate_item_desc_ptr`** *(opt-in, unchanged from before)* —
   builds the relocated ITEM_DESC_PTR table in Cave6. Doesn't conflict
   with ITEM_PARA relocation.
5. Any opt-in shufflers run.
6. **`recalc_edc`** — rebuilds Mode2/2352 EDC/ECC for every modified
   sector.

---

## The sign-extension trick

The relocated base `0x8009DBC8` has low half `0xDBC8` (bit 15 set).
MIPS `addiu` sign-extends a 16-bit immediate, so `addiu rN, rN, 0xDBC8`
adds `-0x2438` (`0xFFFFDBC8` two's-complement). To still construct
the correct address, the `lui` high half must be incremented by 1:
`lui rN, 0x800A; addiu rN, rN, 0xDBC8` ⇒ `0x800A0000 - 0x2438 = 0x8009DBC8`.

This is encapsulated in `_decompose_kuseg(addr)`. **Every wrapper
emitter that constructs a kuseg address from a lui/addiu pair must
use this helper** (or replicate the same logic). The historical
assertion in the wrapper builders (`if (addr & 0xFFFF) >= 0x8000: raise`)
has been replaced with a call to `_decompose_kuseg`.

The 24 reader-site patches at the SLUS lui/addiu sites bake the same
math: `new_hi = 0x800A`, `new_lo = 0xDBC8 + field_offset`. All
observed field offsets are in `[0x00, 0x1D]`, so `new_lo` stays in
`[0xDBC8, 0xDBE5]` (always `>= 0x8000`) — the `lui` high half
stays a constant `0x800A` for every site.

---

## What changes for existing shops? Nothing.

Recycle shop and merit shop patchers were **NOT** modified for Path A
beyond the shared wrapper-builder refactor (sign-extension helper).
The architecture is:

- `apply_tokens` writes AP modifications to **OLD vanilla** locations
  (via the existing `_table_byte_to_bin_flat` and
  `ext_item_para_slot_bin_offset` helpers). No changes there.
- `relocate_item_para` runs after, reading the post-token OLD region
  and copying it to NEW. The AP modifications flow through
  automatically.
- The merit-shop wrappers' MIPS bytecode targets the NEW base because
  `RAM_ITEM_PARA` now points at NEW. Sign-extension handled in
  `_decompose_kuseg`.
- The 24 vanilla SLUS readers now load NEW base via the patched
  lui/addiu pairs.

---

## How to add a new shop using Path A

Use the recycle or merit shop as your template. The architecture is
"hijack the shop's `jal giveItem` with a wrapper that fires
`setTrigger(N)` and skips the vanilla item delivery". The new bits
for Path A are:

1. **Pick a slot range** in `[144, 180]`. Document it in
   `addresses.py` (e.g., `FILE_CITY_SHOP_AP_ITEM_ID_BASE = 144`).
2. **Pick a trigger range** above the merit shop's last trigger
   (920). The next clean band is `921..` (still in byte
   `0x001BE040`, bits 1..5). Verify the bits don't collide with
   anything already in `addresses.py:LOCATION_RAM_BITS` and stay
   well clear of `RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE` at byte
   `0x001BE042`.
3. **Allocate AP description strings** in Cave6 free space. Merit
   shop uses `0x80096000..0x80096240`. The next slot-aligned free
   region inside Cave6 is `0x800963F0..0x80096BCC` (~2 KB).
4. **Write AP slot ITEM_PARA entries** via the existing
   `ext_item_para_slot_bin_offset` helper — **BUT** that helper only
   works for slots 128..255 with the bin offset that points at the
   OLD ITEM_DESC_PTR region. Slots 128..143 fit there (the freed
   ITEM_DESC_PTR region is 512 bytes = 16 slots from 128..143).
   **Slots 144..180 need a different bin-offset helper that targets
   the NEW location directly.** Implement a new helper, e.g.:

   ```python
   def reloc_item_para_slot_bin_offset(slot: int) -> int:
       """Sector-aware .bin offset of slot `slot` in the RELOCATED
       ITEM_PARA region. For slots 144..180 (slots above the freed
       ITEM_DESC_PTR region's capacity)."""
       if not 144 <= slot <= 180:
           raise ValueError(f"slot {slot} out of [144, 180] range")
       byte_offset = slot * ROM_ITEM_TABLE_ENTRY_SIZE
       return _slus_ram_to_bin_offset(
           ITEM_PARA_RELOC_RAM + byte_offset,
       )
   ```

   Token writes to slots 144..180 go directly to the NEW .bin
   location and are NOT touched by `relocate_item_para` (which only
   copies the OLD bytes for slots 0..143).
5. **Patch the shop's scan-loop bound** to include your new slots.
   Vanilla shops have a hardcoded `sltiu` immediate that caps the
   scan; find it via static analysis and patch via apply_tokens.
6. **Hijack the shop's `jal giveItem`** to a new wrapper in Cave6.
   Clone `_build_merit_shop_ext_wrapper_bytes()`.
7. **Tests**: clone `test_merit_shop_extended.py`'s shape — 50+
   tests covering locations, triggers, wrapper bytecode, patcher
   tokens (option on + off).

---

## Free RAM regions (catalog)

Identified by static analysis (free-RAM agent 1A on 2026-05-13).
All are Cave6-style libgs-leftover regions: zero inbound jal/j/branch
targets, zero lui+addiu reads landing in the range.

| RAM range | size | status | notes |
|---|---|---|---|
| `0x800957C0..0x80096BCC` | 5132 B | **Cave6 — heavily used.** Chest + setTrigger + changeMap + merit v1 + recycle wrappers + ITEM_DESC_PTR reloc + recycle AP descs + merit AP descs + merit ext wrapper + icon clamp + recycle init wrapper | ~2 KB free past `0x800963F0`. |
| `0x8009DBC8..0x8009F278` | 5808 B | **Used by Path A (ITEM_PARA relocation).** | 5808 / 32 = 181 slot capacity; slots 144..180 free for future shops. |
| `0x800BA658..0x800BB4FF` | 3752 B | **FREE** (verified by agent 1A) | Cave6-equivalent. Plenty for misc wrappers / tables. |
| `0x800C3860..0x800C494F` | 4336 B | **FREE** (verified by agent 1A) | Cave6-equivalent. Could host another data block. |
| `0x800CA9CC..0x800CB4EB` | 2848 B | **FREE** (verified by agent 1A) | Cave6-equivalent. |
| `0x801091DC..0x80109BBB` | 2528 B | **FREE** (verified by agent 1A) | Cave6-equivalent. |

**Combined free capacity outside Path A:** ~13 KB across 4 regions.
Each independently meets Cave6's "0 inbound calls" test. Run
`tools/dw1_freeregion_probe.lua` to empirically validate before
shipping any code that writes into these.

---

## Pitfalls / gotchas

1. **Sector boundaries.** `apply_tokens` writes flat into the .bin.
   Any single token write that crosses a Mode2/2352 sector boundary
   will overflow into the EC zone (harmless — `recalc_edc` rewrites
   it) AND the next sector's HEADER (catastrophic — the PSX CD-ROM
   won't reliably load the next sector). **Always check that
   data > 2048 bytes either fits in a single sector's user-data
   region or use a procedure extension's `write_user_data_bytes`**
   (sector-aware).

2. **Cave6 vs Path A region.** The Path A region at `0x8009DBC8` is
   NOT Cave6 — it's a separate libgs-leftover region elsewhere in
   the SLUS exec. Don't allocate Cave6-targeted writes there or
   vice versa.

3. **Wrappers must use `_decompose_kuseg`.** Any new wrapper that
   constructs a kuseg address via `lui+addiu` must call
   `_decompose_kuseg(target_address)` to handle the sign-extension
   case correctly. Hardcoding `(addr >> 16) & 0xFFFF` for the lui
   high half is wrong whenever the low half has bit 15 set
   (most kuseg addresses with low half in `0x8000..0xFFFF`).

4. **The 24 reader sites are static.** They reflect a specific SLUS
   build (SLUS-01032 USA). If we ever target a different region/
   build, re-run `tools/dw1_scan_item_para_readers.py` to refresh
   the list.

5. **Don't trust SydPatches docs.** Multiple regions SydPatches
   marked "free" (e.g., Cave1 at `0x800A0A50`) are USED by vanilla
   DW1 (called from many sites). Always verify free-region
   candidates against the vanilla disassembly AND the runtime probe.

6. **Slots 144..180 patches need a NEW-location bin offset.** The
   existing `ext_item_para_slot_bin_offset(slot)` helper resolves
   to OLD .bin offsets (only valid for slots 128..143 because those
   live in the freed ITEM_DESC_PTR region; slot 144 would land on
   the per-item color table at `0x80127BDC`). For slots 144+, write
   directly to the NEW location's .bin offset.
