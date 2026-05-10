-- DW1 Recycle Shop runtime probe v3 (BizHawk; Nymashock or Octoshock)
--
-- v3 fixes vs v2:
--   * BUG FIX: scan loops were stepping by 2, missing odd-aligned arrays.
--     Now step by 1 byte everywhere.
--   * Sanity checks: read player money from gp-0x6C74 and scan RAM
--     for the player's money value (anchor), so we confirm gp + RAM
--     addressing are correct.
--   * Wide gp-slot dump: every 4 bytes from gp-0x7000 to gp-0x6000.
--     Flags any slot whose value looks like a main-RAM pointer.
--   * Scan for "id + price" pairs in RAM (e.g. 01 ?? F4 01 for med.recovery
--     at price 500 -- 7 of those would tell us the array exists in some
--     [id, ?, price_u16_LE] form).
--   * Memory domain + gp value reported on load.
--
-- Usage (same as v2):
--   1. Walk to GIAS06B, Tinmon visible.
--   2. Load this script in BizHawk Lua Console.
--   3. Talk to Tinmon -> "I want a recycled item". Shop list opens.
--   4. Press F. Console fills with diagnostics.
--   5. Paste console output back.

-- BizHawk Nymashock hides MainRAM from getmemorydomainlist() but it
-- IS accessible directly. RAM Watch's dropdown lists it; the Lua list
-- API lies. Pass "MainRAM" with bare offsets unconditionally; if the
-- read errors we fall back to System Bus + kuseg.
local function pick_ram_domain()
    local list = memory.getmemorydomainlist()
    -- Probe MainRAM first by attempting a small read
    local ok = pcall(memory.read_u8, 0, "MainRAM")
    if ok then
        return "MainRAM", 0x00000000, list
    end
    for _, d in ipairs(list) do
        local lower = string.lower(tostring(d))
        if lower == "mainram" or lower == "main ram" then
            return d, 0x00000000, list
        end
    end
    for _, d in ipairs(list) do
        if tostring(d) == "System Bus" then
            return d, 0x80000000, list
        end
    end
    error("[recycle-probe] no usable RAM domain in: "
          .. table.concat(list, ", "))
end

local DOMAIN, ADDR_PREFIX, ALL_DOMAINS = pick_ram_domain()
local RAM_SIZE = 0x00200000

local TRIGGER_BASE = 0x001BDFCD
local KNOWN_IDS = { 0x01, 0x05, 0x0F, 0x10, 0x11, 0x16 }
local KNOWN_NAMES = {
    [0x01] = "med.recovery",
    [0x05] = "Medium MP",
    [0x0F] = "Off. Disk",
    [0x10] = "Def. Disk",
    [0x11] = "Hispeed dsk",
    [0x16] = "Auto Pilot",
}

-- Vanilla prices (from ITEM_PARA dump): id -> i16 price
local KNOWN_PRICES = {
    [0x01] = 500,    -- med.recovery (0x01F4 LE = F4 01)
    [0x05] = 800,    -- Medium MP    (0x0320 LE = 20 03)
    [0x0F] = 500,
    [0x10] = 500,
    [0x11] = 500,
    [0x16] = 300,    -- Auto Pilot   (0x012C LE = 2C 01)
}

local RECYCLE_TRIGGERS = { 385, 389, 406, 423, 399, 400, 401 }

local GP = 0x8013BB2C
local GP_MONEY_DISP = 0x6C74    -- player money (i32 LE)

local function gp_off(disp)
    return (GP - disp) - 0x80000000
end

local GP_SLOTS = {
    { name = "gp-0x6BC0", off = gp_off(0x6BC0) },
    { name = "gp-0x6BC4", off = gp_off(0x6BC4) },
    { name = "gp-0x6BB4", off = gp_off(0x6BB4) },
    { name = "gp-0x6B74", off = gp_off(0x6B74) },
    { name = "gp-0x6B70", off = gp_off(0x6B70) },
    { name = "gp-0x6BC8", off = gp_off(0x6BC8) },
    { name = "gp-0x6BCC", off = gp_off(0x6BCC) },
    { name = "gp-money(0x6C74)", off = gp_off(GP_MONEY_DISP) },
}

