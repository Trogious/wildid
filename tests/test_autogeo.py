"""--geo-auto end to end with the fake classifier: grouping, per-block place lines, JSON,
review flags for unresolved cells, and the prefetch side with a fake iNaturalist client."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime

import pytest
from test_cli import FakeClassifier
from test_gps import NEARBY, write_gps_jpeg

from wildid.cli import main
from wildid.geo import GeoCache, Place, ResolvedPlace
from wildid.gps import place_cache_key


@pytest.fixture
def fake(monkeypatch):
    import wildid.model

    clf = FakeClassifier()
    monkeypatch.setattr(wildid.model, "load_classifier", lambda name, device: clf)
    return clf


@pytest.fixture
def kenya_cell(isolated_cache):
    """The Mara cell resolved to Kenya (country level) with its species lists cached."""
    cache = GeoCache(isolated_cache / "geo")
    kenya = ResolvedPlace(Place(7042, "Kenya", "Kenya", 0, (97392, 7042)), "Kenya")
    cache.save_place(place_cache_key(-1.4, 35.2, "country"), kenya)
    for taxon in ("Mammalia", "Reptilia", "Amphibia", "Aves"):
        species = ["Ursus arctos", "Ursus americanus"] if taxon == "Mammalia" else []
        cache.save_species(
            {
                "place_id": 7042,
                "taxon": taxon,
                "fetched_at": datetime.now(UTC),
                "total_results": len(species),
                "species": species,
            }
        )
    return cache


@pytest.fixture
def trip(tmp_path, bear_jpg):
    """a.jpg in the cached Kenya cell, b.jpg without GPS, c.jpg in a cell nobody prefetched."""
    write_gps_jpeg(tmp_path / "a.jpg", -1.4, 35.2, source=bear_jpg)
    shutil.copy(bear_jpg, tmp_path / "b.jpg")
    write_gps_jpeg(tmp_path / "c.jpg", 10.0, 10.0, source=bear_jpg)
    return tmp_path


def test_geo_auto_text_output(fake, kenya_cell, trip, capsys):
    assert main([str(trip), "--geo-auto", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "candidates=per-photo GPS (country level; 1 place(s);" in out.splitlines()[0]
    assert "a.jpg\n" in out and "  place: Kenya (2 species)" in out
    assert "  place: no GPS in the file \u2192 full TreeOfLife" in out
    assert (
        "  place: no cached place for GPS cell gps:10.00,10.00 (country level) "
        "\u2192 full TreeOfLife"
    ) in out
    assert fake.applied == ["Ursus arctos", "Ursus americanus"]  # the Kenya group was filtered
    # the Kenya group ran filtered with the anomaly line, the others unconstrained
    assert out.count("unconstrained top-1") == 0  # directory mode: anomaly pass is opt-in


def test_geo_auto_json_flags_unresolved_cells(fake, kenya_cell, trip, capsys):
    assert main([str(trip), "--geo-auto", "--offline", "--format", "json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["candidates"]["auto_level"] == "country" and doc["candidates"]["auto_places"] == 1
    by = {r["label"]: r for r in doc["results"]}
    assert by["a.jpg"]["place"] == {"label": "Kenya", "candidates": 2, "note": None}
    assert by["a.jpg"]["review"] is False
    assert by["b.jpg"]["place"]["label"] is None and "no GPS" in by["b.jpg"]["place"]["note"]
    assert by["b.jpg"]["review"] is False  # missing GPS is not a defect to review
    assert by["c.jpg"]["review"] is True
    assert any("prefetch --gps-from" in r for r in by["c.jpg"]["review_reasons"])
    assert ["WildID", "review"] in [kw["path"] for kw in by["c.jpg"]["suggested_keywords"]]


def test_geo_auto_is_cache_only_without_offline(fake, kenya_cell, trip, monkeypatch, capsys):
    """ADR 0006: classify never resolves a cell online; only prefetch does."""
    import wildid.geo

    def no_network(self, path, **params):
        raise AssertionError(f"classify must not call iNaturalist ({path})")

    monkeypatch.setattr(wildid.geo.INatClient, "get", no_network)
    assert main([str(trip), "--geo-auto", "--format", "json"]) == 0
    captured = capsys.readouterr()
    by = {r["label"]: r for r in json.loads(captured.out)["results"]}
    assert by["a.jpg"]["place"]["label"] == "Kenya"  # the cached cell still filters
    assert by["c.jpg"]["place"]["label"] is None and by["c.jpg"]["review"] is True
    assert any("prefetch --gps-from" in r for r in by["c.jpg"]["review_reasons"])
    assert "1 photo(s) in cell(s) nobody prefetched" in captured.err  # the run's summary says so


def test_geo_auto_single_file_runs_anomaly_pass(fake, kenya_cell, trip, capsys):
    assert main([str(trip / "a.jpg"), "--geo-auto", "--offline"]) == 0
    out = capsys.readouterr().out
    assert "  place: Kenya (2 species)" in out and "unconstrained top-1: Ursus arctos" in out


def test_geo_auto_usage_errors(fake, trip, bear_jpg, tmp_path, capsys):
    assert main([str(trip), "--geo-auto", "--country", "Kenya"]) == 1
    assert "cannot be combined" in capsys.readouterr().err
    plain = tmp_path / "plain"
    plain.mkdir()
    shutil.copy(bear_jpg, plain / "x.jpg")
    assert main([str(plain), "--geo-auto", "--offline"]) == 1
    assert "carries GPS" in capsys.readouterr().err


def test_sidecar_carries_the_photo_place_not_the_run_place(tmp_path):
    """Per-photo place wins over the writer's run-level label; a no-place photo gets none."""
    from wildid.autogeo import annotate
    from wildid.output import CandidateInfo, Prediction
    from wildid.pipeline import FileResult
    from wildid.xmp import SidecarWriter

    results = []
    for name in ("a.arw", "b.arw"):
        (tmp_path / name).write_bytes(b"raw")
        results.append(
            FileResult(
                path=tmp_path / name,
                label=name,
                ok=True,
                predictions=[Prediction("Panthera leo", "Lion", 0.9, taxon_class="Mammalia")],
            )
        )
    annotate(results[:1], CandidateInfo(count=2, place_label="Kenya"), None, False)
    annotate(results[1:], None, "no GPS in the file", False)
    writer = SidecarWriter(model="bioclip-2")
    assert [writer.process(fr) for fr in results] == ["written", "written"]
    assert "Kenya" in (tmp_path / "a.xmp").read_text(encoding="utf-8")
    assert "Kenya" not in (tmp_path / "b.xmp").read_text(encoding="utf-8")


