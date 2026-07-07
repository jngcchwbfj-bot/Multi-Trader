"""Compute summary performance metrics from a list of simulated trades."""

from decimal import Decimal

from powerhouse.core.models import BacktestMetrics, ExecutedTrade


def compute_metrics(
    trades: list[ExecutedTrade],
    starting_account_value: Decimal,
    equity_curve: list[dict] | None = None,
) -> BacktestMetrics:
    """Compute win rate, PnL, profit factor, and max drawdown from closed trades."""
    closed = [t for t in trades if t.closed and t.pnl is not None]
    wins = [t for t in closed if t.pnl > 0]
    losses = [t for t in closed if t.pnl <= 0]

    total_pnl = sum((t.pnl for t in closed), Decimal("0"))
    gross_profit = sum((t.pnl for t in wins), Decimal("0"))
    gross_loss = sum((t.pnl for t in losses), Decimal("0"))

    profit_factor = None
    if gross_loss != 0:
        profit_factor = float(abs(gross_profit / gross_loss))
    elif gross_profit > 0:
        profit_factor = float("inf")

    ending_value = starting_account_value + total_pnl
    return_pct = (
        float((ending_value - starting_account_value) / starting_account_value * 100)
        if starting_account_value > 0
        else 0.0
    )

    max_drawdown_pct = _max_drawdown(equity_curve or [], starting_account_value)

    return BacktestMetrics(
        total_trades=len(closed),
        wins=len(wins),
        losses=len(losses),
        win_rate=round(len(wins) / len(closed), 4) if closed else 0.0,
        total_pnl=total_pnl,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        max_drawdown_pct=max_drawdown_pct,
        ending_account_value=ending_value,
        starting_account_value=starting_account_value,
        return_pct=round(return_pct, 4),
    )


def _max_drawdown(equity_curve: list[dict], starting_value: Decimal) -> float:
    if not equity_curve:
        return 0.0
    peak = float(starting_value)
    max_dd = 0.0
    for point in equity_curve:
        value = float(point["equity"])
        peak = max(peak, value)
        if peak > 0:
            dd = (peak - value) / peak * 100
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)
