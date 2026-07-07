"""Base class for specialist agents."""

from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

from powerhouse.core.models import SessionContext

T = TypeVar("T")


class BaseAgent(ABC, Generic[T]):
    """Base class for all specialist agents."""

    name: str = "BaseAgent"

    @abstractmethod
    async def run(self, context: SessionContext) -> T:
        """
        Execute the agent logic.

        Args:
            context: Session context with portfolio, mode, and execution policy.

        Returns:
            Result of the agent's work.
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name})"
