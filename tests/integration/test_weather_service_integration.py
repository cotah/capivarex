"""Integration tests for WeatherService with mocked HTTP responses."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from aiohttp import ClientResponseError

from services.integrations.weather_service import WeatherService


def _make_service():
    svc = WeatherService()
    svc.api_key = "fake-api-key"
    svc._initialized = True
    return svc


def _weather_api_response():
    """Sample WeatherAPI.com current weather response."""
    return {
        "location": {
            "name": "São Paulo",
            "region": "Sao Paulo",
            "country": "Brazil",
            "lat": -23.55,
            "lon": -46.63,
            "localtime": "2026-02-19 14:00",
        },
        "current": {
            "temp_c": 28.0,
            "temp_f": 82.4,
            "condition": {"text": "Partly cloudy", "icon": "//cdn/icon.png"},
            "humidity": 65,
            "wind_kph": 15.0,
            "wind_mph": 9.3,
            "feelslike_c": 30.0,
            "feelslike_f": 86.0,
        },
    }


def _forecast_api_response():
    """Sample WeatherAPI.com forecast response."""
    return {
        "location": {
            "name": "São Paulo",
            "region": "Sao Paulo",
            "country": "Brazil",
        },
        "forecast": {
            "forecastday": [
                {
                    "date": "2026-02-20",
                    "day": {
                        "maxtemp_c": 30.0,
                        "mintemp_c": 22.0,
                        "maxtemp_f": 86.0,
                        "mintemp_f": 71.6,
                        "condition": {"text": "Sunny", "icon": "//cdn/sunny.png"},
                        "daily_chance_of_rain": 10,
                    },
                },
                {
                    "date": "2026-02-21",
                    "day": {
                        "maxtemp_c": 28.0,
                        "mintemp_c": 20.0,
                        "maxtemp_f": 82.4,
                        "mintemp_f": 68.0,
                        "condition": {"text": "Rain", "icon": "//cdn/rain.png"},
                        "daily_chance_of_rain": 80,
                    },
                },
            ]
        },
    }


class TestGetCurrentWeather:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=_weather_api_response())
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.integrations.weather_service.aiohttp.ClientSession", return_value=mock_session):
            result = await svc.get_current_weather("São Paulo")

        assert result["location"]["name"] == "São Paulo"
        assert result["current"]["temp_c"] == 28.0
        assert result["current"]["humidity"] == 65
        assert result["current"]["condition"] == "Partly cloudy"

    @pytest.mark.asyncio
    async def test_api_error(self):
        svc = _make_service()
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("403 Forbidden"))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.integrations.weather_service.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(RuntimeError, match="Erro ao buscar clima"):
                await svc.get_current_weather("InvalidCity")

    @pytest.mark.asyncio
    async def test_initializes_when_no_api_key(self):
        svc = _make_service()
        svc.api_key = None
        svc.initialize = AsyncMock()

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=_weather_api_response())
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.integrations.weather_service.aiohttp.ClientSession", return_value=mock_session):
            await svc.get_current_weather("SP")

        svc.initialize.assert_called_once()


class TestGetForecast:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value=_forecast_api_response())
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.integrations.weather_service.aiohttp.ClientSession", return_value=mock_session):
            result = await svc.get_forecast("São Paulo", days=2)

        assert result["location"]["name"] == "São Paulo"
        assert len(result["forecast"]) == 2
        assert result["forecast"][0]["date"] == "2026-02-20"
        assert result["forecast"][0]["max_temp_c"] == 30.0
        assert result["forecast"][1]["chance_of_rain"] == 80

    @pytest.mark.asyncio
    async def test_api_error(self):
        svc = _make_service()
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock(side_effect=Exception("timeout"))
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("services.integrations.weather_service.aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(RuntimeError, match="Erro ao buscar previsão"):
                await svc.get_forecast("InvalidCity")


class TestGetWeatherAlias:
    @pytest.mark.asyncio
    async def test_alias_calls_get_current_weather(self):
        svc = _make_service()
        svc.get_current_weather = AsyncMock(return_value={"temp": 25})
        result = await svc.get_weather("SP")
        svc.get_current_weather.assert_called_once_with("SP")
        assert result == {"temp": 25}


class TestHealthCheck:
    @pytest.mark.asyncio
    async def test_healthy_with_api_key(self):
        svc = _make_service()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_unhealthy_without_api_key(self):
        svc = _make_service()
        svc.api_key = None
        assert await svc._health_check() is False
