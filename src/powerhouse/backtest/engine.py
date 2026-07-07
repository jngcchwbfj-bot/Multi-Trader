"""Historical replay / simulation backtest engine.

This is a real (if intentionally simple) event-driven backtest: for each
trading day in the requested range it re-runs the scanner -> catalyst ->
strategy -> risk -> execution pipeline using only data available *as of*
that day (no look-ahead), then simulates each approved plan forward
against subsequent bars via `TradeSimulator`.

Simplifying assumption (documented, not hidden): a trade opened on day D
is resolved to completion (fill -> stop/target/trailing/time exit) using
all bars from D+1 onward, and its P&L is realized on day D for daily-loss
and equity-curve accounting. There is no intraday, partial-day, or
overlapping-position-in-the-same-symbol modeling. See docs/backtesting.md
for the full list of limitations.
"""

import asyncio
from decimal import Decimal
from pathlib import Path

import pandas as pd

from powerhouse.agents.catalyst import load_catalyst_fixtures
from powerhouse.agents.risk import RiskAgent
from powerhouse.agents.scanner import momentum_score_from_df, rank_candidates
from powerhouse.agents.strategy import atr_estimate_from_df, size_quantity
from powerhouse.config import BacktestConfig, RiskConfig, ScannerConfig, StrategyConfig
from powerhouse.core.enums import OperatingMode, OrderSide, Phase
from powerhouse.core.exceptions import ConfigError
from powerhouse.core.models import (
    BacktestResult,
    Candidate,
    ExecutionPolicy,
    Portfolio,
    SessionContext,
    TradePlan,
)
from powerhouse.core.phase_router import PhaseRouter
from powerhouse.data import available_symbols, load_ohlcv
from powerhouse.simulation.executor import Bar, TradeSimulator

from .metrics import compute_metrics

DEFAULT_CURATED_DIR = Path("data/curated")
DEFAULT_CATALYST_FIXTURE = Path("data/raw/catalysts.csv")


