"""In-memory paper broker: no network calls, no real money.

`PaperBroker` is the only concrete `Broker` implementation in this repo. It
stores orders and positions purely in memory and reuses
`powerhouse.simulation.executor.TradeSimulator` for the actual fill/exit
math, so a paper account's bookkeeping is derived from the exact same
deterministic logic the backtest engine uses.

Two ways to route a plan through this broker:

- `submit_order(plan)` - the `Broker` ABC method. Mirrors a real broker: no
  forward market data is assumed, so the order comes back `PENDING` and the
  underlying trade is recorded as `no_fill` (identical to what
  `ExecutionAgent` does today without a broker at all).
- `simulate_forward(order_id, bars)` - a `PaperBroker`-only, replay/test
  helper that advances a previously-submitted order through
  `TradeSimulator.run` against supplied forward bars, updating this
  account's cash accordingly. Not used by any live CLI path; useful for
  tests and any future paper-trading loop that feeds bars incrementally.
"""

from datetime import datetime, timezone
from decimal import Decimal

from powerhouse.core.enums import OrderStatus, OrderType
from powerhouse.core.models import ExecutedTrade, Order, TradePlan
from powerhouse.simulation.executor import Bar, TradeSimulator

from .base import Broker, BrokerPosition


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PaperBroker(Broker):
    """Simulated, in-memory-only broker account."""

    name = "paper"

    def __init__(
        self,
        starting_cash: Decimal | float | str = Decimal("100000"),
        simulator: TradeSimulator | None = None,
    ) -> None:
        self._cash = Decimal(str(starting_cash))
        self._positions: dict[str, BrokerPosition] = {}
        self._orders: dict[str, Order] = {}
        self._plans: dict[str, TradePlan] = {}
        self._trades: dict[str, ExecutedTrade] = {}
        self.simulator = simulator or TradeSimulator()

    @property
    def is_paper(self) -> bool:
        return True

    def _new_order(self, plan: TradePlan) -> Order:
        return Order(
            ticker=plan.ticker,
            side=plan.side,
            order_type=OrderType.LIMIT,
            quantity=plan.quantity,
            limit_price=plan.entry_price,
            stop_price=plan.stop_loss_price,
        )

    async def submit_order(self, plan: TradePlan) -> Order:
        order = self._new_order(plan)
        order.status = OrderStatus.PENDING
        order.submitted_at = _now()

        trade = self.simulator.open_pending(plan)
        self.simulator.mark_no_fill(trade)

        self._orders[order.order_id] = order
        self._plans[order.order_id] = plan
        self._trades[order.order_id] = trade
        return order

    def simulate_forward(self, order_id: str, bars: list[Bar]) -> ExecutedTrade:
        """Replay/test-only: advance a submitted order against forward bars.

        Reuses the same `TradeSimulator` the backtest engine uses, then
        applies the resulting cash effect to this paper account. Never
        called from `run-session` or `run-paper-session`.
        """
        order = self._orders[order_id]
        plan = self._plans[order_id]
        trade = self.simulator.run(plan, bars)
        self._trades[order_id] = trade
        self._apply_trade(order, plan, trade)
        return trade

    def _apply_trade(self, order: Order, plan: TradePlan, trade: ExecutedTrade) -> None:
        if trade.outcome == "no_fill":
            order.status = OrderStatus.PENDING
            return

        order.status = OrderStatus.FILLED if trade.closed else OrderStatus.SUBMITTED
        order.filled_quantity = trade.quantity
        order.filled_price = trade.entry_price
        order.filled_at = trade.entry_timestamp

        if trade.closed and trade.pnl is not None:
            self._cash += trade.pnl
            self._positions.pop(plan.ticker, None)
        else:
            # TradeSimulator.run always fully resolves once bars are non-empty
            # today, so this branch is not currently reachable, but is kept
            # for forward-compatibility with a future incremental/bar-by-bar
            # paper-trading loop that could leave a position resting open.
            self._cash -= trade.entry_price * trade.quantity
            self._positions[plan.ticker] = BrokerPosition(
                ticker=plan.ticker,
                quantity=trade.quantity,
                average_entry_price=trade.entry_price,
            )

    async def cancel_order(self, order_id: str) -> bool:
        order = self._orders.get(order_id)
        if order is None or order.status not in (OrderStatus.PENDING, OrderStatus.SUBMITTED):
            return False
        order.status = OrderStatus.CANCELLED
        return True

    async def get_positions(self) -> dict[str, BrokerPosition]:
        return dict(self._positions)

    async def get_cash(self) -> Decimal:
        return self._cash

    async def get_orders(self) -> list[Order]:
        return list(self._orders.values())

    def get_trade(self, order_id: str) -> ExecutedTrade | None:
        """Return the `ExecutedTrade` behind a submitted order, if known."""
        return self._trades.get(order_id)
