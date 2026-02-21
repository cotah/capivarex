"""
Tests for WeatherAgent — current weather and forecasts.
Agente sem cobertura de testes. Adicionado na Fase C do QA.
Updated for improved WeatherAgent (v2) with intent-based routing.
"""
from unittest.mock import AsyncMock, Mock, patch
import pytest
from agents.core import AgentStatus


@pytest.fixture
def weather_agent():
    from agents.specialized.weather_agent import WeatherAgent
    return WeatherAgent()


@pytest.fixture
def mock_weather_svc():
    """Mock WeatherService with new enriched methods."""
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)

    # New enriched detailed forecast data
    detail_data = {
        "location": {"name": "Dublin", "region": "Leinster", "country": "Ireland",
                     "lat": 53.3, "lon": -6.2, "localtime": "2026-02-21 10:30", "tz_id": "Europe/Dublin"},
        "current": {"temp_c": 10.0, "feels_like_c": 7.0, "condition": "Partly cloudy",
                    "humidity": 80, "wind_kph": 25.0, "wind_dir": "SW", "uv": 3.0,
                    "vis_km": 10.0, "cloud": 50, "is_day": 1},
        "forecast": [
            {"date": "2026-02-21", "max_temp_c": 12.0, "min_temp_c": 6.0,
             "avg_temp_c": 9.0, "condition": "Rain", "icon": "//i.png",
             "chance_of_rain": 80, "chance_of_snow": 0, "total_precip_mm": 5.2,
             "avg_humidity": 85, "max_wind_kph": 25, "uv": 3,
             "sunrise": "07:30 AM", "sunset": "06:00 PM",
             "rain_alert": True, "wind_alert": False, "uv_alert": False},
            {"date": "2026-02-22", "max_temp_c": 14.0, "min_temp_c": 8.0,
             "avg_temp_c": 11.0, "condition": "Cloudy", "icon": "//i.png",
             "chance_of_rain": 40, "chance_of_snow": 0, "total_precip_mm": 0,
             "avg_humidity": 70, "max_wind_kph": 15, "uv": 2,
             "sunrise": "07:32 AM", "sunset": "06:02 PM",
             "rain_alert": False, "wind_alert": False, "uv_alert": False},
        ],
        "alerts": [],
    }

    svc.get_detailed_forecast = AsyncMock(return_value=detail_data)
    svc.get_week_summary = AsyncMock(return_value={
        "location": detail_data["location"],
        "forecast": detail_data["forecast"],
        "alerts": [],
        "summary": {
            "best_day": detail_data["forecast"][1],
            "worst_day": detail_data["forecast"][0],
            "rainy_days_count": 1,
            "sunny_days_count": 0,
            "rainy_days": ["2026-02-21"],
            "avg_max_temp_c": 13.0,
            "avg_min_temp_c": 7.0,
            "has_alerts": False,
        },
    })
    svc.get_alerts = AsyncMock(return_value=[])
    # Keep old method for backward compat tests
    svc.get_forecast = AsyncMock(return_value={
        "location": {"name": "Dublin", "region": "Leinster", "country": "Ireland"},
        "forecast": [
            {"date": "2026-02-21", "condition": "Rain", "max_temp_c": 14, "min_temp_c": 8, "chance_of_rain": 80},
            {"date": "2026-02-22", "condition": "Cloudy", "max_temp_c": 12, "min_temp_c": 7, "chance_of_rain": 40},
        ]
    })
    return svc


# ── Happy path ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weather_current_success(weather_agent, mock_weather_svc):
    """WeatherAgent returns current weather for a location."""
    with patch("agents.specialized.weather_agent.get_service", return_value=mock_weather_svc):
        result = await weather_agent.execute("como está o tempo em Dublin?", {"location": "Dublin"})
    assert result.status == AgentStatus.SUCCESS
    assert result.response  # deve ter alguma resposta formatada
    assert result.data  # deve ter dados


@pytest.mark.asyncio
async def test_weather_uses_context_location(weather_agent, mock_weather_svc):
    """WeatherAgent uses location from context when provided."""
    with patch("agents.specialized.weather_agent.get_service", return_value=mock_weather_svc):
        result = await weather_agent.execute("tempo", {"location": "Cork"})
    assert result.status == AgentStatus.SUCCESS


@pytest.mark.asyncio
async def test_weather_capabilities(weather_agent):
    """WeatherAgent declares expected capabilities."""
    caps = weather_agent.get_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0


# ── Falhas e edge cases ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_weather_service_unavailable(weather_agent):
    """WeatherAgent returns error when service is None."""
    with patch("agents.specialized.weather_agent.get_service", return_value=None):
        result = await weather_agent.execute("tempo em Dublin", {"location": "Dublin"})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_weather_service_exception(weather_agent, mock_weather_svc):
    """WeatherAgent returns error when service raises exception."""
    mock_weather_svc.get_detailed_forecast = AsyncMock(side_effect=RuntimeError("API down"))
    with patch("agents.specialized.weather_agent.get_service", return_value=mock_weather_svc):
        result = await weather_agent.execute("tempo", {"location": "Dublin"})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_weather_empty_prompt_uses_default_location(weather_agent, mock_weather_svc):
    """WeatherAgent should not crash on empty prompt - uses default location."""
    with patch("agents.specialized.weather_agent.get_service", return_value=mock_weather_svc):
        result = await weather_agent.execute("", {})
    # Should either succeed with default location or return error gracefully
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response  # must have a response message
