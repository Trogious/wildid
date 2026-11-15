# WildID for Lightroom Classic

`wildid.lrplugin` sends the selected photos' original files (ARW and other RAW included — the
engine reads embedded previews) to the local `wildid serve` daemon and writes the results into
the catalog:

- keywords: `WildID|<class>|<genus>|<species>` — the same tree as the collections below —
  with the common name as a keyword synonym, plus `WildID|review` for photos worth a human
  look (low score, or the unconstrained top-1 is outside the place list), plus the flat tags
  `animals` (photo judged to contain an animal: detector verdict with crop on, else the score
  threshold) and `wildlife` (unless the species is domesticated). `WildID` and those two flat
  tags are the plugin's namespace (the server names it in each run document): a re-run
  replaces whatever an earlier run (or an imported wildid sidecar) left under the root — the
  old species keyword, a stale `WildID|review` — with the new suggestions, takes `animals` /
  `wildlife` off a photo the new run no longer judges to contain an animal (or now calls
  domesticated), and the summary counts the photos; every other keyword stays, so keywords of
  your own belong outside the root and off those two names;
- custom metadata (Metadata panel → WildID): species, common name, class, score, status
  (`ok` or `review` as the run wrote it, `reviewed` once you mark it), model, run —
  `WildID status` and `WildID class` are searchable, so a smart collection with
  *WildID status is review* collects the flagged photos;
- per-run model choice: a radio group **bioclip-2** (default — all taxa incl. reptiles,
  faster, ~7 GB VRAM) / **bioclip-2.5** (more accurate: +3.7 pp species top-1 on 401 of the owner's lemur
  frames, acceptance §E; no reptiles — reptile photos get confident wrong answers; larger,
  slower, ~10 GB VRAM), with a warning when 2.5 is picked while reptiles
  can be among the candidates. "Keep both models loaded (~14 GB VRAM)" warms the other
  model too, so switching is instant; the checkbox is **disabled when the daemon detected
  the GPU's memory and it is below 20 GB** (undetected memory leaves it enabled, and the rule
  is applied again to what the running server reports before the second model is loaded). On
  Apple Silicon there is no VRAM: the dialog quotes the memory figures measured on a Mac, the
  figure the rule looks at is the unified memory Metal recommends using, and the threshold is
  **30 GB**, because Lightroom and macOS share that memory. The
  daemon loads models lazily and keeps them until it exits (`--idle-exit`);
- species collections (on by default, configurable set path in the dialog): under the set the
  plugin keeps a taxonomy tree — a collection set per class, inside it one per genus, and at
  the bottom a collection per species holding the photos:
  `<set>/Mammalia/Panthera/Panthera onca — Jaguar`. Review photos also land in `<set>/_review`,
  next to the class sets. Selecting a class or genus set shows every photo below it, which is
  how a whole class is re-run through the other model: identify a new import with bioclip-2,
  select the `Mammalia` set, identify again with bioclip-2.5. A re-identification that changes
  a photo's species moves it out of the old species collection, wherever that sits under the
  set (the summary reports how many moved, and how many were re-filed from the flat layout of
  plugin 0.2.1–0.3.1 as they are re-run). The engine spells the class as iNaturalist does
  (GBIF's Squamata/Testudines/Crocodylia/Sphenodontia become Reptilia, in keywords too);
  ray-finned fish carry no class in the bioclip-2 table and go under `_no class`. The set path
  nests with `/` and is created when missing. Collections are regular (not smart) collections:
  delete or rename them freely — the plugin recreates what it needs. A flat class *collection*
  from 0.3.1 (`<set>/Mammalia`) would block the class *set* of that name, so the plugin renames
  it `Mammalia (flat)` and says so in the summary; delete it once its photos have been re-run;
- place filter per photo (plugin 0.3): the identify dialog's **Candidates** popup offers the
  full TreeOfLife, one prefetched place, or **each photo's GPS position** (the catalog's
  position — so what the Map module set counts too — at country or region level). The daemon
  resolves positions offline from 0.25° cells it cached, so prefetch them first: the prefetch
  dialog's "selected photos' GPS positions" source sends the distinct cells of the selection
  (one lookup each) and fetches their species lists. Photos without a position run unfiltered;
  photos in a cell nobody prefetched run unfiltered **and** get `WildID|review`; the summary
  counts both;
- Smart Preview fallback: an offline original that has a Smart Preview is identified from the
  Smart Preview DNG (the summary says how many); offline originals without one are skipped.

Menu entries (Library menu and File → Plug-in Extras):

