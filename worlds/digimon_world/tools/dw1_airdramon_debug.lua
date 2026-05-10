-- DW1 Airdramon-arming debug snapshot tool (BizHawk; Nymashock OR Octoshock)
--
-- Captures every piece of in-game state that Section_5 of Script 165/178,
-- Section_51 of Script 210, and Section_57 of Script 162 read when deciding
-- whether to arm the Airdramon ambush. Designed to be run once on a known-
-- working run, once on the failing run, then text-diffed.
--
-- Usage:
--   1. Tools > Lua Console > Open Script > select this file.
--   2. Position the player however you want (e.g. inside Jijimon's House,
--      just before talking to him).
--   3. Press P in the emulator window. A numbered file is written to
--      OUTPUT_DIR (default: same directory as this script).
--   4. Repeat on the other run, then diff the two files.
--
-- Format: hierarchical labeled key/value blocks. Each line is independent so
-- a textual diff highlights only the meaningful changes.

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
    error("[dw1-airdramon-debug] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
local HOTKEY     = "P"
local OUTPUT_DIR = ""  -- empty = BizHawk CWD; or e.g. "C:/opt/dev/AP/ArchipelagoDW/worlds/digimon_world/tools/"

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

local function rb(addr) return memory.readbyte(ADDR_PREFIX + addr) end
local function rh(addr) return memory.read_u16_le(ADDR_PREFIX + addr) end
local function rw(addr) return memory.read_u32_le(ADDR_PREFIX + addr) end
local function bit_at(addr, b) return bit.band(rb(addr), bit.lshift(1, b)) ~= 0 and 1 or 0 end

-- Trigger N -> byte 0x001BDFCD + N/8, bit (N%8)
-- (verified canonical via dw1_settrigger_formula memory note)
local TRIG_BASE = 0x001BDFCD
local function trig(n)
    local byte_addr = TRIG_BASE + math.floor(n / 8)
    local bit_idx   = n % 8
    return bit_at(byte_addr, bit_idx)
end

-- ---------------------------------------------------------------------------
-- Capture
-- ---------------------------------------------------------------------------

-- Named triggers Section_5 / Section_51 / Section_57 actually read or write,
-- plus screen-load context. Each entry: {trigger_id, label}
local NAMED_TRIGGERS = {
    {  3, "story slot 3 (post-battle)"},
    { 50, "Analogman defeated"},
    { 87, "Greymon ambush armed"},
    { 88, "Airdramon ambush done"},
    { 89, "Birdra delivery NPC seen"},
    {200, "(unused recruit slot 0)"},
    {201, "Analogman evil felt (Jijimon)"},
    {202, "Machinedramon defeated"},
    {203, "Agumon recruited"},
    {204, "Betamon recruited"},
    {205, "Greymon recruited (vanilla)"},
    {206, "Devimon recruited"},
    {207, "Airdramon recruited (endgame)"},
    {208, "Tyrannomon recruited"},
    {209, "Meramon recruited"},
    {210, "Seadramon recruited"},
    {211, "Numemon recruited"},
    {212, "MetalGreymon recruited"},
    {213, "Mamemon recruited"},
    {214, "Monzaemon recruited"},
    {215, "Chained Melon given"},
    {216, "Tamer level up flag"},
    {217, "Gabumon recruited"},
    {218, "Elecmon recruited"},
    {219, "Kabuterimon recruited"},
    {220, "Angemon recruited"},
    {221, "Birdramon recruited"},
    {222, "Garurumon recruited"},
    {223, "Frigimon recruited"},
    {224, "Whamon recruited"},
    {225, "Vegiemon recruited"},
    {226, "SkullGreymon recruited"},
    {227, "MetalMamemon recruited"},
    {228, "Vademon recruited"},
    {231, "Patamon recruited"},
    {232, "Kunemon recruited"},
    {233, "Unimon recruited"},
    {234, "Ogremon recruited"},
    {235, "Shellmon recruited"},
    {236, "Centarumon recruited"},
    {237, "Bakemon recruited"},
    {238, "Drimogemon recruited"},
    {243, "(Section_5 cond: trigger 243)"},
    {245, "Biyomon recruited"},
    {246, "Palmon recruited"},
    {247, "Monochromon recruited"},
    {354, "Airdramon ambush armed"},
    {355, "Airdramon ambush completed marker"},
    {320, "Old Fishrod given (canonical)"},
}

-- AP-side BEATEN bits: trigger N+520 for each recruit. Computed for the
-- specific recruits whose visibility the patcher rewires to AP control.
local NAMED_BEATEN = {
    {725, "Greymon AP delivered"},
    {727, "Airdramon AP delivered (always 0; dropped)"},
    {730, "Seadramon AP delivered"},
    {732, "MetalGreymon AP delivered"},
    {734, "Monzaemon AP delivered"},
    {740, "Angemon AP delivered"},
    {741, "Birdramon AP delivered"},
    {745, "Vegiemon AP delivered"},
}

local function dump()
    local fname = OUTPUT_DIR .. string.format("dw1_airdramon_debug_%02d.txt", os.time() % 100)
    -- Use a counter so two captures in the same second don't collide
    local counter = (rawget(_G, "_dw1_airdramon_debug_count") or 0) + 1
    _G._dw1_airdramon_debug_count = counter
    fname = OUTPUT_DIR .. string.format("dw1_airdramon_debug_%02d.txt", counter)

    local f = io.open(fname, "w")
    if not f then
        console.log("[dw1-airdramon-debug] ERROR: cannot write " .. fname)
        return
    end

    f:write(string.format("=== DW1 Airdramon-arming snapshot #%02d ===\n", counter))
    f:write(string.format("domain=%s  frame=%d  os.time=%d\n\n", DOMAIN, emu.framecount(), os.time()))

    -- ----- Screen + script binding -----
    f:write("[screen + script]\n")
    f:write(string.format("  CURRENT_SCREEN @ 0x00134DA8 = %d (0x%02X)\n", rb(0x00134DA8), rb(0x00134DA8)))
    f:write(string.format("  CURRENT_SCRIPT_ID @ 0x00134FC0 = %d\n", rb(0x00134FC0)))
    f:write(string.format("  CURRENT_SCREEN_ALT @ 0x00134FFE = %d (DWAP-style 2-byte)\n", rh(0x00134FFE)))
    f:write(string.format("  RAM_LAST_SCRIPT @ 0x00134FDC = 0x%04X\n", rh(0x00134FDC)))
    f:write("\n")

    -- ----- Player stats (only the ones we know addresses for) -----
    f:write("[player stats]\n")
    f:write(string.format("  pstat(1) PROSPERITY @ 0x001BE032 = %d\n", rb(0x001BE032)))
    f:write(string.format("  RAM_CURRENT_BITS    @ 0x00134EB8 = %d (money)\n", rw(0x00134EB8)))
    f:write(string.format("  RAM_CURRENT_OFFENSE @ 0x001557E0 = %d\n", rh(0x001557E0)))
    f:write(string.format("  RAM_CURRENT_DEFENSE @ 0x001557E2 = %d\n", rh(0x001557E2)))
    f:write(string.format("  RAM_CURRENT_SPEED   @ 0x001557E4 = %d\n", rh(0x001557E4)))
    f:write(string.format("  RAM_CURRENT_BRAINS  @ 0x001557E6 = %d\n", rh(0x001557E6)))
    -- pstat(16) and pstat(103) addresses are not in addresses.py — capture
    -- a wider RAM region around the partner-stats block so a diff catches
    -- changes even without a precise mapping.
    f:write("  partner-stats region (0x00155780..0x00155830, raw):\n")
    for base = 0x00155780, 0x00155820, 16 do
        local row = ""
        for i = 0, 15 do row = row .. string.format("%02X ", rb(base + i)) end
        f:write(string.format("    0x%08X: %s\n", base, row))
    end
    f:write("\n")

    -- ----- Named triggers (decoded from the trigger array) -----
    f:write("[named triggers]\n")
    for _, t in ipairs(NAMED_TRIGGERS) do
        local id, label = t[1], t[2]
        local byte_addr = TRIG_BASE + math.floor(id / 8)
        local bit_idx   = id % 8
        f:write(string.format("  trig %3d = %d  (byte 0x%08X bit %d, mask 0x%02X)  %s\n",
            id, trig(id), byte_addr, bit_idx, 1 << bit_idx, label))
    end
    f:write("\n")

    -- ----- AP-side BEATEN bits -----
    f:write("[AP BEATEN bits]\n")
    for _, t in ipairs(NAMED_BEATEN) do
        local id, label = t[1], t[2]
        local byte_addr = TRIG_BASE + math.floor(id / 8)
        local bit_idx   = id % 8
        f:write(string.format("  trig %3d = %d  (byte 0x%08X bit %d)  %s\n",
            id, trig(id), byte_addr, bit_idx, label))
    end
    f:write("\n")

    -- ----- NPC entity records (8 slots, talk-script for each) -----
    f:write("[NPC slots @ 0x00155828, stride 0x68]\n")
    for i = 0, 7 do
        local rec = 0x00155828 + i * 0x68
        local model    = rb(rec + 0x00)
        local section  = rb(rec + 0x65)
        local x        = rh(rec + 0x10)  -- guess at x-coord; offset may vary
        local y        = rh(rec + 0x12)  -- guess at y-coord
        f:write(string.format("  slot %d: model=0x%02X (%d)  talk-section=%d  pos=(%d,%d)\n",
            i, model, model, section, x, y))
    end
    f:write("\n")

    -- ----- Raw blocks (hard-to-decode but easy-to-diff) -----
    local function dump_range(label, start_addr, end_addr)
        f:write(string.format("[%s]  0x%08X..0x%08X\n", label, start_addr, end_addr))
        for base = start_addr, end_addr, 16 do
            local hex_part = ""
            local bin_part = ""
            for i = 0, 15 do
                if base + i > end_addr then break end
                local b = rb(base + i)
                hex_part = hex_part .. string.format("%02X ", b)
                local bs = ""
                for j = 7, 0, -1 do
                    bs = bs .. ((bit.band(b, bit.lshift(1, j)) ~= 0) and "1" or "0")
                end
                bin_part = bin_part .. bs .. " "
            end
            f:write(string.format("  0x%08X: %s || %s\n", base, hex_part, bin_part))
        end
        f:write("\n")
    end

    dump_range("trigger array (0x001BDFCD..0x001BE040)",     0x001BDFCD, 0x001BE040)
    dump_range("AP-bits mirror (0x001BDFF0..0x001BDFF7)",    0x001BDFF0, 0x001BDFF7)
    dump_range("Permanent-beaten scratch (0x001BDFF8..0x001BDFFF)", 0x001BDFF8, 0x001BDFFF)
    dump_range("BEATEN block (0x001BE027..0x001BE02E)",      0x001BE027, 0x001BE02E)
    dump_range("Item bank (0x001BDF2C..0x001BDFAB)",         0x001BDF2C, 0x001BDFAB)
    dump_range("items_received counter (0x001BDF20..0x001BDF22)", 0x001BDF20, 0x001BDF22)

    f:close()
    console.log("[dw1-airdramon-debug] wrote " .. fname)
    gui.addmessage("airdramon-debug snapshot #" .. counter)
end

-- ---------------------------------------------------------------------------
-- Main loop: poll for hotkey
-- ---------------------------------------------------------------------------

local key_was_down = false
console.log("[dw1-airdramon-debug] loaded; press " .. HOTKEY .. " in the emulator window to capture")

while true do
    local pressed = (input.get()[HOTKEY] == true)
    if pressed and not key_was_down then dump() end
    key_was_down = pressed
    emu.frameadvance()
end
