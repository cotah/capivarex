# -*- coding: utf-8 -*-
"""
tests/test_grok_video_service.py
================================
Tests for GrokVideoService (xAI Grok Imagine Video).
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.media.grok_video_service import GrokVideoService


@pytest.fixture
def service():
    svc = GrokVideoService()
    svc._initialized = True
    svc.client = MagicMock()
    return svc


@pytest.fixture
def fake_image_bytes():
    """Minimal JPEG bytes for testing."""
    return b"\xff\xd8\xff\xe0" + b"\x00" * 100 + b"\xff\xd9"


class TestGrokVideoService:
    def test_init(self):
        svc = GrokVideoService()
        assert svc.name == "grok_video"
        assert svc.client is None

    @pytest.mark.asyncio
    async def test_initialize_no_key(self):
        svc = GrokVideoService()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(Exception):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_health_check_with_client(self, service):
        assert await service._health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_without_client(self):
        svc = GrokVideoService()
        assert await svc._health_check() is False

    @pytest.mark.asyncio
    async def test_image_to_video_success(
        self, service, fake_image_bytes
    ):
        mock_response = MagicMock()
        mock_response.url = "https://vidgen.x.ai/test/video.mp4"
        mock_response.duration = 8
        mock_response.respect_moderation = True
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        with patch.object(
            service, "_download_video", new_callable=AsyncMock
        ) as dl:
            dl.return_value = "/tmp/test_video.mp4"
            result = await service.image_to_video(
                image_data=fake_image_bytes,
                prompt="Animate gently",
            )

        assert result["success"] is True
        assert result["video_path"] == "/tmp/test_video.mp4"
        assert result["provider"] == "grok"
        assert result["model_used"] == "grok-imagine-video"

    @pytest.mark.asyncio
    async def test_image_to_video_moderation_blocked(
        self, service, fake_image_bytes
    ):
        mock_response = MagicMock()
        mock_response.respect_moderation = False
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        result = await service.image_to_video(
            image_data=fake_image_bytes
        )
        assert result["success"] is False
        assert "moderation" in result["error"]

    @pytest.mark.asyncio
    async def test_text_to_video_success(self, service):
        mock_response = MagicMock()
        mock_response.url = "https://vidgen.x.ai/test/video2.mp4"
        mock_response.duration = 10
        mock_response.respect_moderation = True
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        with patch.object(
            service, "_download_video", new_callable=AsyncMock
        ) as dl:
            dl.return_value = "/tmp/test_video2.mp4"
            result = await service.text_to_video(
                prompt="A cat playing"
            )

        assert result["success"] is True
        assert result["provider"] == "grok"

    @pytest.mark.asyncio
    async def test_text_to_video_moderation_blocked(self, service):
        mock_response = MagicMock()
        mock_response.respect_moderation = False
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        result = await service.text_to_video(
            prompt="Something blocked"
        )
        assert result["success"] is False
        assert "moderation" in result["error"]

    @pytest.mark.asyncio
    async def test_image_to_video_api_error(
        self, service, fake_image_bytes
    ):
        service.client.video.generate = MagicMock(
            side_effect=Exception("API timeout")
        )
        result = await service.image_to_video(
            image_data=fake_image_bytes
        )
        assert result["success"] is False
        assert "API timeout" in result["error"]

    @pytest.mark.asyncio
    async def test_text_to_video_api_error(self, service):
        service.client.video.generate = MagicMock(
            side_effect=Exception("API error")
        )
        result = await service.text_to_video(prompt="test prompt")
        assert result["success"] is False
        assert "API error" in result["error"]

    @pytest.mark.asyncio
    async def test_default_prompt_when_empty(
        self, service, fake_image_bytes
    ):
        mock_response = MagicMock()
        mock_response.url = "https://vidgen.x.ai/test/v.mp4"
        mock_response.duration = 8
        mock_response.respect_moderation = True
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        with patch.object(
            service, "_download_video", new_callable=AsyncMock
        ) as dl:
            dl.return_value = "/tmp/v.mp4"
            await service.image_to_video(
                image_data=fake_image_bytes, prompt=""
            )

        call_args = service.client.video.generate.call_args
        used_prompt = call_args.kwargs.get(
            "prompt", call_args[1].get("prompt", "")
        )
        assert "Animate" in used_prompt

    @pytest.mark.asyncio
    async def test_duration_clamped(self, service, fake_image_bytes):
        """Duration is clamped between 1 and 15."""
        mock_response = MagicMock()
        mock_response.url = "https://vidgen.x.ai/test/v.mp4"
        mock_response.duration = 15
        mock_response.respect_moderation = True
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        with patch.object(
            service, "_download_video", new_callable=AsyncMock
        ) as dl:
            dl.return_value = "/tmp/v.mp4"
            await service.image_to_video(
                image_data=fake_image_bytes,
                prompt="test",
                duration=999,
            )

        call_args = service.client.video.generate.call_args
        assert call_args.kwargs.get("duration") == 15

    @pytest.mark.asyncio
    async def test_image_to_video_latency_tracked(
        self, service, fake_image_bytes
    ):
        """Successful calls track latency."""
        mock_response = MagicMock()
        mock_response.url = "https://vidgen.x.ai/test/v.mp4"
        mock_response.duration = 8
        mock_response.respect_moderation = True
        service.client.video.generate = MagicMock(
            return_value=mock_response
        )

        with patch.object(
            service, "_download_video", new_callable=AsyncMock
        ) as dl:
            dl.return_value = "/tmp/v.mp4"
            result = await service.image_to_video(
                image_data=fake_image_bytes, prompt="test"
            )

        assert "latency_seconds" in result
        assert isinstance(result["latency_seconds"], float)
