-- DW1 MAP_WARPS Dump Tool (BizHawk; Nymashock OR Octoshock)
--
-- Dumps the per-screen MapWarps table at RAM 0x80138730 (0x78 bytes,
-- 10 warp slots) along with the current screen ID and filename, so we
-- can identify which warp slot N (0..9) on a boundary screen carries
-- the targetMap we want to gate.
--
-- Mechanism (from references/DW1-SydPatches):
--   * Map.cpp:176 memcpy's the per-map MapWarps blob into the global
--     MAP_WARPS struct on every screen load.
--   * Tamer.cpp:422 reads MAP_WARPS.targetMap[trigger - 110] when the
--     player walks onto a tile whose collision trigger ∈ [110, 119].
--   * Layout (dw1.hpp:849, 0x78 bytes total):
--       int16  spawnX[10]    @ +0x00
--       int16  spawnY[10]    @ +0x14
--       int16  spawnZ[10]    @ +0x28
--       int16  rotation[10]  @ +0x3C
--       uint16 targetMap[10] @ +0x50
--       uint16 targetExit[10]@ +0x64
--
-- Usage:
--   1. Boot BizHawk with the running DW1 ISO. Either PSX core works.
--   2. Tools > Lua Console > Open Script > pick this file.
--   3. Stand on the screen whose warps you want to enumerate (e.g.
--      MIST07 = screen 121). Press W (in the emulator window, NOT the
--      Lua console). Repeat for each screen.
--
-- Output: dw1_map_warps_<screen>.txt in OUTPUT_DIR (CWD by default),
-- one file per snapshot. Also echoed to the Lua console.

-- ----------------------------------------------------------------------------
-- Domain auto-detect (Nymashock = MainRAM @ 0; Octoshock = System Bus @ 0x80000000)
-- See memory note nymashock_memory_domain.md.