local function r8(addr)
    return memory.read_u8(addr + ADDR_PREFIX, DOMAIN)
end

local function r16le(addr)
    return memory.read_u16_le(addr + ADDR_PREFIX, DOMAIN)
end

local function r32le(addr)
    return memory.read_u32_le(addr + ADDR_PREFIX, DOMAIN)
end

local function trig_byte(n)
    return TRIGGER_BASE + math.floor(n / 8)
end

local function trig_mask(n)
    local bit = n % 8
    local masks = { 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80 }
    return masks[bit + 1]
end

local function is_trig_set(n)
    local b = r8(trig_byte(n))
    local m = trig_mask(n)
    return (b % (m * 2)) >= m
end

local function dump_bytes(addr, n)
    local parts = {}
    for i = 0, n - 1 do
        parts[#parts + 1] = string.format("%02X", r8(addr + i))
    end
    return table.concat(parts, " ")
end

-- Scan: find a u32 value anywhere in RAM (sanity-anchor for money).
local function scan_u32(target_value)
    local b0 = target_value % 0x100
    local b1 = math.floor(target_value / 0x100) % 0x100
    local b2 = math.floor(target_value / 0x10000) % 0x100
    local b3 = math.floor(target_value / 0x1000000) % 0x100
    local hits = {}
    for off = 0, RAM_SIZE - 4, 1 do
        if r8(off) == b0 and r8(off + 1) == b1
           and r8(off + 2) == b2 and r8(off + 3) == b3 then
            hits[#hits + 1] = off
            if #hits >= 16 then break end
        end
    end
    return hits
end

-- Strict 6/6 stride-2, EVERY byte offset
local function scan_stride2()
    local hits = {}
    for off = 0, RAM_SIZE - 14, 1 do
        if r8(off) == KNOWN_IDS[1]
        and r8(off + 2) == KNOWN_IDS[2]
        and r8(off + 4) == KNOWN_IDS[3]
        and r8(off + 6) == KNOWN_IDS[4]
        and r8(off + 8) == KNOWN_IDS[5]
        and r8(off + 10) == KNOWN_IDS[6] then
            hits[#hits + 1] = off
            if #hits >= 16 then break end
        end
    end
    return hits
end

-- Strict 6/6 stride-1
local function scan_stride1()
    local hits = {}
    for off = 0, RAM_SIZE - 7, 1 do
        if r8(off) == KNOWN_IDS[1]
        and r8(off + 1) == KNOWN_IDS[2]
        and r8(off + 2) == KNOWN_IDS[3]
        and r8(off + 3) == KNOWN_IDS[4]
        and r8(off + 4) == KNOWN_IDS[5]
        and r8(off + 5) == KNOWN_IDS[6] then
            hits[#hits + 1] = off
            if #hits >= 16 then break end
        end
    end
    return hits
end

-- Strict 6/6 stride-4 (id at +0, +4, +8, ...)
local function scan_stride4()
    local hits = {}
    for off = 0, RAM_SIZE - 28, 1 do
        if r8(off) == KNOWN_IDS[1]
        and r8(off + 4) == KNOWN_IDS[2]
        and r8(off + 8) == KNOWN_IDS[3]
        and r8(off + 12) == KNOWN_IDS[4]
        and r8(off + 16) == KNOWN_IDS[5]
        and r8(off + 20) == KNOWN_IDS[6] then
            hits[#hits + 1] = off
            if #hits >= 16 then break end
        end
    end
    return hits
end

-- "id + price" search: for each known id, find its byte preceded
-- by 0 (high byte of u16 id) and followed by its u16-LE price.
-- Pattern: <id_u8> <??_u8> <price_lo> <price_hi>
local function scan_id_plus_price()
    local hits = {}
    for off = 0, RAM_SIZE - 4, 1 do
        local id_byte = r8(off)
        local price = KNOWN_PRICES[id_byte]
        if price ~= nil then
            local plo = price % 0x100
            local phi = math.floor(price / 0x100) % 0x100
            if r8(off + 2) == plo and r8(off + 3) == phi then
                hits[#hits + 1] = { off = off, id = id_byte, price = price }
                if #hits >= 100 then break end
            end
        end
    end
    return hits
end

-- Look for clusters of "id + price" hits within a 56-byte window
-- (= 7 entries x 8 bytes).
local function find_id_price_clusters(hits)
    local clusters = {}
    for i, hit in ipairs(hits) do
        local cluster = { hit }
        for j = i + 1, #hits do
            if hits[j].off - hit.off > 56 then break end
            cluster[#cluster + 1] = hits[j]
        end
        if #cluster >= 4 then
            clusters[#clusters + 1] = cluster
        end
    end
    return clusters
end

local scan_count = 0

local function dump_gp_wide()
    console.log("--- wide gp-relative scan (every 4 bytes from gp-0x7000 to gp-0x6000) ---")
    local printed = 0
    for disp = 0x7000, 0x6000, -4 do
        local off = gp_off(disp)
        local val = r32le(off)
        if val >= 0x80000000 and val < 0x80200000 then
            console.log(string.format(
                "  gp-0x%04X (off 0x%06X) = 0x%08X (RAM ptr)",
                disp, off, val))
            printed = printed + 1
        end
        if printed >= 30 then
            console.log("  (truncated at 30 RAM-pointer hits)")
            break
        end
    end
    if printed == 0 then
        console.log("  (no main-RAM pointers found in gp-relative range)")
    end
end

local function annotate_id(id_byte)
    return KNOWN_NAMES[id_byte] or string.format("id 0x%02X", id_byte)
end

local function run_scans()
    scan_count = scan_count + 1
    console.log(string.format(
        "\n=== probe scan #%d ===", scan_count))
    console.log(string.format("  domain=%s prefix=0x%08X gp=0x%08X",
        DOMAIN, ADDR_PREFIX, GP))

    -- 1. Sanity: player money
    local money = r32le(gp_off(GP_MONEY_DISP))
    console.log(string.format(
        "--- sanity: player money @ gp-0x6C74 (off 0x%06X) = %d (0x%X)",
        gp_off(GP_MONEY_DISP), money, money))
    if money == 99999 or money == 0x1869F then
        console.log("  ** money matches expected 99999 -> gp + addressing OK **")
    elseif money == 0 then
        console.log("  !! money is 0 -- gp value likely wrong !!")
    else
        console.log(string.format(
            "  ?? unexpected money value -- if you have 99999 in-game, "
            .. "gp may be wrong; current value=0x%08X", money))
    end

    -- 2. Trigger states
    console.log("--- recycle-shop trigger states ---")
    for _, n in ipairs(RECYCLE_TRIGGERS) do
        local b = r8(trig_byte(n))
        console.log(string.format(
            "  trigger %d: byte 0x%06X = 0x%02X, mask 0x%02X, set=%s",
            n, trig_byte(n), b, trig_mask(n),
            is_trig_set(n) and "Y" or "n"))
    end

    -- 3. gp slots
    console.log("--- known gp-relative shop slots ---")
    for _, slot in ipairs(GP_SLOTS) do
        local val = r32le(slot.off)
        local kind = "?"
        if val >= 0x80000000 and val < 0x80200000 then
            kind = "main-RAM ptr"
        elseif val == 0 then
            kind = "NULL"
        end
        console.log(string.format(
            "  %s @ 0x%06X = 0x%08X (%s)",
            slot.name, slot.off, val, kind))
        if val >= 0x80000000 and val < 0x80200000 then
            local bare = val - 0x80000000
            console.log(string.format(
                "    -> dump 32B at 0x%06X: %s",
                bare, dump_bytes(bare, 32)))
        end
    end

    -- 4. Wide gp scan
    dump_gp_wide()

    -- 5. Anchor scan: find money value (sanity check that addressing works)
    if money ~= 0 then
        local money_hits = scan_u32(money)
        console.log(string.format(
            "--- anchor scan: u32 value %d (0x%X) appears %d time(s) in RAM ---",
            money, money, #money_hits))
        for i, off in ipairs(money_hits) do
            if i > 8 then break end
            console.log(string.format("  0x%06X", off))
        end
    end

    -- 6. ID scans
    local h2 = scan_stride2()
    console.log(string.format("[stride-2 6/6] %d hit(s)", #h2))
    for _, off in ipairs(h2) do
        console.log(string.format(
            "  0x%06X: %s", off, dump_bytes(off, 14)))
    end

    local h1 = scan_stride1()
    console.log(string.format("[stride-1 6/6] %d hit(s)", #h1))
    for _, off in ipairs(h1) do
        console.log(string.format(
            "  0x%06X: %s", off, dump_bytes(off, 14)))
    end

    local h4 = scan_stride4()
    console.log(string.format("[stride-4 6/6] %d hit(s)", #h4))
    for _, off in ipairs(h4) do
        console.log(string.format(
            "  0x%06X: %s", off, dump_bytes(off, 28)))
    end

    -- 7. id+price scan + clustering
    local ip_hits = scan_id_plus_price()
    console.log(string.format(
        "[id+price] %d total (id_u8 ?? price_u16_LE) matches", #ip_hits))
    local clusters = find_id_price_clusters(ip_hits)
    console.log(string.format(
        "[id+price clusters of 4+ within 56B] %d", #clusters))
    for ci, cluster in ipairs(clusters) do
        if ci > 5 then break end
        console.log(string.format(
            "  cluster #%d (start 0x%06X, %d entries):",
            ci, cluster[1].off, #cluster))
        for _, hit in ipairs(cluster) do
            console.log(string.format(
                "    0x%06X: id=0x%02X (%s) price=%d, raw[0..8]=%s",
                hit.off, hit.id, annotate_id(hit.id),
                hit.price, dump_bytes(hit.off, 8)))
        end
    end

    console.log("=== end scan ===")
end

local last_trigger_states = {}
for _, n in ipairs(RECYCLE_TRIGGERS) do
    last_trigger_states[n] = false
end
local last_F_state = false

console.log("DW1 Recycle Shop probe v3 loaded.")
console.log(string.format(
    "  domains available: %s", table.concat(ALL_DOMAINS, ", ")))
console.log(string.format(
    "  using domain: %s (prefix 0x%08X)", DOMAIN, ADDR_PREFIX))
console.log(string.format("  GP = 0x%08X", GP))
console.log("  Press F to scan; HUD shows live state.")

while true do
    local any_transition = false
    for _, n in ipairs(RECYCLE_TRIGGERS) do
        local now = is_trig_set(n)
        if now and not last_trigger_states[n] then
            console.log(string.format(
                ">>> trigger %d transitioned 0->1 <<<", n))
            any_transition = true
        end
        last_trigger_states[n] = now
    end
    if any_transition then
        run_scans()
    end

    local f_now = (input.get()["F"] == true)
    if f_now and not last_F_state then
        console.log(">>> manual scan triggered (F key) <<<")
        run_scans()
    end
    last_F_state = f_now

    -- HUD
    local y = 2
    gui.text(2, y, string.format("scans: %d  press F", scan_count),
        "white", "black")
    y = y + 14
    -- Money sanity on HUD
    local money = r32le(gp_off(GP_MONEY_DISP))
    local money_color = (money == 0) and "red" or "lime"
    gui.text(2, y, string.format("money(gp-0x6C74) = %d", money),
        money_color, "black")
    y = y + 14
    for _, n in ipairs(RECYCLE_TRIGGERS) do
        local set = is_trig_set(n)
        gui.text(2, y, string.format("trig %d = %s", n, set and "SET" or "off"),
            set and "lime" or "red", "black")
        y = y + 12
    end

    emu.frameadvance()
end
