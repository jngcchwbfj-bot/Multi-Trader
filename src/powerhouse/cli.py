"""CLI interface for Financial Powerhouse."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from powerhouse.__init__ import __version__
from powerhouse.agents.reporting import build_backtest_markdown, write_backtest_artifacts
from powerhouse.backtest import BacktestEngine
from powerhouse.conductor.service import ConductorService
from powerhouse.core.enums import OperatingMode, Phase
from powerhouse.core.models import ExecutionPolicy, Portfolio, SessionContext
from powerhouse.core.phase_router import PhaseRouter
from powerhouse.data import ingest_fixtures
from powerhouse.memory import MemoryStore

app = typer.Typer(help="Financial Powerhouse - Multi-agent trading system")
console = Console()


@app.command()
def healthcheck() -> None:
    """Validate system wiring and imports."""
    console.print(Panel("[green]Financial Powerhouse Health Check[/green]"))
    try:
        console.print("[cyan]Checking imports...[/cyan]")
        from powerhouse.conductor.service import ConductorService

        console.print("[green]✓[/green] Core imports OK")

        console.print("[cyan]Checking phase router...[/cyan]")
        dt_premarket = datetime(2026, 7, 7, 8, 0, 0)
        phase = PhaseRouter.resolve_phase(dt_premarket)
        assert phase == Phase.PREMARKET
        console.print(f"[green]✓[/green] Phase router OK (resolved {phase.value})")

        console.print("[cyan]Checking conductor initialization...[/cyan]")
        conductor = ConductorService()
        console.print("[green]✓[/green] Conductor OK")

        console.print()
        console.print(
            Panel(
                f"[green bold]All checks passed![/green bold]\n\nVersion: {__version__}",
                title="Status",
            )
        )
    except Exception as e:
        console.print(f"[red]✗ Health check failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def smoke_test() -> None:
    """Run smoke tests to validate wiring."""
    console.print(Panel("[green]Financial Powerhouse Smoke Test[/green]"))

    try:
        # Test 1: Phase routing
        console.print("[cyan]Test 1: Phase routing[/cyan]")
        # Use UTC times that correspond to ET times
        # ET is UTC-4 in July (EDT)
        test_times = [
            (datetime(2026, 7, 7, 11, 0, 0), Phase.PREMARKET),  # 7 AM ET
            (datetime(2026, 7, 7, 14, 0, 0), Phase.OPEN),  # 10 AM ET
            (datetime(2026, 7, 7, 17, 0, 0), Phase.MIDDAY),  # 1 PM ET
            (datetime(2026, 7, 7, 19, 30, 0), Phase.POWER_HOUR),  # 3:30 PM ET
            (datetime(2026, 7, 7, 20, 30, 0), Phase.END_OF_DAY),  # 4:30 PM ET
            (datetime(2026, 7, 8, 2, 0, 0), Phase.CLOSED),  # 10 PM ET (next day)
        ]
        for dt, expected_phase in test_times:
            phase = PhaseRouter.resolve_phase(dt)
            assert phase == expected_phase, f"Expected {expected_phase}, got {phase}"
            console.print(f"  [green]✓[/green] {dt.time()} → {phase.value}")

        # Test 2: Model creation
        console.print("[cyan]Test 2: Model creation[/cyan]")
        portfolio = Portfolio()
        ctx = SessionContext(phase=Phase.PREMARKET)
        console.print(f"  [green]✓[/green] Portfolio: ${portfolio.account_value:,.2f}")
        console.print(f"  [green]✓[/green] Session ID: {ctx.session_id[:8]}...")

        # Test 3: Conductor initialization
        console.print("[cyan]Test 3: Conductor initialization[/cyan]")
        conductor = ConductorService()
        console.print("  [green]✓[/green] Conductor ready")

        # Test 4: Local data layer + a tiny real backtest
        console.print("[cyan]Test 4: Data layer + sample backtest[/cyan]")
        ingest_fixtures(Path("data/raw/ohlcv"), Path("data/curated"))
        console.print("  [green]✓[/green] Fixtures ingested to data/curated")
        engine = BacktestEngine()
        result = engine.run(phase=Phase.OPEN)
        console.print(
            f"  [green]✓[/green] Backtest ran: {result.metrics.total_trades} trades, "
            f"return {result.metrics.return_pct:.2f}%"
        )

        console.print()
        console.print(Panel("[green bold]All smoke tests passed![/green bold]", title="Status"))
    except Exception as e:
        console.print(f"[red]✗ Smoke test failed: {e}[/red]")
        raise typer.Exit(1)


@app.command()
def run_session(
    mode: str = typer.Option("backtest", help="Operating mode: backtest, paper, or live"),
    phase: str = typer.Option("premarket", help="Market phase to simulate"),
) -> None:
    """Run a mock trading session."""
    console.print(Panel(f"[cyan]Running {phase} session in {mode} mode[/cyan]"))

    try:
        # Parse mode and phase
        try:
            op_mode = OperatingMode(mode)
        except ValueError:
            console.print(f"[red]Invalid mode: {mode}[/red]")
            raise typer.Exit(1)

        try:
            market_phase = Phase(phase)
        except ValueError:
            console.print(f"[red]Invalid phase: {phase}[/red]")
            raise typer.Exit(1)

        # Create session context
        ctx = SessionContext(
            timestamp=datetime.now(timezone.utc),
            phase=market_phase,
            mode=op_mode,
            execution_policy=ExecutionPolicy(
                allow_execution=False,  # Phase 1: always blocked
                mode=op_mode,
            ),
            portfolio=Portfolio(),
        )

        # Run conductor
        conductor = ConductorService()
        result = asyncio.run(conductor.run_session(ctx))

        # Display report
        if result.report and result.report.markdown_report:
            md = Markdown(result.report.markdown_report)
            console.print(md)

        # Save report to file
        reports_dir = Path("reports") / "sessions"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_file = reports_dir / f"{ctx.session_id}.md"
        report_file.write_text(result.report.markdown_report)
        console.print(f"\n[cyan]Report saved to:[/cyan] {report_file}")

        # Write a simple memory record for later review.
        memory = MemoryStore()
        memory_path = memory.write_session_record(
            ctx.session_id,
            {
                "session_id": ctx.session_id,
                "phase": ctx.phase.value,
                "mode": ctx.mode.value,
                "status": result.status.value,
                "candidates_found": result.report.candidates_found,
                "trade_plans_proposed": result.report.trade_plans_proposed,
                "trade_plans_approved": result.report.trade_plans_approved,
                "trades_executed": result.report.trades_executed,
                "total_pnl": str(result.report.total_pnl),
            },
        )
        console.print(f"[cyan]Memory record saved to:[/cyan] {memory_path}")

        # Status
        if result.status.value == "success":
            console.print(f"\n[green]Session completed: {result.status.value}[/green]")
        else:
            console.print(f"\n[red]Session failed: {result.status.value}[/red]")
            if result.errors:
                for error in result.errors:
                    console.print(f"  [red]Error:[/red] {error}")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]✗ Session failed: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="ingest-fixtures")
def ingest_fixtures_cmd(
    raw_dir: str = typer.Option("data/raw/ohlcv", help="Directory of raw OHLCV CSV files"),
    curated_dir: str = typer.Option("data/curated", help="Output directory for curated Parquet"),
) -> None:
    """Ingest raw CSV OHLCV fixtures into normalized local Parquet."""
    console.print(Panel(f"[cyan]Ingesting fixtures from {raw_dir} -> {curated_dir}[/cyan]"))
    try:
        written = ingest_fixtures(Path(raw_dir), Path(curated_dir))
        for path in written:
            console.print(f"  [green]✓[/green] {path}")
        console.print(f"\n[green]Ingested {len(written)} symbol(s).[/green]")
    except Exception as e:
        console.print(f"[red]✗ Ingestion failed: {e}[/red]")
        raise typer.Exit(1)


@app.command(name="run-backtest")
def run_backtest(
    symbols: str = typer.Option("", help="Comma-separated symbols (default: full universe)"),
    start_date: str = typer.Option(None, help="Start date YYYY-MM-DD (default: earliest)"),
    end_date: str = typer.Option(None, help="End date YYYY-MM-DD (default: latest)"),
    phase: str = typer.Option("open", help="Market phase profile to simulate under"),
) -> None:
    """Run a real historical replay/simulation backtest over local Parquet data."""
    console.print(Panel("[cyan]Running backtest[/cyan]"))
    try:
        market_phase = Phase(phase)
    except ValueError:
        console.print(f"[red]Invalid phase: {phase}[/red]")
        raise typer.Exit(1)

    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()] or None

    try:
        engine = BacktestEngine()
        result = engine.run(
            symbols=symbol_list, start_date=start_date, end_date=end_date, phase=market_phase
        )
    except Exception as e:
        console.print(f"[red]✗ Backtest failed: {e}[/red]")
        raise typer.Exit(1)

    md = build_backtest_markdown(result)
    console.print(Markdown(md))

    artifact_path = write_backtest_artifacts(result)
    console.print(f"\n[cyan]Artifacts written to:[/cyan] {artifact_path}")

    memory = MemoryStore()
    memory_path = memory.write_backtest_record(
        result.backtest_id,
        {
            "backtest_id": result.backtest_id,
            "symbols": result.symbols,
            "start_date": result.start_date,
            "end_date": result.end_date,
            "metrics": result.metrics.model_dump(mode="json"),
        },
    )
    console.print(f"[cyan]Memory record saved to:[/cyan] {memory_path}")


@app.command(name="build-report")
def build_report(
    jsonl_path: str = typer.Argument(..., help="Path to a backtest JSONL artifact"),
) -> None:
    """Rebuild a markdown summary report from a stored backtest JSONL artifact."""
    path = Path(jsonl_path)
    if not path.exists():
        console.print(f"[red]✗ File not found: {path}[/red]")
        raise typer.Exit(1)

    counts: dict[str, int] = {}
    metrics = None
    with path.open("r") as f:
        for line in f:
            record = json.loads(line)
            kind = record.get("kind", "unknown")
            counts[kind] = counts.get(kind, 0) + 1
            if kind == "metrics":
                metrics = record

    md_lines = [f"# Report rebuilt from {path.name}", ""]
    for kind, count in counts.items():
        md_lines.append(f"- {kind}: {count}")
    if metrics:
        md_lines.extend(
            [
                "",
                "## Metrics",
                "",
                f"- Total PnL: {metrics.get('total_pnl')}",
                f"- Win Rate: {metrics.get('win_rate')}",
                f"- Return %: {metrics.get('return_pct')}",
            ]
        )

    md = "\n".join(md_lines)
    console.print(Markdown(md))

    out_path = path.with_suffix(".md")
    out_path.write_text(md)
    console.print(f"\n[cyan]Report saved to:[/cyan] {out_path}")


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"Financial Powerhouse v{__version__}")


if __name__ == "__main__":
    app()
