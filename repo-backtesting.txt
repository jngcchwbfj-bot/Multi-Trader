# Backtesting - Phase 2 + Phase 3 (overlapping positions)

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

1. **Trades resolve to completion at signal time (default engine only).**
   When a plan is approved on day D, its entire lifecycle (fill through
   exit) is simulated immediately using forward bars, and the realized P&L
   is attributed to day D for daily-loss and equity-curve purposes - even
   though the actual exit may be several days later. **Phase 3 adds an
   opt-in alternative that removes this simplification** - see
   "Overlapping-Positions Mode" below.
2. **One open trade per symbol at a time (default engine only).** A symbol
   is not re-scanned for a new entry until its current simulated trade has
   resolved. Overlapping-positions mode removes this restriction too.
3. **No intraday granularity.** Bars are daily OHLC; there's no intrabar
   path simulation beyond "did the low touch the stop" / "did the high
   touch the target" in bar order (stop checked before target). This
   applies to both engine modes.
4. **No overnight financing, borrow costs, dividends, or corporate actions.**
   Applies to both engine modes.
5. **No shorting.** Only long (`BUY`) plans are generated, matching the
   risk policy of no short positions. Applies to both engine modes.

## Overlapping-Positions Mode (Phase 3, opt-in)

Set `overlapping_positions: true` in `config/backtest.yaml` (or pass
`--overlapping-positions` to `run-backtest`) to replace the "resolve on
open" simplification with a true day-by-day event loop
(`src/powerhouse/backtest/positions.py`: `PositionBook`). This mode is
**off by default** - the Phase 2 engine described above is unchanged and
remains what `run-backtest` uses unless you opt in.

How it works, per simulated trading day:

1. **Fill pending entries.** Any plan approved on a prior day fills at
   today's open (same `fill_on: next_open` + slippage assumption as the
   default engine), if today has a bar for that symbol.
2. **Advance open positions.** Every position opened on a *prior* day (not
   today - a freshly-filled position is never checked against its own fill
   bar) is checked against today's bar for a stop/target/trailing-stop
   touch, in the same stop-before-target precedence as the default engine,
   or force-closed if it has been held past `max_holding_days`.
3. **Mark to market.** `portfolio.account_value = cash + sum(qty * today's close)`
   over all still-open positions. `cash` is reduced by a position's notional
   at fill and restored (plus realized P&L) at close, so `account_value`
   genuinely differs from `cash` while positions are open - unlike the
   default engine, where they are always equal because nothing is ever
   "in flight" between days.
4. **Scan and draft new plans**, capped by how much of
   `PhaseProfile.max_position_count` is not already consumed by open
   positions and not-yet-filled pending entries (i.e. this cap now means
   "max *concurrent* positions", not "max new plans per day" as in the
   default engine). Any symbol can be scanned again even with an existing
   open position - **multiple concurrent positions on the same symbol are
   allowed**, as well as across symbols.
5. **Risk-check new plans one at a time**, exactly as the default engine
   does, so the daily-loss cap can still engage mid-day from losses
   realized by positions that closed earlier that same day (step 2).

At the end of the requested date range, any still-open positions are
force-closed at the last available close price (`manual_close`) and any
never-filled pending entries are marked `no_fill` - the backtest never
silently leaves a position open past the requested window.

This mode still passes every existing engine test and produces the same
`BacktestResult`/artifact shape as the default engine (see
[`docs/artifacts.md`](artifacts.md)) - only the *simulation mechanics* differ,
not the output schema.

## Sample Command

```bash
uv run powerhouse ingest-fixtures
uv run powerhouse run-backtest --symbols AAPL,MSFT,NVDA \
    --start-date 2026-04-01 --end-date 2026-05-26 --phase open

# Opt-in overlapping-positions mode:
uv run powerhouse run-backtest --symbols AAPL,MSFT,NVDA \
    --start-date 2026-04-01 --end-date 2026-05-26 --phase open \
    --overlapping-positions
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
