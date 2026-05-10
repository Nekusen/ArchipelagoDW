"""Static RE helper: scan the DW1 (USA) .bin for MIPS code that
accesses the ``MERIT`` global at RAM ``0x80134FC4`` (kuseg-stripped:
``0x00134FC4``).

The Merit Shop (Volume Villa, ShogunGekomon) is data-driven from the
PSX engine — its purchase logic isn't in script bytecode anywhere
(verified by zero ``giveItem 117`` matches in DW1Script.txt). The
candidate way in is to find code that reads/writes the MERIT counter
and trace from there to the shop's purchase handler.

This script does the static side: rebuild the .bin's user-data stream
(stripping Mode2/2352 sector overhead — see addresses.py), then scan
for MIPS instructions targeting MERIT in two common addressing forms:

* **Absolute** — ``lui $rB, 0x8013`` followed within a small window
  by a load/store instruction with offset ``0x4FC4`` and base $rB.
* **$gp-relative** — load/store with rs=$gp (reg 28), offset
  ``0x9498`` (= MERIT - global_pointer = -0x6B68, sign-extended).
  ``global_pointer = 0x8013BB2C`` per SydPatches' SLUS_labels.asm.

Each hit is reported with:
* The MIPS instruction word and a basic decode (opcode mnemonic + regs).
* The user-data offset (suitable for translating back to a flat .bin
  offset via :func:`worlds.digimon_world.data.addresses._flat_to_user_data`).
* A windowed disassembly of nearby instructions (16 before / 16 after).

Usage::

    python -m worlds.digimon_world.tools.dw1_merit_re

The script reads ``Digimon World (USA).bin`` from the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BIN_PATH = Path(__file__).resolve().parents[3] / "Digimon World (USA).bin"

SECTOR_SIZE = 2352          # Mode2/2352
SECTOR_HEADER = 24          # 12 sync + 4 header + 8 sub-header
SECTOR_USER_DATA = 2048
SECTOR_TAIL = 280           # EDC + ECC

MERIT_RAM_ADDR = 0x80134FC4
GLOBAL_POINTER_RAM = 0x8013BB2C
KUSEG_MASK = 0x80000000

# offset 0x4FC4 within a 0x8013xxxx page accessed from a $rB loaded by lui.
ABS_LOAD_OFFSET = 0x4FC4

# offset (signed 16) from $gp = 0x8013BB2C to reach MERIT = 0x80134FC4.
GP_LOAD_OFFSET = (MERIT_RAM_ADDR - GLOBAL_POINTER_RAM) & 0xFFFF  # = 0x9498

# MIPS opcodes for loads (high 6 bits in byte 3 high-nibble subset).
LOAD_STORE_OPCODES: dict[int, str] = {
    0x20: "lb",
    0x21: "lh",
    0x22: "lwl",
    0x23: "lw",
    0x24: "lbu",
    0x25: "lhu",
    0x26: "lwr",
    0x28: "sb",
    0x29: "sh",
    0x2A: "swl",
    0x2B: "sw",
    0x2E: "swr",
}

REG_NAMES = (
    "$zero", "$at", "$v0", "$v1", "$a0", "$a1", "$a2", "$a3",
    "$t0", "$t1", "$t2", "$t3", "$t4", "$t5", "$t6", "$t7",
    "$s0", "$s1", "$s2", "$s3", "$s4", "$s5", "$s6", "$s7",
    "$t8", "$t9", "$k0", "$k1", "$gp", "$sp", "$fp", "$ra",
)


# ---------------------------------------------------------------------------
# .bin user-data stream
# ---------------------------------------------------------------------------

def build_user_data_stream(bin_bytes: bytes) -> tuple[bytes, list[int]]:
    """Reconstruct a contiguous user-data stream by stripping the
    24-byte sector headers and 280-byte EDC/ECC tails of a Mode2/2352
    image.

    Returns ``(user_data, sector_starts_in_flat)`` so callers can
    translate user-data offsets back to flat-.bin offsets.
    """

    sector_count, rem = divmod(len(bin_bytes), SECTOR_SIZE)
    if rem != 0:
        raise ValueError(
            f"BIN size 0x{len(bin_bytes):X} is not a multiple of 2352",
        )
    user_data_buf = bytearray(sector_count * SECTOR_USER_DATA)
    sector_flat_bases = [0] * sector_count
    for sector_idx in range(sector_count):
        flat_start = sector_idx * SECTOR_SIZE
        sector_flat_bases[sector_idx] = flat_start
        user_start = sector_idx * SECTOR_USER_DATA
        ud = bin_bytes[
            flat_start + SECTOR_HEADER : flat_start + SECTOR_HEADER + SECTOR_USER_DATA
        ]
        user_data_buf[user_start : user_start + SECTOR_USER_DATA] = ud
    return bytes(user_data_buf), sector_flat_bases


def user_data_to_flat(user_offset: int) -> int:
    """Translate a user-data stream offset back to a flat .bin offset."""
    sector_idx, in_sector = divmod(user_offset, SECTOR_USER_DATA)
    return sector_idx * SECTOR_SIZE + SECTOR_HEADER + in_sector


# ---------------------------------------------------------------------------
# MIPS decode (just enough to recognize what we need)
# ---------------------------------------------------------------------------

def decode_word(word: int) -> str:
    """Decode a 32-bit MIPS R3000 instruction word into a string. Best
    effort — only the load/store + lui forms relevant to this scan."""

    opcode = (word >> 26) & 0x3F
    rs = (word >> 21) & 0x1F
    rt = (word >> 16) & 0x1F
    imm = word & 0xFFFF
    sign_imm = imm if imm < 0x8000 else imm - 0x10000

    if opcode == 0x0F:  # lui
        return f"lui {REG_NAMES[rt]}, 0x{imm:04X}"
    if opcode in LOAD_STORE_OPCODES:
        return (
            f"{LOAD_STORE_OPCODES[opcode]} {REG_NAMES[rt]}, "
            f"{sign_imm:+#x}({REG_NAMES[rs]})"
        )
    if opcode == 0x09:  # addiu
        return f"addiu {REG_NAMES[rt]}, {REG_NAMES[rs]}, {sign_imm:+#x}"
    if opcode == 0x08:  # addi
        return f"addi {REG_NAMES[rt]}, {REG_NAMES[rs]}, {sign_imm:+#x}"
    if opcode == 0x0D:  # ori
        return f"ori {REG_NAMES[rt]}, {REG_NAMES[rs]}, 0x{imm:04X}"
    if opcode == 0x0A:  # slti
        return f"slti {REG_NAMES[rt]}, {REG_NAMES[rs]}, {sign_imm:+#x}"
    if opcode == 0x0B:  # sltiu
        return f"sltiu {REG_NAMES[rt]}, {REG_NAMES[rs]}, {sign_imm:+#x}"
    if opcode == 0x04:  # beq
        return f"beq {REG_NAMES[rs]}, {REG_NAMES[rt]}, {sign_imm * 4:+d}"
    if opcode == 0x05:  # bne
        return f"bne {REG_NAMES[rs]}, {REG_NAMES[rt]}, {sign_imm * 4:+d}"
    if opcode == 0x00:  # SPECIAL (nop, add, etc.)
        funct = word & 0x3F
        rd = (word >> 11) & 0x1F
        sa = (word >> 6) & 0x1F
        if word == 0:
            return "nop"
        if funct == 0x21:
            return f"addu {REG_NAMES[rd]}, {REG_NAMES[rs]}, {REG_NAMES[rt]}"
        if funct == 0x23:
            return f"subu {REG_NAMES[rd]}, {REG_NAMES[rs]}, {REG_NAMES[rt]}"
        if funct == 0x25:
            return f"or {REG_NAMES[rd]}, {REG_NAMES[rs]}, {REG_NAMES[rt]}"
        if funct == 0x08:
            return f"jr {REG_NAMES[rs]}"
        if funct == 0x09:
            return f"jalr {REG_NAMES[rs]}"
        return f"<special funct=0x{funct:02X} rs={rs} rt={rt} rd={rd} sa={sa}>"
    if opcode == 0x02:  # j
        target = (word & 0x03FFFFFF) << 2
        return f"j 0x{target:08X}"
    if opcode == 0x03:  # jal
        target = (word & 0x03FFFFFF) << 2
        return f"jal 0x{target:08X}"
    return f"<op=0x{opcode:02X} rs={rs} rt={rt} imm=0x{imm:04X}>"


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------

def find_lui_8013(user_data: bytes) -> list[int]:
    """All positions in the user-data stream where the 32-bit word is
    ``lui $rt, 0x8013`` for any rt 0..31. Returns positions in user-data
    coordinates, 4-byte aligned."""
    hits = []
    # Word pattern: 0x3C [rt-byte] 0x80 0x13. Little-endian: 13 80 [rt] 3C.
    n = len(user_data)
    for i in range(0, n - 3, 4):  # 4-byte aligned (instructions)
        if (
            user_data[i] == 0x13
            and user_data[i + 1] == 0x80
            and user_data[i + 2] <= 0x1F
            and user_data[i + 3] == 0x3C
        ):
            hits.append(i)
    return hits


def find_offset_use(
    user_data: bytes,
    around_pos: int,
    target_offset: int,
    base_reg: int | None = None,
    window_words: int = 8,
) -> list[tuple[int, int, str]]:
    """Within a small window around ``around_pos`` (in word-units before
    and after), find load/store instructions whose immediate offset
    matches ``target_offset``. Returns list of (pos, word, mnemonic).
    """

    n = len(user_data)
    out: list[tuple[int, int, str]] = []
    # Search a window forward — the lui+load pair is typically within a
    # few instructions of each other (often back-to-back, sometimes
    # separated by unrelated instructions due to load-delay slot or
    # interleaved scheduling).
    start = max(0, around_pos - window_words * 4)
    end = min(n - 3, around_pos + window_words * 4)
    for i in range(start, end + 1, 4):
        if i + 3 >= n:
            break
        word = int.from_bytes(user_data[i : i + 4], "little")
        opcode = (word >> 26) & 0x3F
        if opcode not in LOAD_STORE_OPCODES:
            continue
        rs = (word >> 21) & 0x1F
        imm = word & 0xFFFF
        if imm != target_offset:
            continue
        if base_reg is not None and rs != base_reg:
            continue
        mnem = decode_word(word)
        out.append((i, word, mnem))
    return out


def disassemble_window(user_data: bytes, center: int, before: int = 8, after: int = 16) -> list[str]:
    """Return a windowed disassembly of MIPS instructions around the
    given user-data offset (4-byte aligned). Useful for understanding
    the function context after we identify a hit."""

    out: list[str] = []
    n = len(user_data)
    aligned_center = center - (center % 4)
    start = max(0, aligned_center - before * 4)
    end = min(n - 3, aligned_center + after * 4)
    for i in range(start, end + 1, 4):
        if i + 3 >= n:
            break
        word = int.from_bytes(user_data[i : i + 4], "little")
        marker = "  >>" if i == aligned_center else "    "
        flat = user_data_to_flat(i)
        out.append(f"{marker} ud=0x{i:08X} flat=0x{flat:08X} word=0x{word:08X}  {decode_word(word)}")
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not BIN_PATH.exists():
        print(f"Cannot find .bin at {BIN_PATH}", file=sys.stderr)
        return 1

    print(f"Loading {BIN_PATH.name} ({BIN_PATH.stat().st_size:,} bytes)...")
    raw = BIN_PATH.read_bytes()
    user_data, _ = build_user_data_stream(raw)
    print(f"User-data stream: 0x{len(user_data):X} bytes ({len(user_data):,})")

    # ---- Pass 1: absolute lui-then-load pattern ----
    lui_hits = find_lui_8013(user_data)
    print(f"\nPass 1: found {len(lui_hits)} ``lui ?, 0x8013`` instructions")

    abs_pairs: list[tuple[int, int, int, int, str, str]] = []
    for lui_pos in lui_hits:
        lui_word = int.from_bytes(user_data[lui_pos : lui_pos + 4], "little")
        lui_rt = (lui_word >> 16) & 0x1F
        # Look for a subsequent load/store with offset 0x4FC4 and base = lui_rt
        # within a small window.
        uses = find_offset_use(
            user_data, lui_pos, ABS_LOAD_OFFSET, base_reg=lui_rt, window_words=8,
        )
        for use_pos, use_word, use_mnem in uses:
            abs_pairs.append((lui_pos, use_pos, lui_word, use_word, decode_word(lui_word), use_mnem))

    print(f"Pass 1: filtered to {len(abs_pairs)} lui+load_store pairs targeting MERIT")
    for lui_pos, use_pos, _lui_word, _use_word, lui_mnem, use_mnem in abs_pairs:
        flat_lui = user_data_to_flat(lui_pos)
        flat_use = user_data_to_flat(use_pos)
        print(
            f"  abs: ud lui@0x{lui_pos:08X} (flat 0x{flat_lui:08X})  "
            f"use@0x{use_pos:08X} (flat 0x{flat_use:08X})  "
            f"[{lui_mnem}] [{use_mnem}]"
        )

    # ---- Pass 2: $gp-relative ----
    print(f"\nPass 2: scanning for $gp-relative loads/stores at offset 0x{GP_LOAD_OFFSET:04X} (= MERIT - gp)")
    gp_hits: list[tuple[int, int, str]] = []
    n = len(user_data)
    for i in range(0, n - 3, 4):
        # Quick LE filter on imm bytes first
        if user_data[i] != (GP_LOAD_OFFSET & 0xFF) or user_data[i + 1] != ((GP_LOAD_OFFSET >> 8) & 0xFF):
            continue
        word = int.from_bytes(user_data[i : i + 4], "little")
        opcode = (word >> 26) & 0x3F
        if opcode not in LOAD_STORE_OPCODES:
            continue
        rs = (word >> 21) & 0x1F
        if rs != 28:  # $gp
            continue
        gp_hits.append((i, word, decode_word(word)))

    print(f"Pass 2: found {len(gp_hits)} $gp-relative MERIT accesses")
    for pos, _word, mnem in gp_hits:
        flat = user_data_to_flat(pos)
        print(f"  gp:  ud@0x{pos:08X} (flat 0x{flat:08X})  [{mnem}]")

    # ---- Per-hit disassembly windows for the most interesting candidates ----
    all_uses: list[int] = sorted({use_pos for _, use_pos, *_ in abs_pairs} | {pos for pos, *_ in gp_hits})
    print(f"\n=== Disassembly windows around {len(all_uses)} unique MERIT-access sites ===")
    for use_pos in all_uses:
        flat = user_data_to_flat(use_pos)
        print(f"\n----- MERIT access at user-data 0x{use_pos:08X} (flat 0x{flat:08X}) -----")
        for line in disassemble_window(user_data, use_pos, before=8, after=16):
            print(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
