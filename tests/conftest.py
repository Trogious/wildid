from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def bear_jpg() -> Path:
    return FIXTURES / "bear.jpg"


@pytest.fixture
def arw_fixture() -> Path:
    """A Sony ARW is not committed (git-ignored); tests that need one skip when absent."""
    files = sorted(p for p in FIXTURES.iterdir() if p.suffix.lower() == ".arw")
    if not files:
        pytest.skip("no .ARW fixture in tests/fixtures/")
    return files[0]


@pytest.fixture
def isolated_cache(tmp_path, monkeypatch) -> Path:
    """Point wildid's own cache at a temp dir so tests never touch the user's cache."""
    cache = tmp_path / "wildid-cache"
    monkeypatch.setenv("WILDID_CACHE_DIR", str(cache))
    return cache
