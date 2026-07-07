"""Domain enumerations."""

from enum import Enum


class Phase(str, Enum):
    """Market phase enum."""

    PREMARKET = "premarket"
    OPEN = "open"
    MIDDAY = "midday"
    POWER_HOUR = "power_hour"
    END_OF_DAY = "end_of_day"
    CLOSED = "closed"


class OperatingMode(str, Enum):
    """System operating mode."""

    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class OrderType(str, Enum):
    """Order type."""

    LIMIT = "limit"
    MARKET = "market"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderSide(str, Enum):
    """Order direction."""

    BUY = "buy"
    SELL = "sell"


class OrderStatus(str, Enum):
    """Order lifecycle status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalStatus(str, Enum):
    """Trade plan approval status."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    BLOCKED = "blocked"


class SessionStatus(str, Enum):
    """Session execution status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"
