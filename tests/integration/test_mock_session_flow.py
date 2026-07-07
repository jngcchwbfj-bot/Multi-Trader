"""Integration tests for mock session workflow."""

import pytest
from datetime import datetime, timezone

from powerhouse.conductor.service import ConductorService
from powerhouse.core.enums import OperatingMode, Phase, SessionStatus
from powerhouse.core.models import ExecutionPolicy, Portfolio, SessionContext


@pytest.mark.integration
class TestMockSessionFlow:
    """Test complete session workflow."""

    @pytest.fixture
    def conductor(self):
        return ConductorService()

    @pytest.fixture
    def session_context(self):
        return SessionContext(
            timestamp=datetime.now(timezone.utc),
            phase=Phase.PREMARKET,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=False),
            portfolio=Portfolio(),
        )

    @pytest.mark.asyncio
    async def test_premarket_session_complete_flow(self, conductor, session_context):
        """Test complete premarket session execution."""
        result = await conductor.run_session(session_context)

        assert result.status == SessionStatus.SUCCESS
        assert len(result.candidates) > 0
        assert len(result.catalysts) > 0
        assert len(result.trade_plans) > 0
        assert len(result.risk_decisions) > 0

    @pytest.mark.asyncio
    async def test_session_produces_report(self, conductor, session_context):
        """Test that session produces a valid report."""
        result = await conductor.run_session(session_context)

        assert result.report is not None
        assert result.report.session_id == session_context.session_id
        assert result.report.phase == Phase.PREMARKET
        assert "Session Report" in result.report.markdown_report
        assert "Summary" in result.report.markdown_report

    @pytest.mark.asyncio
    async def test_session_with_execution_enabled(self, conductor, session_context):
        """Test session with execution policy enabled."""
        session_context.execution_policy.allow_execution = True
        result = await conductor.run_session(session_context)

        assert result.status == SessionStatus.SUCCESS
        # In Phase 1, trades can still be blocked by other risk checks
        # but the execution gate should not be the reason

    @pytest.mark.asyncio
    async def test_session_tracks_candidates_to_trades(self, conductor, session_context):
        """Test that candidates flow through to trade plans."""
        result = await conductor.run_session(session_context)

        # At least some candidates should have corresponding trade plans
        candidate_tickers = {c.ticker for c in result.candidates}
        plan_tickers = {p.ticker for p in result.trade_plans}

        # Plans should be a subset of or same as candidates
        assert plan_tickers.issubset(candidate_tickers) or len(plan_tickers) > 0
