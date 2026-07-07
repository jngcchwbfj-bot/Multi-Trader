"""Pydantic domain models."""

from datetime import datetime, timezone
from typing import Any, Optional
from decimal import Decimal
from uuid import uuid4

from pydantic import BaseModel, Field

from .enums import (
    ApprovalStatus,
    OrderSide,
    OrderStatus,
    OrderType,
    OperatingMode,
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
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approval_reason: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

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
    created_at: datetime = Field(default_factory=datetime.utcnow)
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
    decided_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutedTrade(BaseModel):
    """A completed trade execution."""

    trade_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    ticker: str
    side: OrderSide
    entry_price: Decimal
    quantity: int
    entry_timestamp: datetime
    stop_loss_price: Decimal
    target_price: Decimal
    closed: bool = False
    exit_price: Optional[Decimal] = None
    exit_timestamp: Optional[datetime] = None
    pnl: Optional[Decimal] = None


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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    duration_seconds: float = 0.0
    candidates_found: int = 0
    trade_plans_proposed: int = 0
    trade_plans_approved: int = 0
    trade_plans_rejected: int = 0
    trades_executed: int = 0
    total_pnl: Optional[Decimal] = None
    error_message: Optional[str] = None
    markdown_report: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


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

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    level: str  # INFO, WARNING, ERROR
    event_type: str
    session_id: str
    details: dict[str, Any] = Field(default_factory=dict)
