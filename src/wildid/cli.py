"""wildid command line.

    wildid PATH [options]        classify a file or directory; never downloads models
    wildid prefetch [options]    download model + embeddings (+ geo lists, detector, SpeciesNet);
                                 the only online command

Heavy imports (torch, open_clip, pybioclip, ultralytics) happen inside the commands, after the
process environment is prepared (HF offline mode for classify).
"""

from __future__ import annotations

import json
import logging
import time
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
import typer.core
from rich.console import Console
from rich.logging import RichHandler
from typer._click.exceptions import ClickException  # typer vendors click; these are what it raises

from wildid import __version__
from wildid.constants import (
    CONTINENTS,
    DEFAULT_BATCH_SIZE,
    DEFAULT_EXTENSIONS,
    DEFAULT_MIN_SCORE,
    DEFAULT_MODEL,
    DEFAULT_PRECISION,
    DEFAULT_TAXA,
    KEYWORD_ROOT,
    TOP_K_DIRECTORY,
    TOP_K_FILE,
)
from wildid.env import force_utf8_stdio, prepare_runtime_env
from wildid.output import SCORE_NOTE, CandidateInfo, block, failures, header, place_line
from wildid.pipeline import FileResult, StageError, Stages

EXIT_OK = 0
EXIT_USAGE = 1  # usage / geo resolution error (incl. missing geo cache when offline)
EXIT_MODEL = 2  # model load failure (incl. missing model cache)
EXIT_ALL_FAILED = 3  # every image failed to load

CLASSIFY = "classify"
GROUP_LEVEL_FLAGS = frozenset({"-h", "--help", "--version"})

err = Console(stderr=True, highlight=False, soft_wrap=True)
log = logging.getLogger("wildid")


class ModelName(StrEnum):
    bioclip_25 = "bioclip-2.5"
    bioclip_2 = "bioclip-2"


class PrefetchModel(StrEnum):
    bioclip_25 = "bioclip-2.5"
    bioclip_2 = "bioclip-2"
    all = "all"


class Device(StrEnum):
    auto = "auto"
    cuda = "cuda"
    mps = "mps"
    cpu = "cpu"


class DetectorName(StrEnum):
    mdv6_yolov9_c = "mdv6-yolov9-c"
    mdv6_yolov9_e = "mdv6-yolov9-e"


class Precision(StrEnum):
    auto = "auto"
    fp32 = "fp32"
    tf32 = "tf32"
    fp16 = "fp16"


class GeoRank(StrEnum):
    species = "species"
    genus = "genus"


class GpsLevel(StrEnum):
    country = "country"
    region = "region"


class OutputFormat(StrEnum):
    text = "text"
    json = "json"


class XmpMode(StrEnum):
    new_only = "new-only"
    merge = "merge"


DEFAULT_MODEL_CHOICE = ModelName(DEFAULT_MODEL)
DEFAULT_PREFETCH_CHOICE = PrefetchModel(DEFAULT_MODEL)
DEFAULT_PRECISION_CHOICE = Precision(DEFAULT_PRECISION)


class DefaultGroup(typer.core.TyperGroup):
    """`wildid PATH ...` is shorthand for `wildid classify PATH ...`."""

    def parse_args(self, ctx, args: list[str]) -> list[str]:
        if args and args[0] not in self.commands and args[0] not in GROUP_LEVEL_FLAGS:
            args = [CLASSIFY, *args]
        return super().parse_args(ctx, args)


APP_HELP = (
    "Species ID for wildlife photos: BioCLIP + TreeOfLife on a local GPU, offline-first.\n\n"
    "[b]wildid PATH \\[options][/b] classifies a file or a directory (same as "
    "[b]wildid classify PATH[/b]). It never downloads: the model loads from the local cache and "
    "geo species lists are cache-first.\n\n"
    "[b]wildid prefetch[/b] downloads the model, the TreeOfLife embeddings, geo lists and the "
    "optional detector / SpeciesNet weights. It is the only online command; run it before "
    "every trip.\n\n"
    f"Note: {SCORE_NOTE}."
)

app = typer.Typer(
    cls=DefaultGroup,
    help=APP_HELP,
    rich_markup_mode="rich",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)


def _version_callback(value: bool) -> None:
    if value:
        print(f"wildid {__version__}")
        raise typer.Exit()


@app.callback()
def _root(
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    pass


def _setup_logging(verbose: bool) -> None:
    handler = RichHandler(
        console=err, show_time=False, show_path=False, markup=False, rich_tracebacks=False
    )
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(message)s",
        handlers=[handler],
        force=True,
    )
    logging.getLogger("wildid").setLevel(logging.DEBUG if verbose else logging.INFO)


def _fail(message: str, code: int) -> typer.Exit:
    err.print(f"[bold red]error:[/bold red] {message}")
    return typer.Exit(code)


def _prefetch_hint(model: str) -> str:
    return f"run `wildid prefetch --model {model}` while online, then retry"


# ----------------------------------------------------------------------------------------------
# optional stages: detector crop (post-MVP 1) and SpeciesNet second opinion (post-MVP 4)
# ----------------------------------------------------------------------------------------------


