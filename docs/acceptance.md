# Acceptance log

Evidence for the per-phase acceptance criteria in `species-id-mvp-plan.md` §8, as run on the
owner's workstation (RTX 4090 24 GB, Gentoo Linux, Python 3.14.7, torch 2.14.1+cu130,
pybioclip 2.1.6). Commands are given as run; timings are wall-clock.

## Phase 0 — environment + model spike (2026-10-23)

- `uv run wildid tests/fixtures/bear.jpg` → 5 rows, top-1 *Ursus arctos* 1.000 (bioclip-2.5),
  7.2 s wall from a warm cache (model load 5.0 s). `--model bioclip-2`: *Ursus arctos* 0.830.
- Same command with the network disabled (`unshare -rn`, no interfaces): identical output,
  7.3 s, no start-up stall, with and without `--offline`.
- Missing model cache (`HF_HOME` pointed at an empty directory): exit 2, message names
  `wildid prefetch --model bioclip-2.5`.
- `--device cuda` without a GPU: exit 2. `--device cpu`: 6.9 s on 32 cores.
- `uv run wildid prefetch --model bioclip-2.5`: idempotent (nothing re-downloaded), and its
  child-process offline verification passes.
- The four 2.5 gates (shape, names, bear top-1 > 0.5, filter on the subclass):
  see `docs/decisions/0001-bioclip-25.md`.

## Phase 1 — single-file path, JPG + ARW (2026-10-23)

- Sony ARW (RX100 VII, 20 MP, Aruba 2022 set) versus a full-size demosaiced JPG export of the
  same frame: both top-1 *Leucophaeus atricilla* (laughing gull), 0.994 (ARW) / 0.965 (JPG).
- ARW load through the embedded 1616×1080 JPEG preview: 58 ms cold, 8–12 ms warm
  (acceptance: < 150 ms). The demosaic fallback was never taken.
- UTF-8 stdout/stderr forced at start-up (`wildid.env.force_utf8_stdio`); diacritics covered by
  `tests/test_output.py`.