local function pick_ram_domain()
    local list = memory.getmemorydomainlist()
    -- Print every domain BizHawk exposes so we can diagnose mismatches.
    console.log("[dw1-mapwarps] available memory domains:")
    for _, d in ipairs(list) do
        console.log("  '" .. tostring(d) .. "'")
    end
    -- Prefer a MainRAM-like domain (Nymashock). Match loosely on any name
    -- containing "main" and "ram" so casing/spacing variations all work.
    for _, d in ipairs(list) do
        local lower = string.lower(tostring(d))
        if lower:find("main") and lower:find("ram") then
            return d, 0x00000000
        end
    end
    -- Fallback: System Bus (Octoshock).
    for _, d in ipairs(list) do
        if tostring(d) == "System Bus" then
            return d, 0x80000000
        end
    end
    error("[dw1-mapwarps] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
console.log(string.format("[dw1-mapwarps] picked domain '%s' prefix=0x%08X",
                          DOMAIN, ADDR_PREFIX))

-- RAM addresses (from references/DW1-SydPatches/SLUS_labels.asm).
local CURRENT_SCREEN_ADDR = 0x00134DA8       -- u8 (per client.py:237)
local CURRENT_EXIT_ADDR   = 0x00134DAA       -- u8
local MAP_WARPS_ADDR      = 0x00138730       -- 0x78 bytes
local MAP_ENTRIES_ADDR    = 0x001292D4       -- MapEntry[255], 16 B each; filename[10] at +0

local HOTKEY     = "W"
local OUTPUT_DIR = ""  -- "" = BizHawk CWD; or "C:/tmp/"

-- ----------------------------------------------------------------------------

local function r_u8(off)
    return memory.read_u8(off + ADDR_PREFIX, DOMAIN)
end

local function r_u16(off)
    return memory.read_u16_le(off + ADDR_PREFIX, DOMAIN)
end

local function r_s16(off)
    return memory.read_s16_le(off + ADDR_PREFIX, DOMAIN)
end

local function read_screen_filename(screen_id)
    if screen_id < 0 or screen_id > 254 then return "?" end
    local base = MAP_ENTRIES_ADDR + screen_id * 16
    local chars = {}
    for i = 0, 9 do
        local b = r_u8(base + i)
        if b == 0 then break end
        chars[#chars + 1] = string.char(b)
    end
    local name = table.concat(chars)
    return (name == "" and "(blank)" or name)
end

local snapshot_count = 0
local key_was_down   = false

local function dump()
    local screen_id   = r_u8(CURRENT_SCREEN_ADDR)
    local screen_name = read_screen_filename(screen_id)
    local current_exit = r_u8(CURRENT_EXIT_ADDR)

    snapshot_count = snapshot_count + 1
    local filename = OUTPUT_DIR .. string.format(
        "dw1_map_warps_%02d_screen%03d_%s.txt",
        snapshot_count, screen_id, screen_name
    )
    local f = io.open(filename, "w")
    if not f then
        console.log("[dw1-mapwarps] ERROR: cannot write " .. filename)
        snapshot_count = snapshot_count - 1
        return
    end

    local header = string.format(
        "DW1 MAP_WARPS dump #%02d\n" ..
        "domain=%s  frame=%d\n" ..
        "screen=%d (%s)  CURRENT_EXIT=%d\n" ..
        "MAP_WARPS @ 0x%08X (0x78 B)\n\n",
        snapshot_count, DOMAIN, emu.framecount(),
        screen_id, screen_name, current_exit,
        MAP_WARPS_ADDR + ADDR_PREFIX
    )
    f:write(header)

    -- Decoded per-slot view.
    f:write("slot  spawnX  spawnY  spawnZ   rot   targetMap                targetExit\n")
    f:write("----  ------  ------  ------  ----  -----------------------  ----------\n")
    for n = 0, 9 do
        local sx = r_s16(MAP_WARPS_ADDR + 0x00 + n * 2)
        local sy = r_s16(MAP_WARPS_ADDR + 0x14 + n * 2)
        local sz = r_s16(MAP_WARPS_ADDR + 0x28 + n * 2)
        local rot = r_s16(MAP_WARPS_ADDR + 0x3C + n * 2)
        local tmap = r_u16(MAP_WARPS_ADDR + 0x50 + n * 2)
        local texit = r_u16(MAP_WARPS_ADDR + 0x64 + n * 2)
        local tmap_name = read_screen_filename(tmap)
        local marker = ""
        if n == current_exit then marker = "  <- player entered here" end
        f:write(string.format(
            "[%d]  %6d  %6d  %6d  %4d  %3d (%-15s)  %5d%s\n",
            n, sx, sy, sz, rot, tmap, tmap_name, texit, marker
        ))
    end

    -- Raw bytes, for cross-check.
    f:write("\nRaw bytes (0x78 B, 16 per line):\n")
    for base = 0, 0x77, 16 do
        local parts = {}
        for i = 0, 15 do
            if base + i <= 0x77 then
                parts[#parts + 1] = string.format("%02X", r_u8(MAP_WARPS_ADDR + base + i))
            end
        end
        f:write(string.format("  +0x%02X: %s\n", base, table.concat(parts, " ")))
    end

    f:close()

    -- Also echo to console for quick inspection.
    console.log("==================================================")
    console.log(string.format("[dw1-mapwarps %02d] screen=%d (%s) entered via exit %d",
                              snapshot_count, screen_id, screen_name, current_exit))
    for n = 0, 9 do
        local tmap = r_u16(MAP_WARPS_ADDR + 0x50 + n * 2)
        local texit = r_u16(MAP_WARPS_ADDR + 0x64 + n * 2)
        if not (tmap == 0 and texit == 0) then
            console.log(string.format("  slot %d -> map %3d (%s) exit %d%s",
                n, tmap, read_screen_filename(tmap), texit,
                n == current_exit and "  <- player entered here" or ""))
        end
    end
    console.log("wrote " .. filename)
end

console.log("DW1 MAP_WARPS dump tool loaded.")
console.log(string.format("  domain : %s", DOMAIN))
console.log(string.format("  hotkey : %s  (press in the emulator window)", HOTKEY))
console.log("  procedure: stand on a boundary screen, press W. Repeat per screen.")

while true do
    local keys     = input.get()
    local key_down = keys[HOTKEY] == true
    if key_down and not key_was_down then
        dump()
    end
    key_was_down = key_down

    -- On-screen status: live current-screen indicator.
    local sid = r_u8(CURRENT_SCREEN_ADDR)
    gui.text(2, 2,
             string.format("MAP_WARPS dump: %d snapshots  screen=%d (%s)  press %s",
                           snapshot_count, sid, read_screen_filename(sid), HOTKEY),
             "white", "black")

    emu.frameadvance()
end
