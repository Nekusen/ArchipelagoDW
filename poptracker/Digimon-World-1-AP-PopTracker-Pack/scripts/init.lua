-- Digimon World 1 (ArchipelagoDW) PopTracker pack — v0.2
-- World map + AP locations with logic + progression items panel.
-- Autotracking is not wired up yet.

ScriptHost:LoadScript("scripts/logic.lua")

Tracker:AddItems("items/items.json")
Tracker:AddMaps("maps/maps.json")
Tracker:AddLocations("locations/locations.json")
Tracker:AddLayouts("layouts/items.json")
Tracker:AddLayouts("layouts/tracker.json")
