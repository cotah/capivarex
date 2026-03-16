"""Tests for weather alert service — A7: proactive severe weather warnings."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.weather_alert_service import (
    check_weather_alerts,
    generate_weather_alert,
    check_weather_for_all_users,
    _get_user_location,
)


class TestWeatherAlerts:
    """Tests for weather condition detection."""

    @pytest.mark.asyncio
    async def test_no_weather_service(self):
        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await check_weather_alerts("u1", "Dublin")
        assert result == []

    @pytest.mark.asyncio
    async def test_rain_alert(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 12, "description": "cloudy", "rain_chance": 85, "wind_speed": 10,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dublin")
        assert len(result) == 1
        assert result[0]["type"] == "rain"
        assert "umbrella" in result[0]["advice"].lower()

    @pytest.mark.asyncio
    async def test_wind_alert(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 15, "description": "windy", "rain_chance": 10, "wind_speed": 60,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dublin")
        assert any(a["type"] == "wind" for a in result)

    @pytest.mark.asyncio
    async def test_heat_alert(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 38, "description": "sunny", "rain_chance": 0, "wind_speed": 5,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Lisbon")
        assert any(a["type"] == "heat" for a in result)

    @pytest.mark.asyncio
    async def test_snow_alert(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": -2, "description": "Snow showers", "rain_chance": 90, "wind_speed": 20,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Helsinki")
        assert any(a["type"] == "snow" for a in result)

    @pytest.mark.asyncio
    async def test_temp_drop_alert(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 18, "description": "cloudy", "feels_like": 5,
            "rain_chance": 10, "wind_speed": 30,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dublin")
        assert any(a["type"] == "temp_drop" for a in result)

    @pytest.mark.asyncio
    async def test_no_alerts(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 20, "description": "sunny", "rain_chance": 5,
            "wind_speed": 10, "feels_like": 20,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dublin")
        assert result == []

    @pytest.mark.asyncio
    async def test_multiple_alerts(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 36, "description": "hot", "rain_chance": 80,
            "wind_speed": 55, "feels_like": 36,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dubai")
        assert len(result) >= 3  # rain + wind + heat


class TestUserLocation:
    """Tests for user location retrieval."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await _get_user_location("u1")
        assert result == ""

    @pytest.mark.asyncio
    async def test_no_location_returns_empty(self):
        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await check_weather_alerts("u1")
        assert result == []


