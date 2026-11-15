"""Prediction → Lightroom keyword policy (plan L5/L6 in lightroom-plugin-plan.md).

This is the single source of truth for how results become keywords: the JSON output, the XMP
sidecar writer and the `wildid serve` responses all call suggest(), so the Lua plugin never
re-implements policy. Top-1 only — top-k as keywords is noise; the review flag marks photos a
human should look at. Photos judged to contain an animal also get the flat tags "animals"
and — unless the species is domesticated — "wildlife".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wildid.constants import (
    ANIMALS_KEYWORD,
    DEFAULT_MIN_SCORE,
    DOMESTIC_SPECIES,
    KEYWORD_ROOT,
    REVIEW_KEYWORD,
    WILDLIFE_KEYWORD,
)
from wildid.output import Prediction


@dataclass(frozen=True, slots=True)
class Keyword:
    """One keyword to create: a hierarchy path (root first) and synonyms for its leaf."""

    path: tuple[str, ...]
    synonyms: tuple[str, ...] = ()

    @property
    def leaf(self) -> str:
        return self.path[-1]

    @property
    def hierarchical(self) -> str:
        """Lightroom's lr:hierarchicalSubject spelling: parent|child|leaf."""
        return "|".join(self.path)


@dataclass(frozen=True, slots=True)
class Suggestion:
    keywords: tuple[Keyword, ...]
    review: bool
    review_reasons: tuple[str, ...]


def _base_species(name: str) -> str:
    """Genus + last epithet, collapsing subgenus spellings and trinomials (the same merge key
    model.canonical_species uses, re-stated here so this module stays torch-free)."""
    parts = name.split()
    return f"{parts[0]} {parts[-1]}" if len(parts) >= 2 else name


def _genus(top: Prediction) -> str:
    """The genus level of the hierarchy: the table's genus, else the first word of a multi-word
    species name (which also collapses subgenus spellings, "Charis Sarota acanthoides" →
    "Charis"); empty for a one-word name, so the level is skipped rather than repeated."""
    if top.genus:
        return top.genus
    parts = top.species.split()
    return parts[0] if len(parts) >= 2 else ""


def suggest(
    predictions: Sequence[Prediction],
    in_candidates: bool | None,
    *,
    root: str = KEYWORD_ROOT,
    min_score: float = DEFAULT_MIN_SCORE,
    detected: bool | None = None,
    extra_reasons: Sequence[str] = (),
) -> Suggestion:
    """Keywords for one classified photo.

    The top-1 species becomes `root|class|genus|species` — the same tree the Lightroom
    plugin's collections use; an empty class is skipped and a missing genus is read off the
    binomial — with the common name as a keyword synonym. When the photo is judged to contain
    an animal — the detector's verdict when the crop stage ran (`detected` True/False),
    otherwise a top-1 score of at least `min_score` — the flat tag "animals" is added, plus
    "wildlife" unless the species is on the domesticated list. The photo is flagged for review
    — an extra `root|review` keyword — when there is no prediction, the top-1 score is below
    `min_score` (a softmax over the candidate set: a heuristic, not a probability), or the
    unconstrained top-1 is not in the geo candidate list (`in_candidates is False`).
    """
    reasons: list[str] = []
    keywords: list[Keyword] = []
    top = predictions[0] if predictions else None
    if top is None:
        reasons.append("no predictions")
    else:
        levels = [root, *(part for part in (top.taxon_class, _genus(top)) if part), top.species]
        synonyms = (top.common_name,) if top.common_name else ()
        keywords.append(Keyword(path=tuple(levels), synonyms=synonyms))
        if top.score < min_score:
            reasons.append(f"top-1 score {top.score:.3f} below {min_score:g}")
        animal_present = detected if detected is not None else top.score >= min_score
        if animal_present:
            keywords.append(Keyword(path=(ANIMALS_KEYWORD,)))
            if _base_species(top.species) not in DOMESTIC_SPECIES:
                keywords.append(Keyword(path=(WILDLIFE_KEYWORD,)))
    if in_candidates is False:
        reasons.append("unconstrained top-1 is not in the place list")
    reasons.extend(r for r in extra_reasons if r)
    if reasons:
        keywords.append(Keyword(path=(root, REVIEW_KEYWORD)))
    return Suggestion(keywords=tuple(keywords), review=bool(reasons), review_reasons=tuple(reasons))
