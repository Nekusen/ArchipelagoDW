"""Python driver for the PCSX-Redux REST API (web server on localhost:8080).

Lets any script read/write PSX RAM, pause/resume, and push Ghidra symbols into the emulator
without touching the GUI. Offsets are physical main-RAM offsets (0x000000..0x1FFFFF), the same
convention as BizHawk's MainRAM domain and data/addresses.py.

CLI usage:
    python dw1_redux_api.py status
    python dw1_redux_api.py dump out.bin
    python dw1_redux_api.py peek 0x1BDFCD 16
    python dw1_redux_api.py poke 0x1BDFD3 00
    python dw1_redux_api.py pause | resume | reset | reset-soft
    python dw1_redux_api.py symbols path/to/symbols.map
    python dw1_redux_api.py check-dump path/to/ram_dump.bin
    python dw1_redux_api.py ping
    python dw1_redux_api.py lua "return PCSX.getCPUCycles()"
    python dw1_redux_api.py quit
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request

RAM_SIZE = 0x200000
_repo = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
WORK_DIR = os.path.join(_repo, "work", "dw1_re")


class ReduxClient:
    def __init__(self, host: str = "127.0.0.1", port: int = 8080):
        self.base = f"http://{host}:{port}"

    def _get(self, path: str) -> bytes:
        with urllib.request.urlopen(self.base + path, timeout=10) as r:
            return r.read()

    def _post(self, path: str, body: bytes = b"") -> bytes:
        req = urllib.request.Request(self.base + path, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read()

    def status(self) -> str:
        return self._get("/api/v1/execution-flow").decode("utf-8", "replace")

    def dump_ram(self) -> bytes:
        data = self._get("/api/v1/cpu/ram/raw")
        return data[:RAM_SIZE]

    def peek(self, offset: int, size: int) -> bytes:
        return self.dump_ram()[offset:offset + size]

    def poke(self, offset: int, data: bytes) -> None:
        self._post(f"/api/v1/cpu/ram/raw?offset={offset}&size={len(data)}", data)

    def pause(self) -> None:
        self._post("/api/v1/execution-flow?function=pause")

    def resume(self) -> None:
        self._post("/api/v1/execution-flow?function=resume")

    def reset(self, hard: bool = True) -> None:
        self._post(f"/api/v1/execution-flow?function=reset&type={'hard' if hard else 'soft'}")

    def flush_cache(self) -> None:
        self._post("/api/v1/cpu/cache?function=flush")

    def eval_lua(self, code: str) -> str:
        """Run arbitrary Lua inside the emulator (handlers registered by dw1_redux_bootstrap.lua).

        Short snippets travel in the query string; redux's HTTP parser rejects URLs over ~256
        bytes, so longer code is written to the shared workbench dir (work\\dw1_re, the emulator's
        CWD) and executed via the /run handler instead. Both return tostring() of the result.
        """
        query = urllib.parse.urlencode({"code": code})
        if len(query) <= 180:
            return self._get("/api/v1/lua/eval?" + query).decode("utf-8", "replace")
        payload = os.path.join(WORK_DIR, "dw1_eval_payload.lua")
        with open(payload, "w", encoding="utf-8") as f:
            f.write(code)
        return self._get("/api/v1/lua/run?file=dw1_eval_payload.lua").decode("utf-8", "replace")

    def quit(self) -> None:
        self._get("/api/v1/lua/quit")

    def ping(self) -> bool:
        try:
            return self._get("/api/v1/lua/ping").startswith(b"pong")
        except OSError:
            return False

    def upload_symbols(self, map_text: str) -> None:
        """map_text: one `Name 80010000` pair per line (Ghidra/redux .map convention)."""
        self._post("/api/v1/assembly/symbols?function=upload", map_text.encode("ascii"))

    def reset_symbols(self) -> None:
        self._post("/api/v1/assembly/symbols?function=reset")


# Known-static content of DW1 USA main RAM once the SLUS is loaded; used to sanity-check dumps.
DUMP_MARKERS = (b"MAYO", b"MGEN", b"OGRE")


def check_dump(path: str) -> int:
    data = open(path, "rb").read()
    head = "nonzero" if any(data[:0x1000]) else "all-zero"
    print(f"{path}: {len(data)} bytes, {head} head")
    missing = [m.decode() for m in DUMP_MARKERS if m not in data]
    if len(data) != RAM_SIZE:
        print(f"FAIL: expected {RAM_SIZE} bytes")
        return 1
    if missing:
        print(f"FAIL: markers not found: {missing} (game not booted far enough?)")
        return 1
    print("OK: size + MAP-filename markers present")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    cmd = argv[1]
    if cmd == "check-dump":
        return check_dump(argv[2])
    c = ReduxClient()
    if cmd == "status":
        print(c.status())
    elif cmd == "dump":
        data = c.dump_ram()
        open(argv[2], "wb").write(data)
        print(f"wrote {len(data)} bytes to {argv[2]}")
    elif cmd == "peek":
        off = int(argv[2], 0)
        size = int(argv[3], 0) if len(argv) > 3 else 16
        print(c.peek(off, size).hex(" "))
    elif cmd == "poke":
        c.poke(int(argv[2], 0), bytes.fromhex(argv[3]))
        print("ok")
    elif cmd == "pause":
        c.pause()
    elif cmd == "resume":
        c.resume()
    elif cmd == "reset":
        c.reset(hard=True)
    elif cmd == "reset-soft":
        c.reset(hard=False)
    elif cmd == "symbols":
        c.upload_symbols(open(argv[2], "r", encoding="ascii").read())
        print("uploaded")
    elif cmd == "lua":
        print(c.eval_lua(argv[2]), end="")
    elif cmd == "quit":
        c.quit()
    elif cmd == "ping":
        print("pong" if c.ping() else "no response")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
