"""Classifier factory: BioCLIP 2.5 Huge (TreeOfLife override) or BioCLIP 2 (stock pybioclip).

All inference goes through pybioclip's TreeOfLifeClassifier (predict / create_taxa_filter /
apply_filter). This module only chooses the model, points 2.5 at its own TreeOfLife-200M text
embeddings, and caches the label table so it is built once per process.

Import this module lazily: it pulls in torch and open_clip. The CLI sets HF_HUB_OFFLINE before
importing it so nothing here ever reaches the network.
"""

from __future__ import annotations

import json
import logging
import os
import time
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass

import numpy as np
import torch
import torchvision.transforms as T
import torchvision.transforms.functional as TF
from bioclip import Rank
from bioclip.predict import TreeOfLifeClassifier
from PIL import Image

from wildid.constants import (
    DEFAULT_MODEL,
    HF_MODEL_IDS,
    PRECISION_MODES,
    REPTILE_CLASS_ALIASES,
    TOL_REPO,
)
from wildid.output import Prediction

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelSpec:
    name: str  # CLI name
    model_str: str  # open_clip "hf-hub:" identifier
    tol_repo: str  # dataset repo holding the TreeOfLife text embeddings
    emb_npy: str
    emb_json: str
    dim: int  # embedding width; used to validate / transpose the text matrix
    caveat: str | None = None  # printed as a warning when the model is loaded

    @property
    def hf_model_id(self) -> str:
        return self.model_str.removeprefix("hf-hub:")


MODELS: dict[str, ModelSpec] = {
    "bioclip-2.5": ModelSpec(
        name="bioclip-2.5",
        model_str=f"hf-hub:{HF_MODEL_IDS['bioclip-2.5']}",
        tol_repo=TOL_REPO,
        emb_npy="embeddings/txt_emb_bioclip-2.5-vith14.npy",
        emb_json="embeddings/txt_emb_bioclip-2.5-vith14.json",
        dim=1024,
        caveat=(
            "the BioCLIP 2.5 TreeOfLife embeddings contain no reptiles (no Squamata, "
            "Testudines or Crocodylia); reptile photos get a confident wrong answer. "
            "Use --model bioclip-2 for reptiles."
        ),
    ),
    "bioclip-2": ModelSpec(
        name="bioclip-2",
        model_str=f"hf-hub:{HF_MODEL_IDS['bioclip-2']}",
        tol_repo=TOL_REPO,
        # pybioclip's stock TreeOfLifeClassifier reads exactly these two files for bioclip-2.
        emb_npy="embeddings/txt_emb_species.npy",
        emb_json="embeddings/txt_emb_species.json",
        dim=768,
    ),
}
assert DEFAULT_MODEL in MODELS


class ModelLoadError(RuntimeError):
    """Model or embeddings could not be loaded. `missing_cache` means prefetch would fix it."""

    def __init__(self, message: str, *, missing_cache: bool = False):
        super().__init__(message)
        self.missing_cache = missing_cache


class _LabelDataCache:
    """pybioclip rebuilds its ~800 k-row label DataFrame on every get_label_data() call (and
    create_taxa_filter calls it internally). Build it once per process."""

    _label_data_cache = None

    def get_label_data(self):
        if self._label_data_cache is None:
            t0 = time.perf_counter()
            self._label_data_cache = super().get_label_data()  # type: ignore[misc]
            log.debug(
                "label data: %d rows in %.1f s",
                len(self._label_data_cache),
                time.perf_counter() - t0,
            )
        return self._label_data_cache


class TreeOfLifeClassifier2(_LabelDataCache, TreeOfLifeClassifier):
    """Stock pybioclip classifier for BioCLIP 2 (its default model), with the label cache."""

    SPEC = MODELS["bioclip-2"]

    def __init__(self, **kwargs):
        kwargs.setdefault("model_str", self.SPEC.model_str)
        super().__init__(**kwargs)


