"""DW1 Recycle Shop item-list scanner.

Phase 1 of recycle-shop randomization: locate the 14-byte
``[item_id, flags] * 7`` array embedded in Script 126's data segment
inside the user's vanilla DW1 .bin.

Usage:

    python worlds/digimon_world/tools/dw1_scan_recycle_shop.py \
        path/to/Digimon_World.bin

The Recycle Shop in Gear Savanna (screen GIAS06B, script 126,
Section_82) sells 7 fixed items. Six are identified from DWAP's item
table cross-referenced with the in-game shop screenshot:

    slot 1: med.recovery     id 0x01  price 500
    slot 2: Medium MP        id 0x05  price 800
    slot 3: Off. Disk        id 0x0F  price 500
    slot 4: Def. Disk        id 0x10  price 500
    slot 5: Hispeed dsk      id 0x11  price 500
    slot 6: Auto Pilot       id 0x16  price 300
    slot 7: ???              id ?     price ?

The shop UI loads these from a 14-byte literal table (per Script 126
disasm: ``shop_obj.item_list_ptr`` points at ``[id_u8, flag_u8] * N``).
The flag byte's 0x80 bit gates "in-stock". The script flow is:
``setTrigger 385 / 389 / 406 / 423 / 399 / 400 / 401`` -> ``callRoutine
8`` (build menu) -> ``unsetTrigger`` cleanup. The 7 setTriggers map
1-to-1 to the 7 array slots.

This scanner searches for the byte pattern of the first 6 known IDs
interleaved with arbitrary flag bytes, then reports the .bin offset
of every match plus the 7 ``[id, flag]`` pairs at that offset (so the
unknown 7th item is revealed).

False positives are possible but rare: the pattern requires 6 specific
item IDs in a specific order with arbitrary bytes in between, which
is enough entropy that only the real recycle-shop array tends to match.

Output:

    [scanner] match at .bin offset 0x.... :
      slot 1: id 0x01 flags 0x..  (vanilla: med.recovery)
      slot 2: id 0x05 flags 0x..  (vanilla: Medium MP)
      ...
      slot 7: id 0x..  flags 0x..  (UNKNOWN -- this is the 7th item)

Pass the offset and 7th item ID back to the implementer for use in
``addresses.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Item-id mapping from references/DWAP/source/DWAP/Resources/DigimonItems.json.
# Trimmed to the entries we need for cross-referencing the 7th slot.
ITEM_ID_TO_NAME: dict[int, str] = {
    0x00: "sm.recovery",
    0x01: "med.recovery",
    0x02: "lrg.recovery",
    0x03: "sup.recovery",
    0x04: "MP Floppy",
    0x05: "Medium MP",
    0x06: "Large MP",
    0x07: "Double flop",
    0x08: "Various",
    0x09: "Omnipotent",
    0x0A: "Protection",
    0x0B: "Restore",
    0x0D: "Bandage",
    0x0E: "Medicine",
    0x0F: "Off. Disk",
    0x10: "Def. Disk",
    0x11: "Hispeed dsk",
    0x12: "Omni Disk",
    0x13: "S.Off.disk",
    0x14: "S.Def.disk",
    0x15: "S.speed.disk",
    0x16: "Auto Pilot",
    0x17: "Off. Chip",
    0x18: "Def. Chip",
    0x19: "Brain Chip",
    0x1A: "Quick Chip",
    0x1B: "HP Chip",
    0x1C: "MP Chip",
    0x1D: "DV Chip A",
    0x1E: "DV Chip D",
    0x1F: "DV Chip E",
    0x20: "Port. potty",
    0x21: "Trn. manual",
    0x22: "Rest pillow",
    0x23: "Enemy repel",
    0x24: "Enemy bell",
    0x25: "Health shoe",
    0x26: "Meat",
    # Add more if 7th item lands outside this range.
}


# Recycle shop slot order observed in-game (Gear Savanna GIAS06B).
KNOWN_VANILLA_IDS: tuple[int, ...] = (0x01, 0x05, 0x0F, 0x10, 0x11, 0x16)
KNOWN_VANILLA_NAMES: tuple[str, ...] = (
    "med.recovery", "Medium MP", "Off. Disk", "Def. Disk",
    "Hispeed dsk", "Auto Pilot",
)


def find_recycle_shop_array(bin_data: bytes) -> list[int]:
    """Return all .bin offsets where the recycle-shop signature matches.

    Pattern: 14 bytes structured as ``[id_u8, flag_u8] * 7`` where the
    first 6 ids match :data:`KNOWN_VANILLA_IDS` exactly. Flag bytes
    and the 7th (id, flag) pair are unconstrained.
    """
    matches: list[int] = []
    target = KNOWN_VANILLA_IDS
    n = len(bin_data)
    # Walk every possible 14-byte window. Stride 1 is fine on a ~380 MB
    # file -- the scan finishes in seconds.
    for offset in range(0, n - 14):
        ok = True
        for i, expected_id in enumerate(target):
            if bin_data[offset + i * 2] != expected_id:
                ok = False
                break
        if ok:
            matches.append(offset)
    return matches


def report_match(bin_data: bytes, offset: int) -> None:
    print(f"[scanner] match at .bin offset 0x{offset:08X}:")
    for slot in range(7):
        item_id = bin_data[offset + slot * 2]
        flags = bin_data[offset + slot * 2 + 1]
        name = ITEM_ID_TO_NAME.get(item_id, "<unknown id>")
        if slot < len(KNOWN_VANILLA_NAMES):
            tag = f"vanilla: {KNOWN_VANILLA_NAMES[slot]}"
        else:
            tag = f"UNKNOWN -- 7th item -> id 0x{item_id:02X} = {name}"
        print(
            f"  slot {slot + 1}: id 0x{item_id:02X} "
            f"flags 0x{flags:02X}  ({tag})"
        )
    # Print 8 bytes before/after for context (helps disambiguate false
    # positives in case multiple matches are reported).
    pre = bin_data[max(0, offset - 8):offset]
    post = bin_data[offset + 14:offset + 14 + 8]
    print(
        f"  context [-8, +8]: "
        f"{pre.hex(' ')} | <14 bytes> | {post.hex(' ')}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan a DW1 .bin for the Recycle Shop item-list array."
    )
    parser.add_argument(
        "bin_path",
        type=Path,
        help="Path to the user's vanilla DW1 .bin (PSX disc image).",
    )
    args = parser.parse_args(argv)

    if not args.bin_path.is_file():
        print(f"[scanner] not a file: {args.bin_path}", file=sys.stderr)
        return 2

    print(f"[scanner] reading {args.bin_path} ...")
    bin_data = args.bin_path.read_bytes()
    print(f"[scanner] {len(bin_data):,} bytes")
    print(
        f"[scanner] searching for signature: "
        f"{' '.join(f'{b:02X} ??' for b in KNOWN_VANILLA_IDS)} ?? ??"
    )

    matches = find_recycle_shop_array(bin_data)
    if not matches:
        print("[scanner] no matches found.")
        print(
            "[scanner] either the .bin is not vanilla DW1 USA, the slot "
            "order differs from the screenshot, or this is the wrong "
            "scanner build. Re-run with the verified vanilla SLUS-01032."
        )
        return 1

    print(f"[scanner] {len(matches)} match(es).")
    for offset in matches:
        print()
        report_match(bin_data, offset)
    print()
    print(
        "[scanner] pass the .bin offset(s) and the 7th item ID back to "
        "the implementer. If multiple matches appear and look "
        "plausible, additional disambiguation may be needed (e.g. "
        "checking the surrounding context bytes against Script 126's "
        "expected data layout)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
