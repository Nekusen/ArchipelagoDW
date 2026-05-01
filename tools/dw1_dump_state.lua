-- DW1 state dump tool (NTSC-U / SLUS-01032).
-- Differential RE helper: press F8 in BizHawk to append a snapshot of the
-- trigger bit array to a log file. Take snapshots before and after each
-- state change (e.g. before/after a destination becomes available in
-- Birdramon's menu); the diff identifies the gating bit.
--
-- Usage:
--   1. Tools -> Lua Console -> Open Script -> select this file.
--   2. The script registers an F8 hotkey and idles.
--   3. Play the game. Press F8 whenever you want a snapshot.
--   4. Each press appends one record to the log file at LOG_PATH below.
--   5. Keep your own annotations in a separate text file describing what
--      each snapshot captured (e.g. "snapshot 3 = 2 destinations visible:
--      Gear Savanna and Misty Trees").
--   6. To start fresh, just delete the log file before snapshotting.
--
-- Output format: one block per snapshot, ASCII-only, hex-dumped 16 bytes
-- per row with absolute addresses on the left. Easy to diff with any
-- text-comparison tool.

memory.usememorydomain("MainRAM")

local LOG_PATH = [[c:\opt\dev\AP\ArchipelagoDW\tools\dw1_dumps.log]]

-- Trigger bit array spans 0x001BDFCD..0x001BE040 inclusive (116 bytes).
-- Includes recruit bits (200+X), beat-fight bits (220+X), AP-mirror block
-- (720+X), chest bits, and gap regions used for story-event flags.
local TRIGGER_BASE = 0x001BDFCD
local TRIGGER_LEN  = 116

-- Sanity-check fields written into each snapshot header.
local MONEY_ADDR = 0x00134EB8

local snapshot_count = 0

local function dump()
    snapshot_count = snapshot_count + 1
    local frame = emu.framecount()
    local money = memory.read_u32_le(MONEY_ADDR)

    local f = io.open(LOG_PATH, "a")
    if not f then
        console.log("[dw1_dump] ERROR: could not open " .. LOG_PATH)
        return
    end

    f:write(string.format(
        "=== snapshot %d  frame %d  money %d ===\n",
        snapshot_count, frame, money))
    f:write(string.format(
        "triggers @ 0x%08X (%d bytes):\n", TRIGGER_BASE, TRIGGER_LEN))
    for row_start = 0, TRIGGER_LEN - 1, 16 do
        local cells = {}
        local row_end = math.min(row_start + 15, TRIGGER_LEN - 1)
        for i = row_start, row_end do
            cells[#cells + 1] = string.format(
                "%02x", memory.read_u8(TRIGGER_BASE + i))
        end
        f:write(string.format(
            "  %08X: %s\n",
            TRIGGER_BASE + row_start, table.concat(cells, " ")))
    end
    f:write("\n")
    f:close()

    console.log(string.format(
        "[dw1_dump] snapshot %d written (frame %d, money %d).",
        snapshot_count, frame, money))
end

-- Edge-triggered F8 hotkey: fires once per press, not once per frame
-- while held.
local f8_was_down = false
event.onframeend(function()
    local keys = input.get()
    local f8_now = keys.F8 == true
    if f8_now and not f8_was_down then
        dump()
    end
    f8_was_down = f8_now
end)

console.log("[dw1_dump] loaded. Press F8 to snapshot.")
console.log("[dw1_dump] log: " .. LOG_PATH)
