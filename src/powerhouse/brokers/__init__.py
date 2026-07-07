"""Broker adapter boundary - paper-only in this phase, never live.

See `docs/architecture.md` and `docs/risk-policy.md` for the safety model:
execution stays gated behind `ExecutionPolicy.allow_execution` regardless of
which broker is wired in, and no broker in this repo performs network I/O.
"""

from .base import Broker, BrokerPosition
from .paper import PaperBroker

__all__ = ["Broker", "BrokerPosition", "PaperBroker"]
