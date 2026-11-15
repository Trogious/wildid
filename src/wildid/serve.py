"""`wildid serve`: a local HTTP daemon so the Lightroom plugin pays the model load once.

Design (lightroom-plugin-plan.md L1–L4, L9, L10):
- stdlib only (http.server + json): no new dependencies.
- Binds 127.0.0.1 exclusively; the port is OS-assigned (or --port). Discovery goes through
  `serve.json` in the wildid cache dir: {port, token, pid, protocol, ...}, owner-only.
- Every request must carry the bearer token. Loopback alone is not a boundary: any local
  process, and a browser page via DNS rebinding, can reach 127.0.0.1 — the token is the wall.
- One inference lock: requests queue, the model is never re-entered. Callers (the plugin)
  chunk their photo lists and get progress for free.
- Geo lists are read cache-first and never fetched during /classify; POST /prefetch is the
  explicit online path (same code as `wildid prefetch` for geo lists + GBIF synonyms).
- --idle-exit frees the GPU: the process exits after N quiet seconds; the plugin restarts it.

Models (plan B4): the `--model` given at start-up loads immediately; any other known model is
loaded lazily, under the same lock, on the first `/classify` or `/warmup` that names it, and
then stays for the process lifetime (torch does not reliably return VRAM — `--idle-exit` is
the release). `/health` reports per-model state and the GPU's memory so the plugin can decide
whether keeping both models loaded is sane; on Apple Silicon that is unified memory
(`vram.kind == "unified"`), reported as what Metal recommends a process stays under.

Endpoints (JSON in, JSON out, UTF-8):
  GET  /health    {ready, protocol, wildid, model, default_model, models, device, vram,
                   uptime_s, error}
  POST /classify  {paths: [...], model?, k?, batch_size?, geo?: {continent|country|region|
                   place_id, taxa?, rank?}, crop?, crop_exact?, detector?, second_opinion?,
                   anomaly?, min_score?, keyword_root?}  → the results.run_document schema
  POST /warmup    {model}  → loads that model now (no-op when already loaded)
  POST /prefetch  {continent|country|region|place_id, taxa?, refresh?}  → fetches geo lists
  POST /shutdown  {}
"""

from __future__ import annotations

import dataclasses
import functools
import json
import logging
import os
import platform
import secrets
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from wildid import __version__
from wildid.constants import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MIN_SCORE,
    DEFAULT_TAXA,
    HF_MODEL_IDS,
    KEYWORD_ROOT,
    cache_dir,
)
from wildid.output import CandidateInfo
from wildid.pipeline import StageError, Stages, iter_results, load_stages
from wildid.results import PROTOCOL, run_document

log = logging.getLogger(__name__)

SERVE_FILE = "serve.json"
MAX_BODY_BYTES = 8 << 20
MAX_PATHS = 2000
DEFAULT_IDLE_EXIT_S = 900.0
DEFAULT_TOP_K = 3
GEO_PLAN_CACHE = 8  # (place, taxa, rank) entries kept in memory
KNOWN_MODELS: tuple[str, ...] = tuple(HF_MODEL_IDS)  # light: no torch import needed


@functools.lru_cache(maxsize=1)
def apple_chip_name() -> str:
    """The chip as macOS names it ("Apple M5 Pro"), for the memory line the plugin shows."""
    try:
        out = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        out = ""
    return out or platform.processor() or "Apple Silicon"


def probe_vram() -> dict | None:
    """Memory the model can use, in SI gigabytes, or None when there is no GPU backend or the
    probe fails. CUDA: total/free of device 0. Apple Silicon (MPS): the machine's memory is
    shared with the system, so `total_gb` is what Metal recommends a process stays under
    (`torch.mps.recommended_max_memory()`), `free_gb` that minus what the Metal driver has
    allocated for this process, and `kind` says "unified". Importing torch here is only cheap
    once the model loader has done it."""
    try:
        import torch

        if torch.cuda.is_available():
            free, total = torch.cuda.mem_get_info(0)
            return {
                "device_name": torch.cuda.get_device_name(0),
                "total_gb": round(total / 1e9, 1),
                "free_gb": round(free / 1e9, 1),
            }
        mps = getattr(torch.backends, "mps", None)
        if mps is not None and mps.is_available():
            total = torch.mps.recommended_max_memory()
            used = torch.mps.driver_allocated_memory()
            return {
                "device_name": apple_chip_name(),
                "total_gb": round(total / 1e9, 1),
                "free_gb": round(max(total - used, 0) / 1e9, 1),
                "kind": "unified",
            }
        return None
    except Exception:  # noqa: BLE001 - a failed probe just means "unknown"
        return None


