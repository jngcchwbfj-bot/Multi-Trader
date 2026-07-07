"""Tests for the broker abstraction boundary (paper-only, no network calls)."""

import socket
from decimal import Decimal

import pytest

from powerhouse.agents.execution import ExecutionAgent
from powerhouse.brokers import Broker, BrokerPosition, PaperBroker
from powerhouse.core.enums import OperatingMode, OrderSide, OrderStatus, Phase
from powerhouse.core.exceptions import ExecutionBlockedError
from powerhouse.core.models import (
    ExecutionPolicy,
    Portfolio,
    RiskDecision,
    SessionContext,
    TradePlan,
)
from powerhouse.simulation.executor import Bar


def _plan(ticker="AAPL", **overrides) -> TradePlan:
    defaults = dict(
        ticker=ticker,
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
class TestBrokerABC:
    def test_cannot_instantiate_broker_directly(self):
        with pytest.raises(TypeError):
            Broker()  # type: ignore[abstract]


@pytest.mark.unit
class TestPaperBroker:
    @pytest.mark.asyncio
    async def test_starts_with_given_cash_and_empty_state(self):
        broker = PaperBroker(starting_cash=Decimal("50000"))
        assert await broker.get_cash() == Decimal("50000")
        assert await broker.get_positions() == {}
        assert await broker.get_orders() == []
        assert broker.is_paper is True
        assert broker.name == "paper"

    @pytest.mark.asyncio
    async def test_submit_order_creates_pending_order_with_no_forward_data(self):
        broker = PaperBroker()
        order = await broker.submit_order(_plan())
        assert order.status == OrderStatus.PENDING
        assert order.ticker == "AAPL"
        assert order.quantity == 10
        orders = await broker.get_orders()
        assert len(orders) == 1
        assert orders[0].order_id == order.order_id

    @pytest.mark.asyncio
    async def test_submit_order_does_not_change_cash_or_positions(self):
        broker = PaperBroker(starting_cash=Decimal("100000"))
        await broker.submit_order(_plan())
        assert await broker.get_cash() == Decimal("100000")
        assert await broker.get_positions() == {}

    @pytest.mark.asyncio
    async def test_cancel_pending_order_succeeds(self):
        broker = PaperBroker()
        order = await broker.submit_order(_plan())
        assert await broker.cancel_order(order.order_id) is True
        orders = await broker.get_orders()
        assert orders[0].status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_cancel_unknown_order_returns_false(self):
        broker = PaperBroker()
        assert await broker.cancel_order("does-not-exist") is False

    @pytest.mark.asyncio
    async def test_cancel_already_cancelled_order_returns_false(self):
        broker = PaperBroker()
        order = await broker.submit_order(_plan())
        await broker.cancel_order(order.order_id)
        assert await broker.cancel_order(order.order_id) is False

    @pytest.mark.asyncio
    async def test_simulate_forward_target_hit_increases_cash(self):
        broker = PaperBroker(starting_cash=Decimal("100000"))
        order = await broker.submit_order(_plan())
        bars = [
            Bar(date="2026-01-02", open=100, high=101, low=99, close=100),
            Bar(date="2026-01-05", open=101, high=112, low=100, close=111),
        ]
        trade = broker.simulate_forward(order.order_id, bars)
        assert trade.outcome == "target_hit"
        assert trade.pnl > 0
        assert await broker.get_cash() == Decimal("100000") + trade.pnl
        orders = await broker.get_orders()
        assert orders[0].status == OrderStatus.FILLED
        assert broker.get_trade(order.order_id) is trade

    @pytest.mark.asyncio
    async def test_simulate_forward_stop_hit_decreases_cash(self):
        broker = PaperBroker(starting_cash=Decimal("100000"))
        order = await broker.submit_order(_plan())
        bars = [
            Bar(date="2026-01-02", open=100, high=101, low=99, close=100),
            Bar(date="2026-01-05", open=99, high=99, low=90, close=94),
        ]
        trade = broker.simulate_forward(order.order_id, bars)
        assert trade.outcome == "stop_hit"
        assert trade.pnl < 0
        assert await broker.get_cash() == Decimal("100000") + trade.pnl

    def test_no_network_calls_during_full_lifecycle(self, monkeypatch):
        def _blocked(*args, **kwargs):
            raise AssertionError("PaperBroker attempted a network call")

        monkeypatch.setattr(socket, "create_connection", _blocked)
        monkeypatch.setattr(socket.socket, "connect", _blocked)

        import asyncio

        async def _run():
            broker = PaperBroker()
            order = await broker.submit_order(_plan())
            bars = [
                Bar(date="2026-01-02", open=100, high=101, low=99, close=100),
                Bar(date="2026-01-05", open=101, high=112, low=100, close=111),
            ]
            broker.simulate_forward(order.order_id, bars)
            await broker.get_positions()
            await broker.get_cash()
            await broker.get_orders()
            await broker.cancel_order(order.order_id)

        asyncio.run(_run())  # would raise AssertionError above if any socket call occurred

    def test_broker_position_model_fields(self):
        position = BrokerPosition(ticker="AAPL", quantity=10, average_entry_price=Decimal("100"))
        assert position.ticker == "AAPL"
        assert position.quantity == 10


@pytest.mark.unit
class TestExecutionAgentBrokerWiring:
    @pytest.fixture
    def approved_context(self):
        return SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=True),
            portfolio=Portfolio(),
        )

    def _approved_decision(self, plan: TradePlan) -> RiskDecision:
        return RiskDecision(
            plan_id=plan.plan_id,
            ticker=plan.ticker,
            approved=True,
            reason="Plan approved",
            adjusted_quantity=plan.quantity,
            daily_loss_check_passed=True,
            exposure_check_passed=True,
            per_trade_risk_check_passed=True,
        )

    @pytest.mark.asyncio
    async def test_defaults_to_a_paper_broker(self):
        agent = ExecutionAgent()
        assert isinstance(agent.broker, PaperBroker)
        assert agent.broker.is_paper is True

    @pytest.mark.asyncio
    async def test_forwards_approved_plans_to_the_broker(self, approved_context):
        broker = PaperBroker()
        agent = ExecutionAgent(broker=broker)
        plan = _plan()
        decision = self._approved_decision(plan)

        trades = await agent.run(approved_context, [plan], [decision])

        assert len(trades) == 1
        assert trades[0].outcome == "no_fill"  # no forward data at this call site
        orders = await broker.get_orders()
        assert len(orders) == 1
        assert orders[0].ticker == "AAPL"

    @pytest.mark.asyncio
    async def test_rejected_plans_are_not_forwarded_to_broker(self, approved_context):
        broker = PaperBroker()
        agent = ExecutionAgent(broker=broker)
        plan = _plan()
        rejected = RiskDecision(
            plan_id=plan.plan_id,
            ticker=plan.ticker,
            approved=False,
            reason="Execution disabled",
            adjusted_quantity=0,
            daily_loss_check_passed=True,
            exposure_check_passed=True,
            per_trade_risk_check_passed=True,
        )
        trades = await agent.run(approved_context, [plan], [rejected])
        assert trades == []
        assert await broker.get_orders() == []

    @pytest.mark.asyncio
    async def test_live_mode_is_always_blocked(self, approved_context):
        approved_context.mode = OperatingMode.LIVE
        agent = ExecutionAgent()
        plan = _plan()
        decision = self._approved_decision(plan)
        with pytest.raises(ExecutionBlockedError):
            await agent.run(approved_context, [plan], [decision])

    @pytest.mark.asyncio
    async def test_execution_disabled_returns_no_trades_and_no_orders(self):
        broker = PaperBroker()
        agent = ExecutionAgent(broker=broker)
        ctx = SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=False),
            portfolio=Portfolio(),
        )
        plan = _plan()
        decision = self._approved_decision(plan)
        trades = await agent.run(ctx, [plan], [decision])
        assert trades == []
        assert await broker.get_orders() == []
