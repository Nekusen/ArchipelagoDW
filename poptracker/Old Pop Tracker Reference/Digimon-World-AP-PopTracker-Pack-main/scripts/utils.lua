-- from https://stackoverflow.com/questions/9168058/how-to-dump-a-table-to-console
-- dumps a table in a readable string
function dump_table(o, depth)
    if depth == nil then
        depth = 0
    end
    if type(o) == 'table' then
        local tabs = ('\t'):rep(depth)
        local tabs2 = ('\t'):rep(depth + 1)
        local s = '{\n'
        for k, v in pairs(o) do
            if type(k) ~= 'number' then
                k = '"' .. k .. '"'
            end
            s = s .. tabs2 .. '[' .. k .. '] = ' .. dump_table(v, depth + 1) .. ',\n'
        end
        return s .. tabs .. '}'
    else
        return tostring(o)
    end
end


function toggle_item(code)
    local active = Tracker:FindObjectForCode(code).Active
    code = code.."_hosted"
    local object = Tracker:FindObjectForCode(code)
    if object then
        object.Active = active
    else
        if ENABLE_DEBUG_LOG then
            print(string.format("toggle_item: could not find object for code %s", code))
        end
    end
end

function toggle_hosted_item(code)
    local active = Tracker:FindObjectForCode(code).Active
    code = code:gsub("_hosted", "")
    local object = Tracker:FindObjectForCode(code)
    if object then
        object.Active = active
    else
        if ENABLE_DEBUG_LOG then
            print(string.format("toggle_hosted_item: could not find object for code %s", code))
        end
    end
end

-----------------------------------------------------------------------


function meat_farm_palmon()
    if Tracker:FindObjectForCode("palmon").Active == true then
        if Tracker:FindObjectForCode("vegiemon").Active == false then
        Tracker:FindObjectForCode("meat_farm").CurrentStage = 1
        end
    elseif Tracker:FindObjectForCode("palmon").Active == false then
        if Tracker:FindObjectForCode("vegiemon").Active == true then
            Tracker:FindObjectForCode("meat_farm").CurrentStage = 2
        elseif Tracker:FindObjectForCode("vegiemon").Active == false then
                Tracker:FindObjectForCode("meat_farm").CurrentStage = 0
        end
    end
end

function meat_farm_vegiemon()
    if Tracker:FindObjectForCode("vegiemon").Active == true then
        Tracker:FindObjectForCode("meat_farm").CurrentStage = 2
    elseif Tracker:FindObjectForCode("vegiemon").Active == false then
        if Tracker:FindObjectForCode("palmon").Active == true then
            Tracker:FindObjectForCode("meat_farm").CurrentStage = 1
        elseif Tracker:FindObjectForCode("palmon").Active == false then
                Tracker:FindObjectForCode("meat_farm").CurrentStage = 0
        end
    end
end

function item_bank_agumon()
    if Tracker:FindObjectForCode("agumon").Active == true then
        Tracker:FindObjectForCode("item_bank").Active = true
    elseif Tracker:FindObjectForCode("agumon").Active == false then
        Tracker:FindObjectForCode("item_bank").Active = false
    end
end

function item_stall_coelamon()
    if Tracker:FindObjectForCode("coelamon").Active == true then
        if Tracker:FindObjectForCode("biyomon").Active == false then
            if Tracker:FindObjectForCode("patamon").Active == false then
                if Tracker:FindObjectForCode("monochromon").Active == false then
                    if Tracker:FindObjectForCode("unimon").Active == false then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                end
            end
        end
    elseif Tracker:FindObjectForCode("coelamon").Active == false then
        if Tracker:FindObjectForCode("betamon").Active == false then
            if Tracker:FindObjectForCode("biyomon").Active == false then
                if Tracker:FindObjectForCode("patamon").Active == false then
                    if Tracker:FindObjectForCode("monochromon").Active == false then
                        if Tracker:FindObjectForCode("unimon").Active == false then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 0
                        elseif Tracker:FindObjectForCode("unimon").Active == true then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                        end
                    elseif Tracker:FindObjectForCode("monochromon").Active == true then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                    end
                elseif Tracker:FindObjectForCode("patamon").Active == true then
                    Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                end
            elseif Tracker:FindObjectForCode("biyomon").Active == true then
                Tracker:FindObjectForCode("item_shop").CurrentStage = 2
            end
        end
    elseif Tracker:FindObjectForCode("betamon").Active == true then
        if Tracker:FindObjectForCode("biyomon").Active == false then
            if Tracker:FindObjectForCode("patamon").Active == false then
                if Tracker:FindObjectForCode("monochromon").Active == false then
                    if Tracker:FindObjectForCode("unimon").Active == false then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                end
            end
        end
    end
end

function item_stall_betamon()
    if Tracker:FindObjectForCode("betamon").Active == true then
        if Tracker:FindObjectForCode("biyomon").Active == false then
            if Tracker:FindObjectForCode("patamon").Active == false then
                if Tracker:FindObjectForCode("monochromon").Active == false then
                    if Tracker:FindObjectForCode("unimon").Active == false then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                end
            end
        end
    elseif Tracker:FindObjectForCode("betamon").Active == false then
        if Tracker:FindObjectForCode("coelamon").Active == false then
            if Tracker:FindObjectForCode("biyomon").Active == false then
                if Tracker:FindObjectForCode("patamon").Active == false then
                    if Tracker:FindObjectForCode("monochromon").Active == false then
                        if Tracker:FindObjectForCode("unimon").Active == false then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 0
                        elseif Tracker:FindObjectForCode("unimon").Active == true then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                        end
                    elseif Tracker:FindObjectForCode("monochromon").Active == true then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                    end
                elseif Tracker:FindObjectForCode("patamon").Active == true then
                    Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                end
            elseif Tracker:FindObjectForCode("biyomon").Active == true then
                Tracker:FindObjectForCode("item_shop").CurrentStage = 2
            end
        end
    elseif Tracker:FindObjectForCode("coelamon").Active == true then
        if Tracker:FindObjectForCode("biyomon").Active == false then
            if Tracker:FindObjectForCode("patamon").Active == false then
                if Tracker:FindObjectForCode("monochromon").Active == false then
                    if Tracker:FindObjectForCode("unimon").Active == false then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                end
            end
        end
    end
end

