# Architecture Overview

## System Design Principles

1. **Conductor-Specialist Pattern**: A central orchestrator (Conductor) manages workflow and calls narrow-purpose specialist agents.

2. **Deterministic Risk**: All risk decisions are made by code, not LLM. LLMs assist with analysis and synthesis, but veto authority belongs to deterministic rules.

3. **Structured Phases**: The trading day is divided into phases. Each phase has different thresholds, aggressiveness, and workflow.

4. **Human-in-the-Loop**: By default, execution is blocked. Human operators must explicitly allow trading and can revoke it at any time.

5. **Auditability**: Every decision is logged structurally. Trade plans, rejections, and execution events can be audited.

6. **Modularity**: Each specialist is independent and can be tested, replaced, or enhanced without breaking the whole system.

## High-Level Flow

```
Market Event / Time Trigger
    ↓
Conductor.run_session()
    ├─ Resolve market phase (premarket, open, midday, etc.)
    ├─ Load configuration for that phase
    ├─ Call workflow (e.g., premarket_workflow)
    │   ├─ Scanner agent → candidates
    │   ├─ Catalyst agent → annotate with news/events
    │   ├─ Strategy agent → draft trade plans
    │   ├─ Risk agent → veto or approve and size
    │   └─ Execution agent → route to broker or paper
    ├─ Risk layer checks: exposure, daily loss, execution policy
    ├─ Approval gate: block if execution not enabled
    └─ Reporting agent → write session report and logs
```

## Core Layers

### 1. Clock and Phase Router

**Module**: `core/clock.py`, `core/phase_router.py`

Responsibilities:
- Map current datetime (with timezone awareness) to a market phase.
- Track market hours, holidays, and halts.
- Provide deterministic phase resolution for all workflows.

### 2. Models and Enums

**Module**: `core/models.py`, `core/enums.py`

Responsibilities:
- Define all domain objects (Candidate, TradePlan, RiskDecision, etc.) using Pydantic.
- Enforce type safety and validation at object creation time.
- Provide serialization for storage and logging.

### 3. Conductor Service

**Module**: `conductor/service.py`

Responsibilities:
- Accept a SessionContext (time, mode, execution policy, etc.).
- Determine current phase and select the appropriate workflow.
- Instantiate and call specialist agents in order.
- Enforce approval gates.
- Catch exceptions and log them.
- Return a SessionResult with outcomes.

### 4. Specialist Agents

**Module**: `agents/` directory

Each agent has a narrow responsibility:

- **Scanner** (`scanner.py`): Find and rank candidate tickers for the current market context.
- **Catalyst** (`catalyst.py`): Summarize news, events, and fundamental context.
- **Strategy** (`strategy.py`): Create detailed trade plans with entry, stop, and target.
- **Risk** (`risk.py`): Veto or approve plans; size positions; check exposure.
- **Execution** (`execution.py`): Simulate fills (paper mode) or prepare broker orders.
- **Reporting** (`reporting.py`): Build markdown and structured reports.
- **Memory** (`memory.py`): Record important observations and trade outcomes.

### 5. Broker Abstraction

**Module**: `brokers/` directory

Responsibilities:
- Define broker interface (Broker ABC).
- Implement Paper broker for simulation.
- Implement Robinhood MCP client (Phase 2+).
- Translate internal OrderRequest to broker-specific API calls.

### 6. Storage Layer

**Module**: `storage/` directory

Responsibilities:
- Write JSONL logs for all events.
- Write Parquet files for time-series data.
- Use DuckDB for analytics queries.
- Provide repository pattern for data access.

### 7. Workflows

**Module**: `workflows/` directory

Each file defines a phase-specific workflow:

- **premarket.py**: Candidate identification and ranking.
- **intraday.py**: Entry confirmation and execution.
- **midday.py**: Risk reduction and profit-taking.
- **power_hour.py**: Final trades and position management.
- **end_of_day.py**: Flat/close and reporting.

## Data Flow

### Session Context → SessionResult

