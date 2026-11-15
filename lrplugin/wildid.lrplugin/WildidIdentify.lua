--[[
Library menu: "Identify species with WildID…"

Flow: options dialog → selection filtered to real photo files (the original on disk, else
its Smart Preview DNG) → chunked POST /classify against the warm daemon, with each photo's
catalog GPS when the run filters by position → per chunk: keywords (withWriteAccessDo),
collections (class/genus sets, species leaves) and custom metadata (withPrivateWriteAccessDo)
→ summary. Keyword policy comes from the server
(suggested_keywords), so the plugin stays a dumb writer; it does own the keyword root's subtree,
which a re-run reconciles with the new suggestions (WildidKeywords.lua).
]]

local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrFileUtils = import 'LrFileUtils'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrProgressScope = import 'LrProgressScope'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Collections = require 'WildidCollections'
local Geo = require 'WildidGeo'
local Keywords = require 'WildidKeywords'
local Models = require 'WildidModels'
local Photos = require 'WildidPhotos'
local Server = require 'WildidServer'

local bind = LrView.bind

-- ------------------------------------------------------------------ options dialog

local function loadPrefs(props)
    local prefs = LrPrefs.prefsForPlugin()
    props.geoMode = Geo.modeFromPrefs(prefs)
    props.geoLevel = Geo.isLevel(prefs.geoLevel) and prefs.geoLevel or Geo.DEFAULT_LEVEL
    props.country = prefs.country or ''
    props.region = prefs.region or ''
    props.placeId = prefs.placeId or ''
    props.taxa = prefs.taxa or Geo.DEFAULT_TAXA
    props.geoRank = prefs.geoRank or 'species'
    props.crop = prefs.crop ~= false -- default on: the accuracy lever for long lenses
    props.cropExact = prefs.cropExact or false -- default off: the platform's own resize
    props.secondOpinion = prefs.secondOpinion or false
    props.k = tostring(prefs.k or 3)
    props.minScore = tostring(prefs.minScore or 0.5)
    props.keywordRoot = prefs.keywordRoot or 'WildID'
    props.chunkSize = tostring(prefs.chunkSize or 24)
    props.useCollections = prefs.useCollections ~= false -- default on
    props.collectionSet = prefs.collectionSet or 'WildID'
    props.model = Models.isKnown(prefs.model) and prefs.model or Models.DEFAULT
    props.loadBoth = prefs.loadBoth or false
    props.dryRun = false
end

local function savePrefs(props)
    local prefs = LrPrefs.prefsForPlugin()
    prefs.geoMode = props.geoMode
    prefs.geoLevel = props.geoLevel
    prefs.useGeo = nil -- pre-0.3 boolean, migrated into geoMode by Geo.modeFromPrefs
    prefs.country = props.country
    prefs.region = props.region
    prefs.placeId = props.placeId
    prefs.taxa = props.taxa
    prefs.geoRank = props.geoRank
    prefs.crop = props.crop
    prefs.cropExact = props.cropExact
    prefs.secondOpinion = props.secondOpinion
    prefs.k = tonumber(props.k) or 3
    prefs.minScore = tonumber(props.minScore) or 0.5
    prefs.keywordRoot = props.keywordRoot
    prefs.chunkSize = tonumber(props.chunkSize) or 24
    prefs.useCollections = props.useCollections
    prefs.collectionSet = props.collectionSet
    prefs.classCollections = nil -- 0.3.1's flat class collections, retired by the class/genus tree
    prefs.model = props.model
    prefs.loadBoth = props.loadBoth
end

local function modelColumn(f, m)
    return f:column {
        f:radio_button { title = m.title, value = bind 'model', checked_value = m.value },
        f:static_text { title = m.note, font = '<system/small>' },
    }
end

