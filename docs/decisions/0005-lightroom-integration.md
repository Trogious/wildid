# 0005 — Lightroom integration: local daemon + Lua plugin, pre-import XMP sidecars

**Date:** 2026-10-24 · **Status:** accepted · **Full plan:** `lightroom-plugin-plan.md`

## Context

Lightroom Classic plugins are Lua 5.1 against Adobe's SDK — no Python runs inside Lightroom,
and every wildid invocation pays torch import + model load. Post-MVP backlog item 8 called for
machine-readable output and XMP keyword write-back.

## Decisions

1. **Transport: HTTP daemon on 127.0.0.1** (`wildid serve`), stdlib `http.server` only — no
   FastAPI/uvicorn (same dependency-bloat rule as ADR 0003's SpeciesNet call). The plugin
   discovers it through `serve.json` (OS-assigned port + bearer token, owner-only file) in the
   wildid cache dir. The token is mandatory on every request: loopback is reachable by any
   local process and by browsers via DNS rebinding. `--idle-exit` (default 900 s) frees the
   GPU; the plugin restarts the server on demand.
2. **Keyword policy lives in Python** (`keywords.py`): top-1 as `Root|class|family|species`
   with the common name as keyword synonym, plus `Root|review` when the score is under
   `--min-score` (default 0.5) or the unconstrained top-1 is outside the place list. The
   server returns `suggested_keywords`; the Lua plugin is a dumb writer. JSON output, XMP
   sidecars and the daemon all share this one implementation.
   *Amended 2026-10-25:* photos judged to contain an animal also get the flat, root-less tags
   `animals` and — unless the species is in `constants.DOMESTIC_SPECIES` (trinomials collapsed
   to genus + epithet first) — `wildlife`. "Judged" = the detector's verdict when the crop
   stage ran, else top-1 score ≥ `min_score`. Additive to `suggested_keywords`, so no
   protocol bump and no plugin change.
   *Amended 2026-10-25 (B4):* the daemon is multi-model — `--model` loads at start-up, any
   other known model loads lazily under the inference lock on the first `/classify` or
   `POST /warmup` naming it, and stays for the process lifetime (`--idle-exit` releases VRAM).
   `/health` reports per-model state and the GPU's memory (SI GB); the plugin offers a per-run
   radio (default unchanged: bioclip-2) and disables "keep both loaded" only when detection
   succeeded and the card has < 20 GB (raised from 14 after the §E measurement: both models
   under load ≈ 15.7 GB incl. desktop, so 16 GB cards must stay off; re-measured on Linux
   2026-10-25 after the detector fix with 24-photo crop requests: 14.1 GB above a 1.3 GB
   desktop, subscripts set to the under-load figures ~7 / ~10 / ~14 GB). All additive:
   protocol stays 1.
   *Amended 2026-10-27 (plugin 0.3.1, class collections):* the owner's workflow is bioclip-2
   on a fresh import, then the mammals again through bioclip-2.5, so the plugin also files
   every photo into `<set>/<class>` (Mammalia, Aves, Reptilia…; "and by class" checkbox,
   default on) and moves it when a re-identification changes the class, using a new
   `wildidClass` custom-metadata field (Metadata.lua `schemaVersion` 2). For this to yield one
   `Reptilia` collection the engine normalises the class at the source
   (`model.normalise_class`, `constants.REPTILE_CLASS_ALIASES`): the GBIF backbone behind the
   TreeOfLife tables has no Reptilia and carries Squamata / Testudines / Crocodylia /
   Sphenodontia in the class column (bioclip-2: 8,475 / 459 / 66 / 7 rows, measured
   2026-10-27). Keywords and XMP therefore read `WildID|Reptilia|…` for reptiles from now on
   (previously `WildID|Squamata|…`; until 2026-10-28 a run never removed keywords, so an old
   hierarchy could linger). Ray-finned fish have no class in that table at all (23,700 rows) and
   are left without one. Additive to the result document: protocol stays 1.
   *Amended 2026-10-28 (plugin 0.3.1+, class/genus tree):* the flat class collections gave
   way to a taxonomy tree under the chosen set — a collection set per class, inside it one
   per genus, and a collection per species as the leaf (`<set>/Mammalia/Panthera/Panthera
   onca — Jaguar`; `_review` stays next to the class sets; a species the table gives no class
   goes under `_no class`). Selecting a class or genus set shows everything below it, which
   covers the "mammals again through 2.5" workflow without filing every photo twice. Family
   is left out on purpose: the owner chose class and genus as the two levels, and the keyword
   hierarchy followed the same day (next amendment). Moves on re-identification look the old species up
   anywhere under the set and only remove a photo from a collection that holds it, so photos
   filed by the flat layout migrate as they are re-run and a re-run of filed photos writes
   nothing; a flat class *collection* that would block its class *set* is renamed `… (flat)`
   and reported (`LrCollection:setName`, the one SDK call added). The "and by class" checkbox
   and the `classCollections` pref are gone; `wildidClass` stays as searchable metadata. The
   "delete empty collections" menu always removes sub-sets left with nothing in them (its
   checkbox is gone): emptied genus and class sets are the normal residue of a move. Uses
   the `genus` and `class` fields the result document already carries: protocol stays 1.
   *Amended 2026-10-28 (keywords follow the tree):* the keyword hierarchy is
   `Root|class|genus|species` from now on (previously `Root|class|family|species`), so the
   Keyword List and the collection tree read the same way. The genus is the table's, else the
   first word of a multi-word species name; an empty class is still skipped. The family branch
   (`WildID|Mammalia|Felidae|…`) comes off a photo when it is re-run (next amendment); the
   emptied family keywords can then be deleted from the Keyword List. JSON output, XMP
   sidecars and the daemon share the change through `keywords.py`; the plugin, a dumb writer,
   needs nothing. `suggested_keywords` keeps its shape: protocol stays 1.
   *Amended 2026-10-28 (the root and the flat tags are the plugin's namespace):* a run now
   replaces the photo's keywords under the root — whatever an earlier run or an imported wildid
   sidecar put there and the new suggestions do not repeat: the old species keyword, a stale
   `<root>|review` — and takes the flat `animals` / `wildlife` tags off when the new run no
   longer suggests them, before attaching the new ones, in the same undoable transaction
   (`WildidKeywords.lua`). This reverses the earlier "a run never removes keywords" rule for
   exactly that namespace: anything under another root, or any other flat keyword, stays. The
   run document declares the namespace (`keywords: {root, flat}`, additive, protocol stays 1),
   so the plugin reconciles what the server names and carries no keyword name of its own;
   policy still comes from `keywords.py`. XMP `merge` is unchanged (append-only, pre-import).
   *Amended 2026-11-15 (the keep-both rule, macOS; ADR 0008 decision 5):* unified memory has
   its own threshold. Where `/health.vram.kind` is `unified` (Apple Silicon), "keep both
   loaded" needs 30 GB of the reported figure, which is what Metal recommends a process stays
   under: both models hold 20.1 GB there and Lightroom and macOS live in the same memory. The
   20 GB rule for a graphics card is unchanged. On a Mac the dialog's subscripts quote the
   footprint measured on Apple Silicon (~12 / ~13 / ~20 GB memory) in place of the VRAM
   figures. On both platforms the rule is now applied again to the running server's `/health`
   before the second model is loaded: the probe for the dialog may predate the server, and
   unknown memory still leaves the checkbox enabled. Plugin only: protocol stays 1.
3. **One result schema** (`results.py`, `protocol: 1`) for `--format json` / `--output` and
   every `/classify` response. `protocol` bumps only on breaking changes; the plugin refuses
   servers speaking another protocol.
   *Amended 2026-11-15 (exact detector resize; ADR 0003 §1):* a request may carry
   `crop_exact`, and the run document gains `crop_resize` (`linear`, `exact`, or `null`
   without the crop). Both are additions: `protocol` stays 1, an older server ignores the
   key and an older plug-in never sends it. The Identify dialog has the checkbox "Exact
   detector resize (the same on a Mac and a PC)", off by default, enabled when the crop or
   the second opinion is on (the title said "meant to be the same on every computer" until
   backlog item 13 had measured it, the same day). The server keeps one loaded detector for
   both kinds of request.
4. **XMP sidecars are pre-import and RAW-only** (`--write-xmp`): Lightroom reads sidecars only
   for proprietary RAW; JPEG/TIFF/DNG embed XMP and wildid never modifies photo files. Default
   `new-only` skips existing sidecars (they carry develop settings); `--xmp-mode merge`
   appends `dc:subject` / `lr:hierarchicalSubject` entries and wildid provenance, touching
   nothing else, atomically. Post-import results go through the catalog via the plugin.
5. **Geo in the daemon is disk-cache-only**; `POST /prefetch` is the explicit online path
   (same code as `wildid prefetch` for geo lists + GBIF synonyms) and invalidates the
   in-memory plan cache.
6. **Distribution: per-user online installer** (Inno Setup) bundling `uv` + the locked
   project + the plugin; `uv sync --frozen` resolves the environment on the target machine,
   the plugin lands in Lightroom's auto-load `Modules` folder, and `wildid setup` is the
   first-run wizard. **Private-first and unsigned**; signing, licensing review and public
   channels are parked as phase P in the plan.
   *Amended 2026-11-15 (owner):* the repository is public since this day (ADR 0007). The
   installers are still unsigned; signing and channels remain phase P.
   *Amended 2026-11-15 (owner):* **Python always comes from uv, never from the machine, on
   every system.** Left to its default, uv builds the environment on a Python 3.14 it finds
   on the machine and downloads its own only when there is none; the first macOS CI run
   showed it (ADR 0008). `python-preference = "only-managed"` in `pyproject.toml` now rules
   that out in a checkout, in CI and in an installed copy alike: both installers ship that
   file, and every uv call of their scripts names the project. Checked on macOS and in CI
   on Linux and macOS; on Windows it is the same uv setting, not yet seen on a PC that has
   its own Python 3.14 (`docs/acceptance-lightroom.md`, section D).

## Consequences

- `cli.py` is a renderer over `pipeline.py`; text output is byte-identical to pre-0.2.0
  (snapshot-tested) and the CLI contract only gained flags (`--format`, `--output`,
  `--min-score`, `--keyword-root`, `--write-xmp`, `--xmp-mode`, `--dry-run`) and commands
  (`serve`, `setup`).
- The Lua side (`lrplugin/wildid.lrplugin`) carries its own minimal JSON codec (verified under
  Lua 5.1/LuaJIT) and is integration-tested against the real daemon outside Lightroom; the
  in-Lightroom pass on Windows is the remaining acceptance step, as is compiling the installer.
- Lightroom SDK rule learned in acceptance (LrC 15.4.1): an object created inside a
  `withWriteAccessDo` call is unusable until that call has returned — it cannot be attached
  to photos (the catalog asserts "packed" at commit), cannot be queried (`getName`,
  `isSmartCollection`, `getPhotos`, …: "can't get collection information after creating
  collection inside the same withWriteAccessDo function") and cannot parent a set or
  collection created in the same call. The plugin therefore writes each chunk in up to six
  transactions — create keywords, attach keywords, create class sets, create genus sets,
  create collections, file photos — caches what it needs to know about collections when it
  indexes the set (outside any transaction), and creates a multi-level set path one level per
  transaction. The collections test's fake catalog enforces all three rules.
- Changing keyword policy, score semantics or the schema means: update `keywords.py` /
  `results.py`, bump `protocol` on breaking changes, and ship plugin + engine together.
- "Mark as reviewed" (plugin 0.3.1+) removes the review markers on the user's explicit
  action: `_review` membership, the `<root>|review` keyword and the status (`review` →
  `reviewed`). A run itself (since 2026-10-28) takes stale keywords under the root off a
  re-run photo and moves it between collections; it never touches anything outside the root.
  The engine's keyword policy stays in `keywords.py`; the next run re-flags what it still
  doubts.
- Per-photo geo (0.3.0, ADR 0006) kept the split: the engine resolves positions and groups the
  run; the plugin only forwards catalog GPS (`gps` map) and renders `place`. The additions to
  the result document (`place`, `candidates.auto_level`, `candidates.auto_places`) are
  additive, so `protocol` stayed 1.