class RequestError(Exception):
    """A client error: maps to the given HTTP status with a JSON body."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def serve_json_path() -> Path:
    return cache_dir() / SERVE_FILE


def write_discovery(port: int, token: str, model: str) -> Path:
    """The file the Lightroom plugin reads to find and authenticate against the daemon."""
    path = serve_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "port": port,
        "token": token,
        "pid": os.getpid(),
        "protocol": PROTOCOL,
        "wildid": __version__,
        "model": model,
        "started_at": int(time.time()),
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)  # best effort; a no-op on Windows ACL filesystems
    except OSError:
        pass
    return path


def read_discovery() -> dict | None:
    try:
        return json.loads(serve_json_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def remove_discovery() -> None:
    serve_json_path().unlink(missing_ok=True)


def existing_server_alive(entry: dict, timeout: float = 1.5) -> bool:
    """True when the serve.json entry answers /health (so a second server must not start)."""
    import urllib.error
    import urllib.request

    port = entry.get("port")
    token = entry.get("token", "")
    if not isinstance(port, int):
        return False
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/health", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


# ----------------------------------------------------------------------------------------------
# state
# ----------------------------------------------------------------------------------------------


@dataclass
class ServerState:
    model_name: str  # the default model: loaded at start-up, used when a request names none
    device: str = "auto"
    precision: str = "auto"
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    idle_exit_s: float = DEFAULT_IDLE_EXIT_S
    classifiers: dict[str, Any] = field(default_factory=dict)  # model name -> Classifier
    load_errors: dict[str, str] = field(default_factory=dict)  # model name -> last failure
    ready: bool = False  # the default model is loaded
    error: str | None = None  # the default model's load failure, if any
    vram: dict | None = None  # probe_vram() result from start-up (None = no GPU / unknown)
    started: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)
    stages_cache: dict[tuple, Stages] = field(default_factory=dict)
    geo_plans: OrderedDict = field(default_factory=OrderedDict)

    @property
    def clf(self) -> Any:
        """The default classifier (None until loaded)."""
        return self.classifiers.get(self.model_name)

    def touch(self) -> None:
        self.last_activity = time.monotonic()

    def _load(self, name: str) -> Any:
        """Load one model (raises ModelLoadError). Callers hold the lock or run at start-up."""
        from wildid.model import load_classifier

        t0 = time.perf_counter()
        clf = load_classifier(name, self.device)
        clf.apply_precision(self.precision)
        self.classifiers[name] = clf
        self.load_errors.pop(name, None)
        log.info(
            "model ready: %s on %s (%.1f s)", clf.spec.name, clf.device, time.perf_counter() - t0
        )
        return clf

    def load_model(self) -> None:
        """Start-up loader: runs in a thread while the server already answers /health."""
        from wildid.model import ModelLoadError

        self.vram = probe_vram()
        try:
            self._load(self.model_name)
            self.ready = True
        except ModelLoadError as exc:
            self.error = str(exc) + (
                f"; run `wildid prefetch --model {self.model_name}` while online"
                if exc.missing_cache
                else ""
            )
            self.load_errors[self.model_name] = self.error
            log.error("model load failed: %s", self.error)

    def get_classifier(self, name: str) -> Any:
        """The classifier for `name`, loading it lazily (lock held by the caller)."""
        from wildid.model import ModelLoadError

        clf = self.classifiers.get(name)
        if clf is not None:
            return clf
        try:
            return self._load(name)
        except ModelLoadError as exc:
            message = str(exc) + (
                f"; run `wildid prefetch --model {name}` while online" if exc.missing_cache else ""
            )
            self.load_errors[name] = message
            log.error("model load failed: %s", message)
            raise RequestError(message, status=503) from exc

    def get_stages(
        self,
        crop: bool,
        detector: str,
        second_opinion: bool,
        device: str,
        crop_exact: bool = False,
    ) -> Stages:
        """Stages per (crop, detector, second-opinion) combination, loaded once and kept.
        `crop_exact` is a setting of the request, not of the loaded models: the cached stages
        are handed out as a copy that carries it."""
        if not crop and not second_opinion:
            return Stages()
        key = (crop or second_opinion, detector, second_opinion)
        stages = self.stages_cache.get(key)
        if stages is None:
            stages = load_stages(crop or second_opinion, detector, second_opinion, device)
            self.stages_cache[key] = stages
        return dataclasses.replace(stages, crop_exact=crop_exact)

    def model_status(self) -> dict:
        names = sorted(set(KNOWN_MODELS) | set(self.classifiers))
        return {
            name: {"loaded": name in self.classifiers, "error": self.load_errors.get(name)}
            for name in names
        }

    def live_vram(self) -> dict | None:
        """Fresh numbers when torch is already imported (cheap), else the start-up probe."""
        if "torch" in sys.modules:
            return probe_vram()
        return self.vram

    def geo_plan(self, geo: dict) -> tuple:
        """(GeoList, synonyms, rank) for a request's geo spec; disk-cache only (plan L10)."""
        from wildid.geo import (
            GEO_RANKS,
            GeoCache,
            parse_taxa,
            resolve_place,
            species_list,
        )
        from wildid.synonyms import resolve_names

        rank = geo.get("rank") or "species"
        if rank not in GEO_RANKS:
            raise RequestError(f"unknown geo rank {rank!r}; choose from {', '.join(GEO_RANKS)}")
        taxa_value = geo.get("taxa") or ",".join(DEFAULT_TAXA)
        if isinstance(taxa_value, list):
            taxa_value = ",".join(str(t) for t in taxa_value)
        key = (
            geo.get("continent"),
            geo.get("country"),
            geo.get("region"),
            geo.get("place_id"),
            taxa_value,
            rank,
        )
        cached = self.geo_plans.get(key)
        if cached is not None:
            self.geo_plans.move_to_end(key)
            return cached
        taxa = parse_taxa(taxa_value)
        cache = GeoCache()
        resolved = resolve_place(
            continent=geo.get("continent"),
            country=geo.get("country"),
            region=geo.get("region"),
            place_id=geo.get("place_id"),
            client=None,
            cache=cache,
            offline=True,
        )
        geo_list = species_list(resolved, taxa, client=None, cache=cache, offline=True)
        synonyms, _ = resolve_names(geo_list.species, cache=cache, offline=True)
        plan = (geo_list, synonyms, rank, cache)
        self.geo_plans[key] = plan
        while len(self.geo_plans) > GEO_PLAN_CACHE:
            self.geo_plans.popitem(last=False)
        return plan


