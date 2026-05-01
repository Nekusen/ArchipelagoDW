"""
Comprehensive enumeration of recruit-visibility patches for DW1.

For every recruit trigger ID 200+X (X = 0..63), find every `if trigger(N)`
read in DW1Script.txt, compute its BIN offset (handling multi-trigger
compounds where N isn't at position 0), verify the bytes match against the
vanilla BIN, and emit a Python tuple list ready to paste into
``addresses.py:ROM_FIELD_SPAWN_TRIGGER_PATCHES``.

Excludes:
- ``setTrigger N`` lines (vanilla owns the cutscene write).
- Agumon (trigger 203 — pinned to 1 by the client; never patched).
- Triggers outside 200..263 (not recruit-block).

Usage:
    venv/Scripts/python.exe tools/generate_recruit_visibility_patches.py
"""

from __future__ import annotations

import io
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# BIN math (Mode2/2352 sectors, script region starts sector 142589 user-data
# position 4)
# ---------------------------------------------------------------------------

SECTOR_SIZE = 0x930
SECTOR_HEADER = 0x18
USER_DATA = 0x800
SCRIPT_REGION_BASE_SECTOR = 142589
SCRIPT_REGION_BASE_USERDATA_POS = 4


def script_byte_to_flat_bin(region_offset: int) -> int:
    """Convert a script-region byte offset to a flat BIN file offset."""
    pos = SCRIPT_REGION_BASE_USERDATA_POS + region_offset
    sa, pw = divmod(pos, USER_DATA)
    sector = SCRIPT_REGION_BASE_SECTOR + sa
    return sector * SECTOR_SIZE + SECTOR_HEADER + pw


# ---------------------------------------------------------------------------
# Recruit map — trigger ID per recruit name (excluding Agumon)
# ---------------------------------------------------------------------------

RECRUIT_RAM_BITS = {
    "Agumon":       (0x001BDFE6, 3),  # excluded — starter
    "Betamon":      (0x001BDFE6, 4),
    "Greymon":      (0x001BDFE6, 5),
    "Devimon":      (0x001BDFE6, 6),
    "Airdramon":    (0x001BDFE6, 7),
    "Tyrannomon":   (0x001BDFE7, 0),
    "Meramon":      (0x001BDFE7, 1),
    "Seadramon":    (0x001BDFE7, 2),
    "Numemon":      (0x001BDFE7, 3),
    "MetalGreymon": (0x001BDFE7, 4),
    "Mamemon":      (0x001BDFE7, 5),
    "Monzaemon":    (0x001BDFE7, 6),
    "Gabumon":      (0x001BDFE8, 1),
    "Elecmon":      (0x001BDFE8, 2),
    "Kabuterimon":  (0x001BDFE8, 3),
    "Angemon":      (0x001BDFE8, 4),
    "Birdramon":    (0x001BDFE8, 5),
    "Garurumon":    (0x001BDFE8, 6),
    "Frigimon":     (0x001BDFE8, 7),
    "Whamon":       (0x001BDFE9, 0),
    "Vegiemon":     (0x001BDFE9, 1),
    "SkullGreymon": (0x001BDFE9, 2),
    "MetalMamemon": (0x001BDFE9, 3),
    "Vademon":      (0x001BDFE9, 4),
    "Patamon":      (0x001BDFE9, 7),
    "Kunemon":      (0x001BDFEA, 0),
    "Unimon":       (0x001BDFEA, 1),
    "Ogremon":      (0x001BDFEA, 2),
    "Shellmon":     (0x001BDFEA, 3),
    "Centarumon":   (0x001BDFEA, 4),
    "Bakemon":      (0x001BDFEA, 5),
    "Drimogemon":   (0x001BDFEA, 6),
    "Sukamon":      (0x001BDFEA, 7),
    "Andromon":     (0x001BDFEB, 0),
    "Giromon":      (0x001BDFEB, 1),
    "Etemon":       (0x001BDFEB, 2),
    "Biyomon":      (0x001BDFEB, 5),
    "Palmon":       (0x001BDFEB, 6),
    "Monochromon":  (0x001BDFEB, 7),
    "Leomon":       (0x001BDFEC, 0),
    "Coelamon":     (0x001BDFEC, 1),
    "Kokatorimon":  (0x001BDFEC, 2),
    "Kuwagamon":    (0x001BDFEC, 3),
    "Mojyamon":     (0x001BDFEC, 4),
    "Nanimon":      (0x001BDFEC, 5),
    "Megadramon":   (0x001BDFEC, 6),
    "Piximon":      (0x001BDFEC, 7),
    "Digitamamon":  (0x001BDFED, 0),
    "Penguinmon":   (0x001BDFED, 1),
    "Ninjamon":     (0x001BDFED, 2),
}

