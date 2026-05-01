"""DW1 RAM snapshot diff analyzer.

Reads N snapshot files dumped by ``dw1_ram_snapshot.lua`` and classifies
each address by its change pattern across the snapshots, surfacing
candidates that look like story-event trigger bits.

A *sticky-flip* candidate is an address where the value changes once
(at some snapshot index) and then matches all subsequent snapshots —
e.g. with three snapshots, pattern ``ABB`` means the value changed
between snap 1 and snap 2 and stayed put through snap 3. The strongest
area-unlock signature is a sticky flip with a single-bit XOR delta,
landing inside one of the trigger bit-array gap regions.

Usage::

    python dw1_ram_diff.py snap_01.txt snap_02.txt snap_03.txt
    python dw1_ram_diff.py snap_*.txt --gaps-only
    python dw1_ram_diff.py snap_*.txt --pattern AABB

The default mode shows every sticky-flip pattern (one A-run followed by
one B-run); ``--gaps-only`` further narrows to trigger-array addresses
that aren't already accounted for by the recruit/chest/beaten subtables.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Trigger-array sub-table boundaries — keep in sync with the geometry
# block in worlds/digimon_world/data/addresses.py.
TRIGGER_BASE = 0x001BDFCD
TRIGGER_END = 0x001BE040
RECRUIT_RANGE = (0x001BDFE6, 0x001BDFED)
CHEST_RANGE = (0x001BE01E, 0x001BE026)
BEATEN_RANGE = (0x001BE027, 0x001BE02E)

LINE_RE = re.compile(r"^0x([0-9A-Fa-f]+):\s+([0-9A-F ]+)\s+\|\|")


def parse_snapshot(path: Path) -> dict[int, int]:
    out: dict[int, int] = {}
    for line in path.read_text().splitlines():
        m = LINE_RE.match(line)
        if not m:
            continue
        base = int(m.group(1), 16)
        for i, hx in enumerate(m.group(2).split()):
            out[base + i] = int(hx, 16)
    return out


def label_pattern(values: list[int]) -> str:
    seen: dict[int, str] = {}
    out: list[str] = []
    next_ch = ord("A")
    for v in values:
        if v not in seen:
            seen[v] = chr(next_ch)
            next_ch += 1
        out.append(seen[v])
    return "".join(out)


def is_sticky_flip(pattern: str) -> bool:
    """Return True for patterns like A...AB...B (one transition, then sticky)."""
    if set(pattern) != {"A", "B"}:
        return False
    first_b = pattern.index("B")
    return all(c == "A" for c in pattern[:first_b]) and all(c == "B" for c in pattern[first_b:])


def subtable(addr: int) -> str | None:
    if RECRUIT_RANGE[0] <= addr <= RECRUIT_RANGE[1]:
        return "recruit"
    if CHEST_RANGE[0] <= addr <= CHEST_RANGE[1]:
        return "chest"
    if BEATEN_RANGE[0] <= addr <= BEATEN_RANGE[1]:
        return "beaten"
    return None


def in_trigger_array(addr: int) -> bool:
    return TRIGGER_BASE <= addr <= TRIGGER_END


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("snapshots", nargs="+", type=Path, help="snapshot files (>= 2)")
    ap.add_argument("--pattern", default=None,
                    help="filter to one specific pattern label (e.g. ABB, AAABB)")
    ap.add_argument("--gaps-only", action="store_true",
                    help="restrict to trigger-array addresses NOT in any known subtable")
    ap.add_argument("--all-patterns", action="store_true",
                    help="show every changing pattern, not just sticky-flip ones")
    args = ap.parse_args()

    if len(args.snapshots) < 2:
        ap.error("need at least 2 snapshot files")

    snaps = [parse_snapshot(p) for p in args.snapshots]
    addrs = sorted(snaps[0].keys())
    print(f"# loaded {len(snaps)} snapshots, {len(addrs)} addresses")
    for i, p in enumerate(args.snapshots, 1):
        print(f"#   snap {i}: {p.name}")
    print()

    by_pattern: dict[str, list[tuple[int, list[int]]]] = {}
    for a in addrs:
        vals = [s[a] for s in snaps]
        by_pattern.setdefault(label_pattern(vals), []).append((a, vals))

    print("=== Pattern frequency ===")
    for pat, lst in sorted(by_pattern.items(), key=lambda kv: -len(kv[1])):
        print(f"  {pat}: {len(lst):>5}")
    print()

    if args.pattern:
        target_patterns = [args.pattern]
    elif args.all_patterns:
        target_patterns = sorted(p for p in by_pattern if len(set(p)) > 1)
    else:
        target_patterns = sorted(p for p in by_pattern if is_sticky_flip(p))

    if not target_patterns:
        print("no matching patterns — try --all-patterns to widen")
        return 0

    label = "all changing patterns" if args.all_patterns else "sticky-flip patterns"
    if args.pattern:
        label = f"pattern {args.pattern}"
    suffix = " (gap-only)" if args.gaps_only else ""
    print(f"=== Candidates ({label}{suffix}) ===\n")

    for pat in target_patterns:
        rows = by_pattern.get(pat, [])
        # Apply gaps-only filter
        if args.gaps_only:
            rows = [
                r for r in rows
                if in_trigger_array(r[0]) and subtable(r[0]) is None
            ]
        if not rows:
            continue
        print(f"--- pattern {pat} ({len(rows)}) ---")
        for addr, vals in rows:
            tbl = subtable(addr)
            in_trig = in_trigger_array(addr)
            xor = vals[0] ^ vals[-1]
            nbits = bin(xor).count("1")
            tags = []
            if in_trig:
                tags.append(f"in {tbl}-table" if tbl else "trigger-array GAP")
            else:
                tags.append("outside trigger array")
            if nbits == 1:
                bit = (xor.bit_length() - 1)
                tags.append(f"1 bit (bit {bit}, mask 0x{xor:02X})")
            else:
                tags.append(f"{nbits} bits")
            vals_str = " -> ".join(f"{v:02X}" for v in vals)
            print(f"  0x{addr:06X}: {vals_str}   [{', '.join(tags)}]")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
