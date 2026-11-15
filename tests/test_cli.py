"""CLI flow tests with a fake classifier: no model, no GPU, no network."""

from __future__ import annotations

import json
import shutil
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from wildid import __version__
from wildid.cli import main
from wildid.output import Prediction


class FakeClassifier:
    def __init__(self):
        self.spec = SimpleNamespace(name="fake")
        self.device = "cpu"
        self.candidate_count = 1000
        self.total_taxa = 1000
        self.filter_species = None
        self.place_label = None
        self.anomaly_check = False
        self.calls: list[tuple[int, int, int]] = []
        self.sizes: list[tuple[int, int]] = []
        self.precision = "fp32"
        self.preshrink = None
        self.known_species = frozenset({"Ursus arctos", "Ursus americanus", "Taurotragus oryx"})
        self.known_genera = frozenset({"Ursus", "Taurotragus"})
        self.synonyms = {}
        self.applied = None
        self.applied_genera = None

    def apply_species_filter(self, species):
        self.applied = list(species)
        self.filter_species = list(species)
        return len(species)

    def clear_filter(self):
        self.filter_species = None

    def apply_genus_filter(self, genera):
        self.applied_genera = list(genera)
        self.filter_species = [s for s in self.known_species if s.split()[0] in genera]
        return len(self.filter_species)

    def prepare_inputs(self, images):
        return list(images)

    def apply_precision(self, mode):
        self.precision = "tf32" if mode == "auto" else mode
        return self.precision

    def predict(self, images, k, batch_size, progress=None):
        self.calls.append((len(images), k, batch_size))
        self.sizes.extend(im.size for im in images)
        if progress is not None:
            progress(len(images), len(images))
        rows = [
            Prediction("Ursus arctos", "Brown bear", 0.9, genus="Ursus", family="Ursidae"),
            Prediction("Ursus americanus", "American black bear", 0.05),
            Prediction("Ursus maritimus", "Polar bear", 0.01),
            Prediction("Gulo gulo", "Wolverine", 0.005),
            Prediction("Canis lupus", "Grey wolf", 0.001),
        ]
        return [rows[:k] for _ in images]

    @contextmanager
    def unfiltered(self):
        yield


@pytest.fixture
def fake(monkeypatch):
    import wildid.model  # heavy, but the real module must exist for the lazy import to resolve

    clf = FakeClassifier()
    monkeypatch.setattr(wildid.model, "load_classifier", lambda name, device: clf)
    return clf


