"""Scanner agent - identifies candidate tickers."""

from decimal import Decimal

from powerhouse.core.models import Candidate, SessionContext

from .base import BaseAgent


class ScannerAgent(BaseAgent[list[Candidate]]):
    """Finds and ranks candidate tickers for trading."""

    name = "Scanner"

    async def run(self, context: SessionContext) -> list[Candidate]:
        """
        Scan for candidate tickers.

        Phase 1: Return mock candidates for testing.

        Args:
            context: Session context.

        Returns:
            List of candidate tickers with scores.
        """
        candidates = [
            Candidate(
                ticker="AAPL",
                price=Decimal("150.00"),
                market_cap=Decimal("2500000000000"),
                relevance_score=0.85,
                reason="Strong technical setup with volume support",
            ),
            Candidate(
                ticker="MSFT",
                price=Decimal("380.00"),
                market_cap=Decimal("2800000000000"),
                relevance_score=0.75,
                reason="Cloud earnings expectations",
            ),
            Candidate(
                ticker="NVDA",
                price=Decimal("875.00"),
                market_cap=Decimal("2100000000000"),
                relevance_score=0.70,
                reason="AI sector momentum",
            ),
        ]
        return candidates
