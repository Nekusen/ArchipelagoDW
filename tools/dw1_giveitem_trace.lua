-- DW1 key-item / inventory write tracer (NTSC-U / SLUS-01032).
--
-- Nymashock's Lua execute callbacks don't fire reliably; write callbacks
-- do. This script registers a write hook on each address in WATCH_LIST
-- below and logs CPU state at every fire. Default targets cover the
-- key-item flag block at 0x001BDF20..0x001BDF2B (per the cheat-engine
-- table — old fishrod = 0x001BDF23, Amazing Rod = 0x001BDF24, Mansion
-- Key = 0x001BDF26, …). To trace inventory items instead, swap WATCH_LIST
-- for the on-hand range 0x0013D474..0x0013D47D.
--
-- Use case: the old fishrod is granted by a script (Section_51 of the
-- Dust Kingdom script, see meekrhino's DW1Script.txt around offset
-- 006820 — `setTrigger 320`). The rod flag itself lives at 0x001BDF23
-- as a byte. Hooking a write on 0x001BDF23 tells us whether the script-
-- VM's setTrigger handler mirrors trigger 320 → 0x001BDF23 (then PC
-- lands inside setTrigger), or whether a separate native path handles
-- it (then PC lands somewhere else entirely).
--
-- Usage:
--   1. Boot BizHawk + Nymashock, load your "right before pickup"
--      savestate.
--   2. Delete the existing log file if present (the script appends).
--   3. Tools -> Lua Console -> Open Script -> select this file.
--   4. Console should print "[dw1_w] hooks installed (N watches ...)".
--   5. Advance through the in-game give event.
--   6. Each write to any watched address prints a one-liner to the
--      console and appends a record to LOG_PATH.
--
-- Reading the log: the rod-grant write is the one labeled `[old fishrod]`
-- whose old=00 -> new=01. `pc` is the SW/SB instruction that performed
-- the byte write; `ra` is the caller's return address.
--
-- Caveats:
--   * onmemorywrite typically fires AFTER the write. The byte read from
--     RAM inside the callback is the post-write value; pre-write comes
--     from the shadow map.
--   * If even write hooks are silent under Nymashock, fall back to PC
--     polling around the pickup frame.

local LOG_PATH = [[c:\opt\dev\AP\ArchipelagoDW\tools\dw1_giveitem_trace.log]]

-- Auto-detect the right RAM domain. PSX cores expose this differently:
--   * Nymashock: "MainRAM" — 2 MiB at offset 0, use bare RAM offsets.
--   * Octoshock: no Main RAM domain at all — use "System Bus" with the
--     0x80000000 kuseg mirror prefix (Octoshock domains observed:
--     GPURAM, SPURAM, BiosROM, PIOMem, DCache, System Bus).
local function pick_ram_domain()
    local list = memory.getmemorydomainlist()
    console.log("[dw1_w] available memory domains:")
    for _, d in ipairs(list) do
        console.log("  " .. tostring(d))
    end
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
    error("[dw1_w] no usable RAM domain in: " .. table.concat(list, ", "))
end

local HOOK_DOMAIN, ADDR_PREFIX = pick_ram_domain()
memory.usememorydomain(HOOK_DOMAIN)
console.log(string.format(
    "[dw1_w] using domain=%s  prefix=0x%08X",
    HOOK_DOMAIN, ADDR_PREFIX))

-- Per-byte watch list. Each entry is {ram_offset, label}. Edit freely.
--
-- The rod-give script does `setTrigger 45` (section gate) and
-- `setTrigger 320` (rod flag). Per references/DW1-Code/getTriggerOffsets.asm
-- the formula is: addr = [0x00134FB8] + 0xF5 + (id / 8) — and our
-- existing TRIGGER_BASE 0x001BDFCD implies [0x00134FB8] resolves to
-- 0x001BDED8 at runtime. So:
--   * trigger  45 -> byte 0x001BDFD2 bit 5  (mask 0x20)
--   * trigger 320 -> byte 0x001BDFF5 bit 0  (mask 0x01)
-- Also keeping the CE-table "key item" bytes for cross-check — if any
-- of those flip *too*, the UI sync path is also detectable here.
local WATCH_LIST = {
    -- Trigger array — primary hypothesis
    {0x001BDFD2, "trig 45 byte (section gate)"},
    {0x001BDFF5, "trig 320 byte (ROD FLAG)"},
    -- CE-table "key item" bytes — secondary cross-check
    {0x001BDF22, "CE: Blue Flute"},
    {0x001BDF23, "CE: old fishrod"},
    {0x001BDF24, "CE: Amazing Rod"},
    {0x001BDF25, "CE: Leomonstone"},
    {0x001BDF26, "CE: Mansion Key"},
}

