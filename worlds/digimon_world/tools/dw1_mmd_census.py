"""Census of the animation table in every species' ``.MMD`` model file.

A field or partner Digimon plays technique slot ``k`` of its species (``DIGIMON_DATA[type].moves[k]``,
16 slots) through animation id ``0x2E + k`` (``entityGetTechFromAnim``).  ``startAnimation`` (SLUS
0x800C1A04, ASM-only upstream) resolves an animation id as ``table[id]``, where ``table`` is the u32
array at ``mmd + u32[1]`` of the species' model file (``loadMMD`` / ``applyMMD``).  Offsets are
relative to the table itself and ``0`` means "no such animation": ``startAnimation`` returns without
touching the entity.  The table carries no count -- it runs up to the first animation's data, so its
length is ``min(non-zero offset) / 4``; an id at or past that reads animation data as an offset.

For every ``DIGIMON_DATA`` species this script opens ``\\CHDAT\\MMD{id // 30}\\{code}.MMD`` (``code``
from the name table at 0x8011D19C) and reports how many animation entries the table has, which of the
16 technique ids 0x2E..0x3D carry a real animation, and how many technique slots ``DIGIMON_DATA``
populates.  Output: ``work/dw1_re/mmd_census.tsv`` plus a summary on stdout.  Reuses the loaders of
``dw1_enemy_census.py``; game-derived output stays under ``work/`` (gitignored).
"""

from __future__ import annotations

import argparse
import struct
import sys

try:
    from .dw1_enemy_census import (
        BIN_PATH,
        SLUS_PATH,
        WORK,
        cstr,
        load_digimon_data,
        load_iso_table,
        read_disc_file,
        slus_bytes,
    )
except ImportError:
    from dw1_enemy_census import (
        BIN_PATH,
        SLUS_PATH,
        WORK,
        cstr,
        load_digimon_data,
        load_iso_table,
        read_disc_file,
        slus_bytes,
    )

DIGIMON_FILE_NAMES = 0x8011D19C   # char *[180]: the 4-letter model code per species
TECH_ANIM_BASE = 0x2E             # animation id of technique slot 0
TECH_SLOTS = 16


def parse_mmd(data: bytes) -> tuple[int, int, int, list[int]]:
    """Return ``(model_off, table_off, header_u32_2, offsets)``; ``offsets[i]`` is table entry ``i``."""
    model_off, table_off, hdr2 = struct.unpack_from("<3I", data, 0)
    offsets: list[int] = []
    end = len(data) - table_off      # the table cannot extend past the lowest animation it points at
    while 4 * len(offsets) < end:
        off = struct.unpack_from("<I", data, table_off + 4 * len(offsets))[0]
        offsets.append(off)
        if off:
            end = min(end, off)
    return model_off, table_off, hdr2, offsets


def anim_frames(data: bytes, table_off: int, off: int) -> int:
    """Frame count of the animation at table offset ``off`` (first u16 of its stream; bit 15 flags a
    per-bone scale block in the initial pose)."""
    return struct.unpack_from("<H", data, table_off + off)[0] & 0x7FFF


