"""
Tests for OrchestratorAgent — refactored architecture.

The refactored OrchestratorAgent uses ``get_service("openai")`` to obtain the
OpenAI client.  Tests mock ``services.get_service`` so that the agent receives
a controlled client.
"""
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from agents.core import AgentStatus
from agents.specialized.orchestrator_agent import OrchestratorAgent


def _mock_openai_service(client):
    """Create a mock openai service wrapper that exposes *client*."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.client = client
    return svc


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_returns_chat_when_client_missing():
    """Test execute fallback when OpenAI client is unavailable."""
    svc = _mock_openai_service(client=None)

    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("hello", {})

    assert result.response == "chat"
    assert result.data["agent"] == "chat"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_returns_allowed_decision():
    """Test execute returns valid orchestrator decision."""
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message = Mock()
    response.choices[0].message.content = '{"agent": "weather", "reason": "weather query"}'

    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=response)

    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("what is the weather?", {})

    assert result.response == "weather"
    assert result.data["agent"] == "weather"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_invalid_decision_fallback():
    """Test execute falls back to chat on invalid decision."""
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message = Mock()
    response.choices[0].message.content = "invalid_agent"

    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=response)

    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("route this", {})

    assert result.response == "chat"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_exception_fallback():
    """Test execute falls back to chat on exception."""
    client = Mock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))

    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("route this", {})

    assert result.response == "chat"
    assert result.status == AgentStatus.ERROR


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_no_openai_service():
    """Covers lines 92-99: OpenAI service not registered."""
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=None):
        result = await agent.execute("hello", {})
    assert result.response == "chat"
    assert result.status == AgentStatus.ERROR
    assert "not registered" in (result.error or "")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_service_init_failure():
    """Covers lines 102-106: OpenAI service fails to initialize."""
    svc = AsyncMock()
    svc.is_initialized = Mock(return_value=False)
    svc.initialize = AsyncMock(side_effect=RuntimeError("init failed"))
    svc.client = None
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("hello", {})
    assert result.response == "chat"
    assert result.status == AgentStatus.ERROR


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_empty_choices():
    """Covers lines 138-139: OpenAI returns empty choices list."""
    response = Mock()
    response.choices = []
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=response)
    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("hello", {})
    assert result.response == "chat"
    assert result.data["reason"] == "Empty OpenAI response"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_unknown_agent_fallback():
    """Covers lines 153-156: agent not in ALLOWED_AGENTS."""
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message.content = '{"agent": "nonexistent_agent", "reason": "test"}'
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=response)
    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("do something", {})
    assert result.response == "chat"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_voice_transcription_override():
    """Covers lines 160-172: voice->chat override for transcription keywords."""
    response = Mock()
    response.choices = [Mock()]
    response.choices[0].message.content = '{"agent": "voice", "reason": "voice request"}'
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=response)
    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("transcrever o meu áudio", {})
    assert result.response == "chat"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_execute_validation_error():
    """Covers lines 198-199: Pydantic validation error."""
    response = Mock()
    response.choices = [Mock()]
    # Valid JSON but missing required 'agent' field
    response.choices[0].message.content = '{"wrong_field": "test"}'
    client = Mock()
    client.chat.completions.create = AsyncMock(return_value=response)
    svc = _mock_openai_service(client)
    agent = OrchestratorAgent()
    with patch("agents.specialized.orchestrator_agent.get_service", return_value=svc):
        result = await agent.execute("route this", {})
    assert result.response == "chat"
    assert result.status == AgentStatus.ERROR
