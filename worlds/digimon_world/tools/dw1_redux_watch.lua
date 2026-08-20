-- Watchpoint harness for PCSX-Redux: the "who touches this byte?" tool.
--
-- Launch:  powershell -File dw1_redux_launch.ps1 -Script worlds\digimon_world\tools\dw1_redux_watch.lua
--
-- Watch list: if a file named dw1_watch_config.lua exists in the working directory
-- (work\dw1_re), it must return a list of entries and replaces the DEFAULTS below:
--     return {
--         { addr = 0x001BDFCD, width = 0x74, type = "Write", name = "trigger-array" },
--         { addr = 0x000FA834, width = 4,    type = "Exec",  name = "build_shop_runtime_list" },
--     }
-- addr accepts physical (0x001B...) or KSEG0 (0x801B...) form. width = bytes covered.
-- type = 'Read' | 'Write' | 'Exec'.
--
-- Every hit appends one tab-separated line to dw1_watch_log.txt (and the console):
--     cycles  name  type  width  accessed-addr  pc  ra  byte-at-addr
-- pc is the instruction that did the access -> feed it to Ghidra. ra gives the caller.
-- Watchpoints do NOT pause emulation; add PCSX.pauseEmulator() in the callback if needed.

local DEFAULTS = {
    { addr = 0x001BDFCD, width = 0x74, type = "Write", name = "trigger-array" },
}

local function kseg0(addr)
    if addr < 0x00200000 then return addr + 0x80000000 end
    return addr
end

local watches = DEFAULTS
local cfg = io.open("dw1_watch_config.lua", "r")
if cfg then
    cfg:close()
    local chunk = assert(loadfile("dw1_watch_config.lua"))
    watches = chunk()
    print("DW1_WATCH: using dw1_watch_config.lua (" .. #watches .. " entries)")
else
    print("DW1_WATCH: no dw1_watch_config.lua in CWD, using built-in defaults")
end

local log = Support.File.open("dw1_watch_log.txt", "TRUNCATE")
local mem = PCSX.getMemPtr()

-- Keep the breakpoint objects globally referenced: GC'd breakpoints silently disarm.
_G.dw1_bps = {}

for _, w in ipairs(watches) do
    local a = kseg0(w.addr)
    local kind = w.type or "Write"
    local name = w.name or string.format("watch@%08x", a)
    local bp = PCSX.addBreakpoint(a, kind, w.width or 1, name, function(address, width, cause)
        local ok, err = pcall(function()
            local regs = PCSX.getRegisters()
            local val = mem[bit.band(address, 0x1FFFFF)]
            local line = string.format("%d\t%s\t%s\t%d\t%08x\t%08x\t%08x\t%02x\n",
                PCSX.getCPUCycles(), name, kind, width, address, regs.pc, regs.GPR.n.ra, val)
            log:write(line)
            print("DW1_WATCH\t" .. line:sub(1, -2))
        end)
        if not ok then print("DW1_WATCH callback error: " .. tostring(err)) end
    end)
    _G.dw1_bps[#_G.dw1_bps + 1] = bp
    print(string.format("DW1_WATCH: armed %-5s %08x +%d  (%s)", kind, a, w.width or 1, name))
end

print(string.format("DW1_WATCH: %d watchpoint(s) live, logging to dw1_watch_log.txt", #_G.dw1_bps))
