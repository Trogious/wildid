-- Integration test: the plugin's real WildidPaths/WildidServer modules against the real
-- wildid daemon (stub classifier), with curl standing in for LrHttp and minimal Lr* stubs.
-- usage: lua5.1 lr_stub_test.lua <plugin_dir> <cache_dir> <test_image>

local pluginDir, cacheDir, testImage = arg[1], arg[2], arg[3]
package.path = pluginDir .. '/?.lua;' .. package.path

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

-- ---------------------------------------------------------------- Lr* stubs
local function shellquote(s) return "'" .. s:gsub("'", "'\\''") .. "'" end

local function curl(method, url, headers, body, timeout)
    local parts = { 'curl -s -w "\\n%{http_code}" --max-time ' .. (timeout or 30) }
    parts[#parts + 1] = '-X ' .. method
    for _, h in ipairs(headers or {}) do
        parts[#parts + 1] = '-H ' .. shellquote(h.field .. ': ' .. h.value)
    end
    if body then parts[#parts + 1] = '--data-binary ' .. shellquote(body) end
    parts[#parts + 1] = shellquote(url)
    local fd = io.popen(table.concat(parts, ' '), 'r')
    local out = fd:read('*a')
    fd:close()
    local payload, status = out:match('^(.*)\n(%d+)%s*$')
    if not status then return nil, { error = { name = 'connection refused' } } end
    return payload, { status = tonumber(status) }
end

local executed = {}
local stubs = {
    LrHttp = {
        get = function(url, headers, timeout) return curl('GET', url, headers, nil, timeout) end,
        post = function(url, body, headers, method, timeout)
            return curl(method or 'POST', url, headers, body, timeout)
        end,
    },
    LrFileUtils = {
        exists = function(p)
            local fd = io.open(p, 'r')
            if fd then fd:close(); return 'file' end
            return false
        end,
    },
    LrPathUtils = { child = function(dir, name) return dir .. '/' .. name end },
    LrPrefs = { prefsForPlugin = function() return {} end },
    LrTasks = {
        sleep = function(s) os.execute('sleep ' .. s) end,
        execute = function(cmd) executed[#executed + 1] = cmd; return 0 end,
    },
}
function import(name) -- luacheck: ignore
    return assert(stubs[name], 'no stub for ' .. name)
end
WIN_ENV = false
_PLUGIN = { path = pluginDir }

-- Point the plugin at our test cache dir (no engine.json: override via prefs stub)
stubs.LrPrefs.prefsForPlugin = function()
    return { cacheDir = cacheDir }
end

-- ---------------------------------------------------------------- the real modules
local Paths = require 'WildidPaths'
local Server = require 'WildidServer'

local entry, err = Paths.readServeJson()
check(entry ~= nil, 'serve.json readable: ' .. tostring(err))
check(type(entry.port) == 'number' and type(entry.token) == 'string', 'discovery fields')

local health, herr = Server.health()
check(health ~= nil, 'health: ' .. tostring(herr))
check(health.ready == true and health.protocol == 1, 'health ready + protocol')
check(Server.checkProtocol(health) == true, 'protocol check passes')

local ok = Server.ensureReady(nil)
check(ok == true, 'ensureReady on a running server')

-- classify one real file through the daemon
local doc, cerr = Server.classify({ testImage }, { k = 2, keyword_root = 'WildID' })
check(doc ~= nil, 'classify: ' .. tostring(cerr))
if doc then
    check(doc.model == 'fake', 'doc model')
    local res = doc.results[1]
    check(res.ok == true, 'result ok')
    check(res.path == testImage, 'path echoed verbatim')
    check(#res.predictions == 2, 'k respected')
    local kw = res.suggested_keywords[1]
    check(table.concat(kw.path, '|') == 'WildID|Ursidae|Ursus arctos', 'keyword path')
    check(kw.synonyms[1] == 'Brown bear', 'keyword synonym')
    check(res.review == false, 'review flag')
end

-- classify a missing file: a per-file error, not a transport error
local doc2 = Server.classify({ '/nope/missing.jpg' }, {})
check(doc2 ~= nil and doc2.results[1].ok == false, 'missing file is a per-file error')

-- a validation error surfaces the server's message
local bad, berr = Server.prefetchPlace({}, false)
check(bad == nil and tostring(berr):find('place'), 'prefetch validation message: ' .. tostring(berr))

-- wrong token -> clean error
stubs.LrPrefs.prefsForPlugin = function()
    return { cacheDir = cacheDir .. '-nowhere' }
end
local noServer, nserr = Server.health()
check(noServer == nil and nserr ~= nil, 'missing serve.json reports a reason')
stubs.LrPrefs.prefsForPlugin = function() return { cacheDir = cacheDir } end

-- B4: model status, warmup and per-request model selection
check(health.models and health.models.fake and health.models.fake.loaded == true,
    'health lists the loaded model')
check(type(health.vram) == 'table' and health.vram.total_gb == 25.8, 'health carries the VRAM probe')
local warm, werr2 = Server.warmup('fake')
check(warm ~= nil and warm.already_loaded == true,
    'warmup of a loaded model is a no-op: ' .. tostring(werr2))
local badWarm, bwerr = Server.warmup('bioclip-9')
check(badWarm == nil and tostring(bwerr):find('unknown model', 1, true) ~= nil,
    'warmup rejects unknown models')
local docM = Server.classify({ testImage }, { k = 1, model = 'fake' })
check(docM ~= nil and docM.model == 'fake', 'classify with an explicit model')

-- shutdown through the client
local down = Server.shutdown()
check(down ~= nil and down.ok == true, 'shutdown')

if failures == 0 then
    print('ALL LUA<->DAEMON INTEGRATION TESTS PASSED')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
