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

Within a single simulated day, plans are risk-checked and simulated one at
a time (not as a single batch decision followed by a batch of fills): each
plan's risk check sees `portfolio.realized_pnl_today` as of the trades
already closed earlier *that same day*, so the daily-loss cap can actually
engage mid-day once enough losses have been realized. `realized_pnl_today`
still resets to zero at the start of each new simulated day, which is the
correct boundary for a *daily* cap.
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
from .positions import PositionBook

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
        if self.backtest_config.overlapping_positions:
            return await self._run_overlapping_async(symbols, start_date, end_date, phase)
        return await self._run_resolve_on_open_async(symbols, start_date, end_date, phase)

    def _load_data(self, symbols: list[str] | None) -> dict[str, pd.DataFrame]:
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
        return data

    def _compute_date_range(
        self, data: dict[str, pd.DataFrame], start_date: str | None, end_date: str | None
    ) -> list[pd.Timestamp]:
        all_dates = sorted(set().union(*[set(df["date"]) for df in data.values()]))
        if start_date:
            all_dates = [d for d in all_dates if d >= pd.Timestamp(start_date)]
        if end_date:
            all_dates = [d for d in all_dates if d <= pd.Timestamp(end_date)]
        return all_dates

    def _build_policy(self) -> ExecutionPolicy:
        return ExecutionPolicy(
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

    def _bars_on(self, data: dict[str, pd.DataFrame], as_of: pd.Timestamp) -> dict[str, Bar]:
        """Return each symbol's bar exactly on `as_of` (if it has one)."""
        bars: dict[str, Bar] = {}
        for symbol, df in data.items():
            row = df[df["date"] == as_of]
            if row.empty:
                continue
            r = row.iloc[0]
            bars[symbol] = Bar(
                date=str(r.date.date()),
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
            )
        return bars

    async def _run_resolve_on_open_async(
        self,
        symbols: list[str] | None,
        start_date: str | None,
        end_date: str | None,
        phase: Phase,
    ) -> BacktestResult:
        data = self._load_data(symbols)
        all_dates = self._compute_date_range(data, start_date, end_date)

        starting_cash = Decimal(str(self.backtest_config.starting_cash))
        portfolio = Portfolio(
            account_value=starting_cash, cash=starting_cash, buying_power=starting_cash
        )
        policy = self._build_policy()

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

            # Risk-check and simulate one plan at a time (not batch-decide then
            # batch-simulate): this lets each plan's risk check see the P&L of
            # trades already closed earlier the same day, so the daily-loss cap
            # can actually stop later same-day plans once it's been hit.
            day_decisions = []
            for plan in plans:
                decision = (await self.risk_agent.run(ctx, [plan]))[0]
                day_decisions.append(decision)
                if not decision.approved:
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
            all_decisions.extend(day_decisions)
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

    async def _run_overlapping_async(
        self,
        symbols: list[str] | None,
        start_date: str | None,
        end_date: str | None,
        phase: Phase,
    ) -> BacktestResult:
        """Event-driven replay allowing multiple concurrent positions per
        symbol and across symbols over multiple days. See
        `docs/backtesting.md` for the accounting model (cash reserved at
        fill, mark-to-market equity, flatten-at-end-of-range).
        """
        data = self._load_data(symbols)
        all_dates = self._compute_date_range(data, start_date, end_date)

        starting_cash = Decimal(str(self.backtest_config.starting_cash))
        portfolio = Portfolio(
            account_value=starting_cash, cash=starting_cash, buying_power=starting_cash
        )
        policy = self._build_policy()

        profile = PhaseRouter.get_profile(phase)
        aggressiveness = self.scanner_config.phase_aggressiveness.get(
            phase.value, profile.scan_aggressiveness
        )
        catalyst_fixtures = load_catalyst_fixtures(self.catalyst_fixture)

        book = PositionBook(self.simulator, self.backtest_config.max_holding_days)
        all_plans: list[TradePlan] = []
        all_decisions = []
        all_trades = []
        equity_curve: list[dict] = []

        for as_of in all_dates:
            portfolio.realized_pnl_today = Decimal("0")
            bars_today = self._bars_on(data, as_of)
            closes_today = {symbol: bar.close for symbol, bar in bars_today.items()}

            filled, closed = book.advance(as_of, bars_today)
            for position in filled:
                portfolio.cash -= position.trade.entry_price * position.trade.quantity
            for position in closed:
                self._settle_close(portfolio, position.plan, position.trade)
                all_trades.append(position.trade)

            portfolio.account_value = portfolio.cash + book.market_value(closes_today)

            capacity = max(0, profile.max_position_count - book.open_count())
            candidates = self._scan(data, as_of) if capacity > 0 else []
            candidates = rank_candidates(candidates, self.scanner_config, aggressiveness)
            plans = self._draft_plans(
                candidates, catalyst_fixtures, data, as_of, profile, portfolio, limit=capacity
            )

            ctx = SessionContext(
                phase=phase,
                mode=OperatingMode.BACKTEST,
                execution_policy=policy,
                portfolio=portfolio,
            )
            day_decisions = []
            for plan in plans:
                decision = (await self.risk_agent.run(ctx, [plan]))[0]
                day_decisions.append(decision)
                if decision.approved:
                    book.queue_entry(plan, as_of)

            all_plans.extend(plans)
            all_decisions.extend(day_decisions)
            equity_curve.append(
                {"date": str(as_of.date()), "equity": float(portfolio.account_value)}
            )

        last_bars = self._bars_on(data, all_dates[-1]) if all_dates else {}
        for position in book.flatten_all(last_bars):
            self._settle_close(portfolio, position.plan, position.trade)
            all_trades.append(position.trade)
        for position in book.open_positions:
            # No bar at all for this symbol on the final requested date (not
            # expected with the committed fixtures, which share one
            # calendar) - keep the trade visible in artifacts as still-open
            # rather than silently dropping it.
            all_trades.append(position.trade)
        for plan, trade in book.expire_pending():
            all_trades.append(trade)
            risk_amount = plan.get_risk_amount(portfolio.account_value)
            portfolio.open_risk_amount = max(Decimal("0"), portfolio.open_risk_amount - risk_amount)

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

    def _settle_close(self, portfolio: Portfolio, plan: TradePlan, trade) -> None:
        """Release reserved cash, realize P&L, and free open-risk for a closed position."""
        if trade.pnl is None:
            return
        portfolio.cash += trade.entry_price * trade.quantity + trade.pnl
        portfolio.realized_pnl_today += trade.pnl
        risk_amount = plan.get_risk_amount(portfolio.account_value)
        portfolio.open_risk_amount = max(Decimal("0"), portfolio.open_risk_amount - risk_amount)

    def _scan(
        self,
        data: dict[str, pd.DataFrame],
        as_of: pd.Timestamp,
        blocked_until: dict[str, pd.Timestamp] | None = None,
    ) -> list[Candidate]:
        blocked_until = blocked_until or {}
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
        limit: int | None = None,
    ) -> list[TradePlan]:
        cap = profile.max_position_count if limit is None else limit
        if cap <= 0:
            return []

        plans: list[TradePlan] = []
        for candidate in candidates:
            if len(plans) >= cap:
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
