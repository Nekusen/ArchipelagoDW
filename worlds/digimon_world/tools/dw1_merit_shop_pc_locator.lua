-- DW1 Merit-Shop Function PC Locator (BizHawk; Nymashock OR Octoshock)
--
-- Goal: find the RAM address of the merit-shop function so we can
-- inject a wrapper there. We have a static .bin offset for the
-- SUBTRACT MERIT instruction (flat 0x14D48BFC) but not its RAM home.
--
-- Strategy A (primary): register an ``event.onmemorywrite`` callback on
-- MERIT (RAM 0x80134FC4). When the callback fires, capture the CPU's
-- current PC. The first write during a purchase is the SUBTRACT MERIT
-- store, so the captured PC tells us the function's RAM-loaded base.
--
-- Strategy B (fallback): if no write callbacks fire (some PSX cores
-- silently drop them), poll MERIT every frame; on change, dump the
-- _current_ PC and a small RAM hex window around the most recent
-- captured PC.
--
-- Hotkeys (focus the emulator window):
--   M  -> set MERIT to 9999 (so you don't have to grind)
--   D  -> dump captured PCs to dw1_merit_pc_dump.txt and reset.
--   W  -> dump a 0x100-byte RAM window centered on the most recent PC.
--   X  -> reset captured-PC list (in case false positives accumulate).
--
-- Procedure:
--   1. Load this script in BizHawk.
--   2. Press M to top up Merit.
--   3. Go to Volume Villa, talk to Gekomon, "Use Merit points",
--      buy any item (S.Restore Floppy works).
--   4. The Lua console will print captured PCs in real time.
--   5. Press D to dump them to a file.
--   6. Press W to capture a hex window around the latest PC (helps me
--      identify the function entry/exit and free space for a wrapper).
--   7. Send me the dump file (`dw1_merit_pc_dump.txt`) and the W
--      window (`dw1_merit_window.txt`).

-- ----------------------------------------------------------------------------
-- Domain auto-detection
-- ----------------------------------------------------------------------------

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
    error("[dw1-pc] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
print(string.format("[dw1-pc] domain=%s prefix=0x%08X", DOMAIN, ADDR_PREFIX))

local MERIT_ADDR_RAM = 0x80134FC4   -- u16, kuseg-prefixed RAM address
local MERIT_ADDR_DOM = MERIT_ADDR_RAM - (0x80000000 - ADDR_PREFIX)

-- ----------------------------------------------------------------------------
-- Helpers to read PC across cores (BizHawk's getregisters keys vary)
-- ----------------------------------------------------------------------------

local function read_pc()
    local ok, regs = pcall(emu.getregisters)
    if not ok or type(regs) ~= "table" then return nil end
    -- Prefer "pc"; fall back to anything ending in "pc" (case-insensitive)
    if regs["pc"] ~= nil then return regs["pc"], "pc" end
    for k, v in pairs(regs) do
        if type(v) == "number" and string.match(string.lower(tostring(k)), "pc$") then
            return v, k
        end
    end
    return nil
end

local function r_u16(addr_dom)
    return memory.read_u16_le(addr_dom, DOMAIN)
end

local function w_u16(addr_dom, value)
    memory.write_u16_le(addr_dom, value, DOMAIN)
end

-- ----------------------------------------------------------------------------
-- Captured-PC log
-- ----------------------------------------------------------------------------

local pc_log = {}   -- list of {pc, frame, source}
local last_pc = nil

local function log_pc(pc, source)
    if pc == nil then return end
    last_pc = pc
    table.insert(pc_log, {pc = pc, frame = emu.framecount(), source = source})
    print(string.format("[dw1-pc] write detected -> pc=0x%08X frame=%d source=%s",
                        pc, emu.framecount(), source))
end

-- ----------------------------------------------------------------------------
-- Strategy A: memory-write callback
-- ----------------------------------------------------------------------------

local cb_id = nil
local function install_cb()
    if cb_id ~= nil then return true end
    -- Try to register a 4-byte write watch on MERIT. The signature varies
    -- by BizHawk version; try the most common form first.
    local ok, id = pcall(function()
        return event.onmemorywrite(function(addr, value, flags)
            local pc, _ = read_pc()
            log_pc(pc, "cb")
        end, MERIT_ADDR_RAM, "dw1-merit-cb", DOMAIN)
    end)
    if not ok or id == nil then
        -- Older signature without domain
        ok, id = pcall(function()
            return event.onmemorywrite(function(addr, value, flags)
                local pc, _ = read_pc()
                log_pc(pc, "cb-noscope")
            end, MERIT_ADDR_RAM)
        end)
    end
    if ok and id ~= nil then
        cb_id = id
        print(string.format("[dw1-pc] memory-write callback registered (id=%s)", tostring(id)))
        return true
    end
    print("[dw1-pc] WARNING: could not register memory-write callback. Strategy B (poll) only.")
    return false
end

-- ----------------------------------------------------------------------------
-- Strategy B: per-frame MERIT poll, captures current PC on change
-- ----------------------------------------------------------------------------

local last_merit = r_u16(MERIT_ADDR_DOM)

local function check_merit_change_and_log()
    local cur = r_u16(MERIT_ADDR_DOM)
    if cur ~= last_merit then
        local pc, _ = read_pc()
        -- Note: this PC is from AFTER the write completed; not as
        -- precise as the callback, but better than nothing.
        log_pc(pc, "poll-change(" .. last_merit .. "->" .. cur .. ")")
        last_merit = cur
    end
end

-- ----------------------------------------------------------------------------
-- Hotkey actions
-- ----------------------------------------------------------------------------

local function set_merit_max()
    w_u16(MERIT_ADDR_DOM, 9999)
    print(string.format("[dw1-pc] M -> MERIT pinned to 9999"))
    last_merit = r_u16(MERIT_ADDR_DOM)
end

local function dump_pcs()
    local path = "dw1_merit_pc_dump.txt"
    local f, err = io.open(path, "w")
    if not f then
        print(string.format("[dw1-pc] cannot open %s: %s", path, tostring(err)))
        return
    end
    f:write(string.format("# dw1_merit_pc_dump  domain=%s  frame=%d  cb=%s  count=%d\n",
                          DOMAIN, emu.framecount(), tostring(cb_id), #pc_log))
    for i, e in ipairs(pc_log) do
        f:write(string.format("%3d: pc=0x%08X frame=%d source=%s\n",
                              i, e.pc, e.frame, e.source))
    end
    f:close()
    print(string.format("[dw1-pc] D -> wrote %s (%d entries)", path, #pc_log))
end

local function reset_pcs()
    pc_log = {}
    last_pc = nil
    print("[dw1-pc] X -> captured-PC list cleared")
end

local function dump_window()
    if last_pc == nil then
        print("[dw1-pc] W -> no last_pc captured; press D after a purchase first")
        return
    end
    -- Capture +/- 0x100 bytes around the last captured PC. The PC came
    -- from RAM (e.g. 0x800Cxxxx); convert to domain offset.
    local pc_dom = last_pc - (0x80000000 - ADDR_PREFIX)
    local START = pc_dom - 0x100
    local LEN = 0x200
    local path = "dw1_merit_window.txt"
    local f = io.open(path, "w")
    f:write(string.format("# dw1_merit_window  domain=%s  pc=0x%08X  pc_dom=0x%08X\n",
                          DOMAIN, last_pc, pc_dom))
    f:write(string.format("# range: 0x%08X..0x%08X (%d bytes)\n",
                          START, START + LEN - 1, LEN))
    for off = 0, LEN - 1, 16 do
        local addr = START + off
        local row = {}
        for k = 0, 15 do
            table.insert(row, string.format("%02X", memory.read_u8(addr + k, DOMAIN)))
        end
        f:write(string.format("0x%08X: %s\n", addr, table.concat(row, " ")))
    end
    f:close()
    print(string.format("[dw1-pc] W -> wrote %s (centered at pc=0x%08X)", path, last_pc))
end

-- ----------------------------------------------------------------------------
-- Main loop
-- ----------------------------------------------------------------------------

install_cb()

local prev = {M = false, D = false, W = false, X = false}
local function check_keys()
    local k = input.get()
    local p = {
        M = k["M"] or false,
        D = k["D"] or false,
        W = k["W"] or false,
        X = k["X"] or false,
    }
    if p.M and not prev.M then set_merit_max() end
    if p.D and not prev.D then dump_pcs() end
    if p.W and not prev.W then dump_window() end
    if p.X and not prev.X then reset_pcs() end
    prev = p
end

print("[dw1-pc] ready. M=set merit  D=dump PCs  W=window  X=reset")
print("[dw1-pc] go to merit shop, buy any item; the captured PC = the SUB MERIT instruction's RAM home.")

while true do
    check_keys()
    check_merit_change_and_log()
    emu.frameadvance()
end