- **Identify species with WildID…** — options dialog (candidates: none / a place / each
  photo's GPS, detector crop, exact detector resize, second opinion, top-k, review threshold,
  dry run), then chunked
  classification with progress and cancel. Whole chunks commit atomically; a cancel never
  leaves a half-written chunk.
  "Exact detector resize (meant to be the same on every computer)" is off by default and
  sends `crop_exact` with the request: the photo is reduced for the detector with OpenCV's
  exact resize, where the default leaves it to the computer's own OpenCV, which makes a Mac
  and a PC name about 2 % of the cropped photos differently. It is enabled when the crop or
  the second opinion is on. That it gives the same on a Mac and a PC is not measured yet
  (backlog item 13 in `species-id-mvp-plan.md`).
- **WildID: mark as reviewed** (needs a selection) — clears every review marker on the
  selected photos: they leave the `_review` collection under the set Identify files into, the
  `<root>|review` keyword comes off, and a WildID status of `review` becomes `reviewed` (so a
  smart collection can tell "a human looked" from "the engine was confident"). Collection and
  keyword changes are one undoable step; a bezel reports the counts. The next identification
  run re-flags a photo it still doubts.
- **WildID: prefetch place list…** — the one online step: fetch a place's species list
  (iNaturalist) + GBIF synonyms through the daemon — for a typed place or for the selected
  photos' GPS cells — so identify runs stay offline.
- **WildID: server status…** — show/start/stop the daemon.
- **WildID: delete empty collections…** — housekeeping after re-identifications: pick a
  collection set (combo box, default the one Identify files into) and delete every empty
  regular collection under it and every sub-set left with nothing in it (the genus and class
  sets a move emptied, the flat collections of the earlier layout). Smart collections,
  non-empty collections and the set itself are never touched; the list is shown for
  confirmation first.

## Install by hand (no installer)

1. Lightroom → File → Plug-in Manager → Add → pick this `wildid.lrplugin` folder
   (or copy it into the auto-load `Modules` folder:
   Windows `%APPDATA%\Adobe\Lightroom\Modules\`, macOS
   `~/Library/Application Support/Adobe/Lightroom/Modules/`).
2. Start the engine once: `uv run wildid serve` (the plugin can also start it if
   `engine.json` — see below — points at a start command).
3. Select photos → Library → Identify species with WildID…

## engine.json (written by the installer, optional by hand)

A small manifest next to `Info.lua` tells the plugin where the engine lives:

```json
{
  "start": "C:\\Users\\me\\AppData\\Local\\Programs\\WildID\\wildid-server-start.cmd",
  "cli": "C:\\Users\\me\\AppData\\Local\\Programs\\WildID\\wildid.cmd",
  "cacheDir": "C:\\Users\\me\\AppData\\Local\\wildid\\Cache"
}
```

On macOS `install.sh` writes the same three keys with paths in its own form:
`~/Library/Application Support/WildID/bin/wildid-server-start`, `…/bin/wildid` and
`~/Library/Caches/wildid` (written out in full, without the `~`).

Without it the plugin still finds a running server through the default cache location
(`%LOCALAPPDATA%\wildid\Cache\serve.json` on Windows, `~/Library/Caches/wildid/serve.json`
on macOS); it just cannot start the server for you.

## Tests (outside Lightroom)

`../tests/` holds plain-Lua tests runnable with any Lua 5.1 (`lua5.1` or `luajit`):
`json_test.lua` (the codec), `collections_test.lua` (class/genus/species filing against a fake
catalog, moves and the flat-layout migration), `models_test.lua` (model choice, VRAM gating, reptile warning), `cleanup_test.lua` (delete
empty collections), `geo_test.lua` (geo modes, classify/prefetch payloads, GPS cells) and
`photos_test.lua` (target selection with the Smart Preview fallback), `reviewed_test.lua`
(mark as reviewed: finding `_review`, membership by catalog id, the removal) and
`keywords_test.lua` (which keywords under the root a re-run takes off a photo) — all eight take
the plugin directory as the argument — and `lr_stub_test.lua`, an
integration test that drives the real `wildid serve` daemon over HTTP with curl standing in
for LrHttp (args: plugin dir, cache dir containing a live `serve.json`, a test image).
Catalog/dialog code paths still need the manual pass inside Lightroom.

## Requirements

- The wildid engine installed, with the model prefetched (`wildid prefetch`, or the
  `wildid setup` wizard). The detector crop stage needs `wildid prefetch --crop`; the second
  opinion needs `wildid prefetch --second-opinion`.
- Lightroom Classic 15 or newer: `Info.lua` pins `LrSdkMinimumVersion = 15.0`, the SDK the
  plugin was accepted on (LrC 15.4.1).
- Originals on disk are sent as they are; an offline original with a Smart Preview is
  identified from the Smart Preview DNG; offline originals without one are skipped and counted.
