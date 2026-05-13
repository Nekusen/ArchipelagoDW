-- dw1_bss_probe.lua
--
-- Stress-test a candidate .bss/heap region (post-Path-A): is it truly
-- free for AP randomizer use, or does some runtime system (allocator,
-- sound mixer, render queue, save-data buffer, indirect call table, ...)
-- touch it?
--
-- DIFFERENT FROM dw1_freeregion_probe.lua: instead of merely watching
-- for WRITES, this probe pre-fills the region with the canary pattern
-- 0xDEADBEEF before the game has a chance to use it. The canary makes
-- every possible misuse loud:
--   * Executed as code:        0xDEADBEEF decodes as `lwc1` (load FPU
--     coproc). The PSX R3000 has no FPU; the instruction raises a
--     CPU exception and the game crashes / locks. Visible.
--   * Dereferenced as pointer: points at 0xDEADBEEF in kseg2 — derefing
--     immediately crashes. Visible.
--   * Read as count / index:   obviously bogus. Most realistic uses of
--     such a value crash or render garbage. Visible.
--
-- The probe ALSO continues to poll the region for writes (anyone
-- storing data in the region, replacing the canary, is logged).
--
-- Use case: see worlds/digimon_world/docs/item_para_bss_relocation.md
-- for the design context and the playthrough test plan checklist.
--
-- USAGE:
--   1. Boot BizHawk with Nymashock and load a vanilla "Digimon World
--      (USA)" disc.
--   2. Tools > Lua Console > Open This Script > select this file.
--   3. The console will report the pre-fill and start polling.
--   4. Work through the checklist in item_para_bss_relocation.md
--      §"Test plan checklist". Watch for `WRITE DETECTED` lines and
--      for game crashes / freezes / soft-locks.
--   5. PASS = full checklist completed with zero writes AND no crashes.
--      FAIL = any write detected, or any unexplained crash.
--
-- NOTES:
--   * The probe writes to RAM at script start. It does NOT modify the
--     ROM or save state. Closing the script returns RAM to whatever
--     the game next initialises it to.
--   * Pre-fill happens once at script load. If the game (or BizHawk)
--     resets the candidate region after our fill — that's a write we
--     want to detect, and the polling loop will see it.
--   * 8 KB is the default region size — fits a 256-entry ITEM_PARA
--     with 32-byte slots. Adjust REGION_SIZE if probing a different
--     allocation size.

------------------------------------------------------------------
-- Configuration — edit these to probe a different candidate
------------------------------------------------------------------

local REGION_BASE_BARE   = 0x00160000     -- bare MainRAM offset
local REGION_SIZE        = 0x2000         -- 8 KB (= 256 ITEM_PARA slots)
local CANARY_WORD        = 0xDEADBEEF     -- visible-crash pattern

local POLL_INTERVAL_FRAMES      = 60      -- diff once per second
local HEARTBEAT_INTERVAL_FRAMES = 600     -- log liveness every 10 s

------------------------------------------------------------------
-- Domain selection (Nymashock primary, Octoshock fallback)
------------------------------------------------------------------

local REGION_BASE_KUSEG = 0x80000000 + REGION_BASE_BARE

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
local READ_BASE = IS_OCTOSHOCK and REGION_BASE_KUSEG or REGION_BASE_BARE

if IS_OCTOSHOCK then
    console.log("WARNING: Octoshock detected. This probe targets Nymashock; addresses are auto-adjusted but callbacks may behave differently.")
end

------------------------------------------------------------------
-- Pre-fill: write 0xDEADBEEF across the region
------------------------------------------------------------------

local function fill_region_with_canary()
    local n_words = REGION_SIZE / 4
    for w = 0, n_words - 1 do
        memory.write_u32_le(READ_BASE + w * 4, CANARY_WORD, DOMAIN)
    end
end

local function read_region_bytes()
    return memory.read_bytes_as_array(READ_BASE, REGION_SIZE, DOMAIN)
end

------------------------------------------------------------------
-- Snapshot helpers (diff against pre-fill)
------------------------------------------------------------------

local function format_hex_dump(arr, start_idx, count)
    local parts = {}
    for i = 0, count - 1 do
        parts[#parts + 1] = string.format("%02X", arr[start_idx + i])
    end
    return table.concat(parts, " ")
end

------------------------------------------------------------------
-- Initial setup
------------------------------------------------------------------

console.log("=== dw1_bss_probe ===")
console.log(string.format(
    "Candidate region: RAM 0x%08X .. 0x%08X (%d B)",
    REGION_BASE_KUSEG,
    REGION_BASE_KUSEG + REGION_SIZE,
    REGION_SIZE
))
console.log(string.format(
    "Memory domain: %s (Octoshock=%s)",
    DOMAIN, tostring(IS_OCTOSHOCK)
))
console.log(string.format(
    "Canary: 0x%08X (decodes as `lwc1` — illegal on R3000)",
    CANARY_WORD
))
console.log("")

console.log("Pre-filling region with canary...")
fill_region_with_canary()

local snapshot = read_region_bytes()
local writes_detected     = 0
local unique_bytes_changed = 0
local first_diff_frame    = nil
local first_diff_offset   = nil
local frame_offset        = emu.framecount()

console.log(string.format(
    "Verification — first 16 bytes after fill: %s",
    format_hex_dump(snapshot, 1, 16)
))
console.log(string.format(
    "Verification — last 16 bytes after fill:  %s",
    format_hex_dump(snapshot, REGION_SIZE - 15, 16)
))
console.log("")
console.log("--- READY. Work through the test-plan checklist in")
console.log("    docs/item_para_bss_relocation.md §Test plan checklist.")
console.log("    Watch for `WRITE DETECTED` lines below AND for any")
console.log("    crash / freeze / soft-lock during play.")
console.log("")

------------------------------------------------------------------
-- Main loop: poll for diffs, heartbeat, never exit
------------------------------------------------------------------

while true do
    local fc      = emu.framecount()
    local elapsed = fc - frame_offset

    if elapsed > 0 and elapsed % POLL_INTERVAL_FRAMES == 0 then
        local current = read_region_bytes()
        local changed_this_tick   = 0
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
            writes_detected      = writes_detected + 1
            unique_bytes_changed = unique_bytes_changed + changed_this_tick
            if first_diff_frame == nil then
                first_diff_frame  = fc
                first_diff_offset = first_off_this_tick
            end
            console.log(string.format(
                "[frame %d] WRITE DETECTED: %d bytes diff (first @ +0x%04X = RAM 0x%08X). Was=%02X Now=%02X",
                fc,
                changed_this_tick,
                first_off_this_tick,
                REGION_BASE_KUSEG + first_off_this_tick,
                snapshot[first_off_this_tick + 1],
                current[first_off_this_tick + 1]
            ))
            -- Refresh snapshot so only *new* changes are counted next tick.
            snapshot = current
        end
    end

    if elapsed > 0 and elapsed % HEARTBEAT_INTERVAL_FRAMES == 0 then
        if writes_detected == 0 then
            console.log(string.format(
                "[frame %d, ~%ds elapsed] still clean: 0 writes detected so far. (Game crashed = also a fail.)",
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