- Note: the A7R V files on this machine contain no animals (owner's note), so the ARW check used
  an RX100 VII frame; both go through the same LibRaw preview path. Re-run on an A7R V wildlife
  frame when one is available.

## Phase 2 — directory mode (2026-10-23)

- `uv run wildid samples --k 1 -v` on the owner's 863 sample JPGs (1440×1800): 863 classified,
  0 failed, **43.0 img/s** (bioclip-2.5, batch 32, chunks of 128 decoded in a thread pool while
  the GPU works). RSS per chunk: 5,653 / 5,716 / 5,695 / 5,727 / 5,664 / 5,644 MB — flat.
- Mixed set of 550 files (300 sample JPGs + 250 Sony ARWs via symlinks): 550 classified,
  0 failed, 44.1 img/s.
- Smaller real folder (44 ARW/JPG, Aruba): 33.6 img/s; laughing gull frames at 0.995.
- Progress bar on stderr (transient, stopped while blocks print so a terminal stays clean);
  stdout holds only the header and the result blocks and diffs cleanly between runs.

## Phase 3 — geo filter (2026-10-23)

Model default switched to `bioclip-2` during this phase (ADR 0001 amendment: the 2.5 embedding
set has no reptiles). Numbers below are with `bioclip-2` unless stated.

- Live place resolution against iNaturalist: `--country Kenya` → 7042; `--country Kenya
  --region Narok` → "Kenya › Narok" (655 species, 531 candidates; cheetah frames *Acinonyx
  jubatus* 1.000); `--country Madagascar` → 844 candidates; `--continent Africa` → 6,300 species.
  Six continent ids pinned after `/v1/places/<id>` checks; Antarctica has none (ADR 0002).
- `uv run wildid samples/Kenya --country Kenya --anomaly-check --k 3` (199 frames): 1,498 iNat
  species → 1,325 candidates (173 not TreeOfLife names, 11.5 % drift, logged with a sample);
  spotted hyaena, hippopotamus, plains zebra at 1.000; 199 classified, 0 failed, 31.7 img/s
  including the unconstrained second pass; 39 frames carry the `⚠ not in Kenya list` line
  (frames without a clear animal, where the full TreeOfLife picks a plant or invertebrate).
- Out-of-region image: `tests/fixtures/bear.jpg --country Kenya` → constrained top-1 *Papio
  hamadryas* 0.191 and `unconstrained top-1: Ursus arctos (0.830)  ⚠ not in Kenya list`.
- Madagascar reptile and tortoise samples with `--country Madagascar`: Cuvier's Madagascar
  swift 0.991, Madagascar boa 0.937, panther chameleon, common flat-tail gecko, ploughshare and
  radiated tortoises; unconstrained the model had picked African and Galápagos tortoises, which
  the anomaly line reports. With `bioclip-2.5` the same frames return ticks, frogs and extinct
  walruses because its embedding set has no reptiles (0 of 230 Kenyan reptiles matched).
- Offline: the Kenya run repeated with `--offline` inside `unshare -rn` (no network interfaces)
  gives **byte-identical stdout**. An uncached place offline (`--country Peru --offline`) exits 1
  with ``'Peru' is not in the geo cache; run `wildid prefetch --country Peru` while online``.
- One transient iNaturalist connection drop was seen mid-fetch; `INatClient` now retries once.
- Tests: 49 unit tests with mocked HTTP (incl. a simulated no-network `ConnectionError`: cached
  place works, uncached place needs prefetch) plus 2 opt-in live model tests, all green.

## Phase 4 — hardening + docs (2026-10-23)

- `uv run ruff check src tests` clean, `uv run ruff format --check` clean; `uv run pytest`:
  49 passed, 2 live tests skipped by default (both pass with `WILDID_LIVE_TESTS=1`).
- `uv lock --check` up to date; `uv.lock` committed, resolved for Linux and Windows
  (`tool.uv.environments`), Python ≥ 3.12, torch 2.14.1+cu130 from the PyTorch index.
- Clean clone on Linux: `git clone` → `uv sync --frozen` (0.4 s from the uv cache) →
  `uv run wildid --version`, ruff, pytest (48 passed, 3 skipped: the ARW fixture is local-only)
  → `wildid tests/fixtures/bear.jpg --offline --country Kenya` inside `unshare -rn` works from the
  clone (model and geo caches live in the user's home, not the checkout).
- Not verified here: a Windows clone (no Windows machine in this session). The lock contains the
  cp312–cp314 `win_amd64` wheels for torch/torchvision/rawpy, so `uv sync` should resolve.
- `--help` lists every flag of plan §4 (classify: geo, model/runtime, output panels; prefetch:
  repeatable geo args, `--verify/--no-verify`); `--format`/`--output` stay reserved.
- README carries the canonical commands, the pre-trip prefetch checklist, the score-semantics
  caveat, cache locations and exit codes.

**MVP status:** all Phase 0–3 acceptance criteria pass on the owner's real photo set, including
a full directory run (199 Kenya frames, geo-filtered) with no network interfaces. Open item
carried from Phase 1: re-check an A7R V wildlife ARW when one is available.

## Post-MVP items 1–4 (2026-10-23)

Backlog order after the owner's reorder: 1 detector crop, 2 RAW formats, 3 precision, 4 second
opinion. Details and decisions in `docs/decisions/0003-post-mvp-stages.md`.

- **Item 2, RAW formats.** CC0 samples from raw.pixls.us (git-ignored, `tests/fixtures/raw/`):
  Nikon D7000 NEF, Canon EOS 6D CR2, Canon EOS M200 CR3, OM System OM-5 ORF, Fujifilm X-T20 RAF,
  Panasonic G9 RW2, DJI FC7303 DNG, Pixel 6 Pro DNG, Leica M240 DNG. All nine load through the
  embedded-preview path (2–84 ms, previews 680–3000 px); the Leica DNG's 160×120 preview trips
  the new small-preview rule and demosaics at half size (355 ms). `wildid tests/fixtures/raw`
  (directory mode, `--crop`) processes 9/9; `discover()` picks every extension in any case.
- **Item 3, precision.** 863 sample JPGs, batch 32: bioclip-2 fp32 77.3 img/s → tf32 85.9
  (863/863 same top-1) → fp16 95.7 (857/863); bioclip-2.5 48.6 → 56.3 (863/863) → 71.3
  (861/863); bf16 798/863 and 838/863, rejected. CLI on the Kenya folder: tf32 56.2 img/s,
  fp16 68.3 img/s, 197/199 agreement. Default is `auto` = tf32 on CUDA; the header shows it.
- **Item 1, detector crop.** MDv6-yolov9-c at its native 640 px: 133 img/s on 1440×1800 frames
  (the 1280-px yolov9-e: 23 img/s). Kenya folder, `--country Kenya --anomaly-check --crop`:
  10 of 199 top-1s change, mean top-1 score 0.840 → 0.857, frames under 0.50 from 23 to 19,
  including *Scleroptila shelleyi* 0.20 → *Acinonyx jubatus* 0.91 (a distant cheetah), impala
  0.46 → 0.84 and Jackson's hornbill 0.45 → 0.72; 16 frames had no animal above 0.2 and used the
  full frame. Crop + second opinion + anomaly pass: 26 img/s.
- **Item 4, second opinion.** Same Kenya run, SpeciesNet v4.0.3a on the crops: agrees 108,
  same genus 14, same family 19, same class 36 (SpeciesNet answering "Aves"), no taxon 7,
  `⚠ disagrees` 15 — mostly SpeciesNet errors on DSLR frames (white rhino → domestic cattle,
  mousebirds → seriema, Somali ostrich → rhea). On the Madagascar reptile samples it answers
  "blank" or iguana, as expected from a camera-trap model; the verdict line makes that visible.
- **Offline and prefetch.** `unshare -rn wildid samples/reptiles --crop --second-opinion
  --offline --country Madagascar` runs with no network interfaces (10.2 s). `wildid prefetch
  --crop --second-opinion` downloads 52 MB + 209 MB with pinned SHA-256, extracts SpeciesNet,
  and its verify child run carries `--crop --detector mdv6-yolov9-c --second-opinion`: ok.
- **Tests:** 80 passed, 2 live skipped by default; ruff clean. New runtime deps: ultralytics
  8.4.184 (+ opencv-python 5.0, matplotlib, polars), onnx2torch 1.5.15 (+ onnx 1.23).

## Loader-thread pre-shrink (2026-10-23)

- 863 sample JPGs, `bioclip-2`, default settings: 60.8 → **144.0 img/s**; `bioclip-2.5`:
  47.0 → **98.1 img/s**. Kenya folder with the Kenya geo list: 56–59 → 145 img/s. Crop +
  second opinion + geo: 27 → 30 img/s (detector and SpeciesNet dominate there).
- Agreement with the original path: `bioclip-2.5` 863/863 identical top-1, |Δscore| 0 (bit-exact);
  `bioclip-2` 847/863, max |Δscore| 0.044, all flips on near-ties (top-1 ≤ 0.44, gap ≤ 0.02).
  Kenya crop run re-run: 197/199 same top-1, 199/199 identical SpeciesNet lines.
- Loader threads swept at 16 / 8 / 4: 104 / 143 / 139 img/s (`bioclip-2`), 76 / 99 / 96
  (`bioclip-2.5`); default cap set to 8, `--workers` added.
- Tests: 85 passed (exactness test for the open_clip path, closeness bound for the squash path,
  loader `post` hook, parallel `prepare_inputs`); ruff clean.

## Post-MVP items 6 and 7 (2026-10-23)

Details in `docs/decisions/0004-synonyms-genus-mode.md`.

- **Item 6a, GBIF synonym mapping.** `wildid prefetch --country Kenya` looked up the 173 Kenyan
  names the model did not know (173 requests pairs, about 70 s, cached in
  `geo/gbif-names.json`): 94 now map to a model name. `wildid samples/Kenya --country Kenya`:
  candidate set 1,325 → 1,416 species, unmatched 173 → 79 (names GBIF lacks or GBIF-accepted
  names the model lacks). 8 of 199 top-1 answers changed, all to species that had been missing:
  both eland frames are now *Taurotragus oryx* (0.972 / 0.984; they were bongo 0.50 and beisa
  0.40), Rüppell's vulture 0.52 (was white-backed 0.43), red-billed oxpecker 0.70 (was
  yellow-billed 0.43). The same run with `--offline` inside `unshare -rn`: identical mapping,
  134 img/s, no network.
- **Item 6b, top-k dedupe.** Rows that are the same species (duplicate binomials: 115 in
  bioclip-2's table, 185 in 2.5's; 11,317 subgenus-style three-word names in bioclip-2's;
  GBIF synonyms in the cache) are merged with summed scores. On the 863 samples no raw top-3
  contained a duplicate, so results are unchanged there; the merge is unit-tested.
- **Item 7, `--geo-rank genus`.** Kenya: 643 genera known to the model → 6,615 candidate species
  (species rank: 1,416). Top-1 differs from species rank on 26 of 199 frames and the mean top-1
  score drops 0.845 → 0.737 (Grevy's zebra 0.89 becomes mountain zebra 0.63, for instance):
  the wider set dilutes confidence and admits non-local congeners, which is why species rank
  stays the default and the header says "genus level".
- Tests: 97 passed (GBIF client/cache/resolution with mocked HTTP, build_filter synonyms and
  genus mode, canonical names and merge, CLI geo wiring from a pre-populated cache), ruff clean.

## Lightroom integration 0.2.1 — Windows acceptance, sections 0/A/C/D (2026-10-25)

Owner's Windows 11 box (RTX 4090 24 GiB, driver 617.42, Lightroom Classic 15.4.1), fresh
install: uv 0.13.5 via winget, `uv sync --frozen` (Python 3.14 + torch 2.14.1+cu130, 21 s from
a warm uv cache). Checklist: `docs/acceptance-lightroom.md`; the in-Lightroom steps (B, C5–C9,
C11–C12, D install) are the owner's and are logged there when done.

- **0, setup.** `uv run pytest -q`: 134 passed, 1 failed on Windows only —
  `test_directory_top3_and_failure_summary` expected `sub/b.JPG` and got `sub.JPG`; fixed by
  making directory labels POSIX-style on every platform (`pipeline.label_of` →
  `relative_to(root).as_posix()`), so text/JSON output is now identical across OSes. With an A7R V
  ARW copied into `tests/fixtures/` and five Lightroom "Enhanced NR" DNGs into
  `tests/fixtures/raw/`: 142 passed, 2 live-model tests skipped. `ruff check .` clean.
  `cache_dir()` = `%LOCALAPPDATA%\wildid\Cache` (the plugin's built-in default). Prefetch:
  bioclip-2 4.47 GB in 19 s, bioclip-2.5 7.28 GB in 27 s, MDv6 52 MB, SpeciesNet 209 MB; Kenya
  1,499 species, Madagascar 992 (Reptilia 337); GBIF 108 of 311 unmatched names mapped (140 s);
  offline verify ok. All three Hugging Face repos are public (`gated=False`): no token was
  needed; the owner has since set `HF_TOKEN` locally and as a GitHub Actions secret (unused by the
  workflow today — nothing in CI downloads a model).
- **A, daemon with the real model.** `wildid serve -v`: port + serve.json path logged, model ready
  4.5 s after bind (8 s after launch). `/health`: ready, protocol 1, per-model states, GPU
  "NVIDIA GeForce RTX 4090, 25.8 GB total / 19.7 free" (SI). No token and wrong token → 401.
  `/classify` on three A7R V ARWs, crop on: hippopotamus 0.56, pin-tailed whydah 0.71, lion 0.88
  in 727 ms, keywords `WildID|class|family|species` + `animals` + `wildlife`. Same with
  `geo={country: Kenya}`: 1,417 candidates, scores 0.997 / 0.875 / 0.971, all `in_candidates`;
  `country: Peru` (uncached) → 400 `'Peru' is not in the geo cache; POST /prefetch …`.
  Stability: 349 Kenya files (327 ARW, 22 DNG) in 11 requests of 32, crop + Kenya filter:
  2.9–3.5 s per request, 9.9 img/s end to end on 61 MP RAWs; daemon RSS 3.1–3.5 GB, GPU memory
  flat at 12.0 GB total used (9.6 GB after the first 16-photo request; the detector loads
  lazily on the first crop request). `--idle-exit 60`: exited after 67 s idle, serve.json removed,
  GPU used back to 1.87 GB (desktop + Lightroom). Second `wildid serve` while one runs: exit 1,
  "already running (pid 14380, port 64612)".
- **B, plugin inside Lightroom (in progress, LrC 15.4.1).** Plugin added from the checkout via
  Plug-in Manager; the daemon was started by the plugin through `engine.json` (ensureReady →
  ready). First Identify run failed with Lightroom's "An internal error has occurred:
  Assertion failed: packed" after the options dialog. Traced with a plain-file log to the
  commit of the keyword transaction: **Lightroom asserts at commit when a keyword (or
  collection) created inside a `withWriteAccessDo` call is also attached to photos in that
  same call**, which is exactly the first run on an empty catalog (the Lua tests' fake catalog
  cannot see this). Fix: per chunk, four transactions — create keywords, attach keywords,
  create collections, file photos — plus synonym lists copied into plain tables before they
  reach the SDK. After the fix, 5 mixed photos: 5 identified, 2 flagged, 0 failed; keyword
  tree `WildID → Mammalia/Aves → family → species` with the common name as synonym,
  `animals`/`wildlife` flat on 4 (the no-detection frame has neither), `WildID|review` on 2,
  six collections under `WildID` (five species + `_review` with 2) — all confirmed by the
  owner in the Lightroom UI. (Reading a copy of the open catalog's SQLite file is not a
  reliable check for collection membership: the WAL copy was inconsistent.)
  Second finding (B4 run with bioclip-2.5): "name is not unique: Struthio camelus — Common
  ostrich" — the two models spell common names differently and Lightroom compares collection
  names case-insensitively, so creating the 2.5-spelled collection next to the bioclip-2 one
  failed. Fix: a species' existing collection is reused whatever the common-name spelling
  (prefix match on the binomial, case-insensitive name match); Lua test added.
  Then, owner-run and passed: model radios + GPU line + reptile warning; 2.5 run with both
  models kept loaded; geo prefetch Kenya › Narok from the plugin (655 species, matching the
  Linux number) and a 20-photo Narok run (3 flagged); move-on-rerun ("1 moved from an earlier
  species"); 200-photo run canceled at exactly 96 = 4 whole chunks of 24, re-run idempotent;
  server killed mid-run → clean dialog, auto-restart on the next Identify; diacritics folder,
  virtual copy, missing original and dry run all counted correctly; server auto-start from
  the plugin. Two more fixes from this pass: `LrDialogs.showError` showed only the first
  paragraph, hiding the "N photos already tagged" count → a titled message that leads with
  the count; and `start "" "<launcher>.cmd"` runs a batch file under `cmd /K`, leaving its
  console open → the plugin now starts the launcher through `cmd /c` (no window left).
  Failures were located with a temporary plain-file trace in the plugin (Lightroom's own
  `LrLogger` logfile never appeared); the instrumentation was removed before committing.
- **C, sidecars on the owner's RAW copies** (`sample-arw/`: 69 ARW, 5 DNG, 3 TIF, Kenya +
  Madagascar mixed, so no geo filter). Dry run: "xmp dry run (nothing written): 69 written,
  5 unsupported", 0 files on disk. Real run with `--format json --output`: 69 `.xmp`, 74 results
  ok, 31 `review: true` (all "score below 0.5" — mostly Lepilemur/Propithecus lemurs scored over
  the full TreeOfLife without a place list, plus 8 frames where the detector found no animal);
  TIFs are not discovered (not an input format), DNGs classified but not sidecar'd.
  Sidecar content checked: `dc:subject` species + common name + `animals`/`wildlife`
  (+ `review`), `lr:hierarchicalSubject` `WildID|Mammalia|Felidae|Panthera leo` plus the two flat
  tags, `wildid:*` provenance; 63 of 69 carry `animals`/`wildlife` (the 6 no-detection ARWs
  carry neither), 29 carry `WildID|review` = the `Review=True` count. Re-run: "0 written,
  69 skipped (sidecar exists; --xmp-mode merge to update)", SHA-256 and mtime of all 69 unchanged.
  Second set for the Lightroom pass: the owner re-cut `sample-arw/` into 20 labelled subfolders
  (152 ARW, 5 DNG, 3 TIF): 152 sidecars, 82 review, 134 with `animals`/`wildlife` (no place
  filter: Kenya and Madagascar mixed). Imported with Add: common names arrive as flat top-level
  keywords next to `WildID` (sidecars cannot carry synonyms) — **owner decision: keep as is**,
  no `--xmp-common-names` flag.
  In-Lightroom steps 5–9 passed (no "changed on disk" badges after Add; real nested tree;
  review ≈ 82; `animals`/`wildlife` top-level and absent on no-detection frames; plugin fields
  empty). Merge on a genuine Lightroom sidecar (`lion/A7R00204`: +1.32 EV and a crop, Ctrl+S,
  then `--xmp-mode merge --keyword-root WildID2`, Read Metadata from File): develop edits and
  old keywords intact, `WildID2|…` added; the `wildid:*` block survived Lightroom's rewrite —
  as **attributes** of `rdf:Description`, which exposed a merge bug: `merge_into` only knew the
  element form and appended a second copy of every property. Fixed (attribute form is updated
  in place, stale element copies removed; unit test with a Lightroom-style rewritten sidecar).
- **D, installer (partial).** Inno Setup 6 is not on this box, so the local build was not run;
  the CI-built `WildID-Setup-0.2.1.exe` was downloaded and its SHA-256 matches
  `SHA256SUMS.txt`. Found and fixed: CI wrote the sums file with CRLF, which makes
  `sha256sum -c` fail on Linux/Git Bash — the workflow now writes LF. Install on this box: owner.
  Rebuilt after the plugin fixes: the install step `uv sync` failed with
  "The path cannot be traversed because it contains an untrusted mount point (os error 448)" on
  uv's managed-Python alias junction. The same `uv.exe` works from a shell and under a
  restricted token; a diagnostic build recorded the `[Run]` child's token as identical to a
  shell's — the difference is a process mitigation: Inno Setup 6.7+ (on the CI runner) enables
  Windows' RedirectionGuard on Setup, children inherit it, and it refuses junctions created by
  non-elevated users. Fix: `RedirectionGuard=no` in `wildid.iss` (per-user installer; nothing
  to protect), documented in `installer/README.md`. Rebuilt, silent install
  here: `uv sync` exit 0 in 33 s, venv present, `wildid.cmd --version` answers, `engine.json`
  correct. Owner's interactive install + Start menu → "WildID Server" then left a console open
  for the server's lifetime: uv's venv `pythonw.exe` is a console-subsystem trampoline, so
  `start "" pythonw.exe` allocates a console. The launcher now starts it via
  `Start-Process -WindowStyle Hidden` (verified: server healthy, no window handle); the dev
  launcher used by the checkout plugin was changed the same way. The owner then passed the rest
  of D with the rebuilt installer: plugin auto-loads from Modules, the Setup
  wizard finds the token, Start menu → WildID Server leaves no window, uninstall removes program
  and plugin and keeps both caches. Workflow trigger flipped to `push: tags: ['v*']`; version
  bumped to 0.2.2 (matching the plugin manifest).
- **E, bioclip-2.5 vs bioclip-2 on the owner's labelled mammal folders.** `samples/` is not on
  this box; the catalog's Madagascar folders are species-labelled lemur sets (`redruffed` =
  *Varecia rubra*, `ringtail` = *Lemur catta*, `sportive` = genus *Lepilemur*, `verreaux` =
  *Propithecus verreauxi*; 401 ARWs). Real workflow flags: `--crop --country Madagascar --k 1`.

  | folder (n) | bioclip-2 top-1 | bioclip-2.5 top-1 | b2 review | b2.5 review |
  |---|---|---|---|---|
  | redruffed (32) | 30 (93.8 %) | 27 (84.4 %) | 3 | 2 |
  | ringtail (156) | 123 (78.8 %) | 141 (90.4 %) | 49 | 11 |
  | sportive (124, genus) | 85 (68.5 %) | 77 (62.1 %) | 121 | 59 |
  | verreaux (89) | 71 (79.8 %) · genus 87 | 79 (88.8 %) · genus 88 | 32 | 11 |
  | **all (401)** | **309 (77.1 %)** | **324 (80.8 %)** | 205 | 83 |

  bioclip-2.5 is ahead by **+3.7 pp** species top-1 over 401 frames (186 frames disagree), which
  meets the decision rule (≥ 2 pp over ≥ 200 frames). Caveats recorded with it: one trip and one
  family (Lemuridae/Lepilemuridae/Indriidae), and the candidate sets differ (Madagascar list →
  860 species known to bioclip-2 vs 575 to 2.5, so 2.5's softmax is spread over fewer names,
  which also explains its far lower review count). bioclip-2's characteristic miss is
  *Phaner parienti* (a fork-marked lemur) on 19 ring-tailed frames; 2.5's is *Eulemur* on red
  ruffed frames. Throughput is equal here (17–23 img/s, ARW decode bound). GPU memory, peak
  total used above the 1.9 GB desktop baseline during a crop run: bioclip-2 6.8 GB on a 32-frame
  folder, 10.5–13.0 GB on 89–156-frame folders (allocator cache grows with the run);
  bioclip-2.5 9.6 GB and 13.2–15.8 GB — consistently about 2.8 GB more than bioclip-2.
  Second pass **without the geo filter** (full TreeOfLife: 867,455 names for bioclip-2,
  794,878 for 2.5): bioclip-2 280/401 (69.8 %), bioclip-2.5 320/401 (79.8 %) — **+10.0 pp**,
  so the gap is not an artefact of the smaller filtered candidate set; the Madagascar list
  lifts bioclip-2 by 7.3 pp and 2.5 by only 1.0 pp. Daemon with both models (the plugin's
  "keep both loaded"), `nvidia-smi` total used above the 1.9 GB desktop baseline: bioclip-2
  idle 4.6 GB; after `POST /warmup bioclip-2.5` (7 s) 11.5 GB; after one 16-photo crop request
  per model 13.8 GB, `/health` free 10.1 GB of 25.8. Switching models between requests costs
  no load pause. The plugin's subscripts (~5 / ~8 / ~13 GB) stand as measured.

## Re-run on the re-cut sample set — Linux (2026-10-25)

The owner replaced `samples/` with two folders, each subfolder named for the animal or the trip:
`sample-jpg/` (863 JPG exports, 44 folders: 14 species-labelled lemur folders, fossa, mongoose,
reptiles, UK birds, `Kenya`, `KhaoYai`, `mg-*`, `uk-chester-zoo`) and `sample-arw/` (152 ARW +
5 DNG + 3 TIF in 20 folders, every ARW still carrying the section-C sidecar). Both are
git-ignored (`sample-jpg*/` added). Only 3 files carry GPS (2 drone JPGs, 1 phone DNG), so the
trip's `--country` stands in for `--geo-auto`. Same workstation as the MVP log (RTX 4090,
25.8 GB, Python 3.14.7, torch 2.14.1+cu130), wildid 0.3.0 plus the detector fix
below. Folders were grouped per country with symlink trees outside the repo; run outputs are in
`~/.cache/wildid-acceptance/` (and `old-session-runs/` there for the first pass).

- **Tests.** `uv run pytest -q`: 164 passed, 2 live skipped (165 with the new detector test);
  `WILDID_LIVE_TESTS=1 uv run pytest -k live`: 2 passed. `ruff check .` clean. `ruff format
  --check .` is **not** clean: 7 files from the 0.2.x/0.3.0 commits would be reformatted
  (`cli.py`, `keywords.py`, `serve.py`, `test_json_output.py`, `test_serve.py`, `test_xmp.py`,
  and code blocks in `species-id-mvp-plan.md`); formatting only, left for the owner.
- **Phase 2.** `wildid sample-jpg --k 1 -v`: 863 classified, 0 failed, 132.4 img/s, RSS flat
  at 2.45–2.56 GB over the seven chunks. `wildid sample-arw --k 1 -v`: 157 classified (152 ARW +
  5 DNG; TIF is not an input format), 0 failed, 59.3 img/s, embedded previews only.
- **Phase 3.** `sample-jpg/Kenya --country Kenya --anomaly-check --k 3`: 1,498 → 1,416
  candidates (94 GBIF synonyms, 79 unmatched), 199 classified, 0 failed, 76.8 img/s including
  the unconstrained pass, 32 `⚠ not in Kenya list` lines (39 before the synonym stage); eland
  *Taurotragus oryx* 0.98 / 0.97 / 0.53, hippo 0.996, spotted hyaena and plains zebra up to
  0.97 (the earlier 1.000s are gone: the candidate set is larger). The same run `--offline`
  inside `unshare -rn`: **byte-identical stdout** (47,768 bytes). `bear.jpg --country Kenya`:
  *Papio hamadryas* 0.183 and `unconstrained top-1: Ursus arctos (0.827) ⚠ not in Kenya list`.
  Madagascar reptiles and frogs (76 frames, 8 folders, `--country Madagascar --anomaly-check`):
  bioclip-2 answers panther and Parson's chameleons, Nile crocodile 9/9, *Uroplatus* and
  *Phelsuma* geckos, *Oplurus cuvieri* 6/7, *Chalarodon madagascariensis* 3/3, radiated and
  ploughshare tortoises, *Boophis* and *Mantella* frogs; 32 anomaly lines, 19 of them on
  crocodile and turtle frames whose unconstrained pass picks non-Malagasy congeners. bioclip-2.5
  on the same frames: frogs, indri, hamerkop and *Cryptoprocta ferox* for tortoises, 68 anomaly
  lines — the no-reptiles gap (ADR 0001), unchanged. `wildid prefetch --country Madagascar`
  (first GBIF pass on this box): 18 of 148 unmatched names mapped, candidates 848 → 860 (the
  Windows number); no reptile top-1 changed.
- **Items 1, 4, 6, 7.** `--geo-rank genus` on Kenya: 6,615 species of 643 genera, top-1 differs
  on 26/199, mean top-1 0.845 → 0.737 (as logged). `--crop` on Kenya (detector fix in place):
  11 top-1 changes, mean top-1 0.845 → 0.865, frames below 0.50 18 → 15, 16 frames without a
  detection, review 39 → 33, anomaly 32 → 28, cheetah *Scleroptila shelleyi* 0.21 → *Acinonyx
  jubatus* 0.90; 46.8 img/s. `--second-opinion`: agrees 107, same genus 12, same family 20, same
  class 36, no taxon 7, `⚠ disagrees` 17 (domestic cattle for rhino, seriema, guineafowl …);
  33.2 img/s. `unshare -rn … --crop --second-opinion --offline --country Madagascar` on the
  reptile folders: 76/76 classified, 26.2 img/s, no network.
- **Precision (863 JPGs, batch 32).** bioclip-2 fp32 119.3 → tf32 142.5 img/s (863/863 same
  top-1, max |Δscore| 0.007) → fp16 184.9 (855/863, 0.019); bioclip-2.5 76.5 → 97.3 (863/863,
  0.019) → fp16 145.5 (857/863, 0.021). Peak GPU memory fp32/tf32 6.9 and 10.0 GB, fp16 8.5 and
  12.5 GB. Loader threads 4 / 8 / 16: 141.3 / 142.5 / 101.8 img/s. Defaults stand (ADR 0003).
- **Sidecars (section C, Linux).** Copies of 22 ARW + 1 DNG + 1 TIF (lion, fossa, snake,
  landscape) with no sidecars: dry run "22 written, 1 unsupported", nothing on disk; real run
  22 sidecars, 11 `review` (both landscape frames: no detection, plants as top-1 at 0.12 / 0.01,
  review, no `animals`/`wildlife`); re-run "0 written, 22 skipped", files **byte-identical**;
  `--xmp-mode merge --keyword-root WildID2`: "22 merged", `WildID2|…` entries appended and
  `wildid:ProcessedAt` updated, develop and subject content otherwise untouched. Then on
  `sample-arw/` itself (152 sidecars from the earlier run): dry and real runs both "0 written,
  152 skipped, 5 unsupported"; SHA-256 and mtime of all 312 files unchanged.
- **Daemon (section A, Linux).** `wildid serve -v`: ready 6 s after launch (model 2.9 s);
  missing or wrong token → 401. Three lion ARWs, crop: *Panthera leo* 0.88–0.94 in 0.91 s;
  with `"geo": {"country": "Kenya"}` 0.97–0.99, 1,416 candidates, all `in_candidates`, 4.3 s;
  `"country": "Peru"` → 400 naming `POST /prefetch`; `"model": "bioclip-2.5"` loads it on
  demand (8.6 s incl. 4.5 s load; 1,216 candidates: no reptiles). `/health` then lists both
  models loaded, free 11.2 of 25.2 GB; `nvidia-smi` 14.0 GB used with both models and the
  detector (1.3 GB desktop included). `POST /shutdown` → 200, process exits, serve.json removed.
- **Auto-geo (ADR 0006) on the three GPS-tagged files.** The first `--geo-auto` run on
  `sample-jpg/mg-baobab4` (2 drone JPGs, cells never prefetched, no `--offline`) **resolved both
  cells online itself** (`GPS cell gps:-20.25,44.25 -> Madagascar (place 7783)`): `cli.py` passed
  a live `INatClient` unless `--offline`, inherited from the `--country` wiring, while ADR 0006
  says a classify run is cache-only and the daemon is. Settled the same day in two steps: the
  text was first aligned to the code, then the owner asked why the CLI should fetch at
  all and it was made cache-only like the daemon (ADR 0006 amendment has the reasons; the run's
  summary now counts the un-prefetched photos). Verified after the change on `sample-arw/lion`
  at region level, which no one had prefetched: with network available the run made **no
  request** (`places.json` unchanged), the GPS-tagged DNG ran unfiltered with the review reason
  `no cached place for GPS cell gps:-1.75,35.00 (region level); run wildid prefetch --gps-from`,
  the five ARWs without GPS ran unfiltered and unflagged (`note: no GPS in the file`), stderr
  carried `geo-auto: 1 photo(s) in cell(s) nobody prefetched ran unfiltered …`, and the JSON was
  byte-identical to the same run inside `unshare -rn`. Then the designed path: `prefetch
  --gps-from sample-arw/lion --geo-level region` → `Kenya › Narok` (place 96954), 655 species,
  51 of 72 unmatched names mapped through GBIF; the next classify filtered that DNG against
  634 candidates with no flag. `sample-jpg/mg-baobab4 --geo-auto` with its cells cached (from the
  first run, and `prefetch --gps-from` confirmed "2 position(s) in 2 cell(s) -> 1 place(s)"):
  Madagascar, 860 candidates, per-photo `place` block; the same run `--offline` inside
  `unshare -rn` works from the cache.
- **Found and fixed: `--crop` GPU memory grew with the loader chunk.** `wildid sample-jpg --crop
  --model bioclip-2.5` (863 frames) died with `torch.OutOfMemoryError` (a 3.12 GiB conv
  allocation) and the bioclip-2 run peaked at 24.6 GB on the 25.8 GB card, while the same runs
  without `--crop` peak at 6.9 / 10.0 GB. `Detector.detect` handed the whole loader chunk
  (4 × batch size = 128 frames) to one ultralytics `predict()` call, which runs a list as a
  single batch, so the detector's activations scaled with the chunk; the acceptance notes above
  had read the growth as allocator caching. The daemon never showed it because the plugin sends
  at most 32 photos per request. Fix: `DETECT_BATCH = 16` sub-batching in `detector.py` with a
  regression test. Every crop run below now fits: peak total used 8.1–8.9 GB for bioclip-2 and
  11.0–11.9 GB for bioclip-2.5 (9–24.6 GB before, growing with the folder), and the stage is
  faster (863 JPGs crop 61.8 → 70.9 img/s, 157 ARWs 27.0 → 31.8, Kenya crop 40.3 → 46.8).
  Letterbox padding depends on a frame's batch neighbours, so a few boxes move: same top-1 on
  845/863 JPGs and 154/157 ARWs, same detection flag on 860/863 and 157/157.
- **Section E on this box: bioclip-2.5 vs bioclip-2 on the owner's labelled folders.** Crop on,
  `--k 1`, folder name = ground truth, scored at the rank the name fixes (species; genus for
  `lemur-bamboo` and `lemur-mouse`; family for `mongoose`, `fruit-bat`, chameleons, geckos,
  iguanids, turtles, snakes, rhino; class for frogs and invertebrates). Same code for both
  models; candidate sets with the GBIF synonyms (Madagascar 860 / 575, Kenya 1,416 / 1,216).

  | set (frames) | place filter | bioclip-2 | bioclip-2.5 | Δ |
  |---|---|---|---|---|
  | 12 species-labelled lemur folders (385 JPG) | Madagascar | 270 (70.1 %) | **279 (72.5 %)** | **+2.3 pp** |
  | same, genus level | Madagascar | 348 (90.4 %) | 346 (89.9 %) | −0.5 pp |
  | same | none (full TreeOfLife) | 253 (65.7 %) | **278 (72.2 %)** | **+6.5 pp** |
  | all 14 lemur folders at their rank (411 JPG) | Madagascar | 295 (71.8 %) | 302 (73.5 %) | +1.7 pp |
  | review flags on those 411 | Madagascar | 188 | 85 | |
  | Fossa 36 + mongoose 26 + fruit-bat 3 (65 JPG) | Madagascar | 63 | 65 | +3.1 pp |
  | `sample-arw/lemur`, family level (55 ARW) | Madagascar | 54 | 54 | 0 |
  | Kenya mammals, 7 folders (22 ARW) | Kenya | 21 | 19 | −9.1 pp |
  | Madagascar reptiles, 6 folders (63 JPG) | Madagascar | **63 (100 %)** | 0 | −100 pp |
  | same | none | 44 (69.8 %) | 0 | |
  | UK birds: puffin, gannet, eagle (15 JPG) | none | 14 | 14 | 0 |
  | insects and crabs, class level (8 JPG) | none | 8 | 8 | 0 |

  Reading: on the owner's lemur frames 2.5 is ahead again, +2.3 pp species top-1 over 385
  frames with the place list and +6.5 pp without it — the same direction and shape as the
  Windows run on 401 ARWs (+3.7 / +10.0 pp): the Madagascar list lifts bioclip-2 by 4.4 pp and
  2.5 by 0.3 pp, and 2.5 flags fewer than half as many frames for review. The decision rule
  (≥ 2 pp over ≥ 200 frames) is met, narrowly, so the radio subscript's claim stands with its
  caveats: one trip, one family group, and both models fail the same way on the hard folders
  (`lemur-brown` 1/32 vs 3/32 at species, both naming other *Eulemur*, 28 vs 31 at genus; the
  two sportive-lemur folders 2/34 vs 8/34 at species, 22 vs 20 at genus). Outside lemurs the
  picture is mixed: 2.5 is perfect on fossa, mongoose and fruit bat but misses an eland
  (*Buphagus africanus* 0.94) and a gerenuk (*Beatragus hunteri* 1.00) on the Kenya ARWs, and it
  stays at 0 % on every reptile folder, where bioclip-2 gets all 63 Madagascar frames right with
  the list (44 without). Both models call the `masai-giraffe` ARW *Giraffa reticulata* 1.00.
  Default unchanged (ADR 0001). GPU, CLI crop runs, total used incl. the 1.3 GB desktop:
  bioclip-2 8.1–8.9 GB, bioclip-2.5 11.0–11.9 GB (post-fix).
- **Daemon memory per model after the fix, for the plugin's subscripts.** `wildid serve`,
  24-photo crop requests on 61 MP ARWs (the plugin's chunk size), `nvidia-smi` usage above the
  1.3 GB desktop, flat across repeated requests: bioclip-2 4.8 GB idle → 6.8 GB under load;
  bioclip-2.5 alone 7.7 → 9.7 GB; both loaded 12.3 GB idle → 14.1 GB under load (`/health` free
  9.9 of 25.2 GB). Windows had 4.6 / 11.5 / 13.8 GB above a 1.9 GB desktop with 16-photo
  requests, so the fix changes little for the daemon (its requests were already small). The
  subscripts now quote the under-load figures, ~7 / ~10 / ~14 GB (`WildidModels.lua`,
  `lrplugin/README.md`); the 20 GB gate stands: both models plus a desktop is 15.4–16 GB, which
  leaves a 16 GB card (17.2 GB SI) no headroom.

## Windows box re-synced for the 0.2.3-0.3.1 Lightroom items (2026-11-02)

The checkout of that day on the acceptance box (uv 0.13.5, LrC 15.4.1). `uv sync --frozen` added
`exifread`; `uv run pytest`: 169 passed, 2 live-model tests skipped, after one test fix —
`test_set_version` copied the checkout's CRLF `uv.lock` and asserted an LF string (the script
itself handles both). `ruff check` clean. The eight plain-Lua plugin suites pass under lupa's
bundled Lua 5.1 and LuaJIT 2.1 (no luajit binary on this box). `wildid prefetch --model all
--crop --second-opinion --country Kenya --country Madagascar`: everything cached, both models
verified offline against the new engine (35 s). Daemon smoke from the checkout: `/classify` with
crop returns the new hierarchy (`WildID|Mammalia|Panthera|Panthera leo`; a chameleon frame comes
back as class `Reptilia` → `WildID|Reptilia|Chamaeleo|…`) and the run document's `keywords`
namespace; `geo: {auto: true, level: country}` on files without GPS runs unfiltered with
`place.note = "no GPS in the file"` and no review flag, as ADR 0006 specifies; clean shutdown.

**Finding for the auto-geo items:** none of the owner's A7R V / RX ARWs carry EXIF GPS (40 files
sampled in each of the ten catalog folders: 0 with a fix), and the test catalog holds one
positioned photo — the Pixel DNG in `sample-arw/lion`, which the engine reads as
(-1.523, 35.114), Maasai Mara. The in-Lightroom auto-geo checks therefore have to use positions
set in the Map module (catalog GPS wins over EXIF) or phone DNGs; the CLI `--geo-auto` path can
be shown on that DNG.