local function buildContents(f, props, photoCount, gpu)
    -- Lightroom Classic runs on Windows and macOS only, and a Mac that runs the engine is Apple
    -- Silicon: there the subscripts quote unified memory, not VRAM
    local texts = Models.dialogTexts(not WIN_ENV)
    return f:column {
        bind_to_object = props,
        spacing = f:control_spacing(),
        f:static_text { title = photoCount .. ' photo(s) selected.' },
        f:separator { fill_horizontal = 1 },
        f:row {
            spacing = f:control_spacing(),
            modelColumn(f, texts.models[1]),
            modelColumn(f, texts.models[2]),
        },
        f:checkbox {
            title = texts.bothTitle,
            value = bind 'loadBoth',
            enabled = bind 'loadBothAllowed',
        },
        f:static_text { title = gpu.note, font = '<system/small>' },
        f:static_text {
            title = bind 'warning',
            font = '<system/small>',
            width_in_chars = 80,
            height_in_lines = 2,
        },
        f:separator { fill_horizontal = 1 },
        f:row {
            f:static_text { title = 'Candidates:', width = LrView.share 'label' },
            f:popup_menu { value = bind 'geoMode', items = Geo.MODES },
        },
        f:row {
            f:static_text { title = 'Country:', width = LrView.share 'label' },
            f:edit_field { value = bind 'country', width_in_chars = 16, enabled = bind 'placeMode' },
            f:static_text { title = 'Region:' },
            f:edit_field { value = bind 'region', width_in_chars = 16, enabled = bind 'placeMode' },
            f:static_text { title = 'Place id:' },
            f:edit_field { value = bind 'placeId', width_in_chars = 8, enabled = bind 'placeMode' },
        },
        f:row {
            f:static_text { title = 'GPS level:', width = LrView.share 'label' },
            f:popup_menu { value = bind 'geoLevel', items = Geo.LEVELS, enabled = bind 'gpsMode' },
            f:static_text {
                title = 'offline lookup \226\128\148 prefetch the cells first ("WildID: prefetch '
                    .. 'place list\226\128\166" \226\134\146 selected photos\' GPS)',
                font = '<system/small>',
                enabled = bind 'gpsMode',
            },
        },
        f:row {
            f:static_text { title = 'Taxa:', width = LrView.share 'label' },
            f:edit_field { value = bind 'taxa', width_in_chars = 24, enabled = bind 'anyGeo' },
            f:popup_menu {
                value = bind 'geoRank',
                enabled = bind 'anyGeo',
                items = {
                    { title = 'species list', value = 'species' },
                    { title = 'whole genera', value = 'genus' },
                },
            },
        },
        f:separator { fill_horizontal = 1 },
        f:row {
            f:checkbox { title = 'Detector crop (MegaDetector)', value = bind 'crop' },
            f:checkbox { title = 'SpeciesNet second opinion', value = bind 'secondOpinion' },
        },
        f:row {
            f:checkbox {
                title = 'Exact detector resize (the same on a Mac and a PC)',
                value = bind 'cropExact',
                enabled = bind 'anyCrop',
                tooltip = 'Resizes each photo for the detector with a method that gives the '
                    .. 'same result on a Mac and a PC. Off, the computer\'s own method is '
                    .. 'used, and a Mac and a PC then name about 2 % of the cropped photos '
                    .. 'differently; on, about 0.2 %. Turning it on changes about 2 % of the '
                    .. 'names against a run with it off.',
            },
        },
        f:row {
            f:static_text { title = 'Top-k:', width = LrView.share 'label' },
            f:edit_field { value = bind 'k', width_in_chars = 3 },
            f:static_text { title = 'Review below score:' },
            f:edit_field { value = bind 'minScore', width_in_chars = 5 },
            f:static_text { title = 'Keyword root:' },
            f:edit_field { value = bind 'keywordRoot', width_in_chars = 10 },
        },
        f:row {
            f:checkbox {
                title = 'File photos into species collections under:',
                value = bind 'useCollections',
            },
            f:edit_field {
                value = bind 'collectionSet',
                width_in_chars = 16,
                enabled = bind 'useCollections',
                tooltip = 'Collection set path, "/" nests (created when missing). Inside it: a '
                    .. 'set per class, a set per genus, then a collection per species '
                    .. '(Mammalia/Panthera/Panthera onca \226\128\148 Jaguar). Select a class '
                    .. 'or genus set to re-run everything below it through the other model. '
                    .. 'Review photos also land in "_review".',
            },
            f:static_text {
                title = '(class / genus / species)',
                font = '<system/small>',
                enabled = bind 'useCollections',
            },
        },
        f:row {
            f:static_text { title = 'Chunk size:', width = LrView.share 'label' },
            f:edit_field { value = bind 'chunkSize', width_in_chars = 4 },
            f:checkbox { title = 'Dry run (nothing written)', value = bind 'dryRun' },
        },
    }
end

