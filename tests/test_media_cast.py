"""Tests for media cast agent."""

from unittest.mock import AsyncMock, MagicMock, patch


class TestMediaCastRegex:
    """Tests for media cast regex patterns."""

    def test_poe_na_tv(self):
        from agents.specialized.media_cast_agent import _RE_PLAY_ON_TV

        m = _RE_PLAY_ON_TV.search("põe Palmeiras na TV")
        assert m and "palmeiras" in m.group(1).lower()

    def test_play_on_tv(self):
        from agents.specialized.media_cast_agent import _RE_PLAY_ON_TV

        m = _RE_PLAY_ON_TV.search("play cooking videos on TV")
        assert m and "cooking" in m.group(1).lower()

    def test_coloca_na_televisao(self):
        from agents.specialized.media_cast_agent import _RE_PLAY_ON_TV

        m = _RE_PLAY_ON_TV.search("coloca filme de ação na televisão")
        assert m and "ação" in m.group(1).lower()

    def test_assistir_na_tv(self):
        from agents.specialized.media_cast_agent import _RE_PLAY_ON_TV

        m = _RE_PLAY_ON_TV.search("assistir Titanic na TV")
        assert m and "titanic" in m.group(1).lower()

    def test_watch_on_chromecast(self):
        from agents.specialized.media_cast_agent import _RE_PLAY_ON_TV

        m = _RE_PLAY_ON_TV.search("watch news on chromecast")
        assert m

    def test_spanish_pon_en_tv(self):
        from agents.specialized.media_cast_agent import _RE_PLAY_ON_TV

        m = _RE_PLAY_ON_TV.search("pon música en la TV")
        assert m

    def test_turn_on_tv(self):
        from agents.specialized.media_cast_agent import _RE_TURN_ON_TV

        assert _RE_TURN_ON_TV.search("liga a TV")
        assert _RE_TURN_ON_TV.search("turn on the TV")
        assert _RE_TURN_ON_TV.search("ligar televisão")

    def test_turn_on_not_match_random(self):
        from agents.specialized.media_cast_agent import _RE_TURN_ON_TV

        assert not _RE_TURN_ON_TV.search("bom dia")
        assert not _RE_TURN_ON_TV.search("play music")


