"""Strategy agent - deterministic, inspectable trade plan generation."""

import math
from decimal import Decimal
from pathlib import Path

import pandas as pd

from powerhouse.config import StrategyConfig
from powerhouse.core.enums import OrderSide
from powerhouse.core.models import Candidate, CatalystSummary, SessionContext, TradePlan
from powerhouse.core.phase_router import PhaseRouter
from powerhouse.data import load_ohlcv

from .base import BaseAgent

DEFAULT_CURATED_DIR = Path("data/curated")


def atr_estimate_from_df(df: pd.DataFrame, lookback: int = 14) -> float | None:
    """Pure average-true-range-style volatility estimate (mean daily range).

    Shared by the live StrategyAgent (full history) and the backtest engine
    (history sliced up to the simulated "as of" date).
    """
    if df.empty:
        return None
    window = df.tail(lookback)
    ranges = (window["high"] - window["low"]).abs()
    if ranges.empty:
        return None
    return float(ranges.mean())


def size_quantity(account_value: Decimal, risk_pct: float, risk_per_share: float) -> int:
    """Deterministic position sizing from a risk budget and per-share risk."""
    if risk_per_share <= 0:
        return 0
    risk_amount = float(account_value) * (risk_pct / 100.0)
    return max(0, math.floor(risk_amount / risk_per_share))


class StrategyAgent(BaseAgent[list[TradePlan]]):
    """Builds explicit, inspectable trade plans from candidates + catalysts.

    Every field on the resulting TradePlan is derived from an auditable
    calculation: entry from the last close, stop/target from a simple
    average-true-range-style volatility estimate, quantity from the
    configured per-trade risk budget, and confidence from a blend of the
    scanner's momentum score and the catalyst's sentiment confidence.
    No black-box models are involved.
    """

    name = "Strategy"

    def __init__(
        self,
        config: StrategyConfig | None = None,
        curated_dir: Path | str = DEFAULT_CURATED_DIR,
    ) -> None:
        self.config = config or StrategyConfig()
        self.curated_dir = Path(curated_dir)

    def _atr_estimate(self, symbol: str, lookback: int = 14) -> float | None:
        try:
            df = load_ohlcv(symbol, self.curated_dir)
        except Exception:
            return None
        return atr_estimate_from_df(df, lookback)

    async def run(
        self,
        context: SessionContext,
        candidates: list[Candidate] | None = None,
        catalysts: list[CatalystSummary] | None = None,
    ) -> list[TradePlan]:
        """Draft trade plans for the given candidates, capped by phase profile."""
        candidates = candidates or []
        catalysts = catalysts or []
        catalyst_by_ticker = {c.ticker.upper(): c for c in catalysts}

        profile = PhaseRouter.get_profile(context.phase)
        if profile.max_position_count == 0:
            return []

        plans: list[TradePlan] = []
        for candidate in candidates:
            if len(plans) >= profile.max_position_count:
                break

            catalyst = catalyst_by_ticker.get(candidate.ticker.upper())
            catalyst_confidence = catalyst.confidence if catalyst else 0.4
            sentiment = catalyst.sentiment if catalyst else "neutral"
            if sentiment == "bearish":
                # Phase 1/2 policy: no shorting, so skip bearish-only setups.
                continue

            atr = self._atr_estimate(candidate.ticker)
            if not atr or atr <= 0:
                atr = float(candidate.price) * 0.01  # 1% fallback volatility

            entry_price = candidate.price
            stop_distance = atr * self.config.stop_atr_multiple
            target_distance = atr * self.config.target_atr_multiple
            stop_price = Decimal(str(round(float(entry_price) - stop_distance, 4)))
            target_price = Decimal(str(round(float(entry_price) + target_distance, 4)))

            confidence = round((candidate.relevance_score + catalyst_confidence) / 2, 4)
            if confidence < self.config.min_confidence:
                continue

            risk_pct = self.config.default_risk_per_trade_pct * profile.risk_multiplier
            quantity = size_quantity(context.portfolio.account_value, risk_pct, stop_distance)
            if quantity < 1:
                continue

            trailing_stop_pct = None
            if self.config.enable_trailing_stop:
                trailing_stop_pct = round(
                    (atr * self.config.trailing_stop_atr_multiple) / float(entry_price) * 100, 4
                )

            rationale = (
                f"{candidate.reason}; catalyst[{sentiment}]: "
                f"{catalyst.summary if catalyst else 'no catalyst fixture'}"
            )

            plans.append(
                TradePlan(
                    ticker=candidate.ticker,
                    side=OrderSide.BUY,
                    entry_price=entry_price,
                    stop_loss_price=stop_price,
                    target_price=target_price,
                    quantity=quantity,
                    rationale=rationale,
                    risk_per_trade_pct=risk_pct,
                    confidence=confidence,
                    trailing_stop_pct=trailing_stop_pct,
                )
            )

        return plans
