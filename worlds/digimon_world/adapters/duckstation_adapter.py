"""Duckstation transport adapter via process memory hooking.

Mirrors the mechanism used by Archipelago.Core's
:file:`DuckstationMemoryHelper.cs` (the same library MMLAP and DWAP
build on top of):

1. Find the running ``duckstation.exe`` process by name.
2. Get the base address of the ``duckstation.exe`` module.
3. Walk the PE export table to find the ``RAM`` exported symbol —
   DuckStation deliberately exports this for tooling.
4. Read 8 bytes at that export address; that's a pointer to the
   currently allocated PSX MainRAM base in DuckStation's process.
5. All subsequent reads/writes are ``ram_base + offset`` where
   ``offset`` is the bare PSX physical address we already store in
   :mod:`worlds.digimon_world.data.addresses` (same convention as the
   BizHawk adapter's ``MainRAM`` domain).

Windows-only — Duckstation builds for Linux/macOS exist but the
``pymem`` library + PE export walk is Windows-specific. Future
work could add ``/proc/$pid/mem`` and ELF symbol parsing.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
from collections.abc import Sequence

from .base import (
    EmulatorAdapter,
    NotConnectedError,
    RequestFailedError,
)

logger = logging.getLogger("Client")

# Mirror of BizHawk's domain name for PSX main RAM. The Duckstation
# adapter accepts the string for source compatibility but only treats
# ``MainRAM`` as valid.
_MAIN_RAM = "MainRAM"

# We match the running emulator by substring (case-insensitive) so a
# variety of DuckStation builds work without configuration:
#
#   duckstation.exe                          (current stable)
#   duckstation-qt-x64-ReleaseLTCG.exe       (dev builds before unification)
#   duckstation-x64.exe                      (older releases)
#   duckstation-nogui-x64.exe                (headless variant)
#
# The user can override with the DW1_DUCKSTATION_PROCESS env var if
# they have a custom build whose name doesn't contain "duckstation".
_DUCKSTATION_PROCESS_SUBSTRING = "duckstation"
# Export the helper looks up. DuckStation publishes a single ``RAM``
# symbol whose target is a pointer to the live PSX MainRAM.
_RAM_EXPORT = "RAM"

# PSX MainRAM is 2 MiB. Any read/write that would cross the upper
# bound is almost certainly a bug (either a stale address or an
# uninitialised pointer) so we hard-guard against it instead of
# letting it scribble on whatever's next in DuckStation's heap.
_PSX_RAM_SIZE = 0x00200000


class DuckstationAdapter(EmulatorAdapter):
    """Process-memory-hook adapter for DuckStation.

    Single-shot connection: opens a handle to the running emulator
    and resolves the PSX MainRAM pointer once at connect time. The
    pointer can shift if the user closes and reopens the game inside
    DuckStation, so :meth:`ping` re-resolves it on every call and
    raises :class:`RequestFailedError` if the export vanishes (which
    means DuckStation exited).
    """

    name = "duckstation"

    def __init__(self) -> None:
        if sys.platform != "win32":
            # We construct the adapter unconditionally in launcher.py
            # so the Launcher can list the component everywhere, but
            # connect() will refuse on non-Windows until/unless the
            # /proc/$pid/mem + ELF path is implemented.
            self._supported = False
        else:
            self._supported = True
        self._pm = None  # pymem.Pymem instance, lazy-initialised
        self._ram_base: int | None = None
        self._exe_name: str | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        if not self._supported:
            return False
        try:
            import pymem
        except ImportError:
            logger.info("pymem is not installed — Duckstation client unavailable")
            return False

        # 1. Locate a process whose name matches our substring.
        exe_name = _find_duckstation_process()
        if exe_name is None:
            # Don't log the misses individually — the watcher loop
            # retries on every tick; spamming the log is unhelpful.
            return False

        # 2. Attach via pymem.
        try:
            pm = pymem.Pymem(exe_name)
        except pymem.exception.ProcessNotFound:
            return False
        except Exception as exc:
            logger.info(f"Could not attach to {exe_name!r}: {exc}")
            return False

        # 3. Resolve the RAM pointer via the PE export table.
        try:
            ram_base = _resolve_psx_ram_base(pm, exe_name)
        except _PeExportLookupError as exc:
            # Process is up but the RAM export couldn't be resolved
            # (mismatched DuckStation build, no game loaded yet, etc.).
            # Log once per cause so a recurrent issue is visible.
            logger.info(f"Duckstation attach failed: {exc}")
            try:
                pm.close_process()
            except Exception:
                pass
            return False

        logger.info(
            f"Duckstation attached: process={exe_name!r}, RAM base=0x{ram_base:016X}"
        )
        self._pm = pm
        self._ram_base = ram_base
        self._exe_name = exe_name
        return True

    async def disconnect(self) -> None:
        if self._pm is not None:
            try:
                self._pm.close_process()
            except Exception:
                pass
        self._pm = None
        self._ram_base = None
        self._exe_name = None

    def is_connected(self) -> bool:
        return self._pm is not None and self._ram_base is not None

    # ------------------------------------------------------------------
    # Per-frame requests
    # ------------------------------------------------------------------

    async def ping(self) -> None:
        if self._pm is None or self._exe_name is None:
            raise NotConnectedError("DuckstationAdapter is not connected")
        # Re-resolve the RAM pointer each ping. Cheap (one
        # ReadProcessMemory call) and catches the case where the user
        # closed and reopened a game inside DuckStation, which moves
        # the live PSX RAM allocation.
        try:
            self._ram_base = _resolve_psx_ram_base(self._pm, self._exe_name)
        except _PeExportLookupError as exc:
            await self.disconnect()
            raise RequestFailedError(str(exc)) from exc
        except Exception as exc:
            await self.disconnect()
            raise RequestFailedError(str(exc)) from exc

    async def read(
        self,
        reads: Sequence[tuple[int, int, str]],
    ) -> list[bytes]:
        if self._pm is None or self._ram_base is None:
            raise NotConnectedError("DuckstationAdapter is not connected")

        out: list[bytes] = []
        try:
            for addr, size, domain in reads:
                _ensure_main_ram(domain)
                _ensure_in_bounds(addr, size)
                out.append(self._pm.read_bytes(self._ram_base + addr, size))
        except Exception as exc:
            raise RequestFailedError(f"DuckStation read failed: {exc}") from exc
        return out

    async def write(
        self,
        writes: Sequence[tuple[int, Sequence[int], str]],
    ) -> None:
        if self._pm is None or self._ram_base is None:
            raise NotConnectedError("DuckstationAdapter is not connected")

        try:
            for addr, value, domain in writes:
                _ensure_main_ram(domain)
                data = bytes(b & 0xFF for b in value)
                _ensure_in_bounds(addr, len(data))
                self._pm.write_bytes(self._ram_base + addr, data, len(data))
        except Exception as exc:
            raise RequestFailedError(f"DuckStation write failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    async def get_system(self) -> str:
        # DuckStation is PSX-only; synthesise the BizHawk-style label
        # so the client's "PSX" check passes uniformly.
        return "PSX"

    async def get_hash(self) -> str | None:
        # DuckStation exposes no ROM hash through the process. The
        # client treats ``None`` as "skip the hash check".
        return None


# =============================================================================
# Internals
# =============================================================================


class _PeExportLookupError(RuntimeError):
    """Raised when ``duckstation.exe`` doesn't expose a usable
    ``RAM`` export at the expected location.

    Causes we accept and retry on:

    * DuckStation is launched but the user hasn't loaded a game yet
      (the RAM allocation is still null).
    * A future build dropped the export. We log and refuse to
      connect.
    """


def _ensure_main_ram(domain: str) -> None:
    if domain != _MAIN_RAM:
        raise RequestFailedError(
            f"DuckstationAdapter only supports the {_MAIN_RAM!r} domain; "
            f"got {domain!r}"
        )


def _ensure_in_bounds(addr: int, size: int) -> None:
    if addr < 0 or size < 0 or addr + size > _PSX_RAM_SIZE:
        raise RequestFailedError(
            f"PSX RAM access out of bounds: addr=0x{addr:08X}, size={size}"
        )


def _find_duckstation_process() -> str | None:
    """Enumerate processes and return the basename of the first one
    whose name contains ``"duckstation"`` (case-insensitive), or
    matches the ``DW1_DUCKSTATION_PROCESS`` env var if set.

    Returns ``None`` if no candidate is running.
    """

    try:
        import pymem.process
    except ImportError:
        return None

    override = os.environ.get("DW1_DUCKSTATION_PROCESS", "").strip().lower()
    needle = override or _DUCKSTATION_PROCESS_SUBSTRING

    try:
        # list_processes() yields PROCESSENTRY32W structs.
        for proc in pymem.process.list_processes():
            try:
                name = proc.szExeFile
                if isinstance(name, bytes):
                    name = name.decode("utf-8", errors="replace")
            except AttributeError:
                continue
            if needle in name.lower():
                return name
    except Exception:
        return None
    return None


def _resolve_psx_ram_base(pm, exe_name: str) -> int:
    """Look up the ``RAM`` export on the DuckStation module and read
    the pointer it advertises.

    Returns the live PSX MainRAM base address inside DuckStation's
    process. Raises :class:`_PeExportLookupError` if the export is
    missing or the pointer is null.
    """

    module = _module_by_name(pm, exe_name)
    if module is None:
        raise _PeExportLookupError(
            f"DuckStation process has no module matching {exe_name!r}"
        )

    export_va = _find_export_va(pm, module, _RAM_EXPORT)
    if export_va == 0:
        raise _PeExportLookupError(
            f"DuckStation module {exe_name!r} exposes no {_RAM_EXPORT!r} export "
            f"(non-stenzek build, or a build with exports stripped?)"
        )

    # The export points to a void* in the module's data section.
    # Read 8 bytes (x64 pointer width) to get the live PSX RAM base.
    raw = pm.read_bytes(export_va, 8)
    ram_base = struct.unpack("<Q", raw)[0]
    if ram_base == 0:
        raise _PeExportLookupError(
            "DuckStation RAM pointer is null — game not loaded yet?"
        )
    return ram_base


def _module_by_name(pm, module_name: str):
    """Return the pymem-style module info object matching
    ``module_name`` (case-insensitive), or ``None`` if not found.
    """

    target = module_name.lower()
    for mod in pm.list_modules():
        # pymem's list_modules() yields MODULEINFO-like objects with
        # ``.name`` (Windows API encodes as bytes; pymem normally
        # decodes to str, but be defensive).
        name = getattr(mod, "name", None) or getattr(mod, "filename", "")
        if isinstance(name, bytes):
            name = name.decode("utf-8", errors="replace")
        if name.lower().endswith(target) or name.lower() == target:
            return mod
    return None


def _find_export_va(pm, module, export_name: str) -> int:
    """Walk the PE export table of ``module`` and return the virtual
    address of ``export_name``, or 0 if not found.

    Implementation: parse the in-memory PE header (DOS stub → PE
    signature → optional header → export directory entry) using
    :class:`ctypes.Structure` definitions matching Microsoft's PE
    spec. We do not depend on the ``pefile`` package — DuckStation
    only ships one export of interest, the parsing fits in <100
    lines, and that's one fewer pip dependency.
    """

    base = int(module.lpBaseOfDll) if hasattr(module, "lpBaseOfDll") else int(module.base_address)
    # Read the DOS header (first 64 bytes) and grab e_lfanew (offset
    # to the PE header at +60).
    dos = pm.read_bytes(base, 0x40)
    if dos[:2] != b"MZ":
        return 0
    e_lfanew = struct.unpack_from("<I", dos, 0x3C)[0]

    # PE signature (4 bytes "PE\0\0") + COFF header (20 bytes) +
    # optional header. The export directory lives in the optional
    # header's data-directories array, entry 0.
    nt_signature = pm.read_bytes(base + e_lfanew, 4)
    if nt_signature != b"PE\x00\x00":
        return 0

    # COFF header: Machine(2) NumberOfSections(2) TimeDateStamp(4)
    # PointerToSymbolTable(4) NumberOfSymbols(4) SizeOfOptionalHeader(2)
    # Characteristics(2) = 20 bytes.
    coff_hdr = pm.read_bytes(base + e_lfanew + 4, 20)
    machine, _num_sections, _tds, _pst, _nsym, size_optional, _chars = struct.unpack_from(
        "<HHIIIHH", coff_hdr, 0,
    )
    # PE32+ (x64) magic = 0x20B at the start of the optional header;
    # PE32 (x86) magic = 0x10B. DuckStation ships as x64 on Windows.
    optional_start = base + e_lfanew + 4 + 20
    magic = struct.unpack_from("<H", pm.read_bytes(optional_start, 2), 0)[0]
    is_pe32_plus = magic == 0x20B

    # The export data directory entry lives at offset 96 in PE32+
    # optional headers, 92 in PE32. Each entry is 8 bytes
    # (VirtualAddress + Size); we only care about VirtualAddress.
    export_dir_off = 112 if is_pe32_plus else 96
    if export_dir_off + 8 > size_optional:
        return 0
    export_dir_entry = pm.read_bytes(optional_start + export_dir_off, 8)
    export_rva, export_size = struct.unpack_from("<II", export_dir_entry, 0)
    if export_rva == 0 or export_size < 40:
        return 0

    # Export directory layout (IMAGE_EXPORT_DIRECTORY):
    #   u32 Characteristics
    #   u32 TimeDateStamp
    #   u16 MajorVersion
    #   u16 MinorVersion
    #   u32 Name                  (RVA of module name string)
    #   u32 Base                  (ordinal base, usually 1)
    #   u32 NumberOfFunctions
    #   u32 NumberOfNames
    #   u32 AddressOfFunctions    (RVA of function-RVA array)
    #   u32 AddressOfNames        (RVA of name-RVA array)
    #   u32 AddressOfNameOrdinals (RVA of name->function ordinal array)
    export_dir = pm.read_bytes(base + export_rva, 40)
    (_chars, _tds, _maj, _min, _name_rva, _ordinal_base,
     _num_funcs, num_names, addr_of_funcs, addr_of_names,
     addr_of_ordinals) = struct.unpack_from("<IIHHIIIIIII", export_dir, 0)

    if num_names == 0:
        return 0

    # Read the three parallel arrays in one shot each.
    name_rvas = struct.unpack_from(
        f"<{num_names}I",
        pm.read_bytes(base + addr_of_names, 4 * num_names),
    )
    name_ordinals = struct.unpack_from(
        f"<{num_names}H",
        pm.read_bytes(base + addr_of_ordinals, 2 * num_names),
    )

    target = export_name.encode("ascii")
    for i, name_rva in enumerate(name_rvas):
        # Read up to 64 bytes — DuckStation's "RAM" is 3 bytes; even
        # an export like "GetProcAddress" only needs ~16.
        raw = pm.read_bytes(base + name_rva, 64)
        nul = raw.find(b"\x00")
        if nul >= 0:
            raw = raw[:nul]
        if raw == target:
            ordinal = name_ordinals[i]
            func_rva = struct.unpack_from(
                "<I",
                pm.read_bytes(base + addr_of_funcs + 4 * ordinal, 4),
            )[0]
            return base + func_rva
    return 0
