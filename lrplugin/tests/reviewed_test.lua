-- "Mark as reviewed": WildidCollections.findReview / inCollection and WildidReview.plan / apply
-- against a fake catalog. usage: lua5.1 reviewed_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
_PLUGIN = { path = arg[1] }
local C = require 'WildidCollections'
local R = require 'WildidReview'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

-- ---------------------------------------------------------------- fakes
local function keyword(name, parentName)
    local parent = parentName and { getName = function() return parentName end } or nil
    return { getName = function() return name end, getParent = function() return parent end }
end
local removedKeywords, statusWrites = {}, {}
local function photo(id, status, keywords)
    return {
        localIdentifier = id,
        _status = status,
        getRawMetadata = function(_, key) if key == 'keywords' then return keywords or {} end end,
        getPropertyForPlugin = function(self, _p, field)
            if field == 'wildidStatus' then return self._status end
        end,
        setPropertyForPlugin = function(self, _p, field, value)
            statusWrites[#statusWrites + 1] = { id = self.localIdentifier, field = field, value = value }
        end,
        removeKeyword = function(self, kw)
            removedKeywords[#removedKeywords + 1] = { id = self.localIdentifier, name = kw:getName() }
        end,
    }
end
local removedFromReview = {}
local function col(name, photos, smart)
    return {
        getName = function() return name end,
        getPhotos = function() return photos or {} end,
        isSmartCollection = function() return smart == true end,
        removePhotos = function(_, list)
            for _, p in ipairs(list) do removedFromReview[#removedFromReview + 1] = p.localIdentifier end
        end,
    }
end
local function set(name, sets, cols)
    return {
        getName = function() return name end,
        getChildCollectionSets = function() return sets or {} end,
        getChildCollections = function() return cols or {} end,
    }
end
local catalog = {
    _writes = {}, _private = 0,
    withWriteAccessDo = function(self, name, fn) self._writes[#self._writes + 1] = name; fn() end,
    withPrivateWriteAccessDo = function(self, fn) self._private = self._private + 1; fn() end,
}

-- p1: every marker. p2: in _review only (a second LrPhoto table for the same catalog photo,
-- status ok). p3: keyword only, never identified (status nil) - the XMP-import case.
-- p4: clean. p5: a "review" keyword under another root, status ok. p6: "Review" under "wildid"
-- (Lightroom keywords are case-insensitive).
local kwReview = keyword('review', 'WildID')
local p1 = photo(1, 'review', { keyword('Panthera onca', 'Felidae'), kwReview })
local p2 = photo(2, 'ok', {})
local p3 = photo(3, nil, { keyword('review', 'WildID') })
local p4 = photo(4, 'ok', { keyword('animals') })
local p5 = photo(5, 'ok', { keyword('review', 'Other') })
local p6 = photo(6, 'ok', { keyword('Review', 'wildid') })
local review = col('_review', { p1, photo(2, 'ok'), photo(9, 'review') })
local wildid = set('WildID', {}, { col('Lemur catta', { p1 }), review })
catalog.getChildCollectionSets = function() return { wildid, set('Smart', {}, { col('_review', {}, true) }) } end

-- ---------------------------------------------------------------- findReview / inCollection
local r, path = C.findReview(catalog, 'wildid')
check(r == review and path == 'WildID/_review', 'findReview: case-insensitive set, normalised path')
r, path = C.findReview(catalog, 'Nope')
check(r == nil and path == 'Nope/_review', 'missing set -> nil + the path looked for')
check(C.findReview(catalog, 'Smart') == nil, 'a smart _review is never a target')
local hits = C.inCollection(review, { p4, p2, p1 })
check(#hits == 2 and hits[1] == p2 and hits[2] == p1, 'membership by catalog id, selection order kept')

-- ---------------------------------------------------------------- plan
check(R.reviewKeywordOf(p1, 'WildID') == kwReview, 'the review keyword under the root is found')
check(R.reviewKeywordOf(p5, 'WildID') == nil, 'a review keyword under another root is not ours')
check(R.reviewKeywordOf(p6, 'WildID') ~= nil, 'keyword and root names match case-insensitively')
check(R.reviewKeywordOf(p1, 'Fauna') == nil, 'a different keyword root finds nothing')
check(R.reviewKeywordOf({ getRawMetadata = function() error('boom') end }, 'WildID') == nil,
    'a failing keyword read is treated as no keyword')

local plan = R.plan({ p1, p2, p3, p4, p5, p6 }, review, 'WildID')
check(plan.touched == 4, 'photos with any marker: 4 (p1, p2, p3, p6), got ' .. plan.touched)
check(#plan.collection == 2 and plan.collection[1] == p1 and plan.collection[2] == p2, 'collection: p1, p2')
check(#plan.keywords == 3 and plan.keywords[1].photo == p1 and plan.keywords[2].photo == p3
    and plan.keywords[3].photo == p6, 'keywords: p1, p3, p6')
check(#plan.status == 1 and plan.status[1] == p1, 'status: only a photo whose status is "review"')
local noCollection = R.plan({ p1, p3 }, nil, 'WildID')
check(noCollection.touched == 2 and #noCollection.collection == 0 and #noCollection.keywords == 2,
    'without a _review collection the keyword and status are still planned')

-- ---------------------------------------------------------------- apply
R.apply(catalog, review, R.plan({ p4 }, review, 'WildID'))
check(#catalog._writes == 0 and catalog._private == 0, 'nothing to clear: no transactions')
R.apply(catalog, review, plan)
check(#catalog._writes == 1 and catalog._writes[1] == 'WildID: mark as reviewed',
    'one named (undoable) write transaction for collection + keywords')
check(catalog._private == 1, 'one private-metadata transaction for the status')
check(#removedFromReview == 2 and removedFromReview[1] == 1 and removedFromReview[2] == 2,
    'exactly p1 and p2 left _review')
check(#removedKeywords == 3 and removedKeywords[1].id == 1 and removedKeywords[2].id == 3
    and removedKeywords[3].id == 6 and removedKeywords[3].name == 'Review',
    'the matched keyword objects were removed from p1, p3, p6')
check(#statusWrites == 1 and statusWrites[1].id == 1 and statusWrites[1].field == 'wildidStatus'
    and statusWrites[1].value == 'reviewed', 'p1 status review -> reviewed; p3 (never identified) untouched')
R.apply(catalog, nil, noCollection)
check(#catalog._writes == 2 and #removedFromReview == 2, 'no collection: keywords only, nothing removed from it')

-- ---------------------------------------------------------------- summary
check(R.summary(plan, 6):find('4 of 6 selected photo%(s%) marked as reviewed') ~= nil, 'summary counts')
check(R.summary(R.plan({ p4 }, review, 'WildID'), 1):find('none of the 1') ~= nil, 'summary when clean')

if failures == 0 then
    print('ALL REVIEWED TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
