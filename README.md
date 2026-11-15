# wildid

Species identification for wildlife photos on your own machine: BioCLIP 2 / 2.5 with the
TreeOfLife-200M taxa through pybioclip, on a local NVIDIA GPU, **offline-first**. Point it at a JPG, a RAW file (Sony
ARW, Nikon NEF, Canon CR2/CR3, OM System ORF, Fujifilm RAF, Panasonic RW2, DNG) or a whole
directory; optionally restrict candidates to the species actually observed in a country, region or
continent (iNaturalist research-grade observations), crop the animal first with MegaDetector,
and ask SpeciesNet for a second opinion.

```
wildid PATH [options]        classify a file (top 5) or a directory (top 3 per file, recursive)
wildid prefetch [options]    download the model, embeddings and geo lists — the only online command
```

## Requirements

- [uv](https://docs.astral.sh/uv/). No Python has to be installed: uv downloads Python 3.14, the
  version the lockfile was built with (the code needs 3.12 or newer), and never uses a Python
  already on the machine (`python-preference` in `pyproject.toml`).
- NVIDIA GPU with a driver that supports CUDA 13 (the lock pins `torch 2.14.1+cu130`); it also
  runs on CPU, slowly. Linux or Windows.
- macOS: Apple Silicon on macOS 14 or newer is what the lock and the installer accept; Intel
  Macs are not supported. The lock pins the same `torch 2.14.1` there and the model runs on
  Metal (`device=mps`, fp32 by default). Measured on exactly one Mac, a MacBook Pro with an M5 Pro and
  48 GB of memory: no other Mac has been tried, so nothing is known about Macs with less
  memory. On that Mac: 33 and 17 photos per second on a folder of JPEGs (`bioclip-2` and
  `bioclip-2.5`), 16 and 11 on RAW files with `--crop`; the daemon holds about 12 GB of
  memory with `bioclip-2`, 13 GB with `bioclip-2.5` and 20 GB with both; and without the crop
  Metal gives the answer of the CPU reference and of the RTX 4090 on every one of the 863
  sample frames (with `--crop` the Mac and the RTX 4090 agree on 98.2 %;
  `docs/acceptance.md`).
  **Available since 2026-11-15** (owner). Still open in `docs/acceptance-macos.md`: the
  plug-in has not been run in Lightroom Classic on a Mac yet. Every other speed, memory-use
  and accuracy figure in this README is from the RTX 4090.
- ~4.4 GB of disk for the default `bioclip-2` model + embeddings (another ~7.3 GB for
  `bioclip-2.5`), plus ~5 GB for the Python environment with CUDA torch (about 1.2 GB on
  macOS).

## Install

```
uv sync                                   # creates .venv, installs everything (incl. CUDA torch)
uv run wildid prefetch                    # downloads bioclip-2 (~4.4 GB) into the Hugging Face cache
uv run wildid tests/fixtures/bear.jpg      # should print Ursus arctos as #1
uv run wildid prefetch --model all        # optionally also bioclip-2.5 (~7.3 GB)
```

No Hugging Face login is needed: the model and dataset repos are public.

**Windows:** use PowerShell or Windows Terminal; the same commands work. A current NVIDIA driver
is all CUDA needs (no toolkit). Output is forced to UTF-8 at start-up.

**macOS:** the same commands in Terminal. `--device auto` picks `mps`, and the header line of
every run then reads `device=mps precision=fp32`.

## Usage

```
uv run wildid photos/                                   # everything under photos/, top 3 each
uv run wildid DSC04512.ARW --country Brazil --region "Mato Grosso"
uv run wildid photos/ --country Kenya --anomaly-check   # flag frames the regional list disagrees on
uv run wildid photos/ --continent Africa --taxa Mammalia,Reptilia
uv run wildid photos/ --place-id 8239                   # iNaturalist place id, skips name lookup
uv run wildid photos/ --model bioclip-2 --k 5 --ext jpg,jpeg,arw --batch-size 32
uv run wildid photos/ --crop                            # MegaDetector finds the animal, BioCLIP sees the crop
uv run wildid photos/ --crop --crop-exact               # exact resize before the detector: the same pixels on a Mac and a PC
uv run wildid photos/ --second-opinion --country Kenya  # + SpeciesNet verdict per frame (implies --crop)
uv run wildid photos/ --precision fp16                  # fastest; may change ~0.5 % of top-1 answers
uv run wildid photos/ --format json --output run.json   # machine-readable results incl. suggested keywords
uv run wildid /media/card/DCIM --write-xmp --country Brazil   # keyword sidecars before Lightroom import
uv run wildid serve                                     # local daemon for the Lightroom plugin
```

Results are plain text blocks on **stdout**; progress, warnings and logs go to **stderr**, so
stdout can be redirected to a file. `python -m wildid` is equivalent to `wildid`.

```
wildid 0.1.0 | model=bioclip-2.5 device=cuda | candidates=412 species (Brazil › Mato Grosso; Mammalia,Reptilia,Amphibia,Aves; fetched 2026-10-23)
note: scores are a softmax over the candidate set and are not comparable between runs with different candidates
DSC04512.ARW
  1. Panthera onca            Jaguar                 0.962
  2. Puma concolor            Puma                   0.021
  3. Leopardus pardalis       Ocelot                 0.009
  unconstrained top-1: Panthera onca (0.871)
```

Rows that are the same species (duplicate table entries, subgenus spellings, GBIF synonyms the
cache knows) are merged in the top-k and their probability mass summed.

**Scores are relative to the candidate set.** A 0.9 among 400 regional species is not a 0.9
among the full ~800 k TreeOfLife taxa. With a geo filter, single-file runs (and directory runs
with `--anomaly-check`) also print the unconstrained top-1 and mark it `⚠ not in <place> list`
when it falls outside the regional list — the signal that the filter may be hiding the truth.

### Detector crop and second opinion

`--crop` runs MegaDetector v6 (`--detector mdv6-yolov9-c`, 640 px, fast; or `mdv6-yolov9-e`,
1280 px, better on small animals) and classifies the highest-confidence animal box, padded by
10 % and at least 224 px. It is the biggest accuracy lever for distant frames: on the owner's
Kenya set it turned a 0.20 "francolin" into a 0.91 cheetah. Frames without a detection fall back
to the full frame, and the block says which happened:

```
  crop: animal 0.93 → 1412×1090 px
```

`--crop-exact` (with `--crop`, off by default) makes the resize before the detector the same
on a Mac and a PC. ultralytics reduces each photo to the detector's size with OpenCV's
bilinear resize, and OpenCV's build for Arm computes that with its own code: the detector's
input then differs by 1 in about a fifth of its values between a Mac and a PC, the box moves
by a pixel or two on about a third of the JPGs, and about 2 % of the cropped photos get
another name, most of them review frames on both. With the flag the resize is OpenCV's
`INTER_LINEAR_EXACT`. Measured on 1,020 photos between the Mac and the Linux box
(`docs/acceptance.md`, 2026-11-15): the detector then computes on the same pixels on both,
and with fp32 on both every crop and all 2,040 answers are the same; against the PC's
default TF32, 31 crops and 5 answers still differ. Windows was not part of the measurement.
The flag is not a gain in accuracy, and on either machine it changes about 2 % of the answers
against a run without it: it is for when two computers have to agree. In JSON output
`crop_resize` says which resize a run used: `linear`, `exact`, or `null` without the crop.

`--second-opinion` additionally classifies the crop with SpeciesNet (Google's camera-trap
classifier, strongest on mammals, weak on birds and reptiles) and prints its answer with a
verdict against BioCLIP's top-1: `agrees`, `same genus/family/order/class`, `no taxon` (blank,
human, vehicle) or `⚠ disagrees`.

