"""The release step of .github/workflows/release.yml, run for real against a stand-in for gh.

A pushed tag must publish a release on that very tag (owner, 2026-11-15); a run started by
hand must only ever make a draft. The step cannot be tried on GitHub without making a
release, so its shell script is cut out of the workflow and run here once per trigger.
Nothing touches the network: `gh` is a script that records what it is asked to do."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "release.yml"
ASSETS = ("SHA256SUMS.txt", "WildID-0.4.0-macos-arm64.zip", "WildID-Setup-0.4.0.exe")

GH_STANDIN = """#!/bin/bash
# `release view` answers as $STANDIN_EXISTING says; `release create` writes its arguments down
if [ "$1 $2" = "release view" ]; then
  case "${STANDIN_EXISTING:-none}" in
    draft) echo "draft"; exit 0 ;;
    published) echo "published release"; exit 0 ;;
    *) echo "release not found" >&2; exit 1 ;;
  esac
fi
if [ "$1 $2" = "release create" ]; then
  printf '%s\\n' "$@" > "$STANDIN_LOG"
  exit 0
fi
echo "unexpected gh call: $*" >&2
exit 64
"""

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("bash") is None, reason="needs a Unix bash"
)


def _release_step() -> str:
    """The shell script of the step that calls `gh release create`, as the runner gets it."""
    lines = WORKFLOW.read_bytes().decode("utf-8").splitlines()
    starts = [
        i for i, line in enumerate(lines) if line.startswith("      - name: gh release create")
    ]
    assert len(starts) == 1, "exactly one step makes the release"
    run = next(i for i in range(starts[0], len(lines)) if lines[i] == "        run: |")
    body = []
    for line in lines[run + 1 :]:
        if line.strip() and not line.startswith(" " * 10):
            break
        body.append(line[10:])
    return "\n".join(body) + "\n"


def _run(
    tmp_path: Path, *, event: str, ref_type: str, ref_name: str, version: str, existing="none"
):
    """Run the step as GitHub would for that trigger; return (exit code, output, gh's arguments)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(GH_STANDIN, encoding="utf-8", newline="\n")
    gh.chmod(0o755)
    (tmp_path / "release").mkdir()
    for name in ASSETS:
        (tmp_path / "release" / name).write_bytes(b"x")
    script = tmp_path / "step.sh"
    script.write_text(_release_step(), encoding="utf-8", newline="\n")
    log = tmp_path / "gh-arguments.txt"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "GH_TOKEN": "not-a-token",
        "GITHUB_EVENT_NAME": event,
        "GITHUB_REF_TYPE": ref_type,
        "GITHUB_REF_NAME": ref_name,
        "GITHUB_SHA": "0123456789abcdef0123456789abcdef01234567",
        "VERSION": version,
        "STANDIN_EXISTING": existing,
        "STANDIN_LOG": str(log),
    }
    done = subprocess.run(
        ["bash", str(script)], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    args = log.read_text(encoding="utf-8").splitlines() if log.exists() else None
    return done.returncode, done.stdout + done.stderr, args


def test_the_workflow_calls_gh_release_in_that_one_step_only():
    text = WORKFLOW.read_bytes().decode("utf-8")
    code = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    assert sum("gh release create" in line for line in code) == 2, "the step's name and its call"
    step = _release_step()
    assert step.count("gh release create") == 1 and step.count("--draft") == 1


def test_a_pushed_tag_publishes_a_release_on_that_tag(tmp_path):
    code, output, args = _run(
        tmp_path, event="push", ref_type="tag", ref_name="v0.4.0", version="0.4.0"
    )
    assert code == 0, output
    assert args[:3] == ["release", "create", "v0.4.0"]
    assert args[3:6] == [f"release/{name}" for name in ASSETS], "both downloads and the checksums"
    assert "--draft" not in args, "a pushed tag makes a proper release, not a draft"
    assert "--prerelease" not in args
    assert "--verify-tag" in args, "the release goes on the pushed tag, never on a new one"
    assert "--target" not in args
    assert "--generate-notes" in args
    assert args[args.index("--title") + 1] == "WildID 0.4.0"


@pytest.mark.parametrize(
    ("tag", "version"),
    [
        ("v1.2.3-rc1", "1.2.3rc1"),
        ("v0.5.0a2", "0.5.0a2"),
        ("v0.5.0b1", "0.5.0b1"),
        ("v0.5.0.dev3", "0.5.0.dev3"),
    ],
)
def test_a_pre_release_version_is_published_as_a_pre_release(tmp_path, tag, version):
    code, output, args = _run(tmp_path, event="push", ref_type="tag", ref_name=tag, version=version)
    assert code == 0, output
    assert args[2] == tag, "the pushed tag itself, not the normalised version"
    assert "--prerelease" in args and "--draft" not in args and "--verify-tag" in args
    assert args[args.index("--title") + 1] == f"WildID {version}"


def test_a_post_release_is_an_ordinary_release(tmp_path):
    code, output, args = _run(
        tmp_path, event="push", ref_type="tag", ref_name="v0.4.0.post1", version="0.4.0.post1"
    )
    assert code == 0, output
    assert "--prerelease" not in args and "--draft" not in args


@pytest.mark.parametrize(("existing", "word"), [("draft", "draft"), ("published", "published")])
def test_a_pushed_tag_never_adds_a_second_release_for_its_tag(tmp_path, existing, word):
    code, output, args = _run(
        tmp_path,
        event="push",
        ref_type="tag",
        ref_name="v0.4.0",
        version="0.4.0",
        existing=existing,
    )
    assert code != 0 and args is None, "the step stops before gh release create"
    assert word in output and "v0.4.0" in output, output


def test_a_manual_run_makes_a_draft(tmp_path):
    code, output, args = _run(
        tmp_path, event="workflow_dispatch", ref_type="branch", ref_name="main", version="0.3.1"
    )
    assert code == 0, output
    assert args[:3] == ["release", "create", "v0.3.1"]
    assert "--draft" in args, "only a pushed tag publishes"
    assert args[args.index("--target") + 1] == "0123456789abcdef0123456789abcdef01234567"
    assert "--verify-tag" not in args and "--prerelease" not in args


def test_a_manual_run_from_a_tag_makes_a_draft_too(tmp_path):
    code, output, args = _run(
        tmp_path, event="workflow_dispatch", ref_type="tag", ref_name="v0.4.0", version="0.4.0"
    )
    assert code == 0, output
    assert args[:3] == ["release", "create", "v0.4.0"]
    assert "--draft" in args, "started by hand, so a draft, whatever it was started from"
