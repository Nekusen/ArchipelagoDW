# Merit Shop Full Randomization — Starter prompt for new session

Paste the block under "PROMPT" below into a fresh Claude Code
session at the repo root. The session will then have the right
context to plan and implement merit shop AP randomization without
re-doing finished RE.

---

## PROMPT

We're extending the Digimon World 1 (PS1) APWorld to make the
**ShogunGekomon merit shop in Volume Villa** fully AP-randomized.
Currently only one slot (id 83 = "AP Item" sentinel) is wired as an
AP location; we want all of the merit shop's items to become
distinct AP locations with custom names + prices, the same way the
recycle shop was just shipped.

### Read these first, in order, before writing any code

1. `worlds/digimon_world/docs/recycle_shop_implementation_plan.md`
   — read the **STATUS section at the top** in full. It's the
   working-implementation summary plus the wrong-guess
   corrections from the original plan. Extended ITEM_PARA via
   ITEM_DESC_PTR relocation is the architectural blueprint for
   what you'll do here. Skim sections 1-7 for context but treat
   them as historical.
2. `worlds/digimon_world/docs/merit_shop.md` — read the **STATUS
   section at the top** plus sections 1-5 (architecture,
   wrapper, reconciler, current single-slot state). Section 6
   (the "scaling beyond ~12" analysis) is now mostly stale —
   the extended-ITEM_PARA infrastructure from §6a Option 1
   already exists. Sections 7-11 still apply.
3. `worlds/digimon_world/data/addresses.py` — search for the
   "Recycle Shop (GIAS06B)" block (~line 6240) and the
   "Merit Shop give-item wrapper" block (~line 3690). The
   recycle shop block is the template for the new merit shop
   constants you'll add. The merit shop block is where existing
   `MERIT_SHOP_DISPATCH` lives — you'll extend it.
4. `worlds/digimon_world/rom.py` — `_write_recycle_shop_tokens`
   shows the patcher pattern; `_write_merit_shop_wrapper_tokens`
   is the existing single-slot merit shop patcher you'll
   extend.
5. `worlds/digimon_world/client.py` —
   `_reconcile_merit_shop_sentinel` is the existing per-tick
   reconciler that bumps slot 83's `meritValue` to `0x7FFF`
   post-purchase. With multi-slot dispatch you may need to
   generalize it (or replace with a different post-purchase UX,
   e.g. the "AP Item Bought" sentinel sets that aren't being
   used).
6. The auto-memory note `dw1_recycle_shop_constructor.md` (in
   `~/.claude/projects/c--opt-dev-AP-ArchipelagoDW/memory/`) —
   the actual recycle shop array writer was at RAM `0x800FA834`,
   NOT the `init_shop_obj` at `0x800A32F4` that an earlier guess
   targeted. Don't repeat that wrong guess for the merit shop.

### What's already true (don't re-derive)

- ITEM_DESC_PTR is **relocated** to RAM `0x80095980` in Cave6.
  The `relocate_item_desc_ptr` procedure extension copies the
  vanilla 128 entries from the source ROM and fills slots 128+
  with AP description-string pointers.
- Three vanilla `lui+addiu` callsites that loaded the original
  ITEM_DESC_PTR base have been patched. All three use `$r2`.
- Slots 128..134 are **used by the recycle shop**. Slots 135..255
  in the relocated table are currently **all zero pointers** —
  available for the merit shop.
- `setItemTexture` is wrapped to clamp `id >= 128 → slot 83`
  (already-blanked icon). Any merit shop AP item displayed via
  an extended slot will show the blank icon automatically.
- AP description strings ("From `<player>'s World`") use 64-byte
  slots starting at RAM `0x80095D80`. The recycle shop uses
  the first 7 (slots 0..6 → RAM `0x80095D80 + i*64`). For merit
  shop, allocate the next N slots immediately after.
- Cave6 has ~3 KB free after the recycle shop. Plenty of room
  for the extended merit shop wrapper, more desc strings, and
  any new wrappers needed.
- A hard assertion at module-load time fires if anything in
  Cave6 overflows the documented end at RAM `0x80096BCC`.

### What's known about the merit shop (from merit_shop.md)

- Open-time scan loop at RAM `0x00107430` walks ITEM_PARA from
  id 0 up to bound `< 0x80` (= 128), filtering items with
  `meritValue > 0`. **The bound `0x0080` is hardcoded as a
  `sltiu $r1, $r5, 0x0080` immediate** — patching to `0x0100`
  (256) would let it reach our extended slots 128+.
- The merit shop function reads name/price/icon from
  `ITEM_PARA[item_id]` and description from
  `ITEM_DESC_PTR[item_id]` — both already work for extended
  slots 128+ thanks to the recycle shop infrastructure.
- giveItem callsite at RAM `0x8010BF3C` is already hijacked by
  the merit shop wrapper at RAM `0x80095800`. The wrapper
  dispatches by `$a0 == item_id` against
  `MERIT_SHOP_DISPATCH`. Currently 1 entry: `(83, 903)`. Each
  added entry costs 28 bytes / 7 instructions in the wrapper.
- Vanilla merit shop sells ~12 items (pre-existing list in
  ITEM_PARA with `meritValue > 0`). The full list isn't in
  this doc — discover it by scanning ITEM_PARA for non-zero
  `meritValue` (or grep the standalone randomizer's reference
  for the merit shop inventory).
