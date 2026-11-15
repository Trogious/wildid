"""iNaturalist ↔ TreeOfLife name reconciliation through the GBIF backbone (post-MVP item 6).

TreeOfLife-200M's names come from the GBIF backbone, iNaturalist's from its own taxonomy, so a
few percent of a regional list fail to match by spelling (*Tragelaphus oryx* vs *Taurotragus
oryx*). For each unmatched name GBIF's `species/match` gives the backbone taxon (accepted or
synonym) and `species/{key}/synonyms` its other spellings; the first spelling the model knows
is used. Lookups happen in `wildid prefetch` only and are cached per name in
`<cache>/geo/gbif-names.json`; the classify path reads the cache and never calls GBIF.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

import requests

from wildid.geo import GeoCache, GeoNetworkError, JsonClient

log = logging.getLogger(__name__)

GBIF_API = "https://api.gbif.org/v1"
GBIF_INTERVAL_S = 0.25  # polite: GBIF has no hard limit, ~4 requests/s is fine
MIN_FUZZY_CONFIDENCE = 95  # a fuzzy match is only a spelling variant above this
SAVE_EVERY = 25  # names; keeps progress on an interrupted prefetch


class GbifClient(JsonClient):
    def __init__(
        self,
        session: requests.Session | None = None,
        *,
        interval_s: float = GBIF_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ):
        super().__init__(GBIF_API, "GBIF", session, interval_s=interval_s, sleep=sleep)


def gbif_candidates(client: JsonClient, name: str) -> dict:
    """Alternative spellings of `name` according to the GBIF backbone."""
    m = client.get("species/match", name=name, strict="true")
    match_type = m.get("matchType") or "NONE"
    confidence = int(m.get("confidence") or 0)
    usable = match_type == "EXACT" or (match_type == "FUZZY" and confidence >= MIN_FUZZY_CONFIDENCE)
    if not usable or not m.get("usageKey"):
        return {"accepted": None, "candidates": [], "match": match_type}
    accepted = m.get("species") or None  # canonical name of the accepted species
    key = m.get("acceptedUsageKey") or m.get("usageKey")
    synonyms: list[str] = []
    js = client.get(f"species/{key}/synonyms", limit=200)
    for row in js.get("results") or []:
        if row.get("rank") == "SPECIES" and row.get("canonicalName"):
            synonyms.append(row["canonicalName"])
    seen: dict[str, None] = {}
    for cand in (accepted, m.get("canonicalName"), *synonyms):
        if cand and cand != name:
            seen.setdefault(cand, None)
    return {
        "accepted": accepted,
        "candidates": list(seen),
        "match": f"{match_type}/{m.get('status') or '?'}",
    }


def resolve_names(
    names: Iterable[str],
    *,
    cache: GeoCache,
    client: JsonClient | None = None,
    offline: bool = False,
) -> tuple[dict[str, list[str]], int]:
    """Candidate spellings per name, cache-first. Returns (name -> candidates, names skipped
    because they are not cached and no lookup was allowed/possible)."""
    data = cache.load_names()
    out: dict[str, list[str]] = {}
    skipped = 0
    pending = 0
    failed = False
    for name in dict.fromkeys(names):
        entry = data.get(name)
        if entry is None:
            if offline or client is None or failed:
                skipped += 1
                continue
            try:
                entry = gbif_candidates(client, name)
            except GeoNetworkError as exc:
                log.warning("GBIF lookup stopped at %r: %s", name, exc)
                failed = True
                skipped += 1
                continue
            entry["fetched_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            data[name] = entry
            pending += 1
            if pending >= SAVE_EVERY:
                cache.save_names(data)
                pending = 0
        out[name] = list(entry.get("candidates") or [])
    if pending:
        cache.save_names(data)
    return out, skipped


def canonical_map(cache: GeoCache) -> dict[str, str]:
    """Every spelling seen in the cache -> its GBIF accepted name (for top-k dedupe)."""
    out: dict[str, str] = {}
    for name, entry in cache.load_names().items():
        accepted = entry.get("accepted") or name
        out[accepted] = accepted
        out[name] = accepted
        for cand in entry.get("candidates") or []:
            out.setdefault(cand, accepted)
    return out
