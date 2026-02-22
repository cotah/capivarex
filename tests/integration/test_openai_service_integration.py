"""Integration tests for OpenAIService with mocked OpenAI client."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.ai.openai_service import OpenAIService


def _make_service():
    svc = OpenAIService()
    svc.api_key = "fake-key"
    svc._initialized = True
    svc.client = MagicMock()
    return svc


def _mock_completion(content="Hello! How can I help?"):
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = content
    resp.usage = MagicMock()
    resp.usage.total_tokens = 25
    return resp


class TestChatCompletion:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        svc.client.chat.completions.create = AsyncMock(
            return_value=_mock_completion("The weather is sunny.")
        )

        result = await svc.chat_completion(
            messages=[{"role": "user", "content": "What's the weather?"}]
        )

        assert result == "The weather is sunny."
        svc.client.chat.completions.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_on_none_content(self):
        svc = _make_service()
        resp = _mock_completion(None)
        svc.client.chat.completions.create = AsyncMock(return_value=resp)

        result = await svc.chat_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        assert result == ""

    @pytest.mark.asyncio
    async def test_api_error_propagates(self):
        svc = _make_service()
        svc.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API Error")
        )

        with pytest.raises(RuntimeError, match="API Error"):
            await svc.chat_completion(
                messages=[{"role": "user", "content": "test"}]
            )

    @pytest.mark.asyncio
    async def test_initializes_when_no_client(self):
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()

        # After initialize, client should exist
        async def set_client():
            svc.client = MagicMock()
            svc.client.chat.completions.create = AsyncMock(
                return_value=_mock_completion("ok")
            )

        svc.initialize.side_effect = set_client

        result = await svc.chat_completion(
            messages=[{"role": "user", "content": "test"}]
        )
        svc.initialize.assert_called_once()
        assert result == "ok"


class TestDecideNextAction:
    @pytest.mark.asyncio
    async def test_success_returns_action(self):
        svc = _make_service()
        svc.client.chat.completions.create = AsyncMock(
            return_value=_mock_completion('{"action": "weather", "location": "SP"}')
        )

        result = await svc.decide_next_action([], "como está o clima?")

        assert result["action"] == "weather"
        assert result["location"] == "SP"

    @pytest.mark.asyncio
    async def test_error_returns_fallback(self):
        svc = _make_service()
        svc.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API down")
        )

        result = await svc.decide_next_action([], "test")

        assert result["action"] == "chat"

    @pytest.mark.asyncio
    async def test_invalid_json_returns_fallback(self):
        svc = _make_service()
        svc.client.chat.completions.create = AsyncMock(
            return_value=_mock_completion("not json")
        )

        result = await svc.decide_next_action([], "test")
        assert result["action"] == "chat"


class TestStreamChatCompletion:
    @pytest.mark.asyncio
    async def test_yields_tokens(self):
        svc = _make_service()

        async def mock_stream():
            for text in ["Hello", " world", "!"]:
                chunk = MagicMock()
                chunk.choices = [MagicMock()]
                chunk.choices[0].delta.content = text
                yield chunk

        svc.client.chat.completions.create = AsyncMock(return_value=mock_stream())

        tokens = []
        async for token in svc.stream_chat_completion(
            messages=[{"role": "user", "content": "hi"}]
        ):
            tokens.append(token)

        assert "".join(tokens) == "Hello world!"

    @pytest.mark.asyncio
    async def test_error_yields_error_message(self):
        svc = _make_service()
        svc.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("stream failed")
        )

        tokens = []
        async for token in svc.stream_chat_completion(
            messages=[{"role": "user", "content": "hi"}]
        ):
            tokens.append(token)

        assert any("ERROR" in t for t in tokens)


class TestGetClient:
    def test_returns_client(self):
        svc = _make_service()
        assert svc.get_client() is svc.client

    def test_returns_none_when_uninitialized(self):
        svc = OpenAIService()
        assert svc.get_client() is None


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_no_client(self):
        svc = OpenAIService()
        assert await svc._health_check() is False

    @pytest.mark.asyncio
    async def test_healthy(self):
        svc = _make_service()
        svc.client.models.list = AsyncMock(return_value=[])
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy_on_exception(self):
        svc = _make_service()
        svc.client.models.list = AsyncMock(side_effect=RuntimeError("fail"))
        assert await svc._health_check() is False
