#!/usr/bin/env python3
"""Set the WildID version everywhere it is written down.

    python installer/set_version.py 0.3.1        # a leading "v" is accepted: v0.3.1

Rewrites, in one go and only if every edit can be made:
  - pyproject.toml                      (what uv and the installer build read)
  - src/wildid/__init__.py              (what the engine reports: --version, JSON, /health, XMP)
  - lrplugin/wildid.lrplugin/Info.lua   (what Lightroom's Plug-in Manager shows; numbers only)
  - uv.lock, root entry                 (so `uv sync --locked` still passes; this is exactly
                                         the line `uv lock` would write)

CI runs it on a tag push, so the tag alone decides the released version and the sources need
no bump beforehand; run it locally when the sources should carry the number. Standard library
only and Python 3.9 syntax: it runs on bare runners before any environment exists.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# X.Y.Z with an optional PEP 440 pre-release (a/b/rc N, any of "-", "." or nothing before it),
# post-release or dev suffix; normalised to the canonical spelling (1.2.3-rc1 -> 1.2.3rc1).
VERSION_RE = re.compile(
    r"^[vV]?(\d+)\.(\d+)\.(\d+)(?:[-._]?(a|b|rc)(\d+))?(\.post\d+)?(\.dev\d+)?$"
)


class SetVersionError(Exception):
    pass


def normalise(raw: str) -> tuple[str, int, int, int]:
    """The canonical version string and its three numbers, or SetVersionError."""
    m = VERSION_RE.match(raw.strip())
    if not m:
        raise SetVersionError(
            f"{raw!r} is not a release version: expected X.Y.Z with an optional aN/bN/rcN, "
            ".postN or .devN suffix (a leading v is fine)"
        )
    major, minor, patch = (int(m.group(i)) for i in (1, 2, 3))
    version = f"{major}.{minor}.{patch}"
    if m.group(4):
        version += f"{m.group(4)}{int(m.group(5))}"
    version += (m.group(6) or "") + (m.group(7) or "")
    return version, major, minor, patch


def _edits(version: str, major: int, minor: int, patch: int):
    """(relative path, pattern matching the one version line, its replacement)."""
    return (
        (
            "pyproject.toml",
            re.compile(r'^version\s*=\s*"[^"]*"', re.M),
            f'version = "{version}"',
        ),
        (
            "src/wildid/__init__.py",
            re.compile(r'^__version__ = "[^"]*"', re.M),
            f'__version__ = "{version}"',
        ),
        (
            "lrplugin/wildid.lrplugin/Info.lua",
            re.compile(r"VERSION = \{ major = \d+, minor = \d+, revision = \d+, build = \d+ \}"),
            f"VERSION = {{ major = {major}, minor = {minor}, revision = {patch}, build = 0 }}",
        ),
        (
            "uv.lock",
            re.compile(r'(\[\[package\]\]\r?\nname = "wildid"\r?\n)version = "[^"]*"'),
            rf'\g<1>version = "{version}"',
        ),
    )


def set_version(root: Path, raw: str) -> list[str]:
    """Rewrite every carrier under `root`. Returns one report line per file. Nothing is
    written unless every file matched exactly once (no half-bumped trees)."""
    version, major, minor, patch = normalise(raw)
    planned = []
    for rel, pattern, replacement in _edits(version, major, minor, patch):
        path = root / rel
        if not path.is_file():
            raise SetVersionError(f"{rel}: not found under {root}")
        with path.open("r", encoding="utf-8", newline="") as fh:  # keep CRLF as is
            text = fh.read()
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise SetVersionError(f"{rel}: expected one version line, found {len(matches)}")
        m = matches[0]
        new_text = text[: m.start()] + m.expand(replacement) + text[m.end() :]
        planned.append((path, rel, m.group(0).splitlines()[-1], new_text, new_text != text))
    report = []
    for path, rel, old_line, new_text, changed in planned:
        if changed:
            with path.open("w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)
        report.append(
            f"{rel}: {old_line.strip()} -> {version}" + ("" if changed else " (unchanged)")
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version", help="the version to write, e.g. 0.3.1 or v0.3.1")
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="repository root (default: this checkout)"
    )
    args = parser.parse_args(argv)
    try:
        for line in set_version(args.root.resolve(), args.version):
            print(line)
    except SetVersionError as exc:
        print(f"set_version: {exc}", file=sys.stderr)
        return 2 if "not a release version" in str(exc) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