class TestAlertGeneration:
    """Tests for humanized alerts."""

    @pytest.mark.asyncio
    async def test_no_alerts(self):
        result = await generate_weather_alert("Marcos", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_rain(self):
        alerts = [{"type": "rain", "severity": "warning", "message": "Rain likely (85%)", "advice": "Bring an umbrella!"}]

        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await generate_weather_alert("Marcos", alerts)
        assert "Marcos" in result
        assert "🌧️" in result

    @pytest.mark.asyncio
    async def test_fallback_multiple(self):
        alerts = [
            {"type": "rain", "severity": "warning", "message": "Rain 80%", "advice": "Umbrella"},
            {"type": "wind", "severity": "warning", "message": "Wind 55 km/h", "advice": "Be careful"},
        ]

        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await generate_weather_alert("Ana", alerts)
        assert "🌧️" in result
        assert "💨" in result

    @pytest.mark.asyncio
    async def test_gpt_alert(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "🌧️ Heads up, Marcos! Rain is expected in the next hour (85% chance). "
            "Grab an umbrella before heading out! Stay dry! 👋"
        )

        alerts = [{"type": "rain", "severity": "warning", "message": "Rain 85%", "advice": "Umbrella"}]

        with patch("services.business.weather_alert_service.get_service", return_value=mock_openai):
            result = await generate_weather_alert("Marcos", alerts)
        assert "Marcos" in result


class TestProactivityLoop:
    """Tests for the loop runner."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await check_weather_for_all_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_users(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[])

        with patch("services.business.weather_alert_service.get_service", return_value=mock_db):
            result = await check_weather_for_all_users()
        assert result == 0


class TestEdgeCases:
    """Edge cases for coverage."""

    @pytest.mark.asyncio
    async def test_weather_exception(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(side_effect=Exception("API error"))

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dublin")
        assert result == []

    @pytest.mark.asyncio
    async def test_weather_returns_none(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value=None)

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Dublin")
        assert result == []

    @pytest.mark.asyncio
    async def test_snow_pt_keyword(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": 0, "description": "Neve forte", "rain_chance": 0, "wind_speed": 10,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Serra da Estrela")
        assert any(a["type"] == "snow" for a in result)

    @pytest.mark.asyncio
    async def test_freezing_keyword(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value={
            "temperature": -5, "description": "Freezing rain", "rain_chance": 90, "wind_speed": 15,
        })

        with patch("services.business.weather_alert_service.get_service", return_value=mock_weather):
            result = await check_weather_alerts("u1", "Moscow")
        types = [a["type"] for a in result]
        assert "snow" in types
        assert "rain" in types

    @pytest.mark.asyncio
    async def test_fallback_snow_emoji(self):
        alerts = [{"type": "snow", "severity": "alert", "message": "Snow showers", "advice": "Drive carefully"}]

        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await generate_weather_alert("Test", alerts)
        assert "❄️" in result

    @pytest.mark.asyncio
    async def test_fallback_heat_emoji(self):
        alerts = [{"type": "heat", "severity": "warning", "message": "38°C", "advice": "Stay hydrated"}]

        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await generate_weather_alert("Test", alerts)
        assert "🌡️" in result

    @pytest.mark.asyncio
    async def test_fallback_temp_drop_emoji(self):
        alerts = [{"type": "temp_drop", "severity": "info", "message": "Feels colder", "advice": "Extra layers"}]

        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await generate_weather_alert("Test", alerts)
        assert "🧥" in result

    @pytest.mark.asyncio
    async def test_user_location_from_db(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"location": "Dublin", "city": "Dublin"}]
        )

        with patch("services.business.weather_alert_service.get_service", return_value=mock_db):
            result = await _get_user_location("u1")
        assert result == "Dublin"

    @pytest.mark.asyncio
    async def test_filter_already_alerted_no_db(self):
        from services.business.weather_alert_service import _filter_already_alerted
        alerts = [{"type": "rain", "severity": "warning", "message": "Rain", "advice": "Umbrella"}]
        with patch("services.business.weather_alert_service.get_service", return_value=None):
            result = await _filter_already_alerted("u1", alerts)
        assert result == alerts

    @pytest.mark.asyncio
    async def test_filter_removes_already_sent(self):
        import json
        from services.business.weather_alert_service import _filter_already_alerted
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"metadata": json.dumps({"alert_types": ["rain"]})}]
        )

        alerts = [
            {"type": "rain", "severity": "warning", "message": "Rain", "advice": "Umbrella"},
            {"type": "wind", "severity": "warning", "message": "Wind", "advice": "Be careful"},
        ]
        with patch("services.business.weather_alert_service.get_service", return_value=mock_db):
            result = await _filter_already_alerted("u1", alerts)
        assert len(result) == 1
        assert result[0]["type"] == "wind"

    @pytest.mark.asyncio
    async def test_store_weather_alert_no_db(self):
        from services.business.weather_alert_service import _store_weather_alert
        with patch("services.business.weather_alert_service.get_service", return_value=None):
            await _store_weather_alert("u1", [{"type": "rain", "message": "Rain"}])

    @pytest.mark.asyncio
    async def test_store_weather_alert_success(self):
        from services.business.weather_alert_service import _store_weather_alert
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch("services.business.weather_alert_service.get_service", return_value=mock_db):
            await _store_weather_alert("u1", [{"type": "rain", "message": "Rain 80%"}])
