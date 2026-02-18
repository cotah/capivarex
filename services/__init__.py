"""
Services Package — CapivaraX Bot

Re-exports core utilities so callers can use::

    from services import get_service
    from services import BaseService
"""

# Core infrastructure (service registry, base class, helpers)
from .core import (
    BaseService,
    ServiceStatus,
    ServiceError,
    ServiceUnavailableError,
    ServiceConfigurationError,
    retry_on_failure,
    ServiceRegistry,
    registry,
    register_service,
    get_service,
    list_services,
)

__all__ = [
    # Core
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
