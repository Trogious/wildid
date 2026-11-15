"""geo.py tests: iNaturalist HTTP is mocked with `responses`; nothing touches the network."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import pytest
import requests
import responses
from responses import matchers

from wildid import geo
from wildid.geo import (
    GeoCache,
    GeoError,
    GeoNetworkError,
    INatClient,
    build_filter,
    fetch_species,
    parse_taxa,
    resolve_place,
    species_list,
)

API = "https://api.inaturalist.org/v1"


@pytest.fixture
def client():
    return INatClient(sleep=lambda _s: None)  # no throttling delay in tests


@pytest.fixture
def cache(tmp_path):
    return GeoCache(tmp_path / "geo")


def row(id_, name, admin_level, ancestors, display=None):
    return {
        "id": id_,
        "name": name,
        "display_name": display or name,
        "admin_level": admin_level,
        "ancestor_place_ids": ancestors,
    }


BRAZIL = row(6878, "Brazil", 0, [97389, 6878])
MATO_GROSSO = row(8239, "Mato Grosso", 10, [97389, 6878, 8239], "Mato Grosso, BR")


def add_autocomplete(q, rows):
    responses.add(
        responses.GET,
        f"{API}/places/autocomplete",
        json={"results": rows},
        match=[matchers.query_param_matcher({"q": q, "per_page": "30"})],
    )


def add_species_page(place_id, taxon, page, total, names_with_rank):
    results = [
        {"count": 10, "taxon": {"name": name, "rank": rank, "iconic_taxon_name": taxon}}
        for name, rank in names_with_rank
    ]
    responses.add(
        responses.GET,
        f"{API}/observations/species_counts",
        json={"total_results": total, "page": page, "per_page": 500, "results": results},
        match=[
            matchers.query_param_matcher(
                {
                    "place_id": str(place_id),
                    "iconic_taxa": taxon,
                    "quality_grade": "research",
                    "per_page": "500",
                    "page": str(page),
                }
            )
        ],
    )


# --- taxa -------------------------------------------------------------------------------------


def test_parse_taxa_canonicalises_and_dedupes():
    assert parse_taxa("mammalia, Aves,Aves") == ("Mammalia", "Aves")
    assert parse_taxa(["Reptilia"]) == ("Reptilia",)
    with pytest.raises(GeoError, match="unknown taxon"):
        parse_taxa("Mammalia,Dinosauria")
    with pytest.raises(GeoError):
        parse_taxa(" , ")


# --- client -----------------------------------------------------------------------------------


@responses.activate
def test_client_sends_user_agent_and_maps_http_errors(client):
    responses.add(responses.GET, f"{API}/places/1", json={"results": []})
    responses.add(responses.GET, f"{API}/places/2", status=500)
    responses.add(responses.GET, f"{API}/places/3", status=429)
    assert client.get("places/1") == {"results": []}
    assert responses.calls[0].request.headers["User-Agent"].startswith("wildid/")
    with pytest.raises(GeoNetworkError, match="HTTP 500"):
        client.get("places/2")
    with pytest.raises(GeoNetworkError, match="rate limit"):
        client.get("places/3")
    assert client.requests_made == 3


@responses.activate
def test_client_connection_failure_is_geo_network_error(client):
    with pytest.raises(GeoNetworkError, match="unreachable"):
        client.get("places/4")  # nothing registered: responses raises ConnectionError
    assert client.requests_made == 2  # one retry


@responses.activate
def test_client_retries_once_after_a_dropped_connection(client):
    responses.add(responses.GET, f"{API}/places/5", body=requests.ConnectionError("reset"))
    responses.add(responses.GET, f"{API}/places/5", json={"results": [{"id": 5}]})
    assert client.get("places/5") == {"results": [{"id": 5}]}


def test_client_throttles_between_requests():
    sleeps: list[float] = []
    c = INatClient(interval_s=1.0, sleep=sleeps.append)
    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, f"{API}/places/1", json={})
        rsps.add(responses.GET, f"{API}/places/1", json={})
        c.get("places/1")
        c.get("places/1")
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0


# --- place resolution -------------------------------------------------------------------------


@responses.activate
def test_resolve_country_prefers_exact_admin0_and_caches(client, cache):
    add_autocomplete("Brazil", [row(21146, "Novo Brazil", 20, [97389, 6878, 21146]), BRAZIL])
    r = resolve_place(country="Brazil", client=client, cache=cache)
    assert (r.place.id, r.label) == (6878, "Brazil")
    responses.reset()  # any further HTTP call would now raise
    again = resolve_place(country="Brazil ", client=client, cache=cache)
    assert again == r
    assert cache.places_path.exists()


@responses.activate
def test_resolve_region_inside_country(client, cache):
    add_autocomplete("Brazil", [BRAZIL])
    add_autocomplete(
        "Mato Grosso",
        [
            row(7555, "Mato Grosso do Sul", 10, [97389, 6878, 7555]),
            row(22761, "Mato Grosso", 20, [97389, 6878, 12593, 22761]),  # a county, same name
            row(4242, "Mato Grosso", 10, [97394, 1, 4242]),  # same name, other country
            MATO_GROSSO,
        ],
    )
    r = resolve_place(country="Brazil", region="Mato Grosso", client=client, cache=cache)
    assert r.place.id == 8239
    assert r.label == "Brazil › Mato Grosso"
    assert r.place.display_name == "Mato Grosso, BR"


@responses.activate
def test_resolve_region_ambiguity_lists_candidates(client, cache):
    add_autocomplete("Brazil", [BRAZIL])
    add_autocomplete(
        "Santa Cruz",
        [
            row(1, "Santa Cruz", 10, [6878, 1], "Santa Cruz, A"),
            row(2, "Santa Cruz", 10, [6878, 2], "Santa Cruz, B"),
        ],
    )
    with pytest.raises(GeoError, match=r"ambiguous.*Santa Cruz, A.*Santa Cruz, B.*--place-id"):
        resolve_place(country="Brazil", region="Santa Cruz", client=client, cache=cache)


@responses.activate
def test_resolve_region_falls_back_to_county_level(client, cache):
    add_autocomplete("Brazil", [BRAZIL])
    add_autocomplete("Bonito", [row(555, "Bonito", 20, [97389, 6878, 7555, 555])])
    r = resolve_place(country="Brazil", region="Bonito", client=client, cache=cache)
    assert r.place.id == 555 and r.place.admin_level == 20


@responses.activate
def test_resolve_unknown_country(client, cache):
    add_autocomplete("Atlantis", [row(9, "Atlantis Resort", 20, [1, 9])])
    with pytest.raises(GeoError, match="no country named 'Atlantis'"):
        resolve_place(country="Atlantis", client=client, cache=cache)


def test_region_requires_country(client, cache):
    with pytest.raises(GeoError, match="--region requires --country"):
        resolve_place(region="Mato Grosso", client=client, cache=cache)


@responses.activate
def test_resolve_place_id_validates_and_caches(client, cache):
    responses.add(responses.GET, f"{API}/places/8239", json={"results": [MATO_GROSSO]})
    r = resolve_place(place_id=8239, client=client, cache=cache)
    assert (r.place.id, r.label) == (8239, "Mato Grosso")
    responses.reset()
    assert resolve_place(place_id=8239, client=client, cache=cache) == r


def test_resolve_continent_is_pinned_offline(client, cache, monkeypatch):
    monkeypatch.setattr(geo, "CONTINENT_PLACE_IDS", {"Europe": 97391, "Oceania": 97393})
    r = resolve_place(continent="europe", client=client, cache=cache, offline=True)
    assert (r.place.id, r.label, r.place.admin_level) == (97391, "Europe", -10)
    assert resolve_place(continent="Australia", client=client, cache=cache).place.id == 97393
    with pytest.raises(GeoError, match="unknown continent"):
        resolve_place(continent="Atlantis", client=client, cache=cache)
    with pytest.raises(GeoError, match="--place-id"):
        resolve_place(continent="Antarctica", client=client, cache=cache)


@responses.activate
def test_resolve_offline_uncached_needs_prefetch(client, cache):
    with pytest.raises(GeoError) as info:
        resolve_place(country="Brazil", client=client, cache=cache, offline=True)
    assert info.value.needs_prefetch
    assert len(responses.calls) == 0


# --- species lists ----------------------------------------------------------------------------


@responses.activate
def test_fetch_species_pages_and_keeps_species_rank_only(client):
    add_species_page(
        6878,
        "Mammalia",
        1,
        501,
        [("Panthera onca", "species"), ("Canis x familiaris", "hybrid"), ("Puma", "genus")],
    )
    add_species_page(6878, "Mammalia", 2, 501, [("Tapirus terrestris", "species")])
    entry = fetch_species(client, 6878, "Mammalia")
    assert entry["species"] == ["Panthera onca", "Tapirus terrestris"]
    assert entry["total_results"] == 501
    assert client.requests_made == 2


def _resolved_brazil():
    return geo.ResolvedPlace(place=geo.Place.from_api(BRAZIL), label="Brazil")


@responses.activate
def test_species_list_fetches_then_serves_from_cache(client, cache):
    add_species_page(
        6878, "Mammalia", 1, 2, [("Panthera onca", "species"), ("Puma concolor", "species")]
    )
    add_species_page(6878, "Aves", 1, 1, [("Ara ararauna", "species")])
    lst = species_list(_resolved_brazil(), ("Mammalia", "Aves"), client=client, cache=cache)
    assert lst.species == ["Panthera onca", "Puma concolor", "Ara ararauna"]
    assert lst.per_taxon == {"Mammalia": 2, "Aves": 1}
    assert lst.from_cache is False and lst.stale is False
    assert lst.fetched_date == datetime.now(UTC).date().isoformat()
    assert cache.species_path(6878, "Mammalia").exists()

    responses.reset()
    cached = species_list(_resolved_brazil(), ("Mammalia", "Aves"), client=client, cache=cache)
    assert cached.species == lst.species and cached.from_cache is True
    # a subset of taxa reuses the per-taxon files without any network call
    only_birds = species_list(_resolved_brazil(), ("Aves",), client=client, cache=cache)
    assert only_birds.species == ["Ara ararauna"]


@responses.activate
def test_species_list_stale_cache_is_used_with_warning(client, cache, caplog):
    cache.save_species(
        {
            "place_id": 6878,
            "taxon": "Mammalia",
            "fetched_at": datetime.now(UTC) - timedelta(days=45),
            "total_results": 1,
            "species": ["Panthera onca"],
        }
    )
    with caplog.at_level(logging.WARNING, logger="wildid.geo"):
        lst = species_list(_resolved_brazil(), ("Mammalia",), client=client, cache=cache)
    assert lst.stale and lst.from_cache and lst.species == ["Panthera onca"]
    assert "45 days old" in caplog.text and "--refresh-geo" in caplog.text
    assert len(responses.calls) == 0


@responses.activate
def test_species_list_refresh_fetches_and_falls_back_when_offline_or_down(client, cache, caplog):
    cache.save_species(
        {
            "place_id": 6878,
            "taxon": "Aves",
            "fetched_at": datetime.now(UTC) - timedelta(days=1),
            "total_results": 1,
            "species": ["Ara ararauna"],
        }
    )
    # network down (nothing registered): refresh keeps the cached list and warns
    with caplog.at_level(logging.WARNING, logger="wildid.geo"):
        lst = species_list(_resolved_brazil(), ("Aves",), client=client, cache=cache, refresh=True)
    assert lst.species == ["Ara ararauna"] and lst.from_cache
    assert "refresh of Brazil / Aves failed" in caplog.text
    # --offline with --refresh-geo: no attempt at all
    lst = species_list(
        _resolved_brazil(), ("Aves",), client=client, cache=cache, refresh=True, offline=True
    )
    assert lst.species == ["Ara ararauna"]
    assert client.requests_made == 2  # the failed attempt plus its single retry
    # network back: refresh replaces the list
    add_species_page(6878, "Aves", 1, 1, [("Ramphastos toco", "species")])
    lst = species_list(_resolved_brazil(), ("Aves",), client=client, cache=cache, refresh=True)
    assert lst.species == ["Ramphastos toco"] and not lst.from_cache


@responses.activate
def test_species_list_uncached_failures_need_prefetch(client, cache):
    with pytest.raises(GeoError) as info:
        species_list(_resolved_brazil(), ("Reptilia",), client=client, cache=cache, offline=True)
    assert info.value.needs_prefetch and "no cached species list" in str(info.value)
    with pytest.raises(GeoError) as info:  # online but iNat unreachable
        species_list(_resolved_brazil(), ("Reptilia",), client=client, cache=cache)
    assert info.value.needs_prefetch and "could not fetch" in str(info.value)


# --- intersection + mask ----------------------------------------------------------------------


class FakeClassifier:
    def __init__(self, known):
        self.known_species = frozenset(known)
        self.known_genera = frozenset(n.split()[0] for n in known)
        self.applied = None
        self.applied_genera = None
        self.place_label = None
        self.filter_species = None

    def apply_species_filter(self, species):
        self.applied = list(species)
        self.filter_species = list(species)
        return len(species) + 1  # pretend one species has a synonym row

    def apply_genus_filter(self, genera):
        self.applied_genera = list(genera)
        self.filter_species = [n for n in self.known_species if n.split()[0] in genera]
        return len(self.filter_species)


def _geo_list(species):
    return geo.GeoList(
        place=geo.Place.from_api(BRAZIL),
        label="Brazil",
        taxa=("Mammalia",),
        species=species,
        per_taxon={"Mammalia": len(species)},
        fetched_at=datetime.now(UTC),
        from_cache=True,
        stale=False,
    )


def test_build_filter_intersects_at_species_rank(caplog):
    clf = FakeClassifier({"Panthera onca", "Puma concolor"})
    with caplog.at_level(logging.WARNING, logger="wildid.geo"):
        result = build_filter(clf, _geo_list(["Panthera onca", "Nope nope", "Puma concolor"]))
    assert result.kept == ["Panthera onca", "Puma concolor"]
    assert result.unmatched == ["Nope nope"]
    assert clf.applied == result.kept
    assert clf.place_label == "Brazil"
    assert "probably wrong" in caplog.text  # fewer than 50 matched


def test_build_filter_with_nothing_known_raises():
    with pytest.raises(GeoError, match="known to the model"):
        build_filter(FakeClassifier(set()), _geo_list(["Nope nope"]))


def test_build_filter_maps_names_through_synonyms():
    clf = FakeClassifier({"Taurotragus oryx", "Panthera leo"})
    synonyms = {"Tragelaphus oryx": ["Taurotragus oryx", "Antilope oryx"], "Nope nope": ["Zz zz"]}
    result = build_filter(
        clf, _geo_list(["Panthera leo", "Tragelaphus oryx", "Nope nope"]), synonyms=synonyms
    )
    assert result.kept == ["Panthera leo", "Taurotragus oryx"]
    assert result.mapped == {"Tragelaphus oryx": "Taurotragus oryx"}
    assert result.unmatched == ["Nope nope"]
    assert result.rank == "species" and result.species_count == 2


def test_build_filter_genus_mode_keeps_whole_genera():
    clf = FakeClassifier({"Panthera leo", "Panthera pardus", "Panthera tigris", "Canis lupus"})
    result = build_filter(clf, _geo_list(["Panthera leo", "Lupulella mesomelas"]), rank="genus")
    assert clf.applied_genera == ["Panthera"]  # Lupulella is unknown to the model
    assert result.rank == "genus" and result.species_count == 3
    assert set(clf.filter_species) == {"Panthera leo", "Panthera pardus", "Panthera tigris"}
    assert clf.place_label == "Brazil"
    with pytest.raises(GeoError, match="unknown geo rank"):
        build_filter(clf, _geo_list(["Panthera leo"]), rank="family")
    with pytest.raises(GeoError, match="genera"):
        build_filter(
            FakeClassifier({"Canis lupus"}), _geo_list(["Lupulella mesomelas"]), rank="genus"
        )
