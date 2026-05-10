-- DW1 BizHawk domain brute-forcer
--
-- The user's getmemorydomainlist() returns only:
--   GPURAM, SPURAM, BiosROM, DCache, Memcard 1, System Bus, Waterbox PageData
-- But the existing client successfully uses domain "MainRAM" with bare
-- offsets like 0x00134EB8 for player money. So either MainRAM exists
-- but is hidden from getmemorydomainlist(), or the client has been
-- failing silently.
--
-- This probe tries reading the player money slot (bare 0x00134EB8)
-- through every plausible domain name regardless of whether the list
-- contains it. pcall protects against nil-domain errors.

console.log("=== DW1 BizHawk domain brute-forcer ===")

local domain_names = {
    -- BizHawk's discovered list
    "GPURAM", "SPURAM", "BiosROM", "DCache", "Memcard 1",
    "System Bus", "Waterbox PageData",
    -- Plausible main RAM names across BizHawk versions / cores
    "MainRAM", "Main RAM", "Main Memory", "Memory",
    "WRAM", "RAM", "EWRAM", "IWRAM",
    "Nymashock", "Octoshock", "PSX MainRAM", "PSX RAM",
    -- Mednafen-style names
    "MainROM", "WorkRAM",
}

-- Try multiple address layouts for the money slot
local addr_attempts = {
    { name = "bare  0x00134EB8", addr = 0x00134EB8 },
    { name = "kuseg 0x80134EB8", addr = 0x80134EB8 },
    { name = "kseg1 0xA0134EB8", addr = 0xA0134EB8 },
}

console.log("Trying every <domain, address-layout> combination for the")
console.log("player money slot. Non-zero, non-error reads are reported.")
console.log("")

for _, dn in ipairs(domain_names) do
    for _, attempt in ipairs(addr_attempts) do
        local ok, val = pcall(memory.read_u32_le, attempt.addr, dn)
        if ok then
            -- ok means the domain accepted the address
            console.log(string.format(
                "  [%-25s] %s = 0x%08X (%d)",
                dn, attempt.name, val, val))
        end
    end
end

console.log("")
console.log("=== second pass: scan a few well-known DW1 RAM addresses ===")

local test_addrs = {
    { name = "trigger array (bare 0x001BDFCD)",  addr = 0x001BDFCD },
    { name = "trigger array (kuseg 0x801BDFCD)", addr = 0x801BDFCD },
    { name = "item bank (bare 0x001BDF2C)",      addr = 0x001BDF2C },
    { name = "item bank (kuseg 0x801BDF2C)",     addr = 0x801BDF2C },
    { name = "current money (bare 0x00134EB8)",  addr = 0x00134EB8 },
    { name = "current money (kuseg 0x80134EB8)", addr = 0x80134EB8 },
}

for _, dn in ipairs(domain_names) do
    local found_any = false
    local lines = {}
    for _, t in ipairs(test_addrs) do
        local ok, val = pcall(memory.read_u32_le, t.addr, dn)
        if ok then
            found_any = true
            lines[#lines + 1] = string.format(
                "    %-40s = 0x%08X", t.name, val)
        end
    end
    if found_any then
        console.log(string.format("  [%s]:", dn))
        for _, line in ipairs(lines) do
            console.log(line)
        end
    end
end

console.log("")
console.log("=== done ===")
console.log("Look for a domain where multiple known addresses return")
console.log("non-zero, sensible-looking values. That's the actual main RAM.")
