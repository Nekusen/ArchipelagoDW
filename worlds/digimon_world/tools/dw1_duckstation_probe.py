"""Diagnostic probe for the Duckstation client transport.

Run with DuckStation already open:

    python worlds/digimon_world/tools/dw1_duckstation_probe.py

Reports:

* every process whose basename contains ``"duck"`` (so we can see
  what DuckStation calls its exe on this user's install);
* for the first one that matches, the first 256 names in its PE
  export table (so we can confirm ``"RAM"`` is published, or see
  what symbol it ships as instead);
* the resolved PSX MainRAM base address if the ``RAM`` export is
  found.

The :mod:`worlds.digimon_world.adapters.duckstation_adapter` does all
of this silently and fails ``connect()`` on any miss; the probe just
makes the misses visible.
"""

from __future__ import annotations

import os
import struct
import sys


def main() -> int:
    try:
        import pymem
        import pymem.process
    except ImportError:
        print("pymem is not installed. Run: python ModuleUpdate.py --yes")
        return 2

    # 1. Process search.
    candidates: list[str] = []
    for proc in pymem.process.list_processes():
        try:
            name = proc.szExeFile
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="replace")
        except AttributeError:
            continue
        if "duck" in name.lower():
            candidates.append(name)

    if not candidates:
        print("No process containing 'duck' in its name is running.")
        print("Open DuckStation and try again. If the executable is named")
        print("something unusual, set DW1_DUCKSTATION_PROCESS=<basename>.")
        return 1

    print("Candidate DuckStation processes:")
    for c in candidates:
        print(f"  - {c}")
    target = candidates[0]
    print(f"\nUsing: {target!r}")

    # 2. Attach.
    try:
        pm = pymem.Pymem(target)
    except Exception as exc:
        print(f"\nFAILED to attach via pymem: {exc}")
        return 1

    # 3. Find the module by basename match.
    module = None
    needle = target.lower()
    for m in pm.list_modules():
        name = getattr(m, "name", None) or getattr(m, "filename", "")
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        if needle in name.lower() or name.lower().endswith(needle):
            module = m
            break
    if module is None:
        print(f"\nFAILED to find a module whose name contains {target!r}")
        return 1
    base = int(getattr(module, "lpBaseOfDll", None) or module.base_address)
    print(f"Module base: 0x{base:016X}")

    # 4. Walk the PE export table.
    dos = pm.read_bytes(base, 0x40)
    if dos[:2] != b"MZ":
        print("Module base is not a valid PE image (no 'MZ' signature).")
        return 1
    e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]
    if pm.read_bytes(base + e_lfanew, 4) != b"PE\x00\x00":
        print("No 'PE' signature at e_lfanew.")
        return 1

    optional_start = base + e_lfanew + 4 + 20
    magic = struct.unpack_from("<H", pm.read_bytes(optional_start, 2), 0)[0]
    is_pe32_plus = magic == 0x20B
    export_dir_off = 112 if is_pe32_plus else 96
    export_rva, export_size = struct.unpack_from(
        "<II", pm.read_bytes(optional_start + export_dir_off, 8), 0,
    )
    if export_rva == 0:
        print("Module has no export directory.")
        return 1

    export_dir = pm.read_bytes(base + export_rva, 40)
    (_chars, _tds, _maj, _min, _name_rva, _ordinal_base,
     num_funcs, num_names, addr_of_funcs, addr_of_names,
     addr_of_ordinals) = struct.unpack_from("<IIHHIIIIIII", export_dir, 0)

    print(f"Export directory: {num_names} named exports (of {num_funcs} total)")

    if num_names == 0:
        print("No named exports.")
        return 1

    name_rvas = struct.unpack_from(
        f"<{num_names}I",
        pm.read_bytes(base + addr_of_names, 4 * num_names),
    )
    name_ordinals = struct.unpack_from(
        f"<{num_names}H",
        pm.read_bytes(base + addr_of_ordinals, 2 * num_names),
    )

    # Dump first 256 names so the user can confirm what's published.
    print("\nFirst 256 exported names (alphabetic order DuckStation chose):")
    ram_index: int | None = None
    for i, rva in enumerate(name_rvas[:256]):
        raw = pm.read_bytes(base + rva, 64)
        nul = raw.find(b"\x00")
        name = raw[:nul] if nul >= 0 else raw
        try:
            decoded = name.decode("ascii")
        except UnicodeDecodeError:
            decoded = repr(name)
        print(f"  {i:4d}: {decoded}")
        if decoded == "RAM":
            ram_index = i

    if num_names > 256:
        print(f"  ... ({num_names - 256} more)")

    # 5. If "RAM" was in the first 256, resolve its target pointer.
    if ram_index is not None:
        ordinal = name_ordinals[ram_index]
        func_rva = struct.unpack_from(
            "<I",
            pm.read_bytes(base + addr_of_funcs + 4 * ordinal, 4),
        )[0]
        export_va = base + func_rva
        print(f"\n'RAM' export found at VA 0x{export_va:016X}")
        ram_ptr_bytes = pm.read_bytes(export_va, 8)
        ram_ptr = struct.unpack("<Q", ram_ptr_bytes)[0]
        print(f"  Pointer value: 0x{ram_ptr:016X}")
        if ram_ptr == 0:
            print("  -> null. Load a game inside DuckStation, then re-run.")
        else:
            print("  -> PSX MainRAM lives here. Adapter should connect fine.")
    else:
        # The whole name list still might have "RAM" further down,
        # but printing 100k names is unhelpful. Scan all of them
        # quickly without printing, and report whether it's present.
        full_idx: int | None = None
        for i, rva in enumerate(name_rvas):
            raw = pm.read_bytes(base + rva, 64)
            nul = raw.find(b"\x00")
            if (raw[:nul] if nul >= 0 else raw) == b"RAM":
                full_idx = i
                break
        if full_idx is not None:
            print(f"\n'RAM' export found at index {full_idx} (past the dump's 256-name limit).")
        else:
            print("\n'RAM' export is NOT present in this DuckStation build.")
            print("This is the most likely cause of the 'Waiting for Duckstation' hang.")
            print("Most exports DuckStation publishes for tooling look like")
            print("'_RAM' / 'g_ram' / etc. — check the dump above and tell me")
            print("which name(s) look like emulator RAM accessors.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
