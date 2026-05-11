-- DW1 Technique Mastery Snapshot Tool (BizHawk; Nymashock OR Octoshock)
--
-- Narrow-range RAM snapshot scoped to the partner save block and the
-- technique-mastery bitmap. Use this — not the generic
-- `dw1_ram_snapshot.lua` — when you want to isolate tech-mastery delta
-- behavior (NPC teach, partner rebirth, digivolution, etc.) without
-- diff noise from the rest of MainRAM.
--
-- Output format is identical to `dw1_ram_snapshot.lua` so the captures
-- feed `dw1_ram_diff.py` unchanged. Files are written as
-- `dw1_tech_snapshot_NN.txt` in BizHawk's working directory by default.
--
-- Captured range (0x001557C0..0x0015582F, 112 bytes) covers:
--
--   * 0x001557C0..0x001557DF (32 B) — pre-partner-stat padding context.
--     Useful when probing what else in the partner block moves during
--     the event being captured (e.g. partner rebirth resets the whole
--     block, not just the mastery bitmap).
--   * 0x001557E0..0x001557F3 — partner battle stats per DWAP Addresses.cs
--     (CurrentOffense/Defence/Speed/Brains, TechniqueSlot1, MaxHp, MaxMp).
--     Slot 1 at 0x001557EC is the partner's first active-moveset entry —
--     interesting because it tells us how mastery vs. active-moveset
--     interact (does setting a mastery bit also add to the slot1..N
--     array, or does that require a separate write?).
--   * 0x001557F4..0x001557FF (12 B) — likely rest of active-moveset slots
--     and other partner-block tail bytes (RE-confirmed via diff).
--   * 0x00155800..0x00155807 (8 B) — technique-mastery bitmap (DWAP
--     `GetTechAddress` switch). Bit N%8 of byte BASE + N//8. Player-
--     masterable slots span 0..56 with slot 48 skipped.
--   * 0x00155808..0x0015582F (40 B) — post-bitmap padding context.
--
-- Workflow (compare with dw1_ram_snapshot.lua workflow, which is the
-- canonical "find ANY changed byte" path):
--
--   1. Get to the moment just before the tech-mastery event you want to
--      capture (just before talking to the Bug NPC, just before the
--      Seadramon teach cutscene, just before the partner dies for rebirth
--      testing, etc.).
--   2. Press G in the emulator window  -> snapshot 01.
--   3. Trigger the event, wait for any cutscene to fully stabilize.
--   4. Press G again                   -> snapshot 02.
--   5. Diff with:
--        python worlds/digimon_world/tools/dw1_ram_diff.py \
--            dw1_tech_snapshot_01.txt dw1_tech_snapshot_02.txt --all-patterns
--      (use --all-patterns instead of the default sticky-flip filter:
--       partner stats fluctuate frame-to-frame, so the sticky filter
--       would hide most of the change set).
--   6. Look for single-bit 0->1 deltas inside 0x00155800..0x00155807.
--      That confirms the bit slot the event actually flipped.
--
-- Hypotheses this is designed to settle (per current chat):
--   * Does NPC teach (e.g. Bug at script offset 002854) flip exactly the
--     slot DWAP claims? (Snapshot before -> talk -> snapshot after.)
--   * Does partner rebirth clear the bitmap? (Master a tech, snapshot,
--     trigger rebirth via debug menu, snapshot.) If yes, the production
--     client needs a _reconcile_techniques tick loop.
--   * Does digivolution preserve mastery? (Master a tech on a Rookie,
--     snapshot, digivolve to Champion, snapshot.) Important for the
--     reconcile design — if mastery persists across forms we don't need
--     to re-write on every transition.

local START_ADDR = 0x001557C0
local END_ADDR   = 0x0015582F

