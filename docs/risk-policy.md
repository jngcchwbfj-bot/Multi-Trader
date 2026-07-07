# Risk Policy - Phase 2

## Overview

This document defines hard constraints enforced by the Financial Powerhouse system. These rules are **deterministic**, not LLM-based, and are checked at critical decision points.

> **Phase 2 update**: the daily loss cap described below is now actually
> enforced (Phase 1 hard-coded it as a no-op). Exposure checks use
> *projected post-trade* exposure, not current exposure. A new total
> open-risk cap and structural plan-validity checks were also added. See
> `src/powerhouse/agents/risk.py` for the implementation and
> `tests/unit/test_daily_loss.py` for enforcement tests.

## Core Principles

1. **Execution is blocked by default.** No orders of any kind are permitted unless execution is explicitly enabled in the session context and the risk layer approves the trade.

2. **All risk decisions are deterministic.** The risk layer uses code-based rules, not LLM judgment, to decide whether a trade can proceed.

3. **No live trading in Phase 1.** The system does not connect to real brokers. Mode is `backtest` or `paper` only.

4. **All trading is human-supervised.** Every session must be initiated, monitored, and concluded by a human operator.

## Hard Constraints

### 1. Execution Gate

- **Default**: All execution is **BLOCKED**.
- **Override**: Execution can only be enabled if:
  - The session context includes `allow_execution=True`.
  - The risk layer approves the individual trade plan.
  - The operating mode is `backtest` or `paper` (never `live` in Phase 1).

### 2. Daily Loss Cap

- **Limit**: Losses in a session are capped at 1% of portfolio value.
- **Tracking**: `Portfolio.realized_pnl_today` accumulates realized P&L from
  simulated trade closes; `Portfolio.get_daily_loss_pct()` derives today's
  loss as a positive percentage (0 on a profitable day).
- **Action**: Once the daily loss limit is reached, no further orders are
  permitted (`RiskAgent` vetoes with a `"Daily loss cap exceeded"` reason).
- **Reporting**: All loss events are logged and reported.
- **Reset**: `BacktestEngine` resets `realized_pnl_today` to zero at the
  start of each simulated trading day.

### 3. Per-Trade Risk Limit

- **Max Risk**: Risk per trade (entry minus stop loss) cannot exceed 0.5% of portfolio value.
- **Position Sizing**: If a trade plan violates this, the position size is reduced to comply.
- **Rejection**: If position sizing makes the trade unviable (< 1 share), the trade is rejected.

### 4. Exposure Cap

- **Total Long Exposure**: No more than 80% of portfolio value, checked
  against **projected post-trade** exposure (current exposure + this
  plan's notional value), not just current exposure. A veto looks like:
  `Long exposure cap exceeded: projected 96.5% > cap 80.0%`.
- **Total Short Exposure**: No short positions permitted.
- **Cash Reserve**: Minimum 20% of portfolio must remain in cash.
- **Total Open Risk Cap**: The sum of per-trade risk across all currently
  open (approved) positions cannot exceed `max_total_open_risk_pct`
  (default 2%). Approving a plan adds its risk to
  `Portfolio.open_risk_amount`; closing a trade releases it.

### 5. Order Types

- **Phase 1 Modes**: Only limit orders and stop-limit orders are permitted.
- **No Market Orders**: Market orders are forbidden to protect against slippage and volatility.
- **No Bracket Orders**: Automatic OCO bracket orders are not supported; separate stop and target orders must be managed.

### 6. Session Duration

- **Max Session Length**: No session can run longer than 6 hours without explicit human approval to extend.
- **Auto-Shutdown**: At end-of-day (4:00 PM ET), all open positions are evaluated for closure.

## Enforcement Points

### At Plan Creation

The strategy agent drafts a trade plan. Before routing to execution, the plan is checked:

- Entry and stop prices are within reasonable bounds (e.g., entry ≠ stop).
- Position size is calculated based on risk limits.
- Trade does not violate exposure caps.
- If check fails, the plan is marked as rejected and reported.

### At Execution Gate

The execution agent checks:

- Is execution enabled (`allow_execution=True` in context)?
- Has the daily loss limit been reached?
- Does this trade violate exposure caps?
- If any check fails, execution is blocked.

### At Risk Review

The risk agent performs final veto:

- Recalculates risk metrics given current portfolio state.
- Checks if the trade aligns with the phase-specific aggression level.
- Logs the decision (approve or reject).

## Approval Context

A session context includes an `ExecutionPolicy`:

```python
class ExecutionPolicy:
    allow_execution: bool = False  # default: blocked
    mode: OperatingMode  # backtest, paper, live
    max_daily_loss_pct: float = 1.0
    max_per_trade_risk_pct: float = 0.5
    max_long_exposure_pct: float = 80.0
    min_cash_reserve_pct: float = 20.0
    allow_market_orders: bool = False
    require_approval_per_trade: bool = True  # Phase 1 default
```

## Phase 1 Defaults

| Setting | Value | Rationale |
|---------|-------|-----------|
| `allow_execution` | `False` | No orders without explicit approval |
| `mode` | `backtest` | No live trading |
| `max_daily_loss_pct` | 1% | Conservative capital protection |
| `max_per_trade_risk_pct` | 0.5% | Tight per-trade risk limit |
| `max_long_exposure_pct` | 80% | Leave 20% cash buffer |
| `allow_market_orders` | `False` | Limit orders only |
| `require_approval_per_trade` | `True` | Human review each trade |

## Violating Policy

If any hard constraint is violated:

1. The action is **blocked**.
2. An error event is **logged**.
3. The session report **flags** the violation.
4. The human operator is **notified**.
5. Further action requires **explicit review** and approval.

## Audit Trail

Every decision point is logged with:

- Timestamp
- Action (plan created, execution requested, blocked, approved)
- Reason (passed risk check, failed exposure cap, etc.)
- Operator (if human-initiated)

Logs are stored in `logs/execution/` in JSONL format for later audit and learning.

## Phase 3 Outlook

Phase 3 should add:

- Tiered approval levels (risk-based auto-approval for tiny trades).
- Multi-day/multi-session risk rollup and correlation analysis across
  strategies (today's tracking is single-session/single-backtest-run scoped).
- Regulatory report generation.
- A real broker adapter, still gated behind the same `allow_execution` check.

Until then, everything is **simulated**, **logged**, and **blocked by
default unless `allow_execution=True` and the risk layer approves**.
