"""`wildid serve`: routing, auth, classify/prefetch/shutdown, idle-exit. Fake classifier,
real HTTP over 127.0.0.1, no model, no network."""

from __future__ import annotations

import http.client
import json
import threading
import time
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from test_cli import FakeClassifier

from wildid.serve import (
    ServerState,
    create_server,
    read_discovery,
    remove_discovery,
    start_idle_monitor,
    write_discovery,
)


def make_state(ready: bool = True) -> ServerState:
    state = ServerState(model_name="fake")
    if ready:
        state.classifiers["fake"] = FakeClassifier()
        state.ready = True
    return state


@pytest.fixture
def server():
    state = make_state()
    srv = create_server(state, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield state, srv, thread
    srv.shutdown()
    srv.server_close()


def call(srv, token: str, method: str, path: str, body: dict | None = None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Authorization": f"Bearer {token}"}
    payload = None
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    conn.request(method, path, body=payload, headers=headers)
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, data


def test_requests_require_the_token(server):
    state, srv, _ = server
    status, data = call(srv, "wrong-token", "GET", "/health")
    assert status == 401 and "token" in data["error"]
    status, data = call(srv, state.token, "GET", "/health")
    assert status == 200
    assert data["ready"] is True and data["protocol"] == 1 and data["model"] == "fake"
    assert data["default_model"] == "fake"
    assert data["models"]["fake"] == {"loaded": True, "error": None}
    assert data["models"]["bioclip-2"] == {"loaded": False, "error": None}
    assert "vram" in data  # None without a GPU; total_gb/free_gb on CUDA, plus kind on a Mac


def test_probe_vram_reports_unified_memory_on_apple_silicon(monkeypatch):
    import torch

    from wildid import serve

    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(torch.mps, "recommended_max_memory", lambda: 36_000_000_000)
    monkeypatch.setattr(torch.mps, "driver_allocated_memory", lambda: 6_400_000_000)
    monkeypatch.setattr(serve, "apple_chip_name", lambda: "Apple M5 Pro")
    assert serve.probe_vram() == {
        "device_name": "Apple M5 Pro",
        "total_gb": 36.0,
        "free_gb": 29.6,
        "kind": "unified",
    }
    # the driver holding more than the recommendation never reports negative room
    monkeypatch.setattr(torch.mps, "driver_allocated_memory", lambda: 40_000_000_000)
    assert serve.probe_vram()["free_gb"] == 0.0


def test_probe_vram_prefers_cuda_and_is_none_without_a_gpu(monkeypatch):
    import torch

    from wildid import serve

    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(torch.cuda, "mem_get_info", lambda *a: (20_000_000_000, 25_800_000_000))
    monkeypatch.setattr(torch.cuda, "get_device_name", lambda *a: "NVIDIA GeForce RTX 4090")
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    assert serve.probe_vram() == {
        "device_name": "NVIDIA GeForce RTX 4090",
        "total_gb": 25.8,
        "free_gb": 20.0,
    }  # the CUDA shape is unchanged: no "kind"
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: False)
    assert serve.probe_vram() is None

    def boom():
        raise RuntimeError("probe failed")

    monkeypatch.setattr(torch.backends.mps, "is_available", lambda: True)
    monkeypatch.setattr(torch.mps, "recommended_max_memory", boom)
    assert serve.probe_vram() is None  # a failed probe means "unknown", never a crash


def test_apple_chip_name_reads_sysctl_and_falls_back(monkeypatch):
    from wildid import serve

    serve.apple_chip_name.cache_clear()
    monkeypatch.setattr(
        serve.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="Apple M5 Pro\n")
    )
    assert serve.apple_chip_name() == "Apple M5 Pro"
    serve.apple_chip_name.cache_clear()

    def missing(*args, **kwargs):
        raise FileNotFoundError("sysctl")

    monkeypatch.setattr(serve.subprocess, "run", missing)
    monkeypatch.setattr(serve.platform, "processor", lambda: "")
    assert serve.apple_chip_name() == "Apple Silicon"
    serve.apple_chip_name.cache_clear()


def test_health_passes_the_vram_probe_through(server, monkeypatch):
    state, srv, _ = server
    probe = {"device_name": "Test GPU", "total_gb": 25.8, "free_gb": 20.1}
    monkeypatch.setattr("wildid.serve.probe_vram", lambda: probe)
    state.vram = probe
    status, data = call(srv, state.token, "GET", "/health")
    assert status == 200 and data["vram"] == probe


