"""
Build the recruit-visibility patch table from info.txt's MUST-CHANGE lists.

The standalone-randomizer's ``info.txt`` classifies every recruit-trigger
read in the BIN as either:
- **NO TOUCH** — wild-spawn, recruit cutscene, story progression, rumor
  dialog. Must NOT be patched (would break story flow / softlock).
- **MUST CHANGE** — city-visibility, shop NPC, plaza-hangin'-out poses.
  Safe to redirect from 200+X (vanilla cutscene-completion) → 720+X
  (AP-delivered) for our Plan A revised model.

This tool parses info.txt's MUST-CHANGE entries for every recruit that has
a block, verifies each BIN address contains the recruit's expected trigger
ID against the vanilla BIN, and emits the patch tuple list.

Recruits without info.txt blocks (Palmon, Greymon, Centarumon, Vegimon,
Birdramon, Angemon, Monzaemon, Megadramon, Seadramon, MetalGreymon,
Airdramon) are NOT covered here — they need separate strategies:
  - Palmon: existing 70-entry full-sweep (user-validated).
  - Birdramon, Angemon, Monzaemon, Vegimon: covered by
    ROM_GETTOPCITY_TRIGGER_PATCHES (C function).
  - Greymon, Centarumon: existing 1-entry-each in current table.
  - Megadramon, Seadramon, MetalGreymon, Airdramon: skip for now.

Usage:
    venv/Scripts/python.exe tools/generate_recruit_patches_from_infotxt.py
"""

from __future__ import annotations

import io
import re
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Recruit map — trigger ID per recruit name
# ---------------------------------------------------------------------------

RECRUIT_RAM_BITS = {
    "Agumon":       (0x001BDFE6, 3),  # excluded
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


def name_to_trigger(byte_addr: int, bit: int) -> int:
    return 200 + (byte_addr - 0x001BDFE6) * 8 + bit


# Some info.txt block names map to multi-word RECRUIT_RAM_BITS keys
INFO_NAME_TO_RECRUIT = {
    "Vegiemon": "Vegiemon",  # info.txt actually uses "Vegimon" sometimes; check
}


# ---------------------------------------------------------------------------
# Parse info.txt
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
INFO_FILE = REPO_ROOT / "references" / "digimon_world_randomizer" / "info.txt"
VANILLA_BIN = REPO_ROOT / "Digimon World (USA).bin"

BLOCK_HEADER_RE = re.compile(r"^\s+(\w+) triggers:")
SECTION_RE = re.compile(r"^\s+(NO TOUCH|MUST CHANGE)")
# Lines like "13FE503A    _192    10096   Elecmon intro"
# We only care about lines that start with an 8-hex-digit BIN address.
ADDR_LINE_RE = re.compile(r"^([0-9A-Fa-f]{8})\b")


def parse_info_txt() -> dict[str, list[tuple[int, str]]]:
    """Return mapping recruit_name → list of (BIN_addr, label) for MUST CHANGE."""
    result: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current_recruit: str | None = None
    current_section: str | None = None

    text = INFO_FILE.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        # Block header
        h = BLOCK_HEADER_RE.match(raw_line)
        if h:
            current_recruit = h.group(1)
            current_section = None
            continue
        # Section marker
        s = SECTION_RE.match(raw_line)
        if s:
            current_section = s.group(1)
            continue
        # Address line — only relevant if we're in MUST CHANGE
        if current_recruit and current_section == "MUST CHANGE":
            m = ADDR_LINE_RE.match(raw_line)
            if m:
                bin_addr = int(m.group(1), 16)
                # Capture the label (everything after the offset, best-effort)
                rest = raw_line[m.end():].strip()
                result[current_recruit].append((bin_addr, rest))

    return result


# ---------------------------------------------------------------------------
# Cross-verify and emit
# ---------------------------------------------------------------------------


def main() -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(f"Parsing {INFO_FILE.name}…")
    blocks = parse_info_txt()
    print(f"  Found {len(blocks)} recruit blocks with MUST CHANGE entries")

    # Normalize info.txt name → RECRUIT_RAM_BITS name (handle Vegimon/Vegiemon)
    name_aliases = {
        "Vegimon": "Vegiemon",  # info.txt uses both spellings
    }

    bin_data = VANILLA_BIN.read_bytes()
    print(f"  vanilla BIN: {len(bin_data):,} bytes")
    print()

    verified: list[tuple[int, int, int, str, str]] = []
    not_in_recruits: list[str] = []
    mismatches: list[tuple[str, int, int, str]] = []

    for info_name, sites in blocks.items():
        recruit_name = name_aliases.get(info_name, info_name)
        if recruit_name not in RECRUIT_RAM_BITS:
            not_in_recruits.append(info_name)
            continue
        byte_addr, bit = RECRUIT_RAM_BITS[recruit_name]
        trig = name_to_trigger(byte_addr, bit)
        if recruit_name == "Agumon":
            continue
        new_trig = trig + 520  # 720+X
        target_le = bytes([trig & 0xFF, (trig >> 8) & 0xFF])
        for bin_addr, label in sites:
            actual = bytes(bin_data[bin_addr:bin_addr + 2])
            if actual == target_le:
                verified.append((bin_addr, trig, new_trig, recruit_name, label))
            else:
                mismatches.append((recruit_name, bin_addr, trig, label))

    if not_in_recruits:
        print(f"info.txt names not in RECRUIT_RAM_BITS (skipped): {not_in_recruits}")
    if mismatches:
        print(f"\n{len(mismatches)} byte-mismatches:")
        for recruit, addr, trig, label in mismatches:
            actual = bin_data[addr:addr + 2].hex()
            print(f"  {recruit} (trig {trig}) at 0x{addr:08X}: actual {actual} vs expected {trig:04x} LE — {label}")

    print(f"\nVerified MUST-CHANGE entries: {len(verified)}")
    print()

    # Per-recruit summary
    by_recruit: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)
    for bin_addr, orig, new, name, label in verified:
        by_recruit[name].append((bin_addr, orig, new, label))

    print(f"{'recruit':<14} {'sites':>5}")
    print("-" * 25)
    for name in sorted(by_recruit, key=lambda n: -len(by_recruit[n])):
        print(f"{name:<14} {len(by_recruit[name]):>5}")

    # Emit final patch table sorted by BIN address
    out_path = REPO_ROOT / "tools" / "_recruit_patches_filtered.txt"
    verified.sort(key=lambda v: v[0])

    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"# Generated by tools/generate_recruit_patches_from_infotxt.py\n")
        f.write(f"# Total: {len(verified)} entries across {len(by_recruit)} recruits\n")
        f.write(f"# Source: info.txt MUST CHANGE classifications (city-visibility only,\n")
        f.write(f"# wild-spawn / story-flow gates explicitly excluded).\n")
        f.write("\n")
        f.write("ROM_FIELD_SPAWN_TRIGGER_PATCHES_FROM_INFOTXT: Final = (\n")
        recruit_order = list(RECRUIT_RAM_BITS.keys())
        for name in recruit_order:
            if name not in by_recruit:
                continue
            entries = by_recruit[name]
            f.write(f"    # ----- {name} ({len(entries)} sites) -----\n")
            for bin_addr, orig, new, label in entries:
                f.write(f"    (0x{bin_addr:08X}, {orig}, {new}),  # {label[:60]}\n")
        f.write(")\n")

    print()
    print(f"Patch table written to: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
