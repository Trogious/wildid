"""`--format json` / `--output`: the machine-readable run document (protocol 1)."""

from __future__ import annotations

import json
import shutil

import pytest
from test_cli import FakeClassifier

from wildid import __version__
from wildid.cli import main


@pytest.fixture
def fake(monkeypatch):
    import wildid.model

    clf = FakeClassifier()
    monkeypatch.setattr(wildid.model, "load_classifier", lambda name, device: clf)
    return clf


def test_single_file_document(fake, bear_jpg, capsys):
    assert main([str(bear_jpg), "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["wildid"] == __version__
    assert doc["protocol"] == 1
    assert doc["keywords"] == {"root": "WildID", "flat": ["animals", "wildlife"]}
    assert doc["model"] == "fake" and doc["device"] == "cpu" and doc["precision"] == "tf32"
    assert doc["crop_resize"] is None  # no crop stage in this run
    assert doc["candidates"] == {
        "count": 1000,
        "place_label": None,
        "taxa": [],
        "fetched": None,
        "rank": "species",
        "auto_level": None,
        "auto_places": 0,
    }
    (res,) = doc["results"]
    assert res["ok"] is True and res["error"] is None
    assert res["label"] == "bear.jpg"
    assert len(res["predictions"]) == 5
    top = res["predictions"][0]
    assert top == {
        "species": "Ursus arctos",
        "common_name": "Brown bear",
        "score": 0.9,
        "genus": "Ursus",
        "family": "Ursidae",
        "class": None,
    }
    assert res["unconstrained"] is None
    assert res["crop"] is None and res["second_opinion"] is None
    assert res["review"] is False and res["review_reasons"] == []
    assert res["suggested_keywords"] == [
        {"path": ["WildID", "Ursus", "Ursus arctos"], "synonyms": ["Brown bear"]},
        {"path": ["animals"], "synonyms": []},
        {"path": ["wildlife"], "synonyms": []},
    ]


def test_json_header_is_not_printed(fake, bear_jpg, capsys):
    assert main([str(bear_jpg), "--format", "json"]) == 0
    out = capsys.readouterr().out
    assert out.lstrip().startswith("{")  # no text header before the document


def test_min_score_and_keyword_root_flow_into_the_document(fake, bear_jpg, capsys):
    assert (
        main([str(bear_jpg), "--format", "json", "--min-score", "0.95", "--keyword-root", "Fauna"])
        == 0
    )
    (res,) = json.loads(capsys.readouterr().out)["results"]
    assert res["review"] is True
    assert any("below 0.95" in r for r in res["review_reasons"])
    assert res["suggested_keywords"][0]["path"][0] == "Fauna"
    assert res["suggested_keywords"][-1]["path"] == ["Fauna", "review"]


def test_directory_document_includes_failures(fake, bear_jpg, tmp_path, capsys):
    shutil.copy(bear_jpg, tmp_path / "a.jpg")
    (tmp_path / "broken.jpg").write_bytes(b"\xff\xd8nope")
    assert main([str(tmp_path), "--format", "json"]) == 0
    captured = capsys.readouterr()
    doc = json.loads(captured.out)
    by_label = {r["label"]: r for r in doc["results"]}
    assert by_label["a.jpg"]["ok"] is True
    assert len(by_label["a.jpg"]["predictions"]) == 3  # directory top-k
    assert by_label["broken.jpg"]["ok"] is False
    assert by_label["broken.jpg"]["error"]
    assert "predictions" not in by_label["broken.jpg"]
    assert "broken.jpg" in captured.err  # the stderr failure summary stays


def test_output_writes_the_file_and_keeps_stdout_clean(fake, bear_jpg, tmp_path, capsys):
    out_file = tmp_path / "run" / "results.json"
    assert main([str(bear_jpg), "--format", "json", "--output", str(out_file)]) == 0
    assert capsys.readouterr().out == ""
    doc = json.loads(out_file.read_text(encoding="utf-8"))
    assert doc["protocol"] == 1 and doc["results"][0]["ok"] is True


def test_output_without_json_format_is_a_usage_error(fake, bear_jpg, tmp_path, capsys):
    assert main([str(bear_jpg), "--output", str(tmp_path / "x.json")]) == 1
    assert "--output requires --format json" in capsys.readouterr().err


def test_all_failed_still_writes_a_document_and_exits_3(fake, tmp_path, capsys):
    (tmp_path / "broken.jpg").write_bytes(b"\xff\xd8nope")
    assert main([str(tmp_path), "--format", "json"]) == 3
    doc = json.loads(capsys.readouterr().out)
    assert doc["results"][0]["ok"] is False


def test_single_file_json_with_geo_unconstrained(fake, bear_jpg, capsys, monkeypatch):
    fake.apply_species_filter(["Ursus arctos", "Ursus americanus"])
    # simulate the geo path having set a filter already via a fresh run: easiest is k only
    assert main([str(bear_jpg), "--format", "json", "--k", "2"]) == 0
    (res,) = json.loads(capsys.readouterr().out)["results"]
    assert res["unconstrained"] == {
        "species": "Ursus arctos",
        "common_name": "Brown bear",
        "score": 0.9,
        "in_candidates": True,
    }
