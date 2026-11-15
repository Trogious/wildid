"""XMP sidecar writer: pre-import keywording for Lightroom (lightroom-plugin-plan.md Phase C).

Scope and safety (decisions L7/L8):
- Sidecars are written for proprietary RAW files only. JPEG, TIFF and DNG carry XMP *inside*
  the file — Lightroom ignores a sidecar next to them — and wildid does not modify photo files.
- This is a pre-import tool. A sidecar of an already-imported photo also holds develop
  settings, so the default mode skips existing sidecars; `merge` appends keyword entries and
  touches nothing else. Writes are atomic (temp file + rename).

Lightroom reads `dc:subject` (flat keywords) and `lr:hierarchicalSubject` (keyword tree) at
import. A `wildid:` namespace block records provenance; Lightroom preserves it and ignores it.
"""

from __future__ import annotations

import io
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape

from wildid import __version__
from wildid.constants import DEFAULT_MIN_SCORE, KEYWORD_ROOT, RAW_EXTENSIONS
from wildid.keywords import suggest
from wildid.pipeline import FileResult

log = logging.getLogger(__name__)

# DNG embeds XMP like JPEG/TIFF does; Lightroom reads sidecars only for the other RAW formats.
SIDECAR_EXTENSIONS: frozenset[str] = frozenset(RAW_EXTENSIONS - {"dng"})
EMBEDDED_XMP_EXTENSIONS: frozenset[str] = frozenset({"jpg", "jpeg", "dng"})

NS_X = "adobe:ns:meta/"
NS_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
NS_DC = "http://purl.org/dc/elements/1.1/"
NS_LR = "http://ns.adobe.com/lightroom/1.0/"
NS_WILDID = "http://ns.wildid.dev/xmp/1.0/"

RDF = f"{{{NS_RDF}}}"
DC = f"{{{NS_DC}}}"
LR = f"{{{NS_LR}}}"
WILDID = f"{{{NS_WILDID}}}"

XPACKET_BEGIN = '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
XPACKET_END = '\n<?xpacket end="w"?>\n'

XMP_MODES = ("new-only", "merge")


class SidecarError(RuntimeError):
    """One sidecar could not be written (bad existing XMP, I/O failure)."""


@dataclass(frozen=True, slots=True)
class SidecarContent:
    subjects: tuple[str, ...]  # flat dc:subject entries (keyword leaves + synonyms)
    hierarchical: tuple[str, ...]  # lr:hierarchicalSubject entries (parent|child|leaf)
    provenance: dict[str, str]  # wildid:* simple properties


def sidecar_path(image_path: Path) -> Path:
    """Lightroom's sidecar convention: DSC04512.ARW → DSC04512.xmp."""
    return image_path.with_suffix(".xmp")


def sidecar_supported(image_path: Path) -> bool:
    return image_path.suffix.lower().lstrip(".") in SIDECAR_EXTENSIONS


def content_for(
    fr: FileResult,
    *,
    model: str,
    place_label: str | None,
    keyword_root: str = KEYWORD_ROOT,
    min_score: float = DEFAULT_MIN_SCORE,
    run_at: str | None = None,
) -> SidecarContent:
    """Sidecar entries for one classified photo, from the shared keyword policy."""
    suggestion = suggest(
        fr.predictions,
        fr.in_candidates,
        root=keyword_root,
        min_score=min_score,
        detected=fr.crop.detected if fr.crop is not None else None,
        extra_reasons=fr.review_notes,
    )
    subjects: list[str] = []
    hierarchical: list[str] = []
    for kw in suggestion.keywords:
        hierarchical.append(kw.hierarchical)
        for name in (kw.leaf, *kw.synonyms):
            if name not in subjects:
                subjects.append(name)
    top = fr.predictions[0] if fr.predictions else None
    provenance: dict[str, str] = {
        "Model": model,
        "ProcessedAt": run_at or datetime.now(UTC).isoformat(timespec="seconds"),
        "Review": "True" if suggestion.review else "False",
    }
    if top is not None:
        provenance["Species"] = top.species
        if top.common_name:
            provenance["CommonName"] = top.common_name
        provenance["Score"] = f"{top.score:.3f}"
    if place_label:
        provenance["Place"] = place_label
    return SidecarContent(
        subjects=tuple(subjects), hierarchical=tuple(hierarchical), provenance=provenance
    )


