"""installer/set_version.py: the one place a release version is written. CI runs it on a tag
push so the tag decides the version; it must touch all four carriers or none."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FILES = (
    "pyproject.toml",
    "src/wildid/__init__.py",
    "lrplugin/wildid.lrplugin/Info.lua",
    "uv.lock",
)

spec = importlib.util.spec_from_file_location("set_version", REPO / "installer" / "set_version.py")
set_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(set_version)


@pytest.fixture
def tree(tmp_path):
    for rel in FILES:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO / rel, dst)
    return tmp_path


def read(tree, rel):
    with (tree / rel).open("r", encoding="utf-8", newline="") as fh:
        return fh.read()


def test_rewrites_every_carrier(tree, capsys):
    assert set_version.main(["v1.2.3-rc1", "--root", str(tree)]) == 0
    assert 'version = "1.2.3rc1"' in read(tree, "pyproject.toml")  # normalised spelling
    assert '__version__ = "1.2.3rc1"' in read(tree, "src/wildid/__init__.py")
    assert "VERSION = { major = 1, minor = 2, revision = 3, build = 0 }" in read(
        tree, "lrplugin/wildid.lrplugin/Info.lua"
    )
    # the checkout may be CRLF (git autocrlf on Windows); the script keeps what it finds
    lock = read(tree, "uv.lock").replace("\r\n", "\n")
    assert '[[package]]\nname = "wildid"\nversion = "1.2.3rc1"\n' in lock
    assert lock.count('"1.2.3rc1"') == 1  # the root entry only, never a dependency
    out = capsys.readouterr().out
    assert out.count("-> 1.2.3rc1") == 4 and "(unchanged)" not in out


def test_idempotent_and_keeps_crlf(tree, capsys):
    info = tree / "lrplugin/wildid.lrplugin/Info.lua"
    crlf = read(tree, "lrplugin/wildid.lrplugin/Info.lua").replace("\n", "\r\n")
    with info.open("w", encoding="utf-8", newline="") as fh:
        fh.write(crlf)
    assert set_version.main(["2.0.0", "--root", str(tree)]) == 0
    assert set_version.main(["2.0.0", "--root", str(tree)]) == 0
    assert capsys.readouterr().out.count("(unchanged)") == 4
    text = read(tree, "lrplugin/wildid.lrplugin/Info.lua")
    assert text.count("\r\n") == text.count("\n") == crlf.count("\n")  # CRLF kept, none doubled
    assert "major = 2, minor = 0, revision = 0" in text


def test_accepted_and_rejected_spellings(tree):
    for raw, canon in (
        ("0.3.1", "0.3.1"),
        ("v0.3.1", "0.3.1"),
        ("1.0.0.post2", "1.0.0.post2"),
        ("1.0.0b3", "1.0.0b3"),
        ("1.0.0.dev1", "1.0.0.dev1"),
    ):
        assert set_version.normalise(raw)[0] == canon
    before = {rel: read(tree, rel) for rel in FILES}
    for bad in ("1.2", "1.2.3.4", "0.3.1-final", "latest", ""):
        assert set_version.main([bad, "--root", str(tree)]) == 2, bad
    assert {rel: read(tree, rel) for rel in FILES} == before


def test_all_or_nothing(tree):
    """A carrier that no longer matches stops the run before anything is written."""
    info = tree / "lrplugin/wildid.lrplugin/Info.lua"
    info.write_text(info.read_text(encoding="utf-8").replace("VERSION = {", "VERSION = ("), "utf-8")
    assert set_version.main(["3.0.0", "--root", str(tree)]) == 1
    assert 'version = "3.0.0"' not in read(tree, "pyproject.toml")
    assert set_version.main(["3.0.0", "--root", str(tree / "nowhere")]) == 1
