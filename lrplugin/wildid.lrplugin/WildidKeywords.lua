--[[
The keyword root is the plugin's namespace: everything a run writes goes under it
("<root>|Mammalia|Panthera|Panthera onca", "<root>|review"), and a re-run replaces what an
earlier run — or an imported wildid XMP sidecar — left there with the new suggestions, so a
changed answer, a cleared review flag or a changed hierarchy leaves nothing stale behind. The
flat tags ("animals" / "wildlife") come off too when a re-run no longer suggests them. The run
document names that namespace (`keywords: {root, flat}`), so no keyword name lives here;
anything under another root, or any other flat keyword, is never touched. Policy still comes
from the server (keywords.py): this only reconciles the namespace with suggested_keywords. Pure
Lua (no Lightroom imports) so it is testable outside Lightroom.
]]

local M = {}

local MAX_DEPTH = 64 -- guard against a getParent() cycle

--- The keyword's hierarchy as names, root first: {"WildID", "Mammalia", "Panthera onca"}.
function M.pathOf(keyword)
    local names = {}
    local kw = keyword
    for _ = 1, MAX_DEPTH do
        if kw == nil then break end
        table.insert(names, 1, kw:getName())
        kw = kw:getParent()
    end
    return names
end

--- Lightroom's lr:hierarchicalSubject spelling, lower-cased (keyword names are
--- case-insensitive in Lightroom).
function M.key(names)
    return table.concat(names, '|'):lower()
end

--- The keys of the keywords a result's suggested_keywords will put on the photo.
function M.keepSet(suggested)
    local keep = {}
    for _, kw in ipairs(suggested or {}) do
        if type(kw.path) == 'table' and #kw.path > 0 then
            keep[M.key(kw.path)] = true
        end
    end
    return keep
end

--- The namespace a run document declares (`doc.keywords`): the root the server actually
--- used, else `fallbackRoot`, and the set of lower-cased flat tag names it owns. An older
--- server names none, and then only the root's subtree is reconciled.
function M.namespace(docKeywords, fallbackRoot)
    local root, flat = fallbackRoot, {}
    if type(docKeywords) == 'table' then
        if type(docKeywords.root) == 'string' and docKeywords.root ~= '' then
            root = docKeywords.root
        end
        for _, name in ipairs(type(docKeywords.flat) == 'table' and docKeywords.flat or {}) do
            if type(name) == 'string' and name ~= '' then flat[name:lower()] = true end
        end
    end
    return root, flat
end

--- The keywords applied to `photo` that are not in `keep` and either sit under `root` (the
--- root itself included) or are a top-level keyword named in `flat`: what a run removes
--- before attaching the new suggestions. Returns the LrKeyword objects, which is what
--- removeKeyword wants. A failing keyword read means nothing to remove.
function M.stale(photo, root, keep, flat)
    local ok, keywords = pcall(photo.getRawMetadata, photo, 'keywords')
    if not ok or type(keywords) ~= 'table' then return {} end
    local wanted = (root ~= nil and root ~= '') and root:lower() or 'wildid'
    local out = {}
    for _, kw in ipairs(keywords) do
        local names = M.pathOf(kw)
        local key = M.key(names)
        if #names > 0 and not keep[key]
            and (names[1]:lower() == wanted or (#names == 1 and flat ~= nil and flat[key])) then
            out[#out + 1] = kw
        end
    end
    return out
end

return M