# ----------------------------------------------------------------------------------------------
# rendering
# ----------------------------------------------------------------------------------------------


def _bag(items: tuple[str, ...], indent: str) -> str:
    lines = [f"{indent}<rdf:Bag>"]
    lines += [f"{indent} <rdf:li>{escape(item)}</rdf:li>" for item in items]
    lines.append(f"{indent}</rdf:Bag>")
    return "\n".join(lines)


def render_new(content: SidecarContent) -> str:
    """A fresh sidecar: readable, deterministic, Lightroom-compatible RDF/XML."""
    parts = [
        XPACKET_BEGIN,
        f'<x:xmpmeta xmlns:x="{NS_X}" x:xmptk="wildid {__version__}">\n',
        f' <rdf:RDF xmlns:rdf="{NS_RDF}">\n',
        '  <rdf:Description rdf:about=""\n',
        f'    xmlns:dc="{NS_DC}"\n',
        f'    xmlns:lr="{NS_LR}"\n',
        f'    xmlns:wildid="{NS_WILDID}">\n',
        "   <dc:subject>\n",
        _bag(content.subjects, "    "),
        "\n   </dc:subject>\n",
        "   <lr:hierarchicalSubject>\n",
        _bag(content.hierarchical, "    "),
        "\n   </lr:hierarchicalSubject>\n",
    ]
    for key, value in content.provenance.items():
        parts.append(f"   <wildid:{key}>{escape(value)}</wildid:{key}>\n")
    parts += [
        "  </rdf:Description>\n",
        " </rdf:RDF>\n",
        "</x:xmpmeta>",
        XPACKET_END,
    ]
    return "".join(parts)


def _register_existing_prefixes(text: str) -> None:
    """Keep the document's own namespace prefixes (crs, dc, …) through an ElementTree
    round-trip. ElementTree would otherwise rename them to ns0/ns1 — still valid XML, but
    needlessly diff-noisy next to develop settings."""
    try:
        for _event, (prefix, uri) in ET.iterparse(io.StringIO(text), events=["start-ns"]):
            if not prefix or prefix.startswith("xml"):
                continue
            try:
                ET.register_namespace(prefix, uri)
            except ValueError:
                continue  # ns0-style prefixes are reserved by ElementTree; let it re-assign
    except ET.ParseError:
        pass  # the caller's fromstring will raise with a better message


def _ensure_bag(descriptions: list[ET.Element], tag: str) -> ET.Element:
    """The rdf:Bag under `tag` in any Description, created in the first one when missing."""
    for desc in descriptions:
        el = desc.find(tag)
        if el is not None:
            seq = el.find(f"{RDF}Bag")
            if seq is None:
                seq = el.find(f"{RDF}Seq")
            if seq is None:
                seq = ET.SubElement(el, f"{RDF}Bag")
            return seq
    el = ET.SubElement(descriptions[0], tag)
    return ET.SubElement(el, f"{RDF}Bag")


def _append_missing(bag: ET.Element, values: tuple[str, ...]) -> int:
    existing = {li.text.strip() for li in bag.findall(f"{RDF}li") if li.text}
    added = 0
    for value in values:
        if value not in existing:
            li = ET.SubElement(bag, f"{RDF}li")
            li.text = value
            added += 1
    return added


