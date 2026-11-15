-- WildidCollections.lua against a fake Lightroom catalog. usage: lua5.1 collections_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
_PLUGIN = { path = arg[1] }

local C = require 'WildidCollections'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

-- ---------------------------------------------------------------- fakes
-- Sibling names are unique across collections and sets, case-insensitively, as in Lightroom.
-- Lightroom's rule (LrC 15.4.1): an object created inside a withWriteAccessDo call cannot be
-- queried, renamed, given photos or used as a parent until that call has returned. The fakes
-- raise the real messages so the module cannot break the rule unnoticed.
local FRESH = "can't get collection information after creating collection inside the same "
    .. 'withWriteAccessDo function'
local function settled(obj)
    if obj._fresh then error(FRESH, 2) end
end

local function fakeCollection(name, smart)
    return {
        _name = name, _photos = {}, _smart = smart == true,
        getName = function(self) settled(self); return self._name end,
        setName = function(self, newName) settled(self); self._name = newName end,
        isSmartCollection = function(self) settled(self); return self._smart end,
        getPhotos = function(self)
            settled(self)
            local out = {}
            for p in pairs(self._photos) do out[#out + 1] = p end
            return out
        end,
        addPhotos = function(self, photos)
            if self._fresh then error('Assertion failed: packed', 2) end
            for _, p in ipairs(photos) do self._photos[p] = true end
        end,
        removePhotos = function(self, photos)
            if self._fresh then error('Assertion failed: packed', 2) end
            for _, p in ipairs(photos) do self._photos[p] = nil end
        end,
        has = function(self, p) return self._photos[p] == true end,
        count = function(self)
            local n = 0
            for _ in pairs(self._photos) do n = n + 1 end
            return n
        end,
    }
end

local function fakeSet(name)
    return {
        _name = name, _sets = {}, _collections = {},
        getName = function(self) settled(self); return self._name end,
        getChildCollectionSets = function(self) settled(self); return { unpack(self._sets) } end,
        getChildCollections = function(self) settled(self); return { unpack(self._collections) } end,
    }
end

local function sibling(container, name)
    local lower = name:lower()
    for _, s in ipairs(container._sets) do
        if s._name:lower() == lower then return s, 'set' end
    end
    for _, c in ipairs(container._collections) do
        if c._name:lower() == lower then return c, 'collection' end
    end
    return nil
end

local function fakeCatalog()
    local root = fakeSet('<root>')
    return {
        _root = root,
        _writes = 0, _inWrite = false, _fresh = {},
        withWriteAccessDo = function(self, _name, fn, _opts)
            self._writes = self._writes + 1
            self._inWrite = true
            fn()
            self._inWrite = false
            for _, obj in ipairs(self._fresh) do obj._fresh = nil end
            self._fresh = {}
        end,
        -- objects made inside an open write block stay 'fresh' (unusable) until it returns;
        -- made outside one (test setup) they are usable at once, as after a block
        _born = function(self, obj)
            if self._inWrite then
                obj._fresh = true
                self._fresh[#self._fresh + 1] = obj
            end
            return obj
        end,
        createCollectionSet = function(self, name, parent, _ret)
            if parent and parent._fresh then error(FRESH, 2) end
            local container = parent or self._root
            local found, kind = sibling(container, name)
            if found then return kind == 'set' and found or nil end
            local set = fakeSet(name)
            container._sets[#container._sets + 1] = set
            return self:_born(set)
        end,
        createCollection = function(self, name, parent, _ret)
            if parent and parent._fresh then error(FRESH, 2) end
            local container = parent or self._root
            local found, kind = sibling(container, name)
            if found then return kind == 'collection' and found or nil end
            local col = fakeCollection(name)
            container._collections[#container._collections + 1] = col
            return self:_born(col)
        end,
    }
end

-- a set or collection by '/'-path from a container (nil when a step is missing)
local function at(container, path)
    local obj = container
    for part in path:gmatch('[^/]+') do
        if not obj or not obj._sets then return nil end
        obj = sibling(obj, part)
    end
    return obj
end

local function fakePhoto(species, status)
    return {
        _species = species, _status = status,
        getPropertyForPlugin = function(self, _plugin, id)
            if id == 'wildidSpecies' then return self._species end
            if id == 'wildidStatus' then return self._status end
            return nil
        end,
    }
end

local EM = ' \226\128\148 '

-- ---------------------------------------------------------------- naming and ranks
check(C.collectionName('Panthera onca', 'Jaguar') == 'Panthera onca' .. EM .. 'Jaguar',
    'name with common')
check(C.collectionName('Panthera onca', nil) == 'Panthera onca', 'name without common')
check(C.collectionName('Panthera onca', '') == 'Panthera onca', 'name with empty common')
check(C.classOf({ class = 'Mammalia' }) == 'Mammalia', 'class from the prediction')
check(C.classOf({ species = 'Arapaima gigas' }) == C.NO_CLASS_NAME, 'missing class -> placeholder')
check(C.classOf({ class = '' }) == C.NO_CLASS_NAME, 'empty class -> placeholder')
check(C.genusOf({ genus = 'Panthera', species = 'Panthera onca' }) == 'Panthera',
    'genus from the prediction')
check(C.genusOf({ species = 'Arapaima gigas' }) == 'Arapaima', 'missing genus -> first word')
check(C.genusOf({ genus = '', species = 'Charis Sarota acanthoides' }) == 'Charis',
    'subgenus spelling -> first word')

-- ---------------------------------------------------------------- prepare
local cat = fakeCatalog()
local state, err = C.prepare(cat, ' Trips / Pantanal 2026 ')
check(state ~= nil, 'prepare: ' .. tostring(err))
check(state.path == 'Trips/Pantanal 2026', 'nested path normalised')
check(at(cat._root, 'Trips/Pantanal 2026') ~= nil, 'nested sets created')
check(cat._writes == 2, 'prepare used one write block per path level')

local state2 = C.prepare(cat, 'Trips/Pantanal 2026')
check(state2.set == state.set, 'prepare reuses the existing set')

local stateDefault = C.prepare(fakeCatalog(), '')
check(stateDefault.path == 'WildID', 'empty path falls back to WildID')

-- ---------------------------------------------------------------- filing + flat-layout migration
-- The set already holds plugin 0.3.1's flat layout: species collections and a class
-- collection directly under it, plus _review.
local root = state.set
local flatJaguar = cat:createCollection('Panthera onca' .. EM .. 'Jaguar', root, true)
local flatPuma = cat:createCollection('Puma concolor' .. EM .. 'Cougar', root, true)
local flatMammalia = cat:createCollection('Mammalia', root, true)
local reviewCol = cat:createCollection(C.REVIEW_NAME, root, true)

local jaguarPhoto = fakePhoto(nil, nil) -- never identified before
local reviewPhoto = fakePhoto(nil, nil)
local movedPhoto = fakePhoto('Puma concolor', 'ok') -- flat layout said puma, now a jaguar
local flatPhoto = fakePhoto('Panthera onca', 'ok') -- flat layout said jaguar, still a jaguar
local clearedPhoto = fakePhoto('Panthera onca', 'review') -- was review, now confident
local fishPhoto = fakePhoto(nil, nil)
flatJaguar:addPhotos({ flatPhoto })
flatPuma:addPhotos({ movedPhoto })
flatMammalia:addPhotos({ flatPhoto, movedPhoto })
reviewCol:addPhotos({ clearedPhoto })

local photos = {
    ['/a.arw'] = jaguarPhoto, ['/b.arw'] = reviewPhoto, ['/c.arw'] = movedPhoto,
    ['/d.arw'] = clearedPhoto, ['/e.arw'] = flatPhoto, ['/f.arw'] = fishPhoto,
}
local lookup = function(p) return photos[p] end

local jaguar = { species = 'Panthera onca', common_name = 'Jaguar', genus = 'Panthera', class = 'Mammalia' }
local doc = {
    results = {
        { path = '/a.arw', ok = true, review = false, predictions = { jaguar } },
        { path = '/b.arw', ok = true, review = true, predictions = {
            { species = 'Caiman yacare', common_name = '', genus = 'Caiman', class = 'Reptilia' } } },
        { path = '/c.arw', ok = true, review = false, predictions = { jaguar } },
        { path = '/d.arw', ok = true, review = false, predictions = { jaguar } },
        { path = '/e.arw', ok = true, review = false, predictions = { jaguar } },
        { path = '/f.arw', ok = true, review = false, predictions = {
            { species = 'Arapaima gigas', common_name = 'Arapaima' } } }, -- class and genus null -> nil
        { path = '/gone.arw', ok = false, error = 'boom' },
        { path = '/unknown.arw', ok = true, review = false, predictions = { jaguar } }, -- not in catalog
    },
}

local state3 = C.prepare(cat, 'Trips/Pantanal 2026')
check(state3.species['puma concolor'][1] == flatPuma, 'existing collections indexed by species')
local prev = C.previousMeta(doc, lookup)
check(prev['/c.arw'].species == 'Puma concolor', 'previousMeta reads old species')
check(prev['/d.arw'].status == 'review', 'previousMeta reads old status')
check(prev['/gone.arw'] == nil, 'failed results have no previous meta')

local writesBefore = cat._writes
local stats = { moved = 0, refiled = 0 }
C.fileChunk(cat, state3, doc, lookup, prev, stats)
check(cat._writes == writesBefore + 4,
    'class sets, genus sets, collections and filing in four transactions')

local jaguarLeaf = at(root, 'Mammalia/Panthera/Panthera onca' .. EM .. 'Jaguar')
check(jaguarLeaf ~= nil, 'species collection under class/genus sets')
check(jaguarLeaf and jaguarLeaf:has(jaguarPhoto) and jaguarLeaf:has(movedPhoto)
    and jaguarLeaf:has(clearedPhoto) and jaguarLeaf:has(flatPhoto),
    'photos filed into the species collection')
check(at(root, 'Reptilia/Caiman/Caiman yacare') ~= nil
    and at(root, 'Reptilia/Caiman/Caiman yacare'):has(reviewPhoto),
    'no-common-name species filed under binomial')
local fishLeaf = at(root, C.NO_CLASS_NAME .. '/Arapaima/Arapaima gigas' .. EM .. 'Arapaima')
check(fishLeaf ~= nil and fishLeaf:has(fishPhoto), 'no class -> placeholder set, genus from the binomial')
check(reviewCol:has(reviewPhoto), 'review photo filed into _review')
check(not reviewCol:has(clearedPhoto), 'cleared photo removed from _review')
check(at(root, C.REVIEW_NAME) == reviewCol and at(root, 'Mammalia/' .. C.REVIEW_NAME) == nil,
    '_review stays directly under the set')
check(not flatPuma:has(movedPhoto), 'photo removed from the earlier species collection')
check(not flatJaguar:has(flatPhoto), 'photo removed from the flat species collection')
check(stats.moved == 1, 'moved count: the puma that became a jaguar')
check(stats.refiled == 1, 'refiled count: the flat jaguar only (the cleared photo was in no collection)')
check(flatMammalia:getName() == 'Mammalia' .. C.FLAT_SUFFIX, 'flat class collection renamed aside')
check(flatMammalia:count() == 2, 'renamed flat class collection keeps its photos')
check(#stats.renamed == 1 and stats.renamed[1] == 'Mammalia (flat)', 'rename reported')
check(at(root, 'Mammalia') ~= nil and at(root, 'Mammalia')._sets ~= nil, 'class set created in its place')
check(stats.problems == nil, 'no problems: ' .. table.concat(stats.problems or {}, '; '))

-- idempotence: the same chunk again, with the metadata the run wrote, writes nothing
local prev2 = {}
for path, res in pairs({ ['/a.arw'] = 'ok', ['/b.arw'] = 'review', ['/c.arw'] = 'ok',
    ['/d.arw'] = 'ok', ['/e.arw'] = 'ok' }) do
    prev2[path] = { species = 'Panthera onca', status = res }
end
prev2['/b.arw'].species = 'Caiman yacare'
prev2['/f.arw'] = { species = 'Arapaima gigas', status = 'ok' }
writesBefore = cat._writes
local stats2 = { moved = 0, refiled = 0 }
C.fileChunk(cat, state3, doc, lookup, prev2, stats2)
check(cat._writes == writesBefore, 'a re-run of filed photos writes nothing')
check(stats2.moved == 0 and stats2.refiled == 0, 'same species again moves nothing')
check(jaguarLeaf:has(movedPhoto) and reviewCol:has(reviewPhoto), 'photos stay where they are')

-- a different common-name spelling for a known species (bioclip-2 "Common Ostrich" vs 2.5
-- "Common ostrich") reuses the existing collection: Lightroom's names are case-insensitive and
-- createCollection would fail with "name is not unique"
local otherSpelling = { results = { { path = '/a.arw', ok = true, review = false, predictions = {
    { species = 'Panthera onca', common_name = 'JAGUAR', genus = 'Panthera', class = 'Mammalia' } } } } }
local genusSet = at(root, 'Mammalia/Panthera')
local before = #genusSet._collections
C.fileChunk(cat, state3, otherSpelling, lookup, {}, { moved = 0, refiled = 0 })
check(#genusSet._collections == before, 'no new collection for a re-spelled common name')

-- a fresh prepare sees the tree the run built
local state4 = C.prepare(cat, 'Trips/Pantanal 2026')
check(state4.species['panthera onca'] ~= nil and #state4.species['panthera onca'] == 2,
    'tree and flat collections of a species both indexed')

-- ---------------------------------------------------------------- moves inside the tree
local cat2 = fakeCatalog()
local st = C.prepare(cat2, 'WildID')
local wild = st.set
local mammalia = cat2:createCollectionSet('MAMMALIA', wild, true) -- hand-made, other case
local puma = cat2:createCollectionSet('Puma', mammalia, true)
local pumaLeaf = cat2:createCollection('Puma concolor' .. EM .. 'Cougar', puma, true)
local aves = cat2:createCollectionSet('Aves', wild, true)
local jabiru = cat2:createCollectionSet('Jabiru', aves, true)
local jabiruLeaf = cat2:createCollection('Jabiru mycteria' .. EM .. 'Jabiru', jabiru, true)
local wasPuma = fakePhoto('Puma concolor', 'ok')
local wasBird = fakePhoto('Jabiru mycteria', 'ok')
local stillBird = fakePhoto('Jabiru mycteria', 'ok')
pumaLeaf:addPhotos({ wasPuma })
jabiruLeaf:addPhotos({ wasBird, stillBird })
local photos2 = { ['/p.arw'] = wasPuma, ['/b.arw'] = wasBird, ['/s.arw'] = stillBird }
local lookup2 = function(p) return photos2[p] end
local doc2 = { results = {
    { path = '/p.arw', ok = true, review = false, predictions = { jaguar } },
    { path = '/b.arw', ok = true, review = false, predictions = { jaguar } }, -- 2.5 says mammal
    { path = '/s.arw', ok = true, review = false, predictions = {
        { species = 'Jabiru mycteria', common_name = 'Jabiru', genus = 'Jabiru', class = 'Aves' } } },
} }
st = C.prepare(cat2, 'WildID')
local statsM = { moved = 0, refiled = 0 }
C.fileChunk(cat2, st, doc2, lookup2, C.previousMeta(doc2, lookup2), statsM)
local leaf2 = at(wild, 'MAMMALIA/Panthera/Panthera onca' .. EM .. 'Jaguar')
check(leaf2 ~= nil and leaf2:has(wasPuma) and leaf2:has(wasBird), 'moved into the new species leaf')
check(not pumaLeaf:has(wasPuma), 'left the old species leaf in the same class')
check(not jabiruLeaf:has(wasBird) and jabiruLeaf:has(stillBird), 'left the old species leaf across classes')
check(statsM.moved == 2 and statsM.refiled == 0, 'both counted as moved')
local classSets = 0
for _, s in ipairs(wild._sets) do
    if s._name:lower() == 'mammalia' then classSets = classSets + 1 end
end
check(classSets == 1, 'an existing class set is reused whatever its case')

-- ---------------------------------------------------------------- blocked by a smart collection
local cat3 = fakeCatalog()
local st3 = C.prepare(cat3, 'WildID')
local smartAves = fakeCollection('Aves', true)
st3.set._collections[#st3.set._collections + 1] = smartAves
local oldJaguar = cat3:createCollection('Panthera onca' .. EM .. 'Jaguar', st3.set, true)
local birdPhoto = fakePhoto('Panthera onca', 'ok')
oldJaguar:addPhotos({ birdPhoto })
st3 = C.prepare(cat3, 'WildID')
local docB = { results = { { path = '/x.arw', ok = true, review = false, predictions = {
    { species = 'Jabiru mycteria', common_name = 'Jabiru', genus = 'Jabiru', class = 'Aves' } } } } }
local lookupB = function() return birdPhoto end
local statsB = { moved = 0, refiled = 0 }
C.fileChunk(cat3, st3, docB, lookupB, C.previousMeta(docB, lookupB), statsB)
check(statsB.problems and #statsB.problems == 1 and statsB.problems[1]:find('"Aves"', 1, true),
    'smart collection in the way is reported: ' .. table.concat(statsB.problems or {}, '; '))
check(smartAves:getName() == 'Aves', 'the smart collection is not renamed')
check(at(st3.set, 'Aves') == smartAves, 'no Aves set created')
check(oldJaguar:has(birdPhoto) and statsB.moved == 0, 'an unfiled photo stays where it was')

if failures == 0 then
    print('ALL COLLECTIONS TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
