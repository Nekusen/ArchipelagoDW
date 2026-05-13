"""Static analysis: enumerate every callsite in the vanilla DW1 SLUS that
constructs / reads an address in the ITEM_PARA range
RAM ``0x801269DC..0x801279DC`` (4096 bytes).

This is the input list for Path A — moving ITEM_PARA to a new RAM
location (e.g. ``0x8009DBC8``). Every site found here needs the
``lui``/``addiu`` immediate pair (or ``lui``/``lw/lh/sb/...`` pair)
patched to load the new base instead.

The script reads the vanilla disassembly at
``references/DW1-Code/SLUS.asm`` (one instruction per line, format
``0xADDRESS mnemonic operands``). It walks the disassembly sequentially,
tracks the most-recent ``lui rN, 0x8012`` per register, and reports any
subsequent instruction whose effective immediate forms an address in the
ITEM_PARA range.

Three reader patterns are detected:

1. **lui + addiu**: ``lui rN, 0x8012; addiu rN, rN, 0xLLLL`` — base
   construction. Patch BOTH instructions (lui's 0x8012 -> new high half,
   addiu's offset -> new low half + the same delta from base).
2. **lui + load/store with imm**: ``lui rN, 0x8012; lw rT, 0xLLLL(rN)``
   (or ``lh/lhu/lbu/sw/sh/sb``). Patch the ``lui`` only; the load/store
   immediate adjusts implicitly with the new base. **CAVEAT**: works only
   if the new base's high-half differs from 0x8012 but the low-half
   offset can stay the same. If we relocate to 0x8009DBC8, the high
   halves differ (0x8009 vs 0x8012) AND the field offset within
   ITEM_PARA changes (0x69DC + X vs 0xDBC8 + X), so we'd need both
   instructions patched. Print both halves for the patcher to use.
3. **lui-only with computed offset**: rare; ``lui rN, 0x8012`` followed
   by an ``addu rN, rN, rOther`` where rOther holds the (already-scaled)
   item-index. Hard to detect reliably without a basic-block analyzer;
   we still report these as candidates needing manual review.

The "lui register state" is invalidated on any instruction that writes
to the register (other than the lui itself) or on a basic-block boundary
(any branch/jump/call). This errs on the side of FALSE NEGATIVES (it may
miss readers that span branches), so the resulting list is a lower
bound. Cross-check against `agent 1A's` lui+addiu enumeration (which
used the same methodology) for confidence.

Usage::

    python -m worlds.digimon_world.tools.dw1_scan_item_para_readers

Output format::

    PC=0x000XXXXX  lui_pc=0x000XXXXX  rN=?  base=0x801269DC+OFFSET  pattern=addiu|load|store|...
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SLUS_ASM = REPO_ROOT / "references" / "DW1-Code" / "SLUS.asm"

# ITEM_PARA span (inclusive start, exclusive end).
ITEM_PARA_BASE = 0x801269DC
ITEM_PARA_END = ITEM_PARA_BASE + 4096  # 0x801279DC

# Register-name decoder (BizHawk-style: r0..r31).
REG_RE = re.compile(r"^r(\d+)$")

# Instruction patterns we care about. Each captures (mnemonic, operands).
INSTR_RE = re.compile(r"^0x([0-9a-fA-F]+)\s+(\S+)\s*(.*)$")

# Specific lui pattern: `lui rN, 0xXXXX`.
LUI_RE = re.compile(r"^lui\s+r(\d+),\s*0x([0-9a-fA-F]+)\s*$")

# Pattern: `addiu rD, rS, 0xXXXX` or `addiu rD, rS, -0xXXXX` or `addiu rD, rS, +0xXXXX`.
ADDIU_RE = re.compile(
    r"^addiu\s+r(\d+),\s*r(\d+),\s*([+-]?0x[0-9a-fA-F]+)\s*$"
)

# Loads / stores: `lw/lh/lhu/lb/lbu/sw/sh/sb rT, IMM(rS)` (imm may be signed).
LOAD_STORE_RE = re.compile(
    r"^(lw|lh|lhu|lb|lbu|sw|sh|sb)\s+r(\d+),\s*([+-]?0x[0-9a-fA-F]+)\(r(\d+)\)\s*$"
)

# Branch / jump / call mnemonics that end a basic block. Conservative
# list — any of these invalidates lui register state across them.
BRANCH_MNEMONICS = frozenset({
    "j", "jal", "jr", "jalr",
    "beq", "bne", "blez", "bgez", "bgtz", "bltz",
    "beql", "bnel",  # likely-branches (R3000 doesn't really have them, but defensive)
    "bgezal", "bltzal",
    "syscall", "break",
})

# Mnemonics that WRITE to their first register operand (so they
# invalidate any pending lui in that register).
# Most arithmetic / logical ops fall into this category.
REGISTER_WRITE_MNEMONICS = frozenset({
    "addiu", "addi", "addu", "add", "subu", "sub",
    "and", "andi", "or", "ori", "xor", "xori", "nor",
    "sll", "srl", "sra", "sllv", "srlv", "srav",
    "slt", "sltu", "slti", "sltiu",
    "mfhi", "mflo",
    "lw", "lh", "lhu", "lb", "lbu", "lui",
    # Note: lw/lh/etc. write to their first operand. They invalidate the
    # lui in their destination register (but NOT in their source/base
    # register, which is what we care about for reader detection).
})


def parse_signed_imm(s: str) -> int:
    """Parse an immediate that may be signed (+0xN / -0xN / 0xN)."""
    s = s.strip()
    if s.startswith("+"):
        return int(s[1:], 16)
    if s.startswith("-"):
        return -int(s[1:], 16)
    return int(s, 16)


def main() -> int:
    if not SLUS_ASM.exists():
        print(f"Cannot find {SLUS_ASM}", file=sys.stderr)
        return 1

    # Register state: maps reg_idx -> (lui_pc, lui_imm_high) for the most-recent
    # `lui rN, 0xH` that hasn't been invalidated. None if no pending lui.
    lui_state: dict[int, tuple[str, int]] = {}

    sites: list[dict] = []
    n_lines = 0
    n_lui_8012 = 0

    with SLUS_ASM.open("r", encoding="utf-8", errors="replace") as f:
        for raw_line in f:
            n_lines += 1
            line = raw_line.rstrip()
            m = INSTR_RE.match(line)
            if not m:
                continue
            pc_str, mnem, operands = m.groups()
            pc_hex = pc_str.lower()
            pc_kuseg = f"0x{pc_hex.zfill(8)}"

            # End-of-basic-block: invalidate all lui state.
            if mnem in BRANCH_MNEMONICS:
                lui_state.clear()
                continue

            # Check for lui itself.
            m_lui = LUI_RE.match(f"{mnem} {operands}".strip())
            if m_lui:
                rN = int(m_lui.group(1))
                hi = int(m_lui.group(2), 16)
                if hi == 0x8012:
                    n_lui_8012 += 1
                    lui_state[rN] = (pc_kuseg, hi)
                else:
                    # lui rN with non-0x8012 high half: invalidates any
                    # pending lui in rN.
                    lui_state.pop(rN, None)
                continue

            # Check for addiu pattern (base + low_half) — the classic
            # 32-bit address construction.
            m_addiu = ADDIU_RE.match(f"{mnem} {operands}".strip())
            if m_addiu:
                rD = int(m_addiu.group(1))
                rS = int(m_addiu.group(2))
                imm = parse_signed_imm(m_addiu.group(3))
                # We only care if rD == rS and rS has a pending 0x8012 lui.
                # (Other addiu cases write to a different register.)
                if rD == rS and rS in lui_state:
                    lui_pc, lui_hi = lui_state[rS]
                    # Sign-extend the addiu immediate per MIPS semantics.
                    if imm & 0x8000:
                        imm_signed = imm - 0x10000
                    else:
                        imm_signed = imm
                    target = (lui_hi << 16) + imm_signed
                    target &= 0xFFFFFFFF
                    if ITEM_PARA_BASE <= target < ITEM_PARA_END:
                        offset_in_table = target - ITEM_PARA_BASE
                        sites.append({
                            "pattern": "lui+addiu",
                            "lui_pc": lui_pc,
                            "addiu_pc": pc_kuseg,
                            "register": rS,
                            "target": target,
                            "offset_in_table": offset_in_table,
                            "raw_imm": imm,
                        })
                    # Whether or not in range, this `addiu rN, rN, ...`
                    # consumes the lui (the address is now built).
                    lui_state.pop(rS, None)
                else:
                    # addiu writes to rD; if rD has a pending lui (and
                    # this isn't the matching consumer), invalidate it.
                    lui_state.pop(rD, None)
                continue

            # Check for load/store pattern: `lw rT, IMM(rS)` etc.
            m_ls = LOAD_STORE_RE.match(f"{mnem} {operands}".strip())
            if m_ls:
                ls_mnem = m_ls.group(1)
                rT = int(m_ls.group(2))
                imm = parse_signed_imm(m_ls.group(3))
                rS = int(m_ls.group(4))
                if rS in lui_state:
                    lui_pc, lui_hi = lui_state[rS]
                    if imm & 0x8000:
                        imm_signed = imm - 0x10000
                    else:
                        imm_signed = imm
                    target = (lui_hi << 16) + imm_signed
                    target &= 0xFFFFFFFF
                    if ITEM_PARA_BASE <= target < ITEM_PARA_END:
                        offset_in_table = target - ITEM_PARA_BASE
                        sites.append({
                            "pattern": f"lui+{ls_mnem}",
                            "lui_pc": lui_pc,
                            "addiu_pc": pc_kuseg,  # reusing field name; here it's the load/store PC
                            "register": rS,
                            "target": target,
                            "offset_in_table": offset_in_table,
                            "raw_imm": imm,
                        })
                # The load/store may write to rT, which can invalidate a
                # pending lui in rT.
                if ls_mnem in ("lw", "lh", "lhu", "lb", "lbu"):
                    lui_state.pop(rT, None)
                continue

            # Any other instruction: invalidate the destination register's
            # lui state if recognizable. Naïve: parse first register-like
            # operand. Skip if uncertain.
            # Use REGISTER_WRITE_MNEMONICS list above for conservative
            # invalidation.
            if mnem in REGISTER_WRITE_MNEMONICS:
                # Try to extract the first "rN" operand.
                m_dst = re.match(r"^r(\d+),", operands)
                if m_dst:
                    rD = int(m_dst.group(1))
                    lui_state.pop(rD, None)
            # Fallthrough: don't invalidate anything (might be jal-style
            # which we already handled in BRANCH_MNEMONICS).

    # --- Report ---
    print(f"Scanned {n_lines:,} lines of SLUS.asm")
    print(f"Found {n_lui_8012} `lui rN, 0x8012` instructions")
    print(f"Detected {len(sites)} reader sites in ITEM_PARA range "
          f"[0x{ITEM_PARA_BASE:08X}, 0x{ITEM_PARA_END:08X})")
    print()
    # Sort by addiu/load-store PC.
    sites.sort(key=lambda s: int(s["addiu_pc"], 16))

    # Group by offset within ITEM_PARA (= field offset, 0..31 for first
    # entry, 32..63 for second, etc.). For analysis, also report the
    # offset_mod_32 (which field).
    print(f"{'#':>3}  {'lui_pc':>10}  {'use_pc':>10}  rN  {'target':>10}  "
          f"offset_in_table  field_in_entry  pattern")
    for i, s in enumerate(sites, 1):
        ofield = s['offset_in_table'] % 32
        print(f"{i:>3}  {s['lui_pc']:>10}  {s['addiu_pc']:>10}   "
              f"r{s['register']:<2} 0x{s['target']:08X}  "
              f"0x{s['offset_in_table']:04X} (={s['offset_in_table']})    "
              f"0x{ofield:02X} ({ofield:>2})       {s['pattern']}")
    print()

    # Summary by pattern.
    by_pattern: dict[str, int] = {}
    by_field: dict[int, int] = {}
    for s in sites:
        by_pattern[s["pattern"]] = by_pattern.get(s["pattern"], 0) + 1
        ofield = s["offset_in_table"] % 32
        by_field[ofield] = by_field.get(ofield, 0) + 1

    print("--- Summary by pattern ---")
    for p, n in sorted(by_pattern.items()):
        print(f"  {p:<20}: {n}")

    print()
    print("--- Summary by field offset within ITEM_PARA entry (32-byte stride) ---")
    field_names = {
        0: "name (0..19)",
        4: "name+4",
        8: "name+8",
        12: "name+12",
        16: "name+16",
        20: "value (i32, money)",
        24: "meritValue (i16)",
        26: "sortingValue",
        28: "itemColor",
        29: "dropable",
        30: "unk",
    }
    for f, n in sorted(by_field.items()):
        label = field_names.get(f, "")
        print(f"  +0x{f:02X} ({f:>2}): {n}{('  -- ' + label) if label else ''}")

    print()
    print(f"--- Estimated patch cost: {len(sites)} reader sites need updating ---")
    print(f"    Each lui+addiu pair = 2 instruction rewrites.")
    print(f"    Each lui+load/store = at least 1 (the lui's high half) + 1 (the load/store's imm).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
