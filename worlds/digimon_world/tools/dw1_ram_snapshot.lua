-- DW1 RAM Snapshot Tool (BizHawk + Nymashock)
--
-- Dumps the DW1 progression-flag RAM region so two snapshots can be diffed
-- to locate the bit/byte that flipped during an in-game event (e.g. the
-- Tropical Jungle bridge becoming permanently usable).
--
-- Usage:
--   1. Load BizHawk with the Nymashock PSX core and the running DW1 ISO.
--   2. Tools > Lua Console > Open Script > pick this file.
--   3. Position the player just before the state-changing event.
--      Press P (in the emulator window, NOT the Lua console) -> snapshot 01.
--   4. Trigger the event (cross the bridge, talk to the NPC, etc.).
--      Press P again -> snapshot 02.
--   5. Diff the two output files. Bytes/bits that differ are candidates
--      for the area-unlock flag.
--
-- Output: dw1_ram_snapshot_NN.txt in OUTPUT_DIR (configurable below).
-- Format: 16 bytes per line as both hex and MSB-first binary, so single-bit
-- flips are visible by eye in the binary column.

local DOMAIN     = "MainRAM"             -- PS1 main RAM under Nymashock
local START_ADDR = 0x001BDE00            -- ~512 B before known progression cluster
local END_ADDR   = 0x001BE300            -- ~512 B after the boss/area-flag area
local HOTKEY     = "P"                   -- press in the emulator window
local OUTPUT_DIR = ""                    -- "" = BizHawk CWD; or e.g. "C:/tmp/"

-- ----------------------------------------------------------------------------

local snapshot_count = 0
local key_was_down   = false

local function byte_to_bits(b)
    local s = ""
    for i = 7, 0, -1 do
        s = s .. (bit.band(b, bit.lshift(1, i)) ~= 0 and "1" or "0")
    end
    return s
end

local function dump()
    snapshot_count = snapshot_count + 1
    local filename = OUTPUT_DIR .. string.format("dw1_ram_snapshot_%02d.txt", snapshot_count)
    local f = io.open(filename, "w")
    if not f then
        console.log("[dw1-snapshot] ERROR: cannot write " .. filename)
        snapshot_count = snapshot_count - 1
        return
    end

    f:write(string.format("DW1 RAM snapshot #%02d\n", snapshot_count))
    f:write(string.format("domain=%s  range=0x%06X..0x%06X  frame=%d\n",
                          DOMAIN, START_ADDR, END_ADDR, emu.framecount()))
    f:write("format: <addr>: <16 bytes hex>  ||  <16 bytes binary MSB-first>\n\n")

    for base = START_ADDR, END_ADDR, 16 do
        local hex_parts, bin_parts = {}, {}
        for i = 0, 15 do
            local addr = base + i
            if addr <= END_ADDR then
                local b = memory.read_u8(addr, DOMAIN)
                hex_parts[#hex_parts + 1] = string.format("%02X", b)
                bin_parts[#bin_parts + 1] = byte_to_bits(b)
            end
        end
        f:write(string.format("0x%06X: %s  ||  %s\n",
                              base,
                              table.concat(hex_parts, " "),
                              table.concat(bin_parts, " ")))
    end

    f:close()
    console.log(string.format("[dw1-snapshot %02d] wrote %s (frame %d)",
                              snapshot_count, filename, emu.framecount()))
end

console.log("DW1 RAM snapshot tool loaded.")
console.log(string.format("  range  : 0x%06X..0x%06X (%d bytes)",
                          START_ADDR, END_ADDR, END_ADDR - START_ADDR + 1))
console.log("  domain : " .. DOMAIN)
console.log("  hotkey : " .. HOTKEY .. "  (press in the emulator window)")

while true do
    local keys     = input.get()
    local key_down = keys[HOTKEY] == true
    if key_down and not key_was_down then
        dump()
    end
    key_was_down = key_down

    gui.text(2, 2,
             string.format("DW1 snapshots: %d  (press %s)", snapshot_count, HOTKEY),
             "white", "black")

    emu.frameadvance()
end
