--[[
Species collections: regular collections the plugin maintains, laid out as a taxonomy tree.

Under a user-chosen collection set (a '/'-separated path, created when missing) come two
levels of collection sets, the class and then the genus, and at the bottom one collection
per top-1 species holding the photos:

    <set>/Mammalia/Panthera/Panthera onca \226\128\148 Jaguar
    <set>/Reptilia/Crocodylus/Crocodylus niloticus \226\128\148 Nile crocodile
    <set>/_review                 review-flagged photos, next to the class sets

Selecting a class or genus set in Lightroom shows every photo below it, which is how a whole
class is re-run through the other model (bioclip-2 on import, then the Mammalia set through
bioclip-2.5). The class is the engine's (it spells GBIF's reptile orders as Reptilia); a
species the table gives no class (ray-finned fish) goes under "_no class". The genus is the
engine's, else the first word of the binomial. On re-identification the plugin moves photos:
the previously stored wildidSpecies / wildidStatus (read before metadata is overwritten) say
which old collections to remove them from, wherever those sit under the set, so photos filed
by the flat layout of plugin 0.2.1-0.3.1 (<set>/<species>, <set>/<class>) migrate as they are
re-run. A flat class collection ("Mammalia") would block the class set of the same name
(Lightroom keeps sibling names unique, case-insensitively), so it is renamed "Mammalia (flat)"
and reported. SDK calls used: createCollectionSet / createCollection / addPhotos /
removePhotos / getPhotos / setName. The Lightroom rule that shapes every write here (LrC
15.4.1): an object created inside a withWriteAccessDo call can neither be queried, nor be
given photos, nor parent another object until that call has returned — hence the per-level,
per-kind transactions and the smart-collection flags cached when a node is indexed.
]]

local M = {}

M.REVIEW_NAME = '_review'
M.NO_CLASS_NAME = '_no class'
M.FLAT_SUFFIX = ' (flat)'
local EM_DASH = ' \226\128\148 ' -- " — "

function M.collectionName(species, common)
    if common and common ~= '' then
        return species .. EM_DASH .. common
    end
    return species
end

--- The class set a prediction files under: the engine's class, or the placeholder when it
--- has none (JSON null decodes to nil; ray-finned fish carry no class in the table).
function M.classOf(top)
    if top and type(top.class) == 'string' and top.class ~= '' then return top.class end
    return M.NO_CLASS_NAME
end

--- The genus set: the engine's genus, else the first word of the binomial (which also
--- collapses subgenus spellings such as "Charis Sarota acanthoides" to "Charis").
function M.genusOf(top)
    if top and type(top.genus) == 'string' and top.genus ~= '' then return top.genus end
    local species = (top and type(top.species) == 'string') and top.species or ''
    return species:match('^(%S+)') or species
end

