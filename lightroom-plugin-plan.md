# `wildid` × Lightroom Classic — build plan (daemon + plugin, pre-import sidecars) and distribution plan

**Status:** plan, for review
**Owner:** Trogious
**Date:** 2026-10-24
**Scope:** options **B** (local daemon `wildid serve` + Lua plugin over `LrHttp`) and **C** (pre-import XMP sidecars), plus a distribution plan for handing the whole thing to other photographers. Option A (one-shot CLI shell-out from the plugin) is explicitly out of scope; `--files-from` with it.
**Relation to the MVP plan:** this executes post-MVP backlog item 8 ("output writers … JSON sidecar per image; optional XMP keyword write-back for Lightroom") and adds the daemon. The CLI contract in `species-id-mvp-plan.md` §4 is only ever extended, never changed (flags added: `--format`, `--output`, `--write-xmp`, `--xmp-mode`, `--min-score`; command added: `serve`).

Confidence tags as in the MVP plan: **[C]** certain (checked), **[L]** likely (strong inference), **[G]** guessing (verify in the phase that needs it).

> **Execution status (2026-10-24):** Phases S, C, B1 (including `POST /prefetch` pulled
> forward from B3), B2 and D1 are implemented (ADR 0005; wildid 0.2.0). D3 was skipped on
> request, then built on 2026-10-25 as `.github/workflows/release.yml` with a
> **manual-dispatch-only** trigger (artifacts always, draft Release on request) until the
> local installer build is validated; `installer/windows/build.ps1` stays the local build.
> Still open before calling B2/D1
> accepted: the manual Lightroom pass on the Windows box (plugin has only been exercised
> against the real daemon outside Lightroom) and compiling/running the installer on Windows,
> including the §1.1 verify-items (Modules auto-load, `io`/`os.getenv` in LR's Lua).
> The runnable checklist for that Windows acceptance run, with expected results and the
> PowerShell probes, is **`docs/acceptance-lightroom.md`**; log outcomes in
> `docs/acceptance.md`. Species collections (variant A of the follow-up discussion) shipped
> with plugin 0.2.1 and are covered by the same checklist; class collections (`Mammalia`,
> `Aves`, `Reptilia`… for the "bioclip-2 on import, mammals again through 2.5" workflow) in
> plugin 0.3.1 with the engine spelling GBIF's reptile classes as Reptilia (ADR 0005, amendment
> 2026-10-27); on 2026-10-28 those flat class collections gave way to a class/genus/species
> tree of collection sets under the chosen set (ADR 0005, amendment 2026-10-28; acceptance box
> in `docs/acceptance-lightroom.md` §B). The Windows pass (LrC 15.4.1)
> accepted sections 0–E on 2026-10-25. **B3 shipped 2026-10-25** (wildid + plugin 0.3.0, ADR
> 0006): per-photo geo from GPS, Smart-Preview fallback, `LrSdkMinimumVersion` pinned to 15.0;
> its acceptance items are the open boxes in `docs/acceptance-lightroom.md` §B.

---

## 0. Proposed decisions (confirm before execution)

