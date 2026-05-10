"""DW1 Recycle Shop scanner — FAST version using bytes.find().

The previous flexible scanner used pure-Python loops and was too slow
on the 381 MB .bin. This rewrite:

  1. Phase 1 — locate ITEM_PARA in the .bin via item-name string search
     (bytes.find is O(n) in C, runs in <1s on 381 MB).
  2. Phase 2 — verify or override the DWAP item-id mapping by walking
     ITEM_PARA entries and printing each entry's name + price.
  3. Phase 3 — search for the recycle-shop item-list array using the
     verified IDs, trying multiple structural hypotheses with
     bytes.find()-based scans (each scan is O(n) in C).

Hypotheses tried in Phase 3:
  H1: 1-byte-stride concatenation of 6 IDs in display order
  H2: 1-byte-stride, all 720 permutations of the 6 IDs
  H3: 2-byte-stride with uniform flag byte (try 0x01, 0x80, 0xFF)
  H4: 4-byte-stride, display order
  H5: 6 IDs anywhere within a 32-byte window (slower; pure Python)

Expected: H1 or H3 hits with 1 well-isolated match.
"""

from __future__ import annotations

import argparse
import sys
from itertools import permutations
from pathlib import Path


# Best-effort DWAP-derived IDs — verified against ITEM_PARA in Phase 2.
KNOWN_NAMES_TO_DWAP_IDS: dict[str, int] = {
    "med.recovery": 0x01,
    "Medium MP":    0x05,
    "Off. Disk":    0x0F,
    "Def. Disk":    0x10,
    "Hispeed dsk":  0x11,
    "Auto Pilot":   0x16,
}


def find_all(haystack: bytes, needle: bytes, max_hits: int = 100) -> list[int]:
    """Fast O(n) all-occurrences finder using bytes.find()."""
    out = []
    offset = 0
    while len(out) < max_hits:
        idx = haystack.find(needle, offset)
        if idx < 0:
            break
        out.append(idx)
        offset = idx + 1
    return out


def find_item_para_anchor(bin_data: bytes) -> int | None:
    """Find ITEM_PARA's start in the .bin by searching for "sm.recovery".

    Item id 0 = "sm.recovery" per DWAP. Its name field is at offset 0
    of ITEM_PARA[0]. Vanilla ITEM_PARA is 128 entries of 32 bytes each.
    The first occurrence of "sm.recovery\\0" inside an aligned 32-byte
    block followed by another known name 32 bytes later is our anchor.
    """
    sm_hits = find_all(bin_data, b"sm.recovery\x00", max_hits=20)
    if not sm_hits:
        return None
    # Filter: ITEM_PARA[1] should be "med.recovery" 32 bytes later.
    for hit in sm_hits:
        candidate = bin_data[hit + 32:hit + 32 + 13]
        if candidate.startswith(b"med.recovery"):
            return hit
    # Fallback: return first occurrence even if neighbor doesn't match.
    return sm_hits[0]


