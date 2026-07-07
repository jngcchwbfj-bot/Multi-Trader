"""Pydantic domain models."""

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import (
    ApprovalStatus,
    OperatingMode,
    OrderSide,
    OrderStatus,
    OrderType,
    Phase,
    SessionStatus,
)


def _utc_now() -> datetime:
    """Get current UTC time."""
    return datetime.now(timezone.utc)


class ExecutionPolicy(BaseModel):
    """Controls what execution is permitted."""

    allow_execution: bool = False
    mode: OperatingMode = OperatingMode.BACKTEST
    max_daily_loss_pct: float = 1.0
    max_per_trade_risk_pct: float = 0.5
    max_total_open_risk_pct: float = 2.0
    max_long_exposure_pct: float = 80.0
    min_cash_reserve_pct: float = 20.0
    allow_market_orders: bool = False
    require_approval_per_trade: bool = True


class Portfolio(BaseModel):
    """Current portfolio state."""

    account_value: Decimal = Decimal("100000")
    cash: Decimal = Decimal("100000")
    positions: dict[str, int] = Field(default_factory=dict)
    buying_power: Decimal = Decimal("100000")
    realized_pnl_today: Decimal = Decimal("0")
    open_risk_amount: Decimal = Decimal("0")

    def get_long_exposure_pct(self) -> float:
        """Calculate total long exposure as % of account value."""
        if self.account_value == 0:
            return 0.0
        return float((self.account_value - self.cash) / self.account_value * 100)

    def get_cash_reserve_pct(self) -> float:
        """Calculate cash reserve as % of account value."""
        if self.account_value == 0:
            return 100.0
        return float(self.cash / self.account_value * 100)

    def get_daily_loss_pct(self) -> float:
        """Calculate today's realized loss as a positive % of account value (0 if profitable)."""
        if self.account_value == 0:
            return 0.0
        loss = -self.realized_pnl_today
        if loss <= 0:
            return 0.0
        return float(loss / self.account_value * 100)

    def get_open_risk_pct(self) -> float:
        """Calculate total open risk (sum of per-trade risk on open plans) as % of account value."""
        if self.account_value == 0:
            return 0.0
        return float(self.open_risk_amount / self.account_value * 100)


class Candidate(BaseModel):
    """A ticker candidate for trading consideration."""

    ticker: str
    price: Decimal
    market_cap: Optional[Decimal] = None
    relevance_score: float = 0.5
    reason: str = "Candidate identified"
    added_at: datetime = Field(default_factory=_utc_now)


class CatalystSummary(BaseModel):
    """Catalyst and news context for a candidate."""

    ticker: str
    catalyst_type: str  # "earnings", "news", "technical", "macro"
    summary: str
    sentiment: str  # "bullish", "neutral", "bearish"
    confidence: float
    added_at: datetime = Field(default_factory=_utc_now)


class TradePlan(BaseModel):
    """A proposed trade with entry, exit, and rationale."""

    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    ticker: str
    side: OrderSide
    entry_price: Decimal
    stop_loss_price: Decimal
    target_price: Decimal
    quantity: int = 1
    rationale: str
    risk_per_trade_pct: float = 0.5
    confidence: float = 0.5
    trailing_stop_pct: Optional[float] = None
    trailing_stop_activation_price: Optional[Decimal] = None
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approval_reason: str = ""
    created_at: datetime = Field(default_factory=_utc_now)

    def get_risk_amount(self, account_value: Decimal) -> Decimal:
        """Calculate risk amount in dollars."""
        if self.side == OrderSide.BUY:
            risk = abs(self.entry_price - self.stop_loss_price) * self.quantity
        else:
            risk = abs(self.stop_loss_price - self.entry_price) * self.quantity
        return risk

    def get_reward_amount(self, account_value: Decimal) -> Decimal:
        """Calculate reward amount in dollars."""
        if self.side == OrderSide.BUY:
            reward = abs(self.target_price - self.entry_price) * self.quantity
        else:
            reward = abs(self.entry_price - self.target_price) * self.quantity
        return reward


class Order(BaseModel):
    """An execution order."""

    order_id: str = Field(default_factory=lambda: str(uuid4()))
    ticker: str
    side: OrderSide
    order_type: OrderType
    quantity: int
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    filled_price: Optional[Decimal] = None
    created_at: datetime = Field(default_factory=_utc_now)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None


