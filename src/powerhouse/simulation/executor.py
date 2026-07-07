"""Simulated trade execution: pending entry -> fill -> stop/target/trailing -> close.

No broker calls are made anywhere in this module. Fills, slippage, and exits
are all computed locally from historical or fixture OHLCV bars.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from powerhouse.core.enums import OrderSide
from powerhouse.core.models import ExecutedTrade, TradeEvent, TradeEventType, TradePlan


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar used as simulator input."""

    date: str
    open: float
    high: float
    low: float
    close: float


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_bar_date(bar_date: str) -> datetime:
    """Parse a bar's date string into a UTC midnight datetime.

    Used to stamp trade fill/exit timestamps with the *simulated* calendar
    date rather than wall-clock time, so backtest artifacts (e.g. a trade
    timeline on an external dashboard) reflect when a trade actually
    happened in the replay, not when the backtest process was run. Falls
    back to wall-clock time for non-ISO placeholder dates (e.g. in tests
    that use bars like `Bar(date="d0", ...)`).
    """
    try:
        return datetime.strptime(bar_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return _now()


class TradeSimulator:
    """Simulates the lifecycle of a single trade plan against a bar series.

    Fill assumption: an approved plan fills at the *next* bar's open price
    (adjusted for slippage), representing a market-on-next-bar-open fill.
    After the fill, each subsequent bar is checked for a stop-loss touch,
    a target touch, and (if configured) a trailing-stop update, in that
    order of precedence within the bar.
    """

    def __init__(
        self,
        slippage_bps: float = 5.0,
        commission_per_share: float = 0.0,
        max_holding_days: int = 5,
    ) -> None:
        self.slippage_bps = slippage_bps
        self.commission_per_share = commission_per_share
        self.max_holding_days = max_holding_days

    def _slip(self, price: float, side: OrderSide) -> Decimal:
        factor = self.slippage_bps / 10_000.0
        # Slippage always works against the trader: buys fill higher, sells fill lower.
        adjusted = price * (1 + factor) if side == OrderSide.BUY else price * (1 - factor)
        return Decimal(str(round(adjusted, 4)))

    def open_pending(self, plan: TradePlan) -> ExecutedTrade:
        """Create a trade in the 'pending entry' state (no fill data available yet)."""
        trade = ExecutedTrade(
            plan_id=plan.plan_id,
            ticker=plan.ticker,
            side=plan.side,
            entry_price=plan.entry_price,
            quantity=plan.quantity,
            entry_timestamp=_now(),
            stop_loss_price=plan.stop_loss_price,
            target_price=plan.target_price,
            outcome="pending",
        )
        trade.events.append(
            TradeEvent(
                trade_id=trade.trade_id,
                plan_id=plan.plan_id,
                ticker=plan.ticker,
                event_type=TradeEventType.PENDING_ENTRY,
                price=plan.entry_price,
                quantity=plan.quantity,
            )
        )
        return trade

    def mark_no_fill(self, trade: ExecutedTrade) -> None:
        """Record `trade` as unfillable (no forward market data available)."""
        trade.outcome = "no_fill"
        trade.events.append(
            TradeEvent(
                trade_id=trade.trade_id,
                plan_id=trade.plan_id,
                ticker=trade.ticker,
                event_type=TradeEventType.NO_FILL,
                details={"reason": "No forward market data available to simulate a fill"},
            )
        )

    def fill(self, trade: ExecutedTrade, plan: TradePlan, bar: Bar) -> None:
        """Fill `trade` at `bar`'s open (adjusted for slippage), in place."""
        fill_price = self._slip(bar.open, plan.side)
        trade.entry_price = fill_price
        trade.entry_timestamp = _parse_bar_date(bar.date)
        trade.outcome = "filled"
        trade.events.append(
            TradeEvent(
                trade_id=trade.trade_id,
                plan_id=plan.plan_id,
                ticker=plan.ticker,
                event_type=TradeEventType.FILLED,
                price=fill_price,
                quantity=plan.quantity,
                details={"bar_date": bar.date},
            )
        )

    def step(
        self,
        trade: ExecutedTrade,
        plan: TradePlan,
        bar: Bar,
        trailing_stop_price: Optional[Decimal],
    ) -> Optional[Decimal]:
        """Advance an already-filled, still-open `trade` by one forward bar.

        Checks stop-loss before target (matching a bar's plausible intrabar
        path), then ratchets the trailing stop (if configured) upward. Sets
        `trade.closed=True` as a side effect if this bar closes the trade.
        Returns the (possibly updated) trailing-stop price for the caller to
        carry into the next call.
        """
        effective_stop = (
            trailing_stop_price if trailing_stop_price is not None else plan.stop_loss_price
        )

        if bar.low <= float(effective_stop):
            exit_price = Decimal(str(min(bar.open, float(effective_stop))))
            self._close(trade, exit_price, bar.date, TradeEventType.STOP_HIT)
            return trailing_stop_price

        if bar.high >= float(plan.target_price):
            exit_price = Decimal(str(max(bar.open, float(plan.target_price))))
            self._close(trade, exit_price, bar.date, TradeEventType.TARGET_HIT)
            return trailing_stop_price

        if plan.trailing_stop_pct:
            candidate = Decimal(str(round(bar.close * (1 - plan.trailing_stop_pct / 100), 4)))
            if trailing_stop_price is None or candidate > trailing_stop_price:
                trailing_stop_price = candidate
                trade.trailing_stop_price = trailing_stop_price
                trade.events.append(
                    TradeEvent(
                        trade_id=trade.trade_id,
                        plan_id=plan.plan_id,
                        ticker=plan.ticker,
                        event_type=TradeEventType.TRAILING_STOP_UPDATED,
                        price=trailing_stop_price,
                        details={"bar_date": bar.date},
                    )
                )

        return trailing_stop_price

    def close_manual(self, trade: ExecutedTrade, bar: Bar) -> None:
        """Force-close `trade` at `bar`'s close (time-based / end-of-range exit)."""
        self._close(trade, Decimal(str(bar.close)), bar.date, TradeEventType.MANUAL_CLOSE)

    def run(self, plan: TradePlan, bars: list[Bar]) -> ExecutedTrade:
        """Run the full simulated lifecycle of a plan against forward bars.

        If `bars` is empty (no forward market data available, e.g. a live
        single-session run with no historical replay context) the trade is
        returned as a no-fill / manual outcome, since there is nothing to
        simulate a fill against.
        """
        trade = self.open_pending(plan)

        if not bars:
            self.mark_no_fill(trade)
            return trade

        self.fill(trade, plan, bars[0])

        trailing_stop_price: Optional[Decimal] = None
        for i, bar in enumerate(bars[1:], start=1):
            if i > self.max_holding_days:
                break
            trailing_stop_price = self.step(trade, plan, bar, trailing_stop_price)
            if trade.closed:
                return trade

        # Time-based exit: still open after max_holding_days / available bars.
        last_bar = bars[min(len(bars) - 1, self.max_holding_days)]
        self.close_manual(trade, last_bar)
        return trade

    def _close(
        self, trade: ExecutedTrade, exit_price: Decimal, bar_date: str, event_type: TradeEventType
    ) -> None:
        outcome_map = {
            TradeEventType.STOP_HIT: "stop_hit",
            TradeEventType.TARGET_HIT: "target_hit",
            TradeEventType.MANUAL_CLOSE: "manual_close",
        }
        trade.closed = True
        trade.exit_price = exit_price
        trade.exit_timestamp = _parse_bar_date(bar_date)
        trade.outcome = outcome_map[event_type]
        gross = (exit_price - trade.entry_price) * trade.quantity
        commission = Decimal(str(self.commission_per_share)) * trade.quantity * 2
        trade.pnl = gross - commission
        trade.events.append(
            TradeEvent(
                trade_id=trade.trade_id,
                plan_id=trade.plan_id,
                ticker=trade.ticker,
                event_type=event_type,
                price=exit_price,
                quantity=trade.quantity,
                details={"bar_date": bar_date},
            )
        )
