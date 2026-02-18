"""
Unit tests for DevAgent — code generation and programming queries.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agents.core import AgentStatus


@pytest.fixture
def dev_agent():
    from agents.specialized.dev_agent import DevAgent
    return DevAgent()


@pytest.fixture
def mock_openai():
    """Mock OpenAI service for DevAgent."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.chat_completion = AsyncMock(return_value="def hello(): pass")
    svc.get_client = Mock(return_value=None)  # skip intent classification
    return svc


# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dev_basic_code_gen(dev_agent, mock_openai):
    """DevAgent generates code via OpenAI fallback."""
    with (
        patch("agents.specialized.dev_agent.get_service",
              side_effect=lambda n: mock_openai if n == "openai" else None),
    ):
        result = await dev_agent.execute("write a Python hello world", {})
    assert result.status == AgentStatus.SUCCESS
    assert "def hello" in result.response


@pytest.mark.asyncio
async def test_dev_empty_prompt(dev_agent):
    """DevAgent returns error for empty prompt."""
    result = await dev_agent.execute("", {"prompt": ""})
    assert result.status == AgentStatus.ERROR
    assert "prompt" in result.response.lower()


@pytest.mark.asyncio
async def test_dev_no_service(dev_agent):
    """DevAgent returns error when no AI service is available."""
    with patch("agents.specialized.dev_agent.get_service", return_value=None):
        result = await dev_agent.execute("write code", {})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_dev_capabilities(dev_agent):
    """DevAgent declares expected capabilities."""
    caps = dev_agent.get_capabilities()
    assert "code_generation" in caps
    assert "debugging" in caps


@pytest.mark.asyncio
async def test_dev_anthropic_success(dev_agent):
    """DevAgent uses Anthropic when available."""
    mock_anthropic = AsyncMock()
    mock_anthropic.is_initialized = Mock(return_value=True)
    mock_anthropic.initialize = AsyncMock()
    mock_anthropic.generate_code = AsyncMock(return_value="def fib(n): return n")

    def side_effect(name):
        if name == "anthropic":
            return mock_anthropic
        return None  # no openai needed for intent → defaults to generate_code

    with patch("agents.specialized.dev_agent.get_service", side_effect=side_effect):
        result = await dev_agent.execute("crie fibonacci", {})

    assert result.status == AgentStatus.SUCCESS
    assert "fib" in result.response


@pytest.mark.asyncio
async def test_dev_anthropic_failure_falls_back_to_openai(dev_agent):
    """DevAgent falls back to OpenAI when Anthropic fails."""
    mock_anthropic = AsyncMock()
    mock_anthropic.is_initialized = Mock(return_value=True)
    mock_anthropic.initialize = AsyncMock()
    mock_anthropic.generate_code = AsyncMock(side_effect=RuntimeError("API down"))

    mock_openai = AsyncMock()
    mock_openai.is_initialized = Mock(return_value=True)
    mock_openai.initialize = AsyncMock()
    mock_openai.chat_completion = AsyncMock(return_value="def fallback(): pass")
    mock_openai.get_client = Mock(return_value=None)  # skip intent

    def side_effect(name):
        if name == "anthropic":
            return mock_anthropic
        if name == "openai":
            return mock_openai
        return None

    with patch("agents.specialized.dev_agent.get_service", side_effect=side_effect):
        result = await dev_agent.execute("generate code", {})

    assert result.status == AgentStatus.SUCCESS
    assert "fallback" in result.response


@pytest.mark.asyncio
async def test_dev_help_intent(dev_agent):
    """DevAgent returns help text."""
    result = await dev_agent._handle_help()
    assert result.status == AgentStatus.SUCCESS
    assert "Dev Agent" in result.response
