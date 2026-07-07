"""Tests for the simulated trade execution lifecycle (no broker calls)."""

from decimal import Decimal

import pytest

from powerhouse.core.enums import OrderSide
from powerhouse.core.models import TradeEventType, TradePlan
from powerhouse.simulation.executor import Bar, TradeSimulator


def _plan(**overrides) -> TradePlan:
    defaults = dict(
        ticker="AAPL",
        side=OrderSide.BUY,
        entry_price=Decimal("100"),
        stop_loss_price=Decimal("95"),
        target_price=Decimal("110"),
        quantity=10,
        rationale="test",
    )
    defaults.update(overrides)
    return TradePlan(**defaults)


@pytest.mark.unit
class TestTradeSimulator:
    def test_no_bars_results_in_no_fill(self):
        sim = TradeSimulator()
        trade = sim.run(_plan(), bars=[])
        assert trade.outcome == "no_fill"
        assert trade.closed is False
        event_types = [e.event_type for e in trade.events]
        assert TradeEventType.PENDING_ENTRY in event_types
        assert TradeEventType.NO_FILL in event_types

    def test_fills_at_next_bar_open_with_slippage(self):
        sim = TradeSimulator(slippage_bps=100)  # 1%
        bars = [Bar(date="2026-01-02", open=100, high=101, low=99, close=100.5)]
        trade = sim.run(_plan(), bars)
        assert trade.outcome in ("manual_close",)  # only one bar: fills then closes same bar
        assert trade.entry_price == Decimal("101.0")  # 100 * 1.01

    def test_target_hit(self):
        sim = TradeSimulator(slippage_bps=0)
        bars = [
            Bar(date="d0", open=100, high=101, low=99, close=100),
            Bar(date="d1", open=101, high=112, low=100, close=111),
        ]
        trade = sim.run(_plan(), bars)
        assert trade.outcome == "target_hit"
        assert trade.closed is True
        assert trade.pnl > 0

    def test_stop_hit(self):
        sim = TradeSimulator(slippage_bps=0)
        bars = [
            Bar(date="d0", open=100, high=101, low=99, close=100),
            Bar(date="d1", open=99, high=99, low=90, close=94),
        ]
        trade = sim.run(_plan(), bars)
        assert trade.outcome == "stop_hit"
        assert trade.closed is True
        assert trade.pnl < 0

    def test_trailing_stop_updates_and_can_trigger(self):
        sim = TradeSimulator(slippage_bps=0)
        plan = _plan(trailing_stop_pct=5.0, target_price=Decimal("500"))
        bars = [
            Bar(date="d0", open=100, high=101, low=99, close=100),
            Bar(date="d1", open=100, high=120, low=100, close=120),  # trailing stop -> 114
            Bar(date="d2", open=113, high=115, low=110, close=112),  # dips below 114 -> stop hit
        ]
        trade = sim.run(plan, bars)
        trailing_events = [
            e for e in trade.events if e.event_type == TradeEventType.TRAILING_STOP_UPDATED
        ]
        assert len(trailing_events) >= 1
        assert trade.outcome == "stop_hit"

    def test_manual_close_after_max_holding_days(self):
        sim = TradeSimulator(slippage_bps=0, max_holding_days=2)
        bars = [
            Bar(date="d0", open=100, high=101, low=99, close=100),
            Bar(date="d1", open=100, high=101, low=99, close=100),
            Bar(date="d2", open=100, high=101, low=99, close=100),
            Bar(date="d3", open=100, high=101, low=99, close=100),
        ]
        trade = sim.run(_plan(), bars)
        assert trade.closed is True
        assert trade.outcome == "manual_close"

    def test_open_pending_creates_pending_event(self):
        sim = TradeSimulator()
        trade = sim.open_pending(_plan())
        assert trade.outcome == "pending"
        assert trade.events[0].event_type == TradeEventType.PENDING_ENTRY
