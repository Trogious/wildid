# Lightroom integration (0.2.x) — Windows acceptance run

Runnable checklist for the owner's Windows box (RTX 4090, Lightroom Classic installed) to
accept what was built for 0.2.x on `main` (ADR 0005). Everything here was already
verified outside Lightroom on Linux: 128 Python tests, the plugin's JSON codec and collection
filing under real Lua 5.1/LuaJIT, and the plugin's HTTP/discovery modules driven against the
real daemon. **This run proves the parts only this machine can:** the real model in the
daemon, the SDK-facing Lua inside Lightroom, sidecar ingestion on real ARWs, and the
installer. Log results (dates, numbers, LR version) into `docs/acceptance.md` per its
convention; tick boxes here as sections pass.

Suggested order: **0 → A → B → C → D** (engine first, plugin against it, then packaging).
Section **E** (model measurement) is independent of Lightroom — run it any time after 0.

---

## 0. Session setup

- [x] `git pull` on `main`; `uv sync` (cu130 wheels, venv ~6 GB). *(2026-10-25: fresh box — uv 0.13.5 via winget, sync 21 s.)*
- [x] `uv run pytest -q` → expect 128 passed; the ARW-fixture skips un-skip if this box has
      `tests/fixtures/*.ARW`. `uv run ruff check .` clean. *(142 passed with the ARW/DNG fixtures; one Windows-only label failure fixed in `pipeline.label_of`.)*
- [x] Model cache present from the MVP work; otherwise
      `uv run wildid prefetch --model bioclip-2 --crop` (add `--second-opinion` if testing it). *(prefetched both models + stages + Kenya/Madagascar; repos are public, no token needed.)*