# ----------------------------------------------------------------------------------------------
# request handling
# ----------------------------------------------------------------------------------------------


def handle_health(state: ServerState, body: dict) -> dict:
    return {
        "ready": state.ready,
        "protocol": PROTOCOL,
        "wildid": __version__,
        "model": state.clf.spec.name if state.ready else state.model_name,
        "default_model": state.model_name,
        "models": state.model_status(),
        "device": state.clf.device if state.ready else None,
        "vram": state.live_vram(),
        "uptime_s": int(time.monotonic() - state.started),
        "error": state.error,
    }


def _requested_model(state: ServerState, body: dict) -> str:
    name = body.get("model") or state.model_name
    if not isinstance(name, str) or (name not in KNOWN_MODELS and name not in state.classifiers):
        raise RequestError(f"unknown model {name!r}; choose from {', '.join(KNOWN_MODELS)}")
    return name


def handle_warmup(state: ServerState, body: dict) -> dict:
    """Load a model now so the first classify with it does not pay the load time."""
    name = _requested_model(state, body)
    if not state.ready:
        raise RequestError(state.error or "model is still loading", status=503)
    with state.lock:
        already = name in state.classifiers
        t0 = time.perf_counter()
        state.get_classifier(name)
        seconds = 0.0 if already else time.perf_counter() - t0
    return {
        "ok": True,
        "model": name,
        "already_loaded": already,
        "load_seconds": round(seconds, 1),
        "models": state.model_status(),
        "vram": state.live_vram(),
    }


