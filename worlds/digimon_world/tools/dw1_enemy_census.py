"""Census of every field Digimon (wild and story) defined in the game's .MAP files.

Each screen's ``.MAP`` file carries, after the 0x78-byte MAP_WARPS block, a ``s16 count``
followed by one record per Digimon entity the screen can host.  ``loadMapDigimon``
(SLUS 0x800B5D0C) copies those records into ``MAP_DIGIMON_TABLE`` / ``NPC_ENTITIES`` when
the screen loads, and a battle uses the NPC entity's stats verbatim.  Record layout (all
``s16`` unless noted, index = s16 index):

    0      type (DIGIMON_DATA index)             1  table byte (+0x18)
    2..4   pos x/y/z                              5..7  rotation x/y/z
    8      table +0x10                             9, 10  NPC bytes (+0x74, +0x75 = scriptId)
    11 hp  12 mp  13 curHP  14 curMP  15 off  16 def  17 spd  18 brn  19 bits
    20 chargeMode  21 NPC +0x72
    22..25 moves[4] (anim slot 0x2E+k or 0xFF)   26..29 movesPrio[4]
    30..32 flee vector                             33  waypoint count N
    then 8 s16 (table +0x84) and N x 3 s16 waypoints

Reads the vanilla disc through the ISO9660 file table (cached in ``work/dw1_re/iso_files.json``,
rebuilt from the disc when missing) and the SLUS image in ``work/dw1_re/`` for MAP_ENTRIES /
DIGIMON_DATA / MOVE_NAMES.  Output: ``work/dw1_re/enemy_census.tsv`` plus a per-screen summary
on stdout.  Game-derived output stays under ``work/`` (gitignored).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import struct
import sys

REPO = pathlib.Path(__file__).resolve().parents[3]
WORK = REPO / "work" / "dw1_re"
SLUS_PATH = WORK / "SLUS_010.32"
ISO_TABLE = WORK / "iso_files.json"
BIN_PATH = REPO / "Digimon World (USA).bin"

SLUS_BASE = 0x80090800
SLUS_HEADER = 0x800
SECTOR = 2352
USER = 2048

MAP_ENTRIES = 0x801292D4      # 255 x 16
DIGIMON_DATA = 0x8012CEB4     # 180 x 52
MOVE_NAMES = 0x80126054       # char *[]
NUM_DIGIMON = 180
NUM_MOVES = 0x3A + 4          # MOVE_DATA has 0x7A0 / 20 = 98 entries; names for the first ~62
RECORD_S16 = 0x22
TAIL_S16 = 8

STAT_NAMES = ("hp", "mp", "curhp", "curmp", "off", "def", "spd", "brn", "bits")


def slus_bytes(slus: bytes, ram: int, size: int) -> bytes:
    off = ram - SLUS_BASE + SLUS_HEADER
    return slus[off:off + size]


def cstr(slus: bytes, ram: int) -> str:
    raw = slus_bytes(slus, ram, 64)
    return raw.split(b"\0", 1)[0].decode("latin1")


def load_map_entries(slus: bytes) -> list[tuple[str, int, int, int]]:
    out = []
    for i in range(255):
        rec = slus_bytes(slus, MAP_ENTRIES + i * 16, 16)
        name = rec[:10].split(b"\0", 1)[0].decode("latin1")
        n8, n4, flags = rec[10], rec[11], rec[12]
        out.append((name, n8, n4, flags))
    return out


def load_digimon_data(slus: bytes) -> list[dict]:
    out = []
    for i in range(NUM_DIGIMON):
        rec = slus_bytes(slus, DIGIMON_DATA + i * 52, 52)
        name = rec[:20].split(b"\0", 1)[0].decode("latin1")
        bone, radius, height = struct.unpack_from("<ihh", rec, 20)
        ptype, level = rec[28], rec[29]
        special = tuple(rec[30:33])
        drop_item, drop_chance = rec[33], rec[34]
        moves = tuple(rec[35:51])
        out.append({"id": i, "name": name, "type": ptype, "level": level, "special": special,
                    "drop_item": drop_item, "drop_chance": drop_chance, "moves": moves,
                    "radius": radius, "height": height, "bones": bone})
    return out


def load_move_names(slus: bytes) -> list[str]:
    names = []
    for i in range(NUM_MOVES):
        ptr = struct.unpack_from("<I", slus_bytes(slus, MOVE_NAMES + i * 4, 4))[0]
        if not (0x80090800 <= ptr < 0x80200000):
            break
        names.append(cstr(slus, ptr))
    return names


MOVE_DATA = 0x8012623C        # Move[122] x 16 B: i32 distance, i16 power, u8 mpCost, iframes, range,
NUM_MOVE_DATA = 122           # special (element), status, accuracy, statusChance, 3 unknown


def load_move_data(slus: bytes) -> list[dict]:
    """Every technique: id, name (MOVE_NAMES has 121 entries; the rest fall back to ``techNN``),
    power, MP cost, element and status class."""
    out = []
    for i in range(NUM_MOVE_DATA):
        ptr = struct.unpack_from("<I", slus_bytes(slus, MOVE_NAMES + i * 4, 4))[0]
        name = cstr(slus, ptr) if 0x80090800 <= ptr < 0x80200000 else f"tech{i:02X}"
        rec = slus_bytes(slus, MOVE_DATA + i * 16, 16)
        _distance, power, mp_cost, _iframes, rng, element, status = struct.unpack_from("<ihBBBBB", rec, 0)
        out.append({"id": i, "name": name, "power": power, "mp": mp_cost, "range": rng,
                    "element": element, "status": status})
    return out


def read_disc_file(binf, lba: int, size: int) -> bytes:
    chunks = []
    for s in range((size + USER - 1) // USER):
        binf.seek((lba + s) * SECTOR + 24)
        chunks.append(binf.read(USER))
    return b"".join(chunks)[:size]


def walk_iso_tree(binf) -> list[tuple[int, int, str]]:
    """Every file on the disc as ``(lba, size, "/DIR/NAME.EXT")`` from the ISO9660 directory tree."""

    def walk(lba: int, size: int, path: str, acc: list) -> None:
        data = read_disc_file(binf, lba, (size + USER - 1) // USER * USER)
        pos = 0
        while pos < len(data):
            length = data[pos]
            if length == 0:
                pos = (pos // USER + 1) * USER
                continue
            rec = data[pos:pos + length]
            entry_lba = struct.unpack_from("<I", rec, 2)[0]
            entry_size = struct.unpack_from("<I", rec, 10)[0]
            flags, name_len = rec[25], rec[32]
            name = rec[33:33 + name_len].decode("latin1")
            if name not in ("\x00", "\x01"):
                full = f"{path}/{name.split(';')[0]}"
                if flags & 2:
                    walk(entry_lba, entry_size, full, acc)
                else:
                    acc.append((entry_lba, entry_size, full))
            pos += length

    pvd = read_disc_file(binf, 16, USER)
    root_lba = struct.unpack_from("<I", pvd, 158)[0]
    root_size = struct.unpack_from("<I", pvd, 166)[0]
    files: list[tuple[int, int, str]] = []
    walk(root_lba, root_size, "", files)
    return sorted(files)


def load_iso_table(bin_path: str) -> dict[str, tuple[int, int]]:
    if ISO_TABLE.exists():
        rows = json.load(open(ISO_TABLE))
    else:
        with open(bin_path, "rb") as binf:
            rows = walk_iso_tree(binf)
        ISO_TABLE.parent.mkdir(parents=True, exist_ok=True)
        json.dump(rows, open(ISO_TABLE, "w"))
    return {name: (lba, size) for lba, size, name in rows}


def parse_map(data: bytes, n8: int, n4: int) -> tuple[int, list[dict]]:
    """Return (entity section offset, records)."""
    idx = 1 + n8 + n4 + (1 if (n8 or n4) else 0)
    ent_off = struct.unpack_from("<I", data, idx * 4)[0]
    pos = ent_off + 0x78
    count = struct.unpack_from("<h", data, pos)[0]
    pos += 2
    recs = []
    for slot in range(count):
        base = pos
        vals = struct.unpack_from(f"<{RECORD_S16}h", data, pos)
        pos += RECORD_S16 * 2
        pos += TAIL_S16 * 2
        n_wp = vals[0x21]
        pos += n_wp * 6
        recs.append({"slot": slot, "offset": base, "type": vals[0], "pos": vals[2:5],
                     "script_id": vals[10] & 0xFF, "stats": vals[0xB:0x14],
                     "charge": vals[0x14], "moves": tuple(v & 0xFF for v in vals[0x16:0x1A]),
                     "prio": tuple(v & 0xFF for v in vals[0x1A:0x1E]), "waypoints": n_wp})
    return ent_off, recs


MAPHEAD_LBA = 142982     # /SCN/MAPHEAD.SCN -- the boot-resident map-head script (getScript(0))
MAPHEAD_SIZE = 24686
OP_LOAD_DIGIMON = 0x46   # 46 XX          loadDigimon XX
OP_SET_DIGIMON = 0x47    # 47 XX ss aa    setDigimon XX slot autotalk
DUMP_PATH = REPO / "references" / "digimon_world_randomizer" / "script" / "DW1Script.txt"


def parse_maphead_sites(maphead: bytes, records_by_map: dict[int, list[dict]]) -> list[tuple[int, int, int, int, int]]:
    """Scan every screen section of MAPHEAD.SCN for its loadDigimon / setDigimon opcodes.

    Section table: ``[u16 table_end][{u16 section_id, u16 offset} x N][FF FF]``; section id == screen id
    for ids < 255.  The scan is validated rather than disassembled: a ``47 XX ss aa`` only counts when
    the screen's record ``ss`` really is species ``XX`` (that is the guard ``scriptSetDigimon`` itself
    applies), and a ``46 XX`` only when ``XX`` is a species the screen's records use.  ``--check-dump``
    compares the result against the reference disassembly.  Returns ``(map, offset, kind, species, slot)``
    with kind 0 = loadDigimon (slot -1), 1 = setDigimon.
    """
    table_end = struct.unpack_from("<H", maphead, 0)[0]
    entries = [struct.unpack_from("<HH", maphead, 2 + 4 * i) for i in range((table_end - 4) // 4)]
    assert maphead[2 + 4 * len(entries):4 + 4 * len(entries)] == b"\xff\xff", "MAPHEAD section table terminator"
    bounds = sorted({off for _, off in entries} | {len(maphead)})
    sites = []
    for section, off in entries:
        if section >= 255 or section not in records_by_map:
            continue
        end = bounds[bounds.index(off) + 1]
        types = {r["type"] for r in records_by_map[section]}
        slot_type = {r["slot"]: r["type"] for r in records_by_map[section]}
        pos = off
        while pos < end - 1:
            op, arg = maphead[pos], maphead[pos + 1]
            if op == OP_SET_DIGIMON and pos + 3 < end and slot_type.get(maphead[pos + 2]) == arg \
                    and maphead[pos + 3] in (0, 1):
                sites.append((section, pos, 1, arg, maphead[pos + 2]))
                pos += 4
                continue
            if op == OP_LOAD_DIGIMON and arg in types:
                sites.append((section, pos, 0, arg, -1))
                pos += 2
                continue
            pos += 1
    return sites


def check_dump(sites: list[tuple[int, int, int, int, int]]) -> int:
    """Lab check: the scanned sites must equal the reference disassembly's Script 0 opcodes."""
    import re
    text = DUMP_PATH.read_text(encoding="utf-8", errors="replace")
    script0 = text.split("== Script ID 1 ==", 1)[0]
    want = set()
    section = None
    for line in script0.splitlines():
        m = re.match(r"Section_(\d+):", line)
        if m:
            section = int(m.group(1))
            continue
        m = re.match(r"(\d+) loadDigimon (\d+)$", line)
        if m and section is not None and section < 255:
            want.add((section, int(m.group(1)), 0, int(m.group(2)), -1))
        m = re.match(r"(\d+) setDigimon (\d+) (\d+) (\d+)$", line)
        if m and section is not None and section < 255:
            want.add((section, int(m.group(1)), 1, int(m.group(2)), int(m.group(3))))
    got = set(sites)
    missing, extra = want - got, got - want
    print(f"dump check: {len(want)} opcodes in the disassembly, {len(got)} scanned, "
          f"{len(missing)} missing, {len(extra)} extra")
    for s in sorted(missing)[:20]:
        print("  missing", s)
    for s in sorted(extra)[:20]:
        print("  extra", s)
    return 0 if not missing and not extra else 1


