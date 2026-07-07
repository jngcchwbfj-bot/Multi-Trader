"""Tests for daily loss cap enforcement and total open risk tracking."""

from decimal import Decimal

import pytest

from powerhouse.agents.risk import RiskAgent
from powerhouse.core.enums import OperatingMode, OrderSide, Phase
from powerhouse.core.models import ExecutionPolicy, Portfolio, SessionContext, TradePlan


def _plan(ticker="AAPL", entry=150, stop=148, target=155, qty=10) -> TradePlan:
    return TradePlan(
        ticker=ticker,
        side=OrderSide.BUY,
        entry_price=Decimal(str(entry)),
        stop_loss_price=Decimal(str(stop)),
        target_price=Decimal(str(target)),
        quantity=qty,
        rationale="test",
    )


@pytest.mark.unit
class TestDailyLossEnforcement:
    @pytest.fixture
    def risk_agent(self):
        return RiskAgent()

    @pytest.mark.asyncio
    async def test_blocks_new_trades_once_daily_loss_cap_hit(self, risk_agent):
        portfolio = Portfolio(
            account_value=Decimal("100000"),
            cash=Decimal("100000"),
            realized_pnl_today=Decimal("-1500"),  # 1.5% loss today
        )
        ctx = SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=True, max_daily_loss_pct=1.0),
            portfolio=portfolio,
        )
        decisions = await risk_agent.run(ctx, [_plan()])
        assert decisions[0].approved is False
        assert decisions[0].daily_loss_check_passed is False
        assert "Daily loss cap exceeded" in decisions[0].reason

    @pytest.mark.asyncio
    async def test_allows_trades_when_under_daily_loss_cap(self, risk_agent):
        portfolio = Portfolio(
            account_value=Decimal("100000"),
            cash=Decimal("100000"),
            realized_pnl_today=Decimal("-200"),  # 0.2% loss today
        )
        ctx = SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=True, max_daily_loss_pct=1.0),
            portfolio=portfolio,
        )
        decisions = await risk_agent.run(ctx, [_plan()])
        assert decisions[0].daily_loss_check_passed is True

    @pytest.mark.asyncio
    async def test_profitable_day_never_trips_loss_cap(self, risk_agent):
        portfolio = Portfolio(
            account_value=Decimal("100000"),
            cash=Decimal("100000"),
            realized_pnl_today=Decimal("5000"),
        )
        assert portfolio.get_daily_loss_pct() == 0.0


@pytest.mark.unit
class TestTotalOpenRiskEnforcement:
    @pytest.fixture
    def risk_agent(self):
        return RiskAgent()

    @pytest.mark.asyncio
    async def test_blocks_when_total_open_risk_exceeded(self, risk_agent):
        portfolio = Portfolio(
            account_value=Decimal("100000"),
            cash=Decimal("100000"),
            open_risk_amount=Decimal("1900"),  # 1.9% already committed
        )
        ctx = SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(
                allow_execution=True, max_total_open_risk_pct=2.0, max_per_trade_risk_pct=5.0
            ),
            portfolio=portfolio,
        )
        # risk of this plan: (150-148)*10 = 20, well within per-trade cap,
        # but 1900 + 20 = 1920 > 2000 is still fine... use a bigger plan.
        big_plan = _plan(entry=150, stop=100, qty=10)  # risk = 500
        decisions = await risk_agent.run(ctx, [big_plan])
        assert decisions[0].total_open_risk_check_passed is False
        assert decisions[0].approved is False
        assert "Total open risk cap exceeded" in decisions[0].reason

    @pytest.mark.asyncio
    async def test_open_risk_accumulates_across_approved_plans(self, risk_agent):
        portfolio = Portfolio(account_value=Decimal("100000"), cash=Decimal("100000"))
        ctx = SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(
                allow_execution=True,
                max_total_open_risk_pct=2.0,
                max_per_trade_risk_pct=5.0,
                max_long_exposure_pct=100.0,
            ),
            portfolio=portfolio,
        )
        plan1 = _plan(ticker="AAPL", entry=100, stop=95, qty=100)  # risk 500 (0.5%)
        decisions1 = await risk_agent.run(ctx, [plan1])
        assert decisions1[0].approved is True
        assert portfolio.open_risk_amount == Decimal("500")


@pytest.mark.unit
class TestPlanValidity:
    @pytest.mark.asyncio
    async def test_rejects_plan_with_invalid_stop_above_entry(self):
        risk_agent = RiskAgent()
        ctx = SessionContext(
            phase=Phase.OPEN,
            execution_policy=ExecutionPolicy(allow_execution=True),
            portfolio=Portfolio(),
        )
        bad_plan = _plan(entry=100, stop=110, target=120)  # invalid: stop above entry
        decisions = await risk_agent.run(ctx, [bad_plan])
        assert decisions[0].approved is False
        assert "Invalid plan" in decisions[0].reason

    @pytest.mark.asyncio
    async def test_rejects_plan_with_zero_quantity(self):
        risk_agent = RiskAgent()
        ctx = SessionContext(
            phase=Phase.OPEN,
            execution_policy=ExecutionPolicy(allow_execution=True),
            portfolio=Portfolio(),
        )
        bad_plan = _plan(qty=0)
        decisions = await risk_agent.run(ctx, [bad_plan])
        assert decisions[0].approved is False
        assert "quantity" in decisions[0].reason
