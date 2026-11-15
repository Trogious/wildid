"""Second opinion for mammals (post-MVP item 4): Google's SpeciesNet crop classifier.

SpeciesNet (EfficientNetV2-M, 2,498 labels, trained on 65 M camera-trap images) is loaded
directly from the files Google publishes on Kaggle: `info.json`, the onnx2torch-converted
classifier and its label list. Preprocessing mirrors `speciesnet.classifier` (Apache-2.0,
github.com/google/cameratrapai); the `speciesnet` package itself is not used because it pins
yolov5 and friends. `wildid prefetch --second-opinion` fetches the files; nothing here downloads.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
import torchvision.transforms.functional as TF
from PIL import Image

from wildid.constants import models_dir
from wildid.output import Prediction

log = logging.getLogger(__name__)

SPECIESNET_VERSION = "v4.0.3a"
SPECIESNET_URL = "https://www.kaggle.com/api/v1/models/google/speciesnet/pyTorch/v4.0.3a/1/download"
SPECIESNET_SHA256 = "d15d070113a03d548ebd1531fd7ca88268bdb0ba00323cfa904902a2f167b6ae"
SPECIESNET_DIRNAME = f"speciesnet-{SPECIESNET_VERSION}"
IMG_SIZE = 480
CROP_BATCH = 8


def speciesnet_dir() -> Path:
    return models_dir() / SPECIESNET_DIRNAME


class SpeciesNetLoadError(RuntimeError):
    def __init__(self, message: str, *, missing_cache: bool = False):
        super().__init__(message)
        self.missing_cache = missing_cache


@dataclass(frozen=True, slots=True)
class Label:
    """One SpeciesNet label: `uuid;class;order;family;genus;species;common name`."""

    uuid: str
    taxon_class: str
    order: str
    family: str
    genus: str
    species: str
    common: str

    @classmethod
    def parse(cls, line: str) -> Label:
        parts = [p.strip() for p in line.strip().split(";")]
        parts += [""] * (7 - len(parts))
        return cls(*parts[:7])

    @property
    def rank(self) -> str:
        if self.species:
            return "species"
        if self.genus:
            return "genus"
        if self.family:
            return "family"
        if self.order:
            return "order"
        if self.taxon_class:
            return "class"
        return "none"  # blank / animal / human / vehicle

    @property
    def binomial(self) -> str | None:
        if self.genus and self.species:
            return f"{self.genus.capitalize()} {self.species.lower()}"
        return None

    @property
    def name(self) -> str:
        if self.binomial:
            return self.binomial
        for value in (self.genus, self.family, self.order, self.taxon_class):
            if value:
                return f"{value.capitalize()} ({self.rank})"
        return self.common or "unknown"


class SpeciesNet:
    def __init__(self, model, labels: list[Label], device: str, version: str):
        self.model = model
        self.labels = labels
        self.device = device
        self.version = version

    @classmethod
    def load(cls, device: str = "cuda", model_dir: Path | None = None) -> SpeciesNet:
        base = model_dir or speciesnet_dir()
        info_path = base / "info.json"
        if not info_path.exists():
            raise SpeciesNetLoadError(
                f"SpeciesNet is not in the local cache ({base})", missing_cache=True
            )
        t0 = time.perf_counter()
        with open(info_path, encoding="utf-8") as fd:
            info = json.load(fd)
        if info.get("type") != "always_crop":
            raise SpeciesNetLoadError(f"unsupported SpeciesNet type {info.get('type')!r}")
        try:
            # The checkpoint is a pickled onnx2torch GraphModule, hence weights_only=False.
            model = torch.load(base / info["classifier"], map_location=device, weights_only=False)
        except Exception as exc:  # noqa: BLE001
            raise SpeciesNetLoadError(f"failed to load SpeciesNet: {exc}") from exc
        model.eval()
        for param in model.parameters():
            param.requires_grad = False
        with open(base / info["classifier_labels"], encoding="utf-8") as fd:
            labels = [Label.parse(line) for line in fd if line.strip()]
        log.info(
            "loaded SpeciesNet %s (%d labels) in %.1f s",
            info.get("version", "?"),
            len(labels),
            time.perf_counter() - t0,
        )
        return cls(model, labels, device, str(info.get("version", "?")))

    @staticmethod
    def preprocess(image: Image.Image) -> np.ndarray:
        """Exactly speciesnet.classifier's crop path: float resize to 480x480 without
        antialiasing, back to uint8, HWC, then scaled to [0, 1]."""
        t = TF.convert_image_dtype(TF.pil_to_tensor(image.convert("RGB")), torch.float32)
        t = TF.resize(t, [IMG_SIZE, IMG_SIZE], antialias=False)
        arr = TF.convert_image_dtype(t, torch.uint8).permute(1, 2, 0).numpy()
        return arr / 255.0

    @torch.no_grad()
    def classify(
        self, images: Sequence[Image.Image], k: int = 3
    ) -> list[list[tuple[Label, float]]]:
        """Top-k (label, probability) per image, in input order."""
        out: list[list[tuple[Label, float]]] = []
        arrays = [self.preprocess(im) for im in images]
        for i in range(0, len(arrays), CROP_BATCH):
            batch = np.stack(arrays[i : i + CROP_BATCH], axis=0).astype(np.float32)
            logits = self.model(torch.from_numpy(batch).to(self.device)).float().cpu()
            probs = torch.softmax(logits, dim=-1)
            top = probs.topk(min(k, probs.shape[-1]), dim=-1)
            for scores, idx in zip(top.values.tolist(), top.indices.tolist(), strict=True):
                out.append([(self.labels[j], float(s)) for j, s in zip(idx, scores, strict=True)])
        return out


def compare(bioclip: Prediction, label: Label) -> str:
    """How SpeciesNet's answer relates to BioCLIP's top-1."""
    if label.rank == "none":
        return "no taxon"
    if label.binomial and label.binomial.lower() == bioclip.species.lower():
        return "agrees"
    if label.genus and bioclip.genus and label.genus.lower() == bioclip.genus.lower():
        return "same genus"
    if label.family and bioclip.family and label.family.lower() == bioclip.family.lower():
        return "same family"
    if label.rank in ("order", "class") and bioclip.taxon_class:
        # SpeciesNet often stops at "Aves" for birds it does not know: consistent, not a dispute.
        if label.taxon_class.lower() == bioclip.taxon_class.lower():
            return f"same {label.rank}"
    return "disagrees"


def opinion_line(bioclip: Prediction, opinion: tuple[Label, float]) -> str:
    """The `speciesnet:` line of a result block."""
    label, score = opinion
    verdict = compare(bioclip, label)
    common = f" — {label.common}" if label.binomial and label.common else ""
    mark = "⚠ " if verdict == "disagrees" else ""
    return f"  speciesnet: {label.name}{common} ({score:.3f})  {mark}{verdict}"
