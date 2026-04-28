# ruff: noqa: T201
"""Diff-pair adjacent snapshots from ``tools/ram_logger.lua`` output.

Usage::

    python tools/parse_ram_log.py <path-to-dw1_ram_log.txt>

Each snapshot in the input file is one block of 16-byte rows preceded by
a ``=== MARKER NNN at frame N ===`` line. The parser pairs every adjacent
``(prev, curr)`` block and prints the addresses whose bytes changed,
including bit-level decomposition for single-bit flips.

Output sample::

    --- DIFF: MARKER 001 -> MARKER 002 (frames 1234 -> 5678) ---
      0x001BDFE6: 0x00 -> 0x08  (bit 3 set)
      0x001BE032: 0x00 -> 0x01  (byte +1)

Use this against a "before X / after X" marker pair to confirm the
RAM bit DW1 actually flips when you trigger event X. Cross-walk against
the candidate addresses in worlds/digimon_world/data/addresses.py to
either confirm DWAP's data or replace it with verified offsets.
"""

from __future__ import annotations

import argparse
import itertools
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_MARKER_RE = re.compile(r"^=== (MARKER \d+) at frame (\d+) ===\s*$")
_ROW_RE = re.compile(r"^0x([0-9A-Fa-f]+):\s+((?:[0-9A-Fa-f]{2}\s*)+)\s*$")


@dataclass
class Snapshot:
    label: str
    frame: int
    bytes_by_addr: dict[int, int]  # absolute address -> byte


def parse_log(path: Path) -> list[Snapshot]:
    snapshots: list[Snapshot] = []
    current: Snapshot | None = None
    for line_no, raw_line in enumerate(path.read_text().splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        marker_match = _MARKER_RE.match(line)
        if marker_match:
            if current is not None:
                snapshots.append(current)
            current = Snapshot(
                label=marker_match.group(1),
                frame=int(marker_match.group(2)),
                bytes_by_addr={},
            )
            continue
        row_match = _ROW_RE.match(line)
        if row_match:
            if current is None:
                raise ValueError(
                    f"line {line_no}: data row outside any MARKER block: {raw_line!r}"
                )
            base_addr = int(row_match.group(1), 16)
            bytes_str = row_match.group(2).split()
            for i, byte_hex in enumerate(bytes_str):
                current.bytes_by_addr[base_addr + i] = int(byte_hex, 16)
            continue
        # Anything else is a stray line — surface but don't fail.
        print(f"# warning: line {line_no} unrecognized: {line!r}", file=sys.stderr)
    if current is not None:
        snapshots.append(current)
    return snapshots


def diff_bytes(prev: int, curr: int) -> str:
    diff = prev ^ curr
    if diff == 0:
        return "(equal)"
    parts: list[str] = []
    bits_set = [i for i in range(8) if (curr & ~prev) & (1 << i)]
    bits_cleared = [i for i in range(8) if (prev & ~curr) & (1 << i)]
    if bits_set:
        parts.append(f"bit{'s' if len(bits_set) > 1 else ''} {','.join(map(str, bits_set))} set")
    if bits_cleared:
        parts.append(f"bit{'s' if len(bits_cleared) > 1 else ''} {','.join(map(str, bits_cleared))} cleared")
    if curr - prev in range(-9, 10) and (curr - prev) != 0:
        parts.append(f"byte {curr - prev:+d}")
    return "(" + "; ".join(parts) + ")"


def diff_pair(prev: Snapshot, curr: Snapshot) -> None:
    print(
        f"--- DIFF: {prev.label} -> {curr.label}"
        f" (frames {prev.frame} -> {curr.frame}) ---"
    )
    addrs = sorted(set(prev.bytes_by_addr) | set(curr.bytes_by_addr))
    changed = 0
    for addr in addrs:
        a = prev.bytes_by_addr.get(addr)
        b = curr.bytes_by_addr.get(addr)
        if a == b:
            continue
        if a is None or b is None:
            print(f"  0x{addr:06X}: only in one snapshot ({a!r} / {b!r})")
            continue
        print(f"  0x{addr:06X}: 0x{a:02X} -> 0x{b:02X}  {diff_bytes(a, b)}")
        changed += 1
    if changed == 0:
        print("  (no byte differences)")
    print()


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("log", type=Path)
    args = p.parse_args(argv)

    snapshots = parse_log(args.log)
    if len(snapshots) < 2:
        print(
            f"# error: log has only {len(snapshots)} snapshot(s); need >=2 for a pair.",
            file=sys.stderr,
        )
        return 1

    print(
        f"# {len(snapshots)} snapshots loaded; emitting {len(snapshots) - 1} pair-diffs.\n"
    )
    for prev, curr in itertools.pairwise(snapshots):
        diff_pair(prev, curr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
