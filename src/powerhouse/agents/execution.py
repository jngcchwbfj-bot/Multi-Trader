"""Execution agent - routes orders to broker or paper."""

from powerhouse.core.models import ExecutedTrade, RiskDecision, SessionContext, TradePlan

from .base import BaseAgent


class ExecutionAgent(BaseAgent[list[ExecutedTrade]]):
    """Routes approved trade plans to broker adapter (or simulates)."""

    name = "Execution"

    async def run(
        self,
        context: SessionContext,
        plans: list[TradePlan] | None = None,
        decisions: list[RiskDecision] | None = None,
    ) -> list[ExecutedTrade]:
        """
        Execute approved trade plans.

        Phase 1: No execution. Return empty list.

        Args:
            context: Session context.
            plans: List of trade plans.
            decisions: Risk layer decisions.

        Returns:
            List of executed trades (empty in Phase 1).
        """
        return []
