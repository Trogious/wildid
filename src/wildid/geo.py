"""Geo species lists from iNaturalist: place resolution, species fetch, disk cache, TreeOfLife
intersection and classifier mask (plan §5, D7–D9).

Network policy: every call goes through INatClient (descriptive User-Agent, ≥ 1 s between
requests, 5 s connect / 30 s read timeout). Results are cached on disk and a cached entry of any
age beats a network call; `offline=True` forbids the network entirely.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import requests

from wildid.constants import (
    CONTINENT_ALIASES,
    CONTINENT_PLACE_IDS,
    CONTINENTS,
    GEO_CACHE_MAX_AGE_DAYS,
    GEO_MIN_MATCHED_SPECIES,
    INAT_API,
    INAT_CONNECT_TIMEOUT_S,
    INAT_ICONIC_TAXA,
    INAT_PER_PAGE,
    INAT_READ_TIMEOUT_S,
    INAT_REQUEST_INTERVAL_S,
    INAT_RESULT_CAP,
    USER_AGENT,
    geo_cache_dir,
)

log = logging.getLogger(__name__)

ADMIN_COUNTRY = 0
ADMIN_STATE = 10
ADMIN_COUNTY = 20
ADMIN_CONTINENT = -10


class GeoError(Exception):
    """A geo problem the user has to act on (exit 1). `needs_prefetch` means the fix is to run
    `wildid prefetch` with the same geo arguments while online."""

    def __init__(self, message: str, *, needs_prefetch: bool = False):
        super().__init__(message)
        self.needs_prefetch = needs_prefetch


class GeoNetworkError(GeoError):
    """iNaturalist could not be reached or answered with an error."""


@dataclass(frozen=True)
class Place:
    id: int
    name: str
    display_name: str
    admin_level: int | None
    ancestor_place_ids: tuple[int, ...] = ()

    @classmethod
    def from_api(cls, row: dict) -> Place:
        return cls(
            id=int(row["id"]),
            name=row.get("name") or str(row["id"]),
            display_name=row.get("display_name") or row.get("name") or str(row["id"]),
            admin_level=row.get("admin_level"),
            ancestor_place_ids=tuple(int(x) for x in (row.get("ancestor_place_ids") or [])),
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "display_name": self.display_name,
            "admin_level": self.admin_level,
            "ancestor_place_ids": list(self.ancestor_place_ids),
        }

    @classmethod
    def from_json(cls, data: dict) -> Place:
        return cls(
            id=int(data["id"]),
            name=data["name"],
            display_name=data.get("display_name", data["name"]),
            admin_level=data.get("admin_level"),
            ancestor_place_ids=tuple(data.get("ancestor_place_ids", ())),
        )


@dataclass(frozen=True)
class ResolvedPlace:
    place: Place
    label: str  # what the header shows, e.g. "Brazil › Mato Grosso"


@dataclass
class GeoList:
    place: Place
    label: str
    taxa: tuple[str, ...]
    species: list[str]  # unique species names, iNat observation-count order within each taxon
    per_taxon: dict[str, int]
    fetched_at: datetime  # oldest of the per-taxon entries
    from_cache: bool
    stale: bool

    @property
    def fetched_date(self) -> str:
        return self.fetched_at.date().isoformat()


# ----------------------------------------------------------------------------------------------
# HTTP client
# ----------------------------------------------------------------------------------------------


class JsonClient:
    """Minimal JSON API client with throttling, the plan's timeouts and one retry."""

    def __init__(
        self,
        base_url: str,
        service: str,
        session: requests.Session | None = None,
        *,
        interval_s: float = INAT_REQUEST_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url
        self.service = service
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.interval_s = interval_s
        self._sleep = sleep
        self._last_request = 0.0
        self.requests_made = 0

    def get(self, path: str, **params) -> dict:
        wait = self._last_request + self.interval_s - time.monotonic()
        if wait > 0 and self._last_request:
            self._sleep(wait)
        url = f"{self.base_url}/{path}"
        for attempt in (1, 2):  # one retry: public APIs occasionally drop a connection
            try:
                self._last_request = time.monotonic()
                self.requests_made += 1
                resp = self.session.get(
                    url, params=params, timeout=(INAT_CONNECT_TIMEOUT_S, INAT_READ_TIMEOUT_S)
                )
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    raise GeoNetworkError(
                        f"{self.service} unreachable ({type(exc).__name__})"
                    ) from exc
                log.debug("%s: %s; retrying once", path, type(exc).__name__)
                self._sleep(self.interval_s)
        if resp.status_code == 429:
            raise GeoNetworkError(
                f"{self.service} rate limit hit (HTTP 429); wait a while and retry"
            )
        if resp.status_code >= 400:
            raise GeoNetworkError(f"{self.service} answered HTTP {resp.status_code} for {path}")
        try:
            return resp.json()
        except ValueError as exc:
            raise GeoNetworkError(f"{self.service} returned invalid JSON for {path}") from exc


class INatClient(JsonClient):
    """iNaturalist API v1 (places, species lists)."""

    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        interval_s: float = INAT_REQUEST_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__(INAT_API, "iNaturalist", session, interval_s=interval_s, sleep=sleep)


# ----------------------------------------------------------------------------------------------
# disk cache
# ----------------------------------------------------------------------------------------------


def _now() -> datetime:
    return datetime.now(UTC)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


class GeoCache:
    """JSON files under <cache>/geo: places.json (query → place) and one species list per
    (place, iconic taxon): <place_id>__<taxon>.json."""

    def __init__(self, root: Path | None = None):
        self.root = root or geo_cache_dir()

    # -- places --
    @property
    def places_path(self) -> Path:
        return self.root / "places.json"

    def _read_places(self) -> dict:
        try:
            with open(self.places_path, encoding="utf-8") as fd:
                return json.load(fd)
        except (OSError, ValueError):
            return {}

    def load_place(self, key: str) -> ResolvedPlace | None:
        entry = self._read_places().get(key)
        if not entry:
            return None
        try:
            return ResolvedPlace(place=Place.from_json(entry["place"]), label=entry["label"])
        except (KeyError, ValueError, TypeError):
            return None

    def save_place(self, key: str, resolved: ResolvedPlace) -> None:
        data = self._read_places()
        data[key] = {
            "place": resolved.place.to_json(),
            "label": resolved.label,
            "resolved_at": _now().isoformat(timespec="seconds"),
        }
        self._write(self.places_path, data)

    # -- GBIF name resolution (synonyms.py) --
    @property
    def names_path(self) -> Path:
        return self.root / "gbif-names.json"

    def load_names(self) -> dict:
        try:
            with open(self.names_path, encoding="utf-8") as fd:
                data = json.load(fd)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save_names(self, data: dict) -> None:
        self._write(self.names_path, data)

    # -- species lists --
    def species_path(self, place_id: int, taxon: str) -> Path:
        return self.root / f"{place_id}__{_slug(taxon)}.json"

    def load_species(self, place_id: int, taxon: str) -> dict | None:
        path = self.species_path(place_id, taxon)
        try:
            with open(path, encoding="utf-8") as fd:
                entry = json.load(fd)
            entry["fetched_at"] = datetime.fromisoformat(entry["fetched_at"])
            if entry["fetched_at"].tzinfo is None:
                entry["fetched_at"] = entry["fetched_at"].replace(tzinfo=UTC)
            assert isinstance(entry["species"], list)
            return entry
        except (OSError, ValueError, KeyError, AssertionError):
            return None

    def save_species(self, entry: dict) -> None:
        data = dict(entry)
        data["fetched_at"] = entry["fetched_at"].isoformat(timespec="seconds")
        self._write(self.species_path(entry["place_id"], entry["taxon"]), data)

    def _write(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fd:
            json.dump(data, fd, ensure_ascii=False, indent=1)
        tmp.replace(path)


# ----------------------------------------------------------------------------------------------
# taxa
# ----------------------------------------------------------------------------------------------


def parse_taxa(text: str | Sequence[str]) -> tuple[str, ...]:
    """'mammalia, Aves' → ('Mammalia', 'Aves'); unknown iconic taxa raise GeoError."""
    parts = text.split(",") if isinstance(text, str) else list(text)
    canonical = {t.lower(): t for t in INAT_ICONIC_TAXA}
    out: list[str] = []
    for raw in parts:
        name = raw.strip()
        if not name:
            continue
        if name.lower() not in canonical:
            raise GeoError(
                f"unknown taxon {name!r}; use iNaturalist class names: "
                f"{', '.join(sorted(INAT_ICONIC_TAXA))}"
            )
        value = canonical[name.lower()]
        if value not in out:
            out.append(value)
    if not out:
        raise GeoError("--taxa must name at least one taxon")
    return tuple(out)


# ----------------------------------------------------------------------------------------------
# place resolution (plan §5.1)
# ----------------------------------------------------------------------------------------------


def _norm(text: str) -> str:
    return " ".join(text.strip().lower().split())


def canonical_continent(name: str) -> str | None:
    key = _norm(name)
    if key in CONTINENT_ALIASES:
        return CONTINENT_ALIASES[key]
    for c in CONTINENTS:
        if _norm(c) == key:
            return c
    return None


def _describe(candidates: Sequence[Place]) -> str:
    return "; ".join(f"{p.display_name} (id {p.id}, admin {p.admin_level})" for p in candidates)


def _autocomplete(client: INatClient, query: str) -> list[Place]:
    js = client.get("places/autocomplete", q=query, per_page=30)
    return [Place.from_api(row) for row in js.get("results", [])]


def _pick(candidates: list[Place], query: str, levels: Sequence[int], what: str) -> Place:
    """Exact name match preferred; then the only candidate at the best admin level."""
    exact = [p for p in candidates if _norm(p.name) == _norm(query)]
    for level in levels:
        at_level = [p for p in exact if p.admin_level == level]
        if len(at_level) == 1:
            return at_level[0]
        if len(at_level) > 1:
            raise GeoError(
                f"{what} {query!r} is ambiguous: {_describe(at_level)}. Pick one with --place-id."
            )
    for level in levels:
        at_level = [p for p in candidates if p.admin_level == level]
        if len(at_level) == 1:
            log.info("%s %r resolved to %r (no exact name match)", what, query, at_level[0].name)
            return at_level[0]
        if len(at_level) > 1:
            raise GeoError(
                f"{what} {query!r} is ambiguous: {_describe(at_level)}. Pick one with --place-id."
            )
    raise GeoError(
        f"no {what} named {query!r} on iNaturalist"
        + (f" (candidates: {_describe(candidates[:5])})" if candidates else "")
        + ". Use --place-id to pass an iNaturalist place id directly."
    )


def resolve_place(
    *,
    continent: str | None = None,
    country: str | None = None,
    region: str | None = None,
    place_id: int | None = None,
    client: INatClient | None = None,
    cache: GeoCache | None = None,
    offline: bool = False,
) -> ResolvedPlace:
    """Most specific wins: place_id > region (needs country) > country > continent."""
    if region and not country:
        raise GeoError("--region requires --country")
    cache = cache or GeoCache()

    if place_id is not None:
        key = f"id:{place_id}"
        cached = cache.load_place(key)
        if cached:
            return cached
        if offline:
            raise GeoError(f"place id {place_id} is not in the geo cache", needs_prefetch=True)
        client = client or INatClient()
        rows = client.get(f"places/{place_id}").get("results") or []
        if not rows:
            raise GeoError(f"iNaturalist has no place with id {place_id}")
        place = Place.from_api(rows[0])
        resolved = ResolvedPlace(place=place, label=place.name)
        cache.save_place(key, resolved)
        return resolved

    if country:
        key = f"country:{_norm(country)}" + (f"/region:{_norm(region)}" if region else "")
        cached = cache.load_place(key)
        if cached:
            return cached
        if offline:
            where = f"{country} › {region}" if region else country
            raise GeoError(f"{where!r} is not in the geo cache", needs_prefetch=True)
        client = client or INatClient()
        c = _pick(_autocomplete(client, country), country, [ADMIN_COUNTRY], "country")
        if not region:
            resolved = ResolvedPlace(place=c, label=c.name)
        else:
            inside = [p for p in _autocomplete(client, region) if c.id in p.ancestor_place_ids]
            r = _pick(inside, region, [ADMIN_STATE, ADMIN_COUNTY], f"region of {c.name}")
            resolved = ResolvedPlace(place=r, label=f"{c.name} › {r.name}")
        cache.save_place(key, resolved)
        return resolved

    if continent:
        name = canonical_continent(continent)
        if name is None:
            raise GeoError(f"unknown continent {continent!r}; one of: {', '.join(CONTINENTS)}")
        pid = CONTINENT_PLACE_IDS.get(name)
        if pid is None:
            raise GeoError(f"no iNaturalist place is pinned for {name}; pass --place-id instead")
        place = Place(id=pid, name=name, display_name=name, admin_level=ADMIN_CONTINENT)
        return ResolvedPlace(place=place, label=name)

    raise GeoError("no place given (use --continent, --country [--region] or --place-id)")


# ----------------------------------------------------------------------------------------------
# species lists (plan §5.2)
# ----------------------------------------------------------------------------------------------


def fetch_species(client: INatClient, place_id: int, taxon: str) -> dict:
    """Page through observations/species_counts for one iconic taxon; species rank only."""
    names: list[str] = []
    page = 1
    total = 0
    while True:
        js = client.get(
            "observations/species_counts",
            place_id=place_id,
            iconic_taxa=taxon,
            quality_grade="research",
            per_page=INAT_PER_PAGE,
            page=page,
        )
        rows = js.get("results") or []
        total = int(js.get("total_results") or 0)
        for row in rows:
            t = row.get("taxon") or {}
            if t.get("rank") == "species" and t.get("name"):
                names.append(t["name"])
        if not rows or page * INAT_PER_PAGE >= total:
            break
        if page * INAT_PER_PAGE >= INAT_RESULT_CAP:
            log.warning(
                "%s for place %d has %d results; iNaturalist caps a query at %d, "
                "the rarest species are missing",
                taxon,
                place_id,
                total,
                INAT_RESULT_CAP,
            )
            break
        page += 1
    log.debug(
        "fetched %s for place %d: %d species (%d results)",
        taxon,
        place_id,
        len(names),
        total,
    )
    return {
        "place_id": place_id,
        "taxon": taxon,
        "fetched_at": _now(),
        "total_results": total,
        "species": names,
    }


def species_list(
    resolved: ResolvedPlace,
    taxa: Sequence[str],
    *,
    client: INatClient | None = None,
    cache: GeoCache | None = None,
    refresh: bool = False,
    refresh_stale: bool = False,
    offline: bool = False,
    max_age: timedelta = timedelta(days=GEO_CACHE_MAX_AGE_DAYS),
) -> GeoList:
    """Species for a place, one cache entry per iconic taxon. Cache-first; a stale entry is used
    with a warning; `refresh` refetches when the network is reachable and otherwise falls back."""
    cache = cache or GeoCache()
    place = resolved.place
    all_names: list[str] = []
    per_taxon: dict[str, int] = {}
    fetched: list[datetime] = []
    from_cache = True
    stale = False
    now = _now()
    for taxon in taxa:
        entry = cache.load_species(place.id, taxon)
        if entry is not None and refresh_stale and now - entry["fetched_at"] > max_age:
            refresh = True  # the pre-trip prefetch renews stale lists while online
        if entry is not None and not refresh:
            age = now - entry["fetched_at"]
            if age > max_age:
                stale = True
                log.warning(
                    "species list for %s / %s is %d days old; using it anyway "
                    "(--refresh-geo to refetch)",
                    resolved.label,
                    taxon,
                    age.days,
                )
            log.info(
                "geo cache hit: %s / %s, %d species, fetched %s",
                resolved.label,
                taxon,
                len(entry["species"]),
                entry["fetched_at"].date().isoformat(),
            )
        else:
            if offline:
                if entry is not None:  # refresh requested but forbidden: keep the cache
                    log.info("offline: keeping cached %s / %s", resolved.label, taxon)
                else:
                    raise GeoError(
                        f"no cached species list for {resolved.label} / {taxon}",
                        needs_prefetch=True,
                    )
            else:
                client = client or INatClient()
                try:
                    fresh = fetch_species(client, place.id, taxon)
                except GeoNetworkError as exc:
                    if entry is None:
                        raise GeoError(
                            f"could not fetch the species list for {resolved.label} / {taxon}: "
                            f"{exc}",
                            needs_prefetch=True,
                        ) from exc
                    log.warning(
                        "refresh of %s / %s failed (%s); using the cached list from %s",
                        resolved.label,
                        taxon,
                        exc,
                        entry["fetched_at"].date().isoformat(),
                    )
                else:
                    entry = fresh
                    cache.save_species(entry)
                    from_cache = False
                    log.info(
                        "geo fetch: %s / %s, %d species",
                        resolved.label,
                        taxon,
                        len(entry["species"]),
                    )
        assert entry is not None
        per_taxon[taxon] = len(entry["species"])
        all_names.extend(entry["species"])
        fetched.append(entry["fetched_at"])
    species = list(dict.fromkeys(all_names))
    log.info(
        "geo list %s: %d species (%s)",
        resolved.label,
        len(species),
        ", ".join(f"{t} {n}" for t, n in per_taxon.items()),
    )
    return GeoList(
        place=place,
        label=resolved.label,
        taxa=tuple(taxa),
        species=species,
        per_taxon=per_taxon,
        fetched_at=min(fetched),
        from_cache=from_cache,
        stale=stale,
    )


# ----------------------------------------------------------------------------------------------
# TreeOfLife intersection + mask (plan §5.3)
# ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class FilterResult:
    kept: list[str]  # regional species known to the model (after synonym mapping)
    unmatched: list[str]  # regional names with no model equivalent
    mapped: dict[str, str]  # iNat name -> model name, for the ones resolved through GBIF
    rank: str  # "species" or "genus"
    species_count: int  # size of the candidate set actually applied


GEO_RANKS = ("species", "genus")


def build_filter(
    classifier,
    geo: GeoList,
    *,
    rank: str = "species",
    synonyms: dict[str, list[str]] | None = None,
) -> FilterResult:
    """Intersect the regional list with the model's species names and apply the filter.

    `synonyms` maps an iNat name to alternative spellings (GBIF accepted name + synonyms); the
    first one the model knows is used. `rank="genus"` keeps every model species of the genera
    on the list (post-MVP item 7, for places with thin iNaturalist coverage); order/family are
    never used (plan §1.2 warning).
    """
    if rank not in GEO_RANKS:
        raise GeoError(f"unknown geo rank {rank!r}; choose from {', '.join(GEO_RANKS)}")
    known = classifier.known_species
    kept: list[str] = []
    unmatched: list[str] = []
    mapped: dict[str, str] = {}
    for name in geo.species:
        if name in known:
            kept.append(name)
            continue
        alt = next((c for c in (synonyms or {}).get(name, ()) if c in known), None)
        if alt is None:
            unmatched.append(name)
        else:
            kept.append(alt)
            mapped[name] = alt
    kept = list(dict.fromkeys(kept))
    if mapped:
        sample = ", ".join(f"{a} \u2192 {b}" for a, b in list(mapped.items())[:3])
        log.info("%d regional names mapped through GBIF synonyms, e.g. %s", len(mapped), sample)
    if unmatched:
        sample = ", ".join(unmatched[:5])
        log.info(
            "%d of %d regional species are not TreeOfLife names (taxonomy drift), e.g. %s",
            len(unmatched),
            len(geo.species),
            sample,
        )
    if rank == "genus":
        genera = list(dict.fromkeys(n.split()[0] for n in kept + unmatched if " " in n))
        known_genera = classifier.known_genera
        keep_genera = [g for g in genera if g in known_genera]
        if not keep_genera:
            raise GeoError(f"none of the genera for {geo.label} are known to the model")
        classifier.apply_genus_filter(keep_genera)
        species_count = len(classifier.filter_species or ())
        log.info(
            "candidate set: %d species of %d genera (genus level) for %s",
            species_count,
            len(keep_genera),
            geo.label,
        )
    else:
        if len(kept) < GEO_MIN_MATCHED_SPECIES:
            log.warning(
                "only %d species matched for %s (%s); the filter is probably wrong "
                "(bad place or taxa?)",
                len(kept),
                geo.label,
                ",".join(geo.taxa),
            )
        if not kept:
            raise GeoError(
                f"none of the {len(geo.species)} species for {geo.label} are known to the model"
            )
        rows = classifier.apply_species_filter(kept)
        species_count = len(kept)
        log.info(
            "candidate set: %d species (%d TreeOfLife rows) for %s", len(kept), rows, geo.label
        )
    classifier.place_label = geo.label
    return FilterResult(
        kept=kept, unmatched=unmatched, mapped=mapped, rank=rank, species_count=species_count
    )
