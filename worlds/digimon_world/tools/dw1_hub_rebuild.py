r"""Rebuild the Mr. Warp teleport hub (``work\dw1_re\debug_warp.state``) from a COLD BOOT, unattended.

The hub is the root of every other lab savestate (``dw1_warp_state.py`` derives any screen from it).
It was lost with ``work/`` on 2026-09-03 and rebuilt by hand on 2026-09-05; this script replays that
proven sequence so the loss of ``work/`` never costs more than a few minutes again:

1. ``pcsx.json`` must pin ``pads[*].PadType = 2`` (Keyboard). ``0`` (Auto) merges a drifting host
   controller into pad 1 and the title menu cursor wanders (phantom pad, see TOOLING.md). The script
   fixes the file. The emulator is always (re)launched with FRESH memory cards: a NEW GAME occupies
   its save slot the moment it is created, and the START SLOT screen then refuses slot 1.
2. Title -> NEW GAME (START opens the menu, CROSS confirms NEW GAME, CROSS picks save slot 1 on the
   "START SLOT" screen).
3. CROSS masher through the intro. The name screen accepts the default letters, the tamer is named
   ``AAAAAA``; the opening plays on map 238, Jijimon's house is 218, the game hands control on
   map 204 (TWNA01, outside the house) with script 164 resident -> ``gamestart_outside.state``.
4. Clear ``0x1BDFD3`` (triggers 48..55: 54 = debug menu used, 55 = debug mode initialised).
   MAPHEAD Section_204 loads the DEBUG NPC set only when 54 AND 55 are both clear at screen load,
   so the screen must be re-entered: hold UP into the house (218), hold DOWN back out (204).
5. Mr. Warp is NPC slot 0 of that set (script 164 Section_5). NPC talk is collision-based, so the
   NPC is moved onto the tamer (``PositionData.location`` + ``Entity.anim.locX/locZ = loc << 15``)
   and four CROSS taps open his menu ``Near / Far away / Very far away`` -> ``debug_warp.state``.
6. Self-test: ``dw1_warp_state.py --map 18`` must land on MIHA00.

Usage (repo root):  python worlds/digimon_world/tools/dw1_hub_rebuild.py [--keep-going]

Lab rules baked in: RAM is read through small Lua evals only (REST data GETs crash this redux
nightly while the game runs); pointers are range-checked before deref (an out-of-range
``getMemPtr()`` index segfaults the emulator); every listener removes itself.
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
WORK = os.path.join(REPO, "work", "dw1_re")
sys.path.insert(0, HERE)
from dw1_redux_api import ReduxClient  # noqa: E402

CURRENT_SCREEN = 0x134DA8
LOADED_SCRIPT_ID = 0x134FC2
IN_GAME_FLAG = 0x12F344         # ENTITY_TABLE[0]: non-zero once the field engine runs
MENU_FLAG = 0x134EB0            # becomes 1 once the title screen has been left
DEBUG_TRIGGER_BYTE = 0x1BDFD3   # triggers 48..55
TAMER_ENTITY = 0x15576C         # dw_decomp TAMER_ENTITY (+4 = PositionData*)
NPC_ENTITIES = 0x155828         # dw_decomp NPC_ENTITIES[8], 0x68 bytes each
NPC_STRIDE = 0x68
POS_LOCATION = 0x78             # PositionData.location (VECTOR x, y, z)
ANIM_LOCX, ANIM_LOCZ = 0x10, 0x18
SCRIPT_BUF = 0x1B9ED8
SELECTION_MENU_STATE = 0x134FFA  # dw_decomp: non-zero while a setSelection menu is up
IS_SCRIPT_PAUSED = 0x134FF4      # misnamed in dw_decomp: 1 = no script running, 0 = a script (dialog) runs
OUTSIDE, HOUSE, DEBUG_SCRIPT = 204, 218, 164
MR_WARP_SLOT, MR_WARP_SECTION = 0, 5

SAVE_HELPER = (
    "function _G.dw1_save(name) PCSX.pauseEmulator() "
    "local f = Support.File.open(name .. '.state', 'TRUNCATE') f:write(PCSX.createSaveState()) f:close() "
    "PCSX.resumeEmulator() return 'saved ' .. name .. '.state' end return 'ok'"
)
ALL_BUTTONS = "B.UP,B.DOWN,B.LEFT,B.RIGHT,B.CROSS,B.CIRCLE,B.TRIANGLE,B.SQUARE,B.START,B.SELECT,B.L1,B.R1,B.L2,B.R2"


class Lab:
    def __init__(self) -> None:
        self.c = ReduxClient()

    # --- emulator lifecycle -------------------------------------------------------------------
    def ensure_pad_type(self) -> bool:
        """Pin PadType=2 in pcsx.json; returns True if the file had to change (restart needed)."""
        path = os.path.join(WORK, "pcsx.json")
        if not os.path.exists(path):
            return False
        with open(path, encoding="utf-8-sig") as fh:   # the launcher writes it with a BOM
            d = json.load(fh)
        changed = 0
        for pad in d.get("pads") or []:
            if isinstance(pad, dict) and pad.get("PadType") != 2:
                pad["PadType"] = 2
                changed += 1
        if changed:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(d, indent=2))
        return bool(changed)

    def alive(self) -> bool:
        try:
            return self.c.ping()
        except Exception:
            return False

    def launch(self, fresh_cards: bool = True) -> None:
        """Start redux through the lab launcher. fresh_cards deletes memcard1/2.mcd first: a NEW GAME
        occupies its save slot the moment it is created (even if never saved), and the START SLOT
        screen then refuses the default slot on the next rebuild."""
        launcher = os.path.join(HERE, "dw1_redux_launch.ps1")
        argv = ["powershell", "-ExecutionPolicy", "Bypass", "-File", launcher]
        if fresh_cards:
            argv.append("-FreshCards")
        subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(40):
            time.sleep(3)
            if self.alive():
                return
        raise SystemExit("emulator did not come up")

    def quit(self) -> None:
        try:
            self.c.quit()          # REST /api/v1/lua/quit (the bootstrap's handler)
        except Exception:
            pass
        time.sleep(4)

    def install(self) -> None:
        inp = os.path.join(HERE, "dw1_redux_input.lua").replace("\\", "/")
        self.c.eval_lua(f"Support.extra.dofile('{inp}') return 'input ok'")
        self.c.eval_lua(SAVE_HELPER)

    # --- RAM ----------------------------------------------------------------------------------
    def u8(self, a: int) -> int:
        return int(self.c.eval_lua(f"return PCSX.getMemPtr()[{a}]").strip())

    def u16(self, a: int) -> int:
        return int(self.c.eval_lua(f"local m = PCSX.getMemPtr() return m[{a}] + m[{a + 1}] * 256").strip())

    def rd(self, a: int, n: int) -> bytes:
        assert 0 <= a and a + n <= 0x200000, hex(a)
        code = (f"local m=PCSX.getMemPtr() local t={{}} for i=0,{n - 1} do "
                f"t[#t+1]=string.format('%02x', m[{a}+i]) end return table.concat(t)")
        s = self.c.eval_lua(code).strip()
        return bytes.fromhex(s)

    def w8(self, a: int, v: int) -> None:
        self.c.eval_lua(f"PCSX.getMemPtr()[{a}] = {v & 255} return 1")

    def w32(self, a: int, v: int) -> None:
        v &= 0xFFFFFFFF
        self.c.eval_lua(f"local m=PCSX.getMemPtr() m[{a}]={v & 255} m[{a + 1}]={(v >> 8) & 255} "
                        f"m[{a + 2}]={(v >> 16) & 255} m[{a + 3}]={v >> 24} return 1")

    @staticmethod
    def s32(b: bytes, o: int) -> int:
        return int.from_bytes(b[o:o + 4], "little", signed=True)

    @staticmethod
    def u32b(b: bytes, o: int) -> int:
        return int.from_bytes(b[o:o + 4], "little")

    def screen(self) -> int:
        return self.u8(CURRENT_SCREEN)

    def script(self) -> int:
        return self.u16(LOADED_SCRIPT_ID)

    def in_game(self) -> bool:
        return self.u32b(self.rd(IN_GAME_FLAG, 4), 0) != 0

    def tamer_pos(self) -> tuple[int, int]:
        pd = self.u32b(self.rd(TAMER_ENTITY + 4, 4), 0)
        if not 0x80000000 <= pd < 0x80200000:
            raise RuntimeError(f"tamer PositionData pointer invalid: {pd:08X}")
        loc = self.rd((pd & 0x1FFFFF) + POS_LOCATION, 12)
        return self.s32(loc, 0), self.s32(loc, 8)

    # --- pad ----------------------------------------------------------------------------------
    def tap(self, button: str, hold: int = 8) -> None:
        self.c.eval_lua(
            "local B=PCSX.CONSTS.PAD.BUTTON local f=0 local l "
            "l=PCSX.Events.createEventListener('GPU::Vsync', function() f=f+1 "
            "local p=PCSX.SIO0.slots[1].pads[1] "
            f"if f==2 then p.setOverride(B.{button}) end "
            f"if f=={2 + hold} then p.clearOverride(B.{button}) l:remove() end end) return 'tap'")

    def hold(self, button: str) -> None:
        self.c.eval_lua(f"local B=PCSX.CONSTS.PAD.BUTTON PCSX.SIO0.slots[1].pads[1].setOverride(B.{button}) return 1")

    def release_all(self) -> None:
        self.c.eval_lua("local B=PCSX.CONSTS.PAD.BUTTON local p=PCSX.SIO0.slots[1].pads[1] "
                        f"for _,b in ipairs({{{ALL_BUTTONS}}}) do p.clearOverride(b) end "
                        "if _G.dw1_masher_listener then _G.dw1_masher_listener:remove() _G.dw1_masher_listener=nil end "
                        "return 'released'")

    def masher(self, mode: str | None) -> None:
        self.c.eval_lua("dw1_masher(%s) return 1" % ("nil" if mode is None else f"'{mode}'"))

    def hold_until_screen(self, button: str, target: int, timeout: float) -> bool:
        self.hold(button)
        t0 = time.time()
        try:
            while time.time() - t0 < timeout:
                time.sleep(0.25)
                if self.screen() == target:
                    return True
        finally:
            self.release_all()
        return False

    def walk_to(self, tx: int, tz: int, timeout: float = 20.0, tol: int = 90) -> bool:
        """Crude axis walk (measured 2026-09-05: RIGHT=+x, LEFT=-x, UP=+z, DOWN=-z). Returns True when
        within tol or when the screen changed (a warp cell fired)."""
        t0 = time.time()
        scr0 = self.screen()
        try:
            while time.time() - t0 < timeout:
                if self.screen() != scr0:
                    return True
                x, z = self.tamer_pos()
                dx, dz = tx - x, tz - z
                if abs(dx) <= tol and abs(dz) <= tol:
                    return True
                btns = []
                if abs(dx) > tol:
                    btns.append("RIGHT" if dx > 0 else "LEFT")
                if abs(dz) > tol:
                    btns.append("UP" if dz > 0 else "DOWN")
                for b in btns:
                    self.hold(b)
                time.sleep(0.35)
                self.release_all()
                time.sleep(0.15)
        finally:
            self.release_all()
        return self.screen() != scr0

    def save(self, name: str) -> str:
        return self.c.eval_lua(f"return _G.dw1_save('{name}')").strip()


def log(msg: str) -> None:
    sys.stdout.write(time.strftime("%H:%M:%S ") + msg + "\n")
    sys.stdout.flush()


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--intro-timeout", type=float, default=600.0, help="seconds allowed for the intro mash")
    ap.add_argument("--no-selftest", action="store_true", help="skip the final dw1_warp_state.py check")
    args = ap.parse_args(argv)
    lab = Lab()

    # 1. emulator with a sane pad config, fresh boot
    lab.ensure_pad_type()
    if lab.alive():
        log("quitting the running emulator (a fresh boot with empty memory cards is required)")
        lab.quit()
    log("launching PCSX-Redux with fresh memory cards")
    lab.launch(fresh_cards=True)
    time.sleep(5)
    lab.install()
    lab.release_all()
    if lab.ensure_pad_type():
        raise SystemExit("pcsx.json PadType was not 2 after launch; fix and rerun")

    # 2. title -> NEW GAME
    log("title screen: opening the menu and starting a new game")
    # The field engine (ENTITY_TABLE[0]) is NOT up during the title, the menu, the save-slot pick or
    # Jijimon's intro dialog (all on screen 0), so there is nothing reliable to poll here: the title
    # masher (START/CROSS alternating) gets through menu -> NEW GAME -> START SLOT 1, then the CROSS
    # masher drives the dialogs; progress is observed through CURRENT_SCREEN (0 -> 238 -> 218 -> 204).
    lab.masher("title")
    time.sleep(20.0)
    lab.masher(None)
    lab.release_all()
    log("title masher done; handing over to the CROSS masher")

    # 3. mash through the intro until control is handed over outside Jijimon's house
    log("mashing CROSS through the intro (name screen -> 'AAAAAA', opening on 238, house 218)")
    # The intro visits 204 twice (a brief "He arrived!" beat, then 238 opening -> 218 house -> 204 for
    # real), so "screen 204 + script 164" alone is not the end: control is handed over only when no
    # script runs any more (IS_SCRIPT_PAUSED == 1, misnamed) and that stays true with the masher off.
    lab.masher("x")
    t0 = time.time()
    last = None
    done = False
    while time.time() - t0 < args.intro_timeout:
        time.sleep(2.0)
        s, sc, idle = lab.screen(), lab.script(), lab.u8(IS_SCRIPT_PAUSED)
        if (s, sc) != last:
            log(f"  screen {s} script {sc}")
            last = (s, sc)
        if s == OUTSIDE and sc == DEBUG_SCRIPT and idle == 1:
            lab.masher(None)
            lab.release_all()
            stable = True
            for _ in range(4):
                time.sleep(1.5)
                if lab.screen() != OUTSIDE or lab.u8(IS_SCRIPT_PAUSED) != 1:
                    stable = False
                    break
            if stable:
                done = True
                break
            lab.masher("x")
    lab.masher(None)
    lab.release_all()
    if not done:
        raise SystemExit(f"intro did not finish on map 204 (screen {lab.screen()}, script {lab.script()})")
    time.sleep(2.0)
    log(lab.save("gamestart_outside"))

    # 4. debug NPC set: clear triggers 48..55, then re-enter the screen through the house
    lab.w8(DEBUG_TRIGGER_BYTE, 0)
    log("triggers 48..55 cleared; walking into the house")
    if not lab.hold_until_screen("UP", HOUSE, 12.0):
        raise SystemExit("did not reach the house (218)")
    time.sleep(3.0)
    door = lab.tamer_pos()          # we spawn ON the door cell; the warp fires only when it is re-entered
    log(f"inside the house at {door}; stepping away and walking back onto the door cell")
    lab.hold("DOWN")
    time.sleep(1.2)
    lab.release_all()
    time.sleep(0.5)
    lab.walk_to(door[0], door[1], timeout=20.0)
    if lab.screen() != OUTSIDE:
        lab.hold_until_screen("DOWN", OUTSIDE, 8.0)
    if lab.screen() != OUTSIDE:
        raise SystemExit(f"did not get back outside (204); screen {lab.screen()} pos {lab.tamer_pos()}")
    time.sleep(3.0)
    if lab.script() != DEBUG_SCRIPT:
        raise SystemExit(f"resident script is {lab.script()}, expected 164")
    e = lab.rd(NPC_ENTITIES + MR_WARP_SLOT * NPC_STRIDE, NPC_STRIDE)
    if e[0x65] != MR_WARP_SECTION:
        raise SystemExit(f"NPC slot 0 has script section {e[0x65]}, expected {MR_WARP_SECTION} (Mr. Warp)")
    if lab.u8(DEBUG_TRIGGER_BYTE) & 0xC0:
        raise SystemExit("triggers 54/55 came back set; the debug set will not be loaded")

    # 5. move Mr. Warp onto the tamer and open his menu
    tx, tz = lab.tamer_pos()
    pd = lab.u32b(e, 4)
    if not 0x80000000 <= pd < 0x80200000:
        raise SystemExit("Mr. Warp PositionData pointer invalid")
    nx, nz = tx + 60, tz
    lab.w32((pd & 0x1FFFFF) + POS_LOCATION, nx)
    lab.w32((pd & 0x1FFFFF) + POS_LOCATION + 8, nz)
    lab.w32(NPC_ENTITIES + MR_WARP_SLOT * NPC_STRIDE + ANIM_LOCX, nx << 15)
    lab.w32(NPC_ENTITIES + MR_WARP_SLOT * NPC_STRIDE + ANIM_LOCZ, nz << 15)
    time.sleep(0.5)
    log(f"Mr. Warp moved next to the tamer at ({nx},{nz}); opening his menu")
    for _ in range(4):           # stats text, date text, "I'm Mr. Warp", then the Near/Far/Very far menu
        lab.tap("CROSS")
        time.sleep(2.5)
    opcode, vanilla = lab.u8(SCRIPT_BUF + 1940), lab.u8(SCRIPT_BUF + 1941)
    if (opcode, vanilla) != (0x4B, 0x12):
        raise SystemExit(f"script buffer bytes {opcode:02X} {vanilla:02X} at +1940, expected 4B 12")
    # menu open? (live-verified values: hub = SELECTION_MENU_STATE 2 / IS_SCRIPT_PAUSED 0; idle field = 0 / 1)
    sel, paused = lab.u8(SELECTION_MENU_STATE), lab.u8(IS_SCRIPT_PAUSED)
    if sel == 0 or paused != 0:
        raise SystemExit(f"Mr. Warp's menu is not open (SELECTION_MENU_STATE={sel}, IS_SCRIPT_PAUSED={paused})")
    log(lab.save("debug_warp"))

    # 6. self-test: the warp tool must be able to land somewhere from the new hub
    if not args.no_selftest:
        warp = os.path.join(HERE, "dw1_warp_state.py")
        r = subprocess.run([sys.executable, warp, "--map", "18", "--out", "hub_selftest"],
                           capture_output=True, text=True, check=False)
        log("self-test: " + (r.stdout.strip() or r.stderr.strip()))
        if r.returncode != 0:
            return 1
        try:
            os.remove(os.path.join(WORK, "hub_selftest.state"))
        except OSError:
            pass
    log("hub rebuilt: work\\dw1_re\\debug_warp.state (+ gamestart_outside.state)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
