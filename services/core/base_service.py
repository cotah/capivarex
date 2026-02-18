"""
Base Service for CapivaraX Bot - Refactored Architecture.

Provides:
- Abstract base class for all services
- Standardized logging and error handling
- Retry logic with exponential backoff
- Health checks
- Metrics tracking
"""

import asyncio
import logging
import time
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
    pass


class ServiceUnavailableError(ServiceError):
    """Raised when service is unavailable."""
    pass


class ServiceConfigurationError(ServiceError):
    """Raised when service configuration is invalid."""
    pass


def retry_on_failure(
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """
    Decorator for retrying failed operations with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_factor: Multiplier for delay between retries
        exceptions: Tuple of exceptions to catch
    """
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            last_exception = None
            delay = 1.0

            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
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
        self.logger = logging.getLogger(f"capivarax.services.{name}")
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
                f"Failed to initialize {self.name} service: {e}",
                exc_info=True
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
        pass

    async def health_check(self) -> ServiceStatus:
        """
        Check service health.

        Returns:
            ServiceStatus enum value
        """
        try:
            is_healthy = await self._health_check()
            self._status = ServiceStatus.HEALTHY if is_healthy else ServiceStatus.DEGRADED
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
        pass

    def get_metrics(self) -> Dict[str, Any]:
        """
        Get service metrics.

        Returns:
            Dictionary with metrics
        """
        avg_latency = (
            self._total_latency / self._call_count
            if self._call_count > 0
            else 0.0
        )

        error_rate = (
            self._error_count / self._call_count
            if self._call_count > 0
            else 0.0
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
        return f"<{self.__class__.__name__}(name='{self.name}', status='{self._status.value}')>"
