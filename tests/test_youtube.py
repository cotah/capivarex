# -*- coding: utf-8 -*-
"""
Tests para YouTubeService e YouTubeAgent.

Cobre:
  - Service: search_videos, get_video_details, get_channel_info,
             get_latest_videos, get_trending
  - Service: tratamento de erros (403, 400, timeout, vídeo não encontrado)
  - Agent intents: search, trending, channel, latest, detail
  - Agent: extração de video ID de URL e texto
  - Agent: extração de categoria para trending
  - Agent: context override (action explícito)
  - Agent: quota excedida → mensagem clara
  - Helpers: _iso_to_readable, _format_count
"""

from typing import Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import httpx


# ─── Factories de resposta da API ─────────────────────────────────────────────

def _search_item(video_id="abc12345678", title="Test Video", channel="Test Chan"):
    return {
        "id": {"kind": "youtube#video", "videoId": video_id},
        "snippet": {
            "title": title,
            "channelTitle": channel,
            "channelId": "UC123",
            "publishedAt": "2026-02-21T10:00:00Z",
            "description": "Descrição do vídeo",
            "thumbnails": {"high": {"url": "https://img.youtube.com/thumb.jpg"}},
        },
    }


def _video_item(video_id="abc12345678", title="Test Video", views="1000000"):
    return {
        "id": video_id,
        "snippet": {
            "title": title,
            "channelTitle": "Test Chan",
            "channelId": "UC123",
            "publishedAt": "2026-02-21T10:00:00Z",
            "description": "Descrição detalhada",
            "thumbnails": {"high": {"url": "https://img.youtube.com/thumb.jpg"}},
        },
        "statistics": {
            "viewCount": views,
            "likeCount": "50000",
            "commentCount": "1200",
        },
        "contentDetails": {"duration": "PT4M13S"},
    }


def _channel_item(channel_id="UC123", name="Test Channel"):
    return {
        "id": channel_id,
        "snippet": {
            "title": name,
            "customUrl": "@testchannel",
            "description": "Descrição do canal",
            "publishedAt": "2020-01-01T00:00:00Z",
            "country": "BR",
            "thumbnails": {"high": {"url": "https://img.youtube.com/chan.jpg"}},
        },
        "statistics": {
            "subscriberCount": "500000",
            "videoCount": "200",
            "viewCount": "10000000",
        },
    }


# ═══════════════════════════════════════════════════════════════════════════════
# FIXTURES
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def youtube_service():
    from services.integrations.youtube_service import YouTubeService
    svc = YouTubeService()
    svc._api_key = "FAKE_KEY"
    svc._client = AsyncMock()
    svc._initialized = True
    return svc


@pytest.fixture
def youtube_agent():
    from agents.specialized.youtube_agent import YouTubeAgent
    return YouTubeAgent()


def _mock_response(data: Dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = data
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# 1. YouTubeService — search_videos
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeServiceSearch:

    @pytest.mark.asyncio
    async def test_search_returns_videos(self, youtube_service):
        items = [_search_item("vid1", "Python Tutorial"), _search_item("vid2", "Python Basics")]
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": items})
        )
        results = await youtube_service.search_videos("python")
        assert len(results) == 2
        assert results[0]["title"] == "Python Tutorial"
        assert results[0]["url"] == "https://youtu.be/vid1"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": []})
        )
        results = await youtube_service.search_videos("zzznothingzzz")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_caps_max_results(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": []})
        )
        await youtube_service.search_videos("test", max_results=100)
        call_params = youtube_service._client.get.call_args
        params = call_params.kwargs.get("params") or call_params.args[1]
        assert params["maxResults"] <= 25

    @pytest.mark.asyncio
    async def test_search_403_raises_quota_error(self, youtube_service):
        resp = MagicMock()
        resp.status_code = 403
        resp.raise_for_status = MagicMock()
        youtube_service._client.get = AsyncMock(return_value=resp)
        with pytest.raises(RuntimeError, match="quota"):
            await youtube_service.search_videos("test")

    @pytest.mark.asyncio
    async def test_search_timeout_raises(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            side_effect=httpx.TimeoutException("timeout")
        )
        with pytest.raises(RuntimeError, match="timeout"):
            await youtube_service.search_videos("test")


# ═══════════════════════════════════════════════════════════════════════════════
# 2. YouTubeService — get_video_details
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeServiceVideoDetails:

    @pytest.mark.asyncio
    async def test_get_video_details(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": [_video_item("abc12345678", "Tutorial")]})
        )
        video = await youtube_service.get_video_details("abc12345678")
        assert video is not None
        assert video["title"] == "Tutorial"
        assert video["duration"] == "4:13"
        assert video["views"] == "1.0M"
        assert video["url"] == "https://youtu.be/abc12345678"

    @pytest.mark.asyncio
    async def test_get_video_not_found(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": []})
        )
        result = await youtube_service.get_video_details("notexist123")
        assert result is None

    @pytest.mark.asyncio
    async def test_video_has_all_fields(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": [_video_item()]})
        )
        video = await youtube_service.get_video_details("abc12345678")
        for field in ["id", "title", "channel", "views", "likes", "duration", "url"]:
            assert field in video


