# Recycle Shop (GIAS06B) Randomization — Implementation Plan

Result of an extensive RE session (2026-05-10). All architectural
discovery is complete. This document is the implementation handoff:
read it first in a fresh session before writing any code.

Read also: [merit_shop.md](merit_shop.md) — sister doc for the merit
shop's analogous wiring. The recycle shop differs significantly from
the merit shop architecturally, but the giveItem-wrapper pattern is
the same.

---

## STATUS — recycle shop implementation (2026-05-11) ✅ shipped, see also corrections

The recycle shop is **functional and shipped** behind the
`recycle_shop_locations` toggle (default off). Sections 1-7 below
are the **original plan**; the actual implementation deviates in
several places. Read **both** before extending.

### ✅ What's working

- 7 AP locations `Recycle Shop #1..#7` (IDs `69_056_000..006`),
  attached to Gear Savanna region, opt-in via
  `RecycleShopLocations` toggle.
- Slot data ships `recycle_shop_locations` so the client knows
  whether to run its reconciler.
- Trigger range **904..910** (NOT the plan-doc's original
  951..957 — those collide with `RAM_MERAMON_TUNNEL_STATE` at
  `0x001BE043`). All 7 land in byte `0x001BE03E`, leaving bit 7
  free for trigger 911.
- Extended ITEM_PARA slots 128..134 hold per-slot AP entries
  (name = multiworld-resolved AP item name truncated to 14
  chars; price = vanilla recycle slot price; meritValue = 0).