def handle_classify(state: ServerState, body: dict) -> dict:
    from wildid.geo import GeoError, build_filter
    from wildid.synonyms import canonical_map

    if not state.ready:
        raise RequestError(state.error or "model is still loading", status=503)
    model_name = _requested_model(state, body)
    paths_raw = body.get("paths")
    if not isinstance(paths_raw, list) or not paths_raw:
        raise RequestError("'paths' must be a non-empty list of file paths")
    if len(paths_raw) > MAX_PATHS:
        raise RequestError(f"at most {MAX_PATHS} paths per request; chunk the workload")
    if not all(isinstance(p, str) and p for p in paths_raw):
        raise RequestError("'paths' entries must be non-empty strings")
    paths = [Path(p) for p in paths_raw]

    def _positive_int(name: str, default: int) -> int:
        value = body.get(name)
        if value is None:
            return default
        try:
            value = int(value)
        except (TypeError, ValueError) as exc:
            raise RequestError(f"'{name}' must be an integer") from exc
        if value < 1:
            raise RequestError(f"'{name}' must be >= 1")
        return value

    top_k = _positive_int("k", DEFAULT_TOP_K)
    batch_size = _positive_int("batch_size", DEFAULT_BATCH_SIZE)
    min_score = float(body.get("min_score", DEFAULT_MIN_SCORE))
    keyword_root = str(body.get("keyword_root") or KEYWORD_ROOT)
    geo = body.get("geo")
    auto = isinstance(geo, dict) and bool(geo.get("auto"))
    gps_override: dict | None = None
    auto_level = auto_taxa = auto_rank = ""
    if auto:
        from wildid.geo import GEO_RANKS, GeoError, parse_taxa
        from wildid.gps import DEFAULT_GPS_LEVEL, GPS_LEVELS

        auto_level = str(geo.get("level") or DEFAULT_GPS_LEVEL)
        if auto_level not in GPS_LEVELS:
            raise RequestError(
                f"unknown geo level {auto_level!r}; choose from {', '.join(GPS_LEVELS)}"
            )
        auto_rank = str(geo.get("rank") or "species")
        if auto_rank not in GEO_RANKS:
            raise RequestError(
                f"unknown geo rank {auto_rank!r}; choose from {', '.join(GEO_RANKS)}"
            )
        taxa_value = geo.get("taxa") or ",".join(DEFAULT_TAXA)
        if isinstance(taxa_value, list):
            taxa_value = ",".join(str(t) for t in taxa_value)
        try:
            parse_taxa(taxa_value)
        except GeoError as exc:
            raise RequestError(str(exc)) from exc
        auto_taxa = taxa_value
        raw_gps = body.get("gps") or {}
        if not isinstance(raw_gps, dict):
            raise RequestError("'gps' must be an object mapping each path to [lat, lon]")
        gps_override = {}
        for p, coords in raw_gps.items():
            try:
                gps_override[Path(str(p))] = (float(coords[0]), float(coords[1]))
            except (TypeError, ValueError, IndexError, KeyError):
                gps_override[Path(str(p))] = None
    anomaly = bool(body.get("anomaly", True))
    crop = bool(body.get("crop", False))
    second_opinion = bool(body.get("second_opinion", False))
    crop_exact = bool(body.get("crop_exact", False))
    detector = str(body.get("detector") or "mdv6-yolov9-c")

    with state.lock:
        clf = state.get_classifier(model_name)  # lazy-loads a non-default model
        clf.clear_filter()
        clf.place_label = None
        clf.anomaly_check = anomaly
        candidates = CandidateInfo(count=clf.candidate_count)
        if auto:
            from wildid.autogeo import AutoGeoSettings, auto_candidates, plan_groups, run_groups
            from wildid.geo import GeoCache

            try:
                stages = state.get_stages(crop, detector, second_opinion, clf.device, crop_exact)
            except StageError as exc:
                raise RequestError(str(exc)) from exc
            settings = AutoGeoSettings(
                level=auto_level, taxa=auto_taxa, rank=auto_rank, offline=True, client=None
            )
            cache = GeoCache()
            groups = plan_groups(paths, settings, cache=cache, gps_override=gps_override)
            collected = run_groups(
                clf,
                groups,
                settings,
                cache=cache,
                top_k=top_k,
                batch_size=batch_size,
                stages=stages,
                root=None,
            )
            # back to request order; a path listed twice gets its one result twice
            by_path = {fr.path: fr for fr in collected}
            results = [by_path[p] for p in paths]
            return run_document(
                model=clf.spec.name,
                device=clf.device,
                precision=clf.precision,
                candidates=auto_candidates(groups, auto_level),
                results=results,
                keyword_root=keyword_root,
                min_score=min_score,
                crop_resize=stages.crop_resize,
            )
        if isinstance(geo, dict) and any(
            geo.get(k) is not None for k in ("continent", "country", "region", "place_id")
        ):
            try:
                geo_list, synonyms, rank, cache = state.geo_plan(geo)
                clf.synonyms = canonical_map(cache)
                result = build_filter(clf, geo_list, rank=rank, synonyms=synonyms)
            except GeoError as exc:
                hint = (
                    "; POST /prefetch (or run `wildid prefetch` with these geo arguments) "
                    "while online"
                    if getattr(exc, "needs_prefetch", False)
                    else ""
                )
                raise RequestError(f"{exc}{hint}") from exc
            candidates = CandidateInfo(
                count=result.species_count,
                place_label=geo_list.label,
                taxa=geo_list.taxa,
                fetched=geo_list.fetched_date,
                rank=result.rank,
            )
        try:
            stages = state.get_stages(crop, detector, second_opinion, clf.device, crop_exact)
        except StageError as exc:
            raise RequestError(str(exc)) from exc
        results = []
        for chunk in iter_results(clf, paths, top_k, batch_size, stages, root=None):
            results.extend(chunk)
        return run_document(
            model=clf.spec.name,
            device=clf.device,
            precision=clf.precision,
            candidates=candidates,
            results=results,
            keyword_root=keyword_root,
            min_score=min_score,
            crop_resize=stages.crop_resize,
        )


