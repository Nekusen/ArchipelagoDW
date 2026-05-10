-- DW1 Merit Shop probe (BizHawk; Nymashock OR Octoshock)
--
-- Two jobs:
--   1) Pin the Merit counter at 9999 (max) so the player never has to grind cards.
--   2) On hotkey, snapshot the RAM regions relevant to Merit Shop RE +
--      print the current PC. Snapshots are written to numbered files so
--      we can diff them after the test session.
--
-- Snapshot regions:
--   * 0x00134F00..0x00135050 (≈336 B) — the gp-relative globals page that
--     contains MERIT (0x00134FC4) + the shop's "selected item ID"
--     candidate at 0x00134F78 + the "current item PRICE" candidate at
--     0x0013500C (per static RE of the shop function at flat
--     0x14D488D8..0x14D48C28).
--   * 0x001BDFCD..0x001BE040 (200 B) — full AP-relevant trigger array.
--   * 0x0013D470..0x0013D4F0 (128 B) — inventory (item types + amounts +
--     names per SydPatches' SLUS_labels).
--
-- Hotkeys (in BizHawk, you may need to focus the emulator window after
-- toggling the Lua console):
--   M  -> set MERIT to 9999 (idempotent; press anytime).
--   S  -> snapshot all three regions to dw1_merit_snapshot_NN.txt
--         (auto-numbers; the first call writes _01.txt, then _02.txt, …).
--         Also prints the current PC ($pc) in the Lua console.
--   D  -> dump current MERIT / item-id-candidate / item-price-candidate
--         values to the Lua console (no file write).
--
-- Usage:
--   1. Launch BizHawk, load `Digimon World (USA).bin` patched with the
--      Merit-Test seed.
--   2. Tools > Lua Console > Open Script -> select this file.
--   3. The Lua Console should print the loaded banner.
--   4. Press M to top up Merit (do this whenever Merit drops too low).
--   5. Take snapshots at key moments per the protocol the human's tester
--      gave you.
--
-- File naming:
--   dw1_merit_snapshot_01.txt, _02.txt, ... — written next to this script.
--   The first snapshot per emulator session resets to _01 if no _NN file
--   exists, otherwise picks the next free NN.

-- ----------------------------------------------------------------------------
-- Domain auto-detection (mirrors dw1_bit_poker.lua / dw1_ram_snapshot.lua)
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
    error("[dw1-merit] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
print(string.format("[dw1-merit] domain=%s prefix=0x%08X", DOMAIN, ADDR_PREFIX))

-- ----------------------------------------------------------------------------
-- Constants
-- ----------------------------------------------------------------------------

local MERIT_ADDR             = 0x00134FC4   -- u16 (i16 max 9999 = 0x270F)
local SHOP_ITEM_ID_CANDIDATE = 0x00134F78   -- u8  (gp-0x6BB4 in the shop fn)
local SHOP_ITEM_PRICE_CAND   = 0x0013500C   -- s16 (gp-0x6B20 in the shop fn)

local MERIT_MAX = 9999

-- Snapshot regions: { name, start, length }
local REGIONS = {
    { name = "gp_globals", start = 0x00134F00, length = 0x150 },  -- 336 B
    { name = "trigger_array", start = 0x001BDFCD, length = 0x074 },  -- 116 B
    { name = "inventory", start = 0x0013D470, length = 0x080 },  -- 128 B
}

-- ----------------------------------------------------------------------------
-- Snapshot file numbering
-- ----------------------------------------------------------------------------

local function next_snapshot_number()
    -- Try _01..._99; return the first NN whose file doesn't exist.
    -- We can't list directories from BizHawk Lua portably, so we just
    -- attempt to open files until we find a free slot.
    for nn = 1, 99 do
        local path = string.format("dw1_merit_snapshot_%02d.txt", nn)
        local f = io.open(path, "r")
        if not f then return nn, path end
        f:close()
    end
    error("[dw1-merit] all dw1_merit_snapshot_NN.txt slots 1..99 in use")
end

-- ----------------------------------------------------------------------------
-- Read helpers (always little-endian)
-- ----------------------------------------------------------------------------

local function r_u8(addr)  return memory.read_u8(addr + ADDR_PREFIX, DOMAIN) end
local function r_u16(addr) return memory.read_u16_le(addr + ADDR_PREFIX, DOMAIN) end
local function r_s16(addr)
    local v = r_u16(addr)
    if v >= 0x8000 then return v - 0x10000 end
    return v
end

local function w_u16(addr, value)
    memory.write_u16_le(addr + ADDR_PREFIX, value, DOMAIN)
end

-- ----------------------------------------------------------------------------
-- Actions
-- ----------------------------------------------------------------------------

local function set_merit_max()
    w_u16(MERIT_ADDR, MERIT_MAX)
    print(string.format("[dw1-merit] M -> MERIT pinned to %d (0x%04X)",
                        MERIT_MAX, r_u16(MERIT_ADDR)))
end

local function dump_state()
    local m  = r_s16(MERIT_ADDR)
    local id = r_u8(SHOP_ITEM_ID_CANDIDATE)
    local pr = r_s16(SHOP_ITEM_PRICE_CAND)
    print(string.format(
        "[dw1-merit] D  MERIT=%d  itemId@0x%X=0x%02X(%d)  price@0x%X=%d",
        m, SHOP_ITEM_ID_CANDIDATE, id, id, SHOP_ITEM_PRICE_CAND, pr))
end

local function snapshot_to_file()
    local nn, path = next_snapshot_number()
    local f, err = io.open(path, "w")
    if not f then
        print(string.format("[dw1-merit] cannot open %s for write: %s", path, tostring(err)))
        return
    end
    -- Header
    f:write(string.format("# dw1_merit_snapshot %02d  domain=%s  frame=%d\n",
                          nn, DOMAIN, emu.framecount()))
    -- Try to print current PC. Octoshock's CPU register set may differ
    -- from Nymashock's; this is best-effort and we wrap in pcall.
    local pc_str = "<unavailable>"
    local ok, regs = pcall(emu.getregisters)
    if ok and type(regs) == "table" then
        for k, v in pairs(regs) do
            local lower = string.lower(tostring(k))
            if lower == "pc" or lower == "pc_r3000a" or string.match(lower, "pc$") then
                pc_str = string.format("0x%08X (key=%s)", v, k)
                break
            end
        end
    end
    f:write("# pc       = " .. pc_str .. "\n")
    f:write(string.format("# MERIT    = %d\n", r_s16(MERIT_ADDR)))
    f:write(string.format("# itemId@0x%X = 0x%02X (%d)\n",
                          SHOP_ITEM_ID_CANDIDATE,
                          r_u8(SHOP_ITEM_ID_CANDIDATE),
                          r_u8(SHOP_ITEM_ID_CANDIDATE)))
    f:write(string.format("# price@0x%X  = %d\n",
                          SHOP_ITEM_PRICE_CAND, r_s16(SHOP_ITEM_PRICE_CAND)))
    f:write("\n")
    -- Region dumps: hex bytes, 16 per line, with offset prefix.
    for _, r in ipairs(REGIONS) do
        f:write(string.format("=== region %s 0x%06X..0x%06X (%d bytes) ===\n",
                              r.name, r.start, r.start + r.length - 1, r.length))
        for off = 0, r.length - 1, 16 do
            local addr = r.start + off
            local row = {}
            local rowsize = math.min(16, r.length - off)
            for k = 0, rowsize - 1 do
                table.insert(row, string.format("%02X", r_u8(addr + k)))
            end
            f:write(string.format("0x%06X: %s\n", addr, table.concat(row, " ")))
        end
        f:write("\n")
    end
    f:close()
    print(string.format("[dw1-merit] S -> wrote %s  pc=%s  MERIT=%d  itemId=%d",
                        path, pc_str, r_s16(MERIT_ADDR), r_u8(SHOP_ITEM_ID_CANDIDATE)))
end

-- ----------------------------------------------------------------------------
-- Hotkey handling — edge-detect each frame
-- ----------------------------------------------------------------------------

local prev = {M = false, S = false, D = false}

local function check_keys()
    local keys = input.get()
    local pressed = {
        M = keys["M"] or false,
        S = keys["S"] or false,
        D = keys["D"] or false,
    }
    if pressed.M and not prev.M then set_merit_max() end
    if pressed.S and not prev.S then snapshot_to_file() end
    if pressed.D and not prev.D then dump_state() end
    prev = pressed
end

print("[dw1-merit] ready.  M=set merit 9999  S=snapshot  D=dump live")
print("[dw1-merit] Snapshots write next to this script as dw1_merit_snapshot_NN.txt")

while true do
    check_keys()
    emu.frameadvance()
end
