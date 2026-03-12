"""
Core service infrastructure for CAPIVAREX Bot.

Provides:
- BaseService abstract class
- ServiceRegistry for service management
- Service status and error types
- Retry decorator
"""

from .base_service import (
    BaseService,
    ServiceStatus,
    ServiceError,
    ServiceUnavailableError,
    ServiceConfigurationError,
    retry_on_failure,
)
from .service_registry import (
    ServiceRegistry,
    registry,
    register_service,
    get_service,
    list_services,
)

__all__ = [
    "BaseService",
    "ServiceStatus",
    "ServiceError",
    "ServiceUnavailableError",
    "ServiceConfigurationError",
    "retry_on_failure",
    "ServiceRegistry",
    "registry",
    "register_service",
    "get_service",
    "list_services",
]