class TreeOfLifeClassifier25(_LabelDataCache, TreeOfLifeClassifier):
    """pybioclip's TreeOfLifeClassifier pointed at the BioCLIP 2.5 model and its 1024-d
    TreeOfLife-200M text embeddings (pybioclip 2.1.x only knows bioclip and bioclip-2)."""

    SPEC = MODELS["bioclip-2.5"]

    def __init__(self, **kwargs):
        kwargs.setdefault("model_str", self.SPEC.model_str)
        super().__init__(**kwargs)

    def get_tol_repo_id(self) -> str:
        return self.SPEC.tol_repo

    def get_txt_emb(self) -> torch.Tensor:
        path = self.get_cached_datafile(self.SPEC.emb_npy)
        emb = torch.from_numpy(np.load(path))
        # pybioclip indexes txt_embeddings[:, idx] and computes img @ txt, i.e. it wants (dim, N).
        if emb.shape[0] != self.SPEC.dim and emb.shape[1] == self.SPEC.dim:
            emb = emb.T.contiguous()
        if emb.shape[0] != self.SPEC.dim:
            raise ModelLoadError(
                f"unexpected text embedding shape {tuple(emb.shape)} for {self.SPEC.name}; "
                f"expected ({self.SPEC.dim}, N)"
            )
        return emb

    def get_txt_names(self) -> list:
        path = self.get_cached_datafile(self.SPEC.emb_json)
        with open(path, encoding="utf-8") as fd:
            return json.load(fd)


PreShrink = Callable[[Image.Image], Image.Image]
_PIL_FILTERS = {
    T.InterpolationMode.BILINEAR: Image.Resampling.BILINEAR,
    T.InterpolationMode.BICUBIC: Image.Resampling.BICUBIC,
    T.InterpolationMode.LANCZOS: Image.Resampling.LANCZOS,
}


def make_preshrink(preprocess) -> tuple[PreShrink | None, str]:
    """Build a PIL→PIL function that does the expensive part of the model's own transform.

    pybioclip resizes every image on the main thread inside predict(); that serial loop, not
    the GPU, bounds throughput. Applying the model's *own* resize/crop objects in the loader
    threads makes pybioclip's transform an identity on the result, so scoring is unchanged:
    - open_clip style (Resize → CenterCrop → tensor): exact, the same ops on the same PIL image;
    - pybioclip's squash (ToTensor → Resize((224, 224)) → Normalize): the same tensor resize,
      quantised back to 8 bit (|Δ| ≤ 0.5/255 per channel before normalisation).
    Returns (None, "none") for an unrecognised transform, which simply disables the shortcut.
    """
    if os.environ.get("WILDID_NO_PRESHRINK") == "1":
        return None, "disabled by WILDID_NO_PRESHRINK"
    steps = list(getattr(preprocess, "transforms", None) or [])
    if len(steps) >= 2 and isinstance(steps[0], T.ToTensor) and isinstance(steps[1], T.Resize):
        resize = steps[1]
        size = list(resize.size) if isinstance(resize.size, list | tuple) else [resize.size]
        pil_filter = _PIL_FILTERS.get(resize.interpolation)
        if len(size) == 2 and pil_filter is not None and resize.antialias is not False:
            # PIL's filters are antialiased on downscale and torchvision's antialias=True was
            # built to match them; PIL is ~9x faster than the tensor resize and releases the GIL.
            target = (int(size[1]), int(size[0]))  # (w, h)

            def squash_pil(img: Image.Image) -> Image.Image:
                return img.convert("RGB").resize(target, pil_filter)

            return (
                squash_pil,
                f"PIL {resize.interpolation.value} resize to {tuple(size)} in loader threads",
            )

        def squash(img: Image.Image) -> Image.Image:
            t = TF.resize(
                TF.to_tensor(img.convert("RGB")),
                size,
                interpolation=resize.interpolation,
                max_size=resize.max_size,
                antialias=resize.antialias,
            )
            arr = (t.clamp(0, 1) * 255).round().to(torch.uint8).permute(1, 2, 0).numpy()
            return Image.fromarray(arr)

        return squash, f"tensor resize to {tuple(size)} in loader threads (8-bit quantised)"
    if len(steps) >= 2 and isinstance(steps[0], T.Resize) and isinstance(steps[1], T.CenterCrop):
        resize, crop = steps[0], steps[1]

        def resize_crop(img: Image.Image) -> Image.Image:
            return crop(resize(img.convert("RGB")))

        return resize_crop, f"resize + centre crop to {tuple(crop.size)} in loader threads (exact)"
    return None, "none"


def mps_available() -> bool:
    """True when this torch build carries Apple's Metal backend and the machine can use it."""
    mps = getattr(torch.backends, "mps", None)
    return bool(mps is not None and mps.is_available())


