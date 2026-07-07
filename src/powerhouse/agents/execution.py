"""Execution agent - simulates order lifecycle for approved plans.

This never calls a broker. For a live/paper single-session run there is no
forward price data to replay against, so approved plans are recorded as
simulated "pending entry" -> "no_fill" trades with structured events. The
full fill/stop/target/trailing simulation runs in the backtest engine
(`powerhouse.backtest.engine`), which has forward bars to replay against.
"""

from powerhouse.core.models import ExecutedTrade, RiskDecision, SessionContext, TradePlan
from powerhouse.simulation import TradeSimulator

from .base import BaseAgent


class ExecutionAgent(BaseAgent[list[ExecutedTrade]]):
    """Simulates routing of approved trade plans (never touches a broker)."""

    name = "Execution"

    def __init__(self, simulator: TradeSimulator | None = None) -> None:
        self.simulator = simulator or TradeSimulator()

    async def run(
        self,
        context: SessionContext,
        plans: list[TradePlan] | None = None,
        decisions: list[RiskDecision] | None = None,
    ) -> list[ExecutedTrade]:
        """Simulate execution for approved plans only.

        Args:
            context: Session context. `execution_policy.allow_execution` must
                be True and the mode must not be `live` for any simulated
                fill to be attempted; live trading is not implemented.
            plans: List of trade plans.
            decisions: Risk layer decisions - only plans with `approved=True`
                are simulated.

        Returns:
            List of simulated trades (empty if execution is disabled).
        """
        plans = plans or []
        decisions = decisions or []
        if not context.execution_policy.allow_execution:
            return []

        approved_plan_ids = {d.plan_id for d in decisions if d.approved}
        trades: list[ExecutedTrade] = []
        for plan in plans:
            if plan.plan_id not in approved_plan_ids:
                continue
            # No forward bars available at single-session granularity - the
            # trade is opened as pending/no-fill and left for the backtest
            # engine (or a future broker adapter) to actually progress.
            trades.append(self.simulator.run(plan, bars=[]))

        return trades
