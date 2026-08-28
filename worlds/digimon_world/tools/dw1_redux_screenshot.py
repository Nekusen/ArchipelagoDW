r"""Grabs what the game is showing right now, through PCSX-Redux's Lua screenshot API.

Usage:  python dw1_redux_screenshot.py [out.png]
        python dw1_redux_screenshot.py out.png --vram x y w h      # raw VRAM rect (see caveat)

Default: ``PCSX.GPU.takeScreenShot()`` executed inside the emulator, which hands back the
current display (16- or 24-bit) as a slice written to ``work\dw1_re\screen_raw.bin``; this
script converts it to a PNG with zlib by hand. No external dependencies.

Why not the REST VRAM dump any more: ``/api/v1/gpu/vram/raw`` races the running emulation and
segfaulted this nightly mid-session (2026-08-28, sentry dump), and with the emulator paused it
simply never answers. ``--vram`` keeps that path for inspecting texture pages / the back buffer,
but only use it with the emulator parked -- never during a live play session.

This is the "eyes" of scripted play: press buttons (vector-harness sequencer or
``pad.setOverride``), then screenshot to see where the game actually is. Screens like name
entry cannot be blind-mashed through.
"""

from __future__ import annotations

import os
import struct
import sys
import urllib.request
import zlib

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
from dw1_redux_api import ReduxClient  # noqa: E402

VRAM_W = 1024
RAW_NAME = "screen_raw.bin"  # written by the emulator into its CWD, work\dw1_re

LUA_SHOT = (
    "local ss = PCSX.GPU.takeScreenShot() "
    f"local f = Support.File.open('{RAW_NAME}', 'TRUNCATE') f:writeMoveSlice(ss.data) f:close() "
    "return ss.width .. ' ' .. ss.height .. ' ' .. tostring(ss.bpp)"
)


def _png(w: int, h: int, rows: list[bytes], out_path: str) -> str:
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
           + chunk(b"IEND", b""))
    with open(out_path, "wb") as f:
        f.write(png)
    return out_path


def _rows_bgr555(raw: bytes, w: int, h: int, stride_px: int, x0: int = 0, y0: int = 0) -> list[bytes]:
    rows = []
    for yy in range(h):
        row = bytearray(b"\x00")
        base = (y0 + yy) * stride_px * 2 + x0 * 2
        for xx in range(w):
            p = struct.unpack_from("<H", raw, base + xx * 2)[0]
            row += bytes((((p & 31) << 3), (((p >> 5) & 31) << 3), (((p >> 10) & 31) << 3)))
        rows.append(bytes(row))
    return rows


def screenshot(out_path: str) -> str:
    """Current display via the Lua API. Safe while the game runs."""

    c = ReduxClient()
    reply = c.eval_lua(LUA_SHOT).strip().split()
    w, h, bpp = int(reply[0]), int(reply[1]), reply[2]
    with open(os.path.join(REPO, "work", "dw1_re", RAW_NAME), "rb") as f:
        raw = f.read()
    if "24" in bpp:
        rows = [b"\x00" + raw[yy * w * 3:(yy + 1) * w * 3] for yy in range(h)]
    else:
        rows = _rows_bgr555(raw, w, h, w)
    return _png(w, h, rows, out_path)


def screenshot_vram(out_path: str, x: int, y: int, w: int, h: int,
                    host: str = "127.0.0.1", port: int = 8080) -> str:
    """Raw VRAM rect via REST. Emulator must be parked (see module docstring)."""

    raw = urllib.request.urlopen(f"http://{host}:{port}/api/v1/gpu/vram/raw", timeout=15).read()
    return _png(w, h, _rows_bgr555(raw, w, h, VRAM_W, x, y), out_path)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--vram"]
    out = args[0] if args else os.path.join("work", "dw1_re", "screen_now.png")
    if "--vram" in argv:
        rect = [int(a, 0) for a in args[1:5]] if len(args) >= 5 else [0, 0, 320, 240]
        sys.stdout.write(screenshot_vram(out, *rect) + "\n")
    else:
        sys.stdout.write(screenshot(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
