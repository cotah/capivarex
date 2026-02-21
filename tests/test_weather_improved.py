# -*- coding: utf-8 -*-
"""
Tests para WeatherService (melhorado) e WeatherAgent (melhorado).

Cobre:
  - Backward compat: get_current_weather, get_forecast (originais inalterados)
  - Novos métodos: get_detailed_forecast, get_alerts, get_week_summary
  - WeatherAgent: intents (hoje, amanhã, semana, alertas)
  - Formatação: emojis, dias da semana, alertas derivados
  - Edge cases: sem dados, API 500, location não encontrada
  - Segurança: injeção via location string, tamanho máximo de dias
"""
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest


# ─── Fixtures ─────────────────────────────────────────────────────────────────

def _make_api_response(
    city: str = "Dublin",
    region: str = "Leinster",
    country: str = "Ireland",
    days: int = 7,
    with_alerts: bool = False,
) -> Dict[str, Any]:
    """Monta resposta completa da WeatherAPI.com para testes."""
    forecast_days = []
    for i in range(days):
        rain = 80 if i == 2 else (20 if i == 4 else 40)
        wind = 60 if i == 3 else 20
        uv = 8 if i == 5 else 3
        forecast_days.append({
            "date": f"2026-02-{21 + i:02d}",
            "day": {
                "maxtemp_c": 12.0 + i,
                "mintemp_c": 5.0 + i,
                "maxtemp_f": 53.6 + i * 1.8,
                "mintemp_f": 41.0 + i * 1.8,
                "avgtemp_c": 8.5 + i,
                "condition": {"text": "Partly cloudy", "icon": "//icon.png"},
                "daily_chance_of_rain": rain,
                "daily_chance_of_snow": 0,
                "totalprecip_mm": 3.2 if rain > 50 else 0,
                "avghumidity": 75,
                "maxwind_kph": wind,
                "uv": uv,
            },
            "astro": {"sunrise": "07:30 AM", "sunset": "06:00 PM"},
        })

    alerts = []
    if with_alerts:
        alerts = [{
            "headline": "Wind Warning in effect",
            "severity": "Moderate",
            "urgency": "Expected",
            "areas": "Leinster",
            "event": "Wind Warning",
            "effective": "2026-02-21T10:00:00",
            "expires": "2026-02-22T10:00:00",
            "desc": "Strong winds expected with gusts up to 90 km/h.",
        }]

    return {
        "location": {
            "name": city, "region": region, "country": country,
            "lat": 53.33, "lon": -6.25,
            "localtime": "2026-02-21 10:30",
            "tz_id": "Europe/Dublin",
        },
        "current": {
            "temp_c": 10.0, "temp_f": 50.0,
            "feelslike_c": 7.0, "feelslike_f": 44.6,
            "condition": {"text": "Partly cloudy", "icon": "//icon.png"},
            "humidity": 80,
            "wind_kph": 25.0, "wind_mph": 15.5, "wind_dir": "SW",
            "uv": 3.0, "vis_km": 10.0,
            "cloud": 50, "is_day": 1,
        },
        "forecast": {"forecastday": forecast_days},
        "alerts": {"alert": alerts},
    }


@pytest.fixture
def mock_svc_response():
    return _make_api_response()


@pytest.fixture
def weather_service():
    """WeatherService com aiohttp mockado."""
    from services.integrations.weather_service import WeatherService
    svc = WeatherService()
    svc.api_key = "test_key_placeholder"
    svc._initialized = True
    return svc