class FakeINatForPrefetch:
    """places/nearby -> the Mara payload; species_counts -> two mammals, nothing else."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, path, **params):
        self.calls.append(path)
        if path == "places/nearby":
            return NEARBY
        if path == "observations/species_counts":
            if params.get("iconic_taxa") == "Mammalia":
                return {
                    "total_results": 2,
                    "results": [
                        {"taxon": {"rank": "species", "name": "Panthera leo"}},
                        {"taxon": {"rank": "species", "name": "Acinonyx jubatus"}},
                    ],
                }
            return {"total_results": 0, "results": []}
        raise AssertionError(path)


def test_prefetch_gps_resolves_cells_and_fetches_lists(isolated_cache, monkeypatch):
    import wildid.geo
    from wildid.prefetch import prefetch_gps

    client = FakeINatForPrefetch()
    monkeypatch.setattr(wildid.geo, "INatClient", lambda: client)
    lists = prefetch_gps([(-1.4, 35.2), (-1.45, 35.24), (-1.6, 35.2)], "country", "Mammalia,Aves")
    assert [lst.label for lst in lists] == ["Kenya"]  # two cells, one place, fetched once
    assert lists[0].species == ["Panthera leo", "Acinonyx jubatus"]
    assert client.calls.count("places/nearby") == 2  # one lookup per distinct cell
    cache = GeoCache(isolated_cache / "geo")
    assert cache.load_place(place_cache_key(-1.6, 35.2, "country")).place.id == 7042


def test_prefetch_gps_from_without_gps_exits_1(monkeypatch, tmp_path, bear_jpg, capsys):
    import wildid.prefetch

    monkeypatch.setattr(wildid.prefetch, "prefetch_model", lambda name: [])
    shutil.copy(bear_jpg, tmp_path / "x.jpg")
    assert main(["prefetch", "--gps-from", str(tmp_path), "--no-verify"]) == 1
    assert "carries GPS" in capsys.readouterr().err
