-- WildidCollections cleanup helpers (findSet / allSetPaths / collectEmpty / deleteEntries)
-- against a fake catalog. usage: lua5.1 cleanup_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
_PLUGIN = { path = arg[1] }
local C = require 'WildidCollections'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

local deleted = {}
local function col(name, nPhotos, smart)
    local photos = {}
    for i = 1, nPhotos or 0 do photos[i] = 'p' .. i end
    return {
        _name = name,
        getName = function(self) return self._name end,
        getPhotos = function() return photos end,
        isSmartCollection = function() return smart == true end,
        delete = function(self) deleted[#deleted + 1] = self._name end,
    }
end
local function set(name, sets, cols)
    return {
        _name = name,
        getName = function(self) return self._name end,
        getChildCollectionSets = function() return sets or {} end,
        getChildCollections = function() return cols or {} end,
        delete = function(self) deleted[#deleted + 1] = '[set] ' .. self._name end,
    }
end

-- WildID/
--   Panthera onca — Jaguar (3)      _review (0)        Caiman yacare (0)
--   Trips/ (set)
--     2025/ (set)   Lemur catta (0)   Old smart (smart, 0)
--     Empty/ (set)  Nothing (0)
--   Archive/ (set)  Kept (5)
--   Mammalia/ (set)                            -- the tree layout after a move
--     Puma/ (set)      Puma concolor (0)
--     Panthera/ (set)  Panthera onca (2)
--   Aves/ (set)                                -- nothing left in it at all
-- Other/ (set, unrelated)
local lemur = col('Lemur catta', 0)
local smart = col('Old smart', 0, true)
local nothing = col('Nothing', 0)
local y2025 = set('2025', nil, { lemur, smart })
local empty = set('Empty', nil, { nothing })
local trips = set('Trips', { y2025, empty })
local archive = set('Archive', nil, { col('Kept', 5) })
local puma = set('Puma', nil, { col('Puma concolor', 0) })
local panthera = set('Panthera', nil, { col('Panthera onca', 2) })
local mammalia = set('Mammalia', { puma, panthera })
local aves = set('Aves')
local jaguar, review, caiman = col('Panthera onca \226\128\148 Jaguar', 3), col('_review', 0), col('Caiman yacare', 0)
local wildid = set('WildID', { trips, archive, mammalia, aves }, { jaguar, review, caiman })
local other = set('Other')
local catalog = {
    _writes = 0,
    getChildCollectionSets = function() return { wildid, other } end,
    withWriteAccessDo = function(self, _n, fn) self._writes = self._writes + 1; fn() end,
}

-- allSetPaths
local paths = C.allSetPaths(catalog)
check(table.concat(paths, '|') == 'Other|WildID|WildID/Archive|WildID/Aves|WildID/Mammalia|WildID/Mammalia/Panthera'
    .. '|WildID/Mammalia/Puma|WildID/Trips|WildID/Trips/2025|WildID/Trips/Empty',
    'allSetPaths lists nested paths sorted: ' .. table.concat(paths, '|'))

-- findSet
local s1, p1 = C.findSet(catalog, 'wildid / trips / 2025')
check(s1 == y2025 and p1 == 'WildID/Trips/2025', 'findSet nested, case-insensitive, normalised path')
local s2, p2 = C.findSet(catalog, 'WildID/Nope')
check(s2 == nil and p2 == 'WildID/Nope', 'findSet missing -> nil + path')
local s3 = C.findSet(catalog, '')
check(s3 == wildid, 'empty path falls back to WildID')

-- collectEmpty: empty regular collections, then the sets left with nothing in them, deepest
-- first. Empty/ and Puma/ qualify (only an empty collection inside), Aves/ too (no children);
-- 2025/ does not (its smart collection keeps it alive), so Trips/ stays; Mammalia/ keeps
-- Panthera/ with its photos; Archive/ has Kept; the root is never listed.
local entries = C.collectEmpty(wildid, 'WildID')
local got = {}
for _, e in ipairs(entries) do got[#got + 1] = (e.kind == 'set' and '[set] ' or '') .. e.path end
check(table.concat(got, '|') == 'WildID/Trips/2025/Lemur catta|WildID/Trips/Empty/Nothing'
    .. '|WildID/Mammalia/Puma/Puma concolor|WildID/_review|WildID/Caiman yacare'
    .. '|[set] WildID/Trips/Empty|[set] WildID/Mammalia/Puma|[set] WildID/Aves',
    'collections first, then emptied sets; smart keeps 2025 alive; root never listed: '
    .. table.concat(got, '|'))
check(not table.concat(got, '|'):find('Old smart', 1, true), 'smart collections are never candidates')
check(not table.concat(got, '|'):find('Jaguar', 1, true) and not table.concat(got, '|'):find('Kept', 1, true),
    'non-empty collections kept')
check(not table.concat(got, '|'):find('[set] WildID/Mammalia|', 1, true)
    and not table.concat(got, '|'):find('Panthera', 1, true), 'a class set with photos below it stays')

-- deleteEntries: one transaction, every entry deleted, counts right
local counts = C.deleteEntries(catalog, entries)
check(catalog._writes == 1, 'single write transaction')
check(counts.collections == 5 and counts.sets == 3, 'counts: ' .. counts.collections .. '/' .. counts.sets)
check(deleted[#deleted] == '[set] Aves' and deleted[#deleted - 1] == '[set] Puma' and #deleted == 8,
    'sets deleted last, after their collections')

if failures == 0 then
    print('ALL CLEANUP TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
