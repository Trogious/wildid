# ADR 0004 — Post-MVP items 6 and 7: GBIF synonym mapping, top-k dedupe, genus-level geo mode

**Status:** accepted (2026-10-23)
**Context:** plan §10 items 6 ("synonym-aware dedupe of top-k rows; collapse subspecies into
species") and 7 ("genus-level geo mode for regions with thin iNat coverage"); the risk-table
entry "iNat ↔ TOL name mismatch drops real species … later add synonym mapping".

## 6a. Regional-list synonym mapping through the GBIF backbone

**Problem.** 173 of the 1,498 Kenyan species on the iNaturalist list were unknown to the model
by spelling (11.5 %; 39 % for the Africa list), and real frames paid for it: the eland frame was
classified as beisa oryx because iNaturalist says *Tragelaphus oryx* and TreeOfLife says
*Taurotragus oryx*.

**Decision.** TreeOfLife-200M's names come from the GBIF backbone, so GBIF is the authority for
reconciliation: `species/match?strict=true` gives the backbone taxon for the iNat name
(accepted or synonym), `species/{acceptedKey}/synonyms` its other species-rank spellings, and the
first spelling the model knows is used (`wildid.synonyms`). Only EXACT matches count, plus FUZZY
at confidence ≥ 95: non-strict/fuzzy matching maps *Mops pumilus* to *Chaerephon pusillus*, a
different bat, at confidence 94, and names GBIF lacks entirely (recent splits such as
*Lupulella mesomelas*, *Genetta fieldiana*, *Madoqua hindei*) only get useless genus-level
HIGHERRANK matches. Those stay unmatched, honestly.

Lookups happen in **`wildid prefetch` only** (it is the online, pre-trip step; D15), after the
models and species lists, for the names the prefetched model(s) do not know; results are cached
per name in `<cache>/geo/gbif-names.json` (progress saved every 25 names). The classify path
reads that cache and never calls GBIF; it logs how many unmatched names have no lookup yet and
the prefetch command that would do it. GBIF's role here is name resolution; iNaturalist stays
the only source of species lists (D9).

**Measured** (Kenya list, bioclip-2): GBIF resolves 94 of the 173 unmatched names, e.g.
*Tragelaphus oryx* → *Taurotragus oryx*, *Nesotragus moschatus* → *Neotragus moschatus*,
*Felis lybica* → *Felis silvestris*, *Smutsia temminckii* → *Manis temminckii*,
*Herpestes sanguineus* → *Galerella sanguinea*; 44 names are absent from the backbone and 35 are
GBIF-accepted names the model simply lacks. ~350 requests at 4/s ≈ 70 s, once.

## 6b. Top-k dedupe

The label tables contain duplicate binomials (115 rows in bioclip-2's table, 185 in 2.5's) and,
in bioclip-2's, 11,317 subgenus-style three-word names ("Charis Sarota acanthoides"). The
classifier now fetches a few extra rows (`max(2k, k+4)`), merges rows whose canonical key is
equal, and keeps the first row's names. Canonical key = genus + last epithet word (collapses
subgenus spellings and any trinomial), then the GBIF accepted name when the name cache knows
one. Merged rows **sum** their probability mass (the softmax had split it). Full TreeOfLife-wide
synonym resolution (867 k names) is out of scope; the cache only covers names that went through
a regional-list lookup, so synonym pairs like *Grus grus* / *Grus communis* merge only once one
of them was resolved (the second is not in the table today).

## 7. Genus-level geo mode (`--geo-rank genus`)

For places with thin iNaturalist coverage, `--geo-rank genus` keeps every model species of
the genera on the regional list (genera of unmatched names included, as their genus often
exists in the model under another species). It uses pybioclip's `create_taxa_filter(Rank.GENUS,
…)`; order and family are still never used (plan §1.2). The header says "genus level". Kenya:
660 genera (628 known), 6,416 candidate species instead of 1,325.

## Consequences

- CLAUDE.md's geo rule becomes "species rank by default; `--geo-rank genus` is the only wider
  mode; never order/family".
- `--geo-rank` and the synonym step add no network to the classify path.
- The remaining unmatched names (recent taxonomic splits) need a curated override list; not done.
