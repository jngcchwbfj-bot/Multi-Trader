"""Typed configuration schemas (pydantic) for every subsystem."""

from pydantic import BaseModel, Field


class SessionConfig(BaseModel):
    max_duration_seconds: int = 21600
    auto_shutdown_at_eod: bool = True
    require_human_approval: bool = True


class PortfolioConfig(BaseModel):
    initial_cash: float = 100_000
    min_cash_reserve_pct: float = 20.0
    max_long_exposure_pct: float = 80.0


class AppConfig(BaseModel):
    """Top-level application settings (config/app.yaml)."""

    timezone: str = "America/New_York"
    log_level: str = "INFO"
    environment: str = "development"
    session: SessionConfig = Field(default_factory=SessionConfig)
    portfolio: PortfolioConfig = Field(default_factory=PortfolioConfig)


class ScannerConfig(BaseModel):
    """Candidate ranking rules (config/scanner.yaml)."""

    universe: list[str] = Field(default_factory=list)
    max_candidates: int = 5
    min_price: float = 1.0
    min_relevance_score: float = 0.0
    momentum_lookback_days: int = 5
    phase_aggressiveness: dict[str, float] = Field(
        default_factory=lambda: {
            "premarket": 0.3,
            "open": 0.9,
            "midday": 0.5,
            "power_hour": 0.7,
            "end_of_day": 0.2,
            "closed": 0.0,
        }
    )


class StrategyConfig(BaseModel):
    """Entry/exit rules (config/strategy.yaml)."""

    default_risk_per_trade_pct: float = 0.5
    stop_atr_multiple: float = 1.0
    target_atr_multiple: float = 2.0
    trailing_stop_atr_multiple: float = 1.5
    enable_trailing_stop: bool = True
    min_confidence: float = 0.4


class RiskConfig(BaseModel):
    """Risk limits (config/risk.yaml)."""

    max_daily_loss_pct: float = 1.0
    max_per_trade_risk_pct: float = 0.5
    max_total_open_risk_pct: float = 2.0
    max_long_exposure_pct: float = 80.0
    min_cash_reserve_pct: float = 20.0
    allow_market_orders: bool = False
    require_approval_per_trade: bool = True


class ReportingConfig(BaseModel):
    """Reporting/artifact output rules (config/reporting.yaml)."""

    reports_dir: str = "reports/sessions"
    artifacts_dir: str = "data/backtests"
    memory_dir: str = "data/memory"
    write_jsonl: bool = True
    write_parquet: bool = True


class BacktestConfig(BaseModel):
    """Backtest engine assumptions (config/backtest.yaml)."""

    data_dir: str = "data/curated"
    slippage_bps: float = 5.0
    commission_per_share: float = 0.0
    fill_on: str = "next_open"  # "next_open" or "same_close"
    max_holding_days: int = 5
    starting_cash: float = 100_000


class RootConfig(BaseModel):
    """Aggregate of all typed configs, as loaded from config/*.yaml."""

    app: AppConfig = Field(default_factory=AppConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    reporting: ReportingConfig = Field(default_factory=ReportingConfig)
    backtest: BacktestConfig = Field(default_factory=BacktestConfig)