def test_version(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"wildid {__version__}"


def test_usage_error_exits_1(capsys):
    assert main(["--bogus"]) == 1
    assert main([]) == 1


def test_single_file(fake, bear_jpg, capsys):
    assert main([str(bear_jpg)]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[0] == (
        f"wildid {__version__} | model=fake device=cpu precision=tf32 | "
        "candidates=full TreeOfLife (1,000 taxa)"
    )
    assert out[1].startswith("note: scores are a softmax")
    assert out[2] == "bear.jpg"
    assert out[3].startswith("  1. Ursus arctos")
    assert len(out) == 3 + 5  # top 5 for a file
    assert fake.calls == [(1, 5, 1)]


def test_explicit_classify_subcommand_is_equivalent(fake, bear_jpg, capsys):
    assert main(["classify", str(bear_jpg), "--k", "2"]) == 0
    assert fake.calls == [(1, 2, 1)]


def test_directory_top3_and_failure_summary(fake, bear_jpg, tmp_path, capsys):
    for name in ("a.jpg", "sub/b.JPG", "c.arw"):
        dst = tmp_path / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(bear_jpg, dst)
    (tmp_path / "broken.jpg").write_bytes(b"\xff\xd8nope")
    assert main([str(tmp_path), "--batch-size", "2"]) == 0
    captured = capsys.readouterr()
    out = captured.out.splitlines()
    labels = [line for line in out if line and not line.startswith(("  ", "wildid", "note:"))]
    assert labels == ["a.jpg", "sub/b.JPG"]  # c.arw is a JPEG in disguise -> rawpy fails on it
    assert sum(1 for line in out if line.startswith("  1. ")) == 2
    assert all(call[1] == 3 for call in fake.calls)  # top 3 per file in directory mode
    assert all(call[2] == 2 for call in fake.calls)
    assert "2 file(s) could not be loaded:" in captured.err
    assert "broken.jpg" in captured.err and "c.arw" in captured.err


def test_directory_all_failed_exits_3(fake, tmp_path, capsys):
    (tmp_path / "broken.jpg").write_bytes(b"\xff\xd8nope")
    assert main([str(tmp_path)]) == 3


def test_no_images_exits_1(fake, tmp_path, capsys):
    assert main([str(tmp_path)]) == 1
    assert "no images" in capsys.readouterr().err


def test_unsupported_extension_exits_1(fake, tmp_path, capsys):
    p = tmp_path / "x.png"
    p.write_bytes(b"")
    assert main([str(p)]) == 1
    assert "extension not in --ext" in capsys.readouterr().err


def test_missing_model_cache_exits_2_with_prefetch_hint(monkeypatch, bear_jpg, capsys):
    import wildid.model
    from wildid.model import ModelLoadError

    def boom(name, device):
        raise ModelLoadError("bioclip-2 is not in the local cache", missing_cache=True)

    monkeypatch.setattr(wildid.model, "load_classifier", boom)
    assert main([str(bear_jpg)]) == 2
    err = capsys.readouterr().err
    assert "wildid prefetch --model bioclip-2" in err


def test_single_file_load_failure_exits_3(fake, tmp_path, capsys):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"\xff\xd8nope")
    assert main([str(p)]) == 3


def test_setup_requires_a_terminal(capsys):
    # pytest replaces stdin with a non-tty object, so the guard trips without monkeypatching.
    assert main(["setup"]) == 1
    assert "interactive" in capsys.readouterr().err


def test_geo_prefetch_command_and_specs():
    from wildid.cli import _geo_specs, geo_prefetch_command

    cmd = geo_prefetch_command(None, "Brazil", "Mato Grosso", None, "Mammalia,Reptilia")
    assert cmd == 'wildid prefetch --country Brazil --region "Mato Grosso" --taxa Mammalia,Reptilia'
    default_taxa = "Mammalia,Reptilia,Amphibia,Aves"
    assert geo_prefetch_command("South America", None, None, None, default_taxa) == (
        'wildid prefetch --continent "South America"'
    )
    assert (
        geo_prefetch_command(None, None, None, 8239, default_taxa)
        == "wildid prefetch --place-id 8239"
    )
    specs = _geo_specs(["Africa"], ["Madagascar", "Thailand"], ["", "Nakhon Ratchasima"], [8239])
    assert specs == [
        {"country": "Madagascar", "region": None},
        {"country": "Thailand", "region": "Nakhon Ratchasima"},
        {"continent": "Africa"},
        {"place_id": 8239},
    ]
    import typer

    with pytest.raises(typer.Exit):
        _geo_specs([], ["Madagascar"], ["A", "B"], [])


class FakeDetector:
    def __init__(self, hit=True):
        self.hit = hit
        self.seen: list[tuple[int, int]] = []
        self.exact: list[bool] = []  # the `exact` flag of each detect() call

    def detect(self, images, *, exact=False):
        from wildid.detector import Detection

        self.exact.append(exact)
        self.seen.extend(im.size for im in images)
        return [Detection(10, 10, 110, 60, 0.93) if self.hit else None for _ in images]


class FakeSpeciesNet:
    def classify(self, images, k=1):
        from wildid.speciesnet import Label

        bear = Label.parse("x;mammalia;carnivora;ursidae;ursus;arctos;brown bear")
        return [[(bear, 0.88)] for _ in images]


@pytest.fixture
def fake_stages(monkeypatch):
    import wildid.detector
    import wildid.speciesnet

    det = FakeDetector()
    monkeypatch.setattr(wildid.detector.Detector, "load", classmethod(lambda cls, n, d: det))
    monkeypatch.setattr(
        wildid.speciesnet.SpeciesNet,
        "load",
        classmethod(lambda cls, d, model_dir=None: FakeSpeciesNet()),
    )
    return det


def test_crop_feeds_the_classifier_a_crop(fake, fake_stages, bear_jpg, capsys):
    assert main([str(bear_jpg), "--crop", "--k", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert fake_stages.seen == [(640, 432)]  # the detector saw the full frame
    assert fake.sizes == [(224, 224)]  # the classifier saw the crop (grown to the 224 minimum)
    assert out[-1] == "  crop: animal 0.93 \u2192 224\u00d7224 px"


def test_crop_without_detection_uses_full_frame(fake, fake_stages, bear_jpg, capsys):
    fake_stages.hit = False
    assert main([str(bear_jpg), "--crop", "--k", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert fake.sizes == [(640, 432)]
    assert out[-1] == "  crop: no animal detected, full frame used"


def test_second_opinion_implies_crop_and_prints_verdict(fake, fake_stages, bear_jpg, capsys):
    assert main([str(bear_jpg), "--second-opinion", "--k", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[-2].startswith("  crop: animal 0.93")
    assert out[-1] == "  speciesnet: Ursus arctos \u2014 brown bear (0.880)  agrees"


def test_second_opinion_in_directory_mode(fake, fake_stages, bear_jpg, tmp_path, capsys):
    shutil.copy(bear_jpg, tmp_path / "a.jpg")
    shutil.copy(bear_jpg, tmp_path / "b.jpg")
    assert main([str(tmp_path), "--second-opinion"]) == 0
    out = capsys.readouterr().out
    assert out.count("  speciesnet: Ursus arctos") == 2 and out.count("  crop: animal") == 2


def test_crop_exact_reaches_the_detector_and_is_off_by_default(fake, fake_stages, bear_jpg):
    assert main([str(bear_jpg), "--crop", "--k", "1"]) == 0
    assert main([str(bear_jpg), "--crop", "--crop-exact", "--k", "1"]) == 0
    assert main([str(bear_jpg), "--second-opinion", "--crop-exact", "--k", "1"]) == 0
    assert fake_stages.exact == [False, True, True]


def test_crop_exact_in_directory_mode_and_in_the_run_document(
    fake, fake_stages, bear_jpg, tmp_path, capsys
):
    shutil.copy(bear_jpg, tmp_path / "a.jpg")
    shutil.copy(bear_jpg, tmp_path / "b.jpg")
    seen = []
    for flags in ([], ["--crop"], ["--crop", "--crop-exact"]):
        assert main([str(tmp_path), "--format", "json", *flags]) == 0
        seen.append(json.loads(capsys.readouterr().out)["crop_resize"])
    assert seen == [None, "linear", "exact"]
    assert fake_stages.exact == [False, True]  # one detect() call per run with the crop


def test_crop_exact_without_crop_is_a_usage_error(fake, fake_stages, bear_jpg, capsys):
    assert main([str(bear_jpg), "--crop-exact"]) == 1
    assert "--crop-exact needs --crop" in capsys.readouterr().err
    assert fake.calls == [] and fake_stages.exact == []  # nothing ran


def test_missing_detector_weights_exit_2_with_hint(fake, monkeypatch, bear_jpg, capsys):
    import wildid.detector
    from wildid.detector import DetectorLoadError

    def boom(cls, name, device):
        raise DetectorLoadError("detector weights are not in the local cache", missing_cache=True)

    monkeypatch.setattr(wildid.detector.Detector, "load", classmethod(boom))
    assert main([str(bear_jpg), "--crop"]) == 2
    assert "wildid prefetch --crop --detector mdv6-yolov9-c" in capsys.readouterr().err


def test_precision_flag_reaches_the_classifier(fake, bear_jpg, capsys):
    assert main([str(bear_jpg), "--precision", "fp16"]) == 0
    assert fake.precision == "fp16"
    assert "precision=fp16" in capsys.readouterr().out.splitlines()[0]


@pytest.fixture
def kenya_cache(isolated_cache):
    """A geo cache with a resolved place, species lists and one GBIF synonym, no network."""
    import json
    from datetime import UTC, datetime

    from wildid.geo import GeoCache, Place, ResolvedPlace

    cache = GeoCache(isolated_cache / "geo")
    place = Place(7042, "Kenya", "Kenya", 0, (97392, 7042))
    cache.save_place("country:kenya", ResolvedPlace(place=place, label="Kenya"))
    for taxon, species in {
        "Mammalia": ["Ursus arctos", "Tragelaphus oryx", "Lupulella mesomelas"],
        "Reptilia": [],
        "Amphibia": [],
        "Aves": [],
    }.items():
        cache.save_species(
            {
                "place_id": 7042,
                "taxon": taxon,
                "fetched_at": datetime.now(UTC),
                "total_results": len(species),
                "species": species,
            }
        )
    cache.names_path.parent.mkdir(parents=True, exist_ok=True)
    cache.names_path.write_text(
        json.dumps(
            {
                "Tragelaphus oryx": {
                    "accepted": "Taurotragus oryx",
                    "candidates": ["Taurotragus oryx"],
                }
            }
        )
    )
    return cache


def test_geo_filter_from_cache_with_synonym_mapping(fake, kenya_cache, bear_jpg, capsys):
    assert main([str(bear_jpg), "--country", "Kenya", "--offline", "--k", "1"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert "candidates=2 species (Kenya; Mammalia,Reptilia,Amphibia,Aves; fetched" in out[0]
    assert fake.applied == ["Ursus arctos", "Taurotragus oryx"]  # the synonym was mapped
    assert fake.synonyms["Tragelaphus oryx"] == "Taurotragus oryx"
    assert out[-1].startswith("  unconstrained top-1: Ursus arctos")


def test_geo_rank_genus_widens_to_whole_genera(fake, kenya_cache, bear_jpg, capsys):
    assert main([str(bear_jpg), "--country", "Kenya", "--offline", "--geo-rank", "genus"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert fake.applied_genera == ["Ursus", "Taurotragus"]  # Lupulella unknown to the model
    assert "candidates=3 species (Kenya, genus level;" in out[0]
