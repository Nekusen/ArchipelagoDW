-- DW1 wide-RAM snapshot tool (NTSC-U / SLUS-01032).
--
-- Sister to tools/dw1_dump_state.lua, but dumps a much wider RAM region
-- (configurable below — default 0x001BDE00..0x001BE300, covering the
-- player-state and trigger-bit-array region). Output format matches
-- worlds/digimon_world/tools/dw1_ram_diff.py exactly so the existing
-- analyzer can diff a series of snapshots.
--
-- Auto-detects PSX core domain at startup:
--   * Nymashock: "MainRAM" with bare offsets
--   * Octoshock: "System Bus" with 0x80000000 kuseg prefix
-- (Octoshock has no Main RAM domain — observed 2026-05-01 with domain
-- list {GPURAM, SPURAM, BiosROM, PIOMem, DCache, System Bus}.)
--
-- Usage:
--   1. Tools -> Lua Console -> Open Script -> select this file.
--   2. Console prints "[dw1_snap] hook installed (F8)" plus the picked
--      domain.
--   3. Press F8 in BizHawk to append a snapshot to LOG_PATH below.
--   4. Take snapshots before AND after each state change you're hunting
--      (e.g. before the rod-give cutscene; after the rod is confirmed
--      in the player profile).
--   5. Run dw1_ram_diff.py over the snapshots to surface candidates.
--   6. To start fresh, delete the log file before snapshotting.

local LOG_PATH    = [[c:\opt\dev\AP\ArchipelagoDW\tools\dw1_ram_snapshot_wide.log]]
local DUMP_BASE   = 0x001BDE00
local DUMP_END    = 0x001BE300        -- exclusive
local MONEY_ADDR  = 0x00134EB8        -- header sanity field

local function pick_ram_domain()
    local list = memory.getmemorydomainlist()
    for _, d in ipairs(list) do
        local lower = string.lower(tostring(d))
        if lower == "mainram" or lower == "main ram" then
            return d, 0x00000000
        end
    end
    for _, d in ipairs(list) do
        if tostring(d) == "System Bus" then
            return d, 0x80000000
        end
    end
    error("[dw1_snap] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
memory.usememorydomain(DOMAIN)

local snapshot_count = 0

local function read_u8(addr)
    return memory.read_u8(addr + ADDR_PREFIX)
end

local function read_u32_le(addr)
    return memory.read_u32_le(addr + ADDR_PREFIX)
end

local function byte_to_bits(b)
    local out = ""
    for i = 7, 0, -1 do
        out = out .. (((b >> i) & 1) == 1 and "1" or "0")
    end
    return out
end

local function dump()
    snapshot_count = snapshot_count + 1
    local frame = emu.framecount()
    local money = read_u32_le(MONEY_ADDR)

    local f = io.open(LOG_PATH, "a")
    if not f then
        console.log("[dw1_snap] ERROR: could not open " .. LOG_PATH)
        return
    end

    f:write(string.format("DW1 RAM snapshot #%02d\n", snapshot_count))
    f:write(string.format(
        "domain=%s  range=0x%X..0x%X  frame=%d  money=%d\n",
        DOMAIN, DUMP_BASE, DUMP_END, frame, money))
    f:write("format: <addr>: <16 bytes hex>  ||  <16 bytes binary MSB-first>\n\n")

    for row = DUMP_BASE, DUMP_END - 1, 16 do
        local hex_cells = {}
        local bin_cells = {}
        for i = 0, 15 do
            local addr = row + i
            if addr < DUMP_END then
                local b = read_u8(addr)
                hex_cells[#hex_cells + 1] = string.format("%02x", b)
                bin_cells[#bin_cells + 1] = byte_to_bits(b)
            end
        end
        f:write(string.format(
            "0x%06X: %s  ||  %s\n",
            row, table.concat(hex_cells, " "), table.concat(bin_cells, " ")))
    end
    f:write("\n")
    f:close()

    console.log(string.format(
        "[dw1_snap] snapshot #%02d written (frame=%d, money=%d, %d bytes)",
        snapshot_count, frame, money, DUMP_END - DUMP_BASE))
end

local f8_was_down = false
event.onframeend(function()
    local keys = input.get()
    local f8_now = keys.F8 == true
    if f8_now and not f8_was_down then
        dump()
    end
    f8_was_down = f8_now
end)

console.log(string.format(
    "[dw1_snap] hook installed (F8 to snapshot). domain=%s prefix=0x%08X",
    DOMAIN, ADDR_PREFIX))
console.log(string.format(
    "[dw1_snap] dumping 0x%X..0x%X (%d bytes)",
    DUMP_BASE, DUMP_END, DUMP_END - DUMP_BASE))
console.log("[dw1_snap] log: " .. LOG_PATH)

-- Keep-alive so the F8 callback doesn't get deregistered when the main
-- body returns (BizHawk Lua quirk; see memory note bizhawk_lua_keepalive.md).
while true do
    emu.frameadvance()
end
