--[[
Library menu: "WildID: delete empty collections…"

Species collections accumulate as photos get re-identified and moved; this removes the empty
regular collections under a chosen collection set (default: the one Identify files into) and
the sub-sets left with nothing in them — the genus and class sets a move emptied. Smart
collections and non-empty collections are never touched, and the chosen root set itself is
kept. The list of what would be deleted is shown for confirmation before anything happens.
]]

local LrApplication = import 'LrApplication'
local LrBinding = import 'LrBinding'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrTasks = import 'LrTasks'
local LrView = import 'LrView'

local Collections = require 'WildidCollections'

local bind = LrView.bind
local MAX_LISTED = 30

local function run(context)
    local catalog = LrApplication.activeCatalog()
    local prefs = LrPrefs.prefsForPlugin()
    local f = LrView.osFactory()
    local props = LrBinding.makePropertyTable(context)
    props.setPath = prefs.cleanupSet or prefs.collectionSet or 'WildID'
    local contents = f:column {
        bind_to_object = props,
        spacing = f:control_spacing(),
        f:static_text {
            title = 'Delete every empty regular collection under a collection set, and every '
                .. 'sub-set left with nothing in it\n(the genus and class sets a move emptied). '
                .. 'Smart collections, non-empty collections and the set itself are left alone.',
        },
        f:row {
            f:static_text { title = 'Collection set:' },
            f:combo_box {
                value = bind 'setPath',
                items = Collections.allSetPaths(catalog),
                width_in_chars = 32,
                tooltip = 'Pick an existing set, or type a "/"-separated path.',
            },
        },
    }
    local verdict = LrDialogs.presentModalDialog {
        title = 'WildID: delete empty collections',
        contents = contents,
        actionVerb = 'Scan',
    }
    if verdict ~= 'ok' then return end
    prefs.cleanupSet = props.setPath
    prefs.cleanupIncludeSets = nil -- pre-tree checkbox: empty sub-sets are always removed now

    local set, path = Collections.findSet(catalog, props.setPath)
    if not set then
        LrDialogs.message('WildID', 'No collection set "' .. path .. '" in this catalog.', 'warning')
        return
    end
    local entries = Collections.collectEmpty(set, path)
    if #entries == 0 then
        LrDialogs.message('WildID', 'Nothing to delete: no empty collections under "' .. path
            .. '".', 'info')
        return
    end
    local lines = {}
    for i, e in ipairs(entries) do
        if i <= MAX_LISTED then
            lines[#lines + 1] = (e.kind == 'set' and '[set] ' or '') .. e.path
        end
    end
    if #entries > MAX_LISTED then
        lines[#lines + 1] = string.format('\226\128\166 and %d more', #entries - MAX_LISTED)
    end
    local confirm = LrDialogs.confirm(
        string.format('Delete %d empty item(s) under "%s"?', #entries, path),
        table.concat(lines, '\n'), 'Delete', 'Cancel')
    if confirm ~= 'ok' then return end
    local counts = Collections.deleteEntries(catalog, entries)
    LrDialogs.message('WildID', string.format(
        'Deleted %d empty collection(s) and %d empty sub-set(s) under "%s".',
        counts.collections, counts.sets, path), 'info')
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext('wildidCleanup', run)
end)
