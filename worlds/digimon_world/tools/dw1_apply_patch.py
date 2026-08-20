"""Apply one DW1 patch spec to live PCSX-Redux RAM, or to a .bin copy — same spec, both nets.

The patch-testing loop (see NEXT_PATCH_TEST_PLAN.md): iterate a ROM patch as live-RAM pokes
over a savestate (seconds per try), then generate ONE confirming .bin build from the same
spec. This tool is the single driver for both, so what was tested in RAM is byte-for-byte
what lands in the ISO.

Spec (JSON)::

    {
      "name": "recycle-shop-ap-builder",
      "patches": [
        { "ram": "0x800FA834", "words": [ 897581056, ... ], "note": "builder body" },
        { "ram": "0x801279F0", "hex": "0102...",            "note": "ext ITEM_PARA"  },
        { "bin": "0x14B8B698", "hex": "dd00",               "note": "raw bin patch"  }
      ]
    }

Each entry carries exactly one address key and one payload key:

* ``ram``  — KSEG0 (0x80xxxxxx) or physical (0x001xxxxx) main-RAM address. Applied to live
  RAM directly; translated to a sector-aware .bin offset via ``_slus_ram_to_bin_offset``
  for ISO mode (valid only for SLUS-image-resident addresses).
* ``bin``  — flat .bin offset (the convention of ``data/addresses.py`` ROM constants).
  ISO mode only; ``apply``/``verify`` reject it (no general bin->RAM inverse here).
* ``hex``  — byte payload as a hex string.  ``words`` — payload as a list of u32s,
  little-endian encoded (convenient for MIPS instruction words).

Modes::

    python dw1_apply_patch.py show   spec.json                 # resolve + list, no writes
    python dw1_apply_patch.py apply  spec.json                 # poke live RAM (REST)
    python dw1_apply_patch.py verify spec.json                 # read live RAM, diff vs spec
    python dw1_apply_patch.py to-iso spec.json src.bin dst.bin # patched copy + EDC recalc

ISO mode is sector-aware (Mode2/2352: writes skip the 0x18-byte sector headers when a
payload crosses a 2048-byte user-data boundary) and recomputes EDC/ECC for changed sectors
via ``data/edc.py`` — the same primitives the AP patcher uses.
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent
DATA_DIR = TOOLS_DIR.parent / "data"

KSEG0_BASE = 0x80000000
RAM_SIZE = 0x200000


def _load_data_package():
    """Load worlds/digimon_world/data as a synthetic package.

    Importing it the normal way would pull in ``worlds/__init__.py`` (the
    Archipelago world auto-discovery, i.e. every installed game). A synthetic
    package keeps the relative import inside ``edc.py`` working without that.
    """

    if "dw1data" not in sys.modules:
        spec = importlib.machinery.ModuleSpec("dw1data", None, is_package=True)
        pkg = importlib.util.module_from_spec(spec)
        pkg.__path__ = [str(DATA_DIR)]
        sys.modules["dw1data"] = pkg
    import importlib as _il
    addresses = _il.import_module("dw1data.addresses")
    edc = _il.import_module("dw1data.edc")
    return addresses, edc


def _load_redux_client():
    sys.path.insert(0, str(TOOLS_DIR))
    from dw1_redux_api import ReduxClient  # noqa: PLC0415
    return ReduxClient()


def _payload(entry: dict) -> bytes:
    if "hex" in entry:
        return bytes.fromhex(entry["hex"])
    if "words" in entry:
        out = bytearray()
        for w in entry["words"]:
            out += int(w).to_bytes(4, "little")
        return bytes(out)
    raise ValueError(f"entry has no payload (hex/words): {entry.get('note', entry)}")


def _ram_phys(entry: dict) -> int:
    addr = int(entry["ram"], 0) if isinstance(entry["ram"], str) else int(entry["ram"])
    phys = addr - KSEG0_BASE if addr >= KSEG0_BASE else addr
    if not 0 <= phys < RAM_SIZE:
        raise ValueError(f"RAM address out of range: {entry['ram']}")
    return phys


def load_spec(path: str) -> dict:
    with open(path, "r") as fh:
        spec = json.load(fh)
    for entry in spec["patches"]:
        _payload(entry)  # validate early
        if ("ram" in entry) == ("bin" in entry):
            raise ValueError(f"entry needs exactly one of ram/bin: {entry.get('note', entry)}")
    return spec


def cmd_show(spec: dict) -> int:
    addresses, _ = _load_data_package()
    for entry in spec["patches"]:
        data = _payload(entry)
        note = entry.get("note", "")
        if "ram" in entry:
            phys = _ram_phys(entry)
            try:
                bin_off = addresses._slus_ram_to_bin_offset(phys + KSEG0_BASE)
                bin_s = f"bin 0x{bin_off:09X}"
            except Exception:
                bin_s = "bin n/a"
            print(f"ram 0x{phys + KSEG0_BASE:08X} (phys 0x{phys:06X})  {bin_s}  {len(data):4d} B  {note}")
        else:
            print(f"bin 0x{int(entry['bin'], 0):09X}  {len(data):4d} B  {note}")
    return 0


def cmd_apply(spec: dict, verify_only: bool) -> int:
    client = _load_redux_client()
    failures = 0
    for entry in spec["patches"]:
        if "bin" not in entry:
            continue
        print(f"SKIP (bin-only entry, ISO mode only): {entry.get('note', entry['bin'])}")
    for entry in spec["patches"]:
        if "ram" not in entry:
            continue
        phys = _ram_phys(entry)
        data = _payload(entry)
        note = entry.get("note", "")
        if verify_only:
            live = client.peek(phys, len(data))
            ok = live == data
            print(f"{'OK  ' if ok else 'DIFF'} 0x{phys + KSEG0_BASE:08X} {len(data):4d} B  {note}")
            if not ok:
                failures += 1
                print(f"  spec: {data.hex()}")
                print(f"  live: {live.hex()}")
        else:
            client.poke(phys, data)
            print(f"POKED 0x{phys + KSEG0_BASE:08X} {len(data):4d} B  {note}")
    if verify_only:
        print("VERIFY: OK" if failures == 0 else f"VERIFY: {failures} mismatch(es)")
    return 1 if failures else 0


def cmd_to_iso(spec: dict, src: str, dst: str) -> int:
    addresses, edc = _load_data_package()
    src_p, dst_p = Path(src), Path(dst)
    if not src_p.is_file():
        print(f"source not found: {src}")
        return 1
    print(f"copying {src_p.name} -> {dst_p} ...")
    shutil.copyfile(src_p, dst_p)
    base_data = src_p.read_bytes()
    rom = bytearray(base_data)
    for entry in spec["patches"]:
        data = _payload(entry)
        note = entry.get("note", "")
        if "ram" in entry:
            bin_off = addresses._slus_ram_to_bin_offset(_ram_phys(entry) + KSEG0_BASE)
        else:
            bin_off = int(entry["bin"], 0)
        addresses.write_user_data_bytes(rom, bin_off, data)
        print(f"WROTE bin 0x{bin_off:09X} {len(data):4d} B  {note}")
    stats = edc.diff_recalc_in_place(rom, base_data, calc_form_2_edc=False)
    print(f"EDC recalc: {stats}")
    dst_p.write_bytes(rom)
    print(f"done: {dst_p} ({len(rom)} bytes)")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    mode, spec_path = argv[1], argv[2]
    spec = load_spec(spec_path)
    print(f"spec: {spec.get('name', spec_path)} ({len(spec['patches'])} entries)")
    if mode == "show":
        return cmd_show(spec)
    if mode == "apply":
        return cmd_apply(spec, verify_only=False)
    if mode == "verify":
        return cmd_apply(spec, verify_only=True)
    if mode == "to-iso":
        if len(argv) != 5:
            print("usage: dw1_apply_patch.py to-iso spec.json src.bin dst.bin")
            return 2
        return cmd_to_iso(spec, argv[3], argv[4])
    print(f"unknown mode: {mode}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
