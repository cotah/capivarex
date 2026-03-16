"""Tests for morning briefing and meeting briefing services."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.morning_briefing_service import (
    generate_morning_briefing,
    _get_greeting,
    _weather_icon,
)


class TestMorningBriefing:
    """Tests for morning briefing generation."""

    @pytest.mark.asyncio
    async def test_greeting_function(self):
        greeting = _get_greeting()
        assert greeting in ("Good morning", "Good afternoon", "Good evening")

    def test_weather_icon(self):
        assert _weather_icon("clear sky") == "☀️"
        assert _weather_icon("light rain") == "🌧️"
        assert _weather_icon("overcast clouds") == "☁️"
        assert _weather_icon("snow") == "❄️"
        assert _weather_icon("thunderstorm") == "⛈️"
        assert _weather_icon("fog") == "🌫️"
        assert _weather_icon("partly cloudy") == "☁️"
        assert _weather_icon("unknown") == "🌤️"

    @pytest.mark.asyncio
    async def test_generate_briefing_basic(self):
        """Test briefing generation with mocked services."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_current_weather.return_value = {
            "temperature": 12, "description": "partly cloudy"
        }

        mock_calendar = MagicMock()
        mock_calendar.is_initialized.return_value = True
        mock_calendar.async_get_today_events = AsyncMock(return_value=[
            {"time": "09:00", "summary": "Team standup"},
            {"time": "14:00", "summary": "Client call"},
        ])

        mock_finance = MagicMock()
        mock_finance.is_initialized.return_value = True
        mock_finance.get_watchlist_summary.return_value = {
            "AAPL": {"change_pct": 2.5},
            "TSLA": {"change_pct": -1.3},
        }

        def fake_get_service(name):
            return {
                "database": mock_db,
                "weather": mock_weather,
                "calendar": mock_calendar,
                "finance": mock_finance,
                "crypto": None,
                "notification": None,
            }.get(name)

        with patch("services.business.morning_briefing_service.get_service", fake_get_service):
            result = await generate_morning_briefing(
                user_id="test-user-123",
                user_name="Marcos Silva",
                location="Dublin",
            )

        assert result is not None
        assert "Marcos" in result["message"]
        assert "12°C" in result["message"]
        assert "Team standup" in result["message"]
        assert "AAPL" in result["message"]

    @pytest.mark.asyncio
    async def test_briefing_deduplication(self):
        """Test that briefing is not sent twice in same day."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "already-sent"}]
        )

        with patch("services.business.morning_briefing_service.get_service", return_value=mock_db):
            result = await generate_morning_briefing(
                user_id="test-user-123",
                user_name="Marcos",
            )

        assert result is None  # Already sent today

    @pytest.mark.asyncio
    async def test_briefing_no_events(self):
        """Test briefing with empty calendar."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        mock_calendar = MagicMock()
        mock_calendar.is_initialized.return_value = True
        mock_calendar.async_get_today_events = AsyncMock(return_value=[])

        def fake_get_service(name):
            return {
                "database": mock_db,
                "weather": None,
                "calendar": mock_calendar,
                "finance": None,
                "crypto": None,
                "notification": None,
            }.get(name)

        with patch("services.business.morning_briefing_service.get_service", fake_get_service):
            result = await generate_morning_briefing(
                user_id="test-user-456",
                user_name="Ana",
            )

        assert result is not None
        assert "No events today" in result["message"]
        assert "Ana" in result["message"]


class TestMorningBriefingHelpers:
    """Additional tests for helper functions and edge cases."""

    @pytest.mark.asyncio
    async def test_get_weather_no_service(self):
        from services.business.morning_briefing_service import _get_weather
        with patch("services.business.morning_briefing_service.get_service", return_value=None):
            result = await _get_weather("Dublin")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_today_events_no_service(self):
        from services.business.morning_briefing_service import _get_today_events
        with patch("services.business.morning_briefing_service.get_service", return_value=None):
            result = await _get_today_events("user-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_finance_no_service(self):
        from services.business.morning_briefing_service import _get_finance_summary
        with patch("services.business.morning_briefing_service.get_service", return_value=None):
            result = await _get_finance_summary("user-123")
        assert result is None

    @pytest.mark.asyncio
    async def test_store_briefing_no_db(self):
        from services.business.morning_briefing_service import _store_briefing
        with patch("services.business.morning_briefing_service.get_service", return_value=None):
            await _store_briefing("user-123", "title", "msg")  # Should not crash

    @pytest.mark.asyncio
    async def test_briefing_sent_today_no_db(self):
        from services.business.morning_briefing_service import _briefing_sent_today
        with patch("services.business.morning_briefing_service.get_service", return_value=None):
            result = await _briefing_sent_today("user-123")
        assert result is False

    @pytest.mark.asyncio
    async def test_briefing_with_finance_crypto(self):
        """Test briefing includes crypto data."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

        mock_crypto = MagicMock()
        mock_crypto.is_initialized.return_value = True
        mock_crypto.get_top_coins.return_value = [
            {"symbol": "btc", "price_change_percentage_24h": 3.5},
            {"symbol": "eth", "price_change_percentage_24h": -1.2},
        ]

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "crypto":
                return mock_crypto
            return None

        with patch("services.business.morning_briefing_service.get_service", fake_svc):
            result = await generate_morning_briefing(user_id="test-u", user_name="Test")

        assert result is not None
        assert "BTC" in result["message"]
        assert "ETH" in result["message"]