| # | Decision | Value |
|---|---|---|
| L1 | Plugin ↔ engine transport | HTTP on `127.0.0.1` only, daemon started on demand, bearer token. No shell-out from Lua in the classify path. |
| L2 | Server implementation | stdlib `http.server.ThreadingHTTPServer` + `json`. **No new Python dependencies** (FastAPI/uvicorn is exactly the bloat the project rejected for SpeciesNet). One inference lock; requests queue. |
| L3 | Server discovery | `serve` binds port 0 (OS-assigned) and writes `<cache_dir>/serve.json` `{port, token, pid, protocol, version, started_at}` with owner-only permissions. The plugin reads that file; no port configuration UI. |
| L4 | Batch progress | The **plugin chunks** (16–32 photos per `POST /classify`) and drives `LrProgressScope` between chunks. No async job API in v1. |
| L5 | Keyword policy lives in Python | `keywords.py` maps predictions → keyword paths + review flag. The server returns `suggested_keywords` per photo; C's sidecar writer uses the same module. Lua stays a dumb writer, policy changes never touch the plugin. |
| L6 | Keyword shape | `WildID\|<class>\|<genus>\|<Genus species>` (genus since 2026-10-28, family before: ADR 0005) with the common name as a keyword **synonym**; plus `WildID\|review` when score < `--min-score` (default 0.5) or the unconstrained top-1 disagrees with the place list. Top-1 only — top-k as keywords is noise. Root name configurable. |
| L7 | Sidecars (C) are **pre-import only**, RAW only | Write `<basename>.xmp` next to `.arw/.nef/.cr3/...`. JPEG/TIFF need *embedded* XMP (LR ignores sidecars for them) → skipped with a warning in v1. The plugin never writes sidecars; post-import results go through the catalog. |
| L8 | Sidecar safety | Default `--xmp-mode new-only`: an existing `.xmp` is skipped and listed. `--xmp-mode merge` appends `dc:subject` / `lr:hierarchicalSubject` entries and touches nothing else; atomic write (temp + rename). Never delete or rewrite develop settings. |
| L9 | Daemon lifetime | `--idle-exit` (default 900 s) frees the GPU when unused; `POST /shutdown` from the plugin's menu. The plugin health-checks and offers to start the server when it is down. |
| L10 | Geo per request | `POST /classify` carries the geo spec; the server caches built filter masks per `(place, taxa, rank)` (small LRU). Geo resolution stays cache-first; the daemon never fetches with `offline=true` in the request (default). |
| L11 | Distribution unit | **Decided 2026-10-24: packaging option 1.** One per-user **online installer** per OS that ships the Lua plugin + `uv` + the locked project, resolves the environment at install time (`uv sync --frozen`), and installs the plugin into Lightroom's auto-load `Modules` folder. Model weights are **not** bundled (gated + huge); first-run setup prefetches. Unsigned (L14; signing is phase P). |
| L12 | Platforms | v1 Windows (x64, CUDA with CPU fallback — the plugin's audience runs LR Classic on Windows/macOS only). macOS: removed from the backlog 2026-10-25, planned on paper from 2026-10-28 and **built on 2026-11-14** on the owner's go (Apple Silicon, `--device mps`, zip installer; ADR 0008; the acceptance on a Mac is open: `docs/acceptance-macos.md`). Linux stays dev-only (no LR Classic). |
| L13 | Pricing & licence | **Free app** (decided 2026-10-24); **open source under AGPL-3.0-or-later in a public GitHub repository** (decided 2026-11-04, ADR 0007; the `ultralytics` AGPL dependency made closed source the expensive option). Review of the third-party terms and `THIRD_PARTY_LICENSES` stay in phase P (§6.6). |
| L14 | Distribution posture | **Private first** (decided 2026-10-24): built and versioned like a real release, used by Trogious only, with the unsigned installer attached to the repository's GitHub Releases. **The repository is public since 2026-11-15** (owner; ADR 0007); the installers are still unsigned. Signing, licensing, winget/Homebrew/Adobe Exchange are parked in **phase P — public release** (§6.6). |

---

## 1. Facts and verify-items

### 1.1 Lightroom Classic SDK (Lua 5.1)
- **[C]** Plugins are Lua only; no Python embedding. UI via `LrView`/`LrDialogs`/`LrBinding`, menu entries via `LrExportMenuItems` / `LrLibraryMenuItems` in `Info.lua`, long work inside `LrTasks.startAsyncTask`, progress via `LrProgressScope` (cancellable).
- **[C]** `LrHttp.get/post` work against `http://127.0.0.1:<port>` with custom headers. Timeout is settable. **[L]** Default timeout is generous enough for a 32-photo chunk, set it explicitly anyway.
- **[C]** Catalog access: `catalog:getTargetPhotos()` (current selection), `photo:getRawMetadata('path')`, `('gps')`, `('isVirtualCopy')`, `('fileFormat')`; writes inside `catalog:withWriteAccessDo`.
- **[C]** Keywords: `catalog:createKeyword(name, synonyms, includeOnExport, parent, returnExisting)` builds hierarchies; `photo:addKeyword(kw)`. Keyword objects should be cached per run (create-or-get once per path).
- **[C]** Custom metadata: `LrMetadataProvider` declares plugin fields shown in the Metadata panel; **[L]** fields with `searchable=true` (and `dataType='string'`) are filterable in smart collections ("Searchable Plug-in Metadata").
- **[L]** Lua in LR has `io.*` and `os.getenv` available to plugins (needed to read `serve.json` and expand `%LOCALAPPDATA%`), and `LrFileUtils`/`LrPathUtils` cover the rest. **Verify in B2 first hour.**
- **[L]** Plugins placed in the `Modules` folder auto-load without the Plug-in Manager "Add" step: Windows `%APPDATA%\Adobe\Lightroom\Modules\`, macOS `~/Library/Application Support/Adobe/Lightroom/Modules/`. **Verify in D1 (distribution phase) on a clean machine.**
- **[L]** `LrTasks.execute` on Windows flashes a console window for console binaries — relevant only to the "Start server" button; mitigate with a windowless launcher (D-phase) or `start /min`.
- **[C]** There is no SDK call to force "Read Metadata from File" — which is why C is pre-import only (L7).
- **[C]** A JSON codec is not in LR's Lua; bundle `dkjson.lua` (MIT, pure Lua) inside the plugin.

### 1.2 Lightroom metadata behaviour
- **[C]** For proprietary RAW (ARW…), LR reads a `<basename>.xmp` sidecar **at import** and shows its keywords; `dc:subject` (flat) + `lr:hierarchicalSubject` (hierarchy) is the pair LR itself writes.
- **[C]** For JPEG/TIFF/DNG, XMP lives embedded in the file; LR ignores sidecar files for them. (DNG: embedded too — so C's sidecar path covers ARW/NEF/CR3/CR2/ORF/RAF/RW2 but **not** DNG. DJI drone DNGs would need embedded-XMP writing — out of v1, note in help text.)
- **[C]** Post-import external XMP edits cause "metadata changed on disk" conflicts and the sidecar also carries develop settings → L7/L8.

### 1.3 Engine facts (from this repo)
- **[C]** Model + label data load once per process; warm load is seconds (6–8 s for bioclip-2.5; bioclip-2, the default, is smaller), plus torch import. This is the whole case for the daemon.
- **[C]** `Prediction` already carries species, common name, score, genus, family, class — the JSON writer and keyword mapper need no new model work.
- **[C]** Loaders pre-shrink with the model's own transforms; the daemon must keep using `clf.preshrink` / `prepare_inputs` exactly as `cli.py` does (ADR 0003 §5 re-measure rule applies if touched).
- **[C]** `apply_filter` mutates classifier state → the server must serialize requests (L2) and re-apply masks per request from the LRU (L10).
- **[C]** `constants.cache_dir()` exists for `serve.json` (L3).

---

## 2. Architecture

```
                         ┌───────────────────────────────┐
                         │ Lightroom Classic (Lua plugin)│
                         │  selection → paths → chunks   │
                         │  keywords + custom metadata   │
                         └──────────────┬────────────────┘
                                        │ LrHttp POST /classify (JSON, token)
                                        ▼
 wildid CLI ──────────────┐   ┌──────────────────────┐
  classify --format json  │   │ wildid serve (daemon) │ 127.0.0.1:<port0>, serve.json
  classify --write-xmp (C)│   │  model warm, 1 lock   │ idle-exit frees VRAM
                          │   └──────────┬───────────┘
                          ▼              ▼
                   ┌─────────────────────────────┐
                   │ shared core (new)           │
                   │  results.py: run → dict/JSON│
                   │  keywords.py: → kw paths,   │
                   │    review flag (L5/L6)      │
                   │  xmp.py: sidecar writer (C) │
                   └─────────────────────────────┘
                   existing: images / model / geo / output
```

One classify pipeline, three front doors (CLI text, CLI json/xmp, HTTP). The pipeline pieces currently inlined in `cli.py` (`_run_single`/`_run_directory`) get extracted into a `pipeline.py` the daemon can call without typer — a refactor, not a behaviour change; existing CLI output stays byte-identical (tests assert it).

### JSON result schema (v1, `protocol: 1`)

```json
{
  "wildid": "0.2.0", "protocol": 1,
  "model": "bioclip-2", "device": "cuda", "precision": "tf32",
  "candidates": {"count": 412, "place_label": "Brazil › Mato Grosso",
                  "taxa": ["Mammalia","Reptilia"], "fetched": "2026-10-23", "rank": "species"},
  "keywords": {"root": "WildID", "flat": ["animals","wildlife"]},
  "results": [{
    "path": "D:/photos/DSC04512.ARW", "ok": true, "error": null,
    "predictions": [{"species": "Panthera onca", "common_name": "Jaguar", "score": 0.962,
                      "genus": "Panthera", "family": "Felidae", "class": "Mammalia"}],
    "unconstrained": {"species": "Panthera onca", "score": 0.871, "in_candidates": true},
    "crop": {"detected": true, "conf": 0.93}, "second_opinion": null,
    "review": false,
    "suggested_keywords": [{"path": ["WildID","Mammalia","Panthera","Panthera onca"],
                             "synonyms": ["Jaguar"]}, {"path": ["animals"], "synonyms": []},
                            {"path": ["wildlife"], "synonyms": []}]
  }]
}
```

---

## 3. Phase S — shared core *(gate for both B and C)*

- [x] `pipeline.py`: extract load→(crop)→predict→(anomaly/opinion) from `cli.py` into functions returning plain result objects; `cli.py` becomes a thin caller. Text output byte-identical (snapshot test before/after).
- [x] `results.py`: result objects → dict (schema above); `--format [text|json]` + `--output PATH` on `classify` (reserved names from §4 of the MVP plan). `text` stays the default.
- [x] `keywords.py`: `suggest(result, *, root, min_score) → keywords + review flag` per L6; unit tests incl. UTF-8 common names, missing common name, genus-rank geo runs.
- **Accept when:** `wildid samples/trip --format json --output out.json` round-trips through `json.load`, text output unchanged, ruff/pytest green.
- **Effort:** 1–2 focused sessions.

## 4. Phase C — pre-import sidecars

- [x] `xmp.py`: minimal RDF/XML writer (template for new files; `xml.etree` namespace-aware append for `merge`). No new dependencies — python-xmp-toolkit needs the exempi C library and is a packaging liability.
- [x] Flags on `classify`: `--write-xmp`, `--xmp-mode [new-only|merge]` (default new-only), `--min-score FLOAT` (shared with keywords), `--dry-run`. Writes `dc:subject` (species, common name, root tag), `lr:hierarchicalSubject`, and a `wildid:` provenance block (model, score, place, date) that LR preserves but ignores.
- [x] Behaviour: RAW files except `.dng` only (fact 1.2); JPEG/DNG counted and warned once. Existing sidecars per L8. End-of-run summary: written / merged / skipped / failed. Exit codes unchanged.
- [x] Tests: golden-file comparison for a fresh sidecar; merge against a committed LR-style `.xmp` fixture (hand-built text file — no photos committed, per repo rule); idempotence (second run with `merge` adds nothing); atomicity (write failure leaves the original).
- **Accept when:** run over a copy of a real card folder → import into LR Classic shows the full hierarchy + synonyms on ARW files, develop settings of a pre-existing sidecar survive `merge` untouched (manual check on the Windows box), `--offline` run works from cache.
- **Effort:** 2–3 sessions (XMP merge is the slow part).

## 5. Phase B — daemon + plugin

### B1 — `wildid serve`
- [x] `serve.py` + `wildid serve [--model|--device|--precision|--idle-exit|--token-file]`: offline env prepared exactly like classify (`prepare_runtime_env(allow_model_download=False)` before heavy imports); model loads at startup; binds `127.0.0.1:0`; writes `serve.json` (L3) and removes it on exit.
- [x] Endpoints: `GET /health` → `{ready, protocol, version, model, device}` (503-style `ready:false` while loading); `POST /classify` (schema above; request carries `paths`, `k`, `geo`, `crop`, `second_opinion`, `min_score`, `keyword_root`); `POST /shutdown`. Every request requires the bearer token — localhost is reachable by any local process and by browsers (DNS-rebinding/CSRF), the token is the defence, not the bind address alone.
- [x] Single inference lock; per-request geo mask from the LRU (L10); unknown paths / unsupported extensions come back as per-file errors, never 500s. Idle-exit timer per L9.
- [x] Tests: handler tests against a stub classifier (no model, no network — repo rule); token rejection; idle-exit; mask-LRU behaviour; a `scripts/serve_smoke.py` that exercises a real session for manual runs.
- **Accept when:** scripted session classifies 500 mixed JPG/ARW in 16-photo chunks with correct results and stable RSS; VRAM returns to baseline after idle-exit; second server start while one runs refuses cleanly (pid check in `serve.json`).
- **Effort:** 2–3 sessions.

### B2 — Lua plugin MVP (`lrplugin/wildid.lrplugin/`)
- [x] Skeleton: `Info.lua` (SDK min 6.0, menu items), `dkjson.lua`, `ServerClient.lua` (read `serve.json`, health-check, chunked POST, timeouts), `Identify.lua` (dialog + run loop), `Metadata.lua` (fields: species, score, status, model, run date; searchable), `Settings.lua` (prefs: keyword root, min-score, chunk size, geo presets, engine path).
- [x] Dialog: geo preset dropdown (persisted; country/region/place-id + taxa), crop toggle, k, min-score, dry-run. Flow: selection → skip virtual copies/videos/missing files (reported) → chunks → `withWriteAccessDo` per chunk: keyword hierarchy (cached create-or-get), `addKeyword`, custom metadata, review keyword → progress with cancel → summary dialog.
- [x] Server-down path: offer "Start WildID server" (configured engine path; `LrTasks.execute` detached) then poll `/health` with backoff; clear error naming `wildid serve` otherwise. Protocol check: `/health.protocol != 1` → update message, abort.
- [x] Manual test checklist (no LR test harness exists): Windows LR Classic current version; selections of 1 / 50 / 1000; cancel mid-run; server killed mid-run; non-ASCII paths; virtual copies; keyword hierarchy collision with an existing user keyword named `WildID`.
- **Accept when:** on the Windows/4090 box, selecting a Pantanal folder and running "Identify species…" tags ARWs with correct hierarchies at interactive speed (first run pays the model load once; subsequent chunks sub-second/photo), review photos land in a `WildID|review`-based smart collection, and cancel leaves the catalog consistent (whole chunks committed or not at all).
- **Effort:** 3–5 sessions — budget real manual time in Lightroom; Lua debugging is print-file-based.

### B4 — per-run model choice in the plugin (specced and built 2026-10-25)

Owner's request: pick the model per shoot — 2.5 when the cards hold only mammals, bioclip-2
when reptiles (or everything) are in play. Built as specced below (wildid 0.2.1, plugin
0.2.2); only the *wording* of the accuracy claim waits for the §E measurement in
`docs/acceptance-lightroom.md`. Added on build: the daemon probes the GPU
(`torch.cuda.mem_get_info`) and `/health` reports it; the plugin **disables** the
keep-both-loaded checkbox when detection succeeded and the card has < 20 GB (14 until the §E
measurement showed both models under load at ~15.7 GB), and leaves it
enabled when nothing was detected (CPU, probe failure, server not yet running).
*2026-11-15:* before the second model is loaded the rule is applied again to the running
server's `/health`, so a tick made while the memory was unknown is not honoured on a machine
below the threshold; and unified memory on a Mac has its own threshold, 30 GB (ADR 0008).

- **Engine (multi-model daemon):** `/classify` gains an optional `model` field;
  `ServerState` holds a classifiers dict and lazy-loads the second model under the inference
  lock on first use; new `POST /warmup {model}`; `/health` lists loaded models. Loaded models
  stay for the process lifetime (torch does not reliably give VRAM back) — `--idle-exit`
  remains the release mechanism. Geo plans, stages and keyword policy are model-independent
  already. Additive request fields: protocol stays 1.
- **Plugin dialog:** radio group, default **bioclip-2** (the CLAUDE.md default-model rule;
  the radio is per-run selection, not a default flip), with subscripts:
  - bioclip-2 — "all taxa including reptiles; faster; ~5 GB VRAM"
  - bioclip-2.5 — "no reptiles — reptile photos get confident wrong answers; larger and
    slower; ~8 GB VRAM" (append "more accurate (+N pp on owner mammal set)" only if §E
    clears its ≥2 pp / ≥200 frames bar)
  - below the radios, a checkbox: "Keep both models loaded (~13 GB VRAM) — instant
    switching", which fires `/warmup` for the unselected model once the server is ready.
- **Guard:** selecting 2.5 while the run's taxa include Reptilia (explicitly, or via the
  default taxa with geo on, or no geo at all) shows a one-line warning in the dialog.
- VRAM figures are **[L]** estimates (fp32 weights + fp32 text matrix + activations:
  ~1.7+2.5 GB vs ~3.9+3.8 GB; both ≈ 13 GB with one shared CUDA context) — §E records the
  measured values and the subscripts ship with those.

### B3 — polish (post-acceptance, optional) — **done 2026-10-25 (0.3.0)**
GPS → auto-geo (backlog #5) passed per photo from `photo:getRawMetadata('gps')`; Smart-Preview fallback for offline originals; `POST /prefetch` so the plugin can fetch a trip's geo list while online.

As built (ADR 0006): the engine owns the resolution — `gps.py` reads EXIF GPS (`exifread`),
buckets positions into 0.25° cells, and `places/nearby` resolves each cell once to the
iNaturalist country or state (`--geo-level`), cached in the geo cache; `autogeo.py` groups the
photos by place and runs the pipeline once per group because the classifier holds one filter.
CLI: `--geo-auto [--geo-level region]`, `wildid prefetch --gps-from PATH`. Daemon: `geo:
{auto, level, rank, taxa}` plus an optional per-path `gps` map (catalog positions win over
EXIF), `POST /prefetch {gps: [[lat, lon]…], level}`. Plugin: "Candidates" popup (none / place /
each photo's GPS), the prefetch dialog's "selected photos' GPS" source (distinct cells only),
Smart Preview DNG as the sent file for offline originals (`WildidPhotos.lua`). Unresolved
cells and photos without a fix run unfiltered; only the former are flagged for review, with
the prefetch command in the reason. The result schema gained an additive `place` object and
`candidates.auto_level/auto_places`; protocol stays 1.

---

## 6. Distribution plan

### 6.1 The constraints that shape everything
- **[C]** The environment is ~5 GB installed with CUDA torch (MVP plan §7.1); CUDA wheels alone are gigabytes. A true single-file binary is off the table; "installer that assembles" is the realistic reading of "single package".
- **[C, checked 2026-11-04 against the Hugging Face API]** TreeOfLife-200M, which holds the text embeddings for both models, is CC0-1.0 and **not gated**; the earlier "gated, accept the terms" belief was wrong. Redistributing the `.npy` would be allowed, but they are 2.7–3.3 GB, so the installer ships no weights and first-run setup prefetches per user. The setup wizard's token step says so since 2026-11-13: optional, Enter skips it.
- **[C]** GitHub release assets cap at 2 GiB per file — a bundled-CUDA offline installer wouldn't fit on Releases regardless.
- **[C]** PyInstaller-style freezing of torch is notoriously fragile (hidden imports, doubled disk, slow extraction, AV false positives) and we'd carry that pain per release. **[L]** tags on the specific failure modes, but the direction is well-established.
- **[C]** `ultralytics` (imported for MegaDetector `--crop` / `--second-opinion`) is **AGPL-3.0**. Phase-P concern: nothing triggers while the installer is conveyed to no one (L14). Notes for then: with the app open source the obligations are satisfiable by construction, and the installer never redistributes AGPL bits itself — the user's machine resolves them from PyPI at install time (**[L]** standard pragmatic reading). **[L]** MDv6 weights are MIT via PyTorch-Wildlife; the weights-vs-ultralytics-training-code question is a phase-P verify-item. If the app were ever closed: detector stages become an opt-in user-side extra or an ultralytics-free reimplementation (ONNX export).

### 6.2 Packaging options compared

| | 1. Online installer: bundled `uv` + lockfile **(decided, L11)** | 2. PyInstaller one-dir, offline installer | 3. Bootstrap script (`irm …/install.ps1 \| iex`) |
|---|---|---|---|
| Installer size | ~50–150 MB (uv + sources + plugin) | 3–6 GB (CUDA) / ~1 GB (CPU) | ~0 (one command) |
| Install-time network | yes — pinned wheels via uv (needed for prefetch anyway) | no (for the env) | yes |
| Fidelity to dev env | exact (`uv.lock`) | frozen snapshot, separate debug surface | exact |
| CUDA + CPU handling | one installer; uv resolves the pinned torch index per machine | separate builds + variant picker | one script |
| Fragility | low (uv is a static binary) | high (torch freezing, AV flags) | medium (PowerShell policies, proxies) |
| Photographer UX | double-click, wizard, done | double-click, huge download | terminal — fails the audience |
| Hosting | GitHub Releases fits | external storage (R2/S3/HF) required | GitHub |

**Decided: option 1 (L11).** Install-time network is not a real cost because first-run prefetch needs the network regardless (6.1). Option 2 stays documented as the fallback if uv-at-install misbehaves on real machines (corporate proxies are the known hazard).

### 6.3 Windows installer (D1) — reference design
Inno Setup, per-user (no UAC), unsigned (L14; signing is phase P). It:
1. Installs to `%LOCALAPPDATA%\Programs\WildID\`: `uv.exe`, the project (sources + `uv.lock` + `pyproject.toml`), and thin launchers `wildid.cmd` / windowless `wildid-server.exe` (tiny compiled launcher so the plugin's "Start server" button doesn't flash a console — fact 1.1).
2. Runs `uv sync --frozen` (progress page; uv also provisions the pinned Python — no system Python assumed; CUDA vs CPU torch resolved by the lockfile's platform markers or an installer checkbox — decide in D1 once tested on a GPU-less machine).
3. Copies `wildid.lrplugin` into `%APPDATA%\Adobe\Lightroom\Modules\` (auto-load, fact 1.1 — verify-item) and writes the engine path into the plugin's install manifest.
4. Creates Start-menu entries: "WildID Setup" (first-run wizard) and "WildID Server".
5. Uninstaller removes program + plugin, leaves caches (weights, geo) with a checkbox.

**First-run wizard** = new `wildid setup` command (console, rich): HF account + terms link, token paste (stored via `huggingface_hub`), model choice, `prefetch` with progress, optional trip geo prefetch, final `--offline` verification — exactly the pre-trip checklist, automated. The plugin detects a missing cache (`/health` or exit 2) and points at the wizard.

**Signing: parked in phase P (§6.6).** The installer ships unsigned; SmartScreen's "More info → Run anyway" is acceptable for self-use on your own machines.

### 6.4 macOS — built 2026-11-14, acceptance open
Removed from the backlog on 2026-10-25, reopened as a paper plan on 2026-10-28 (Apple Silicon
only, MPS, zip + `install.sh`; `.pkg`/`.dmg` ruled out by owner decision,
signing at phase P). The owner said "build macOS version now" on 2026-11-14: the engine runs
on MPS, `installer/macos/` builds the zip, and `release.yml` builds it and installs it on a
`macos-15` runner. ADR 0008 is the record of what was decided and found. The build plan
itself, `docs/PLAN_MacOS.md`, was removed on 2026-11-15 once it had been executed (owner).
The owner declared macOS available on 2026-11-15; its acceptance is still open:
`docs/acceptance-macos.md` lists what is to be run.

### 6.5 Release pipeline (D3)
- GitHub Actions: tag → build the Windows installer (Inno; it carries the plugin, so no separate plugin zip) → attach to the repository's Release (fits under 2 GiB by design) → checksums. No sign step yet; phase P inserts it. *(As built: the macOS zip is the second download (ADR 0008). Since 2026-11-15 a pushed tag publishes the release itself, as a pre-release for an `aN`/`bN`/`rcN`/`.devN` version; a manual run with `create_release` still makes a draft. `installer/README.md` has the details.)*
- Versioning: engine, plugin and protocol versions move together; `/health` carries `protocol` (B2 already checks it). Installer upgrades are re-runs (idempotent `uv sync --frozen`).
- Support matrix in README: Windows 10/11 x64; NVIDIA GPU optional (CPU works — set expectations: **[L]** roughly 1–3 s/photo on a modern CPU with bioclip-2 vs ~0.1 s on the 4090); LR Classic 12+ (**[G]** pick exact floor in B2; SDK features used are old, so likely much lower).
- **Effort:** D1 3–5 sessions; D3 1 session.

### 6.6 Phase P — public release (parked until Trogious reopens it)

Everything deliberately skipped while the app is private-use lives here, so going public is a checklist, not a re-plan. **Tripwire: phase P opens before the installer is handed to any other person — conveying to one photographer is distribution.** *(2026-11-15: the repository is public, owner. It has no release yet; the items below are open as written.)*
- Licence: **decided 2026-11-04 (ADR 0007) — AGPL-3.0-or-later for the whole repository, public GitHub repo, releases from the same repo.** Still to do here: review of the third-party terms (TreeOfLife-200M gate, bioclip-2/2.5 weights **[L]** MIT, SpeciesNet **[L]** Apache-2.0, rawpy/LibRaw **[L]** LGPL/CDDL, the MDv6-weights question, §6.1) and `THIRD_PARTY_LICENSES` for what the installer bundles.
- Windows signing: SignPath Foundation first, free for open-source projects (**[C, checked 2026-11-15 against https://signpath.org/terms]**; the page is headed "Code of conduct", marked draft and carries no date, so re-read it before applying), then Certum (**[L]** ~€70/yr), then Azure Trusted Signing (**[L]**). Calendar-bound, start paperwork first; add the sign step to D3's CI. The SignPath terms against wildid as it stood on 2026-11-15:
  - What it gives: the certificate is issued to SignPath Foundation, so the installer names SignPath Foundation as its publisher, not WildID. Every release needs a manual signing approval. Acceptance is their decision alone, with no appeal, and they may revoke a certificate.
  - Not met yet: "Released" (the project "must already be released in the form that should be signed"; the repository is public since 2026-11-15 and has no release) and "Documented" (the download page must describe the program; the website does, and GitHub Pages is switched on for it since 2026-11-15). The order is therefore fixed: public repository, an unsigned public release, then the application. On this route the first public release is necessarily unsigned, which settles question 7 of §8 for it.
  - Their judgement, the real risk: for executables they "require a certain verifiable reputation" and name no threshold. On 2026-11-15 the project was three weeks old and its public repository new, with no stars, no forks and no release.
  - To ask them, because the terms do not settle it: (1) the licence must be OSI-approved "without commercial dual-licensing for all components": wildid has one licence, but `ultralytics` is offered under AGPL-3.0 and an Enterprise licence (ADR 0007); **[L]** the clause aims at the applicant's own code. (2) The project may not contain any "proprietary, non open-source component": the installer holds only open-source parts (uv.exe, the sources, the plugin, three launchers), but its `uv sync` step downloads the CUDA build of PyTorch, which carries NVIDIA's proprietary libraries (**[L]** read from `uv.lock`: the Windows wheel comes from the cu130 index and takes none of the separate NVIDIA packages; the wheel was not opened), and **[L]** these are not the System Libraries the terms exempt. (3) The models are downloaded at setup under terms that are not software licences (MegaDetector weights CC BY 4.0, SpeciesNet per its Kaggle page).
  - To do before applying: a "Code signing policy", under that exact term, on the project's home page and its download and release pages (the website's start page, which holds the download section, and the README). It carries the line "Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org)", the team roles and their members (authors, reviewers, approvers: the owner holds all three), and a link to `privacy.html` or the sentence "This program will not transfer any information to other networked systems unless specifically requested by the user or the person installing or operating it"; the terms also ask for the privacy policies of the services the program uses where users are affected (iNaturalist, GBIF, Hugging Face), which `privacy.html` names without linking their policies. Multi-factor authentication on GitHub and on SignPath for every team member (the check could not see the account's setting). `VersionInfoVersion` in `installer/windows/wildid.iss`, because product name and product version must be set on the signed file (**[C]** read from the draft 0.3.1 installer: product name "WildID" and product version "0.3.1" as text, the numeric file and product versions 0.0.0.0, the file version text empty; **[L]** that directive takes numbers only, so a pre-release suffix has to be cut off as for the plugin's `VERSION`).
  - Met as it stands: no malware, no hacking tools; maintained; the owner's own repository and build scripts; built from the tag on a GitHub-hosted Windows runner (`release.yml`); per-user install without elevation; an uninstaller. No telemetry, and every connection is started by the user and listed on `privacy.html` (photo positions go to iNaturalist only when the user picks GPS in the prefetch dialog), so **[L]** the clause on software that "collects user data and transfers it to systems not specified by the user" (policy shown during installation, install options to switch it off) does not apply. The bundled uv.exe is an upstream open-source binary: the terms allow it inside the signed installer and forbid signing it with the project's certificate.
  - Not read: the application form at https://signpath.org/apply did not load, so what it asks is unknown.
- Channels: winget manifest, **[L]** Adobe Exchange listing; public README with support matrix (no Hugging Face account is needed: the repos are public).

---

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| XMP merge corrupts a sidecar with develop settings | low, high impact | new-only default; merge appends only `dc:subject`/`lr:hierarchicalSubject`; atomic write; LR-style fixture test; manual LR check in Phase C acceptance |
| LR Lua lacks `os.getenv`/`io` for `serve.json` | low | verify hour one of B2; fallback: plugin asks installer-written manifest for the path (it already knows the engine path) |
| Localhost server abused by another local process / browser | low | loopback bind + mandatory bearer token + owner-only `serve.json`; no CORS |
| `Modules` auto-load path wrong/changed | low | D1 verify on clean machine; fallback: installer finishes with Plug-in Manager instructions |
| uv-at-install fails behind proxies/AV | medium | clear error + retry; documented offline fallback (option 2 build) if it becomes common |
| TreeOfLife licence forbids any redistribution convenience *(phase P)* | medium | phase-P licence review gates bundling ideas only; default plan already assumes per-user prefetch |
| ultralytics AGPL-3.0 vs distribution *(phase P)* | low | at-install dependency resolution + open source, in a public repository since 2026-11-15 (ADR 0007); phase P confirms the MDv6 weights question |
| ~~HF account friction loses non-technical users~~ *(resolved)* | none | The model and dataset repos are public (MIT / CC0-1.0, checked 2026-11-04): no account, no terms to accept. The wizard's token step is optional since 2026-11-13. |
| Chunked requests make partial runs on cancel | certain, by design | whole-chunk catalog writes; summary names the untagged remainder; re-run is idempotent (same keywords) |

---

## 8. Questions asked while planning (none is open)

1. ~~Keyword root name~~ — **`WildID`**, configurable. Built that way; settled, not a pending
   question (owner, 2026-11-15).
2. ~~`--min-score` default~~ — **0.5**; the scores are a softmax over the candidate set and
   the help text carries the caveat. Built that way; settled (owner, 2026-11-15).
3. ~~Windows signing route/budget~~ — moved to phase P (unsigned until then, L14).
4. ~~Mac in scope, or Windows-only v1?~~ — **Windows-only v1**; macOS planned on paper since 2026-10-28, built on the owner's go on 2026-11-14 (ADR 0008), acceptance open.
5. ~~Is the distributed tool free/non-commercial?~~ **Answered 2026-10-24: free (L13).**
6. ~~Licence for wildid's own code~~ — **AGPL-3.0-or-later, decided 2026-11-04 (ADR 0007).**
7. ~~Ship unsigned vs hold?~~ — v1 ships unsigned (L14). For the first public release §6.6 settles it: on the SignPath route that release is necessarily unsigned.

## 9. Execution order

```
S (1–2) ─► C (2–3) ─► B1 (2–3) ─► B2 (3–5) ─► D1 (3–5) ─► D3 (1) ─► [B3, P]
```

C ships value before any Lua exists (the sidecar workflow is usable standalone). Phase P (licensing, signing, channels — §6.6) stays parked until the decision to go public, and must reopen before the installer is given to anyone else. *(2026-11-15: the repository is public, owner; signing and channels are still open, §6.6.)*