def handle_prefetch(state: ServerState, body: dict) -> dict:
    """Fetch (or renew) geo species lists + GBIF synonyms — the one online endpoint."""
    from wildid.geo import GeoError
    from wildid.prefetch import prefetch_geo, prefetch_synonyms

    spec: dict = {}
    for key in ("continent", "country", "region", "place_id"):
        if body.get(key) is not None:
            spec[key] = body[key]
    gps_points = body.get("gps")
    if gps_points is None and not spec:
        raise RequestError("give a place: continent, country [+ region], place_id, or gps")
    taxa = body.get("taxa") or ",".join(DEFAULT_TAXA)
    if isinstance(taxa, list):
        taxa = ",".join(str(t) for t in taxa)
    refresh = bool(body.get("refresh", False))
    points: list[tuple[float, float]] = []
    level = ""
    if gps_points is not None:
        from wildid.gps import DEFAULT_GPS_LEVEL, GPS_LEVELS

        if not isinstance(gps_points, list) or not gps_points:
            raise RequestError("'gps' must be a non-empty list of [lat, lon] pairs")
        for item in gps_points:
            try:
                points.append((float(item[0]), float(item[1])))
            except (TypeError, ValueError, IndexError, KeyError) as exc:
                raise RequestError("'gps' entries must be [lat, lon] numbers") from exc
        level = str(body.get("level") or DEFAULT_GPS_LEVEL)
        if level not in GPS_LEVELS:
            raise RequestError(f"unknown geo level {level!r}; choose from {', '.join(GPS_LEVELS)}")
    with state.lock:
        try:
            if points:
                from wildid.prefetch import prefetch_gps

                lists = prefetch_gps(points, level, taxa, refresh=refresh)
            else:
                lists = prefetch_geo([spec], taxa, refresh=refresh)
            prefetch_synonyms(lists, [state.model_name])
        except GeoError as exc:
            raise RequestError(str(exc)) from exc
        state.geo_plans.clear()  # fresh lists invalidate cached plans
    return {
        "ok": True,
        "places": [
            {
                "label": lst.label,
                "species": len(lst.species),
                "per_taxon": lst.per_taxon,
                "fetched": lst.fetched_date,
                "from_cache": lst.from_cache,
            }
            for lst in lists
        ],
    }


ROUTES = {
    ("GET", "/health"): handle_health,
    ("POST", "/classify"): handle_classify,
    ("POST", "/warmup"): handle_warmup,
    ("POST", "/prefetch"): handle_prefetch,
}


