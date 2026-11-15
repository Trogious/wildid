--[[
Library menu: "WildID: prefetch place list…"

The one online operation: asks the daemon to fetch (or renew) the iNaturalist species list
and GBIF synonyms for a place — typed in, or resolved from the selected photos' GPS positions
(one lookup per 0.25-degree cell) — so later identification runs stay fully offline.
]]

local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrProgressScope = import 'LrProgressScope'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Geo = require 'WildidGeo'
local Server = require 'WildidServer'

local bind = LrView.bind

local SOURCE_PLACE, SOURCE_GPS = 'place', 'gps'

local function run(context)
    local f = LrView.osFactory()
    local prefs = LrPrefs.prefsForPlugin()
    local catalog = LrApplication.activeCatalog()
    local photos = catalog:getTargetPhotos()
    local cells = Geo.distinctCells(Geo.pointsOf(photos))
    local props = LrBinding.makePropertyTable(context)
    props.source = (prefs.prefetchSource == SOURCE_GPS and #cells > 0) and SOURCE_GPS
        or SOURCE_PLACE
    props.country = prefs.country or ''
    props.region = prefs.region or ''
    props.placeId = prefs.placeId or ''
    props.geoLevel = Geo.isLevel(prefs.geoLevel) and prefs.geoLevel or Geo.DEFAULT_LEVEL
    props.taxa = prefs.taxa or Geo.DEFAULT_TAXA
    props.refresh = false
    local function refreshSource()
        props.placeSource = props.source == SOURCE_PLACE
        props.gpsSource = props.source == SOURCE_GPS
    end
    props:addObserver('source', refreshSource)
    refreshSource()
    local gpsTitle = string.format(
        "the selected photos' GPS positions (%d of %d photo(s) have one, %d cell(s))",
        #Geo.pointsOf(photos), #photos, #cells)
    local contents = f:column {
        bind_to_object = props,
        spacing = f:control_spacing(),
        f:static_text {
            title = 'Fetch the species list(s) for a place (needs the network once);\n'
                .. 'identification runs then work offline.',
        },
        f:row {
            f:static_text { title = 'For:', width = LrView.share 'lbl' },
            f:popup_menu {
                value = bind 'source',
                items = {
                    { title = 'a place I type in', value = SOURCE_PLACE },
                    { title = gpsTitle, value = SOURCE_GPS },
                },
            },
        },
        f:row {
            f:static_text { title = 'Country:', width = LrView.share 'lbl' },
            f:edit_field { value = bind 'country', width_in_chars = 16, enabled = bind 'placeSource' },
            f:static_text { title = 'Region:' },
            f:edit_field { value = bind 'region', width_in_chars = 16, enabled = bind 'placeSource' },
            f:static_text { title = 'Place id:' },
            f:edit_field { value = bind 'placeId', width_in_chars = 8, enabled = bind 'placeSource' },
        },
        f:row {
            f:static_text { title = 'GPS level:', width = LrView.share 'lbl' },
            f:popup_menu { value = bind 'geoLevel', items = Geo.LEVELS, enabled = bind 'gpsSource' },
            f:static_text {
                title = 'must match the level chosen in the identify dialog',
                font = '<system/small>',
                enabled = bind 'gpsSource',
            },
        },
        f:row {
            f:static_text { title = 'Taxa:', width = LrView.share 'lbl' },
            f:edit_field { value = bind 'taxa', width_in_chars = 24 },
        },
        f:checkbox { title = 'Refresh even if already cached', value = bind 'refresh' },
    }
    local verdict = LrDialogs.presentModalDialog {
        title = 'WildID: prefetch place list',
        contents = contents,
        actionVerb = 'Fetch',
    }
    if verdict ~= 'ok' then return end
    local geo = {}
    if props.taxa ~= '' then geo.taxa = props.taxa end
    if props.source == SOURCE_GPS then
        if #cells == 0 then
            LrDialogs.message('WildID', 'None of the selected photos carries a GPS position.',
                'warning')
            return
        end
        geo.gps = cells
        geo.level = props.geoLevel
    else
        if props.placeId ~= '' and tonumber(props.placeId) then
            geo.place_id = tonumber(props.placeId)
        else
            if props.country ~= '' then geo.country = props.country end
            if props.region ~= '' then geo.region = props.region end
        end
        if not (geo.place_id or geo.country) then
            LrDialogs.message('WildID', 'Give a country (optionally a region) or a place id.',
                'warning')
            return
        end
    end
    prefs.country, prefs.region, prefs.placeId, prefs.taxa =
        props.country, props.region, props.placeId, props.taxa
    prefs.prefetchSource, prefs.geoLevel = props.source, props.geoLevel

    local progress = LrProgressScope {
        title = 'WildID: fetching species list…', functionContext = context,
    }
    progress:setCaption('starting the WildID server…')
    local ok, err = Server.ensureReady(nil)
    if not ok then
        progress:done()
        LrDialogs.showError(err)
        return
    end
    progress:setCaption('fetching from iNaturalist (can take a while for large places)…')
    local result, fetchErr = Server.prefetchPlace(geo, props.refresh)
    progress:done()
    if not result then
        LrDialogs.showError('WildID prefetch failed: ' .. tostring(fetchErr))
        return
    end
    local lines = {}
    if geo.gps then
        lines[#lines + 1] = string.format('%d GPS cell(s) resolved at %s level.', #cells, geo.level)
    end
    for _, place in ipairs(result.places or {}) do
        lines[#lines + 1] = string.format(
            '%s: %d species (fetched %s%s)',
            place.label, place.species, place.fetched, place.from_cache and ', cached' or '')
    end
    LrDialogs.message('WildID: place list ready', table.concat(lines, '\n'), 'info')
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext('wildidPrefetch', run)
end)
