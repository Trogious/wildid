"""Classifier helpers that need no model: device and precision selection (CUDA and Apple's
MPS backend are faked, so this runs the same on every platform)."""

from __future__ import annotations

import warnings

import numpy as np
import pytest
import torch
import torchvision.transforms as T
from PIL import Image

from wildid import model as model_module
from wildid.model import (
    MODELS,
    Classifier,
    ModelLoadError,
    canonical_species,
    make_preshrink,
    merge_predictions,
    normalise_class,
    pick_device,
    route_mps_fallback_warnings,
)
from wildid.output import Prediction

MEAN = (0.48145466, 0.4578275, 0.40821073)
STD = (0.26862954, 0.26130258, 0.27577711)


def _cpu_classifier():
    return Classifier(MODELS["bioclip-2"], clf=None, device="cpu")


def test_apply_precision_on_cpu_is_always_fp32():
    clf = _cpu_classifier()
    assert clf.apply_precision("auto") == "fp32"
    assert clf.apply_precision("fp16") == "fp32"  # warns, falls back
    assert clf._autocast_dtype is None


def test_apply_precision_sets_torch_flags(monkeypatch):
    clf = Classifier(MODELS["bioclip-2"], clf=None, device="cuda")
    assert clf.apply_precision("auto") == "tf32"
    assert torch.backends.cuda.matmul.allow_tf32 is True
    assert clf.apply_precision("fp32") == "fp32"
    assert torch.backends.cuda.matmul.allow_tf32 is False
    assert clf.apply_precision("fp16") == "fp16" and clf._autocast_dtype is torch.float16
    clf.apply_precision("fp32")
    with pytest.raises(ModelLoadError):
        clf.apply_precision("bf16")


def _backends(monkeypatch, *, cuda: bool, mps: bool) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: cuda)
    monkeypatch.setattr(model_module, "mps_available", lambda: mps)


def test_pick_device_auto_prefers_cuda_then_mps_then_cpu(monkeypatch):
    _backends(monkeypatch, cuda=True, mps=True)
    assert pick_device("auto") == "cuda"
    _backends(monkeypatch, cuda=False, mps=True)
    assert pick_device("auto") == "mps"
    _backends(monkeypatch, cuda=False, mps=False)
    assert pick_device("auto") == "cpu"


def test_pick_device_named_backend_must_exist(monkeypatch):
    _backends(monkeypatch, cuda=False, mps=False)
    with pytest.raises(ModelLoadError, match="mps"):
        pick_device("mps")
    with pytest.raises(ModelLoadError, match="cuda"):
        pick_device("cuda")
    assert pick_device("cpu") == "cpu"
    _backends(monkeypatch, cuda=True, mps=True)
    assert pick_device("mps") == "mps" and pick_device("cuda") == "cuda"
    assert pick_device("cpu") == "cpu"  # the CPU is always honoured


def test_mps_available_follows_torch(monkeypatch):
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert model_module.mps_available() is True
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    assert model_module.mps_available() is False


def test_apply_precision_on_mps_fp32_by_default_fp16_opt_in(monkeypatch, caplog):
    monkeypatch.delenv("WILDID_MPS_FP16", raising=False)  # the old measurement switch is gone
    clf = Classifier(MODELS["bioclip-2"], clf=None, device="mps")
    assert clf.apply_precision("auto") == "fp32" and clf._autocast_dtype is None
    with caplog.at_level("WARNING", logger="wildid.model"):
        assert clf.apply_precision("tf32") == "fp32"  # a CUDA mode: warns, falls back
    assert "tf32 is a CUDA mode" in caplog.text and clf._autocast_dtype is None
    caplog.clear()
    # fp16 is the opt-in it is on CUDA (owner decision 2026-11-15, ADR 0003): no warning
    with caplog.at_level("WARNING", logger="wildid.model"):
        assert clf.apply_precision("fp16") == "fp16"
    assert clf._autocast_dtype is torch.float16 and clf.precision == "fp16"
    assert caplog.text == ""
    assert torch.backends.cuda.matmul.allow_tf32 is False  # TF32 stays a CUDA matter
    assert clf.apply_precision("auto") == "fp32" and clf._autocast_dtype is None


