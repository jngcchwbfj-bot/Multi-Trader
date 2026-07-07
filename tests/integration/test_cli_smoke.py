"""Integration test for the CLI smoke flow (ingest -> backtest -> report)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from powerhouse.cli import app

runner = CliRunner()


@pytest.mark.integration
class TestCliSmokeFlow:
    def test_healthcheck(self):
        result = runner.invoke(app, ["healthcheck"])
        assert result.exit_code == 0

    def test_smoke_test_command(self):
        result = runner.invoke(app, ["smoke-test"])
        assert result.exit_code == 0
        assert "All smoke tests passed" in result.stdout

    def test_ingest_fixtures_command(self, tmp_path):
        curated = tmp_path / "curated"
        result = runner.invoke(
            app,
            [
                "ingest-fixtures",
                "--raw-dir",
                "data/raw/ohlcv",
                "--curated-dir",
                str(curated),
            ],
        )
        assert result.exit_code == 0
        assert (curated / "AAPL.parquet").exists()

    def test_run_session_smoke(self):
        result = runner.invoke(app, ["run-session", "--mode", "backtest", "--phase", "premarket"])
        assert result.exit_code == 0
        assert Path("reports/sessions").exists()

    def test_run_backtest_and_build_report(self):
        result = runner.invoke(
            app,
            [
                "run-backtest",
                "--symbols",
                "AAPL,MSFT",
                "--start-date",
                "2026-04-01",
                "--end-date",
                "2026-05-26",
            ],
        )
        assert result.exit_code == 0

        runs_dir = Path("data/backtests/runs")
        jsonl_files = sorted(runs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
        assert jsonl_files, "expected a backtest JSONL artifact to be written"
        latest = jsonl_files[-1]

        report_result = runner.invoke(app, ["build-report", str(latest)])
        assert report_result.exit_code == 0
        assert latest.with_suffix(".md").exists()

        with latest.open() as f:
            first_record = json.loads(f.readline())
        assert first_record["kind"] == "metrics"
