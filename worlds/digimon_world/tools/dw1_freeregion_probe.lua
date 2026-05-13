-- dw1_freeregion_probe.lua
--
-- Empirically verify that a candidate "free" RAM region in vanilla
-- DW1 stays unchanged through gameplay. If anything writes to it, the
-- region is not safe to repurpose for AP randomizer data.
--
-- TARGET: RAM 0x8009DBC8..0x8009F277 (5808 bytes)
--   This region was identified by static analysis (free-RAM agent 1A)
--   as a Cave6-style libgs-leftover region: bytes present in the SLUS
--   .bin but with zero inbound jal/j/branch targets and zero
--   lui+addiu reads. We want to use it as the new home for a
--   relocated, expanded ITEM_PARA table (256 entries x 32 bytes = 8 KB).
--
-- USAGE:
--   1. Open BizHawk. Load your vanilla "Digimon World (USA).bin" with
--      the **Nymashock** PSX core (Octoshock won't work — different
--      memory-domain semantics).
--   2. Tools > Lua Console > Open This Script > select this file.
--   3. The console will print an initial snapshot summary.
--   4. Play normally for 60-90 seconds. Exercise as many systems as
--      you can:
--        - title screen -> File City (Jijimon's House)
--        - leave the house, walk around outside
--        - one wild battle (any digimon)
--        - one digivolution (or just check the partner stats)
--        - one map transition (Native Forest, Tropical Jungle, etc.)
--        - open the merit shop / regular shop UI if convenient
--        - save & reload (optional but useful)
--   5. Watch the console for "WRITE DETECTED" lines.
--   6. After the play session, press Stop in Lua Console (or close it)
--      and read the final summary.
--
-- INTERPRETATION:
--   - If TOTAL writes == 0 after a full session: region is empirically
--     free. Path A is safe to use 0x8009DBC8 for the relocated
--     ITEM_PARA. Tell Claude.
--   - If writes ARE detected: region is NOT free. Note which RAM
--     offset got hit and when. Claude will pick the next candidate
--     (0x800C3860, 4336 bytes — the next-best from agent 1A).
--
-- NOTE: The probe is read-only. It will NOT modify game state.

------------------------------------------------------------------
-- Configuration
------------------------------------------------------------------

local REGION_BASE_BARE = 0x0009DBC8       -- bare MainRAM offset
local REGION_BASE_KUSEG = 0x80000000 + REGION_BASE_BARE  -- for log lines
local REGION_SIZE = 5808                  -- bytes (= 0x8009F278 - 0x8009DBC8)
local POLL_INTERVAL_FRAMES = 60           -- once per second @ 60fps
local HEARTBEAT_INTERVAL_FRAMES = 600     -- "still running" once per 10s

------------------------------------------------------------------
-- Domain selection (Nymashock primary, Octoshock fallback warning)
------------------------------------------------------------------

local function pick_domain()
    local list = memory.getmemorydomainlist()
    for _, d in ipairs(list) do
        if d == "MainRAM" then return "MainRAM", false end
    end
    for _, d in ipairs(list) do
        if d == "System Bus" then return "System Bus", true end
    end
    error("Cannot find MainRAM (Nymashock) or System Bus (Octoshock) memory domain. Is a PSX core loaded?")
end

local DOMAIN, IS_OCTOSHOCK = pick_domain()
if IS_OCTOSHOCK then
    console.log("WARNING: Octoshock detected — this probe is designed for Nymashock.")
    console.log("         Octoshock's System Bus uses kuseg-prefixed addresses; the")
    console.log("         probe may report false negatives if the offset math drifts.")
end

------------------------------------------------------------------
-- Snapshot helpers
------------------------------------------------------------------

local function read_region()
    -- read_bytes_as_array returns a 1-indexed Lua table of ints.
    return memory.read_bytes_as_array(REGION_BASE_BARE, REGION_SIZE, DOMAIN)
end

local function format_hex_dump(arr, start_idx, count)
    local parts = {}
    for i = 0, count - 1 do
        parts[#parts + 1] = string.format("%02X", arr[start_idx + i])
    end
    return table.concat(parts, " ")
end

------------------------------------------------------------------
-- State
------------------------------------------------------------------

local snapshot = read_region()
local writes_detected = 0
local unique_bytes_changed = 0  -- best-effort cumulative
local first_diff_frame = nil
local first_diff_offset = nil
local frame_offset = emu.framecount()

------------------------------------------------------------------
-- Initial output
------------------------------------------------------------------

console.log(string.format(
    "=== dw1_freeregion_probe ==="
))
console.log(string.format(
    "Watching RAM 0x%08X..0x%08X (%d bytes) on domain %q",
    REGION_BASE_KUSEG,
    REGION_BASE_KUSEG + REGION_SIZE,
    REGION_SIZE,
    DOMAIN
))
console.log(string.format(
    "Poll cadence: every %d frames (~%.2fs at 60fps)",
    POLL_INTERVAL_FRAMES, POLL_INTERVAL_FRAMES / 60
))
console.log(string.format(
    "Initial snapshot first 32 bytes: %s",
    format_hex_dump(snapshot, 1, 32)
))
console.log(string.format(
    "Initial snapshot last 32 bytes:  %s",
    format_hex_dump(snapshot, REGION_SIZE - 31, 32)
))
console.log("--- Play now. Writes to this region will be logged below. ---")

------------------------------------------------------------------
-- Frame loop
------------------------------------------------------------------

while true do
    local fc = emu.framecount()
    local elapsed = fc - frame_offset

    if elapsed % POLL_INTERVAL_FRAMES == 0 and elapsed > 0 then
        local current = read_region()
        local changed_this_tick = 0
        local first_off_this_tick = nil
        for i = 1, REGION_SIZE do
            if current[i] ~= snapshot[i] then
                if first_off_this_tick == nil then
                    first_off_this_tick = i - 1
                end
                changed_this_tick = changed_this_tick + 1
            end
        end

        if changed_this_tick > 0 then
            writes_detected = writes_detected + 1
            unique_bytes_changed = unique_bytes_changed + changed_this_tick
            if first_diff_frame == nil then
                first_diff_frame = fc
                first_diff_offset = first_off_this_tick
            end
            console.log(string.format(
                "[frame %d] WRITE DETECTED: %d bytes diff (first @ +0x%04X = RAM 0x%08X). Old=%02X New=%02X",
                fc,
                changed_this_tick,
                first_off_this_tick,
                REGION_BASE_KUSEG + first_off_this_tick,
                snapshot[first_off_this_tick + 1],
                current[first_off_this_tick + 1]
            ))
            -- Refresh snapshot so we only count *new* changes next time.
            snapshot = current
        end
    end

    -- Heartbeat
    if elapsed % HEARTBEAT_INTERVAL_FRAMES == 0 and elapsed > 0 then
        if writes_detected == 0 then
            console.log(string.format(
                "[frame %d, ~%ds elapsed] still clean: 0 writes detected so far",
                fc, math.floor(elapsed / 60)
            ))
        else
            console.log(string.format(
                "[frame %d, ~%ds elapsed] cumulative: %d write events, ~%d bytes touched, first at frame %d offset +0x%04X",
                fc,
                math.floor(elapsed / 60),
                writes_detected,
                unique_bytes_changed,
                first_diff_frame,
                first_diff_offset
            ))
        end
    end

    emu.frameadvance()
end
