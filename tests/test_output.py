from __future__ import annotations

from wildid import __version__
from wildid.output import CandidateInfo, Prediction, block, failures, header


def test_header_full_tol():
    text = header("bioclip-2.5", "cuda", CandidateInfo(count=794878))
    first, note = text.split("\n")
    assert first == (
        f"wildid {__version__} | model=bioclip-2.5 device=cuda | "
        "candidates=full TreeOfLife (794,878 taxa)"
    )
    assert note.startswith("note: scores are a softmax over the candidate set")


def test_header_with_place():
    info = CandidateInfo(
        count=412,
        place_label="Brazil › Mato Grosso",
        taxa=("Mammalia", "Reptilia"),
        fetched="2026-10-23",
    )
    assert info.description == (
        "412 species (Brazil › Mato Grosso; Mammalia,Reptilia; fetched 2026-10-23)"
    )


def test_block_rows_and_anomaly_marker():
    preds = [
        Prediction("Panthera onca", "Jaguar", 0.9624),
        Prediction("Puma concolor", "Puma", 0.021),
        Prediction("Leopardus pardalis", "", 0.0094),
    ]
    text = block(
        "DSC04512.ARW",
        preds,
        unconstrained=Prediction("Panthera tigris", "Tiger", 0.871),
        in_candidates=False,
        place_label="Brazil › Mato Grosso",
    )
    lines = text.split("\n")
    assert lines[0] == "DSC04512.ARW"
    assert lines[1].startswith("  1. Panthera onca")
    assert lines[1].split() == ["1.", "Panthera", "onca", "Jaguar", "0.962"]
    assert lines[3].split()[1:] == ["Leopardus", "pardalis", "-", "0.009"]
    assert lines[4] == (
        "  unconstrained top-1: Panthera tigris (0.871)  ⚠ not in Brazil › Mato Grosso list"
    )


def test_block_in_candidates_has_no_marker():
    text = block(
        "x.jpg",
        [Prediction("Ursus arctos", "Brown bear", 0.99)],
        unconstrained=Prediction("Ursus arctos", "Brown bear", 0.98),
        in_candidates=True,
        place_label="Europe",
    )
    assert text.endswith("unconstrained top-1: Ursus arctos (0.980)")
    assert "⚠" not in text


def test_block_keeps_diacritics():
    text = block("x.jpg", [Prediction("Capreolus capreolus", "Sarna européjska", 0.5)])
    assert "Sarna européjska" in text


def test_block_without_predictions():
    assert block("x.jpg", []) == "x.jpg\n  (no predictions)"


def test_failures_summary():
    assert failures([]) == ""
    text = failures([("a/b.jpg", "UnidentifiedImageError: cannot identify"), ("c.ARW", "boom")])
    assert text.split("\n") == [
        "2 file(s) could not be loaded:",
        "  a/b.jpg: UnidentifiedImageError: cannot identify",
        "  c.ARW: boom",
    ]


def test_header_shows_precision():
    text = header("bioclip-2", "cuda", CandidateInfo(count=5), precision="tf32")
    assert text.split("\n")[0].startswith(
        f"wildid {__version__} | model=bioclip-2 device=cuda precision=tf32 | "
    )


def test_block_orders_crop_anomaly_and_opinion_lines():
    text = block(
        "x.jpg",
        [Prediction("Panthera pardus", "Leopard", 0.9)],
        unconstrained=Prediction("Panthera pardus", "Leopard", 0.8),
        in_candidates=True,
        crop_line="  crop: animal 0.95 \u2192 800\u00d7600 px",
        opinion_line="  speciesnet: Panthera pardus \u2014 leopard (0.910)  agrees",
    )
    assert text.split("\n")[2:] == [
        "  crop: animal 0.95 \u2192 800\u00d7600 px",
        "  unconstrained top-1: Panthera pardus (0.800)",
        "  speciesnet: Panthera pardus \u2014 leopard (0.910)  agrees",
    ]
