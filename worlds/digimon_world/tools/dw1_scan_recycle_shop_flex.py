"""DW1 Recycle Shop scanner — flexible version.

The strict-order 2-byte-stride scan didn't match. This tool tries
multiple structural hypotheses and also verifies item IDs against
ITEM_PARA in the .bin (DWAP's IDs may not match vanilla).

Hypotheses tried:
  H1: 2-byte stride, display-order ([id, flag] * 7) — already failed
  H2: 2-byte stride, any permutation of the 6 known IDs
  H3: 1-byte stride (just IDs, no flag) — display order
  H4: 1-byte stride, any permutation
  H5: 4-byte stride (id + 3 bytes), display order
  H6: 6 known IDs anywhere within a 32-byte window, any ordering

Also: dump ITEM_PARA from the .bin to verify item ID -> name mapping.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from itertools import permutations


# DWAP-derived IDs (may not match vanilla ITEM_PARA — verify below).
KNOWN_NAMES_TO_DWAP_IDS: dict[str, int] = {
    "med.recovery": 0x01,
    "Medium MP":    0x05,
    "Off. Disk":    0x0F,
    "Def. Disk":    0x10,
    "Hispeed dsk":  0x11,
    "Auto Pilot":   0x16,
}


def find_item_para(bin_data: bytes) -> list[tuple[int, str]]:
    """Locate ITEM_PARA in .bin by searching for known item-name strings.

    ITEM_PARA entries are 32 bytes; the name string lives at offset 0
    as a null-padded fixed-width field (likely 14-16 bytes wide).
    Returns list of (offset, name_bytes_decoded) hits.
    """
    candidates = []
    # Search for distinctive item-name strings that wouldn't appear elsewhere.
    needles = [
        b"med.recovery\x00",
        b"sm.recovery\x00",
        b"Medium MP\x00",
        b"Auto Pilot\x00",
    ]
    for needle in needles:
        offset = 0
        while True:
            idx = bin_data.find(needle, offset)
            if idx < 0:
                break
            candidates.append((idx, needle.rstrip(b"\x00").decode("ascii")))
            offset = idx + 1
    return candidates


def dump_item_para_around(bin_data: bytes, start_offset: int, n_entries: int) -> None:
    """Walk back to align with a 32-byte boundary and dump entries."""
    # ITEM_PARA name field is at offset 0 of each 32-byte entry.
    # Walk backwards: find the start of the entry by snapping to 32B.
    # We can't know the alignment without an anchor; assume the name
    # we found is aligned at offset 0 of an entry.
    print(f"  dumping {n_entries} entries starting at .bin 0x{start_offset:08X}:")
    for i in range(n_entries):
        entry_offset = start_offset + i * 32
        if entry_offset + 32 > len(bin_data):
            break
        entry = bin_data[entry_offset:entry_offset + 32]
        # Name field: read up to first null byte.
        name_end = entry.find(b"\x00")
        if name_end < 0:
            name_end = 14
        name = entry[:name_end].decode("ascii", errors="replace")
        # Price candidates: lw at offset 0x14 (i32 little-endian)
        # Merit value at offset 0x18 (i16 little-endian)
        value_le = int.from_bytes(entry[0x14:0x18], "little", signed=True)
        merit_le = int.from_bytes(entry[0x18:0x1A], "little", signed=True)
        print(
            f"    +{i:3d} @ 0x{entry_offset:08X}: "
            f"name={name!r:<20} value={value_le} merit={merit_le}"
        )


def scan_strict_2byte(bin_data: bytes, ids: tuple[int, ...]) -> list[int]:
    """H1/H2: 2-byte stride, given ID order; flag bytes unconstrained."""
    out = []
    target_len = len(ids) * 2
    for offset in range(len(bin_data) - target_len):
        ok = True
        for i, expected in enumerate(ids):
            if bin_data[offset + i * 2] != expected:
                ok = False
                break
        if ok:
            out.append(offset)
    return out


def scan_strict_1byte(bin_data: bytes, ids: tuple[int, ...]) -> list[int]:
    """H3/H4: 1-byte stride, given ID order, contiguous."""
    needle = bytes(ids)
    out = []
    offset = 0
    while True:
        idx = bin_data.find(needle, offset)
        if idx < 0:
            break
        out.append(idx)
        offset = idx + 1
    return out


def scan_strict_4byte(bin_data: bytes, ids: tuple[int, ...]) -> list[int]:
    """H5: 4-byte stride, given ID order."""
    out = []
    target_len = len(ids) * 4
    for offset in range(len(bin_data) - target_len):
        ok = True
        for i, expected in enumerate(ids):
            if bin_data[offset + i * 4] != expected:
                ok = False
                break
        if ok:
            out.append(offset)
    return out


def scan_proximity_window(bin_data: bytes, ids: set[int], window: int) -> list[int]:
    """H6: all 6 IDs appear within a ``window``-byte sliding window."""
    out = []
    if len(ids) > window:
        return out
    needed = sorted(ids)
    for offset in range(len(bin_data) - window):
        chunk = bin_data[offset:offset + window]
        # quick check: all needed IDs present?
        if all(byte in chunk for byte in needed):
            out.append(offset)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bin_path", type=Path)
    parser.add_argument(
        "--max-matches", type=int, default=20,
        help="Cap reported matches per hypothesis (default: 20)",
    )
    parser.add_argument(
        "--proximity-window", type=int, default=32,
        help="Window size for H6 proximity scan (default: 32)",
    )
    args = parser.parse_args(argv)

    bin_data = args.bin_path.read_bytes()
    print(f"[scanner] {args.bin_path}: {len(bin_data):,} bytes")

    # ----- Phase 1: verify ITEM_PARA layout in the .bin -----
    print("\n=== Phase 1: locate ITEM_PARA via name strings ===")
    name_hits = find_item_para(bin_data)
    if not name_hits:
        print("[scanner] no item-name strings found in .bin. The .bin "
              "may be encrypted or the names may not be ASCII.")
    else:
        print(f"[scanner] {len(name_hits)} name hit(s):")
        seen = set()
        for offset, name in name_hits:
            key = (offset & ~0x1F, name)
            if key in seen:
                continue
            seen.add(key)
            # Snap to 32B boundary (ITEM_PARA entry start) for cleaner dump.
            print(f"  - {name!r} at 0x{offset:08X} "
                  f"(snap to 32B: 0x{offset & ~0x1F:08X})")
        # Pick the first hit as a likely ITEM_PARA anchor.
        first = name_hits[0]
        anchor = first[0] & ~0x1F  # snap down to 32B
        print()
        # Walk back further if "med.recovery" is name #1 (id 1) — the
        # table starts at id 0 = "sm.recovery", one entry earlier.
        table_start = anchor - 32 if first[1] == "med.recovery" else anchor
        print(f"[scanner] inferred ITEM_PARA start: 0x{table_start:08X}")
        dump_item_para_around(bin_data, table_start, n_entries=40)

    # ----- Phase 2: try multiple structural hypotheses for the array -----
    display_order = (0x01, 0x05, 0x0F, 0x10, 0x11, 0x16)
    id_set = set(display_order)

    print("\n=== Phase 2: scan for recycle-shop array ===")

    print("\n[H1] 2-byte stride, display order")
    h1 = scan_strict_2byte(bin_data, display_order)
    print(f"  {len(h1)} match(es)")
    for off in h1[:args.max_matches]:
        ctx = bin_data[off:off + 16].hex(" ")
        print(f"  0x{off:08X}: {ctx}")

    print("\n[H3] 1-byte stride, display order (just IDs concatenated)")
    h3 = scan_strict_1byte(bin_data, display_order)
    print(f"  {len(h3)} match(es)")
    for off in h3[:args.max_matches]:
        ctx = bin_data[off:off + 16].hex(" ")
        print(f"  0x{off:08X}: {ctx}")

    print("\n[H5] 4-byte stride, display order")
    h5 = scan_strict_4byte(bin_data, display_order)
    print(f"  {len(h5)} match(es)")
    for off in h5[:args.max_matches]:
        ctx = bin_data[off:off + 32].hex(" ")
        print(f"  0x{off:08X}: {ctx}")

    print("\n[H2] 2-byte stride, ANY permutation of 6 known IDs")
    h2_total = 0
    for perm in permutations(display_order):
        if perm == display_order:
            continue  # already covered by H1
        hits = scan_strict_2byte(bin_data, perm)
        if hits:
            for off in hits:
                ctx = bin_data[off:off + 16].hex(" ")
                print(f"  perm {perm}: 0x{off:08X}: {ctx}")
                h2_total += 1
                if h2_total >= args.max_matches:
                    break
        if h2_total >= args.max_matches:
            break
    print(f"  {h2_total} match(es) reported (cap: {args.max_matches})")

    print("\n[H4] 1-byte stride, ANY permutation of 6 known IDs")
    h4_total = 0
    for perm in permutations(display_order):
        if perm == display_order:
            continue
        hits = scan_strict_1byte(bin_data, perm)
        if hits:
            for off in hits:
                ctx = bin_data[off:off + 16].hex(" ")
                print(f"  perm {perm}: 0x{off:08X}: {ctx}")
                h4_total += 1
                if h4_total >= args.max_matches:
                    break
        if h4_total >= args.max_matches:
            break
    print(f"  {h4_total} match(es) reported (cap: {args.max_matches})")

    print(f"\n[H6] all 6 IDs appear within a {args.proximity_window}-byte window")
    h6 = scan_proximity_window(bin_data, id_set, args.proximity_window)
    print(f"  {len(h6)} match(es)")
    for off in h6[:args.max_matches]:
        ctx = bin_data[off:off + args.proximity_window].hex(" ")
        print(f"  0x{off:08X}: {ctx}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
