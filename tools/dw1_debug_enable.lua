-- DW1 debug menu enabler (NTSC-U / SLUS-01032).
-- Clears triggers 54 and 55 in MainRAM so the next entry into Jijimon's House
-- loads the hidden debug map (Script 164) instead of the normal house (Script 193).
-- One-shot: load via Tools -> Lua Console -> Open Script in BizHawk.
-- Re-run after using a debug option that re-sets these triggers.

memory.usememorydomain("MainRAM")

local addr = 0x001BDFD3
local before = memory.read_u8(addr)
local after = bit.band(before, 0x3F)  -- clear bits 6 and 7 (triggers 54 and 55)

memory.write_u8(addr, after)

console.log(string.format(
    "[DW1 debug] ENABLED. byte 0x%08X: 0x%02X -> 0x%02X. Walk into Jijimon's House.",
    addr, before, after))
