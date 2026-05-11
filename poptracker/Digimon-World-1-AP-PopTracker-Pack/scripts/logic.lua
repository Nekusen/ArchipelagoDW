-- Access-rule helpers for the DW1 ArchipelagoDW PopTracker pack.
--
-- Codes referenced here are the `codes` declared on each entry in
-- items/items.json. They mirror the AP item names from
-- worlds/digimon_world/items.py.
--
-- Region-reach functions mirror the entrance rules in
-- worlds/digimon_world/rules.py (with the optimistic assumption that
-- the seed runs in "shuffled" mode for the three option-gated
-- accesses: Lava Cave, TJ Bridge, GC Bridge — the player toggles
-- those items on at game start if their seed is in vanilla / always_open
-- mode).

local PROSPERITY_PER_ITEM = 3

local function has(code)
    return Tracker:ProviderCountForCode(code) > 0
end

local function count(code)
    return Tracker:ProviderCountForCode(code)
end

-- Translate a vanilla PP threshold to "do we have enough Prosperity
-- Point items" (each delivers PROSPERITY_PER_ITEM PP).
function has_pp(amount)
    return count("prosperity_point") * PROSPERITY_PER_ITEM >= tonumber(amount)
end

-- ---------------------------------------------------------------------
-- Region-reach helpers — one per region pin.
-- ---------------------------------------------------------------------

function reach_file_city() return true end
function reach_native_forest() return reach_file_city() end

function reach_drill_tunnel()
    return reach_native_forest()
end

function reach_meramon_tunnel()
    return reach_drill_tunnel() and has("lava_cave_access")
end

function reach_leomon_ancestor_cave()
    return reach_drill_tunnel() and has_pp(45)
end

function reach_mt_panorama()
    return reach_meramon_tunnel()
end

function reach_gear_savanna()
    if has("recruit_birdramon") and has("flight_gear_savanna") then return true end
    return reach_mt_panorama()
end

function reach_geko_swamp()
    return reach_gear_savanna()
end

function reach_misty_trees()
    if has("recruit_birdramon") and has("flight_misty_trees") then return true end
    if reach_geko_swamp() then return true end
    return reach_freezeland()
end

function reach_toy_town()
    return reach_misty_trees()
end

function reach_tropical_jungle()
    -- Shuffled-mode optimistic: requires the TJ Bridge AP item.
    return reach_native_forest() and has("tropical_jungle_bridge")
end

function reach_overdell()
    return reach_tropical_jungle()
end

function reach_grey_lords_mansion()
    return reach_overdell() and has("mansion_key")
end

function reach_ancient_dino_region()
    if has("recruit_birdramon") and has("flight_ancient_dino_region") then return true end
    return reach_tropical_jungle()
end

function reach_greatlake()
    return reach_native_forest()
end

function reach_beetle_land()
    if has("recruit_birdramon") and has("flight_beetle_land") then return true end
    if not reach_greatlake() then return false end
    return has("old_fishrod") or has("amazing_rod") or has("blue_flute")
end

function reach_great_canyon()
    -- Shuffled-mode optimistic: requires the GC Bridge AP item.
    return reach_greatlake() and has("great_canyon_bridge")
end

function reach_freezeland()
    if has("recruit_birdramon") and has("flight_freezeland") then return true end
    return reach_great_canyon()
end

function reach_mt_infinity()
    return reach_file_city() and has_pp(50)
end

function reach_tower()
    return reach_mt_infinity() and has_pp(50)
end

function reach_big_store()
    return reach_file_city() and has_pp(50)
end

function reach_factorial_town()
    return reach_file_city() and has("recruit_whamon")
end

function reach_secret_beach_cave()
    return reach_file_city() and has("recruit_whamon")
end

function reach_back_dimension()
    return has_pp(50)
       and reach_grey_lords_mansion()
       and reach_freezeland()
       and reach_great_canyon()
end
