-- Session bootstrap for scripted RE in PCSX-Redux. Loaded on every launch by dw1_redux_launch.ps1.
--
-- The web server itself is enabled by the launcher pre-seeding pcsx.json (portable settings in
-- work\dw1_re) -- it binds during startup's SettingsLoaded pass, before this script runs.
-- Here we register the remote-control HTTP handlers under /api/v1/lua/:
--
--   GET /api/v1/lua/ping                          -> liveness check
--   GET /api/v1/lua/quit                          -> clean emulator shutdown
--   GET /api/v1/lua/eval?code=<urlencoded lua>    -> run a short Lua snippet, return the result
--   GET /api/v1/lua/run?file=<name.lua>           -> dofile() from the CWD (work\dw1_re)
--
-- These are the escape hatch that lets Python (dw1_redux_api.py) arm watchpoints, poke settings,
-- take savestates, etc. without pre-planning a Lua script for each session. The code travels in
-- the query string because redux's web server exposes neither the POST body nor usable form
-- fields to Lua handlers (request.form carries the multipart part *headers*, the part data goes
-- to an unexposed body buffer -- verified against src/core/web-server.cc 2026-08-19). Requests
-- whose URL exceeds ~256 bytes are rejected by redux's HTTP parser, so anything beyond a
-- one-liner goes through `run`: the client drops the code into a file in the shared CWD and
-- asks for it by name (dw1_redux_api.py does this automatically).

PCSX.WebServer = PCSX.WebServer or {}
PCSX.WebServer.Handlers = PCSX.WebServer.Handlers or {}

PCSX.WebServer.Handlers.ping = function()
    return "pong\n"
end

PCSX.WebServer.Handlers.quit = function()
    PCSX.nextTick(function() PCSX.quit() end)
    return "quitting\n"
end

local function urldecode(s)
    s = s:gsub("%+", " ")
    return (s:gsub("%%(%x%x)", function(h) return string.char(tonumber(h, 16)) end))
end

local function badRequest(msg)
    return "HTTP/1.1 400 Bad Request\r\nContent-Type: text/plain\r\n\r\n" .. msg .. "\n"
end

local function runChunk(chunk, err)
    if not chunk then return badRequest("compile error: " .. tostring(err)) end
    local ok, res = pcall(chunk)
    if not ok then
        return "HTTP/1.1 500 Internal Server Error\r\nContent-Type: text/plain\r\n\r\nruntime error: " ..
            tostring(res) .. "\n"
    end
    return tostring(res) .. "\n"
end

local function queryParam(req, name)
    local query = (req.urlData and req.urlData.query) or ""
    local encoded = query:match("^" .. name .. "=([^&]*)") or query:match("&" .. name .. "=([^&]*)")
    return encoded and urldecode(encoded) or nil
end

PCSX.WebServer.Handlers.eval = function(req)
    local code = queryParam(req, "code")
    if not code then return badRequest("missing query parameter 'code'") end
    return runChunk(loadstring(code))
end

PCSX.WebServer.Handlers.run = function(req)
    local file = queryParam(req, "file") or "dw1_eval_payload.lua"
    if file:match("%.%.") then return badRequest("path traversal not allowed") end
    return runChunk(loadfile(file))
end

print("DW1_BOOTSTRAP: /api/v1/lua/{ping,quit,eval} handlers registered")
