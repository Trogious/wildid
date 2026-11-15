# `wildid` — Species ID CLI (BioCLIP 2.5 + TreeOfLife) — MVP Plan

**Status:** plan, ready for execution
**Owner:** Trogious
**Date:** 2026-10-23
**Target machine:** local workstation, NVIDIA RTX 4090 (24 GB), Windows or Linux

> Working name is `wildid` (package and CLI command). Rename freely; nothing below depends on it.

---

## 0. Decisions locked (do not re-litigate during execution)

| # | Decision | Value |
|---|---|---|
| D1 | Deployment | Local, GPU (RTX 4090). No cloud, no Lambda. |
| D2 | Model | BioCLIP 2.5 Huge (`hf-hub:imageomics/bioclip-2.5-vith14`) with TreeOfLife-200M text embeddings. **Fallback:** BioCLIP 2 (`hf-hub:imageomics/bioclip-2`, pybioclip default) if the 2.5 path fails the Phase 0 time-box. Selectable via `--model`. |
| D3 | Library | `pybioclip` (MIT) for TreeOfLife prediction, taxa subsetting and batching. Do not reimplement what it provides. |
| D4 | Input | Positional `PATH`: a file or a directory. Directories are walked recursively. |
| D5 | Formats (MVP) | `.jpg`, `.jpeg`, `.arw` (Sony). **Post-MVP:** `.dng` (DJI, Pixel). |
| D6 | Top-k | File → top 5. Directory → top 3 per file. `--k` overrides both. |
| D7 | Geo params | `--continent`, `--country`, `--region` (= region in country). All optional. If given, the resolved species list **constrains the classifier's candidate set** (applied via `apply_filter`) — i.e. it is both the filter and the input to the classifier. |
| D8 | Geo precedence | Most specific wins: `region` > `country` > `continent`. `--region` requires `--country`. Lists are never unioned. |
| D9 | Geo data source | iNaturalist API v1 (`observations/species_counts`), cached on disk. GBIF only as a documented manual fallback. |
| D10 | RAW handling | ARW → embedded JPEG preview via `rawpy.extract_thumb()`. **Never full demosaic** (model input is 224 px; demosaicing 61 MP is pure waste). Demosaic only as a fallback when no usable preview exists. |
| D11 | Language / tooling | Python 3.12, `uv` for env + lockfile, `typer` CLI, `rich` output, `pytest`. |
| D12 | Implementation files | Created during execution. This document contains sketches only, not deliverable code. |
| D13 | Output (MVP) | **stdout only, text blocks.** No `--format`, no `--output`, no csv/json writers in MVP (post-MVP backlog). |
| D14 | Default geo taxa | `Mammalia,Reptilia,Amphibia,Aves` (mammals, reptiles, amphibians, **birds**). Birds stay in the default: they do not compete with mammal/reptile candidates, and excluding them forces bird photos into a confident wrong mammal/reptile. Use `--taxa Mammalia,Reptilia` for a tight list on purpose. |
| D15 | Offline operation | **Offline-first runtime (hard requirement).** `wildid PATH` never downloads models: it runs in Hugging Face offline mode and reads geo lists cache-first. `wildid prefetch` is the only command that downloads (model, embeddings, geo lists). `--offline` forbids every network call and fails fast with a prefetch hint if anything is missing. |

**Taxa glossary (values are taxonomic class names, as used by iNaturalist and TreeOfLife):** Mammalia = mammals · Reptilia = reptiles (lizards, snakes, crocodilians, turtles) · Amphibia = amphibians (frogs, salamanders) · Aves = birds.

---

## 1. Verified facts (so execution does not re-research)

Confidence tags: **[C]** certain (checked source), **[L]** likely (strong inference), **[G]** guessing (verify in Phase 0).

### 1.1 Models
- **[C]** BioCLIP 2.5 Huge: ViT-H/14, 986 M params, ~3.9 GB fp32, ~325 GFLOPs/image, 1024-d embeddings. HF id `imageomics/bioclip-2.5-vith14`. Loads with `open_clip.create_model_and_transforms('hf-hub:imageomics/bioclip-2.5-vith14')`.
- **[C]** BioCLIP 2: ViT-L/14, 428 M params, ~1.7 GB fp32, 768-d embeddings. HF id `imageomics/bioclip-2`. This is pybioclip's default model.
- **[C]** TreeOfLife-200M dataset repo (`imageomics/TreeOfLife-200M`, HF, `repo_type="dataset"`) contains the precomputed TOL text embeddings:
  - `embeddings/txt_emb_bioclip-2.npy` + `.json`
  - `embeddings/txt_emb_bioclip-2.5-vith14.npy` + `.json`
  - `embeddings/txt_emb_species.npy` + `.json` — duplicate of the BioCLIP 2 files, kept "to maintain pybioclip functionality for versions 2.1.x and earlier".
- **[L]** The dataset is gated on Hugging Face: accept its terms in the browser and authenticate locally (`hf auth login` or `huggingface-cli login`, or set `HF_TOKEN`) before first run. Phase 0 verifies.
- **[L]** GPU memory budget on 2.5: model ~3.9 GB + TOL text matrix (~930 k × 1024 × 4 B ≈ 3.8 GB) + activations. Comfortably < 12 GB of the 24 GB available. No fp16 tricks needed for MVP.

### 1.2 pybioclip (latest release 2.1.6, 15 Aug 2026)
- **[C]** Requires Python ≥ 3.10. `pip install pybioclip`.
- **[C]** `TreeOfLifeClassifier(model_str=..., pretrained_str=None, device='cpu')`. Pass `device='cuda'`.
- **[C]** `predict(images, rank, min_prob=1e-9, k=5, batch_size=10, callback=None)` — `images` is a path, a list of paths, **or a list of PIL images**. Returns a list of dicts with `file_name`, `kingdom`…`species`, `common_name`, `score`.
- **[C]** `get_label_data()` → pandas DataFrame of all TOL taxa (rank columns). Build it **once** per process; it is ~930 k rows.
- **[C]** `create_taxa_filter(rank, user_values)` → bool mask. **Raises `ValueError` if any value is unknown** → intersect the geo list with `get_label_data()['species']` first.
- **[C]** `apply_filter(mask)` restricts subsequent `predict()` calls to the kept taxa (precomputed embeddings → fast). There is no documented `clear_filter`; construct a second classifier or re-apply an all-True mask for the unconstrained pass.
- **[C]** `get_txt_emb()` / `get_txt_names()` / `get_tol_repo_id()` are overridable methods on `BaseClassifier`; the stock implementation hardcodes `embeddings/txt_emb_species.npy` and raises for unsupported `model_str`. **This is why 2.5 needs the override in §2.**
- **[C]** CLI: `bioclip predict --device cuda --rank species --k 5 --model ... [--subset file.csv | --cls file.txt | --bins file.csv] IMAGES...`, `bioclip list-tol-taxa --model ...`, `bioclip list-models`.
- **[C]** pybioclip's own "Geo-Restricted Taxon List Predictions" doc endorses exactly the D7 approach (subset of TOL by a regional species list) and warns: filtering by higher ranks (order/family) does **not** exclude non-local species — always filter at **species** rank.
- **[L]** `make_key()` for PIL inputs keys results by list index, not file name. Keep a parallel `paths` list and zip results back by order.
- **[C]** Windows is CI-tested by pybioclip (UTF-8 fixes landed in 2.1.1). Still force UTF-8 stdout (common names contain diacritics).

### 1.3 Images
- **[C]** `rawpy` (LibRaw bindings) reads Sony ARW and DNG; binary wheels exist for Windows and Linux.
- **[L]** `rawpy.imread(p).extract_thumb()` returns the embedded preview; `.format` is `rawpy.ThumbFormat.JPEG` (bytes → `PIL.Image.open(BytesIO)`) or `ThumbFormat.BITMAP` (ndarray → `PIL.Image.fromarray`). Exceptions to catch: `rawpy.LibRawNoThumbnailError`, `rawpy.LibRawUnsupportedThumbnailError`.
- **[L]** Sony bodies embed a reduced-size JPEG preview (roughly 1.6 MP class) — far above the 224 px model input. Extraction is tens of ms; demosaic of a 61 MP A7R V file is seconds. Hence D10.
- **[G]** The embedded preview may not carry orientation; for a classifier this is irrelevant (CLIP is orientation-tolerant enough), so ignore for MVP. Revisit when a detector/crop stage is added.