local function optionsDialog(context, photoCount, gpu)
    local f = LrView.osFactory()
    local props = LrBinding.makePropertyTable(context)
    loadPrefs(props)
    props.loadBothAllowed = gpu.allowed
    if not gpu.allowed then props.loadBoth = false end
    local function refreshWarning()
        local text = Models.warningFor(props.model, props.geoMode, props.taxa)
        if text == nil or text == '' then text = ' ' end
        props.warning = text
    end
    local function refreshMode()
        props.placeMode = props.geoMode == Geo.MODE_PLACE
        props.gpsMode = props.geoMode == Geo.MODE_GPS
        props.anyGeo = props.geoMode ~= Geo.MODE_NONE
        refreshWarning()
    end
    -- the second opinion crops as well (the engine implies it), so either one enables the
    -- exact-resize box
    local function refreshCrop()
        props.anyCrop = (props.crop or props.secondOpinion) and true or false
    end
    props:addObserver('model', refreshWarning)
    props:addObserver('taxa', refreshWarning)
    props:addObserver('geoMode', refreshMode)
    props:addObserver('crop', refreshCrop)
    props:addObserver('secondOpinion', refreshCrop)
    refreshMode()
    refreshCrop()
    local verdict = LrDialogs.presentModalDialog {
        title = 'WildID: identify species',
        contents = buildContents(f, props, photoCount, gpu),
        actionVerb = 'Identify',
    }
    if verdict ~= 'ok' then return nil end
    savePrefs(props)
    return props
end

-- ------------------------------------------------------------------ catalog writes

