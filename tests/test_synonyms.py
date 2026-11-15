"""GBIF synonym resolution with mocked HTTP."""

from __future__ import annotations

import pytest
import responses
from responses import matchers

from wildid.geo import GeoCache, GeoNetworkError
from wildid.synonyms import GbifClient, canonical_map, gbif_candidates, resolve_names

API = "https://api.gbif.org/v1"


@pytest.fixture
def client():
    return GbifClient(sleep=lambda _s: None)


@pytest.fixture
def cache(tmp_path):
    return GeoCache(tmp_path / "geo")


def add_match(name, **fields):
    responses.add(
        responses.GET,
        f"{API}/species/match",
        json=fields,
        match=[matchers.query_param_matcher({"name": name, "strict": "true"})],
    )


def add_synonyms(key, names):
    responses.add(
        responses.GET,
        f"{API}/species/{key}/synonyms",
        json={"results": [{"canonicalName": n, "rank": "SPECIES"} for n in names]},
    )


@responses.activate
def test_exact_synonym_match_yields_accepted_name_and_other_synonyms(client):
    add_match(
        "Tragelaphus oryx",
        matchType="EXACT",
        status="SYNONYM",
        confidence=100,
        usageKey=1,
        acceptedUsageKey=2,
        canonicalName="Tragelaphus oryx",
        species="Taurotragus oryx",
    )
    add_synonyms(2, ["Tragelaphus oryx", "Antilope oryx"])
    entry = gbif_candidates(client, "Tragelaphus oryx")
    assert entry["accepted"] == "Taurotragus oryx"
    assert entry["candidates"] == ["Taurotragus oryx", "Antilope oryx"]  # the name itself dropped
    assert entry["match"] == "EXACT/SYNONYM"


@responses.activate
def test_no_match_and_weak_fuzzy_match_give_no_candidates(client):
    add_match("Lupulella mesomelas", matchType="NONE", confidence=100)
    assert gbif_candidates(client, "Lupulella mesomelas") == {
        "accepted": None,
        "candidates": [],
        "match": "NONE",
    }
    add_match(
        "Mops pumilus",
        matchType="FUZZY",
        status="SYNONYM",
        confidence=94,
        usageKey=3,
        species="Chaerephon pusillus",
    )
    assert gbif_candidates(client, "Mops pumilus")["candidates"] == []  # below the 95 bar


@responses.activate
def test_resolve_names_caches_and_is_cache_only_when_offline(client, cache):
    add_match(
        "Felis lybica",
        matchType="EXACT",
        status="SYNONYM",
        confidence=100,
        usageKey=5,
        acceptedUsageKey=6,
        canonicalName="Felis lybica",
        species="Felis silvestris",
    )
    add_synonyms(6, [])
    add_match(
        "Panthera leo",
        matchType="EXACT",
        status="ACCEPTED",
        confidence=100,
        usageKey=8,
        canonicalName="Panthera leo",
        species="Panthera leo",
    )
    add_synonyms(8, ["Felis leo"])
    out, skipped = resolve_names(["Felis lybica", "Panthera leo"], cache=cache, client=client)
    assert out == {"Felis lybica": ["Felis silvestris"], "Panthera leo": ["Felis leo"]}
    assert skipped == 0
    assert cache.names_path.exists()
    # second call: served from the cache, no HTTP
    responses.reset()
    out2, skipped2 = resolve_names(["Felis lybica"], cache=cache, client=client)
    assert out2 == {"Felis lybica": ["Felis silvestris"]} and skipped2 == 0
    # offline: uncached names are skipped and counted, cached ones still answered
    out3, skipped3 = resolve_names(["Felis lybica", "Zebra nova"], cache=cache, offline=True)
    assert out3 == {"Felis lybica": ["Felis silvestris"]} and skipped3 == 1


@responses.activate
def test_resolve_names_stops_after_a_network_failure_but_keeps_progress(client, cache):
    add_match(
        "Aa bb", matchType="EXACT", status="ACCEPTED", confidence=100, usageKey=7, species="Aa bb"
    )
    add_synonyms(7, ["Cc dd"])
    # the second name has no registered response -> ConnectionError -> GeoNetworkError
    out, skipped = resolve_names(["Aa bb", "Ee ff", "Gg hh"], cache=cache, client=client)
    assert out == {"Aa bb": ["Cc dd"]}
    assert skipped == 2
    assert "Aa bb" in cache.load_names()


def test_canonical_map_points_every_spelling_at_the_accepted_name(cache):
    cache.save_names(
        {
            "Tragelaphus oryx": {
                "accepted": "Taurotragus oryx",
                "candidates": ["Taurotragus oryx"],
            },
            "Grus communis": {"accepted": "Grus grus", "candidates": ["Grus grus"]},
            "Nope nope": {"accepted": None, "candidates": []},
        }
    )
    cmap = canonical_map(cache)
    assert cmap["Tragelaphus oryx"] == cmap["Taurotragus oryx"] == "Taurotragus oryx"
    assert cmap["Grus communis"] == "Grus grus" and cmap["Grus grus"] == "Grus grus"
    assert cmap["Nope nope"] == "Nope nope"


def test_gbif_client_reports_its_service_name(client):
    with pytest.raises(GeoNetworkError, match="GBIF unreachable"):
        with responses.RequestsMock():
            client.get("species/match", name="x")
