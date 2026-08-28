r"""Produce a PCSX-Redux savestate on ANY screen of DW1, unattended.

Mechanism (user idea, 2026-08-28): ``work\dw1_re\debug_warp.state`` sits on the debug map with
Mr. Warp's dialog open. There, script 164 is the resident streamed script at 0x1B9ED8 and its
in-slot offsets match the script dump 1:1, so the byte at +1941 -- the map-id operand of
``warpTo 18 0 255`` behind "Near -> The peak of Mt. Panorama" -- can be pointed at any screen.
Two CROSS presses then perform the warp. The tool verifies that ``CURRENT_SCREEN`` (0x134DA8)
really became the requested id before it writes the state, so a failed warp never yields a
mislabelled file.

Usage (repo root; the emulator is launched if not already running):

    python worlds/digimon_world/tools/dw1_warp_state.py --map 141 --out shop_merit_warp
    python worlds/digimon_world/tools/dw1_warp_state.py --map 226 --out back_dimension --god --set-trigger 50
    python worlds/digimon_world/tools/dw1_warp_state.py --map 6 --out fishing_spot --god \
        --set-trigger 45 --set-trigger 46

``--out`` is a state name (``.state`` is appended, written to ``work\dw1_re``). ``--god`` applies
the lab's god-mode pokes; ``--set-trigger N`` sets trigger bits before the warp (repeatable).
Exit 0 only if the screen matched and the state was written.

Lab-session rules baked in: the only Lua listener installed is a one-shot press sequence that
removes itself after the second press; all RAM access is via small Lua reads/writes; the state
write is wrapped in ``PCSX.pauseEmulator()``/``resumeEmulator()``.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, HERE)
from dw1_redux_api import ReduxClient  # noqa: E402

HUB_STATE = "debug_warp.state"
SCRIPT_BUF = 0x1B9ED8          # resident streamed-script buffer (script 164 on the debug map)
WARP_BYTE = SCRIPT_BUF + 1941  # map-id operand of "Near -> The peak of Mt. Panorama"
WARP_VANILLA = 0x12            # 18 = Mt. Panorama peak
CURRENT_SCREEN = 0x134DA8      # dw_decomp CURRENT_SCREEN (u8)
LOADED_SCRIPT_ID = 0x134FC2    # u16
TRIGGER_BASE = 0x1BDFCD        # trigger N -> byte BASE + N//8, bit N%8

SAVE_HELPER = (
    "function _G.dw1_save(name) PCSX.pauseEmulator() "
    "local f = Support.File.open(name .. '.state', 'TRUNCATE') f:write(PCSX.createSaveState()) f:close() "
    "PCSX.resumeEmulator() return 'saved ' .. name .. '.state' end return 'ok'"
)

# One-shot CROSS x2: pressed at frames 10 and 45 (held 8 frames each); the listener removes
# itself after the second release, so nothing persistent is left behind.
PRESS_SEQUENCE = (
    "local B = PCSX.CONSTS.PAD.BUTTON local frame = 0 local l "
    "l = PCSX.Events.createEventListener('GPU::Vsync', function() "
    "frame = frame + 1 local pad = PCSX.SIO0.slots[1].pads[1] "
    "if frame == 10 or frame == 45 then pad.setOverride(B.CROSS) end "
    "if frame == 18 or frame == 53 then pad.clearOverride(B.CROSS) end "
    "if frame >= 54 then l:remove() end end) return 'pressing'"
)


def screen_names() -> dict[int, str]:
    src = open(os.path.join(REPO, "worlds", "digimon_world", "data", "addresses.py"), encoding="utf-8").read()
    body = src.split("SCREEN_FILENAMES: Final[dict[int, str]] = {", 1)[1]
    body = body.split("\n}", 1)[0]
    return {int(k): v for k, v in re.findall(r'(\d+): "([A-Z0-9_]+)"', body)}


def ensure_emulator(c: ReduxClient) -> None:
    try:
        if c.ping():
            return
    except Exception:
        pass
    launcher = os.path.join(HERE, "dw1_redux_launch.ps1")
    subprocess.Popen(["powershell", "-ExecutionPolicy", "Bypass", "-File", launcher],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(40):
        time.sleep(3)
        try:
            if c.ping():
                return
        except Exception:
            continue
    raise SystemExit("emulator did not come up")


def lua_u8(c: ReduxClient, addr: int) -> int:
    return int(c.eval_lua(f"return PCSX.getMemPtr()[{addr}]").strip())


def lua_u16(c: ReduxClient, addr: int) -> int:
    return int(c.eval_lua(f"local m = PCSX.getMemPtr() return m[{addr}] + m[{addr + 1}] * 256").strip())


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--map", type=int, required=True, help="target screen id (0..255)")
    ap.add_argument("--out", required=True, help="state name to write (without .state)")
    ap.add_argument("--god", action="store_true", help="apply god-mode stats/HP/MP/Bits before warping")
    ap.add_argument("--set-trigger", type=int, action="append", default=[],
                    help="trigger id to set before warping (repeatable)")
    ap.add_argument("--wait", type=float, default=12.0, help="seconds to wait for the screen to match")
    args = ap.parse_args(argv)
    if not 0 <= args.map <= 255:
        raise SystemExit("--map must be 0..255")
    names = screen_names()
    target_name = names.get(args.map, "?")

    c = ReduxClient()
    ensure_emulator(c)
    c.eval_lua(SAVE_HELPER)
    c.eval_lua(f"PCSX.loadSaveState(Support.File.open('{HUB_STATE}')) return 'loaded'")
    time.sleep(2.0)

    resident = lua_u16(c, LOADED_SCRIPT_ID)
    opcode, vanilla = lua_u8(c, WARP_BYTE - 1), lua_u8(c, WARP_BYTE)
    if resident != 164 or opcode != 0x4B or vanilla != WARP_VANILLA:
        sys.stderr.write(f"hub state unexpected: resident script {resident}, bytes {opcode:02X} {vanilla:02X} "
                         "at +1940 (want 164, 4B 12) -- refusing to poke\n")
        return 2

    pokes = [f"m[{WARP_BYTE}] = {args.map}"]
    pokes.extend(
        f"m[{TRIGGER_BASE + t // 8}] = bit.bor(m[{TRIGGER_BASE + t // 8}], {1 << (t % 8)})"
        for t in args.set_trigger
    )
    if args.god:
        pokes.append(
            "local function w16(a, v) m[a] = v % 256 m[a + 1] = math.floor(v / 256) % 256 end "
            "for _, a in ipairs({0x1557E0, 0x1557E2, 0x1557E4, 0x1557E6}) do w16(a, 999) end "
            "for _, a in ipairs({0x1557F0, 0x1557F2, 0x1557EC, 0x1557EE}) do w16(a, 9999) end "
            "w16(0x134EB8, 9999999 % 65536) w16(0x134EBA, math.floor(9999999 / 65536))"
        )
    c.eval_lua("local m = PCSX.getMemPtr() " + " ".join(pokes) + " return 'poked'")
    before = lua_u8(c, CURRENT_SCREEN)
    c.eval_lua(PRESS_SEQUENCE)

    deadline = time.time() + args.wait
    seen = before
    while time.time() < deadline:
        time.sleep(0.5)
        seen = lua_u8(c, CURRENT_SCREEN)
        if seen == args.map:
            break
    if seen != args.map:
        sys.stderr.write(f"warp did not land: CURRENT_SCREEN is {seen} ({names.get(seen, '?')}), wanted "
                         f"{args.map} ({target_name}); hub was on {before} ({names.get(before, '?')}). "
                         "Not saving.\n")
        return 1

    # Let the map finish loading (entities, scripts) before freezing it.
    time.sleep(3.0)
    if lua_u8(c, CURRENT_SCREEN) != args.map:
        sys.stderr.write("screen changed again after landing (an auto-transition?) -- not saving\n")
        return 1
    msg = c.eval_lua(f"return _G.dw1_save('{args.out}')").strip()
    path = os.path.join(REPO, "work", "dw1_re", args.out + ".state")
    size = os.path.getsize(path) if os.path.exists(path) else 0
    sys.stdout.write(f"{msg} -- screen {args.map} ({target_name}), {size} bytes\n")
    return 0 if size > 1_000_000 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
