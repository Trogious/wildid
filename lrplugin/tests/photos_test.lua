-- WildidPhotos.lua (target selection with the Smart Preview fallback) under plain Lua 5.1.
-- usage: lua5.1 photos_test.lua <plugin_dir>
package.path = arg[1] .. '/?.lua;' .. package.path
local Photos = require 'WildidPhotos'

local failures = 0
local function check(cond, msg)
    if not cond then failures = failures + 1; print('FAIL: ' .. msg) end
end

local function photo(meta)
    return { getRawMetadata = function(_, key) return meta[key] end }
end
local function throwing(meta)
    return { getRawMetadata = function(_, key)
        if key == 'smartPreviewInfo' then error('unsupported key') end
        return meta[key]
    end }
end
local onDisk = { ['D:\\trip\\a.ARW'] = true, ['C:\\cat\\Smart Previews\\b.dng'] = true }
local function exists(p) return onDisk[p] == true end

local photos = {
    photo({ path = 'D:\\trip\\a.ARW', gps = { latitude = -1.4, longitude = 35.2 } }),
    photo({ path = 'E:\\offline\\b.ARW',
        smartPreviewInfo = { smartPreviewPath = 'C:\\cat\\Smart Previews\\b.dng', smartPreviewSize = 1 } }),
    photo({ path = 'E:\\offline\\c.ARW' }),
    photo({ path = 'E:\\offline\\d.ARW', smartPreviewInfo = { smartPreviewPath = 'C:\\gone.dng' } }),
    photo({ path = 'D:\\trip\\a.ARW', isVirtualCopy = true }),
    photo({ path = 'D:\\trip\\v.MP4', fileFormat = 'VIDEO' }),
    throwing({ path = 'E:\\offline\\e.ARW' }),
}
local targets, skipped, smart = Photos.selectTargets(photos, exists)
check(#targets == 2, '2 targets (original + smart preview), got ' .. #targets)
check(targets[1].path == 'D:\\trip\\a.ARW' and targets[1].smart == false, 'original on disk is sent as is')
check(targets[1].gps[1] == -1.4 and targets[1].gps[2] == 35.2, 'catalog GPS rides along')
check(targets[2].path == 'C:\\cat\\Smart Previews\\b.dng' and targets[2].smart == true,
    'offline original with a Smart Preview: the DNG is sent')
check(targets[2].gps == nil, 'no catalog GPS -> nil (the daemon reads the file)')
check(smart == 1, 'one Smart Preview counted')
check(skipped.missing == 3, 'offline without a usable Smart Preview (none / gone / probe error) skipped: '
    .. skipped.missing)
check(skipped.virtual == 1 and skipped.video == 1, 'virtual copy and video skipped')
check(Photos.smartPreviewPath(photo({}), exists) == nil, 'no smartPreviewInfo -> nil')

if failures == 0 then
    print('ALL PHOTOS TESTS PASSED (' .. _VERSION .. ')')
else
    print(failures .. ' FAILURES')
    os.exit(1)
end