def make_handler(state: ServerState, server_box: dict) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = f"wildid/{__version__}"
        protocol_version = "HTTP/1.0"  # one request per connection: simple and robust

        def log_message(self, fmt: str, *args) -> None:  # quiet by default
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, payload: dict) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            header = self.headers.get("Authorization", "")
            token = header.removeprefix("Bearer ").strip() if header else ""
            token = token or self.headers.get("X-WildID-Token", "")
            return bool(token) and secrets.compare_digest(token, state.token)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY_BYTES:
                raise RequestError("request body too large", status=413)
            raw = self.rfile.read(length) if length else b""
            if not raw:
                return {}
            try:
                body = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise RequestError(f"request body is not valid JSON: {exc}") from exc
            if not isinstance(body, dict):
                raise RequestError("request body must be a JSON object")
            return body

        def _dispatch(self, method: str) -> None:
            if not self._authorized():
                self._send(401, {"error": "missing or wrong token"})
                return
            state.touch()
            try:
                if method == "POST" and self.path == "/shutdown":
                    self._send(200, {"ok": True})
                    log.info("shutdown requested")
                    server = server_box.get("server")
                    if server is not None:
                        threading.Thread(target=server.shutdown, daemon=True).start()
                    return
                handler = ROUTES.get((method, self.path))
                if handler is None:
                    self._send(404, {"error": f"no such endpoint: {method} {self.path}"})
                    return
                body = self._body() if method == "POST" else {}
                self._send(200, handler(state, body))
            except RequestError as exc:
                self._send(exc.status, {"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 - a request must never kill the server
                log.exception("unhandled error on %s %s", method, self.path)
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})
            finally:
                state.touch()

        def do_GET(self) -> None:  # noqa: N802 - http.server API
            self._dispatch("GET")

        def do_POST(self) -> None:  # noqa: N802 - http.server API
            self._dispatch("POST")

    return Handler


# ----------------------------------------------------------------------------------------------
# server lifecycle
# ----------------------------------------------------------------------------------------------


def create_server(state: ServerState, port: int = 0) -> ThreadingHTTPServer:
    """Bind 127.0.0.1 (never a routable interface) and wire the handler to the state."""
    server_box: dict = {}
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, server_box))
    server.daemon_threads = True
    server_box["server"] = server
    return server


def start_idle_monitor(
    state: ServerState, server: ThreadingHTTPServer, check_interval: float = 15.0
) -> threading.Thread:
    """Shut the server down after idle_exit_s seconds without a request (0 disables)."""

    def monitor() -> None:
        while True:
            time.sleep(check_interval)
            if state.idle_exit_s <= 0:
                continue
            idle = time.monotonic() - state.last_activity
            if idle >= state.idle_exit_s:
                log.info("idle for %.0f s; exiting (--idle-exit %.0f)", idle, state.idle_exit_s)
                server.shutdown()
                return

    thread = threading.Thread(target=monitor, daemon=True, name="wildid-idle-exit")
    thread.start()
    return thread


def run_server(
    model: str,
    device: str = "auto",
    precision: str = "auto",
    port: int = 0,
    idle_exit: float = DEFAULT_IDLE_EXIT_S,
) -> int:
    """The `wildid serve` entry point. Returns the process exit code."""
    existing = read_discovery()
    if existing is not None and existing_server_alive(existing):
        log.error(
            "a wildid server is already running (pid %s, port %s); stop it first "
            "(POST /shutdown) or use the running one",
            existing.get("pid"),
            existing.get("port"),
        )
        return 1
    state = ServerState(model_name=model, device=device, precision=precision, idle_exit_s=idle_exit)
    server = create_server(state, port)
    actual_port = server.server_address[1]
    write_discovery(actual_port, state.token, model)
    log.info(
        "wildid serve on 127.0.0.1:%d (token in %s, idle-exit %.0f s)",
        actual_port,
        serve_json_path(),
        idle_exit,
    )
    loader = threading.Thread(target=state.load_model, daemon=True, name="wildid-model-load")
    loader.start()
    start_idle_monitor(state, server)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        remove_discovery()
        log.info("wildid serve stopped")
    return 0
