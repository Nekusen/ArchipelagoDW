"""PSX Mode2 EDC/ECC recalculation, in-memory.

The EDC/ECC math here was originally written by **fdelduque** for the
SOTN APWorld (MIT). It was then carried into the FFT Ivalice Island
APWorld (also MIT) at ``worlds/fftii/ErrorRecalc.py``. This module
adapts the algorithm to work on a single ``bytearray`` already loaded
in memory — the FFT version drives EDC recalc off two file paths,
which is awkward inside an :class:`APPatchExtension` step where the
patched data is just bytes in flight.

Algorithm credit: fdelduque (MIT, via SOTN APWorld and FFT Ivalice
Island APWorld).

Sector geometry (from ``worlds.digimon_world.data.addresses``):

* ``SECTOR_SIZE_BYTES = 0x930`` (2352 bytes)
* ``SECTOR_HEADER_BYTES = 0x18`` (24 bytes — sync header + sector address + mode)
* ``USER_DATA_BYTES = 0x800`` (2048 bytes user data per Mode2 Form 1 sector)
* ``SECTOR_EDC_ECC_BYTES = 0x118`` (280 bytes of EDC + ECC at sector tail)

These constants describe a Mode2/2352 disc image, which is what the
canonical SLUS-01032 redump dump is. The first 16 sectors (0x9300
bytes) are the ISO9660 system area and are never recalculated — that's
the upstream convention for SOTN/FFT/this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .addresses import SECTOR_SIZE_BYTES

SYSTEM_AREA_SECTORS: Final = 16  # ISO9660 reserved area; we never touch it.

_SYNC_HEADER: Final = bytes([0, 255, 255, 255, 255, 255, 255, 255, 255, 255, 255, 0])

# ECC look-up tables — one-time init, mirrored verbatim from the SOTN/FFT
# implementation.
_ECC_F_LUT: Final = bytearray(256)
_ECC_B_LUT: Final = bytearray(256)
_EDC_LUT: Final = [0] * 256

for _i in range(256):
    _j = (_i << 1) ^ (0x11D if _i & 0x80 else 0)
    _ECC_F_LUT[_i] = _j
    _ECC_B_LUT[_i ^ _j] = _i
    _edc = _i
    for _ in range(8):
        _edc = (_edc >> 1) ^ (0xD8018001 if _edc & 1 else 0)
    _EDC_LUT[_i] = _edc
del _i, _j, _edc


def _compute_edc_block(data: bytes | bytearray | memoryview) -> int:
    edc = 0
    for b in data:
        edc = (edc >> 8) ^ _EDC_LUT[(edc ^ b) & 0xFF]
    return edc


def _compute_ecc_block(
    sector: bytearray | memoryview,
    major_count: int,
    minor_count: int,
    major_mult: int,
    minor_inc: int,
) -> bytearray:
    size = major_count * minor_count
    block = bytearray(major_count * 2)
    for major in range(major_count):
        index = (major >> 1) * major_mult + (major & 1)
        ecc_a = 0
        ecc_b = 0
        for _ in range(minor_count):
            temp = sector[index]
            index += minor_inc
            if index >= size:
                index -= size
            ecc_a ^= temp
            ecc_b ^= temp
            ecc_a = _ECC_F_LUT[ecc_a]
        ecc_a = _ECC_B_LUT[_ECC_F_LUT[ecc_a] ^ ecc_b]
        block[major] = ecc_a
        block[major + major_count] = ecc_a ^ ecc_b
    return block


def _generate_ecc(sector: bytearray, zero_address: bool) -> None:
    if zero_address:
        address = bytes(sector[12:12 + 4])
        sector[12:12 + 4] = b"\x00\x00\x00\x00"
    p_code = _compute_ecc_block(memoryview(sector)[0xC:], 86, 24, 2, 86)
    sector[0x81C:0x81C + len(p_code)] = p_code
    q_code = _compute_ecc_block(memoryview(sector)[0xC:], 52, 43, 86, 88)
    sector[0x8C8:0x8C8 + len(q_code)] = q_code
    if zero_address:
        sector[12:12 + 4] = address


@dataclass(slots=True)
class RecalcStats:
    identical_sectors: int = 0
    recalc_sectors: int = 0
    edc_blocks_computed: int = 0
    ecc_blocks_generated: int = 0

    @property
    def total_sectors(self) -> int:
        return self.identical_sectors + self.recalc_sectors


def _recalc_one_sector(sector: bytearray, calc_form_2_edc: bool, stats: RecalcStats) -> None:
    """Regenerate EDC + ECC in place for one 2352-byte Mode2 sector."""

    sector[0:len(_SYNC_HEADER)] = _SYNC_HEADER
    mode = sector[0x0F]
    if mode == 0:
        sector[0x10:0x10 + 0x920] = bytes(0x920)
    elif mode == 1:
        edc = _compute_edc_block(memoryview(sector)[:0x810])
        sector[0x810:0x814] = edc.to_bytes(4, "little")
        sector[0x814:0x81C] = bytes(8)
        _generate_ecc(sector, zero_address=False)
        stats.edc_blocks_computed += 1
        stats.ecc_blocks_generated += 1
    elif mode == 2:
        form2 = sector[0x12] & 0x20
        if not form2:
            edc = _compute_edc_block(memoryview(sector)[0x10:0x10 + 0x808])
            sector[0x818:0x81C] = edc.to_bytes(4, "little")
            _generate_ecc(sector, zero_address=True)
            stats.edc_blocks_computed += 1
            stats.ecc_blocks_generated += 1
        else:
            if calc_form_2_edc:
                edc = _compute_edc_block(memoryview(sector)[0x10:0x10 + 0x91C])
                stats.edc_blocks_computed += 1
            else:
                edc = 0
            sector[0x92C:0x930] = edc.to_bytes(4, "little")
            # Form 2 doesn't generate ECC.


def diff_recalc_in_place(
    target: bytearray,
    base: bytes | bytearray | memoryview,
    calc_form_2_edc: bool = False,
) -> RecalcStats:
    """Recompute EDC/ECC only for sectors that differ from ``base``.

    Both arguments must be Mode2/2352 images of identical size. The
    first 16 sectors (system area) are never touched. Operates in
    place on ``target``.
    """

    if len(target) != len(base):
        raise ValueError(
            f"target ({len(target)} bytes) and base ({len(base)} bytes) "
            f"must have identical sizes for diff EDC recalc",
        )
    if len(target) % SECTOR_SIZE_BYTES != 0:
        raise ValueError(
            f"target size {len(target)} is not a multiple of SECTOR_SIZE_BYTES "
            f"({SECTOR_SIZE_BYTES}); not a Mode2/2352 image",
        )

    stats = RecalcStats()
    sector_count = len(target) // SECTOR_SIZE_BYTES
    base_view = memoryview(base)
    target_view = memoryview(target)
    for sector_no in range(SYSTEM_AREA_SECTORS, sector_count):
        start = sector_no * SECTOR_SIZE_BYTES
        end = start + SECTOR_SIZE_BYTES
        if base_view[start:end] == target_view[start:end]:
            stats.identical_sectors += 1
            continue
        sector = bytearray(target_view[start:end])
        _recalc_one_sector(sector, calc_form_2_edc, stats)
        target_view[start:end] = sector
        stats.recalc_sectors += 1
    return stats


__all__ = ["SYSTEM_AREA_SECTORS", "RecalcStats", "diff_recalc_in_place"]