- Existing helpers: `AP_SHOP_BOUGHT_VISIBLE_BYTES` /
  `AP_SHOP_BOUGHT_SENTINEL_*` for post-purchase display state
  (currently used only for slot 114 sentinel that's hidden;
  the wrapper's mark_bought path doesn't fire — known mystery,
  see merit_shop.md §2c).

### Your task

Plan the work in steps and confirm with me before writing code.
A reasonable shape would be:

1. **RE step**: enumerate the ~12 vanilla merit shop items by
   scanning ITEM_PARA for non-zero `meritValue` (write a small
   probe or use static analysis of the standalone randomizer's
   data). Document slot-id, name, vanilla `meritValue` for each.
2. **Trigger allocation**: pick a contiguous range of trigger
   IDs for the new AP locations. The recycle shop uses
   904..910, with 911 free. 912+ is the natural next band; we
   need to verify it doesn't collide with anything in
   `addresses.py` or RAM near `0x001BE03F+`.
3. **Extended slot allocation**: pick a slot range for the AP
   merit shop entries. Recycle uses 128..134; 135..146 is the
   natural next band.
4. **Patcher writes** (modeled on `_write_recycle_shop_tokens`):
   - Per-AP-slot ITEM_PARA entry at extended slot id (name +
     price + non-zero `meritValue` so the scan picks it up).
   - Per-AP-slot description string (truncated player name).
   - Update relocated ITEM_DESC_PTR slots to point at the new
     description strings.
   - Patch the merit shop scan-loop bound from `< 0x80` to
     `< (highest-used-extended-slot + 1)`, so the scan reaches
     our slots.
   - Extend `MERIT_SHOP_DISPATCH` to cover all 12 (id, trigger)
     pairs.
   - Optionally: zero out the existing vanilla items'
     `meritValue` so they no longer appear in the shop (since
     the shop now displays AP slots instead).
5. **Locations**: add `Merit Shop #1..#12` (or item-named?
   discuss) AP locations in a new `69_057_xxx` block in
   `locations.py`. Gate on a new `MeritShopLocations` toggle
   in `options.py`. Ship via `slot_data`.
6. **Client**: extend or replace `_reconcile_merit_shop_sentinel`
   to handle multi-slot post-purchase state. Trigger polling
   for the new IDs needs to feed `LOCATION_RAM_BITS`.
7. **Tests**: mirror `test/test_recycle_shop.py` shape — 50+
   tests covering locations, triggers, wrapper bytecode (with
   careful decode-verify of every emitted instruction), patcher
   tokens (option on + off).

### Constraints (locked, do not revisit)

- **Don't re-baseline on SydPatches.** v1 patches everything
  against vanilla SLUS-01032 (SHA-1 verified). Re-baselining
  is multi-week work not in scope.
- **Don't break v1.** The existing slot-83-as-AP-Item flow
  must keep working — chests, merit shop's current single AP
  item, etc. Test before and after.
- **Don't put data in vanilla code regions.** The "Cave1"
  region at RAM `0x800A0A50+` looked free per SydPatches'
  docs but is full of live vanilla DW1 code (functions called
  from `0x000B61F0`, `0x000D9764`, `0x000E3624`,
  `0x000F1534`, etc.). Cave6 (`0x800957C0..0x80096BCC`) is
  the only verified-safe write region. The hard assertion
  in `addresses.py` will catch overflows.
- **Don't trust hand-typed MIPS opcodes.** Always derive from
  `(opcode << 26) | (rs << 21) | (rt << 16) | imm` and verify
  by decoding back. Two encoding bugs slipped through review
  on the recycle shop's filter-bought wrapper (later
  reverted). The decode-verify pattern is in the recycle
  shop's wrapper-build sanity check at the bottom of the
  constants block.
- **Don't use BizHawk's `event.onmemorywrite` / `onmemoryexecute`
  for RE.** They're unreliable across PSX cores
  (silently no-op under Nymashock). The canonical workflow is
  static disassembly hunt + snapshot/diff with
  `dw1_ram_snapshot.lua`. See `dw1_re_workflow.md` memory note.

### Existing v1 must keep working

- Chest sentinel at slot 83 ("AP Item" name) for chest pickups.
- Merit shop slot 83 single-item flow (one AP location at
  trigger 903 = `Amazing Rod Pickup`). May get superseded by
  the new full-merit-shop pool — discuss with me how to
  transition.
- All other existing AP items, locations, and wrappers untouched.

### Recycle shop nitpick that's still open (low priority, optional)

The user wanted bought slots **removed** from the recycle shop
display list (not just visible-but-unbuyable). My implementation
attempted to filter entries in the prebuild wrapper and decrement
`entry_count`; it crashed the game with full framebuffer
corruption. Reverted in `b5b16796`. If the merit shop work
exposes a similar need (hide post-purchase slots), it'd be worth
revisiting with runtime instrumentation rather than static
review. See git log for the wrapper code that was tried.

### Working state when you start

Branch: `digimon-world-ps1`. Last commit:
`b5b16796` (revert of `bd02848d`).

Latest tests: `pytest worlds/digimon_world` → 449 passed, 4
skipped. Run them after your first patch and after each
substantive change.

The recycle shop is functional and shipped behind
`recycle_shop_locations: 1`; toggle on in your YAML to test
end-to-end with the user's seed.