def pick_device(choice: str = "auto") -> str:
    """Resolve auto/cuda/mps/cpu to a torch device string. auto prefers CUDA, then Apple's
    Metal backend (MPS, Apple Silicon), then the CPU; naming `cuda` or `mps` is an error when
    that backend is unavailable."""
    if choice == "cpu":
        return "cpu"
    cuda = torch.cuda.is_available()
    if choice == "cuda":
        if not cuda:
            raise ModelLoadError("--device cuda requested but CUDA is not available")
        return "cuda"
    mps = mps_available()
    if choice == "mps":
        if not mps:
            raise ModelLoadError("--device mps requested but MPS (Apple Metal) is not available")
        return "mps"
    if cuda:
        return "cuda"
    if mps:
        return "mps"
    log.warning("no GPU backend available (CUDA or MPS); running on CPU (expect seconds per image)")
    return "cpu"


_MPS_FALLBACK_ROUTED = False


def route_mps_fallback_warnings() -> None:
    """torch warns once per operator that has no Metal kernel and therefore runs on the CPU
    (PYTORCH_ENABLE_MPS_FALLBACK, env.py). Keep that out of the result output and log it at
    debug instead, so `-v` names the operators that fell back. Every other warning is passed
    on untouched. Idempotent."""
    global _MPS_FALLBACK_ROUTED
    if _MPS_FALLBACK_ROUTED:
        return
    _MPS_FALLBACK_ROUTED = True
    previous = warnings.showwarning

    def show(message, category, filename, lineno, file=None, line=None):
        text = str(message)
        if "MPS backend" in text and "fall back" in text:
            log.debug("MPS fallback to CPU: %s", text.split(" (Triggered", 1)[0])
            return
        previous(message, category, filename, lineno, file, line)

    warnings.showwarning = show


