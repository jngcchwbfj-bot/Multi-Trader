"""Tests for artifact schema stability (docs/artifacts.md contract).

These check *presence* of the documented fields/kinds, not exact values, so
they stay stable as engine internals evolve while still catching accidental
breaking changes to the artifact contract external dashboards depend on.
"""

import asyncio
import json
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from powerhouse.agents.reporting import write_backtest_artifacts
from powerhouse.backtest import BacktestEngine
from powerhouse.core.enums import OperatingMode, Phase
from powerhouse.core.models import ExecutionPolicy, Portfolio, SessionContext
from powerhouse.memory import MemoryStore

RAW_DIR = Path("data/raw/ohlcv")


@pytest.mark.unit
class TestBacktestArtifactSchema:
    @pytest.fixture
    def result(self, tmp_path):
        from powerhouse.data import ingest_fixtures

        ingest_fixtures(RAW_DIR, tmp_path)
        engine = BacktestEngine(curated_dir=tmp_path)
        return engine.run(symbols=["AAPL", "MSFT"], start_date="2026-04-01", end_date="2026-05-01")

    @pytest.fixture
    def artifact_path(self, result, tmp_path, monkeypatch):
        from powerhouse.config import ReportingConfig

        config = ReportingConfig(artifacts_dir=str(tmp_path / "artifacts"))
        return write_backtest_artifacts(result, config=config), result

    def test_every_row_has_kind_and_backtest_id(self, artifact_path):
        path, result = artifact_path
        with path.open() as f:
            rows = [json.loads(line) for line in f]
        assert rows, "expected at least one JSONL row"
        for row in rows:
            assert "kind" in row
            assert row["backtest_id"] == result.backtest_id

    def test_metrics_row_is_first_and_carries_run_metadata(self, artifact_path):
        path, result = artifact_path
        with path.open() as f:
            first = json.loads(f.readline())
        assert first["kind"] == "metrics"
        assert first["symbols"] == result.symbols
        assert first["start_date"] == result.start_date
        assert first["end_date"] == result.end_date
        assert "total_trades" in first
        assert "win_rate" in first

    def test_expected_kinds_present(self, artifact_path):
        path, _ = artifact_path
        with path.open() as f:
            kinds = {json.loads(line)["kind"] for line in f}
        assert "metrics" in kinds
        assert "equity_point" in kinds
        # trade_plan/risk_decision/executed_trade are present whenever any
        # plans were drafted; the fixture universe over this range should
        # draft at least one.
        assert kinds & {"trade_plan", "risk_decision"}

    def test_executed_trade_rows_have_documented_fields(self, artifact_path):
        path, _ = artifact_path
        with path.open() as f:
            rows = [json.loads(line) for line in f]
        trade_rows = [row for row in rows if row["kind"] == "executed_trade"]
        for row in trade_rows:
            for field in (
                "plan_id",
                "trade_id",
                "ticker",
                "side",
                "entry_price",
                "quantity",
                "outcome",
                "closed",
                "events",
            ):
                assert field in row

    def test_risk_decision_rows_have_check_flags(self, artifact_path):
        path, _ = artifact_path
        with path.open() as f:
            rows = [json.loads(line) for line in f if json.loads(line)["kind"] == "risk_decision"]
        assert rows, "expected at least one risk_decision row"
        for row in rows:
            for field in (
                "approved",
                "reason",
                "daily_loss_check_passed",
                "exposure_check_passed",
                "per_trade_risk_check_passed",
                "total_open_risk_check_passed",
            ):
                assert field in row

    def test_trades_parquet_has_backtest_id_column(self, artifact_path, tmp_path):
        _, result = artifact_path
        if not result.executed_trades:
            pytest.skip("no executed trades to check parquet for")
        parquet_path = tmp_path / "artifacts" / "runs" / f"{result.backtest_id}_trades.parquet"
        table = pq.read_table(parquet_path)
        assert "backtest_id" in table.column_names
        assert set(table.column("backtest_id").to_pylist()) == {result.backtest_id}

    def test_equity_parquet_written_with_expected_columns(self, artifact_path, tmp_path):
        _, result = artifact_path
        parquet_path = tmp_path / "artifacts" / "runs" / f"{result.backtest_id}_equity.parquet"
        assert parquet_path.exists()
        table = pq.read_table(parquet_path)
        assert set(table.column_names) >= {"backtest_id", "date", "equity"}


@pytest.mark.unit
class TestSessionArtifactSchema:
    def test_conductor_session_artifact_uses_singular_kind_names(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "data" / "raw" / "ohlcv").mkdir(parents=True)
        (tmp_path / "data" / "raw" / "catalysts.csv").write_text(
            "ticker,catalyst_type,summary,sentiment,confidence\n"
        )
        for src in RAW_DIR.glob("*.csv"):
            (tmp_path / "data" / "raw" / "ohlcv" / src.name).write_text(src.read_text())

        from powerhouse.conductor.service import ConductorService
        from powerhouse.data import ingest_fixtures

        ingest_fixtures(tmp_path / "data" / "raw" / "ohlcv", tmp_path / "data" / "curated")

        ctx = SessionContext(
            phase=Phase.OPEN,
            mode=OperatingMode.BACKTEST,
            execution_policy=ExecutionPolicy(allow_execution=False),
            portfolio=Portfolio(),
        )
        conductor = ConductorService()
        asyncio.run(conductor.run_session(ctx))

        jsonl_path = Path("data/backtests/sessions") / f"{ctx.session_id}.jsonl"
        assert jsonl_path.exists()
        with jsonl_path.open() as f:
            rows = [json.loads(line) for line in f]
        kinds = {row["kind"] for row in rows}
        assert kinds <= {"candidate", "catalyst", "trade_plan", "risk_decision", "executed_trade"}
        for row in rows:
            assert row["session_id"] == ctx.session_id
            assert "phase" in row and "mode" in row


@pytest.mark.unit
class TestMemoryRecordSchema:
    def test_backtest_memory_record_has_documented_fields(self, tmp_path):
        from powerhouse.data import ingest_fixtures

        ingest_fixtures(RAW_DIR, tmp_path)
        engine = BacktestEngine(curated_dir=tmp_path)
        result = engine.run(symbols=["AAPL"], start_date="2026-04-01", end_date="2026-05-01")

        memory = MemoryStore(memory_dir=tmp_path / "memory")
        path = memory.write_backtest_record(
            result.backtest_id,
            {
                "backtest_id": result.backtest_id,
                "symbols": result.symbols,
                "start_date": result.start_date,
                "end_date": result.end_date,
                "metrics": result.metrics.model_dump(mode="json"),
            },
        )
        record = json.loads(path.read_text())
        for field in ("backtest_id", "symbols", "start_date", "end_date", "metrics"):
            assert field in record