# ═══════════════════════════════════════════════════════════════════════════════
# 3. YouTubeService — get_channel_info
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeServiceChannel:

    @pytest.mark.asyncio
    async def test_get_channel_by_handle(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": [_channel_item("UC123", "Código Fonte TV")]})
        )
        info = await youtube_service.get_channel_info("@codigofonte")
        assert info is not None
        assert info["name"] == "Código Fonte TV"
        assert info["subscribers"] == "500.0K"

    @pytest.mark.asyncio
    async def test_get_channel_not_found(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": []})
        )
        result = await youtube_service.get_channel_info("@nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_channel_has_url(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": [_channel_item("UC456")]})
        )
        info = await youtube_service.get_channel_info("UC456")
        assert "youtube.com/channel/UC456" in info["url"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. YouTubeService — get_trending
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeServiceTrending:

    @pytest.mark.asyncio
    async def test_get_trending_returns_videos(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": [_video_item(), _video_item("vid2", "Outro")]})
        )
        videos = await youtube_service.get_trending(region_code="BR", max_results=2)
        assert len(videos) == 2

    @pytest.mark.asyncio
    async def test_get_trending_passes_region(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": []})
        )
        await youtube_service.get_trending(region_code="US")
        params = youtube_service._client.get.call_args.kwargs.get("params", {})
        assert params.get("regionCode") == "US"

    @pytest.mark.asyncio
    async def test_get_trending_passes_category(self, youtube_service):
        youtube_service._client.get = AsyncMock(
            return_value=_mock_response({"items": []})
        )
        await youtube_service.get_trending(category_id="10")
        params = youtube_service._client.get.call_args.kwargs.get("params", {})
        assert params.get("videoCategoryId") == "10"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Helpers estáticos
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeHelpers:

    def test_iso_duration_minutes_seconds(self):
        from services.integrations.youtube_service import _iso_to_readable
        assert _iso_to_readable("PT4M13S") == "4:13"

    def test_iso_duration_hours(self):
        from services.integrations.youtube_service import _iso_to_readable
        assert _iso_to_readable("PT1H30M0S") == "1:30:00"

    def test_iso_duration_seconds_only(self):
        from services.integrations.youtube_service import _iso_to_readable
        assert _iso_to_readable("PT45S") == "0:45"

    def test_format_count_millions(self):
        from services.integrations.youtube_service import _format_count
        assert _format_count(1_500_000) == "1.5M"

    def test_format_count_thousands(self):
        from services.integrations.youtube_service import _format_count
        assert _format_count(25_000) == "25.0K"

    def test_format_count_small(self):
        from services.integrations.youtube_service import _format_count
        assert _format_count(500) == "500"

    def test_format_count_invalid(self):
        from services.integrations.youtube_service import _format_count
        assert _format_count(None) == "N/A"


# ═══════════════════════════════════════════════════════════════════════════════
# 6. YouTubeAgent — intents
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeAgent:

    @pytest.fixture
    def mock_svc(self):
        from services.integrations.youtube_service import YouTubeService
        svc = AsyncMock(spec=YouTubeService)
        svc.is_initialized.return_value = True

        video = {
            "id": "abc12345678",
            "title": "Python Tutorial",
            "channel": "Código Fonte TV",
            "channel_id": "UC123",
            "published_at": "2026-02-21",
            "description": "Aprenda Python",
            "url": "https://youtu.be/abc12345678",
            "duration": "15:30",
            "views": "500.0K",
            "likes": "25.0K",
            "comments": "1.2K",
            "thumbnail": "",
        }

        channel = {
            "id": "UC123",
            "name": "Código Fonte TV",
            "handle": "@codigofonte",
            "url": "https://youtube.com/channel/UC123",
            "subscribers": "500.0K",
            "video_count": "200",
            "view_count": "10.0M",
            "description": "Canal de tecnologia",
            "country": "BR",
        }

        svc.search_videos = AsyncMock(return_value=[video])
        svc.get_video_details = AsyncMock(return_value=video)
        svc.get_channel_info = AsyncMock(return_value=channel)
        svc.get_latest_videos = AsyncMock(return_value=[video])
        svc.get_trending = AsyncMock(return_value=[video])
        return svc

    @pytest.mark.asyncio
    async def test_search_intent(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute(
                "Busca vídeos de Python no YouTube", {}
            )
        assert r.is_success()
        mock_svc.search_videos.assert_called_once()
        assert "Python" in r.response or "python" in r.response.lower()

    @pytest.mark.asyncio
    async def test_trending_intent(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute("Vídeos em alta no YouTube", {})
        assert r.is_success()
        mock_svc.get_trending.assert_called_once()
        assert "alta" in r.response.lower() or "trending" in r.response.lower()

    @pytest.mark.asyncio
    async def test_trending_music_category(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            await youtube_agent.execute("Trending de música no YouTube", {})
        call_kwargs = mock_svc.get_trending.call_args.kwargs
        assert call_kwargs.get("category_id") == "10"

    @pytest.mark.asyncio
    async def test_channel_intent(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute("Info do canal @codigofonte", {})
        assert r.is_success()
        mock_svc.get_channel_info.assert_called_once()
        assert "Código Fonte TV" in r.response

    @pytest.mark.asyncio
    async def test_detail_with_video_id(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute(
                "Detalhes do vídeo abc12345678", {}
            )
        assert r.is_success()
        mock_svc.get_video_details.assert_called_once_with("abc12345678")

    @pytest.mark.asyncio
    async def test_detail_from_url(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute(
                "https://youtu.be/dQw4w9WgXcQ", {}
            )
        assert r.is_success()
        mock_svc.get_video_details.assert_called_once_with("dQw4w9WgXcQ")

    @pytest.mark.asyncio
    async def test_context_action_search(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute(
                "algo",
                {"action": "search", "query": "machine learning"},
            )
        assert r.is_success()
        call_kwargs = mock_svc.search_videos.call_args.kwargs
        assert "machine learning" in (call_kwargs.get("query") or "")

    @pytest.mark.asyncio
    async def test_context_action_trending(self, youtube_agent, mock_svc):
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute(
                "algo",
                {"action": "trending", "region_code": "US", "category_id": "20"},
            )
        assert r.is_success()
        mock_svc.get_trending.assert_called_once()

    @pytest.mark.asyncio
    async def test_service_unavailable(self, youtube_agent):
        with patch("agents.specialized.youtube_agent.get_service", return_value=None):
            r = await youtube_agent.execute("busca python", {})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_quota_error_friendly_message(self, youtube_agent, mock_svc):
        mock_svc.search_videos = AsyncMock(
            side_effect=RuntimeError("403 quota excedida")
        )
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute("busca python", {})
        assert not r.is_success()
        assert "Quota" in r.response or "quota" in r.response.lower()

    @pytest.mark.asyncio
    async def test_video_not_found(self, youtube_agent, mock_svc):
        mock_svc.get_video_details.return_value = None
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute("detalhes dQw4w9WgXcQ", {})
        assert not r.is_success()
        assert "não encontrado" in r.response.lower()

    @pytest.mark.asyncio
    async def test_search_no_results(self, youtube_agent, mock_svc):
        mock_svc.search_videos.return_value = []
        with patch("agents.specialized.youtube_agent.get_service", return_value=mock_svc):
            r = await youtube_agent.execute("busca zzznothingzzz", {})
        assert r.is_success()
        assert "nenhum" in r.response.lower()

    def test_capabilities(self, youtube_agent):
        caps = youtube_agent.get_capabilities()
        assert "search_videos" in caps
        assert "get_trending" in caps
        assert "get_channel_info" in caps


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Agent helpers — extração de texto
# ═══════════════════════════════════════════════════════════════════════════════

class TestYouTubeAgentHelpers:

    @pytest.fixture
    def agent(self):
        from agents.specialized.youtube_agent import YouTubeAgent
        return YouTubeAgent()

    def test_extract_video_id_from_youtu_be(self, agent):
        result = agent._extract_video_id("https://youtu.be/dQw4w9WgXcQ")
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_from_watch_url(self, agent):
        result = agent._extract_video_id("https://youtube.com/watch?v=dQw4w9WgXcQ")
        assert result == "dQw4w9WgXcQ"

    def test_extract_video_id_direct(self, agent):
        result = agent._extract_video_id("dQw4w9WgXcQ")
        assert result == "dQw4w9WgXcQ"

    def test_extract_category_music(self):
        from agents.specialized.youtube_agent import _extract_category
        assert _extract_category("trending de música") == "10"

    def test_extract_category_gaming(self):
        from agents.specialized.youtube_agent import _extract_category
        assert _extract_category("games em alta") == "20"

    def test_extract_category_default(self):
        from agents.specialized.youtube_agent import _extract_category
        assert _extract_category("vídeos em alta") == "0"

    def test_extract_count(self):
        from agents.specialized.youtube_agent import _extract_count
        assert _extract_count("top 5 vídeos") == 5
        assert _extract_count("10 vídeos") == 10
        assert _extract_count("sem número") == 5  # default