def test_classify_uses_the_requested_loaded_model(server, bear_jpg):
    state, srv, _ = server
    other = FakeClassifier()
    other.spec.name = "bioclip-2.5"
    state.classifiers["bioclip-2.5"] = other
    status, doc = call(
        srv,
        state.token,
        "POST",
        "/classify",
        {"paths": [str(bear_jpg)], "model": "bioclip-2.5"},
    )
    assert status == 200 and doc["model"] == "bioclip-2.5"
    assert other.calls and not state.clf.calls  # the default model was not used
    status, data = call(
        srv, state.token, "POST", "/classify", {"paths": [str(bear_jpg)], "model": "nope"}
    )
    assert status == 400 and "unknown model" in data["error"]


def test_classify_lazy_loads_a_known_model(server, bear_jpg, monkeypatch):
    import wildid.model

    state, srv, _ = server
    lazy = FakeClassifier()
    lazy.spec.name = "bioclip-2.5"
    loads: list[str] = []

    def fake_load(name, device):
        loads.append(name)
        return lazy

    monkeypatch.setattr(wildid.model, "load_classifier", fake_load)
    body = {"paths": [str(bear_jpg)], "model": "bioclip-2.5"}
    status, doc = call(srv, state.token, "POST", "/classify", body)
    assert status == 200 and doc["model"] == "bioclip-2.5"
    status, doc = call(srv, state.token, "POST", "/classify", body)
    assert status == 200
    assert loads == ["bioclip-2.5"]  # loaded once, then reused
    assert lazy.precision == "tf32"  # the server's precision policy was applied
    status, data = call(srv, state.token, "GET", "/health")
    assert data["models"]["bioclip-2.5"]["loaded"] is True


def test_warmup_loads_once_and_reports(server, monkeypatch):
    import wildid.model

    state, srv, _ = server
    lazy = FakeClassifier()
    lazy.spec.name = "bioclip-2.5"
    loads: list[str] = []
    monkeypatch.setattr(
        wildid.model, "load_classifier", lambda name, device: loads.append(name) or lazy
    )
    status, data = call(srv, state.token, "POST", "/warmup", {"model": "bioclip-2.5"})
    assert status == 200 and data["ok"] is True
    assert data["model"] == "bioclip-2.5" and data["already_loaded"] is False
    assert data["models"]["bioclip-2.5"]["loaded"] is True
    status, data = call(srv, state.token, "POST", "/warmup", {"model": "bioclip-2.5"})
    assert status == 200 and data["already_loaded"] is True
    assert loads == ["bioclip-2.5"]
    status, data = call(srv, state.token, "POST", "/warmup", {"model": "nope"})
    assert status == 400


def test_warmup_reports_a_missing_model_cache(server, monkeypatch):
    import wildid.model
    from wildid.model import ModelLoadError

    state, srv, _ = server

    def boom(name, device):
        raise ModelLoadError(f"{name} is not in the local cache", missing_cache=True)

    monkeypatch.setattr(wildid.model, "load_classifier", boom)
    status, data = call(srv, state.token, "POST", "/warmup", {"model": "bioclip-2.5"})
    assert status == 503
    assert "wildid prefetch --model bioclip-2.5" in data["error"]
    status, data = call(srv, state.token, "GET", "/health")
    assert data["models"]["bioclip-2.5"]["loaded"] is False
    assert "prefetch" in data["models"]["bioclip-2.5"]["error"]
    assert data["ready"] is True  # the default model is unaffected


def test_classify_one_file(server, bear_jpg):
    state, srv, _ = server
    status, doc = call(srv, state.token, "POST", "/classify", {"paths": [str(bear_jpg)], "k": 2})
    assert status == 200
    assert doc["protocol"] == 1 and doc["model"] == "fake"
    (res,) = doc["results"]
    assert res["ok"] is True
    assert len(res["predictions"]) == 2
    assert res["suggested_keywords"][0]["path"] == ["WildID", "Ursus", "Ursus arctos"]
    assert state.clf.calls  # the fake actually ran


