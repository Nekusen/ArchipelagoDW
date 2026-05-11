-- DW1 Technique Mastery Poker (BizHawk; Nymashock OR Octoshock)
--
-- Toggles technique-mastery bits in the partner save block to debug the
-- "AP grants tech X by writing one bit" hypothesis. Mastery storage was
-- mapped via DWAP's `GetTechAddress` switch (references/DWAP/source/
-- DWAP/Helpers.cs:507): bitmap base 0x00155800, bit (slot % 8) of byte
-- (0x00155800 + slot // 8). Player-masterable range is slots 0..56 with
-- slot 48 skipped (duplicate "Dynamite Kick v2"). Tech names match the
-- standalone randomizer (references/digimon_world_randomizer/digimon/
-- data.py:65).
--
-- Workflow this is designed for:
--   1. Boot DW1 in BizHawk, get into game (past Jijimon intro so the
--      partner save block is populated).
--   2. Tools > Lua Console > Open Script > pick this file.
--   3. Press `D` to dump current mastery state to the console. On a
--      fresh starter you should see only that starter's initial tech bit
--      set (e.g. slot 45 "Spit Fire" for most Rookies).
--   4. Pick a tech ID from `TEST_LIST` below (or edit the list) and
--      press `T` to set every bit in the list. Watch the in-game combat
--      menu / status screen to verify whether mastery alone makes the
--      tech usable, or whether the active-moveset (TECH_PARA species
--      list) gates it. Open RE question per the current chat.
--   5. Walk into a battle, try to use one of the granted techs. The
--      answer to "does the bit alone work" lives in whether the tech
--      shows up in the move menu.
--   6. Press `S` to set ALL 56 (mass test).  `C` to clear everything.
--      `D` again any time to re-dump.
--   7. Optional partner-rebirth test: trigger a partner death/rebirth
--      via debug menu (`dw1_debug_enable.lua` -> Mr. Warp), then press
--      `D`. If the byte goes back to 0, the bitmap lives in the partner
--      save block and resets on rebirth — the production client will
--      need a per-tick reconcile loop like _reconcile_recruits.
--
-- Hotkeys (press in the EMULATOR window, not the Lua console):
--   B  -> set every bit listed in TEST_LIST
--   N  -> clear every bit listed in TEST_LIST
--   A  -> set ALL 56 player-masterable techs
--   Z  -> clear ALL 56 player-masterable techs
--   D  -> dump current mastery state to the Lua console
--
-- NOTE: keys are chosen to avoid BizHawk's default hotkey bindings.
-- B / A / D are confirmed free in this project (they're what
-- `dw1_bit_poker.lua` uses). S, T, L, P, and the function keys are all
-- bound to save/load state / pause / throttle by default and will get
-- eaten before Lua sees them. If a key here ever stops working, flip
-- DEBUG_KEYS to true below and the script will log every key press it
-- actually receives, so you can pick a replacement.
--
-- Output: in-emulator HUD with live mastered-count + the active TEST_LIST
-- state, plus console.log() on every action.

-- Mastery bitmap base. Confirmed via DWAP's GetTechAddress switch.
local BITMAP_BASE = 0x00155800

-- Pick a writable (domain, prefix) combo by trial.
--
-- NOTE: on recent BizHawk builds (>2.10), `memory.getmemorydomainlist()`
-- omits `MainRAM` from its return value even when BizHawk's UI shows
-- it in the Memory Domains list. This is a known longstanding BizHawk
-- bug. Solution: don't trust the enumeration — try `MainRAM` directly
-- by name first via a write-and-read-back round-trip. If the call
-- doesn't error and the readback matches, MainRAM is accessible.
-- Otherwise fall through to whatever `getmemorydomainlist()` does
-- report and probe each `System Bus` prefix variant.
--
-- Probes happen at BITMAP_BASE + 16 (one byte past the bitmap, so any
-- failure to restore can't corrupt mastery state).
local function find_writable_domain()
    local enumerated = memory.getmemorydomainlist()
    console.log("[dw1-tech] memory.getmemorydomainlist() returns:")
    for _, d in ipairs(enumerated) do
        console.log("    " .. tostring(d))
    end

    -- MainRAM is the canonical Nymashock domain but BizHawk hides it
    -- from getmemorydomainlist() — try it by name regardless.
    local candidates = {
        {domain="MainRAM",    prefix=0x00000000, label="MainRAM (bare, by name)"},
    }
    -- Any other RAM-looking name the enumeration *did* return.
    for _, d in ipairs(enumerated) do
        local lower = string.lower(tostring(d))
        if (lower == "mainram" or lower == "main ram") and d ~= "MainRAM" then
            table.insert(candidates, {domain=d, prefix=0x00000000, label=tostring(d) .. " (bare, enumerated)"})
        end
    end
    -- System Bus fallbacks (cover all PSX MIPS virtual-address windows).
    for _, d in ipairs(enumerated) do
        if tostring(d) == "System Bus" then
            table.insert(candidates, {domain=d, prefix=0x80000000, label="System Bus +0x80000000 (KSEG0)"})
            table.insert(candidates, {domain=d, prefix=0xA0000000, label="System Bus +0xA0000000 (KSEG1)"})
            table.insert(candidates, {domain=d, prefix=0x00000000, label="System Bus (bare)"})
        end
    end

    local probe = BITMAP_BASE + 16
    console.log(string.format("[dw1-tech] probing each candidate at 0x%06X:", probe))
    for _, c in ipairs(candidates) do
        local addr = probe + c.prefix
        -- Use pcall — accessing an absent domain by name errors hard.
        local ok_read, orig = pcall(memory.read_u8, addr, c.domain)
        if not ok_read then
            console.log(string.format("    %-44s  (domain not accessible: %s)",
                                      c.label, tostring(orig)))
        else
            local target = (orig == 0xA5) and 0x5A or 0xA5
            pcall(memory.write_u8, addr, target, c.domain)
            local _, back = pcall(memory.read_u8, addr, c.domain)
            pcall(memory.write_u8, addr, orig, c.domain)  -- restore
            local ok = (back == target)
            console.log(string.format("    %-44s write=0x%02X readback=0x%02X  %s",
                                      c.label, target, back or 0, ok and "OK" or "FAIL"))
            if ok then
                console.log("    -> using " .. c.label)
                return c.domain, c.prefix
            end
        end
    end
    error("[dw1-tech] no writable domain found — paste the probe table above.")
end

local DOMAIN, ADDR_PREFIX = find_writable_domain()

-- Slot 48 (Dynamite Kick v2) is a duplicate of slot 47 and is skipped by
-- both DW1's own "Master all Techniques" debug script and DWAP's bit
-- table (it returns address=0, bit=0 — a no-op). Don't touch it.
local SKIPPED_SLOT = 48

-- Player-masterable range: 0..56 inclusive, minus SKIPPED_SLOT = 56 techs.
local MIN_SLOT, MAX_SLOT = 0, 56

-- Tech names (0x00..0x39 = slots 0..57). Verbatim from the standalone
-- randomizer's data.py:65 names dict. Slots 57+ are mostly digivolution
-- finishers; we only act on 0..56 but the table is kept long for human
-- reference when debugging.
local TECH_NAMES = {
    [0]  = "Fire Tower",       [1]  = "Prominence Beam", [2]  = "Spit Fire",
    [3]  = "Red Inferno",      [4]  = "Magma Bomb",      [5]  = "Heat Laser",
    [6]  = "Infinity Burn",    [7]  = "Meltdown",        [8]  = "Thunder Justice",
    [9]  = "Spinning Shot",    [10] = "Electric Cloud",  [11] = "Megalo Spark",
    [12] = "Static Elect",     [13] = "Wind Cutter",     [14] = "Confused Storm",
    [15] = "Hurricane",        [16] = "Giga Freeze",     [17] = "Ice Statue",
    [18] = "Winter Blast",     [19] = "Ice Needle",      [20] = "Water Blit",
    [21] = "Aqua Magic",       [22] = "Aurora Freeze",   [23] = "Tear Drop",
    [24] = "Power Crane",      [25] = "All Range Beam",  [26] = "Metal Sprinter",
    [27] = "Pulse Laser",      [28] = "Delete Program",  [29] = "DG Dimension",
    [30] = "Full Potential",   [31] = "Reverse Prog",    [32] = "Poison Powder",
    [33] = "Bug",              [34] = "Mass Morph",      [35] = "Insect Plague",
    [36] = "Charm Perfume",    [37] = "Poison Claw",     [38] = "Danger Sting",
    [39] = "Green Trap",       [40] = "Tremar",          [41] = "Muscle Charge",
    [42] = "War Cry",          [43] = "Sonic Jab",       [44] = "Dynamite Kick",
    [45] = "Counter",          [46] = "Megaton Punch",   [47] = "Buster Dive",
    [48] = "Dynamite Kick v2", -- SKIPPED — duplicate, not player-masterable
    [49] = "Odor Spray",       [50] = "Poop Spd Toss",   [51] = "Big Poop Toss",
    [52] = "Big Rnd Toss",     [53] = "Poop Rnd Toss",   [54] = "Rnd Spd Toss",
    [55] = "Horizontal Kick",  [56] = "Ult Poop Hell",
}

-- Set to true to log every key press input.get() reports. Use this if a
-- hotkey isn't responding — the log will tell you whether BizHawk is
-- delivering the press to Lua at all (vs. the key being eaten by a
-- core hotkey binding).
local DEBUG_KEYS = false

-- Edit this list to focus on a subset for the `B` / `N` hotkeys.
-- Default: a mixed bag representing different element/type categories,
-- so when you press `B` and walk into a battle you can see whether ANY
-- of these get added to the partner's move menu (answers the "does the
-- bit alone make the tech usable?" question regardless of partner form).
local TEST_LIST = {
    0,   -- Fire Tower
    8,   -- Thunder Justice
    13,  -- Wind Cutter
    16,  -- Giga Freeze
    20,  -- Water Blit
    24,  -- Power Crane (mech)
    33,  -- Bug
    37,  -- Poison Claw
    43,  -- Sonic Jab
}

-- ----------------------------------------------------------------------------

local function slot_addr_bit(slot)
    return BITMAP_BASE + math.floor(slot / 8), slot % 8
end

local function read_slot(slot)
    local addr, bitn = slot_addr_bit(slot)
    local v = memory.read_u8(addr + ADDR_PREFIX, DOMAIN)
    return (v & (1 << bitn)) ~= 0
end

local function write_slot(slot, set)
    if slot == SKIPPED_SLOT then return end
    local addr, bitn = slot_addr_bit(slot)
    local full = addr + ADDR_PREFIX
    local v = memory.read_u8(full, DOMAIN)
    local mask = 1 << bitn
    local target
    if set then
        target = v | mask
    else
        target = v & (~mask & 0xFF)
    end
    memory.write_u8(full, target, DOMAIN)
end

local function set_list(slots, set)
    for _, slot in ipairs(slots) do
        write_slot(slot, set)
    end
    local verb = set and "SET" or "CLEAR"
    local names = {}
    for _, slot in ipairs(slots) do
        names[#names + 1] = string.format("%d:%s", slot, TECH_NAMES[slot] or "?")
    end
    console.log(string.format("[tech-poke] %s %d techs: %s",
                              verb, #slots, table.concat(names, ", ")))
end

local function set_all(set)
    local n = 0
    for slot = MIN_SLOT, MAX_SLOT do
        if slot ~= SKIPPED_SLOT then
            write_slot(slot, set)
            n = n + 1
        end
    end
    console.log(string.format("[tech-poke] %s ALL %d player techs",
                              set and "SET" or "CLEAR", n))
end

local function count_mastered()
    local n = 0
    for slot = MIN_SLOT, MAX_SLOT do
        if slot ~= SKIPPED_SLOT and read_slot(slot) then
            n = n + 1
        end
    end
    return n
end

local function dump()
    console.log("--- DW1 technique mastery dump ---")
    -- Byte view: show each of the 8 bytes that hold the bitmap.
    for i = 0, 7 do
        local addr = BITMAP_BASE + i
        local v = memory.read_u8(addr + ADDR_PREFIX, DOMAIN)
        local bits = ""
        -- LSB-first to match slot ordering (slot N = bit N%8 of byte N//8).
        for b = 0, 7 do
            bits = bits .. (((v & (1 << b)) ~= 0) and "1" or "0")
        end
        console.log(string.format("  0x%06X = 0x%02X  slots %d..%d : %s",
                                  addr, v, i * 8, i * 8 + 7, bits))
    end
    -- Per-slot view: only mastered techs, by name.
    local mastered = {}
    for slot = MIN_SLOT, MAX_SLOT do
        if slot ~= SKIPPED_SLOT and read_slot(slot) then
            mastered[#mastered + 1] = string.format("%d:%s", slot, TECH_NAMES[slot] or "?")
        end
    end
    if #mastered == 0 then
        console.log("  (no techs mastered)")
    else
        console.log(string.format("  mastered (%d): %s",
                                  #mastered, table.concat(mastered, ", ")))
    end
end

local last = {}

local function edge(key)
    local now = (input.get()[key] == true)
    local was = last[key] or false
    last[key] = now
    return now and not was
end

console.log("DW1 Technique Mastery Poker loaded.")
console.log(string.format("  bitmap : 0x%06X..0x%06X  domain=%s",
                          BITMAP_BASE, BITMAP_BASE + 7, DOMAIN))
console.log(string.format("  range  : slots %d..%d (skipping %d)",
                          MIN_SLOT, MAX_SLOT, SKIPPED_SLOT))
console.log("  hotkeys: [B] set TEST_LIST  [N] clear TEST_LIST")
console.log("           [A] set ALL 56     [Z] clear ALL 56")
console.log("           [D] dump current state to console")
if DEBUG_KEYS then
    console.log("  DEBUG_KEYS=true: every key press will be logged.")
end
local test_names = {}
for _, slot in ipairs(TEST_LIST) do
    test_names[#test_names + 1] = string.format("%d:%s", slot, TECH_NAMES[slot] or "?")
end
console.log("  TEST_LIST: " .. table.concat(test_names, ", "))

local debug_last = {}
while true do
    if DEBUG_KEYS then
        -- Log any key whose state just went from up to down.
        local keys = input.get()
        for k, v in pairs(keys) do
            if v == true and not debug_last[k] then
                console.log(string.format("[tech-poke debug] key down: %q", k))
            end
        end
        debug_last = {}
        for k, v in pairs(keys) do
            if v == true then debug_last[k] = true end
        end
    end

    if edge("B") then set_list(TEST_LIST, true)  end
    if edge("N") then set_list(TEST_LIST, false) end
    if edge("A") then set_all(true)  end
    if edge("Z") then set_all(false) end
    if edge("D") then dump() end

    -- HUD: mastered count + TEST_LIST live status
    local n = count_mastered()
    gui.text(2, 2, string.format("DW1 techs mastered: %d / 56", n),
             n > 0 and "lime" or "white", "black")
    for i, slot in ipairs(TEST_LIST) do
        local on = read_slot(slot)
        gui.text(2, i * 14 + 2,
                 string.format("  %2d %-18s %s", slot,
                               TECH_NAMES[slot] or "?", on and "1" or "0"),
                 on and "lime" or "red", "black")
    end

    emu.frameadvance()
end
