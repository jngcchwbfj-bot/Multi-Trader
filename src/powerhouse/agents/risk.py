"""Risk agent - validates and approves trade plans."""

from decimal import Decimal

from powerhouse.core.enums import OrderSide
from powerhouse.core.models import RiskDecision, SessionContext, TradePlan

from .base import BaseAgent


class RiskAgent(BaseAgent[list[RiskDecision]]):
    """
    Validates trade plans against policy and market constraints.

    Enforces:
    - Daily loss caps
    - Per-trade risk limits
    - Exposure caps
    """

    name = "Risk"

    async def run(
        self, context: SessionContext, plans: list[TradePlan] | None = None
    ) -> list[RiskDecision]:
        """
        Review trade plans and make approval decisions.

        Phase 1: Reject all plans by default due to execution policy.

        Args:
            context: Session context.
            plans: List of proposed trade plans.

        Returns:
            List of risk decisions.
        """
        if plans is None:
            plans = []

        decisions = []

        for plan in plans:
            portfolio = context.portfolio
            policy = context.execution_policy

            # Check daily loss cap
            daily_loss_passed = True  # TODO: track daily losses

            # Check exposure: project what long exposure would be AFTER this
            # trade fills, not just the portfolio's current exposure. Only
            # BUY orders add long exposure (Phase 1 permits no shorting).
            current_exposure_value = portfolio.account_value - portfolio.cash
            notional_value = (
                plan.entry_price * plan.quantity
                if plan.side == OrderSide.BUY
                else Decimal("0")
            )
            projected_exposure_value = current_exposure_value + notional_value
            projected_exposure_pct = (
                float(projected_exposure_value / portfolio.account_value * 100)
                if portfolio.account_value > 0
                else 0.0
            )
            max_new_exposure = policy.max_long_exposure_pct
            exposure_passed = projected_exposure_pct <= max_new_exposure

            # Check per-trade risk
            risk_amount = plan.get_risk_amount(portfolio.account_value)
            max_risk = portfolio.account_value * Decimal(policy.max_per_trade_risk_pct / 100)
            per_trade_passed = risk_amount <= max_risk

            # In Phase 1, execution is blocked by default
            approved = (
                policy.allow_execution
                and daily_loss_passed
                and exposure_passed
                and per_trade_passed
            )

            if not policy.allow_execution:
                reason = "Execution disabled"
            elif not daily_loss_passed:
                reason = "Daily loss cap exceeded"
            elif not exposure_passed:
                reason = (
                    f"Long exposure cap exceeded: projected "
                    f"{projected_exposure_pct:.1f}% > cap {max_new_exposure:.1f}%"
                )
            elif not per_trade_passed:
                reason = "Per-trade risk limit exceeded"
            else:
                reason = "Plan approved"

            adjusted_quantity = plan.quantity if approved else 0

            decision = RiskDecision(
                plan_id=plan.plan_id,
                ticker=plan.ticker,
                approved=approved,
                reason=reason,
                adjusted_quantity=adjusted_quantity,
                daily_loss_check_passed=daily_loss_passed,
                exposure_check_passed=exposure_passed,
                per_trade_risk_check_passed=per_trade_passed,
            )
            decisions.append(decision)

        return decisions
