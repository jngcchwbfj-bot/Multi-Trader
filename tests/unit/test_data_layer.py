"""Tests for the local Parquet/DuckDB data layer (fixtures only, no network)."""

from pathlib import Path

import pytest

from powerhouse.core.exceptions import ConfigError
from powerhouse.data import (
    available_symbols,
    ingest_csv_to_parquet,
    ingest_fixtures,
    load_ohlcv,
    load_universe,
    query_sql,
    read_csv_rows,
)

RAW_DIR = Path("data/raw/ohlcv")


@pytest.mark.unit
class TestIngestion:
    def test_read_csv_rows(self):
        rows = read_csv_rows(RAW_DIR / "AAPL.csv", symbol="AAPL")
        assert len(rows) > 0
        assert rows[0].symbol == "AAPL"
        assert rows == sorted(rows, key=lambda r: r.date)

    def test_ingest_csv_to_parquet(self, tmp_path):
        out = ingest_csv_to_parquet(RAW_DIR / "AAPL.csv", tmp_path)
        assert out.exists()
        df = load_ohlcv("AAPL", tmp_path)
        assert not df.empty
        assert set(df.columns) >= {"symbol", "date", "open", "high", "low", "close", "volume"}

    def test_ingest_fixtures_all_symbols(self, tmp_path):
        written = ingest_fixtures(RAW_DIR, tmp_path)
        assert len(written) == 3
        symbols = set(available_symbols(tmp_path))
        assert symbols == {"AAPL", "MSFT", "NVDA"}

    def test_ingest_missing_raw_dir_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            ingest_fixtures(tmp_path / "does-not-exist", tmp_path)

    def test_missing_required_column_raises(self, tmp_path):
        bad_csv = tmp_path / "BAD.csv"
        bad_csv.write_text("date,open,high,low,close\n2026-01-01,1,2,0.5,1.5\n")
        with pytest.raises(ConfigError):
            read_csv_rows(bad_csv, symbol="BAD")

    def test_invalid_high_low_raises(self, tmp_path):
        bad_csv = tmp_path / "BAD.csv"
        bad_csv.write_text(
            "date,open,high,low,close,volume\n2026-01-01,10,9,11,10,1000\n"
        )
        with pytest.raises(ValueError):
            read_csv_rows(bad_csv, symbol="BAD")


@pytest.mark.unit
class TestQuery:
    @pytest.fixture(autouse=True)
    def curated(self, tmp_path):
        ingest_fixtures(RAW_DIR, tmp_path)
        self.curated_dir = tmp_path

    def test_load_ohlcv_sorted(self):
        df = load_ohlcv("AAPL", self.curated_dir)
        assert list(df["date"]) == sorted(df["date"])

    def test_load_ohlcv_missing_symbol_raises(self):
        with pytest.raises(ConfigError):
            load_ohlcv("ZZZZ", self.curated_dir)

    def test_load_universe(self):
        df = load_universe(["AAPL", "MSFT", "ZZZZ"], self.curated_dir)
        assert set(df["symbol"].unique()) == {"AAPL", "MSFT"}

    def test_query_sql(self):
        df = query_sql("SELECT symbol, count(*) as n FROM ohlcv GROUP BY symbol", self.curated_dir)
        assert set(df["symbol"]) == {"AAPL", "MSFT", "NVDA"}
