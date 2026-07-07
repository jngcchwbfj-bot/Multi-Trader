# Phase 1 Backtest & Self-Audit Report

**Date**: 2026-07-07
**Scope**: Validate Phase 1 scaffold before starting Phase 2.

## 1. Important Caveat: No Real Backtest Engine Exists Yet

Phase 1 did **not** build `src/powerhouse/backtest/` (engine, fills, slippage,
metrics, scenarios). The `--mode backtest` flag on `run-session` only tags
the session context with `OperatingMode.BACKTEST` — it runs the same mocked
specialist pipeline as any other mode, with no historical price data,
no fills simulation, and no P&L computation over time.

What follows is therefore a **pipeline exercise**, not a historical
backtest: it confirms the conductor/specialist/risk/reporting flow runs
correctly end-to-end and doesn't crash under any phase input. A real
backtest engine is Phase 2/3 work.

## 2. Pipeline Run Across All Market Phases

Ran `run-session --mode backtest --phase <phase>` for all six phases.

| Phase | Candidates | Plans Proposed | Plans Approved | Trades Executed | Status |
|---|---|---|---|---|---|
| premarket | 3 | 2 | 0 | 0 | success |
| open | 3 | 2 | 0 | 0 | success |
| midday | 3 | 2 | 0 | 0 | success |
| power_hour | 3 | 2 | 0 | 0 | success |
| end_of_day | 3 | 2 | 0 | 0 | success |
| closed | 3 | 2 | 0 | 0 | success |

All six runs completed without errors. Execution was correctly blocked
in every case (`allow_execution=False` by default), consistent with the
Phase 1 risk policy.

**Finding**: results are identical across all six phases. No agent except
`ReportingAgent` reads `context.phase` — Scanner, Catalyst, Strategy, and
Risk all return the same mocked output regardless of market phase. This is
consistent with the Phase 1 scope ("mocked specialist agents with
deterministic placeholder behavior"), but phase-driven tuning (aggressiveness,
thresholds, position count) does not exist yet and is a Phase 2 item.

## 3. Test Suite

```
uv run pytest
14 passed in 0.13s
```

All unit and integration tests pass with zero warnings.

## 4. Bug Found and Fixed

**`RiskAgent.run()` reported a misleading approval reason.**

When `execution_policy.allow_execution=True` but a plan failed the exposure
or per-trade-risk check, the decision's `reason` field still said
`"Plan approved"` even though `approved=False`.

Reproduction (before fix):
```
approved: False
reason: Plan approved       # WRONG — should explain the rejection
exposure_check_passed: False
```

This directly undermines the audit-trail requirement in
`docs/risk-policy.md` ("Reason (passed risk check, failed exposure cap,
etc.)"). A human operator reading the log would see a rejected trade
labeled as approved.

**Fix**: `src/powerhouse/agents/risk.py` now derives `reason` from which
specific check failed (`allow_execution` → `daily_loss` → `exposure` →
`per_trade_risk` → approved), in priority order. Verified fix:
```
approved: False
reason: Long exposure cap exceeded
```

All 14 tests still pass after the fix.

## 5. Other Gaps Identified (Not Fixed — Flagged for Phase 2)

1. **Daily loss cap is not enforced.** `RiskAgent` hard-codes
   `daily_loss_passed = True` with a `# TODO: track daily losses` comment.
   The risk policy doc claims this cap is enforced; in code it is a no-op.
   No portfolio-level loss tracking exists yet.

2. **Exposure check uses current exposure, not post-trade exposure.**
   `exposure_passed = long_exposure < max_new_exposure` checks the
   portfolio's *current* long exposure, not what exposure would become
   after adding the proposed position. A large new trade on top of an
   already-near-cap portfolio can pass the check even though it would
   blow through the cap once filled.

3. **`allow_market_orders` is defined but never checked.** No code path
   reads this policy field — order type restrictions aren't wired to
   anything yet (moot in Phase 1 since `ExecutionAgent.run()` always
   returns `[]`, but worth noting before it matters in Phase 2).

4. **No standalone `ApprovalGate` module.** The original scaffold
   sketched `conductor/approval_gate.py` as its own component; approval
   logic instead lives inline inside `RiskAgent`. Functionally fine for
   Phase 1, but there's no dedicated unit test for "approval gating" as
   its own concern — it's only exercised indirectly through
   `test_risk_agent.py` and the integration test.

5. **Missing modules from the original scaffold tree** (expected — Phase 1
   scope explicitly excluded these): `backtest/`, `brokers/`, `workflows/`,
   `storage/`, `reports/builders.py`, `testsupport/`. None of these exist
   yet. `data/`, `logs/`, `reports/` directories exist but are empty
   (gitignored) placeholders.

## 6. Verdict

- **Safe to proceed to Phase 2**: yes. Execution is verifiably blocked by
  default, the pipeline runs cleanly across all phases, and the one real
  bug found (misleading approval reason) is fixed and covered by existing
  tests.
- **Before building live/paper execution in a later phase**, items 1–3
  above need real implementations, not placeholders — they are exactly the
  kind of deterministic risk logic the project's guiding principles say
  must never be hand-waved.

## Recommended Phase 2 Priorities (in order)

1. Implement `backtest/engine.py` with real historical data replay,
   fills, and slippage — this is the actual "backtest" capability that
   doesn't exist yet.
2. Wire daily loss tracking into `RiskAgent` (remove the TODO).
3. Fix exposure check to account for the proposed trade's incremental
   exposure, not just current state.
4. Add phase-driven behavior to Scanner/Strategy/Risk (aggressiveness,
   thresholds) per the original phase-profile design.
