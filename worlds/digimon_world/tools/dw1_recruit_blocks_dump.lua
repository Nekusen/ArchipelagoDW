-- DW1 recruit-related block dumper (3-way side-by-side).
--
-- Dumps the THREE blocks that any "is Digimon X recruited?" gate could
-- possibly read from, so we can see which one(s) have which bits set
-- and reverse-engineer how Greymon's recruit-block bit got set while
-- MetalGreymon's didn't.
--
-- Blocks:
--   * RECRUIT_BLOCK   at 0x001BDFE6 (8 bytes)  — vanilla trigger(200+X)
--   * AP_BITS_MIRROR  at 0x001BDFF0 (8 bytes)  — isTriggerSet wrapper source
--   * BEATEN_BLOCK    at 0x001BE027 (8 bytes)  — AP delivery target (720+X)
--
-- For each digimon, prints which of the three blocks has its bit set.
-- Run after AP-delivering several Progressive Arena copies to see the
-- pattern.

local DOMAIN = "MainRAM"

local function read_byte(addr)
    local v = memory.read_u8(addr, DOMAIN)
    if v == nil then error("read_u8 returned nil at 0x"..string.format("%08X", addr)) end
    return v
end

local function bit_set(b, i)
    return bit.band(b, bit.lshift(1, i)) ~= 0
end

-- Per-Digimon byte/bit (RECRUIT_RAM_BITS from addresses.py).
-- byte is RECRUIT_BLOCK-relative offset (subtract 0x001BDFE6 to get
-- 0-based index into the 8-byte block). Same byte/bit indexing applies
-- to AP_BITS_MIRROR and BEATEN_BLOCK -- per the wrapper's arithmetic,
-- all three blocks pack `digimon_id X` as `byte (X/8), bit (X%8)`.
local RECRUIT = {
    {name="Agumon",       addr=0x001BDFE6, bit=0},
    {name="Greymon",      addr=0x001BDFE6, bit=5},
    {name="Devimon",      addr=0x001BDFE6, bit=6},
    {name="Airdramon",    addr=0x001BDFE6, bit=7},
    {name="Tyrannomon",   addr=0x001BDFE7, bit=0},
    {name="Meramon",      addr=0x001BDFE7, bit=1},
    {name="Seadramon",    addr=0x001BDFE7, bit=2},
    {name="Numemon",      addr=0x001BDFE7, bit=3},
    {name="MetalGreymon", addr=0x001BDFE7, bit=4},
    {name="Mamemon",      addr=0x001BDFE7, bit=5},
    {name="Monzaemon",    addr=0x001BDFE7, bit=6},
    {name="Gabumon",      addr=0x001BDFE7, bit=7},
    {name="Elecmon",      addr=0x001BDFE8, bit=0},
    {name="Kabuterimon",  addr=0x001BDFE8, bit=1},
    {name="Angemon",      addr=0x001BDFE8, bit=2},
    {name="Birdramon",    addr=0x001BDFE8, bit=3},
    {name="Garurumon",    addr=0x001BDFE8, bit=4},
    {name="Frigimon",     addr=0x001BDFE8, bit=7},
    {name="Vegimon",      addr=0x001BDFE9, bit=1},
    {name="SkullGreymon", addr=0x001BDFE9, bit=7},
    {name="Vademon",      addr=0x001BDFEA, bit=0},
    {name="Whamon",       addr=0x001BDFE8, bit=5},
    {name="MetalMamemon", addr=0x001BDFEA, bit=2},
    {name="Megadramon",   addr=0x001BDFEC, bit=6},
    {name="Penguinmon",   addr=0x001BDFED, bit=1},
}

local RECRUIT_BLOCK_BASE  = 0x001BDFE6
local AP_MIRROR_BASE      = 0x001BDFF0
local BEATEN_BLOCK_BASE   = 0x001BE027

-- Dump raw block bytes (one print per block).
local function dump_block(label, base, size)
    local parts = {string.format("  %-16s @ 0x%08X:", label, base)}
    for i = 0, size - 1 do
        local b = read_byte(base + i)
        table.insert(parts, string.format("%02X", b))
    end
    table.insert(parts, " | ")
    for i = 0, size - 1 do
        local b = read_byte(base + i)
        local bin = ""
        for bi = 7, 0, -1 do
            bin = bin .. (bit_set(b, bi) and "1" or "0")
        end
        table.insert(parts, bin)
    end
    print(table.concat(parts, " "))
end

print("=========================================================")
print("DW1 recruit-block 3-way dump")
print("=========================================================")
print("")
print("Raw bytes (hex || binary MSB-first):")
dump_block("RECRUIT_BLOCK",  RECRUIT_BLOCK_BASE, 8)
dump_block("AP_BITS_MIRROR", AP_MIRROR_BASE,     8)
dump_block("BEATEN_BLOCK",   BEATEN_BLOCK_BASE,  8)
print("")

print(string.format("Per-Digimon (%-16s  R  M  B):", "name"))
print("  R = RECRUIT_BLOCK bit set (= what vanilla bytecode reads)")
print("  M = AP_BITS_MIRROR bit set (= what isTriggerSet wrapper reads)")
print("  B = BEATEN_BLOCK bit set (= AP delivery writes here)")
print("")
for _, e in ipairs(RECRUIT) do
    local block_off = e.addr - RECRUIT_BLOCK_BASE
    local r = bit_set(read_byte(RECRUIT_BLOCK_BASE + block_off), e.bit)
    local m = bit_set(read_byte(AP_MIRROR_BASE     + block_off), e.bit)
    local b = bit_set(read_byte(BEATEN_BLOCK_BASE  + block_off), e.bit)
    if r or m or b then
        print(string.format("  %-16s  %s  %s  %s", e.name,
            r and "1" or "0", m and "1" or "0", b and "1" or "0"))
    end
end
print("")
print("(One-shot dump complete -- stop the script.)")
