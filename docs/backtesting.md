# Backtesting - Phase 2

## What This Is

`src/powerhouse/backtest/engine.py` (`BacktestEngine`) is a real, local-data-only
historical replay engine. For each trading day in the requested range, it:

1. Slices each symbol's curated OHLCV data to "as of" that day (no look-ahead).
2. Runs the same scanner -> catalyst -> strategy -> risk pipeline logic used
   by `run-session`, tuned by the given `Phase`'s `PhaseProfile`.
3. Risk-checks and simulates plans one at a time via `TradeSimulator`
   (`src/powerhouse/simulation/executor.py`) against subsequent bars - not as
   one batch risk decision followed by one batch of fills - so a plan's risk
   check reflects realized P&L from trades already closed earlier the same
   day (see "Daily-loss enforcement" below).
4. Tracks portfolio cash, realized P&L, open risk, and an equity curve.
5. Computes summary metrics (`backtest/metrics.py`) and writes JSONL/Parquet
   artifacts plus a JSON memory record.

This is **not** a mocked pipeline exercise - it reads real (if synthetic)
OHLCV bars, produces real fills with slippage, and computes real P&L.

## Fill and Exit Assumptions

- **Fill timing**: a plan drafted on day D fills at day D+1's opening price
  (`fill_on: next_open` in `config/backtest.yaml`), adjusted by
  `slippage_bps` (against the trader: buys fill higher).
- **Exit precedence per bar**: stop-loss touch is checked before target
  touch; a trailing stop (if the plan has `trailing_stop_pct`) only ratchets
  upward and is checked as the effective stop once initialized.
- **Time-based exit**: if neither stop nor target is hit within
  `max_holding_days`, the trade is closed at that bar's close
  (`outcome=manual_close`).
- **No-fill**: if there is no forward bar at all (the plan was drafted on
  the last available day), the trade stays `no_fill` and contributes no P&L.
- **Commission**: a flat `commission_per_share`, charged on both entry and exit.

## Daily-Loss Enforcement

`RiskAgent` vetoes plans once `Portfolio.get_daily_loss_pct()` reaches
`max_daily_loss_pct` (see `docs/risk-policy.md`). Inside `BacktestEngine`,
each day's candidate plans are risk-checked and simulated **one at a time**,
in ranked order, rather than all being decided as a single batch before any
are simulated. This means:

- A plan drafted later in the same day can be rejected because of losses
  realized by an earlier plan drafted *that same day*, not just losses
  carried in from a previous day.
- `realized_pnl_today` still resets to zero at the start of each new
  simulated day - the cap is a genuine daily cap, not a running total across
  the whole backtest.

See `tests/unit/test_backtest_engine.py::TestDailyLossEnforcementInEngine`
for a regression test that runs the real engine with a near-zero
`max_daily_loss_pct` and asserts at least one plan is rejected with a
`"Daily loss cap exceeded"` reason.

## Known Simplifications (labeled, not hidden)

These are intentional scope cuts for a first real backtest engine, not bugs:

1. **Trades resolve to completion at signal time.** When a plan is approved
   on day D, its entire lifecycle (fill through exit) is simulated
   immediately using forward bars, and the realized P&L is attributed to
   day D for daily-loss and equity-curve purposes - even though the actual
   exit may be several days later. There is no true day-by-day interleaving
   of multiple, simultaneously-open positions across symbols.
2. **One open trade per symbol at a time.** A symbol is not re-scanned for
   a new entry until its current simulated trade has resolved.
3. **No intraday granularity.** Bars are daily OHLC; there's no intrabar
   path simulation beyond "did the low touch the stop" / "did the high
   touch the target" in bar order (stop checked before target).
4. **No overnight financing, borrow costs, dividends, or corporate actions.**
5. **No shorting.** Only long (`BUY`) plans are generated, matching the
   Phase 1/2 risk policy of no short positions.

Phase 3 should replace simplification #1 with true concurrent, overlapping
position tracking driven by a single unified daily event loop, if deeper
accuracy is needed.

## Sample Command

```bash
uv run powerhouse ingest-fixtures
uv run powerhouse run-backtest --symbols AAPL,MSFT,NVDA \
    --start-date 2026-04-01 --end-date 2026-05-26 --phase open
```

Writes:
- `data/backtests/runs/<backtest_id>.jsonl` - metrics, trade plans, risk
  decisions, executed trades, and equity curve points.
- `data/backtests/runs/<backtest_id>_trades.parquet` - executed trades table.
- `data/memory/backtests/<backtest_id>.json` - a short memory record.

## Data Requirements

The engine reads from `data/curated/*.parquet` (one file per symbol),
produced by `powerhouse ingest-fixtures` from `data/raw/ohlcv/*.csv`. See
the "Local Data Layout" section of the [README](../README.md) for the full
directory layout.
