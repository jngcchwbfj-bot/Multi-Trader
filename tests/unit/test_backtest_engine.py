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
class TestDailyLossEnforcementInEngine:
    """Regression coverage for Phase 2.1: the daily-loss cap must actually be
    able to block plans inside a real `BacktestEngine` run, not just in an
    isolated `RiskAgent.run` call with a hand-built `Portfolio`.
    """

    @pytest.fixture
    def curated_dir(self, tmp_path):
        from powerhouse.data import ingest_fixtures

        ingest_fixtures(RAW_DIR, tmp_path)
        return tmp_path

    def test_tiny_daily_loss_cap_blocks_plans_in_a_real_run(self, curated_dir):
        from powerhouse.config import RiskConfig

        engine = BacktestEngine(
            curated_dir=curated_dir,
            risk_config=RiskConfig(max_daily_loss_pct=0.0001),
        )
        result = engine.run(
            symbols=["AAPL", "MSFT", "NVDA"],
            start_date="2026-04-01",
            end_date="2026-05-26",
            phase=Phase.OPEN,
        )

        loss_blocked = [
            d for d in result.risk_decisions if not d.daily_loss_check_passed
        ]
        assert loss_blocked, "expected at least one daily-loss rejection with a near-zero cap"
        assert all(not d.approved for d in loss_blocked)
        assert all("Daily loss cap exceeded" in d.reason for d in loss_blocked)

    def test_generous_daily_loss_cap_does_not_spuriously_block(self, curated_dir):
        from powerhouse.config import RiskConfig

        engine = BacktestEngine(
            curated_dir=curated_dir,
            risk_config=RiskConfig(max_daily_loss_pct=100.0),
        )
        result = engine.run(
            symbols=["AAPL", "MSFT", "NVDA"],
            start_date="2026-04-01",
            end_date="2026-05-26",
            phase=Phase.OPEN,
        )
        assert all(d.daily_loss_check_passed for d in result.risk_decisions)


@pytest.mark.unit
class TestComputeMetrics:
    def test_empty_trades_returns_zeroed_metrics(self):
        from decimal import Decimal

        metrics = compute_metrics([], Decimal("100000"))
        assert metrics.total_trades == 0
        assert metrics.win_rate == 0.0
        assert metrics.ending_account_value == Decimal("100000")