- AP description strings ("From `<player>'s World"`) live in
  Cave6 starting at RAM `0x80095D80`, 64-byte slots, 7 entries.
  ITEM_DESC_PTR[128..134] points into this region.
- Three vanilla `lui+addiu` callsites that load the original
  ITEM_DESC_PTR base (`0x801279DC`) are patched to load the
  relocated table base instead. All three use `$r2`; verified
  against `references/DW1-Code/SLUS.asm`.
- `setItemTexture` at vanilla RAM `0x800E5DFC` is wrapped to
  clamp `id >= 128` to slot 83 (already blanked by the existing
  merit-shop patcher) — fixes garbage icons for extended slots.
- Wrapper at the recycle shop's giveItem callsite (RAM
  `0x800FB410`) hijacks `jal 0x800C5240` and dispatches:
  `id in [128, 134]` → `setTrigger(904 + (id - 128))` and skip
  vanilla giveItem (no item enters inventory; AP delivers via
  the normal path); else → tail-call vanilla giveItem.
- Wrapper at `build_shop_runtime_list` epilogue (RAM
  `0x800FAA60`) overwrites the runtime [id, flag] * 7 array at
  RAM `0x80088828` with `[128,1, 129,1, ..., 134,1]`
  synchronously inside the engine's call chain — eliminates the
  UI name-flicker that the client-side reconciler couldn't fix.
- Client-side reconciler (`_reconcile_recycle_shop_array` in
  `client.py`) writes the same [128..134, flag=1] array each
  game-watcher tick as a defensive backstop. Trigger polling
  for 904..910 is folded into `LOCATION_RAM_BITS`.

### ⚠ What's NOT working (and was reverted)

- **Hide-bought-from-list feature**: an extended wrapper that
  filtered out bought entries (gated each per-slot emit on its
  trigger bit) and decremented `entry_count` to match. Crashed
  the game with full framebuffer corruption regardless of
  bought state. Reverted in `b5b16796`. Static review of the
  wrapper bytecode found no encoding bug; the failure mode is
  unknown without runtime instrumentation. See git history of
  `bd02848d` for the wrapper code that was tried. The
  original 92-byte wrapper (no filter) still ships and works.
- Bought entries currently stay visible in the shop list;
  their trigger bit is set so AP doesn't re-fire on re-buy
  (and the player wastes money but nothing breaks).

### ⚠ Wrong-guess corrections from the original plan

- **Cave1 is NOT free RAM in vanilla DW1.** The plan-doc claimed
  `0x800A0A50..0x800AFD78` was 61 KB free. SydPatches treats
  this as "Cave1" because they ship a complete C++ rewrite
  replacing every function in the range; vanilla DW1 still
  calls into `0x000A0E58`, `0x000A0E60`, `0x000A0E68`, etc.
  from many sites (e.g. `0x000B61F0`, `0x000D9764`,
  `0x000E3624`, `0x000F1534`). Writing data there crashes the
  game on first call. **The relocated ITEM_DESC_PTR table now
  lives in Cave6 at RAM `0x80095980`** (verified safe — same
  region as the chest wrapper, merit shop wrapper, combat
  trampolines, and recycle shop wrapper).
- **The recycle shop's runtime array is built by
  `build_shop_runtime_list` at RAM `0x800FA834`**, not by any
  function that hardcodes the shop_obj base address
  `0x80088804`. The original "construction not fully traced"
  note is now stale — see
  `~/.claude/.../memory/dw1_recycle_shop_constructor.md` for
  the full RE notes and the don't-repeat-the-wrong-guess
  warning. An earlier attempt patched `init_shop_obj` at RAM
  `0x800A32F4` (the only function that loads `0x80088804`
  directly via `lui+ori`); that patch had no effect on the UI
  because `init_shop_obj` populates the shop_obj structure
  but doesn't fill the items array.
- **The trigger byte `0x001BE03E` holds all 7 recycle shop
  bought-bits** (904..910 → bits 0..6 of one byte).

### Files that hold the working implementation

| File | Sections / symbols |
|------|--------------------|
| `data/addresses.py` | "Recycle Shop (GIAS06B) — AP randomization (Phase 10)" block at the bottom (~470 lines). Constants: `RAM_RECYCLE_SHOP_*`, `RECYCLE_SHOP_*`, `RELOC_ITEM_DESC_PTR_*`, `AP_DESC_*`, `ROM_RECYCLE_SHOP_*`, `ROM_ICON_CLAMP_*`, plus the wrapper-builder `_build_recycle_shop_init_wrapper_bytes()`. |
| `rom.py` | `_write_recycle_shop_tokens` writes 9 token sets when option on; `relocate_item_desc_ptr` is a procedure extension run after `apply_tokens`. |
| `client.py` | `_reconcile_recycle_shop_array` runtime patcher; `LOCATION_RAM_BITS` includes `RECYCLE_SHOP_LOCATION_RAM_BITS`. |
| `locations.py` | `_RECYCLE_SHOP_LOCATIONS` (7 entries in `69_056_xxx`); skip-listed in `create_all_locations` when option off. |
| `options.py` | `RecycleShopLocations` toggle in the "Locations" group. |
| `world.py` | `recycle_shop_locations` shipped in `fill_slot_data`. |
| `test/test_recycle_shop.py` | 53 tests covering locations, triggers, wrapper bytecode, patcher tokens (on + off). |

### Cave6 layout after recycle shop ships

```
RAM 0x800957C0..0x800957DC  chest wrapper                28 B  (always-on)
RAM 0x800957DC..0x800957FC  setTrigger wrapper           32 B  (RESERVED, NOT installed)
RAM 0x800957FC..0x80095800  4-byte gap
RAM 0x80095800..0x800958B4  merit shop wrapper          180 B  for N=1 dispatch entry, +28 B per extra entry
RAM 0x800958B4..0x800958CD  AP_ITEM_DESC_STRING          25 B  ("Item from the multiworld\0")
RAM 0x800958CD..0x80095900  ~51-byte gap
RAM 0x80095900..0x8009593C  combat trampolines tr1/2/3   60 B  (option-gated)
RAM 0x80095940..0x8009597C  recycle shop giveItem wrap   60 B  (recycle option only)
RAM 0x80095980..0x80095D80  RELOC_ITEM_DESC_PTR        1024 B  (recycle option only)
RAM 0x80095D80..0x80095F40  AP_DESC_STRINGS             448 B  (recycle option only) — 7 × 64 B
RAM 0x80095F40..0x80095F5C  setItemTexture clamp wrap    28 B  (recycle option only)
RAM 0x80095F5C..0x80095FB8  shop array prebuild wrap     92 B  (recycle option only)
RAM 0x80095FB8..0x80096BCC  ~3 KB free for future expansion
```

Cave6 ends at RAM `0x80096BCC` (verified: vanilla function starts
right after, called from `0x000B40D4` etc.). A hard assertion in
addresses.py fires at module-load if anything overflows.

---

## 1. What we know about the Recycle Shop

### 1a. Identity

- **NPC**: "Market Manager" (in-game text); player-facing reference =
  Tinmon's Recycle Shop in Gear Savanna.
- **Screen**: `GIAS06B` (map id 131 in `SCREEN_FILENAMES`).
- **Script**: ID 126, Section 82 (per
  `references/digimon_world_randomizer/script/DW1Script.txt:19271-19304`).
- **Dialog flow**:
    ```
    showTextbox "This's a Recycled Goods shop."
    showTextbox "I want a regular item / I want a recycled item / Next time"
    [recycled branch:]
      setTrigger 385
      setTrigger 389
      setTrigger 406
      setTrigger 423
      setTrigger 399
      setTrigger 400
      setTrigger 401
      callRoutine 8           ; opens shop UI
      unsetTrigger 385..401   ; cleanup
    ```
- **Currency**: money (Bits).

### 1b. Vanilla items (verified 2026-05-10 via runtime probe)

The 14-byte item-list array at RAM `0x80088828` contains
`[id_u8, flag_u8] * 7` with flag = `0x01` for all entries:

| Slot | id (hex) | Item        | Vanilla price |
|------|----------|-------------|---------------|
| 1    | `0x01`   | med.recovery | 500          |
| 2    | `0x05`   | Medium MP    | 800          |
| 3    | `0x0F`   | Off. Disk    | 500          |
| 4    | `0x10`   | Def. Disk    | 500          |
| 5    | `0x11`   | Hispeed dsk  | 500          |
| 6    | `0x16`   | Auto Pilot   | 300          |
| 7    | `0x27`   | Giant Meat   | 500          |

### 1c. Runtime data structures

Per the runtime probe (BizHawk Nymashock, MainRAM domain):

**`shop_obj`** at RAM `0x80088804` (pointed to by `gp - 0x6BC4` =
RAM `0x80134F68`). 32-byte structure:

| Offset | Size | Field            | Observed value        |
|--------|------|------------------|-----------------------|
| 0x00   | u32  | item_list_ptr    | `0x80088828` (= shop_obj + 0x24) |
| 0x04   | u32  | initialized?     | `0x00000001`          |
| 0x08   | u8   | entry_count      | `0x07` (= 7 entries)  |
| 0x09   | u8   | start_idx        | `0x00`                |
| 0x0A   | u8   | cursor_offset    | `0x00..0x06`          |
| 0x0B   | u8   | visible_count    | `0x06`                |
| 0x0C   | u32  | flags?           | `0x00000001`          |
| 0x10+  | …    | (UI state, color/render fields) | … |

**Runtime array** at RAM `0x80088828` (pointed to by
`shop_obj.item_list_ptr`). 14 bytes:

```
01 01 05 01 0F 01 10 01 11 01 16 01 27 01
```

The array is **NOT in the .bin** as static data — verified by
exhaustive signature scan (every layout: 1-byte/2-byte/4-byte stride,
all 720 permutations, ID+price clusters, etc. — zero hits). The array
is constructed at runtime from scattered ROM data via some engine
path that has not been fully traced.

**Practical implication:** we cannot patch the array statically. We
must either (a) patch it at runtime via a client poll, or (b) trace
and patch the engine code that constructs it. Path (a) is the chosen
approach for v1.

### 1d. giveItem callsite

The recycle shop's `jal giveItem` is at RAM `0x800FB410`. **Unique to
this shop** (not shared with the File City money shops at
`0x80108798/0x8010896C/0x80108B68` or with the merit shop at
`0x8010BF3C`).

`$a0` = item id of the bought slot (read from gp - 0x6BB4 = "current
item id" set just before the jal).

### 1e. Trigger states confirmed

When the shop opens, all 7 triggers do flip 0->1 as expected (verified
2026-05-10):

| Trigger | Byte address | Mask  |
|---------|--------------|-------|
| 385     | `0x001BDFFD` | `0x02` |
| 389     | `0x001BDFFD` | `0x20` |
| 406     | `0x001BDFFF` | `0x40` |
| 423     | `0x001BE001` | `0x80` |
| 399     | `0x001BDFFE` | `0x80` |
| 400     | `0x001BDFFF` | `0x01` |
| 401     | `0x001BDFFF` | `0x02` |

These triggers **do not appear to be per-item visibility flags** — the
agent's earlier hypothesis that they map 1-to-1 to the 7 array slots
is not yet verified. Set the array directly via runtime patch instead.

---

## 2. Architectural plan: in-place ITEM_PARA extension

### 2a. Why this approach

The user's UX requirement: **each AP shop slot must display a custom
name** (the multiworld-resolved AP item name, truncated to 14 chars,
with description "From X's World"). Vanilla item names are not
acceptable.

This requires **distinct ITEM_PARA entries per AP slot** (the renderer
reads name/price from `ITEM_PARA[id]`). Vanilla ITEM_PARA only has
~3 truly unused slots (83, 114, 124), and those are already used by
the existing v1 AP system (chest sentinel, merit shop sentinel, etc.).
So we need **new** ITEM_PARA slots without disturbing 0-127.

### 2b. The trick: ITEM_DESC_PTR relocation

ITEM_DESC_PTR lives at RAM `0x801279DC` — the byte **immediately after**
ITEM_PARA[127]. If we relocate the entire ITEM_DESC_PTR to free RAM
(Cave1), the 512 bytes at `0x801279DC..0x80127BDC` become available
to extend ITEM_PARA in place. That gives us **16 new slots** (128-143)
without touching slots 0-127 or any other engine state.

The renderer already reads `ITEM_PARA + id*32` for name/price/etc., so
when we put valid item data at the freed addresses, slot id=128 reads
naturally land at `0x801279DC` — our extended slot data. **No renderer
patches needed.**

The only patches needed are the 3 callsites that read ITEM_DESC_PTR
(they need to read from the relocated address instead of the original
`0x801279DC`).

### 2c. ITEM_DESC_PTR readers

Only **3 callsites** in the SLUS read ITEM_DESC_PTR (verified by grep
on `addiu rN, rN, 0x79dc`):

| Address | Function context | Role |
|---------|------------------|------|
| `0x000DC64C` | Inventory desc display (function entry near `0x000DC600`) | Reads desc pointer for item shown in inventory hover |
| `0x000FD754` | Shop desc panel (function `0x000FD61C`) | First desc read in shop UI |
| `0x000FD770` | Shop desc panel (same function) | Second desc read in shop UI |

All three need the same patch: change `lui $rN, 0x8012` from
`0x3C0?8012` to point at the new Cave1 base, and change
`addiu $rN, $rN, 0x79dc` to point at the new offset.

If the new base is e.g. `0x800A0A50`:
- Original encoding (hi): `lui $r2, 0x8012` = `0x3C028012`
- New encoding (hi): `lui $r2, 0x800B` (because addiu sign-extends and 0xA50 is positive, so high half stays the same) — wait no: `lui 0x800A; addiu r2, r2, 0x0A50` resolves to `0x800A0000 + 0x0A50 = 0x800A0A50`. So: `lui $r2, 0x800A` = `0x3C02800A`, `addiu $r2, $r2, 0x0A50` = `0x24420A50`.

For the implementer: place the relocated ITEM_DESC_PTR at an address
whose low 16 bits are convenient — e.g. `0x800A0A50` works.

---

## 3. Cave1 layout (proposed)

Cave1 spans RAM `0x800A0A50..0x800AFD78` (61 KB). Plenty of room.

| RAM address | Size | Content |
|-------------|------|---------|
| `0x800A0A50` | 1024 B | Relocated ITEM_DESC_PTR (256 entries × u32). Slots 0-127 = vanilla pointers (copied from .bin offset corresponding to original RAM `0x801279DC`). Slots 128-134 = pointers to AP description strings (below). Slots 135-255 = zeros. |
| `0x800A0E50` | ~450 B | 7 AP description strings (e.g., `"From <player_name>'s World\0"`), null-terminated. Each ~64 bytes. |
| `0x800A1000+` | (free) | ~60 KB available for future shops |

**Bin offset translation:** RAM `0x800A0A50` maps to .bin offset
`_flat_to_user_data(SLUS_BIN_BASE, 0xA0A50 - 0x90000) = _flat_to_user_data(SLUS_BIN_BASE, 0x10A50)`.

`SLUS_BIN_BASE` = the .bin offset corresponding to RAM `0x80090000`
(the SLUS executable's load address). We can derive this from the
existing chest wrapper offset: `ROM_CHEST_GIVEITEM_WRAPPER_OFFSET =
0x14CC0B18` corresponds to RAM `0x800957C0`. So:
`SLUS_BIN_BASE = 0x14CC0B18 - (0x800957C0 - 0x80090000) = 0x14CBB358`.

But sector hops apply for any address that crosses 2048-byte user-data
boundaries. **Always use `_flat_to_user_data`** (defined in
`addresses.py`) when computing bin offsets for arbitrary RAM addresses.

---

## 4. Implementation steps (in order)

### STEP 1: addresses.py — add constants

Add a new section at the end (after the merit shop section). Constants
needed:

```python
# === Recycle Shop (GIAS06B) — AP randomization ===

# RAM addresses (verified live 2026-05-10)
RAM_RECYCLE_SHOP_OBJ = 0x00088804           # bare; shop_obj for recycle
RAM_RECYCLE_SHOP_LIST_PTR = 0x00088828      # bare; runtime [id,flag]*7 array
RAM_RECYCLE_SHOP_GP_SLOT = 0x00134F68       # bare; gp-0x6BC4 (holds shop_obj ptr)

# Per-shop count (used for detecting "is recycle shop open")
RECYCLE_SHOP_ENTRY_COUNT = 7

# AP slot range for recycle shop (extends ITEM_PARA in-place)
RECYCLE_SHOP_AP_ITEM_ID_BASE = 128          # ITEM_PARA slot 128
RECYCLE_SHOP_AP_ITEM_ID_COUNT = 7           # uses slots 128..134

# AP location triggers (allocated 951-957 — verify these are unused)
RECYCLE_SHOP_TRIGGER_BASE = 951             # trigger 951 = "bought slot 1"
RECYCLE_SHOP_TRIGGER_COUNT = 7              # 951..957

# Vanilla item IDs of the 7 slots (for reference / diagnostics)
RECYCLE_SHOP_VANILLA_IDS = (0x01, 0x05, 0x0F, 0x10, 0x11, 0x16, 0x27)
RECYCLE_SHOP_VANILLA_PRICES = (500, 800, 500, 500, 500, 300, 500)

# Cave1 layout
EXT_CAVE1_RAM_BASE = 0x800A0A50
EXT_CAVE1_BIN_OFFSET = _flat_to_user_data(SLUS_BIN_BASE, 0xA0A50 - 0x90000)

# Relocated ITEM_DESC_PTR
RELOC_ITEM_DESC_PTR_RAM = EXT_CAVE1_RAM_BASE                   # 0x800A0A50
RELOC_ITEM_DESC_PTR_SIZE = 256 * 4                              # 256 entries u32
RELOC_ITEM_DESC_PTR_BIN_OFFSET = EXT_CAVE1_BIN_OFFSET

# AP description strings (7 strings, ~64 B each)
AP_DESC_STRING_MAX_LEN = 64
AP_DESC_STRINGS_RAM = RELOC_ITEM_DESC_PTR_RAM + RELOC_ITEM_DESC_PTR_SIZE  # 0x800A0E50
AP_DESC_STRINGS_BIN_OFFSET = ...  # _flat_to_user_data based on offset

# Vanilla ITEM_DESC_PTR source location (.bin)
# RAM 0x801279DC = ITEM_PARA[128] = ITEM_DESC_PTR base
VANILLA_ITEM_DESC_PTR_RAM = 0x801279DC
VANILLA_ITEM_DESC_PTR_BIN_OFFSET = _flat_to_user_data(SLUS_BIN_BASE, 0x1279DC - 0x90000)

# Extended ITEM_PARA region (the freed-up bytes at original ITEM_DESC_PTR location)
EXT_ITEM_PARA_RAM = 0x801279DC                                  # = original ITEM_DESC_PTR
EXT_ITEM_PARA_BIN_OFFSET = VANILLA_ITEM_DESC_PTR_BIN_OFFSET     # same .bin location

# ITEM_DESC_PTR callsite patches
# Each callsite has lui $rN, 0x8012 + addiu $rN, $rN, 0x79DC
# We change lui to 0x800A and addiu to 0x0A50 (matches RELOC_ITEM_DESC_PTR_RAM)

# Each entry: (.bin offset of the lui, .bin offset of the addiu)
RELOC_ITEM_DESC_PTR_PATCH_SITES = (
    # Inventory desc display
    (_flat_to_user_data(SLUS_BIN_BASE, 0xDC648 - 0x90000),
     _flat_to_user_data(SLUS_BIN_BASE, 0xDC64C - 0x90000)),
    # Shop desc panel #1
    (_flat_to_user_data(SLUS_BIN_BASE, 0xFD750 - 0x90000),
     _flat_to_user_data(SLUS_BIN_BASE, 0xFD754 - 0x90000)),
    # Shop desc panel #2
    (_flat_to_user_data(SLUS_BIN_BASE, 0xFD76C - 0x90000),
     _flat_to_user_data(SLUS_BIN_BASE, 0xFD770 - 0x90000)),
)

# giveItem wrapper for recycle shop
ROM_RECYCLE_SHOP_PATCH_OFFSET = _flat_to_user_data(SLUS_BIN_BASE, 0xFB410 - 0x90000)
ROM_RECYCLE_SHOP_WRAPPER_RAM = 0x80095800 + ...  # after merit shop wrapper in Cave6
ROM_RECYCLE_SHOP_WRAPPER_OFFSET = _flat_to_user_data(...)

# Wrapper bytes (built dynamically from RECYCLE_SHOP_AP_ITEM_ID_BASE etc.)
def _build_recycle_shop_wrapper_bytes() -> bytes:
    """Build MIPS wrapper for recycle shop's giveItem callsite.
    
    Logic:
      if $a0 - 128 < 7:   # in AP slot range
          setTrigger(951 + ($a0 - 128))
          jr $ra; addiu $v0, $0, 1   # success, skip vanilla giveItem
      else:
          j 0x800C5240   # tail-call vanilla giveItem
    """
    # ~12 instructions / 48 bytes
    ...

ROM_RECYCLE_SHOP_WRAPPER_BYTES = _build_recycle_shop_wrapper_bytes()

# Patch site: replace original `jal 0x800C5240` (= 0x0C031490 LE)
# at .bin offset 0xFB410 with `jal wrapper_ram`
ROM_RECYCLE_SHOP_PATCH_VALUE = (
    0x0C000000 | ((ROM_RECYCLE_SHOP_WRAPPER_RAM >> 2) & 0x03FFFFFF)
)

# AP_DESC_PREFIX (added to each AP item desc)
AP_DESC_PREFIX = b"From "
AP_DESC_SUFFIX = b"'s World\x00"
```

### STEP 2: rom.py — patcher writes

Add a `_write_recycle_shop_tokens(self, ...)` method that emits all
the patcher writes:

1. **Relocated ITEM_DESC_PTR**: read 512 bytes from
   `VANILLA_ITEM_DESC_PTR_BIN_OFFSET` and write to
   `RELOC_ITEM_DESC_PTR_BIN_OFFSET`. Then write 7 new u32 entries
   (offsets 128..134) pointing to AP description strings.

2. **AP description strings**: format each as
   `b"From " + player_name.encode() + b"'s World\x00"` (truncate if
   needed to fit in `AP_DESC_STRING_MAX_LEN`). Write to
   `AP_DESC_STRINGS_BIN_OFFSET + i * AP_DESC_STRING_MAX_LEN`.

3. **AP ITEM_PARA entries** (overwriting old ITEM_DESC_PTR location):
   for each AP slot i in 0..6:
   - Compute name from multiworld-resolved AP item at the corresponding
     location (truncate to 14 chars).
   - Compute price (vanilla price for that slot per
     `RECYCLE_SHOP_VANILLA_PRICES`).
   - Write 32-byte ITEM_PARA entry at
     `EXT_ITEM_PARA_BIN_OFFSET + i * 32`.

4. **3 ITEM_DESC_PTR callsite patches**: for each `(lui_off, addiu_off)`
   in `RELOC_ITEM_DESC_PTR_PATCH_SITES`:
   - Write `0x3C02800A` (lui $r2, 0x800A) at lui_off
   - Write `0x24420A50` (addiu $r2, $r2, 0x0A50) at addiu_off
   - Note: the original instructions used different registers; preserve
     the destination register from the vanilla encoding.

5. **giveItem wrapper**: write `ROM_RECYCLE_SHOP_WRAPPER_BYTES` to
   `ROM_RECYCLE_SHOP_WRAPPER_OFFSET`. Patch the jal at
   `ROM_RECYCLE_SHOP_PATCH_OFFSET` to `ROM_RECYCLE_SHOP_PATCH_VALUE`.

### STEP 3: client.py — runtime array patcher

Add a per-tick reconciler (called from the game-watcher loop):

```python
async def _reconcile_recycle_shop_array(self, ctx):
    # Read shop_obj pointer at gp-0x6BC4 = RAM 0x80134F68
    gp_slot = (await bizhawk.read(ctx.bizhawk_ctx, [
        (RAM_RECYCLE_SHOP_GP_SLOT, 4, DOMAIN_MAIN_RAM)
    ]))[0]
    if not gp_slot or len(gp_slot) != 4:
        return
    shop_obj_ptr = int.from_bytes(gp_slot, "little")
    # NULL = no shop open
    if shop_obj_ptr < 0x80000000 or shop_obj_ptr >= 0x80200000:
        return
    bare = shop_obj_ptr - 0x80000000
    # Read entry_count from shop_obj+8
    entry_count = (await bizhawk.read(ctx.bizhawk_ctx, [
        (bare + 8, 1, DOMAIN_MAIN_RAM)
    ]))[0]
    if not entry_count or entry_count[0] != RECYCLE_SHOP_ENTRY_COUNT:
        return
    # Read item_list_ptr from shop_obj+0
    item_list_ptr_bytes = (await bizhawk.read(ctx.bizhawk_ctx, [
        (bare + 0, 4, DOMAIN_MAIN_RAM)
    ]))[0]
    item_list_ptr = int.from_bytes(item_list_ptr_bytes, "little")
    if item_list_ptr < 0x80000000:
        return
    list_bare = item_list_ptr - 0x80000000
    # Read current array contents to check if patching needed
    current = (await bizhawk.read(ctx.bizhawk_ctx, [
        (list_bare, 14, DOMAIN_MAIN_RAM)
    ]))[0]
    # Check if first byte is already 128 (= already patched)
    if current and current[0] == RECYCLE_SHOP_AP_ITEM_ID_BASE:
        return
    # Build new array: [128,1, 129,1, ..., 134,1]
    new_array = bytes()
    for i in range(RECYCLE_SHOP_AP_ITEM_ID_COUNT):
        new_array += bytes([RECYCLE_SHOP_AP_ITEM_ID_BASE + i, 0x01])
    await bizhawk.write(ctx.bizhawk_ctx, [
        (list_bare, list(new_array), DOMAIN_MAIN_RAM)
    ])
```

Add a per-tick check for the new triggers (951..957) in
`_check_locations`:

```python
# In the trigger-array poll, also check 951..957 for recycle shop
recycle_block = await bizhawk.read(...)  # bytes covering bits 951..957
for i in range(RECYCLE_SHOP_TRIGGER_COUNT):
    bit = 951 + i
    byte_offset = bit // 8
    bit_mask = 1 << (bit % 8)
    if recycle_block[byte_offset] & bit_mask:
        location_name = f"Recycle Shop #{i + 1}"
        await self._send_location(location_name)
```

### STEP 4: locations.py — add 7 new locations

```python
RECYCLE_SHOP_LOCATIONS = (
    "Recycle Shop #1",
    "Recycle Shop #2",
    "Recycle Shop #3",
    "Recycle Shop #4",
    "Recycle Shop #5",
    "Recycle Shop #6",
    "Recycle Shop #7",
)

# Map each to its trigger ID (used for AP -> trigger dispatch)
RECYCLE_SHOP_LOCATION_TRIGGERS = {
    f"Recycle Shop #{i + 1}": 951 + i
    for i in range(7)
}
```

Wire into `LOCATION_TABLE` and `LOCATION_DEFINITIONS`. Region:
"Gear Savanna" (verify region name from existing locations.py).

### STEP 5: tests

`worlds/digimon_world/test/test_recycle_shop.py`:

1. `test_recycle_shop_locations_registered` — 7 locations exist with
   correct names and IDs.
2. `test_recycle_shop_triggers_in_range` — 951..957 are within the AP
   trigger range and don't conflict with existing triggers.
3. `test_recycle_shop_patcher_writes` — verify the patcher emits
   writes for the relocated ITEM_DESC_PTR, AP item entries, AP desc
   strings, callsite patches, and giveItem wrapper.
4. `test_recycle_shop_wrapper_bytes` — verify the wrapper MIPS bytes
   are correctly assembled (sentinel comparison + setTrigger call).

---

## 5. Testing checklist (in-game smoke)

After patching a generated ROM:

1. **Boot** — game loads without crashing (relocations didn't break
   anything).
2. **Inventory** — open inventory, hover an item. Description should
   display correctly (relocated ITEM_DESC_PTR works for vanilla items).
3. **File City money shop** — open. Items should display normally
   (vanilla shop unaffected by recycle shop changes).
4. **Merit shop** — open. AP item still shows correctly (existing v1
   functionality unaffected).
5. **Recycle shop** — open. The 7 slots should display the multiworld
   AP item names (truncated to 14 chars). The description (when
   hovered) should show "From <player_name>'s World".
6. **Buy a slot** — money should be deducted. Vanilla item should NOT
   appear in inventory. AP location should fire (visible in tracker).
   The actual AP item (e.g., a key item or a foreign world's item)
   should be delivered via the normal AP path.
7. **Repeat for all 7 slots** — verify each fires its specific
   location.

---

## 6. Open questions / pitfalls

- **`_flat_to_user_data` might need a different `SLUS_BIN_BASE` than
  what we derived.** The merit-shop wrapper offset gives us one anchor;
  cross-check with another known address before patching.
- **The runtime array gets re-initialized every time the shop opens.**
  Our client poll patches it after the engine writes the vanilla IDs.
  There's a 1-frame race window where vanilla items might briefly
  display. Acceptable for v1.
- **The 7 setTrigger calls in Script 126 are still set whenever the
  shop opens.** We don't need to do anything with them, but be aware
  they're set/unset around `callRoutine 8`.
- **Trigger IDs 951..957 — verify these are unused.** Existing AP
  trigger ranges in `addresses.py` should be checked. If conflict,
  shift to 1000+ or use a different range.
- **`AP_DESC_STRING_MAX_LEN` (64) might be too short** for very long
  player names + item names. If truncation cuts off important info,
  bump it. Cave1 has 60 KB headroom.
- **The 3 ITEM_DESC_PTR callsite patches might use different registers
  ($r2, $r3, etc.).** Check each callsite's vanilla encoding before
  computing the patch bytes — the destination register must be
  preserved.

---

## 7. Files touched

| File | Changes |
|------|---------|
| `worlds/digimon_world/data/addresses.py` | New section at end (~150 lines) |
| `worlds/digimon_world/rom.py` | Add `_write_recycle_shop_tokens` method (~80 lines) |
| `worlds/digimon_world/client.py` | Add `_reconcile_recycle_shop_array` + extend `_check_locations` (~50 lines) |
| `worlds/digimon_world/locations.py` | Add 7 location entries + region mapping (~20 lines) |
| `worlds/digimon_world/test/test_recycle_shop.py` | New file, 4 tests (~150 lines) |
| `worlds/digimon_world/tools/dw1_recycle_shop_probe.lua` | Already updated to use MainRAM directly |

Other DW1 Lua probes (`dw1_keyitem_bank_probe.lua`,
`dw1_merit_shop_probe.lua`, etc.) should be updated to use the same
"force-MainRAM-via-pcall" trick as a follow-up.

---

## 8. Estimated effort

~3 hours of focused implementation in a fresh session. Most of the
complexity is in step 1 (constants — lots of address math) and step 2
(patcher writes). Steps 3-5 are mostly mechanical extensions of
existing code patterns.
