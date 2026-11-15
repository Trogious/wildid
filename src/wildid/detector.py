"""Animal detector for the --crop stage: MegaDetector v6 through ultralytics (post-MVP item 1).

The detector finds the animal; BioCLIP then sees a crop instead of a distant speck in a wide
frame. Weights are plain ultralytics checkpoints fetched by `wildid prefetch --crop` into the
wildid cache; nothing here downloads.
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from wildid.constants import CROP_MARGIN, CROP_MIN_PX, models_dir

log = logging.getLogger(__name__)

ANIMAL_CLASS = 0  # MegaDetector classes: 0 animal, 1 person, 2 vehicle
# Images per ultralytics predict() call. The pipeline hands detect() a whole loader chunk
# (4 x batch size = 128 frames by default) and ultralytics runs a list as one batch, so without
# this bound the detector's activations grow with the chunk: 128 frames at 640 px need more
# than 12 GB and bioclip-2.5 + crop ran out of memory on a 24 GB card (acceptance 2026-10-25).
DETECT_BATCH = 16
# One predict() at a time: exact_resize() swaps a class inside ultralytics for the length of
# a detect() call, and a second caller must not see it half-way.
_PREDICT_LOCK = threading.Lock()


@dataclass(frozen=True)
class DetectorSpec:
    name: str
    filename: str
    url: str
    sha256: str
    imgsz: int  # the size the checkpoint was trained at; running MDv6-c at 1280 loses animals
    conf: float  # MegaDetector's typical threshold

    @property
    def path(self) -> Path:
        return models_dir() / self.filename


DETECTORS: dict[str, DetectorSpec] = {
    "mdv6-yolov9-c": DetectorSpec(
        name="mdv6-yolov9-c",
        filename="MDV6-yolov9-c.pt",
        url="https://zenodo.org/records/15398270/files/MDV6-yolov9-c.pt?download=1",
        sha256="daa6cd5d2e3fd52754889cd9c702f73c0349a8388318952e6eaf83e0667543e4",
        imgsz=640,
        conf=0.2,
    ),
    "mdv6-yolov9-e": DetectorSpec(
        name="mdv6-yolov9-e",
        filename="MDV6-yolov9-e-1280.pt",
        url="https://zenodo.org/records/15398270/files/MDV6-yolov9-e-1280.pt?download=1",
        sha256="15909cd77250fbdde454ed3c67618cc85c396373da514c67b34e434d7b5a59fa",
        imgsz=1280,
        conf=0.2,
    ),
}
DEFAULT_DETECTOR = "mdv6-yolov9-c"


class DetectorLoadError(RuntimeError):
    def __init__(self, message: str, *, missing_cache: bool = False):
        super().__init__(message)
        self.missing_cache = missing_cache


@dataclass(frozen=True, slots=True)
class Detection:
    x1: int
    y1: int
    x2: int
    y2: int
    conf: float

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1


def ultralytics_device(device: str) -> int | str:
    """A torch device string in ultralytics' spelling: CUDA device 0, "mps" or "cpu"."""
    if device.startswith("cuda"):
        return 0
    return "mps" if device.startswith("mps") else "cpu"


@contextlib.contextmanager
def exact_resize():
    """While active, ultralytics resizes a photo to the detector's size with OpenCV's
    INTER_LINEAR_EXACT, the bilinear resize that gives the same pixels on an Arm Mac and an
    x86-64 PC (measured on 1,020 photos, acceptance 2026-11-15). Its default, INTER_LINEAR,
    does not: OpenCV's Arm build computes it with its own code, the detector's input then
    differs by 1 in about a fifth of the values between a Mac and a PC, and about 2 % of the
    cropped photos get another name. ultralytics' LetterBox takes the interpolation as an
    argument that its predictor never passes; this swaps the class the predictor builds for
    one that does."""
    import cv2
    from ultralytics.engine import predictor

    original = predictor.LetterBox

    class ExactLetterBox(original):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("interpolation", cv2.INTER_LINEAR_EXACT)
            super().__init__(*args, **kwargs)

    predictor.LetterBox = ExactLetterBox
    try:
        yield
    finally:
        predictor.LetterBox = original


