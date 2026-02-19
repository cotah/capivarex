"""Integration tests for AnthropicService with mocked Anthropic client."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from services.ai.anthropic_service import AnthropicService


def _make_service():
    svc = AnthropicService()
    svc.api_key = "fake-key"
    svc._initialized = True
    svc.client = MagicMock()
    return svc


class TestGenerateCode:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        resp = MagicMock()
        resp.content = [MagicMock()]
        resp.content[0].text = "def hello(): print('hi')"
        svc.client.messages.create = AsyncMock(return_value=resp)

        result = await svc.generate_code("Write a hello function")

        assert "def hello" in result
        svc.client.messages.create.assert_called_once()

    @pytest.mark.asyncio
    async def test_empty_content(self):
        svc = _make_service()
        resp = MagicMock()
        resp.content = []
        svc.client.messages.create = AsyncMock(return_value=resp)

        result = await svc.generate_code("test")
        assert result == ""

    @pytest.mark.asyncio
    async def test_api_error_propagates(self):
        svc = _make_service()
        svc.client.messages.create = AsyncMock(
            side_effect=RuntimeError("API Error")
        )

        with pytest.raises(RuntimeError, match="API Error"):
            await svc.generate_code("test")

    @pytest.mark.asyncio
    async def test_custom_system_prompt(self):
        svc = _make_service()
        resp = MagicMock()
        resp.content = [MagicMock()]
        resp.content[0].text = "code"
        svc.client.messages.create = AsyncMock(return_value=resp)

        await svc.generate_code("test", system_prompt="Custom prompt")

        call_kwargs = svc.client.messages.create.call_args
        assert call_kwargs.kwargs["system"] == "Custom prompt"

    @pytest.mark.asyncio
    async def test_initializes_when_no_client(self):
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()

        async def set_client():
            svc.client = MagicMock()
            resp = MagicMock()
            resp.content = [MagicMock()]
            resp.content[0].text = "ok"
            svc.client.messages.create = AsyncMock(return_value=resp)

        svc.initialize.side_effect = set_client

        result = await svc.generate_code("test")
        svc.initialize.assert_called_once()
        assert result == "ok"


class TestGenerateCodeStream:
    @pytest.mark.asyncio
    async def test_yields_tokens(self):
        svc = _make_service()

        # Mock the async context manager and text_stream
        mock_stream = AsyncMock()

        async def text_iter():
            for t in ["def ", "hello", "():"]:
                yield t

        mock_stream.text_stream = text_iter()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        svc.client.messages.stream = MagicMock(return_value=mock_stream)

        tokens = []
        async for token in svc.generate_code_stream("Write hello"):
            tokens.append(token)

        assert "".join(tokens) == "def hello():"

    @pytest.mark.asyncio
    async def test_error_yields_error_message(self):
        svc = _make_service()
        svc.client.messages.stream = MagicMock(
            side_effect=RuntimeError("stream failed")
        )

        tokens = []
        async for token in svc.generate_code_stream("test"):
            tokens.append(token)

        assert any("Erro" in t for t in tokens)


class TestGetClient:
    def test_returns_client(self):
        svc = _make_service()
        assert svc.get_client() is svc.client

    def test_returns_none_when_uninitialized(self):
        svc = AnthropicService()
        assert svc.get_client() is None


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy(self):
        svc = _make_service()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy_no_client(self):
        svc = AnthropicService()
        assert await svc._health_check() is False

    @pytest.mark.asyncio
    async def test_unhealthy_no_api_key(self):
        svc = _make_service()
        svc.api_key = None
        assert await svc._health_check() is False
