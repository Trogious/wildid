"""The classify pipeline, independent of the CLI: load → (crop) → predict → (anomaly, opinion).

cli.py renders these results as text blocks; results.py turns them into the JSON document;
serve.py calls this per HTTP request. Heavy modules (detector, speciesnet, images) are imported
lazily inside functions, exactly like cli.py did, so tests can stub them and `wildid --help`
stays fast.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from wildid.constants import CROP_DECODE_PX
from wildid.output import Prediction

log = logging.getLogger(__name__)

Progress = Callable[[int], None]  # absolute number of images finished (failed loads included)


class StageError(RuntimeError):
    """A detector / SpeciesNet stage could not be loaded (the message carries the prefetch
    hint when one applies). The CLI maps this to exit 2."""


@dataclass(frozen=True, slots=True)
class CropInfo:
    """What the detector stage did to one image (stage on; None in results means stage off)."""

    detected: bool
    confidence: float | None
    size: tuple[int, int] | None  # crop size actually fed to the classifier
    line: str  # the pre-formatted `  crop: ...` text line


@dataclass(frozen=True, slots=True)
class OpinionInfo:
    """SpeciesNet's second opinion on one image (stage on; None in results means stage off)."""

    name: str
    common_name: str
    score: float
    verdict: str  # agrees | same genus | same family | same order/class | disagrees | no taxon
    line: str  # the pre-formatted `  speciesnet: ...` text line


@dataclass(slots=True)
class FileResult:
    """Everything known about one input file after the pipeline ran."""

    path: Path
    label: str
    ok: bool
    error: str | None = None
    predictions: list[Prediction] = field(default_factory=list)
    unconstrained: Prediction | None = None
    in_candidates: bool | None = None
    crop: CropInfo | None = None
    opinion: OpinionInfo | None = None
    # auto-geo (plan B3): the place this photo was classified against, if any
    place_label: str | None = None
    place_candidates: int | None = None
    place_note: str | None = None  # why no place applied (no GPS, cell not prefetched…)
    review_notes: list[str] = field(default_factory=list)  # extra review reasons


# ----------------------------------------------------------------------------------------------
# optional stages: detector crop (post-MVP 1) and SpeciesNet second opinion (post-MVP 4)
# ----------------------------------------------------------------------------------------------


@dataclass
class Stages:
    detector: object | None = None
    speciesnet: object | None = None
    # resize the photos for the detector with OpenCV's exact method (detector.exact_resize)
    crop_exact: bool = False

    @property
    def crop(self) -> bool:
        return self.detector is not None

    @property
    def decode_px(self) -> int | None:
        return CROP_DECODE_PX if self.crop else None

    @property
    def crop_resize(self) -> str | None:
        """How the photos were resized for the detector, for the run document."""
        if not self.crop:
            return None
        return "exact" if self.crop_exact else "linear"

    def prepare(self, images: list) -> tuple[list, list[CropInfo | None]]:
        """Model inputs (crops, or the originals) and the crop info per image."""
        if self.detector is None:
            return list(images), [None] * len(images)
        from wildid.detector import crop_image, crop_line

        inputs: list = []
        infos: list[CropInfo | None] = []
        found = self.detector.detect(images, exact=self.crop_exact)
        for image, det in zip(images, found, strict=True):
            if det is None:
                inputs.append(image)
                infos.append(
                    CropInfo(detected=False, confidence=None, size=None, line=crop_line(None, None))
                )
            else:
                crop = crop_image(image, det)
                inputs.append(crop)
                infos.append(
                    CropInfo(
                        detected=True,
                        confidence=det.conf,
                        size=crop.size,
                        line=crop_line(det, crop.size),
                    )
                )
        return inputs, infos

    def opinions(self, inputs: list, predictions: list[list]) -> list[OpinionInfo | None]:
        """SpeciesNet's opinion per image (None when the stage is off or there is no top-1)."""
        if self.speciesnet is None or not inputs:
            return [None] * len(inputs)
        from wildid.speciesnet import compare, opinion_line

        results = self.speciesnet.classify(inputs, k=1)
        out: list[OpinionInfo | None] = []
        for preds, result in zip(predictions, results, strict=True):
            if preds and result:
                label, score = result[0]
                out.append(
                    OpinionInfo(
                        name=label.name,
                        common_name=label.common or "",
                        score=score,
                        verdict=compare(preds[0], label),
                        line=opinion_line(preds[0], result[0]),
                    )
                )
            else:
                out.append(None)
        return out


def load_stages(
    crop: bool,
    detector_name: str,
    second_opinion: bool,
    device: str,
    *,
    crop_exact: bool = False,
) -> Stages:
    """Load the optional stages or raise StageError with the exact prefetch hint."""
    stages = Stages(crop_exact=crop_exact)
    if crop or second_opinion:
        from wildid.detector import Detector, DetectorLoadError

        try:
            stages.detector = Detector.load(detector_name, device)
        except DetectorLoadError as exc:
            hint = ""
            if exc.missing_cache:
                hint = f"; run `wildid prefetch --crop --detector {detector_name}` while online"
            raise StageError(f"{exc}{hint}") from exc
    if second_opinion:
        from wildid.speciesnet import SpeciesNet, SpeciesNetLoadError

        try:
            stages.speciesnet = SpeciesNet.load(device)
        except SpeciesNetLoadError as exc:
            hint = (
                "; run `wildid prefetch --second-opinion` while online" if exc.missing_cache else ""
            )
            raise StageError(f"{exc}{hint}") from exc
    return stages


# ----------------------------------------------------------------------------------------------
# runs
# ----------------------------------------------------------------------------------------------


