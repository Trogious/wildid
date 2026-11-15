-- WildidGeo.lua (geo modes, /classify geo + gps payloads, GPS cells) under plain Lua 5.1.
-- usage: lua5.1 geo_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
local Geo = require 'WildidGeo'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

-- prefs migration
check(Geo.modeFromPrefs({}) == 'none', 'fresh prefs: no filter')
check(Geo.modeFromPrefs({ useGeo = true }) == 'place', 'pre-0.3 useGeo=true becomes place mode')
check(Geo.modeFromPrefs({ useGeo = false }) == 'none', 'pre-0.3 useGeo=false stays none')
check(Geo.modeFromPrefs({ geoMode = 'gps', useGeo = false }) == 'gps', 'geoMode wins over useGeo')
check(Geo.modeFromPrefs({ geoMode = 'bogus' }) == 'none', 'unknown mode falls back to none')
check(Geo.isLevel('country') and Geo.isLevel('region') and not Geo.isLevel('county'), 'levels')

-- /classify geo member
check(Geo.classifyGeo({ geoMode = 'none', country = 'Kenya' }) == nil, 'none: no geo member')
local gps = Geo.classifyGeo({ geoMode = 'gps', geoLevel = 'region', geoRank = 'genus', taxa = 'Mammalia' })
check(gps.auto == true and gps.level == 'region' and gps.rank == 'genus' and gps.taxa == 'Mammalia',
    'gps mode: auto with level, rank and taxa')
local gpsDefault = Geo.classifyGeo({ geoMode = 'gps', geoLevel = 'county', geoRank = 'species', taxa = '' })
check(gpsDefault.level == 'country' and gpsDefault.taxa == nil and gpsDefault.country == nil,
    'gps mode: bad level -> country, empty taxa omitted, no place fields')
local place = Geo.classifyGeo({ geoMode = 'place', geoRank = 'species', taxa = 'Aves',
    country = 'Kenya', region = 'Narok', placeId = '' })
check(place.auto == nil and place.country == 'Kenya' and place.region == 'Narok' and place.taxa == 'Aves',
    'place mode: country + region')
local byId = Geo.classifyGeo({ geoMode = 'place', geoRank = 'species', taxa = '',
    country = 'Kenya', region = '', placeId = '7042' })
check(byId.place_id == 7042 and byId.country == nil, 'place id wins over the country')
check(Geo.classifyGeo({ geoMode = 'place', geoRank = 'species', taxa = '', country = '', region = '',
    placeId = 'abc' }) == nil, 'place mode without a usable place: no filter')

-- catalog GPS -> coordinates
local c = Geo.coords({ latitude = -1.4, longitude = 35.2 })
check(c[1] == -1.4 and c[2] == 35.2, 'coords from the catalog table')
check(Geo.coords(nil) == nil and Geo.coords('x') == nil, 'no gps -> nil')
check(Geo.coords({ latitude = 0, longitude = 0 }) == nil, '(0, 0) non-fix -> nil')
check(Geo.coords({ latitude = 91, longitude = 0 }) == nil, 'out of range -> nil')
check(Geo.coords({ latitude = 'n/a', longitude = 1 }) == nil, 'malformed -> nil')

-- per-chunk gps map
local map, n = Geo.gpsMap({ { path = 'a.jpg' }, { path = 'b.jpg' } })
check(map == nil and n == 0, 'no positions: nil (never an empty table)')
map, n = Geo.gpsMap({ { path = 'C:\\a.ARW', gps = { -1.4, 35.2 } }, { path = 'b.jpg' } })
check(n == 1 and map['C:\\a.ARW'][1] == -1.4 and map['C:\\a.ARW'][2] == 35.2 and map['b.jpg'] == nil,
    'map keyed by the path sent, only for targets with a position')

-- cells (same arithmetic as wildid.gps.cell_of)
local clat, clon = Geo.cellOf(-1.4, 35.2)
check(math.abs(clat - -1.5) < 1e-9 and math.abs(clon - 35.0) < 1e-9, 'cell of (-1.4, 35.2) is (-1.5, 35.0)')
local cells = Geo.distinctCells({ { -1.4, 35.2 }, { -1.45, 35.24 }, { -1.6, 35.2 }, { -1.4, 35.2 } })
check(#cells == 2 and cells[1][1] == -1.4 and cells[2][1] == -1.6, 'first point per distinct cell, in order')
local function photo(gps) return { getRawMetadata = function(_, k) if k == 'gps' then return gps end end } end
local pts = Geo.pointsOf({ photo({ latitude = 1, longitude = 2 }), photo(nil), photo({ latitude = 0, longitude = 0 }) })
check(#pts == 1 and pts[1][1] == 1, 'pointsOf keeps the photos with a real fix')

if failures == 0 then
    print('ALL GEO TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
