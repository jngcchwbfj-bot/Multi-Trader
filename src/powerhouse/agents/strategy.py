"""Strategy agent - creates trade plans."""

from decimal import Decimal

from powerhouse.core.enums import OrderSide
from powerhouse.core.models import SessionContext, TradePlan

from .base import BaseAgent


class StrategyAgent(BaseAgent[list[TradePlan]]):
    """Drafts trade plans with entry, stop, and target."""

    name = "Strategy"

    async def run(self, context: SessionContext) -> list[TradePlan]:
        """
        Create trade plans for candidates.

        Phase 1: Return mock trade plans for testing.

        Args:
            context: Session context.

        Returns:
            List of trade plans.
        """
        plans = [
            TradePlan(
                ticker="AAPL",
                side=OrderSide.BUY,
                entry_price=Decimal("150.50"),
                stop_loss_price=Decimal("148.00"),
                target_price=Decimal("155.00"),
                quantity=10,
                rationale="Breakout play with support at 148",
                risk_per_trade_pct=0.5,
            ),
            TradePlan(
                ticker="MSFT",
                side=OrderSide.BUY,
                entry_price=Decimal("381.00"),
                stop_loss_price=Decimal("377.00"),
                target_price=Decimal("390.00"),
                quantity=5,
                rationale="Cloud momentum continuation",
                risk_per_trade_pct=0.5,
            ),
        ]
        return plans