def label_of(path: Path, root: Path | None) -> str:
    """Directory results are labelled relative to the walked root when possible."""
    if root is None:
        return path.name
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def run_single(clf, path: Path, top_k: int, stages: Stages) -> FileResult:
    """One file, with the unconstrained anomaly pass whenever a geo filter is set."""
    from wildid.images import load_image

    t0 = time.perf_counter()
    # Without a crop stage the loader pre-shrinks for the model right away; with one the
    # detector needs the full frame first and the crops are shrunk afterwards.
    post = None if stages.crop else clf.preshrink
    result = load_image(path, max_px=stages.decode_px, post=post)
    if not result.ok:
        return FileResult(path=path, label=path.name, ok=False, error=result.error)
    log.debug(
        "loaded %s (%s, %dx%d) in %.0f ms",
        path.name,
        result.source,
        *(result.size or result.image.size),
        (time.perf_counter() - t0) * 1000,
    )
    if stages.crop:
        crops, crop_infos = stages.prepare([result.image])
        inputs = clf.prepare_inputs(crops)
    else:
        crops, crop_infos = [result.image], [None]
        inputs = crops
    preds = clf.predict(inputs, k=top_k, batch_size=1)[0]
    unconstrained = None
    in_candidates = None
    if clf.filter_species is not None:
        with clf.unfiltered():
            unconstrained = clf.predict(inputs, k=1, batch_size=1)[0][0]
        in_candidates = unconstrained.species in clf.filter_species
    opinions = stages.opinions(crops, [preds])
    return FileResult(
        path=path,
        label=path.name,
        ok=True,
        predictions=preds,
        unconstrained=unconstrained,
        in_candidates=in_candidates,
        crop=crop_infos[0],
        opinion=opinions[0],
    )


def iter_results(
    clf,
    paths: Sequence[Path],
    top_k: int,
    batch_size: int,
    stages: Stages,
    workers: int | None = None,
    *,
    root: Path | None = None,
    progress: Progress | None = None,
) -> Iterator[list[FileResult]]:
    """Directory / batch mode: yield one list of FileResults per loaded chunk, in input order.

    The unconstrained anomaly pass runs only when the classifier has a filter AND
    `clf.anomaly_check` is set (single-file mode always runs it; see run_single).
    `progress` receives absolute completed counts compatible with a progress bar total of
    len(paths); failed loads count as completed.
    """
    from wildid.images import iter_loaded_chunks

    chunk_size = max(batch_size * 4, 8)
    anomaly = clf.filter_species is not None and clf.anomaly_check
    filter_set = set(clf.filter_species or ())
    post = None if stages.crop else clf.preshrink
    done_before = 0
    total = len(paths)
    for results in iter_loaded_chunks(
        paths, chunk_size, workers, max_px=stages.decode_px, post=post
    ):
        ok = [r for r in results if r.ok]
        images = [r.image for r in ok]
        if stages.crop:
            crops, crop_infos = stages.prepare(images)
            inputs = clf.prepare_inputs(crops)
        else:
            crops, crop_infos = images, [None] * len(images)
            inputs = images

        def on_progress(done: int, _total: int, base: int = done_before) -> None:
            if progress is not None:
                progress(base + done)

        preds = clf.predict(inputs, k=top_k, batch_size=batch_size, progress=on_progress)
        unconstrained = None
        if anomaly and inputs:
            with clf.unfiltered():
                unconstrained = clf.predict(inputs, k=1, batch_size=batch_size)
        opinions = stages.opinions(crops, preds)
        done_before += len(results)
        if progress is not None:
            progress(done_before)

        out: list[FileResult] = []
        i_ok = 0
        for r in results:
            if not r.ok:
                out.append(
                    FileResult(
                        path=r.path,
                        label=label_of(r.path, root),
                        ok=False,
                        error=r.error or "unknown error",
                    )
                )
                continue
            un = unconstrained[i_ok][0] if unconstrained else None
            out.append(
                FileResult(
                    path=r.path,
                    label=label_of(r.path, root),
                    ok=True,
                    predictions=preds[i_ok],
                    unconstrained=un,
                    in_candidates=(un.species in filter_set) if un else None,
                    crop=crop_infos[i_ok],
                    opinion=opinions[i_ok],
                )
            )
            i_ok += 1
        del images, inputs, crops, results, ok
        log.debug("chunk done: %d/%d images, rss %s", done_before, total, rss())
        yield out


def rss() -> str:
    """Memory for the stability check in the debug log ('?' where neither source exists).

    Linux: the resident set size from /proc. macOS: the resident size and the physical
    footprint; on Apple Silicon the model lives in Metal memory, which the footprint counts
    and the resident size does not, so the footprint is the figure to watch there."""
    try:
        with open("/proc/self/statm") as fd:
            pages = int(fd.read().split()[1])
        return f"{pages * os.sysconf('SC_PAGE_SIZE') / 1e6:.0f} MB"
    except (OSError, ValueError, IndexError):
        pass
    usage = _darwin_memory() if sys.platform == "darwin" else None
    if usage is None:
        return "?"
    resident, footprint = usage
    return f"{resident / 1e6:.0f} MB (footprint {footprint / 1e6:.0f} MB)"


def _darwin_memory() -> tuple[int, int] | None:
    """(resident size, physical footprint) in bytes from libproc's proc_pid_rusage."""
    try:
        libproc = ctypes.CDLL("/usr/lib/libproc.dylib")
        # struct rusage_info_v2: a 16-byte uuid, then 18 uint64 fields (160 bytes in all);
        # ri_resident_size and ri_phys_footprint are the 7th and 8th of those
        info = (ctypes.c_uint64 * 20)()
        if libproc.proc_pid_rusage(os.getpid(), 2, ctypes.byref(info)) != 0:
            return None
        return int(info[8]), int(info[9])
    except (OSError, AttributeError):
        return None
