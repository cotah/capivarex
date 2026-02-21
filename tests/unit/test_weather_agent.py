"""Unit tests for WeatherAgent (improved v2 with intents)."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from agents.core import AgentStatus
from agents.specialized.weather_agent import WeatherAgent, LOCATION_PATTERN


@pytest.fixture
def agent():
    return WeatherAgent()


@pytest.fixture
def mock_svc():
    """Mock WeatherService with enriched methods for v2 agent."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)

    detail_data = {
        "location": {"name": "Dublin", "region": "Leinster", "country": "Ireland",
                     "lat": 53.3, "lon": -6.2, "localtime": "2026-02-21 10:30", "tz_id": "Europe/Dublin"},
        "current": {"temp_c": 10.0, "feels_like_c": 7.0, "condition": "Rain",
                    "humidity": 80, "wind_kph": 25.0, "wind_dir": "SW", "uv": 3.0,
                    "vis_km": 10.0, "cloud": 50, "is_day": 1},
        "forecast": [
            {"date": "2026-02-21", "max_temp_c": 12.0, "min_temp_c": 6.0,
             "avg_temp_c": 9.0, "condition": "Rain", "icon": "//i.png",
             "chance_of_rain": 80, "chance_of_snow": 0, "total_precip_mm": 5.2,
             "avg_humidity": 85, "max_wind_kph": 25, "uv": 3,
             "sunrise": "07:30 AM", "sunset": "06:00 PM",
             "rain_alert": True, "wind_alert": False, "uv_alert": False},
        ],
        "alerts": [],
    }
    svc.get_detailed_forecast = AsyncMock(return_value=detail_data)
    svc.get_week_summary = AsyncMock(return_value={
        "location": detail_data["location"],
        "forecast": detail_data["forecast"],
        "alerts": [],
        "summary": {
            "best_day": detail_data["forecast"][0],
            "worst_day": detail_data["forecast"][0],
            "rainy_days_count": 1,
            "sunny_days_count": 0,
            "rainy_days": ["2026-02-21"],
            "avg_max_temp_c": 12.0,
            "avg_min_temp_c": 6.0,
            "has_alerts": False,
        },
    })
    svc.get_alerts = AsyncMock(return_value=[])
    return svc


class TestLocationExtraction:
    def test_from_context(self, agent):
        loc = agent._extract_location("anything", {"location": "Cork"})
        assert loc == "Cork"

    def test_from_prompt_em(self, agent):
        loc = agent._extract_location("tempo em Lisboa", {})
        assert loc == "Lisboa"

    def test_from_prompt_in(self, agent):
        loc = agent._extract_location("weather in London", {})
        assert loc == "London"

    def test_fallback_to_prompt(self, agent):
        loc = agent._extract_location("Dublin", {})
        assert loc == "Dublin"

    def test_regex_pattern(self):
        m = LOCATION_PATTERN.search("como esta o tempo em Sao Paulo?")
        assert m is not None
        assert "Sao Paulo" in m.group(1)

    def test_empty_prompt_returns_none(self, agent):
        """Empty prompt with no context returns None (improved v2 behavior)."""
        loc = agent._extract_location("", {})
        assert loc is None


class TestWeatherAgentExecute:
    @pytest.mark.asyncio
    async def test_success(self, agent, mock_svc):
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            result = await agent.execute("tempo em Dublin", {"location": "Dublin"})
        assert result.is_success()
        assert "Dublin" in result.response

    @pytest.mark.asyncio
    async def test_no_service(self, agent):
        with patch("agents.specialized.weather_agent.get_service", return_value=None):
            result = await agent.execute("tempo", {"location": "Dublin"})
        assert result.status == AgentStatus.ERROR
        assert "disponível" in result.response.lower() or "não" in result.response.lower()

    @pytest.mark.asyncio
    async def test_no_location(self, agent, mock_svc):
        """Empty prompt and no context location returns error."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            result = await agent.execute("", {})
        assert result.status == AgentStatus.ERROR

    @pytest.mark.asyncio
    async def test_service_exception(self, agent, mock_svc):
        mock_svc.get_detailed_forecast = AsyncMock(side_effect=RuntimeError("API down"))
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            result = await agent.execute("tempo", {"location": "Dublin"})
        assert result.status == AgentStatus.ERROR

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        assert "current_weather" in caps
        assert "weather_forecast" in caps
        assert "7_day_forecast" in caps
        assert "rain_alerts" in caps
        assert "week_summary" in caps
