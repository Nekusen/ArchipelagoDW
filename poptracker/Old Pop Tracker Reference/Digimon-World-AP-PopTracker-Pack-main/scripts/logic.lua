function has(item, amount)
    local count = Tracker:ProviderCountForCode(item)
    amount = tonumber(amount)
    if not amount then
      return count > 0
    else
      return count == amount
    end
end

function has_pp(item, amount)
    local count = Tracker:ProviderCountForCode(item)
    amount = tonumber(amount)
    if amount < count then
      return count > 0
    else
      return count == amount
    end
end

function checkRequirements(reference, check_count)
    local reqCount = Tracker:ProviderCountForCode(reference)
    local count = Tracker:ProviderCountForCode(check_count)
  
    if count >= reqCount then
        return true
    else
        return false
    end
end

function panorama()
    return has("meramon") or has_pp("prosperity_counter", 6)
end

function savanna()
    return has("meramon") or has_pp("prosperity_counter", 6)
end

function swamp()
    return has("meramon") or has_pp("prosperity_counter", 6)
end

function misty()
    return has("meramon") or has_pp("prosperity_counter", 6)
end

function toy()
    return has("meramon") and has_pp("prosperity_counter", 6)
end

function beetle()
    return has("seadramon") and (has("meramon") or has_pp("prosperity_counter", 6))
end

function factorial()
    return has("whamon") and has_pp("prosperity_counter", 6)
end

function infinity()
    return has("airdramon") and has_pp("prosperity_counter", 50)
end

------------------------------------------

function item_shop()
    return has("biyomon") or has("monochromon") or has("patamon") or has("unimon")
end

function restaurant()
    return  has("frigimon") or has("garurumon") or has("meramon") or has("tyrannomon") or has("digitamamon")
end

function secret_item_shop()
    return has("devimon") or has("mamemon") or has("numemon") or has("mojyamon")
end

function ogre_reqs()
    return has_pp("prosperity_counter", 6) and has("whamon")
end

function nani_reqs()
    return has_pp("prosperity_counter", 45) and has("leomon") and has("tyrannomon") and has("numemon") and has("meramon")
end
