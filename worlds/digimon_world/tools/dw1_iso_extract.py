r"""List or extract files from the DW1 disc image (single-track Mode2/2352 BIN).

Usage:
    python dw1_iso_extract.py list [path\to\image.bin]
    python dw1_iso_extract.py extract SLUS_010.32 [out_dir] [path\to\image.bin]

Defaults: image = "Digimon World (USA).bin" at the repo root, out_dir = work\dw1_re.
The ;1 ISO9660 version suffix is optional in the file argument. Root-directory files only
(the DW1 disc keeps all overlays and the SLUS in the root).
"""

from __future__ import annotations

import os
import struct
import sys

SECTOR = 2352
USER_OFF = 24  # Mode2 Form1: sync(12) + header(4) + subheader(8)
USER_LEN = 2048

_here = os.path.dirname(os.path.abspath(__file__))
_repo = os.path.abspath(os.path.join(_here, "..", "..", ".."))
DEFAULT_BIN = os.path.join(_repo, "Digimon World (USA).bin")
DEFAULT_OUT = os.path.join(_repo, "work", "dw1_re")


def _user_data(f, lba: int) -> bytes:
    f.seek(lba * SECTOR)
    return f.read(SECTOR)[USER_OFF:USER_OFF + USER_LEN]


def read_root_entries(bin_path: str) -> dict[str, tuple[int, int]]:
    """Return {name: (lba, size)} for the root directory of the image."""
    with open(bin_path, "rb") as f:
        pvd = _user_data(f, 16)
        if pvd[1:6] != b"CD001":
            raise ValueError(f"no ISO9660 PVD at sector 16 of {bin_path}")
        root_lba = struct.unpack("<I", pvd[158:162])[0]
        root_len = struct.unpack("<I", pvd[166:170])[0]
        entries: dict[str, tuple[int, int]] = {}
        for s in range((root_len + USER_LEN - 1) // USER_LEN):
            d = _user_data(f, root_lba + s)
            i = 0
            while i < len(d):
                rec_len = d[i]
                if rec_len == 0:
                    i += 1
                    continue
                lba = struct.unpack("<I", d[i + 2:i + 6])[0]
                size = struct.unpack("<I", d[i + 10:i + 14])[0]
                name_len = d[i + 32]
                name = d[i + 33:i + 33 + name_len].decode("ascii", "replace")
                if name.strip("\x00\x01"):
                    entries[name] = (lba, size)
                i += rec_len
        return entries


def extract(bin_path: str, name: str, out_dir: str) -> str:
    entries = read_root_entries(bin_path)
    key = next((k for k in entries if k == name or k == name + ";1"), None)
    if key is None:
        raise KeyError(f"{name} not in image root; try: python {os.path.basename(__file__)} list")
    lba, size = entries[key]
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, key.split(";")[0])
    with open(bin_path, "rb") as f, open(out_path, "wb") as out:
        left = size
        while left > 0:
            chunk = _user_data(f, lba)[:min(USER_LEN, left)]
            out.write(chunk)
            left -= len(chunk)
            lba += 1
    return out_path


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in ("list", "extract"):
        print(__doc__)
        return 2
    if argv[1] == "list":
        bin_path = argv[2] if len(argv) > 2 else DEFAULT_BIN
        for n, (lba, size) in sorted(read_root_entries(bin_path).items()):
            print(f"{n:22s} lba={lba:7d} size={size}")
    else:
        name = argv[2]
        out_dir = argv[3] if len(argv) > 3 else DEFAULT_OUT
        bin_path = argv[4] if len(argv) > 4 else DEFAULT_BIN
        out = extract(bin_path, name, out_dir)
        print(f"extracted {out} ({os.path.getsize(out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
