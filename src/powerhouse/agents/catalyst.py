"""Catalyst agent - analyzes news and catalysts."""

from powerhouse.core.models import Candidate, CatalystSummary, SessionContext

from .base import BaseAgent


class CatalystAgent(BaseAgent[list[CatalystSummary]]):
    """Summarizes news, events, and catalyst context for candidates."""

    name = "Catalyst"

    async def run(self, context: SessionContext) -> list[CatalystSummary]:
        """
        Analyze catalysts for candidates.

        Phase 1: Return mock catalysts for testing.

        Args:
            context: Session context.

        Returns:
            List of catalyst summaries.
        """
        catalysts = [
            CatalystSummary(
                ticker="AAPL",
                catalyst_type="technical",
                summary="Strong support at 150, resistance at 155",
                sentiment="bullish",
                confidence=0.8,
            ),
            CatalystSummary(
                ticker="MSFT",
                catalyst_type="earnings",
                summary="Cloud revenue growth expected to accelerate",
                sentiment="bullish",
                confidence=0.75,
            ),
            CatalystSummary(
                ticker="NVDA",
                catalyst_type="macro",
                summary="AI infrastructure spending cycle continues",
                sentiment="bullish",
                confidence=0.7,
            ),
        ]
        return catalysts
