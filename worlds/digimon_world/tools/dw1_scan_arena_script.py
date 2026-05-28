"""DW1 Arena Cup script-offset locator.

Finds the .bin offsets of the 14 ``giveItem`` opcodes inside Script 214
Section_51 that the AP arena-cup feature needs to patch with
``setTrigger`` so the 5 grade-tier cup wins (D/C/B/A/S) fire AP
location checks.

Background
==========
Script 214 §51 is the post-arena-match handler. Its **win path** (entry
pstat(255)==3) dispatches on ``pstat(3)`` to one of N cup branches and
hands out the vanilla prize via ``giveItem``. The 5 grade-tier cups
sit at the top of that dispatch (pstat(3) == 0..4). We need to swap
each cup's ``giveItem`` (primary + inventory-overflow bank copy) with
``setTrigger N`` so the cup win is detectable via the trigger-bit
array.

14 patch sites total. Script-relative offsets are for the SLUS-01032
USA build; the randomizer's reference disassembly has a 304-byte
shorter Grade S region (USA inserts an extra block after the FB-primary
giveItem) -- the offsets below reflect what's actually in the USA .bin,
verified 2026-05-26 against ``Digimon World (USA).bin``.

  Grade D (pstat(3)==0)  giveItem  7 1  primary @ script-offset 0476
                         giveItem  7 1  bank    @ script-offset 0554
  Grade C (pstat(3)==1)  giveItem 40 3  primary @ script-offset 0742
                         giveItem 40 3  bank    @ script-offset 0820
  Grade B (pstat(3)==2)  giveItem 11 1  primary @ script-offset 1006
                         giveItem 11 1  bank    @ script-offset 1084
  Grade A (pstat(3)==3)  giveItem 80 1  primary @ script-offset 1378
                         giveItem 80 1  bank    @ script-offset 1456
  Grade S (pstat(3)==4)  random sub-branch on pstat(110):
    pstat(110)==0        giveItem 99 1  primary @ script-offset 1748
                         giveItem 99 1  bank    @ script-offset 1826
    pstat(110)==1        giveItem 100 1 primary @ script-offset 2008
                         giveItem 100 1 bank    @ script-offset 2390  (USA +304)
    pstat(110)==2        giveItem 102 1 primary @ script-offset 2568  (USA +304)
                         giveItem 102 1 bank    @ script-offset 2646  (USA +304)

Strategy
========
DW1's textbox bytecode encodes strings in a custom (non-ASCII) glyph
table, so anchoring on the prize-name text (``"Double Floppy"`` etc.)
doesn't work. Instead the scan anchors on the giveItem **opcode**
itself (``0x28 0x00 <item_id> <qty>``, a 4-byte fixed-format
instruction confirmed against the existing key-item neuter patches):

1. Find every occurrence of Grade D's primary giveItem byte pattern
   (``28 00 07 01``) in the .bin.
2. For each candidate offset C, derive a Section_51 base
   ``base = C - 476`` and check whether all 14 patch sites reproduce
   the expected ``28 00 <item> <qty>`` 4-byte opcode at
   ``base + script_relative_offset``.
3. Report every base that verifies. False positives (random byte
   sequences that look like Grade D's primary giveItem) reliably fail
   verification because the chance of 13 more 4-byte coincidences at
   the exact expected offsets is astronomical.

If multiple matches survive verification, all are reported (DW1 has
multi-copy scripts; vending has 2 copies of most scripts).

Usage
=====
    python -m worlds.digimon_world.tools.dw1_scan_arena_script PATH/TO/DW1.BIN

Output is a Python literal suitable for pasting into
:data:`worlds.digimon_world.data.addresses.ROM_ARENA_SECTION_51_BASES`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple


class CupSite(NamedTuple):
    cup: str            # "Grade D" / "Grade C" / ...
    branch: int         # 0 for primary, 1 for bank-fallback
    sub_branch: int     # 0 for non-Grade-S; 0/1/2 for the 3 Grade S prize variants
    prize_id: int       # item ID
    prize_qty: int      # quantity
    script_offset: int  # script-relative offset of the giveItem opcode in Section_51


# 14 patch sites, in the order they appear in Section_51 (SLUS-01032 USA).
# (cup, branch, sub_branch, prize_id, prize_qty, script_relative_offset)
PATCH_SITES: tuple[CupSite, ...] = (
    CupSite("Grade D", 0, 0,   7, 1,  476),
    CupSite("Grade D", 1, 0,   7, 1,  554),
    CupSite("Grade C", 0, 0,  40, 3,  742),
    CupSite("Grade C", 1, 0,  40, 3,  820),
    CupSite("Grade B", 0, 0,  11, 1, 1006),
    CupSite("Grade B", 1, 0,  11, 1, 1084),
    CupSite("Grade A", 0, 0,  80, 1, 1378),
    CupSite("Grade A", 1, 0,  80, 1, 1456),
    CupSite("Grade S", 0, 0,  99, 1, 1748),  # Metal Part
    CupSite("Grade S", 1, 0,  99, 1, 1826),
    CupSite("Grade S", 0, 1, 100, 1, 2008),  # Fatal Bone primary
    CupSite("Grade S", 1, 1, 100, 1, 2390),  # Fatal Bone bank (USA +304)
    CupSite("Grade S", 0, 2, 102, 1, 2568),  # Mega Hand primary (USA +304)
    CupSite("Grade S", 1, 2, 102, 1, 2646),  # Mega Hand bank (USA +304)
)


# DW1's giveItem opcode = (0x28, 0x00, item_id, quantity), 4 bytes.
# Confirmed by inspecting bytes at known giveItem sites in existing
# key-item neuters (Rain Plant @ 0x1405AFEC, Leomonstone @ 0x14030216).
GIVEITEM_OPCODE: int = 0x28


def find_all(haystack: bytes, needle: bytes) -> list[int]:
    out: list[int] = []
    offset = 0
    while True:
        idx = haystack.find(needle, offset)
        if idx < 0:
            return out
        out.append(idx)
        offset = idx + 1


def verify_base(bin_data: bytes, section_base: int) -> tuple[bool, list[str]]:
    """Check that every patch site has the expected 4-byte giveItem
    opcode at ``section_base + script_offset``.
    """

    errors: list[str] = []
    for site in PATCH_SITES:
        addr = section_base + site.script_offset
        if addr + 4 > len(bin_data):
            errors.append(f"{site.cup} br{site.branch} sub{site.sub_branch}: "
                          f"address 0x{addr:08X} out of bounds")
            continue
        if (bin_data[addr] != GIVEITEM_OPCODE or bin_data[addr + 1] != 0x00
                or bin_data[addr + 2] != site.prize_id
                or bin_data[addr + 3] != site.prize_qty):
            actual = bin_data[addr:addr + 4].hex(' ')
            expected = bytes(
                (GIVEITEM_OPCODE, 0x00, site.prize_id, site.prize_qty)
            ).hex(' ')
            errors.append(f"{site.cup} br{site.branch} sub{site.sub_branch} "
                          f"@ 0x{addr:08X}: expected {expected}, "
                          f"got {actual}")
    return (not errors, errors)


def report(bin_data: bytes) -> int:
    print(f"DW1.BIN size: {len(bin_data):,} bytes "
          f"(0x{len(bin_data):08X})")

    # Find every Grade D primary giveItem byte pattern; derive a
    # Section_51 base from each and verify the full 14-site layout.
    seed = PATCH_SITES[0]
    needle = bytes((GIVEITEM_OPCODE, 0x00, seed.prize_id, seed.prize_qty))
    print()
    print("=" * 72)
    print(f"Scanning for Grade D primary giveItem pattern ({needle.hex(' ')})")
    print("=" * 72)
    candidates = find_all(bin_data, needle)
    print(f"  {len(candidates)} candidate(s)")

    confirmed_bases: list[int] = []
    for cand in candidates:
        base = cand - seed.script_offset
        if base < 0:
            continue
        ok, _errs = verify_base(bin_data, base)
        if ok:
            confirmed_bases.append(base)
            print(f"  CONFIRMED base = 0x{base:08X} "
                  f"(via giveItem at 0x{cand:08X})")

    if not confirmed_bases:
        print()
        print("ERROR: no Section_51 base candidate verified.")
        print("The .bin may use a different bytecode encoding, or the")
        print("script offsets may differ from the SLUS-01032 USA build.")
        return 1

    print()
    print("=" * 72)
    print(f"Patch-table literal for {len(confirmed_bases)} confirmed "
          f"Section_51 ROM copy/copies")
    print("=" * 72)
    print()
    print("    ROM_ARENA_SECTION_51_BASES: Final[tuple[int, ...]] = (")
    for base in confirmed_bases:
        print(f"        0x{base:08X},")
    print("    )")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bin_path", type=Path,
                        help="Path to the DW1 USA .bin (Mode 2/2352).")
    args = parser.parse_args(argv)

    if not args.bin_path.is_file():
        print(f"ERROR: {args.bin_path} is not a file", file=sys.stderr)
        return 2

    bin_data = args.bin_path.read_bytes()
    return report(bin_data)


if __name__ == "__main__":
    sys.exit(main())