def test_classify_crop_exact_is_a_setting_of_the_request(server, bear_jpg, monkeypatch):
    from test_cli import FakeDetector

    import wildid.detector

    det = FakeDetector()
    loads = []

    def load(cls, name, device):
        loads.append(name)
        return det

    monkeypatch.setattr(wildid.detector.Detector, "load", classmethod(load))
    state, srv, _ = server
    seen = []
    for extra in ({"crop": True, "crop_exact": True}, {"crop": True}, {"crop_exact": True}):
        body = {"paths": [str(bear_jpg)], **extra}
        status, doc = call(srv, state.token, "POST", "/classify", body)
        assert status == 200
        seen.append((doc["crop_resize"], doc["results"][0]["crop"] is not None))
    # exact when asked for, the platform's resize when not, and nothing without the crop
    assert seen == [("exact", True), ("linear", True), (None, False)]
    assert det.exact == [True, False]
    assert loads == ["mdv6-yolov9-c"]  # the detector is loaded once for both


def test_classify_missing_file_is_a_per_file_error(server):
    state, srv, _ = server
    status, doc = call(srv, state.token, "POST", "/classify", {"paths": ["/nope/x.jpg"]})
    assert status == 200
    assert doc["results"][0]["ok"] is False
    assert doc["results"][0]["error"]


def test_classify_validation_errors(server):
    state, srv, _ = server
    for body in ({}, {"paths": []}, {"paths": [1]}, {"paths": ["x"], "k": 0}):
        status, data = call(srv, state.token, "POST", "/classify", body)
        assert status == 400, body
        assert "error" in data
    status, data = call(srv, state.token, "POST", "/nowhere", {})
    assert status == 404


