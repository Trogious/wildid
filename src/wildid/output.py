"""Text-block writer for stdout. Pure formatting; the CLI decides where it goes.

MVP output is text only (plan D13). Table/CSV/JSON writers are post-MVP.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from wildid import __version__

SCORE_NOTE = (
    "scores are a softmax over the candidate set and are not comparable between runs "
    "with different candidates"
)


@dataclass(frozen=True, slots=True)
class Prediction:
    species: str
    common_name: str
    score: float
    genus: str = ""
    family: str = ""
    taxon_class: str = ""


@dataclass(frozen=True, slots=True)
class CandidateInfo:
    """What the classifier was allowed to choose from."""

    count: int
    place_label: str | None = None  # e.g. "Brazil › Mato Grosso"; None means the full TreeOfLife
    taxa: Sequence[str] = ()
    fetched: str | None = None  # ISO date of the geo list
    rank: str = "species"  # "genus" when --geo-rank genus widened the list
    auto_level: str | None = None  # --geo-auto: per-photo places at this admin level
    auto_places: int = 0

    @property
    def description(self) -> str:
        if self.auto_level is not None:
            return (
                f"per-photo GPS ({self.auto_level} level; {self.auto_places} place(s); "
                "see each block's place line)"
            )
        if self.place_label is None:
            return f"full TreeOfLife ({self.count:,} taxa)"
        parts = [self.place_label + (", genus level" if self.rank == "genus" else "")]
        if self.taxa:
            parts.append(",".join(self.taxa))
        if self.fetched:
            parts.append(f"fetched {self.fetched}")
        return f"{self.count:,} species ({'; '.join(parts)})"


def header(
    model: str, device: str, candidates: CandidateInfo, *, precision: str | None = None
) -> str:
    """The first stdout lines: what was run, and the score caveat."""
    runtime = f"device={device}" + (f" precision={precision}" if precision else "")
    line = f"wildid {__version__} | model={model} {runtime} | candidates={candidates.description}"
    return f"{line}\nnote: {SCORE_NOTE}"


def block(
    label: str,
    predictions: Sequence[Prediction],
    *,
    unconstrained: Prediction | None = None,
    in_candidates: bool | None = None,
    place_label: str | None = None,
    crop_line: str | None = None,
    opinion_line: str | None = None,
    place_line: str | None = None,
) -> str:
    """One result block: file label, ranked rows, then the optional crop, anomaly and
    second-opinion lines."""
    lines = [label]
    if not predictions:
        lines.append("  (no predictions)")
    species_w = max([len(p.species) for p in predictions] + [20])
    common_w = max([len(p.common_name or "-") for p in predictions] + [16])
    for i, p in enumerate(predictions, start=1):
        lines.append(
            f"  {i}. {p.species.ljust(species_w)}  {(p.common_name or '-').ljust(common_w)}"
            f"  {p.score:.3f}"
        )
    if place_line:
        lines.append(place_line)
    if crop_line:
        lines.append(crop_line)
    if unconstrained is not None:
        line = f"  unconstrained top-1: {unconstrained.species} ({unconstrained.score:.3f})"
        if in_candidates is False:
            where = f" {place_label}" if place_label else ""
            line += f"  \u26a0 not in{where} list"
        lines.append(line)
    if opinion_line:
        lines.append(opinion_line)
    return "\n".join(lines)


def place_line(label: str | None, candidates: int | None, note: str | None) -> str | None:
    """The `place:` line of an auto-geo block (None when the run had no auto-geo)."""
    if label is not None:
        count = f" ({candidates:,} species)" if candidates is not None else ""
        return f"  place: {label}{count}"
    if note is not None:
        return f"  place: {note} \u2192 full TreeOfLife"
    return None


def failures(failed: Sequence[tuple[str, str]]) -> str:
    """Summary of files that could not be loaded, as (label, reason) pairs."""
    if not failed:
        return ""
    lines = [f"{len(failed)} file(s) could not be loaded:"]
    lines.extend(f"  {label}: {reason}" for label, reason in failed)
    return "\n".join(lines)