-- Find a writable (domain, prefix). Mirrors `dw1_tech_poker.lua`'s
-- probe so the snapshot reflects the same memory view the poker
-- modifies.
--
-- NOTE: on recent BizHawk builds `memory.getmemorydomainlist()` hides
-- `MainRAM` even when BizHawk's UI exposes it. Known longstanding
-- BizHawk bug. Always try `MainRAM` by name first regardless of what
-- the enumeration returns.
local function find_writable_domain()
    local enumerated = memory.getmemorydomainlist()
    console.log("[dw1-tech-snapshot] memory.getmemorydomainlist() returns:")
    for _, d in ipairs(enumerated) do
        console.log("    " .. tostring(d))
    end

    local candidates = {
        {domain="MainRAM",    prefix=0x00000000, label="MainRAM (bare, by name)"},
    }
    for _, d in ipairs(enumerated) do
        local lower = string.lower(tostring(d))
        if (lower == "mainram" or lower == "main ram") and d ~= "MainRAM" then
            table.insert(candidates, {domain=d, prefix=0x00000000, label=tostring(d) .. " (bare, enumerated)"})
        end
    end
    for _, d in ipairs(enumerated) do
        if tostring(d) == "System Bus" then
            table.insert(candidates, {domain=d, prefix=0x80000000, label="System Bus +0x80000000 (KSEG0)"})
            table.insert(candidates, {domain=d, prefix=0xA0000000, label="System Bus +0xA0000000 (KSEG1)"})
            table.insert(candidates, {domain=d, prefix=0x00000000, label="System Bus (bare)"})
        end
    end

    -- Probe past END_ADDR so it doesn't appear inside the snapshot window.
    local probe = END_ADDR + 1
    console.log(string.format("[dw1-tech-snapshot] probing each candidate at 0x%06X:", probe))
    for _, c in ipairs(candidates) do
        local addr = probe + c.prefix
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
    error("[dw1-tech-snapshot] no writable domain found.")
end

local DOMAIN, ADDR_PREFIX = find_writable_domain()
local HOTKEY     = "G"   -- T is bound to throttle in BizHawk defaults
local OUTPUT_DIR = ""                    -- "" = BizHawk CWD; or e.g. "C:/tmp/"

-- Annotated regions, rendered into the snapshot header so diffs are
-- easier to read without having to cross-reference this comment block.
local REGION_NOTES = {
    "0x001557E0..0x001557E7  partner current stats (Off/Def/Spd/Brn, u16 LE)",
    "0x001557EC..0x001557ED  TechniqueSlot1 (active-moveset entry 1)",
    "0x001557F0..0x001557F3  partner MaxHp / MaxMp (u16 LE pair)",
    "0x00155800..0x00155807  technique mastery bitmap (slots 0..63)",
}

-- ----------------------------------------------------------------------------

local snapshot_count = 0
local key_was_down   = false

local function byte_to_bits(b)
    local s = ""
    for i = 7, 0, -1 do
        s = s .. (((b & (1 << i)) ~= 0) and "1" or "0")
    end
    return s
end

local function dump()
    snapshot_count = snapshot_count + 1
    local filename = OUTPUT_DIR .. string.format("dw1_tech_snapshot_%02d.txt", snapshot_count)
    local f = io.open(filename, "w")
    if not f then
        console.log("[dw1-tech-snapshot] ERROR: cannot write " .. filename)
        snapshot_count = snapshot_count - 1
        return
    end

    f:write(string.format("DW1 technique mastery snapshot #%02d\n", snapshot_count))
    f:write(string.format("domain=%s  range=0x%06X..0x%06X  frame=%d\n",
                          DOMAIN, START_ADDR, END_ADDR, emu.framecount()))
    f:write("format: <addr>: <16 bytes hex>  ||  <16 bytes binary MSB-first>\n")
    f:write("regions:\n")
    for _, note in ipairs(REGION_NOTES) do
        f:write("  " .. note .. "\n")
    end
    f:write("\n")

    for base = START_ADDR, END_ADDR, 16 do
        local hex_parts, bin_parts = {}, {}
        for i = 0, 15 do
            local addr = base + i
            if addr <= END_ADDR then
                local b = memory.read_u8(addr + ADDR_PREFIX, DOMAIN)
                hex_parts[#hex_parts + 1] = string.format("%02X", b)
                bin_parts[#bin_parts + 1] = byte_to_bits(b)
            end
        end
        f:write(string.format("0x%06X: %s  ||  %s\n",
                              base,
                              table.concat(hex_parts, " "),
                              table.concat(bin_parts, " ")))
    end

    f:close()
    console.log(string.format("[dw1-tech-snapshot %02d] wrote %s (frame %d)",
                              snapshot_count, filename, emu.framecount()))
end

console.log("DW1 technique mastery snapshot tool loaded.")
console.log(string.format("  range  : 0x%06X..0x%06X (%d bytes)",
                          START_ADDR, END_ADDR, END_ADDR - START_ADDR + 1))
console.log("  domain : " .. DOMAIN)
console.log("  hotkey : " .. HOTKEY .. "  (press in the emulator window)")
console.log("  diff   : python dw1_ram_diff.py dw1_tech_snapshot_*.txt --all-patterns")

while true do
    local keys     = input.get()
    local key_down = keys[HOTKEY] == true
    if key_down and not key_was_down then
        dump()
    end
    key_was_down = key_down

    gui.text(2, 2,
             string.format("DW1 tech snapshots: %d  (press %s)", snapshot_count, HOTKEY),
             "white", "black")

    emu.frameadvance()
end
