-- Canary probe for the .bss/heap ITEM_PARA extension (Flavor A) — PCSX-Redux port of
-- tools/dw1_bss_probe.lua (BizHawk). See docs/item_para_bss_relocation.md for the design.
--
-- Launch:  powershell -File dw1_redux_launch.ps1 -Script worlds\digimon_world\tools\dw1_redux_bss_probe.lua
-- The script only DEFINES the probe; nothing is armed at load (the BIOS boot memclear
-- would drown the watchpoints). Drive it over REST once the game is up:
--     dw1_redux_api.py lua "return dw1_probe_start()"    -- fill canary + arm everything
--     dw1_redux_api.py lua "return dw1_probe_status()"   -- one-line status
--     dw1_redux_api.py lua "return dw1_probe_fill()"     -- re-fill + reset baseline
--
-- What it does once started:
--   * Fills REGION (default 0x80160000..0x80162000, 8 KB) with 0xDEADBEEF: executed it
--     faults (no FPU on R3000), dereferenced it crashes (kseg2), read as data it's absurd.
--   * Polls every 60 vsyncs: any byte differing from the baseline is logged
--     (offset/old/new). >256 changed bytes at once = mass change (BIOS clear or savestate
--     load): logged as one line and the canary is AUTO-REFILLED.
--   * Arms Write/Read/Exec watchpoints over the region for instant pc/ra attribution.
--     Each type disarms itself after 24 hits (anti-drown); re-arm via dw1_probe_start().
--   * Heartbeat line every ~10 s so you can tell the probe is alive.
-- Log: dw1_bss_probe_log.txt in the working directory (work\dw1_re).
--
-- PASS condition for a session: only MASS-CHANGE lines from known boots/savestate loads,
-- zero watchpoint hits, zero small diffs, no crash — through the full gameplay checklist.

local BASE_PHYS = 0x00160000
local SIZE = 0x2000
local PATTERN = { 0xEF, 0xBE, 0xAD, 0xDE }  -- 0xDEADBEEF little-endian

local mem = PCSX.getMemPtr()
local log = Support.File.open("dw1_bss_probe_log.txt", "TRUNCATE")

local expected = {}
local started = false
local frames = 0
local writes_total = 0
local mass_changes = 0
local hits = { Write = 0, Read = 0, Exec = 0 }
local HIT_CAP = 24
_G.dw1_probe_bps = {}

local function stamp()
    return string.format("%d\t%d", tonumber(PCSX.getCPUCycles()) or 0, frames)
end

local function logline(s)
    log:write(stamp() .. "\t" .. s .. "\n")
    print("DW1_PROBE\t" .. s)
end

function _G.dw1_probe_fill()
    for i = 0, SIZE - 1 do
        local b = PATTERN[(i % 4) + 1]
        mem[BASE_PHYS + i] = b
        expected[i] = b
    end
    logline(string.format("FILLED %06x..%06x with DEADBEEF", BASE_PHYS, BASE_PHYS + SIZE - 1))
    return "filled"
end

local function arm_watch(kind)
    local bp = PCSX.addBreakpoint(0x80000000 + BASE_PHYS, kind, SIZE, "bssprobe:" .. kind,
        function(address, width, cause)
            local ok = pcall(function()
                hits[kind] = hits[kind] + 1
                local regs = PCSX.getRegisters()
                logline(string.format("WATCH-%s addr=%08x pc=%08x ra=%08x", kind,
                    address, regs.pc, regs.GPR.n.ra))
                if hits[kind] >= HIT_CAP then
                    logline("WATCH-" .. kind .. " hit cap reached, disarming this type")
                    for _, e in ipairs(_G.dw1_probe_bps) do
                        if e.kind == kind then e.bp:disable() end
                    end
                end
            end)
        end)
    _G.dw1_probe_bps[#_G.dw1_probe_bps + 1] = { kind = kind, bp = bp }
end

function _G.dw1_probe_start()
    _G.dw1_probe_fill()
    for _, e in ipairs(_G.dw1_probe_bps) do e.bp:disable() end
    _G.dw1_probe_bps = {}
    hits = { Write = 0, Read = 0, Exec = 0 }
    arm_watch("Write")
    arm_watch("Read")
    arm_watch("Exec")
    started = true
    logline("STARTED (poll every 60 vsyncs, W/R/X watchpoints armed)")
    return "probe started"
end

function _G.dw1_probe_status()
    return string.format("started=%s frames=%d small_writes=%d mass_changes=%d whits=%d rhits=%d xhits=%d",
        tostring(started), frames, writes_total, mass_changes, hits.Write, hits.Read, hits.Exec)
end

-- Keep the listener globally referenced: GC'd listeners silently stop firing.
_G.dw1_probe_listener = PCSX.Events.createEventListener("GPU::Vsync", function()
    frames = frames + 1
    if not started then return end
    if frames % 60 == 0 then
        local ok = pcall(function()
            local diffs = 0
            local first = -1
            for i = 0, SIZE - 1 do
                if mem[BASE_PHYS + i] ~= expected[i] then
                    diffs = diffs + 1
                    if first < 0 then first = i end
                end
            end
            if diffs == 0 then return end
            if diffs > 256 then
                mass_changes = mass_changes + 1
                logline(string.format(
                    "MASS-CHANGE %d bytes (first at +%04x, now %02x %02x %02x %02x) — refilling",
                    diffs, first, mem[BASE_PHYS + first], mem[BASE_PHYS + first + 1],
                    mem[BASE_PHYS + first + 2], mem[BASE_PHYS + first + 3]))
                _G.dw1_probe_fill()
            else
                local listed = 0
                for i = 0, SIZE - 1 do
                    local v = mem[BASE_PHYS + i]
                    if v ~= expected[i] then
                        writes_total = writes_total + 1
                        if listed < 32 then
                            logline(string.format("DIFF +%04x %02x -> %02x", i, expected[i], v))
                            listed = listed + 1
                        end
                        expected[i] = v
                    end
                end
            end
        end)
    end
    if frames % 600 == 0 then
        logline("HEARTBEAT " .. _G.dw1_probe_status())
    end
end)

logline(string.format("LOADED region=%08x size=%04x (dormant — call dw1_probe_start once in-game)",
    0x80000000 + BASE_PHYS, SIZE))