EXCLUDED = {"Agumon"}  # starter — never patched


def name_to_trigger(byte_addr: int, bit: int) -> int:
    """RECRUIT byte/bit → trigger ID 200+X."""
    base_byte = 0x001BDFE6
    return 200 + (byte_addr - base_byte) * 8 + bit


# ---------------------------------------------------------------------------
# Parse DW1Script.txt
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_FILE = REPO_ROOT / "references" / "digimon_world_randomizer" / "script" / "DW1Script.txt"
VANILLA_BIN = REPO_ROOT / "Digimon World (USA).bin"

HEADER_RE = re.compile(r"== Script ID (\d+) ==\s+([0-9a-fA-F]+)")
LINE_RE = re.compile(r"^(\d{6})\s+(.*)$")
TRIGGER_RE = re.compile(r"trigger\((\d+)\)")
# Each "primitive" call in an IF compound takes one 4-byte slot.
# Observed in DW1Script.txt: trigger(N) and pstat(M).
PRIMITIVE_RE = re.compile(r"(trigger|pstat)\((\d+)\)")


def parse_script_file() -> tuple[dict[int, int], list[tuple[int, int, int, str]]]:
    """Return (script_bases, trigger_lines).

    trigger_lines is a list of (line_no, script_id, script_byte_offset, text)
    for every line that contains at least one ``trigger(N)`` reference (and is
    not a setTrigger).
    """
    script_bases: dict[int, int] = {}
    trigger_lines: list[tuple[int, int, int, str]] = []
    current_script: int | None = None

    with SCRIPT_FILE.open("r", encoding="utf-8", errors="replace") as f:
        for line_no, raw in enumerate(f, start=1):
            h = HEADER_RE.match(raw)
            if h:
                current_script = int(h.group(1))
                script_bases[current_script] = int(h.group(2), 16)
                continue
            m = LINE_RE.match(raw)
            if not m:
                continue
            text = m.group(2).rstrip()
            if "setTrigger" in text:
                continue
            if "trigger(" not in text:
                continue
            offset = int(m.group(1))
            trigger_lines.append((line_no, current_script, offset, text))

    return script_bases, trigger_lines


# ---------------------------------------------------------------------------
# Per-recruit enumeration
# ---------------------------------------------------------------------------


