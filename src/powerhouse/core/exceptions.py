"""Custom exceptions."""


class PowerhouseError(Exception):
    """Base exception for all Powerhouse errors."""

    pass


class ExecutionBlockedError(PowerhouseError):
    """Execution was blocked by policy or risk gate."""

    pass


class RiskVetoError(PowerhouseError):
    """Risk layer rejected the trade plan."""

    pass


class InvalidPlanError(PowerhouseError):
    """Trade plan violates constraints."""

    pass


class ApprovalGateError(PowerhouseError):
    """Approval gate rejected the action."""

    pass


class BrokerError(PowerhouseError):
    """Broker adapter error."""

    pass


class ConfigError(PowerhouseError):
    """Configuration error."""

    pass
