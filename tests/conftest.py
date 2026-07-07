"""Shared test fixtures.

Curated Parquet data is a gitignored, generated artifact - this ensures it
exists (built from the committed synthetic CSV fixtures) before any test
that reads from `data/curated` runs, without needing a manual setup step.
"""

from pathlib import Path

import pytest

from powerhouse.data import ingest_fixtures

RAW_DIR = Path("data/raw/ohlcv")
CURATED_DIR = Path("data/curated")


@pytest.fixture(scope="session", autouse=True)
def curated_fixture_data() -> Path:
    """Ingest committed CSV fixtures into data/curated once per test run."""
    ingest_fixtures(RAW_DIR, CURATED_DIR)
    return CURATED_DIR