### 1.4 iNaturalist API (geo species lists)
- **[L]** `GET https://api.inaturalist.org/v1/observations/species_counts?place_id=<id>&iconic_taxa=<Mammalia|Reptilia|Amphibia|Aves|...>&quality_grade=research&per_page=500&page=<n>` → `results[].taxon.{name, rank, preferred_common_name, iconic_taxon_name}` ordered by observation count. `per_page` up to 500 on this endpoint.
- **[L]** A query set is capped at 10 000 results. Query **one iconic taxon per request series** so no series exceeds the cap (a continent's full vertebrate list can).
- **[L]** `GET /v1/places/autocomplete?q=<name>` → candidates with `id`, `name`, `display_name`, `admin_level`, `ancestor_place_ids`. Countries are `admin_level == 0`; states/provinces 10; counties 20. Continents exist as places (seen in third-party tooling: 97389 = South America, 97394 = North America — **verify and pin all seven in Phase 3**).
- **[C]** Recommended practice: ≤ 1 request/second, a descriptive `User-Agent`, and reasonable daily volume. Hence mandatory disk cache.
- **[L]** `GET /v1/places/<id>` returns the place record (use it to validate pinned continent IDs).

### 1.5 Offline
- **[C]** `HF_HUB_OFFLINE=1` makes `huggingface_hub` serve every `hf_hub_download` from the local cache with zero network calls. Both open_clip's `hf-hub:` model loading and pybioclip's embedding fetch go through `huggingface_hub`, so one env var covers model + TOL embeddings.
- **[L]** Without it, each cached file lookup first contacts the hub to compare revisions and, with no connectivity, waits out a connection timeout before falling back to the cache — several files per run, so a field run stalls for tens of seconds before starting.
- **[C]** `HF_HOME` relocates the Hugging Face cache (default `~/.cache/huggingface`; on Windows `%USERPROFILE%\.cache\huggingface`). Copying that directory to another machine moves the model and embeddings with it.
- **[C]** Nothing in the predict path (torch, open_clip, pybioclip, rawpy, PIL) phones home. The only runtime network client is `geo.py`.

---

## 2. The one real blocker: BioCLIP 2.5 inside pybioclip

**Problem.** pybioclip 2.1.6's `TreeOfLifeClassifier` fetches `txt_emb_species.*` (= BioCLIP 2's 768-d embeddings) and rejects unknown model strings. Passing the 2.5 model string either raises in `get_tol_repo_id()` or — worse — pairs a 1024-d image encoder with 768-d text embeddings.

**Strategy (Phase 0 spike, time-boxed).**

1. First check whether native support has landed since this plan was written: `uv pip index versions pybioclip`, and grep the installed `bioclip/predict.py` for `bioclip-2.5`. If present, use it and skip the override.
2. Otherwise implement a thin subclass (sketch in Appendix A) that overrides `get_tol_repo_id`, `get_txt_emb`, `get_txt_names` to point at `txt_emb_bioclip-2.5-vith14.*`, and passes `model_str='hf-hub:imageomics/bioclip-2.5-vith14'`.
3. Verification gates (all must pass):
   - `txt_emb.shape[0] == 1024` (if the file is `(N, 1024)`, transpose — pybioclip indexes `txt_embeddings[:, idx]`, i.e. `(dim, N)`).
   - `len(txt_names) == txt_emb.shape[1]`.
   - A known test image (brown bear / jaguar / red deer JPG) returns the correct species top-1 with score > 0.5.
   - `create_taxa_filter` + `apply_filter` work on the subclass unchanged.
4. **Time-box: 2 focused sessions.** If gates fail, ship MVP on `bioclip-2` (pybioclip default; zero override needed), keep `--model` wired so 2.5 is a flag flip later, and record findings in `docs/decisions/0001-bioclip-25.md`.

---

## 3. Architecture

```
wildid/
├── pyproject.toml            # uv-managed; console_scripts: wildid = wildid.cli:app
├── uv.lock
├── README.md
├── CLAUDE.md                 # §12 seed
├── src/wildid/
│   ├── __init__.py
│   ├── cli.py                # typer app: `wildid PATH` (classify) and `wildid prefetch`
│   ├── prefetch.py           # downloads model + TOL embeddings + geo lists; the ONLY module allowed to download models
│   ├── images.py             # discovery (recursive, ext whitelist) + loaders (JPG, ARW) → PIL.Image
│   ├── model.py              # classifier factory (bioclip-2.5 override | bioclip-2), device pick, label-data cache
│   ├── geo.py                # place resolution, species list fetch, disk cache, TOL intersection, mask build
│   ├── output.py             # text-block writer to stdout, top-k rules (table/csv/json post-MVP)
│   └── constants.py          # iconic taxa, continent place IDs, extensions, cache paths
├── tests/
│   ├── test_images.py        # fixtures: small JPG; ARW skipped if fixture absent
│   ├── test_geo.py           # iNat responses mocked (respx / responses); no network in tests
│   ├── test_output.py
│   └── fixtures/             # git-ignored except a tiny JPG
└── docs/decisions/           # ADRs (0001-bioclip-25.md, 0002-geo-source.md)
```

**Data flow**

```
PATH ──► images.discover()  ──► [paths]
                                    │  chunk of N
                                    ▼
                           images.load() (thread pool) ──► [PIL] + [paths]
                                    │
geo args ──► geo.resolve_place() ──► geo.species_list() ──► geo.build_mask(classifier) ──► apply_filter
                                    │
                                    ▼
                    classifier.predict([PIL], Rank.SPECIES, k, batch_size=32)
                                    │
                                    ▼
                    output.write_text(rows, top_k, candidates=N, place=...)  → stdout
```

**Key invariants**
- Model + text embeddings load **once** per process (6–8 s on 2.5 from warm HF cache; first run downloads ~8 GB).
- `get_label_data()` is computed once and cached on the classifier wrapper.
- Image loading overlaps GPU work (thread pool, 4–8 workers; ARW thumb extraction is CPU/IO-bound).
- No network calls in the predict path except an opportunistic geo-list fetch, and that is cache-first with a short timeout. `cli.py` sets `os.environ.setdefault("HF_HUB_OFFLINE", "1")` **before** importing `bioclip`/`open_clip`/`torch` for the classify command; `prefetch` clears it.

---

## 4. CLI specification

```
wildid PATH [options]        classify. Never downloads models (HF offline mode); geo lists cache-first.
wildid prefetch [options]    download model + TOL embeddings (+ geo lists when geo args are given).
                             The only command that downloads. Idempotent; run before every trip.

prefetch options
  --model [bioclip-2.5|bioclip-2|all]   default bioclip-2.5
  --continent / --country / --region / --place-id / --taxa   same meaning as below; repeatable
                                        (e.g. prefetch two countries in one call)

Positional (classify)
  PATH                      file or directory (recursive)

Geo (optional; precedence region > country > continent)
  --continent TEXT          Africa | Antarctica | Asia | Europe | North America | Oceania | South America
  --country TEXT            country name (iNat place, admin_level 0), e.g. "Brazil"
  --region TEXT             region within --country (state/province/county), e.g. "Mato Grosso"; requires --country
  --place-id INT            escape hatch: use this iNat place id directly, skip name resolution
  --taxa TEXT               taxonomic classes for the geo list, comma-separated.
                            default: Mammalia,Reptilia,Amphibia,Aves
                            (mammals, reptiles, amphibians, birds)
  --refresh-geo             ignore cache, refetch the species list

Model / runtime
  --model [bioclip-2.5|bioclip-2]   default bioclip-2.5
  --device [auto|cuda|cpu]          default auto (cuda if available, else cpu with a warning)
  --batch-size INT                  default 32
  --anomaly-check                   also run the unconstrained pass and flag disagreement (always on for single file)
  --offline                         forbid all network calls; exit 1 with a `wildid prefetch ...` hint if any cache is missing

Output (MVP = text blocks on stdout; see D13)
  --k INT                   override top-k (default: 5 for file, 3 for directory)
  --ext TEXT                default jpg,jpeg,arw
  -v / --verbose

Post-MVP (reserved, do not implement now): --format [table|csv|json], --output PATH
```

