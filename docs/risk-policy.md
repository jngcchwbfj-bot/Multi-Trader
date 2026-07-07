# Risk Policy - Phase 1

## Overview

This document defines hard constraints enforced by the Financial Powerhouse system in Phase 1. These rules are **deterministic**, not LLM-based, and are checked at critical decision points.

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
- **Action**: Once the daily loss limit is reached, no further orders are permitted.
- **Reporting**: All loss events are logged and reported.

### 3. Per-Trade Risk Limit

- **Max Risk**: Risk per trade (entry minus stop loss) cannot exceed 0.5% of portfolio value.
- **Position Sizing**: If a trade plan violates this, the position size is reduced to comply.
- **Rejection**: If position sizing makes the trade unviable (< 1 share), the trade is rejected.

### 4. Exposure Cap

- **Total Long Exposure**: No more than 80% of portfolio value.
- **Total Short Exposure**: No short positions permitted in Phase 1.
- **Cash Reserve**: Minimum 20% of portfolio must remain in cash.

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

## Phase 2 Outlook

Phase 2 will add:

- Tiered approval levels (risk-based auto-approval for tiny trades).
- More sophisticated exposure tracking across strategies.
- Multi-day risk rollup and correlation analysis.
- Regulatory report generation.

Until then, everything is **manual**, **logged**, and **blocked by default**.
