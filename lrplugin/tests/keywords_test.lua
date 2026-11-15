-- WildidKeywords.lua: which keywords under the root a re-run takes off a photo.
-- usage: lua5.1 keywords_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
_PLUGIN = { path = arg[1] }
local K = require 'WildidKeywords'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

-- ---------------------------------------------------------------- fakes
local function keyword(name, parent)
    return { getName = function() return name end, getParent = function() return parent end }
end
local function photo(keywords)
    return { getRawMetadata = function(_, key) if key == 'keywords' then return keywords end end }
end

local root = keyword('WildID')
local mammalia = keyword('Mammalia', root)
local felidae = keyword('Felidae', mammalia)
local panthera = keyword('Panthera', mammalia)
local oldJaguar = keyword('Panthera onca', felidae) -- the family-level hierarchy of earlier runs
local newJaguar = keyword('Panthera onca', panthera)
local review = keyword('review', root)
local animals = keyword('animals')
local other = keyword('Panthera onca', keyword('Felidae', keyword('Mammalia', keyword('Fauna'))))

-- ---------------------------------------------------------------- pathOf / key
check(table.concat(K.pathOf(oldJaguar), '|') == 'WildID|Mammalia|Felidae|Panthera onca', 'pathOf, root first')
check(K.key(K.pathOf(newJaguar)) == 'wildid|mammalia|panthera|panthera onca', 'key is lower-cased')
check(#K.pathOf(animals) == 1, 'a flat tag has a one-name path')
local a = keyword('a')
local b = keyword('b', a)
a.getParent = function() return b end
check(#K.pathOf(b) == 64, 'a getParent cycle never hangs')

-- ---------------------------------------------------------------- keepSet
local suggested = {
    { path = { 'WildID', 'Mammalia', 'Panthera', 'Panthera onca' }, synonyms = { 'Jaguar' } },
    { path = { 'animals' }, synonyms = {} },
    { path = {}, synonyms = {} },
}
local keep = K.keepSet(suggested)
check(keep['wildid|mammalia|panthera|panthera onca'] and keep['animals'], 'keep holds the suggested paths')
check(next(K.keepSet(nil)) == nil, 'no suggestions -> empty keep')

-- ---------------------------------------------------------------- stale
local p = photo({ oldJaguar, newJaguar, review, animals, other, root })
local function keysOf(list)
    local names = {}
    for _, kw in ipairs(list) do names[#names + 1] = K.key(K.pathOf(kw)) end
    return table.concat(names, ';')
end
check(keysOf(K.stale(p, 'WildID', keep)) == 'wildid|mammalia|felidae|panthera onca;wildid|review;wildid',
    'the old hierarchy, a stale review and the bare root come off; the new keyword, flat tags '
    .. 'and other roots stay: ' .. keysOf(K.stale(p, 'WildID', keep)))
check(#K.stale(p, 'Fauna', keep) == 1 and K.stale(p, 'Fauna', keep)[1] == other, 'the root picks the namespace')
check(#K.stale(p, '', keep) == 3 and #K.stale(p, nil, keep) == 3, 'an empty root means WildID')
check(#K.stale(photo({ keyword('Review', keyword('wildid')) }), 'WildID', {}) == 1,
    'names match case-insensitively')
check(#K.stale(photo({ newJaguar, review }), 'WildID', K.keepSet({ suggested[1],
    { path = { 'WildID', 'review' }, synonyms = {} } })) == 0, 'a still-flagged photo keeps its review keyword')
check(#K.stale({ getRawMetadata = function() error('boom') end }, 'WildID', keep) == 0,
    'a failing keyword read removes nothing')
check(#K.stale(photo(nil), 'WildID', keep) == 0, 'no keywords -> nothing to remove')

-- ---------------------------------------------------------------- namespace / flat tags
local root2, flat2 = K.namespace({ root = 'Fauna', flat = { 'animals', 'Wildlife' } }, 'WildID')
check(root2 == 'Fauna' and flat2['animals'] and flat2['wildlife'], 'namespace from the run document, lower-cased')
local root3, flat3 = K.namespace(nil, 'WildID')
check(root3 == 'WildID' and next(flat3) == nil, 'an older server: fallback root, no flat tags')
local root4 = K.namespace({ root = '', flat = 'nope' }, 'WildID')
check(root4 == 'WildID', 'a malformed block falls back')

local _, flatWild = K.namespace({ root = 'WildID', flat = { 'animals', 'wildlife' } }, 'WildID')
local wildlife = keyword('wildlife')
local nested = keyword('animals', keyword('Zoo'))
local q = photo({ newJaguar, animals, wildlife, nested, keyword('Animals'), other })
local speciesOnly = K.keepSet({ suggested[1] }) -- the new run suggests neither flat tag
check(keysOf(K.stale(q, 'WildID', speciesOnly, flatWild)) == 'animals;wildlife;animals',
    'dropped flat tags come off whatever their case; a nested "animals" and other roots stay: '
    .. keysOf(K.stale(q, 'WildID', speciesOnly, flatWild)))
local partly = K.stale(q, 'WildID', keep, flatWild) -- keep has animals, not wildlife
check(#partly == 1 and partly[1] == wildlife, 'a still-suggested flat tag stays, the dropped one goes')
check(#K.stale(q, 'WildID', speciesOnly, nil) == 0 and #K.stale(q, 'WildID', speciesOnly, flat3) == 0,
    'without a declared namespace no flat tag is touched')

if failures == 0 then
    print('ALL KEYWORDS TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