```
  speciesnet: Crocuta crocuta — spotted hyaena (0.941)  agrees
```

Both need weights fetched once: `uv run wildid prefetch --crop --second-opinion`.

### Precision and throughput

`--precision auto` (default) uses TF32 matmuls on CUDA: identical top-1 answers on 863 test
frames and about 11–16 % faster. `fp16` enables autocast: 22–47 % faster again but changed 6 of
863 answers, so it is opt-in. `fp32` turns everything off. The header line shows what ran.
On Apple Silicon (`mps`) `auto` is fp32: TF32 is a CUDA mode and falls back to fp32 with a
warning. `fp16` is the same opt-in there (measured on 2026-11-14 and 2026-11-15, ADR 0003;
the figures above are the RTX 4090's).

Images are resized for the model in the loader threads (`--workers`, default up to 8) rather
than one by one inside the classifier, which more than doubles directory throughput on the
RTX 4090: 144 img/s with `bioclip-2` and 98 img/s with `bioclip-2.5` on 1440×1800 JPGs. For
`bioclip-2.5` this is bit-exact; for `bioclip-2` it uses PIL's antialiased resize instead of
torchvision's and flipped 16 of 863 near-tie answers (top-1 ≤ 0.44, scores within 0.05).
`WILDID_NO_PRESHRINK=1` restores the original path.

### Geo filter

`--region` > `--country` > `--continent` (most specific wins, lists are never unioned;
`--region` requires `--country`). The species list for the place is fetched from iNaturalist
once per taxon class (`--taxa`, default `Mammalia,Reptilia,Amphibia,Aves`), cached on disk, and
intersected with the model's species names at species rank. Birds stay in the default list on
purpose: without them, bird photos are forced into a confident wrong mammal or reptile.

Cached lists are used as long as they exist; older than 30 days only earns a warning.
`--refresh-geo` refetches when the network is reachable. iNaturalist has no continent-level
place for Antarctica: use `--place-id` with a regional place there.

iNaturalist and TreeOfLife spell some species differently (*Tragelaphus oryx* vs *Taurotragus
oryx*). `wildid prefetch --country <X>` looks the unmatched names up in the GBIF backbone once,
caches the result, and the classifier then maps them (94 of 173 unmatched Kenyan names);
`wildid PATH` itself never calls GBIF. `--geo-rank genus` keeps every model species of the
genera on the list instead of the exact species, for places with thin iNaturalist coverage
(Kenya: 6,416 candidates instead of 1,325).

### Per-photo geo from GPS

`--geo-auto` reads each photo's EXIF GPS position, maps it to its iNaturalist country
(`--geo-level region` picks the state/province instead) and classifies the photo against that
place's cached species list. Photos are grouped by place and each group runs once with its own
filter; the header says how many places took part and every block carries a `place:` line.
The lookup is cache-only, in the CLI and the daemon alike: `wildid prefetch --gps-from PATH`
resolves the distinct 0.25° cells of a folder's photos online once (one iNaturalist
`places/nearby` call per cell), then fetches the species lists and GBIF synonyms for the places
found. A classify run never resolves a cell itself, even with network: a trip spans many cells,
each failed lookup would cost seconds and silently change the result, and the synonyms only come
with prefetch. A photo without GPS runs against the full TreeOfLife and is not flagged; a photo
whose cell was never prefetched (or prefetched at the other level) also runs unfiltered **and**
is flagged for review, with the prefetch command in the reason, and the run's summary says how
many. `--geo-auto` cannot be combined with `--country`/`--region`/`--place-id`.

