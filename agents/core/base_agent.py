"""
Base Agent for CAPIVAREX Bot - Refactored Architecture.

Provides:
- Abstract base class for all agents
- Standardized logging and error handling
- Metrics and monitoring hooks
- Input/output validation
- Lifecycle management
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
from enum import Enum


class AgentStatus(Enum):
    """Agent execution status."""
    SUCCESS = "success"
    ERROR = "error"
    PARTIAL = "partial"
    TIMEOUT = "timeout"


class AgentResponse:
    """Standardized agent response."""

    def __init__(
        self,
        status: AgentStatus,
        response: str = "",
        data: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        message: Optional[str] = None,
    ):
        """Create an agent response with the given status and payload."""
        self.status = status
        self.response = message if message is not None else response
        self.data = data or {}
        self.error = error
        self.metadata = metadata or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def message(self) -> str:
        """Alias for response — used by agents that prefer 'message' naming."""
        return self.response

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "status": self.status.value,
            "response": self.response,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
            "timestamp": self.timestamp
        }

    def is_success(self) -> bool:
        """Check if response is successful."""
        return self.status == AgentStatus.SUCCESS


class BaseAgent(ABC):
    """
    Abstract base class for all agents.

    All agents must inherit from this class and implement the execute() method.
    Provides standardized logging, error handling, and monitoring.
    """

    def __init__(self, name: str, description: str):
        """
        Initialize the agent.

        Args:
            name: Agent name (e.g., "calendar", "weather")
            description: Human-readable description
        """
        self.name = name
        self.description = description
        self.logger = logging.getLogger(f"capivarex.agents.{name}")
        self._execution_count = 0
        self._error_count = 0

    @abstractmethod
    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Execute the agent's main logic.

        Args:
            prompt: User's input prompt
            context: Execution context (tenant_id, user_id, etc.)

        Returns:
            AgentResponse with status, response text, and optional data
        """

    async def process(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Process a request with full lifecycle management.

        This method wraps execute() with:
        - Pre-execution validation
        - Logging and monitoring
        - Error handling
        - Post-execution cleanup

        Args:
            prompt: User's input prompt
            context: Execution context

        Returns:
            AgentResponse
        """
        self._execution_count += 1
        start_time = datetime.now(timezone.utc)

        try:
            # Pre-execution hook
            await self._before_execute(prompt, context)

            # Validate input
            validation_error = self._validate_input(prompt, context)
            if validation_error:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=f"Invalid input: {validation_error}",
                    error=validation_error
                )

            # Execute agent logic
            self.logger.info(
                f"Executing {self.name} agent",
                extra={
                    "prompt_length": len(prompt),
                    "tenant_id": context.get("tenant_id"),
                    "user_id": context.get("user_id")
                }
            )

            response = await self.execute(prompt, context)

            # Post-execution hook
            await self._after_execute(response, context)

            # Log execution time
            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            self.logger.info(
                f"{self.name} agent completed",
                extra={
                    "duration_seconds": duration,
                    "status": response.status.value
                }
            )

            return response

        except Exception as e:
            self._error_count += 1
            self.logger.error(
                f"{self.name} agent failed",
                exc_info=True,
                extra={
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                }
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"I encountered an error: {str(e)}",
                error=str(e),
                metadata={"error_type": type(e).__name__}
            )

    def _validate_input(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> Optional[str]:
        """
        Validate input parameters.

        Args:
            prompt: User's input prompt
            context: Execution context

        Returns:
            Error message if validation fails, None otherwise
        """
        if not prompt or not prompt.strip():
            return "Prompt cannot be empty"

        if not isinstance(context, dict):
            return "Context must be a dictionary"

        # Subclasses can override for custom validation
        return None

    async def _before_execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ):
        """
        Hook called before execute().

        Subclasses can override for custom pre-processing.
        """

    async def _after_execute(
        self,
        response: AgentResponse,
        context: Dict[str, Any]
    ):
        """
        Hook called after execute().

        Subclasses can override for custom post-processing.
        """

    def get_capabilities(self) -> List[str]:
        """
        Get list of agent capabilities.

        Subclasses should override to provide specific capabilities.

        Returns:
            List of capability strings
        """
        return []

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get agent execution metrics.

        Returns:
            Dictionary with metrics
        """
        return {
            "name": self.name,
            "execution_count": self._execution_count,
            "error_count": self._error_count,
            "error_rate": (
                self._error_count / self._execution_count
                if self._execution_count > 0
                else 0.0
            )
        }

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return f"<{self.__class__.__name__}(name='{self.name}')>"
