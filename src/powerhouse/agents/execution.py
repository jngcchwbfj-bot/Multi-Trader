"""Execution agent - routes approved plans through a `Broker`.

For a live/paper single-session run there is no forward price data to
replay against, so approved plans are recorded as simulated "pending entry"
-> "no_fill" trades with structured events. The full fill/stop/target/
trailing simulation runs in the backtest engine (`powerhouse.backtest.engine`),
which has forward bars to replay against.

This agent always routes through a `Broker` (defaulting to an in-memory
`PaperBroker`). No broker in this repo makes network calls or places a real
order - see `powerhouse.brokers` for the abstraction boundary. `OperatingMode.LIVE`
is refused outright, independent of `execution_policy.allow_execution`,
since no live broker adapter exists yet.
"""

from powerhouse.brokers import Broker, PaperBroker
from powerhouse.core.enums import OperatingMode
from powerhouse.core.exceptions import ExecutionBlockedError
from powerhouse.core.models import ExecutedTrade, RiskDecision, SessionContext, TradePlan
from powerhouse.simulation import TradeSimulator

from .base import BaseAgent


class ExecutionAgent(BaseAgent[list[ExecutedTrade]]):
    """Simulates routing of approved trade plans through a paper broker."""

    name = "Execution"

    def __init__(
        self,
        simulator: TradeSimulator | None = None,
        broker: Broker | None = None,
    ) -> None:
        self.simulator = simulator or TradeSimulator()
        self.broker = broker or PaperBroker(simulator=self.simulator)

    async def run(
        self,
        context: SessionContext,
        plans: list[TradePlan] | None = None,
        decisions: list[RiskDecision] | None = None,
    ) -> list[ExecutedTrade]:
        """Simulate execution for approved plans only.

        Args:
            context: Session context. `execution_policy.allow_execution` must
                be True for any simulated fill to be attempted; `mode=live`
                is always refused since no live broker adapter exists.
            plans: List of trade plans.
            decisions: Risk layer decisions - only plans with `approved=True`
                are simulated.

        Returns:
            List of simulated trades (empty if execution is disabled).
        """
        plans = plans or []
        decisions = decisions or []

        if context.mode == OperatingMode.LIVE:
            raise ExecutionBlockedError(
                "Live trading is not implemented in this codebase; no broker "
                "adapter may receive live orders."
            )

        if not context.execution_policy.allow_execution:
            return []

        approved_plan_ids = {d.plan_id for d in decisions if d.approved}
        trades: list[ExecutedTrade] = []
        for plan in plans:
            if plan.plan_id not in approved_plan_ids:
                continue
            # No forward bars available at single-session granularity - the
            # trade is opened as pending/no-fill and left for the backtest
            # engine (or a future paper-session replay loop) to progress.
            trades.append(self.simulator.run(plan, bars=[]))
            await self.broker.submit_order(plan)

        return trades
