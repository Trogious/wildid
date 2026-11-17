--[[
Per-run model choice (plan B4): the two models, their dialog subscripts, the memory rule for
keeping both loaded, and the reptile warning. Pure Lua (no Lightroom imports) so it can be
tested outside Lightroom; WildidIdentify.lua renders it.

The accuracy claim for 2.5 comes from acceptance §E (2026-10-25: +3.7 pp species top-1 on 401
owner lemur frames, corroborated at +2.3 pp on 385 JPG frames; docs/acceptance.md). VRAM figures
are the daemon's own usage above the desktop, measured 2026-10-25 after the detector stage was
sub-batched, with 24-photo crop requests (the plugin's chunk): bioclip-2 4.8 GB idle / 6.8 GB
under load, bioclip-2.5 7.7 / 9.7 GB, both loaded 12.3 / 14.1 GB. The subscripts quote the
under-load figures, rounded.

Apple Silicon has no video memory of its own: the models share the machine's memory with macOS
and Lightroom. The figures for it are the daemon's whole footprint under the same requests,
measured 2026-11-14 on the one Mac tried, an M5 Pro with 48 GB: bioclip-2 9.4 GB idle / 11.7 GB
under load, bioclip-2.5 12.9 / 13.4 GB, both loaded 19.2 / 20.1 GB (docs/acceptance.md).
]]

local M = {}

M.DEFAULT = 'bioclip-2' -- the repo default stays the default; the radio is per-run only

-- the memory figure each subscript ends on, per kind of memory (measurements in the header)
local MEMORY = {
    vram = { ['bioclip-2'] = '~7 GB VRAM', ['bioclip-2.5'] = '~10 GB VRAM', both = '~14 GB VRAM' },
    unified = {
        ['bioclip-2'] = '~12 GB memory',
        ['bioclip-2.5'] = '~13 GB memory',
        both = '~20 GB memory',
    },
}

local function modelsWith(memory)
    return {
        {
            value = 'bioclip-2',
            title = 'bioclip-2',
            note = 'all taxa incl. reptiles \194\183 faster \194\183 ' .. memory['bioclip-2'],
        },
        {
            value = 'bioclip-2.5',
            title = 'bioclip-2.5',
            note = 'more accurate (+3.7 pp on 401 owner lemur frames) \194\183 no reptiles \226\128\148 '
                .. 'reptile photos get confident wrong answers \194\183 larger, slower \194\183 '
                .. memory['bioclip-2.5'],
        },
    }
end

local function bothTitleWith(memory)
    return 'Keep both models loaded (' .. memory.both .. ') \226\128\148 instant switching'
end

M.MODELS = modelsWith(MEMORY.vram)
M.BOTH_MODELS_TITLE = bothTitleWith(MEMORY.vram)
-- the same texts on a Mac (Apple Silicon): unified memory and the figures measured there
M.MODELS_UNIFIED = modelsWith(MEMORY.unified)
M.BOTH_MODELS_TITLE_UNIFIED = bothTitleWith(MEMORY.unified)

--- The dialog's model texts for this machine. `unified` is true on a Mac; the dialog cannot
--- ask the server, which may not be running yet.
function M.dialogTexts(unified)
    if unified then
        return { models = M.MODELS_UNIFIED, bothTitle = M.BOTH_MODELS_TITLE_UNIFIED }
    end
    return { models = M.MODELS, bothTitle = M.BOTH_MODELS_TITLE }
end

-- Both models under 24-photo crop requests measured 14.1 GB above a 1.3 GB desktop (Linux, after
-- the detector fix; 13.8 GB above 1.9 GB on Windows), so a 16 GB card (17.2 GB in SI) would pass
-- a 14 GB gate with no headroom and run out of memory: the gate is 20 GB (SI, as /health reports
-- it), which keeps 24 GB cards on and 16 GB cards off.
M.MIN_VRAM_FOR_BOTH_GB = 20
-- Unified memory has its own gate (owner decision 2026-11-15, ADR 0008). /health reports what
-- Metal recommends a process stays under (40.2 GB on the 48 GB M5 Pro), and Lightroom and macOS
-- live in the same memory: both models hold 20.1 GB there, so the 20 GB gate would pass a Mac
-- with nothing to spare. The gate is 30 GB of that reported figure.
M.MIN_UNIFIED_FOR_BOTH_GB = 30
-- The reptile warning follows the Candidates mode, because the advice does: the taxa belong to a
-- place list, so with the full TreeOfLife there is none to take Reptilia out of (the dialog greys
-- the Taxa field out there) and only the other model helps.
M.REPTILE_WARNING_UNFILTERED = 'bioclip-2.5 has no reptiles: a reptile in this shoot gets a '
    .. 'confident wrong species. Pick bioclip-2 for reptiles.'
M.REPTILE_WARNING = 'bioclip-2.5 has no reptiles: a reptile in this shoot gets a confident '
    .. 'wrong species. Pick bioclip-2, or exclude Reptilia from the taxa.'
M.REPTILE_WARNING_GPS = 'bioclip-2.5 has no reptiles: photos without a GPS fix (or in a cell '
    .. 'not prefetched) run against the full TreeOfLife, where a reptile gets a confident '
    .. 'wrong species.'

function M.other(name)
    return name == 'bioclip-2' and 'bioclip-2.5' or 'bioclip-2'
end

function M.isKnown(name)
    for _, m in ipairs(M.MODELS) do
        if m.value == name then return true end
    end
    return false
end

--- What the daemon reported about the GPU: whether both models may be kept loaded, and a
--- one-line note for the dialog. Undetected memory leaves the checkbox enabled on purpose
--- (the rule only bites when detection succeeded and shows less than the threshold). On Apple
--- Silicon (vram.kind == "unified") memory is shared with the system and total_gb is what
--- Metal recommends a process stays under, not the machine's RAM: the note says so, and the
--- threshold is the one for unified memory.
function M.gpuInfo(health)
    local vram = health and health.vram
    if type(vram) == 'table' and type(vram.total_gb) == 'number' then
        local unified = vram.kind == 'unified'
        local needed = unified and M.MIN_UNIFIED_FOR_BOTH_GB or M.MIN_VRAM_FOR_BOTH_GB
        local allowed = vram.total_gb >= needed
        local note
        if unified then
            note = string.format('%s, unified memory: %s GB usable', tostring(vram.device_name),
                tostring(vram.total_gb))
        else
            note = string.format('GPU: %s, %s GB', tostring(vram.device_name),
                tostring(vram.total_gb))
        end
        if not allowed then
            note = note .. string.format(
                ' \226\128\148 below the %d GB needed for both models', needed)
        end
        return { allowed = allowed, known = true, note = note }
    end
    local note = health and 'GPU memory not detected (CPU, or probe failed)'
        or 'GPU memory unknown (server not running yet)'
    return { allowed = true, known = false, note = note }
end

local function normaliseMode(geoMode)
    if geoMode == true then return 'place' end
    if geoMode == false or geoMode == nil then return 'none' end
    return geoMode
end

--- Could a reptile be among the candidates? Without a geo filter the full TreeOfLife is in
--- play; with one ('place', or 'gps' for the photos that resolve), only when Reptilia is
--- among the taxa. geoMode: 'none' | 'place' | 'gps' (a boolean still means none/place).
function M.reptilesPossible(geoMode, taxa)
    if normaliseMode(geoMode) == 'none' then return true end
    return (taxa or ''):lower():find('reptilia', 1, true) ~= nil
end

function M.warningFor(model, geoMode, taxa)
    if model ~= 'bioclip-2.5' then return '' end
    local mode = normaliseMode(geoMode)
    -- the full TreeOfLife: no place list, so no taxa to edit, whatever the greyed-out field holds
    if mode == 'none' then return M.REPTILE_WARNING_UNFILTERED end
    if M.reptilesPossible(mode, taxa) then return M.REPTILE_WARNING end
    -- per-photo GPS: photos without a fix, or in a cell nobody prefetched, run unfiltered
    if mode == 'gps' then return M.REPTILE_WARNING_GPS end
    return ''
end

--- Is `name` loaded according to a /health document?
function M.isLoaded(health, name)
    local models = health and health.models
    return (models and models[name] and models[name].loaded == true) or false
end

return M
