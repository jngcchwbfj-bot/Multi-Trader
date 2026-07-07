"""Scanner agent - deterministic candidate ranking from local OHLCV data."""

from decimal import Decimal
from pathlib import Path

import pandas as pd

from powerhouse.config import ScannerConfig
from powerhouse.core.models import Candidate, SessionContext
from powerhouse.core.phase_router import PhaseRouter
from powerhouse.data import available_symbols, load_ohlcv

from .base import BaseAgent

DEFAULT_CURATED_DIR = Path("data/curated")


def momentum_score_from_df(
    df: pd.DataFrame, lookback_days: int
) -> tuple[float, Decimal, str] | None:
    """Pure momentum scoring over a dataframe's *last* row (no look-ahead).

    Shared by the live ScannerAgent (full history) and the backtest engine
    (history sliced up to the simulated "as of" date), so ranking logic is
    identical in both contexts.
    """
    if df.empty:
        return None
    lookback = min(lookback_days, len(df) - 1)
    if lookback < 1:
        return None
    last_close = float(df.iloc[-1]["close"])
    past_close = float(df.iloc[-1 - lookback]["close"])
    if past_close == 0:
        return None
    pct_change = (last_close - past_close) / past_close
    # Squash into a 0..1 relevance-style score for a +/-10% swing.
    score = max(0.0, min(1.0, 0.5 + pct_change * 5))
    return score, Decimal(str(last_close)), f"{pct_change:+.2%} over {lookback}d"


def rank_candidates(
    scored: list[Candidate], config: ScannerConfig, aggressiveness: float
) -> list[Candidate]:
    """Apply phase-aggressiveness score floor and candidate-count cap."""
    scored = sorted(scored, key=lambda c: c.relevance_score, reverse=True)
    min_score = max(config.min_relevance_score, 0.5 - aggressiveness * 0.5)
    filtered = [c for c in scored if c.relevance_score >= min_score]
    max_candidates = max(1, round(config.max_candidates * (0.4 + aggressiveness)))
    return filtered[:max_candidates]


class ScannerAgent(BaseAgent[list[Candidate]]):
    """Ranks candidate tickers deterministically from local historical data.

    Ranking is a simple momentum score: the % price change over the
    configured lookback window. No ML, no external data - just arithmetic
    over local Parquet bars. Phase aggressiveness (from ScannerConfig)
    controls how many candidates are surfaced and how low a score is
    still admissible.
    """

    name = "Scanner"

    def __init__(
        self,
        config: ScannerConfig | None = None,
        curated_dir: Path | str = DEFAULT_CURATED_DIR,
    ) -> None:
        self.config = config or ScannerConfig()
        self.curated_dir = Path(curated_dir)

    def _score_symbol(self, symbol: str) -> tuple[float, Decimal, str] | None:
        try:
            df = load_ohlcv(symbol, self.curated_dir)
        except Exception:
            return None
        return momentum_score_from_df(df, self.config.momentum_lookback_days)

    async def run(self, context: SessionContext) -> list[Candidate]:
        """Rank the configured universe by local-data momentum.

        Falls back to an empty list (not mocked data) when no curated
        data is available for a symbol - callers should run
        `ingest-fixtures` first.
        """
        profile = PhaseRouter.get_profile(context.phase)
        aggressiveness = self.config.phase_aggressiveness.get(
            context.phase.value, profile.scan_aggressiveness
        )

        universe = self.config.universe or available_symbols(self.curated_dir)
        scored: list[Candidate] = []
        for symbol in universe:
            result = self._score_symbol(symbol)
            if result is None:
                continue
            score, price, reason = result
            if price < Decimal(str(self.config.min_price)):
                continue
            scored.append(
                Candidate(
                    ticker=symbol,
                    price=price,
                    relevance_score=round(score, 4),
                    reason=f"Momentum {reason} (phase={context.phase.value})",
                )
            )

        return rank_candidates(scored, self.config, aggressiveness)