def emit_python(path: str, digimon: list[dict], models: dict[int, int], rows: list[dict],
                sites: list[tuple[int, int, int, int, int]], moves: list[dict]) -> None:
    lines = [
        '"""Field-Digimon data for Digimon World 1 (SLUS-01032) -- GENERATED, do not edit by hand.',
        "",
        "Produced by ``tools/dw1_enemy_census.py --emit-python`` from the vanilla disc.  Four tables:",
        "",
        "* :data:`MOVES` -- one row per ``MOVE_DATA`` technique (122): ``(id, name, power, mp_cost, element,",
        "  status)``.  ``power`` is the damage base the battle uses (0 = buff / status-only move); ``element``",
        "  indexes the 7x7 affinity matrix the enemy AI and the partner's battle-learn check consult.",
        "* :data:`SPECIES` -- one row per ``DIGIMON_DATA`` entry (180): ``(id, name, level, moves16, heap)``.",
        "  ``moves16`` is the species' 16-slot technique list as a 32-char hex string (``ff`` = empty slot);",
        "  a field record's move byte ``0x2E + k`` selects slot ``k``.  ``heap`` is the malloc3 footprint of",
        "  the species' ``.MMD`` model (file size rounded up to 2 KB) -- the budget a substitute must fit in.",
        "* :data:`FIELD_RECORDS` -- one row per Digimon record in a screen's ``.MAP`` file (989):",
        "  ``(map, slot, bin_off, type, hp, mp, cur_hp, cur_mp, off, def, spd, brn, bits, m0..m3, p0..p3, script)``.",
        "  ``bin_off`` is the flat Mode2/2352 .bin offset of the record's first byte; field offsets are",
        "  ``FIELD_RECORD_*`` s16 indices (see ``data/addresses.py``) and must be resolved sector-aware.",
        "* :data:`MAPHEAD_SITES` -- every ``loadDigimon`` / ``setDigimon`` opcode of the boot-resident",
        "  MAPHEAD.SCN, per screen section: ``(map, file_off, kind, species, slot)`` with kind 0 =",
        "  loadDigimon (operand at ``file_off + 1``), kind 1 = setDigimon (operand at ``file_off + 1``,",
        "  slot at ``+2``).  Substituting a species on a screen rewrites both the record type and these",
        "  operands, or ``scriptSetDigimon`` refuses to place the entity.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Final",
        "",
        "MOVES: Final[tuple[tuple[int, str, int, int, int, int], ...]] = (",
    ]
    lines.extend(
        f"    ({m['id']}, {json.dumps(m['name'])}, {m['power']}, {m['mp']}, {m['element']}, {m['status']}),"
        for m in moves
    )
    lines.append(")")
    lines.append("")
    lines.append("SPECIES: Final[tuple[tuple[int, str, int, str, int], ...]] = (")
    for d in digimon:
        mv = bytes(d["moves"]).hex()
        lines.append(f"    ({d['id']}, {json.dumps(d['name'])}, {d['level']}, \"{mv}\", {models.get(d['id'], 0)}),")
    lines.append(")")
    lines.append("")
    lines.append("FIELD_RECORDS: Final[tuple[tuple[int, ...], ...]] = (")
    for r in rows:
        stats = ", ".join(str(r[k]) for k in STAT_NAMES)
        moves = ", ".join(str(int(m, 16)) for m in r["move_slots"].split(","))
        prio = ", ".join(r["prio"].split(","))
        line = (f"    ({r['map']}, {r['slot']}, 0x{r['bin_off']:X}, {r['type']}, {stats}, {moves}, {prio}, "
                f"{r['script_id']}),")
        if len(line) > 120:
            head, tail = line.rsplit(", ", 4)[0], ", ".join(line.rsplit(", ", 4)[1:])
            line = f"{head},\n     {tail}"
        lines.append(line)
    lines.append(")")
    lines.append("")
    lines.append("MAPHEAD_SITES: Final[tuple[tuple[int, int, int, int, int], ...]] = (")
    lines.extend(f"    ({s[0]}, {s[1]}, {s[2]}, {s[3]}, {s[4]})," for s in sorted(sites))
    lines.append(")")
    lines.append("")
    pathlib.Path(path).write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--bin", default=str(BIN_PATH))
    ap.add_argument("--out", default=str(WORK / "enemy_census.tsv"))
    ap.add_argument("--map", type=int, help="only this screen id")
    ap.add_argument("--emit-python", metavar="PATH", help="also write the world's data/enemy_records.py")
    ap.add_argument("--check-dump", action="store_true",
                    help="validate the MAPHEAD opcode scan against the reference script disassembly")
    args = ap.parse_args()

    slus = SLUS_PATH.read_bytes()
    entries = load_map_entries(slus)
    digimon = load_digimon_data(slus)
    move_names = load_move_names(slus)
    files = load_iso_table(args.bin)

    rows = []
    with open(args.bin, "rb") as binf:
        for map_id, (name, n8, n4, flags) in enumerate(entries):
            if not name or (args.map is not None and map_id != args.map):
                continue
            if not flags & 0x80:
                # loadMapDigimon only parses the section when MAP_ENTRIES.flags bit 7 is set.
                continue
            path = f"/MAP/MAP{map_id // 15 + 1}/{name}.MAP"
            if path not in files:
                print(f"map {map_id} {name}: {path} not on disc", file=sys.stderr)
                continue
            lba, size = files[path]
            data = read_disc_file(binf, lba, size)
            try:
                _, recs = parse_map(data, n8, n4)
            except struct.error as exc:
                print(f"map {map_id} {name}: parse error {exc}", file=sys.stderr)
                continue
            for r in recs:
                d = digimon[r["type"]] if r["type"] < NUM_DIGIMON else None
                mv = []
                for m in r["moves"]:
                    if m == 0xFF or d is None:
                        mv.append("-")
                    else:
                        tech = d["moves"][m - 0x2E] if 0x2E <= m < 0x3E else 0xFF
                        mv.append(move_names[tech] if tech < len(move_names) else f"tech{tech:02X}")
                bin_off = (lba + r["offset"] // USER) * SECTOR + 24 + r["offset"] % USER
                rows.append({
                    "map": map_id, "screen": name, "lba": lba, "flags": flags,
                    "slot": r["slot"], "file_off": r["offset"], "bin_off": bin_off,
                    "type": r["type"], "digimon": d["name"] if d else "?",
                    "level": d["level"] if d else -1, "ptype": d["type"] if d else -1,
                    "script_id": r["script_id"],
                    **dict(zip(STAT_NAMES, r["stats"], strict=True)),
                    "charge": r["charge"], "moves": ",".join(mv),
                    "move_slots": ",".join(f"{m:02X}" for m in r["moves"]),
                    "prio": ",".join(str(p) for p in r["prio"]), "waypoints": r["waypoints"],
                })

    cols = ["map", "screen", "lba", "flags", "slot", "file_off", "bin_off", "type", "digimon",
            "level", "ptype", "script_id", *STAT_NAMES, "charge", "moves", "move_slots", "prio",
            "waypoints"]
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\t".join(cols) + "\n")
        for r in rows:
            f.write("\t".join(str(r[c]) if not isinstance(r[c], int) or c not in ("file_off", "bin_off")
                              else f"0x{r[c]:X}" for c in cols) + "\n")
    print(f"{len(rows)} records across {len({r['map'] for r in rows})} screens -> {args.out}")

    if args.emit_python or args.check_dump:
        with open(args.bin, "rb") as binf:
            maphead = read_disc_file(binf, MAPHEAD_LBA, MAPHEAD_SIZE)
        by_map: dict[int, list[dict]] = {}
        for r in rows:
            by_map.setdefault(r["map"], []).append(r)
        sites = parse_maphead_sites(maphead, by_map)
        print(f"{len(sites)} MAPHEAD load/set sites across {len({s[0] for s in sites})} screens")
        if args.check_dump and check_dump(sites):
            return 1
        if args.emit_python:
            models = {}
            for d in digimon:
                ptr = struct.unpack_from("<I", slus_bytes(slus, 0x8011D19C + d["id"] * 4, 4))[0]
                code = cstr(slus, ptr)
                entry = files.get(f"/CHDAT/MMD{d['id'] // 30}/{code}.MMD")
                models[d["id"]] = ((entry[1] + 0x7FF) & ~0x7FF) if entry else 0
            emit_python(args.emit_python, digimon, models, rows, sites, load_move_data(slus))
            print(f"wrote {args.emit_python}")
    if args.map is not None:
        for r in rows:
            print(f"  slot {r['slot']:2d} @file 0x{r['file_off']:X} bin 0x{r['bin_off']:X}: "
                  f"{r['digimon']:<14} L{r['level']} hp {r['hp']} mp {r['mp']} off {r['off']} "
                  f"def {r['def']} spd {r['spd']} brn {r['brn']} bits {r['bits']} "
                  f"moves [{r['moves']}] prio [{r['prio']}] script {r['script_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
