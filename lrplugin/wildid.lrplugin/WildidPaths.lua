--[[
Where things live: the wildid cache dir (serve.json discovery) and the engine manifest.

The installer drops an optional `engine.json` next to this file:
  { "start": "<command that starts the server detached>",
    "cli":   "<path of the wildid launcher>",
    "cacheDir": "<wildid cache dir>" }
Everything has a sensible per-OS default so a hand-installed plugin still works; the plugin
preferences can override each value.
]]

local LrFileUtils = import 'LrFileUtils'
local LrPathUtils = import 'LrPathUtils'
local LrPrefs = import 'LrPrefs'

local JSON = require 'JSON'

local M = {}

local function getenv(name)
    local ok, value = pcall(os.getenv, name)
    if ok then return value end
    return nil
end

function M.engineManifest()
    local path = LrPathUtils.child(_PLUGIN.path, 'engine.json')
    if LrFileUtils.exists(path) then
        local fd = io.open(path, 'r')
        if fd then
            local text = fd:read('*a')
            fd:close()
            local data = JSON.decode(text)
            if type(data) == 'table' then return data end
        end
    end
    return {}
end

--- wildid's cache directory (platformdirs user_cache_dir("wildid", appauthor=False)).
function M.cacheDir()
    local prefs = LrPrefs.prefsForPlugin()
    if prefs.cacheDir and prefs.cacheDir ~= '' then return prefs.cacheDir end
    local manifest = M.engineManifest()
    if manifest.cacheDir and manifest.cacheDir ~= '' then return manifest.cacheDir end
    if WIN_ENV then
        local base = getenv('LOCALAPPDATA')
        if base then return base .. '\\wildid\\Cache' end
        return nil
    end
    local home = getenv('HOME')
    if home then return home .. '/Library/Caches/wildid' end
    return nil
end

function M.serveJsonPath()
    local dir = M.cacheDir()
    if not dir then return nil end
    return LrPathUtils.child(dir, 'serve.json')
end

--- The daemon's discovery record {port, token, protocol, ...}, or nil + reason.
function M.readServeJson()
    local path = M.serveJsonPath()
    if not path then
        return nil, 'could not determine the wildid cache directory (set it in the plugin settings)'
    end
    if not LrFileUtils.exists(path) then
        return nil, 'serve.json not found (' .. path .. '); the WildID server is not running'
    end
    local fd = io.open(path, 'r')
    if not fd then return nil, 'serve.json is not readable: ' .. path end
    local text = fd:read('*a')
    fd:close()
    local data, err = JSON.decode(text)
    if type(data) ~= 'table' or type(data.port) ~= 'number' or type(data.token) ~= 'string' then
        return nil, 'serve.json is not valid: ' .. tostring(err)
    end
    return data
end

--- The command that starts the server, detached, or nil + help text.
function M.serverStartCommand()
    local prefs = LrPrefs.prefsForPlugin()
    local cmd = prefs.serverStartCommand
    if not cmd or cmd == '' then
        cmd = M.engineManifest().start
    end
    if not cmd or cmd == '' then
        return nil,
            'No server start command is configured. Start it yourself with `wildid serve`, '
                .. 'or set the command in the WildID plugin settings / engine.json.'
    end
    if WIN_ENV then
        -- cmd.exe via LrTasks.execute: `start` detaches; the empty "" is start's window title.
        -- A batch file handed to `start` directly runs under `cmd /K` and its console stays open
        -- after the launcher exits (seen on LrC 15.4.1): go through `cmd /c` so the window
        -- closes as soon as the server has been spawned.
        return 'start "" cmd /c "' .. cmd .. '"'
    end
    return '"' .. cmd .. '" > /dev/null 2>&1 &'
end

return M
