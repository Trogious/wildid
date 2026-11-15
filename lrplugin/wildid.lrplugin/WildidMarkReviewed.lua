--[[
Library menu: "WildID: mark as reviewed"

For the selected photos, clears every review marker a run left: membership in the "_review"
collection under the set Identify files into (default "WildID"), the "<root>|review" keyword,
and the WildID status "review" (which becomes "reviewed"). Collection and keyword changes are
one undoable transaction; the next identification run re-flags a photo it still doubts.
]]

local LrApplication = import 'LrApplication'
local LrDialogs = import 'LrDialogs'
local LrFunctionContext = import 'LrFunctionContext'
local LrPrefs = import 'LrPrefs'
local LrTasks = import 'LrTasks'

local Collections = require 'WildidCollections'
local Review = require 'WildidReview'

-- a transient bezel like Lightroom's own "Flagged" notice; a dialog if the SDK lacks it
local function notify(message)
    if type(LrDialogs.showBezel) == 'function' then
        LrDialogs.showBezel(message)
    else
        LrDialogs.message('WildID', message, 'info')
    end
end

local function run()
    local catalog = LrApplication.activeCatalog()
    local photos = catalog:getTargetPhotos()
    if #photos == 0 then
        LrDialogs.message('WildID', 'Select the photos you have reviewed first.', 'info')
        return
    end
    local prefs = LrPrefs.prefsForPlugin()
    local keywordRoot = (prefs.keywordRoot ~= nil and prefs.keywordRoot ~= '') and prefs.keywordRoot
        or 'WildID'
    -- no _review collection is fine: the keyword and status markers are still cleared
    local review = Collections.findReview(catalog, prefs.collectionSet or 'WildID')
    local plan = Review.plan(photos, review, keywordRoot)
    Review.apply(catalog, review, plan)
    notify(Review.summary(plan, #photos))
end

LrTasks.startAsyncTask(function()
    LrFunctionContext.callWithContext('wildidMarkReviewed', run)
end)
