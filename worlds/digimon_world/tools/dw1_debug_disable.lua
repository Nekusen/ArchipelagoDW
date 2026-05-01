-- DW1 debug menu disabler (NTSC-U / SLUS-01032). BizHawk; Nymashock OR Octoshock.
--
-- Sets triggers 54 and 55 in MainRAM so the next entry into Jijimon's House
-- loads the normal house (Script 193) instead of the debug map (Script 164).
-- One-shot: load via Tools -> Lua Console -> Open Script.

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
    error("[DW1 debug] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
local addr = 0x001BDFD3 + ADDR_PREFIX
local before = memory.read_u8(addr, DOMAIN)
local after = bit.bor(before, 0xC0)  -- set bits 6 and 7 (triggers 54 and 55)

memory.write_u8(addr, after, DOMAIN)

console.log(string.format(
    "[DW1 debug] DISABLED. byte 0x%08X (domain=%s): 0x%02X -> 0x%02X.",
    addr, DOMAIN, before, after))
