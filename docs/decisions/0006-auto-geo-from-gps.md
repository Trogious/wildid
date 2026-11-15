# 0006 — Per-photo geo filtering from GPS (auto-geo)

**Status:** accepted 2026-10-25 (wildid 0.3.0, plugin 0.3.0)
**Context:** MVP backlog #5 and plugin plan B3. A trip folder mixes countries (Kenya and
Madagascar in the owner's own samples), so one `--country` per run either misfilters or forces
the user to split folders by hand. Photos carry EXIF GPS; Lightroom also holds positions set
in the Map module.

## Decision

1. **The engine resolves positions; nothing else does.** `gps.py` reads EXIF GPS (via
   `exifread`, previews untouched), buckets positions into 0.25° cells and resolves each cell
   once through iNaturalist `GET /v1/places/nearby` (the `results.standard` list: admin level
   0 = country, 10 = state/province; the community list is ignored). The resolved place is
   cached in the geo cache under the cell key, so a classify run is cache-only — in the CLI
   and in the daemon (see the amendment below for how the CLI briefly differed).
2. **Country is the default level, region the only other one** (`--geo-level`). Finer levels
   (county, protected area) would multiply the lists to prefetch and iNaturalist coverage thins
   quickly below state level; a 0.25° cell (~28 km) is coarse enough that a trip resolves to a
   handful of lookups and fine enough that a state boundary is rarely straddled.
3. **One filter per place group.** The classifier holds one species filter, so `autogeo.py`
   partitions the photos by resolved place and runs the pipeline per group (`run_groups`); the
   output stays per photo (a `place:` line per block, `place` object in JSON).
4. **Misses never filter by a guess.** A photo without GPS runs against the full TreeOfLife and
   is not flagged (nothing is wrong with it). A photo whose cell was not prefetched, or was
   prefetched at the other level, runs unfiltered **and** is flagged for review, with the exact
   `wildid prefetch --gps-from` command in the reason, and the run's summary counts them. The
   run never fetches, with or without `--offline`: online work is `wildid prefetch --gps-from
   PATH` / `POST /prefetch {gps, level}` only (offline-first rule).
5. **The plugin forwards catalog GPS and stays a dumb writer.** It sends an optional `gps`
   map (path → [lat, lon]) per chunk; the daemon prefers it over EXIF (Map-module positions,
   Smart Preview DNGs) and reads the file for paths missing from it. Lightroom's prefetch dialog
   sends only the distinct cells of the selection.
6. **Smart Preview fallback** (same release): an offline original with a Smart Preview is sent
   as the Smart Preview DNG (`WildidPhotos.lua`); one without is skipped and counted.
7. **`LrSdkMinimumVersion` / `LrSdkVersion` pinned to 15.0**, the SDK the plugin was accepted on
   (LrC 15.4.1), instead of the 6.0/10.0 placeholders — an older Lightroom now refuses the
   plugin instead of failing on a missing API.

## Consequences

- New runtime dependency `exifread` (pure Python). RAW previews are still never demosaiced.
- Cache layout: `places.json` gains `gps:<lat>,<lon>:<level>` entries (cell corner, 2 dp); the
  species lists are the same per-place files, so a country prefetched by name is reused by
  auto-geo and vice versa.
- Result schema: `place` per result and `candidates.auto_level` / `auto_places` (additive;
  protocol 1). `review_reasons` can carry the prefetch hint.
- CLI contract only extended: `--geo-auto`, `--geo-level`, `prefetch --gps-from`.
- Measurement debt: top-1 agreement with the manual `--country` runs on `samples/` is expected
  to be identical for photos resolving to the same place (same lists); not yet re-measured on
  the Windows box — logged as an acceptance item.

## Amendment 2026-10-25 — the CLI is cache-only too

As first shipped, `cli.py` passed a live `INatClient` to auto-geo unless `--offline` was given
(inherited from the `--country` wiring), so `wildid PATH --geo-auto` resolved an uncached cell
online while the daemon never did. Found on the Linux re-run (`docs/acceptance.md`) when the
first `--geo-auto` run on two never-prefetched drone JPGs resolved both cells itself. The text
was first aligned to the code, then the owner asked why the CLI should fetch at all,
and the CLI was changed to match decisions 1 and 4 as written:

- A trip spans many 0.25° cells, each a separate `places/nearby` call. `--country` is one lookup
  that fails loudly (exit 1 with a prefetch hint); per-cell lookups fail quietly, photo by photo.
- Without network each uncached cell costs the 5 s connect timeout plus one retry before its
  photos fall back; twenty cells is minutes of waiting for nothing.
- A place first met during classify got its species lists online but never its GBIF synonyms
  (`resolve_names` is always offline there), so the candidate set differed from the prefetched
  one (Madagascar: 848 vs 860 species). Results depended on whether one had prefetched.
- One rule for both front ends: classify never goes online, `prefetch --gps-from` does; the
  flagged photos already carry that command, and the run's summary now counts them.

`--country` keeps its cache-first rule: one lookup, loud failure, `--offline` to forbid it.
