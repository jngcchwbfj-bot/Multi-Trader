"""Conductor orchestration service."""

from powerhouse.agents.catalyst import CatalystAgent
from powerhouse.agents.execution import ExecutionAgent
from powerhouse.agents.reporting import ReportingAgent
from powerhouse.agents.risk import RiskAgent
from powerhouse.agents.scanner import ScannerAgent
from powerhouse.agents.strategy import StrategyAgent
from powerhouse.core.enums import SessionStatus
from powerhouse.core.models import SessionContext, SessionResult


class ConductorService:
    """Orchestrates trading workflow for a session."""

    def __init__(self):
        self.scanner = ScannerAgent()
        self.catalyst = CatalystAgent()
        self.strategy = StrategyAgent()
        self.risk = RiskAgent()
        self.execution = ExecutionAgent()
        self.reporting = ReportingAgent()

    async def run_session(self, context: SessionContext) -> SessionResult:
        """
        Execute a complete trading session workflow.

        Flow:
        1. Scanner identifies candidates.
        2. Catalyst analyzes context.
        3. Strategy creates trade plans.
        4. Risk validates and approves.
        5. Execution routes orders (or blocks).
        6. Reporting builds output.

        Args:
            context: Session context with portfolio, mode, and execution policy.

        Returns:
            Complete session result with trades, report, and logs.
        """
        result = SessionResult(status=SessionStatus.IN_PROGRESS)
        try:
            # Stage 1: Identify candidates
            result.candidates = await self.scanner.run(context)

            # Stage 2: Analyze catalysts
            result.catalysts = await self.catalyst.run(context)

            # Stage 3: Create trade plans
            result.trade_plans = await self.strategy.run(context)

            # Stage 4: Risk validation
            result.risk_decisions = await self.risk.run(context, result.trade_plans)

            # Stage 5: Execute approved trades
            result.executed_trades = await self.execution.run(
                context, result.trade_plans, result.risk_decisions
            )

            # Stage 6: Build report
            result.report = await self.reporting.run(
                context,
                result.candidates,
                result.catalysts,
                result.trade_plans,
                result.risk_decisions,
                result.executed_trades,
            )

            result.status = SessionStatus.SUCCESS
        except Exception as e:
            result.status = SessionStatus.FAILED
            result.errors.append(str(e))
            result.report.status = SessionStatus.FAILED
            result.report.error_message = str(e)

        return result
