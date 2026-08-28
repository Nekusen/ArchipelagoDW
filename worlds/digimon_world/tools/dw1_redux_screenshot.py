"""Grabs what the game is showing right now, via the PCSX-Redux REST VRAM dump.

Usage:  python dw1_redux_screenshot.py [out.png] [x y w h]

Default crop is the standard DW1 framebuffer at VRAM (0,0), 320x240. Pass a custom rect to
inspect other VRAM areas (texture pages, the back buffer at another x/y, ...). No external
dependencies: decodes BGR555 and writes the PNG with zlib by hand.

This is the "eyes" of scripted play: press buttons with dw1_redux_api.py lua "dw1_press({...})"
(sequencer installed by the vector harness) or pad.setOverride, then screenshot to see where
the game actually is. Screens like name entry cannot be blind-mashed through.
"""

from __future__ import annotations

import os
import struct
import sys
import urllib.parse
import urllib.request
import zlib

VRAM_W = 1024


def screenshot(out_path: str, x: int = 0, y: int = 0, w: int = 320, h: int = 240,
               host: str = "127.0.0.1", port: int = 8080) -> str:
    # The VRAM GET races the running emulation and has segfaulted this nightly mid-session
    # (2026-08-28, sentry dump). Pause through the Lua endpoint for the duration of the fetch.
    base = f"http://{host}:{port}"

    def lua(code: str) -> None:
        urllib.request.urlopen(base + "/api/v1/lua/eval?code=" + urllib.parse.quote(code), timeout=15).read()

    lua("PCSX.pauseEmulator()")
    try:
        raw = urllib.request.urlopen(base + "/api/v1/gpu/vram/raw", timeout=15).read()
    finally:
        lua("PCSX.resumeEmulator()")
    rows = []
    for yy in range(h):
        row = bytearray(b"\x00")
        base = (y + yy) * VRAM_W * 2 + x * 2
        for xx in range(w):
            p = struct.unpack_from("<H", raw, base + xx * 2)[0]
            row += bytes((((p & 31) << 3), (((p >> 5) & 31) << 3), (((p >> 10) & 31) << 3)))
        rows.append(bytes(row))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"".join(rows), 6))
           + chunk(b"IEND", b""))
    with open(out_path, "wb") as f:
        f.write(png)
    return out_path


def main(argv: list[str]) -> int:
    out = argv[1] if len(argv) > 1 else os.path.join("work", "dw1_re", "screen_now.png")
    rect = [int(a, 0) for a in argv[2:6]] if len(argv) >= 6 else [0, 0, 320, 240]
    print(screenshot(out, *rect))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