class TestExtractContentQuery:
    """Tests for content query extraction."""

    def test_removes_tv_words(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        result = MediaCastAgent._extract_content_query("play cooking videos on tv")
        assert result and "cooking" in result.lower()
        assert "tv" not in result.lower()

    def test_short_text_returns_none(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        result = MediaCastAgent._extract_content_query("tv")
        assert result is None


class TestBuildCastResponse:
    """Tests for cast response builder."""

    def test_includes_video_title(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        videos = [{"title": "Test Video", "id": "abc123", "channel": "TestCh"}]
        result = MediaCastAgent._build_cast_response(videos, "test", None, "en")
        assert "Test Video" in result
        assert "abc123" in result

    def test_includes_tv_turned_on(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        videos = [{"title": "Test", "id": "abc"}]
        result = MediaCastAgent._build_cast_response(
            videos, "test", "📺 TV ligada!", "pt"
        )
        assert "TV ligada" in result

    def test_includes_cast_tip(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        videos = [{"title": "Test", "id": "abc"}]
        result = MediaCastAgent._build_cast_response(videos, "test", None, "en")
        assert "Cast" in result

    def test_uses_url_field_when_available(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        videos = [
            {
                "title": "Test",
                "id": "abc",
                "url": "https://youtu.be/abc",
            }
        ]
        result = MediaCastAgent._build_cast_response(videos, "test", None, "en")
        assert "youtu.be/abc" in result

    def test_includes_duration_and_views(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        videos = [
            {
                "title": "Test",
                "id": "abc",
                "channel": "Ch",
                "duration": "12:34",
                "views": "1.2M",
            }
        ]
        result = MediaCastAgent._build_cast_response(videos, "test", None, "en")
        assert "12:34" in result
        assert "1.2M" in result


class TestMediaCastKeywords:
    """Tests for media cast keywords."""

    def test_na_tv_detected(self):
        from services.i18n.keywords import check_keywords, MEDIA_CAST_KEYWORDS

        assert check_keywords("põe na tv", MEDIA_CAST_KEYWORDS)

    def test_on_tv_detected(self):
        from services.i18n.keywords import check_keywords, MEDIA_CAST_KEYWORDS

        assert check_keywords("play on tv", MEDIA_CAST_KEYWORDS)

    def test_chromecast_detected(self):
        from services.i18n.keywords import check_keywords, MEDIA_CAST_KEYWORDS

        assert check_keywords("cast to chromecast", MEDIA_CAST_KEYWORDS)

    def test_random_not_detected(self):
        from services.i18n.keywords import check_keywords, MEDIA_CAST_KEYWORDS

        assert not check_keywords("bom dia", MEDIA_CAST_KEYWORDS)
        assert not check_keywords("comprar leite", MEDIA_CAST_KEYWORDS)


class TestI18nKeys:
    """Tests for i18n strings."""

    def test_all_keys_exist(self):
        from services.i18n import t

        keys = [
            "media_tv_turned_on",
            "media_found_videos",
            "media_watch",
            "media_cast_tip",
            "media_no_results",
            "media_cast_help",
        ]
        for key in keys:
            for lang in ("en", "pt", "es"):
                result = t(key, lang=lang, query="test")
                assert result and len(result) > 2, f"Missing: {key}/{lang}"


# ═══════════════════════════════════════════════════════════════════
# Async tests for execute() paths
# ═══════════════════════════════════════════════════════════════════


class TestMediaCastExecute:
    """Tests for MediaCastAgent.execute() method."""

    async def test_play_on_tv_with_videos(self):
        """Test 'play X on TV' when YouTube returns results."""
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentStatus

        agent = MediaCastAgent()
        videos = [{"title": "Palmeiras Gol", "id": "v1", "channel": "ESPN"}]
        with patch.object(
            agent, "_search_youtube", new_callable=AsyncMock, return_value=videos
        ):
            result = await agent.execute("play Palmeiras on TV", {})
            assert result.status == AgentStatus.SUCCESS
            assert "Palmeiras Gol" in result.response
            assert result.data["videos"] == videos

    async def test_play_on_tv_no_results(self):
        """Test 'play X on TV' when YouTube returns nothing."""
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentStatus

        agent = MediaCastAgent()
        with patch.object(
            agent, "_search_youtube", new_callable=AsyncMock, return_value=[]
        ):
            result = await agent.execute("play nothingXYZ on TV", {})
            assert result.status == AgentStatus.SUCCESS
            assert "nothingXYZ" in result.response

    async def test_turn_on_tv_only(self):
        """Test 'liga a TV' without content search."""
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentStatus

        agent = MediaCastAgent()
        with patch.object(
            agent,
            "_turn_on_tv",
            new_callable=AsyncMock,
            return_value="📺 TV ligada!",
        ):
            result = await agent.execute("liga a TV", {})
            assert result.status == AgentStatus.SUCCESS
            assert "TV ligada" in result.response

    async def test_fallback_no_intent(self):
        """Test fallback when no intent matches."""
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentStatus

        agent = MediaCastAgent()
        # "hi" is too short (len <= 2) for _extract_content_query → None
        result = await agent.execute("hi", {})
        assert result.status == AgentStatus.SUCCESS
        assert "TV" in result.response  # media_cast_help

    async def test_youtube_search_via_yt_prefix(self):
        """Test 'youtube cooking' extracts search via _RE_YOUTUBE_SEARCH."""
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentStatus

        agent = MediaCastAgent()
        videos = [{"title": "Cooking 101", "id": "c1"}]
        with patch.object(
            agent, "_search_youtube", new_callable=AsyncMock, return_value=videos
        ):
            result = await agent.execute("youtube cooking recipes", {})
            assert result.status == AgentStatus.SUCCESS
            assert "Cooking 101" in result.response

    async def test_turn_on_tv_and_play(self):
        """Test 'liga a TV e põe Palmeiras' — both TV + content."""
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentStatus

        agent = MediaCastAgent()
        videos = [{"title": "Palmeiras", "id": "p1"}]
        with (
            patch.object(
                agent,
                "_turn_on_tv",
                new_callable=AsyncMock,
                return_value="📺 TV ligada!",
            ),
            patch.object(
                agent, "_search_youtube", new_callable=AsyncMock, return_value=videos
            ),
        ):
            result = await agent.execute("liga a TV e põe Palmeiras na TV", {})
            assert result.status == AgentStatus.SUCCESS
            assert "TV ligada" in result.response
            assert "Palmeiras" in result.response


class TestTurnOnTV:
    """Tests for _turn_on_tv method."""

    async def test_success(self):
        from agents.specialized.media_cast_agent import MediaCastAgent
        from agents.core.base_agent import AgentResponse, AgentStatus

        agent = MediaCastAgent()
        mock_smarthome = MagicMock()
        mock_smarthome.process = AsyncMock(
            return_value=AgentResponse(status=AgentStatus.SUCCESS, response="TV on")
        )
        with patch(
            "agents.core.get_agent",
            return_value=mock_smarthome,
        ):
            result = await agent._turn_on_tv({}, "en")
            assert result and "TV" in result

    async def test_no_smarthome_agent(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        agent = MediaCastAgent()
        with patch(
            "agents.core.get_agent",
            return_value=None,
        ):
            result = await agent._turn_on_tv({}, "en")
            assert result is None

    async def test_exception(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        agent = MediaCastAgent()
        with patch(
            "agents.core.get_agent",
            side_effect=Exception("fail"),
        ):
            result = await agent._turn_on_tv({}, "en")
            assert result is None


class TestSearchYoutube:
    """Tests for _search_youtube method."""

    async def test_no_service(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        agent = MediaCastAgent()
        with patch(
            "agents.specialized.media_cast_agent.get_service",
            return_value=None,
        ):
            result = await agent._search_youtube("test", "en")
            assert result == []

    async def test_service_not_initialized(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        agent = MediaCastAgent()
        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = False
        mock_svc.initialize = AsyncMock()
        mock_svc.search_videos = AsyncMock(return_value=[{"title": "V1", "id": "x"}])
        with patch(
            "agents.specialized.media_cast_agent.get_service",
            return_value=mock_svc,
        ):
            result = await agent._search_youtube("test", "en")
            mock_svc.initialize.assert_awaited_once()
            assert len(result) == 1

    async def test_exception(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        agent = MediaCastAgent()
        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = True
        mock_svc.search_videos = AsyncMock(side_effect=Exception("boom"))
        with patch(
            "agents.specialized.media_cast_agent.get_service",
            return_value=mock_svc,
        ):
            result = await agent._search_youtube("test", "en")
            assert result == []

    async def test_returns_none_converted_to_empty(self):
        from agents.specialized.media_cast_agent import MediaCastAgent

        agent = MediaCastAgent()
        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = True
        mock_svc.search_videos = AsyncMock(return_value=None)
        with patch(
            "agents.specialized.media_cast_agent.get_service",
            return_value=mock_svc,
        ):
            result = await agent._search_youtube("test", "en")
            assert result == []
