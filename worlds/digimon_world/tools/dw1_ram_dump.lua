-- DW1 RAM Dump (BizHawk; Nymashock OR Octoshock)
--
-- Dump a wide range of RAM to a binary file so we can scan it offline
-- for byte signatures (e.g. the merit-shop function we statically
-- located). The target signature for that function is the unique
-- 28-byte run starting with ``lh $v0, -0x6b68($gp)`` and ending with
-- ``jal 0x000C5240`` (LE: 98 94 82 87 03 1C 03 00 22 10 43 00 4C 94
-- 84 93 98 94 82 A7 58 94 85 AF 90 14 03 0C).
--
-- The PC locator's onmemorywrite callback returned scattered PCs that
-- post-date the actual store; this dump bypasses the callback timing
-- problem entirely by just snapshotting the memory.
--
-- Hotkeys (focus the emulator window):
--   M  -> set MERIT to 9999.
--   B  -> dump main RAM 0x80000000..0x80200000 to dw1_ram_dump.bin
--         (2 MiB; takes a few seconds in Lua but only needs to run once
--         per session).
--
-- Procedure:
--   1. At Volume Villa, in front of Gekomon (so the merit-shop overlay
--      is loaded). Optionally open the Use-Merit-points menu first to
--      ensure the relevant code is in RAM.
--   2. Press B. The console will print progress and then "wrote
--      dw1_ram_dump.bin (NN bytes)" when done.
--   3. Send me the resulting `dw1_ram_dump.bin` file.

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
    error("[dw1-dump] no usable RAM domain in: " .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX = pick_ram_domain()
print(string.format("[dw1-dump] domain=%s prefix=0x%08X", DOMAIN, ADDR_PREFIX))

local MERIT_ADDR_DOM = 0x80134FC4 - (0x80000000 - ADDR_PREFIX)

-- Range to dump: full 2 MiB of PSX MainRAM (kuseg 0x80000000..0x80200000).
-- The merit-shop function we want lives somewhere in 0x80010000..0x80200000.
-- We cover 0x80000000..0x80200000 just to be safe.
local DUMP_START_RAM = 0x80000000
local DUMP_END_RAM   = 0x80200000

local DUMP_START_DOM = DUMP_START_RAM - (0x80000000 - ADDR_PREFIX)
local DUMP_LEN       = DUMP_END_RAM - DUMP_START_RAM

local function dump_ram()
    local path = "dw1_ram_dump.bin"
    local f, err = io.open(path, "wb")
    if not f then
        print(string.format("[dw1-dump] cannot open %s: %s", path, tostring(err)))
        return
    end
    print(string.format("[dw1-dump] dumping 0x%08X..0x%08X (%d bytes)...",
                        DUMP_START_RAM, DUMP_END_RAM, DUMP_LEN))
    -- Read in 4 KiB chunks, batching memory.read_bytes_as_array calls
    -- where possible. (BizHawk's API varies; fall back to per-byte.)
    local CHUNK = 0x1000
    local written = 0
    local ok_batch = pcall(function()
        for chunk_start = 0, DUMP_LEN - 1, CHUNK do
            local addr = DUMP_START_DOM + chunk_start
            local n = math.min(CHUNK, DUMP_LEN - chunk_start)
            local arr = memory.read_bytes_as_array(addr, n, DOMAIN)
            local buf = {}
            for i = 1, n do buf[i] = string.char(arr[i]) end
            f:write(table.concat(buf))
            written = written + n
        end
    end)
    if not ok_batch then
        -- Per-byte fallback
        f:close()
        f = io.open(path, "wb")
        written = 0
        for off = 0, DUMP_LEN - 1, CHUNK do
            local n = math.min(CHUNK, DUMP_LEN - off)
            local addr = DUMP_START_DOM + off
            local buf = {}
            for k = 0, n - 1 do
                buf[k + 1] = string.char(memory.read_u8(addr + k, DOMAIN))
            end
            f:write(table.concat(buf))
            written = written + n
            if (off % 0x10000) == 0 then
                print(string.format("[dw1-dump] %d / %d bytes...", off, DUMP_LEN))
            end
        end
    end
    f:close()
    print(string.format("[dw1-dump] B -> wrote %s (%d bytes)", path, written))
end

local function set_merit_max()
    memory.write_u16_le(MERIT_ADDR_DOM, 9999, DOMAIN)
    print("[dw1-dump] M -> MERIT pinned to 9999")
end

local prev = {M = false, B = false}
local function check_keys()
    local k = input.get()
    local p = {M = k["M"] or false, B = k["B"] or false}
    if p.M and not prev.M then set_merit_max() end
    if p.B and not prev.B then dump_ram() end
    prev = p
end

print("[dw1-dump] ready. M=set merit  B=dump RAM to dw1_ram_dump.bin")

while true do
    check_keys()
    emu.frameadvance()
end
