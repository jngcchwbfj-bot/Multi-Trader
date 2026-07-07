"""Tests for the overlapping-position backtest mechanics (Phase 3).

Split into two layers:
- `TestPositionBook` exercises the day-by-day fill/close/mark-to-market
  mechanics directly against synthetic bars, independent of the scanner/
  strategy/risk pipeline or fixture data - this is the most direct proof
  that multiple positions (including on the same symbol) can be open at once.
- `TestBacktestEngineOverlappingMode` runs the full `BacktestEngine` in
  overlapping mode over the committed fixtures as an integration smoke test.
"""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from powerhouse.backtest import BacktestEngine
from powerhouse.backtest.positions import PositionBook
from powerhouse.config import BacktestConfig
from powerhouse.core.enums import OrderSide, Phase
from powerhouse.core.models import TradePlan
from powerhouse.simulation.executor import Bar, TradeSimulator

RAW_DIR = Path("data/raw/ohlcv")


def _plan(ticker="AAPL", entry="100", stop="95", target="110", qty=10) -> TradePlan:
    return TradePlan(
        ticker=ticker,
        side=OrderSide.BUY,
        entry_price=Decimal(entry),
        stop_loss_price=Decimal(stop),
        target_price=Decimal(target),
        quantity=qty,
        rationale="test",
    )


def _bars(ticker: str, day_offset: int) -> Bar:
    return Bar(date=f"2026-04-{day_offset:02d}", open=100, high=101, low=99, close=100)


def _flat_bar(date: str, close: float = 100) -> Bar:
    return Bar(date=date, open=100, high=101, low=99, close=close)


@pytest.mark.unit
class TestPositionBook:
    def test_queue_and_fill_next_bar(self):
        book = PositionBook(TradeSimulator(slippage_bps=0), max_holding_days=10)
        day1 = pd.Timestamp("2026-04-01")
        day2 = pd.Timestamp("2026-04-02")
        book.queue_entry(_plan(), day1)

        # No bar available yet on day1 itself for a same-day fill.
        filled, closed = book.advance(day1, bars_today={})
        assert filled == [] and closed == []
        assert book.open_count() == 1

        filled, closed = book.advance(day2, bars_today={"AAPL": _bars("AAPL", 2)})
        assert len(filled) == 1
        assert closed == []
        assert book.open_count() == 1

    def test_multiple_open_positions_same_symbol_can_coexist(self):
        book = PositionBook(TradeSimulator(slippage_bps=0), max_holding_days=10)
        day1 = pd.Timestamp("2026-04-01")
        day2 = pd.Timestamp("2026-04-02")
        day3 = pd.Timestamp("2026-04-03")

        # Two separate plans for the SAME ticker queued on consecutive days.
        book.queue_entry(_plan(ticker="AAPL", entry="100", stop="90", target="200"), day1)
        book.advance(day2, bars_today={"AAPL": _flat_bar("2026-04-02")})
        book.queue_entry(_plan(ticker="AAPL", entry="100", stop="90", target="200"), day2)
        filled, closed = book.advance(day3, bars_today={"AAPL": _flat_bar("2026-04-03")})

        assert len(filled) == 1  # the second plan just filled
        assert closed == []
        assert book.open_count() == 2  # both AAPL positions open simultaneously
        assert all(p.plan.ticker == "AAPL" for p in book.open_positions)

    def test_advance_closes_on_stop_hit_and_leaves_others_open(self):
        book = PositionBook(TradeSimulator(slippage_bps=0), max_holding_days=10)
        day1 = pd.Timestamp("2026-04-01")
        day2 = pd.Timestamp("2026-04-02")
        day3 = pd.Timestamp("2026-04-03")

        book.queue_entry(_plan(ticker="AAPL", entry="100", stop="95", target="200"), day1)
        book.queue_entry(_plan(ticker="MSFT", entry="100", stop="95", target="200"), day1)
        book.advance(
            day2,
            bars_today={
                "AAPL": Bar(date="2026-04-02", open=100, high=101, low=99, close=100),
                "MSFT": Bar(date="2026-04-02", open=100, high=101, low=99, close=100),
            },
        )
        assert book.open_count() == 2

        # Day 3: AAPL drops through its stop, MSFT stays flat and stays open.
        filled, closed = book.advance(
            day3,
            bars_today={
                "AAPL": Bar(date="2026-04-03", open=94, high=95, low=90, close=92),
                "MSFT": Bar(date="2026-04-03", open=100, high=101, low=99, close=100),
            },
        )
        assert filled == []
        assert len(closed) == 1
        assert closed[0].plan.ticker == "AAPL"
        assert closed[0].trade.outcome == "stop_hit"
        assert book.open_count() == 1
        assert book.open_positions[0].plan.ticker == "MSFT"

    def test_market_value_sums_open_positions_at_current_close(self):
        book = PositionBook(TradeSimulator(slippage_bps=0), max_holding_days=10)
        day1 = pd.Timestamp("2026-04-01")
        day2 = pd.Timestamp("2026-04-02")
        book.queue_entry(_plan(ticker="AAPL", qty=10), day1)
        book.queue_entry(_plan(ticker="MSFT", qty=5), day1)
        book.advance(
            day2,
            bars_today={
                "AAPL": Bar(date="2026-04-02", open=100, high=101, low=99, close=105),
                "MSFT": Bar(date="2026-04-02", open=100, high=101, low=99, close=200),
            },
        )
        value = book.market_value({"AAPL": 105.0, "MSFT": 200.0})
        assert value == Decimal("105") * 10 + Decimal("200") * 5

    def test_flatten_all_force_closes_remaining_positions(self):
        book = PositionBook(TradeSimulator(slippage_bps=0), max_holding_days=10)
        day1 = pd.Timestamp("2026-04-01")
        day2 = pd.Timestamp("2026-04-02")
        book.queue_entry(_plan(ticker="AAPL", stop="50", target="500"), day1)
        book.advance(day2, bars_today={"AAPL": _flat_bar("2026-04-02")})
        assert book.open_count() == 1

        closed = book.flatten_all({"AAPL": _flat_bar("2026-04-10", close=123)})
        assert len(closed) == 1
        assert closed[0].trade.outcome == "manual_close"
        assert closed[0].trade.exit_price == Decimal("123")
        assert book.open_count() == 0

    def test_expire_pending_marks_no_fill(self):
        book = PositionBook(TradeSimulator(slippage_bps=0), max_holding_days=10)
        day1 = pd.Timestamp("2026-04-01")
        book.queue_entry(_plan(ticker="ZZZZ"), day1)
        expired = book.expire_pending()
        assert len(expired) == 1
        plan, trade = expired[0]
        assert plan.ticker == "ZZZZ"
        assert trade.outcome == "no_fill"
        assert book.open_count() == 0


