-- Test harness for the plugin's JSON.lua under real Lua 5.1.
package.path = arg[1] .. '/?.lua;' .. package.path
local JSON = require('JSON')

local failures = 0
local function check(cond, msg)
    if not cond then
        failures = failures + 1
        print('FAIL: ' .. msg)
    end
end

-- decode: realistic server document (ensure_ascii=False UTF-8 + \u escapes mixed)
local doc = [[
{
  "wildid": "0.2.0", "protocol": 1, "model": "bioclip-2", "precision": null,
  "candidates": {"count": 412, "place_label": "Brazil \u203a Mato Grosso", "taxa": ["Mammalia"], "rank": "species"},
  "results": [
    {"path": "C:\\photos\\DSC04512.ARW", "ok": true, "error": null,
     "predictions": [{"species": "Panthera onca", "common_name": "Jaguár", "score": 0.962}],
     "unconstrained": {"species": "Panthera onca", "score": 0.871, "in_candidates": true},
     "review": false,
     "suggested_keywords": [{"path": ["WildID", "Mammalia", "Felidae", "Panthera onca"], "synonyms": ["Jaguár"]}]},
    {"path": "C:\\photos\\bad.ARW", "ok": false, "error": "boom", "review": true}
  ]
}
]]
local t, err = JSON.decode(doc)
check(t ~= nil, 'decode server doc: ' .. tostring(err))
check(t.protocol == 1, 'protocol int')
check(t.precision == nil, 'null -> nil')
check(t.candidates.place_label == 'Brazil \226\128\186 Mato Grosso', 'unicode escape to UTF-8')
check(t.results[1].path == 'C:\\photos\\DSC04512.ARW', 'windows path backslashes')
check(t.results[1].predictions[1].score == 0.962, 'float score')
check(t.results[1].predictions[1].common_name == 'Jagu\195\161r', 'raw UTF-8 passthrough')
check(t.results[1].unconstrained.in_candidates == true, 'nested true')
check(t.results[2].ok == false, 'false value')
check(#t.results == 2, 'array length')
check(t.results[1].suggested_keywords[1].path[4] == 'Panthera onca', 'deep array')

-- surrogate pair (emoji) and escapes
local s = JSON.decode('"a\\ud83d\\ude00b\\n\\t\\"\\\\"')
check(s == 'a\240\159\152\128b\n\t"\\', 'surrogate pair + escapes')

-- numbers
check(JSON.decode('-12.5e2') == -1250, 'scientific notation')
check(JSON.decode('0.5') == 0.5, 'leading zero float')
check(JSON.decode('[1,2,3]')[3] == 3, 'int array')

-- encode and round-trip the request shape
local req = {
    paths = JSON.array({ 'C:\\x\\a.ARW', '/mac/β.nef' }),
    k = 3, min_score = 0.5, crop = true,
    geo = { country = 'Brazil', region = 'Mato Grosso', rank = 'species' },
}
local encoded = JSON.encode(req)
local back = JSON.decode(encoded)
check(back.paths[1] == 'C:\\x\\a.ARW' and back.paths[2] == '/mac/β.nef', 'round-trip paths')
check(back.k == 3 and back.min_score == 0.5 and back.crop == true, 'round-trip scalars')
check(back.geo.region == 'Mato Grosso', 'round-trip nested object')
check(JSON.encode(JSON.array({})) == '[]', 'empty array marker')
check(JSON.encode({}) == '{}', 'empty object')
check(JSON.encode('a"b\\c\n') == '"a\\"b\\\\c\\n"', 'string escaping')
check(JSON.encode(1e15 + 0.5):find('e') ~= nil or tonumber(JSON.encode(1e15 + 0.5)), 'big number encodes')

-- control character escaping in encode
check(JSON.encode(string.char(7)) == '"\\u0007"', 'control char escaped')

-- errors
local bad, e1 = JSON.decode('{nope')
check(bad == nil and e1 ~= nil, 'broken json reports error')
local trail, e2 = JSON.decode('{} trailing')
check(trail == nil and e2:find('trailing'), 'trailing data reported')
local nostr, e3 = JSON.decode(nil)
check(nostr == nil, 'nil input')

-- deep nesting guard on encode
local deep = {}
local cur = deep
for i = 1, 40 do cur.n = {}; cur = cur.n end
local ok = pcall(JSON.encode, deep)
check(ok == false, 'encode depth guard')

if failures == 0 then
    print('ALL JSON TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