class RiskDecision(BaseModel):
    """Risk layer's decision on a trade plan."""

    plan_id: str
    ticker: str
    approved: bool
    reason: str
    adjusted_quantity: int
    daily_loss_check_passed: bool
    exposure_check_passed: bool
    per_trade_risk_check_passed: bool
    total_open_risk_check_passed: bool = True
    decided_at: datetime = Field(default_factory=_utc_now)


class TradeEventType(str, Enum):
    """Structured execution simulator event types."""

    PENDING_ENTRY = "pending_entry"
    FILLED = "filled"
    STOP_HIT = "stop_hit"
    TARGET_HIT = "target_hit"
    TRAILING_STOP_UPDATED = "trailing_stop_updated"
    NO_FILL = "no_fill"
    MANUAL_CLOSE = "manual_close"


class TradeEvent(BaseModel):
    """A structured event emitted by the execution simulator."""

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    trade_id: str
    plan_id: str
    ticker: str
    event_type: TradeEventType
    price: Optional[Decimal] = None
    quantity: Optional[int] = None
    timestamp: datetime = Field(default_factory=_utc_now)
    details: dict[str, Any] = Field(default_factory=dict)


class ExecutedTrade(BaseModel):
    """A completed (or in-progress) simulated trade execution."""

    trade_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ticker: str
    side: OrderSide
    entry_price: Decimal
    quantity: int
    entry_timestamp: datetime
    stop_loss_price: Decimal
    target_price: Decimal
    trailing_stop_price: Optional[Decimal] = None
    outcome: str = "pending"  # pending, filled, stop_hit, target_hit, no_fill, manual_close
    closed: bool = False
    exit_price: Optional[Decimal] = None
    exit_timestamp: Optional[datetime] = None
    pnl: Optional[Decimal] = None
    events: list[TradeEvent] = Field(default_factory=list)


class SessionContext(BaseModel):
    """Input context for a trading session."""

    session_id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=_utc_now)
    phase: Phase
    mode: OperatingMode = OperatingMode.BACKTEST
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    portfolio: Portfolio = Field(default_factory=Portfolio)


class SessionReport(BaseModel):
    """Output report for a trading session."""

    session_id: str = ""
    status: SessionStatus = SessionStatus.PENDING
    phase: Phase = Phase.CLOSED
    timestamp: datetime = Field(default_factory=_utc_now)
    duration_seconds: float = 0.0
    candidates_found: int = 0
    trade_plans_proposed: int = 0
    trade_plans_approved: int = 0
    trade_plans_rejected: int = 0
    trades_executed: int = 0
    total_pnl: Optional[Decimal] = None
    error_message: Optional[str] = None
    markdown_report: str = ""
    created_at: datetime = Field(default_factory=_utc_now)


class SessionResult(BaseModel):
    """Complete result of a session run."""

    status: SessionStatus
    candidates: list[Candidate] = Field(default_factory=list)
    catalysts: list[CatalystSummary] = Field(default_factory=list)
    trade_plans: list[TradePlan] = Field(default_factory=list)
    risk_decisions: list[RiskDecision] = Field(default_factory=list)
    executed_trades: list[ExecutedTrade] = Field(default_factory=list)
    report: SessionReport = Field(default_factory=SessionReport)
    logs: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class LogEntry(BaseModel):
    """A structured log entry."""

    timestamp: datetime = Field(default_factory=_utc_now)
    level: str  # INFO, WARNING, ERROR
    event_type: str
    session_id: str
    details: dict[str, Any] = Field(default_factory=dict)


class BacktestMetrics(BaseModel):
    """Summary performance metrics for a completed backtest run."""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: Decimal = Decimal("0")
    gross_profit: Decimal = Decimal("0")
    gross_loss: Decimal = Decimal("0")
    profit_factor: Optional[float] = None
    max_drawdown_pct: float = 0.0
    ending_account_value: Decimal = Decimal("0")
    starting_account_value: Decimal = Decimal("0")
    return_pct: float = 0.0


class BacktestResult(BaseModel):
    """Complete result of a historical backtest replay."""

    backtest_id: str = Field(default_factory=lambda: str(uuid4()))
    symbols: list[str] = Field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    trade_plans: list[TradePlan] = Field(default_factory=list)
    risk_decisions: list[RiskDecision] = Field(default_factory=list)
    executed_trades: list[ExecutedTrade] = Field(default_factory=list)
    metrics: BacktestMetrics = Field(default_factory=BacktestMetrics)
    equity_curve: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
