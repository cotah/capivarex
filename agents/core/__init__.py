"""
Core agent infrastructure for CapivaraX Bot.

Provides:
- BaseAgent abstract class
- AgentResponse standardized response
- AgentRegistry for agent management
- AgentStatus enum
"""

from .base_agent import BaseAgent, AgentResponse, AgentStatus
from .agent_registry import (
    AgentRegistry,
    registry,
    register_agent,
    get_agent,
    list_agents
)

__all__ = [
    "BaseAgent",
    "AgentResponse",
    "AgentStatus",
    "AgentRegistry",
    "registry",
    "register_agent",
    "get_agent",
    "list_agents",
]