def tech_entries(offsets: list[int]) -> list[int | None]:
    """Table entries for the 16 technique ids; ``None`` when the id lies past the table."""
    return [offsets[TECH_ANIM_BASE + k] if TECH_ANIM_BASE + k < len(offsets) else None
            for k in range(TECH_SLOTS)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--bin", default=str(BIN_PATH))
    ap.add_argument("--out", default=str(WORK / "mmd_census.tsv"))
    ap.add_argument("--species", type=int, help="also print this species' full animation table")
    args = ap.parse_args()

    slus = SLUS_PATH.read_bytes()
    digimon = load_digimon_data(slus)
    files = load_iso_table(args.bin)

    rows = []
    with open(args.bin, "rb") as binf:
        for d in digimon:
            ptr = struct.unpack_from("<I", slus_bytes(slus, DIGIMON_FILE_NAMES + d["id"] * 4, 4))[0]
            code = cstr(slus, ptr)
            # Species 62 (WereGarurumon, code "wEAG") and 114 (blank, "tAKA") are leftovers with no file on
            # the disc; the game's lookup (file.c, strcmp) could never load them either.
            path = f"/CHDAT/MMD{d['id'] // 30}/{code}.MMD"
            populated = [k for k in range(TECH_SLOTS) if d["moves"][k] != 0xFF]
            row = {"id": d["id"], "name": d["name"], "code": code, "path": path, "size": 0,
                   "model_off": 0, "table_off": 0, "hdr2": 0, "bones": d["bones"], "n_entries": 0,
                   "n_anims": 0, "tech_mask": "-" * TECH_SLOTS, "tech_frames": "", "n_tech_anims": 0,
                   "n_populated": len(populated), "populated_no_anim": "", "anim_no_tech": "",
                   "tech_dups": "", "beyond_tech": 0}
            rows.append(row)
            if path not in files:
                continue
            lba, size = files[path]
            data = read_disc_file(binf, lba, size)
            model_off, table_off, hdr2, offsets = parse_mmd(data)
            present = [i for i, o in enumerate(offsets) if o]
            tech = tech_entries(offsets)
            first_slot: dict[int, int] = {}
            dups = []
            for k, o in enumerate(tech):
                if o:
                    if o in first_slot:
                        dups.append(f"{k}={first_slot[o]}")
                    else:
                        first_slot[o] = k
            row.update({
                "size": size, "model_off": model_off, "table_off": table_off, "hdr2": hdr2,
                "n_entries": len(offsets), "n_anims": len(present),
                "tech_mask": "".join("A" if o else ("." if o == 0 else ">") for o in tech),
                "tech_frames": ",".join(str(anim_frames(data, table_off, o)) if o else "-" for o in tech),
                "n_tech_anims": sum(1 for o in tech if o),
                "populated_no_anim": ",".join(str(k) for k in populated if not tech[k]),
                "anim_no_tech": ",".join(str(k) for k in range(TECH_SLOTS) if tech[k] and k not in populated),
                "tech_dups": ",".join(dups),
                "beyond_tech": sum(1 for i in present if i >= TECH_ANIM_BASE + TECH_SLOTS),
            })
            if args.species == d["id"]:
                print(f"{d['name']} ({path}): {len(offsets)} entries, table @ 0x{table_off:X}")
                for i, o in enumerate(offsets):
                    slot = i - TECH_ANIM_BASE
                    tag = f"  tech slot {slot}" if 0 <= slot < TECH_SLOTS else ""
                    body = f"+0x{o:X} ({anim_frames(data, table_off, o)} frames)" if o else "-"
                    print(f"  anim 0x{i:02X}: {body}{tag}")

    cols = ["id", "name", "code", "path", "size", "model_off", "table_off", "hdr2", "bones", "n_entries",
            "n_anims", "tech_mask", "tech_frames", "n_tech_anims", "n_populated", "populated_no_anim",
            "anim_no_tech", "tech_dups", "beyond_tech"]
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(f"0x{r[c]:X}" if c in ("model_off", "table_off") else str(r[c])
                              for c in cols) + "\n")

    with_model = [r for r in rows if r["size"]]
    exact = [r for r in with_model if not r["anim_no_tech"] and not r["populated_no_anim"]]
    more = [r for r in with_model if r["anim_no_tech"]]
    fewer = [r for r in with_model if r["populated_no_anim"]]
    dups = [r for r in with_model if r["tech_dups"]]
    print(f"{len(rows)} species, {len(with_model)} with a model file -> {args.out}")
    for r in rows:
        if not r["size"]:
            print(f"    no model: {r['id']:3d} {r['name']:<16} {r['path']}")
    print(f"  table sizes: min {min(r['n_entries'] for r in with_model)}, "
          f"max {max(r['n_entries'] for r in with_model)}; "
          f"{sum(1 for r in with_model if r['beyond_tech'])} species with animations past id 0x3D")
    print(f"  technique animations == populated slots: {len(exact)}")
    print(f"  animations in EMPTY slots (room to grow): {len(more)}")
    for r in more:
        print(f"    {r['id']:3d} {r['name']:<16} populated {r['n_populated']:2d}, "
              f"extra animated slots {r['anim_no_tech']}")
    print(f"  populated slots WITHOUT an animation: {len(fewer)}")
    for r in fewer:
        print(f"    {r['id']:3d} {r['name']:<16} populated {r['n_populated']:2d}, "
              f"missing slots {r['populated_no_anim']}")
    print(f"  species whose technique slots share one animation: {len(dups)}")
    for r in dups:
        print(f"    {r['id']:3d} {r['name']:<16} {r['tech_dups']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