def test_apply_precision_on_cpu_names_what_the_mode_needs(caplog):
    clf = _cpu_classifier()
    with caplog.at_level("WARNING", logger="wildid.model"):
        assert clf.apply_precision("fp16") == "fp32"
        assert clf.apply_precision("tf32") == "fp32"
    assert "fp16 needs CUDA or MPS" in caplog.text and "tf32 needs CUDA;" in caplog.text


@pytest.mark.parametrize(
    ("device", "mode", "backend"),
    [
        ("mps", "fp16", "mps"),
        ("cuda:0", "fp16", "cuda"),
        ("mps", "auto", None),
        ("cpu", "fp16", None),
    ],
)
def test_predict_runs_under_the_autocast_only_in_fp16(monkeypatch, device, mode, backend):
    """fp16 is an autocast around pybioclip's predict, on CUDA and on MPS alike."""
    entered = []

    class Autocast:
        def __init__(self, device_type, dtype=None):
            entered.append((device_type, dtype))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    class Bioclip:
        def predict(self, images, rank, k, batch_size, callback):
            return []

    monkeypatch.setattr(model_module.torch, "autocast", Autocast)
    clf = Classifier(MODELS["bioclip-2"], clf=Bioclip(), device=device)
    clf.apply_precision(mode)
    assert clf.predict([Image.new("RGB", (8, 8))], k=1, batch_size=1) == [[]]
    assert entered == ([(backend, torch.float16)] if backend else [])
    clf.apply_precision("fp32")  # leave torch's TF32 flags as they were


def test_mps_fallback_warnings_go_to_the_debug_log(monkeypatch, caplog):
    shown = []
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        monkeypatch.setattr(
            warnings, "showwarning", lambda message, *args, **kwargs: shown.append(str(message))
        )
        monkeypatch.setattr(model_module, "_MPS_FALLBACK_ROUTED", False)
        route_mps_fallback_warnings()
        route_mps_fallback_warnings()  # idempotent: wraps once
        with caplog.at_level("DEBUG", logger="wildid.model"):
            warnings.warn(
                "The operator 'aten::foo' is not currently supported on the MPS backend and "
                "will fall back to run on the CPU. This may have performance implications. "
                "(Triggered internally at MPSFallback.mm:14.)",
                UserWarning,
                stacklevel=1,
            )
            warnings.warn("something else", UserWarning, stacklevel=1)
    assert shown == ["something else"]  # every other warning is passed on untouched
    assert "MPS fallback to CPU: The operator 'aten::foo'" in caplog.text
    assert "Triggered" not in caplog.text


def _noise_image(w=640, h=480, seed=0):
    rng = np.random.default_rng(seed)
    return Image.fromarray(rng.integers(0, 256, (h, w, 3), dtype=np.uint8))


def test_preshrink_is_exact_for_openclip_style_transform():
    full = T.Compose(
        [
            T.Resize(224, interpolation=T.InterpolationMode.BICUBIC),
            T.CenterCrop(224),
            T.ToTensor(),
            T.Normalize(MEAN, STD),
        ]
    )
    pre, desc = make_preshrink(full)
    assert pre is not None and "exact" in desc
    img = _noise_image()
    small = pre(img)
    assert small.size == (224, 224)
    assert torch.equal(full(img), full(small))  # the model's transform is an identity on it