local function ensureKeyword(catalog, pathArray, synonyms, cache)
    local parent = nil
    local prefix = ''
    for i, name in ipairs(pathArray) do
        prefix = prefix .. '|' .. name
        local kw = cache[prefix]
        if not kw then
            local syn = nil
            if i == #pathArray and synonyms and #synonyms > 0 then
                syn = {}
                for _, s in ipairs(synonyms) do syn[#syn + 1] = tostring(s) end
            end
            kw = catalog:createKeyword(name, syn, true, parent, true)
            cache[prefix] = kw
        end
        parent = kw
    end
    return parent
end

local function photoForPath(byPath, path)
    if byPath[path] then return byPath[path] end
    -- defensive: tolerate separator normalisation between Lua and the server
    local alt = path:gsub('/', '\\')
    if byPath[alt] then return byPath[alt] end
    alt = path:gsub('\\', '/')
    return byPath[alt]
end

--- Per-chunk counts. In an auto-geo run a result whose `place.label` is null ran without a
--- place list (no GPS fix, or a cell nobody prefetched) and is counted for the summary.
local function tally(doc, stats, keepFailures)
    for _, res in ipairs(doc.results or {}) do
        if res.ok then
            stats.tagged = stats.tagged + 1
            if res.review then stats.review = stats.review + 1 end
            if stats.autoGeo
                and not (type(res.place) == 'table' and type(res.place.label) == 'string') then
                stats.noPlace = stats.noPlace + 1
            end
        else
            stats.failed = stats.failed + 1
            if keepFailures and #stats.failures < 10 then
                stats.failures[#stats.failures + 1] =
                    tostring(res.path) .. ': ' .. tostring(res.error)
            end
        end
    end
end

local function writeChunk(catalog, doc, byPath, keywordCache, stats, collections, keywordRoot)
    local lookup = function(path) return photoForPath(byPath, path) end
    -- previous species/status must be read before withPrivateWriteAccessDo overwrites them
    local prev = collections and Collections.previousMeta(doc, lookup) or {}
    -- Two transactions on purpose: Lightroom (LrC 15.4.1) asserts "packed" at commit when a
    -- keyword or collection created in a withWriteAccessDo call is also attached to photos in
    -- that same call. Pass 1 creates every missing keyword, pass 2 attaches them.
    catalog:withWriteAccessDo('WildID keywords', function()
        for _, res in ipairs(doc.results or {}) do
            if photoForPath(byPath, res.path) and res.ok then
                for _, kw in ipairs(res.suggested_keywords or {}) do
                    if kw.path and #kw.path > 0 then
                        ensureKeyword(catalog, kw.path, kw.synonyms, keywordCache)
                    end
                end
            end
        end
    end, { timeout = 60 })
    -- the namespace the server owns on a photo (the root it used, its flat tags): whatever an
    -- earlier run or an imported wildid sidecar put there and the new answer does not repeat
    -- comes off before the new keywords go on
    local root, flat = Keywords.namespace(doc.keywords, keywordRoot)
    catalog:withWriteAccessDo('WildID tagging', function()
        for _, res in ipairs(doc.results or {}) do
            local photo = photoForPath(byPath, res.path)
            if photo and res.ok then
                local stale = Keywords.stale(photo, root, Keywords.keepSet(res.suggested_keywords), flat)
                for _, kw in ipairs(stale) do
                    photo:removeKeyword(kw)
                end
                if #stale > 0 then stats.retagged = (stats.retagged or 0) + 1 end
                for _, kw in ipairs(res.suggested_keywords or {}) do
                    if kw.path and #kw.path > 0 then
                        photo:addKeyword(ensureKeyword(catalog, kw.path, kw.synonyms, keywordCache))
                    end
                end
            end
        end
    end, { timeout = 60 })
    if collections then
        -- separate transactions: see Collections.fileChunk
        Collections.fileChunk(catalog, collections, doc, lookup, prev, stats)
    end
    catalog:withPrivateWriteAccessDo(function()
        local stamp = os.date('%Y-%m-%d %H:%M')
        for _, res in ipairs(doc.results or {}) do
            local photo = photoForPath(byPath, res.path)
            if photo and res.ok then
                local top = res.predictions and res.predictions[1]
                photo:setPropertyForPlugin(_PLUGIN, 'wildidSpecies', top and top.species or nil)
                photo:setPropertyForPlugin(
                    _PLUGIN, 'wildidCommonName', top and top.common_name or nil)
                photo:setPropertyForPlugin(_PLUGIN, 'wildidClass', top and top.class or nil)
                photo:setPropertyForPlugin(
                    _PLUGIN, 'wildidScore', top and string.format('%.3f', top.score) or nil)
                photo:setPropertyForPlugin(
                    _PLUGIN, 'wildidStatus', res.review and 'review' or 'ok')
                photo:setPropertyForPlugin(_PLUGIN, 'wildidModel', doc.model)
                photo:setPropertyForPlugin(_PLUGIN, 'wildidRun', stamp)
            end
        end
    end, { timeout = 60 })
    tally(doc, stats, true)
end

-- ------------------------------------------------------------------ main

local function run(context)
    local catalog = LrApplication.activeCatalog()
    local targets, skipped, smartCount =
        Photos.selectTargets(catalog:getTargetPhotos(), LrFileUtils.exists)
    local total = #targets
    if total == 0 then
        LrDialogs.message('WildID', 'No usable photos in the selection (an original on disk '
            .. 'or a Smart Preview is needed; virtual copies and videos are skipped).', 'info')
        return
    end
    -- a cheap health probe before the dialog (never starts the server): GPU memory, if known,
    -- decides whether "keep both models loaded" is offered
    local health = Server.health()
    local gpu = Models.gpuInfo(health)
    local props = optionsDialog(context, total, gpu)
    if not props then return end

    local progress = LrProgressScope {
        title = 'WildID: identifying ' .. total .. ' photo(s)',
        functionContext = context,
    }
    progress:setCancelable(true)
    progress:setCaption('starting the WildID server…')
    local ok, err = Server.ensureReady(function() return progress:isCanceled() end)
    if not ok then
        progress:done()
        LrDialogs.showError(err)
        return
    end
    health = Server.health()
    local protoOk, protoErr = Server.checkProtocol(health)
    if not protoOk then
        progress:done()
        LrDialogs.showError(protoErr)
        return
    end

    -- Load the chosen model up front (otherwise the first chunk pays for it), and the other
    -- one too when asked and the GPU allows it.
    local function isLoaded(name)
        return Models.isLoaded(health, name)
    end
    if not isLoaded(props.model) then
        progress:setCaption('loading ' .. props.model .. '\226\128\166')
        local warm, warmErr = Server.warmup(props.model)
        if not warm then
            progress:done()
            LrDialogs.showError('WildID: ' .. tostring(warmErr))
            return
        end
    end
    -- The memory rule is applied to what the server reports now: the probe for the dialog may
    -- have run before the server was started, and unknown memory leaves the checkbox enabled.
    if props.loadBoth and Models.gpuInfo(health).allowed then
        local other = Models.other(props.model)
        if not isLoaded(other) then
            progress:setCaption('loading ' .. other .. ' as well\226\128\166')
            local warm, warmErr = Server.warmup(other)
            if not warm then
                LrDialogs.message('WildID', 'Could not load ' .. other .. ': ' .. tostring(warmErr)
                    .. '\nContinuing with ' .. props.model .. ' only.', 'warning')
            end
        end
    end

    local opts = {
        model = props.model,
        k = tonumber(props.k) or 3,
        geo = Geo.classifyGeo(props),
        crop = props.crop or nil,
        crop_exact = (props.cropExact and (props.crop or props.secondOpinion)) and true or nil,
        second_opinion = props.secondOpinion or nil,
        min_score = tonumber(props.minScore) or 0.5,
        keyword_root = props.keywordRoot ~= '' and props.keywordRoot or nil,
    }
    local keywordRoot = opts.keyword_root or 'WildID' -- the server's default root
    local chunkSize = math.max(1, math.min(200, tonumber(props.chunkSize) or 24))
    local autoGeo = opts.geo ~= nil and opts.geo.auto == true
    local stats = {
        tagged = 0, review = 0, failed = 0, moved = 0, refiled = 0, retagged = 0, noPlace = 0,
        failures = {},
        autoGeo = autoGeo,
    }
    local keywordCache = {}
    local collections = nil
    if props.useCollections and not props.dryRun then
        local state, colErr = Collections.prepare(catalog, props.collectionSet)
        if not state then
            progress:done()
            LrDialogs.showError('WildID: ' .. colErr)
            return
        end
        collections = state
    end

    local done = 0
    while done < total do
        if progress:isCanceled() then break end
        local paths, byPath, chunk = {}, {}, {}
        local last = math.min(done + chunkSize, total)
        for i = done + 1, last do
            local target = targets[i]
            paths[#paths + 1] = target.path
            byPath[target.path] = target.photo
            chunk[#chunk + 1] = target
        end
        progress:setCaption(string.format('classifying %d–%d of %d', done + 1, last, total))
        -- catalog GPS (also what the Map module set) beats the file's EXIF for the position
        local gps = autoGeo and Geo.gpsMap(chunk) or nil
        local doc, classifyErr = Server.classify(paths, opts, gps)
        if not doc then
            progress:done()
            -- LrDialogs.showError showed only the first paragraph on LrC 15.4.1, hiding the
            -- count: use a titled message with the count up front.
            local info = string.format(
                '%d of %d photo(s) were tagged before the server stopped answering; '
                    .. 'the remaining %d were not processed. Re-run the selection to finish '
                    .. '(already tagged photos are simply re-filed).',
                done, total, total - done)
            LrDialogs.message('WildID: identification stopped', info .. '\n\nServer error: '
                .. tostring(classifyErr), 'critical')
            return
        end
        if props.dryRun then
            tally(doc, stats, false)
        else
            writeChunk(catalog, doc, byPath, keywordCache, stats, collections, keywordRoot)
        end
        done = last
        progress:setPortionComplete(done, total)
    end
    progress:done()

    local lines = {}
    if props.dryRun then lines[#lines + 1] = 'Dry run - nothing was written.' end
    lines[#lines + 1] = 'Model: ' .. props.model
    lines[#lines + 1] = string.format(
        '%d photo(s) identified, %d flagged "%s|review", %d failed.',
        stats.tagged, stats.review, keywordRoot, stats.failed)
    if stats.retagged > 0 then
        lines[#lines + 1] = string.format(
            '%d photo(s) had keywords from an earlier run replaced.', stats.retagged)
    end
    if autoGeo then
        lines[#lines + 1] = string.format(
            'Place filter from each photo\'s GPS (%s level); %d photo(s) ran unfiltered '
                .. '(no GPS fix, or a cell not yet prefetched \226\128\148 those are flagged for review).',
            opts.geo.level, stats.noPlace)
    end
    if smartCount > 0 then
        lines[#lines + 1] = string.format(
            '%d photo(s) identified from Smart Previews (originals offline).', smartCount)
    end
    if collections then
        local moves = {}
        if stats.moved > 0 then
            moves[#moves + 1] = string.format('%d moved from an earlier species', stats.moved)
        end
        if stats.refiled > 0 then
            moves[#moves + 1] = string.format('%d re-filed from the flat layout', stats.refiled)
        end
        lines[#lines + 1] = string.format(
            'Filed into class/genus/species collections under "%s"%s.', collections.path,
            #moves > 0 and ('; ' .. table.concat(moves, ', ')) or '')
        if stats.renamed and #stats.renamed > 0 then
            lines[#lines + 1] = 'Flat class collections from the earlier layout were renamed to '
                .. 'make room for the class sets: ' .. table.concat(stats.renamed, ', ')
                .. ' (delete them once their photos have been re-run).'
        end
        for _, text in ipairs(stats.problems or {}) do
            lines[#lines + 1] = 'Not filed: ' .. text
        end
    end
    if done < total then
        lines[#lines + 1] = string.format('Canceled: %d of %d photo(s) were processed.', done, total)
    end
    local skippedTotal = skipped.virtual + skipped.video + skipped.missing
    if skippedTotal > 0 then
        lines[#lines + 1] = string.format(
            'Skipped before classifying: %d virtual cop(ies), %d video(s), %d offline without '
                .. 'a Smart Preview.',
            skipped.virtual, skipped.video, skipped.missing)
    end
    for _, failure in ipairs(stats.failures) do
        lines[#lines + 1] = '  ' .. failure
    end
    LrDialogs.message('WildID', table.concat(lines, '\n'), 'info')
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext('wildidIdentify', run)
end)
