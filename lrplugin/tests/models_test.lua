-- WildidModels.lua (per-run model choice, VRAM gating, reptile warning) under plain Lua 5.1.
-- usage: lua5.1 models_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
local Models = require 'WildidModels'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

check(Models.DEFAULT == 'bioclip-2', 'default stays bioclip-2')
check(Models.isKnown('bioclip-2.5') and not Models.isKnown('bioclip-3'), 'known models')
check(Models.other('bioclip-2') == 'bioclip-2.5' and Models.other('bioclip-2.5') == 'bioclip-2',
    'other model')
check(Models.MODELS[2].note:find('no reptiles', 1, true) ~= nil, '2.5 subscript names the gap')
check(Models.MODELS[2].note:find('more accurate', 1, true) ~= nil,
    '2.5 subscript carries the measured accuracy claim (acceptance §E)')
check(Models.MODELS[1].note:find('GB VRAM', 1, true) and Models.MODELS[2].note:find('GB VRAM', 1, true),
    'subscripts carry VRAM estimates')
check(Models.BOTH_MODELS_TITLE:find('GB VRAM', 1, true) ~= nil, 'both-models checkbox carries a VRAM figure')

-- VRAM gating: only a successful probe under the threshold disables the checkbox
local big = Models.gpuInfo({ vram = { device_name = 'RTX 4090', total_gb = 25.8, free_gb = 20 } })
check(big.allowed == true and big.known == true and big.note:find('25.8', 1, true), '24 GB card allowed')
local edge = Models.gpuInfo({ vram = { device_name = 'x', total_gb = 20, free_gb = 1 } })
check(edge.allowed == true, 'exactly 20 GB allowed')
local sixteen = Models.gpuInfo({ vram = { device_name = 'RTX 4080', total_gb = 17.2, free_gb = 15 } })
check(sixteen.allowed == false and sixteen.note:find('below the 20 GB', 1, true),
    '16 GB card (17.2 GB SI) disabled: both models under load measured 14.1 GB + desktop')
local small = Models.gpuInfo({ vram = { device_name = 'RTX 4070', total_gb = 12.9, free_gb = 10 } })
check(small.allowed == false and small.note:find('below the 20 GB', 1, true), '12 GB card disabled')
-- Apple Silicon: unified memory, reported as what Metal recommends staying under. Its own
-- wording and its own threshold, 30 GB: both models hold 20.1 GB there and Lightroom lives in
-- the same memory. 40.2 GB is what the one measured Mac reports (M5 Pro, 48 GB); the other
-- figures are test values, not machines.
local function unified(totalGb)
    return Models.gpuInfo({ vram = { device_name = 'Apple M5 Pro', total_gb = totalGb,
        free_gb = totalGb - 5, kind = 'unified' } })
end
local mac = unified(40.2)
check(mac.allowed == true and mac.known == true
    and mac.note == 'Apple M5 Pro, unified memory: 40.2 GB usable', 'unified memory note: ' .. mac.note)
check(unified(30).allowed == true, 'unified: exactly 30 GB allowed')
local under = unified(29.9)
check(under.allowed == false and under.note:find('unified memory: 29.9 GB usable', 1, true)
    and under.note:find('below the 30 GB needed for both models', 1, true),
    'unified: 29.9 GB disabled and the note names the 30 GB: ' .. under.note)
local asCard = unified(25.8)
check(asCard.allowed == false and asCard.note:find('below the 30 GB', 1, true),
    'unified: 25.8 GB, enough on a graphics card, is not enough of shared memory')
check(unified(17.9).allowed == false, 'unified: 17.9 GB disabled')
check(big.note:find('unified', 1, true) == nil, 'a CUDA card keeps the GPU wording')
check(Models.MIN_VRAM_FOR_BOTH_GB == 20 and Models.MIN_UNIFIED_FOR_BOTH_GB == 30,
    'the two thresholds: 20 GB of video memory, 30 GB of unified memory')

-- the dialog's texts: video-memory figures on a graphics card, the Mac's own on a Mac
local pc, onMac = Models.dialogTexts(false), Models.dialogTexts(true)
check(pc.models == Models.MODELS and pc.bothTitle == Models.BOTH_MODELS_TITLE
    and Models.dialogTexts(nil).models == Models.MODELS, 'not a Mac: the VRAM texts')
check(onMac.models[1].note:find('~12 GB memory', 1, true)
    and onMac.models[2].note:find('~13 GB memory', 1, true)
    and onMac.bothTitle == 'Keep both models loaded (~20 GB memory) \226\128\148 instant switching',
    'Mac: the footprint measured on Apple Silicon (11.7 / 13.4 / 20.1 GB)')