**First Identify with the class/genus tree (plugin 0.3.1+) failed:** "An internal error has
occurred: can't get collection information after creating collection inside the same
withWriteAccessDo function". Two offenders in `WildidCollections.lua`, both the same Lightroom
rule as October's "packed" assertion: the genus set was created under a class set created in
the same transaction, and `isSmartCollection()` was asked of collections created moments
earlier in that transaction (two photos of one species, or two review photos, in a chunk).
Fix: class sets, genus sets, collections and filing in four transactions (a set path one level
per transaction), smart flags cached when the set is indexed; the test's fake catalog now
raises Lightroom's messages for all three same-transaction misuses and reproduced the failure
against the old code before the fix.

## Linux re-run of the full sample matrix at 0.3.1 (2026-11-03)

Version 0.3.1 on the Linux workstation (RTX 4090 25.8 GB, Python 3.14,
torch 2.14.1+cu130), caches as the October runs left them, every classify run offline. Driver,
scorer, comparison script and all run outputs are in `~/.cache/wildid-acceptance/2026-11-03/`
next to the October files; the per-country trees are real directories of file symlinks
(`discover()` uses `os.walk`, which does not descend into directory symlinks).

- **Suites.** `uv sync`; `WILDID_LIVE_TESTS=1 uv run pytest`: 175 passed, live tests included;
  `ruff check` and `ruff format --check` clean. The eight plain-Lua plugin suites pass under
  LuaJIT 2.1 (installed on this box the same day; under lua5.4 `collections_test.lua` needs
  `-e 'unpack = table.unpack'`, a 5.1-ism of its fake catalog).
- **Regression against the October JSONs (same inputs, 0.3.0 + detector fix → 0.3.1).** Crop
  runs on all 863 JPGs and all 157 ARW/DNG with both models, the Madagascar JPG tree (554), the
  Kenya ARW tree (24), the Madagascar ARW tree (96) and the Kenya crop run (199): identical top-1
  on every frame, max |Δscore| 0.000, identical review and detection flags. The keyword
  hierarchy and class-spelling changes since 0.3.0 touched no classification.
- **Phase 2.** `sample-jpg --k 1 -v`: 863 classified, 0 failed, 136.5 img/s, RSS 2.49–2.55 GB
  across the seven chunks; `sample-arw`: 157 classified, 0 failed, 52.9 img/s.
- **Phase 3.** Kenya + anomaly check: 1,416 candidates, 32 anomaly lines, 47,768 bytes of
  stdout, byte-identical with `--offline` inside `unshare -rn`; bear → *Papio hamadryas* 0.183
  and *Ursus arctos* 0.827 flagged. Madagascar reptiles + frogs (76 frames): bioclip-2 32
  anomaly lines and the October species; bioclip-2.5 68 lines of frogs, fossa and birds (no
  reptiles). `KhaoYai` against the cached `Thailand › Nakhon Ratchasima` list, offline: 511
  candidates, 20 classified, 8 anomaly lines.
- **Items 1, 4, 7.** Genus rank on Kenya: 26/199 top-1 changes, mean 0.845 → 0.737. Crop: 11
  changes, mean 0.845 → 0.865, below 0.50 18 → 15, 16 frames without a detection, review 33,
  anomaly 28, 46.7 img/s. Second opinion: agrees 107, same genus 12, same family 20, same class
  36, no taxon 7, disagrees 17; 32.5 img/s. Reptiles with crop + second opinion inside
  `unshare -rn --offline`: 76/76, 29.9 img/s.
- **Section E** reproduced row for row (crop, `--k 1`, same code for both models): lemur species
  top-1 270 vs 279 of 385 with the Madagascar list (+2.3 pp), 253 vs 278 without it (+6.5 pp);
  all 14 lemur folders 295 vs 302 of 411; fossa/mongoose/fruit bat 63 vs 65; ARW lemurs 54/55
  both; Kenya ARW mammals 21 vs 19 of 22; reptiles 63/63 vs 0 (44/63 vs 0 unfiltered); UK
  birds 14/15 both; invertebrates 8/8 both. Peak GPU used (0.8 GB desktop included):
  bioclip-2 6.3 GB plain, 7.5–8.4 GB crop; bioclip-2.5 9.4 GB plain, 10.4–11.3 GB crop.
- **Precision (863 JPGs, batch 32).** bioclip-2 fp32 120.7 → tf32 138.8 img/s (863/863 same
  top-1, max |Δscore| 0.007) → fp16 179.9 (855/863, 0.019); bioclip-2.5 75.0 → 98.2 (863/863,
  0.019) → fp16 142.0 (857/863, 0.021). The 2026-10-25 figures, unchanged.
- **Auto-geo (cache-only).** `mg-baobab4 --geo-auto`: both photos → Madagascar, 860 candidates.
  `sample-arw/lion --geo-auto` at country level: the DNG → Kenya, 1,416; the five ARWs
  unfiltered with `no GPS in the file` and no flag; at region level the DNG → Kenya › Narok,
  634. Each run byte-identical to its `--offline` repeat inside `unshare -rn`.
- **Sidecars (copies: 12 ARW + 1 DNG + 1 TIF).** Dry run "12 written, 1 unsupported", nothing on
  disk; real run 12 sidecars with `WildID|Mammalia|Panthera|Panthera leo` + `animals`/`wildlife`
  (the two landscape frames: a plant top-1, `WildID|review`, no flat tags); re-run "0 written,
  12 skipped", SHA-256 unchanged; `--xmp-mode merge --keyword-root WildID2`: "12 merged",
  `WildID2|…` appended, nothing else changed. `sample-arw/` itself, dry run only: "0 written,
  152 skipped, 5 unsupported"; mtime and size of all 312 files and SHA-256 of the 152 sidecars unchanged.
- **Daemon.** `wildid serve -v`: ready 4.6 s after launch; missing or wrong token → 401; three
  lion ARWs with crop → *Panthera leo* 0.88–0.94 in 1.0 s, keywords
  `WildID|Mammalia|Panthera|Panthera leo` + `animals` + `wildlife`; `geo: {country: Kenya}` →
  0.97–0.99, 1,416 candidates, 4.3 s; Peru → 400 naming `POST /prefetch`; `model: bioclip-2.5`
  on demand 8.6 s, 1,216 candidates; `geo: {auto: true}` at country and region level → the DNG
  filtered (Kenya 1,416 / Narok 634), the ARW `no GPS in the file`, no flag; `/health` both
  models loaded, free 11.9 of 25.2 GB; `POST /shutdown` → 200, exit in 3 s, serve.json removed.

## macOS build on the owner's M5 Pro — smoke, not the acceptance (2026-11-14)

Machine: Apple M5 Pro, 48 GB, macOS 26.5.1, no Lightroom Classic, no sample photos. This is
what was checked while building the macOS version (ADR 0008). The acceptance proper is
`docs/acceptance-macos.md` and is open.

- **Lock and environment.** Darwin arm64 added to the universal lock with the pinned uv
  0.11.32 (`revision` stays 3): no existing package lost a file or changed a hash; 117 macOS
  wheels and two macOS torch entries added (torch 2.14.1, torchvision 0.29.1, both tagged
  `macosx_14_0_arm64`). `uv sync --locked`: `.venv` 1.2 GB, MPS built and available. 188
  passed, 5 skipped; ruff clean; the eight Lua suites pass.
- **Prefetch.** `wildid prefetch --model all --crop --second-opinion`: bioclip-2 4.47 GB,
  bioclip-2.5 7.28 GB, detector 52 MB, SpeciesNet 209 MB, no Hugging Face account; offline
  verification ok for both models on `--device auto` (mps).
- **CLI on MPS, `tests/fixtures/bear.jpg`.** bioclip-2: *Ursus arctos* 0.826 (0.821 with
  crop), crop box 0.95 → 409×326 px, SpeciesNet *Ursus arctos* 0.977 "agrees"; header
  `device=mps precision=fp32`; model load 3.1 s. bioclip-2.5: *Ursus arctos* 1.000, load
  5.2 s. `--device cpu` gives the same bioclip-2 top-3 to three decimals, the same crop box
  and the same SpeciesNet score. With `-v`, no operator fell back from MPS to the CPU.
  `--precision tf32` and `fp16` warn and run fp32.
