"""Risk agent - validates and approves trade plans.

All checks are deterministic (no LLM judgment). Vetoes are returned with a
specific, human-readable reason so the audit trail always explains *why*
a plan was blocked, not just that it was.
"""

from decimal import Decimal

from powerhouse.core.enums import OrderSide
from powerhouse.core.models import RiskDecision, SessionContext, TradePlan

from .base import BaseAgent


def _plan_is_valid(plan: TradePlan) -> str | None:
    """Return a veto reason if the plan is structurally invalid, else None."""
    if not plan.ticker or not plan.ticker.strip():
        return "Trade plan missing required field: ticker"
    if not plan.rationale or not plan.rationale.strip():
        return "Trade plan missing required field: rationale"
    if plan.entry_price is None or plan.entry_price <= 0:
        return "Trade plan missing/invalid required field: entry_price"
    if plan.stop_loss_price is None or plan.stop_loss_price <= 0:
        return "Trade plan missing/invalid required field: stop_loss_price"
    if plan.target_price is None or plan.target_price <= 0:
        return "Trade plan missing/invalid required field: target_price"
    if plan.quantity is None or plan.quantity < 1:
        return "Trade plan missing/invalid required field: quantity"
    if plan.side == OrderSide.BUY and plan.stop_loss_price >= plan.entry_price:
        return "Invalid plan: stop_loss_price must be below entry_price for a long"
    if plan.side == OrderSide.BUY and plan.target_price <= plan.entry_price:
        return "Invalid plan: target_price must be above entry_price for a long"
    return None


class RiskAgent(BaseAgent[list[RiskDecision]]):
    """
    Validates trade plans against policy and market constraints.

    Enforces, in order:
    1. Plan structural validity (required fields present and sane).
    2. Execution policy gate (`allow_execution`).
    3. Daily loss cap (today's realized loss vs. `max_daily_loss_pct`).
    4. Projected post-trade long exposure cap.
    5. Per-trade risk cap.
    6. Total open risk cap (sum of per-trade risk across open positions).
    """

    name = "Risk"

    async def run(
        self, context: SessionContext, plans: list[TradePlan] | None = None
    ) -> list[RiskDecision]:
        if plans is None:
            plans = []

        decisions = []
        portfolio = context.portfolio
        policy = context.execution_policy

        for plan in plans:
            invalid_reason = _plan_is_valid(plan)

            # Daily loss cap: check today's realized loss against the cap.
            daily_loss_passed = portfolio.get_daily_loss_pct() < policy.max_daily_loss_pct

            # Exposure: project what long exposure would be AFTER this trade
            # fills, not just the portfolio's current exposure. Only BUY
            # orders add long exposure (no shorting is permitted).
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

            # Per-trade risk.
            risk_amount = plan.get_risk_amount(portfolio.account_value)
            max_risk = portfolio.account_value * Decimal(policy.max_per_trade_risk_pct / 100)
            per_trade_passed = risk_amount <= max_risk

            # Total open risk: this trade's risk plus whatever's already open.
            projected_open_risk = portfolio.open_risk_amount + risk_amount
            max_total_open_risk = portfolio.account_value * Decimal(
                policy.max_total_open_risk_pct / 100
            )
            total_open_risk_passed = projected_open_risk <= max_total_open_risk

            approved = (
                invalid_reason is None
                and policy.allow_execution
                and daily_loss_passed
                and exposure_passed
                and per_trade_passed
                and total_open_risk_passed
            )

            if invalid_reason:
                reason = invalid_reason
            elif not policy.allow_execution:
                reason = "Execution disabled"
            elif not daily_loss_passed:
                reason = (
                    f"Daily loss cap exceeded: {portfolio.get_daily_loss_pct():.2f}% "
                    f"> cap {policy.max_daily_loss_pct:.2f}%"
                )
            elif not exposure_passed:
                reason = (
                    f"Long exposure cap exceeded: projected "
                    f"{projected_exposure_pct:.1f}% > cap {max_new_exposure:.1f}%"
                )
            elif not per_trade_passed:
                reason = "Per-trade risk limit exceeded"
            elif not total_open_risk_passed:
                reason = (
                    "Total open risk cap exceeded: projected "
                    f"{float(projected_open_risk / portfolio.account_value * 100):.2f}% "
                    f"> cap {policy.max_total_open_risk_pct:.2f}%"
                )
            else:
                reason = "Plan approved"

            adjusted_quantity = plan.quantity if approved else 0

            if approved:
                portfolio.open_risk_amount += risk_amount

            decision = RiskDecision(
                plan_id=plan.plan_id,
                ticker=plan.ticker,
                approved=approved,
                reason=reason,
                adjusted_quantity=adjusted_quantity,
                daily_loss_check_passed=daily_loss_passed,
                exposure_check_passed=exposure_passed,
                per_trade_risk_check_passed=per_trade_passed,
                total_open_risk_check_passed=total_open_risk_passed,
            )
            decisions.append(decision)

        return decisions
