"""In-memory book of overlapping open positions for the event-driven backtest engine.

Kept separate from `BacktestEngine` so the day-by-day fill/close/mark-to-market
mechanics can be unit-tested directly against synthetic bars, without
depending on the scanner/strategy/risk pipeline or fixture data.

Unlike the Phase 2 "resolve on open" engine (which fully simulates a trade's
fill-through-exit lifecycle the instant a plan is approved, and blocks a
symbol from being re-scanned until its one open trade resolves),
`PositionBook` lets any number of positions - including several on the same
symbol - stay open across multiple simulated days at once. A newly-approved
plan is queued and fills at the next available bar (matching the
`fill_on: next_open` assumption used elsewhere), then advances one bar at a
time until it hits its stop, target, or the configured `max_holding_days`.
"""

from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from powerhouse.core.models import ExecutedTrade, TradePlan
from powerhouse.simulation.executor import Bar, TradeSimulator


@dataclass
class OpenPosition:
    """A filled, still-open simulated trade tracked by `PositionBook`."""

    trade: ExecutedTrade
    plan: TradePlan
    entry_date: pd.Timestamp
    trailing_stop_price: Decimal | None = None
    days_held: int = 0


@dataclass
class _PendingEntry:
    plan: TradePlan
    drafted_date: pd.Timestamp


@dataclass
class PositionBook:
    """Tracks pending entries and open positions across symbols and days."""

    simulator: TradeSimulator
    max_holding_days: int
    pending: list[_PendingEntry] = field(default_factory=list)
    open_positions: list[OpenPosition] = field(default_factory=list)

    def queue_entry(self, plan: TradePlan, as_of: pd.Timestamp) -> None:
        """Queue an approved plan to fill at the next bar with data."""
        self.pending.append(_PendingEntry(plan=plan, drafted_date=as_of))

    def open_count(self) -> int:
        """Currently open positions plus not-yet-filled pending entries."""
        return len(self.open_positions) + len(self.pending)

    def advance(
        self, as_of: pd.Timestamp, bars_today: dict[str, Bar]
    ) -> tuple[list[OpenPosition], list[OpenPosition]]:
        """Advance the book by one simulated day.

        Fills any pending entries whose symbol has a bar today, then checks
        every already-open position (opened on a *prior* day) against
        today's bar for a stop/target/trailing-stop touch or a
        max-holding-days time exit. Positions filled today are not
        evaluated against today's bar (matching `TradeSimulator.run`, which
        never checks the fill bar itself for an exit).

        Returns `(newly_filled, newly_closed)`.
        """
        newly_filled: list[OpenPosition] = []
        still_pending: list[_PendingEntry] = []
        for entry in self.pending:
            bar = bars_today.get(entry.plan.ticker)
            if bar is None:
                still_pending.append(entry)
                continue
            trade = self.simulator.open_pending(entry.plan)
            self.simulator.fill(trade, entry.plan, bar)
            position = OpenPosition(trade=trade, plan=entry.plan, entry_date=as_of)
            self.open_positions.append(position)
            newly_filled.append(position)
        self.pending = still_pending

        newly_closed: list[OpenPosition] = []
        still_open: list[OpenPosition] = []
        for position in self.open_positions:
            if position.entry_date == as_of:
                still_open.append(position)
                continue
            bar = bars_today.get(position.plan.ticker)
            if bar is None:
                still_open.append(position)
                continue
            position.days_held += 1
            if position.days_held > self.max_holding_days:
                self.simulator.close_manual(position.trade, bar)
            else:
                position.trailing_stop_price = self.simulator.step(
                    position.trade, position.plan, bar, position.trailing_stop_price
                )
            if position.trade.closed:
                newly_closed.append(position)
            else:
                still_open.append(position)
        self.open_positions = still_open

        return newly_filled, newly_closed

    def market_value(self, closes_today: dict[str, float]) -> Decimal:
        """Mark-to-market value of all currently open positions."""
        total = Decimal("0")
        for position in self.open_positions:
            price = closes_today.get(position.plan.ticker)
            if price is None:
                continue
            total += Decimal(str(price)) * position.plan.quantity
        return total

    def flatten_all(self, last_bars: dict[str, Bar]) -> list[OpenPosition]:
        """Force-close every remaining open position at the given final bars.

        Called once at the end of the requested backtest date range so no
        position is left open indefinitely. A position whose symbol has no
        bar at all in `last_bars` (not expected with the committed fixtures,
        which share one calendar) is left open and excluded from the result.
        """
        closed: list[OpenPosition] = []
        remaining: list[OpenPosition] = []
        for position in self.open_positions:
            bar = last_bars.get(position.plan.ticker)
            if bar is None:
                remaining.append(position)
                continue
            self.simulator.close_manual(position.trade, bar)
            closed.append(position)
        self.open_positions = remaining
        return closed

    def expire_pending(self) -> list[tuple[TradePlan, ExecutedTrade]]:
        """Mark any never-filled pending entries as `no_fill` at backtest end."""
        expired: list[tuple[TradePlan, ExecutedTrade]] = []
        for entry in self.pending:
            trade = self.simulator.open_pending(entry.plan)
            self.simulator.mark_no_fill(trade)
            expired.append((entry.plan, trade))
        self.pending = []
        return expired
