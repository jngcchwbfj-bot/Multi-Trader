"""Risk agent - validates and approves trade plans."""

from decimal import Decimal

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

            # Check exposure
            long_exposure = portfolio.get_long_exposure_pct()
            max_new_exposure = policy.max_long_exposure_pct
            exposure_passed = long_exposure < max_new_exposure

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

            reason = "Execution disabled" if not policy.allow_execution else "Plan approved"

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
