"""Static probe: enumerate every ITEM_PARA entry with ``meritValue > 0``.

The Merit Shop's open-time scan walks the 128-entry ITEM_PARA from id 0
up to bound ``< 0x80`` and includes any entry whose ``meritValue`` is
non-zero. The same ground-truth list drives v2 multi-slot AP
randomization: the patcher needs to zero each vanilla item's
``meritValue`` (so it stops appearing) and write the same count of
extended ITEM_PARA entries with non-zero merit values.

Usage::

    python -m worlds.digimon_world.tools.dw1_merit_inventory

Reads ``Digimon World (USA).bin`` from the repo root, sector-strips it
to user-data via :func:`worlds.digimon_world.data.addresses.read_item_table_user_data`,
unpacks each 32-byte record per :data:`ROM_ITEM_DATA.record_format`,
and prints every entry whose ``meritValue > 0``.

Output is plain Python literal so it can be pasted directly into
``addresses.py`` as ``MERIT_SHOP_VANILLA_ENTRIES``.
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BIN_PATH = REPO_ROOT / "Digimon World (USA).bin"


def main() -> int:
    # Late imports so the script can be run as a top-level file too.
    sys.path.insert(0, str(REPO_ROOT))
    from worlds.digimon_world.data.addresses import (  # noqa: E402
        ROM_ITEM_DATA,
        ROM_ITEM_TABLE_ENTRY_COUNT,
        ROM_ITEM_TABLE_ENTRY_SIZE,
        read_item_table_user_data,
    )

    if not BIN_PATH.exists():
        print(f"Cannot find .bin at {BIN_PATH}", file=sys.stderr)
        return 1

    print(f"Loading {BIN_PATH.name} ({BIN_PATH.stat().st_size:,} bytes)...")
    raw = BIN_PATH.read_bytes()
    user_data = read_item_table_user_data(raw)
    assert len(user_data) == ROM_ITEM_TABLE_ENTRY_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE, (
        f"Expected {ROM_ITEM_TABLE_ENTRY_COUNT * ROM_ITEM_TABLE_ENTRY_SIZE} bytes, "
        f"got {len(user_data)}"
    )

    record_fmt = ROM_ITEM_DATA.record_format
    record_size = struct.calcsize(record_fmt)
    assert record_size == ROM_ITEM_TABLE_ENTRY_SIZE, (record_size, ROM_ITEM_TABLE_ENTRY_SIZE)

    print(f"\nITEM_PARA = {ROM_ITEM_TABLE_ENTRY_COUNT} entries × {ROM_ITEM_TABLE_ENTRY_SIZE} bytes\n")
    print(f"{'idx':>3} {'hex':>4}  {'name':<20s} {'value':>8} {'merit':>6} {'sort':>5} {'color':>5} {'drop':>4}")
    print("-" * 70)

    entries: list[tuple[int, str, int, int]] = []
    for idx in range(ROM_ITEM_TABLE_ENTRY_COUNT):
        rec = user_data[idx * record_size : (idx + 1) * record_size]
        name_bytes, value, merit, sort, color, dropable = struct.unpack(record_fmt, rec)
        name = name_bytes.rstrip(b"\x00").decode("ascii", errors="replace")
        if merit > 0:
            entries.append((idx, name, merit, value))
            print(
                f"{idx:>3} 0x{idx:02X}  {name:<20s} {value:>8} {merit:>6} {sort:>5} "
                f"{color:>5} {int(dropable):>4}"
            )

    print(f"\nTotal entries with meritValue > 0: {len(entries)}")
    print("\n--- Paste-ready tuple for addresses.py ---\n")
    print("MERIT_SHOP_VANILLA_ENTRIES: Final[tuple[tuple[int, str, int], ...]] = (")
    for idx, name, merit, _value in entries:
        print(f"    (0x{idx:02X}, {name!r:<24s}, {merit:>5}),  # value={_value}")
    print(")")
    return 0


if __name__ == "__main__":
    sys.exit(main())
