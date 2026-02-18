"""
Service Registry for CapivaraX Bot.

Provides:
- Service discovery and registration
- Lazy loading of services
- Dependency injection
- Service lifecycle management
"""

import logging
from typing import Dict, Optional, Type, List
from .base_service import BaseService, ServiceStatus


logger = logging.getLogger("capivarax.services.registry")


class ServiceRegistry:
    """
    Registry for managing all services in the system.

    Implements:
    - Singleton pattern for global access
    - Lazy loading for performance
    - Type-safe service registration
    """

    _instance: Optional['ServiceRegistry'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._services: Dict[str, BaseService] = {}
        self._service_classes: Dict[str, Type[BaseService]] = {}
        self._initialized = True
        logger.info("ServiceRegistry initialized")

    def register(
        self,
        name: str,
        service_class: Type[BaseService],
        lazy: bool = True
    ):
        """
        Register a service class.

        Args:
            name: Service name (e.g., "openai", "calendar")
            service_class: Service class (must inherit from BaseService)
            lazy: If True, instantiate only when first accessed
        """
        if not issubclass(service_class, BaseService):
            raise TypeError(f"{service_class} must inherit from BaseService")

        self._service_classes[name] = service_class

        if not lazy:
            self._services[name] = service_class(name=name)

        logger.info(f"Registered service: {name} (lazy={lazy})")

    def get(self, name: str) -> Optional[BaseService]:
        """
        Get a service by name.

        Args:
            name: Service name

        Returns:
            Service instance or None if not found
        """
        # Check if already instantiated
        if name in self._services:
            return self._services[name]

        # Check if registered for lazy loading
        if name in self._service_classes:
            service_class = self._service_classes[name]
            self._services[name] = service_class(name=name)
            logger.info(f"Lazy-loaded service: {name}")
            return self._services[name]

        logger.warning(f"Service not found: {name}")
        return None

    def list_services(self) -> List[str]:
        """
        List all registered service names.

        Returns:
            List of service names
        """
        return list(self._service_classes.keys())

    def get_all_metrics(self) -> Dict[str, Dict]:
        """
        Get metrics for all instantiated services.

        Returns:
            Dictionary mapping service names to their metrics
        """
        return {
            name: service.get_metrics()
            for name, service in self._services.items()
        }

    async def health_check_all(self) -> Dict[str, ServiceStatus]:
        """
        Run health checks on all instantiated services.

        Returns:
            Dictionary mapping service names to their status
        """
        results = {}
        for name, service in self._services.items():
            try:
                status = await service.health_check()
                results[name] = status
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                results[name] = ServiceStatus.UNHEALTHY

        return results

    def clear(self):
        """Clear all registered services (useful for testing)."""
        self._services.clear()
        self._service_classes.clear()
        logger.info("ServiceRegistry cleared")


# Global registry instance
registry = ServiceRegistry()


def register_service(name: str, lazy: bool = True):
    """
    Decorator for registering services.

    Usage:
        @register_service("openai")
        class OpenAIService(BaseService):
            ...

    Args:
        name: Service name
        lazy: If True, instantiate only when first accessed
    """
    def decorator(service_class: Type[BaseService]):
        registry.register(name, service_class, lazy=lazy)
        return service_class
    return decorator


def get_service(name: str) -> Optional[BaseService]:
    """
    Get a service by name from the global registry.

    Args:
        name: Service name

    Returns:
        Service instance or None
    """
    return registry.get(name)


def list_services() -> List[str]:
    """
    List all registered service names.

    Returns:
        List of service names
    """
    return registry.list_services()
