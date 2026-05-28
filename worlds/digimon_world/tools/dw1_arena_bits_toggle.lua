-- DW1 200+X recruit-bit per-byte toggle + full-trigger-array dump.
--
-- Recruit-block per-byte hotkeys cover the 200..263 range (8 bytes).
-- Plus utilities to dump the WHOLE trigger array (so we can see what
-- story flags are set / unset and look for the Grade S gate) and to
-- mass-set every vanilla trigger (a "what if everything were on?" test
-- that excludes the AP-allocated 880+ band to keep AP locations safe).
--
-- Hotkeys (focus the BizHawk emulator window):
--   F1..F8  toggle recruit-block byte 0..7 (triggers 200..263)
--   F9      SET recruit-block (all 8 bytes = 0xFF)
--   F10     SET ALL vanilla triggers to 1   (range 0..879, AP band excluded)
--   F11     CLEAR recruit-block only
--   F12     DUMP every SET trigger across the full array (with names)

local DOMAIN          = "MainRAM"
local TRIGGER_BASE    = 0x001BDFCD   -- trigger 0 byte address
local RECRUIT_BASE    = 0x001BDFE6   -- trigger 200 byte = TRIGGER_BASE + 25
local RECRUIT_SIZE    = 8            -- covers triggers 200..263
-- AP-allocated trigger band starts at 880 (= byte TRIGGER_BASE+110 =
-- 0x001BE03B). Touching it would mess with cup-win, Birdramon flight,
-- vending, shop AP location detection. The "set everything" hotkey
-- stops at byte 0x001BE03A inclusive = trigger 879.
local VANILLA_END_BYTE = 0x001BE03A  -- last byte exclusively-vanilla
local FULL_ARRAY_END   = 0x001BE042  -- end of physical trigger array

-- Per-trigger labels for the dump. Only well-known ones; everything
-- else prints as "trigger N". Pulled from the project memory notes
-- and addresses.py inline comments.
local TRIGGER_NAMES = {
    [37]  = "arena: entered today's tournament",
    [38]  = "arena flag 38 (cleared by recalculatePPandArena)",
    [39]  = "arena flag 39 (cleared by recalculatePPandArena)",
    [45]  = "vanilla fishing-enable",
    [46]  = "Amazing Rod ownership",
    [50]  = "game-beaten (post-Machinedramon)",
    [76]  = "Rain Plant pickup",
    [91]  = "Arena building intro shown",
    [104] = "Frig Key pickup",
    [110] = "Mansion Key pickup",
    [120] = "Lava Cave boulder moved",
    [124] = "Great Canyon NPC unlock",
    [135] = "Leomonstone pickup",
    [145] = "Lava Cave Access (AP)",
    [203] = "Agumon recruited",     [204] = "Betamon recruited",
    [205] = "Greymon recruited",    [206] = "Devimon recruited",
    [207] = "Airdramon recruited",  [208] = "Tyrannomon recruited",
    [209] = "Meramon recruited",    [210] = "Seadramon recruited",
    [211] = "Numemon recruited",    [212] = "MetalGreymon recruited",
    [213] = "Mamemon recruited",    [214] = "Monzaemon recruited",
    [215] = "Gabumon recruited",    [216] = "Elecmon recruited",
    [217] = "Kabuterimon recruited",[218] = "Angemon recruited",
    [219] = "Birdramon recruited",  [220] = "Garurumon recruited",
    [221] = "Frigimon recruited",   [222] = "Vegimon recruited",
    [223] = "SkullGreymon recruited",[224] = "Whamon recruited",
    [225] = "MetalMamemon recruited",[226] = "Vademon recruited",
    [227] = "Patamon recruited",    [228] = "Kunemon recruited",
    [229] = "Unimon recruited",     [230] = "Ogremon recruited",
    [231] = "Shellmon recruited",   [232] = "Centarumon recruited",
    [233] = "Bakemon recruited",    [234] = "Drimogemon recruited",
    [235] = "Sukamon recruited",    [236] = "Andromon recruited",
    [237] = "Giromon recruited",    [238] = "Etemon recruited",
    [239] = "Biyomon recruited",    [240] = "Palmon recruited",
    [241] = "Monochromon recruited",[242] = "Leomon recruited",
    [243] = "Coelamon recruited",   [244] = "Kokatorimon recruited",
    [245] = "Kuwagamon recruited",  [246] = "Mojyamon recruited",
    [247] = "Nanimon recruited",    [248] = "Megadramon recruited",
    [249] = "Piximon recruited",    [250] = "Digitamamon recruited",
    [251] = "Penguinmon recruited", [252] = "Ninjamon recruited",
    [270] = "Gear pickup",          [320] = "Old Fishrod pickup",
    [575] = "Jijimon-dialog: Agumon-came shown",
    [577] = "Jijimon-dialog: Greymon-came shown",
    [584] = "Jijimon-dialog: MetalGreymon-came shown",
    [902] = "Old Fishrod AP location",
    [903] = "Amazing Rod AP location",
    [885] = "Arena Grade D won (AP)",
    [886] = "Arena Grade C won (AP)",
    [887] = "Arena Grade B won (AP)",
    [888] = "Arena Grade A won (AP)",
    [889] = "Arena Grade S won (AP)",
}