def enumerate_for_trigger(
    target_id: int,
    script_bases: dict[int, int],
    trigger_lines: list[tuple[int, int, int, str]],
    bin_data: bytes,
) -> tuple[list[tuple[int, int, int]], list[tuple[int, int, int, str]]]:
    """Find every patch site for one recruit trigger ID.

    Returns (verified_sites, mismatches):
      - verified_sites: list of (bin_offset, line_no, script_id) ready to patch
      - mismatches: list of (line_no, script_id, computed_bin_offset, text) that
        didn't match the expected ``<id_LE>`` 2 bytes
    """
    target_le = bytes([target_id & 0xFF, (target_id >> 8) & 0xFF])
    verified: list[tuple[int, int, int]] = []
    mismatches: list[tuple[int, int, int, str]] = []

    for line_no, script_id, off, text in trigger_lines:
        if script_id is None or script_id not in script_bases:
            continue
        # Find every primitive (trigger/pstat) in source order. Each takes
        # one 4-byte slot in the compound. Locate the slot of OUR target
        # ``trigger(target_id)`` reference.
        primitives = [(kind, int(arg)) for kind, arg in PRIMITIVE_RE.findall(text)]
        try:
            position = primitives.index(("trigger", target_id))
        except ValueError:
            continue
        base = script_bases[script_id]
        # Add the slot offset in *script-region space* (not BIN space) so the
        # helper handles sector boundaries — Mode2/2352 has 304 bytes of
        # EDC/header overhead between user-data regions, and adding 4 directly
        # to a BIN address spanning that boundary would land in EDC.
        region_off = base + off + 4 * position
        bin_addr = script_byte_to_flat_bin(region_off)
        actual = bytes(bin_data[bin_addr:bin_addr + 2])
        if actual == target_le:
            verified.append((bin_addr, line_no, script_id))
        else:
            mismatches.append((line_no, script_id, bin_addr, text))

    return verified, mismatches


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    print("Loading DW1Script.txt and vanilla BIN…")
    script_bases, trigger_lines = parse_script_file()
    print(f"  {len(script_bases)} script headers, {len(trigger_lines)} trigger lines")

    bin_data = VANILLA_BIN.read_bytes()
    print(f"  vanilla BIN: {len(bin_data):,} bytes")
    print()

    # Per-recruit summary
    all_entries: list[tuple[int, int, int, str]] = []  # (bin, orig, redirected, name)
    grand_mismatches: list[tuple[str, int, int, int, str]] = []

    print(f"{'recruit':<14} {'trig':>4}  {'sites':>5}  {'mismatches':>10}")
    print("-" * 50)
    for name, (byte_addr, bit) in RECRUIT_RAM_BITS.items():
        if name in EXCLUDED:
            continue
        trig = name_to_trigger(byte_addr, bit)
        verified, mismatches = enumerate_for_trigger(trig, script_bases, trigger_lines, bin_data)
        new_trig = trig + 520  # 720+X = 200+X + 520
        for bin_addr, line_no, script_id in verified:
            all_entries.append((bin_addr, trig, new_trig, name))
        if mismatches:
            for ln, scr, ba, txt in mismatches:
                grand_mismatches.append((name, ln, scr, ba, txt))
        print(f"{name:<14} {trig:>4}  {len(verified):>5}  {len(mismatches):>10}")

    print()
    print(f"TOTAL verified entries: {len(all_entries)}")
    print(f"TOTAL mismatches: {len(grand_mismatches)}")
    if grand_mismatches:
        print("\nMismatches:")
        for name, ln, scr, ba, txt in grand_mismatches:
            print(f"  {name}: L{ln} script {scr} bin 0x{ba:08X}  {txt[:60]}")

    # Sort by BIN address for the final patch table
    all_entries.sort(key=lambda e: e[0])

    out_path = REPO_ROOT / "tools" / "_recruit_visibility_patches.txt"
    with out_path.open("w", encoding="utf-8") as f:
        f.write("# Generated by tools/generate_recruit_visibility_patches.py\n")
        f.write(f"# Total: {len(all_entries)} entries across {len(RECRUIT_RAM_BITS) - len(EXCLUDED)} recruits\n")
        f.write("\n")
        f.write("ROM_FIELD_SPAWN_TRIGGER_PATCHES: Final = (\n")
        # Group by recruit for readability
        by_recruit: dict[str, list[tuple[int, int, int]]] = defaultdict(list)
        for bin_addr, orig, new, name in all_entries:
            by_recruit[name].append((bin_addr, orig, new))
        recruit_order = list(RECRUIT_RAM_BITS.keys())
        for name in recruit_order:
            if name in EXCLUDED or name not in by_recruit:
                continue
            entries = by_recruit[name]
            f.write(f"    # ----- {name} ({len(entries)} sites) -----\n")
            for bin_addr, orig, new in entries:
                f.write(f"    (0x{bin_addr:08X}, {orig}, {new}),\n")
        f.write(")\n")

    print()
    print(f"Patch table written to: {out_path}")
    print(f"Review then paste into worlds/digimon_world/data/addresses.py")

    # Per-recruit count summary table
    print()
    print("Per-recruit site counts:")
    for name in recruit_order:
        if name in EXCLUDED:
            continue
        cnt = len(by_recruit.get(name, []))
        print(f"  {name:<14} {cnt:>4}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
