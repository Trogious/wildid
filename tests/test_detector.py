from __future__ import annotations

from types import SimpleNamespace

import pytest
from PIL import Image

from wildid.detector import (
    DEFAULT_DETECTOR,
    DETECT_BATCH,
    DETECTORS,
    Detection,
    Detector,
    crop_box,
    crop_image,
    crop_line,
    exact_resize,
    ultralytics_device,
)
from wildid.env import prepare_runtime_env


def test_crop_box_pads_by_margin_and_clamps():
    det = Detection(100, 100, 300, 200, 0.9)  # 200x100 box in a 1000x800 image
    x1, y1, x2, y2 = crop_box((1000, 800), det, margin=0.1, min_px=0)
    assert (x1, y1, x2, y2) == (80, 90, 320, 210)
    # box touching the right/bottom edge stays inside the image
    det = Detection(900, 700, 1000, 800, 0.9)
    x1, y1, x2, y2 = crop_box((1000, 800), det, margin=0.25, min_px=0)
    assert x2 <= 1000 and y2 <= 800 and x1 >= 0 and y1 >= 0
    assert (x2 - x1, y2 - y1) == (150, 150)


def test_crop_box_grows_tiny_boxes_to_min_size():
    det = Detection(500, 400, 520, 410, 0.5)  # a 20x10 speck
    x1, y1, x2, y2 = crop_box((1000, 800), det, margin=0.1, min_px=224)
    assert (x2 - x1, y2 - y1) == (224, 224)
    assert x1 <= 510 <= x2 and y1 <= 405 <= y2  # still centred on the animal


def test_crop_box_never_exceeds_the_image():
    det = Detection(0, 0, 50, 50, 0.5)
    assert crop_box((100, 60), det, margin=0.5, min_px=224) == (0, 0, 100, 60)


def test_crop_image_and_line():
    image = Image.new("RGB", (640, 480))
    det = Detection(100, 100, 300, 300, 0.87)
    crop = crop_image(image, det)
    assert crop.size == (240, 240)
    assert crop_line(det, crop.size) == "  crop: animal 0.87 → 240×240 px"
    assert crop_line(None, None) == "  crop: no animal detected, full frame used"


class _Column:
    def __init__(self, values):
        self.values = values

    def tolist(self):
        return list(self.values)


class FakeBoxes:
    """Mimics ultralytics Boxes: .conf / .xyxy with tolist(), and len()."""

    def __init__(self, boxes):
        self.conf = _Column([c for c, _ in boxes])
        self.xyxy = _Column([x for _, x in boxes])
        self._n = len(boxes)

    def __len__(self):
        return self._n


class FakeYolo:
    def __init__(self, per_image):
        self.per_image = per_image
        self.calls = []

    def predict(self, images, **kwargs):
        self.calls.append(kwargs)
        return [SimpleNamespace(boxes=FakeBoxes(boxes)) for boxes in self.per_image]


def test_detector_picks_highest_confidence_animal():
    yolo = FakeYolo([[(0.3, [0, 0, 10, 10]), (0.9, [5.4, 6.6, 100.2, 80.9])], []])
    det = Detector(DETECTORS[DEFAULT_DETECTOR], yolo, "cpu")
    found = det.detect([Image.new("RGB", (200, 200))] * 2)
    assert found[0] == Detection(5, 7, 100, 81, 0.9)
    assert found[1] is None
    assert yolo.calls[0]["classes"] == [0] and yolo.calls[0]["device"] == "cpu"
    assert yolo.calls[0]["imgsz"] == DETECTORS[DEFAULT_DETECTOR].imgsz
    assert det.detect([]) == []


def test_detector_device_is_passed_in_ultralytics_spelling():
    assert ultralytics_device("cuda") == 0 and ultralytics_device("cuda:0") == 0
    assert ultralytics_device("mps") == "mps"  # Apple Silicon: the Metal backend
    assert ultralytics_device("cpu") == "cpu"
    yolo = FakeYolo([[]])
    Detector(DETECTORS[DEFAULT_DETECTOR], yolo, "mps").detect([Image.new("RGB", (8, 8))])
    assert yolo.calls[0]["device"] == "mps"


class WidthYolo(FakeYolo):
    """Reports each image's width as its box so the caller's ordering can be checked."""

    def predict(self, images, **kwargs):
        self.calls.append(len(images))
        return [SimpleNamespace(boxes=FakeBoxes([(0.9, [0, 0, im.width, 1])])) for im in images]


def test_detector_runs_predict_in_bounded_batches_and_keeps_order():
    yolo = WidthYolo([])
    det = Detector(DETECTORS[DEFAULT_DETECTOR], yolo, "cpu")
    images = [Image.new("RGB", (w, 4)) for w in range(1, 2 * DETECT_BATCH + 6)]
    found = det.detect(images)
    # a 128-frame loader chunk never reaches the GPU in one predict() call
    assert yolo.calls == [DETECT_BATCH, DETECT_BATCH, 5]
    assert [d.x2 for d in found] == [im.width for im in images]


def test_exact_resize_makes_ultralytics_resize_exactly_and_only_while_active():
    """The real ultralytics, no model: its LetterBox must take the interpolation that
    exact_resize() gives it, and the predictor must get its own class back afterwards."""
    prepare_runtime_env(allow_model_download=False)
    import cv2
    import numpy as np
    from ultralytics.engine import predictor

    original = predictor.LetterBox
    photo = np.random.default_rng(7).integers(0, 256, size=(900, 720, 3), dtype=np.uint8)
    # 720 x 900 goes to 512 x 640, which fits the stride: no border, the result is the resize
    plain = predictor.LetterBox(640, auto=True, stride=32)(image=photo)
    with exact_resize():
        assert predictor.LetterBox is not original
        exact = predictor.LetterBox(640, auto=True, stride=32)(image=photo)
    assert predictor.LetterBox is original
    assert exact.shape == plain.shape == (640, 512, 3)
    linear = cv2.resize(photo, (512, 640), interpolation=cv2.INTER_LINEAR)
    exactly = cv2.resize(photo, (512, 640), interpolation=cv2.INTER_LINEAR_EXACT)
    assert np.array_equal(exact, exactly) and np.array_equal(plain, linear)
    assert not np.array_equal(exact, plain)

    with pytest.raises(RuntimeError), exact_resize():
        raise RuntimeError("a predict() that fails")
    assert predictor.LetterBox is original


class LetterBoxYolo(FakeYolo):
    """Notes which LetterBox class ultralytics would build during each predict() call."""

    def predict(self, images, **kwargs):
        from ultralytics.engine import predictor

        self.calls.append(predictor.LetterBox.__name__)
        return [SimpleNamespace(boxes=FakeBoxes([])) for _ in images]


def test_detect_runs_every_batch_inside_exact_resize_when_asked():
    prepare_runtime_env(allow_model_download=False)
    yolo = LetterBoxYolo([])
    det = Detector(DETECTORS[DEFAULT_DETECTOR], yolo, "cpu")
    images = [Image.new("RGB", (8, 8))] * (DETECT_BATCH + 1)
    det.detect(images)
    det.detect(images, exact=True)
    det.detect(images)
    assert yolo.calls == ["LetterBox"] * 2 + ["ExactLetterBox"] * 2 + ["LetterBox"] * 2