local function read_byte(addr)
    return memory.read_u8(addr, DOMAIN)
end

local function write_byte(addr, val)
    memory.write_u8(addr, val, DOMAIN)
end

local function bit_set(b, i)
    return bit.band(b, bit.lshift(1, i)) ~= 0
end

local recruit_next_action = {true, true, true, true, true, true, true, true}

local function toggle_recruit_byte(byte_off)
    local addr = RECRUIT_BASE + byte_off
    local trig_lo = 200 + byte_off * 8
    if recruit_next_action[byte_off + 1] then
        write_byte(addr, 0xFF)
        print(string.format("[toggle] SET   recruit byte %d @ 0x%08X = 0xFF  (triggers %d..%d ON)",
            byte_off, addr, trig_lo, trig_lo + 7))
        recruit_next_action[byte_off + 1] = false
    else
        write_byte(addr, 0x00)
        print(string.format("[toggle] CLEAR recruit byte %d @ 0x%08X = 0x00  (triggers %d..%d OFF)",
            byte_off, addr, trig_lo, trig_lo + 7))
        recruit_next_action[byte_off + 1] = true
    end
end

local function set_recruit_block()
    for i = 0, RECRUIT_SIZE - 1 do
        write_byte(RECRUIT_BASE + i, 0xFF)
        recruit_next_action[i + 1] = false
    end
    print("[toggle] SET recruit-block (triggers 200..263 ALL = 1)")
end

local function clear_recruit_block()
    for i = 0, RECRUIT_SIZE - 1 do
        write_byte(RECRUIT_BASE + i, 0x00)
        recruit_next_action[i + 1] = true
    end
    print("[toggle] CLEAR recruit-block (triggers 200..263 ALL = 0)")
end

local function set_all_vanilla()
    -- Set every trigger 0..879 to 1 (AP band 880+ left alone).
    for addr = TRIGGER_BASE, VANILLA_END_BYTE do
        write_byte(addr, 0xFF)
    end
    -- Reset toggle state on recruit-block since we just SET it.
    for i = 0, RECRUIT_SIZE - 1 do
        recruit_next_action[i + 1] = false
    end
    print(string.format(
        "[toggle] SET ALL vanilla triggers (0..879, bytes 0x%08X..0x%08X) = 0xFF",
        TRIGGER_BASE, VANILLA_END_BYTE))
    print("        (AP-allocated band 880+ left untouched)")
end

local function dump_set_triggers()
    print("[toggle] Currently SET triggers across the full array:")
    local count = 0
    for addr = TRIGGER_BASE, FULL_ARRAY_END do
        local b = read_byte(addr)
        if b ~= 0 then
            for bit_i = 0, 7 do
                if bit_set(b, bit_i) then
                    local trig_id = (addr - TRIGGER_BASE) * 8 + bit_i
                    local name = TRIGGER_NAMES[trig_id] or ""
                    if name == "" then
                        print(string.format("  trigger %4d  @ 0x%08X bit %d", trig_id, addr, bit_i))
                    else
                        print(string.format("  trigger %4d  @ 0x%08X bit %d  -- %s",
                            trig_id, addr, bit_i, name))
                    end
                    count = count + 1
                end
            end
        end
    end
    print(string.format("[toggle] Total set: %d", count))
end

print("DW1 trigger toggle + dump ready.")
print("Hotkeys (focus the BizHawk window):")
print("  F1..F8  toggle recruit byte 0..7 (triggers 200..263)")
print("  F9      SET recruit-block (200..263)")
print("  F10     SET ALL vanilla triggers (0..879, AP band excluded)")
print("  F11     CLEAR recruit-block (200..263)")
print("  F12     DUMP every set trigger across the full array")
print("")
print("Initial dump of currently set triggers:")
dump_set_triggers()

local KEYS = {
    F1  = function() toggle_recruit_byte(0) end,
    F2  = function() toggle_recruit_byte(1) end,
    F3  = function() toggle_recruit_byte(2) end,
    F4  = function() toggle_recruit_byte(3) end,
    F5  = function() toggle_recruit_byte(4) end,
    F6  = function() toggle_recruit_byte(5) end,
    F7  = function() toggle_recruit_byte(6) end,
    F8  = function() toggle_recruit_byte(7) end,
    F9  = set_recruit_block,
    F10 = set_all_vanilla,
    F11 = clear_recruit_block,
    F12 = dump_set_triggers,
}

local prev = {}
while true do
    local k = input.get()
    for keyname, fn in pairs(KEYS) do
        if k[keyname] and not prev[keyname] then
            fn()
        end
        prev[keyname] = k[keyname]
    end
    emu.frameadvance()
end
