-- Smoke test: boot DW1, wait ~25s of emulated time, dump the 2MB of main RAM plus an
-- (uncompressed) savestate into the working directory, then quit the emulator.
--
-- Launch:  powershell -File dw1_redux_launch.ps1 -Script worlds\digimon_world\tools\dw1_redux_smoke.lua
-- Outputs (in work\dw1_re):  redux_smoke_ram.bin, redux_smoke.state
-- Validate the dump afterwards with:  python dw1_redux_api.py check-dump work\dw1_re\redux_smoke_ram.bin
--
-- Doubles as the first-run initializer: quitting persists the settings the bootstrap
-- enabled (web server, debugger) into the portable pcsx.json.

local DUMP_AT_VSYNC = 1500  -- ~25s NTSC: enough for fastboot + intro to load the SLUS into RAM

local vsyncs = 0
_G.dw1_smoke_listener = PCSX.Events.createEventListener("GPU::Vsync", function()
    vsyncs = vsyncs + 1
    if vsyncs ~= DUMP_AT_VSYNC then return end
    PCSX.nextTick(function()
        local ok, err = pcall(function()
            local ram = PCSX.getMemoryAsFile():readAt(2 * 1024 * 1024, 0x80000000)
            local out = Support.File.open("redux_smoke_ram.bin", "TRUNCATE")
            out:write(ram)
            out:close()
            local state = PCSX.createSaveState()
            local sf = Support.File.open("redux_smoke.state", "TRUNCATE")
            sf:writeMoveSlice(state)
            sf:close()
            print("DW1_SMOKE: wrote redux_smoke_ram.bin + redux_smoke.state")
        end)
        if not ok then print("DW1_SMOKE ERROR: " .. tostring(err)) end
        PCSX.quit()
    end)
end)

print("DW1_SMOKE: armed, dumping at vsync " .. DUMP_AT_VSYNC)