**Behaviour**
- Single file: print top 5 (species, common name, score). With geo: print constrained top 5, then one line `unconstrained top-1: <species> (<score>)`, marked `⚠ not in <place> list` if it is outside the regional list.
- Directory: one block per file, top 3, in discovery order; progress bar on stderr (rich). Files that fail to load are reported at the end with the reason, exit code stays 0 unless **every** file failed.
- Header line (stdout) states what was run: model, device, candidates (`full TOL` or `<N> species from <place> [taxa …]`), and geo-list fetch date. Progress and warnings go to **stderr** so stdout stays clean and pipeable.
- Scores are a softmax over the **candidate set**; a 0.9 over 400 regional species is not comparable to a 0.9 over the full TOL. Say so in `--help` and in the header.
- Exit codes: 0 ok, 1 usage/geo resolution error (incl. missing geo cache when offline), 2 model load failure (incl. missing model cache — message names the exact `wildid prefetch` command to run), 3 all images failed.

**Text output example**

```
wildid 0.1.0 | model=bioclip-2.5 device=cuda | candidates=412 species (Brazil › Mato Grosso; Mammalia,Reptilia,Amphibia,Aves; fetched 2026-10-23)
DSC04512.ARW
  1. Panthera onca            Jaguar                 0.962
  2. Puma concolor            Puma                   0.021
  3. Leopardus pardalis       Ocelot                 0.009
  unconstrained top-1: Panthera onca (0.871)
```

---

## 5. Geo filter design

### 5.1 Place resolution (`geo.resolve_place`)
1. `--place-id` given → use as-is (validate via `/v1/places/<id>`).
2. `--region` + `--country`: resolve country first (autocomplete, exact-name match preferred, `admin_level == 0`); then autocomplete region and keep candidates whose `ancestor_place_ids` contains the country id; prefer `admin_level == 10`, then 20. Ambiguity → list candidates and exit 1 with a hint to use `--place-id`.
3. `--country` only: as above, country.
4. `--continent` only: look up in `constants.CONTINENT_PLACE_IDS` (pinned in Phase 3 after one-time verification; accept "Australia" as alias of Oceania).

### 5.2 Species list (`geo.species_list`)
- For each iconic taxon in `--taxa`: page through `species_counts` (`per_page=500`, `quality_grade=research`) until `results` is empty or `page * per_page >= total_results`. Sleep ~1 s between requests. Collect `taxon.name` where `taxon.rank == "species"` (drop subspecies/hybrids/genus-level leaves).
- Cache JSON at `<user_cache_dir>/wildid/geo/<place_id>__<taxa-slug>.json` with `fetched_at`.
- **Place resolution is cached too** (`geo/places.json`: normalised query → `{id, name, admin_level, ancestor_place_ids}`), so a known place never touches the network again.
- Freshness rule: if cached and < 30 days → use. If cached and older → **use it anyway** and warn on stderr; refetch only when `--refresh-geo` is given and the network is reachable. Staleness never blocks a run.
- Fetch attempts (when not cached, or `--refresh-geo`) use a 5 s connect / 30 s read timeout; any failure → exit 1 with the exact `wildid prefetch ...` command to run when back online. `--offline` skips the attempt entirely.
- Log: species count per taxon, total, cache hit/miss, fetch date.

### 5.3 Intersection with TOL (`geo.build_mask`)
- `known = set(label_data['species'])`; `keep = [s for s in regional if s in known]`.
- Log unmatched count and a sample (taxonomy drift between iNat and TOL is expected; a few % loss is normal). If matched < 50 species, warn loudly — the filter is probably wrong (bad place, wrong taxa).
- `mask = clf.create_taxa_filter(Rank.SPECIES, keep)`; `clf.apply_filter(mask)`.
- **Species rank only** (see §1.2 warning about higher ranks).

### 5.4 Anomaly check
- Unconstrained pass uses a second classifier instance **sharing the loaded model** if pybioclip allows, else re-apply an all-True mask between passes. Measure; on a 4090 the second encode pass is cheap (single-file mode always does it; directory mode only with `--anomaly-check`).

---

## 6. Image ingestion

- Discovery: `Path.rglob('*')`, filter by lower-cased suffix in `--ext`, skip hidden/system dirs, deterministic sort.
- JPG: `PIL.Image.open` → `ImageOps.exif_transpose` → `.convert('RGB')`.
- ARW: `rawpy.imread` → `extract_thumb()` → PIL (JPEG bytes or bitmap array) → RGB. On `LibRawNoThumbnailError` / `LibRawUnsupportedThumbnailError`: fallback `postprocess(half_size=True, use_camera_wb=True, output_bps=8)` (still slow; log it).
- Loader returns `(path, PIL | None, error | None)`; never raises into the batch loop.
- DNG (post-MVP): identical rawpy path; adding `dng` to `--ext` default is the whole change, kept out of MVP only so it gets tested with real DJI/Pixel files.

---

## 7. Environment setup

**Either OS**
```
uv init wildid --package && cd wildid
uv python pin 3.12
uv add pybioclip rawpy pillow typer rich requests platformdirs
uv add --dev pytest respx ruff
# PyTorch with CUDA: pick the current stable cu12x wheel index from pytorch.org "Get started"; do not hardcode.
uv add torch torchvision --index https://download.pytorch.org/whl/cu128   # adjust cuXXX to current
uv run python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
hf auth login        # (or huggingface-cli login) after accepting TreeOfLife-200M terms on HF
```

**Windows notes**
- Use PowerShell or Windows Terminal; set `PYTHONUTF8=1` (or `sys.stdout.reconfigure(encoding="utf-8")` at startup).
- Current NVIDIA driver (Studio or Game Ready) is all CUDA needs; no CUDA toolkit install.
- Use `pathlib` everywhere; no shell globbing assumptions.

**Linux notes**
- Same commands; nothing special.

**First run:** `uv run wildid prefetch --model bioclip-2.5` downloads the model and embeddings (~4 GB + ~3.8 GB). Nothing else ever downloads a model.

### 7.1 Offline operation (requirement, D15)

What needs the network, and when:

| Component | Network | When | Lives in | Size |
|---|---|---|---|---|
| Python packages | yes | `uv sync` at install time only | project `.venv` | ~5 GB incl. CUDA torch |
| Model weights | yes | `wildid prefetch` only | HF cache (`HF_HOME`) | 2.5 Huge ~3.9 GB; bioclip-2 ~1.7 GB |
| TOL text embeddings | yes | `wildid prefetch` only | HF cache | ~3.8 GB (2.5) / ~2.9 GB (2) |
| Place resolution + species lists | yes | first use per place/taxa, or `prefetch` with geo args | wildid cache (`platformdirs.user_cache_dir`) | kB–MB per place |
| Classification | **no** | — | — | — |

Rules:
- Classify command always runs with `HF_HUB_OFFLINE=1` → loads from cache or exits 2 naming the prefetch command. No revision checks, no timeouts, deterministic start-up.
- Geo lists are cache-first (§5.2). `--offline` makes the guarantee absolute: zero network calls.
- **Pre-trip checklist** (goes in README): `uv run wildid prefetch --model bioclip-2.5 --country <X> [--region <Y>]` for every destination; then verify with the network disabled: `uv run wildid --offline test.jpg --country <X>` must succeed.
- The cache belongs to the machine that runs inference. On the 4090 desktop nothing changes. For a laptop in the field: run `prefetch` on the laptop (or copy the `HF_HOME` directory and the wildid cache dir); without an NVIDIA GPU it runs on CPU — **[L]** 2.5 Huge is seconds per image on a laptop CPU, bioclip-2 markedly faster — and needs roughly 10 GB free RAM for model + embeddings. Prefetch `--model all` on a laptop so you can pick at run time.

