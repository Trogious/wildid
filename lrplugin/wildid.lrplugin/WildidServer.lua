--[[
HTTP client for the wildid daemon: discovery via serve.json, bearer-token auth, JSON bodies.
All calls block the current LrTask; callers run inside LrTasks.startAsyncTask.
]]

local LrHttp = import 'LrHttp'
local LrTasks = import 'LrTasks'

local JSON = require 'JSON'
local Paths = require 'WildidPaths'

local M = {}

M.PROTOCOL = 1
local CLASSIFY_TIMEOUT_S = 600 -- a CPU-only chunk with a cold detector can take minutes
local PREFETCH_TIMEOUT_S = 1800 -- a whole continent pages at 1 request/s
local WARMUP_TIMEOUT_S = 600 -- a cold ViT-H load on a slow disk
local READY_WAIT_S = 300 -- model load incl. first torch import

local function baseUrl(entry)
    return 'http://127.0.0.1:' .. entry.port
end

local function authHeaders(entry)
    return { { field = 'Authorization', value = 'Bearer ' .. entry.token } }
end

local function parse(body, headers)
    if body == nil then
        local reason = headers and headers.error and headers.error.name or 'connection failed'
        return nil, 'no response from the WildID server (' .. tostring(reason) .. ')'
    end
    local data, err = JSON.decode(body)
    if data == nil and err then
        return nil, 'bad response from the WildID server: ' .. err
    end
    local status = headers and headers.status or 0
    if status ~= 200 then
        local message = (type(data) == 'table' and data.error) or ('HTTP ' .. tostring(status))
        return nil, message, status
    end
    return data
end

--- GET /health. Returns the health table, or nil + why.
function M.health()
    local entry, err = Paths.readServeJson()
    if not entry then return nil, err end
    local body, headers = LrHttp.get(baseUrl(entry) .. '/health', authHeaders(entry), 10)
    return parse(body, headers)
end

local function post(path, payload, timeout)
    local entry, err = Paths.readServeJson()
    if not entry then return nil, err end
    local headers = authHeaders(entry)
    headers[#headers + 1] = { field = 'Content-Type', value = 'application/json' }
    local body, respHeaders =
        LrHttp.post(baseUrl(entry) .. path, JSON.encode(payload), headers, 'POST', timeout)
    return parse(body, respHeaders)
end

--- POST /classify. paths: array of file path strings; opts: model, k, geo, crop, crop_exact,
--- second_opinion, min_score, keyword_root, detector; gps: optional path -> {lat, lon} map
--- (catalog positions for geo.auto runs). Returns the run document, or nil + error.
function M.classify(paths, opts, gps)
    local payload = {
        paths = JSON.array(paths),
        model = opts.model,
        k = opts.k,
        geo = opts.geo,
        gps = gps,
        crop = opts.crop,
        crop_exact = opts.crop_exact,
        second_opinion = opts.second_opinion,
        detector = opts.detector,
        min_score = opts.min_score,
        keyword_root = opts.keyword_root,
    }
    return post('/classify', payload, CLASSIFY_TIMEOUT_S)
end

--- POST /warmup: load a model now (blocks until loaded; no-op when already loaded).
function M.warmup(model)
    return post('/warmup', { model = model }, WARMUP_TIMEOUT_S)
end

--- POST /prefetch (the one online call): fetch geo species lists for a place, or for the
--- places of GPS positions (geo.gps = array of {lat, lon}, geo.level = country | region).
function M.prefetchPlace(geo, refresh)
    local payload = {
        continent = geo.continent,
        country = geo.country,
        region = geo.region,
        place_id = geo.place_id,
        gps = geo.gps,
        level = geo.level,
        taxa = geo.taxa,
        refresh = refresh and true or false,
    }
    return post('/prefetch', payload, PREFETCH_TIMEOUT_S)
end

function M.shutdown()
    return post('/shutdown', {}, 15)
end

--- Start the server (detached) when it is not running, then wait until the model is ready.
--- checkCanceled: optional function returning true to abort the wait.
--- Returns true, or false + a user-facing message.
function M.ensureReady(checkCanceled)
    local health = M.health()
    if health and health.ready then return true end
    if health and health.error then
        return false, 'WildID server: ' .. health.error
    end
    if not health then
        local cmd, cmdErr = Paths.serverStartCommand()
        if not cmd then return false, cmdErr end
        LrTasks.execute(cmd)
    end
    local waited = 0
    while waited < READY_WAIT_S do
        LrTasks.sleep(2)
        waited = waited + 2
        if checkCanceled and checkCanceled() then return false, 'canceled' end
        health = M.health()
        if health and health.ready then return true end
        if health and health.error then
            return false, 'WildID server: ' .. health.error
        end
    end
    return false, 'the WildID server did not become ready within ' .. READY_WAIT_S .. ' s'
end

--- Protocol guard: the plugin only talks to servers speaking its protocol.
function M.checkProtocol(health)
    if health and health.protocol and health.protocol ~= M.PROTOCOL then
        return false,
            'WildID server speaks protocol ' .. tostring(health.protocol) .. ' but the plugin '
                .. 'expects ' .. M.PROTOCOL .. '. Update the WildID app and the plugin together.'
    end
    return true
end

return M
