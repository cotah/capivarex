"""
Unit tests for ChatAgent — general conversation handler.
"""
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agents.core import AgentStatus


@pytest.fixture
def chat_agent():
    """Create a ChatAgent instance."""
    from agents.specialized.chat_agent import ChatAgent
    return ChatAgent()


@pytest.fixture
def mock_openai():
    """Mock OpenAI service for ChatAgent."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()

    async def _stream(*_a, **_kw):
        for tok in ["Hello", " world", "!"]:
            yield tok

    svc.stream_chat_completion = _stream

    client = AsyncMock()
    resp = Mock()
    resp.choices = [Mock()]
    resp.choices[0].message = Mock(content="Fallback reply")
    client.chat.completions.create = AsyncMock(return_value=resp)
    svc.get_client = Mock(return_value=client)
    return svc


# -------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chat_basic_response(chat_agent, mock_openai):
    """ChatAgent returns streaming response when OpenAI is available."""
    with patch("agents.specialized.chat_agent.get_service", return_value=mock_openai):
        result = await chat_agent.execute("Ola, tudo bem?", {})
    assert result.status == AgentStatus.SUCCESS
    assert "Hello world!" in result.response


@pytest.mark.asyncio
async def test_chat_with_history(chat_agent, mock_openai):
    """ChatAgent includes conversation history in messages."""
    history = [
        {"role": "user", "content": "msg1"},
        {"role": "assistant", "content": "resp1"},
    ]
    with patch("agents.specialized.chat_agent.get_service", return_value=mock_openai):
        result = await chat_agent.execute("msg2", {"history": history})
    assert result.is_success()


@pytest.mark.asyncio
async def test_chat_service_unavailable(chat_agent):
    """ChatAgent returns error when OpenAI service is None."""
    with patch("agents.specialized.chat_agent.get_service", return_value=None):
        result = await chat_agent.execute("hello", {})
    assert result.status == AgentStatus.ERROR
    assert "nao consegui" in result.response.lower()


@pytest.mark.asyncio
async def test_chat_fallback_on_stream_error(chat_agent, mock_openai):
    """ChatAgent falls back to completion when streaming fails."""
    async def _bad_stream(*_a, **_kw):
        raise RuntimeError("stream broken")
        yield  # noqa: F541 — keeps it an async generator

    mock_openai.stream_chat_completion = _bad_stream

    with patch("agents.specialized.chat_agent.get_service", return_value=mock_openai):
        result = await chat_agent.execute("test", {})
    assert result.status == AgentStatus.SUCCESS
    assert result.response == "Fallback reply"


@pytest.mark.asyncio
async def test_chat_capabilities(chat_agent):
    """ChatAgent declares expected capabilities."""
    caps = chat_agent.get_capabilities()
    assert "conversation" in caps
    assert "knowledge_queries" in caps