- **Daemon.** Ready 4.1 s after launch on `mps`; `/health.vram` = Apple M5 Pro, 40.2 GB
  total, `kind: unified` (35.3 GB free with bioclip-2 loaded); a missing or wrong token → 401;
  serve.json mode 600; the bear fixture through `/classify`: 0.826 in 1.1 s, keywords
  `WildID|Mammalia|Ursus|Ursus arctos` + `animals` + `wildlife`; a second server exits 1
  naming pid and port; `--idle-exit 20` exited after 26 s and removed serve.json;
  `POST /shutdown` → ok, the process gone within a few seconds.
- **Installer, in a throwaway home folder.** `build.sh` → `WildID-0.3.1-macos-arm64.zip`,
  22.6 MB. `bash install.sh --no-path`: `uv sync --frozen` through the bundled uv (77
  packages), payload and plug-in in place, `engine.json` valid with executable `start` and
  `cli`; `wildid --version` and a classification on MPS through the installed launcher;
  `wildid-server-start` returned in 0.3 s and the detached server answered. A second run
  added the PATH line once. With `com.apple.quarantine` set on every file of the unzipped
  folder, `bash install.sh` still ran and the installed files carried no flag. uv's release
  binary is ad-hoc signed and not notarized (`spctl`: rejected). `uninstall.sh --yes` removed
  program, plug-in and PATH line and kept the cache; `--purge` removed only WildID's folders.
- **Not done.** No sample photo was classified, so there is no accuracy, speed or memory
  figure for macOS; nothing ran inside Lightroom; no install into the real home folder and no
  browser download; the macOS CI jobs have not run.

## macOS acceptance on the owner's M5 Pro — sections 0, A, C (file steps) and E (2026-11-14)

Version 0.3.1 plus the memory-reading fix noted at the end; Apple M5 Pro, 48 GB,
macOS 26.5.1, Python 3.14.7, torch 2.14.1 on MPS, fp32 unless stated. The owner's `sample-jpg/`
(863 JPG, 43 folders) and `sample-arw/` (152 ARW + 5 DNG + 3 TIF, 152 sidecars) were in the
repository root; place lists were fetched the same day and every classify run was offline.
Drivers, scorer, comparison script and all outputs are in
`~/.cache/wildid-acceptance/2026-11-14-macos/`; the per-country trees are directories of file
symlinks, as on Linux. The reference is the Linux CUDA run of 2026-11-03 at the same version
(previous section). Its per-file JSONs are not on this Mac, so parity is shown **per file
against CPU fp32 on the Mac** and **in aggregate against the reference's figures**. Not run:
anything inside Lightroom (not installed) and a real install (`docs/acceptance-macos.md` B, D).

- **Suites.** `WILDID_LIVE_TESTS=1 uv run pytest`: 192 passed with the live-model tests, 3
  skipped (no RAW fixtures); `ruff check` and `ruff format --check` clean; the eight Lua suites
  pass under LuaJIT.
- **MPS against the CPU reference (the E8 question).** `sample-jpg --k 1`, no crop: bioclip-2
  **863/863 identical top-1**, max |Δscore| 0.0003; bioclip-2.5 **863/863**, 0.0002; review
  flags identical. The whole pipeline (552-frame Madagascar tree, crop + place list, bioclip-2):
  **552/552**, max |Δscore| 0.0000, identical review and detection flags. The detector alone
  on 182 frames (all 102 that got no box, 80 that did): same flag, confidence and box on every
  frame. Two MPS runs of the same command: 863/863, Δ 0. For scale, CUDA tf32 against fp32 was
  863/863 with 0.007.
- **Aggregate against the Linux CUDA run** (reference in brackets). Kenya, 199 JPG, 1,421
  candidates today (1,416): mean top-1 0.845 (0.845), below 0.50 18 (18), review 39 (39),
  not-in-list 32 (32); the text output is 47,767 bytes (47,768 on Linux, where the header
  says `cuda`, one character longer than `mps`) and byte-identical with `--offline`; bear →
  *Papio hamadryas* 0.184 with *Ursus arctos* 0.826 flagged (0.183 / 0.827). Genus rank: 26/199
  top-1 changes, mean 0.845 → 0.737 (same). Crop: 10 changes (11), mean → 0.866 (0.865), below
  0.50 18 → 15 (same), 16 frames without a detection (16), review 34 (33), not-in-list 29 (28).
  Second opinion: agrees 107, same genus 12, same family 20, same class 36, no taxon 7,
  disagrees 17 — all six as on Linux. Madagascar reptiles and frogs (76): 32 not-in-list lines
  for bioclip-2 and 68 for 2.5 (32 / 68); crop + second opinion offline 76/76. `KhaoYai`: 557
  candidates (511; the regional list has grown to 589 species), 20 classified, 8 lines (8).
- **Section E rows on the Mac** (crop, `--k 1`; folder name = ground truth at the rank it
  fixes, scorer rebuilt from the Linux description as `score.py`):

  | set (frames) | place filter | bioclip-2 Mac (Linux) | bioclip-2.5 Mac (Linux) |
  |---|---|---|---|
  | 12 species-labelled lemur folders (385 JPG) | Madagascar | 268 (270) | 276 (279) |
  | same, genus level | Madagascar | 346 (348) | 345 (346) |
  | same | none | 251 (253) | 275 (278) |
  | all 14 lemur folders at their rank (411 JPG) | Madagascar | 293 (295) | 298 (302) |
  | review flags on those 411 | Madagascar | 185 (188) | 81 (85) |
  | Fossa + mongoose + fruit-bat (65 JPG) | Madagascar | 63 (63) | 65 (65) |
  | `sample-arw/lemur`, family level (55 ARW) | Madagascar | 54 (54) | 54 (54) |
  | Kenya mammals, 7 folders (22 frames) | Kenya | 21 (21) | 19 (19) |
  | Madagascar reptiles, 6 folders (63 JPG) | Madagascar | 63 (63) | 0 (0) |
  | same | none | 42 (44) | 0 (0) |

  Reading: every row outside the lemur species counts is identical; those sit two to four
  frames under the reference, both models, with and without the list. The backend is not the
  cause: the CPU run of the same tree gives exactly the MPS answers (above). What differs from
  the Linux run is the input: today's lists (Madagascar 862 / 576 candidates against 860 / 575),
  a 552-file tree against a 554-file one, and with it the detector's batch neighbours — on the
  Mac itself, the same 552 frames inside the 863-file run and inside the tree keep their top-1
  on 552/552 but move scores by up to 0.06 (bioclip-2) and 0.38 (2.5) and flip one detection
  flag. bioclip-2.5's lead on the 385 lemur frames has the reference's shape: +8 frames with
  the list (+2.1 pp; Linux +2.3) and +24 without (+6.2 pp; +6.5). `lemur-brown` 1/32 and 3/32
  and the sportive folders 2/34 for bioclip-2 are as logged on Linux.
- **Speed, images per second** (863 JPGs or 157 RAW, batch 32, 8 loader threads; CUDA tf32 on
  the RTX 4090 for scale):

  | run | bioclip-2 | bioclip-2.5 | RTX 4090 |
  |---|---|---|---|
  | `sample-jpg`, fp32 | 33.4 | 17.3 | 138.8 / 98.2 |
  | `sample-jpg`, fp16 (measurement switch) | 82.5 | 48.4 | 179.9 / 142.0 |
  | `sample-jpg --crop` | 21.0 | 13.5 | 70.9 / — |
  | `sample-arw` | 25.7 | — | 52.9 / — |
  | `sample-arw --crop` | 15.9 | 11.1 | 31.8 / — |
  | Kenya with anomaly check / crop / second opinion | 17.3 / 12.7 / 11.6 | — | 76.8 / 46.7 / 32.5 |
  | `sample-jpg --device cpu` | 7.6 | 4.4 | — |

  Model load 3.1 s and 5.2 s. Batch 16 / 32 / 64: 32.9 / 33.4 / 34.4; loader threads 4 / 8 /
  16: 33.4 / 33.4 / 31.9 — the Mac is GPU-bound in fp32, the defaults stand.
- **fp16 on MPS** (`WILDID_MPS_FP16=1 --precision fp16`, against fp32 on MPS and equally
  against CPU): bioclip-2 851/863 same top-1 (98.6 %), max |Δscore| 0.017, 2.5 times the speed;
  bioclip-2.5 862/863 (99.9 %), 0.023, 2.8 times. All 13 changed frames are near-ties between
  low-scoring candidates (largest winning score 0.43, gaps of 0.001–0.012). On CUDA fp16
  changed 8 and 6 of 863 answers for 1.5 and 1.9 times the fp32 speed. Not decided here:
  whether to offer it.
- **Memory** (physical footprint of the process, which on Apple Silicon includes the Metal
  memory; in brackets what the Metal driver holds, as `/health` reports it; 40.2 GB is Metal's
  recommended maximum on this machine):

  | daemon, 24-photo crop requests on the ARWs | idle | under load |
  |---|---|---|
  | bioclip-2 | 9.4 GB (4.9) | 11.7 GB (9.3) |
  | bioclip-2.5 alone | 12.9 GB (7.6) | 13.4 GB (11.0) |
  | both models | 19.2 GB (12.5) | 20.1 GB (16.9) |

  Flat: over 1,256 photos in 56 requests the bioclip-2 footprint stays at 11.5–11.7 GB from the
  third pass on, the Metal figure at 9.3 GB. CLI peaks: `sample-jpg` 11.1 GB (bioclip-2) and
  14.5 GB (2.5), with `--crop` 15.8 and 19.3 GB, fp16 13.0 and 17.2 GB, on CPU 6.9 and 9.9 GB;
  across the seven chunks of a run the footprint holds at 11.08–11.10 GB and ends lower. The
  CUDA daemon figures were 6.8 / 9.7 / 14.1 GB of video memory, with the label table in system
  memory on top; on a Mac both come out of the one pool.
- **Daemon.** Ready 4.0 s after launch (bioclip-2.5: 6.9 s). Three lion ARWs with crop:
  *Panthera leo* 0.882 / 0.915 / 0.942 in 1.3 s (Linux 0.88–0.94), keywords
  `WildID|Mammalia|Panthera|Panthera leo`; with `geo: {country: Kenya}` 0.970 / 0.984 / 0.990,
  1,421 candidates, all `in_candidates`, 3.8 s; `Peru` → 400 naming `POST /prefetch`;
  `POST /warmup` for bioclip-2.5 in 5.5 s, `/health` then lists both models; 15.6 img/s
  (bioclip-2) and 10.4–10.8 img/s (2.5) over the RAW files in 24-photo crop requests, 0 failed
  in 1,956 photos; `POST /shutdown` → ok, exit within 3–5 s, serve.json removed.
- **Auto-geo (cache-only).** `prefetch --gps-from`: the two drone JPGs resolve through cells
  `gps:-20.25,44.25` and `gps:-20.25,44.50` to Madagascar, the phone DNG through
  `gps:-1.75,35.00` to Kenya and, at region level, Kenya › Narok. `mg-baobab4 --geo-auto`:
  both photos → Madagascar, 862 candidates. `sample-arw/lion --geo-auto`: the DNG → Kenya,
  1,421 (region: Kenya › Narok, 638); the five ARWs unfiltered with `no GPS in the file` and
  no flag.
- **Sidecars (copies: 12 ARW + 1 DNG + 1 TIF, no sidecars).** Dry run "12 written, 1
  unsupported", nothing on disk; real run 12 sidecars with `dc:subject`,
  `WildID|Mammalia|Panthera|Panthera leo` + `animals` + `wildlife` and the `wildid:*` block
  (the two landscape frames: no detection, a plant top-1 at 0.12 / 0.01, `WildID|review`, no
  flat tags); re-run "0 written, 12 skipped", SHA-256 unchanged; `--xmp-mode merge
  --keyword-root WildID2`: "12 merged", one `WildID2|…` entry appended and
  `wildid:ProcessedAt` updated in each, the namespace declarations re-serialised onto the root
  element, nothing else. `sample-arw/` itself, dry run only: "0 written, 152 skipped, 5
  unsupported".
- **The samples were not touched.** Name, size and mtime of all 864 + 312 files and the
  SHA-256 of the 152 existing sidecars are the same before and after the run.
- **Found and fixed: the debug log's memory reading was Linux-only.** `chunk done … rss ?` on
  macOS, so the per-chunk stability check could not be read from `-v`. `pipeline.rss()` now
  reports the resident size and the physical footprint on macOS (libproc), with tests.
- **Open after this run.** The per-file comparison with the CUDA JSONs (they are on the Linux
  box; `compare.py` takes them as they are); the firewall and sleep/wake checks; everything in
  Lightroom; the real install; the macOS CI jobs. Decisions for the owner, with the figures
  above: whether to offer fp16 on MPS, the "keep both models loaded" rule for unified memory,
  and what to say about Macs with less memory than this one. *(2026-11-15: the last one is
  decided. The owner cannot get a smaller Mac, so the requirements state only what was
  measured: they name this machine, say that no other Mac has been tried and say nothing
  about smaller ones. ADR 0008 decision 8. The both-models rule is decided too: on unified
  memory the option needs 30 GB of what Metal recommends, against the 20.1 GB both models
  hold; this machine reports 40.2 GB and keeps the option. ADR 0008 decision 5. And fp16 is
  offered as the opt-in it is on CUDA: next section, ADR 0003.)*

## macOS: fp16 on the plug-in's path — crop, RAW files, the daemon (2026-11-15)