def dump_item_para(bin_data: bytes, anchor: int, n_entries: int = 130) -> dict[str, int]:
    """Walk ITEM_PARA from ``anchor`` and print each entry. Return name->id."""
    name_to_id: dict[str, int] = {}
    print(f"  ITEM_PARA dump from .bin 0x{anchor:08X}:")
    for slot in range(n_entries):
        entry_offset = anchor + slot * 32
        if entry_offset + 32 > len(bin_data):
            break
        entry = bin_data[entry_offset:entry_offset + 32]
        name_end = entry.find(b"\x00")
        if name_end < 0:
            name_end = 14
        name_bytes = entry[:name_end]
        try:
            name = name_bytes.decode("ascii")
        except UnicodeDecodeError:
            name = repr(name_bytes)
        value = int.from_bytes(entry[0x14:0x18], "little", signed=True)
        merit = int.from_bytes(entry[0x18:0x1A], "little", signed=True)
        if 0 < slot < 128:
            name_to_id[name] = slot
        print(
            f"    +{slot:3d} 0x{entry_offset:08X}: "
            f"name={name!r:<18} value={value:>6} merit={merit:>5}"
        )
    return name_to_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bin_path", type=Path)
    parser.add_argument(
        "--dump-item-para", action="store_true",
        help="Print all 128 ITEM_PARA entries (default: only the relevant ones)",
    )
    parser.add_argument(
        "--max-matches", type=int, default=20,
        help="Cap reported matches per hypothesis",
    )
    args = parser.parse_args(argv)

    bin_data = args.bin_path.read_bytes()
    print(f"[scanner] {args.bin_path}: {len(bin_data):,} bytes")

    # ----- Phase 1: locate ITEM_PARA -----
    print("\n=== Phase 1: locate ITEM_PARA ===")
    anchor = find_item_para_anchor(bin_data)
    if anchor is None:
        print("[scanner] could not locate ITEM_PARA. Bailing.")
        return 1
    print(f"  anchor (ITEM_PARA[0] = 'sm.recovery'): 0x{anchor:08X}")

    # ----- Phase 2: verify item IDs -----
    print("\n=== Phase 2: ITEM_PARA dump ===")
    n_entries = 130 if args.dump_item_para else 40
    name_to_id = dump_item_para(bin_data, anchor, n_entries)

    print("\n  cross-check known names against ITEM_PARA:")
    verified_ids: list[int] = []
    for name, dwap_id in KNOWN_NAMES_TO_DWAP_IDS.items():
        # Try DWAP's name first. ITEM_PARA's actual name might differ
        # in spacing (e.g. "Off. Disk" vs "Off.Disk").
        actual_id = name_to_id.get(name)
        if actual_id is None:
            # Try alternate spellings.
            for n2, idn in name_to_id.items():
                if n2.replace(" ", "").lower() == name.replace(" ", "").lower():
                    actual_id = idn
                    print(
                        f"    {name!r}: matched ITEM_PARA name "
                        f"{n2!r} -> id {actual_id} (DWAP said {dwap_id})"
                    )
                    break
        if actual_id is None:
            print(f"    {name!r}: NOT FOUND in ITEM_PARA dump")
            verified_ids.append(dwap_id)  # fall back to DWAP id
        else:
            match_str = "match" if actual_id == dwap_id else "MISMATCH"
            print(
                f"    {name!r}: ITEM_PARA id={actual_id} "
                f"(DWAP id={dwap_id}) [{match_str}]"
            )
            verified_ids.append(actual_id)

    display_order = tuple(verified_ids)
    print(f"\n  using verified IDs: {[hex(b) for b in display_order]}")

    # ----- Phase 3: scan for the recycle-shop array -----
    print("\n=== Phase 3: search for recycle-shop array ===")

    # H1: 1-byte stride, display order (just 6 IDs concatenated)
    needle_h1 = bytes(display_order)
    print(f"\n[H1] 1-byte stride, display order: needle={needle_h1.hex(' ')}")
    h1 = find_all(bin_data, needle_h1, max_hits=args.max_matches)
    print(f"  {len(h1)} match(es)")
    for off in h1:
        ctx = bin_data[off:off + 16].hex(" ")
        print(f"  0x{off:08X}: {ctx}")

    # H3: 2-byte stride with uniform flag (try common values)
    for flag in (0x01, 0x80, 0xFF, 0x00):
        needle = bytes(b for pair in
                       ((id_, flag) for id_ in display_order)
                       for b in pair)
        print(f"\n[H3 flag=0x{flag:02X}] 2-byte stride: needle={needle.hex(' ')}")
        hits = find_all(bin_data, needle, max_hits=args.max_matches)
        print(f"  {len(hits)} match(es)")
        for off in hits:
            ctx = bin_data[off:off + 20].hex(" ")
            print(f"  0x{off:08X}: {ctx}")

    # H4: 4-byte stride, display order
    needle_h4 = bytes(b for id_ in display_order for b in (id_, 0, 0, 0))
    print(f"\n[H4] 4-byte stride, id+3 zeros: needle={needle_h4.hex(' ')}")
    h4 = find_all(bin_data, needle_h4, max_hits=args.max_matches)
    print(f"  {len(h4)} match(es)")
    for off in h4:
        ctx = bin_data[off:off + 32].hex(" ")
        print(f"  0x{off:08X}: {ctx}")

    # H2: 1-byte stride, ANY permutation. Fast — bytes.find on 720
    # 6-byte needles is < 1s total.
    print("\n[H2] 1-byte stride, any permutation of 6 IDs (720 needles)")
    h2_total = 0
    h2_hits: list[tuple[tuple[int, ...], int]] = []
    for perm in permutations(display_order):
        if perm == display_order:
            continue
        needle = bytes(perm)
        hits = find_all(bin_data, needle, max_hits=3)
        for off in hits:
            h2_hits.append((perm, off))
            h2_total += 1
            if h2_total >= args.max_matches:
                break
        if h2_total >= args.max_matches:
            break
    print(f"  {h2_total} match(es) reported")
    for perm, off in h2_hits[:args.max_matches]:
        perm_str = " ".join(f"{b:02X}" for b in perm)
        ctx = bin_data[off:off + 16].hex(" ")
        print(f"  perm [{perm_str}] @ 0x{off:08X}: {ctx}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
