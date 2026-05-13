# Item Shop Randomization — Starter prompt for new session

Paste the block under "PROMPT" below into a fresh Claude Code
session at the repo root. The session will then have the right
context to plan and implement Item Shop (regular money shop) AP
randomization without re-doing finished work.

---

## PROMPT

We're extending the Digimon World 1 (PS1, USA SLUS-01032) APWorld
to add AP randomization for the **regular money shops** — File City's
Normal Shop (3 sub-shops) and the **Secret Shop**. Both pay in Bits
(money) rather than Merits. They scan ITEM_PARA at open time, similar
to the merit shop but filtering on the ``value`` field (offset 0x14)
instead of ``meritValue`` (offset 0x18).

Two AP shop randomizations already ship in this codebase and are the
direct architectural templates: **recycle shop** and **merit shop**.
The infrastructure they rely on (extended ITEM_PARA, relocated
ITEM_DESC_PTR, Cave6 wrappers, sector-aware bin offsets) is in place
and tested. Don't re-design any of that.

### Read these first, in order, before writing any code

1. ``worlds/digimon_world/docs/item_para_relocation.md`` —
   **read the whole thing**. This documents the always-on
   ITEM_PARA relocation (Path A) that ships in every seed. It
   defines the free-slot range (144..180) and the free-region
   catalog you'll draw from. Critical sections:
   - Memory layout (where ITEM_PARA lives now).
   - "How to add a new shop using Path A" (your recipe).
   - "Free RAM regions (catalog)" (where to put new wrappers /
     data — Cave6 is nearly full so probably use one of the
     fresh regions like ``0x800BA658`` or ``0x800C3860``).
   - Pitfalls.
2. ``worlds/digimon_world/docs/merit_shop_session_starter.md`` and
   ``worlds/digimon_world/docs/merit_shop.md`` — the architectural
   template. Read the STATUS section of merit_shop.md plus
   sections 1-5. **Section 7** sketches the regular-money-shop
   architectural hypothesis (4 jal-giveItem callsites in
   ``0x80108xxx``) that you'll be confirming.
3. ``worlds/digimon_world/docs/recycle_shop_implementation_plan.md`` —
   STATUS section at the top. Recycle shop is a slightly different
   shape (engine-managed array vs ITEM_PARA scan), so review for the
   ITEM_DESC_PTR / extended-slot mechanics that apply here too.
4. ``worlds/digimon_world/data/addresses.py`` — search for:
   - ``ITEM_PARA_RELOC_*`` (the new relocation constants block at
     the very end).
   - ``MERIT_SHOP_*`` (~line 6700+) — your dispatch / wrapper builder
     template.
   - ``RECYCLE_SHOP_*`` (~line 6280+).
5. ``worlds/digimon_world/rom.py`` — search for:
   - ``relocate_item_para`` (in ``DigimonWorldPatchExtension``).
   - ``_write_merit_shop_locations_tokens`` and
     ``_write_recycle_shop_tokens`` — your patcher templates.
6. ``worlds/digimon_world/tools/dw1_scan_item_para_readers.py`` —
   the static-analysis pattern. Adapt it for any new scan you need
   (e.g., to find the regular-shop scan loops by their reader
   pattern).

### What's already true (don't re-derive)

- **ITEM_PARA is relocated to RAM 0x8009DBC8.** Capacity 181 slots.
  Slots 0..127 vanilla, 128..134 recycle, 135..143 merit. Slots
  144..180 (37 slots) are reserved for your work + any further
  expansion.
- All 24 vanilla SLUS readers of ITEM_PARA load the new base.
  No additional patching needed for the table itself.
- ``RAM_ITEM_PARA`` constant points to the NEW location;
  ``RAM_ITEM_PARA_VANILLA`` is the original 0x801269DC, used for
  some patcher writes whose data flows through to the relocation.
- ``_decompose_kuseg(addr)`` handles MIPS lui/addiu sign-extension
  for any new wrapper.
- Cave6 (``0x800957C0..0x80096BCC``) is nearly full (~2 KB free
  past the merit ext wrapper). For new wrappers, use one of the
  fresh free regions catalogued in ``item_para_relocation.md``
  (``0x800BA658``, ``0x800C3860``, ``0x800CA9CC``, ``0x801091DC``).
  Empirically validate any chosen region with
  ``tools/dw1_freeregion_probe.lua`` before shipping.
