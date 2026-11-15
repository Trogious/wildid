"""Opt-in end-to-end test with the real model: WILDID_LIVE_TESTS=1 uv run pytest -k live."""

from __future__ import annotations

import os

import pytest

from wildid.cli import main

pytestmark = pytest.mark.skipif(
    os.environ.get("WILDID_LIVE_TESTS") != "1", reason="set WILDID_LIVE_TESTS=1 to run"
)


@pytest.mark.parametrize("model", ["bioclip-2", "bioclip-2.5"])
def test_bear_is_ursus_arctos(model, bear_jpg, capsys):
    assert main([str(bear_jpg), "--model", model, "--offline"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert out[2] == "bear.jpg"
    assert out[3].startswith("  1. Ursus arctos")
    assert float(out[3].split()[-1]) > 0.5
