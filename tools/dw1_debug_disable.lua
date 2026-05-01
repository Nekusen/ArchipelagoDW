-- DW1 debug menu disabler (NTSC-U / SLUS-01032).
-- Sets triggers 54 and 55 in MainRAM so the next entry into Jijimon's House
-- loads the normal house (Script 193) instead of the debug map (Script 164).
-- One-shot: load via Tools -> Lua Console -> Open Script in BizHawk.

memory.usememorydomain("MainRAM")

local addr = 0x001BDFD3
local before = memory.read_u8(addr)
local after = bit.bor(before, 0xC0)  -- set bits 6 and 7 (triggers 54 and 55)

memory.write_u8(addr, after)

console.log(string.format(
    "[DW1 debug] DISABLED. byte 0x%08X: 0x%02X -> 0x%02X.",
    addr, before, after))