### Exit codes

| code | meaning |
|---|---|
| 0 | ok (some files may have failed to load; they are listed on stderr) |
| 1 | usage or geo error, including a missing geo cache when offline |
| 2 | model load failure, including a missing model cache (the message names the `wildid prefetch` command) |
| 3 | every image failed to load |

## JSON output, XMP sidecars and Lightroom

`--format json` (optionally `--output FILE`) writes one machine-readable document (`protocol`
1): a `keywords` block naming the root and the flat tags wildid owns on a photo, then per
photo the predictions, the anomaly verdict, a `review` flag and `suggested_keywords` —
the top-1 as `WildID|<class>|<genus>|<species>` with the common name as a keyword synonym
(the class as iNaturalist spells it: the TreeOfLife tables carry GBIF's Squamata, Testudines,
Crocodylia and Sphenodontia in the class column, and wildid writes `Reptilia` for all four),
plus `WildID|review` when the top-1 score is under `--min-score` (default 0.5; scores are a
softmax over the candidate set, so this is a heuristic) or the unconstrained top-1 falls
outside the place list. `--keyword-root` renames the root. Photos judged to contain an animal
also get the flat tags `animals` and — unless the species is domesticated (dog, cat, cattle,
horse, …; `constants.DOMESTIC_SPECIES`) — `wildlife`; "judged" means the detector's verdict
when `--crop` ran, otherwise top-1 score ≥ `--min-score`.