function item_shop_biyomon()
    if Tracker:FindObjectForCode("biyomon").Active == true then
        Tracker:FindObjectForCode("item_shop").CurrentStage = 2
    elseif Tracker:FindObjectForCode("biyomon").Active == false then
        if Tracker:FindObjectForCode("patamon").Active == false then
            if Tracker:FindObjectForCode("monochromon").Active == false then
                if Tracker:FindObjectForCode("unimon").Active == false then
                    if Tracker:FindObjectForCode("coelamon").Active == false then
                        if Tracker:FindObjectForCode("betamon").Active == false then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 0
                        elseif Tracker:FindObjectForCode("betamon").Active == true then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                        end
                    elseif Tracker:FindObjectForCode("coelamon").Active == true then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                elseif Tracker:FindObjectForCode("unimon").Active == true then
                    Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                end
            elseif Tracker:FindObjectForCode("monochromon").Active == true then
                Tracker:FindObjectForCode("item_shop").CurrentStage = 2
            end
        elseif Tracker:FindObjectForCode("patamon").Active == true then
            Tracker:FindObjectForCode("item_shop").CurrentStage = 2
        end
    end
end

function item_shop_patamon()
    if Tracker:FindObjectForCode("patamon").Active == true then
        Tracker:FindObjectForCode("item_shop").CurrentStage = 2
    elseif Tracker:FindObjectForCode("patamon").Active == false then
        if Tracker:FindObjectForCode("biyomon").Active == false then
            if Tracker:FindObjectForCode("monochromon").Active == false then
                if Tracker:FindObjectForCode("unimon").Active == false then
                    if Tracker:FindObjectForCode("coelamon").Active == false then
                        if Tracker:FindObjectForCode("betamon").Active == false then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 0
                        elseif Tracker:FindObjectForCode("betamon").Active == true then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                        end
                    elseif Tracker:FindObjectForCode("coelamon").Active == true then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                elseif Tracker:FindObjectForCode("unimon").Active == true then
                    Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                end
            elseif Tracker:FindObjectForCode("monochromon").Active == true then
                Tracker:FindObjectForCode("item_shop").CurrentStage = 2
            end
        elseif Tracker:FindObjectForCode("biyomon").Active == true then
            Tracker:FindObjectForCode("item_shop").CurrentStage = 2
        end
    end
end

function item_shop_monochromon()
    if Tracker:FindObjectForCode("monochromon").Active == true then
        Tracker:FindObjectForCode("item_shop").CurrentStage = 2
    elseif Tracker:FindObjectForCode("monochromon").Active == false then
        if Tracker:FindObjectForCode("patamon").Active == false then
            if Tracker:FindObjectForCode("biyomon").Active == false then
                if Tracker:FindObjectForCode("unimon").Active == false then
                    if Tracker:FindObjectForCode("coelamon").Active == false then
                        if Tracker:FindObjectForCode("betamon").Active == false then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 0
                        elseif Tracker:FindObjectForCode("betamon").Active == true then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                        end
                    elseif Tracker:FindObjectForCode("coelamon").Active == true then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                elseif Tracker:FindObjectForCode("unimon").Active == true then
                    Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                end
            elseif Tracker:FindObjectForCode("biyomon").Active == true then
                Tracker:FindObjectForCode("item_shop").CurrentStage = 2
            end
        elseif Tracker:FindObjectForCode("patamon").Active == true then
            Tracker:FindObjectForCode("item_shop").CurrentStage = 2
        end
    end
end

function item_shop_unimon()
    if Tracker:FindObjectForCode("unimon").Active == true then
        Tracker:FindObjectForCode("item_shop").CurrentStage = 2
    elseif Tracker:FindObjectForCode("unimon").Active == false then
        if Tracker:FindObjectForCode("patamon").Active == false then
            if Tracker:FindObjectForCode("monochromon").Active == false then
                if Tracker:FindObjectForCode("biyomon").Active == false then
                    if Tracker:FindObjectForCode("coelamon").Active == false then
                        if Tracker:FindObjectForCode("betamon").Active == false then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 0
                        elseif Tracker:FindObjectForCode("betamon").Active == true then
                            Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                        end
                    elseif Tracker:FindObjectForCode("coelamon").Active == true then
                        Tracker:FindObjectForCode("item_shop").CurrentStage = 1
                    end
                elseif Tracker:FindObjectForCode("biyomon").Active == true then
                    Tracker:FindObjectForCode("item_shop").CurrentStage = 2
                end
            elseif Tracker:FindObjectForCode("monochromon").Active == true then
                Tracker:FindObjectForCode("item_shop").CurrentStage = 2
            end
        elseif Tracker:FindObjectForCode("patamon").Active == true then
            Tracker:FindObjectForCode("item_shop").CurrentStage = 2
        end
    end
end

function birdra_transport_birdramon()
    if Tracker:FindObjectForCode("birdramon").Active == true then
        Tracker:FindObjectForCode("birdra_transport").Active = true
    elseif Tracker:FindObjectForCode("birdramon").Active == false then
        Tracker:FindObjectForCode("birdra_transport").Active = false
    end
end

function clinic_centarumon()
    if Tracker:FindObjectForCode("centarumon").Active == true then
        Tracker:FindObjectForCode("clinic").Active = true
    elseif Tracker:FindObjectForCode("centarumon").Active == false then
        Tracker:FindObjectForCode("clinic").Active = false
    end
end

function restaurant_frigimon()
    if Tracker:FindObjectForCode("frigimon").Active == true then
        Tracker:FindObjectForCode("restaurant").Active = true
    elseif Tracker:FindObjectForCode("frigimon").Active == false then
        if Tracker:FindObjectForCode("garurumon").Active == false then
            if Tracker:FindObjectForCode("meramon").Active == false then
                if Tracker:FindObjectForCode("tyrannomon").Active == false then
                    if Tracker:FindObjectForCode("digitamamon").Active == false then
                        Tracker:FindObjectForCode("restaurant").Active = false
                    end
                end
            end
        end
    end
end

function restaurant_garurumon()
    if Tracker:FindObjectForCode("garurumon").Active == true then
        Tracker:FindObjectForCode("restaurant").Active = true
    elseif Tracker:FindObjectForCode("garurumon").Active == false then
        if Tracker:FindObjectForCode("frigimon").Active == false then
            if Tracker:FindObjectForCode("meramon").Active == false then
                if Tracker:FindObjectForCode("tyrannomon").Active == false then
                    if Tracker:FindObjectForCode("digitamamon").Active == false then
                        Tracker:FindObjectForCode("restaurant").Active = false
                    end
                end
            end
        end
    end
end

