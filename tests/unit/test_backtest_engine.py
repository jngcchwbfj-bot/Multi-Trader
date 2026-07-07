"""Tests for the real backtest replay/simulation engine."""

from pathlib import Path

import pytest

from powerhouse.backtest import BacktestEngine, compute_metrics
from powerhouse.core.enums import Phase

RAW_DIR = Path("data/raw/ohlcv")


@pytest.mark.unit
class TestBacktestEngine:
    @pytest.fixture
    def curated_dir(self, tmp_path):
        from powerhouse.data import ingest_fixtures

        ingest_fixtures(RAW_DIR, tmp_path)
        return tmp_path

    def test_run_produces_trades_and_metrics(self, curated_dir):
        engine = BacktestEngine(curated_dir=curated_dir)
        result = engine.run(
            symbols=["AAPL", "MSFT", "NVDA"],
            start_date="2026-04-01",
            end_date="2026-05-26",
            phase=Phase.OPEN,
        )
        assert result.metrics.total_trades > 0
        assert len(result.executed_trades) > 0
        assert len(result.trade_plans) >= len(result.executed_trades)
        assert result.start_date == "2026-04-01"

    def test_run_is_deterministic(self, curated_dir):
        engine = BacktestEngine(curated_dir=curated_dir)
        r1 = engine.run(symbols=["AAPL"], start_date="2026-04-01", end_date="2026-05-01")
        r2 = engine.run(symbols=["AAPL"], start_date="2026-04-01", end_date="2026-05-01")
        assert r1.metrics.total_pnl == r2.metrics.total_pnl
        assert r1.metrics.total_trades == r2.metrics.total_trades

    def test_no_data_raises(self, tmp_path):
        from powerhouse.core.exceptions import ConfigError

        engine = BacktestEngine(curated_dir=tmp_path)
        with pytest.raises(ConfigError):
            engine.run(symbols=["AAPL"])

    def test_closed_phase_produces_no_new_trades(self, curated_dir):
        engine = BacktestEngine(curated_dir=curated_dir)
        result = engine.run(symbols=["AAPL"], phase=Phase.CLOSED)
        assert len(result.trade_plans) == 0
        assert len(result.executed_trades) == 0

    def test_equity_curve_tracks_starting_value(self, curated_dir):
        engine = BacktestEngine(curated_dir=curated_dir)
        result = engine.run(symbols=["AAPL"], start_date="2026-04-01", end_date="2026-05-26")
        assert result.equity_curve[0]["equity"] > 0
        assert result.metrics.starting_account_value == 100_000


@pytest.mark.unit
class TestComputeMetrics:
    def test_empty_trades_returns_zeroed_metrics(self):
        from decimal import Decimal

        metrics = compute_metrics([], Decimal("100000"))
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.ending_account_value == Decimal("100000")