```python
# Input
session_ctx = SessionContext(
    timestamp=datetime.now(tz=timezone.utc),
    mode=OperatingMode.PAPER,
    execution_policy=ExecutionPolicy(allow_execution=False),
    portfolio=Portfolio(...),
    phase=Phase.PREMARKET,
)

# Process
conductor = ConductorService()
result = conductor.run_session(session_ctx)

# Output
result.status  # SUCCESS, PARTIAL, FAILED
result.trade_plans  # list of TradePlan
result.executed_trades  # list of ExecutedTrade
result.report  # SessionReport (markdown)
result.logs  # list of LogEntry
```

### Approval Gate Logic

```
Plan submitted → Risk checks
    ├─ Pass daily loss? → Continue
    ├─ Pass exposure? → Continue
    ├─ Pass per-trade risk? → Continue
    ├─ Now check execution_policy.allow_execution
    │   ├─ False → BLOCK and LOG
    │   └─ True → APPROVE
    └─ Execution → Broker or Paper
```

## Phase Profiles

Each market phase has a profile that tunes the system:

```python
class PhaseProfile:
    name: Phase
    scan_aggressiveness: float  # 0.0 (conservative) to 1.0 (aggressive)
    max_position_count: int  # how many open trades
    risk_multiplier: float  # adjust per-trade risk %
    require_premarket_analysis: bool
```

Example:
- **Premarket** (4–9:30 AM): Low aggressiveness, focus on planning.
- **Open** (9:30–12 PM): High aggressiveness, execution focus.
- **Midday** (12–3 PM): Lower aggressiveness, risk reduction.
- **Power Hour** (3–4 PM): Moderate aggressiveness, final push.
- **End-of-Day** (4–5 PM): Flat positions, reporting.

## Testing Strategy

### Unit Tests

- Phase router: given time, returns correct phase.
- Approval gate: given policy and plan, returns correct decision.
- Risk agent: given portfolio, returns correct sizing.
- Report builder: given trades, produces valid markdown.

### Integration Tests

- Mock session: conductor calls all agents, produces report.
- Storage roundtrip: write JSONL, read back, deserialize.
- Workflow execution: premarket workflow produces candidates.

### Regression Tests

- Phase profiles: each phase selects the right workflow.
- Risk constraint enforcement: exposure caps are respected.
- Report structure: markdown report contains all required sections.

## Extensibility

### Adding a New Specialist

1. Subclass `BaseAgent` in `agents/new_agent.py`.
2. Implement `run(context: SessionContext) → AgentResult`.
3. Add to the workflow in `workflows/phase_name.py`.
4. Test with mock context and mocked dependencies.

### Adding a New Workflow

1. Create `workflows/new_workflow.py`.
2. Define the phase profile and agent sequence.
3. Add to the phase router in `conductor/phase_router.py`.
4. Add integration test in `tests/integration/`.

### Adding a New Broker

1. Subclass `Broker` in `brokers/new_broker.py`.
2. Implement `place_order()`, `cancel_order()`, `get_positions()`.
3. Add to broker factory in `brokers/__init__.py`.
4. Test with mock orders and positions.

## Configuration

Phase-specific configuration is stored in `config/` as YAML files:

- `config/app.yaml`: General settings (timezone, log level, etc.).
- `config/scanner.yaml`: Candidate filtering rules.
- `config/strategy.yaml`: Entry/exit rules per phase.
- `config/risk.yaml`: Risk limits and exposure caps.
- `config/reporting.yaml`: Report templates and output paths.

Each phase workflow loads its own configuration subset.

## Logging and Audit

All major decisions are logged as structured entries:

```python
# Example log entry
{
    "timestamp": "2026-07-07T09:30:00Z",
    "session_id": "sess_xyz123",
    "event_type": "PLAN_SUBMITTED",
    "plan_id": "plan_abc456",
    "ticker": "AAPL",
    "action": "BLOCKED",
    "reason": "execution_disabled",
    "details": {...}
}
```

Logs are written to:
- `logs/execution/` (trade and order events)
- `logs/app/` (general application events)
- `logs/sessions/` (session-level events)

## Security and Deployment

- **Phase 1**: Local development only. No secrets stored in code.
- **Phase 2**: Environment variables for broker credentials. Secure vault integration.
- **Phase 3**: Kubernetes-ready, multi-region deployment support.

All credentials are loaded from environment at startup, never from files.
