"""Auto-geo from EXIF GPS (plan B3, MVP backlog item 5).

A photo's GPS position is turned into an iNaturalist place — the country (admin level 0) or
the state/province (admin level 10) containing it — through `GET /v1/places/nearby`, and the
species list for that place then constrains the classifier exactly like `--country` does.
Positions are cached per grid cell (GPS_CELL_DEG) so a trip costs a handful of lookups; the
classify path reads the cache and, as everywhere in wildid, `--offline` forbids the network.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from wildid.geo import (
    ADMIN_COUNTRY,
    ADMIN_STATE,
    GeoCache,
    GeoError,
    INatClient,
    Place,
    ResolvedPlace,
)

log = logging.getLogger(__name__)

GPS_CELL_DEG = 0.25  # cache grid; a cell is about 28 km across at the equator
GPS_LEVELS: tuple[str, ...] = ("country", "region")
DEFAULT_GPS_LEVEL = "country"
NEARBY_HALF_DEG = 0.0005  # the query box around a point (the endpoint wants a bounding box)

Coords = tuple[float, float]


# ----------------------------------------------------------------------------------------------
# EXIF
# ----------------------------------------------------------------------------------------------


def _dms(tag) -> float | None:
    """EXIF degrees/minutes/seconds rationals -> decimal degrees."""
    try:
        values = list(tag.values)
    except AttributeError:
        return None
    parts: list[float] = []
    for ratio in values[:3]:
        num = getattr(ratio, "num", None)
        den = getattr(ratio, "den", None)
        if num is None or den is None:
            try:
                parts.append(float(ratio))
                continue
            except (TypeError, ValueError):
                return None
        if den == 0:
            return None
        parts.append(num / den)
    if not parts:
        return None
    parts += [0.0] * (3 - len(parts))
    return parts[0] + parts[1] / 60.0 + parts[2] / 3600.0


def read_gps(path: Path) -> Coords | None:
    """Decimal (latitude, longitude) from the file's EXIF, or None.

    None covers: no GPS tags, a (0, 0) fix some bodies write without a lock, containers
    exifread cannot parse (CR3), unreadable files. Never raises."""
    import exifread  # pure Python; parses JPEG and the TIFF-based RAWs (ARW, NEF, CR2, DNG…)

    try:
        with open(path, "rb") as fd:
            tags = exifread.process_file(fd, details=False)
    except Exception:  # noqa: BLE001 - any parse failure just means "no GPS here"
        return None
    lat = _dms(tags.get("GPS GPSLatitude"))
    lon = _dms(tags.get("GPS GPSLongitude"))
    if lat is None or lon is None:
        return None
    if str(tags.get("GPS GPSLatitudeRef", "N")).strip().upper().startswith("S"):
        lat = -lat
    if str(tags.get("GPS GPSLongitudeRef", "E")).strip().upper().startswith("W"):
        lon = -lon
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or (lat == 0.0 and lon == 0.0):
        return None
    return (lat, lon)


def scan_gps(paths: Iterable[Path]) -> dict[Path, Coords | None]:
    """GPS per file, in input order (None where there is none)."""
    return {Path(p): read_gps(Path(p)) for p in paths}


# ----------------------------------------------------------------------------------------------
# cells and places
# ----------------------------------------------------------------------------------------------


def cell_of(lat: float, lon: float, step: float = GPS_CELL_DEG) -> Coords:
    """South-west corner of the grid cell containing the point."""
    return (math.floor(lat / step) * step, math.floor(lon / step) * step)


def cell_key(lat: float, lon: float) -> str:
    clat, clon = cell_of(lat, lon)
    return f"gps:{clat:.2f},{clon:.2f}"


def place_cache_key(lat: float, lon: float, level: str) -> str:
    return f"{cell_key(lat, lon)}:{level}"


def distinct_cells(points: Iterable[Coords]) -> list[Coords]:
    """One representative point per grid cell, in first-seen order."""
    seen: dict[str, Coords] = {}
    for lat, lon in points:
        seen.setdefault(cell_key(lat, lon), (lat, lon))
    return list(seen.values())


def _standard_rows(payload: dict) -> list[dict]:
    results = payload.get("results")
    if isinstance(results, dict):
        return list(results.get("standard") or [])
    if isinstance(results, list):
        return results
    return []


def pick_place(rows: list[dict], level: str) -> tuple[Place | None, str | None]:
    """The admin place for `level` among the nearby rows: the state/province (admin 10) for
    "region" — falling back to the country — or the country (admin 0). Returns (place,
    country_name) with the smallest bounding box winning among several candidates."""
    if level not in GPS_LEVELS:
        raise GeoError(f"unknown GPS level {level!r}; choose from {', '.join(GPS_LEVELS)}")
    countries = [r for r in rows if r.get("admin_level") == ADMIN_COUNTRY]
    country_name = countries[0].get("name") if countries else None
    wanted = ADMIN_STATE if level == "region" else ADMIN_COUNTRY
    candidates = [r for r in rows if r.get("admin_level") == wanted]
    if not candidates and level == "region":
        candidates = countries
    if not candidates:
        return None, country_name
    best = min(candidates, key=lambda r: float(r.get("bbox_area") or math.inf))
    return Place.from_api(best), country_name


def resolve_gps_place(
    lat: float,
    lon: float,
    level: str = DEFAULT_GPS_LEVEL,
    *,
    cache: GeoCache | None = None,
    client: INatClient | None = None,
    offline: bool = False,
) -> ResolvedPlace:
    """The place for a position, cache-first per grid cell; online only with a client."""
    cache = cache or GeoCache()
    key = place_cache_key(lat, lon, level)
    cached = cache.load_place(key)
    if cached:
        return cached
    if offline or client is None:
        raise GeoError(
            f"no cached place for GPS cell {cell_key(lat, lon)} ({level} level)",
            needs_prefetch=True,
        )
    h = NEARBY_HALF_DEG
    payload = client.get(
        "places/nearby",
        nelat=f"{lat + h:.5f}",
        nelng=f"{lon + h:.5f}",
        swlat=f"{lat - h:.5f}",
        swlng=f"{lon - h:.5f}",
        per_page=50,
    )
    place, country_name = pick_place(_standard_rows(payload), level)
    if place is None:
        raise GeoError(f"iNaturalist has no {level}-level place around {lat:.3f}, {lon:.3f}")
    if level == "region" and country_name and place.admin_level == ADMIN_STATE:
        label = f"{country_name} \u203a {place.name}"
    else:
        label = place.name
    resolved = ResolvedPlace(place=place, label=label)
    cache.save_place(key, resolved)
    log.info("GPS cell %s -> %s (place %d)", cell_key(lat, lon), label, place.id)
    return resolved


# ----------------------------------------------------------------------------------------------
# grouping photos by place
# ----------------------------------------------------------------------------------------------

NO_GPS = "no-gps"


@dataclass
class GpsGroup:
    """Photos that share one place (or share having no usable place)."""

    key: str  # cache key of the cell+level, or NO_GPS
    resolved: ResolvedPlace | None
    paths: list[Path] = field(default_factory=list)
    note: str | None = None  # why there is no place (no GPS / not prefetched)
    actionable: bool = False  # the note is fixable by prefetching -> flag the photos


def group_by_place(
    gps: Mapping[Path, Coords | None],
    level: str = DEFAULT_GPS_LEVEL,
    *,
    cache: GeoCache | None = None,
    client: INatClient | None = None,
    offline: bool = True,
) -> list[GpsGroup]:
    """Partition photos by the place their GPS resolves to, in first-seen order. Photos
    without GPS form one group; cells that cannot be resolved (cache miss while offline, or
    an iNaturalist error) form one group each, marked actionable when prefetch would fix it."""
    cache = cache or GeoCache()
    groups: dict[str, GpsGroup] = {}
    for path, coords in gps.items():
        if coords is None:
            group = groups.get(NO_GPS)
            if group is None:
                group = GpsGroup(key=NO_GPS, resolved=None, note="no GPS in the file")
                groups[NO_GPS] = group
            group.paths.append(path)
            continue
        lat, lon = coords
        key = place_cache_key(lat, lon, level)
        group = groups.get(key)
        if group is None:
            try:
                resolved = resolve_gps_place(
                    lat, lon, level, cache=cache, client=client, offline=offline
                )
                group = GpsGroup(key=key, resolved=resolved)
            except GeoError as exc:
                group = GpsGroup(
                    key=key, resolved=None, note=str(exc), actionable=exc.needs_prefetch
                )
            groups[key] = group
        group.paths.append(path)
    return list(groups.values())
