-- DW1 Bit Poker (BizHawk + Nymashock)
--
-- Toggles specific story-event bits in MainRAM to test hypotheses about
-- what unlocks what. Designed for the workflow: load a save before the
-- gating event, walk to the supposedly-gated spot, then toggle bits and
-- see what makes the gate open.
--
-- Currently configured to test the "does beating Meramon open Mt.
-- Panorama?" hypothesis. The two bits set by the vanilla Meramon-defeat
-- sequence are:
--   * Meramon BEATEN  -- 0x001BE028 bit 1, trigger ID 729
--   * Meramon RECRUIT -- 0x001BDFE7 bit 1, trigger ID 209 ("Meramon joins city")
--
-- Edit the `bits` table below to test other flags.
--
-- Usage:
--   1. Load this script in BizHawk: Tools > Lua Console > Open Script.
--   2. Status HUD shows live bit values in the top-left corner.
--   3. In the emulator window:
--        B  -> toggle Meramon BEATEN
--        R  -> toggle Meramon RECRUIT
--        A  -> toggle ALL bits in lockstep (sets if any are 0, clears if all 1)
--        D  -> dump current values to the Lua console
--
-- Test plan for the Mt. Panorama hypothesis:
--   * Save before the Meramon fight, confirm Mt. Panorama spot is gated.
--   * Press B -> walk to spot -> is the gate open? (BEATEN-only)
--   * Press B again to clear, then R -> walk to spot. (RECRUIT-only)
--   * Press A to set BOTH -> walk to spot. (full Meramon-defeat state)
--
-- If none of those open the gate, the hypothesis is wrong (or the gate
-- is on a different flag that we still need to find).

local DOMAIN = "MainRAM"

local bits = {
    { name = "Meramon BEATEN",  addr = 0x001BE028, bit = 1, key = "B" },
    { name = "Meramon RECRUIT", addr = 0x001BDFE7, bit = 1, key = "R" },
}

-- ----------------------------------------------------------------------------

local function read_bit(b)
    local v = memory.read_u8(b.addr, DOMAIN)
    return bit.band(v, bit.lshift(1, b.bit)) ~= 0, v
end

local function write_bit(b, set)
    local v = memory.read_u8(b.addr, DOMAIN)
    local mask = bit.lshift(1, b.bit)
    if set then
        memory.write_u8(b.addr, bit.bor(v, mask), DOMAIN)
    else
        memory.write_u8(b.addr, bit.band(v, bit.bnot(mask)), DOMAIN)
    end
end

local function toggle(b)
    local cur, _ = read_bit(b)
    write_bit(b, not cur)
    console.log(string.format("[poke] %s @ 0x%06X bit %d -> %s",
                              b.name, b.addr, b.bit, tostring(not cur)))
end

local function toggle_all()
    local any_clear = false
    for _, b in ipairs(bits) do
        local cur, _ = read_bit(b)
        if not cur then any_clear = true break end
    end
    local target = any_clear  -- if anything is clear, set all; else clear all
    for _, b in ipairs(bits) do
        write_bit(b, target)
    end
    console.log(string.format("[poke] ALL bits -> %s", tostring(target)))
end

local function dump()
    console.log("--- DW1 bit dump ---")
    for _, b in ipairs(bits) do
        local cur, v = read_bit(b)
        console.log(string.format("  %s @ 0x%06X bit %d = %s  (byte=0x%02X)",
                                  b.name, b.addr, b.bit, tostring(cur), v))
    end
end

local last = {}

local function edge(key)
    local now = (input.get()[key] == true)
    local was = last[key] or false
    last[key] = now
    return now and not was
end

console.log("DW1 Bit Poker loaded.")
for _, b in ipairs(bits) do
    console.log(string.format("  [%s] toggle %s @ 0x%06X bit %d",
                              b.key, b.name, b.addr, b.bit))
end
console.log("  [A] toggle ALL    [D] dump current values to console")

while true do
    for _, b in ipairs(bits) do
        if edge(b.key) then toggle(b) end
    end
    if edge("A") then toggle_all() end
    if edge("D") then dump() end

    -- HUD overlay: live bit status
    for i, b in ipairs(bits) do
        local cur, _ = read_bit(b)
        local color = cur and "lime" or "red"
        gui.text(2, (i - 1) * 14 + 2,
                 string.format("[%s] %-18s %s", b.key, b.name, cur and "1" or "0"),
                 color, "black")
    end

    emu.frameadvance()
end
