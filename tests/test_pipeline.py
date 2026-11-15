"""Pipeline helpers that need no model."""

from __future__ import annotations

import re
import sys

import pytest

from wildid import pipeline


def test_rss_reports_memory_where_the_platform_can():
    text = pipeline.rss()
    if sys.platform == "linux":
        assert re.fullmatch(r"\d+ MB", text)
    elif sys.platform == "darwin":
        match = re.fullmatch(r"(\d+) MB \(footprint (\d+) MB\)", text)
        assert match, text
        assert int(match.group(1)) > 0 and int(match.group(2)) > 0
    else:
        assert text == "?"


@pytest.mark.skipif(sys.platform == "linux", reason="/proc answers first on Linux")
def test_rss_is_a_question_mark_when_no_source_answers(monkeypatch):
    monkeypatch.setattr(pipeline, "_darwin_memory", lambda: None)
    assert pipeline.rss() == "?"