def _gradient_image(w=800, h=500):
    y, x = np.mgrid[0:h, 0:w]
    arr = np.stack(
        [x * 255 // (w - 1), y * 255 // (h - 1), ((x + y) * 255) // (w + h - 2)], axis=-1
    )
    return Image.fromarray(arr.astype(np.uint8))


def test_preshrink_matches_pybioclip_squash_closely():
    full = T.Compose([T.ToTensor(), T.Resize((224, 224), antialias=True), T.Normalize(MEAN, STD)])
    pre, desc = make_preshrink(full)
    assert pre is not None and desc.startswith("PIL bilinear")
    img = _gradient_image()
    small = pre(img)
    assert small.size == (224, 224)
    # PIL's antialiased bilinear and torchvision's antialias=True are built to agree; on a smooth
    # image the normalised inputs differ by well under 1 % of the dynamic range.
    delta = (full(img) - full(small)).abs()
    assert delta.max().item() < 0.05 and delta.mean().item() < 0.01
    # the model's own transform is then an identity on the pre-shrunk image
    assert torch.allclose(full(small), full(pre(small)), atol=1e-6)


def test_preshrink_unknown_transform_is_disabled(monkeypatch):
    assert make_preshrink(T.Compose([T.ToTensor()])) == (None, "none")
    assert make_preshrink(None) == (None, "none")
    monkeypatch.setenv("WILDID_NO_PRESHRINK", "1")
    assert make_preshrink(T.Compose([T.ToTensor(), T.Resize((224, 224))]))[0] is None


def test_prepare_inputs_runs_the_preshrink_in_parallel():
    clf = _cpu_classifier()
    clf.preshrink = lambda im: im.resize((8, 8))
    out = clf.prepare_inputs([_noise_image(32, 32, seed=i) for i in range(5)])
    assert [im.size for im in out] == [(8, 8)] * 5
    clf.preshrink = None
    assert [im.size for im in clf.prepare_inputs([_noise_image(32, 32)])] == [(32, 32)]


def test_canonical_species_collapses_subgenus_spellings_and_synonyms():
    assert canonical_species("Charis Sarota acanthoides") == "Charis acanthoides"
    assert canonical_species("Panthera pardus pardus") == "Panthera pardus"
    assert canonical_species("Grus grus") == "Grus grus"
    syn = {"Grus communis": "Grus grus", "Grus grus": "Grus grus"}
    assert canonical_species("Grus communis", syn) == "Grus grus"
    assert canonical_species("Grus grus", syn) == "Grus grus"
    assert canonical_species("Ursus arctos", syn) == "Ursus arctos"


def test_merge_predictions_sums_duplicates_and_keeps_order_by_score():
    rows = [
        Prediction("Charis Sarota acanthoides", "", 0.30, genus="Charis"),
        Prediction("Grus grus", "Common crane", 0.25),
        Prediction("Charis acanthoides", "Acanthoides metalmark", 0.20),
        Prediction("Grus communis", "", 0.10),
        Prediction("Ursus arctos", "Brown bear", 0.05),
    ]
    merged = merge_predictions(rows, k=2, synonyms={"Grus communis": "Grus grus"})
    assert [(p.species, round(p.score, 2)) for p in merged] == [
        ("Charis Sarota acanthoides", 0.5),
        ("Grus grus", 0.35),
    ]
    assert merged[0].common_name == "Acanthoides metalmark"  # filled from the merged row
    assert merge_predictions([], 3) == []


def test_normalise_class_spells_gbif_reptile_orders_as_reptilia():
    # the TreeOfLife tables carry Squamata/Testudines/Crocodylia/Sphenodontia in the class column
    for gbif in ("Squamata", "Testudines", "Crocodylia", "Sphenodontia", "Rhynchocephalia"):
        assert normalise_class(gbif) == "Reptilia"
    assert normalise_class("Mammalia") == "Mammalia"
    assert normalise_class("Aves") == "Aves"
    assert normalise_class("") == ""
    assert normalise_class(None) == ""


class _FakeTol:
    """pybioclip's predict() output for one image: a chameleon row spelled the GBIF way."""

    preprocess = None

    def predict(self, images, rank, k, batch_size, callback):
        return [
            {
                "file_name": "0",
                "species": "Furcifer pardalis",
                "common_name": "Panther chameleon",
                "score": 0.9,
                "genus": "Furcifer",
                "family": "Chamaeleonidae",
                "class": "Squamata",
                "order": "",
            },
            {
                "file_name": "0",
                "species": "Panthera onca",
                "common_name": "Jaguar",
                "score": 0.1,
                "genus": "Panthera",
                "family": "Felidae",
                "class": "Mammalia",
                "order": "Carnivora",
            },
        ]


def test_predict_normalises_the_class_of_every_row():
    clf = Classifier(MODELS["bioclip-2"], clf=_FakeTol(), device="cpu")
    (preds,) = clf.predict([_noise_image(8, 8)], k=2, batch_size=1)
    assert [(p.species, p.taxon_class) for p in preds] == [
        ("Furcifer pardalis", "Reptilia"),
        ("Panthera onca", "Mammalia"),
    ]
