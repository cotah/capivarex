"""Unit tests for BaseAgent, AgentResponse, and AgentStatus."""

import pytest
from agents.core.base_agent import BaseAgent, AgentResponse, AgentStatus


# -- Concrete agent for testing the abstract base class --


class _StubAgent(BaseAgent):
    """Minimal concrete agent for testing BaseAgent behaviour."""

    def __init__(self, fail=False):
        super().__init__(name="stub", description="test agent")
        self._fail = fail

    async def execute(self, prompt, context):
        if self._fail:
            raise RuntimeError("boom")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"echo:{prompt}",
            data={"key": "value"},
        )


# -- AgentResponse --


class TestAgentResponse:
    def test_is_success_true(self):
        r = AgentResponse(status=AgentStatus.SUCCESS, response="ok")
        assert r.is_success() is True

    def test_is_success_false_for_error(self):
        r = AgentResponse(status=AgentStatus.ERROR, response="fail", error="e")
        assert r.is_success() is False

    def test_to_dict_structure(self):
        r = AgentResponse(
            status=AgentStatus.PARTIAL,
            response="partial",
            data={"x": 1},
            error="warn",
            metadata={"m": True},
        )
        d = r.to_dict()
        assert d["status"] == "partial"
        assert d["response"] == "partial"
        assert d["data"] == {"x": 1}
        assert d["error"] == "warn"
        assert d["metadata"] == {"m": True}
        assert "timestamp" in d

    def test_defaults(self):
        r = AgentResponse(status=AgentStatus.TIMEOUT, response="t")
        assert r.data == {}
        assert r.error is None
        assert r.metadata == {}


# -- AgentStatus --


class TestAgentStatus:
    def test_values(self):
        assert AgentStatus.SUCCESS.value == "success"
        assert AgentStatus.ERROR.value == "error"
        assert AgentStatus.PARTIAL.value == "partial"
        assert AgentStatus.TIMEOUT.value == "timeout"


# -- BaseAgent.process lifecycle --


class TestBaseAgentProcess:
    @pytest.mark.asyncio
    async def test_process_success(self):
        agent = _StubAgent()
        result = await agent.process("hello", {"user_id": "u1"})
        assert result.is_success()
        assert result.response == "echo:hello"
        assert agent._execution_count == 1
        assert agent._error_count == 0

    @pytest.mark.asyncio
    async def test_process_catches_exception(self):
        agent = _StubAgent(fail=True)
        result = await agent.process("hi", {})
        assert result.status == AgentStatus.ERROR
        assert "boom" in result.response
        assert agent._error_count == 1

    @pytest.mark.asyncio
    async def test_process_rejects_empty_prompt(self):
        agent = _StubAgent()
        result = await agent.process("", {})
        assert result.status == AgentStatus.ERROR
        assert "empty" in result.response.lower()

    @pytest.mark.asyncio
    async def test_process_rejects_bad_context(self):
        agent = _StubAgent()
        result = await agent.process("hello", "not_a_dict")
        assert result.status == AgentStatus.ERROR
        assert "dictionary" in result.response.lower()


# -- BaseAgent utilities --


class TestBaseAgentUtilities:
    def test_get_capabilities_default_empty(self):
        agent = _StubAgent()
        assert agent.get_capabilities() == []

    def test_get_metrics(self):
        agent = _StubAgent()
        m = agent.get_metrics()
        assert m["name"] == "stub"
        assert m["execution_count"] == 0
        assert m["error_count"] == 0
        assert m["error_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_metrics_after_calls(self):
        agent = _StubAgent()
        await agent.process("a", {})
        await agent.process("b", {})
        m = agent.get_metrics()
        assert m["execution_count"] == 2
        assert m["error_rate"] == 0.0
