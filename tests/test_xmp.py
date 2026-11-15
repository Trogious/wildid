"""XMP sidecars: fresh render, safe merge, writer modes, CLI wiring. No photos, no network."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from wildid.output import Prediction
from wildid.pipeline import FileResult
from wildid.xmp import (
    DC,
    LR,
    RDF,
    WILDID,
    SidecarWriter,
    content_for,
    merge_into,
    render_new,
    sidecar_path,
    sidecar_supported,
)

JAGUAR = Prediction(
    "Panthera onca", "Jaguar", 0.962, genus="Panthera", family="Felidae", taxon_class="Mammalia"
)


def result(path="DSC04512.ARW", score=0.962, in_candidates=None) -> FileResult:
    pred = Prediction(
        JAGUAR.species,
        JAGUAR.common_name,
        score,
        genus=JAGUAR.genus,
        family=JAGUAR.family,
        taxon_class=JAGUAR.taxon_class,
    )
    return FileResult(
        path=Path(path),
        label=Path(path).name,
        ok=True,
        predictions=[pred],
        in_candidates=in_candidates,
    )


LR_SIDECAR = """<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" x:xmptk="Adobe XMP Core 7.0-c000">
 <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
  <rdf:Description rdf:about=""
    xmlns:xmp="http://ns.adobe.com/xap/1.0/"
    xmlns:crs="http://ns.adobe.com/camera-raw-settings/1.0/"
    xmlns:dc="http://purl.org/dc/elements/1.1/"
    xmp:Rating="3"
    crs:Version="15.0"
    crs:Exposure2012="+0.35"
    crs:WhiteBalance="As Shot">
   <dc:subject>
    <rdf:Bag>
     <rdf:li>Pantanal</rdf:li>
    </rdf:Bag>
   </dc:subject>
  </rdf:Description>
 </rdf:RDF>
