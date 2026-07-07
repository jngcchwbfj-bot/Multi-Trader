"""CLI interface for Financial Powerhouse."""

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from powerhouse.__init__ import __version__
from powerhouse.conductor.service import ConductorService
from powerhouse.core.enums import OperatingMode, Phase
from powerhouse.core.models import ExecutionPolicy, Portfolio, SessionContext
from powerhouse.core.phase_router import PhaseRouter

app = typer.Typer(help="Financial Powerhouse - Multi-agent trading system")
console = Console()


@app.command()
def healthcheck() -> None:
    """Validate system wiring and imports."""
    console.print(Panel("[green]Financial Powerhouse Health Check[/green]"))
    try:
        console.print("[cyan]Checking imports...[/cyan]")
        from powerhouse.core.models import SessionContext, SessionResult
        from powerhouse.conductor.service import ConductorService

        console.print("[green]✓[/green] Core imports OK")

        console.print("[cyan]Checking phase router...[/cyan]")
        dt_premarket = datetime(2026, 7, 7, 8, 0, 0)
        phase = PhaseRouter.resolve_phase(dt_premarket)
        assert phase == Phase.PREMARKET
        console.print(f"[green]✓[/green] Phase router OK (resolved {phase.value})")

        console.print("[cyan]Checking conductor initialization...[/cyan]")
        conductor = ConductorService()
        console.print(f"[green]✓[/green] Conductor OK")

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
        console.print(f"  [green]✓[/green] Conductor ready")

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


@app.command()
def version() -> None:
    """Show version."""
    console.print(f"Financial Powerhouse v{__version__}")


if __name__ == "__main__":
    app()
