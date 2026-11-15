"""Image discovery and loading: JPEG and Sony ARW (embedded preview) to PIL RGB.

Loaders never raise into the batch loop; they return a LoadResult with an error string.
RAW files are never demosaiced in the normal path (plan D10); demosaic is a logged fallback
for files with no usable embedded preview.
"""

from __future__ import annotations

import io
import logging
import os
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

from wildid.constants import (
    DEFAULT_EXTENSIONS,
    MAX_DECODE_PX,
    RAW_EXTENSIONS,
    RAW_PREVIEW_MIN_PX,
    SKIP_DIR_NAMES,
)

log = logging.getLogger(__name__)


PostLoad = Callable[[Image.Image], Image.Image]


@dataclass(slots=True)
class LoadResult:
    path: Path
    image: Image.Image | None
    error: str | None = None
    source: str = ""  # "jpeg" | "raw-preview" | "raw-demosaic"
    size: tuple[int, int] | None = None  # decoded size, before any `post` transform

    @property
    def ok(self) -> bool:
        return self.image is not None


def normalise_extensions(extensions: str | Iterable[str]) -> set[str]:
    """'jpg, .JPEG,arw' -> {'jpg', 'jpeg', 'arw'}."""
    if isinstance(extensions, str):
        extensions = extensions.split(",")
    out = {e.strip().lower().lstrip(".") for e in extensions}
    out.discard("")
    return out


def _suffix(path: Path) -> str:
    return path.suffix.lower().lstrip(".")


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name in SKIP_DIR_NAMES


def discover(root: Path, extensions: Iterable[str] = DEFAULT_EXTENSIONS) -> list[Path]:
    """All files under `root` (recursively) whose extension is in the whitelist, in a
    deterministic order. A file path is returned as-is (the caller checks its extension)."""
    exts = normalise_extensions(extensions)
    if root.is_file():
        return [root]
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a file or directory")
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not _skip_dir(d))
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            p = Path(dirpath) / name
            if _suffix(p) in exts:
                found.append(p)
    return found


def _open_jpeg_like(fp, *, max_px: int | None = None) -> Image.Image:
    """Open with PIL, decode JPEGs at reduced scale (DCT draft), fix EXIF orientation, RGB.

    With `max_px` the result is also bounded to that many pixels on the long side (memory
    bound for the detector-crop stage, which decodes larger than the default)."""
    target = max_px or MAX_DECODE_PX
    with Image.open(fp) as im:
        if im.format in ("JPEG", "MPO"):
            im.draft("RGB", (target, target))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
    if max_px and max(im.size) > max_px:
        im.thumbnail((max_px, max_px))
    return im


def load_jpeg(path: Path, *, max_px: int | None = None) -> Image.Image:
    return _open_jpeg_like(path, max_px=max_px)


def load_raw(path: Path, *, max_px: int | None = None) -> tuple[Image.Image, str]:
    """Embedded preview of a RAW file (fast). Demosaic only when no preview is usable."""
    import rawpy  # binary dependency; keep it local to the RAW path

    with rawpy.imread(str(path)) as raw:
        try:
            thumb = raw.extract_thumb()
        except (rawpy.LibRawNoThumbnailError, rawpy.LibRawUnsupportedThumbnailError) as exc:
            log.warning("%s: no usable embedded preview (%s); demosaicing at half size", path, exc)
            return _demosaic(raw, max_px), "raw-demosaic"
        if thumb.format == rawpy.ThumbFormat.JPEG:
            image = _open_jpeg_like(io.BytesIO(thumb.data), max_px=max_px)
        else:
            image = Image.fromarray(thumb.data).convert("RGB")
        if min(image.size) < RAW_PREVIEW_MIN_PX:
            log.warning(
                "%s: embedded preview is only %dx%d; demosaicing at half size",
                path,
                *image.size,
            )
            return _demosaic(raw, max_px), "raw-demosaic"
        return image, "raw-preview"


def _demosaic(raw, max_px: int | None) -> Image.Image:
    rgb = raw.postprocess(half_size=True, use_camera_wb=True, output_bps=8)
    image = Image.fromarray(rgb).convert("RGB")
    if max_px and max(image.size) > max_px:
        image.thumbnail((max_px, max_px))
    return image


def load_image(
    path: Path, *, max_px: int | None = None, post: PostLoad | None = None
) -> LoadResult:
    """Load one file. Never raises; failures come back as LoadResult.error.

    `post` runs in the loading thread on the decoded image (the model's pre-shrink), so the
    expensive resize happens in parallel instead of inside the serial predict loop."""
    try:
        if _suffix(path) in RAW_EXTENSIONS:
            image, source = load_raw(path, max_px=max_px)
        else:
            image, source = load_jpeg(path, max_px=max_px), "jpeg"
        size = image.size
        if post is not None:
            image = post(image)
        return LoadResult(path=path, image=image, source=source, size=size)
    except Exception as exc:  # noqa: BLE001 - any decode failure is a per-file error
        return LoadResult(path=path, image=None, error=f"{type(exc).__name__}: {exc}")


def default_workers() -> int:
    """Loader threads for decode + pre-shrink. Measured on a 32-core box: 8 beats 16 (more
    threads contend with the main thread's GIL work) and 4; 8 is the cap."""
    return max(2, min(8, os.cpu_count() or 4))


def load_many(
    paths: Sequence[Path],
    workers: int | None = None,
    *,
    max_px: int | None = None,
    post: PostLoad | None = None,
) -> list[LoadResult]:
    """Load several files in a thread pool, preserving order."""
    with ThreadPoolExecutor(max_workers=workers or default_workers()) as pool:
        return list(pool.map(lambda p: load_image(p, max_px=max_px, post=post), paths))


def iter_loaded_chunks(
    paths: Sequence[Path],
    chunk_size: int,
    workers: int | None = None,
    *,
    max_px: int | None = None,
    post: PostLoad | None = None,
) -> Iterator[list[LoadResult]]:
    """Yield chunks of loaded images; the next chunk decodes while the caller uses this one."""
    chunks = [list(paths[i : i + chunk_size]) for i in range(0, len(paths), chunk_size)]
    with ThreadPoolExecutor(max_workers=workers or default_workers()) as pool:
        pending: list[Future[LoadResult]] | None = None
        for chunk in chunks:
            futures = [pool.submit(load_image, p, max_px=max_px, post=post) for p in chunk]
            if pending is not None:
                yield [f.result() for f in pending]
            pending = futures
        if pending is not None:
            yield [f.result() for f in pending]
