"""
Base Service for CAPIVAREX Bot - Refactored Architecture.

Provides:
- Abstract base class for all services
- Standardized logging and error handling
- Retry logic with exponential backoff
- Health checks
- Metrics tracking
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, Callable
from enum import Enum
from functools import wraps


class ServiceStatus(Enum):
    """Service health status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class ServiceError(Exception):
    """Base exception for service errors."""


class ServiceUnavailableError(ServiceError):
    """Raised when service is unavailable."""


class ServiceConfigurationError(ServiceError):
    """Raised when service configuration is invalid."""


def _is_retryable(exc: Exception) -> bool:
    """
    Determine if an exception is worth retrying.

    Retries on:
    - Timeout errors (asyncio.TimeoutError, httpx.TimeoutException)
    - Server errors (HTTP 5xx)
    - Rate limit errors (HTTP 429)

    Does NOT retry on:
    - Client errors (HTTP 4xx except 429)
    - Any other exception type
    """
    # Always retry on timeout
    if isinstance(exc, (asyncio.TimeoutError,)):
        return True

    # Check for httpx exceptions (imported lazily to avoid hard dependency)
    exc_class_name = type(exc).__name__

    if exc_class_name == "TimeoutException":
        return True

    if exc_class_name == "HTTPStatusError":
        status_code = getattr(getattr(exc, "response", None), "status_code", None)
        if status_code is not None:
            # Retry on 429 (rate limited) and 5xx (server errors)
            if status_code == 429 or status_code >= 500:
                return True
            # Do NOT retry on other 4xx (client errors)
            return False

    return False


def retry_on_failure(
    max_retries: int = 3, backoff_factor: float = 2.0, exceptions: tuple = (Exception,)
):
    """
    Decorator for retrying failed operations with exponential backoff.

    Only retries on transient errors (timeouts, 5xx, 429).
    Raises immediately on client errors (4xx except 429) and
    other non-retryable exceptions.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch
    """

    def decorator(func: Callable):
        """Register *cls* and return it unchanged."""

        @wraps(func)
        async def wrapper(*args, **kwargs):
            """Execute *func* with retry and exponential back-off on transient errors."""
            last_exception = None
            delay = 1.0

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    # Check if the error is retryable
                    if not _is_retryable(e):
                        raise

                    last_exception = e
                    if attempt < max_retries:
                        logger = logging.getLogger("capivarex.services.retry")
                        logger.warning(
                            "Attempt %d/%d failed for %s: %s. Retrying in %.1fs...",
                            attempt + 1,
                            max_retries,
                            func.__name__,
                            e,
                            delay,
                        )
                        await asyncio.sleep(delay)
                        delay *= backoff_factor
                    else:
                        raise

            raise last_exception

        return wrapper

    return decorator


class BaseService(ABC):
    """
    Abstract base class for all services.

    Provides:
    - Standardized initialization
    - Logging infrastructure
    - Health checking
    - Metrics tracking
    - Error handling patterns
    """

    def __init__(self, name: str, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the service.

        Args:
            name: Service name (e.g., "openai", "calendar")
            config: Optional configuration dictionary
        """
        self.name = name
        self.config = config or {}
        self.logger = logging.getLogger(f"capivarex.services.{name}")
        self._status = ServiceStatus.UNKNOWN
        self._initialized = False
        self._call_count = 0
        self._error_count = 0
        self._total_latency = 0.0

    async def initialize(self):
        """
        Initialize the service.

        Override this method to perform service-specific initialization
        (e.g., connecting to APIs, loading credentials).
        """
        if self._initialized:
            self.logger.warning(f"{self.name} service already initialized")
            return

        try:
            await self._initialize()
            self._initialized = True
            self._status = ServiceStatus.HEALTHY
            self.logger.info(f"{self.name} service initialized successfully")
        except Exception as e:
            self._status = ServiceStatus.UNHEALTHY
            self.logger.error(
                f"Failed to initialize {self.name} service: {e}", exc_info=True
            )
            raise ServiceConfigurationError(
                f"Failed to initialize {self.name}: {e}"
            ) from e

    @abstractmethod
    async def _initialize(self):
        """
        Service-specific initialization logic.

        Override this method in subclasses.
        """

    async def health_check(self) -> ServiceStatus:
        """
        Check service health.

        Returns:
            ServiceStatus enum value
        """
        try:
            is_healthy = await self._health_check()
            self._status = (
                ServiceStatus.HEALTHY if is_healthy else ServiceStatus.DEGRADED
            )
        except Exception as e:
            self.logger.error(f"Health check failed for {self.name}: {e}")
            self._status = ServiceStatus.UNHEALTHY

        return self._status

    @abstractmethod
    async def _health_check(self) -> bool:
        """
        Service-specific health check logic.

        Returns:
            True if healthy, False otherwise
        """

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get service metrics.

        Returns:
            Dictionary with metrics
        """
        avg_latency = (
            self._total_latency / self._call_count if self._call_count > 0 else 0.0
        )

        error_rate = (
            self._error_count / self._call_count if self._call_count > 0 else 0.0
        )

        return {
            "name": self.name,
            "status": self._status.value,
            "initialized": self._initialized,
            "call_count": self._call_count,
            "error_count": self._error_count,
            "error_rate": error_rate,
            "avg_latency_ms": avg_latency * 1000,
        }

    def _track_call(self, latency: float, error: bool = False):
        """
        Track service call metrics.

        Args:
            latency: Call latency in seconds
            error: Whether the call resulted in an error
        """
        self._call_count += 1
        self._total_latency += latency
        if error:
            self._error_count += 1

    def _get_config(self, key: str, default: Any = None, required: bool = False) -> Any:
        """
        Get configuration value.

        Args:
            key: Configuration key
            default: Default value if key not found
            required: If True, raise error if key not found

        Returns:
            Configuration value

        Raises:
            ServiceConfigurationError: If required key not found
        """
        if key not in self.config:
            if required:
                raise ServiceConfigurationError(
                    f"Required configuration '{key}' not found for {self.name} service"
                )
            return default

        return self.config[key]

    def is_initialized(self) -> bool:
        """Check if service is initialized."""
        return self._initialized

    def is_healthy(self) -> bool:
        """Check if service is healthy."""
        return self._status == ServiceStatus.HEALTHY

    def __repr__(self) -> str:
        """Return a developer-friendly representation."""
        return f"<{self.__class__.__name__}(name='{self.name}', status='{self._status.value}')>"
