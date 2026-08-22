-- Scripted input helpers for PCSX-Redux sessions. Load standalone (-Script) or install live:
--   python dw1_redux_api.py lua "Support.extra.dofile('c:/opt/dev/AP/ArchipelagoDW/worlds/digimon_world/tools/dw1_redux_input.lua')"
--
-- Provides:
--   dw1_press({'RIGHT','CROSS',...}, gap)  -- queue timed button taps (default 25 frames apart)
--   dw1_masher('x')                        -- gentle CROSS tap every 50 frames (advances dialogs)
--   dw1_masher('title')                    -- START/CROSS alternating (gets past the title screen)
--   dw1_masher(nil)                        -- stop the masher
--
-- Drive blind screens with eyes: pair with `python dw1_redux_screenshot.py` to see the result
-- of each press. Known blind-mash blockers: the two name-entry screens in the intro (cursor
-- starts on OK with an empty name; type a letter first: RIGHT, CROSS, then LEFT, DOWN, CROSS).

-- Resolve the pad on EVERY use, never once at load time. `PCSX.loadSaveState()` replaces the
-- pad object, and a cached reference silently no-ops afterwards: `setOverride` appears to work,
-- returns no error, and the game just never sees the button. That failure mode reads exactly
-- like "the game ignored the input" and has cost more than one confused capture session.
local function pad()
    return PCSX.SIO0.slots[1].pads[1]
end
local B = PCSX.CONSTS.PAD.BUTTON

if _G.dw1_seq and _G.dw1_seq.listener then _G.dw1_seq.listener:remove() end
_G.dw1_seq = { queue = {}, frame = 0 }
_G.dw1_seq.listener = PCSX.Events.createEventListener("GPU::Vsync", function()
    local s = _G.dw1_seq
    s.frame = s.frame + 1
    local q = s.queue[1]
    if not q then return end
    if s.frame >= q.at and not q.pressed then
        pad().setOverride(B[q.btn])
        q.pressed = true
    end
    if s.frame >= q.at + (q.hold or 8) and q.pressed then
        pad().clearOverride(B[q.btn])
        table.remove(s.queue, 1)
    end
end)

function _G.dw1_press(list, gap)
    local s = _G.dw1_seq
    s.frame = 0
    s.queue = {}
    local at = 10
    for _, b in ipairs(list) do
        s.queue[#s.queue + 1] = { btn = b, at = at }
        at = at + (gap or 25)
    end
    return "queued " .. #list
end

function _G.dw1_masher(mode)
    if _G.dw1_masher_listener then
        _G.dw1_masher_listener:remove()
        _G.dw1_masher_listener = nil
    end
    for _, b in pairs(B) do pad().clearOverride(b) end
    if not mode then return "masher off" end
    local f = 0
    _G.dw1_masher_listener = PCSX.Events.createEventListener("GPU::Vsync", function()
        f = f + 1
        if mode == "x" then
            local ph = f % 50
            if ph == 0 then pad().setOverride(B.CROSS) elseif ph == 10 then pad().clearOverride(B.CROSS) end
        else -- 'title'
            local ph = f % 120
            if ph == 0 then pad().setOverride(B.START)
            elseif ph == 20 then pad().clearOverride(B.START)
            elseif ph == 60 then pad().setOverride(B.CROSS)
            elseif ph == 80 then pad().clearOverride(B.CROSS)
            end
        end
    end)
    return "masher " .. mode
end

print("DW1_INPUT: dw1_press / dw1_masher ready")
