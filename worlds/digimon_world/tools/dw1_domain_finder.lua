-- DW1 BizHawk domain finder v2
--
-- Tries to find ANY of several candidate "anchor" values across every
-- BizHawk memory domain. Anchors include several plausible money cap
-- values plus known trigger-array bytes (0x001BDFCD..) which our
-- existing client uses successfully.
--
-- Run this with the game running (any screen). Paste full output.

console.log("=== DW1 BizHawk domain finder v2 ===")

local domains = memory.getmemorydomainlist()
console.log(string.format("found %d domain(s):", #domains))
for _, d in ipairs(domains) do
    local size = memory.getmemorydomainsize(d)
    console.log(string.format(
        "  %-25s size=%d (0x%X)", tostring(d), size, size))
end

-- Anchor values to scan for. Each is a u32 little-endian byte signature.
local function u32_to_bytes(v)
    return {
        v % 0x100,
        math.floor(v / 0x100) % 0x100,
        math.floor(v / 0x10000) % 0x100,
        math.floor(v / 0x1000000) % 0x100,
    }
end

-- Money cap candidates (try them all)
local ANCHORS = {
    { val = 99999,    label = "money 99999 (5 nines)" },
    { val = 999999,   label = "money 999999 (6 nines)" },
    { val = 9999999,  label = "money 9999999 (7 nines)" },
    { val = 65535,    label = "money 65535 (u16 cap)" },
    -- Some other common DW1 anchors
    { val = 0x000000A5, label = "AP scratch magic 0xA5" },
}

local function bytes_match(domain, off, sig)
    local ok1, b0 = pcall(memory.read_u8, off, domain)
    if not ok1 or b0 ~= sig[1] then return false end
    local ok2, b1 = pcall(memory.read_u8, off + 1, domain)
    if not ok2 or b1 ~= sig[2] then return false end
    local ok3, b2 = pcall(memory.read_u8, off + 2, domain)
    if not ok3 or b2 ~= sig[3] then return false end
    local ok4, b3 = pcall(memory.read_u8, off + 3, domain)
    if not ok4 or b3 ~= sig[4] then return false end
    return true
end

console.log("\n=== Scan each domain for each anchor value ===")
for _, anchor in ipairs(ANCHORS) do
    local sig = u32_to_bytes(anchor.val)
    console.log(string.format(
        "\n[anchor: %s] bytes %02X %02X %02X %02X",
        anchor.label, sig[1], sig[2], sig[3], sig[4]))
    for _, d in ipairs(domains) do
        local size = memory.getmemorydomainsize(d)
        if size > 4 then
            local hits = {}
            for off = 0, size - 4, 1 do
                if bytes_match(d, off, sig) then
                    hits[#hits + 1] = off
                    if #hits >= 8 then break end
                end
            end
            if #hits > 0 then
                console.log(string.format(
                    "  [%-25s] %d hit(s):", d, #hits))
                for _, off in ipairs(hits) do
                    console.log(string.format("    -> 0x%08X", off))
                end
            end
        end
    end
end

-- Try reading a fixed RAM address that should always have stable data
-- in vanilla DW1 — the SLUS executable's loaded image starts at
-- 0x80010000 typically. The PSX BIOS magic at 0x80000000..F should
-- read as `0x90 0x9F 0x10 0x60` or similar (the BIOS jump vectors).
console.log("\n=== Direct reads at well-known PSX addresses ===")
local probes = {
    { name = "kuseg 0x80000000 (BIOS reset vector area)", addr = 0x80000000 },
    { name = "kuseg 0x80010000 (typical exe start)",       addr = 0x80010000 },
    { name = "kuseg 0x80100000 (mid main RAM)",            addr = 0x80100000 },
    { name = "kuseg 0x801BDFCD (DW1 trigger array)",       addr = 0x801BDFCD },
    { name = "bare  0x00000000",                           addr = 0x00000000 },
    { name = "bare  0x00010000",                           addr = 0x00010000 },
    { name = "bare  0x00100000",                           addr = 0x00100000 },
    { name = "bare  0x001BDFCD",                           addr = 0x001BDFCD },
}
for _, d in ipairs(domains) do
    local size = memory.getmemorydomainsize(d)
    if size > 0 then
        for _, p in ipairs(probes) do
            if p.addr + 4 <= size then
                local ok, val = pcall(memory.read_u32_le, p.addr, d)
                if ok and val ~= 0 then
                    console.log(string.format(
                        "  [%-25s] %s = 0x%08X",
                        d, p.name, val))
                end
            end
        end
    end
end

console.log("\n=== done ===")
console.log("Look for: which domain found ANY of the anchors,")
console.log("and which domain returned non-zero for the kuseg/bare probes.")