class Detector:
    """Highest-confidence animal box per image (or None)."""

    def __init__(self, spec: DetectorSpec, model, device: str):
        self.spec = spec
        self.model = model
        self.device = device

    @classmethod
    def load(cls, name: str = DEFAULT_DETECTOR, device: str = "cuda") -> Detector:
        if name not in DETECTORS:
            raise DetectorLoadError(
                f"unknown detector {name!r}; choose from {', '.join(DETECTORS)}"
            )
        spec = DETECTORS[name]
        if not spec.path.exists():
            raise DetectorLoadError(
                f"detector weights are not in the local cache ({spec.path})", missing_cache=True
            )
        t0 = time.perf_counter()
        from ultralytics import YOLO

        model = YOLO(str(spec.path))
        log.info("loaded detector %s in %.1f s", spec.name, time.perf_counter() - t0)
        return cls(spec, model, device)

    def detect(
        self, images: Sequence[Image.Image], *, exact: bool = False
    ) -> list[Detection | None]:
        """Best animal box per image, in input order; predict() sees at most DETECT_BATCH
        images at a time so GPU memory stays bounded whatever the caller's chunk size.
        `exact` resizes the photos for the detector with OpenCV's exact method, the same on
        a Mac and a PC (exact_resize); the default leaves the resize to the platform's
        OpenCV."""
        out: list[Detection | None] = []
        if not images:
            return out
        with _PREDICT_LOCK, exact_resize() if exact else contextlib.nullcontext():
            for start in range(0, len(images), DETECT_BATCH):
                results = self.model.predict(
                    list(images[start : start + DETECT_BATCH]),
                    imgsz=self.spec.imgsz,
                    conf=self.spec.conf,
                    classes=[ANIMAL_CLASS],
                    device=ultralytics_device(self.device),
                    verbose=False,
                )
                for res in results:
                    boxes = res.boxes
                    best = None
                    if boxes is not None and len(boxes):
                        confs = boxes.conf.tolist()
                        xyxy = boxes.xyxy.tolist()
                        i = max(range(len(confs)), key=confs.__getitem__)
                        x1, y1, x2, y2 = (int(round(v)) for v in xyxy[i])
                        best = Detection(x1, y1, x2, y2, float(confs[i]))
                    out.append(best)
        return out


def crop_box(
    size: tuple[int, int],
    det: Detection,
    *,
    margin: float = CROP_MARGIN,
    min_px: int = CROP_MIN_PX,
) -> tuple[int, int, int, int]:
    """Box padded by `margin` on each side, grown (centred) to at least `min_px`, clamped."""
    w, h = size
    cx = (det.x1 + det.x2) / 2
    cy = (det.y1 + det.y2) / 2
    cw = min(w, max(det.width * (1 + 2 * margin), min_px))
    ch = min(h, max(det.height * (1 + 2 * margin), min_px))
    x1 = int(round(cx - cw / 2))
    y1 = int(round(cy - ch / 2))
    cw_i, ch_i = int(round(cw)), int(round(ch))
    x1 = max(0, min(x1, w - cw_i))
    y1 = max(0, min(y1, h - ch_i))
    return x1, y1, x1 + cw_i, y1 + ch_i


def crop_image(image: Image.Image, det: Detection) -> Image.Image:
    return image.crop(crop_box(image.size, det))


def crop_line(det: Detection | None, crop_size: tuple[int, int] | None) -> str:
    """The `crop:` line of a result block."""
    if det is None or crop_size is None:
        return "  crop: no animal detected, full frame used"
    return f"  crop: animal {det.conf:.2f} → {crop_size[0]}×{crop_size[1]} px"
