# ADR 0001 — BioCLIP 2.5 Huge inside pybioclip

**Status:** accepted 2026-10-23, **amended the same day** (default flipped to bioclip-2, see
"Amendment" below).
**Context:** plan §2 (the one real blocker), D2.

## Decision

BioCLIP 2.5 Huge (`hf-hub:imageomics/bioclip-2.5-vith14`) runs through pybioclip's
`TreeOfLifeClassifier` via a thin subclass (`wildid.model.TreeOfLifeClassifier25`) that points
the TreeOfLife text embeddings at `imageomics/TreeOfLife-200M` /
`embeddings/txt_emb_bioclip-2.5-vith14.{npy,json}`. The override works and all Phase 0 gates
pass. **The default model is nevertheless `bioclip-2`** (D2's fallback), because the published
2.5 embedding set has no reptiles; 2.5 remains selectable with `--model bioclip-2.5`.

## Amendment (2026-10-23, Phase 3): the 2.5 TreeOfLife embeddings contain no reptiles

Found while checking iNaturalist ↔ TreeOfLife name drift for `--country Kenya`: every one of
the 230 Kenyan reptile species was "unknown" to the 2.5 label table, while mammals, amphibians
and birds matched at the expected ~90 %. Verified directly on the raw files:

| | `txt_emb_bioclip-2.5-vith14.json` (794,878 taxa) | `txt_emb_species.json` = BioCLIP 2 (867,455 taxa) |
|---|---|---|
| `"Crocodylus"` occurrences | 0 | 25 |
| `"Squamata"` / `"Testudines"` | 7 / 0 | 8,476 / 460 |
| *Crocodylus niloticus*, *Iguana iguana*, *Vipera berus*, *Caretta caretta*, *Chamaeleo dilepis* | all absent | all present |
| Kenya list matched (Mammalia / Reptilia / Amphibia / Aves) | 202/234 / **0/230** / 78/89 / 848/945 | 202/234 / 195/230 / 78/89 / 850/945 |

On the owner's reptile and tortoise samples 2.5 returns ticks, frogs and extinct walruses;
bioclip-2 returns Madagascar swift, chameleons, a Madagascar boa, a flat-tail gecko and
tortoises. The cause is upstream: the dataset's `embeddings/README.md` says the 2.5 JSON was
built from the 2.5 catalog with null-rank filtering; reptiles in the GBIF backbone carry an
empty `class` (BioCLIP 2's table has 32,106 such rows, reptiles among them), and they did not
survive into the 2.5 file.

*Correction 2026-10-27, measured on the raw bioclip-2 table:* reptiles are not class-less there
— the GBIF backbone has no Reptilia and puts the reptile orders in the class column (Squamata
8,475 rows, Testudines 459, Crocodylia 66, Sphenodontia 7) with an empty order. The 32,106
empty-class rows are mostly ray-finned fish (23,700 Chordata rows: Perciformes, Cypriniformes,
Siluriformes…). The 2.5 file's null-rank filtering then dropped the reptiles on their empty
*order*. The engine maps those four classes to Reptilia (ADR 0005, amendment 2026-10-27).

Consequences: `constants.DEFAULT_MODEL = "bioclip-2"`; loading 2.5 logs a warning naming the gap;
the README says when 2.5 is still the better choice (mammal/bird-only shoots). Revisit when
`imageomics/TreeOfLife-200M` ships a 2.5 embedding file with reptiles or pybioclip adds native
2.5 support; flipping the default back is a one-line change.

## What Phase 0 found

- pybioclip 2.1.6 (latest on PyPI, 2026-08-15) has **no native 2.5 support**: `TOL_MODELS` lists
  only `bioclip` and `bioclip-2`, and `get_tol_repo_id()` raises for anything else. The override
  is still required.
- The override only needs three methods: `get_tol_repo_id`, `get_txt_emb`, `get_txt_names`.
  `get_cached_datafile()` (which `get_txt_emb` uses) already routes through `hf_hub_download`
  with `repo_type="dataset"`, so HF offline mode covers it.
- Embedding file is `float32 (1024, 794878)`, i.e. already `(dim, N)` as pybioclip expects; the
  transpose branch in the override is defensive only. Names JSON has 794,878 entries with full
  7-rank taxonomy (BioCLIP 2's `txt_emb_species` has 867,455 entries, some with blank ranks).
- Neither the model repos nor the dataset repo is gated; no HF login needed.
- Verification gates (bear fixture, RTX 4090, eager mode):

  | gate | bioclip-2 | bioclip-2.5 |
  |---|---|---|
  | embeddings shape | (768, 867455) | (1024, 794878) |
  | names == columns | yes | yes |
  | bear top-1 | *Ursus arctos* 0.830 | *Ursus arctos* 0.99998 |
  | create/apply filter + unfiltered pass | ok | ok |
  | load time (warm cache) | 3.1 s | 4.4 s |
  | 32-image batch | 117 img/s | 75 img/s |
  | GPU memory (allocated) | 4.4 GB | 7.3 GB |

## Related runtime decisions

- **torch.compile is disabled by default.** pybioclip wraps the model in `torch.compile()`; the
  first forward pass would then compile ViT-H (tens of seconds, needs a C compiler and Triton,
  not available for CUDA on Windows). Eager mode gives 75 img/s on the 4090, so
  `wildid.env` sets `TORCH_COMPILE_DISABLE=1` unless `WILDID_TORCH_COMPILE=1` is set.
- **Preprocessing differs between the two models** and this is left as pybioclip ships it:
  for bioclip-2 pybioclip uses its own squash-resize to 224×224; for 2.5 (unknown to pybioclip)
  the open_clip transform from the model card applies (shortest-side resize + centre crop).
- **Label data is cached**: pybioclip rebuilds the ~800 k-row DataFrame on every
  `get_label_data()` call and `create_taxa_filter()` calls it internally. Both wildid classifier
  classes cache it (one build, ~4 s).
- `clear_filter()` resets pybioclip's private `_subset_txt_*` attributes. Re-applying an all-True
  mask would copy the full text matrix on the GPU; pybioclip has no public clear.

## Python version

The plan said 3.12; the project runs on **Python 3.14** (owner's request, 2026-10-23) with
`requires-python >= 3.12`. All binary dependencies ship cp314 wheels (torch 2.14.1+cu130,
torchvision 0.29.1, rawpy 0.27.1, pandas 3.1, numpy 2.5, pillow 13). torch.compile works on
3.14 but is off by default anyway (see above).

## Measurement 2026-10-25 (Windows acceptance, section E)

First accuracy comparison on the owner's own photos: 401 species-labelled lemur frames
(Madagascar 2025, four folders), crop on, Madagascar place list, top-1 only. bioclip-2.5 77.1 →
**80.8 % correct species (+3.7 pp)**; genus level 81.0 → 83.0 %. Caveats: one trip, one taxon
group. Without the place list (full TreeOfLife) the gap widens to **+10.0 pp** (69.8 → 79.8 %),
so it is not an artefact of the smaller filtered candidate set (575 vs 860 names).
This counts as the "new evidence" the default-model rule asks for, but it does not change the
default: 2.5 still has no reptiles, and the gain is modest and single-trip. Consequence: the
plugin's model radio may describe 2.5 as "more accurate (+3.7 pp on 401 owner lemur frames)"
instead of coverage/speed only. Full table in `docs/acceptance.md`.

## Measurement 2026-10-25 (Linux, re-cut sample set)

Second comparison, on the owner's JPG exports (`sample-jpg/`, 14 species-labelled lemur folders
from the same Madagascar 2025 trip), crop on, same code for both models: species top-1 over 385
frames 70.1 → **72.5 % (+2.3 pp)** with the Madagascar place list (860 / 575 candidates),
65.7 → 72.2 % (+6.5 pp) without it; genus level 90.4 → 89.9 %. Same direction and shape as the
Windows run; the decision rule (≥ 2 pp over ≥ 200 frames) is met narrowly. On the 63 Madagascar
reptile frames bioclip-2 scores 100 % with the list and 2.5 scores 0 %, and on 22 Kenya mammal
ARWs 2.5 misses two frames bioclip-2 gets. Default unchanged; the subscript's "+3.7 pp on 401
owner lemur frames" is corroborated, not increased. Table in `docs/acceptance.md`.