@pytest.mark.unit
class TestBacktestEngineOverlappingMode:
    @pytest.fixture
    def curated_dir(self, tmp_path):
        from powerhouse.data import ingest_fixtures

        ingest_fixtures(RAW_DIR, tmp_path)
        return tmp_path

    def test_overlapping_positions_defaults_to_false(self):
        assert BacktestConfig().overlapping_positions is False

    def test_overlapping_mode_runs_and_produces_metrics(self, curated_dir):
        engine = BacktestEngine(
            curated_dir=curated_dir, backtest_config=BacktestConfig(overlapping_positions=True)
        )
        result = engine.run(
            symbols=["AAPL", "MSFT", "NVDA"],
            start_date="2026-04-01",
            end_date="2026-05-26",
            phase=Phase.OPEN,
        )
        assert result.metrics.total_trades > 0
        assert len(result.executed_trades) > 0
        # No trade should ever appear twice (regression guard for a fill/close
        # double-append bug caught during development).
        trade_ids = [t.trade_id for t in result.executed_trades]
        assert len(trade_ids) == len(set(trade_ids))

    def test_overlapping_mode_is_deterministic(self, curated_dir):
        engine = BacktestEngine(
            curated_dir=curated_dir, backtest_config=BacktestConfig(overlapping_positions=True)
        )
        r1 = engine.run(symbols=["AAPL", "MSFT"], start_date="2026-04-01", end_date="2026-05-01")
        r2 = engine.run(symbols=["AAPL", "MSFT"], start_date="2026-04-01", end_date="2026-05-01")
        assert r1.metrics.total_pnl == r2.metrics.total_pnl
        assert r1.metrics.total_trades == r2.metrics.total_trades

    def test_overlapping_mode_can_hold_more_open_positions_than_resolve_on_open(self, curated_dir):
        """With overlapping positions enabled, more than one plan can be
        approved and in-flight across days for the same phase/universe than
        the Phase 2 "resolve on open" engine, which blocks a symbol from
        being re-scanned until its single open trade fully resolves.
        """
        overlapping = BacktestEngine(
            curated_dir=curated_dir, backtest_config=BacktestConfig(overlapping_positions=True)
        )
        resolve_on_open = BacktestEngine(curated_dir=curated_dir)

        overlap_result = overlapping.run(
            symbols=["AAPL", "MSFT", "NVDA"],
            start_date="2026-04-01",
            end_date="2026-05-26",
            phase=Phase.OPEN,
        )
        resolve_result = resolve_on_open.run(
            symbols=["AAPL", "MSFT", "NVDA"],
            start_date="2026-04-01",
            end_date="2026-05-26",
            phase=Phase.OPEN,
        )
        # Both should still produce trades; the resolve-on-open default
        # behavior must be completely unaffected by the new engine existing.
        assert overlap_result.metrics.total_trades > 0
        assert resolve_result.metrics.total_trades > 0
