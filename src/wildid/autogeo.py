"""Per-photo geo filtering: run the pipeline once per place group (plan B3).

The classifier holds one filter at a time (apply_filter mutates it), so auto-geo partitions
the photos by resolved place, applies that place's species list, runs the pipeline on the
group, and moves on. Shared by the CLI (`--geo-auto`) and the daemon (`geo: {auto: true}`).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from wildid.constants import DEFAULT_TAXA
from wildid.geo import GeoCache, GeoError, INatClient, build_filter, parse_taxa, species_list
from wildid.gps import DEFAULT_GPS_LEVEL, Coords, GpsGroup, group_by_place, scan_gps
from wildid.output import CandidateInfo
from wildid.pipeline import FileResult, Stages, iter_results, run_single
from wildid.synonyms import canonical_map, resolve_names

log = logging.getLogger(__name__)

PREFETCH_HINT = "run `wildid prefetch --gps-from <folder>` while online"


@dataclass
class AutoGeoSettings:
    level: str = DEFAULT_GPS_LEVEL
    taxa: str = ",".join(DEFAULT_TAXA)
    rank: str = "species"
    offline: bool = True  # classify never fetches (ADR 0006): CLI and daemon are cache-only
    client: INatClient | None = None


def plan_groups(
    paths: Sequence[Path],
    settings: AutoGeoSettings,
    *,
    cache: GeoCache,
    gps_override: Mapping[Path, Coords | None] | None = None,
) -> list[GpsGroup]:
    """Resolve each photo's place. `gps_override` (the plugin's catalog GPS) wins over EXIF;
    paths missing from it fall back to reading the file."""
    gps: dict[Path, Coords | None] = {}
    for path in paths:
        if gps_override is not None and path in gps_override:
            gps[path] = gps_override[path]
    remaining = [p for p in paths if p not in gps]
    if remaining:
        gps.update(scan_gps(remaining))
    ordered = {p: gps[p] for p in paths}
    return group_by_place(
        ordered, settings.level, cache=cache, client=settings.client, offline=settings.offline
    )


def apply_group_filter(
    clf, group: GpsGroup, settings: AutoGeoSettings, *, cache: GeoCache
) -> tuple[CandidateInfo | None, str | None, bool]:
    """Put the group's species list on the classifier (or clear it). Returns
    (candidates, note, actionable): candidates is None when the group runs unconstrained."""
    clf.clear_filter()
    clf.place_label = None
    if group.resolved is None:
        return None, group.note, group.actionable
    try:
        geo_list = species_list(
            group.resolved,
            parse_taxa(settings.taxa),
            client=settings.client,
            cache=cache,
            offline=settings.offline,
        )
        synonyms, _ = resolve_names(geo_list.species, cache=cache, offline=True)
        clf.synonyms = canonical_map(cache)
        result = build_filter(clf, geo_list, rank=settings.rank, synonyms=synonyms)
    except GeoError as exc:
        clf.clear_filter()
        clf.place_label = None
        log.warning("%s: %s; classifying unconstrained", group.resolved.label, exc)
        return None, f"{group.resolved.label}: {exc}", exc.needs_prefetch
    return (
        CandidateInfo(
            count=result.species_count,
            place_label=geo_list.label,
            taxa=geo_list.taxa,
            fetched=geo_list.fetched_date,
            rank=result.rank,
        ),
        None,
        False,
    )


def annotate(
    results: Sequence[FileResult],
    candidates: CandidateInfo | None,
    note: str | None,
    actionable: bool,
) -> None:
    for fr in results:
        if candidates is not None:
            fr.place_label = candidates.place_label
            fr.place_candidates = candidates.count
        fr.place_note = note
        if actionable and fr.ok:
            fr.review_notes.append(f"{note}; {PREFETCH_HINT}")


def run_groups(
    clf,
    groups: Sequence[GpsGroup],
    settings: AutoGeoSettings,
    *,
    cache: GeoCache,
    top_k: int,
    batch_size: int,
    stages: Stages,
    workers: int | None = None,
    root: Path | None = None,
    single: bool = False,
    on_group: Callable[[GpsGroup, CandidateInfo | None], None] | None = None,
    on_results: Callable[[list[FileResult]], None] | None = None,
    progress: Callable[[int], None] | None = None,
) -> list[FileResult]:
    """Run every group in turn. `on_results` receives each chunk as it completes (the CLI
    renders/streams there); the full list comes back in group order."""
    collected: list[FileResult] = []
    done_before = 0
    for group in groups:
        candidates, note, actionable = apply_group_filter(clf, group, settings, cache=cache)
        if on_group is not None:
            on_group(group, candidates)
        if single and len(group.paths) == 1:
            chunks = [[run_single(clf, group.paths[0], top_k, stages)]]
            if progress is not None:
                progress(done_before + 1)
        else:
            base = done_before

            def group_progress(done: int, base: int = base) -> None:
                if progress is not None:
                    progress(base + done)

            chunks = iter_results(
                clf,
                group.paths,
                top_k,
                batch_size,
                stages,
                workers,
                root=root,
                progress=group_progress,
            )
        for chunk in chunks:
            annotate(chunk, candidates, note, actionable)
            collected.extend(chunk)
            if on_results is not None:
                on_results(chunk)
        done_before += len(group.paths)
    clf.clear_filter()
    clf.place_label = None
    return collected


def auto_candidates(groups: Sequence[GpsGroup], level: str) -> CandidateInfo:
    """The header's candidate description for an auto-geo run."""
    places = {g.resolved.place.id for g in groups if g.resolved is not None}
    return CandidateInfo(count=0, auto_level=level, auto_places=len(places))