local function splitPath(path)
    local names = {}
    for part in string.gmatch(path or '', '[^/]+') do
        local trimmed = part:match('^%s*(.-)%s*$')
        if trimmed ~= '' then names[#names + 1] = trimmed end
    end
    if #names == 0 then names = { 'WildID' } end
    return names
end

-- LrPhoto objects are not guaranteed to be the same table twice; the catalog id is stable.
local function photoKey(photo)
    if type(photo) == 'table' and photo.localIdentifier ~= nil then
        return photo.localIdentifier
    end
    return photo
end

-- ----------------------------------------------------------------------------------------------
-- the tree under the set: one node per collection set, children keyed by lower-cased name
-- (Lightroom compares sibling names case-insensitively: "name is not unique")
-- ----------------------------------------------------------------------------------------------

-- a node of the tree: its set, the child sets and collections by lower-case name, and each
-- collection's smart flag read when the node was indexed. Everything the passes need to know
-- about a collection is cached here: Lightroom refuses every query (getName,
-- isSmartCollection, getPhotos, ...) on an object created inside the still-open
-- withWriteAccessDo call ("can't get collection information after creating collection
-- inside the same withWriteAccessDo function").
local function newNode(set)
    return { set = set, sets = {}, cols = {}, smart = {} }
end

-- the species a collection is named after: the part before " — ", else the whole name
local function speciesKey(name)
    local cut = name:find(EM_DASH, 1, true)
    if cut then name = name:sub(1, cut - 1) end
    return name:lower()
end

-- every regular collection under the set, by species, so a photo's earlier collection is
-- found wherever an earlier layout (or a changed class spelling) put it
local function remember(state, col, name)
    local key = speciesKey(name)
    local list = state.species[key]
    if not list then
        list = {}
        state.species[key] = list
    end
    list[#list + 1] = col
end

local function indexNode(state, node)
    for _, sub in ipairs(node.set:getChildCollectionSets()) do
        local child = newNode(sub)
        node.sets[sub:getName():lower()] = child
        indexNode(state, child)
    end
    for _, col in ipairs(node.set:getChildCollections()) do
        local name = col:getName()
        local key = name:lower()
        local smart = col:isSmartCollection()
        node.cols[key] = col
        node.smart[key] = smart
        if not smart then remember(state, col, name) end
    end
end

local function childSet(node, name)
    return node.sets[name:lower()]
end

-- a regular (never smart) collection of the node by name
local function childCollection(node, name)
    local key = name:lower()
    local col = node.cols[key]
    if col and not node.smart[key] then return col end
    return nil
end

-- the species' collection in the node, whatever common-name spelling it was created with
-- (the two models spell them differently: "Common Ostrich" vs "Common ostrich")
local function childSpecies(node, species)
    local exact = childCollection(node, species)
    if exact then return exact end
    local prefix = (species .. EM_DASH):lower()
    for name, col in pairs(node.cols) do
        if name:sub(1, #prefix) == prefix and not node.smart[name] then return col end
    end
    return nil
end

local function problem(stats, text)
    stats.problems = stats.problems or {}
    for _, seen in ipairs(stats.problems) do
        if seen == text then return end
    end
    stats.problems[#stats.problems + 1] = text
end

-- get-or-create the child set `name` of a node; must run inside withWriteAccessDo. A regular
-- collection of that name (plugin 0.3.1's flat class collections) is renamed aside first; a
-- smart collection is the user's and is left alone, reported instead.
local function ensureSet(catalog, state, node, name, stats)
    local child = childSet(node, name)
    if child then return child end
    local key = name:lower()
    local blocking = node.cols[key]
    if blocking then
        local newName = name .. M.FLAT_SUFFIX
        if node.smart[key] or node.cols[newName:lower()]
            or not pcall(function() blocking:setName(newName) end) then
            problem(stats, 'a collection named "' .. name .. '" under "' .. state.path
                .. '" is in the way of the "' .. name .. '" set: rename or delete it, then run again')
            return nil
        end
        node.cols[key] = nil
        node.smart[key] = nil
        node.cols[newName:lower()] = blocking
        node.smart[newName:lower()] = false
        stats.renamed = stats.renamed or {}
        stats.renamed[#stats.renamed + 1] = newName
    end
    local set = catalog:createCollectionSet(name, node.set, true)
    if not set then
        problem(stats, 'could not create the collection set "' .. name .. '" under "'
            .. state.path .. '"')
        return nil
    end
    child = newNode(set)
    node.sets[key] = child
    return child
end

-- get-or-create a regular collection in a node; must run inside withWriteAccessDo
local function ensureCollection(catalog, state, node, name, stats)
    local col = childCollection(node, name)
    if col then return col end
    if node.cols[name:lower()] then
        problem(stats, 'a smart collection named "' .. name .. '" under "' .. state.path
            .. '" is in the way: rename it, then run again')
        return nil
    end
    col = catalog:createCollection(name, node.set, true)
    if not col then
        problem(stats, 'could not create the collection "' .. name .. '" under "' .. state.path .. '"')
        return nil
    end
    node.cols[name:lower()] = col
    node.smart[name:lower()] = false
    remember(state, col, name)
    return col
end

local function ensureSpecies(catalog, state, node, species, common, stats)
    return childSpecies(node, species)
        or ensureCollection(catalog, state, node, M.collectionName(species, common), stats)
end

--- Resolve (creating when missing) the collection set and index everything under it.
--- Runs its own withWriteAccessDo; call from a task, outside any write access.
--- Returns a state table {set, path, root, species}, or nil + message.
function M.prepare(catalog, path)
    local names = splitPath(path)
    -- one transaction per path level: a set created inside a withWriteAccessDo call cannot
    -- be the parent of a set created in that same call
    local set = nil
    for _, name in ipairs(names) do
        local created
        catalog:withWriteAccessDo('WildID collection set', function()
            created = catalog:createCollectionSet(name, set, true)
        end, { timeout = 60 })
        if not created then
            set = nil
            break
        end
        set = created
    end
    if not set then
        return nil, 'could not create the collection set "' .. table.concat(names, '/')
            .. '" (a collection with that name may be in the way)'
    end
    local state = {
        set = set,
        path = table.concat(names, '/'),
        root = newNode(set),
        species = {},
    }
    indexNode(state, state.root)
    return state
end

--- Previous per-photo metadata, read BEFORE the run overwrites it. Keyed by result path.
function M.previousMeta(doc, lookupPhoto)
    local prev = {}
    for _, res in ipairs(doc.results or {}) do
        local photo = lookupPhoto(res.path)
        if photo and res.ok then
            prev[res.path] = {
                species = photo:getPropertyForPlugin(_PLUGIN, 'wildidSpecies'),
                status = photo:getPropertyForPlugin(_PLUGIN, 'wildidStatus'),
            }
        end
    end
    return prev
end

-- one chunk's work: the results that have a photo in the catalog and succeeded
local function itemsOf(doc, lookupPhoto, prev)
    local items = {}
    for _, res in ipairs(doc.results or {}) do
        local photo = lookupPhoto(res.path)
        if photo and res.ok then
            local top = res.predictions and res.predictions[1]
            items[#items + 1] = {
                photo = photo,
                top = top,
                class = top and M.classOf(top) or nil,
                genus = top and M.genusOf(top) or nil,
                review = res.review == true,
                old = prev[res.path] or {},
            }
        end
    end
    return items
end

-- lookups only, no creation
local function genusNode(state, it)
    local classNode = childSet(state.root, it.class)
    return classNode and childSet(classNode, it.genus) or nil
end

local function leafOf(state, it)
    local node = genusNode(state, it)
    return node and childSpecies(node, it.top.species) or nil
end

--- File one chunk's results into collections. Runs its own write transactions: Lightroom
--- asserts ("Assertion failed: packed", seen in LrC 15.4.1) when photos are added to a
--- collection created inside the same withWriteAccessDo call, refuses a set created in the
--- call as the parent of another, and refuses every query on an object created in the call,
--- so missing class sets are created in one transaction, missing genus sets in a second,
--- missing collections in a third, and photos added/removed in a fourth; each is skipped
--- when it has nothing to do, so a re-run of filed photos writes nothing.
--- Call it OUTSIDE any withWriteAccessDo. stats.moved counts photos that left an earlier
--- species' collection, stats.refiled those that left a collection of the same species
--- elsewhere under the set (the flat layout of earlier plugins); stats.renamed lists flat
--- class collections renamed aside, stats.problems what could not be filed and why.
function M.fileChunk(catalog, state, doc, lookupPhoto, prev, stats)
    local items = itemsOf(doc, lookupPhoto, prev)
    -- pass 1a: the class sets; pass 1b: the genus sets. Two transactions, because a set
    -- created inside a withWriteAccessDo call cannot be the parent of a set created in it.
    local missing = false
    for _, it in ipairs(items) do
        if it.top and not childSet(state.root, it.class) then
            missing = true
            break
        end
    end
    if missing then
        catalog:withWriteAccessDo('WildID class sets', function()
            for _, it in ipairs(items) do
                if it.top then ensureSet(catalog, state, state.root, it.class, stats) end
            end
        end, { timeout = 60 })
    end
    missing = false
    for _, it in ipairs(items) do
        if it.top and childSet(state.root, it.class) and not genusNode(state, it) then
            missing = true
            break
        end
    end
    if missing then
        catalog:withWriteAccessDo('WildID genus sets', function()
            for _, it in ipairs(items) do
                if it.top then
                    local classNode = childSet(state.root, it.class)
                    if classNode then ensureSet(catalog, state, classNode, it.genus, stats) end
                end
            end
        end, { timeout = 60 })
    end
    -- pass 2: the species collections and _review
    missing = false
    for _, it in ipairs(items) do
        if (it.top and genusNode(state, it) and not leafOf(state, it))
            or (it.review and not childCollection(state.root, M.REVIEW_NAME)) then
            missing = true
            break
        end
    end
    if missing then
        catalog:withWriteAccessDo('WildID collections', function()
            for _, it in ipairs(items) do
                if it.top then
                    local node = genusNode(state, it)
                    if node then
                        ensureSpecies(catalog, state, node, it.top.species, it.top.common_name, stats)
                    end
                end
                if it.review then
                    ensureCollection(catalog, state, state.root, M.REVIEW_NAME, stats)
                end
            end
        end, { timeout = 60 })
    end
    -- pass 3: plan the adds/removes against actual membership (read once per collection)
    local adds, removes, membership = {}, {}, {}
    local function holds(col, photo)
        local present = membership[col]
        if not present then
            present = {}
            for _, p in ipairs(col:getPhotos()) do present[photoKey(p)] = true end
            membership[col] = present
        end
        return present[photoKey(photo)] == true
    end
    local function plan(map, col, photo)
        local list = map[col]
        if not list then
            list = {}
            map[col] = list
        end
        list[#list + 1] = photo
    end
    local review = childCollection(state.root, M.REVIEW_NAME)
    for _, it in ipairs(items) do
        if it.top then
            local target = leafOf(state, it)
            -- without a target (a set or collection could not be made, reported above) the
            -- photo stays where it is
            if target then
                if not holds(target, it.photo) then plan(adds, target, it.photo) end
                local old = it.old.species
                if type(old) == 'string' and old ~= '' then
                    local left = false
                    for _, col in ipairs(state.species[old:lower()] or {}) do
                        if col ~= target and holds(col, it.photo) then
                            plan(removes, col, it.photo)
                            left = true
                        end
                    end
                    if left then
                        if old:lower() ~= it.top.species:lower() then
                            stats.moved = (stats.moved or 0) + 1
                        else
                            stats.refiled = (stats.refiled or 0) + 1
                        end
                    end
                end
            end
        end
        if it.review then
            if review and not holds(review, it.photo) then plan(adds, review, it.photo) end
        elseif it.old.status == 'review' and review and holds(review, it.photo) then
            plan(removes, review, it.photo)
        end
    end
    if next(adds) or next(removes) then
        catalog:withWriteAccessDo('WildID species filing', function()
            for col, photos in pairs(adds) do
                col:addPhotos(photos)
            end
            for col, photos in pairs(removes) do
                col:removePhotos(photos)
            end
        end, { timeout = 60 })
    end
end

-- ----------------------------------------------------------------------------------------------
-- cleanup: "delete empty collections under <set>" (menu WildidCleanup.lua)
-- ----------------------------------------------------------------------------------------------

--- Every collection-set path in the catalog ('/'-joined), sorted, for the cleanup combo box.
function M.allSetPaths(catalog)
    local out = {}
    local function walk(container, prefix)
        for _, set in ipairs(container:getChildCollectionSets()) do
            local path = prefix and (prefix .. '/' .. set:getName()) or set:getName()
            out[#out + 1] = path
            walk(set, path)
        end
    end
    walk(catalog, nil)
    table.sort(out)
    return out
end

--- An existing collection set by '/'-path (each level matched case-insensitively, like
--- Lightroom itself), never creating anything. Returns set, normalisedPath — or nil, path.
function M.findSet(catalog, path)
    local names = splitPath(path)
    local container = catalog
    local resolved = {}
    for _, name in ipairs(names) do
        local found
        for _, set in ipairs(container:getChildCollectionSets()) do
            if set:getName():lower() == name:lower() then
                found = set
                break
            end
        end
        if not found then return nil, table.concat(names, '/') end
        resolved[#resolved + 1] = found:getName()
        container = found
    end
    return container, table.concat(resolved, '/')
end

--- Empty regular collections under `set` (recursively) and the sub-sets that would be left
--- holding nothing — after moves, the genus and class sets of the tree layout. Smart
--- collections are never candidates (an empty smart collection is a rule's current result,
--- not clutter) and keep their parent set alive. The root set itself is never listed. Entries
--- {kind='collection'|'set', obj, path} come back in deletion order: collections first, then
--- sets deepest-first.
function M.collectEmpty(set, rootPath)
    local collections, sets = {}, {}
    local function walk(container, path)
        local anythingLeft = false
        for _, sub in ipairs(container:getChildCollectionSets()) do
            local subPath = path .. '/' .. sub:getName()
            if walk(sub, subPath) then
                sets[#sets + 1] = { kind = 'set', obj = sub, path = subPath }
            else
                anythingLeft = true
            end
        end
        for _, c in ipairs(container:getChildCollections()) do
            local colPath = path .. '/' .. c:getName()
            if c:isSmartCollection() then
                anythingLeft = true
            elseif #c:getPhotos() == 0 then
                collections[#collections + 1] = { kind = 'collection', obj = c, path = colPath }
            else
                anythingLeft = true
            end
        end
        return not anythingLeft
    end
    walk(set, rootPath or set:getName())
    local out = {}
    for _, e in ipairs(collections) do out[#out + 1] = e end
    for _, e in ipairs(sets) do out[#out + 1] = e end -- appended post-order: deepest first
    return out
end

-- ----------------------------------------------------------------------------------------------
-- "mark as reviewed" (WildidReview.lua): the _review collection and who is in it
-- ----------------------------------------------------------------------------------------------

--- The regular "_review" collection directly under the set at `path` (matched like
--- Lightroom: case-insensitively), never creating anything. Returns the collection and its
--- '/'-path, or nil and the path that was looked for.
function M.findReview(catalog, path)
    local set, resolved = M.findSet(catalog, path)
    if not set then return nil, resolved .. '/' .. M.REVIEW_NAME end
    for _, c in ipairs(set:getChildCollections()) do
        if c:getName():lower() == M.REVIEW_NAME:lower() and not c:isSmartCollection() then
            return c, resolved .. '/' .. c:getName()
        end
    end
    return nil, resolved .. '/' .. M.REVIEW_NAME
end

--- Those of `photos` that are in `collection`, in the given order.
function M.inCollection(collection, photos)
    local present = {}
    for _, p in ipairs(collection:getPhotos()) do present[photoKey(p)] = true end
    local hits = {}
    for _, p in ipairs(photos) do
        if present[photoKey(p)] then hits[#hits + 1] = p end
    end
    return hits
end

--- Delete the entries collectEmpty() returned, in one write transaction. Returns counts.
function M.deleteEntries(catalog, entries)
    local counts = { collections = 0, sets = 0 }
    catalog:withWriteAccessDo('WildID: delete empty collections', function()
        for _, e in ipairs(entries) do
            e.obj:delete()
            if e.kind == 'set' then
                counts.sets = counts.sets + 1
            else
                counts.collections = counts.collections + 1
            end
        end
    end, { timeout = 60 })
    return counts
end

return M
