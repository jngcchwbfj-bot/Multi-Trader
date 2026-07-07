"""Tests for risk agent."""

from decimal import Decimal

import pytest

from powerhouse.agents.risk import RiskAgent
from powerhouse.core.enums import OperatingMode, OrderSide, Phase
from powerhouse.core.models import ExecutionPolicy, Portfolio, SessionContext, TradePlan


@pytest.mark.unit
class TestRiskAgent:
    """Test risk validation logic."""

    @pytest.fixture
    def risk_agent(self):
        return RiskAgent()

    @pytest.fixture
    def session_context(self):
        return SessionContext(
            phase=Phase.PREMARKET,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=False),
            portfolio=Portfolio(),
        )

    @pytest.fixture
    def trade_plan(self):
        return TradePlan(
            ticker="AAPL",
            side=OrderSide.BUY,
            entry_price=Decimal("150.00"),
            stop_loss_price=Decimal("148.00"),
            target_price=Decimal("155.00"),
            quantity=10,
            rationale="Test trade",
            risk_per_trade_pct=0.5,
        )

    @pytest.mark.asyncio
    async def test_reject_when_execution_disabled(self, risk_agent, session_context, trade_plan):
        """Test that execution is blocked when policy disables it."""
        decisions = await risk_agent.run(session_context, [trade_plan])
        assert len(decisions) == 1
        assert decisions[0].approved is False
        assert "Execution disabled" in decisions[0].reason

    @pytest.mark.asyncio
    async def test_approve_when_execution_enabled(
        self, risk_agent, session_context, trade_plan
    ):
        """Test that execution is approved when policy enables it."""
        session_context.execution_policy.allow_execution = True
        decisions = await risk_agent.run(session_context, [trade_plan])
        assert len(decisions) == 1
        assert decisions[0].approved is True

    @pytest.mark.asyncio
    async def test_multiple_plans(self, risk_agent, session_context, trade_plan):
        """Test risk evaluation of multiple plans."""
        plan2 = TradePlan(
            ticker="MSFT",
            side=OrderSide.BUY,
            entry_price=Decimal("380.00"),
            stop_loss_price=Decimal("377.00"),
            target_price=Decimal("390.00"),
            quantity=5,
            rationale="Test trade 2",
            risk_per_trade_pct=0.5,
        )
        decisions = await risk_agent.run(session_context, [trade_plan, plan2])
        assert len(decisions) == 2
        assert all(d.approved is False for d in decisions)  # all blocked
