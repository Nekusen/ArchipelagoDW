-- DW1 RAM-diff logger for the Digimon World 1 APWorld RE workflow.
--
-- Loads inside BizHawk's Lua Console (Tools > Lua Console > Open Script).
-- On every press of F8, the script writes a labelled snapshot of a fixed
-- MainRAM window to dw1_ram_log.txt next to BizHawk.exe. After the user
-- captures a baseline snapshot, triggers an in-game event, captures
-- another snapshot, etc., the corresponding Python parser
-- (tools/parse_ram_log.py) diffs adjacent snapshots and reports which
-- bytes actually changed.
--
-- Why snapshot-on-keypress instead of continuous logging:
--
-- DW1 mutates a fair amount of RAM every frame (sprite scratch, animation
-- timers, the in-game clock). A naive per-frame logger drowns the signal
-- in noise. By only sampling at user-chosen "before" / "after" moments,
-- we automatically filter scratch values that return to the same state
-- between markers.
--
-- Region: 0x001BDF00..0x001BE1FF (768 bytes). DWAP's named addresses
-- (ItemBankBaseAddress = 0x001BDF2C, ProsperityPoints = 0x001BE032,
-- the recruit-flag region around 0x001BDFE6, the chest-flag region
-- around 0x001BE01E, etc.) all fall inside this window.

local DOMAIN = "MainRAM"
local START_ADDRESS = 0x001BDF00
local REGION_BYTES = 0x300  -- 768 bytes
local LOG_FILE = "dw1_ram_log.txt"
local HOTKEY = "F8"

local marker_count = 0
local prev_hotkey_state = false


local function ensure_log_header()
    if marker_count == 0 then
        local f = io.open(LOG_FILE, "w")
        if f == nil then
            console.log("[ram_logger] ERROR: cannot open " .. LOG_FILE)
            return false
        end
        f:write("# DW1 RAM-diff log\n")
        f:write(string.format(
            "# region: 0x%06X..0x%06X (%d bytes), domain: %s\n",
            START_ADDRESS, START_ADDRESS + REGION_BYTES - 1, REGION_BYTES, DOMAIN
        ))
        f:write("# Each snapshot is one block beginning with a MARKER line; rows hold\n")
        f:write("# 16 bytes each, prefixed with the absolute address. Pair adjacent\n")
        f:write("# blocks via tools/parse_ram_log.py to extract bit-flip diffs.\n")
        f:write("\n")
        f:close()
    end
    return true
end


local function snapshot()
    if not ensure_log_header() then return end
    marker_count = marker_count + 1
    local frame = emu.framecount()
    local label = string.format("MARKER %03d at frame %d", marker_count, frame)
    console.log("[ram_logger] " .. label)

    local f = io.open(LOG_FILE, "a")
    if f == nil then
        console.log("[ram_logger] ERROR: cannot append to " .. LOG_FILE)
        return
    end
    f:write(string.format("=== %s ===\n", label))

    -- Read the full region as a Lua table of bytes.
    -- memory.read_bytes_as_array works on the currently-selected
    -- domain; we set it explicitly each call to be safe.
    memory.usememorydomain(DOMAIN)
    local row_size = 16
    for offset = 0, REGION_BYTES - 1, row_size do
        local addr = START_ADDRESS + offset
        local cells = {}
        for j = 0, row_size - 1 do
            local byte = memory.read_u8(addr + j)
            cells[#cells + 1] = string.format("%02X", byte)
        end
        f:write(string.format("0x%06X: %s\n", addr, table.concat(cells, " ")))
    end
    f:write("\n")
    f:close()
end


local function tick()
    -- Edge-detect F8 press (key was up last frame, down this frame).
    local current = input.get()
    local now = current[HOTKEY] == true
    if now and not prev_hotkey_state then
        snapshot()
    end
    prev_hotkey_state = now
end


-- Register the per-frame callback. event.onframeend runs once per emulated
-- frame; the script keeps running across save-load and reset.
event.onframeend(tick)

console.log("[ram_logger] Loaded. Press " .. HOTKEY .. " to capture a snapshot of "
    .. string.format("0x%06X..0x%06X (%d bytes) into %s.",
        START_ADDRESS, START_ADDRESS + REGION_BYTES - 1, REGION_BYTES, LOG_FILE))
console.log("[ram_logger] Suggested workflow: snapshot before each event, then again after.")
