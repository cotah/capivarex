"""
Unit tests for ImageAgent — AI image generation.
"""
from unittest.mock import AsyncMock, patch

import pytest

from agents.core import AgentStatus


@pytest.fixture
def image_agent():
    from agents.specialized.image_agent import ImageAgent
    return ImageAgent()


def _make_image_svc(result=None):
    """Build a mock image service that exposes generate_image directly."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.generate_image = AsyncMock(return_value=result or {
        "success": True,
        "url": "https://example.com/image.png",
    })
    return svc


# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_image_basic_generation(image_agent):
    """ImageAgent generates an image and returns success."""
    mock_svc = _make_image_svc()
    with patch("agents.specialized.image_agent.get_service", return_value=mock_svc):
        result = await image_agent.execute("a sunset over the ocean", {})
    assert result.status == AgentStatus.SUCCESS
    assert result.data.get("success") is True


@pytest.mark.asyncio
async def test_image_empty_prompt(image_agent):
    """ImageAgent returns error for empty prompt."""
    result = await image_agent.execute("", {"prompt": ""})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_image_service_unavailable(image_agent):
    """ImageAgent returns error when service is None."""
    with patch("agents.specialized.image_agent.get_service", return_value=None):
        result = await image_agent.execute("draw a cat", {})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_image_generation_failure(image_agent):
    """ImageAgent returns error when generation result reports failure."""
    mock_svc = _make_image_svc(result={"success": False, "error": "quota exceeded"})
    with patch("agents.specialized.image_agent.get_service", return_value=mock_svc):
        result = await image_agent.execute("draw something", {})
    assert result.status == AgentStatus.ERROR
    assert "quota" in result.response.lower()