class Classifier:
    """Thin wrapper over a loaded pybioclip classifier: label table cached once, species-rank
    filtering, batched prediction on PIL images zipped back by index."""

    def __init__(self, spec: ModelSpec, clf: TreeOfLifeClassifier, device: str):
        self.spec = spec
        self.clf = clf
        self.device = device
        self._known_species: frozenset[str] | None = None
        self._known_genera: frozenset[str] | None = None
        self._filter_species: list[str] | None = None
        self.synonyms: Mapping[str, str] = {}  # spelling -> accepted name, for top-k dedupe
        self.dedupe = True  # merge duplicate / subgenus / synonym rows in the top-k
        self.place_label: str | None = None  # e.g. "Brazil › Mato Grosso"; set by the geo filter
        self.anomaly_check = False  # directory mode: also run the unconstrained pass
        self.precision = "fp32"  # effective mode, see apply_precision()
        self._autocast_dtype: torch.dtype | None = None
        self.preshrink, self.preshrink_desc = make_preshrink(getattr(clf, "preprocess", None))
        self._pool: ThreadPoolExecutor | None = None

    # -- label data ----------------------------------------------------------------------------
    @property
    def label_data(self):
        """pybioclip's full taxa table (one row per text embedding); built once per process."""
        return self.clf.get_label_data()

    @property
    def known_species(self) -> frozenset[str]:
        if self._known_species is None:
            self._known_species = frozenset(self.label_data["species"].tolist())
        return self._known_species

    @property
    def known_genera(self) -> frozenset[str]:
        if self._known_genera is None:
            self._known_genera = frozenset(self.label_data["genus"].tolist())
        return self._known_genera

    @property
    def total_taxa(self) -> int:
        return len(self.clf.txt_names)

    @property
    def candidate_count(self) -> int:
        return len(self.clf.get_current_txt_names())

    # -- filtering -------------------------------------------------------------------------------
    def apply_species_filter(self, species: Sequence[str]) -> int:
        """Restrict predictions to these species (must all be known to the model; species rank
        only, see plan §5.3). Returns the number of candidate rows kept."""
        keep = list(dict.fromkeys(species))  # de-duplicate, keep order
        mask = self.clf.create_taxa_filter(Rank.SPECIES, keep)
        self.clf.apply_filter(mask)
        self._filter_species = keep
        return self.candidate_count

    def apply_genus_filter(self, genera: Sequence[str]) -> int:
        """Keep every model species of these genera (post-MVP item 7). Returns rows kept."""
        keep = list(dict.fromkeys(genera))
        mask = self.clf.create_taxa_filter(Rank.GENUS, keep)
        self.clf.apply_filter(mask)
        species = self.label_data.loc[list(mask), "species"]
        self._filter_species = list(dict.fromkeys(species.tolist()))
        return self.candidate_count

    def clear_filter(self) -> None:
        # pybioclip has no clear_filter(); re-applying an all-True mask would copy the whole
        # text matrix, so reset the subset the same way the library's own code checks for it.
        self.clf._subset_txt_embeddings = None
        self.clf._subset_txt_names = None
        self._filter_species = None

    @property
    def filter_species(self) -> list[str] | None:
        return self._filter_species

    @contextmanager
    def unfiltered(self) -> Iterator[None]:
        """Temporarily predict against the full TreeOfLife (the anomaly pass)."""
        saved_emb = self.clf._subset_txt_embeddings
        saved_names = self.clf._subset_txt_names
        saved_species = self._filter_species
        self.clf._subset_txt_embeddings = None
        self.clf._subset_txt_names = None
        self._filter_species = None
        try:
            yield
        finally:
            self.clf._subset_txt_embeddings = saved_emb
            self.clf._subset_txt_names = saved_names
            self._filter_species = saved_species

    # -- prediction ------------------------------------------------------------------------------
    def prepare_inputs(self, images: Sequence[Image.Image]) -> list[Image.Image]:
        """Pre-shrink many images in parallel (used after the crop stage, which needs the full
        frames first). The loader applies the same function per file when there is no crop."""
        if self.preshrink is None or not images:
            return list(images)
        if self._pool is None:
            from wildid.images import default_workers

            self._pool = ThreadPoolExecutor(max_workers=default_workers())
        return list(self._pool.map(self.preshrink, images))

    def predict(
        self,
        images: Sequence[Image.Image],
        k: int,
        batch_size: int,
        progress=None,
    ) -> list[list[Prediction]]:
        """Top-k species for each image, in input order. `progress(done, total)` is optional.

        With `dedupe` (default) a few extra rows are fetched and rows that are the same species
        (duplicate entries, subgenus spellings such as "Charis Sarota acanthoides", GBIF
        synonyms seen in the cache) are merged by summing their probability mass."""
        if not images:
            return []
        callback = progress if progress is not None else (lambda done, total: None)
        fetch_k = max(2 * k, k + 4) if self.dedupe else k
        backend = self.device.split(":", 1)[0]
        if self._autocast_dtype is not None and backend in ("cuda", "mps"):
            with torch.autocast(backend, dtype=self._autocast_dtype):
                rows = self.clf.predict(
                    list(images), Rank.SPECIES, k=fetch_k, batch_size=batch_size, callback=callback
                )
        else:
            rows = self.clf.predict(
                list(images), Rank.SPECIES, k=fetch_k, batch_size=batch_size, callback=callback
            )
        # For PIL inputs pybioclip keys results by list index (as a string); zip back by order.
        per_image: list[list[Prediction]] = [[] for _ in images]
        for row in rows:
            idx = int(row["file_name"])
            per_image[idx].append(
                Prediction(
                    species=row["species"],
                    common_name=row.get("common_name") or "",
                    score=float(row["score"]),
                    genus=row.get("genus") or "",
                    family=row.get("family") or "",
                    taxon_class=normalise_class(row.get("class")),
                )
            )
        if self.dedupe:
            return [merge_predictions(preds, k, self.synonyms) for preds in per_image]
        return per_image

    def apply_precision(self, mode: str = "auto") -> str:
        """Set matmul/conv precision for this process (post-MVP item 3, measured first).

        tf32 is lossless in practice (863/863 identical top-1, |dscore| <= 0.002) and ~11 %
        faster end to end; fp16 autocast is faster still but changed 6 of 863 top-1 answers, so
        it stays opt-in. bf16 changed 65 and is not offered. On Apple's Metal backend (MPS)
        auto is fp32 and tf32, a CUDA mode, falls back to it; fp16 is the same opt-in as on
        CUDA (measured 2026-11-14: 12 and 1 of 863 answers change, each a review frame in
        either precision; ADR 0003). Returns the effective mode."""
        if mode not in PRECISION_MODES:
            raise ModelLoadError(
                f"unknown precision {mode!r}; choose from {', '.join(PRECISION_MODES)}"
            )
        cuda = self.device.startswith("cuda")
        mps = self.device.startswith("mps")
        if mode == "auto":
            mode = "tf32" if cuda else "fp32"
        if mps and mode == "tf32":
            log.warning("precision tf32 is a CUDA mode; running fp32 on MPS")
            mode = "fp32"
        elif not cuda and not mps and mode != "fp32":
            needs = "CUDA" if mode == "tf32" else "CUDA or MPS"
            log.warning("precision %s needs %s; running fp32 on CPU", mode, needs)
            mode = "fp32"
        tf32 = cuda and mode in ("tf32", "fp16")
        torch.backends.cuda.matmul.allow_tf32 = tf32
        torch.backends.cudnn.allow_tf32 = tf32
        self._autocast_dtype = torch.float16 if mode == "fp16" else None
        self.precision = mode
        return mode


