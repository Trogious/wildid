"""FileResults → the machine-readable run document (plan §2 of lightroom-plugin-plan.md).

One schema for every consumer: `wildid classify --format json` writes it to stdout or
`--output`, and `wildid serve` returns it per request. `protocol` is bumped only when a field
changes meaning or disappears; adding fields is compatible. `keywords` names what a consumer
owns on a photo — the root's subtree and the flat tags — so a re-run can reconcile it with
`suggested_keywords` (the Lightroom plugin does; it knows no keyword names of its own).
"""

from __future__ import annotations

from collections.abc import Sequence

from wildid import __version__
from wildid.constants import ANIMALS_KEYWORD, DEFAULT_MIN_SCORE, KEYWORD_ROOT, WILDLIFE_KEYWORD
from wildid.keywords import suggest
from wildid.output import CandidateInfo, Prediction
from wildid.pipeline import FileResult

PROTOCOL = 1


def prediction_dict(p: Prediction) -> dict:
    return {
        "species": p.species,
        "common_name": p.common_name or None,
        "score": round(p.score, 6),
        "genus": p.genus or None,
        "family": p.family or None,
        "class": p.taxon_class or None,
    }


def candidates_dict(info: CandidateInfo) -> dict:
    return {
        "count": info.count,
        "place_label": info.place_label,
        "taxa": list(info.taxa),
        "fetched": info.fetched,
        "rank": info.rank,
        "auto_level": info.auto_level,
        "auto_places": info.auto_places,
    }


def file_result_dict(
    fr: FileResult,
    *,
    keyword_root: str = KEYWORD_ROOT,
    min_score: float = DEFAULT_MIN_SCORE,
) -> dict:
    out: dict = {
        "path": str(fr.path),
        "label": fr.label,
        "ok": fr.ok,
        "error": fr.error,
    }
    if not fr.ok:
        return out
    suggestion = suggest(
        fr.predictions,
        fr.in_candidates,
        root=keyword_root,
        min_score=min_score,
        detected=fr.crop.detected if fr.crop is not None else None,
        extra_reasons=fr.review_notes,
    )
    out["predictions"] = [prediction_dict(p) for p in fr.predictions]
    out["unconstrained"] = (
        {
            "species": fr.unconstrained.species,
            "common_name": fr.unconstrained.common_name or None,
            "score": round(fr.unconstrained.score, 6),
            "in_candidates": fr.in_candidates,
        }
        if fr.unconstrained is not None
        else None
    )
    out["crop"] = (
        {
            "detected": fr.crop.detected,
            "confidence": fr.crop.confidence,
            "size": list(fr.crop.size) if fr.crop.size else None,
        }
        if fr.crop is not None
        else None
    )
    out["second_opinion"] = (
        {
            "name": fr.opinion.name,
            "common_name": fr.opinion.common_name or None,
            "score": round(fr.opinion.score, 6),
            "verdict": fr.opinion.verdict,
        }
        if fr.opinion is not None
        else None
    )
    out["place"] = (
        {"label": fr.place_label, "candidates": fr.place_candidates, "note": fr.place_note}
        if (fr.place_label is not None or fr.place_note is not None)
        else None
    )
    out["review"] = suggestion.review
    out["review_reasons"] = list(suggestion.review_reasons)
    out["suggested_keywords"] = [
        {"path": list(kw.path), "synonyms": list(kw.synonyms)} for kw in suggestion.keywords
    ]
    return out


def run_document(
    *,
    model: str,
    device: str,
    precision: str | None,
    candidates: CandidateInfo,
    results: Sequence[FileResult],
    keyword_root: str = KEYWORD_ROOT,
    min_score: float = DEFAULT_MIN_SCORE,
    crop_resize: str | None = None,
) -> dict:
    """`crop_resize` is how the photos were resized for the detector: "linear" (the
    platform's OpenCV), "exact" (OpenCV's exact method, meant to be the same on every
    system) or None without the crop stage."""
    return {
        "wildid": __version__,
        "protocol": PROTOCOL,
        "model": model,
        "device": device,
        "precision": precision,
        "crop_resize": crop_resize,
        "candidates": candidates_dict(candidates),
        "keywords": {"root": keyword_root, "flat": [ANIMALS_KEYWORD, WILDLIFE_KEYWORD]},
        "results": [
            file_result_dict(fr, keyword_root=keyword_root, min_score=min_score) for fr in results
        ],
    }
