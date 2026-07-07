# Financial Powerhouse

A Python-first, multi-agent day-trading system with human-in-the-loop approval gates, deterministic risk management, and full backtesting support.

## Phase 1 Status

**Phase 1 is a scaffold build. No live trading is enabled.**

This phase focuses on:
- Repository architecture and module structure
- Conductor + Specialists orchestration pattern
- Deterministic risk and approval gates
- Backtesting framework foundation
- CLI wiring and integration tests
- Structured logging and reporting

## Quick Start

### Prerequisites

- Python 3.12 or later
- `uv` package manager ([install](https://github.com/astral-sh/uv))

### Setup

```bash
uv sync
```

### Validate Installation

```bash
uv run python -m powerhouse.cli healthcheck
uv run python -m powerhouse.cli smoke-test
```

### Run a Mock Session

```bash
uv run python -m powerhouse.cli run-session --mode backtest --phase premarket
```

### Run Tests

```bash
uv run pytest
uv run pytest --cov=powerhouse --cov-report=html  # with coverage
```

## Operating Modes

The system supports three explicit modes:

- **backtest**: Historical replay using the same logic as live trading.
- **paper**: Real logic executed against simulated fills and broker responses.
- **live**: Integration with Robinhood MCP (Phase 2+). Disabled in Phase 1.

## Market Phases

The system understands Eastern Time market phases:

- **premarket**: 4:00 AM – 9:30 AM ET
- **open**: 9:30 AM – 12:00 PM ET
- **midday**: 12:00 PM – 3:00 PM ET
- **power_hour**: 3:00 PM – 4:00 PM ET
- **end_of_day**: 4:00 PM – 5:00 PM ET
- **closed**: All other times

## Repository Structure

```
financial-powerhouse/
├── config/              # YAML configuration files
├── data/                # Data storage (raw, staged, curated, backtests, memory)
├── docs/                # Architecture and policy docs
├── logs/                # Session and execution logs
├── reports/             # Daily, session, trade, and backtest reports
├── scripts/             # Utility and bootstrap scripts
├── src/powerhouse/      # Main package
├── tests/               # Unit, integration, and regression tests
├── pyproject.toml       # Project configuration
└── README.md            # This file
```

## Key Concepts

### Conductor

Orchestrates the trading day. Maps the current time to a phase, selects the appropriate workflow, calls specialist agents in sequence, enforces approval gates, and generates reports.

### Specialists

Narrow-responsibility agents:

- **Scanner**: Identifies candidate tickers.
- **Catalyst**: Summarizes market context and catalysts.
- **Strategy**: Drafts trade plans with entry, stop, and target.
- **Risk**: Validates trade plans against policy, sizes positions, and enforces exposure caps.
- **Execution**: Simulates or routes approved orders to the broker.
- **Reporting**: Builds session reports and analytics.
- **Memory**: Records observations and trade outcomes for future learning.

### Approval Gate

By default, all execution is blocked. Phase 1 requires explicit approval context to allow orders. This is enforced deterministically, not by LLM.

### Storage

All major events are written to structured storage (JSONL, Parquet, DuckDB) for auditability and learning.

## Safety and Risk Policy

See [`docs/risk-policy.md`](docs/risk-policy.md) for hard constraints:

- Execution is disabled by default.
- Daily loss caps are enforced.
- Per-trade risk limits are enforced.
- No market orders in live phases.
- All live orders require explicit approval.

## Phase 2 Preview

Phase 2 will add:

- Real market data adapters and exchange calendar awareness.
- Richer candidate scoring and analysis.
- More sophisticated strategy agents.
- Backtest engine refinement and metrics.
- Durable memory schema for learning.
- Pre-market and end-of-day workflow templates.

## Commands

```bash
# Health check: validate package wiring
uv run python -m powerhouse.cli healthcheck

# Run a session
uv run python -m powerhouse.cli run-session --mode backtest --phase premarket
uv run python -m powerhouse.cli run-session --mode paper --phase open

# Build a report for a specific date
uv run python -m powerhouse.cli build-report --date 2026-07-06

# Run smoke tests
uv run python -m powerhouse.cli smoke-test
```

## Development

### Code Style

Code is formatted with Black and linted with Ruff. Check before committing:

```bash
uv run ruff check src tests
uv run black --check src tests
```

### Type Checking

Run mypy to check types:

```bash
uv run mypy src
```

## Contributing

All changes should:

1. Pass existing tests: `uv run pytest`
2. Be formatted with `uv run black`
3. Pass linting: `uv run ruff check`
4. Include tests for new features
5. Update docs as needed

## License

MIT