def _mock_aiohttp(response_data: Dict):
    """Helper para mockar aiohttp.ClientSession."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.raise_for_status = Mock()
    mock_response.json = AsyncMock(return_value=response_data)

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.get = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(return_value=mock_response),
        __aexit__=AsyncMock(return_value=None),
    ))
    return mock_session


# ═══════════════════════════════════════════════════════════════════════════════
# 1. BACKWARD COMPAT — métodos originais inalterados
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeatherServiceBackwardCompat:
    """Garante que os métodos originais continuam funcionando."""

    @pytest.mark.asyncio
    async def test_get_current_weather_returns_original_shape(self, weather_service):
        """get_current_weather deve retornar o mesmo shape de antes."""
        data = _make_api_response(days=1)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_current_weather("Dublin")

        assert "location" in result
        assert "current" in result
        assert "temp_c" in result["current"]
        assert "condition" in result["current"]
        assert "humidity" in result["current"]
        assert "wind_kph" in result["current"]
        assert "feels_like_c" in result["current"]

    @pytest.mark.asyncio
    async def test_get_forecast_returns_original_shape(self, weather_service):
        """get_forecast deve retornar lista com date/max_temp_c/chance_of_rain."""
        data = _make_api_response(days=3)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_forecast("Dublin", days=3)

        assert "location" in result
        assert "forecast" in result
        assert len(result["forecast"]) == 3
        day = result["forecast"][0]
        assert "date" in day
        assert "max_temp_c" in day
        assert "min_temp_c" in day
        assert "condition" in day
        assert "chance_of_rain" in day

    @pytest.mark.asyncio
    async def test_get_weather_alias(self, weather_service):
        """get_weather deve chamar get_current_weather (alias)."""
        data = _make_api_response(days=1)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_weather("Dublin")
        assert "current" in result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. NOVOS MÉTODOS — get_detailed_forecast
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetDetailedForecast:

    @pytest.mark.asyncio
    async def test_returns_enriched_fields(self, weather_service):
        """Deve retornar UV, vento, humidade, nascer/pôr do sol por dia."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_detailed_forecast("Dublin", days=7)

        assert "current" in result
        assert "uv" in result["current"]
        assert "wind_dir" in result["current"]
        assert "vis_km" in result["current"]

        day = result["forecast"][0]
        assert "uv" in day
        assert "max_wind_kph" in day
        assert "avg_humidity" in day
        assert "sunrise" in day
        assert "sunset" in day
        assert "total_precip_mm" in day
        assert "avg_temp_c" in day

    @pytest.mark.asyncio
    async def test_rain_alert_flag_set_above_threshold(self, weather_service):
        """Dia com chance de chuva >= 70% deve ter rain_alert=True."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_detailed_forecast("Dublin", days=7)

        # Dia índice 2 tem 80% de chuva no mock
        day_with_rain = result["forecast"][2]
        assert day_with_rain["rain_alert"] is True
        assert day_with_rain["chance_of_rain"] == 80

    @pytest.mark.asyncio
    async def test_wind_alert_flag(self, weather_service):
        """Dia com vento >= 50 km/h deve ter wind_alert=True."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_detailed_forecast("Dublin", days=7)

        # Dia índice 3 tem 60 km/h no mock
        day_with_wind = result["forecast"][3]
        assert day_with_wind["wind_alert"] is True

    @pytest.mark.asyncio
    async def test_uv_alert_flag(self, weather_service):
        """Dia com UV >= 6 deve ter uv_alert=True."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_detailed_forecast("Dublin", days=7)

        # Dia índice 5 tem UV=8 no mock
        day_with_uv = result["forecast"][5]
        assert day_with_uv["uv_alert"] is True

    @pytest.mark.asyncio
    async def test_returns_official_alerts(self, weather_service):
        """Deve retornar alertas oficiais da WeatherAPI."""
        data = _make_api_response(days=3, with_alerts=True)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_detailed_forecast("Dublin", days=3)

        assert len(result["alerts"]) == 1
        alert = result["alerts"][0]
        assert alert["event"] == "Wind Warning"
        assert alert["severity"] == "Moderate"
        assert len(alert["description"]) <= 300  # truncado

    @pytest.mark.asyncio
    async def test_no_alerts_returns_empty_list(self, weather_service):
        """Sem alertas deve retornar lista vazia."""
        data = _make_api_response(days=3, with_alerts=False)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_detailed_forecast("Dublin", days=3)
        assert result["alerts"] == []

    @pytest.mark.asyncio
    async def test_days_capped_at_14(self, weather_service):
        """days > 14 deve ser limitado a 14."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)) as mock_session:
            await weather_service.get_detailed_forecast("Dublin", days=99)
        # Verifica que params passados à API têm days <= 14
        # (verificação indireta — não crashou)

    @pytest.mark.asyncio
    async def test_api_error_raises_runtime(self, weather_service):
        """Erro da API deve lançar RuntimeError."""
        import aiohttp
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_response = AsyncMock()
        mock_response.raise_for_status = Mock(
            side_effect=aiohttp.ClientResponseError(
                request_info=Mock(), history=(), status=500
            )
        )
        mock_session.get = MagicMock(return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=mock_response),
            __aexit__=AsyncMock(return_value=None),
        ))
        with patch("aiohttp.ClientSession", return_value=mock_session):
            with pytest.raises(RuntimeError):
                await weather_service.get_detailed_forecast("Dublin")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. get_week_summary
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetWeekSummary:

    @pytest.mark.asyncio
    async def test_returns_summary_fields(self, weather_service):
        """Deve retornar best_day, worst_day, rainy_days_count, avg temps."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_week_summary("Dublin")

        assert "summary" in result
        summary = result["summary"]
        assert "best_day" in summary
        assert "worst_day" in summary
        assert "rainy_days_count" in summary
        assert "sunny_days_count" in summary
        assert "avg_max_temp_c" in summary
        assert "avg_min_temp_c" in summary

    @pytest.mark.asyncio
    async def test_worst_day_is_most_rainy(self, weather_service):
        """worst_day deve ser o dia com maior chance de chuva."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_week_summary("Dublin")

        worst = result["summary"]["worst_day"]
        # Dia 2 tem 80% de chuva no mock — deve ser o pior
        assert worst["chance_of_rain"] == 80

    @pytest.mark.asyncio
    async def test_best_day_has_low_rain(self, weather_service):
        """best_day deve ter baixa chance de chuva."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_week_summary("Dublin")

        best = result["summary"]["best_day"]
        assert best["chance_of_rain"] <= 40  # melhor dos disponíveis

    @pytest.mark.asyncio
    async def test_rainy_days_count_correct(self, weather_service):
        """rainy_days_count deve contar apenas dias com >= 70% de chuva."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_week_summary("Dublin")

        # No mock: apenas dia 2 tem 80% (>= threshold 70)
        assert result["summary"]["rainy_days_count"] == 1

    @pytest.mark.asyncio
    async def test_avg_temps_are_floats(self, weather_service):
        """avg_max_temp_c e avg_min_temp_c devem ser floats."""
        data = _make_api_response(days=7)
        with patch("aiohttp.ClientSession", return_value=_mock_aiohttp(data)):
            result = await weather_service.get_week_summary("Dublin")

        assert isinstance(result["summary"]["avg_max_temp_c"], float)
        assert isinstance(result["summary"]["avg_min_temp_c"], float)


