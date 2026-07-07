"""Broker abstraction boundary.

`Broker` is the only surface through which order routing may happen. This
repo ships exactly one concrete implementation, `PaperBroker`
(`powerhouse.brokers.paper`), which is in-memory only and never performs
network I/O. A real brokerage integration (e.g. Robinhood) would be added in
a future phase as another `Broker` subclass, still gated behind the same
`ExecutionPolicy.allow_execution` check used today - this module does not
add any live trading capability.

`is_paper` is an abstract property (no default) so every subclass - including
any future live-broker adapter - must explicitly declare which kind of
account it represents, rather than silently inheriting a "safe" default.
"""

from abc import ABC, abstractmethod
from decimal import Decimal

from pydantic import BaseModel

from powerhouse.core.models import Order, TradePlan


class BrokerPosition(BaseModel):
    """A single open position as reported by a broker."""

    ticker: str
    quantity: int
    average_entry_price: Decimal


class Broker(ABC):
    """Abstract broker interface for routing trade plans to an account."""

    name: str = "broker"

    @property
    @abstractmethod
    def is_paper(self) -> bool:
        """True if this broker only simulates fills (no real money at risk)."""
        raise NotImplementedError

    @abstractmethod
    async def submit_order(self, plan: TradePlan) -> Order:
        """Submit a trade plan for execution. Returns the resulting order.

        Implementations must not assume forward market data is available:
        a real (or paper) broker only knows the current state at submission
        time, so an order may come back `PENDING` rather than filled.
        """
        raise NotImplementedError

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Attempt to cancel a resting order. Returns whether it was cancelled."""
        raise NotImplementedError

    @abstractmethod
    async def get_positions(self) -> dict[str, BrokerPosition]:
        """Return currently held positions, keyed by ticker."""
        raise NotImplementedError

    @abstractmethod
    async def get_cash(self) -> Decimal:
        """Return current account cash balance."""
        raise NotImplementedError

    @abstractmethod
    async def get_orders(self) -> list[Order]:
        """Return all orders known to this broker (any status)."""
        raise NotImplementedError
