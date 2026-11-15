"""The macOS installer (installer/macos/) against the facts it relies on elsewhere in the
repository. File reads only: nothing is installed and nothing touches the network."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from wildid.constants import HF_MODEL_IDS, TOL_REPO, cache_dir

REPO = Path(__file__).resolve().parents[1]
MACOS = REPO / "installer" / "macos"
SCRIPTS = [
    MACOS / "build.sh",
    MACOS / "install.sh",
    MACOS / "uninstall.sh",
    MACOS / "launchers" / "wildid",
    MACOS / "launchers" / "wildid-setup",
    MACOS / "launchers" / "wildid-server-start",
]


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_are_bash_with_unix_line_endings(script):
    raw = script.read_bytes()
    assert raw.startswith(b"#!/bin/bash\n"), "macOS ships bash 3.2 at /bin/bash"
    assert b"\r" not in raw, "a CRLF script does not run on a Mac (.gitattributes pins LF)"


@pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="needs a Unix bash"
)
@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_scripts_parse(script):
    done = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_uv_version_is_pinned_the_same_everywhere():
    """One uv for the Windows installer, the macOS download and CI ("keep in step")."""
    mac = re.search(r'^UV_VERSION="([^"]+)"', _text(MACOS / "build.sh"), re.M).group(1)
    win = re.search(
        r'\$UvVersion\s*=\s*"([^"]+)"', _text(REPO / "installer" / "windows" / "build.ps1")
    ).group(1)
    workflow = _text(REPO / ".github" / "workflows" / "release.yml")
    ci = set(re.findall(r"inputs\.uv_version \|\| '([^']+)'", workflow))
    ci |= set(re.findall(r'default: "(\d+\.\d+\.\d+)"', workflow))
    assert {mac, win} | ci == {mac}, f"uv pins differ: macOS {mac}, Windows {win}, CI {ci}"


def _job(workflow: str, name: str) -> list[str]:
    """The lines of one job of the release workflow, below the line that names it."""
    lines = workflow.splitlines()
    body = []
    for line in lines[lines.index(f"  {name}:") + 1 :]:
        if re.match(r"  \S", line):
            break
        body.append(line)
    return body


def test_ci_runs_the_macos_jobs_on_a_tag_and_on_a_manual_run():
    """Owner decision 2026-11-15 (ADR 0008 decision 7): no trigger leaves the macOS jobs out."""
    workflow = _text(REPO / ".github" / "workflows" / "release.yml")
    triggers = workflow.split("\njobs:")[0]
    assert re.search(r"^  push:\s*\n\s+tags: \['v\*'\]", triggers, re.M), "the tag trigger"
    assert re.search(r"^  workflow_dispatch:", triggers, re.M), "the manual trigger"
    # the macOS job and the two it waits for: a job-level `if:` on any of them would skip it
    for job in ("lua-tests", "build-macos", "python-tests-macos"):
        conditions = [line.strip() for line in _job(workflow, job) if re.match(r"    if:", line)]
        assert not conditions, f"{job} must run on every trigger, found {conditions}"


def test_ci_installs_as_on_a_mac_without_homebrew_or_python():
    """The smoke must not lend the installer the runner's Homebrew, its Python or a uv cache."""
    workflow = _text(REPO / ".github" / "workflows" / "release.yml")
    smoke = "\n".join(_job(workflow, "python-tests-macos"))
    assert "env -i " in smoke and "PATH=/usr/bin:/bin:/usr/sbin:/sbin" in smoke
    for command in (
        'bare bash "$folder/install.sh"',
        'bare "$app/bin/wildid" --version',
        'bare bash "$app/uninstall.sh"',
    ):
        assert command in smoke, command
    assert '"$HOME/.local/share/uv/python/"*' in smoke, "the check that the Python is uv's own"


