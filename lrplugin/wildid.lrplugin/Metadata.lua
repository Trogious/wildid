--[[
Custom metadata fields: what WildID concluded per photo. Searchable fields can drive smart
collections (e.g. wildidStatus is "review", wildidClass is "Mammalia") and the library filter.
wildidStatus is "ok" or "review" as the run wrote it, or "reviewed" once "WildID: mark as
reviewed" cleared the flag by hand.
schemaVersion 2 (plugin 0.3.1) added wildidClass. Fields are only added, never renamed, so no
updateFromEarlierSchemaVersion migration is defined; that the earlier fields' stored values
survive the bump is an acceptance item (docs/acceptance-lightroom.md, class/genus tree).
]]

return {
    metadataFieldsForPhotos = {
        { id = 'wildidSpecies', title = 'WildID species', dataType = 'string',
          searchable = true, browsable = true },
        { id = 'wildidCommonName', title = 'WildID common name', dataType = 'string',
          searchable = true, browsable = true },
        { id = 'wildidClass', title = 'WildID class', dataType = 'string',
          searchable = true, browsable = true },
        { id = 'wildidScore', title = 'WildID score', dataType = 'string',
          searchable = false },
        { id = 'wildidStatus', title = 'WildID status', dataType = 'string',
          searchable = true, browsable = true },
        { id = 'wildidModel', title = 'WildID model', dataType = 'string',
          searchable = false },
        { id = 'wildidRun', title = 'WildID run', dataType = 'string',
          searchable = false },
    },
    schemaVersion = 2,
}