- Trigger array spans `0x001BDFCD..0x001BE041` (sub-tables
  documented in ``addresses.py``). The merit shop ends at trigger
  920 (byte 0x001BE040 bit 0). Next free band starts at trigger
  921 (byte 0x001BE040 bit 1), runs through byte 0x001BE041 bits
  0..7 (= trigger 928..935). **DO NOT use byte 0x001BE042 or
  beyond — that's ``RAM_MERAMON_TUNNEL_DRIMOGEMON_STATE`` and
  setting bits there will corrupt the digging-tunnel state machine.**
  Realistic budget: ~15 triggers (921..935) before you'd need
  another sub-band.
- Bin-offset translation helper ``_slus_ram_to_bin_offset(ram_addr)``
  is sector-aware. Use it for any new RAM target.
- The merit shop's scan-loop bound was patched from `<0x80` to
  `<0x90` to include slots 128..143. To include new slots
  144..180 in regular-money-shop scans, the same kind of patch
  applies to each money shop's own scan loop (if they have an
  analogous bound).

### What's known about the regular money shops (open questions)

Per ``merit_shop.md`` §7, three or four ``jal 0x800C5240`` (giveItem)
callsites exist in vanilla SLUS that aren't the chest, recycle,
or merit shop:

- ``RAM 0x80108798``  — probably File City sub-shop A.
- ``RAM 0x8010896C``  — probably File City sub-shop B.
- ``RAM 0x80108B68``  — probably File City sub-shop C.
- ``RAM 0x8010C648``  — purpose unknown. Possibly Secret Shop.