---

## 8. Phased execution plan

### Phase 0 — Environment + model spike  *(gate for everything else)*
- [ ] Repo skeleton (§3), `uv` env, CUDA verified, HF auth done.
- [ ] `model.py`: factory for `bioclip-2` (stock) — smoke test on one JPG, `device='cuda'`.
- [ ] 2.5 override (§2, Appendix A) behind `--model bioclip-2.5`; run the four verification gates.
- [ ] `wildid prefetch --model ...` subcommand (`prefetch.py`); classify path sets `HF_HUB_OFFLINE=1` before heavy imports and exits 2 with the prefetch hint when the cache is missing.
- [ ] Record outcome in `docs/decisions/0001-bioclip-25.md`; set default model accordingly.
- **Accept when:** `wildid tests/fixtures/bear.jpg` prints 5 rows, top-1 `Ursus arctos`, in < 15 s warm — **and the same command succeeds with the network adapter disabled**, with no stall at start-up.

### Phase 1 — Single-file path (JPG + ARW)
- [ ] `images.py` loaders per §6; unit tests (JPG fixture in repo; ARW fixture optional, test skips if absent).
- [ ] `cli.py` single-file flow; `output.py` text-block writer; top-5 rule.
- [ ] UTF-8 stdout hardening.
- **Accept when:** an A7R V `.ARW` and its sidecar/exported `.jpg` give the same top-1; ARW load < 150 ms.

### Phase 2 — Directory mode
- [ ] Recursive discovery, chunked loading with thread pool, `predict(batch_size=32)`, results zipped by index to paths.
- [ ] Progress bar (stderr), per-file top-3 text blocks (stdout), failure summary at the end.
- **Accept when:** 500 mixed JPG/ARW files finish with no per-file crashes; throughput ≥ 10 img/s on the 4090 for JPG (2.5 Huge) — measure and record; memory stable (no growth across chunks).

### Phase 3 — Geo filter
- [ ] `geo.py`: resolution (§5.1), fetch + cache (§5.2), intersection + mask (§5.3), anomaly pass (§5.4).
- [ ] Pin the seven continent place IDs after verification; `--place-id` escape hatch.
- [ ] Place-resolution cache, stale-but-usable rule, 5 s timeouts, `--offline`; `prefetch` accepts geo args (repeatable).
- [ ] Tests with mocked iNat responses (no network); one opt-in live test; one test that simulates no network (requests raising `ConnectionError`) → cached place works, uncached place exits 1 with the prefetch hint.
- **Accept when:** `wildid pantanal/ --country Brazil --region "Mato Grosso"` shows candidates ≈ several hundred species, jaguar/giant otter/caiman frames come back correct, an out-of-region test image is flagged by the anomaly line — and the same run repeated with `--offline` and the network disabled gives identical output.

### Phase 4 — Hardening + docs
- [ ] `ruff` clean, `pytest` green, `--help` complete, README with the canonical commands, the pre-trip prefetch checklist and the score-semantics caveat.
- [ ] `uv lock` committed; `uv run wildid` works from a clean clone on Windows and Linux.
- **MVP done when** all Phase 0–3 acceptance criteria pass on the user's real photo set, including one full directory run with the network physically disabled.

---

## 9. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| 2.5 override breaks on embedding shape / name format | medium | Phase 0 gates + hard fallback to bioclip-2 (D2) |
| HF dataset gated / auth friction | medium | Explicit step in §7; clear error message pointing at the HF terms page |
| iNat ↔ TOL name mismatch drops real species | certain, small | Log unmatched; species-level only; later add synonym mapping (post-MVP) |
| Geo list too narrow → confident wrong species | medium | Anomaly line (unconstrained top-1) in output; `--anomaly-check` for dirs |
| TOL synonyms produce near-duplicate rows (`Grus grus` / `Grus communis`) | certain | Accept for MVP; post-MVP dedupe by genus+epithet or common name |
| Sony preview missing on some files | low | Demosaic fallback path, logged |
| Windows console encoding | low | UTF-8 forced at startup |
| iNat rate limits during a continent fetch (thousands of species) | low | 1 req/s, per-taxon series, 30-day cache |
| Field run with a missing cache (model or geo list) | medium | `prefetch` is the documented pre-trip step; classify fails fast (no timeouts) with the exact prefetch command; `--offline` verification in the checklist |
| Cache on the wrong machine (desktop vs laptop) | medium | Prefetch on the machine that will run; `HF_HOME` + wildid cache dir are copyable |

---

## 10. Post-MVP backlog (ordered by value for mammals/reptiles)

1. **Detector-crop stage** (MegaDetector / SpeciesNet detector): crop the animal before BioCLIP. Biggest accuracy lever for distant 200–600 mm frames. Design slot: `--crop` before `predict`. **Done 2026-10-23** (`--crop`, MegaDetector v6 via ultralytics; ADR 0003).
2. **More RAW formats:** add RAW support for `.nef` (Nikon), `.cr3` and `.cr2` (Canon), `.orf` (OM System/Olympus), `.raf` (Fujifilm), `.rw2` (Panasonic Lumix) and `.dng` (DJI drones, Pixel/phones, Leica), handled exactly like `.arw` via rawpy's embedded-preview path, with case-insensitive extension matching. Test each with real files before it joins the default `--ext` list (this absorbs the earlier DNG-only item). **Done 2026-10-23** (CC0 samples for every format; ADR 0003).
3. fp16 autocast + TF32 for throughput; measure before adopting. **Done 2026-10-23**: TF32 default, fp16 opt-in (`--precision`), bf16 rejected (ADR 0003).
4. Second-opinion ensemble (SpeciesNet for mammals) with disagreement flag. **Done 2026-10-23** (`--second-opinion`; ADR 0003).
5. **Auto-geo from EXIF GPS** → reverse-geocode to iNat place → implicit `--place-id`. Removes the need to pass geo flags per shoot. **Done 2026-10-25** (`--geo-auto`, `--geo-level`, `wildid prefetch --gps-from`; ADR 0006; wildid 0.3.0).
6. Synonym-aware dedupe of top-k rows; collapse subspecies into species. **Done 2026-10-23** (GBIF-backed synonym mapping for the geo list in `prefetch`, top-k merge by canonical name; ADR 0004).
7. Genus-level geo mode (`--geo-rank genus`) for regions with thin iNat coverage. **Done 2026-10-23** (ADR 0004).
8. Output writers: `--format table|csv|json`, `--output PATH`; JSON sidecar per image; optional XMP keyword write-back for Lightroom. **Done 2026-10-24** (`--format json` + `--output`, XMP keyword sidecars via `--write-xmp`, plus `wildid serve` + the Lightroom plugin; table/csv dropped as not needed; ADR 0005, lightroom-plugin-plan.md).
9. **CUDA reference runs for the macOS comparison. Done 2026-11-15**: the nine runs were
   made on the Linux box, brought to the Mac and compared the same day (`docs/acceptance.md`).
   Without the crop the Mac and CUDA give the same answer on every file: 863 of 863 JPGs
   for both models and 157 of 157 RAW files. With the crop 2,003 of 2,040 answers agree
   (98.2 %): the detector's box differs by a pixel or two on about a third of the JPGs, and
   item 10 asks why. What the item asked for, kept as the record:

   The macOS acceptance has two boxes waiting for it
   (`docs/acceptance-macos.md`, sections 0 and E): the per-file comparison of the Mac's
   answers on MPS with CUDA's answers on the same photos. The Mac's half exists as files; the
   CUDA half was never kept as files. *(It is since 2026-11-15, on the Linux box: last point
   below.)*

   On the Linux box, on current `main`, in the repository root, with the same `sample-jpg/`
   and `sample-arw/` as on the Mac, generate exactly these nine run documents and keep them:

   ```sh
   OUT=~/.cache/wildid-acceptance/cuda-reference && mkdir -p "$OUT"
   run() { n="$1"; shift; uv run wildid classify "$@" -v --format json --output "$OUT/$n.json" > "$OUT/$n.out" 2> "$OUT/$n.err"; }
   run jpg-b2        sample-jpg --model bioclip-2   --k 1
   run jpg-b25       sample-jpg --model bioclip-2.5 --k 1
   run jpg-b2-crop   sample-jpg --model bioclip-2   --k 1 --crop
   run jpg-b25-crop  sample-jpg --model bioclip-2.5 --k 1 --crop
   run arw-b2        sample-arw --model bioclip-2   --k 1
   run arw-b2-crop   sample-arw --model bioclip-2   --k 1 --crop
   run arw-b25-crop  sample-arw --model bioclip-2.5 --k 1 --crop
   run jpg-b2-fp32   sample-jpg --model bioclip-2   --k 1 --precision fp32
   run jpg-b25-fp32  sample-jpg --model bioclip-2.5 --k 1 --precision fp32
   ```

   - The first seven use the default precision, which is TF32 on CUDA. Each has a counterpart
     of the same name on the Mac, in `~/.cache/wildid-acceptance/2026-11-15-macos-installed/`.
     The last two repeat the plain runs in fp32, so that a difference can be put down either
     to the backend or to TF32.
   - Expected in every file: `"device": "cuda"`; `"precision": "tf32"`, or `"fp32"` in the
     last two; 863 results for `sample-jpg` and 157 for `sample-arw`, none failed.
   - Keep the whole folder. The nine `.json` files are the reference; the `.err` files carry
     the load time and the speed line. Add a `MANIFEST.txt` with the commit
     (`git rev-parse HEAD`), `uv run wildid --version`, the name of the GPU and the date.
   - Read-only on the samples: no `--write-xmp`. The files stay outside the repository, like
     the photos.
   - The first `uv run` after this pull rebuilds the environment on uv's own Python (the rule
     of 2026-11-15, `python-preference` in `pyproject.toml`): let that finish first.
   - Then bring the folder to the Mac under the same path,
     `~/.cache/wildid-acceptance/cuda-reference/`. The comparison runs there, with
     `compare.py` and `deep_compare.py` from the Mac's `2026-11-15-macos-installed/` folder:
     each CUDA file against the Mac file of the same name, and the two fp32 files against the
     Mac's `jpg-b2.json` and `jpg-b25.json`. Expected: at least 99.5 % of the top-1 answers
     identical. The result goes into `docs/acceptance.md` and the two boxes get ticked.
   - **Made 2026-11-15, the part that belongs to the Linux box.** The environment was rebuilt
     first (`uv sync --locked`: uv's CPython 3.14.9 in place of the system's 3.14.7, the same
     96 packages, the lock unchanged; suite with the live-model tests 210 passed, 2 skipped).
     Then the nine runs, kept in `~/.cache/wildid-acceptance/cuda-reference/`
     with `MANIFEST.txt`: every file is as expected above. Eight of them equal the 2026-11-03
     documents of the same commands in every field; the ninth had only a text output then and
     gives its answers. Log: `docs/acceptance.md`. The folder also holds `samples.sha256`,
     the checksums of the 1,020 photos classified.
   - **Compared on the Mac the same day.** The folder was brought over; its checksums match
     the Mac's sample files on all 1,020 photos; the comparison ran and the two boxes are
     ticked. The result is at the head of this item and in `docs/acceptance.md`.