`--write-xmp` writes those keywords as `.xmp` sidecars next to **RAW files only** (JPEG and
DNG embed XMP inside the file; wildid never modifies photo files) — run it on a card folder
*before* importing and Lightroom picks the keywords up at import. Existing sidecars are
skipped by default because they carry develop settings; `--xmp-mode merge` appends the keyword
entries and touches nothing else. `--dry-run` reports without writing. Pre-import only, on
purpose: Lightroom treats an external XMP change to an imported photo as a fork — resolving
it either reverts unsaved catalog edits (Read Metadata) or discards the external keywords
(Save Metadata) — so once photos are in the catalog, the plugin (which writes through the
catalog, never files) is the right path.

For photos already in Lightroom, use the plugin (`lrplugin/wildid.lrplugin`,
[docs](lrplugin/README.md)): it talks to `wildid serve`, a token-protected daemon on
127.0.0.1 that keeps the model warm (`--idle-exit` frees the GPU after 15 quiet minutes;
`--model` picks the model loaded at start-up, any other is loaded lazily on the first request
or `POST /warmup` naming it, and `/health` reports per-model state plus the GPU's memory), and
writes keywords plus searchable custom metadata into the catalog, and files photos into a
taxonomy tree of collections under a collection set of your choice — a set per class, a set
per genus, a collection per species (`WildID/Mammalia/Panthera/Panthera onca — Jaguar`; review
photos into `_review`; re-identified photos move with their new species) — so a fresh import
can run through bioclip-2 and the `Mammalia` set again through bioclip-2.5. The plugin's
"prefetch place list" menu is the one online step; identification runs stay offline. A per-user Windows
installer that ships engine + plugin together lives in [installer/](installer/README.md), next
to a macOS download for Apple Silicon (a zip with `install.sh`; built, acceptance open), and
`wildid setup` is the guided first-run (downloads → offline verification; a Hugging Face
token is optional, the repos are public). Design decisions: `docs/decisions/0005-lightroom-integration.md`.

## Offline operation and the pre-trip checklist

`wildid PATH` never downloads anything: it runs with `HF_HUB_OFFLINE=1` (model and embeddings
come from the local cache, no revision checks, no connection timeouts) and reads geo lists
cache-first. `--offline` makes the guarantee absolute: zero network calls, fail fast with the
exact prefetch command if something is missing.

Before a trip, on the machine that will run inference:

```
uv run wildid prefetch --model all --crop --second-opinion --country <X> [--region <Y>]
uv run wildid prefetch --gps-from <last trip's folder>   # per-photo geo: resolve its GPS cells
uv run wildid --offline test.jpg --country <X>                            # with the network disabled
```

`prefetch` is idempotent, renews stale geo lists, and by default verifies itself by running the
classify path once in a child process with the network forbidden. Geo arguments repeat; each
`--region` pairs with the `--country` at the same position, so pass `--region ""` for a country
that has none:

```
uv run wildid prefetch --country Thailand --region "Nakhon Ratchasima" --country Madagascar --region ""
```

On a laptop without an NVIDIA GPU (and that is not an Apple Silicon Mac) it runs on CPU
(seconds per image) and needs ~10 GB of free RAM for model + embeddings.

Caches you can copy to another machine:

| what | where | override |
|---|---|---|
| model + TreeOfLife embeddings | `~/.cache/huggingface` (`%USERPROFILE%\.cache\huggingface`) | `HF_HOME` |
| geo lists, place resolution, GPS cells | `~/.cache/wildid/geo` (`%LOCALAPPDATA%\wildid\Cache\geo`; macOS `~/Library/Caches/wildid/geo`) | `WILDID_CACHE_DIR` |
| MegaDetector + SpeciesNet weights | `~/.cache/wildid/models` (macOS `~/Library/Caches/wildid/models`) | `WILDID_CACHE_DIR` |

## Models

| `--model` | encoder | embeddings | notes |
|---|---|---|---|
| `bioclip-2` (default) | ViT-L/14, 768-d | TreeOfLife-200M, 867,455 taxa | pybioclip's stock model; ~4.4 GB GPU, ~117 img/s batch 32 on an RTX 4090 |
| `bioclip-2.5` | ViT-H/14, 1024-d | TreeOfLife-200M, 794,878 taxa | **no reptiles in its embedding set** (see below); ~7.3 GB GPU, ~75 img/s |

`bioclip-2.5` is the larger, newer encoder, but the TreeOfLife text embeddings published for it
contain no reptiles at all (no Squamata, Testudines or Crocodylia), so a reptile photo gets a
confident wrong answer. That is why `bioclip-2` is the default; pick `--model bioclip-2.5` for
mammal- or bird-only shoots. Details and evidence: `docs/decisions/0001-bioclip-25.md`.

RAW files (`arw nef cr2 cr3 orf raf rw2 dng`, any letter case) are read through their embedded
JPEG preview (LibRaw via rawpy); nothing is demosaiced in the normal path. A file whose preview
is smaller than 256 px (some DNGs) falls back to a half-size demosaic, logged on stderr.

## Development

```
uv run pytest                      # unit tests: no network, no GPU, no model
WILDID_LIVE_TESTS=1 uv run pytest  # also the end-to-end tests with the real model
uv run ruff check src tests && uv run ruff format src tests
```

Design decisions live in `docs/decisions/` (ADRs); per-phase acceptance evidence in
`docs/acceptance.md`; the original plan in `species-id-mvp-plan.md` (its §4 is the CLI contract:
flags get added, never renamed).

## Website

The project website is a static site in [`website/`](website/README.md): plain HTML with the
setup guides for Windows (Lightroom Classic) and Linux, no build step.
`.github/workflows/pages.yml` publishes it to GitHub Pages whenever a push to `main` changes
`website/`. `website/TODO_WEBSITE.md` lists what is still open for the site.

## Licence

wildid, the `wildid serve` daemon, the Lightroom plugin and the installer scripts are free
software under the GNU Affero General Public License, version 3 or later (`LICENSE`, SPDX
`AGPL-3.0-or-later`; `docs/decisions/0007-free-open-source-agpl.md`). This repository is the
source; each release carries the installer next to the tagged source it was built from. The
detector crop and the second opinion import `ultralytics` (AGPL-3.0), which is why the whole
program is AGPL rather than permissively licensed. Model weights and reference data are not
part of this licence and keep their publishers' terms: BioCLIP 2 / 2.5 (MIT) and the
TreeOfLife-200M text embeddings (CC0-1.0) on Hugging Face, downloaded per user by `prefetch`
and never bundled; MegaDetector v6 weights (CC-BY 4.0, Microsoft / PyTorch-Wildlife);
SpeciesNet (Google, Apache-2.0 code; weights per the Kaggle model page); the GBIF Backbone
Taxonomy (CC-BY 4.0) and the iNaturalist API terms of service.
