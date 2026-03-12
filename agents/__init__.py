"""
Agents Refactored Package

This package contains all refactored agents following best practices:
- Inheritance from BaseAgent
- Async/await support
- Lifecycle management
- Type hints
- Comprehensive logging
- Error handling

Author: CAPIVAREX Team
"""

# Core infrastructure (BaseAgent, registry, response types)
from .core import (
    BaseAgent,
    AgentResponse,
    AgentStatus,
    AgentRegistry,
    registry,
    register_agent,
    get_agent,
    list_agents,
)

# Specialized agents — importing triggers @register_agent decorators
from .specialized import (
    OrchestratorAgent,
    ChatAgent,
    WeatherAgent,
    ResearchAgent,
    FinanceAgent,
    DevAgent,
    ImageAgent,
    VideoAgent,
    VoiceAgent,
    CalendarAgent,
    TrafficAgent,
    CarAgent,
    SmartHomeAgent,
    GitHubAgent,
    TransportAgent,
    TravelAgent,
)

__all__ = [
    # Core infrastructure
    "BaseAgent",
    "AgentResponse",
    "AgentStatus",
    "AgentRegistry",
    "registry",
    "register_agent",
    "get_agent",
    "list_agents",
    # Specialized agents
    "OrchestratorAgent",
    "ChatAgent",
    "WeatherAgent",
    "ResearchAgent",
    "FinanceAgent",
    "DevAgent",
    "ImageAgent",
    "VideoAgent",
    "VoiceAgent",
    "CalendarAgent",
    "TrafficAgent",
    "CarAgent",
    "SmartHomeAgent",
    "GitHubAgent",
    "TransportAgent",
    "TravelAgent",
]