Engine at 0.3.1 (nothing in `src/` has changed since the previous section's fix); the same
M5 Pro, samples and method as the previous section; drivers and outputs in
`~/.cache/wildid-acceptance/2026-11-15-macos/`. Why this run: the fp16
figure of 2026-11-14, 2.5 and 2.8 times the fp32 speed, is classification alone on JPGs. The
Lightroom plug-in runs with the crop, mostly on RAW files, through the daemon in 24-photo
requests, and the detector and the image decoding take the same time in either precision.
This measures fp16 there, against fp32 baselines taken in the same session. fp16 is reached
through the measurement switch (`WILDID_MPS_FP16=1 --precision fp16`): it was not offered yet.

- **The baselines reproduce.** The four fp32 crop runs give the 2026-11-14 answers on every
  frame (863/863 and 157/157, Δ 0) and its speeds within 3 %.
- **Speed, images per second, crop on:**

  | run | bioclip-2, fp32 → fp16 | bioclip-2.5, fp32 → fp16 |
  |---|---|---|
  | daemon, 24-photo requests, 157 RAW | 15.4 → 21.4 (1.4 times) | 10.2–10.7 → 16.4–17.5 (1.6 times) |
  | CLI, `sample-arw --crop` | 15.7 → 22.4 (1.4 times) | 11.0 → 18.4 (1.7 times) |
  | CLI, `sample-jpg --crop` | 21.6 → 36.1 (1.7 times) | 13.5 → 26.7 (2.0 times) |

  At the daemon's rates a thousand RAW files take 65 s in fp32 and 47 s in fp16 with
  bioclip-2, 93–98 s and 57–61 s with bioclip-2.5, before Lightroom's own share.
- **Answers, fp16 against fp32 on the same frames:**

  | run, crop on | bioclip-2 | bioclip-2.5 |
  |---|---|---|
  | `sample-jpg --crop`, 863 JPG | 858 same top-1, 5 changed | 856 same, 7 changed |
  | `sample-arw --crop`, 157 RAW (CLI) | 157 same | 156 same, 1 changed |
  | daemon, 157 RAW | 154 same, 3 changed | 156 same, 1 changed |

  Every changed frame is a review frame in both precisions; the highest top score among them
  is 0.40. The same holds for the 13 frames that changed on 2026-11-14 without the crop
  (highest 0.43). The review flag itself moves on 5 of the 1,726 JPG results, each with a
  score within 0.01 of the 0.50 threshold, and on no RAW file. Detection flags do not move:
  the detector does not run under the autocast. Largest |Δscore| on agreeing frames: 0.029.
- **Memory**, the daemon's footprint, same request sequence in both precisions:

  | daemon, 24-photo crop requests | fp32 | fp16 |
  |---|---|---|
  | bioclip-2 under load | 10.7 GB | 12.9 GB |
  | bioclip-2.5 alone under load | 13.4 GB | 15.0 GB |
  | both models, idle | 19.0 GB | 20.0 GB |
  | both models under load | 18.8 GB | 20.4 GB |

  Under load fp16 costs 1.6 to 2.2 GB (on the RTX 4090 it cost 1.6 and 2.5 GB of video
  memory). CLI peaks with the crop: 15.8 → 17.2 GB for bioclip-2 and 19.2 → 20.8 GB for
  bioclip-2.5 on the JPGs.
- **Why these fp32 figures sit below the 11.7 and 20.1 GB of 2026-11-14.** The footprint
  under load depends on what the server has been asked. This run made no place-list request;
  the 2026-11-14 sequence made one (Kenya) before its passes. Checked by repeating the
  bioclip-2 sequence both ways in fp32: 10.7 GB with crop requests only (twice the same);
  10.5 GB right after one Kenya request, 11.4 GB after the passes that follow it, and 12.5 GB
  (Metal 9.3 GB) after a pass that uses the Kenya list, the level the 2026-11-14 run ended on.
  So bioclip-2 under load is 10.7 to 12.5 GB on this machine, and 11.7 GB is where the
  stability run held.
- **Reading.** On the plug-in's path fp16 is worth 1.4 times with bioclip-2 and 1.6 times with
  bioclip-2.5, not the 2.5 and 2.8 of bare classification. It changes about 1 % of the
  answers and none of the confident ones, and costs about 2 GB. No operator fell back to the
  CPU, nothing failed, and the sample folders are unchanged (fingerprints before and after,
  identical to those of 2026-11-14). Whether to offer it was left to the owner (next point).
- **Decided and built the same day: fp16 is opt-in on a Mac, as on CUDA** (ADR 0003). The
  plug-in's server stays on `auto`, which is fp32 there. The measurement switch is gone, and
  `--precision fp16` alone gives the measured answers: `sample-jpg --k 1 --precision fp16`
  against the switch runs of 2026-11-14, bioclip-2 863/863 identical top-1 and bioclip-2.5
  863/863, Δ 0, no warning, 91.1 and 49.5 img/s. The bear fixture: `--precision fp16` →
  `device=mps precision=fp16`, *Ursus arctos* 0.828 (0.826 in fp32), the same through
  `wildid serve --precision fp16`; `--precision tf32` warns and runs fp32; `--device cpu
  --precision fp16` warns that fp16 needs CUDA or MPS and runs fp32. Suite with the live-model
  tests: 197 passed, 3 skipped; ruff clean; the eight Lua suites pass.

## macOS: first run of the macOS CI jobs (2026-11-15)

The first run of `release.yml` with the macOS jobs: a manual run the owner started on `main`,
with `create_release` off. All five jobs green and the release job skipped, as it should be;
2 min 29 s from start to end. Everything below is read from the run's logs.

| Job | Runner | Result | Time |
|---|---|---|---|
| plugin Lua tests | `ubuntu-latest` | the eight suites pass under Lua 5.1 | 13 s |
| engine tests | `ubuntu-latest` | ruff clean; 194 passed, 7 skipped | 2 min 25 s |
| Windows installer | `windows-latest` | `WildID-Setup-0.3.1.exe` | 51 s |
| macOS download | `ubuntu-latest` | `WildID-0.3.1-macos-arm64.zip`, uv 0.11.32 | 9 s |
| engine tests + install smoke | `macos-15` | ruff clean; 196 passed, 5 skipped; smoke passed | 1 min 17 s |

- **The macOS runner** reports macOS 15.8.2 on an "Apple M2 Pro (Virtual)". It is the first
  machine other than the owner's Mac, and the first macOS 15, on which the lock, the suite and
  the installer have run. `uv sync --locked` with uv 0.11.32 fetched and installed the 77
  packages of the macOS environment in 9 s (torch 2.14.1 from PyPI, 127 MB). The suite's
  counts are those of the owner's Mac; the skips are the RAW fixtures and the live-model
  tests.
- **The install smoke** ran every step the workflow lists: the checksum, the unzip, the
  quarantine flag on every file, `bash install.sh --no-path` ("WildID 0.3.1 on macOS 15.8.2
  (Apple M2 Pro (Virtual))"), 77 packages installed, the launchers and `engine.json` checked,
  no quarantine flag left on the program or the plug-in, `wildid --version` → `wildid 0.3.1`,
  `uninstall.sh --yes`, nothing left behind.
- **Two things the smoke does not show, found in its log.**
  1. *The Python was the runner's own.* uv built the environment on Homebrew's
     `/opt/homebrew/opt/python@3.14` (3.14.10). With its default preference uv takes an
     installed interpreter that satisfies `.python-version` and downloads its managed CPython
     only when there is none. The owner's Mac has Homebrew's Python 3.14 as well (the
     checkout's `.venv` runs on it and no uv-managed Python is installed), so the install of
     2026-11-14 in a throwaway home folder will have gone the same way. A Mac without a
     Python 3.14, the usual photographer's Mac, makes uv download one: **that path has not
     run anywhere yet.** It also means that the "uv-managed Python" of ADR 0008 decision 6 and
     plan M8 is what happens only when no other Python 3.14 is found. An environment built on
     Homebrew's Python lasts as long as Homebrew keeps that Python; when it goes, the
     launchers rebuild the environment on next use.
  2. *The bundled uv downloaded nothing.* `setup-uv` sets `UV_CACHE_DIR` for the whole job, so
     the installer's `uv sync --frozen` found every wheel the test step had fetched a minute
     earlier ("Prepared 1 package in 92ms", "Installed 77 packages in 576ms"; the whole
     step took 4 s). The same uv version did download everything in the test step, so the
     download is shown, but not from the copy of uv inside the zip.
- **Artifacts**, kept one day: `wildid-0.3.1-windows` (18.3 MB; the installer's SHA-256 is
  `6537399ccf9cb6f0fbb80fd7c5bc997a7102d7d095d775637236fef031d43073`) and
  `wildid-0.3.1-macos-arm64` (22.6 MB; the zip's SHA-256 is
  `4d025324b6eef0fdb6446b3dbc1c42ec4794a16ea561985ce2bfea3118695538`).
- **Warnings, none of them a failure:** GitHub runs three actions on Node.js 24 although they
  target Node.js 20, which it has deprecated (`astral-sh/setup-uv@v6`,
  `actions/upload-artifact@v4`, `actions/download-artifact@v4`), and announces that
  `ubuntu-latest` moves to Ubuntu 26.
- **Open after this run:** the CI-built zip installed once by hand, the second half of the
  checklist's CI item. The two gaps were closed the same day (next section).

## macOS: the installer uses uv's own Python (2026-11-15)

The owner's rule after the first CI run: assume that a photographer's Mac has no Homebrew, no
Python and no developer tools. What changed: `install.sh` and the launchers `wildid` and
`wildid-server-start` export `UV_PYTHON_PREFERENCE=only-managed`. The CI smoke runs the
installer, the launcher and the uninstaller under `env -i` with macOS's stock PATH, after
removing the runner's uv cache and any uv-managed Python, and fails unless the environment
stands on uv's own Python. Three tests keep the setting, the commands the scripts may call
and the shape of the smoke.

- **uv's behaviour, tried in a scratch project with the bundled uv 0.11.32.** With Homebrew's
  Python 3.14.7 on PATH the default builds on it. With the setting uv downloads
  `cpython-3.14.6-macos-aarch64-none` (26 MB) and builds on that; over an environment built on
  Homebrew's Python it removes the environment and rebuilds it. A later `uv run` without the
  setting keeps the managed environment. An environment whose Python has vanished is rebuilt
  by `uv sync --frozen` ("Ignoring existing virtual environment linked to non-existent Python
  interpreter"), which is what the launchers run when `app/.venv/bin/python` is not
  executable.
- **A real install on the owner's M5 Pro**, into a throwaway home folder, Homebrew first on
  PATH, from a zip built from the working tree with every file quarantined: uv downloaded
  CPython 3.14.6 and the 77 packages itself, 8 s in all. The environment's Python is
  `~/.local/share/uv/python/cpython-3.14-macos-aarch64-none/bin/python3.14`: Python 3.14.6,
  torch 2.14.1, MPS available. As `du` counts them: environment 1.2 GB, uv's Python 75 MB,
  uv's download cache 1.2 GB. No quarantine flag left.
- **The engine on that Python.** Every measurement so far ran on Homebrew's 3.14.7. Through
  the installed launcher the bear fixture, with crop and second opinion, gives the
  checkout's answers exactly: *Ursus arctos* 0.821, crop 0.95 → 409×326 px, SpeciesNet 0.977,
  `device=mps precision=fp32`. `wildid-server-start` returns at once; the server is ready
  3.7 s later on `mps` (`vram.kind` unified, 40.2 GB), `/classify` gives 0.826 without the
  crop, `/shutdown` removes `serve.json` and the process ends.
- **A second `install.sh` over the install:** 2 s, the environment and its Python kept.
  **`uninstall.sh`:** program and plug-in gone; uv's two folders stay, as its closing message
  says.
- The owner's real home folder was not written: no install and no uv Python there, and the
  model caches were only read. Suite: 199 passed, 5 skipped; ruff clean.
- **Second CI run** (manual, started from the Mac on the owner's word): all five jobs green
  in 2 min 34 s, the release job skipped. Suite: 199 passed and 5
  skipped on `macos-15`, 197 passed and 7 skipped on Linux. The install smoke, now in the bare
  environment on macOS 15.8.2, shows both gaps closed: the bundled uv downloaded
  `cpython-3.14.6-macos-aarch64-none` (26 MB) and every wheel itself ("Prepared 77 packages in
  6.61s"; the install took 9 s, the first run's 4 s step had downloaded nothing); the check
  printed `Python: /Users/runner/.local/share/uv/python/cpython-3.14.6-macos-aarch64-none`;
  `wildid --version` through the launcher gave `wildid 0.3.1`; the uninstall left nothing of
  WildID. Artifacts, kept one day: the zip's SHA-256 is
  `4015718402b5e7e2a6f013a3f22b6d17209f4457552a8395c2788063cf140bb4`, the Windows installer's
  `395402a934dd7ebb50a9c7d1211e5f81f853b9b5141663a9dec5da9c5df7d8aa`.
- **Still open:** the CI-built zip installed once by hand (done the same day, next section);
  the real install from a browser download (checklist D). Not looked at: the Windows
  installer, which calls uv the old way.

## macOS: the CI-built zip by hand, and the samples through an installed copy (2026-11-15)

On the owner's go, two things in one run: the second half of the checklist's CI item, and the
question the Python change raised. An installed WildID runs on the CPython 3.14.6 that uv
downloads; every measurement so far ran in the checkout on Homebrew's 3.14.7. Driver, scorers
and outputs: `~/.cache/wildid-acceptance/2026-11-15-macos-installed/`.

- **The CI-built zip:** the artifact `wildid-0.3.1-macos-arm64` of the second CI run, 22.6 MB,
  with the SHA-256 the build job logged (previous section). Built on Linux, it holds the same
  49 files as the zip built on the Mac, byte for byte, with the same executable bits, no CRLF
  and the scripts of the commit that run built.
- **Installed by hand** into a throwaway home folder on the M5 Pro, every file quarantined,
  Homebrew first on PATH: `install.sh` took 7 s; uv downloaded CPython 3.14.6 and the 77
  packages; the environment stands on uv's Python (torch 2.14.1, MPS available); payload,
  launchers, plug-in and `engine.json` in place; no quarantine flag left; `wildid --version`
  gives `wildid 0.3.1`; a second `install.sh` took 1 s and kept the environment; the bear
  fixture as in the checkout (0.821, crop 0.95 → 409×326 px, SpeciesNet 0.977); at the end
  `uninstall.sh` removed program and plug-in.
- **The samples through that copy**, fp32 on MPS, against the reference runs, compared field
  by field (`deep_compare.py`: every field of every result, numbers by absolute difference):

  | Run | Frames | Reference | Result | Speed |
  |---|---|---|---|---|
  | `sample-jpg`, bioclip-2 | 863 | 2026-11-14 | identical | 33.6 img/s |
  | `sample-jpg`, bioclip-2.5 | 863 | 2026-11-14 | identical | 17.8 img/s |
  | `sample-jpg --crop`, bioclip-2 | 863 | 2026-11-15 | identical | 21.2 img/s |
  | `sample-jpg --crop`, bioclip-2.5 | 863 | 2026-11-15 | identical | 13.6 img/s |
  | `sample-arw`, bioclip-2 | 157 | 2026-11-14 | identical | 21.8 img/s |
  | `sample-arw --crop`, bioclip-2 | 157 | 2026-11-15 | identical | 15.9 img/s |
  | `sample-arw --crop`, bioclip-2.5 | 157 | 2026-11-15 | identical | 11.2 img/s |
  | Kenya, place list, anomaly check | 199 | 2026-11-14 | identical | 17.3 img/s |
  | Kenya, the same with crop | 199 | 2026-11-14 | identical | 13.1 img/s |
  | Kenya, place list, second opinion | 199 | 2026-11-14 | identical | 11.7 img/s |

  "Identical" is literal: all 4,520 results are equal in every field and every score
  difference is 0, the crop boxes, the unconstrained top-1 and the SpeciesNet answers
  included. The speeds are the checkout's (33.4 and 17.3 img/s without the crop on
  2026-11-14, 21.6 and 13.5 with it this morning).
- **The plug-in's path through the copy.** `wildid-server-start` returned at once and the
  server was ready 3.9 s later on `mps`. One request of 24 RAW files with the crop gave the
  answers of the installed command line on the same files, 24 of 24 with score difference 0,
  in 2.7 s for this first request. `/shutdown` removed `serve.json` within 0.5 s and the
  process ended.
- **Untouched:** the sample folders (864 and 312 files; fingerprints equal before and after,
  and equal to this morning's), the real home folder (no install, no uv Python) and the model
  and place-list caches (no file changed).
- **What this closes:** the checklist's CI item, both halves, and the doubt whether the engine
  behaves the same on the Python a photographer gets. **Still open in D:** the real install
  from a browser download into a real home folder, the wizard, Lightroom.

## Python from uv on every system, and the CI actions on Node 24 (2026-11-15)

- **The rule (owner):** Python always comes from uv, never from the machine, on every system.
  It is one line now, `python-preference = "only-managed"` in `pyproject.toml`; the setting
  that `install.sh` and the macOS launchers carried since the morning is gone. Both
  installers ship the file, and every uv call of their scripts names the project. A test
  checks the line, the shipping and the calls on both systems, and each CI test job fails
  unless its environment stands on uv's own Python.
- **Tried with uv 0.11.32 in a scratch project:** with Homebrew's Python on PATH and no
  environment variable, the setting alone makes uv download CPython 3.14.6 and rebuild an
  environment that stood on Homebrew's, also when called from another folder with
  `--project`. `uv lock --check` passes for the repository and `uv.lock` is unchanged.
- **The checkout on the Mac:** the first `uv run` rebuilt `.venv` on uv's Python (3.14.10, the
  newest the Homebrew uv 0.13.6 knows, in `~/.local/share/uv/python`). Suite on it: 199
  passed, 5 skipped; ruff clean. The Linux and Windows checkouts will do the same on their
  first `uv run` after the pull. *(The Linux checkout did, the same day: last section.)*
- **A real install** of a zip built from the working tree, into a throwaway home folder with
  Homebrew first on PATH: 11 s; the environment stands on uv's CPython 3.14.6; the bear
  fixture as before (0.821, crop 0.95 → 409×326 px, SpeciesNet 0.977); the server ready in
  3.7 s on `mps`; a second `install.sh` 2 s; `uninstall.sh` clean.
- **Windows:** none of its scripts changed and nothing was run there. It is the same uv and
  the same file. What is left to see is a PC that has its own Python 3.14
  (`docs/acceptance-lightroom.md`, section D).
- **CI upkeep:** the three actions GitHub ran with a Node 20 deprecation warning moved to
  releases that target Node 24: `astral-sh/setup-uv` 6 → 10.3.3 (named by its full release;
  the project publishes no moving major tag since v8), `actions/upload-artifact` 4 → 7,
  `actions/download-artifact` 4 → 8.
- **Third CI run** (manual): all five jobs green in 3 min 41 s,
  the release job skipped, and no Node 20 warning left; the only annotations are GitHub's
  notices about `ubuntu-latest` and macOS runner capacity. The artifacts were uploaded by
  the new upload action and fetched by the new download action. In both test jobs uv
  downloaded its own CPython 3.14.6 and the new check printed it
  (`…/uv-python-dir/cpython-3.14.6-linux-x86_64-gnu` and `…-macos-aarch64-none`); suites 197
  passed and 7 skipped on Linux, 199 passed and 5 skipped on macOS. The install smoke again
  downloaded Python and all 77 packages itself and stands on uv's Python. The Linux test
  job took 3 min 38 s against 2 min 29 s before: its uv cache started empty under the new
  action version.

## Linux: the CUDA reference runs for the macOS comparison (2026-11-15)

Backlog item 9 (`species-id-mvp-plan.md` §10), the part that belongs to the Linux box: the
nine run documents that the Mac's per-file comparison needs. Version 0.3.1, clean
tree, on the Linux workstation (RTX 4090 25.8 GB, driver 595.99.02, torch 2.14.1+cu130).
That was `main` when the runs were made; the website commit that reached it a few minutes
later changes nothing in `src/`, the tests, `pyproject.toml` or the lock.
The outputs, the driver, its log and the two checking scripts are in
`~/.cache/wildid-acceptance/cuda-reference/`. **The comparison itself has not been run:** the
folder is on the Linux box only (last point).

- **The environment was rebuilt first**, as the previous section said this checkout would.
  `uv sync --locked` with uv 0.13.5 downloaded `cpython-3.14.9-linux-x86_64-gnu` (37 MB),
  removed the `.venv` that stood on the system's Python 3.14.7 (`/usr/bin`) and built it
  again: the same 96 packages at the same versions, `uv.lock` unchanged, the RTX 4090
  available to torch. `WILDID_LIVE_TESTS=1 uv run pytest` on it: 210 passed with the
  live-model tests, 2 skipped (both are checks for macOS only).
- **The nine runs**, the item's commands unchanged (`uv run wildid classify … -v --format json
  --output …`), one after the other. The speed of the same command on 2026-11-03 is given for
  scale; the peak is the whole card, the desktop's 1.0 GB included:

  | Run | Frames | Precision | Model load | Speed | 2026-11-03 | Peak GPU |
  |---|---|---|---|---|---|---|
  | `jpg-b2`: `sample-jpg`, bioclip-2 | 863 | tf32 | 2.8 s | 143.1 img/s | 138.8 | 6.6 GB |
  | `jpg-b25`: `sample-jpg`, bioclip-2.5 | 863 | tf32 | 4.8 s | 99.9 img/s | 98.2 | 9.7 GB |
  | `jpg-b2-crop`: `sample-jpg --crop`, bioclip-2 | 863 | tf32 | 2.8 s | 71.5 img/s | 70.5 | 8.6 GB |
  | `jpg-b25-crop`: `sample-jpg --crop`, bioclip-2.5 | 863 | tf32 | 4.8 s | 57.4 img/s | 55.8 | 11.6 GB |
  | `arw-b2`: `sample-arw`, bioclip-2 | 157 | tf32 | 2.8 s | 59.0 img/s | 52.9 | 6.6 GB |
  | `arw-b2-crop`: `sample-arw --crop`, bioclip-2 | 157 | tf32 | 2.8 s | 30.3 img/s | 31.3 | 8.2 GB |
  | `arw-b25-crop`: `sample-arw --crop`, bioclip-2.5 | 157 | tf32 | 4.8 s | 28.6 img/s | 29.6 | 11.2 GB |
  | `jpg-b2-fp32`: `sample-jpg --precision fp32`, bioclip-2 | 863 | fp32 | 2.8 s | 121.3 img/s | 120.7 | 6.6 GB |
  | `jpg-b25-fp32`: `sample-jpg --precision fp32`, bioclip-2.5 | 863 | fp32 | 4.8 s | 76.2 img/s | 75.0 | 9.7 GB |

- **Every file is what the item expects.** `"device": "cuda"` in all nine; `"precision":
  "tf32"` in the first seven and `"fp32"` in the last two; 863 results for `sample-jpg` and
  157 for `sample-arw` (152 ARW + 5 DNG; the three TIF copies are outside the default
  extensions); none failed, every exit code 0, nothing on stdout. The only warning in any
  `.err` file is bioclip-2.5's standing notice that it has no reptiles, once in each of its
  four runs.
- **They are the 2026-11-03 runs again.** Eight of the nine have a document of that run made
  by the same command (`e1-*`, `e2-*`, `p-*-tf32` and `p-*-fp32` in `2026-11-03/runs/`): all
  5,492 results are equal in every field and every numeric difference is 0, the scores, the
  crop sizes and detection confidences, the review flags and the keywords included. The
  ninth, `arw-b2`, had only a text output then: the same top-1 on 157 of 157 frames and the
  same score to the three decimals that output prints. So neither the Python under the engine
  (uv's 3.14.9 for the system's 3.14.7) nor what changed in `src/` since 2026-11-03 (seven
  files: the macOS work and the setup wizard's optional token) moved a CUDA answer.
- **TF32 against fp32**, the reason for the last two runs: bioclip-2 863 of 863 the same
  top-1, largest |Δscore| 0.007; bioclip-2.5 863 of 863, 0.019; the review flag is the same
  on every frame. These are the figures of 2026-10-25 and 2026-11-03.
- **Speed and memory.** Eight runs are within 4 % of the 2026-11-03 speed; the plain RAW run
  gave 59.0 against 52.9 img/s, over 2.7 s. The photo files had been read for checksums just
  before, so they will have come from memory. Every peak is 0.3 GB above the one of
  2026-11-03; the desktop held 1.0 GB of the card before these runs, lock screen included,
  and the earlier log gives 0.8 GB for it.
- **The samples were not touched.** SHA-256, size and modification time of all 864 + 312
  files in the two folders, taken before and after the runs, are identical.
- **In the folder, besides the nine runs:** `MANIFEST.txt` (commit, `wildid --version`, the
  GPU, the date, the environment with the two model snapshots, and the table above),
  `driver.sh` and `run.log`, `verify.py` and `deepcmp.py` (the checks above), and
  `samples.sha256`, the checksums of the 1,020 photos classified. With it the Mac can check
  that its sample folders hold the same files (`shasum -a 256 -c`, in the repository root).
  **That has not been checked:** the Mac's files were not available here.
- **Open, the rest of item 9.** The folder goes to the Mac under the same path. The
  comparison runs there, with the Mac's `compare.py` and `deep_compare.py`: each file against
  the Mac file of the same name, the two fp32 files against the Mac's `jpg-b2.json` and
  `jpg-b25.json`, expected at least 99.5 % of the top-1 answers identical. Its result goes
  into this file, and only then are the two boxes of `docs/acceptance-macos.md` (sections 0
  and E) ticked.
  *(Done on the Mac the same day: next section.)*

## macOS against CUDA, file by file (2026-11-15)

Backlog item 9, the part that belongs to the Mac. The nine run documents of the previous
section came over from the Linux box, with their manifest, as
`~/.cache/wildid-acceptance/cuda-reference/`. Compared there with the
Mac's runs of the same names (`2026-11-15-macos-installed/`, identical to the checkout's), using
`compare.py`, `deep_compare.py` and `crop_diff.py` from that folder. The outputs are
`cuda-comparison.txt` and `cuda-crop-diff.txt` in it.

- **The same photos.** The manifest lists the SHA-256 of the 1,020 photos the Linux box
  classified (863 JPG, 157 RAW). All 1,020 match the Mac's files, and the results come in the
  same order in both sets of documents.
- **Classification agrees on every file.** No crop, the Mac on MPS in fp32 against CUDA in its
  default TF32:

  | Run | Identical top-1 | Largest score difference | Review flag |
  |---|---|---|---|
  | `sample-jpg`, bioclip-2 | 863 of 863 | 0.0069 | same on every frame |
  | `sample-jpg`, bioclip-2.5 | 863 of 863 | 0.0185 | same on every frame |
  | `sample-arw`, bioclip-2 | 157 of 157 | 0.0080 | same on every frame |

  The checklist expected at least 99.5 %. The two fp32 control runs say where the small score
  differences come from: MPS fp32 against CUDA fp32 is 863 of 863 with 0.0002 (bioclip-2) and
  0.0001 (bioclip-2.5), and CUDA fp32 against CUDA TF32 is 863 of 863 with 0.0070 and 0.0185.
  The two backends agree to the fourth decimal; the rest is TF32.
- **With the crop, 1.8 % of the answers differ.**

  | Run | Identical top-1 | Answers that differ | Of those, review frames on both machines |
  |---|---|---|---|
  | `sample-jpg --crop`, bioclip-2 | 848 of 863 (98.3 %) | 15 | 14 |
  | `sample-jpg --crop`, bioclip-2.5 | 846 of 863 (98.0 %) | 17 | 12 |
  | `sample-arw --crop`, bioclip-2 | 154 of 157 (98.1 %) | 3 | 3 |
  | `sample-arw --crop`, bioclip-2.5 | 155 of 157 (98.7 %) | 2 | 2 |

  2,003 of 2,040 results agree. Of the 37 that differ, 31 are review frames on both machines
  and 6 carry a score of 0.5 or more on at least one side: one with bioclip-2, five with
  bioclip-2.5, none on RAW. The review flag itself differs on 6, 19, 0 and 1 frames.
- **The cause is the detector's box, not the classification.** On the 863 JPGs the crop has
  the same pixel size on 483 frames, is cut a pixel or two differently on 270, is another box
  on 7, exists on one machine only on 2, and 101 have no detection on either. On the 157 RAW
  files: 124, 11, 2, 0 and 20. The detector's confidence differs by up to 0.05 between the
  machines. Of the 37 differing answers, 32 sit on frames whose crop differs by a pixel or two:
  the model was undecided there and a pixel of crop tips it. Four sit on frames where another
  box won, among them `bird-northern-gannet/2A7R3887.jpg`: two detections tie at 0.928, the Mac
  crops the smaller one and answers *Uria aalge* with 0.92, CUDA crops the larger one and
  answers *Morus bassanus* with 0.91, the folder's species. One sits on a frame with the same
  crop, a near-tie at 0.09.
- **Not known yet: is it TF32?** On CUDA the detector runs under the same TF32 switch as the
  classifier; on the Mac it runs in fp32. On the Mac, MPS and CPU, both fp32, gave the same box
  on every frame checked on 2026-11-14. The nine runs hold no CUDA crop run in fp32, so they
  cannot say whether CUDA's default precision moves the box or the backend does. Backlog item
  10 asks for the four runs that settle it. If it is TF32, then on a PC, too, the crop makes
  about 2 % of the answers depend on the precision; the precision measurement of 2026-10-23
  compared runs without the crop. *(The four runs were made the same day: next section. On
  CUDA the precision changes 3 of 2,040 answers through the crop, not 2 %.)*
- **Reproducible on each machine.** The previous section shows that the CUDA crop runs equal
  those of 2026-11-03 in every field, crop sizes and detection confidences included, and the
  Mac's crop runs repeat exactly as well. So each machine gives its own boxes every time; it
  is between the machines that they differ.
- **Closed:** the two boxes of the macOS checklist that waited for the CUDA files (sections 0
  and E). The agreement the checklist asks for is that of the plain runs, and it is complete.

## Linux: the CUDA crop runs in fp32 (2026-11-15)

Backlog item 10 (`species-id-mvp-plan.md` §10), the part that belongs to the Linux box: four
crop runs with `--precision fp32`, and their comparison with the TF32 crop runs of item 9.
Version 0.3.1, clean tree; no file under `src/`, the tests, `pyproject.toml` or the
lock differs from the commit of the nine runs. The same machine, environment (uv's
CPython 3.14.9, torch 2.14.1+cu130), model snapshots, detector and photos. The files went into
the same folder, `~/.cache/wildid-acceptance/cuda-reference/`, next to the nine. **These runs
have not been compared with the Mac's:** the new files are on the Linux box only (last point).

- **The four runs**, the item's commands unchanged. The speed of the TF32 run of item 9 is
  given for scale; the peak is the whole card, the desktop's 1.1 GB included:

  | Run | Frames | Model load | Speed | In TF32 | Peak GPU |
  |---|---|---|---|---|---|
  | `jpg-b2-crop-fp32`: `sample-jpg --crop --precision fp32`, bioclip-2 | 863 | 2.8 s | 64.5 img/s | 71.5 | 9.3 GB |
  | `jpg-b25-crop-fp32`: the same, bioclip-2.5 | 863 | 4.8 s | 48.5 img/s | 57.4 | 12.2 GB |
  | `arw-b2-crop-fp32`: `sample-arw --crop --precision fp32`, bioclip-2 | 157 | 2.9 s | 30.8 img/s | 30.3 | 8.4 GB |
  | `arw-b25-crop-fp32`: the same, bioclip-2.5 | 157 | 4.8 s | 25.5 img/s | 28.6 | 11.3 GB |

- **Every file is what the item expects.** `"device": "cuda"` and `"precision": "fp32"` in all
  four; 863 results for `sample-jpg` and 157 for `sample-arw`; none failed, every exit code 0,
  nothing on stdout. The only warning is bioclip-2.5's notice that it has no reptiles, in its
  two runs.
- **Item 9's files were not touched.** The 27 files of the nine runs and the other files of
  the folder have the checksums they had before these runs. The one exception is
  `MANIFEST.txt`, as the item asks: its first part is unchanged, byte for byte, and a section
  for the four runs follows it.
- **CUDA in fp32 against CUDA in TF32, through the crop.** Each new file against the item-9
  file of the same name without `-fp32`; the report is `fp32-crop-comparison.txt` in the
  folder. The crop size is compared on the frames that have a detection in both runs:

  | Pair | Top-1 answers that differ | Crop size differs | Largest confidence difference |
  |---|---|---|---|
  | `sample-jpg --crop`, bioclip-2 | 2 of 863 | 29 of 760 | 0.0038 |
  | `sample-jpg --crop`, bioclip-2.5 | 1 of 863 | 29 of 760 | 0.0038 |
  | `sample-arw --crop`, bioclip-2 | 0 of 157 | 3 of 137 | 0.0010 |
  | `sample-arw --crop`, bioclip-2.5 | 0 of 157 | 3 of 137 | 0.0010 |

- **The precision reaches the detector and moves few boxes.** The detector's confidence
  differs between fp32 and TF32 on every frame that has a detection in both runs (760 of 760
  JPGs, 137 of 137 RAW files), by 0.0038 at most. On the 863 JPGs the crop is not the same on
  30 frames: the size differs by 1 px on 23 and by 2 px on 5; on one the detector keeps
  another box (`Kenya/A7R09873-Enhanced-NR.jpg`, 805 px wide in fp32 and 1,279 px in TF32,
  confidence 0.449 and 0.450); and one has a detection in TF32 only
  (`reptile/RX707460-Enhanced-NR.jpg`, confidence 0.2002 against the detector's threshold of
  0.2). On the 157 RAW files the size differs on 3 frames, by 1 px. The two models show the
  same crops on every frame, in either precision: the crop does not depend on the classifier.
- **Answers.** 3 of the 2,040 results change with the precision, each a review frame in both
  runs. All three sit on frames whose crop changed. On the 833 JPGs whose crop is the same in
  both runs no answer changes and the scores differ by 0.0070 and 0.0185 at most, which is
  what TF32 does to the classifier without the crop. A crop that differs by one pixel can do
  more: the largest score difference on an unchanged answer is 0.066 with bioclip-2 and 0.193
  with bioclip-2.5 (`lemur-verreaux-sifaka/3A7R07889.jpg`, 0.593 against 0.399), and the
  review flag changes on 2 frames, both with bioclip-2.5. So on a PC the crop makes about
  0.15 % of these answers depend on the precision.
- **Against the Mac: a lower bound, not the comparison.** The previous section gives the crop
  as different between the Mac and the TF32 runs on 279 of the 863 JPGs (270 a pixel or two,
  7 another box, 2 on one machine only) and on 13 of the 157 RAW files. TF32 changes the crop
  on 30 JPGs and 3 RAW files. A frame that differs between the Mac and TF32, and not between
  TF32 and fp32, differs between the Mac and fp32. So CUDA in fp32 still differs from the Mac
  on at least 249 JPGs and 10 RAW files, if the Mac's figures count a crop as the same the
  way this comparison does (same detection, same size). The precision is then not what
  separates the two machines. Whether it is the CUDA backend or something else between the
  two platforms, these runs cannot say; a crop run with `--device cpu` on the Linux box would
  help to tell the two apart, and is not part of the item.
- **Speed.** With the crop fp32 gives 64.5 against 71.5 img/s for bioclip-2 on the JPGs and
  48.5 against 57.4 for bioclip-2.5; on the RAW files 30.8 against 30.3 and 25.5 against 28.6.
- **The samples were not touched.** SHA-256, size and modification time of all 864 + 312 files
  are the same before and after the runs, and the same as after item 9's runs.
- **In the folder for item 10:** the four runs (`.json`, `.err`, `.out`), `driver-item10.sh`
  and `run-item10.log`, `verify-item10.py`, `fp32-crop-compare.py` and its output
  `fp32-crop-comparison.txt`, and the new section of `MANIFEST.txt`.
- **Open, the rest of item 10.** The folder goes to the Mac under the same path. There the
  four files are compared with the Mac's `-crop` runs, fp32 on both sides, with
  `crop_diff.py`. That comparison, not the lower bound above, decides between the item's two
  outcomes; the bound says to expect the second one, that the machines differ in the detector
  whatever the precision.

## Linux: crop runs on the CPU (2026-11-15)

The follow-up to item 10, on the owner's word the same day, and recorded as backlog item 11
(`species-id-mvp-plan.md` §10): the crop commands of item 9 with `--device cpu` on the Linux
box, to see whether the CUDA backend is what moves the detector's box. Version 0.3.1, clean
tree; no file under `src/`, the tests, `pyproject.toml` or the lock differs from
the commits of the earlier runs. The same machine (i9-13900KF, torch's default of 24 threads),
environment, model snapshots, detector and photos, in fp32. The files went into the same
folder, `~/.cache/wildid-acceptance/cuda-reference/`. **These runs have not been compared with
the Mac's:** the new files are on the Linux box only (last point).

- **The four runs.**

  | Run | Frames | Model load | Speed |
  |---|---|---|---|
  | `jpg-b2-crop-cpu`: `sample-jpg --crop --device cpu`, bioclip-2 | 863 | 2.5 s | 4.0 img/s |
  | `arw-b2-crop-cpu`: `sample-arw --crop --device cpu`, bioclip-2 | 157 | 2.5 s | 3.5 img/s |
  | `jpg-b25-crop-cpu`: `sample-jpg --crop --device cpu`, bioclip-2.5 | 863 | 4.2 s | 2.5 img/s |
  | `arw-b25-crop-cpu`: `sample-arw --crop --device cpu`, bioclip-2.5 | 157 | 4.3 s | 2.3 img/s |

  `"device": "cpu"` and `"precision": "fp32"` in all four; 863 and 157 results; none failed,
  every exit code 0, nothing on stdout; the only warning is bioclip-2.5's notice that it has
  no reptiles. Nothing went to the GPU: the card held the desktop's 1.0 GB before the runs
  and during them.
- **The earlier files were not touched.** The 50 files that were in the folder have the
  checksums they had before, except `MANIFEST.txt`, which has a third section after its
  unchanged part.
- **The CPU gives CUDA's fp32 crops on every frame.** Each CPU run against the CUDA fp32 run
  of the same folder and model (`cpu-crop-comparison.txt` in the folder):

  | Pair | Top-1 answers that differ | Crop size differs | Detection in one run only | Largest confidence difference |
  |---|---|---|---|---|
  | `sample-jpg --crop`, bioclip-2 | 0 of 863 | 0 of 760 | 0 | 0.0000047 |
  | `sample-jpg --crop`, bioclip-2.5 | 0 of 863 | 0 of 760 | 0 | 0.0000047 |
  | `sample-arw --crop`, bioclip-2 | 0 of 157 | 0 of 137 | 0 | 0.0000022 |
  | `sample-arw --crop`, bioclip-2.5 | 0 of 157 | 0 of 137 | 0 | 0.0000022 |

  The review flag is the same on every frame and the scores differ by 0.0002 at most. The
  detector's confidence differs at all on 637 of 760 and 111 of 137 frames, in the sixth
  decimal: rounding.
- **Against CUDA in TF32** the CPU runs show what the CUDA fp32 runs showed in the previous
  section: the same 30 JPG and 3 RAW crops, and the same 3 answers.
- **What this settles on this box.** CUDA's precision changes 30 of 863 JPG crops (previous
  section) and its backend changes none: CPU and CUDA in fp32 give the same crop on all
  1,020 photos, for both models. The Mac found the same on its side on 2026-11-14, MPS and
  CPU giving the same box on every frame it checked. So each machine gives one answer on
  all its devices, and the two machines differ: the Mac and the CUDA TF32 runs on 279 of
  the 863 JPGs. By the reasoning of the previous section this box's CPU then differs from
  the Mac on at least 249 and at most 309 JPGs, and on 10 to 16 of the RAW files, if the
  Mac's figures count a crop as the same the way these comparisons do.
- **Not known: what differs between the two machines.** A hypothesis, not tested here: the
  detector's input. Its confidence differs by up to 0.05 between the Mac and CUDA and by
  0.000005 between CPU and CUDA on this box, so a change of backend moves it ten thousand
  times less than the change of machine does. That fits two machines that hand the detector
  slightly different pixels, decoded or resized, better than two that compute differently.
  A checksum of the decoded pixels of the same photos on both machines would say.
- **The samples were not touched.** SHA-256, size and modification time of all 864 + 312
  files are the same before and after the runs.
- **In the folder for these runs:** the four runs (`.json`, `.err`, `.out`), `driver-cpu.sh`
  and `run-cpu.log`, `verify-cpu.py`, `cpu-crop-compare.py` and its output
  `cpu-crop-comparison.txt`, and the third section of `MANIFEST.txt`.
- **Open.** The folder goes to the Mac, as for item 10. There the four `-crop-cpu` files are
  compared with the Mac's `-crop` runs with `crop_diff.py`. They hold the same crops as the
  four `-crop-fp32` files of item 10, detection and size on every frame, so both comparisons
  should name the same frames.

## macOS against the Linux box in fp32 and on its CPU, through the crop (2026-11-15)

The Mac's part of backlog items 10 and 11. The folder with the eight new run documents of the
two previous sections came over from the Linux box; each was checked against its item (cuda
or cpu, fp32, 863 and 157 results, none failed). Compared with the Mac's `-crop` runs of the
same names, with `compare.py` and `crop_diff.py`; the output is
`linux-fp32-and-cpu-crop-diff.txt` in `~/.cache/wildid-acceptance/2026-11-15-macos-installed/`.

- **With fp32 on both machines the difference is as large as before.**

  | The Mac's crop runs against | JPG crops that differ, of 863 | RAW crops that differ, of 157 | Answers that differ, of 2,040 |
  |---|---|---|---|
  | CUDA in TF32 (item 9) | 279 | 13 | 37 |
  | CUDA in fp32 (item 10) | 281 | 10 | 38 |
  | the Linux box's CPU (item 11) | 281 | 10 | 38 |

  Per run against CUDA in fp32: 17 and 16 answers on the JPGs (bioclip-2, bioclip-2.5), 3 and
  2 on the RAW files. 32 of the 38 are review frames on both machines; 6 carry a score of 0.5
  or more on at least one side. Of the 281 JPG crops, 272 are cut a pixel or two differently,
  8 are another box and 1 exists on one machine only.
- **The fp32 and the CPU comparison name the same frames**, as the Linux box's log expected:
  the same crops and the same answers, for all four runs.
- **The machines hand the detector different pixels.** On the 760 JPGs that have a detection
  on both machines the detector's confidence is equal on 2; it differs by 0.0014 at the median
  and by 0.053 at most. On each machine the CPU and the GPU agree to the fifth decimal (the
  Mac on 2026-11-14, the Linux box in the previous section). A difference of that size on
  nearly every frame, on the CPU of both machines, cannot be arithmetic: the input differs.
- **Where the input can differ.** Without the crop it does not: the classifier's scores agree
  to 0.0002 between the machines, which is what MPS against the CPU gives on the Mac alone
  (0.0003), so the JPEG decoding and Pillow's resizing give the same pixels on both. What only
  the crop path has is ultralytics' own resize of the photo to the detector's size
  (`cv2.resize`, in its letterbox step). The Mac's OpenCV 5.0.0 reports `IPP in use: False`;
  the x86-64 OpenCV wheel normally carries Intel IPP, which brings its own resize. Not tested
  yet: backlog item 12 writes checksums of what the detector is handed and of the letterboxed
  image on both machines, on the Linux box with IPP and without, and repeats the four crop
  runs there without IPP. *(The Linux box's part was made the same day: last section.
  Switching IPP off changes nothing there, so IPP is not it.)*
- **Closed:** backlog items 10 and 11. Neither CUDA's precision nor its backend separates the
  machines.

## Linux: what the detector sees, with Intel IPP and without (2026-11-15)

The Linux box's part of backlog item 12 (`species-id-mvp-plan.md` §10). Version 0.3.1, clean
tree; no file under `src/`, the tests, `pyproject.toml` or the lock differs from
the commits of the earlier runs. The same machine, environment, model snapshots, detector and
photos; opencv-python 5.0.0.93, which reports `IPP in use: True` by default (IPP 2026.0.0,
AVX2). The files went into `~/.cache/wildid-acceptance/cuda-reference/`. **The Mac's
checksums have not been written or compared:** the new files are on the Linux box only.

- **The script is the item's, unchanged** (`detector_pixels.py`, checked against the plan's
  text line by line). It runs the ordinary crop classification and records, for every photo,
  shape and SHA-256 of the image wildid hands the detector and of the letterboxed image
  ultralytics makes of it. `OPENCV_IPP=disabled` is honoured by this OpenCV: the two files
  made with it say `IPP in use: False`, the two without say `True`, so the fallback of the
  item, switching IPP off inside the process, was not needed. OpenCV also prints that the
  variable disabled IPP, once in the `.err` file of each of the four runs made with it.
- **The four checksum files.** 863 rows for `sample-jpg` and 157 for `sample-arw` in each,
  the photos of the earlier runs in the same order. What is handed over: 858 of the 863 JPGs
  at 1,440 × 1,800 px, the RAW previews at 2,048 px on the long side or smaller. Letterboxed:
  512 × 640 px or 640 × 640 px for the JPGs, 384 × 640 or 640 × 640 for the RAW files. Every
  photo has its own checksum at both stages.
- **With IPP against without: no difference at all.**

  | | `sample-jpg`, 863 | `sample-arw`, 157 |
  |---|---|---|
  | Image handed to the detector differs | 0 | 0 |
  | Letterboxed image differs | 0 | 0 |

  The first row is what the item expected. The second is not: the guess was that IPP's
  resize makes the letterboxed image, and switching IPP off leaves every one of the 1,020
  letterboxed images the same, to the last byte.
- **The four runs without IPP are item 10's runs again.** `jpg-b2-crop-noipp`,
  `jpg-b25-crop-noipp`, `arw-b2-crop-noipp` and `arw-b25-crop-noipp` (CUDA, fp32, 863 and 157
  results, none failed) against the `-crop-fp32` runs of the same names:

  | Pair | Top-1 answers that differ | Crop size differs | Results equal in every field |
  |---|---|---|---|
  | `sample-jpg --crop`, bioclip-2 | 0 of 863 | 0 of 760 | 863 of 863 |
  | `sample-jpg --crop`, bioclip-2.5 | 0 of 863 | 0 of 760 | 863 of 863 |
  | `sample-arw --crop`, bioclip-2 | 0 of 157 | 0 of 137 | 157 of 157 |
  | `sample-arw --crop`, bioclip-2.5 | 0 of 157 | 0 of 137 | 157 of 157 |

  Answers, scores, crop sizes and the detector's confidence are equal to the last digit in
  all 2,040 results. The speeds are item 10's as well (65.6, 48.9, 31.0 and 26.5 img/s
  against 64.5, 48.5, 30.8 and 25.5).
- **What this settles: IPP is not what separates the machines.** The runs without IPP equal
  the runs with it, so they differ from the Mac's exactly as those do: on the 281 JPG crops,
  10 RAW crops and 38 answers of the previous section. The Linux box without IPP does not
  give the Mac's crops. In the item's words, the guess is wrong.
- **What it does not settle: which step differs.** That is what the Mac's checksums are for.
  Compared with `pixels-jpg-linux.tsv` and `pixels-arw-linux.tsv`, they say whether the two
  machines already differ in the image handed to the detector or only in the letterboxed
  one. Nothing on this box can say that. One thing was checked here because it bears on the
  item's reasoning: for the JPG exports the crop path and the plain path decode the same
  way, at full size (the plain path's decode bound of 1,024 px does not reduce a 1,440 ×
  1,800 px JPEG, and the one file looked at has no chroma subsampling), so the agreement of
  the machines without the crop does speak for the JPGs' decoding. The RAW previews are
  another matter: with the crop they are decoded towards 2,048 px and then reduced by
  Pillow, without it towards 1,024 px.
- **The earlier files and the samples were not touched.** The 67 files that were in the
  folder have the checksums they had before, except `MANIFEST.txt`, which has a fourth
  section after its unchanged part. SHA-256, size and modification time of all 864 + 312
  sample files are the same before and after the runs.
- **In the folder for item 12:** `detector_pixels.py`, the four `pixels-*.tsv` files, the
  four `-crop-noipp` runs (`.json`, `.err`, `.out`), `driver-item12.sh` and `run-item12.log`,
  `verify-item12.py`, `ipp-compare.py` and its output `ipp-comparison.txt`.
- **Open, the Mac's part of item 12.** The folder goes to the Mac. There the same script
  writes the Mac's two `.tsv` files and they are compared with the two of this box: are the
  handed-over checksums equal on both machines, and the letterboxed ones? The second half
  of the item's question, whether the runs without IPP give the Mac's crops, is answered
  here already: they cannot, being item 10's runs to the last digit.

## macOS: what the detector sees, and the step that differs (2026-11-15)

The Mac's part of backlog item 12, which closes it. The item's script, byte for byte the
Linux box's, wrote the Mac's checksums for both sample folders; scripts and outputs are in
`~/.cache/wildid-acceptance/detector-pixels/`. The sample folders are unchanged by the run.

- **The image handed to the detector is the same on both machines**: on all 863 JPGs and all
  157 RAW files, shape and checksum. Decoding, orientation and the loader give the same
  pixels on the Mac and on the Linux box.
- **The letterboxed image is not.** It differs on all 863 JPGs and on 24 of the 157 RAW
  files, always in the pixels and never in the shape, and the same against the Linux box
  with Intel IPP and without. The step that differs is ultralytics' resize of the photo to
  the detector's size, `cv2.resize` with `INTER_LINEAR`.
- **The Linux box computes OpenCV's portable resize; the Mac does not.** OpenCV's plain
  `INTER_LINEAR` for 8-bit images, written out in NumPy (`generic_resize.py`: 11-bit
  fixed-point weights, a horizontal pass into integers, the 8-bit vertical pass), plus
  ultralytics' grey border, gives the Linux box's letterboxed image to the byte on all 1,020
  photos. The Mac's equals it on 133 RAW files, the 2048 × 1152 previews, which are reduced by
  exactly 3.2, and on nothing else. On a 1440 × 1800 JPG about a fifth of the Mac's pixel
  values differ from the portable result, each by 1 of 255.
- **Why the Mac differs.** Its OpenCV 5.0.0 wheel is built with two Arm acceleration layers
  (`Custom HAL: YES (carotene (ver 0.0.1) KleidiCV (ver 26.03))`), which take over the resize
  for most sizes. `cv2.setUseOptimized(False)` does not switch them off. Same OpenCV version
  on both machines, different code for the processor.
- **So this is the whole chain.** A difference of 1 in a fifth of the detector's input values
  moves its confidence by 0.0014 at the median and 0.053 at most, moves the box by a pixel or
  two on about a third of the JPGs, and in 38 of the 2,040 answers the classifier then prefers
  another name; 32 of those are review frames on both machines. Neither machine is wrong.
- **What could make the crop the same on both** (measured on the Mac, one 1440 × 1800 JPG):
  `cv2.resize` with `INTER_LINEAR` takes 0.17 ms; with `INTER_LINEAR_EXACT`, OpenCV's variant
  meant to be the same everywhere, 0.30 ms; the portable algorithm in NumPy 13.9 ms as
  written. Whether the exact variant really gives the same bytes on both machines has not
  been checked. Nothing is changed in wildid: the choice is the owner's.
- **The four crop runs without IPP** from the Linux box equal its fp32 runs in every field
  (checked here as well), so against the Mac they differ on the same 281 JPG and 10 RAW crops
  and 38 answers.

## CI: a pushed tag publishes the release (2026-11-15)

Owner, 2026-11-15: the next pushed tag is to produce a proper release, not a draft. Changed:
the last step of the `release` job in `.github/workflows/release.yml`, and a new test file.
**The publishing itself has not run:** it cannot be tried without making a release, so it
runs for the first time at the next pushed tag (last point).

- **What a pushed tag does now.** Once every build and test job is green, the step publishes
  a GitHub Release on the pushed tag, with the Windows installer, the macOS zip and one
  `SHA256SUMS.txt`, titled "WildID <version>" with GitHub's generated notes. A version with an
  `aN`, `bN`, `rcN` or `.devN` suffix is published as a pre-release, which GitHub never shows
  as the latest release; the website's download buttons point to the latest one.
- **What a run started by hand does.** As before: artifacts only, or a draft release when
  `create_release` is ticked. That holds when the run is started from a tag as well.
- **The release goes on the pushed tag itself.** The step used to name the release
  `v<version>`. For a tag such as `v1.2.3-rc1`, whose version is normalised to `1.2.3rc1`,
  that is another name: harmless in a draft, a second tag once published. The step now takes
  the pushed tag and passes `--verify-tag`, so no tag is ever created by it.
- **It never adds a second release for a tag.** If a release or a draft for the pushed tag
  exists already, the step stops with a message and creates nothing. gh has a check of its
  own, a function named `publishedReleaseExists`; whether that one sees drafts was not read,
  so the step does its own lookup, which does find them.
- **Checked.** The YAML parses. `tests/test_release_workflow.py` cuts the step's script out
  of the workflow and runs it with a stand-in for `gh` that records its arguments: a pushed
  tag; four pre-release spellings; a post-release; an existing draft and an existing
  published release; a manual run from a branch and from a tag. 11 tests; the suite is at
  219 passed, 4 skipped; ruff clean. Against GitHub, read-only: the step's lookup answers
  "draft" for a tag that has a draft release and "release not found" for a tag without a
  release. gh's source
  (`pkg/cmd/release/create/create.go` on its trunk, read the same day): with files and
  without `--draft` it creates the release as a draft, uploads the files, then publishes,
  and deletes the draft if an upload fails; `--verify-tag` aborts when the tag is not in the
  remote repository. Which gh version the hosted runner carries was not looked at.
- **Not checked, and the state on GitHub.** Nothing of the new step has run on GitHub. The
  jobs before it last ran green on 2026-11-15, in three manual runs. *(Later the same day the
  repository became public. It holds no release and no tag.)*

## The exact detector resize as an option (2026-11-15)

The owner's decision on the last point of backlog item 12: the default stays as it is, and a
resize meant to be the same on every system is built as an option, off by default. Built the
same day (ADR 0003 §1, ADR 0005 decision 3).

- **What there is.** `wildid classify --crop --crop-exact`; `crop_exact` in a `/classify`
  request; the checkbox "Exact detector resize (meant to be the same on every computer)" in
  the plug-in's Identify dialog, enabled when the crop or the second opinion is on. The run
  document says which resize a run used (`crop_resize`: `linear`, `exact`, or `null` without
  the crop). `--crop-exact` without a crop stage is a usage error on the command line and has
  no effect in a request.
- **How.** ultralytics' `LetterBox` takes the interpolation as an argument, which its
  predictor never passes. `detector.exact_resize()` swaps that class, for the length of one
  `detect()` call and under a lock, for one whose default is `cv2.INTER_LINEAR_EXACT`.
  Nothing else in the detector's path changes: the same letterbox size, the same border, the
  same boxes scaled back by ultralytics.
- **Checked on the Mac.** Suite: 216 passed, 5 skipped; ruff clean; the eight Lua suites and
  the syntax of every plug-in file. One test runs the swap against the real ultralytics: inside
  it the letterboxed image is `cv2.resize` with `INTER_LINEAR_EXACT` to the byte, outside it
  with `INTER_LINEAR`, and the class is restored after an exception. With the real detector on
  one sample JPG (1440 × 1800): default, crop 1440 × 1345 with confidence 0.8952; with
  `--crop-exact`, the same crop with 0.8970; *Cryptoprocta ferox* 0.983 in both; the letterboxed
  image equals the resize of the mode asked for. Through the real server, four requests in a
  row: crop → `linear` 0.8952, crop with `crop_exact` → `exact` 0.8970, crop again → `linear`
  0.8952, `crop_exact` without crop → no crop. One detector stays loaded for all of them.
- **Not done.** Nothing was run in Lightroom: the checkbox has a box in both acceptance
  checklists. And the claim itself, that the option gives the same pixels and so the same crop
  on a Mac and on a PC, is OpenCV's and is not measured yet: backlog item 13. Until then
  `--help`, the checkbox's title and tooltip, the README and the website say "meant to".
  *(Measured the same day: "macOS: the exact detector resize against the Linux box", below.
  The texts were changed with it.)*

## Linux: the exact detector resize against the default (2026-11-15)

The Linux box's part of backlog item 13 (`species-id-mvp-plan.md` §10): what `--crop-exact`
changes on a PC. Version 0.3.1, current `main`, clean tree, in a fresh clone of the public
repository with the environment built anew from the lock: the same Python and the same
package versions as in the earlier runs. The same machine, model snapshots, detector and
photos; all 1,020 photos were checked against `samples.sha256` first. The files went into
`~/.cache/wildid-acceptance/cuda-reference/`. **Whether the option makes a Mac and a PC agree
is not answered here:** that takes the Mac's checksums and runs, and the new files are on the
Linux box only.

- **A control first.** Items 9 to 12 could say that nothing under `src/` differed from the
  commit of the runs before them. This item cannot: the engine has the new option, and the
  code of the earlier runs was not at hand to compare with. Instead the earlier commands
  were repeated on this commit without the
  option: the item's script with no extra argument, and the eight default crop runs of items
  9 and 10. The two checksum files equal item 12's row for row. The eight runs equal the
  earlier ones in every field of all 4,080 results; the documents differ only in their new
  head field `crop_resize`, which says `linear`. So what the runs with the option differ in
  is the option's doing. The control is in the folder, under `control-item13/`.
- **The script is the item's** (`detector_pixels2.py`, taken from the plan's text): item 12's
  script with what the item adds, extra arguments passed on to `wildid classify` and
  `crop_resize` in the head line. Every file is as the item expects: `crop_resize exact` in
  the first line of both `.tsv` files; in the eight run documents `"crop_resize": "exact"`,
  `"device": "cuda"`, `tf32` in the first four and `fp32` in the last four, 863 and 157
  results, none failed. Each `.err` file carries wildid's line that the detector's resize is
  the exact one.
- **The detector is handed the same image and computes on another one, on every photo.**

  | | `sample-jpg`, 863 | `sample-arw`, 157 |
  |---|---|---|
  | Image handed to the detector differs | 0 | 0 |
  | Letterboxed image differs | 863 | 157 |
  | Shape of the letterboxed image differs | 0 | 0 |

  The first row is what the item requires. The second says that on this box OpenCV's exact
  resize is not what its portable default computes, on any photo.
- **By how much** (not asked by the item; `exact-pixels.py`). The script rebuilds each
  photo's image for the detector outside a run and letterboxes it with both methods; its
  three checksums equal the ones recorded inside the runs on all 1,020 photos. Of the colour
  values of the letterboxed photos, without ultralytics' grey border, 11.1 % differ on the
  JPGs and 11.1 % on the RAW previews, every one of them by 1 of 255, between 4 % and 13 % of
  a photo's values. The exact resize gives the higher value in all but 118 of 94.6 million
  cases on the JPGs and all but 26,331 of 12.3 million on the RAW previews. For comparison,
  the Mac's default resize differs from this box's default by 1 in about a fifth of the
  values (item 12).
- **What the option changes in the runs.** Each run with `--crop-exact` against the run of
  the same command without it, the same precision on both sides:

  | Pair | Precision | Crop not the same | Top-1 answers that differ | Of those, review frames in both runs |
  |---|---|---|---|---|
  | `sample-jpg --crop`, bioclip-2 | TF32 | 231 of 863 | 13 | 13 |
  | `sample-jpg --crop`, bioclip-2.5 | TF32 | 231 of 863 | 15 | 12 |
  | `sample-arw --crop`, bioclip-2 | TF32 | 57 of 157 | 5 | 5 |
  | `sample-arw --crop`, bioclip-2.5 | TF32 | 57 of 157 | 10 | 7 |
  | `sample-jpg --crop`, bioclip-2 | fp32 | 228 of 863 | 11 | 11 |
  | `sample-jpg --crop`, bioclip-2.5 | fp32 | 228 of 863 | 15 | 12 |
  | `sample-arw --crop`, bioclip-2 | fp32 | 55 of 157 | 5 | 5 |
  | `sample-arw --crop`, bioclip-2.5 | fp32 | 55 of 157 | 10 | 7 |

  In TF32, 43 of the 2,040 answers differ and 37 of them are review frames in both runs; in
  fp32, 41 and 35. In each precision six of the changed answers carry a score of 0.5 or more
  in at least one run. "Crop not the same" in TF32: on the JPGs the size differs on 229 of
  the 761 frames detected in both runs, by 1 px on 124, by 2 px on 58, by 3 to 10 px on 35
  and by more on 12, and 2 frames have a detection with the option only; on the RAW files
  the size differs on 57 of 137, by 1 px on 29, by 2 px on 11, by 3 to 10 px on 12 and by
  more on 5. The detector's confidence moves by 0.0009 at the median and 0.029 at most on
  the JPGs, by 0.0012 and 0.026 on the RAW files. The number of review frames stays within
  two of the default's in every run. The run document records the crop's size and not its
  position: one of the changed answers in fp32 sits on a frame whose crop has the same size
  in both runs.
- **For scale.** Without the option the Mac and this box differ on 281 JPG crops, 10 RAW
  crops and 38 of 2,040 answers, fp32 on both ("macOS against the Linux box in fp32 and on
  its CPU, through the crop", above). On this box, in fp32, the option changes 228 JPG
  crops, 55 RAW crops and 41 answers: about as many answers, fewer JPG crops and more RAW
  crops. The Mac's default resize equals this box's on the 2048 × 1152 previews, which 133
  of the 157 RAW files have; the exact resize equals this box's default on none.
- **Against the folder names** (not asked by the item; the truth table of `bench.py`, the
  benchmark of section E of the acceptance checklists, which scores an answer at the finest
  rank the folder's name fixes). With the option 404 and 379 of the 569 scored JPG answers
  are right, for bioclip-2 and bioclip-2.5, where 406 and 384 are without it; of the 155
  scored RAW answers 136 and 116 where 137 and 117 are. Together 1,035 against 1,044 of
  1,448, the same in TF32 and in fp32. Ten answers are right without the option only and one
  with it only. Seven of the ten are review frames with and without the option. The other
  three are bioclip-2.5 answers that had no review flag without it (scores in TF32):
  *Varecia rubra* 0.847 on the full frame becomes *Ailurus styani* 0.559 on a crop of
  319 × 1200 px (`lemur-red-ruffed/A7R04965.jpg`, a detection the default does not have);
  *Mungotictis decemlineata* 0.936 becomes *Mungos gambianus* 0.325, flagged for review, as
  the box shrinks from the whole frame to 914 × 799 px (`mongoose/1A7R02141.jpg`); *Eulemur
  rufus* 0.591 becomes *Phascolarctos cinereus* 0.815 as the box grows to the whole preview
  (`lemur/A7R06620.ARW`). Eleven frames are too few to say that the exact resize makes the
  detector worse. They do say that on these photos it has not made the answers better.
- **The PC's precision still shows under the option** (not asked by the item; for the Mac's
  comparison with both sets of runs). With `--crop-exact`, fp32 against TF32: 2, 2, 0 and 1
  answers differ, and the crop's size on 25 JPGs and 6 RAW files. Item 10 found 2, 1, 0 and
  0 answers and 29 and 3 crop sizes for the default resize.
- **Speed.** One resize of a 1440 × 1800 px JPG to the detector's size takes 0.26 ms with the
  exact method and 0.09 ms with the default on this box, 0.14 s more on 863 photos. The
  runs: 68.6, 55.7, 31.5 and 29.2 img/s in TF32 against the control's 68.3, 57.2, 31.6 and
  29.5; 62.5, 47.2, 30.4 and 27.1 img/s in fp32 against 64.6, 48.9, 30.7 and 26.8. One
  command differs by as much from run to run: `jpg-b2-crop` gave 71.5 img/s in item 9 and
  68.3 in the control. Peak GPU memory is the same.
- **The earlier files and the samples were not touched.** The 88 files that were in the
  folder besides `MANIFEST.txt` have the checksums, sizes and times they had; `MANIFEST.txt`
  has a fifth section after its unchanged part. SHA-256, size and modification time of all
  864 + 312 sample files are the same before and after the runs.
- **In the folder for item 13:** `detector_pixels2.py`, the two `pixels-*-linux-exact.tsv`
  files, the eight `-crop-exact` runs (`.json`, `.err`, `.out`), `driver-item13.sh` and
  `run-item13.log`, `verify-item13.py`, `exact-compare.py` and its output
  `exact-comparison.txt`, `exact-pixels.py` and its output `exact-pixel-difference.txt`, a
  copy of `bench.py`; for the control `driver-item13-control.sh`,
  `control-item13-compare.py` and the folder `control-item13/`.
- **Open, the Mac's part of item 13.** The folder goes to the Mac. There the same script and
  the four crop runs with `--crop-exact` are made, and the comparison that decides: is the
  letterboxed checksum with the option the same on both machines on every photo, and do the
  Mac's runs give the crops and answers of this box's `-crop-exact-fp32` runs? Until then
  every text about the option says "meant to". *(Made the same day: next section.)*

## macOS: the exact detector resize against the Linux box (2026-11-15)

The Mac's part of backlog item 13 (`species-id-mvp-plan.md` §10), the part that decides:
does `--crop-exact` make the Mac and the PC agree? **It does.** Version 0.3.1, current
`main`, clean tree, in the checkout with uv (uv's Python 3.14.10, torch 2.14.1, OpenCV
5.0.0); the M5 Pro, MPS, fp32. All 1,020 photos match `samples.sha256`, and the sample
folders are unchanged after the runs. Driver, comparison script and outputs are in
`~/.cache/wildid-acceptance/2026-11-15-macos-exact/` (`driver-item13-mac.sh`,
`mac-exact-compare.py`, `mac-exact-comparison.txt`); the Linux box's files are in
`~/.cache/wildid-acceptance/cuda-reference/`.

- **A control first**, as on the Linux box: the Mac's default runs were made before the
  option existed. On this commit, without the option, the item's script gives item 12's two
  checksum files of the Mac row for row, and the four default crop runs equal the earlier
  ones in every field of all 2,040 results; the documents differ only in their new head
  field `crop_resize`, which says `linear`. So what differs below is the option's doing.
- **With the option the detector computes on the same pixels on both machines.** The
  letterboxed image by checksum, the script with `--crop-exact` on the Mac against the Linux
  box's file, and the other pairs for comparison:

  | Letterboxed image the same on | `sample-jpg`, 863 | `sample-arw`, 157 |
  |---|---|---|
  | the Mac with the option and the Linux box with the option | 863 | 157 |
  | the Mac and the Linux box, both without it | 0 | 133 |
  | the Mac with the option and the Mac without it | 0 | 0 |
  | the Linux box with the option and the Linux box without it | 0 | 0 |

  The image handed to the detector is the same on every photo in all of them, as before.
- **The runs give the same crops and the same answers.** The Mac's four runs with
  `--crop-exact` against the Linux box's:

  | The Mac with the option against | Crop not the same, of 863 JPGs | Of 157 RAW files | Top-1 answers that differ, of 2,040 | Of those, review frames in both |
  |---|---|---|---|---|
  | the Linux box with the option, fp32 | 0 | 0 | 0 | |
  | the Linux box with the option, TF32 | 25 | 6 | 5 | 5 |
  | for scale, both without the option, the Linux box in fp32 | 281 | 10 | 38 | 32 |
  | for scale, both without the option, the Linux box in TF32 | 279 | 13 | 37 | 31 |

  With fp32 on both, no crop size, no detection and no review flag differs on any of the
  2,040 results. The detector's confidence agrees to 0.000004 and the top-1 scores to
  0.0002, which is what the two machines give without the crop. Against TF32 the crop's size
  differs by 1 px on 20 JPGs and 6 RAW files and by 2 px on 5 JPGs, and 2, 2, 0 and 1
  answers differ: exactly what TF32 against fp32 gives on the Linux box itself under the
  option (its log above: 25 and 6 crop sizes, 5 answers). So what is left between a Mac and
  a PC in its default precision is the precision, not the resize.
- **What the option changes on the Mac**, each run with it against the control run without
  it: the crop is not the same on 269 of the 863 JPGs and 54 of the 157 RAW files. On the
  JPGs the size differs on 265 of the 760 frames detected in both runs, by 1 px on 131, by
  2 px on 78, by 3 to 10 px on 41 and by more on 15, and 4 frames have a detection in one
  run only; on the RAW files it differs on 54 of 137, by 1 px on 23, by 2 px on 13, by 3 to
  10 px on 13 and by more on 5. The detector's confidence moves by 0.0014 at the median and
  0.054 at most on the JPGs, by 0.0013 and 0.027 on the RAW files. Top-1 answers that
  differ: 14 and 19 of 863 (bioclip-2, bioclip-2.5), 5 and 11 of 157: 49 of 2,040, 40 of
  them review frames in both runs, 9 with a score of 0.5 or more in at least one run. On the
  Linux box the option changes 41 answers in fp32.
- **Against the folder names** (not asked by the item; the truth table of `bench.py`, as in
  the Linux box's log): with the option 404 and 379 of the 569 scored JPG answers and 136
  and 116 of the 155 scored RAW answers are right, 1,035 of 1,448, the Linux box's figures
  with the option, as they must be with the same answers. Without it the Mac has 401, 379,
  136 and 117: 1,033. Five answers are right with the option only and three without it
  only. On the Linux box it was 1,035 against 1,044. So the option moves answers both ways
  and is not a gain in accuracy on these photos.
- **Speed.** 21.0, 13.4, 15.6 and 11.1 img/s with the option against 21.6, 13.6, 15.6 and
  11.1 in the control.
- **What follows.** The option does what its name says, so the texts that said "meant to"
  now say what was measured: `--help`, the checkbox's title ("Exact detector resize (the
  same on a Mac and a PC)") and tooltip, the READMEs, the website, `CLAUDE.md`. They also
  say what it costs: about 2 % of the answers change against a run without it on either
  machine, and a PC in its default TF32 still differs from the Mac on about 0.2 % of the
  answers. The default stays off: making the option a default is the owner's decision (ADR
  0003 §1).
- **Not measured.** Windows: the comparison is between the Mac and the Linux box. Any other
  Mac. And the checkbox has still not been seen in Lightroom: its box in both acceptance
  checklists is open.
