-- DW1 RAM Snapshot Tool (BizHawk; Nymashock OR Octoshock)
--
-- **Canonical RE/discovery tool.** When you need to find what RAM byte/bit
-- changes during an in-game event (NPC give, area unlock, cutscene, ...),
-- this is the go-to: take a snapshot before, trigger the event, take
-- another snapshot, then diff with `dw1_ram_diff.py` (sibling file).
-- See `README.md` in this directory for the canonical workflow.
--
-- Usage:
--   1. Boot BizHawk with the running DW1 ISO. Either PSX core works.
--   2. Tools > Lua Console > Open Script > pick this file.
--   3. Position the player just before the state-changing event.
--      Press P (in the emulator window, NOT the Lua console) -> snapshot 01.
--   4. Trigger the event (cross the bridge, talk to the NPC, etc.).
--      Press P again -> snapshot 02.
--   5. Diff the two output files. Bytes/bits that differ are candidates
--      for the gate / flag / state.
--
-- Output: dw1_ram_snapshot_NN.txt in OUTPUT_DIR (configurable below).
-- Format: 16 bytes per line as both hex and MSB-first binary, so single-bit
-- flips are visible by eye in the binary column. Format matches what
-- dw1_ram_diff.py expects.

-- Auto-detect the right RAM domain. PSX cores expose this differently:
--   * Nymashock: "MainRAM" — 2 MiB at offset 0; bare RAM offsets work.
--   * Octoshock: no Main RAM domain at all; main RAM only addressable via
--     "System Bus" with the 0x80000000 kuseg mirror prefix.
-- See memory note `nymashock_memory_domain.md`.
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
    error("[dw1-snapshot] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
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
                local b = memory.read_u8(addr + ADDR_PREFIX, DOMAIN)
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
