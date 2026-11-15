# ADR 0002 — Geo species lists from iNaturalist

**Status:** accepted (2026-10-23)
**Context:** plan §5, D7–D9, D14.

## Decision

Regional species lists come from the iNaturalist API v1
(`observations/species_counts`, research grade, one iconic taxon per request series) and are
cached on disk. The list both filters and *constrains* the classifier: it is intersected with
the model's species names and applied with pybioclip's `create_taxa_filter(Rank.SPECIES, …)` +
`apply_filter`. Filtering is species-rank only (pybioclip's own docs warn that higher ranks do
not exclude non-local species). GBIF stays a documented manual fallback only.

## Verified against the live API (2026-10-23)

- Continent places (autocomplete, then `/v1/places/<id>`), all `admin_level -10`,
  `place_type 29`: Africa 97392, Asia 97395, Europe 97391, North America 97394,
  Oceania 97393, South America 97389. These are pinned in `constants.CONTINENT_PLACE_IDS`.
  **Antarctica has no continent-level place** (only regional ones such as "Ross Dependency -
  Antarctica", id 67583); `--continent Antarctica` therefore errors and points at `--place-id`.
- Countries are `admin_level 0` / `place_type 12` (Brazil 6878, Aruba 8359, Poland 7800,
  Kenya 7042); states/provinces `admin_level 10` (Mato Grosso 8239), counties `admin_level 20`.
  `ancestor_place_ids` lists the chain, e.g. Mato Grosso → [97389, 6878, 8239].
- `species_counts` honours `per_page=500`, returns `total_results`, and rows carry
  `taxon.{name, rank, preferred_common_name, iconic_taxon_name}`; ranks seen include
  `species` and `hybrid` (dropped). Counts for Aruba: Mammalia 12, Reptilia 30, Amphibia 3,
  Aves 191; Brazil: Mammalia 572, Aves 1784 (4 pages).

## Cache layout (`platformdirs.user_cache_dir("wildid")/geo`, override `WILDID_CACHE_DIR`)

- `places.json`: normalised query (`country:brazil/region:mato grosso`, `id:8239`) → place
  record + label. A known place never touches the network again.
- `<place_id>__<taxon>.json`: **one file per (place, iconic taxon)**, not per taxa combination.
  This is a deliberate refinement of the plan's `<place_id>__<taxa-slug>.json`: a run with
  `--taxa Mammalia,Reptilia` reuses the files fetched by the default four-taxa run, and the
  fetch itself is per taxon anyway (10 000-result cap per query series).
- Freshness: < 30 days → use; older → use and warn; `--refresh-geo` refetches when the network
  is reachable and otherwise falls back to the cached list with a warning. `wildid prefetch`
  renews stale lists automatically (it is the pre-trip step). `--offline` never attempts a fetch.
- Request policy: `User-Agent: wildid/<version> (personal wildlife photo tool)`, ≥ 1 s between
  requests, 5 s connect / 30 s read timeout, HTTP 429 surfaces as a clear error.

## Known limitations (post-MVP backlog)

- iNat ↔ TreeOfLife name drift drops a few percent of species (logged with a sample); no
  synonym mapping yet.
- Scores are a softmax over the candidate set, so a regional 0.9 is not comparable to a full-TOL
  0.9; the header and `--help` say so, and the anomaly line shows the unconstrained top-1.