These are HYPOTHESES, not verified. **Your first RE step is to
confirm.** The merit_shop.md §7 prediction is that each is a
``scan ITEM_PARA, filter by value > 0`` pattern (parallel to the
merit shop's ``filter by meritValue > 0`` at function 0x801072C4).
If the prediction holds, the patcher work is almost a direct clone
of the merit shop's — different scan-bound patch site, different
hijack callsite, same wrapper shape, just a different filter field.

The **Secret Shop** is in the Drimogemon Tunnel area (verified in
the standalone DW1 randomizer; an NPC hidden behind a route puzzle).
NPC identity + script + scan-function entry are unknown — you'll
need to RE them.

### Your task — suggested step shape

1. **RE step — confirm the regular-money-shop architecture.**
   - Disassemble around each of the four ``jal giveItem``
     callsites (``0x80108798, 0x8010896C, 0x80108B68, 0x8010C648``).
     Find each one's containing function entry (look upward for
     ``addiu r29, r29, ...`` prologue).
   - In each containing function, find the ITEM_PARA scan loop
     (look for ``lui rN, 0x800A; addiu rN, rN, 0xDBC8 + 0x14``
     reading the `value` field at offset 20 — note 0x800A/0xDBC8
     is the **post-Path-A** encoding; the vanilla disasm in
     ``references/DW1-Code/SLUS.asm`` still shows the OLD
     ``lui 0x8012; addiu 0x69F0`` since that .asm was generated
     before relocation. So grep for ``0x69F0`` in SLUS.asm — that
     resolves to vanilla ``ITEM_PARA + 0x14 = value`` field).
   - Find each scan loop's bound (``sltiu rN, rM, 0xLL`` immediate
     near the loop top). This is the target of your scan-bound
     patch for new slots.
   - Identify the NPC / script that opens each shop (search
     ``references/digimon_world_randomizer/script/DW1Script.txt``
     for ``callRoutine`` opcodes near each shop function's caller).
   - Document findings in ``docs/item_shop.md`` (you'll create this).

2. **RE step — find the Secret Shop.**
   - Likely associated with Drimogemon Tunnel NPC + a quest gate.
     Cross-reference standalone randomizer's docs at
     ``references/digimon_world_randomizer/`` (no LICENSE — study
     only, do not copy verbatim).
   - Confirm it uses the same money-shop architecture once located.
   - Documented findings in ``docs/item_shop.md``.

3. **Inventory each shop's vanilla items.**
   - Adapt ``tools/dw1_merit_inventory.py`` to scan ITEM_PARA for
     entries with ``value > 0`` (vs ``meritValue > 0`` for the
     merit shop). Filter by the scan-bound from step 1.
   - Each shop has a SPECIFIC scan range / filter rule (the merit
     shop scans ALL of ITEM_PARA filtering by meritValue; the regular
     shops probably ALSO scan all of ITEM_PARA filtering by value,
     and which items appear in *which* shop is engine-encoded
     elsewhere — find that selector mechanism too).
   - Output: tuple per shop, ``[(slot_id, name, value), ...]``.

4. **Allocate slot + trigger ranges.**
   - File City Normal Shop subshops + Secret Shop ≈ ~15-25 items.
     Pick slot ranges starting at 144 (e.g., 144..150 for shop A,
     151..157 for shop B, etc.).
   - Pick trigger ranges starting at 921 (next free after merit's
     920). Stay below byte 0x001BE042 (MERAMON_TUNNEL_DRIMOGEMON
     state).

5. **Implement the patcher** following ``item_para_relocation.md``'s
   "How to add a new shop using Path A" recipe:
   - Pick a new wrapper location in one of the catalogued free
     regions (e.g., ``0x800BA658``). Empirically verify with the
     freeregion probe.
   - Add a new ``reloc_item_para_slot_bin_offset(slot)`` helper
     to ``addresses.py`` for slots 144..180 (these write directly
     to NEW .bin offset, not OLD — see the doc's pitfall #6).
   - Per shop: new wrapper builder, jal hijack token, scan-bound
     patch, per-slot ITEM_PARA writes (name + value), per-slot
     AP description string, dispatch table entries.
   - New `MoneyShopLocations` option (or per-shop options).
   - New location IDs in ``69_058_xxx`` / ``69_059_xxx`` blocks.
   - Wire slot_data in ``world.py``.

6. **Tests.** Clone ``test/test_merit_shop_extended.py`` shape.
   50+ tests covering each shop's locations, triggers, wrapper
   bytecode (decode-verified), patcher tokens (option on + off).

### Constraints (locked, do not revisit)

- **Don't re-baseline on SydPatches.** v1 patches vanilla
  SLUS-01032 (SHA-1 verified). Re-baselining is multi-week work
  not in scope.
- **Don't break shipping shops.** Recycle + merit must keep
  working after your changes. Run the full ``pytest worlds/digimon_world``
  before and after. Currently 550 passing, 4 skipped.
- **Don't write data into vanilla code regions.** Use only
  ``item_para_relocation.md``'s catalogued free regions.
  Empirically validate any region you choose with the
  freeregion probe. **Cave1 at 0x800A0A50 is NOT free** —
  SydPatches lies about that one.
- **Don't trust hand-typed MIPS opcodes.** Always derive from
  ``(opcode << 26) | (rs << 21) | (rt << 16) | imm`` and verify
  by decoding back. The wrapper builders in addresses.py have
  decode-verify patterns at module load — clone that style.
- **Sector boundaries.** ``apply_tokens`` writes flat. Any token
  larger than ~2 KB risks crossing a sector. Either keep token
  writes small or use a procedure extension's
  ``write_user_data_bytes`` (sector-aware). The merit AP desc
  strings sector-crossing bug (merit_shop.md ITEM_PARA relocation
  notes 2026-05-13) is the canonical example of how this fails.
- **Don't use BizHawk's ``event.onmemorywrite`` /
  ``onmemoryexecute``.** They're unreliable across PSX cores
  (silently no-op under Nymashock). Canonical RE workflow:
  static disassembly hunt + Lua HUD probes + RAM snapshot diff.
  See ``dw1_re_workflow.md`` memory note.
- **Use the existing scan-finder script.** Don't re-invent —
  ``tools/dw1_scan_item_para_readers.py`` already enumerates
  ITEM_PARA-base readers. Generalize/duplicate it if needed (e.g.,
  for finding ``value``-field readers specifically).

### Existing v1 + Path A must keep working

- All 65 chest AP locations.
- All 46 recruit AP locations.
- Key item pickups (Old Fishrod / Mansion Key / Frig Key / Gear /
  Rain Plant / Blue Flute / Leomonstone / Amazing Rod).
- 10 vending machine AP locations (opt-in).
- 7 recycle shop AP locations (opt-in).
- 9 merit shop AP locations (opt-in).
- ITEM_PARA relocation procedure step (always-on).
- 24 SLUS reader-site patches (always-on).
- All 550 tests.

### Working state when you start

Branch: ``digimon-world-ps1``.
Latest tests: ``pytest worlds/digimon_world`` → 550 passed, 4 skipped.
Path A shipped and empirically validated.

To test end-to-end with a real seed:

```
python Generate.py
python MultiServer.py output/AP_*.zip --log_network &
python Launcher.py
# In Launcher: Open APDW1 patch → load BizHawk Nymashock core
```

Re-run the freeregion probe with your chosen wrapper region if you
go outside Cave6:

```
# In BizHawk Lua Console, with vanilla DW1 .bin loaded:
Tools > Lua Console > Open This Script > tools/dw1_freeregion_probe.lua
# Edit REGION_BASE_BARE and REGION_SIZE in the script first.
```
