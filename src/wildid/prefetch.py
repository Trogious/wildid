"""`wildid prefetch`: the only code path allowed to download models and embeddings.

BioCLIP models and TreeOfLife embeddings go into the Hugging Face cache (HF_HOME) through the
same functions the runtime uses. Detector and SpeciesNet weights go into the wildid cache
(`constants.models_dir()`), verified by SHA-256, so what prefetch fetched is exactly what the
offline classify path will find.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

import requests

from wildid.constants import USER_AGENT, models_dir

log = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT_S = (10.0, 120.0)


def prefetch_model(name: str) -> list[Path]:
    """Download model config + weights and the TreeOfLife text embeddings for one model."""
    from huggingface_hub import hf_hub_download
    from open_clip.pretrained import download_pretrained_from_hf

    from wildid.model import MODELS

    spec = MODELS[name]
    paths: list[Path] = []
    t0 = time.perf_counter()
    log.info("prefetch %s: model %s", name, spec.hf_model_id)
    paths.append(Path(hf_hub_download(spec.hf_model_id, "open_clip_config.json")))
    # open_clip prefers open_clip_model.safetensors and falls back to open_clip_pytorch_model.bin
    paths.append(Path(download_pretrained_from_hf(spec.hf_model_id)))
    log.info("prefetch %s: TreeOfLife embeddings %s/%s", name, spec.tol_repo, spec.emb_npy)
    paths.append(Path(hf_hub_download(spec.tol_repo, spec.emb_json, repo_type="dataset")))
    paths.append(Path(hf_hub_download(spec.tol_repo, spec.emb_npy, repo_type="dataset")))
    size = sum(p.stat().st_size for p in paths)
    log.info("prefetch %s: %.2f GB in cache (%.0f s)", name, size / 1e9, time.perf_counter() - t0)
    return paths


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fd:
        for chunk in iter(lambda: fd.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(url: str, dest: Path, sha256: str | None = None) -> Path:
    """Stream `url` to `dest` (atomic rename), verifying the SHA-256 when one is pinned.
    An existing file with the right hash is left alone."""
    if dest.exists() and (sha256 is None or sha256_of(dest) == sha256):
        log.info("%s already in cache", dest.name)
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    t0 = time.perf_counter()
    log.info("downloading %s", url)
    digest = hashlib.sha256()
    with requests.get(
        url, stream=True, timeout=DOWNLOAD_TIMEOUT_S, headers={"User-Agent": USER_AGENT}
    ) as resp:
        resp.raise_for_status()
        with open(part, "wb") as fd:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fd.write(chunk)
                digest.update(chunk)
    if sha256 is not None and digest.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {url}: got {digest.hexdigest()}")
    part.replace(dest)
    log.info(
        "%s: %.0f MB in %.0f s", dest.name, dest.stat().st_size / 1e6, time.perf_counter() - t0
    )
    return dest


def prefetch_detector(name: str) -> Path:
    """MegaDetector weights for `--crop`."""
    from wildid.detector import DETECTORS

    spec = DETECTORS[name]
    return download_file(spec.url, spec.path, spec.sha256)


def prefetch_speciesnet() -> Path:
    """SpeciesNet classifier files for `--second-opinion` (Kaggle tarball, extracted)."""
    from wildid.speciesnet import SPECIESNET_SHA256, SPECIESNET_URL, speciesnet_dir

    target = speciesnet_dir()
    if (target / "info.json").exists():
        log.info("SpeciesNet already in cache (%s)", target)
        return target
    archive = download_file(
        SPECIESNET_URL, models_dir() / f"{target.name}.tar.gz", SPECIESNET_SHA256
    )
    tmp = target.with_name(target.name + ".extracting")
    tmp.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:gz") as tar:
        tar.extractall(tmp, filter="data")
    if not (tmp / "info.json").exists():  # archive wrapped in a top-level folder?
        inner = [p for p in tmp.iterdir() if (p / "info.json").exists()]
        if not inner:
            raise RuntimeError(f"no info.json in {archive}")
        tmp = inner[0]
    tmp.replace(target)
    archive.unlink(missing_ok=True)
    log.info("SpeciesNet extracted to %s", target)
    return target


def prefetch_geo(specs: list[dict], taxa: str, *, refresh: bool = False) -> list:
    """Resolve each place and fetch (or renew stale) species lists for the given taxa."""
    from wildid.geo import GeoCache, INatClient, parse_taxa, resolve_place, species_list

    taxa_tuple = parse_taxa(taxa)
    cache = GeoCache()
    client = INatClient()
    lists = []
    for spec in specs:
        resolved = resolve_place(client=client, cache=cache, **spec)
        lst = species_list(
            resolved,
            taxa_tuple,
            client=client,
            cache=cache,
            refresh=refresh,
            refresh_stale=True,
        )
        log.info(
            "geo ready: %s, %d species (%s), fetched %s%s",
            lst.label,
            len(lst.species),
            ", ".join(f"{t} {n}" for t, n in lst.per_taxon.items()),
            lst.fetched_date,
            " (cached)" if lst.from_cache else "",
        )
        lists.append(lst)
    return lists


def prefetch_gps(points: list, level: str, taxa: str, *, refresh: bool = False) -> list:
    """Resolve GPS positions (one lookup per grid cell) to places and fetch their species
    lists — the online half of `--geo-auto`."""
    from wildid.geo import GeoCache, INatClient, parse_taxa, species_list
    from wildid.gps import distinct_cells, resolve_gps_place

    taxa_tuple = parse_taxa(taxa)
    cache = GeoCache()
    client = INatClient()
    places: dict = {}
    cells = distinct_cells(points)
    for lat, lon in cells:
        resolved = resolve_gps_place(lat, lon, level, cache=cache, client=client)
        places.setdefault(resolved.place.id, resolved)
    log.info(
        "GPS: %d position(s) in %d cell(s) -> %d place(s)", len(points), len(cells), len(places)
    )
    lists = []
    for resolved in places.values():
        lst = species_list(
            resolved,
            taxa_tuple,
            client=client,
            cache=cache,
            refresh=refresh,
            refresh_stale=True,
        )
        log.info(
            "geo ready: %s, %d species (%s), fetched %s%s",
            lst.label,
            len(lst.species),
            ", ".join(f"{t} {n}" for t, n in lst.per_taxon.items()),
            lst.fetched_date,
            " (cached)" if lst.from_cache else "",
        )
        lists.append(lst)
    return lists


def tol_species_names(model_name: str) -> set[str]:
    """Species names of a model's TreeOfLife table, read from the cached names JSON (no model
    load needed)."""
    from huggingface_hub import hf_hub_download

    from wildid.model import MODELS

    spec = MODELS[model_name]
    path = hf_hub_download(spec.tol_repo, spec.emb_json, repo_type="dataset")
    with open(path, encoding="utf-8") as fd:
        names = json.load(fd)
    return {f"{entry[0][-2]} {entry[0][-1]}" for entry in names}


def prefetch_synonyms(geo_lists: list, model_names: list[str]) -> None:
    """Look up GBIF spellings for regional names the prefetched model(s) do not know."""
    from wildid.geo import GeoCache
    from wildid.synonyms import GbifClient, resolve_names

    known: set[str] = set()
    for name in model_names:
        known |= tol_species_names(name)
    unmatched = list(dict.fromkeys(s for lst in geo_lists for s in lst.species if s not in known))
    if not unmatched:
        return
    cache = GeoCache()
    cached_before = len(cache.load_names())
    t0 = time.perf_counter()
    candidates, skipped = resolve_names(unmatched, cache=cache, client=GbifClient())
    resolved = sum(1 for n in unmatched if any(c in known for c in candidates.get(n, ())))
    log.info(
        "GBIF synonyms: %d of %d unmatched names now map to a model name (%d new lookups, "
        "%d skipped, %.0f s)",
        resolved,
        len(unmatched),
        len(cache.load_names()) - cached_before,
        skipped,
        time.perf_counter() - t0,
    )


def verify_offline(name: str, device: str = "auto", extra_args: list[str] | None = None) -> bool:
    """Run the real classify path in a child process with the network forbidden.

    This is the pre-trip guarantee: if it passes here, `wildid --offline` will start without
    touching the network on this machine.
    """
    from PIL import Image

    with tempfile.TemporaryDirectory(prefix="wildid-verify-") as tmp:
        probe = Path(tmp) / "probe.jpg"
        Image.new("RGB", (256, 256), (120, 110, 90)).save(probe, "JPEG")
        cmd = [
            sys.executable,
            "-m",
            "wildid",
            "classify",
            str(probe),
            "--model",
            name,
            "--device",
            device,
            "--offline",
            "--k",
            "1",
            *(extra_args or []),
        ]
        log.info("verify %s offline: %s", name, " ".join(cmd[2:]))
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode != 0:
        log.error(
            "offline verification of %s failed (exit %d):\n%s",
            name,
            proc.returncode,
            proc.stderr.strip(),
        )
        return False
    log.info("verify %s offline: ok", name)
    return True
