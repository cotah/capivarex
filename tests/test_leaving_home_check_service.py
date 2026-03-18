"""Tests for leaving home check service — A2: departure briefing."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.leaving_home_check_service import (
    is_leaving_trigger,
    generate_departure_briefing,
    _check_weather,
    _check_next_event,
    # _check_smart_home,  # PAUSED — TODO: Reativar no Q3 2026
    _humanize_briefing,
)


class TestLeavingTrigger:
    """Tests for trigger keyword detection."""

    def test_pt_vou_sair(self):
        assert is_leaving_trigger("vou sair") is True

    def test_pt_saindo(self):
        assert is_leaving_trigger("estou saindo de casa agora") is True

    def test_en_leaving(self):
        assert is_leaving_trigger("I'm leaving now") is True

    def test_en_heading_out(self):
        assert is_leaving_trigger("heading out, see you later") is True

    def test_es_me_voy(self):
        assert is_leaving_trigger("me voy de casa") is True

    def test_not_trigger(self):
        assert is_leaving_trigger("que horas são?") is False

    def test_not_trigger_similar(self):
        assert is_leaving_trigger("I'm not leaving yet") is False


class TestWeatherCheck:
    """Tests for weather during departure."""

    @pytest.mark.asyncio
    async def test_no_weather_service(self):
        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=None,
        ):
            result = await _check_weather("Dublin")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_location(self):
        assert await _check_weather("") is None

    @pytest.mark.asyncio
    async def test_weather_with_rain(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(
            return_value={
                "temperature": 12,
                "description": "cloudy",
                "feels_like": 10,
                "rain_chance": 80,
                "wind_speed": 15,
            }
        )

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_weather,
        ):
            result = await _check_weather("Dublin")
        assert result is not None
        assert "umbrella" in result.lower()

    @pytest.mark.asyncio
    async def test_weather_no_warnings(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(
            return_value={
                "temperature": 22,
                "description": "sunny",
                "feels_like": 22,
                "rain_chance": 5,
                "wind_speed": 10,
            }
        )

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_weather,
        ):
            result = await _check_weather("Dublin")
        assert result is not None
        assert "umbrella" not in result.lower()


class TestNextEvent:
    """Tests for calendar check."""

    @pytest.mark.asyncio
    async def test_no_services(self):
        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=None,
        ):
            result = await _check_next_event("u1", "Dublin")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_events(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[])

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            return None

        with patch(
            "services.business.leaving_home_check_service.get_service", fake_svc
        ):
            result = await _check_next_event("u1", "")
        assert result is not None
        assert "no events" in result.lower() or "enjoy" in result.lower()


# TestSmartHome: PAUSED — _check_smart_home removed (Grupo 2 — Q3 2026)


class TestFullBriefing:
    """Tests for complete departure briefing."""

    @pytest.mark.asyncio
    async def test_no_data(self):
        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=None,
        ):
            result = await generate_departure_briefing("u1", "Marcos")
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_briefing(self):
        result = await _humanize_briefing(
            "Marcos",
            {
                "weather": "12°C, cloudy. ⚠️ rain likely — bring an umbrella",
                "event": "Next: Team Meeting at 15:00",
            },
        )
        assert "Marcos" in result
        assert "🌤️" in result or "📅" in result


class TestBriefingGPT:
    """Tests for GPT humanization."""

    @pytest.mark.asyncio
    async def test_gpt_humanize(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "☀️ Hey Marcos! It's 22°C and sunny — perfect day to head out! "
            "📅 You have a meeting at 15:00. Have a great one! 👋"
        )

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_openai,
        ):
            result = await _humanize_briefing(
                "Marcos", {"weather": "22°C sunny", "event": "Meeting 15:00"}
            )
        assert "Marcos" in result


class TestEdgeCases:
    """Edge cases for coverage."""

    @pytest.mark.asyncio
    async def test_weather_exception(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(side_effect=Exception("API error"))

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_weather,
        ):
            result = await _check_weather("Dublin")
        assert result is None

    # test_smarthome_exception: PAUSED — _check_smart_home removed (Grupo 2 — Q3 2026)

    @pytest.mark.asyncio
    async def test_weather_no_data(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(return_value=None)

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_weather,
        ):
            result = await _check_weather("Dublin")
        assert result is None

    @pytest.mark.asyncio
    async def test_weather_strong_wind(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(
            return_value={
                "temperature": 18,
                "description": "windy",
                "wind_speed": 50,
            }
        )

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_weather,
        ):
            result = await _check_weather("Dublin")
        assert "wind" in result.lower()

    # test_smarthome_no_devices: PAUSED — _check_smart_home removed (Grupo 2 — Q3 2026)

    @pytest.mark.asyncio
    async def test_briefing_weather_only(self):
        """Briefing with only weather data."""
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(
            return_value={
                "temperature": 15,
                "description": "cloudy",
                "rain_chance": 10,
            }
        )

        def fake_svc(name):
            if name == "weather":
                return mock_weather
            return None

        with patch(
            "services.business.leaving_home_check_service.get_service", fake_svc
        ):
            result = await generate_departure_briefing("u1", "Marcos", "Dublin")
        assert result is not None
        assert "Marcos" in result

    @pytest.mark.asyncio
    async def test_weather_slight_rain(self):
        mock_weather = MagicMock()
        mock_weather.is_initialized.return_value = True
        mock_weather.get_weather = AsyncMock(
            return_value={
                "temperature": 16,
                "description": "partly cloudy",
                "feels_like": 14,
                "rain_chance": 35,
                "wind_speed": 8,
            }
        )

        with patch(
            "services.business.leaving_home_check_service.get_service",
            return_value=mock_weather,
        ):
            result = await _check_weather("Dublin")
        assert "slight" in result.lower() or "rain" in result.lower()

    @pytest.mark.asyncio
    async def test_next_event_from_calendar(self):
        """Calendar returns an upcoming event."""
        from datetime import datetime, timezone, timedelta

        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        future = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                {"summary": "Team Standup", "start": future, "location": "Office"},
            ]
        )

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            return None

        with patch(
            "services.business.leaving_home_check_service.get_service", fake_svc
        ):
            result = await _check_next_event("u1", "")
        assert result is not None
        assert "Team Standup" in result

    @pytest.mark.asyncio
    async def test_next_event_exception(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(side_effect=Exception("fail"))

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            return None

        with patch(
            "services.business.leaving_home_check_service.get_service", fake_svc
        ):
            result = await _check_next_event("u1", "")
        assert result is None

    # test_next_event_with_leaving_service: PAUSED — leaving_now service removed (Grupo 2 — Q3 2026)
    # @pytest.mark.asyncio
    # async def test_next_event_with_leaving_service(self):
    #     ...

    @pytest.mark.asyncio
    async def _placeholder_test_leaving_paused(self):
        """Placeholder — leaving_now paused."""
        pass

    @pytest.mark.asyncio
    async def test_next_event_calendar_fallback(self):
        """Without leaving_now, falls back to calendar — no events returns enjoy message."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[])

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            return None

        with patch(
            "services.business.leaving_home_check_service.get_service", fake_svc
        ):
            result = await _check_next_event("u1", "Dublin")
        assert result is not None
        assert "No events" in result or "enjoy" in result