- [x] Print the real cache dir once and use it below (don't assume):
      `uv run python -c "from wildid.constants import cache_dir; print(cache_dir())"`
      — expected `%LOCALAPPDATA%\wildid\Cache`; if it differs, the plugin needs `engine.json`
      (section B) since its built-in Windows default assumes that path. *(= `%LOCALAPPDATA%\wildid\Cache`.)*
- [ ] Optional: a Lua 5.1 (`scoop install luajit`) to run `lrplugin/tests/*.lua` locally.

## A. Daemon with the real model (B1 acceptance)

- [x] `uv run wildid serve -v` → logs the port and the serve.json path; "model ready" within
      ~15 s from a warm cache. *(ready 4.5 s after bind.)*
- [x] Health + auth, in PowerShell (adjust the cache dir from step 0):

```powershell
$s = Get-Content "$env:LOCALAPPDATA\wildid\Cache\serve.json" | ConvertFrom-Json
Invoke-RestMethod "http://127.0.0.1:$($s.port)/health" -Headers @{Authorization="Bearer $($s.token)"}
# ready=True, protocol=1. Then without the header: expect HTTP 401.
```

- [x] Classify a real frame through the daemon:

```powershell
$body = @{ paths = @("D:\photos\DSC04512.ARW"); k = 3; crop = $true } | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:$($s.port)/classify" -Method Post `
  -ContentType "application/json" -Headers @{Authorization="Bearer $($s.token)"} -Body $body
# sane species, suggested_keywords with the WildID|class|genus|species path (family before 2026-10-28).
```

- [x] Geo request against a cached place (`geo = @{ country = "Kenya" }` in the body):
      candidates reflect the place; an uncached place returns a 400 naming prefetch. *(Kenya 1,417 candidates; Peru → 400 naming prefetch.)*
- [x] Throughput/stability: a few hundred photos in 16–32-photo requests (or simply section
      B's big run): RSS flat, `nvidia-smi` VRAM flat across requests. *(349 files × 32/request: RSS 3.1–3.5 GB, GPU flat 12.0 GB, 9.9 img/s.)*
- [x] `--idle-exit 60`: after a quiet minute the process exits, serve.json is gone,
      `nvidia-smi` shows the VRAM released. *(exited after 67 s idle, serve.json gone, 1.87 GB GPU used left = desktop.)*
- [x] Second-server refusal: start another `wildid serve` while one runs → exit 1 naming the
      live pid/port.

## B. Plugin inside Lightroom (B2 acceptance)

Setup: File → Plug-in Manager → Add → `lrplugin/wildid.lrplugin` (the installer's auto-load
path is tested in D instead). Start the daemon manually first, or create
`lrplugin/wildid.lrplugin/engine.json` by hand (see `lrplugin/README.md`) so the plugin can
start it. Use a **test catalog** for the first pass.

*2026-10-25: first run hit "Assertion failed: packed" — Lightroom rejects attaching, in one
`withWriteAccessDo`, a keyword/collection created in that same call; fixed by splitting the
writes into separate transactions (details in `docs/acceptance.md`). Small run then passed:
5 identified, 2 flagged, collections correct (owner-confirmed). Whole section passed the same day; three more findings fixed along the way (collection-name case collision between the two models' common names, clipped error dialog, launcher console left open) — all in `docs/acceptance.md`. LR Classic 15.4.1 (202606201310).*

[L]-assumptions this section confirms (fallbacks exist if one fails — say which fired):
`os.getenv`/`io` available to plugin Lua (fallback: `engine.json` carries `cacheDir`); the
Windows cache default matching step 0; `LrHttp` behavior with long POSTs.

- [x] Plugin loads with no Plug-in Manager errors; the three entries appear in the Library
      menu and File → Plug-in Extras; "Identify" is greyed without a selection.
- [x] "WildID: server status…" shows ready/model/uptime while the daemon runs; Stop works.
- [x] Small run (5 mixed photos, crop on, no geo): options dialog values persist across
      invocations; progress + summary correct. Then verify in LR:
      keyword tree `WildID → class → family → species` (genus in place of family since
      2026-10-28: see the class/genus tree box); the species keyword's **synonym** is
      the common name (Keyword List → right-click → Edit Keyword Tag); flat top-level
      keywords `animals` and `wildlife` on each identified photo (crop was on, so the
      detector's verdict gates them; a frame with no detection gets neither); Metadata panel →
      "All Plug-in Metadata" shows species/score/status/model/run; collections: the `WildID`
      set exists with per-species collections (`Panthera onca — Jaguar`) holding the right
      photos; a low-confidence frame is in `_review` + keyword `WildID|review`.
- [x] Model choice (B4): the dialog shows the bioclip-2 / bioclip-2.5 radios with their
      subscripts and the GPU line ("GPU: NVIDIA GeForce RTX 4090, 25.8 GB" — SI GB, so a
      24 GiB card reads 25.8). "Keep both models loaded" is **enabled** on the 4090; picking
      2.5 without a geo filter (or with Reptilia in the taxa) shows the reptile warning,
      excluding Reptilia clears it. Run once with 2.5: the progress caption shows the model
      loading, the summary names the model, `wildidModel` metadata says bioclip-2.5. With the
      checkbox on, "WildID: server status…" lists both models as loaded and the free VRAM
      dropped by roughly the second model's size; run again switching models — no load pause.
      Negative case (can't be done on this card): a < 20 GB GPU (e.g. a 16 GB card, 17.2 GB in
      SI) must show the checkbox disabled with the "below the 20 GB needed" note — covered by
      `lrplugin/tests/models_test.lua`. Threshold raised from 14 to 20 GB on 2026-10-25 after §E
      measured both models under load at ~15.7 GB including the desktop. Linux re-measurement
      after the detector fix (24-photo crop requests): 14.1 GB above a 1.3 GB desktop; the
      subscripts now read ~7 / ~10 / ~14 GB (under load) and the gate is unchanged.
      *Changed 2026-11-15, not re-run in Lightroom:* the rule is applied again to the running
      server's report before the second model is loaded, so on a card below 20 GB a tick made
      while the server was not running yet is no longer honoured. Nothing changes on the 4090,
      which passes the rule either way; this card cannot show the negative case.
- [x] Geo run: "WildID: prefetch place list…" (online) for a trip place, then Identify with
      the place set — out-of-place frames get flagged for review.
- [x] Move-on-rerun: force a species change (e.g. identify a bird with a Mammalia-only geo
      list, then re-run without geo) → the photo leaves the wrong species collection, joins
      the right one, summary counts it as moved; a cleared review flag removes the photo from
      `_review`.
- [x] Big run (200+ photos): smooth progress; **cancel mid-run** → whole chunks committed
      only, summary names how many; re-run is idempotent (no duplicate keywords/collections).
- [x] Kill the server mid-run → clean error dialog naming how many photos were already tagged.
- [x] Edge cases: a folder with diacritics in the path round-trips; a virtual copy and an
      offline original are skipped and counted; dry run writes nothing but reports counts.
- [x] Server auto-start from the plugin (via engine.json): note whether a console flashes
      (acceptable) and that health polling then proceeds to ready.
- [x] Note the LR Classic version used (for pinning `LrSdkMinimumVersion` later).
- [ ] "WildID: delete empty collections…" (plugin 0.2.3; sub-sets always included since the
      class/genus tree): the combo box lists the catalog's collection sets with `WildID`
      preselected, there is no "also remove sub-sets" checkbox; after a move-on-rerun left an
      empty species collection, Scan lists it (and `_review` when empty) plus every sub-set
      left with nothing in it (`[set] …`: the genus and class sets the move emptied), smart
      collections and non-empty ones are absent, Delete removes exactly the listed items and
      keeps the set; a sub-set holding a smart collection stays.
*2026-11-02: the first run of this item failed ("can't get collection information after
creating collection inside the same withWriteAccessDo function"); fixed the same day, see
`docs/acceptance.md`. Reload the plugin before retrying.*

- [ ] Class/genus tree (plugin 0.3.1+, replaces the 0.3.1 class collections): the identify
      dialog shows no "and by class" checkbox any more; the collection-set field's tooltip
      describes the tree. After a bioclip-2 run on a mixed folder the set holds collection
      sets `Mammalia`, `Aves`, `Reptilia`…, each with genus sets and species collections
      inside (`WildID/Mammalia/Panthera/Panthera onca — Jaguar`) holding the right photos,
      and `_review` directly under `WildID`; a chameleon/gecko/tortoise frame lands under
      `Reptilia` (not `Squamata`/`Testudines`) and its keyword reads `WildID|Reptilia|…`; a
      fish frame (no class in the table) goes under `_no class`. Clicking the `Mammalia` set
      shows every mammal below it. Metadata panel → "All Plug-in Metadata" shows "WildID
      class" **and the pre-upgrade species/status values are still there** (Metadata.lua
      `schemaVersion` went 1 → 2 in 0.3.1). The owner's workflow: select the `Mammalia` set,
      select all, identify again with bioclip-2.5 → a frame whose species changed leaves its
      old species collection for the new one and is counted as moved, also across class sets
      (2.5 calling a mammal a bird); a re-run that changes nothing reports no moves and adds
      no history steps for collections. Migration from the flat layout: a catalog with
      0.2.x/0.3.1 collections (`WildID/Panthera onca — Jaguar`, `WildID/Mammalia`) re-run →
      the photos leave the flat species collection for the tree ("N re-filed from the flat
      layout"), the flat `Mammalia` collection is renamed `Mammalia (flat)` with its photos
      intact and named in the summary (the one `setName` call: watch for an SDK error), and
      "WildID: delete empty collections…" lists and clears the emptied flat collections and
      every genus/class set left empty after moves. Keywords follow the same tree, and a
      re-run replaces what is under `WildID`: the photo gains
      `WildID|Mammalia|Panthera|Panthera onca`, loses `WildID|Mammalia|Felidae|Panthera onca`
      and a stale `WildID|review` (a confident re-run of a flagged photo), loses `animals` /
      `wildlife` when the new run drops them (re-run a tagged frame with crop on in which the
      detector finds nothing), keeps any keyword under another root, and the summary says
      "N photo(s) had keywords from an earlier run replaced". The emptied family keywords can
      then be deleted from the Keyword List.
- [ ] "WildID: mark as reviewed" (plugin 0.3.1+): greyed out with nothing selected; with a
      selection that mixes flagged photos and others, a bezel reports "N of M … marked as
      reviewed (… left _review, … keyword(s), … status(es))"; only those N leave `_review`
      (species, class and other collections untouched), lose the `WildID|review` keyword
      (other keywords kept) and show WildID status `reviewed`; Edit → Undo puts the keyword
      and the collection membership back (the status stays `reviewed`: private metadata is
      not undoable); a clean selection reports "none of the N … carries a review marker" and
      changes nothing; a photo flagged only by an imported XMP sidecar (keyword, no
      collection) is cleared too.
- [ ] SDK pin (plugin 0.3.0, `Info.lua` `LrSdkVersion`/`LrSdkMinimumVersion` = 15.0): the
      plugin still loads on LrC 15.4.1 (Plug-in Manager shows it enabled, no "requires a newer
      SDK" message) and all four menu items appear. Expected [L]: LrC 15 reports SDK 15.0; if
      it refuses, drop both values to 14.0 and log the version it reports.
*Note 2026-11-02: the A7R V and RX ARWs in the test catalog carry no EXIF GPS (sampled, see
`docs/acceptance.md`), so geotag a test folder in the Map module first (drag the photos onto
the map; catalog positions win over EXIF) or use phone DNGs — the Pixel DNG in
`sample-arw/lion` has a Maasai Mara fix.*

- [ ] Auto-geo, happy path (0.3.0): select a geotagged trip folder → "WildID: prefetch place
      list…" → For: "the selected photos' GPS positions" (the title names how many photos have
      a fix and how many cells), country level → the result lists "N GPS cell(s) resolved" and
      one place line per country. Then Identify with Candidates = "each photo's GPS position",
      country level → the summary names the level and how many photos ran unfiltered; JSON
      `place.label` (visible in `wildid --format json --geo-auto` on the same folder) is the
      country; no `WildID|review` from geo on photos whose cell was prefetched.
- [ ] Auto-geo, misses: one photo without GPS (strip it or pick an untagged frame) → classified,
      counted as unfiltered, **not** flagged; identify at region level after prefetching at
      country level only → those photos run unfiltered and are flagged, the review reason
      names `wildid prefetch --gps-from`; prefetch at region level → re-run clears the flag.
      A position set in the Map module (no EXIF GPS) also resolves (catalog GPS wins).
- [ ] bioclip-2.5 + GPS mode: with Reptilia removed from the taxa the dialog still shows the
      GPS-specific warning (photos without a fix run unfiltered); with Reptilia in, the
      standard one.
- [ ] Smart Preview fallback (0.3.0): build Smart Previews for a few photos on an external
      drive, eject the drive → Identify processes them (summary: "N photo(s) identified from
      Smart Previews"), the Smart Preview DNG classifies (embedded preview path, no demosaic
      warning in the server log), keywords land on the catalog photo; photos on the ejected
      drive without a Smart Preview are counted as "offline without a Smart Preview".

- [ ] Exact detector resize *(added 2026-11-15, not run in Lightroom)*: the Identify dialog
      has the checkbox "Exact detector resize (meant to be the same on every computer)" under
      the crop row. It is off the first time, greyed while "Detector crop" and "SpeciesNet
      second opinion" are both off, has a tooltip, and keeps its state between runs like the
      other options. Its title is not clipped. A run with it on finishes as usual. The engine
      half is covered outside Lightroom: `wildid --crop --crop-exact --format json` on the
      same photos says `"crop_resize": "exact"`, and without `--crop-exact` it says `"linear"`.

## C. Sidecar spot-check on real ARWs (Phase C acceptance)

*2026-10-25: steps 1–4 and 10 done on `sample-arw/` (69 ARW + 5 DNG + 3 TIF copies, Kenya and
Madagascar mixed → no geo filter); numbers in `docs/acceptance.md`. 31 of 74 results are `review`
(low score without a place list), so expect a large `_review`-style keyword count in step 6. Steps
5–9, 11–12 passed in Lightroom the same day on the re-cut 160-file set; step 12 exposed a
merge bug with Lightroom's attribute-form rewrite, fixed (see `docs/acceptance.md`).*

Copies only; use a test catalog. This confirms Lightroom's ingestion of what the unit tests
could only validate structurally.

1. - [x] Copy 20–50 ARWs (mammals, a reptile, a bird, an empty frame) to `D:\xmp-test`.
2. - [x] Dry run: `uv run wildid D:\xmp-test --write-xmp --dry-run --crop [--country …]`
         → "xmp dry run … N written", zero files on disk.
3. - [x] Real run with `--format json --output run.json`: one `.xmp` per ARW, count matches
         the summary; note the number of `"review": true` results in run.json.
4. - [x] Open one sidecar in a text editor: `dc:subject` (species, common name, `animals`,
         `wildlife`, review where flagged), `lr:hierarchicalSubject` (`WildID|…` plus the two
         flat tags), `wildid:*` provenance.
5. - [x] Import with **Add**: no "metadata changed" badges.
6. - [x] Keyword List: a real nested `WildID` tree (fail = one flat keyword with pipes in
         its name); `review` count ≈ run.json's; `animals`/`wildlife` as plain top-level
         keywords, absent on the empty frames (with `--crop` the detector gates them).
7. - [x] On a jaguar-type frame: species keyword appears once (flat + hierarchical merged);
         the common name is a **separate flat keyword** (sidecars cannot express synonyms —
         designed). **Decision point:** keep flat common names, or make them optional
         (`--xmp-common-names off`)? Record the preference. *Decided 2026-10-25 by the owner:
         keep them as they are (flat top-level common names next to `WildID`); no flag.*
8. - [x] Review set contents are genuinely the ambiguous frames.
9. - [x] WildID plugin metadata fields stay empty for sidecar-imported photos (expected —
         raw XMP is not plugin metadata).
10. - [x] Idempotence: re-run step 3's command → "0 written … N skipped", files untouched.
11. - [x] Merge on a genuine LR sidecar, lossless ordering **(Ctrl+S first!)**: develop-edit
          one photo (+2 EV, crop) → Ctrl+S → `uv run wildid <file> --write-xmp
          --xmp-mode merge --keyword-root WildID2` → in LR: Read Metadata from File →
          develop edits intact, old keywords intact, WildID2 added.
          **Any lost develop edit is a hard fail — keep the sidecar.**
12. - [x] After LR's own rewrite (the Ctrl+S above), the sidecar still contains the
          `wildid:*` block (LR preserves unknown namespaces — confirm).

Reminder of the standing rule (cli help + ADR 0005): sidecars are pre-import; post-import
external XMP writes fork catalog state — use the plugin instead.

## D. Installer

- [ ] *(not run: Inno Setup is not installed on this box; the CI build stands in)* `cd installer\windows; powershell -ExecutionPolicy Bypass -File build.ps1`
      (Inno Setup 6 installed) → `output\WildID-Setup-0.2.0.exe`.
- [x] Install (SmartScreen: More info → Run anyway — unsigned by design, plan L14):
      `uv sync` runs with visible progress; files under `%LOCALAPPDATA%\Programs\WildID`;
      plugin in `%APPDATA%\Adobe\Lightroom\Modules\wildid.lrplugin` with a correct
      `engine.json`.
- [x] Restart LR: the plugin **auto-loads from Modules** (the last [L] verify-item).
- [x] Start-menu "WildID Setup" runs the wizard (existing HF token detected → skips the
      paste); "WildID Server" starts the daemon windowless; the plugin finds it.
- [x] Uninstall: program + plugin gone, `%LOCALAPPDATA%\wildid` and the HF cache intact.
- [ ] Python comes from uv on Windows too *(added 2026-11-15; the rule is one line in
      `pyproject.toml`, checked on macOS and in CI on Linux and macOS, not run on Windows
      yet)*: after the next install or upgrade,
      `type "%LOCALAPPDATA%\Programs\WildID\app\.venv\pyvenv.cfg"` names a `home` under
      `%APPDATA%\uv\python`. The case that matters is a PC that has its own Python 3.14
      (python.org or the Store): uv's default would have built on that one. In the checkout
      on this box the first `uv run` after the pull rebuilds `.venv` on uv's Python.
- [x] CI build (D3, manual only): Actions → *release* → Run workflow with `create_release`
      **off**. (First run, on 2026-10-25: Lua and engine jobs green on hosted runners — the
      locked CUDA wheels fit after the disk-cleanup step, so hosted engine tests run on every
      dispatch (no opt-out input) and no self-hosted runner is needed for them; the Windows job failed on a
      `.sha256` parsing bug in build.ps1, fixed the same day. Second run: all jobs green,
      installer compiled on `windows-latest` in 49 s, artifact `wildid-0.2.1-windows`
      uploaded.) What remains here is installing that CI-built exe once on this box. Expected: Lua + Python jobs green, a `wildid-<version>-windows` artifact with
      installer and `SHA256SUMS.txt`; install the CI-built exe once the same way
      as the local one. When it matches, flip the workflow's trigger to `push: tags: ['v*']`
      (comment at the top of the file) and, when you want a release, run it with
      `create_release` on and publish the draft by hand. *(2026-10-25: the run's artifact downloaded, SHA-256 verified; CI's CRLF `SHA256SUMS.txt` fixed to LF. Local Inno Setup build not run — Inno Setup is not installed here.)* *(2026-11-15: the tag trigger has been in place since 2026-10-25, and from now on a pushed tag publishes the release itself; only a manual run with `create_release` still makes a draft.)*

## E. Measurement — bioclip-2.5 vs bioclip-2 on the owner's mammal samples

Purpose: the proposed per-run model choice in the plugin (radio group) wants the subscript
*2026-10-25: done on the catalog's four species-labelled Madagascar lemur folders (401 ARWs) in place of `samples/`, which is not on this box: bioclip-2.5 +3.7 pp species top-1 (77.1 → 80.8 %), rule met (+10.0 pp without the geo filter); table, VRAM figures and caveats in `docs/acceptance.md`, outcome in ADR 0001; the 2.5 radio subscript now carries the claim (`WildidModels.lua`, Lua test flipped).*

*2026-10-25, Linux re-run on the owner's re-cut `sample-jpg/` (14 species-labelled lemur folders, 411 frames, plus fossa, mongoose, reptiles and the Kenya ARW mammals), same code for both models: bioclip-2.5 +2.3 pp species top-1 on 385 lemur frames with the Madagascar list (70.1 → 72.5 %), +6.5 pp without it; rule met again, same shape as the Windows run; 0 % on every reptile folder, two misses on 22 Kenya mammal ARWs. Table in `docs/acceptance.md`. The VRAM figures there are post-fix: the CLI's detector stage is sub-batched (`DETECT_BATCH`) after an 863-frame crop run ran out of GPU memory.*

"more accurate" for bioclip-2.5 — a claim this repo has **never measured**. The bear.jpg
score gap (1.000 vs 0.830) is not evidence: both answers were correct and softmax scores are
not comparable across models. This measurement decides the wording, and whether the radio is
worth building at all. It is also "new evidence" in the sense of the CLAUDE.md default-model
rule — record it either way.

- [x] Both models cached: `uv run wildid prefetch --model all` (idempotent).
- [x] For each mammal folder in `samples/` (one folder per species/trip), run both models
      under the real workflow (crop on, the trip's geo filter) with `--k 1`:

```powershell
uv run wildid samples\<folder> --model bioclip-2   --crop --country <X> --k 1 --format json --output out\<folder>-b2.json
uv run wildid samples\<folder> --model bioclip-2.5 --crop --country <X> --k 1 --format json --output out\<folder>-b25.json
```

- [x] Tabulate top-1 correctness per model (the folder name is the ground truth):

```powershell
uv run python - <<'PY'
import json, pathlib
for f in sorted(pathlib.Path("out").glob("*-b2.json")):
    name = f.name.removesuffix("-b2.json")
    pair = [json.loads(p.read_text(encoding="utf-8"))
            for p in (f, f.with_name(f"{name}-b25.json"))]
    for tag, doc in zip(("bioclip-2  ", "bioclip-2.5"), pair):
        tops = [r["predictions"][0]["species"] for r in doc["results"] if r["ok"]]
        print(name, tag, "top-1:", tops and max(set(tops), key=tops.count), f"n={len(tops)}")
PY
# then count folders/frames where each model's top-1 matches the known species;
# save the disagreeing frames for an eyeball pass.
```

- [x] Optional second pass without the geo filter (unconstrained candidates separate the
      models more; the filtered run reflects real use).
- [x] While each model runs, record its process VRAM from `nvidia-smi` — the plan's B4
      radio subscripts want measured figures in place of the estimates (~5 GB bioclip-2,
      ~8 GB bioclip-2.5; "both loaded" ≈ their sum minus one CUDA context, measurable
      directly once B4's multi-model daemon exists).
- [x] Decision rule: 2.5 ahead by ≥ 2 percentage points over ≥ 200 frames → the radio
      subscript may say "more accurate (+N pp on owner mammal set)"; within noise → the
      subscript stays coverage/speed only ("no reptiles; larger and slower"), and consider
      dropping the radio. Log the numbers in `docs/acceptance.md` and note the outcome in
      `docs/decisions/0001-bioclip-25.md`.

## When something fails

Fix-or-file per deviation with: the step number, the artifact (sidecar file, serve log,
screenshot of the Keyword List / error dialog), and the LR version. Plugin-side quick levers
that exist without code changes: `engine.json` (`start`, `cli`, `cacheDir`) next to
`Info.lua`.
