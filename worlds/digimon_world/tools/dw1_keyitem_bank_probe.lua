-- DW1 Key-Item Bank Probe (BizHawk; Nymashock OR Octoshock)
--
-- Diagnoses why AP-delivered Mansion Key / Frig Key reportedly do not
-- appear in the in-game bank UI, even though the bank deliverer
-- (`_make_bank_deliverer` in client.py) writes 1 byte to
-- `RAM_ITEM_BANK_BASE + slot`. Slot 119 = Mansion Key, slot 123 =
-- Frig Key.
--
-- Two competing hypotheses:
--   (A) the byte is never written -- deliverer is misrouted or skipped
--   (B) the byte IS written, but the bank UI filters out this slot
--       range (e.g. by ITEM_PARA category)
--
-- This probe distinguishes them: it shows the live byte value at every
-- key-item bank slot. The user runs the probe, lets AP deliver the
-- item, and observes whether the byte transitions 0 -> 1.
--
--   * byte == 0 forever -> hypothesis (A); investigate the deliverer
--   * byte goes 0 -> 1 but the bank UI still hides it -> hypothesis
--     (B); investigate the bank UI's display filter
--
-- The probe also offers a "force-poke" hotkey (P) that writes 1 to
-- every key-item bank slot at once. Useful for confirming whether the
-- bank UI displays the slot when the byte is definitely non-zero,
-- independently of the AP delivery path.
--
-- Usage:
--   1. Load this script in BizHawk: Tools > Lua Console > Open Script.
--   2. The HUD shows live byte values for slots 115..123 (key-item
--      range) and the AP scratch counter at 0x001BDF20..0x001BDF22.
--   3. Hotkeys (in the emulator window):
--        P -> poke 1 into every key-item slot (bypasses AP delivery)
--        Z -> zero every key-item slot
--        D -> dump current byte values to the Lua console

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
    error("[dw1-keyitem-probe] no usable RAM domain in: "
          .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()

local BANK_BASE = 0x001BDF2C
local COUNTER_BASE = 0x001BDF20  -- magic + 2-byte items_received counter

local key_items = {
    { slot = 115, name = "Blue Flute" },
    { slot = 116, name = "Old Fishrod" },
    { slot = 117, name = "Amazing Rod" },
    { slot = 118, name = "Leomonstone" },
    { slot = 119, name = "Mansion Key" },
    { slot = 120, name = "Gear" },
    { slot = 121, name = "Rain Plant" },
    { slot = 122, name = "Steak" },
    { slot = 123, name = "Frig Key" },
}

local function read8(addr)
    return memory.read_u8(addr + ADDR_PREFIX, DOMAIN)
end

local function write8(addr, val)
    memory.write_u8(addr + ADDR_PREFIX, val, DOMAIN)
end

local function poke_all(val)
    for _, ki in ipairs(key_items) do
        write8(BANK_BASE + ki.slot, val)
    end
    console.log(string.format("[probe] poked %d into key-item slots", val))
end

local function dump()
    console.log("--- DW1 key-item bank probe ---")
    local magic = read8(COUNTER_BASE)
    local cl = read8(COUNTER_BASE + 1)
    local ch = read8(COUNTER_BASE + 2)
    console.log(string.format(
        "  counter: magic=0x%02X (expect 0xA5), counter=%d",
        magic, cl + ch * 256))
    for _, ki in ipairs(key_items) do
        local addr = BANK_BASE + ki.slot
        local v = read8(addr)
        console.log(string.format(
            "  slot %3d (%-12s) @ 0x%06X = %d",
            ki.slot, ki.name, addr, v))
    end
end

local last_keys = {}
local function edge(key)
    local now = (input.get()[key] == true)
    local was = last_keys[key] or false
    last_keys[key] = now
    return now and not was
end

console.log("DW1 Key-Item Bank Probe loaded.")
console.log("  HUD shows live byte values for key-item bank slots.")
console.log("  [P] poke 1 into every key-item slot")
console.log("  [Z] zero every key-item slot")
console.log("  [D] dump current values to console")

while true do
    if edge("P") then poke_all(1) end
    if edge("Z") then poke_all(0) end
    if edge("D") then dump() end

    -- HUD: live byte values
    local y = 2
    local magic = read8(COUNTER_BASE)
    local cl = read8(COUNTER_BASE + 1)
    local ch = read8(COUNTER_BASE + 2)
    local magic_color = (magic == 0xA5) and "lime" or "yellow"
    gui.text(2, y, string.format(
        "counter magic=0x%02X count=%d", magic, cl + ch * 256),
        magic_color, "black")
    y = y + 14
    for _, ki in ipairs(key_items) do
        local v = read8(BANK_BASE + ki.slot)
        local color = (v == 0) and "red" or "lime"
        gui.text(2, y, string.format(
            "slot %3d %-12s = %d", ki.slot, ki.name, v),
            color, "black")
        y = y + 12
    end

    emu.frameadvance()
end
