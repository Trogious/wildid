--[[
"Mark as reviewed" (menu WildidMarkReviewed.lua): clear the three review markers a run leaves
on a photo — membership in the "_review" collection, the "<root>|review" keyword and the
WildID status "review" (set to "reviewed", so a smart collection can tell "a human looked" from
"the engine was confident") — for the photos the user selected, on their say-so. The engine's
keyword policy (keywords.py) is untouched: this is the human closing the loop, and the next
identification run re-flags what it still doubts. Pure Lua (no Lightroom imports) so the
planning is testable outside Lightroom.
]]

local Collections = require 'WildidCollections'

local M = {}

M.REVIEW_KEYWORD = 'review'
M.STATUS_REVIEW = 'review'
M.STATUS_REVIEWED = 'reviewed'

--- The "<root>|review" keyword among those applied to `photo`, or nil. Matched by name through
--- the parent (case-insensitively, like Lightroom), so no catalog-wide keyword lookup is needed
--- and the object handed back is the one removeKeyword wants.
function M.reviewKeywordOf(photo, root)
    local ok, keywords = pcall(photo.getRawMetadata, photo, 'keywords')
    if not ok or type(keywords) ~= 'table' then return nil end
    local wanted = (root ~= nil and root ~= '') and root:lower() or 'wildid'
    for _, kw in ipairs(keywords) do
        if kw:getName():lower() == M.REVIEW_KEYWORD then
            local parent = kw:getParent()
            if parent and parent:getName():lower() == wanted then return kw end
        end
    end
    return nil
end

--- What to clear for `photos`. `review` is the _review collection or nil (none in the
--- catalog: the keyword and status are still cleared). Returns a plan:
--- { collection = {photos}, keywords = {{photo, keyword}}, status = {photos}, touched = n }
--- where touched counts the photos carrying at least one marker.
function M.plan(photos, review, keywordRoot)
    local plan = { collection = {}, keywords = {}, status = {}, touched = 0 }
    local inReview = {}
    if review then
        for _, p in ipairs(Collections.inCollection(review, photos)) do inReview[p] = true end
    end
    for _, photo in ipairs(photos) do
        local any = false
        if inReview[photo] then
            plan.collection[#plan.collection + 1] = photo
            any = true
        end
        local kw = M.reviewKeywordOf(photo, keywordRoot)
        if kw then
            plan.keywords[#plan.keywords + 1] = { photo = photo, keyword = kw }
            any = true
        end
        if photo:getPropertyForPlugin(_PLUGIN, 'wildidStatus') == M.STATUS_REVIEW then
            plan.status[#plan.status + 1] = photo
            any = true
        end
        if any then plan.touched = plan.touched + 1 end
    end
    return plan
end

--- Apply a plan: one undoable write transaction for the collection and keyword removals
--- (Edit → Undo "WildID: mark as reviewed"), then the private-metadata transaction for the
--- status, which Lightroom does not put on the undo stack.
function M.apply(catalog, review, plan)
    if #plan.collection > 0 or #plan.keywords > 0 then
        catalog:withWriteAccessDo('WildID: mark as reviewed', function()
            if review and #plan.collection > 0 then review:removePhotos(plan.collection) end
            for _, e in ipairs(plan.keywords) do e.photo:removeKeyword(e.keyword) end
        end, { timeout = 60 })
    end
    if #plan.status > 0 then
        catalog:withPrivateWriteAccessDo(function()
            for _, photo in ipairs(plan.status) do
                photo:setPropertyForPlugin(_PLUGIN, 'wildidStatus', M.STATUS_REVIEWED)
            end
        end, { timeout = 60 })
    end
end

--- The one-line notice for the bezel.
function M.summary(plan, total)
    if plan.touched == 0 then
        return string.format('WildID: none of the %d selected photo(s) carries a review marker',
            total)
    end
    return string.format(
        'WildID: %d of %d selected photo(s) marked as reviewed (%d left _review, %d keyword(s), '
            .. '%d status(es))',
        plan.touched, total, #plan.collection, #plan.keywords, #plan.status)
end

return M