class BacktestEngine:
    """Runs a deterministic, local-data-only historical replay."""

    def __init__(
        self,
        curated_dir: Path | str = DEFAULT_CURATED_DIR,
        catalyst_fixture: Path | str = DEFAULT_CATALYST_FIXTURE,
        scanner_config: ScannerConfig | None = None,
        strategy_config: StrategyConfig | None = None,
        risk_config: RiskConfig | None = None,
        backtest_config: BacktestConfig | None = None,
    ) -> None:
        self.curated_dir = Path(curated_dir)
        self.catalyst_fixture = Path(catalyst_fixture)
        self.scanner_config = scanner_config or ScannerConfig()
        self.strategy_config = strategy_config or StrategyConfig()
        self.risk_config = risk_config or RiskConfig()
        self.backtest_config = backtest_config or BacktestConfig()
        self.simulator = TradeSimulator(
            slippage_bps=self.backtest_config.slippage_bps,
            commission_per_share=self.backtest_config.commission_per_share,
            max_holding_days=self.backtest_config.max_holding_days,
        )
        self.risk_agent = RiskAgent()

    def run(
        self,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        phase: Phase = Phase.OPEN,
    ) -> BacktestResult:
        """Synchronous entry point (wraps the async pipeline internally)."""
        return asyncio.run(self.run_async(symbols, start_date, end_date, phase))

    async def run_async(
        self,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        phase: Phase = Phase.OPEN,
    ) -> BacktestResult:
        symbols = symbols or self.scanner_config.universe or available_symbols(self.curated_dir)
        data = {}
        for s in symbols:
            try:
                df = load_ohlcv(s, self.curated_dir)
            except ConfigError:
                continue
            if not df.empty:
                data[s] = df
        if not data:
            raise ConfigError(
                f"No curated data found for symbols {symbols} in {self.curated_dir}. "
                "Run `powerhouse ingest-fixtures` first."
            )

        all_dates = sorted(set().union(*[set(df["date"]) for df in data.values()]))
        if start_date:
            all_dates = [d for d in all_dates if d >= pd.Timestamp(start_date)]
        if end_date:
            all_dates = [d for d in all_dates if d <= pd.Timestamp(end_date)]

        starting_cash = Decimal(str(self.backtest_config.starting_cash))
        portfolio = Portfolio(
            account_value=starting_cash, cash=starting_cash, buying_power=starting_cash
        )
        policy = ExecutionPolicy(
            allow_execution=True,
            mode=OperatingMode.BACKTEST,
            max_daily_loss_pct=self.risk_config.max_daily_loss_pct,
            max_per_trade_risk_pct=self.risk_config.max_per_trade_risk_pct,
            max_total_open_risk_pct=self.risk_config.max_total_open_risk_pct,
            max_long_exposure_pct=self.risk_config.max_long_exposure_pct,
            min_cash_reserve_pct=self.risk_config.min_cash_reserve_pct,
            allow_market_orders=self.risk_config.allow_market_orders,
            require_approval_per_trade=self.risk_config.require_approval_per_trade,
        )

        profile = PhaseRouter.get_profile(phase)
        aggressiveness = self.scanner_config.phase_aggressiveness.get(
            phase.value, profile.scan_aggressiveness
        )
        catalyst_fixtures = load_catalyst_fixtures(self.catalyst_fixture)

        all_plans: list[TradePlan] = []
        all_decisions = []
        all_trades = []
        equity_curve: list[dict] = []
        blocked_until: dict[str, pd.Timestamp] = {}

        for as_of in all_dates:
            portfolio.realized_pnl_today = Decimal("0")

            candidates = self._scan(data, as_of, blocked_until)
            candidates = rank_candidates(candidates, self.scanner_config, aggressiveness)
            plans = self._draft_plans(
                candidates, catalyst_fixtures, data, as_of, profile, portfolio
            )

            ctx = SessionContext(
                phase=phase,
                mode=OperatingMode.BACKTEST,
                execution_policy=policy,
                portfolio=portfolio,
            )
            decisions = await self.risk_agent.run(ctx, plans)
            approved_ids = {d.plan_id for d in decisions if d.approved}

            for plan in plans:
                if plan.plan_id not in approved_ids:
                    continue
                bars = self._forward_bars(data[plan.ticker], as_of)
                trade = self.simulator.run(plan, bars)
                all_trades.append(trade)
                if trade.closed and trade.pnl is not None:
                    portfolio.realized_pnl_today += trade.pnl
                    portfolio.cash += trade.pnl
                    portfolio.account_value = portfolio.cash
                    risk_amount = plan.get_risk_amount(portfolio.account_value)
                    portfolio.open_risk_amount = max(
                        Decimal("0"), portfolio.open_risk_amount - risk_amount
                    )
                    blocked_until[plan.ticker] = as_of  # resolved same step; symbol free next day

            all_plans.extend(plans)
            all_decisions.extend(decisions)
            equity_curve.append(
                {"date": str(as_of.date()), "equity": float(portfolio.account_value)}
            )

        metrics = compute_metrics(all_trades, starting_cash, equity_curve)

        return BacktestResult(
            symbols=list(data.keys()),
            start_date=str(all_dates[0].date()) if all_dates else "",
            end_date=str(all_dates[-1].date()) if all_dates else "",
            trade_plans=all_plans,
            risk_decisions=all_decisions,
            executed_trades=all_trades,
            metrics=metrics,
            equity_curve=equity_curve,
        )

    def _scan(
        self,
        data: dict[str, pd.DataFrame],
        as_of: pd.Timestamp,
        blocked_until: dict[str, pd.Timestamp],
    ) -> list[Candidate]:
        candidates = []
        for symbol, df in data.items():
            if symbol in blocked_until and blocked_until[symbol] >= as_of:
                continue
            df_upto = df[df["date"] <= as_of]
            result = momentum_score_from_df(df_upto, self.scanner_config.momentum_lookback_days)
            if result is None:
                continue
            score, price, reason = result
            if price < Decimal(str(self.scanner_config.min_price)):
                continue
            candidates.append(
                Candidate(
                    ticker=symbol,
                    price=price,
                    relevance_score=round(score, 4),
                    reason=f"Momentum {reason} (as of {as_of.date()})",
                )
            )
        return candidates

    def _draft_plans(
        self,
        candidates: list[Candidate],
        catalyst_fixtures: dict,
        data: dict[str, pd.DataFrame],
        as_of: pd.Timestamp,
        profile,
        portfolio: Portfolio,
    ) -> list[TradePlan]:
        if profile.max_position_count == 0:
            return []

        plans: list[TradePlan] = []
        for candidate in candidates:
            if len(plans) >= profile.max_position_count:
                break
            catalyst = catalyst_fixtures.get(candidate.ticker.upper())
            catalyst_confidence = catalyst.confidence if catalyst else 0.4
            sentiment = catalyst.sentiment if catalyst else "neutral"
            if sentiment == "bearish":
                continue

            df_upto = data[candidate.ticker]
            df_upto = df_upto[df_upto["date"] <= as_of]
            atr = atr_estimate_from_df(df_upto) or float(candidate.price) * 0.01

            entry_price = candidate.price
            stop_distance = atr * self.strategy_config.stop_atr_multiple
            target_distance = atr * self.strategy_config.target_atr_multiple
            stop_price = Decimal(str(round(float(entry_price) - stop_distance, 4)))
            target_price = Decimal(str(round(float(entry_price) + target_distance, 4)))

            confidence = round((candidate.relevance_score + catalyst_confidence) / 2, 4)
            if confidence < self.strategy_config.min_confidence:
                continue

            risk_pct = self.strategy_config.default_risk_per_trade_pct * profile.risk_multiplier
            quantity = size_quantity(portfolio.account_value, risk_pct, stop_distance)
            if quantity < 1:
                continue

            trailing_stop_pct = None
            if self.strategy_config.enable_trailing_stop:
                trailing_stop_pct = round(
                    (atr * self.strategy_config.trailing_stop_atr_multiple)
                    / float(entry_price)
                    * 100,
                    4,
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

    def _forward_bars(self, df: pd.DataFrame, as_of: pd.Timestamp) -> list[Bar]:
        forward = df[df["date"] > as_of].head(self.backtest_config.max_holding_days + 3)
        return [
            Bar(
                date=str(row.date.date()),
                open=float(row.open),
                high=float(row.high),
                low=float(row.low),
                close=float(row.close),
            )
            for row in forward.itertuples()
        ]