def merge_into(existing_text: str, content: SidecarContent) -> str:
    """Append keyword entries (and refresh wildid:* provenance) into an existing sidecar,
    leaving everything else — develop settings above all — untouched."""
    _register_existing_prefixes(existing_text)
    # Elements this merge may add get stable prefixes even when the input lacked them.
    for prefix, uri in (("rdf", NS_RDF), ("dc", NS_DC), ("lr", NS_LR), ("wildid", NS_WILDID)):
        ET.register_namespace(prefix, uri)
    try:
        root = ET.fromstring(existing_text)
    except ET.ParseError as exc:
        raise SidecarError(f"existing sidecar is not valid XML: {exc}") from exc
    rdf = root if root.tag == f"{RDF}RDF" else root.find(f"{RDF}RDF")
    if rdf is None:
        raise SidecarError("existing sidecar has no rdf:RDF element")
    descriptions = rdf.findall(f"{RDF}Description")
    if not descriptions:
        descriptions = [ET.SubElement(rdf, f"{RDF}Description", {f"{RDF}about": ""})]
    _append_missing(_ensure_bag(descriptions, f"{DC}subject"), content.subjects)
    _append_missing(_ensure_bag(descriptions, f"{LR}hierarchicalSubject"), content.hierarchical)
    host = descriptions[0]
    for key, value in content.provenance.items():
        tag = f"{WILDID}{key}"
        # Lightroom rewrites simple properties as attributes of rdf:Description (its own
        # serialisation); a sidecar it has saved carries wildid:* that way. Update whichever
        # form exists so the property is never present twice.
        owner = next((d for d in descriptions if d.get(tag) is not None), None)
        if owner is not None:
            owner.set(tag, value)
            for desc in descriptions:
                for stale in desc.findall(tag):
                    desc.remove(stale)
            continue
        el = None
        for desc in descriptions:
            el = desc.find(tag)
            if el is not None:
                break
        if el is None:
            el = ET.SubElement(host, tag)
        el.text = value
    body = ET.tostring(root, encoding="unicode")
    return XPACKET_BEGIN + body + XPACKET_END


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ----------------------------------------------------------------------------------------------
# per-run writer (driven by the CLI)
# ----------------------------------------------------------------------------------------------


@dataclass
class SidecarWriter:
    """Processes FileResults as a run streams by and keeps the tally for the summary line."""

    mode: str = "new-only"
    dry_run: bool = False
    keyword_root: str = KEYWORD_ROOT
    min_score: float = DEFAULT_MIN_SCORE
    model: str = ""
    place_label: str | None = None
    run_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    written: int = 0
    merged: int = 0
    skipped: int = 0
    unsupported: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.mode not in XMP_MODES:
            raise ValueError(f"unknown xmp mode {self.mode!r}; choose from {', '.join(XMP_MODES)}")

    def process(self, fr: FileResult) -> str:
        """Write/merge the sidecar for one successful result. Returns the status."""
        if not fr.ok:
            return "not-classified"
        if not sidecar_supported(fr.path):
            self.unsupported += 1
            return "unsupported"
        target = sidecar_path(fr.path)
        content = content_for(
            fr,
            model=self.model,
            place_label=fr.place_label or self.place_label,
            keyword_root=self.keyword_root,
            min_score=self.min_score,
            run_at=self.run_at,
        )
        try:
            if target.exists():
                if self.mode != "merge":
                    self.skipped += 1
                    log.debug("%s exists; skipped (new-only mode)", target.name)
                    return "skipped"
                text = merge_into(target.read_text(encoding="utf-8"), content)
                if not self.dry_run:
                    _write_atomic(target, text)
                self.merged += 1
                return "merged"
            if not self.dry_run:
                _write_atomic(target, render_new(content))
            self.written += 1
            return "written"
        except (OSError, SidecarError) as exc:
            self.failed.append((fr.label or fr.path.name, str(exc)))
            log.warning("sidecar for %s failed: %s", fr.path.name, exc)
            return "failed"

    def summary(self) -> str:
        head = "xmp dry run (nothing written):" if self.dry_run else "xmp sidecars:"
        parts = [f"{self.written} written", f"{self.merged} merged"]
        if self.skipped:
            parts.append(f"{self.skipped} skipped (sidecar exists; --xmp-mode merge to update)")
        if self.unsupported:
            parts.append(f"{self.unsupported} unsupported (JPEG/DNG embed XMP; not modified)")
        if self.failed:
            parts.append(f"{len(self.failed)} failed")
        lines = [f"{head} {', '.join(parts)}"]
        lines.extend(f"  {label}: {reason}" for label, reason in self.failed)
        return "\n".join(lines)