</x:xmpmeta>
<?xpacket end="w"?>
"""


def bag_values(root: ET.Element, tag: str) -> list[str]:
    el = root.find(f".//{tag}")
    assert el is not None, f"no {tag} element"
    bag = el.find(f"{RDF}Bag")
    if bag is None:
        bag = el.find(f"{RDF}Seq")
    return [li.text for li in bag.findall(f"{RDF}li")]


def test_sidecar_path_and_support():
    assert sidecar_path(Path("a/DSC1.ARW")) == Path("a/DSC1.xmp")
    assert sidecar_supported(Path("x.ARW")) and sidecar_supported(Path("x.nef"))
    assert not sidecar_supported(Path("x.jpg"))
    assert not sidecar_supported(Path("x.DNG"))  # DNG embeds XMP; LR ignores a sidecar


def test_content_includes_keywords_synonym_and_provenance():
    c = content_for(result(), model="bioclip-2", place_label="Brazil › Mato Grosso")
    assert c.subjects == ("Panthera onca", "Jaguar", "animals", "wildlife")
    assert c.hierarchical == ("WildID|Mammalia|Panthera|Panthera onca", "animals", "wildlife")
    assert c.provenance["Species"] == "Panthera onca"
    assert c.provenance["Score"] == "0.962"
    assert c.provenance["Place"] == "Brazil › Mato Grosso"
    assert c.provenance["Review"] == "False"


def test_review_adds_the_review_keyword():
    c = content_for(result(score=0.2), model="bioclip-2", place_label=None)
    assert "review" in c.subjects
    assert "WildID|review" in c.hierarchical
    assert c.provenance["Review"] == "True"
    assert "animals" not in c.subjects  # low score + no detector verdict = presence unproven


def test_render_new_is_valid_xmp_lightroom_can_read():
    c = content_for(result(), model="bioclip-2", place_label=None, run_at="2026-10-24T00:00:00Z")
    text = render_new(c)
    assert text.startswith('<?xpacket begin="﻿"')
    assert text.rstrip().endswith('<?xpacket end="w"?>')
    root = ET.fromstring(text)
    assert bag_values(root, f"{DC}subject") == ["Panthera onca", "Jaguar", "animals", "wildlife"]
    assert bag_values(root, f"{LR}hierarchicalSubject") == [
        "WildID|Mammalia|Panthera|Panthera onca",
        "animals",
        "wildlife",
    ]
    assert root.find(f".//{WILDID}ProcessedAt").text == "2026-10-24T00:00:00Z"


def test_merge_appends_and_preserves_develop_settings():
    c = content_for(result(), model="bioclip-2", place_label=None)
    merged = merge_into(LR_SIDECAR, c)
    root = ET.fromstring(merged)
    assert bag_values(root, f"{DC}subject") == [
        "Pantanal",
        "Panthera onca",
        "Jaguar",
        "animals",
        "wildlife",
    ]
    assert bag_values(root, f"{LR}hierarchicalSubject") == [
        "WildID|Mammalia|Panthera|Panthera onca",
        "animals",
        "wildlife",
    ]
    desc = root.find(f".//{RDF}Description")
    crs = "{http://ns.adobe.com/camera-raw-settings/1.0/}"
    assert desc.get(f"{crs}Exposure2012") == "+0.35"  # develop settings untouched
    assert desc.get(f"{crs}WhiteBalance") == "As Shot"
    assert desc.get("{http://ns.adobe.com/xap/1.0/}Rating") == "3"
    assert root.find(f".//{WILDID}Species").text == "Panthera onca"


def test_merge_is_idempotent():
    c = content_for(result(), model="bioclip-2", place_label=None)
    once = merge_into(LR_SIDECAR, c)
    twice = merge_into(once, c)
    root = ET.fromstring(twice)
    assert bag_values(root, f"{DC}subject") == [
        "Pantanal",
        "Panthera onca",
        "Jaguar",
        "animals",
        "wildlife",
    ]
    assert len(bag_values(root, f"{LR}hierarchicalSubject")) == 3


# Lightroom rewrites simple properties as attributes of rdf:Description when it saves a
# sidecar (Ctrl+S), so a previously merged wildid:* block comes back in attribute form.
LR_REWRITTEN_SIDECAR = LR_SIDECAR.replace(
    '    crs:WhiteBalance="As Shot">',
    '    crs:WhiteBalance="As Shot"\n'
    '    xmlns:wildid="http://ns.wildid.dev/xmp/1.0/"\n'
    '    wildid:Model="bioclip-2" wildid:Species="Felis catus" wildid:Score="0.500">',
)


def test_merge_updates_attribute_form_provenance_without_duplicating_it():
    c = content_for(result(), model="bioclip-2.5", place_label=None)
    merged = merge_into(LR_REWRITTEN_SIDECAR, c)
    root = ET.fromstring(merged)
    descs = root.findall(f".//{RDF}Description")
    attr = [d.get(f"{WILDID}Species") for d in descs if d.get(f"{WILDID}Species")]
    assert attr == ["Panthera onca"]  # the attribute was updated in place
    assert root.find(f".//{WILDID}Species") is None  # no element-form duplicate
    assert [d.get(f"{WILDID}Model") for d in descs if d.get(f"{WILDID}Model")] == ["bioclip-2.5"]
    assert merged.count("Felis catus") == 0
    # keys that were not present before are added (element form is fine for Lightroom)
    assert root.find(f".//{WILDID}CommonName").text == "Jaguar"


def test_merge_rejects_broken_xml():
    from wildid.xmp import SidecarError

    with pytest.raises(SidecarError):
        merge_into("<not-xmp>", content_for(result(), model="m", place_label=None))


def test_writer_new_only_skips_existing(tmp_path):
    arw = tmp_path / "a.arw"
    arw.write_bytes(b"raw")
    existing = tmp_path / "a.xmp"
    existing.write_text(LR_SIDECAR, encoding="utf-8")
    w = SidecarWriter(model="bioclip-2")
    assert w.process(result(str(arw))) == "skipped"
    assert existing.read_text(encoding="utf-8") == LR_SIDECAR  # untouched
    assert w.skipped == 1 and w.written == 0
    assert "--xmp-mode merge" in w.summary()


def test_writer_merge_mode_updates_existing(tmp_path):
    arw = tmp_path / "a.arw"
    arw.write_bytes(b"raw")
    (tmp_path / "a.xmp").write_text(LR_SIDECAR, encoding="utf-8")
    w = SidecarWriter(mode="merge", model="bioclip-2")
    assert w.process(result(str(arw))) == "merged"
    merged = (tmp_path / "a.xmp").read_text(encoding="utf-8")
    assert "Panthera onca" in merged and "Pantanal" in merged and "crs:Exposure2012" in merged


def test_writer_creates_fresh_sidecar_and_dry_run_does_not(tmp_path):
    arw = tmp_path / "b.nef"
    arw.write_bytes(b"raw")
    dry = SidecarWriter(dry_run=True, model="bioclip-2")
    assert dry.process(result(str(arw))) == "written"
    assert not (tmp_path / "b.xmp").exists()
    assert "dry run" in dry.summary()
    w = SidecarWriter(model="bioclip-2")
    assert w.process(result(str(arw))) == "written"
    text = (tmp_path / "b.xmp").read_text(encoding="utf-8")
    assert "Panthera onca" in text and "hierarchicalSubject" in text


def test_writer_counts_unsupported_and_rejects_bad_mode(tmp_path):
    jpg = tmp_path / "c.jpg"
    jpg.write_bytes(b"x")
    w = SidecarWriter(model="bioclip-2")
    assert w.process(result(str(jpg))) == "unsupported"
    assert w.unsupported == 1
    with pytest.raises(ValueError):
        SidecarWriter(mode="overwrite")


def test_cli_write_xmp_reports_unsupported_jpeg(fake_clf, bear_jpg, capsys):
    from wildid.cli import main

    assert main([str(bear_jpg), "--write-xmp"]) == 0
    captured = capsys.readouterr()
    assert "xmp sidecars:" in captured.err
    assert "1 unsupported" in captured.err
    assert not sidecar_path(bear_jpg).exists()


def test_cli_dry_run_requires_write_xmp(fake_clf, bear_jpg, capsys):
    from wildid.cli import main

    assert main([str(bear_jpg), "--dry-run"]) == 1
    assert "--dry-run only applies to --write-xmp" in capsys.readouterr().err


@pytest.fixture
def fake_clf(monkeypatch):
    from test_cli import FakeClassifier

    import wildid.model

    clf = FakeClassifier()
    monkeypatch.setattr(wildid.model, "load_classifier", lambda name, device: clf)
    return clf