def test_classify_before_model_is_ready_gives_503():
    state = make_state(ready=False)
    srv = create_server(state, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        status, data = call(srv, state.token, "GET", "/health")
        assert status == 200 and data["ready"] is False
        status, data = call(srv, state.token, "POST", "/classify", {"paths": ["x.jpg"]})
        assert status == 503
    finally:
        srv.shutdown()
        srv.server_close()


def kenya_cache(isolated_cache):
    from wildid.geo import GeoCache, Place, ResolvedPlace

    cache = GeoCache(isolated_cache / "geo")
    place = Place(7042, "Kenya", "Kenya", 0, (97392, 7042))
    cache.save_place("country:kenya", ResolvedPlace(place=place, label="Kenya"))
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


def test_classify_with_cached_geo_filter(server, bear_jpg, isolated_cache):
    state, srv, _ = server
    kenya_cache(isolated_cache)
    body = {"paths": [str(bear_jpg)], "geo": {"country": "Kenya"}}
    status, doc = call(srv, state.token, "POST", "/classify", body)
    assert status == 200
    assert doc["candidates"]["place_label"] == "Kenya"
    assert doc["candidates"]["count"] == 2
    assert state.clf.applied == ["Ursus arctos", "Ursus americanus"]
    res = doc["results"][0]
    assert res["unconstrained"]["in_candidates"] is True  # anomaly pass is on by default
    # the second identical request hits the in-memory geo plan cache
    status, doc = call(srv, state.token, "POST", "/classify", body)
    assert status == 200 and doc["candidates"]["place_label"] == "Kenya"


def test_classify_geo_without_cache_names_prefetch(server, bear_jpg, isolated_cache):
    state, srv, _ = server
    status, data = call(
        srv,
        state.token,
        "POST",
        "/classify",
        {"paths": [str(bear_jpg)], "geo": {"country": "Nowhere"}},
    )
    assert status == 400
    assert "prefetch" in data["error"]


def test_prefetch_endpoint_fetches_and_invalidates_plans(server, monkeypatch):
    state, srv, _ = server
    state.geo_plans["stale"] = ("x",)
    fetched = {}

    def fake_prefetch_geo(specs, taxa, refresh=False):
        fetched["specs"] = specs
        fetched["taxa"] = taxa
        fetched["refresh"] = refresh
        return [
            SimpleNamespace(
                label="Kenya",
                species=["a", "b"],
                per_taxon={"Mammalia": 2},
                fetched_date="2026-10-24",
                from_cache=False,
            )
        ]

    import wildid.prefetch

    monkeypatch.setattr(wildid.prefetch, "prefetch_geo", fake_prefetch_geo)
    monkeypatch.setattr(wildid.prefetch, "prefetch_synonyms", lambda lists, names: None)
    status, data = call(
        srv, state.token, "POST", "/prefetch", {"country": "Kenya", "refresh": True}
    )
    assert status == 200
    assert data["ok"] is True
    assert data["places"] == [
        {
            "label": "Kenya",
            "species": 2,
            "per_taxon": {"Mammalia": 2},
            "fetched": "2026-10-24",
            "from_cache": False,
        }
    ]
    assert fetched["specs"] == [{"country": "Kenya"}] and fetched["refresh"] is True
    assert not state.geo_plans  # cache invalidated

    status, data = call(srv, state.token, "POST", "/prefetch", {})
    assert status == 400


def test_classify_auto_geo_with_catalog_gps(server, bear_jpg, isolated_cache):
    from datetime import UTC, datetime

    from wildid.geo import GeoCache, Place, ResolvedPlace
    from wildid.gps import place_cache_key

    state, srv, _ = server
    cache = GeoCache(isolated_cache / "geo")
    cache.save_place(
        place_cache_key(-1.4, 35.2, "country"),
        ResolvedPlace(Place(7042, "Kenya", "Kenya", 0, (97392, 7042)), "Kenya"),
    )
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
    body = {
        "paths": [str(bear_jpg), str(bear_jpg)],
        "geo": {"auto": True, "level": "country"},
        "gps": {str(bear_jpg): [-1.4, 35.2]},
    }
    status, doc = call(srv, state.token, "POST", "/classify", body)
    assert status == 200
    assert doc["candidates"]["auto_level"] == "country"
    assert [r["place"]["label"] for r in doc["results"]] == ["Kenya", "Kenya"]
    assert state.clf.applied == ["Ursus arctos", "Ursus americanus"]
    # a photo whose GPS the catalog does not know and whose file has none: unconstrained
    body["gps"] = {}
    status, doc = call(srv, state.token, "POST", "/classify", body)
    assert status == 200 and "no GPS" in doc["results"][0]["place"]["note"]
    status, data = call(
        srv,
        state.token,
        "POST",
        "/classify",
        {"paths": [str(bear_jpg)], "geo": {"auto": True, "level": "county"}},
    )
    assert status == 400


def test_prefetch_endpoint_accepts_gps_points(server, monkeypatch):
    state, srv, _ = server
    captured = {}

    def fake_prefetch_gps(points, level, taxa, refresh=False):
        captured.update(points=points, level=level, taxa=taxa, refresh=refresh)
        return [
            SimpleNamespace(
                label="Kenya",
                species=["a"],
                per_taxon={"Mammalia": 1},
                fetched_date="2026-10-25",
                from_cache=False,
            )
        ]

    import wildid.prefetch

    monkeypatch.setattr(wildid.prefetch, "prefetch_gps", fake_prefetch_gps)
    monkeypatch.setattr(wildid.prefetch, "prefetch_synonyms", lambda lists, names: None)
    status, data = call(
        srv,
        state.token,
        "POST",
        "/prefetch",
        {"gps": [[-1.4, 35.2], [-1.6, 35.2]], "level": "region"},
    )
    assert status == 200 and data["places"][0]["label"] == "Kenya"
    assert captured["points"] == [(-1.4, 35.2), (-1.6, 35.2)] and captured["level"] == "region"
    status, data = call(srv, state.token, "POST", "/prefetch", {"gps": [["x", 1]]})
    assert status == 400
    status, data = call(srv, state.token, "POST", "/prefetch", {"gps": []})
    assert status == 400


def test_shutdown_endpoint_stops_the_server(server):
    state, srv, thread = server
    status, data = call(srv, state.token, "POST", "/shutdown")
    assert status == 200 and data["ok"] is True
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_idle_exit_shuts_down_a_quiet_server():
    state = make_state()
    state.idle_exit_s = 0.2
    srv = create_server(state, 0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    start_idle_monitor(state, srv, check_interval=0.05)
    deadline = time.monotonic() + 5
    while thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not thread.is_alive()
    srv.server_close()


def test_discovery_file_roundtrip(isolated_cache):
    path = write_discovery(4321, "secret-token", "bioclip-2")
    assert path.parent == isolated_cache
    entry = read_discovery()
    assert entry["port"] == 4321 and entry["token"] == "secret-token"
    assert entry["protocol"] == 1 and entry["model"] == "bioclip-2"
    remove_discovery()
    assert read_discovery() is None


def test_bad_json_body_is_a_400(server):
    state, srv, _ = server
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request(
        "POST",
        "/classify",
        body=b"{nope",
        headers={"Authorization": f"Bearer {state.token}"},
    )
    resp = conn.getresponse()
    data = json.loads(resp.read().decode("utf-8"))
    conn.close()
    assert resp.status == 400 and "not valid JSON" in data["error"]
