--[[
Library menu: "WildID: server status…" — shows what the daemon is doing and offers to
start or stop it.
]]

local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrTasks = import 'LrTasks'

local Paths = require 'WildidPaths'
local Server = require 'WildidServer'

local function describe(health)
    local lines = {
        'Running on 127.0.0.1 (see serve.json).',
        'Default model: ' .. tostring(health.model) .. ' on ' .. tostring(health.device),
        'Ready: ' .. tostring(health.ready) .. ', protocol ' .. tostring(health.protocol)
            .. ', wildid ' .. tostring(health.wildid),
        'Uptime: ' .. tostring(health.uptime_s) .. ' s',
    }
    if type(health.models) == 'table' then
        local names = {}
        for name in pairs(health.models) do names[#names + 1] = name end
        table.sort(names)
        for _, name in ipairs(names) do
            local info = health.models[name]
            local state = info.loaded and 'loaded' or 'not loaded'
            if info.error then state = state .. ' (' .. info.error .. ')' end
            lines[#lines + 1] = '  ' .. name .. ': ' .. state
        end
    end
    if type(health.vram) == 'table' then
        lines[#lines + 1] = string.format('GPU: %s, %s GB total, %s GB free',
            tostring(health.vram.device_name), tostring(health.vram.total_gb),
            tostring(health.vram.free_gb))
    else
        lines[#lines + 1] = 'GPU: not detected (CPU, or probe failed)'
    end
    if health.error then lines[#lines + 1] = 'Error: ' .. health.error end
    return table.concat(lines, '\n')
end

local function run()
    local health = Server.health()
    if health then
        local verdict = LrDialogs.confirm('WildID server', describe(health), 'Stop server', 'Close')
        if verdict == 'ok' then
            Server.shutdown()
            LrDialogs.message('WildID', 'Server stopped. It restarts on the next identify run.',
                'info')
        end
        return
    end
    local startCmd, cmdErr = Paths.serverStartCommand()
    local message = 'The WildID server is not running.'
    if not startCmd then
        LrDialogs.message('WildID server', message .. '\n\n' .. cmdErr, 'warning')
        return
    end
    local verdict = LrDialogs.confirm('WildID server', message, 'Start server', 'Close')
    if verdict == 'ok' then
        local ok, err = Server.ensureReady(nil)
        if ok then
            LrDialogs.message('WildID', 'Server is running and the model is ready.', 'info')
        else
            LrDialogs.showError(err)
        end
    end
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext('wildidServerMenu', function() run() end)
end)
