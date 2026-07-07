"""Reporting agent - builds markdown/structured reports and writes artifacts."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from powerhouse.config import ReportingConfig
from powerhouse.core.enums import SessionStatus
from powerhouse.core.models import (
    BacktestResult,
    Candidate,
    CatalystSummary,
    ExecutedTrade,
    RiskDecision,
    SessionContext,
    SessionReport,
    TradePlan,
)

from .base import BaseAgent


def _json_default(obj: Any) -> Any:
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


class ReportingAgent(BaseAgent[SessionReport]):
    """Builds markdown and structured reports, and writes JSONL/Parquet artifacts."""

    name = "Reporting"

    def __init__(self, config: ReportingConfig | None = None) -> None:
        self.config = config or ReportingConfig()

    async def run(
        self,
        context: SessionContext,
        candidates: list[Candidate] | None = None,
        catalysts: list[CatalystSummary] | None = None,
        plans: list[TradePlan] | None = None,
        decisions: list[RiskDecision] | None = None,
        trades: list[ExecutedTrade] | None = None,
    ) -> SessionReport:
        """Build a session report and write artifacts to disk."""
        candidates = candidates or []
        catalysts = catalysts or []
        plans = plans or []
        decisions = decisions or []
        trades = trades or []

        # Ranked candidates: preserve the scanner's ranking order (already sorted).
        ranked_candidates = list(candidates)

        approved_plans = [d for d in decisions if d.approved]
        rejected_plans = [d for d in decisions if not d.approved]

        markdown = self._build_markdown(
            context, ranked_candidates, catalysts, plans, decisions, trades
        )

        realized_pnl = sum((t.pnl for t in trades if t.pnl is not None), Decimal("0"))

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
            total_pnl=realized_pnl,
            markdown_report=markdown,
        )

        if self.config.write_jsonl or self.config.write_parquet:
            self._write_artifacts(context, ranked_candidates, catalysts, plans, decisions, trades)

        return report

    def _build_markdown(
        self,
        context: SessionContext,
        candidates: list[Candidate],
        catalysts: list[CatalystSummary],
        plans: list[TradePlan],
        decisions: list[RiskDecision],
        trades: list[ExecutedTrade],
    ) -> str:
        approved_plans = [d for d in decisions if d.approved]
        rejected_plans = [d for d in decisions if not d.approved]
        catalyst_by_ticker = {c.ticker: c for c in catalysts}

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
            f"- Trades Executed (simulated): {len(trades)}",
            "",
        ]

        if candidates:
            md_lines.extend(["## Ranked Candidates", ""])
            for i, cand in enumerate(candidates, start=1):
                catalyst = catalyst_by_ticker.get(cand.ticker)
                md_lines.append(
                    f"{i}. **{cand.ticker}** - ${cand.price} "
                    f"(score {cand.relevance_score:.2f}) - {cand.reason}"
                )
                if catalyst:
                    md_lines.append(
                        f"   - Catalyst [{catalyst.sentiment}]: {catalyst.summary} "
                        f"(confidence {catalyst.confidence:.2f})"
                    )
            md_lines.append("")

        if plans:
            md_lines.extend(["## Trade Plans", ""])
            for plan in plans:
                decision = next((d for d in decisions if d.plan_id == plan.plan_id), None)
                status = decision.approved if decision else False
                md_lines.append(f"### {plan.ticker} - {plan.side.value.upper()}")
                md_lines.append(f"- Entry: ${plan.entry_price}")
                md_lines.append(f"- Stop: ${plan.stop_loss_price}")
                md_lines.append(f"- Target: ${plan.target_price}")
                md_lines.append(f"- Qty: {plan.quantity}")
                if plan.trailing_stop_pct:
                    md_lines.append(f"- Trailing Stop: {plan.trailing_stop_pct:.2f}%")
                md_lines.append(f"- Confidence: {plan.confidence:.2f}")
                md_lines.append(f"- Rationale: {plan.rationale}")
                md_lines.append(f"- Status: {'APPROVED' if status else 'REJECTED'}")
                if decision:
                    md_lines.append(f"- Reason: {decision.reason}")
                md_lines.append("")

        if trades:
            md_lines.extend(["## Simulated Outcomes", ""])
            for trade in trades:
                md_lines.append(
                    f"- {trade.ticker}: {trade.outcome} "
                    f"(entry ${trade.entry_price}, exit {trade.exit_price}, pnl {trade.pnl})"
                )
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
                f"- Daily Loss: {context.portfolio.get_daily_loss_pct():.2f}%",
                f"- Open Risk: {context.portfolio.get_open_risk_pct():.2f}%",
                "",
            ]
        )

        return "\n".join(md_lines)

    def _write_artifacts(
        self,
        context: SessionContext,
        candidates: list[Candidate],
        catalysts: list[CatalystSummary],
        plans: list[TradePlan],
        decisions: list[RiskDecision],
        trades: list[ExecutedTrade],
    ) -> None:
        artifacts_dir = Path(self.config.artifacts_dir) / "sessions"
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        # `kind` is singular per record (matches the backtest artifact
        # convention below) so a dashboard can rely on one naming scheme
        # across both artifact families. See docs/artifacts.md.
        records: dict[str, list[dict]] = {
            "candidate": [c.model_dump() for c in candidates],
            "catalyst": [c.model_dump() for c in catalysts],
            "trade_plan": [p.model_dump() for p in plans],
            "risk_decision": [d.model_dump() for d in decisions],
            "executed_trade": [t.model_dump() for t in trades],
        }
        common = {
            "session_id": context.session_id,
            "phase": context.phase.value,
            "mode": context.mode.value,
            "timestamp": context.timestamp,
        }

        if self.config.write_jsonl:
            jsonl_path = artifacts_dir / f"{context.session_id}.jsonl"
            with jsonl_path.open("w") as f:
                for kind, rows in records.items():
                    for row in rows:
                        f.write(
                            json.dumps({"kind": kind, **common, **row}, default=_json_default)
                            + "\n"
                        )

        if self.config.write_parquet and plans:
            rows = [
                json.loads(json.dumps({**common, **p.model_dump()}, default=_json_default))
                for p in plans
            ]
            table = pa.Table.from_pylist(rows)
            pq.write_table(table, artifacts_dir / f"{context.session_id}_plans.parquet")


def build_backtest_markdown(result: BacktestResult) -> str:
    """Build a markdown summary report for a completed backtest."""
    m = result.metrics
    lines = [
        "# Backtest Report",
        "",
        f"**Backtest ID**: {result.backtest_id}",
        f"**Symbols**: {', '.join(result.symbols)}",
        f"**Range**: {result.start_date} to {result.end_date}",
        "",
        "## Summary Metrics",
        "",
        f"- Total Trades: {m.total_trades}",
        f"- Wins / Losses: {m.wins} / {m.losses}",
        f"- Win Rate: {m.win_rate:.2%}",
        f"- Total PnL: ${m.total_pnl:,.2f}",
        f"- Profit Factor: {m.profit_factor}",
        f"- Max Drawdown: {m.max_drawdown_pct:.2f}%",
        f"- Starting Value: ${m.starting_account_value:,.2f}",
        f"- Ending Value: ${m.ending_account_value:,.2f}",
        f"- Return: {m.return_pct:.2f}%",
        "",
        "## Trades",
        "",
    ]
    for t in result.executed_trades:
        lines.append(
            f"- {t.ticker}: {t.outcome} entry=${t.entry_price} exit=${t.exit_price} pnl={t.pnl}"
        )
    return "\n".join(lines)


def _write_jsonl_record(f, kind: str, backtest_id: str, record: dict) -> None:
    f.write(
        json.dumps({"kind": kind, "backtest_id": backtest_id, **record}, default=_json_default)
        + "\n"
    )


def write_backtest_artifacts(result: BacktestResult, config: ReportingConfig | None = None) -> Path:
    """Write JSONL + Parquet artifacts for a completed backtest run.

    Every JSONL row carries `backtest_id` and `kind` so rows from multiple
    runs can be safely concatenated/joined by an external dashboard. Only
    the singleton `metrics` row also carries run-level metadata (symbols,
    date range) to avoid repeating it on every trade/plan/decision row. See
    docs/artifacts.md for the full field reference.
    """
    config = config or ReportingConfig()
    out_dir = Path(config.artifacts_dir) / "runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    bid = result.backtest_id

    jsonl_path = out_dir / f"{bid}.jsonl"
    with jsonl_path.open("w") as f:
        _write_jsonl_record(
            f,
            "metrics",
            bid,
            {
                "symbols": result.symbols,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "created_at": result.created_at,
                **result.metrics.model_dump(),
            },
        )
        for plan in result.trade_plans:
            _write_jsonl_record(f, "trade_plan", bid, plan.model_dump())
        for decision in result.risk_decisions:
            _write_jsonl_record(f, "risk_decision", bid, decision.model_dump())
        for trade in result.executed_trades:
            _write_jsonl_record(f, "executed_trade", bid, trade.model_dump())
        for point in result.equity_curve:
            _write_jsonl_record(f, "equity_point", bid, point)

    if result.executed_trades:
        rows = [
            json.loads(json.dumps({"backtest_id": bid, **t.model_dump()}, default=_json_default))
            for t in result.executed_trades
        ]
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, out_dir / f"{bid}_trades.parquet")

    if result.equity_curve:
        equity_rows = [{"backtest_id": bid, **point} for point in result.equity_curve]
        pq.write_table(pa.Table.from_pylist(equity_rows), out_dir / f"{bid}_equity.parquet")

    return jsonl_path
