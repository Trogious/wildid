from __future__ import annotations

import time
from pathlib import Path

import pytest
from PIL import Image

from wildid.images import (
    discover,
    iter_loaded_chunks,
    load_image,
    load_many,
    normalise_extensions,
)


def _jpeg(path: Path, size=(64, 48), color=(200, 120, 40), **save_kw) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, "JPEG", **save_kw)
    return path


def test_normalise_extensions():
    assert normalise_extensions("jpg, .JPEG,arw,,") == {"jpg", "jpeg", "arw"}
    assert normalise_extensions([".ARW"]) == {"arw"}
    assert normalise_extensions("") == set()


def test_discover_is_recursive_sorted_and_skips_hidden(tmp_path):
    _jpeg(tmp_path / "b.jpg")
    _jpeg(tmp_path / "B.JPEG")
    _jpeg(tmp_path / "sub" / "e.ARW")
    _jpeg(tmp_path / ".hidden" / "c.jpg")
    _jpeg(tmp_path / "__MACOSX" / "d.jpg")
    _jpeg(tmp_path / ".dotfile.jpg")
    (tmp_path / "x.png").write_bytes(b"not an image")
    found = discover(tmp_path, "jpg,jpeg,arw")
    assert [p.relative_to(tmp_path).as_posix() for p in found] == ["B.JPEG", "b.jpg", "sub/e.ARW"]


def test_discover_file_returns_itself(bear_jpg):
    assert discover(bear_jpg, ["jpg"]) == [bear_jpg]


def test_discover_missing_path_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        discover(tmp_path / "nope", ["jpg"])


def test_load_jpeg_fixture(bear_jpg):
    res = load_image(bear_jpg)
    assert res.ok and res.error is None
    assert res.source == "jpeg"
    assert res.image.mode == "RGB"
    assert res.image.size == (640, 432)


def test_load_jpeg_applies_exif_orientation(tmp_path):
    exif = Image.Exif()
    exif[274] = 6  # rotate 270 CW on display: a 100x50 file shows as 50x100
    p = _jpeg(tmp_path / "rot.jpg", size=(100, 50), exif=exif.tobytes())
    res = load_image(p)
    assert res.ok
    assert res.image.size == (50, 100)


def test_load_jpeg_decodes_large_files_at_reduced_scale(tmp_path):
    p = _jpeg(tmp_path / "big.jpg", size=(4096, 3072))
    res = load_image(p)
    assert res.ok
    # draft mode: largest DCT reduction that keeps both sides >= MAX_DECODE_PX (1024)
    assert res.image.size == (2048, 1536)


def test_load_image_never_raises(tmp_path):
    p = tmp_path / "broken.jpg"
    p.write_bytes(b"\xff\xd8garbage")
    res = load_image(p)
    assert not res.ok
    assert res.image is None
    assert res.error and ":" in res.error


def test_load_many_and_chunks_preserve_order(tmp_path):
    paths = [_jpeg(tmp_path / f"{i:02d}.jpg", color=(i, i, i)) for i in range(10)]
    bad = tmp_path / "05.jpg"
    bad.write_bytes(b"nope")
    results = load_many(paths, workers=4)
    assert [r.path for r in results] == paths
    assert [r.ok for r in results] == [i != 5 for i in range(10)]
    chunks = list(iter_loaded_chunks(paths, chunk_size=4, workers=4))
    assert [len(c) for c in chunks] == [4, 4, 2]
    assert [r.path for c in chunks for r in c] == paths


def test_load_arw_uses_embedded_preview(arw_fixture):
    t0 = time.perf_counter()
    res = load_image(arw_fixture)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert res.ok, res.error
    assert res.source == "raw-preview"
    assert res.image.mode == "RGB"
    assert min(res.image.size) >= 224
    assert elapsed_ms < 1500, f"ARW load took {elapsed_ms:.0f} ms"


RAW_SAMPLES = sorted((Path(__file__).parent / "fixtures" / "raw").glob("*"))


@pytest.mark.parametrize("raw_path", RAW_SAMPLES, ids=[p.name for p in RAW_SAMPLES])
def test_load_other_raw_formats_via_preview(raw_path):
    """CC0 samples from raw.pixls.us, git-ignored; one per format (nef, cr2, cr3, orf, raf, rw2,
    dng from a drone, a phone and a Leica)."""
    res = load_image(raw_path)
    assert res.ok, res.error
    assert res.image.mode == "RGB"
    assert min(res.image.size) >= 256
    assert res.source in ("raw-preview", "raw-demosaic")


def test_raw_samples_present_or_skipped():
    if not RAW_SAMPLES:
        pytest.skip("no RAW samples in tests/fixtures/raw/")


def test_default_extensions_include_all_raw_formats_case_insensitively(tmp_path):
    from wildid.constants import DEFAULT_EXTENSIONS

    for name in ("a.NEF", "b.cr3", "c.Cr2", "d.ORF", "e.raf", "f.RW2", "g.dng", "h.ARW"):
        (tmp_path / name).write_bytes(b"x")
    found = discover(tmp_path, DEFAULT_EXTENSIONS)
    assert [p.name for p in found] == [
        "a.NEF",
        "b.cr3",
        "c.Cr2",
        "d.ORF",
        "e.raf",
        "f.RW2",
        "g.dng",
        "h.ARW",
    ]


def test_max_px_bounds_decoded_size(tmp_path):
    p = _jpeg(tmp_path / "big.jpg", size=(4096, 3072))
    res = load_image(p, max_px=1200)
    assert res.ok and max(res.image.size) == 1200


def test_post_hook_runs_on_the_decoded_image(bear_jpg):
    res = load_image(bear_jpg, post=lambda im: im.resize((10, 10)))
    assert res.ok and res.image.size == (10, 10)
    assert res.size == (640, 432)  # decoded size is kept for logging

    def boom(im):
        raise ValueError("bad transform")

    res = load_image(bear_jpg, post=boom)
    assert not res.ok and "bad transform" in res.error
