-- Call-vector capture harness for function decomp verification.
--
-- Launch:  powershell -File dw1_redux_launch.ps1 -Script worlds\digimon_world\tools\dw1_redux_vectors.lua
-- Config:  dw1_vector_config.lua in the working directory (work\dw1_re) must return:
--     return {
--         out = "vectors.jsonl",         -- output file (JSON lines), truncated per session
--         max_total = 2000,              -- stop capturing after this many vectors
--         autoplay = true,               -- X/START masher to get from title into gameplay
--         funcs = {
--             { addr = 0x80106CA8, name = "getTriggerOffsets",
--               pre  = { { addr = 0x80134FB8, len = 4 } },      -- memory hexdumped at entry
--               post = {},                                       -- memory hexdumped at return
--               deref = { { reg = "a1", type = "u32" },          -- at return, read *entry-reg
--                         { reg = "a2", type = "u8" } } },
--         },
--     }
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

local function regions_json(list, into)
    local parts = {}
    for _, r in ipairs(list or {}) do
        parts[#parts + 1] = string.format('"%08X":"%s"', r.addr, hexdump(r.addr, r.len))
    end
    return "{" .. table.concat(parts, ",") .. "}"
end

for _, fn in ipairs(cfg.funcs) do
    counts[fn.name] = 0
    local pending = nil
    local entry_bp = PCSX.addBreakpoint(fn.addr, "Exec", 4, "vec:" .. fn.name, function()
        local ok, err = pcall(function()
            if total >= (cfg.max_total or 2000) then return end
            local regs = PCSX.getRegisters().GPR.n
            pending = {
                a0 = regs.a0, a1 = regs.a1, a2 = regs.a2, a3 = regs.a3,
                ra = regs.ra, pre = regions_json(fn.pre),
            }
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
                        table.concat(dparts, ","), pending.pre, regions_json(fn.post))
                    out:write(line)
                    pending = nil
                    total = total + 1
                    counts[fn.name] = counts[fn.name] + 1
                end)
                if not ok2 then print("DW1_VEC ret error: " .. tostring(err2)) end
                return false  -- one-shot: remove this return breakpoint
            end)
        end)
        if not ok then print("DW1_VEC entry error: " .. tostring(err)) end
    end)
    _G.dw1_vec_bps[#_G.dw1_vec_bps + 1] = entry_bp
    print(string.format("DW1_VEC: armed %s @ %08X", fn.name, fn.addr))
end

PCSX.WebServer = PCSX.WebServer or {}
PCSX.WebServer.Handlers = PCSX.WebServer.Handlers or {}
PCSX.WebServer.Handlers.vecstat = function()
    local parts = {}
    for k, v in pairs(counts) do parts[#parts + 1] = string.format('"%s":%u', k, v) end
    return string.format('{"total":%u,%s}\n', total, table.concat(parts, ","))
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