def test_python_always_comes_from_uv_on_every_system():
    """Owner, 2026-11-15: Python comes from uv, never from the machine. One setting in
    pyproject.toml says so; it reaches an installed copy because both installers ship that
    file and every uv call they make names the project it belongs to."""
    project = tomllib.loads(_text(REPO / "pyproject.toml"))
    assert project["tool"]["uv"]["python-preference"] == "only-managed"

    windows = REPO / "installer" / "windows"
    staged_mac = r'^cp "\$REPO/pyproject\.toml" .*"\$STAGE/app/"'
    staged_win = r'^foreach \(\$f in @\("pyproject\.toml",'
    assert re.search(staged_mac, _text(MACOS / "build.sh"), re.M)
    assert re.search(staged_win, _text(windows / "build.ps1"), re.M)

    shipped = [s for s in SCRIPTS if s.name != "build.sh"]
    shipped += sorted((windows / "launchers").glob("*.cmd")) + [windows / "wildid.iss"]
    calls = {}
    for script in shipped:
        for line in _text(script).splitlines():
            if re.search(r'"\$\w+/uv" (sync|run)\b', line) or re.search(
                r'uv\.exe".*\b(sync|run) --frozen', line
            ):
                calls.setdefault(script.name, []).append(line.strip())
    assert set(calls) == {
        "install.sh",
        "wildid",
        "wildid-server-start",
        "wildid.cmd",
        "wildid-setup.cmd",
        "wildid-server-start.cmd",
        "wildid.iss",
    }
    for name, lines in calls.items():
        for line in lines:
            assert "--project" in line, f"{name}: a uv call outside the project: {line}"


def test_shipped_scripts_call_nothing_a_bare_mac_lacks():
    """No Homebrew, no Python, no developer tools on a photographer's Mac: `python3`, `git` or
    `make` are stubs there that open Apple's offer to install the developer tools."""
    absent = {"python", "python3", "pip", "pip3", "brew", "git", "make", "cc", "gcc", "clang"}
    absent |= {"xcrun", "xcodebuild"}
    for script in SCRIPTS:
        if script.name == "build.sh":  # runs where the zip is built, not on the user's Mac
            continue
        for number, line in enumerate(_text(script).splitlines(), 1):
            code = re.sub(r"(^|\s)#.*", "", line)
            words = set(re.split(r"""[\s;|&()<>"'`$={}]+""", code))
            assert not words & absent, f"{script.name}:{number} calls {sorted(words & absent)}"


def test_macos_floor_matches_the_locked_torch_wheels():
    """install.sh refuses anything older than the macOS the locked torch wheel was built for."""
    floor = int(re.search(r"^MIN_MACOS=(\d+)", _text(MACOS / "install.sh"), re.M).group(1))
    lock = tomllib.loads(_text(REPO / "uv.lock"))
    tags = {
        int(m.group(1))
        for pkg in lock["package"]
        if pkg["name"] in ("torch", "torchvision")
        for wheel in pkg.get("wheels", [])
        if (m := re.search(r"macosx_(\d+)_\d+_arm64", wheel["url"]))
    }
    assert tags, "the lock has no macOS arm64 torch wheels"
    assert floor == max(tags)


def test_install_and_uninstall_agree_on_what_they_touch():
    install, uninstall = _text(MACOS / "install.sh"), _text(MACOS / "uninstall.sh")
    marker = re.search(r'^MARKER="([^"]+)"', install, re.M).group(1)
    assert f'marker="{marker}"' in uninstall, "uninstall.sh must remove the line install.sh adds"
    for folder in (
        "Library/Application Support/WildID",
        "Library/Application Support/Adobe/Lightroom/Modules",
        "Library/Caches/wildid",
    ):
        assert folder in install and folder in uninstall, folder
    # the three launchers engine.json and the README name are the ones the build stages
    build = _text(MACOS / "build.sh")
    for launcher in ("wildid", "wildid-setup", "wildid-server-start"):
        assert f"launchers/{launcher}" in build and f"bin/{launcher}" in install


def test_purge_names_exactly_the_engines_hugging_face_repos():
    uninstall = _text(MACOS / "uninstall.sh")
    expected = {f"models--{repo.replace('/', '--')}" for repo in HF_MODEL_IDS.values()}
    expected.add(f"datasets--{TOL_REPO.replace('/', '--')}")
    found = set(re.findall(r"\b((?:models|datasets)--[\w.-]+--[\w.-]+)", uninstall))
    assert found == expected


@pytest.mark.skipif(sys.platform != "darwin", reason="the macOS cache location")
def test_cache_dir_is_where_the_installer_and_the_plugin_expect_it(monkeypatch):
    monkeypatch.delenv("WILDID_CACHE_DIR", raising=False)
    assert cache_dir() == Path.home() / "Library" / "Caches" / "wildid"
    paths_lua = _text(REPO / "lrplugin" / "wildid.lrplugin" / "WildidPaths.lua")
    assert "'/Library/Caches/wildid'" in paths_lua