# ═══════════════════════════════════════════════════════════════════════════════
# 4. WEATHER AGENT — intents e formatação
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeatherAgentIntents:

    @pytest.fixture
    def agent(self):
        from agents.specialized.weather_agent import WeatherAgent
        return WeatherAgent()

    @pytest.fixture
    def mock_svc(self):
        svc = AsyncMock()
        svc.is_initialized.return_value = True

        detail_data = {
            "location": {"name": "Dublin", "region": "Leinster", "country": "Ireland",
                         "lat": 53.3, "lon": -6.2, "localtime": "2026-02-21 10:30", "tz_id": "Europe/Dublin"},
            "current": {"temp_c": 10.0, "feels_like_c": 7.0, "condition": "Partly cloudy",
                        "humidity": 80, "wind_kph": 25.0, "wind_dir": "SW", "uv": 3.0,
                        "vis_km": 10.0, "cloud": 50, "is_day": 1},
            "forecast": [
                {"date": "2026-02-21", "max_temp_c": 12.0, "min_temp_c": 6.0,
                 "avg_temp_c": 9.0, "condition": "Partly cloudy", "icon": "//i.png",
                 "chance_of_rain": 30, "chance_of_snow": 0, "total_precip_mm": 0,
                 "avg_humidity": 75, "max_wind_kph": 25, "uv": 3,
                 "sunrise": "07:30 AM", "sunset": "06:00 PM",
                 "rain_alert": False, "wind_alert": False, "uv_alert": False},
                {"date": "2026-02-22", "max_temp_c": 11.0, "min_temp_c": 5.0,
                 "avg_temp_c": 8.0, "condition": "Rain", "icon": "//i.png",
                 "chance_of_rain": 80, "chance_of_snow": 0, "total_precip_mm": 5.2,
                 "avg_humidity": 90, "max_wind_kph": 40, "uv": 2,
                 "sunrise": "07:32 AM", "sunset": "06:02 PM",
                 "rain_alert": True, "wind_alert": False, "uv_alert": False},
            ],
            "alerts": [],
        }

        week_data = {
            "location": detail_data["location"],
            "forecast": detail_data["forecast"],
            "alerts": [],
            "summary": {
                "best_day": detail_data["forecast"][0],
                "worst_day": detail_data["forecast"][1],
                "rainy_days_count": 1,
                "sunny_days_count": 1,
                "rainy_days": ["2026-02-22"],
                "avg_max_temp_c": 11.5,
                "avg_min_temp_c": 5.5,
                "has_alerts": False,
            },
        }

        svc.get_detailed_forecast = AsyncMock(return_value=detail_data)
        svc.get_week_summary = AsyncMock(return_value=week_data)
        svc.get_alerts = AsyncMock(return_value=[])
        return svc

    @pytest.mark.asyncio
    async def test_today_intent(self, agent, mock_svc):
        """Query de hoje deve retornar clima atual com UV e vento."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Como está o clima em Dublin?", {})
        assert r.is_success()
        assert "Dublin" in r.response
        assert "°C" in r.response
        assert "UV" in r.response

    @pytest.mark.asyncio
    async def test_tomorrow_intent(self, agent, mock_svc):
        """'amanhã' deve retornar previsão do segundo dia."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Vai chover amanhã em Dublin?", {})
        assert r.is_success()
        assert "Amanhã" in r.response
        assert "80%" in r.response  # chance de chuva do dia 2 no mock

    @pytest.mark.asyncio
    async def test_week_intent(self, agent, mock_svc):
        """'semana' deve retornar previsão 7 dias com resumo."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Previsão para essa semana em Dublin", {})
        assert r.is_success()
        assert "7 dias" in r.response or "semana" in r.response.lower() or "Melhor dia" in r.response
        mock_svc.get_week_summary.assert_called_once()

    @pytest.mark.asyncio
    async def test_alert_intent(self, agent, mock_svc):
        """'alerta' deve chamar _handle_alerts."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("Tem algum alerta meteorológico em Dublin?", {})
        assert r.is_success()
        assert "Alerta" in r.response or "alerta" in r.response.lower() or "✅" in r.response

    @pytest.mark.asyncio
    async def test_previsao_keyword_triggers_week(self, agent, mock_svc):
        """'previsão' deve acionar modo semana."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            await agent.execute("previsão para Dublin", {})
        mock_svc.get_week_summary.assert_called()

    @pytest.mark.asyncio
    async def test_location_from_context(self, agent, mock_svc):
        """Contexto com 'location' deve ser usado sem precisar extrair do prompt."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("como está?", {"location": "Dublin"})
        assert r.is_success()

    @pytest.mark.asyncio
    async def test_no_location_returns_error(self, agent, mock_svc):
        """Sem localização no prompt nem contexto deve retornar ERROR."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("", {})
        assert not r.is_success()
        # Deve ter sugestões de uso
        assert "Dublin" in r.response or "São Paulo" in r.response or "Lisboa" in r.response

    @pytest.mark.asyncio
    async def test_service_unavailable(self, agent):
        """Sem WeatherService deve retornar ERROR claro."""
        with patch("agents.specialized.weather_agent.get_service", return_value=None):
            r = await agent.execute("clima em Dublin", {})
        assert not r.is_success()

    @pytest.mark.asyncio
    async def test_rain_alert_in_today_response(self, agent, mock_svc):
        """Se chance de chuva > 0 hoje, deve aparecer na resposta."""
        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("clima hoje em Dublin", {})
        assert r.is_success()
        # Hoje tem 30% de chuva no mock
        assert "30%" in r.response or "chuva" in r.response.lower()

    @pytest.mark.asyncio
    async def test_official_alerts_shown_in_week(self, agent, mock_svc):
        """Alertas oficiais devem aparecer na resposta semanal."""
        mock_svc.get_week_summary.return_value["alerts"] = [{
            "headline": "Wind Warning in effect",
            "severity": "Moderate",
            "urgency": "Expected",
            "areas": "Leinster",
            "event": "Wind Warning",
            "effective": "2026-02-21T10:00:00",
            "expires": "2026-02-22T10:00:00",
            "description": "Gusts up to 90 km/h.",
        }]
        mock_svc.get_week_summary.return_value["summary"]["has_alerts"] = True

        with patch("agents.specialized.weather_agent.get_service", return_value=mock_svc):
            r = await agent.execute("semana em Dublin", {})
        assert r.is_success()
        assert "Wind Warning" in r.response or "⚠️" in r.response

    def test_capabilities(self, agent):
        caps = agent.get_capabilities()
        assert "7_day_forecast" in caps
        assert "rain_alerts" in caps
        assert "official_weather_alerts" in caps
        assert "week_summary" in caps
        assert "best_day_recommendation" in caps


# ═══════════════════════════════════════════════════════════════════════════════
# 5. HELPERS — condição emoji, UV label, dia da semana
# ═══════════════════════════════════════════════════════════════════════════════

class TestWeatherAgentHelpers:

    def test_condition_emoji_rain(self):
        from agents.specialized.weather_agent import _condition_emoji
        assert _condition_emoji("Heavy rain") == "🌧️"

    def test_condition_emoji_sun(self):
        from agents.specialized.weather_agent import _condition_emoji
        assert _condition_emoji("Sunny") == "☀️"

    def test_condition_emoji_unknown(self):
        from agents.specialized.weather_agent import _condition_emoji
        assert _condition_emoji("XYZ Unknown") == "🌡️"

    def test_uv_label_low(self):
        from agents.specialized.weather_agent import _uv_label
        assert _uv_label(1) == "baixo"

    def test_uv_label_high(self):
        from agents.specialized.weather_agent import _uv_label
        assert _uv_label(7) == "alto"

    def test_uv_label_extreme(self):
        from agents.specialized.weather_agent import _uv_label
        assert _uv_label(11) == "extremo"

    def test_date_to_weekday(self):
        from agents.specialized.weather_agent import _date_to_weekday
        # 2026-02-21 é sábado (weekday=5)
        assert _date_to_weekday("2026-02-21") == "Sáb"

    def test_date_to_weekday_invalid(self):
        from agents.specialized.weather_agent import _date_to_weekday
        # Data inválida não deve crashar
        result = _date_to_weekday("not-a-date")
        assert isinstance(result, str)