function restaurant_meramon()
    if Tracker:FindObjectForCode("meramon").Active == true then
        Tracker:FindObjectForCode("restaurant").Active = true
    elseif Tracker:FindObjectForCode("meramon").Active == false then
        if Tracker:FindObjectForCode("frigimon").Active == false then
            if Tracker:FindObjectForCode("garurumon").Active == false then
                if Tracker:FindObjectForCode("tyrannomon").Active == false then
                    if Tracker:FindObjectForCode("digitamamon").Active == false then
                        Tracker:FindObjectForCode("restaurant").Active = false
                    end
                end
            end
        end
    end
end

function restaurant_tyrannomon()
    if Tracker:FindObjectForCode("tyrannomon").Active == true then
        Tracker:FindObjectForCode("restaurant").Active = true
    elseif Tracker:FindObjectForCode("tyrannomon").Active == false then
        if Tracker:FindObjectForCode("frigimon").Active == false then
            if Tracker:FindObjectForCode("garurumon").Active == false then
                if Tracker:FindObjectForCode("meramon").Active == false then
                    if Tracker:FindObjectForCode("digitamamon").Active == false then
                        Tracker:FindObjectForCode("restaurant").Active = false
                    end
                end
            end
        end
    end
end

function restaurant_digitamamon()
    if Tracker:FindObjectForCode("digitamamon").Active == true then
        Tracker:FindObjectForCode("restaurant").Active = true
    elseif Tracker:FindObjectForCode("digitamamon").Active == false then
        if Tracker:FindObjectForCode("frigimon").Active == false then
            if Tracker:FindObjectForCode("garurumon").Active == false then
                if Tracker:FindObjectForCode("meramon").Active == false then
                    if Tracker:FindObjectForCode("tyrannomon").Active == false then
                        Tracker:FindObjectForCode("restaurant").Active = false
                    end
                end
            end
        end
    end
end

ScriptHost:AddWatchForCode("meat_farm_handler_palmon", "palmon", meat_farm_palmon)
ScriptHost:AddWatchForCode("meat_farm_handler_vegiemon", "vegiemon", meat_farm_vegiemon)
ScriptHost:AddWatchForCode("item_bank_handler_agumon", "agumon", item_bank_agumon)
ScriptHost:AddWatchForCode("item_stall_handler_betamon", "betamon", item_stall_betamon)
ScriptHost:AddWatchForCode("item_stall_handler_coelamon", "coelamon", item_stall_coelamon)
ScriptHost:AddWatchForCode("item_shop_handler_biyomon", "biyomon", item_shop_biyomon)
ScriptHost:AddWatchForCode("item_shop_handler_patamon", "patamon", item_shop_patamon)
ScriptHost:AddWatchForCode("item_shop_handler_monochromon", "monochromon", item_shop_monochromon)
ScriptHost:AddWatchForCode("item_shop_handler_unimon", "unimon", item_shop_unimon)
ScriptHost:AddWatchForCode("birdra_transport_handler_birdramon", "birdramon", birdra_transport_birdramon)
ScriptHost:AddWatchForCode("clinic_handler_centarumon", "centarumon", clinic_centarumon)
ScriptHost:AddWatchForCode("restaurant_handler_frigimon", "frigimon", restaurant_frigimon)
ScriptHost:AddWatchForCode("restaurant_handler_garurumon", "garurumon", restaurant_garurumon)
ScriptHost:AddWatchForCode("restaurant_handler_meramon", "meramon", restaurant_meramon)
ScriptHost:AddWatchForCode("restaurant_handler_tyrannomon", "tyrannomon", restaurant_tyrannomon)
ScriptHost:AddWatchForCode("restaurant_handler_digitamamon", "digitamamon", restaurant_digitamamon)

---------------------------------------------------------------------------------------------------

