--[[
Geo modes for the identify and prefetch dialogs (plan B3): no place filter, one prefetched
place, or each photo's own GPS position (the daemon resolves 0.25-degree cells to an
iNaturalist place offline, from what `prefetch` cached). Pure Lua (no Lightroom imports) so
the payload rules are testable outside Lightroom; WildidIdentify.lua and WildidPrefetch.lua
render them.
]]

local M = {}

M.MODE_NONE, M.MODE_PLACE, M.MODE_GPS = 'none', 'place', 'gps'
M.MODES = {
    { title = 'the full TreeOfLife (no place filter)', value = M.MODE_NONE },
    { title = 'a prefetched place (country / region / place id)', value = M.MODE_PLACE },
    { title = "each photo's GPS position (cells prefetched from the photos)", value = M.MODE_GPS },
}
M.LEVELS = {
    { title = 'country', value = 'country' },
    { title = 'region (state / province)', value = 'region' },
}
M.DEFAULT_LEVEL = 'country'
M.DEFAULT_TAXA = 'Mammalia,Reptilia,Amphibia,Aves'
M.CELL_DEG = 0.25 -- must match wildid.gps.GPS_CELL_DEG

function M.isMode(v)
    return v == M.MODE_NONE or v == M.MODE_PLACE or v == M.MODE_GPS
end

function M.isLevel(v)
    for _, l in ipairs(M.LEVELS) do
        if l.value == v then return true end
    end
    return false
end

--- Dialog prefs -> mode. `geoMode` wins; the pre-0.3 `useGeo` boolean maps onto 'place'.
function M.modeFromPrefs(prefs)
    if M.isMode(prefs.geoMode) then return prefs.geoMode end
    if prefs.useGeo then return M.MODE_PLACE end
    return M.MODE_NONE
end

--- The `geo` member of a /classify body for the dialog values, or nil for no filter.
--- props: geoMode, geoLevel, geoRank, taxa, country, region, placeId.
function M.classifyGeo(props)
    local taxa = (props.taxa ~= nil and props.taxa ~= '') and props.taxa or nil
    if props.geoMode == M.MODE_GPS then
        return {
            auto = true,
            level = M.isLevel(props.geoLevel) and props.geoLevel or M.DEFAULT_LEVEL,
            rank = props.geoRank,
            taxa = taxa,
        }
    end
    if props.geoMode ~= M.MODE_PLACE then return nil end
    local geo = { rank = props.geoRank, taxa = taxa }
    if props.placeId ~= nil and props.placeId ~= '' and tonumber(props.placeId) then
        geo.place_id = tonumber(props.placeId)
    else
        if props.country ~= nil and props.country ~= '' then geo.country = props.country end
        if props.region ~= nil and props.region ~= '' then geo.region = props.region end
    end
    if not (geo.place_id or geo.country) then return nil end
    return geo
end

--- Catalog GPS (photo:getRawMetadata('gps') -> {latitude=, longitude=}) as {lat, lon}, or
--- nil when absent, a (0, 0) non-fix, or malformed.
function M.coords(gps)
    if type(gps) ~= 'table' then return nil end
    local lat, lon = tonumber(gps.latitude), tonumber(gps.longitude)
    if lat == nil or lon == nil then return nil end
    if lat == 0 and lon == 0 then return nil end
    if lat < -90 or lat > 90 or lon < -180 or lon > 180 then return nil end
    return { lat, lon }
end

--- The per-chunk `gps` member of a /classify body: path -> [lat, lon] for the targets that
--- carry catalog GPS (the daemon reads the file's EXIF for the others). Returns nil when no
--- target has one (an empty Lua table would not encode as a JSON object), plus the count.
function M.gpsMap(targets)
    local map, n = {}, 0
    for _, t in ipairs(targets) do
        if t.gps then
            map[t.path] = t.gps
            n = n + 1
        end
    end
    if n == 0 then return nil, 0 end
    return map, n
end

--- The 0.25-degree cell corner of a position (same arithmetic as wildid.gps.cell_of).
function M.cellOf(lat, lon)
    local d = M.CELL_DEG
    return math.floor(lat / d) * d, math.floor(lon / d) * d
end

--- One representative point per distinct cell (the first seen), in first-seen order: what
--- prefetch sends, so a thousand-photo selection becomes a handful of lookups.
function M.distinctCells(points)
    local seen, out = {}, {}
    for _, p in ipairs(points) do
        local clat, clon = M.cellOf(p[1], p[2])
        local key = string.format('%.2f,%.2f', clat, clon)
        if not seen[key] then
            seen[key] = true
            out[#out + 1] = { p[1], p[2] }
        end
    end
    return out
end

--- Positions of the photos (LrPhoto-like, getRawMetadata) that carry catalog GPS.
function M.pointsOf(photos)
    local points = {}
    for _, photo in ipairs(photos) do
        local c = M.coords(photo:getRawMetadata('gps'))
        if c then points[#points + 1] = c end
    end
    return points
end

return M
