"""
Agent Registry for CAPIVAREX Bot.

Provides:
- Agent discovery and registration
- Lazy loading of agents
- Dependency injection
- Agent lifecycle management
"""

import logging
from typing import Dict, Optional, Type, List
from .base_agent import BaseAgent


logger = logging.getLogger("capivarex.agents.registry")


class AgentRegistry:
    """
    Registry for managing all agents in the system.

    Implements:
    - Singleton pattern for global access
    - Lazy loading for performance
    - Type-safe agent registration
    """

    _instance: Optional["AgentRegistry"] = None

    def __new__(cls):
        """Create or return the singleton AgentRegistry instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the registry (only runs once due to singleton guard)."""
        if self._initialized:
            return

        self._agents: Dict[str, BaseAgent] = {}
        self._agent_classes: Dict[str, Type[BaseAgent]] = {}
        self._initialized = True
        logger.info("AgentRegistry initialized")

    def register(self, name: str, agent_class: Type[BaseAgent], lazy: bool = True):
        """
        Register an agent class.

        Args:
            name: Agent name (e.g., "calendar", "weather")
            agent_class: Agent class (must inherit from BaseAgent)
            lazy: If True, instantiate only when first accessed
        """
        if not issubclass(agent_class, BaseAgent):
            raise TypeError(f"{agent_class} must inherit from BaseAgent")

        self._agent_classes[name] = agent_class

        if not lazy:
            self._agents[name] = agent_class()

        logger.info(f"Registered agent: {name} (lazy={lazy})")

    def get(self, name: str) -> Optional[BaseAgent]:
        """
        Get an agent by name.

        Args:
            name: Agent name

        Returns:
            Agent instance or None if not found
        """
        # Check if already instantiated
        if name in self._agents:
            return self._agents[name]

        # Check if registered for lazy loading
        if name in self._agent_classes:
            agent_class = self._agent_classes[name]
            self._agents[name] = agent_class()
            logger.info(f"Lazy-loaded agent: {name}")
            return self._agents[name]

        logger.warning(f"Agent not found: {name}")
        return None

    def list_agents(self) -> List[str]:
        """
        List all registered agent names.

        Returns:
            List of agent names
        """
        return list(self._agent_classes.keys())

    def get_all_metrics(self) -> Dict[str, Dict]:
        """
        Get metrics for all instantiated agents.

        Returns:
            Dictionary mapping agent names to their metrics
        """
        return {name: agent.get_metrics() for name, agent in self._agents.items()}

    def clear(self):
        """Clear all registered agents (useful for testing)."""
        self._agents.clear()
        self._agent_classes.clear()
        logger.info("AgentRegistry cleared")


# Global registry instance
registry = AgentRegistry()


def register_agent(name: str, lazy: bool = True):
    """
    Decorator for registering agents.

    Usage:
        @register_agent("calendar")
        class CalendarAgent(BaseAgent):
            ...

    Args:
        name: Agent name
        lazy: If True, instantiate only when first accessed
    """

    def decorator(agent_class: Type[BaseAgent]):
        """Register *agent_class* in the global registry and return it unchanged."""
        registry.register(name, agent_class, lazy=lazy)
        return agent_class

    return decorator


def get_agent(name: str) -> Optional[BaseAgent]:
    """
    Get an agent by name from the global registry.

    Args:
        name: Agent name

    Returns:
        Agent instance or None
    """
    return registry.get(name)


def list_agents() -> List[str]:
    """
    List all registered agent names.

    Returns:
        List of agent names
    """
    return registry.list_agents()
