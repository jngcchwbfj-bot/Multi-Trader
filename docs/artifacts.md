# Artifact Contract - Phase 3

This document describes every file this system writes under `data/backtests/`
and `data/memory/`, and how an external dashboard app (outside this repo)
should read them. Nothing here requires network access or credentials -
every artifact is generated locally from local, offline data.

## Stability guarantees

- Field names and types documented below will not change without a version
  bump to this document. New optional fields may be added in future phases -
  dashboard consumers should tolerate unknown extra keys rather than failing
  on them.
- JSONL files are written once, in full, at the end of a run (`run-backtest`)
  or session (`run-session` / `run-paper-session`) - they are never appended
  to afterward, so it's always safe to read a file in its entirety.
- Every JSONL row carries a `kind` discriminator (string) and an id field
  (`backtest_id` or `session_id`) so rows from many files can be concatenated
  into one table and still be told apart / joined back to their run.

## Backtest artifacts (`run-backtest`)

Written by `powerhouse.agents.reporting.write_backtest_artifacts`.

### `data/backtests/runs/<backtest_id>.jsonl`

One JSON object per line. Every row has `kind` and `backtest_id`. Row shapes
by `kind`:

| `kind`            | Count per file | Notable fields |
|-------------------|----------------|----------------|
| `metrics`         | exactly 1      | `symbols` (list[str]), `start_date`, `end_date`, `created_at`, plus every field of `BacktestMetrics` (below) |
| `trade_plan`      | 1 per drafted plan | `plan_id`, `ticker`, `side`, `entry_price`, `stop_loss_price`, `target_price`, `quantity`, `rationale`, `confidence`, `trailing_stop_pct`, `created_at` |
| `risk_decision`   | 1 per drafted plan | `plan_id`, `ticker`, `approved` (bool), `reason` (str), `adjusted_quantity`, `daily_loss_check_passed`, `exposure_check_passed`, `per_trade_risk_check_passed`, `total_open_risk_check_passed` (the four boolean "flags" behind `reason`) |
| `executed_trade`  | 1 per approved plan (incl. `no_fill`) | see "Executed trade" below |
| `equity_point`    | 1 per simulated trading day | `date` (`YYYY-MM-DD`), `equity` (float account value that day) |

`BacktestMetrics` fields (on the `metrics` row): `total_trades`, `wins`,
`losses`, `win_rate`, `total_pnl`, `gross_profit`, `gross_loss`,
`profit_factor` (nullable), `max_drawdown_pct`, `starting_account_value`,
`ending_account_value`, `return_pct`.

#### Executed trade

`plan_id`, `trade_id`, `ticker`, `side`, `entry_price`, `quantity`,
`entry_timestamp`, `stop_loss_price`, `target_price`,
`trailing_stop_price` (nullable), `outcome`
(`pending`/`filled`/`stop_hit`/`target_hit`/`no_fill`/`manual_close`),
`closed` (bool), `exit_price` (nullable), `exit_timestamp` (nullable),
`pnl` (nullable), `events` (list of structured lifecycle events - see below).

`entry_timestamp`/`exit_timestamp` reflect the **simulated** bar date (not
wall-clock run time), parsed as UTC midnight on that date, so a dashboard
trade timeline lines up with the equity curve. A trade that never got a
usable bar (`no_fill`) keeps `closed=False` and has no `exit_*` fields.

Each entry in `events` has: `event_id`, `trade_id`, `plan_id`, `ticker`,
`event_type` (`pending_entry`/`filled`/`stop_hit`/`target_hit`/
`trailing_stop_updated`/`no_fill`/`manual_close`), `price` (nullable),
`quantity` (nullable), `timestamp`, and a free-form `details` dict - e.g.
`{"bar_date": "2026-04-14"}` on `filled`/exit events, or
`{"reason": "..."}` on `no_fill`.

### `data/backtests/runs/<backtest_id>_trades.parquet`

Flat table of every `executed_trade` row (same fields as above, minus the
nested `events` list, plus a `backtest_id` column). Convenient for bulk
loads, e.g.:

```sql
SELECT * FROM read_parquet('data/backtests/runs/*_trades.parquet')
```

### `data/backtests/runs/<backtest_id>_equity.parquet`

Flat table of the equity curve: `backtest_id`, `date`, `equity`. Only
written when the run has at least one simulated day.

## Session artifacts (`run-session` / `run-paper-session`)

Written by `powerhouse.agents.reporting.ReportingAgent._write_artifacts`.

### `data/backtests/sessions/<session_id>.jsonl`

Same `kind`-per-line convention as backtest artifacts (singular record
names, so a dashboard can share one parser across both artifact families).
Every row also carries `session_id`, `phase`, `mode`, `timestamp`.

| `kind`           | Fields |
|------------------|--------|
| `candidate`      | `ticker`, `price`, `market_cap` (nullable), `relevance_score`, `reason`, `added_at` |
| `catalyst`       | `ticker`, `catalyst_type`, `summary`, `sentiment`, `confidence`, `added_at` |
| `trade_plan`     | same fields as the backtest `trade_plan` row |
| `risk_decision`  | same fields as the backtest `risk_decision` row |
| `executed_trade` | same fields as the backtest `executed_trade` row |

A single-point-in-time session (both `run-session` and `run-paper-session`)
has no forward market data, so `executed_trade` rows are always
`outcome=no_fill` / `closed=False` today - a full fill/exit lifecycle only
comes from `run-backtest`'s historical replay.

### `data/backtests/sessions/<session_id>_plans.parquet`

Flat table of `trade_plan` rows (only written when at least one plan was
drafted), with the same `session_id`/`phase`/`mode`/`timestamp` columns
prepended.

## Memory records

Written by `powerhouse.memory.MemoryStore`. Plain JSON (one file per run),
not JSONL - intended as a small, human-readable index of runs, not a bulk
data source. A dashboard should treat these as "recently run" listings and
read the JSONL/Parquet artifacts above for the actual data.

- `data/memory/sessions/<session_id>.json`: `session_id`, `phase`, `mode`,
  `status`, `candidates_found`, `trade_plans_proposed`,
  `trade_plans_approved`, `trades_executed`, `total_pnl`. The
  `run-paper-session` command additionally writes `broker`
  (`"paper"`), `broker_is_paper` (`true`), `broker_orders` (count),
  `broker_cash`, `execution_enabled`.
- `data/memory/backtests/<backtest_id>.json`: `backtest_id`, `symbols`,
  `start_date`, `end_date`, `metrics` (nested `BacktestMetrics`, as above).

## Reading recommendations for a dashboard

1. For a single run's headline KPIs, read the one `metrics` row (backtest)
   or use the session's memory JSON record (session).
2. For a trade blotter, stream `executed_trade` rows (or the trades
   Parquet) and filter to `closed=true` for realized trades.
3. For an equity curve chart, use `equity_point` rows or the equity
   Parquet - one point per simulated trading day.
4. To cross-reference why a plan was rejected, join `risk_decision` rows to
   `trade_plan` rows on `plan_id`; the boolean `*_check_passed` flags tell
   you which specific gate failed, `reason` is the human-readable summary.
5. Multiple runs can be loaded together (e.g. via
   `read_parquet('data/backtests/runs/*_trades.parquet')` or by
   concatenating JSONL files) since every row is tagged with its
   `backtest_id`/`session_id`.

## Out of scope

No dashboard code lives in this repo - Phase 3 only guarantees the artifact
contract above is stable and documented. See `docs/backtesting.md` for the
backtest engine's simulation assumptions and `docs/risk-policy.md` for the
risk model that produces the `risk_decision` rows.
