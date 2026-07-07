"""Catalyst agent - fixture-based structured news/catalyst annotations."""

import csv
from pathlib import Path

from powerhouse.core.models import Candidate, CatalystSummary, SessionContext

from .base import BaseAgent

DEFAULT_CATALYST_FIXTURE = Path("data/raw/catalysts.csv")


def load_catalyst_fixtures(
    fixture_path: Path | str = DEFAULT_CATALYST_FIXTURE,
) -> dict[str, CatalystSummary]:
    """Load the structured catalyst fixture CSV into a ticker-keyed dict.

    Shared by CatalystAgent (live/session use) and the backtest engine.
    """
    fixture_path = Path(fixture_path)
    if not fixture_path.exists():
        return {}
    by_ticker: dict[str, CatalystSummary] = {}
    with fixture_path.open("r", newline="") as f:
        for row in csv.DictReader(f):
            ticker = row["ticker"].strip().upper()
            by_ticker[ticker] = CatalystSummary(
                ticker=ticker,
                catalyst_type=row["catalyst_type"],
                summary=row["summary"],
                sentiment=row["sentiment"],
                confidence=float(row["confidence"]),
            )
    return by_ticker


class CatalystAgent(BaseAgent[list[CatalystSummary]]):
    """Attaches lightweight, fixture-based catalyst annotations to candidates.

    This intentionally stays "dumb": it reads structured rows from a local
    CSV fixture (ticker, catalyst_type, summary, sentiment, confidence)
    rather than calling any news/LLM service. There is no network use.
    """

    name = "Catalyst"

    def __init__(self, fixture_path: Path | str = DEFAULT_CATALYST_FIXTURE) -> None:
        self.fixture_path = Path(fixture_path)

    async def run(
        self, context: SessionContext, candidates: list[Candidate] | None = None
    ) -> list[CatalystSummary]:
        """Return catalyst annotations for the given candidates (or all fixtures)."""
        fixtures = load_catalyst_fixtures(self.fixture_path)
        if candidates is None:
            return list(fixtures.values())

        catalysts = []
        for candidate in candidates:
            match = fixtures.get(candidate.ticker.upper())
            if match:
                catalysts.append(match)
            else:
                catalysts.append(
                    CatalystSummary(
                        ticker=candidate.ticker,
                        catalyst_type="technical",
                        summary="No structured catalyst fixture available",
                        sentiment="neutral",
                        confidence=0.3,
                    )
                )
        return catalysts
