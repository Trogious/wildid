"""EXIF GPS reading, grid cells, place resolution and grouping. No network: a fake client."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from wildid.geo import GeoCache, GeoError, Place, ResolvedPlace
from wildid.gps import (
    NO_GPS,
    cell_key,
    cell_of,
    distinct_cells,
    group_by_place,
    pick_place,
    place_cache_key,
    read_gps,
    resolve_gps_place,
    scan_gps,
)

# the real shape of GET /v1/places/nearby for a Maasai Mara point (probed 2026-10-25)
NEARBY = {
    "total_results": 5,
    "results": {
        "standard": [
            {"id": 97392, "name": "Africa", "admin_level": -10, "bbox_area": 6941.8},
            {
                "id": 7042,
                "name": "Kenya",
                "admin_level": 0,
                "bbox_area": 78.8,
                "ancestor_place_ids": [97392, 7042],
            },
            {
                "id": 96954,
                "name": "Narok",
                "admin_level": 10,
                "bbox_area": 2.9,
                "ancestor_place_ids": [97392, 7042, 96954],
            },
            {"id": 101219, "name": "Narok West", "admin_level": 20, "bbox_area": 0.78},
        ],
        "community": [{"id": 69173, "name": "Masai Mara", "admin_level": None}],
    },
}


def write_gps_jpeg(path: Path, lat: float, lon: float, source: Path | None = None) -> Path:
    """A JPEG carrying an EXIF GPS IFD (Pillow writes DMS floats as rationals)."""
    img = Image.open(source).convert("RGB") if source else Image.new("RGB", (48, 32), (90, 120, 60))
    exif = Image.Exif()

    def dms(value: float) -> tuple[float, float, float]:
        value = abs(value)
        d = int(value)
        m = int((value - d) * 60)
        s = round(((value - d) * 60 - m) * 60, 4)
        return (float(d), float(m), float(s))

    exif[0x8825] = {
        1: "S" if lat < 0 else "N",
        2: dms(lat),
        3: "W" if lon < 0 else "E",
        4: dms(lon),
    }
    img.save(path, "JPEG", exif=exif)
    return path


class FakeINat:
    def __init__(self, payload=NEARBY):
        self.payload = payload
        self.calls: list[tuple[str, dict]] = []

    def get(self, path, **params):
        self.calls.append((path, params))
        return self.payload


def test_read_gps_signs_and_precision(tmp_path):
    p = write_gps_jpeg(tmp_path / "se.jpg", -1.4, 35.2)
    lat, lon = read_gps(p)
    assert lat == pytest.approx(-1.4, abs=1e-3) and lon == pytest.approx(35.2, abs=1e-3)
    p = write_gps_jpeg(tmp_path / "nw.jpg", 51.5, -0.12)
    lat, lon = read_gps(p)
    assert lat == pytest.approx(51.5, abs=1e-3) and lon == pytest.approx(-0.12, abs=1e-3)


def test_read_gps_absent_zero_and_unreadable(tmp_path, bear_jpg):
    assert read_gps(bear_jpg) is None  # the fixture carries no GPS
    assert read_gps(write_gps_jpeg(tmp_path / "zero.jpg", 0.0, 0.0)) is None
    assert read_gps(tmp_path / "missing.jpg") is None
    junk = tmp_path / "junk.arw"
    junk.write_bytes(b"not a tiff")
    assert read_gps(junk) is None
    assert scan_gps([bear_jpg]) == {bear_jpg: None}


def test_cells_and_keys():
    assert cell_of(-1.4, 35.2) == (-1.5, 35.0)
    assert cell_key(-1.4, 35.2) == "gps:-1.50,35.00"
    assert cell_key(-1.49, 35.24) == cell_key(-1.4, 35.2)  # same 0.25-degree cell
    assert cell_key(-1.51, 35.2) != cell_key(-1.4, 35.2)
    assert place_cache_key(-1.4, 35.2, "region") == "gps:-1.50,35.00:region"
    assert distinct_cells([(-1.4, 35.2), (-1.45, 35.21), (-1.6, 35.2)]) == [
        (-1.4, 35.2),
        (-1.6, 35.2),
    ]


def test_pick_place_levels():
    rows = NEARBY["results"]["standard"]
    place, country = pick_place(rows, "country")
    assert place.id == 7042 and place.name == "Kenya" and country == "Kenya"
    place, _ = pick_place(rows, "region")
    assert place.id == 96954 and place.admin_level == 10
    place, _ = pick_place([r for r in rows if r["admin_level"] != 10], "region")
    assert place.id == 7042  # no state around: fall back to the country
    assert pick_place([rows[0]], "country") == (None, None)
    with pytest.raises(GeoError):
        pick_place(rows, "county")


def test_resolve_gps_place_online_then_cached(isolated_cache):
    cache = GeoCache(isolated_cache / "geo")
    client = FakeINat()
    resolved = resolve_gps_place(-1.4, 35.2, "region", cache=cache, client=client)
    assert resolved.place.id == 96954 and resolved.label == "Kenya \u203a Narok"
    assert len(client.calls) == 1
    path, params = client.calls[0]
    assert path == "places/nearby"
    assert float(params["nelat"]) > -1.4 > float(params["swlat"])
    again = resolve_gps_place(-1.45, 35.24, "region", cache=cache, client=client)  # same cell
    assert again == resolved and len(client.calls) == 1
    country = resolve_gps_place(-1.4, 35.2, "country", cache=cache, client=client)
    assert country.place.id == 7042 and country.label == "Kenya" and len(client.calls) == 2


def test_resolve_gps_place_offline_miss_names_prefetch(isolated_cache):
    cache = GeoCache(isolated_cache / "geo")
    with pytest.raises(GeoError) as exc:
        resolve_gps_place(-1.4, 35.2, cache=cache, client=None, offline=True)
    assert exc.value.needs_prefetch
    with pytest.raises(GeoError):
        resolve_gps_place(-1.4, 35.2, cache=cache, client=FakeINat({"results": []}))


def test_group_by_place(isolated_cache):
    cache = GeoCache(isolated_cache / "geo")
    kenya = ResolvedPlace(Place(7042, "Kenya", "Kenya", 0, (97392, 7042)), "Kenya")
    cache.save_place(place_cache_key(-1.4, 35.2, "country"), kenya)
    gps = {
        Path("a.jpg"): (-1.4, 35.2),
        Path("b.jpg"): None,
        Path("c.jpg"): (-1.45, 35.24),  # same cell as a
        Path("d.jpg"): (10.0, 10.0),  # cell never resolved
    }
    groups = group_by_place(gps, "country", cache=cache, client=None, offline=True)
    assert [g.key for g in groups] == [
        place_cache_key(-1.4, 35.2, "country"),
        NO_GPS,
        "gps:10.00,10.00:country",
    ]
    assert groups[0].resolved == kenya and groups[0].paths == [Path("a.jpg"), Path("c.jpg")]
    assert groups[1].note == "no GPS in the file" and groups[1].actionable is False
    assert groups[2].resolved is None and groups[2].actionable is True
    assert "prefetch" in groups[2].note or "cached" in groups[2].note
