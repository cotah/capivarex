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


class TestDetectAspectRatio:
    """Tests for _detect_aspect_ratio static method."""

    def _make_image_bytes(self, width: int, height: int) -> bytes:
        """Create minimal PNG bytes with given dimensions."""
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (width, height), color="red")
        buf = BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    def test_landscape_16_9(self):
        data = self._make_image_bytes(1920, 1080)
        assert GrokVideoService._detect_aspect_ratio(data) == "16:9"

    def test_portrait_9_16(self):
        data = self._make_image_bytes(1080, 1920)
        assert GrokVideoService._detect_aspect_ratio(data) == "9:16"

    def test_square_1_1(self):
        data = self._make_image_bytes(1000, 1000)
        assert GrokVideoService._detect_aspect_ratio(data) == "1:1"

    def test_ratio_4_3(self):
        data = self._make_image_bytes(1600, 1200)
        assert GrokVideoService._detect_aspect_ratio(data) == "4:3"

    def test_ratio_3_4(self):
        data = self._make_image_bytes(1200, 1600)
        assert GrokVideoService._detect_aspect_ratio(data) == "3:4"

    def test_ratio_3_2(self):
        data = self._make_image_bytes(1500, 1000)
        assert GrokVideoService._detect_aspect_ratio(data) == "3:2"

    def test_ratio_2_3(self):
        data = self._make_image_bytes(1000, 1500)
        assert GrokVideoService._detect_aspect_ratio(data) == "2:3"

    def test_invalid_bytes_fallback(self):
        """Invalid image bytes should fallback to 16:9."""
        assert (
            GrokVideoService._detect_aspect_ratio(b"not an image")
            == "16:9"
        )

    @pytest.mark.asyncio
    async def test_auto_detection_in_image_to_video(
        self, fake_image_bytes
    ):
        """image_to_video with aspect_ratio='auto' calls detection."""
        svc = GrokVideoService()
        svc._initialized = True
        svc.client = MagicMock()

        mock_response = MagicMock()
        mock_response.url = "https://vidgen.x.ai/test/v.mp4"
        mock_response.duration = 8
        mock_response.respect_moderation = True
        svc.client.video.generate = MagicMock(
            return_value=mock_response
        )

        with patch.object(
            svc, "_download_video", new_callable=AsyncMock
        ) as dl, patch.object(
            GrokVideoService,
            "_detect_aspect_ratio",
            return_value="4:3",
        ) as detect:
            dl.return_value = "/tmp/v.mp4"
            await svc.image_to_video(
                image_data=fake_image_bytes, prompt="test"
            )

        detect.assert_called_once_with(fake_image_bytes)
        call_args = svc.client.video.generate.call_args
        assert call_args.kwargs.get("aspect_ratio") == "4:3"
