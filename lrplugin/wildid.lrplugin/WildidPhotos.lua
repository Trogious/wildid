--[[
Which selected photos go to the daemon, and as what file (plan B3): the original when it is
on disk, else the Smart Preview DNG Lightroom keeps for offline originals (readable by the
engine like any DNG); each target also carries the catalog GPS for auto-geo. Pure Lua: the
file-exists check is injected (LrFileUtils.exists in the plugin, a table lookup in tests).
]]

local Geo = require 'WildidGeo'

local M = {}

--- The Smart Preview DNG of a photo whose original is offline, when Lightroom has one.
function M.smartPreviewPath(photo, exists)
    local ok, info = pcall(photo.getRawMetadata, photo, 'smartPreviewInfo')
    if not ok or type(info) ~= 'table' then return nil end
    local path = info.smartPreviewPath
    if type(path) == 'string' and path ~= '' and exists(path) then return path end
    return nil
end

--- photos: LrPhoto-like objects. Returns the targets ({photo, path, gps, smart}), the
--- skipped counts {virtual, video, missing} and how many targets use a Smart Preview.
function M.selectTargets(photos, exists)
    local targets, skipped, smart = {}, { virtual = 0, video = 0, missing = 0 }, 0
    for _, photo in ipairs(photos) do
        if photo:getRawMetadata('isVirtualCopy') then
            skipped.virtual = skipped.virtual + 1
        elseif photo:getRawMetadata('fileFormat') == 'VIDEO' then
            skipped.video = skipped.video + 1
        else
            local path = photo:getRawMetadata('path')
            local usedSmart = false
            if not (type(path) == 'string' and path ~= '' and exists(path)) then
                path = M.smartPreviewPath(photo, exists)
                usedSmart = path ~= nil
            end
            if path then
                targets[#targets + 1] = {
                    photo = photo,
                    path = path,
                    smart = usedSmart,
                    gps = Geo.coords(photo:getRawMetadata('gps')),
                }
                if usedSmart then smart = smart + 1 end
            else
                skipped.missing = skipped.missing + 1
            end
        end
    end
    return targets, skipped, smart
end

return M