def _is_cache_miss(exc: BaseException) -> bool:
    """True when the failure chain bottoms out in a Hugging Face cache miss.

    open_clip wraps hub errors in RuntimeError/FileNotFoundError; huggingface_hub raises
    LocalEntryNotFoundError (a FileNotFoundError) in offline mode when a file is not cached.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        name = type(cur).__name__
        if name in {"LocalEntryNotFoundError", "OfflineModeIsEnabled"} or isinstance(
            cur, FileNotFoundError
        ):
            return True
        if "cannot find the requested files in the local cache" in str(cur):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def normalise_class(name: str | None) -> str:
    """The class as iNaturalist and the keyword hierarchy spell it. The GBIF backbone behind
    the TreeOfLife tables has no Reptilia: reptiles carry their order (Squamata, Testudines,
    Crocodylia, Sphenodontia) in the class column, and those become "Reptilia" here so
    keywords, the JSON `class` field and the plugin's class collections agree with the
    iNaturalist taxa the geo lists use."""
    cls = name or ""
    return REPTILE_CLASS_ALIASES.get(cls, cls)


def canonical_species(name: str, synonyms: Mapping[str, str] | None = None) -> str:
    """Merge key for a TreeOfLife species name: genus + last epithet word (collapses subgenus
    spellings and trinomials), then the GBIF accepted name when the cache knows one."""
    parts = name.split()
    base = f"{parts[0]} {parts[-1]}" if len(parts) >= 2 else name
    if synonyms:
        return synonyms.get(base) or synonyms.get(name) or base
    return base


def merge_predictions(
    preds: Sequence[Prediction], k: int, synonyms: Mapping[str, str] | None = None
) -> list[Prediction]:
    """Sum the scores of rows that are the same species; keep the first row's names."""
    merged: dict[str, Prediction] = {}
    for p in preds:
        key = canonical_species(p.species, synonyms)
        first = merged.get(key)
        if first is None:
            merged[key] = p
        else:
            merged[key] = Prediction(
                species=first.species,
                common_name=first.common_name or p.common_name,
                score=first.score + p.score,
                genus=first.genus,
                family=first.family,
                taxon_class=first.taxon_class,
            )
    return sorted(merged.values(), key=lambda p: -p.score)[:k]


def load_classifier(name: str = DEFAULT_MODEL, device: str = "auto") -> Classifier:
    """Load model + TreeOfLife text embeddings once. Raises ModelLoadError."""
    if name not in MODELS:
        raise ModelLoadError(f"unknown model {name!r}; choose from {', '.join(MODELS)}")
    spec = MODELS[name]
    dev = pick_device(device)
    if dev == "mps":
        route_mps_fallback_warnings()
    t0 = time.perf_counter()
    try:
        cls = TreeOfLifeClassifier25 if name == "bioclip-2.5" else TreeOfLifeClassifier2
        clf = cls(device=dev)
    except ModelLoadError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface anything from torch/open_clip as exit 2
        if _is_cache_miss(exc):
            raise ModelLoadError(
                f"{spec.name} is not in the local Hugging Face cache "
                f"(model {spec.hf_model_id} or {spec.tol_repo} embeddings)",
                missing_cache=True,
            ) from exc
        raise ModelLoadError(f"failed to load {spec.name}: {type(exc).__name__}: {exc}") from exc
    n_names = len(clf.txt_names)
    if clf.txt_embeddings.shape[1] != n_names:
        raise ModelLoadError(
            f"text embeddings ({tuple(clf.txt_embeddings.shape)}) do not match names ({n_names})"
        )
    log.info(
        "loaded %s on %s: %d taxa, %d-d, %.1f s",
        spec.name,
        dev,
        n_names,
        clf.txt_embeddings.shape[0],
        time.perf_counter() - t0,
    )
    if spec.caveat:
        log.warning("%s: %s", spec.name, spec.caveat)
    classifier = Classifier(spec, clf, dev)
    log.debug("input pre-shrink: %s", classifier.preshrink_desc)
    return classifier


def model_names() -> Iterable[str]:
    return MODELS.keys()
