-- Call-vector capture harness for function decomp verification.
--
-- Launch:  powershell -File dw1_redux_launch.ps1 -Script worlds\digimon_world\tools\dw1_redux_vectors.lua
-- Config:  dw1_vector_config.lua in the working directory (work\dw1_re) must return:
--     return {
--         out = "vectors.jsonl",         -- output file (JSON lines), truncated per session
--         max_total = 2000,              -- stop capturing after this many vectors
--         autoplay = true,               -- X/START masher to get from title into gameplay
--         funcs = {
--             -- `max` (optional) caps THIS function's vectors, so one very hot function cannot
--             -- consume the whole `max_total` budget and starve the rest of the unit.
--             { addr = 0x80106CA8, name = "getTriggerOffsets", max = 4000,
--               pre  = { { addr = 0x80134FB8, len = 4 } },      -- memory hexdumped at entry
--               post = {},                                       -- memory hexdumped at return
--               deref = { { reg = "a1", type = "u32" },          -- at return, read *entry-reg
--                         { reg = "a2", type = "u8" } } },
--         },
--     }
--
-- A pre/post region addresses memory in one of three ways -- pick exactly one key:
--     { addr = 0x80134FB8, len = 4 }   -- STATIC address
--     { reg  = "a0",       len = 8 }   -- address = that register's value AT ENTRY
--     { ptr  = 0x80134FDC, len = 8 }   -- address = the u32 stored at 0x80134FDC, read when the
--                                      --   region is dumped (so a `post` ptr region follows the
--                                      --   pointer's NEW value, a `pre` one its old value)
-- `reg`/`ptr` regions are what make pointer-walking functions (script VM, list builders)
-- verifiable: the replay harness reloads each dumped region at its RESOLVED address, which is
-- the JSON key, so the model sees the same bytes the real function saw. A region whose address
-- resolves outside main RAM is skipped (emitted as null) rather than dumping garbage.
--
-- Every completed call emits one JSON line:
--     {"name":..., "cycles":..., "a0":..a3.., "v0":..., "v1":..., "deref":{...}, "pre":{...}, "post":{...}}
-- Poll progress over REST: GET /api/v1/lua/vecstat
--
-- Limitation: assumes the watched functions do not recurse. A second entry before the first
-- return overwrites the pending slot (the older call is dropped, not corrupted).

local cfg = assert(loadfile("dw1_vector_config.lua"))()
local mem = PCSX.getMemPtr()
local out = Support.File.open(cfg.out or "vectors.jsonl", "TRUNCATE")
local total = 0
local counts = {}
local leaked = {}   -- per function: return breakpoints reclaimed because the call never returned
_G.dw1_vec_bps = {}

local function phys(a) return bit.band(a, 0x1FFFFF) end

local function hexdump(addr, len)
    local t = {}
    local base = phys(addr)
    for i = 0, len - 1 do t[#t + 1] = string.format("%02X", mem[base + i]) end
    return table.concat(t)
end

local function readval(addr, ty)
    local p = phys(addr)
    if ty == "u8" then return mem[p] end
    if ty == "u16" then return mem[p] + mem[p + 1] * 0x100 end
    return mem[p] + mem[p + 1] * 0x100 + mem[p + 2] * 0x10000 + mem[p + 3] * 0x1000000  -- u32
end

-- Resolve a region descriptor to an absolute address: static (`addr`), register-at-entry
-- (`reg`, taken from the captured entry registers) or pointer-indirect (`ptr`).
local function resolve_addr(r, entry_regs)
    if r.addr then return r.addr end
    if r.reg then return entry_regs and entry_regs[r.reg] or nil end
    if r.ptr then return readval(r.ptr, "u32") end
    return nil
end

-- Main RAM is 2 MB, mirrored at 0x00000000 / 0x80000000 / 0xA0000000. Anything else (scratchpad,
-- I/O, BIOS, or a null/garbage pointer) must not be hexdumped -- phys() would alias it into RAM.
--
-- Deliberately plain arithmetic, no bit ops: LuaJIT's bit library returns SIGNED 32-bit results,
-- so `bit.band(0x80134FB8, 0xFF000000) ~= 0x80000000` is TRUE (-2147483648 vs 2147483648) and a
-- segment test written that way rejects every KSEG0 address -- which is exactly what it did on
-- the first capture run, nulling all regions.
local function in_main_ram(addr, len)
    if not addr or addr == 0 then return false end
    local u = addr % 0x100000000          -- normalise to unsigned 32-bit
    local seg = u - (u % 0x1000000)       -- top byte, still unsigned
    if seg ~= 0x00000000 and seg ~= 0x80000000 and seg ~= 0xA0000000 then return false end
    return (u % 0x200000) + len <= 0x200000
end

local function regions_json(list, entry_regs)
    local parts = {}
    for _, r in ipairs(list or {}) do
        local addr = resolve_addr(r, entry_regs)
        if in_main_ram(addr, r.len) then
            parts[#parts + 1] = string.format('"%08X":"%s"', addr, hexdump(addr, r.len))
        else
            parts[#parts + 1] = string.format('"%s":null', r.reg or r.ptr and
                string.format("ptr:%08X", r.ptr) or string.format("%08X", r.addr or 0))
        end
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

for _, fn in ipairs(cfg.funcs) do
    counts[fn.name] = 0
    local pending = nil
    local prev_ret_bp = nil
    local entry_bp = PCSX.addBreakpoint(fn.addr, "Exec", 4, "vec:" .. fn.name, function()
        local ok, err = pcall(function()
            if total >= (cfg.max_total or 2000) then return end
            if fn.max and counts[fn.name] >= fn.max then return end
            local regs = PCSX.getRegisters().GPR.n
            pending = {
                a0 = regs.a0, a1 = regs.a1, a2 = regs.a2, a3 = regs.a3,
                ra = regs.ra, pre = regions_json(fn.pre, regs), regs = regs,
            }
            -- Reclaim the previous call's return breakpoint if it never fired. A call that does
            -- not come back through the captured `ra` (tail call, longjmp, or a nested entry
            -- overwriting the pending slot) would otherwise leave its one-shot breakpoint armed
            -- forever; across a long session those accumulate until addBreakpoint starts failing
            -- and the emulator dies. That failure was observed repeatedly before this existed.
            if prev_ret_bp then
                pcall(function() prev_ret_bp:remove() end)
                leaked[fn.name] = (leaked[fn.name] or 0) + 1
            end
            local ret_bp
            ret_bp = PCSX.addBreakpoint(regs.ra, "Exec", 4, "ret:" .. fn.name, function()
                local ok2, err2 = pcall(function()
                    if pending == nil then return end
                    local r2 = PCSX.getRegisters().GPR.n
                    local dparts = {}
                    for _, d in ipairs(fn.deref or {}) do
                        dparts[#dparts + 1] = string.format('"%s":%u', d.reg, readval(pending[d.reg], d.type))
                    end
                    local line = string.format(
                        '{"name":"%s","cycles":%u,"a0":%u,"a1":%u,"a2":%u,"a3":%u,"v0":%u,"v1":%u,' ..
                        '"deref":{%s},"pre":%s,"post":%s}\n',
                        fn.name, tonumber(PCSX.getCPUCycles()) or 0,
                        pending.a0, pending.a1, pending.a2, pending.a3, r2.v0, r2.v1,
                        table.concat(dparts, ","), pending.pre, regions_json(fn.post, pending.regs))
                    out:write(line)
                    pending = nil
                    prev_ret_bp = nil  -- fired: nothing left to reclaim
                    total = total + 1
                    counts[fn.name] = counts[fn.name] + 1
                end)
                if not ok2 then print("DW1_VEC ret error: " .. tostring(err2)) end
                return false  -- one-shot: remove this return breakpoint
            end)
            prev_ret_bp = ret_bp
        end)
        if not ok then print("DW1_VEC entry error: " .. tostring(err)) end
    end)
    _G.dw1_vec_bps[#_G.dw1_vec_bps + 1] = entry_bp
    print(string.format("DW1_VEC: armed %s @ %08X%s", fn.name, fn.addr,
        fn.max and string.format(" (max %d)", fn.max) or ""))
end

PCSX.WebServer = PCSX.WebServer or {}
PCSX.WebServer.Handlers = PCSX.WebServer.Handlers or {}
PCSX.WebServer.Handlers.vecstat = function()
    local parts = {}
    for k, v in pairs(counts) do parts[#parts + 1] = string.format('"%s":%u', k, v) end
    local lparts = {}
    for k, v in pairs(leaked) do lparts[#lparts + 1] = string.format('"%s":%u', k, v) end
    local fmt = '{"total":%u,%s,"unreturned":{%s}}' .. string.char(10)
    return string.format(fmt, total, table.concat(parts, ","), table.concat(lparts, ","))
end

-- Crude autoplay: alternate START and X (cross) presses to get from the title screen into the
-- opening and through dialog boxes. Enough to make trigger/script functions fire.
if cfg.autoplay then
    local pad = PCSX.SIO0.slots[1].pads[1]
    local B = PCSX.CONSTS.PAD.BUTTON
    local frame = 0
    _G.dw1_vec_autoplay = PCSX.Events.createEventListener("GPU::Vsync", function()
        frame = frame + 1
        local phase = frame % 120
        if phase == 0 then pad.setOverride(B.START)
        elseif phase == 20 then pad.clearOverride(B.START)
        elseif phase == 60 then pad.setOverride(B.CROSS)
        elseif phase == 80 then pad.clearOverride(B.CROSS)
        end
    end)
    print("DW1_VEC: autoplay masher on (START/X alternating)")
end

print("DW1_VEC: capturing to " .. (cfg.out or "vectors.jsonl"))