def _load_stages(
    crop: bool, detector_name: str, second_opinion: bool, device: str, crop_exact: bool = False
) -> Stages:
    from wildid.pipeline import load_stages

    try:
        return load_stages(crop, detector_name, second_opinion, device, crop_exact=crop_exact)
    except StageError as exc:
        raise _fail(str(exc), EXIT_MODEL) from exc


# ----------------------------------------------------------------------------------------------
# classify
# ----------------------------------------------------------------------------------------------

CLASSIFY_HELP = (
    f"Classify an image file (top {TOP_K_FILE}) or a directory of images "
    f"(top {TOP_K_DIRECTORY} per file, recursive).\n\n"
    "Runs fully offline: the model loads from the local Hugging Face cache (exit 2 with a "
    "prefetch hint when it is missing). Results are text blocks on stdout; progress and "
    "warnings go to stderr.\n\n"
    f"Note: {SCORE_NOTE}."
)

GEO_PANEL = "Geo (optional; precedence region > country > continent)"
RUNTIME_PANEL = "Model / runtime"
STAGES_PANEL = "Optional stages"
OUTPUT_PANEL = "Output"
TAXA_HELP = (
    "Taxonomic classes for the geo list, comma-separated "
    "(mammals, reptiles, amphibians, birds by default)."
)