10. **CUDA crop runs in fp32. Done 2026-11-15**: the runs and their comparison with TF32 on
    the Linux box, the comparison with the Mac's runs on the Mac. The precision is not what
    separates the two machines (last point below). (Added 2026-11-15, follows item 9.)
    With the crop on, the Mac and CUDA disagree on 1.8 % of the answers,
    and the cause is the detector's box, not the classification (`docs/acceptance.md`, "macOS
    against CUDA, file by file"). On CUDA the detector runs under the same TF32 switch as the
    classifier; on the Mac it runs in fp32. The nine runs of item 9 hold no CUDA crop run in
    fp32, so they cannot say whether CUDA's default precision moves the box or the backend
    does. Four more runs settle it.

    On the Linux box, on current `main`, in the repository root, into the same folder as
    item 9 and without touching its nine files:

    ```sh
    OUT=~/.cache/wildid-acceptance/cuda-reference && mkdir -p "$OUT"
    run() { n="$1"; shift; uv run wildid classify "$@" -v --format json --output "$OUT/$n.json" > "$OUT/$n.out" 2> "$OUT/$n.err"; }
    run jpg-b2-crop-fp32   sample-jpg --model bioclip-2   --k 1 --crop --precision fp32
    run jpg-b25-crop-fp32  sample-jpg --model bioclip-2.5 --k 1 --crop --precision fp32
    run arw-b2-crop-fp32   sample-arw --model bioclip-2   --k 1 --crop --precision fp32
    run arw-b25-crop-fp32  sample-arw --model bioclip-2.5 --k 1 --crop --precision fp32
    ```

    - Expected in every file: `"device": "cuda"`, `"precision": "fp32"`, 863 results for
      `sample-jpg` and 157 for `sample-arw`, none failed. Add the four runs to `MANIFEST.txt`.
    - Compare right there, each new file with the item-9 file of the same name without
      `-fp32` (`jpg-b2-crop-fp32.json` against `jpg-b2-crop.json`, and so on): CUDA fp32
      against CUDA TF32, which is what the precision alone does through the crop. Report per
      pair how many top-1 answers differ, on how many frames the crop's `size` differs, and
      the largest difference of the crop's `confidence`. Write the result to
      `fp32-crop-comparison.txt` in the folder.
    - Then bring the folder to the Mac under the same path. There the four files are compared
      with the Mac's `-crop` runs (fp32 on both sides: what the backend alone does), with
      `crop_diff.py` from the Mac's `2026-11-15-macos-installed/` folder.
    - What the answer decides: if CUDA in fp32 gives the Mac's boxes, TF32 is what moves
      them, and the question becomes whether the detector should run in fp32 on CUDA
      (ADR 0003). If CUDA in fp32 still differs from the Mac, the backends differ in the
      detector and nothing in the precision setting changes that.
    - **Made 2026-11-15, the part that belongs to the Linux box.** The four runs
      (nothing in `src/` differs from the commit of the nine runs), next to item 9's files,
      which are unchanged; `MANIFEST.txt` has a section for them. Every file is as expected
      above. CUDA fp32 against CUDA TF32 (`fp32-crop-comparison.txt`): 2 and 1 of 863 top-1
      answers differ on the JPGs and none of 157 on the RAW files; the crop's size differs on
      29 of the 760 JPGs detected in both runs and on 3 of 137 RAW files, almost always by a
      pixel or two; one JPG has a detection in TF32 only; the largest confidence difference
      is 0.0038. So TF32 does change the crop, on 30 of the 863 JPGs. The Mac differs from the
      TF32 runs on 279, so at least 249 must still differ between the Mac and CUDA in fp32:
      expect the second outcome. Log: `docs/acceptance.md`.
    - **Compared on the Mac the same day.** Against CUDA in fp32 the Mac's crop still differs
      on 281 of the 863 JPGs and on 10 of the 157 RAW files, and 38 of the 2,040 answers
      differ (37 against TF32). It is the second outcome: with fp32 on both machines the
      difference is as large as before.
