"""Tests for Discovery Engine service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.discovery_engine_service import (
    generate_discovery,
    _get_user_interests,
    _pick_category,
    _fallback_discovery,
    _generate_fallback_discovery,
    _is_on_cooldown,
)


class TestPickCategory:
    def test_with_location(self):
        cat = _pick_category(["food", "travel"], "Dublin")
        assert cat in ["restaurant", "event", "article", "tip"]

    def test_food_interest_boost(self):
        # With food interest, restaurant should be more likely
        results = [_pick_category(["food", "cooking"], "Dublin") for _ in range(50)]
        assert "restaurant" in results

    def test_tech_interest_boost(self):
        results = [_pick_category(["technology", "ai"], "") for _ in range(50)]
        assert "article" in results

    def test_no_location(self):
        cat = _pick_category(["music"], "")
        assert cat in ["restaurant", "event", "article", "tip"]


class TestFallbackDiscovery:
    def test_restaurant(self):
        d = _fallback_discovery("restaurant", ["food"])
        assert "title" in d
        assert "description" in d

    def test_event(self):
        d = _fallback_discovery("event", [])
        assert "title" in d

    def test_article(self):
        d = _fallback_discovery("article", ["tech"])
        assert "tech" in d["title"].lower() or "title" in d

    def test_tip(self):
        d = _fallback_discovery("tip", [])
        assert "title" in d

    def test_unknown(self):
        d = _fallback_discovery("unknown", [])
        assert "title" in d


class TestFallbackMessage:
    def test_with_name(self):
        discovery = {
            "title": "Sushi Place",
            "description": "Amazing sushi",
            "why": "You love Japanese food",
        }
        msg = _generate_fallback_discovery("João", "restaurant", discovery)
        assert "Achei algo" in msg
        assert "Sushi Place" in msg
        assert "João" in msg

    def test_no_name(self):
        discovery = {"title": "Tech Article", "description": "AI trends"}
        msg = _generate_fallback_discovery("", "article", discovery)
        assert "Achei algo" in msg
        assert "Tech Article" in msg

    def test_with_why(self):
        discovery = {
            "title": "Event",
            "description": "Music fest",
            "why": "You love music",
        }
        msg = _generate_fallback_discovery("Ana", "event", discovery)
        assert "music" in msg.lower()


class TestGetInterests:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.discovery_engine_service.get_service", return_value=None
        ):
            result = await _get_user_interests("u1")
        assert len(result) > 0  # Returns defaults

    @pytest.mark.asyncio
    async def test_with_stored(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": '["music", "tech", "food"]'}]
        )
        with patch(
            "services.business.discovery_engine_service.get_service",
            return_value=mock_db,
        ):
            result = await _get_user_interests("u1")
        assert "music" in result

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.discovery_engine_service.get_service",
            return_value=mock_db,
        ):
            result = await _get_user_interests("u1")
        assert len(result) > 0  # Falls back to defaults


class TestCooldown:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.discovery_engine_service.get_service", return_value=None
        ):
            assert await _is_on_cooldown("u1") is False

    @pytest.mark.asyncio
    async def test_on_cooldown(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
            count=3
        )
        with patch(
            "services.business.discovery_engine_service.get_service",
            return_value=mock_db,
        ):
            assert await _is_on_cooldown("u1") is True

    @pytest.mark.asyncio
    async def test_not_on_cooldown(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
            count=0
        )
        with patch(
            "services.business.discovery_engine_service.get_service",
            return_value=mock_db,
        ):
            assert await _is_on_cooldown("u1") is False


class TestGenerateDiscovery:
    @pytest.mark.asyncio
    async def test_on_cooldown(self):
        with patch(
            "services.business.discovery_engine_service._is_on_cooldown",
            new_callable=AsyncMock,
            return_value=True,
        ):
            result = await generate_discovery("u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_full_flow(self):
        discovery = {
            "title": "Cool Place",
            "description": "Nice spot",
            "why": "Matches your taste",
        }
        with (
            patch(
                "services.business.discovery_engine_service._is_on_cooldown",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "services.business.discovery_engine_service._get_user_interests",
                new_callable=AsyncMock,
                return_value=["food", "tech"],
            ),
            patch(
                "services.business.discovery_engine_service._generate_by_category",
                new_callable=AsyncMock,
                return_value=discovery,
            ),
            patch(
                "services.business.discovery_engine_service._generate_ai_discovery",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "services.business.discovery_engine_service._store_discovery",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_discovery("u1", "João", "Dublin")
        assert result is not None
        assert "Achei algo" in result["text"]
        assert result["category"] in ["restaurant", "event", "article", "tip"]

    @pytest.mark.asyncio
    async def test_no_discovery_generated(self):
        with (
            patch(
                "services.business.discovery_engine_service._is_on_cooldown",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "services.business.discovery_engine_service._get_user_interests",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.discovery_engine_service._generate_by_category",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await generate_discovery("u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_forced_category(self):
        discovery = {"title": "Event X", "description": "Fun event"}
        with (
            patch(
                "services.business.discovery_engine_service._is_on_cooldown",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "services.business.discovery_engine_service._get_user_interests",
                new_callable=AsyncMock,
                return_value=["music"],
            ),
            patch(
                "services.business.discovery_engine_service._generate_by_category",
                new_callable=AsyncMock,
                return_value=discovery,
            ),
            patch(
                "services.business.discovery_engine_service._generate_ai_discovery",
                new_callable=AsyncMock,
                return_value="💡 AI discovery!",
            ),
            patch(
                "services.business.discovery_engine_service._store_discovery",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_discovery("u1", "Ana", "Dublin", category="event")
        assert result["text"] == "💡 AI discovery!"
        assert result["category"] == "event"


class TestStoreDiscovery:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.discovery_engine_service import _store_discovery

        with patch(
            "services.business.discovery_engine_service.get_service", return_value=None
        ):
            await _store_discovery("u1", "text", {})

    @pytest.mark.asyncio
    async def test_store_exception(self):
        from services.business.discovery_engine_service import _store_discovery

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.discovery_engine_service.get_service",
            return_value=mock_db,
        ):
            await _store_discovery("u1", "text", {})