check(not (onMac.models[1].note .. onMac.models[2].note .. onMac.bothTitle):find('VRAM', 1, true),
    'Mac: no VRAM wording, there is no video memory')
for i = 1, 2 do
    check(onMac.models[i].value == pc.models[i].value and onMac.models[i].title == pc.models[i].title,
        'Mac: same models, same order')
    -- everything before the memory figure (the last " · " item) is the same claim
    local cut = '^(.*\194\183) [^\194]*$'
    check(onMac.models[i].note:match(cut) == pc.models[i].note:match(cut)
        and pc.models[i].note:match(cut) ~= nil, 'Mac: only the memory figure differs')
end
local cpu = Models.gpuInfo({ vram = nil, ready = true })
check(cpu.allowed == true and cpu.known == false, 'no CUDA: checkbox stays enabled')
local noServer = Models.gpuInfo(nil)
check(noServer.allowed == true and noServer.note:find('not running', 1, true), 'server down: unknown, enabled')
local junk = Models.gpuInfo({ vram = { total_gb = 'lots' } })
check(junk.allowed == true and junk.known == false, 'malformed probe treated as unknown')

-- reptile warning
check(Models.warningFor('bioclip-2.5', false, '') ~= '', '2.5 without geo warns (full TreeOfLife)')
check(Models.warningFor('bioclip-2.5', true, 'Mammalia,Reptilia,Aves') ~= '', '2.5 + Reptilia warns')
check(Models.warningFor('bioclip-2.5', true, 'mammalia, reptilia') ~= '', 'case-insensitive taxa')
check(Models.warningFor('bioclip-2.5', true, 'Mammalia,Aves') == '', '2.5 with reptiles excluded: quiet')
check(Models.warningFor('bioclip-2', false, '') == '', 'bioclip-2 never warns')
check(Models.warningFor('bioclip-2.5', 'none', 'Mammalia') == Models.REPTILE_WARNING_UNFILTERED,
    "mode 'none' warns")
-- the advice follows the mode: the taxa belong to a place list, and the dialog greys the Taxa
-- field out with the full TreeOfLife, so that text names the other model only
check(Models.warningFor('bioclip-2.5', 'none', 'Mammalia,Reptilia') == Models.REPTILE_WARNING_UNFILTERED
    and Models.warningFor('bioclip-2.5', false, '') == Models.REPTILE_WARNING_UNFILTERED
    and Models.warningFor('bioclip-2.5', nil, nil) == Models.REPTILE_WARNING_UNFILTERED,
    "mode 'none' (or a false or missing mode): its own text, whatever the taxa hold")
check(Models.REPTILE_WARNING_UNFILTERED:find('Pick bioclip-2 ', 1, true) ~= nil
    and Models.REPTILE_WARNING_UNFILTERED:find('taxa', 1, true) == nil,
    "mode 'none': the advice is the other model, never the greyed-out taxa")
check(Models.warningFor('bioclip-2.5', 'place', 'Mammalia,Reptilia') == Models.REPTILE_WARNING
    and Models.REPTILE_WARNING:find('exclude Reptilia from the taxa', 1, true) ~= nil,
    "mode 'place' with Reptilia: the advice names the taxa, which can be edited there")
check(Models.warningFor('bioclip-2.5', 'place', 'Mammalia,Aves') == '', "mode 'place' without Reptilia: quiet")
check(Models.warningFor('bioclip-2.5', 'gps', 'Mammalia,Reptilia') == Models.REPTILE_WARNING,
    "mode 'gps' with Reptilia: the standard warning")
check(Models.warningFor('bioclip-2.5', 'gps', 'Mammalia,Aves') == Models.REPTILE_WARNING_GPS,
    "mode 'gps' without Reptilia still warns: photos without a fix run unfiltered")
check(Models.warningFor('bioclip-2', 'gps', 'Mammalia') == '', 'bioclip-2 never warns in gps mode')

-- loaded lookup against a /health document
local health = { models = { ['bioclip-2'] = { loaded = true }, ['bioclip-2.5'] = { loaded = false } } }
check(Models.isLoaded(health, 'bioclip-2') == true, 'loaded true')
check(Models.isLoaded(health, 'bioclip-2.5') == false, 'loaded false')
check(Models.isLoaded(nil, 'bioclip-2') == false, 'no health -> not loaded')

if failures == 0 then
    print('ALL MODELS TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
