"""Reporting agent - builds session reports."""

from decimal import Decimal

from powerhouse.core.enums import SessionStatus
from powerhouse.core.models import (
    Candidate,
    CatalystSummary,
    ExecutedTrade,
    RiskDecision,
    SessionContext,
    SessionReport,
    TradePlan,
)

from .base import BaseAgent


class ReportingAgent(BaseAgent[SessionReport]):
    """Builds markdown and structured reports for sessions."""

    name = "Reporting"

    async def run(
        self,
        context: SessionContext,
        candidates: list[Candidate] | None = None,
        catalysts: list[CatalystSummary] | None = None,
        plans: list[TradePlan] | None = None,
        decisions: list[RiskDecision] | None = None,
        trades: list[ExecutedTrade] | None = None,
    ) -> SessionReport:
        """
        Build a session report.

        Args:
            context: Session context.
            candidates: Candidates identified.
            catalysts: Catalyst summaries.
            plans: Trade plans proposed.
            decisions: Risk decisions.
            trades: Executed trades.

        Returns:
            Session report with markdown content.
        """
        if candidates is None:
            candidates = []
        if catalysts is None:
            catalysts = []
        if plans is None:
            plans = []
        if decisions is None:
            decisions = []
        if trades is None:
            trades = []

        approved_plans = [d for d in decisions if d.approved]
        rejected_plans = [d for d in decisions if not d.approved]

        # Build markdown report
        md_lines = [
            f"# Session Report - {context.phase.value.upper()}",
            "",
            f"**Session ID**: {context.session_id}",
            f"**Timestamp**: {context.timestamp.isoformat()}",
            f"**Mode**: {context.mode.value}",
            "",
            "## Summary",
            "",
            f"- Candidates Found: {len(candidates)}",
            f"- Trade Plans Proposed: {len(plans)}",
            f"- Plans Approved: {len(approved_plans)}",
            f"- Plans Rejected: {len(rejected_plans)}",
            f"- Trades Executed: {len(trades)}",
            "",
        ]

        if candidates:
            md_lines.extend(
                [
                    "## Candidates",
                    "",
                ]
            )
            for cand in candidates:
                md_lines.append(f"### {cand.ticker}")
                md_lines.append(f"- Price: ${cand.price}")
                md_lines.append(f"- Relevance: {cand.relevance_score:.2%}")
                md_lines.append(f"- Reason: {cand.reason}")
                md_lines.append("")

        if plans:
            md_lines.extend(
                [
                    "## Trade Plans",
                    "",
                ]
            )
            for plan in plans:
                decision = next((d for d in decisions if d.plan_id == plan.plan_id), None)
                status = decision.approved if decision else False
                md_lines.append(f"### {plan.ticker} - {plan.side.value.upper()}")
                md_lines.append(f"- Entry: ${plan.entry_price}")
                md_lines.append(f"- Stop: ${plan.stop_loss_price}")
                md_lines.append(f"- Target: ${plan.target_price}")
                md_lines.append(f"- Qty: {plan.quantity}")
                md_lines.append(f"- Rationale: {plan.rationale}")
                md_lines.append(f"- Status: {'APPROVED' if status else 'REJECTED'}")
                if decision:
                    md_lines.append(f"- Reason: {decision.reason}")
                md_lines.append("")

        if context.execution_policy.allow_execution is False:
            md_lines.extend(
                [
                    "## Execution Status",
                    "",
                    "⚠️ **Execution Disabled**: All trades were blocked due to execution policy.",
                    "",
                ]
            )

        md_lines.extend(
            [
                "## Risk Summary",
                "",
                f"- Portfolio Value: ${context.portfolio.account_value:,.2f}",
                f"- Cash: ${context.portfolio.cash:,.2f}",
                f"- Long Exposure: {context.portfolio.get_long_exposure_pct():.1f}%",
                f"- Cash Reserve: {context.portfolio.get_cash_reserve_pct():.1f}%",
                "",
            ]
        )

        markdown = "\n".join(md_lines)

        report = SessionReport(
            session_id=context.session_id,
            status=SessionStatus.SUCCESS,
            phase=context.phase,
            timestamp=context.timestamp,
            candidates_found=len(candidates),
            trade_plans_proposed=len(plans),
            trade_plans_approved=len(approved_plans),
            trade_plans_rejected=len(rejected_plans),
            trades_executed=len(trades),
            total_pnl=Decimal("0"),
            markdown_report=markdown,
        )
        return report