-- Shadow map tracks pre-write values so log can show old -> new.
local shadow = {}
for _, e in ipairs(WATCH_LIST) do
    shadow[e[1]] = memory.read_u8(e[1] + ADDR_PREFIX)
end

local hit_count       = 0
local first_full_dump = true

local function safe_get(regs, ...)
    for _, name in ipairs({...}) do
        local v = regs[name]
        if v ~= nil then return v end
    end
    return 0
end

local function on_write(ram_offset, label)
    hit_count = hit_count + 1
    local frame  = emu.framecount()
    local new_v  = memory.read_u8(ram_offset + ADDR_PREFIX)
    local old_v  = shadow[ram_offset] or 0
    shadow[ram_offset] = new_v

    local regs = emu.getregisters()
    local pc   = safe_get(regs, "pc", "PC")
    local ra   = safe_get(regs, "ra", "RA", "r31", "R31")
    local a0   = safe_get(regs, "a0", "A0", "r4",  "R4")
    local a1   = safe_get(regs, "a1", "A1", "r5",  "R5")

    local f = io.open(LOG_PATH, "a")
    if f then
        f:write(string.format(
            "=== hit %d  frame %d  [%s] ===\n", hit_count, frame, label))
        f:write(string.format(
            "  addr=%08X  old=%02X -> new=%02X\n",
            ram_offset, old_v, new_v))
        f:write(string.format(
            "  pc=%08X  ra=%08X  a0=%08X  a1=%08X\n",
            pc, ra, a0, a1))
        if first_full_dump then
            first_full_dump = false
            f:write("  full register dump (first hit only):\n")
            local keys = {}
            for k in pairs(regs) do keys[#keys + 1] = tostring(k) end
            table.sort(keys)
            for _, k in ipairs(keys) do
                f:write(string.format(
                    "    %-12s = 0x%08X\n", k, regs[k]))
            end
        end
        f:write("\n")
        f:close()
    else
        console.log("[dw1_w] ERROR: could not open " .. LOG_PATH)
    end

    console.log(string.format(
        "[dw1_w] hit %d  frame=%d  [%s] %02X->%02X  pc=%08X  ra=%08X",
        hit_count, frame, label, old_v, new_v, pc, ra))
end

for _, e in ipairs(WATCH_LIST) do
    local ram_offset, label = e[1], e[2]
    local hook_addr         = ram_offset + ADDR_PREFIX
    event.onmemorywrite(
        function() on_write(ram_offset, label) end,
        hook_addr,
        "dw1_w_" .. string.format("%08X", hook_addr),
        HOOK_DOMAIN)
end

-- Polling fallback. Even if write hooks stay silent under Nymashock,
-- this loop will at least confirm whether the watched byte ever
-- changed and at what frame — which tells us the address is right and
-- isolates the failure to the hook mechanism.
local function poll_changes()
    for _, e in ipairs(WATCH_LIST) do
        local addr   = e[1]
        local label  = e[2]
        local cur    = memory.read_u8(addr + ADDR_PREFIX)
        local prev   = shadow[addr]
        if cur ~= prev then
            shadow[addr] = cur
            local frame = emu.framecount()
            console.log(string.format(
                "[dw1_poll] frame=%d  [%s] %02X->%02X  (write hook %s)",
                frame, label, prev, cur,
                "did NOT fire — domain or hook broken"))
            local f = io.open(LOG_PATH, "a")
            if f then
                f:write(string.format(
                    "=== POLL frame %d  [%s]  %02X->%02X ===\n\n",
                    frame, label, prev, cur))
                f:close()
            end
        end
    end
end
event.onframeend(poll_changes)

console.log(string.format(
    "[dw1_w] hooks installed (%d watches, domain=%s) + polling fallback",
    #WATCH_LIST, HOOK_DOMAIN))
console.log("[dw1_w] log: " .. LOG_PATH)

-- BizHawk Lua scripts whose main body returns are treated as finished
-- and their event callbacks get deregistered. Park here forever so the
-- write hooks above stay live until the user closes the script.
while true do
    emu.frameadvance()
end