@app.command(name=CLASSIFY, help=CLASSIFY_HELP)
def classify(
    path: Annotated[
        Path, typer.Argument(metavar="PATH", help="Image file, or directory walked recursively.")
    ],
    continent: Annotated[
        str | None,
        typer.Option(help=" | ".join(CONTINENTS), rich_help_panel=GEO_PANEL),
    ] = None,
    country: Annotated[
        str | None,
        typer.Option(
            help='Country name (iNaturalist place, admin level 0), e.g. "Brazil".',
            rich_help_panel=GEO_PANEL,
        ),
    ] = None,
    region: Annotated[
        str | None,
        typer.Option(
            help='Region within --country (state/province/county), e.g. "Mato Grosso". '
            "Requires --country.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = None,
    place_id: Annotated[
        int | None,
        typer.Option(
            "--place-id",
            help="Escape hatch: use this iNaturalist place id directly, skip name resolution.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = None,
    taxa: Annotated[str, typer.Option(help=TAXA_HELP, rich_help_panel=GEO_PANEL)] = ",".join(
        DEFAULT_TAXA
    ),
    refresh_geo: Annotated[
        bool,
        typer.Option(
            "--refresh-geo",
            help="Ignore the cache and refetch the species list.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = False,
    geo_rank: Annotated[
        GeoRank,
        typer.Option(
            "--geo-rank",
            help="species = exactly the regional list; genus = every model species of the "
            "genera on the list, for places with thin iNaturalist coverage.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = GeoRank.species,
    geo_auto: Annotated[
        bool,
        typer.Option(
            "--geo-auto",
            help="Per-photo place filter from each file's EXIF GPS (the country or region "
            "containing it). Cache-only, like the daemon: resolve the cells first with "
            "`wildid prefetch --gps-from <folder>`; a photo in a cell not prefetched runs "
            "unfiltered and is flagged for review. Not combinable with an explicit place.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = False,
    geo_level: Annotated[
        GpsLevel,
        typer.Option(
            "--geo-level",
            help="Admin level for --geo-auto: country (default, fuller lists) or region "
            "(state/province, tighter).",
            rich_help_panel=GEO_PANEL,
        ),
    ] = GpsLevel.country,
    model: Annotated[
        ModelName,
        typer.Option(
            help="Classifier. bioclip-2.5 is larger and slower, and its TreeOfLife "
            "embeddings have no reptiles.",
            rich_help_panel=RUNTIME_PANEL,
        ),
    ] = DEFAULT_MODEL_CHOICE,
    device: Annotated[
        Device,
        typer.Option(
            help="auto = cuda if available, else mps (Apple Silicon), else cpu with a warning.",
            rich_help_panel=RUNTIME_PANEL,
        ),
    ] = Device.auto,
    batch_size: Annotated[
        int, typer.Option(min=1, help="Images per model batch.", rich_help_panel=RUNTIME_PANEL)
    ] = DEFAULT_BATCH_SIZE,
    workers: Annotated[
        int | None,
        typer.Option(
            min=1,
            help="Loader threads (decode + resize). Default: CPU count, at most 8.",
            rich_help_panel=RUNTIME_PANEL,
        ),
    ] = None,
    precision: Annotated[
        Precision,
        typer.Option(
            help="auto = tf32 on CUDA (identical results in tests, faster), fp32 on mps and "
            "cpu; fp32; fp16 = autocast on CUDA or mps, fastest, may change about 0.5 % of "
            "top-1 answers (about 1 % on mps). tf32 is a CUDA mode; the cpu always runs fp32.",
            rich_help_panel=RUNTIME_PANEL,
        ),
    ] = DEFAULT_PRECISION_CHOICE,
    anomaly_check: Annotated[
        bool,
        typer.Option(
            "--anomaly-check",
            help="With a geo filter, also run the unconstrained pass and flag disagreement "
            "(always on for a single file).",
            rich_help_panel=RUNTIME_PANEL,
        ),
    ] = False,
    offline: Annotated[
        bool,
        typer.Option(
            "--offline",
            help="Forbid every network call; exit 1 with a prefetch hint if a cache is missing.",
            rich_help_panel=RUNTIME_PANEL,
        ),
    ] = False,
    crop: Annotated[
        bool,
        typer.Option(
            "--crop",
            help="Find the animal first (MegaDetector) and classify the crop; the biggest "
            "accuracy lever for distant frames. Needs `wildid prefetch --crop`.",
            rich_help_panel=STAGES_PANEL,
        ),
    ] = False,
    detector: Annotated[
        DetectorName,
        typer.Option(
            help="Detector for --crop: mdv6-yolov9-c (640 px, fast) or mdv6-yolov9-e "
            "(1280 px, better on small animals).",
            rich_help_panel=STAGES_PANEL,
        ),
    ] = DetectorName.mdv6_yolov9_c,
    crop_exact: Annotated[
        bool,
        typer.Option(
            "--crop-exact",
            help="With --crop: resize the photo for the detector with OpenCV's exact method, "
            "which gives the same pixels on a Mac and a PC. By default the platform's OpenCV "
            "resizes, and a Mac and a PC then name about 2 % of the cropped photos differently; "
            "with this, about 0.2 %, and none when the PC runs --precision fp32. About 2 % of "
            "the answers change against a run without it.",
            rich_help_panel=STAGES_PANEL,
        ),
    ] = False,
    second_opinion: Annotated[
        bool,
        typer.Option(
            "--second-opinion",
            help="Also classify the crop with SpeciesNet (camera-trap model, strongest on "
            "mammals) and flag disagreement. Implies --crop. Needs "
            "`wildid prefetch --second-opinion`.",
            rich_help_panel=STAGES_PANEL,
        ),
    ] = False,
    k: Annotated[
        int | None,
        typer.Option(
            "--k",
            min=1,
            help=f"Top-k override (default {TOP_K_FILE} for a file, "
            f"{TOP_K_DIRECTORY} per file in a directory).",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = None,
    ext: Annotated[
        str,
        typer.Option(help="Extensions to include, comma-separated.", rich_help_panel=OUTPUT_PANEL),
    ] = ",".join(DEFAULT_EXTENSIONS),
    format_: Annotated[
        OutputFormat,
        typer.Option(
            "--format",
            help="text = human-readable blocks on stdout (default); json = one "
            "machine-readable document with suggested keywords per photo.",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = OutputFormat.text,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            help="Write the --format json document to this file instead of stdout.",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = None,
    min_score: Annotated[
        float,
        typer.Option(
            "--min-score",
            min=0.0,
            max=1.0,
            help="Top-1 score below which a photo is flagged for review in JSON and XMP "
            "keyword output (a softmax over the candidate set: a heuristic, not a "
            "probability).",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = DEFAULT_MIN_SCORE,
    keyword_root: Annotated[
        str,
        typer.Option(
            "--keyword-root",
            help="Root of the suggested keyword hierarchy in JSON and XMP output.",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = KEYWORD_ROOT,
    write_xmp: Annotated[
        bool,
        typer.Option(
            "--write-xmp",
            help="Write keyword XMP sidecars next to RAW files, for Lightroom to read at "
            "import. Pre-import only: external XMP edits to already-imported photos fork "
            "Lightroom's catalog state (use the plugin after import). JPEG and DNG embed "
            "XMP and are never modified.",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = False,
    xmp_mode: Annotated[
        XmpMode,
        typer.Option(
            "--xmp-mode",
            help="new-only = skip files that already have a sidecar (safe default); "
            "merge = append keyword entries to existing sidecars, touching nothing else.",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = XmpMode.new_only,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            help="With --write-xmp: classify and report what would be written, write nothing.",
            rich_help_panel=OUTPUT_PANEL,
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "-v", "--verbose", help="Debug logging on stderr.", rich_help_panel=OUTPUT_PANEL
        ),
    ] = False,
) -> None:
    _setup_logging(verbose)
    t_start = time.perf_counter()
    as_text = format_ is OutputFormat.text
    if output is not None and as_text:
        raise _fail("--output requires --format json", EXIT_USAGE)
    if not keyword_root.strip():
        raise _fail("--keyword-root must not be empty", EXIT_USAGE)
    if dry_run and not write_xmp:
        raise _fail("--dry-run only applies to --write-xmp", EXIT_USAGE)
    if crop_exact and not (crop or second_opinion):
        raise _fail(
            "--crop-exact needs --crop (or --second-opinion, which implies it)", EXIT_USAGE
        )
    if geo_auto and any(v is not None for v in (continent, country, region, place_id)):
        raise _fail(
            "--geo-auto cannot be combined with --continent/--country/--region/--place-id",
            EXIT_USAGE,
        )
    from wildid.images import discover, normalise_extensions

    extensions = normalise_extensions(ext)
    if not extensions:
        raise _fail("--ext must name at least one extension", EXIT_USAGE)
    try:
        paths = discover(path, extensions)
    except FileNotFoundError as exc:
        raise _fail(str(exc), EXIT_USAGE) from exc
    single = path.is_file()
    if single and path.suffix.lower().lstrip(".") not in extensions:
        raise _fail(
            f"{path.name}: extension not in --ext ({','.join(sorted(extensions))})", EXIT_USAGE
        )
    if not paths:
        raise _fail(
            f"no images with extensions {','.join(sorted(extensions))} under {path}", EXIT_USAGE
        )
    top_k = k or (TOP_K_FILE if single else TOP_K_DIRECTORY)
    log.info("%d image(s) under %s", len(paths), path)

    # --- geo list: resolved before the model loads (fast, and fails fast) --------------------
    geo_list = None
    if any(v is not None for v in (continent, country, region, place_id)):
        from wildid.geo import (
            GeoCache,
            GeoError,
            INatClient,
            parse_taxa,
            resolve_place,
            species_list,
        )

        prefetch_cmd = geo_prefetch_command(continent, country, region, place_id, taxa)
        try:
            taxa_tuple = parse_taxa(taxa)
            cache = GeoCache()
            client = None if offline else INatClient()
            resolved = resolve_place(
                continent=continent,
                country=country,
                region=region,
                place_id=place_id,
                client=client,
                cache=cache,
                offline=offline,
            )
            geo_list = species_list(
                resolved,
                taxa_tuple,
                client=client,
                cache=cache,
                refresh=refresh_geo,
                offline=offline,
            )
        except GeoError as exc:
            hint = f"; run `{prefetch_cmd}` while online" if exc.needs_prefetch else ""
            raise _fail(f"{exc}{hint}", EXIT_USAGE) from exc

    # --- auto-geo: GPS -> place per photo, resolved (cache-first) before the model loads -----
    auto_groups = None
    auto_settings = None
    auto_cache = None
    if geo_auto:
        from wildid.autogeo import AutoGeoSettings, plan_groups
        from wildid.geo import GeoCache, GeoError, parse_taxa
        from wildid.gps import NO_GPS

        try:
            parse_taxa(taxa)
        except GeoError as exc:
            raise _fail(str(exc), EXIT_USAGE) from exc
        auto_cache = GeoCache()
        # Cache-only whether or not --offline was given (ADR 0006): a trip spans many cells,
        # and resolving them here would stall per cell without network, degrade quietly and
        # skip the GBIF synonyms prefetch adds. `wildid prefetch --gps-from` is the online path.
        auto_settings = AutoGeoSettings(
            level=geo_level.value,
            taxa=taxa,
            rank=geo_rank.value,
            offline=True,
            client=None,
        )
        auto_groups = plan_groups(paths, auto_settings, cache=auto_cache)
        with_gps = sum(len(g.paths) for g in auto_groups if g.key != NO_GPS)
        if with_gps == 0:
            raise _fail(f"--geo-auto: none of the {len(paths)} file(s) carries GPS", EXIT_USAGE)
        for g in auto_groups:
            log.info(
                "GPS group %s: %d file(s)%s",
                g.resolved.label if g.resolved else g.key,
                len(g.paths),
                f" ({g.note})" if g.note else "",
            )

    # --- model: offline mode must be set before torch / huggingface_hub are imported ---------
    prepare_runtime_env(allow_model_download=False)
    from wildid.model import ModelLoadError, load_classifier

    try:
        clf = load_classifier(model.value, device.value)
        effective_precision = clf.apply_precision(precision.value)
    except ModelLoadError as exc:
        hint = f"; {_prefetch_hint(model.value)}" if exc.missing_cache else ""
        raise _fail(f"{exc}{hint}", EXIT_MODEL) from exc

    stages = _load_stages(crop, detector.value, second_opinion, clf.device, crop_exact)
    if stages.crop_exact:
        log.info("crop: exact resize for the detector (OpenCV INTER_LINEAR_EXACT)")

    if geo_list is not None:
        from wildid.geo import GeoError, build_filter
        from wildid.synonyms import canonical_map, resolve_names

        # GBIF synonym lookups happen in prefetch only; here the cache is read, never the network.
        synonyms, _ = resolve_names(geo_list.species, cache=cache, offline=True)
        clf.synonyms = canonical_map(cache)
        try:
            result = build_filter(clf, geo_list, rank=geo_rank.value, synonyms=synonyms)
        except GeoError as exc:
            raise _fail(str(exc), EXIT_USAGE) from exc
        not_looked_up = sum(1 for name in result.unmatched if name not in synonyms)
        if not_looked_up:
            log.info(
                "%d unmatched names have no GBIF lookup yet; `%s` resolves synonyms while online",
                not_looked_up,
                prefetch_cmd,
            )
        clf.anomaly_check = anomaly_check
        candidates = CandidateInfo(
            count=result.species_count,
            place_label=geo_list.label,
            taxa=geo_list.taxa,
            fetched=geo_list.fetched_date,
            rank=result.rank,
        )
    elif auto_groups is not None:
        from wildid.autogeo import auto_candidates

        clf.anomaly_check = anomaly_check
        candidates = auto_candidates(auto_groups, geo_level.value)
    else:
        candidates = CandidateInfo(count=clf.candidate_count)
    sidecars = None
    if write_xmp:
        from wildid.xmp import SidecarWriter

        sidecars = SidecarWriter(
            mode=xmp_mode.value,
            dry_run=dry_run,
            keyword_root=keyword_root,
            min_score=min_score,
            model=clf.spec.name,
            place_label=clf.place_label,
        )
    if as_text:
        print(
            header(clf.spec.name, clf.device, candidates, precision=effective_precision),
            flush=True,
        )

    if auto_groups is not None:
        code, collected = _run_auto(
            clf,
            path,
            paths,
            auto_groups,
            auto_settings,
            auto_cache,
            top_k,
            batch_size,
            stages,
            workers,
            text=as_text,
            sidecars=sidecars,
            single=single,
        )
    elif single:
        code, collected = _run_single(clf, path, top_k, stages, text=as_text, sidecars=sidecars)
    else:
        code, collected = _run_directory(
            clf, path, paths, top_k, batch_size, stages, workers, text=as_text, sidecars=sidecars
        )
    if sidecars is not None:
        err.print(sidecars.summary())
    if not as_text:
        from wildid.results import run_document

        doc = run_document(
            model=clf.spec.name,
            device=clf.device,
            precision=effective_precision,
            candidates=candidates,
            results=collected,
            keyword_root=keyword_root,
            min_score=min_score,
            crop_resize=stages.crop_resize,
        )
        payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(payload, encoding="utf-8")
            log.info("wrote %s (%d results)", output, len(collected))
        else:
            print(payload, end="", flush=True)
    log.debug("done in %.1f s", time.perf_counter() - t_start)
    raise typer.Exit(code)


def _render_block(fr: FileResult, place_label: str | None) -> str:
    return block(
        fr.label,
        fr.predictions,
        unconstrained=fr.unconstrained,
        in_candidates=fr.in_candidates,
        place_label=place_label,
        crop_line=fr.crop.line if fr.crop else None,
        opinion_line=fr.opinion.line if fr.opinion else None,
        place_line=place_line(fr.place_label, fr.place_candidates, fr.place_note),
    )


def _run_single(
    clf, path: Path, top_k: int, stages: Stages, *, text: bool = True, sidecars=None
) -> tuple[int, list[FileResult]]:
    from wildid.pipeline import run_single

    fr = run_single(clf, path, top_k, stages)
    if not fr.ok:
        err.print(f"[bold red]error:[/bold red] {path.name}: {fr.error}")
        return EXIT_ALL_FAILED, [fr]
    if sidecars is not None:
        sidecars.process(fr)
    if text:
        print(_render_block(fr, clf.place_label), flush=True)
    return EXIT_OK, [fr]


def _run_directory(
    clf,
    root: Path,
    paths: list[Path],
    top_k: int,
    batch_size: int,
    stages: Stages,
    workers: int | None = None,
    *,
    text: bool = True,
    sidecars=None,
) -> tuple[int, list[FileResult]]:
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    from wildid.pipeline import iter_results

    failed: list[tuple[str, str]] = []
    collected: list[FileResult] = []
    n_ok = 0
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=err,
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
    )
    t0 = time.perf_counter()
    with progress:
        task = progress.add_task("classifying", total=len(paths))
        for chunk in iter_results(
            clf,
            paths,
            top_k,
            batch_size,
            stages,
            workers,
            root=root,
            progress=lambda done: progress.update(task, completed=done),
        ):
            collected.extend(chunk)
            blocks = []
            for fr in chunk:
                if not fr.ok:
                    failed.append((fr.label, fr.error or "unknown error"))
                    continue
                n_ok += 1
                if sidecars is not None:
                    sidecars.process(fr)
                if text:
                    blocks.append(_render_block(fr, clf.place_label))
            if blocks:
                progress.stop()  # keep the live bar from interleaving with stdout on a terminal
                print("\n".join(blocks), flush=True)
                progress.start()
    elapsed = time.perf_counter() - t0
    log.info(
        "%d classified, %d failed, %.1f s (%.1f img/s)",
        n_ok,
        len(failed),
        elapsed,
        n_ok / elapsed if elapsed > 0 else 0.0,
    )
    if failed:
        err.print(failures(failed))
    return (EXIT_ALL_FAILED if n_ok == 0 else EXIT_OK), collected


def _run_auto(
    clf,
    root: Path,
    paths: list[Path],
    groups,
    settings,
    cache,
    top_k: int,
    batch_size: int,
    stages: Stages,
    workers: int | None = None,
    *,
    text: bool = True,
    sidecars=None,
    single: bool = False,
) -> tuple[int, list[FileResult]]:
    """--geo-auto: the pipeline runs once per place group; blocks stream out per group."""
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        TextColumn,
        TimeElapsedColumn,
        TimeRemainingColumn,
    )

    from wildid.autogeo import PREFETCH_HINT, run_groups

    failed: list[tuple[str, str]] = []
    n_ok = 0
    progress = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=err,
        transient=True,
        redirect_stdout=False,
        redirect_stderr=False,
    )

    def on_results(chunk: list[FileResult]) -> None:
        nonlocal n_ok
        blocks = []
        for fr in chunk:
            if not fr.ok:
                failed.append((fr.label, fr.error or "unknown error"))
                continue
            n_ok += 1
            if sidecars is not None:
                sidecars.process(fr)
            if text:
                blocks.append(_render_block(fr, fr.place_label))
        if blocks:
            progress.stop()
            print("\n".join(blocks), flush=True)
            progress.start()

    t0 = time.perf_counter()
    with progress:
        task = progress.add_task("classifying", total=len(paths))
        collected = run_groups(
            clf,
            groups,
            settings,
            cache=cache,
            top_k=top_k,
            batch_size=batch_size,
            stages=stages,
            workers=workers,
            root=None if single else root,
            single=single,
            on_results=on_results,
            progress=lambda done: progress.update(task, completed=done),
        )
    elapsed = time.perf_counter() - t0
    log.info(
        "%d classified, %d failed, %.1f s (%.1f img/s), %d place group(s)",
        n_ok,
        len(failed),
        elapsed,
        n_ok / elapsed if elapsed > 0 else 0.0,
        len(groups),
    )
    unprefetched = sum(
        1 for fr in collected if fr.ok and any(PREFETCH_HINT in n for n in fr.review_notes)
    )
    if unprefetched:
        log.warning(
            "geo-auto: %d photo(s) in cell(s) nobody prefetched ran unfiltered and are flagged "
            "for review; run `wildid prefetch --gps-from %s` while online",
            unprefetched,
            _quote(str(root)),
        )
    if single and failed:
        err.print(f"[bold red]error:[/bold red] {failed[0][0]}: {failed[0][1]}")
    elif failed:
        err.print(failures(failed))
    return (EXIT_ALL_FAILED if n_ok == 0 else EXIT_OK), collected


def _quote(value: str) -> str:
    return f'"{value}"' if any(ch in value for ch in " \t\"'") else value


def geo_prefetch_command(
    continent: str | None,
    country: str | None,
    region: str | None,
    place_id: int | None,
    taxa: str,
) -> str:
    """The exact `wildid prefetch ...` call that would populate the geo cache for these args."""
    parts = ["wildid prefetch"]
    if place_id is not None:
        parts.append(f"--place-id {place_id}")
    if country:
        parts.append(f"--country {_quote(country)}")
    if region:
        parts.append(f"--region {_quote(region)}")
    if continent:
        parts.append(f"--continent {_quote(continent)}")
    if taxa and taxa != ",".join(DEFAULT_TAXA):
        parts.append(f"--taxa {_quote(taxa)}")
    return " ".join(parts)


# ----------------------------------------------------------------------------------------------
# prefetch
# ----------------------------------------------------------------------------------------------

PREFETCH_HELP = (
    "Download the model weights and TreeOfLife text embeddings into the local Hugging Face "
    "cache, geo species lists into the wildid cache, and with --crop / --second-opinion the "
    "MegaDetector and SpeciesNet weights.\n\n"
    "This is the only wildid command that downloads anything. It is idempotent: run it before "
    "every trip. With --verify (default) it then runs the real offline classify path once in a "
    "child process, so a pass here means [b]wildid --offline[/b] will start without the network."
)


@app.command(help=PREFETCH_HELP)
def prefetch(
    model: Annotated[
        PrefetchModel, typer.Option(help="Which model(s) to download.")
    ] = DEFAULT_PREFETCH_CHOICE,
    continent: Annotated[
        list[str] | None,
        typer.Option(
            help="Continent to fetch species lists for (repeatable).", rich_help_panel=GEO_PANEL
        ),
    ] = None,
    country: Annotated[
        list[str] | None,
        typer.Option(help="Country (repeatable).", rich_help_panel=GEO_PANEL),
    ] = None,
    region: Annotated[
        list[str] | None,
        typer.Option(
            help='Region inside the --country at the same position (repeatable; pass "" '
            "for a country without one).",
            rich_help_panel=GEO_PANEL,
        ),
    ] = None,
    place_id: Annotated[
        list[int] | None,
        typer.Option(
            "--place-id", help="iNaturalist place id (repeatable).", rich_help_panel=GEO_PANEL
        ),
    ] = None,
    taxa: Annotated[str, typer.Option(help=TAXA_HELP, rich_help_panel=GEO_PANEL)] = ",".join(
        DEFAULT_TAXA
    ),
    gps_from: Annotated[
        Path | None,
        typer.Option(
            "--gps-from",
            help="Folder (or file) whose EXIF GPS positions are resolved to places and their "
            "species lists fetched, for `wildid PATH --geo-auto`.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = None,
    geo_level: Annotated[
        GpsLevel,
        typer.Option(
            "--geo-level",
            help="Admin level for --gps-from: country (default) or region.",
            rich_help_panel=GEO_PANEL,
        ),
    ] = GpsLevel.country,
    refresh_geo: Annotated[
        bool,
        typer.Option("--refresh-geo", help="Refetch species lists even if cached and fresh."),
    ] = False,
    crop: Annotated[
        bool,
        typer.Option(
            "--crop", help="Also fetch the MegaDetector weights.", rich_help_panel=STAGES_PANEL
        ),
    ] = False,
    detector: Annotated[
        DetectorName,
        typer.Option(help="Which detector to fetch for --crop.", rich_help_panel=STAGES_PANEL),
    ] = DetectorName.mdv6_yolov9_c,
    second_opinion: Annotated[
        bool,
        typer.Option(
            "--second-opinion",
            help="Also fetch SpeciesNet (and the detector it needs).",
            rich_help_panel=STAGES_PANEL,
        ),
    ] = False,
    device: Annotated[Device, typer.Option(help="Device for the --verify run.")] = Device.auto,
    verify: Annotated[
        bool,
        typer.Option("--verify/--no-verify", help="Prove the cache works offline afterwards."),
    ] = True,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Debug logging on stderr.")
    ] = False,
) -> None:
    _setup_logging(verbose)
    prepare_runtime_env(allow_model_download=True)
    from wildid.prefetch import (
        prefetch_detector,
        prefetch_geo,
        prefetch_gps,
        prefetch_model,
        prefetch_speciesnet,
        prefetch_synonyms,
        verify_offline,
    )

    names = ["bioclip-2", "bioclip-2.5"] if model == PrefetchModel.all else [model.value]
    for name in names:
        try:
            prefetch_model(name)
        except Exception as exc:  # noqa: BLE001 - any download failure is exit 2
            raise _fail(
                f"prefetch of {name} failed: {type(exc).__name__}: {exc}", EXIT_MODEL
            ) from exc

    specs = _geo_specs(continent or [], country or [], region or [], place_id or [])
    if specs:
        from wildid.geo import GeoError

        try:
            geo_lists = prefetch_geo(specs, taxa, refresh=refresh_geo)
            prefetch_synonyms(geo_lists, names)
        except GeoError as exc:
            raise _fail(str(exc), EXIT_USAGE) from exc
    if gps_from is not None:
        from wildid.geo import GeoError
        from wildid.gps import scan_gps
        from wildid.images import discover

        try:
            files = discover(gps_from, DEFAULT_EXTENSIONS)
        except FileNotFoundError as exc:
            raise _fail(str(exc), EXIT_USAGE) from exc
        points = [c for c in scan_gps(files).values() if c is not None]
        if not points:
            raise _fail(
                f"--gps-from: none of the {len(files)} file(s) under {gps_from} carries GPS",
                EXIT_USAGE,
            )
        err.print(f"GPS: {len(points)} of {len(files)} file(s) carry a position")
        try:
            gps_lists = prefetch_gps(points, geo_level.value, taxa, refresh=refresh_geo)
            prefetch_synonyms(gps_lists, names)
        except GeoError as exc:
            raise _fail(str(exc), EXIT_USAGE) from exc
    extra_args: list[str] = []
    if crop or second_opinion:
        try:
            prefetch_detector(detector.value)
        except Exception as exc:  # noqa: BLE001
            raise _fail(f"detector download failed: {exc}", EXIT_MODEL) from exc
        extra_args += ["--crop", "--detector", detector.value]
    if second_opinion:
        try:
            prefetch_speciesnet()
        except Exception as exc:  # noqa: BLE001
            raise _fail(f"SpeciesNet download failed: {exc}", EXIT_MODEL) from exc
        extra_args.append("--second-opinion")
    if verify:
        for name in names:
            if not verify_offline(name, device.value, extra_args):
                raise _fail(f"{name} did not load offline after prefetch", EXIT_MODEL)
    done = (
        names
        + (["detector"] if crop or second_opinion else [])
        + (["speciesnet"] if second_opinion else [])
    )
    err.print(f"[green]prefetch complete:[/green] {', '.join(done)}")


def _geo_specs(
    continents: list[str], countries: list[str], regions: list[str], place_ids: list[int]
) -> list[dict]:
    """Pair each --region with the --country at the same position; continents and ids stand
    alone."""
    if len(regions) > len(countries):
        raise _fail("each --region needs a --country given at the same position", EXIT_USAGE)
    specs: list[dict] = []
    for i, c in enumerate(countries):
        region = regions[i].strip() if i < len(regions) else ""
        specs.append({"country": c, "region": region or None})  # "" keeps the pairing aligned
    specs.extend({"continent": c} for c in continents)
    specs.extend({"place_id": p} for p in place_ids)
    return specs


# ----------------------------------------------------------------------------------------------
# setup (first-run wizard; UI glue around prefetch)
# ----------------------------------------------------------------------------------------------

SETUP_HELP = (
    "First-run wizard: model download (a Hugging Face token is optional), optional "
    "detector/SpeciesNet stages and trip species lists, then an offline verification.\n\n"
    "Interactive; it is the guided version of [b]wildid prefetch[/b] and needs the network."
)

HF_TOKEN_URL = "https://huggingface.co/settings/tokens"


def _existing_hf_token() -> str | None:
    try:
        from huggingface_hub import get_token

        return get_token()
    except Exception:  # noqa: BLE001 - any hub/env hiccup just means "ask the user"
        return None


@app.command(help=SETUP_HELP)
def setup(
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Debug logging on stderr.")
    ] = False,
) -> None:
    import sys

    _setup_logging(verbose)
    if not sys.stdin.isatty():
        raise _fail("wildid setup is interactive; run it in a terminal", EXIT_USAGE)
    prepare_runtime_env(allow_model_download=True)
    err.print("[bold]WildID setup[/bold] — one-time download of the model and data.\n")

    # 1. Hugging Face token: optional. The model and dataset repos are public (checked against
    #    the Hub on 2026-11-04), so anonymous downloads work; a token only lifts the limits the
    #    Hub puts on them.
    if _existing_hf_token():
        err.print("Hugging Face token: already configured.")
    else:
        err.print(
            "Hugging Face token (optional). Every file WildID downloads is public: no account "
            "is needed.\n"
            "  A token only helps if Hugging Face slows down or refuses anonymous downloads; "
            f"a read token\n  can be created at {HF_TOKEN_URL}\n"
            "  Press Enter to continue without one."
        )
        token = typer.prompt(
            "Hugging Face token (Enter to skip)", hide_input=True, default="", show_default=False
        ).strip()
        if token:
            from huggingface_hub import login

            try:
                login(token=token, add_to_git_credential=False)
            except Exception as exc:  # noqa: BLE001 - a bad token must not crash the wizard
                raise _fail(f"the token was not accepted: {exc}", EXIT_USAGE) from exc
            err.print("Token saved.")
        else:
            err.print("No token: downloading anonymously.")

    # 2. what to download
    model_choice = typer.prompt(
        "Model to download (bioclip-2 | bioclip-2.5 | all)", default=DEFAULT_MODEL
    ).strip()
    while model_choice not in {m.value for m in PrefetchModel}:
        model_choice = typer.prompt(
            "Please answer bioclip-2, bioclip-2.5 or all", default=DEFAULT_MODEL
        ).strip()
    crop = typer.confirm(
        "Also fetch the MegaDetector crop stage (recommended for wildlife)?", default=True
    )
    second = typer.confirm("Also fetch SpeciesNet (second opinion, mammals)?", default=False)

    # 3. trip species lists
    countries: list[str] = []
    regions: list[str] = []
    while typer.confirm("Prefetch a species list for a destination?", default=not countries):
        country = typer.prompt("  Country", default="", show_default=False).strip()
        if not country:
            break
        region = typer.prompt(
            "  Region within it (empty = whole country)", default="", show_default=False
        ).strip()
        countries.append(country)
        regions.append(region)

    # 4. download + offline verification (reuses the prefetch command wholesale)
    err.print("\nDownloading — the model alone is gigabytes; this can take a while.\n")
    prefetch(
        model=PrefetchModel(model_choice),
        continent=None,
        country=countries or None,
        region=regions or None,
        place_id=None,
        taxa=",".join(DEFAULT_TAXA),
        refresh_geo=False,
        crop=crop,
        detector=DetectorName.mdv6_yolov9_c,
        second_opinion=second,
        device=Device.auto,
        verify=True,
        verbose=verbose,
    )
    err.print(
        "\n[green]Setup complete.[/green] Next steps:\n"
        "  - Lightroom: select photos → Library → “Identify species with WildID…”\n"
        "  - Before a trip: run `wildid setup` (or `wildid prefetch`) again for the "
        "destination's species list.\n"
        "  - Pre-import keywording without Lightroom: "
        "`wildid <card-folder> --write-xmp --country <X>`"
    )


# ----------------------------------------------------------------------------------------------
# serve
# ----------------------------------------------------------------------------------------------

SERVE_HELP = (
    "Run the local HTTP daemon (for the Lightroom plugin): the model loads once and stays "
    "warm across requests.\n\n"
    "Binds 127.0.0.1 on an OS-assigned port and writes [b]serve.json[/b] (port + access token) "
    "into the wildid cache directory; every request must carry that token. Classification "
    "stays fully offline (geo lists cache-first); only [b]POST /prefetch[/b] fetches geo "
    "species lists. With --idle-exit the process ends after that many quiet seconds, freeing "
    "the GPU until the next start."
)


@app.command(help=SERVE_HELP)
def serve(
    model: Annotated[
        ModelName, typer.Option(help="Classifier to keep loaded.")
    ] = DEFAULT_MODEL_CHOICE,
    device: Annotated[
        Device, typer.Option(help="auto = cuda if available, else mps (Apple Silicon), else cpu.")
    ] = Device.auto,
    precision: Annotated[
        Precision, typer.Option(help="Same semantics as `wildid classify --precision`.")
    ] = DEFAULT_PRECISION_CHOICE,
    port: Annotated[
        int,
        typer.Option(
            min=0,
            max=65535,
            help="0 = OS-assigned (recommended; clients read the port from serve.json).",
        ),
    ] = 0,
    idle_exit: Annotated[
        float,
        typer.Option(
            "--idle-exit",
            min=0,
            help="Exit after this many seconds without a request (frees the GPU); 0 disables.",
        ),
    ] = 900.0,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="Debug logging on stderr.")
    ] = False,
) -> None:
    _setup_logging(verbose)
    prepare_runtime_env(allow_model_download=False)
    from wildid.serve import run_server

    raise typer.Exit(
        run_server(
            model=model.value,
            device=device.value,
            precision=precision.value,
            port=port,
            idle_exit=idle_exit,
        )
    )


# ----------------------------------------------------------------------------------------------
# entry point
# ----------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Console entry point. Maps usage errors to exit 1 (plan §4 exit codes)."""
    force_utf8_stdio()
    try:
        rv = app(args=argv, prog_name="wildid", standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except ClickException as exc:
        try:
            from typer import rich_utils

            rich_utils.rich_format_error(exc)
        except Exception:  # noqa: BLE001 - plain fallback if typer's rich helpers change
            exc.show()
        return EXIT_USAGE
    except typer.Abort:
        err.print("aborted")
        return 130
    except KeyboardInterrupt:
        return 130
    return rv if isinstance(rv, int) else EXIT_OK