11. **Crop runs on the CPU of the Linux box. Done 2026-11-15**: the runs and their
    comparison with CUDA on the Linux box, the comparison with the Mac's runs on the Mac
    (added 2026-11-15 on the owner's word, follows item 10). Item 10 showed that CUDA's precision changes few crops.
    These runs ask whether the CUDA backend does: the crop commands of item 9 with
    `--device cpu`, on the Linux box, into the same folder, without touching its other files:

    ```sh
    OUT=~/.cache/wildid-acceptance/cuda-reference && mkdir -p "$OUT"
    run() { n="$1"; shift; uv run wildid classify "$@" -v --format json --output "$OUT/$n.json" > "$OUT/$n.out" 2> "$OUT/$n.err"; }
    run jpg-b2-crop-cpu   sample-jpg --model bioclip-2   --k 1 --crop --device cpu
    run arw-b2-crop-cpu   sample-arw --model bioclip-2   --k 1 --crop --device cpu
    run jpg-b25-crop-cpu  sample-jpg --model bioclip-2.5 --k 1 --crop --device cpu
    run arw-b25-crop-cpu  sample-arw --model bioclip-2.5 --k 1 --crop --device cpu
    ```

    - **Made 2026-11-15.** Nothing in `src/` differs from the commits of the
      earlier runs. `"device": "cpu"` and `"precision": "fp32"` in all four, 863 and 157
      results, none failed, nothing on the GPU; `MANIFEST.txt` has a third section. The CPU
      against CUDA in fp32 (`cpu-crop-comparison.txt`): the same crop on every one of the
      1,020 photos, for both models; no top-1 answer differs; the detector's confidence
      agrees to the fifth decimal. So neither CUDA's precision (item 10: 30 of 863 JPG crops)
      nor its backend is what separates the two machines. Log: `docs/acceptance.md`.
    - **Compared on the Mac the same day.** The four `-crop-cpu` files against the Mac's
      `-crop` runs give what item 10's `-crop-fp32` files give, frame for frame: the same
      281 JPG and 10 RAW crops differ and the same 38 answers. On the 760 JPGs with a
      detection on both machines the detector's confidence is equal on 2 and differs by
      0.0014 at the median and 0.053 at most, while on each machine the CPU and the GPU agree
      to the fifth decimal. So the machines do not differ in how they compute: they hand the
      detector different pixels. Log: `docs/acceptance.md`.
    - **What is left to find** is which step makes the pixels differ: item 12.
12. **What the detector sees on each machine. Done 2026-11-15**: the step that differs is
    the resize before the detector. The Linux box computes OpenCV's portable `INTER_LINEAR`,
    the Mac's OpenCV uses Arm-specific code that differs by 1 in about a fifth of the pixel
    values. Intel IPP, the guess below, is not it. The owner's decision: the default stays,
    and a resize meant to be the same everywhere is an option (last point; item 13)
    (added 2026-11-15, follows items 10 and 11). The two machines must hand the detector
    different pixels. Without the crop they hand the classifier the same ones: its scores
    agree to 0.0002 between the machines, which is what CPU against GPU gives on one
    machine, so the decoding and Pillow's resizing are the same on both. What only the crop
    path has is ultralytics' own resize of the photo to the detector's size, `cv2.resize`
    in its letterbox step. The Mac's OpenCV has no Intel IPP (`IPP in use: False`). The
    x86-64 OpenCV wheel normally has it, and IPP brings its own resize. That is the guess
    this item tests.

    The script runs the ordinary crop classification and writes, for every photo, a checksum
    of the image wildid hands the detector and a checksum of the letterboxed image
    ultralytics makes of it. It changes nothing in wildid or ultralytics. On the Linux box,
    on current `main`, in the repository root:

    ```sh
    OUT=~/.cache/wildid-acceptance/cuda-reference && mkdir -p "$OUT"
    cat > "$OUT/detector_pixels.py" <<'PY'
    import hashlib, json, pathlib, platform, sys, tempfile
    from wildid.env import prepare_runtime_env
    prepare_runtime_env(allow_model_download=False)
    import cv2, numpy as np, PIL
    from ultralytics.engine import predictor
    from wildid.cli import main

    folder, out = sys.argv[1], pathlib.Path(sys.argv[2])
    rows, original = [], predictor.BasePredictor.pre_transform
    sha = lambda a: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

    def pre_transform(self, im):
        boxed = original(self, im)
        for a, b in zip(im, boxed):
            rows.append(("x".join(map(str, a.shape)), sha(a), "x".join(map(str, b.shape)), sha(b)))
        return boxed

    predictor.BasePredictor.pre_transform = pre_transform
    with tempfile.TemporaryDirectory() as tmp:
        doc_path = pathlib.Path(tmp) / "run.json"
        code = main(["classify", folder, "--model", "bioclip-2", "--k", "1", "--crop",
                     "--format", "json", "--output", str(doc_path)])
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    paths = [r["path"] for r in doc["results"]]
    if code not in (0, None) or len(paths) != len(rows):
        sys.exit(f"exit code {code}; {len(paths)} results but {len(rows)} images seen by the detector")
    head = (f"# {platform.system()} {platform.machine()} | device {doc['device']} | opencv {cv2.__version__}, "
            f"IPP in use: {cv2.ipp.useIPP()} ({cv2.ipp.getIppVersion()}) | pillow {PIL.__version__} | numpy {np.__version__}")
    lines = [head, "# path\thanded to the detector: shape, sha256\tletterboxed: shape, sha256"]
    lines += ["\t".join((p, *row)) for p, row in zip(paths, rows)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(head[2:], f"| {len(rows)} photos -> {out}")
    PY
    uv run python "$OUT/detector_pixels.py" sample-jpg "$OUT/pixels-jpg-linux.tsv"
    uv run python "$OUT/detector_pixels.py" sample-arw "$OUT/pixels-arw-linux.tsv"
    OPENCV_IPP=disabled uv run python "$OUT/detector_pixels.py" sample-jpg "$OUT/pixels-jpg-linux-noipp.tsv"
    OPENCV_IPP=disabled uv run python "$OUT/detector_pixels.py" sample-arw "$OUT/pixels-arw-linux-noipp.tsv"
    run() { n="$1"; shift; uv run wildid classify "$@" -v --format json --output "$OUT/$n.json" > "$OUT/$n.out" 2> "$OUT/$n.err"; }
    OPENCV_IPP=disabled run jpg-b2-crop-noipp   sample-jpg --model bioclip-2   --k 1 --crop --precision fp32
    OPENCV_IPP=disabled run jpg-b25-crop-noipp  sample-jpg --model bioclip-2.5 --k 1 --crop --precision fp32
    OPENCV_IPP=disabled run arw-b2-crop-noipp   sample-arw --model bioclip-2   --k 1 --crop --precision fp32
    OPENCV_IPP=disabled run arw-b25-crop-noipp  sample-arw --model bioclip-2.5 --k 1 --crop --precision fp32
    ```

    - The first line of each `.tsv` says whether IPP was in use. Expected: `True` in the first
      two files and `False` in the two made with `OPENCV_IPP=disabled`. If the first two say
      `False`, the guess is wrong: say so and stop. If the last two still say `True`, the
      variable is not honoured by this OpenCV: switch IPP off in the process instead, with
      `cv2.ipp.setUseIPP(False)` before `main(...)` is called, for the script and for the
      four runs, and say that this was needed.
    - Compare on the Linux box, with IPP against without: on how many photos does the first
      checksum differ (expected: none) and on how many the letterboxed one? And the four
      `-noipp` runs against item 10's `-crop-fp32` runs: on how many frames do the crop's
      `size` and the top-1 differ? Write both to `ipp-comparison.txt`, add the runs to
      `MANIFEST.txt`, log it, and leave the other files of the folder as they are.
    - Then bring the folder to the Mac. There the same script writes the Mac's two `.tsv`
      files, and the comparison decides: are the handed-over checksums equal on both
      machines, do the letterboxed ones differ with IPP, and are they equal without it?
      And do the four `-noipp` runs give the Mac's crops and answers (`crop_diff.py`)?
    - What the answer decides: if the Linux box without IPP gives the Mac's crops, the cause
      is IPP's resize, and the question for the owner becomes how to make the crop the same
      on every system. If not, the checksums say which step differs instead.
    - **Made 2026-11-15, the Linux box's part.** Nothing in `src/` differs from the commits
      of the earlier runs; the script and the commands as above, next to the
      earlier files, which are unchanged; `MANIFEST.txt` has a fourth section. The first line
      of each `.tsv` is as expected: `IPP in use: True` in the first two, `False` in the two
      made with `OPENCV_IPP=disabled`, so the variable is honoured and the fallback was not
      needed. With IPP against without (`ipp-comparison.txt`): the image handed to the
      detector differs on none of the 863 JPGs and 157 RAW files, as expected, **and the
      letterboxed image differs on none either**. The four `-noipp` runs equal item 10's
      `-crop-fp32` runs in every field of all 2,040 results: no crop size and no top-1
      differs. So the Linux box without IPP gives its own crops, not the Mac's: the cause is
      not IPP's resize. Log: `docs/acceptance.md`.
    - **Made on the Mac the same day.** The handed-over image has the same checksum on both
      machines on all 1,020 photos. The letterboxed image differs on all 863 JPGs and on 24
      of the 157 RAW files. OpenCV's portable `INTER_LINEAR`, written out in NumPy, gives
      the Linux box's letterboxed image to the byte on every photo; the Mac's OpenCV, built
      with the Carotene and KleidiCV layers for Arm, gives values that differ by 1 on about
      a fifth of the pixels. That is the cause of the differing boxes and of the 38
      differing answers. Log: `docs/acceptance.md`, "macOS: what the detector sees, and the
      step that differs".
    - **Decided by the owner, 2026-11-15.** Of the three ways (leave it; wildid resizes for
      the detector itself with the portable algorithm; every system uses OpenCV's
      `INTER_LINEAR_EXACT`): the default stays as it is, and the third is built as an option,
      off by default: `--crop-exact` on the command line, `crop_exact` in a server request and
      a checkbox in the plug-in's Identify dialog (ADR 0003 §1). Whether the option makes the
      two systems agree is item 13.
13. **Does `--crop-exact` make the Mac and the PC agree? Done 2026-11-15: yes.** With the
    option the detector computes on the same pixels on both, and with fp32 on both every
    crop and answer is the same (added 2026-11-15, follows item 12; what the two machines
    found is in the last points below). With `--crop-exact` ultralytics resizes the
    photo for the detector with OpenCV's `INTER_LINEAR_EXACT`, which is meant to give the same
    pixels on every system. That is OpenCV's claim. This item measures it, and what the option
    changes on each machine.

    On the Linux box, on current `main` (it must have `--crop-exact`: `uv run wildid classify
    --help` names it), in the repository root. The script is item 12's with one addition: what
    follows the two file names is passed on to `wildid classify`.

    ```sh
    OUT=~/.cache/wildid-acceptance/cuda-reference && mkdir -p "$OUT"
    cat > "$OUT/detector_pixels2.py" <<'PY'
    import hashlib, json, pathlib, platform, sys, tempfile
    from wildid.env import prepare_runtime_env
    prepare_runtime_env(allow_model_download=False)
    import cv2, numpy as np, PIL
    from ultralytics.engine import predictor
    from wildid.cli import main

    folder, out, extra = sys.argv[1], pathlib.Path(sys.argv[2]), sys.argv[3:]
    rows, original = [], predictor.BasePredictor.pre_transform
    sha = lambda a: hashlib.sha256(np.ascontiguousarray(a).tobytes()).hexdigest()

    def pre_transform(self, im):
        boxed = original(self, im)
        for a, b in zip(im, boxed):
            rows.append(("x".join(map(str, a.shape)), sha(a), "x".join(map(str, b.shape)), sha(b)))
        return boxed

    predictor.BasePredictor.pre_transform = pre_transform
    with tempfile.TemporaryDirectory() as tmp:
        doc_path = pathlib.Path(tmp) / "run.json"
        code = main(["classify", folder, "--model", "bioclip-2", "--k", "1", "--crop", *extra,
                     "--format", "json", "--output", str(doc_path)])
        doc = json.loads(doc_path.read_text(encoding="utf-8"))
    paths = [r["path"] for r in doc["results"]]
    if code not in (0, None) or len(paths) != len(rows):
        sys.exit(f"exit code {code}; {len(paths)} results but {len(rows)} images seen by the detector")
    head = (f"# {platform.system()} {platform.machine()} | device {doc['device']} | crop_resize {doc['crop_resize']} | "
            f"opencv {cv2.__version__}, IPP in use: {cv2.ipp.useIPP()} | pillow {PIL.__version__} | numpy {np.__version__}")
    lines = [head, "# path\thanded to the detector: shape, sha256\tletterboxed: shape, sha256"]
    lines += ["\t".join((p, *row)) for p, row in zip(paths, rows)]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(head[2:], f"| {len(rows)} photos -> {out}")
    PY
    uv run python "$OUT/detector_pixels2.py" sample-jpg "$OUT/pixels-jpg-linux-exact.tsv" --crop-exact
    uv run python "$OUT/detector_pixels2.py" sample-arw "$OUT/pixels-arw-linux-exact.tsv" --crop-exact
    run() { n="$1"; shift; uv run wildid classify "$@" -v --format json --output "$OUT/$n.json" > "$OUT/$n.out" 2> "$OUT/$n.err"; }
    run jpg-b2-crop-exact        sample-jpg --model bioclip-2   --k 1 --crop --crop-exact
    run jpg-b25-crop-exact       sample-jpg --model bioclip-2.5 --k 1 --crop --crop-exact
    run arw-b2-crop-exact        sample-arw --model bioclip-2   --k 1 --crop --crop-exact
    run arw-b25-crop-exact       sample-arw --model bioclip-2.5 --k 1 --crop --crop-exact
    run jpg-b2-crop-exact-fp32   sample-jpg --model bioclip-2   --k 1 --crop --crop-exact --precision fp32
    run jpg-b25-crop-exact-fp32  sample-jpg --model bioclip-2.5 --k 1 --crop --crop-exact --precision fp32
    run arw-b2-crop-exact-fp32   sample-arw --model bioclip-2   --k 1 --crop --crop-exact --precision fp32
    run arw-b25-crop-exact-fp32  sample-arw --model bioclip-2.5 --k 1 --crop --crop-exact --precision fp32
    ```

    - Expected in every run document: `"crop_resize": "exact"`, `"device": "cuda"`, `"precision":
      "tf32"` in the first four and `"fp32"` in the last four, 863 and 157 results, none
      failed. The first line of each `.tsv` says `crop_resize exact`.
    - Compare on the Linux box and write the result to `exact-comparison.txt`: (1) the two
      new `.tsv` files against item 12's `pixels-jpg-linux.tsv` and `pixels-arw-linux.tsv`: the
      handed-over checksum must be the same on every photo; on how many does the letterboxed
      one differ? (2) Each `-crop-exact` run against item 9's `-crop` run, and each
      `-crop-exact-fp32` run against item 10's `-crop-fp32` run: on how many frames do the
      crop's `size` and the top-1 differ, and how many of the changed answers are review
      frames in both? That is what the option changes on a PC. Add the runs to `MANIFEST.txt`,
      log it, leave the other files of the folder as they are.
    - Then bring the folder to the Mac. There the same script and the four crop runs with
      `--crop-exact` are made (the Mac runs fp32), and the comparison that decides: is the
      letterboxed checksum with `--crop-exact` the same on both machines on every photo? Do
      the Mac's runs give the crops and answers of the Linux box's `-crop-exact-fp32` runs,
      and how many differ against its `-crop-exact` runs in TF32? And what does the option
      change on the Mac against its own default runs?
    - What the answer decides: if the checksums are equal and the fp32 runs agree, the option
      does what its name says, and the texts that say "meant to" (`--help`, the checkbox's
      title and tooltip in the plug-in, the README, the website) can say "is". If not, the
      option does not deliver what it is for, and the owner decides what becomes of it.
    - **Made 2026-11-15, the Linux box's part.** On current `main`, in a fresh clone of the
      public repository, the environment built anew from the lock. The engine has the new
      option, and the code of the earlier runs was not at hand to compare with, so a
      control came first: the earlier commands again, without the option, give item 12's
      two checksum files row for row and the eight crop runs of items 9 and 10 in every
      field of all 4,080 results (`control-item13/` in the folder). Then the script and the
      ten commands as above, next to the earlier files, which are unchanged; `MANIFEST.txt`
      has a fifth section. Every file is as expected above. The option against the default
      (`exact-comparison.txt`): the image handed to the detector is the same on all 863 JPGs
      and 157 RAW files, and **the letterboxed image differs on every one of them**, in
      about 11 % of its values, each by 1 (`exact-pixel-difference.txt`). In the runs the
      crop is not the same on 231 of the 863 JPGs and 57 of the 157 RAW files in TF32, 228
      and 55 in fp32, mostly by a pixel or two; 43 of the 2,040 top-1 answers differ in
      TF32 and 41 in fp32, and 37 and 35 of those are review frames in both runs. That is
      about what separates the Mac and the PC without the option (281 JPG crops, 10 RAW
      crops, 38 answers). Measured as well, though not asked: against the folder names
      1,035 of 1,448 scored answers are right with the option and 1,044 without it, ten
      right without it only and one with it only; and under the option fp32 and TF32 still
      differ on 25 JPG crops, 6 RAW crops and 5 answers. Log: `docs/acceptance.md`.
    - **For the Mac's part.** The folder holds this part's scripts (`verify-item13.py`,
      `exact-compare.py`, `exact-pixels.py`, `bench.py`). The Mac's default runs were made
      before the option existed, like the Linux box's: a control of the same kind shows
      whether they still stand for the default path there.
    - **Made 2026-11-15, the Mac's part: the two machines agree.** The control first: on
      current `main`, without the option, the script gives item 12's two checksum files of
      the Mac row for row and the four default crop runs in every field of all 2,040
      results. Then the script and the four crop runs with `--crop-exact` (MPS, fp32), in
      `~/.cache/wildid-acceptance/2026-11-15-macos-exact/` (`mac-exact-comparison.txt`).
      **With the option the letterboxed image has the same checksum on the Mac and on the
      Linux box on all 863 JPGs and all 157 RAW files.** Against the Linux box's
      `-crop-exact-fp32` runs no crop and none of the 2,040 top-1 answers differs; the
      detector's confidence agrees to 0.000004 and the scores to 0.0002, as without the
      crop. Against its `-crop-exact` runs in TF32 the crop's size differs on 25 JPGs and 6
      RAW files and 5 answers differ, all review frames in both: that is what TF32 does on
      the Linux box itself. Without the option the same comparisons give 281 JPG crops, 10
      RAW crops and 38 answers (fp32), 279, 13 and 37 (TF32). On the Mac the option changes
      the crop on 269 of 863 JPGs and 54 of 157 RAW files and 49 of 2,040 answers against
      its default, 40 of them review frames in both runs. Against the folder names 1,035 of
      1,448 scored answers are right with the option, as on the Linux box, and 1,033
      without it on the Mac. So the option does what its name says, and the texts no longer
      say "meant to": they say what was measured, and that it is not a gain in accuracy.
      The default stays off (ADR 0003 §1). Not measured: Windows. Log: `docs/acceptance.md`.

---

## 11. Questions for Trogious (none is open)

Resolved 2026-10-23:
- Default `--taxa` = Mammalia,Reptilia,Amphibia,Aves (birds kept in; see D14).
- Output = stdout text blocks only (D13).

Closed 2026-11-15. Both ran on their defaults from 2026-10-23, the tool was built that way,
and neither is a pending question:
1. `--region` takes the region's name, as iNaturalist spells it, together with `--country`.
   It takes no administrative code (GADM style). When a name does not resolve or is
   ambiguous, `--place-id` takes the iNaturalist place number directly.
2. The repository is `Trogious/wildid` on GitHub: private at first, public since 2026-11-15
   (owner).

---

## 12. Seed `CLAUDE.md` for the repo

```markdown
# wildid — project conventions
- Python 3.12, managed by uv. Run everything via `uv run`. Never pip into the global interpreter.
- Model inference only through pybioclip APIs (TreeOfLifeClassifier, create_taxa_filter, apply_filter). Do not reimplement CLIP scoring.
- Never demosaic RAW files in the predict path; use embedded previews. Demosaic is a logged fallback only.
- No network in tests. iNat calls go through geo.py with the disk cache; tests mock HTTP.
- Offline-first: `wildid PATH` runs with HF_HUB_OFFLINE=1 set before importing bioclip/open_clip/torch and never downloads a model. Only `wildid prefetch` downloads. Geo fetches are cache-first with a 5 s connect timeout; a cached entry of any age beats a network call.
- Geo filtering is species-rank only. Never filter TOL by order/family.
- Model + label data load once per process. No per-image model calls.
- Keep the CLI contract in docs/plan §4 stable; add flags, do not rename.
- Decisions live in docs/decisions/*.md (ADR style). Update when a locked decision changes.
- Output must be UTF-8 safe on Windows.
- SI units only in any user-facing text.
```

---

## Appendix A — BioCLIP 2.5 TreeOfLife override (sketch; verify shapes in Phase 0)

```python
# sketch — becomes src/wildid/model.py during execution
import json, numpy as np, torch
from huggingface_hub import hf_hub_download
from bioclip.predict import TreeOfLifeClassifier

TOL_REPO = "imageomics/TreeOfLife-200M"
MODEL_25 = "hf-hub:imageomics/bioclip-2.5-vith14"
EMB_NPY_25 = "embeddings/txt_emb_bioclip-2.5-vith14.npy"
EMB_JSON_25 = "embeddings/txt_emb_bioclip-2.5-vith14.json"


class TreeOfLifeClassifier25(TreeOfLifeClassifier):
    def __init__(self, **kw):
        kw.setdefault("model_str", MODEL_25)
        super().__init__(**kw)

    def get_tol_repo_id(self) -> str:
        return TOL_REPO

    def get_txt_emb(self) -> torch.Tensor:
        p = hf_hub_download(TOL_REPO, EMB_NPY_25, repo_type="dataset")
        emb = torch.from_numpy(np.load(p))
        # pybioclip indexes txt_embeddings[:, idx] → expects (dim, N)
        if emb.shape[0] != 1024 and emb.shape[1] == 1024:
            emb = emb.T.contiguous()
        assert emb.shape[0] == 1024, emb.shape
        return emb

    def get_txt_names(self):
        p = hf_hub_download(TOL_REPO, EMB_JSON_25, repo_type="dataset")
        with open(p, encoding="utf-8") as fd:
            return json.load(fd)
```

Gate checks after construction: `clf.txt_embeddings.shape[1] == len(clf.txt_names)`; `clf.predict("bear.jpg", Rank.SPECIES, k=5)[0]["species"] == "Ursus arctos"`.

## Appendix B — ARW loader (sketch)

```python
import io, rawpy
from PIL import Image, ImageOps


def load_arw(path) -> Image.Image:
    with rawpy.imread(str(path)) as raw:
        try:
            t = raw.extract_thumb()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError):
            rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
            return Image.fromarray(rgb)
        if t.format == rawpy.ThumbFormat.JPEG:
            return ImageOps.exif_transpose(Image.open(io.BytesIO(t.data))).convert("RGB")
        return Image.fromarray(t.data).convert("RGB")
```

## Appendix C — iNat species list fetch (sketch)

```python
import time, requests

BASE = "https://api.inaturalist.org/v1"
UA = {"User-Agent": "wildid/0.1 (personal wildlife photo tool)"}


def species_for_place(place_id: int, iconic: str) -> list[str]:
    names, page = [], 1
    while True:
        r = requests.get(
            f"{BASE}/observations/species_counts",
            headers=UA,
            timeout=30,
            params={
                "place_id": place_id,
                "iconic_taxa": iconic,
                "quality_grade": "research",
                "per_page": 500,
                "page": page,
            },
        )
        r.raise_for_status()
        js = r.json()
        rows = js.get("results", [])
        names += [x["taxon"]["name"] for x in rows if x["taxon"]["rank"] == "species"]
        if not rows or page * 500 >= js.get("total_results", 0):
            return names
        page += 1
        time.sleep(1.0)
```

## Appendix D — Sources
- pybioclip docs: https://imageomics.github.io/pybioclip/ (Python API, geo-restricted taxa page), releases: https://github.com/Imageomics/pybioclip/releases
- BioCLIP ecosystem model table: https://imageomics.github.io/bioclip-ecosystem/pages/models.html
- BioCLIP 2.5 Huge model card: https://huggingface.co/imageomics/bioclip-2.5-vith14
- TreeOfLife-200M dataset (embeddings layout): https://huggingface.co/datasets/imageomics/TreeOfLife-200M
- iNaturalist API recommended practices: https://www.inaturalist.org/pages/api+recommended+practices
