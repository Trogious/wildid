--[[
WildID for Lightroom Classic: species identification via the local wildid daemon.
The engine (Python, BioCLIP + TreeOfLife) runs outside Lightroom as `wildid serve`;
this plugin sends selected photos' paths and writes the returned keywords + metadata.
]]

local menuItems = {
    {
        title = 'Identify species with WildID…',
        file = 'WildidIdentify.lua',
        enabledWhen = 'photosSelected',
    },
    {
        title = 'WildID: mark as reviewed',
        file = 'WildidMarkReviewed.lua',
        enabledWhen = 'photosSelected',
    },
    { title = 'WildID: prefetch place list…', file = 'WildidPrefetch.lua' },
    { title = 'WildID: server status…', file = 'WildidServerMenu.lua' },
    { title = 'WildID: delete empty collections…', file = 'WildidCleanup.lua' },
}

return {
    -- pinned to the SDK the plugin was accepted on (Lightroom Classic 15.4.1, 2026-10-25);
    -- older Lightroom versions refuse to load it rather than fail on a missing API
    LrSdkVersion = 15.0,
    LrSdkMinimumVersion = 15.0,
    LrToolkitIdentifier = 'dev.wildid.lightroom',
    LrPluginName = 'WildID',
    LrPluginInfoUrl = 'https://github.com/Trogious/wildid',
    LrMetadataProvider = 'Metadata.lua',
    LrLibraryMenuItems = menuItems,
    LrExportMenuItems = menuItems,
    VERSION = { major = 0, minor = 3, revision = 1, build = 0 },
}
