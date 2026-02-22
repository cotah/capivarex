"""Unit tests for AgentRegistry."""

import pytest
from agents.core.base_agent import BaseAgent, AgentResponse, AgentStatus
from agents.core.agent_registry import AgentRegistry


class _DummyAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="dummy", description="dummy agent")

    async def execute(self, prompt, context):
        return AgentResponse(status=AgentStatus.SUCCESS, response="ok")


class _NotAnAgent:
    """Not a BaseAgent subclass."""


@pytest.fixture
def fresh_registry():
    """Return a fresh AgentRegistry (bypass singleton for isolation)."""
    reg = object.__new__(AgentRegistry)
    reg._agents = {}
    reg._agent_classes = {}
    reg._initialized = True
    return reg


class TestAgentRegistryRegister:
    def test_register_lazy(self, fresh_registry):
        fresh_registry.register("dummy", _DummyAgent, lazy=True)
        assert "dummy" in fresh_registry.list_agents()
        # Not yet instantiated
        assert "dummy" not in fresh_registry._agents

    def test_register_eager(self, fresh_registry):
        fresh_registry.register("dummy", _DummyAgent, lazy=False)
        assert "dummy" in fresh_registry._agents

    def test_register_non_agent_raises(self, fresh_registry):
        with pytest.raises(TypeError):
            fresh_registry.register("bad", _NotAnAgent, lazy=True)


class TestAgentRegistryGet:
    def test_get_lazy_loads(self, fresh_registry):
        fresh_registry.register("dummy", _DummyAgent, lazy=True)
        agent = fresh_registry.get("dummy")
        assert isinstance(agent, _DummyAgent)
        # Second call returns same instance
        assert fresh_registry.get("dummy") is agent

    def test_get_missing_returns_none(self, fresh_registry):
        assert fresh_registry.get("nonexistent") is None


class TestAgentRegistryOther:
    def test_list_agents(self, fresh_registry):
        fresh_registry.register("a", _DummyAgent)
        fresh_registry.register("b", _DummyAgent)
        assert sorted(fresh_registry.list_agents()) == ["a", "b"]

    def test_clear(self, fresh_registry):
        fresh_registry.register("a", _DummyAgent, lazy=False)
        fresh_registry.clear()
        assert fresh_registry.list_agents() == []
        assert fresh_registry._agents == {}

    def test_get_all_metrics(self, fresh_registry):
        fresh_registry.register("dummy", _DummyAgent, lazy=False)
        metrics = fresh_registry.get_all_metrics()
        assert "dummy" in metrics
        assert metrics["dummy"]["name"] == "dummy"