function agumon_recruit()
    if Tracker:FindObjectForCode("agumon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
        Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("agumon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
        Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount + 1
    end
end

function betamon_recruit()
    if Tracker:FindObjectForCode("betamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("betamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function greymon_recruit()
    if Tracker:FindObjectForCode("greymon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("greymon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function devimon_recruit()
    if Tracker:FindObjectForCode("devimon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("devimon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function airdramon_recruit()
    if Tracker:FindObjectForCode("airdramon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("airdramon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function tyrannomon_recruit()
    if Tracker:FindObjectForCode("tyrannomon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("tyrannomon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function meramon_recruit()
    if Tracker:FindObjectForCode("meramon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("meramon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function seadramon_recruit()
    if Tracker:FindObjectForCode("seadramon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("seadramon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function numemon_recruit()
    if Tracker:FindObjectForCode("numemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("numemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function metalgreymon_recruit()
    if Tracker:FindObjectForCode("metalgreymon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("metalgreymon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function mamemon_recruit()
    if Tracker:FindObjectForCode("mamemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("mamemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function monzaemon_recruit()
    if Tracker:FindObjectForCode("monzaemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("monzaemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function gabumon_recruit()
    if Tracker:FindObjectForCode("gabumon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("gabumon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function elecmon_recruit()
    if Tracker:FindObjectForCode("elecmon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("elecmon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function kabuterimon_recruit()
    if Tracker:FindObjectForCode("kabuterimon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("kabuterimon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function angemon_recruit()
    if Tracker:FindObjectForCode("angemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("angemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function birdramon_recruit()
    if Tracker:FindObjectForCode("birdramon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("birdramon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function garurumon_recruit()
    if Tracker:FindObjectForCode("garurumon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("garurumon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function frigimon_recruit()
    if Tracker:FindObjectForCode("frigimon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("frigimon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function whamon_recruit()
    if Tracker:FindObjectForCode("whamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("whamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function vegiemon_recruit()
    if Tracker:FindObjectForCode("vegiemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("vegiemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function skullgreymon_recruit()
    if Tracker:FindObjectForCode("skullgreymon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("skullgreymon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function metalmamemon_recruit()
    if Tracker:FindObjectForCode("metalmamemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("metalmamemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function vademon_recruit()
    if Tracker:FindObjectForCode("vademon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("vademon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function patamon_recruit()
    if Tracker:FindObjectForCode("patamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("patamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function kunemon_recruit()
    if Tracker:FindObjectForCode("kunemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("kunemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function unimon_recruit()
    if Tracker:FindObjectForCode("unimon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("unimon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function ogremon_recruit()
    if Tracker:FindObjectForCode("ogremon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("ogremon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function shellmon_recruit()
    if Tracker:FindObjectForCode("shellmon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("shellmon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function centarumon_recruit()
    if Tracker:FindObjectForCode("centarumon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("centarumon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function bakemon_recruit()
    if Tracker:FindObjectForCode("bakemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("bakemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function drimogemon_recruit()
    if Tracker:FindObjectForCode("drimogemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("drimogemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function sukamon_recruit()
    if Tracker:FindObjectForCode("sukamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("sukamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function andromon_recruit()
    if Tracker:FindObjectForCode("andromon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("andromon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function giromon_recruit()
    if Tracker:FindObjectForCode("giromon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("giromon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function etemon_recruit()
    if Tracker:FindObjectForCode("etemon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("etemon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function biyomon_recruit()
    if Tracker:FindObjectForCode("biyomon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("biyomon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function palmon_recruit()
    if Tracker:FindObjectForCode("palmon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("palmon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function monochromon_recruit()
    if Tracker:FindObjectForCode("monochromon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("monochromon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function leomon_recruit()
    if Tracker:FindObjectForCode("leomon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("leomon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function coelamon_recruit()
    if Tracker:FindObjectForCode("coelamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("coelamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function kokatorimon_recruit()
    if Tracker:FindObjectForCode("kokatorimon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("kokatorimon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function kuwagamon_recruit()
    if Tracker:FindObjectForCode("kuwagamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("kuwagamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function mojyamon_recruit()
    if Tracker:FindObjectForCode("mojyamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("mojyamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end

function nanimon_recruit()
    if Tracker:FindObjectForCode("nanimon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("nanimon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function megadramon_recruit()
    if Tracker:FindObjectForCode("megadramon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("megadramon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function piximon_recruit()
    if Tracker:FindObjectForCode("piximon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("piximon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function digitamamon_recruit()
    if Tracker:FindObjectForCode("digitamamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 3
    elseif Tracker:FindObjectForCode("digitamamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 3
    end
end

function penguinmon_recruit()
    if Tracker:FindObjectForCode("penguinmon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 1
    elseif Tracker:FindObjectForCode("penguinmon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 1
    end
end

function ninjamon_recruit()
    if Tracker:FindObjectForCode("ninjamon").Active then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount + 2
    elseif Tracker:FindObjectForCode("ninjamon").Active == false then
        Tracker:FindObjectForCode("prosperity_counter").AcquiredCount = Tracker:FindObjectForCode("prosperity_counter").AcquiredCount - 2
    end
end


---------------------------------------------------------------------


function agumon_recruit_vanilla()
    if Tracker:FindObjectForCode("agumon").Active then
        Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("agumon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Agumon/Prosperity Point").AvailableChestCount + 1
    end
end

function betamon_recruit_vanilla()
    if Tracker:FindObjectForCode("betamon").Active then
        Tracker:FindObjectForCode("@Tropical Jungle/Betamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Betamon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("betamon").Active == false then
        Tracker:FindObjectForCode("@Tropical Jungle/Betamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Betamon/Prosperity Point").AvailableChestCount + 1
    end
end

function greymon_recruit_vanilla()
    if Tracker:FindObjectForCode("greymon").Active then
        Tracker:FindObjectForCode("@File City/Greymon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@File City/Greymon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("greymon").Active == false then
        Tracker:FindObjectForCode("@File City/Greymon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@File City/Greymon/Prosperity Point").AvailableChestCount + 2
    end
end

function devimon_recruit_vanilla()
    if Tracker:FindObjectForCode("devimon").Active then
        Tracker:FindObjectForCode("@Mt. Infinity/Devimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/Devimon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("devimon").Active == false then
        Tracker:FindObjectForCode("@Mt. Infinity/Devimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/Devimon/Prosperity Point").AvailableChestCount + 2
    end
end

function airdramon_recruit_vanilla()
    if Tracker:FindObjectForCode("airdramon").Active then
        Tracker:FindObjectForCode("@File City/Airdramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@File City/Airdramon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("airdramon").Active == false then
        Tracker:FindObjectForCode("@File City/Airdramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@File City/Airdramon/Prosperity Point").AvailableChestCount + 2
    end
end

function tyrannomon_recruit_vanilla()
    if Tracker:FindObjectForCode("tyrannomon").Active then
        Tracker:FindObjectForCode("@Ancient Dino Region/Tyrannomon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Ancient Dino Region/Tyrannomon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("tyrannomon").Active == false then
        Tracker:FindObjectForCode("@Ancient Dino Region/Tyrannomon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Ancient Dino Region/Tyrannomon/Prosperity Point").AvailableChestCount + 2
    end
end

function meramon_recruit_vanilla()
    if Tracker:FindObjectForCode("meramon").Active then
        Tracker:FindObjectForCode("@Drill Tunnel/Meramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Drill Tunnel/Meramon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("meramon").Active == false then
        Tracker:FindObjectForCode("@Drill Tunnel/Meramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Drill Tunnel/Meramon/Prosperity Point").AvailableChestCount + 2
    end
end

function seadramon_recruit_vanilla()
    if Tracker:FindObjectForCode("seadramon").Active then
        Tracker:FindObjectForCode("@Native Forest/Seadramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Seadramon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("seadramon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Seadramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Seadramon/Prosperity Point").AvailableChestCount + 2
    end
end

function numemon_recruit_vanilla()
    if Tracker:FindObjectForCode("numemon").Active then
        Tracker:FindObjectForCode("@Factorial Town/Numemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/Numemon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("numemon").Active == false then
        Tracker:FindObjectForCode("@Factorial Town/Numemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/Numemon/Prosperity Point").AvailableChestCount + 1
    end
end

function metalgreymon_recruit_vanilla()
    if Tracker:FindObjectForCode("metalgreymon").Active then
        Tracker:FindObjectForCode("@Mt. Infinity/MetalGreymon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/MetalGreymon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("metalgreymon").Active == false then
        Tracker:FindObjectForCode("@Mt. Infinity/MetalGreymon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/MetalGreymon/Prosperity Point").AvailableChestCount + 3
    end
end

function mamemon_recruit_vanilla()
    if Tracker:FindObjectForCode("mamemon").Active then
        Tracker:FindObjectForCode("@Mt. Panorama/Mamemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Panorama/Mamemon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("mamemon").Active == false then
        Tracker:FindObjectForCode("@Mt. Panorama/Mamemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Panorama/Mamemon/Prosperity Point").AvailableChestCount + 3
    end
end

function monzaemon_recruit_vanilla()
    if Tracker:FindObjectForCode("monzaemon").Active then
        Tracker:FindObjectForCode("@Toy Town/Monzaemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Toy Town/Monzaemon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("monzaemon").Active == false then
        Tracker:FindObjectForCode("@Toy Town/Monzaemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Toy Town/Monzaemon/Prosperity Point").AvailableChestCount + 3
    end
end

function gabumon_recruit_vanilla()
    if Tracker:FindObjectForCode("gabumon").Active then
        Tracker:FindObjectForCode("@Misty Trees/Gabumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Misty Trees/Gabumon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("gabumon").Active == false then
        Tracker:FindObjectForCode("@Misty Trees/Gabumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Misty Trees/Gabumon/Prosperity Point").AvailableChestCount + 1
    end
end

function elecmon_recruit_vanilla()
    if Tracker:FindObjectForCode("elecmon").Active then
        Tracker:FindObjectForCode("@Gear Savanna/Elecmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Elecmon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("elecmon").Active == false then
        Tracker:FindObjectForCode("@Gear Savanna/Elecmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Elecmon/Prosperity Point").AvailableChestCount + 1
    end
end

function kabuterimon_recruit_vanilla()
    if Tracker:FindObjectForCode("kabuterimon").Active then
        Tracker:FindObjectForCode("@Beetle Land/Kabuterimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Beetle Land/Kabuterimon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("kabuterimon").Active == false then
        Tracker:FindObjectForCode("@Beetle Land/Kabuterimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Beetle Land/Kabuterimon/Prosperity Point").AvailableChestCount + 2
    end
end

function angemon_recruit_vanilla()
    if Tracker:FindObjectForCode("angemon").Active then
        Tracker:FindObjectForCode("@Freezeland/Angemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Angemon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("angemon").Active == false then
        Tracker:FindObjectForCode("@Freezeland/Angemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Angemon/Prosperity Point").AvailableChestCount + 2
    end
end

function birdramon_recruit_vanilla()
    if Tracker:FindObjectForCode("birdramon").Active then
        Tracker:FindObjectForCode("@Great Canyon/Birdramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Great Canyon/Birdramon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("birdramon").Active == false then
        Tracker:FindObjectForCode("@Great Canyon/Birdramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Great Canyon/Birdramon/Prosperity Point").AvailableChestCount + 2
    end
end

function garurumon_recruit_vanilla()
    if Tracker:FindObjectForCode("garurumon").Active then
        Tracker:FindObjectForCode("@Freezeland/Garurumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Garurumon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("garurumon").Active == false then
        Tracker:FindObjectForCode("@Freezeland/Garurumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Garurumon/Prosperity Point").AvailableChestCount + 2
    end
end

function frigimon_recruit_vanilla()
    if Tracker:FindObjectForCode("frigimon").Active then
        Tracker:FindObjectForCode("@Freezeland/Frigimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Frigimon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("frigimon").Active == false then
        Tracker:FindObjectForCode("@Freezeland/Frigimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Frigimon/Prosperity Point").AvailableChestCount + 2
    end
end

function whamon_recruit_vanilla()
    if Tracker:FindObjectForCode("whamon").Active then
        Tracker:FindObjectForCode("@Freezeland/Whamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Whamon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("whamon").Active == false then
        Tracker:FindObjectForCode("@Freezeland/Whamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Whamon/Prosperity Point").AvailableChestCount + 2
    end
end

function vegiemon_recruit_vanilla()
    if Tracker:FindObjectForCode("vegiemon").Active then
        Tracker:FindObjectForCode("@Tropical Jungle/Vegiemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Vegiemon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("vegiemon").Active == false then
        Tracker:FindObjectForCode("@Tropical Jungle/Vegiemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Vegiemon/Prosperity Point").AvailableChestCount + 2
    end
end

function skullgreymon_recruit_vanilla()
    if Tracker:FindObjectForCode("skullgreymon").Active then
        Tracker:FindObjectForCode("@Grey Lord Mansion/SkullGreymon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Grey Lord Mansion/SkullGreymon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("skullgreymon").Active == false then
        Tracker:FindObjectForCode("@Grey Lord Mansion/SkullGreymon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Grey Lord Mansion/SkullGreymon/Prosperity Point").AvailableChestCount + 3
    end
end

function metalmamemon_recruit_vanilla()
    if Tracker:FindObjectForCode("metalmamemon").Active then
        Tracker:FindObjectForCode("@Factorial Town/MetalMamemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/MetalMamemon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("metalmamemon").Active == false then
        Tracker:FindObjectForCode("@Factorial Town/MetalMamemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/MetalMamemon/Prosperity Point").AvailableChestCount + 3
    end
end

function vademon_recruit_vanilla()
    if Tracker:FindObjectForCode("vademon").Active then
        Tracker:FindObjectForCode("@Mt. Panorama/Vademon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Panorama/Vademon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("vademon").Active == false then
        Tracker:FindObjectForCode("@Mt. Panorama/Vademon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Panorama/Vademon/Prosperity Point").AvailableChestCount + 3
    end
end

function patamon_recruit_vanilla()
    if Tracker:FindObjectForCode("patamon").Active then
        Tracker:FindObjectForCode("@Gear Savanna/Patamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Patamon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("patamon").Active == false then
        Tracker:FindObjectForCode("@Gear Savanna/Patamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Patamon/Prosperity Point").AvailableChestCount + 1
    end
end

function kunemon_recruit_vanilla()
    if Tracker:FindObjectForCode("kunemon").Active then
        Tracker:FindObjectForCode("@Native Forest/Kunemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Kunemon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("kunemon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Kunemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Kunemon/Prosperity Point").AvailableChestCount + 1
    end
end

function unimon_recruit_vanilla()
    if Tracker:FindObjectForCode("unimon").Active then
        Tracker:FindObjectForCode("@Mt. Panorama/Unimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Panorama/Unimon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("unimon").Active == false then
        Tracker:FindObjectForCode("@Mt. Panorama/Unimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Panorama/Unimon/Prosperity Point").AvailableChestCount + 2
    end
end

function ogremon_recruit_vanilla()
    if Tracker:FindObjectForCode("ogremon").Active then
        Tracker:FindObjectForCode("@Drill Tunnel/Ogremon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Drill Tunnel/Ogremon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("ogremon").Active == false then
        Tracker:FindObjectForCode("@Drill Tunnel/Ogremon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Drill Tunnel/Ogremon/Prosperity Point").AvailableChestCount + 2
    end
end

function shellmon_recruit_vanilla()
    if Tracker:FindObjectForCode("shellmon").Active then
        Tracker:FindObjectForCode("@Great Canyon/Shellmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Great Canyon/Shellmon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("shellmon").Active == false then
        Tracker:FindObjectForCode("@Great Canyon/Shellmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Great Canyon/Shellmon/Prosperity Point").AvailableChestCount + 2
    end
end

function centarumon_recruit_vanilla()
    if Tracker:FindObjectForCode("centarumon").Active then
        Tracker:FindObjectForCode("@Tropical Jungle/Centarumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Centarumon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("centarumon").Active == false then
        Tracker:FindObjectForCode("@Tropical Jungle/Centarumon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Centarumon/Prosperity Point").AvailableChestCount + 2
    end
end

function bakemon_recruit_vanilla()
    if Tracker:FindObjectForCode("bakemon").Active then
        Tracker:FindObjectForCode("@Grey Lord Mansion/Bakemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Grey Lord Mansion/Bakemon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("bakemon").Active == false then
        Tracker:FindObjectForCode("@Grey Lord Mansion/Bakemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Grey Lord Mansion/Bakemon/Prosperity Point").AvailableChestCount + 2
    end
end

function drimogemon_recruit_vanilla()
    if Tracker:FindObjectForCode("drimogemon").Active then
        Tracker:FindObjectForCode("@Drill Tunnel/Drimogemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Drill Tunnel/Drimogemon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("drimogemon").Active == false then
        Tracker:FindObjectForCode("@Drill Tunnel/Drimogemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Drill Tunnel/Drimogemon/Prosperity Point").AvailableChestCount + 2
    end
end

function sukamon_recruit_vanilla()
    if Tracker:FindObjectForCode("sukamon").Active then
        Tracker:FindObjectForCode("@Gear Savanna/Sukamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Sukamon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("sukamon").Active == false then
        Tracker:FindObjectForCode("@Gear Savanna/Sukamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Sukamon/Prosperity Point").AvailableChestCount + 1
    end
end

function andromon_recruit_vanilla()
    if Tracker:FindObjectForCode("andromon").Active then
        Tracker:FindObjectForCode("@Factorial Town/Andromon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/Andromon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("andromon").Active == false then
        Tracker:FindObjectForCode("@Factorial Town/Andromon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/Andromon/Prosperity Point").AvailableChestCount + 3
    end
end

function giromon_recruit_vanilla()
    if Tracker:FindObjectForCode("giromon").Active then
        Tracker:FindObjectForCode("@Factorial Town/Giromon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/Giromon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("giromon").Active == false then
        Tracker:FindObjectForCode("@Factorial Town/Giromon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Factorial Town/Giromon/Prosperity Point").AvailableChestCount + 3
    end
end

function etemon_recruit_vanilla()
    if Tracker:FindObjectForCode("etemon").Active then
        Tracker:FindObjectForCode("@Native Forest/Etemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Etemon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("etemon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Etemon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Etemon/Prosperity Point").AvailableChestCount + 3
    end
end

function biyomon_recruit_vanilla()
    if Tracker:FindObjectForCode("biyomon").Active then
        Tracker:FindObjectForCode("@Gear Savanna/Biyomon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Biyomon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("biyomon").Active == false then
        Tracker:FindObjectForCode("@Gear Savanna/Biyomon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Biyomon/Prosperity Point").AvailableChestCount + 1
    end
end

function palmon_recruit_vanilla()
    if Tracker:FindObjectForCode("palmon").Active then
        Tracker:FindObjectForCode("@Native Forest/Palmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Palmon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("palmon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Palmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Palmon/Prosperity Point").AvailableChestCount + 1
    end
end

function monochromon_recruit_vanilla()
    if Tracker:FindObjectForCode("monochromon").Active then
        Tracker:FindObjectForCode("@Great Canyon/Monochromon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Great Canyon/Monochromon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("monochromon").Active == false then
        Tracker:FindObjectForCode("@Great Canyon/Monochromon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Great Canyon/Monochromon/Prosperity Point").AvailableChestCount + 2
    end
end

function leomon_recruit_vanilla()
    if Tracker:FindObjectForCode("leomon").Active then
        Tracker:FindObjectForCode("@Gear Savanna/Leomon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Leomon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("leomon").Active == false then
        Tracker:FindObjectForCode("@Gear Savanna/Leomon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Gear Savanna/Leomon/Prosperity Point").AvailableChestCount + 2
    end
end

function coelamon_recruit_vanilla()
    if Tracker:FindObjectForCode("coelamon").Active then
        Tracker:FindObjectForCode("@Native Forest/Coelamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Coelamon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("coelamon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Coelamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Coelamon/Prosperity Point").AvailableChestCount + 2
    end
end

function kokatorimon_recruit_vanilla()
    if Tracker:FindObjectForCode("kokatorimon").Active then
        Tracker:FindObjectForCode("@Misty Trees/Kokatorimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Misty Trees/Kokatorimon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("kokatorimon").Active == false then
        Tracker:FindObjectForCode("@Misty Trees/Kokatorimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Misty Trees/Kokatorimon/Prosperity Point").AvailableChestCount + 2
    end
end

function kuwagamon_recruit_vanilla()
    if Tracker:FindObjectForCode("kuwagamon").Active then
        Tracker:FindObjectForCode("@Beetle Land/Kuwagamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Beetle Land/Kuwagamon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("kuwagamon").Active == false then
        Tracker:FindObjectForCode("@Beetle Land/Kuwagamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Beetle Land/Kuwagamon/Prosperity Point").AvailableChestCount + 2
    end
end

function mojyamon_recruit_vanilla()
    if Tracker:FindObjectForCode("mojyamon").Active then
        Tracker:FindObjectForCode("@Freezeland/Mojyamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Mojyamon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("mojyamon").Active == false then
        Tracker:FindObjectForCode("@Freezeland/Mojyamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Mojyamon/Prosperity Point").AvailableChestCount + 2
    end
end

function nanimon_recruit_vanilla()
    if Tracker:FindObjectForCode("nanimon").Active then
        Tracker:FindObjectForCode("@Ancient Dino Region/Nanimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Ancient Dino Region/Nanimon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("nanimon").Active == false then
        Tracker:FindObjectForCode("@Ancient Dino Region/Nanimon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Ancient Dino Region/Nanimon/Prosperity Point").AvailableChestCount + 1
    end
end

function megadramon_recruit_vanilla()
    if Tracker:FindObjectForCode("megadramon").Active then
        Tracker:FindObjectForCode("@Mt. Infinity/Megadramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/Megadramon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("megadramon").Active == false then
        Tracker:FindObjectForCode("@Mt. Infinity/Megadramon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/Megadramon/Prosperity Point").AvailableChestCount + 3
    end
end

function piximon_recruit_vanilla()
    if Tracker:FindObjectForCode("piximon").Active then
        Tracker:FindObjectForCode("@Tropical Jungle/Piximon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Piximon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("piximon").Active == false then
        Tracker:FindObjectForCode("@Tropical Jungle/Piximon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Tropical Jungle/Piximon/Prosperity Point").AvailableChestCount + 3
    end
end

function digitamamon_recruit_vanilla()
    if Tracker:FindObjectForCode("digitamamon").Active then
        Tracker:FindObjectForCode("@Mt. Infinity/Digitamamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/Digitamamon/Prosperity Point").AvailableChestCount - 3
    elseif Tracker:FindObjectForCode("digitamamon").Active == false then
        Tracker:FindObjectForCode("@Mt. Infinity/Digitamamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Mt. Infinity/Digitamamon/Prosperity Point").AvailableChestCount + 3
    end
end

function penguinmon_recruit_vanilla()
    if Tracker:FindObjectForCode("penguinmon").Active then
        Tracker:FindObjectForCode("@Freezeland/Penguinmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Penguinmon/Prosperity Point").AvailableChestCount - 1
    elseif Tracker:FindObjectForCode("penguinmon").Active == false then
        Tracker:FindObjectForCode("@Freezeland/Penguinmon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Freezeland/Penguinmon/Prosperity Point").AvailableChestCount + 1
    end
end

function ninjamon_recruit_vanilla()
    if Tracker:FindObjectForCode("ninjamon").Active then
        Tracker:FindObjectForCode("@Native Forest/Ninjamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Ninjamon/Prosperity Point").AvailableChestCount - 2
    elseif Tracker:FindObjectForCode("ninjamon").Active == false then
        Tracker:FindObjectForCode("@Native Forest/Ninjamon/Prosperity Point").AvailableChestCount = Tracker:FindObjectForCode("@Native Forest/Ninjamon/Prosperity Point").AvailableChestCount + 2
    end
end

ScriptHost:AddWatchForCode("agumon_prosperity", "agumon", agumon_recruit)
ScriptHost:AddWatchForCode("betamon_prosperity", "betamon", betamon_recruit)
ScriptHost:AddWatchForCode("greymon_prosperity", "greymon", greymon_recruit)
ScriptHost:AddWatchForCode("devimon_prosperity", "devimon", devimon_recruit)
ScriptHost:AddWatchForCode("airdramon_prosperity", "airdramon", airdramon_recruit)
ScriptHost:AddWatchForCode("tyrannomon_prosperity", "tyrannomon", tyrannomon_recruit)
ScriptHost:AddWatchForCode("meramon_prosperity", "meramon", meramon_recruit)
ScriptHost:AddWatchForCode("seadramon_prosperity", "seadramon", seadramon_recruit)
ScriptHost:AddWatchForCode("numemon_prosperity", "numemon", numemon_recruit)
ScriptHost:AddWatchForCode("metalgreymon_prosperity", "metalgreymon", metalgreymon_recruit)
ScriptHost:AddWatchForCode("mamemon_prosperity", "mamemon", mamemon_recruit)
ScriptHost:AddWatchForCode("monzaemon_prosperity", "monzaemon", monzaemon_recruit)
ScriptHost:AddWatchForCode("gabumon_prosperity", "gabumon", gabumon_recruit)
ScriptHost:AddWatchForCode("elecmon_prosperity", "elecmon", elecmon_recruit)
ScriptHost:AddWatchForCode("kabuterimon_prosperity", "kabuterimon", kabuterimon_recruit)
ScriptHost:AddWatchForCode("angemon_prosperity", "angemon", angemon_recruit)
ScriptHost:AddWatchForCode("birdramon_prosperity", "birdramon", birdramon_recruit)
ScriptHost:AddWatchForCode("garurumon_prosperity", "garurumon", garurumon_recruit)
ScriptHost:AddWatchForCode("frigimon_prosperity", "frigimon", frigimon_recruit)
ScriptHost:AddWatchForCode("whamon_prosperity", "whamon", whamon_recruit)
ScriptHost:AddWatchForCode("vegiemon_prosperity", "vegiemon", vegiemon_recruit)
ScriptHost:AddWatchForCode("skullgreymon_prosperity", "skullgreymon", skullgreymon_recruit)
ScriptHost:AddWatchForCode("metalmamemon_prosperity", "metalmamemon", metalmamemon_recruit)
ScriptHost:AddWatchForCode("vademon_prosperity", "vademon", vademon_recruit)
ScriptHost:AddWatchForCode("patamon_prosperity", "patamon", patamon_recruit)
ScriptHost:AddWatchForCode("kunemon_prosperity", "kunemon", kunemon_recruit)
ScriptHost:AddWatchForCode("unimon_prosperity", "unimon", unimon_recruit)
ScriptHost:AddWatchForCode("ogremon_prosperity", "ogremon", ogremon_recruit)
ScriptHost:AddWatchForCode("shellmon_prosperity", "shellmon", shellmon_recruit)
ScriptHost:AddWatchForCode("centarumon_prosperity", "centarumon", centarumon_recruit)
ScriptHost:AddWatchForCode("bakemon_prosperity", "bakemon", bakemon_recruit)
ScriptHost:AddWatchForCode("drimogemon_prosperity", "drimogemon", drimogemon_recruit)
ScriptHost:AddWatchForCode("sukamon_prosperity", "sukamon", sukamon_recruit)
ScriptHost:AddWatchForCode("andromon_prosperity", "andromon", andromon_recruit)
ScriptHost:AddWatchForCode("giromon_prosperity", "giromon", giromon_recruit)
ScriptHost:AddWatchForCode("etemon_prosperity", "etemon", etemon_recruit)
ScriptHost:AddWatchForCode("biyomon_prosperity", "biyomon", biyomon_recruit)
ScriptHost:AddWatchForCode("palmon_prosperity", "palmon", palmon_recruit)
ScriptHost:AddWatchForCode("monochromon_prosperity", "monochromon", monochromon_recruit)
ScriptHost:AddWatchForCode("leomon_prosperity", "leomon", leomon_recruit)
ScriptHost:AddWatchForCode("coelamon_prosperity", "coelamon", coelamon_recruit)
ScriptHost:AddWatchForCode("kokatorimon_prosperity", "kokatorimon", kokatorimon_recruit)
ScriptHost:AddWatchForCode("kuwagamon_prosperity", "kuwagamon", kuwagamon_recruit)
ScriptHost:AddWatchForCode("mojyamon_prosperity", "mojyamon", mojyamon_recruit)
ScriptHost:AddWatchForCode("nanimon_prosperity", "nanimon", nanimon_recruit)
ScriptHost:AddWatchForCode("megadramon_prosperity", "megadramon", megadramon_recruit)
ScriptHost:AddWatchForCode("piximon_prosperity", "piximon", piximon_recruit)
ScriptHost:AddWatchForCode("digitamamon_prosperity", "digitamamon", digitamamon_recruit)
ScriptHost:AddWatchForCode("penguinmon_prosperity", "penguinmon", penguinmon_recruit)
ScriptHost:AddWatchForCode("ninjamon_prosperity", "ninjamon", ninjamon_recruit)

ScriptHost:AddWatchForCode("agumon_location", "agumon", agumon_recruit_vanilla)
ScriptHost:AddWatchForCode("betamon_location", "betamon", betamon_recruit_vanilla)
ScriptHost:AddWatchForCode("greymon_location", "greymon", greymon_recruit_vanilla)
ScriptHost:AddWatchForCode("devimon_location", "devimon", devimon_recruit_vanilla)
ScriptHost:AddWatchForCode("airdramon_location", "airdramon", airdramon_recruit_vanilla)
ScriptHost:AddWatchForCode("tyrannomon_location", "tyrannomon", tyrannomon_recruit_vanilla)
ScriptHost:AddWatchForCode("meramon_location", "meramon", meramon_recruit_vanilla)
ScriptHost:AddWatchForCode("seadramon_location", "seadramon", seadramon_recruit_vanilla)
ScriptHost:AddWatchForCode("numemon_location", "numemon", numemon_recruit_vanilla)
ScriptHost:AddWatchForCode("metalgreymon_location", "metalgreymon", metalgreymon_recruit_vanilla)
ScriptHost:AddWatchForCode("mamemon_location", "mamemon", mamemon_recruit_vanilla)
ScriptHost:AddWatchForCode("monzaemon_location", "monzaemon", monzaemon_recruit_vanilla)
ScriptHost:AddWatchForCode("gabumon_location", "gabumon", gabumon_recruit_vanilla)
ScriptHost:AddWatchForCode("elecmon_location", "elecmon", elecmon_recruit_vanilla)
ScriptHost:AddWatchForCode("kabuterimon_location", "kabuterimon", kabuterimon_recruit_vanilla)
ScriptHost:AddWatchForCode("angemon_location", "angemon", angemon_recruit_vanilla)
ScriptHost:AddWatchForCode("birdramon_location", "birdramon", birdramon_recruit_vanilla)
ScriptHost:AddWatchForCode("garurumon_location", "garurumon", garurumon_recruit_vanilla)
ScriptHost:AddWatchForCode("frigimon_location", "frigimon", frigimon_recruit_vanilla)
ScriptHost:AddWatchForCode("whamon_location", "whamon", whamon_recruit_vanilla)
ScriptHost:AddWatchForCode("vegiemon_location", "vegiemon", vegiemon_recruit_vanilla)
ScriptHost:AddWatchForCode("skullgreymon_location", "skullgreymon", skullgreymon_recruit_vanilla)
ScriptHost:AddWatchForCode("metalmamemon_location", "metalmamemon", metalmamemon_recruit_vanilla)
ScriptHost:AddWatchForCode("vademon_location", "vademon", vademon_recruit_vanilla)
ScriptHost:AddWatchForCode("patamon_location", "patamon", patamon_recruit_vanilla)
ScriptHost:AddWatchForCode("kunemon_location", "kunemon", kunemon_recruit_vanilla)
ScriptHost:AddWatchForCode("unimon_location", "unimon", unimon_recruit_vanilla)
ScriptHost:AddWatchForCode("ogremon_location", "ogremon", ogremon_recruit_vanilla)
ScriptHost:AddWatchForCode("shellmon_location", "shellmon", shellmon_recruit_vanilla)
ScriptHost:AddWatchForCode("centarumon_location", "centarumon", centarumon_recruit_vanilla)
ScriptHost:AddWatchForCode("bakemon_location", "bakemon", bakemon_recruit_vanilla)
ScriptHost:AddWatchForCode("drimogemon_location", "drimogemon", drimogemon_recruit_vanilla)
ScriptHost:AddWatchForCode("sukamon_location", "sukamon", sukamon_recruit_vanilla)
ScriptHost:AddWatchForCode("andromon_location", "andromon", andromon_recruit_vanilla)
ScriptHost:AddWatchForCode("giromon_location", "giromon", giromon_recruit_vanilla)
ScriptHost:AddWatchForCode("etemon_location", "etemon", etemon_recruit_vanilla)
ScriptHost:AddWatchForCode("biyomon_location", "biyomon", biyomon_recruit_vanilla)
ScriptHost:AddWatchForCode("palmon_location", "palmon", palmon_recruit_vanilla)
ScriptHost:AddWatchForCode("monochromon_location", "monochromon", monochromon_recruit_vanilla)
ScriptHost:AddWatchForCode("leomon_location", "leomon", leomon_recruit_vanilla)
ScriptHost:AddWatchForCode("coelamon_location", "coelamon", coelamon_recruit_vanilla)
ScriptHost:AddWatchForCode("kokatorimon_location", "kokatorimon", kokatorimon_recruit_vanilla)
ScriptHost:AddWatchForCode("kuwagamon_location", "kuwagamon", kuwagamon_recruit_vanilla)
ScriptHost:AddWatchForCode("mojyamon_location", "mojyamon", mojyamon_recruit_vanilla)
ScriptHost:AddWatchForCode("nanimon_location", "nanimon", nanimon_recruit_vanilla)
ScriptHost:AddWatchForCode("megadramon_location", "megadramon", megadramon_recruit_vanilla)
ScriptHost:AddWatchForCode("piximon_location", "piximon", piximon_recruit_vanilla)
ScriptHost:AddWatchForCode("digitamamon_location", "digitamamon", digitamamon_recruit_vanilla)
ScriptHost:AddWatchForCode("penguinmon_location", "penguinmon", penguinmon_recruit_vanilla)
ScriptHost:AddWatchForCode("ninjamon_location", "ninjamon", ninjamon_recruit_vanilla)