# -*- coding: utf-8 -*-
"""
services/integrations/weather_service.py  (versão melhorada)
=============================================================
PATCH cirúrgico — adiciona novos métodos sem alterar os existentes.

Novos métodos:
  - get_detailed_forecast(location, days)  → previsão enriquecida (UV, vento, humidade)
  - get_alerts(location)                   → alertas meteorológicos ativos
  - get_week_summary(location)             → resumo da semana (melhor/pior dia, tendência)

Métodos existentes (inalterados):
  - get_current_weather(location)
  - get_forecast(location, days=3)
  - get_weather(location)                  ← alias backward compat

WeatherAPI.com docs:
  https://www.weatherapi.com/docs/
"""

import os
import time
from typing import Any, Dict, List

import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, register_service, retry_on_failure

load_dotenv()

# Limiar de chuva para considerar "dia chuvoso" (%)
RAIN_ALERT_THRESHOLD = 70
# Limiar UV para considerar "alto"
UV_HIGH_THRESHOLD = 6
# Limiar de vento forte (km/h)
WIND_STRONG_THRESHOLD = 50


@register_service("weather")
class WeatherService(BaseService):
    """Serviço para buscar informações de clima via WeatherAPI.com"""

    def __init__(self, name: str = "weather", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.api_key = None
        self.base_url = "http://api.weatherapi.com/v1"

    async def _initialize(self):
        self.api_key = os.getenv("WEATHER_API_KEY")
        if not self.api_key:
            raise ValueError("WEATHER_API_KEY not found in environment variables")
        self.logger.info("Weather service initialized successfully")

    async def _health_check(self) -> bool:
        return self.api_key is not None

    # ──────────────────────────────────────────────────────────────────────────
    # MÉTODOS EXISTENTES (inalterados — backward compat garantida)
    # ──────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_current_weather(self, location: str) -> Dict[str, Any]:
        """Busca o clima atual para uma localização."""
        if not self.api_key:
            await self.initialize()

        start_time = time.time()
        try:
            url = f"{self.base_url}/current.json"
            params = {"key": self.api_key, "q": location, "aqi": "no"}

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "location": {
                    "name": data["location"]["name"],
                    "region": data["location"]["region"],
                    "country": data["location"]["country"],
                    "lat": data["location"]["lat"],
                    "lon": data["location"]["lon"],
                    "localtime": data["location"]["localtime"],
                },
                "current": {
                    "temp_c": data["current"]["temp_c"],
                    "temp_f": data["current"]["temp_f"],
                    "condition": data["current"]["condition"]["text"],
                    "icon": data["current"]["condition"]["icon"],
                    "humidity": data["current"]["humidity"],
                    "wind_kph": data["current"]["wind_kph"],
                    "wind_mph": data["current"]["wind_mph"],
                    "feels_like_c": data["current"]["feelslike_c"],
                    "feels_like_f": data["current"]["feelslike_f"],
                },
            }
        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching current weather: {e}", exc_info=True)
            raise RuntimeError(f"Erro ao buscar clima: {str(e)}")

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_forecast(self, location: str, days: int = 3) -> Dict[str, Any]:
        """Busca a previsão do tempo para os próximos dias (formato original)."""
        if not self.api_key:
            await self.initialize()

        start_time = time.time()
        try:
            url = f"{self.base_url}/forecast.json"
            params = {
                "key": self.api_key,
                "q": location,
                "days": min(days, 14),
                "aqi": "no",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            forecast_days = []
            for day in data["forecast"]["forecastday"]:
                forecast_days.append({
                    "date": day["date"],
                    "max_temp_c": day["day"]["maxtemp_c"],
                    "min_temp_c": day["day"]["mintemp_c"],
                    "max_temp_f": day["day"]["maxtemp_f"],
                    "min_temp_f": day["day"]["mintemp_f"],
                    "condition": day["day"]["condition"]["text"],
                    "icon": day["day"]["condition"]["icon"],
                    "chance_of_rain": day["day"]["daily_chance_of_rain"],
                })

            return {
                "location": {
                    "name": data["location"]["name"],
                    "region": data["location"]["region"],
                    "country": data["location"]["country"],
                },
                "forecast": forecast_days,
            }
        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching forecast: {e}", exc_info=True)
            raise RuntimeError(f"Erro ao buscar previsão: {str(e)}")

    async def get_weather(self, location: str) -> Dict[str, Any]:
        """Alias for get_current_weather (backward compatibility)."""
        return await self.get_current_weather(location)

    # ──────────────────────────────────────────────────────────────────────────
    # NOVOS MÉTODOS
    # ──────────────────────────────────────────────────────────────────────────

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_detailed_forecast(
        self, location: str, days: int = 7
    ) -> Dict[str, Any]:
        """
        Previsão enriquecida com UV, vento, humidade, sensação térmica e alertas.

        Args:
            location: Cidade, coordenadas ou CEP
            days: 1–14 dias (padrão: 7)

        Returns:
            Dict com location, current, forecast (lista enriquecida), alerts
        """
        if not self.api_key:
            await self.initialize()

        days = min(max(days, 1), 14)
        start_time = time.time()

        try:
            url = f"{self.base_url}/forecast.json"
            params = {
                "key": self.api_key,
                "q": location,
                "days": days,
                "aqi": "no",
                "alerts": "yes",
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params, timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    response.raise_for_status()
                    data = await response.json()

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            # ── Localização ───────────────────────────────────────────────────
            loc = data["location"]
            location_data = {
                "name": loc["name"],
                "region": loc.get("region", ""),
                "country": loc["country"],
                "lat": loc["lat"],
                "lon": loc["lon"],
                "localtime": loc["localtime"],
                "tz_id": loc.get("tz_id", ""),
            }

            # ── Clima atual (enriquecido) ─────────────────────────────────────
            cur = data["current"]
            current_data = {
                "temp_c": cur["temp_c"],
                "feels_like_c": cur["feelslike_c"],
                "condition": cur["condition"]["text"],
                "humidity": cur["humidity"],
                "wind_kph": cur["wind_kph"],
                "wind_dir": cur.get("wind_dir", ""),
                "uv": cur.get("uv", 0),
                "vis_km": cur.get("vis_km", 0),
                "cloud": cur.get("cloud", 0),
                "is_day": cur.get("is_day", 1),
            }

            # ── Previsão por dia (enriquecida) ────────────────────────────────
            forecast_days = []
            for day_data in data["forecast"]["forecastday"]:
                d = day_data["day"]
                forecast_days.append({
                    "date": day_data["date"],
                    "max_temp_c": d["maxtemp_c"],
                    "min_temp_c": d["mintemp_c"],
                    "avg_temp_c": d["avgtemp_c"],
                    "condition": d["condition"]["text"],
                    "icon": d["condition"]["icon"],
                    "chance_of_rain": d["daily_chance_of_rain"],
                    "chance_of_snow": d.get("daily_chance_of_snow", 0),
                    "total_precip_mm": d.get("totalprecip_mm", 0),
                    "avg_humidity": d.get("avghumidity", 0),
                    "max_wind_kph": d.get("maxwind_kph", 0),
                    "uv": d.get("uv", 0),
                    "sunrise": day_data.get("astro", {}).get("sunrise", ""),
                    "sunset": day_data.get("astro", {}).get("sunset", ""),
                    # Flags de alerta
                    "rain_alert": d["daily_chance_of_rain"] >= RAIN_ALERT_THRESHOLD,
                    "wind_alert": d.get("maxwind_kph", 0) >= WIND_STRONG_THRESHOLD,
                    "uv_alert": d.get("uv", 0) >= UV_HIGH_THRESHOLD,
                })

            # ── Alertas meteorológicos oficiais ───────────────────────────────
            raw_alerts = data.get("alerts", {}).get("alert", [])
            alerts = [
                {
                    "headline": a.get("headline", ""),
                    "severity": a.get("severity", ""),
                    "urgency": a.get("urgency", ""),
                    "areas": a.get("areas", ""),
                    "event": a.get("event", ""),
                    "effective": a.get("effective", ""),
                    "expires": a.get("expires", ""),
                    "description": a.get("desc", "")[:300] if a.get("desc") else "",
                }
                for a in raw_alerts
            ]

            self.logger.info(
                f"Detailed forecast fetched for {location} ({days} days, "
                f"{len(alerts)} alerts)"
            )

            return {
                "location": location_data,
                "current": current_data,
                "forecast": forecast_days,
                "alerts": alerts,
            }

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching detailed forecast: {e}", exc_info=True)
            raise RuntimeError(f"Erro ao buscar previsão detalhada: {str(e)}")

    async def get_alerts(self, location: str) -> List[Dict[str, Any]]:
        """
        Retorna apenas os alertas meteorológicos ativos para uma localização.

        Args:
            location: Cidade, coordenadas ou CEP

        Returns:
            Lista de alertas (vazia se não houver)
        """
        data = await self.get_detailed_forecast(location, days=1)
        return data.get("alerts", [])

    async def get_week_summary(self, location: str) -> Dict[str, Any]:
        """
        Resumo da semana: melhor dia, pior dia, tendência de chuva.

        Returns:
            Dict com: best_day, worst_day, rainy_days, sunny_days,
                      avg_max_temp, avg_min_temp, rain_days_list, forecast
        """
        data = await self.get_detailed_forecast(location, days=7)
        forecast = data["forecast"]

        if not forecast:
            return {"error": "Sem dados de previsão disponíveis"}

        # Melhor dia: menor chance de chuva + maior temperatura máxima
        best_day = min(
            forecast,
            key=lambda d: (d["chance_of_rain"], -d["max_temp_c"])
        )
        # Pior dia: maior chance de chuva
        worst_day = max(forecast, key=lambda d: d["chance_of_rain"])

        rainy_days = [d for d in forecast if d["chance_of_rain"] >= RAIN_ALERT_THRESHOLD]
        sunny_days = [d for d in forecast if d["chance_of_rain"] < 30]

        avg_max = round(
            sum(d["max_temp_c"] for d in forecast) / len(forecast), 1
        )
        avg_min = round(
            sum(d["min_temp_c"] for d in forecast) / len(forecast), 1
        )

        return {
            "location": data["location"],
            "forecast": forecast,
            "alerts": data.get("alerts", []),
            "summary": {
                "best_day": best_day,
                "worst_day": worst_day,
                "rainy_days_count": len(rainy_days),
                "sunny_days_count": len(sunny_days),
                "rainy_days": [d["date"] for d in rainy_days],
                "avg_max_temp_c": avg_max,
                "avg_min_temp_c": avg_min,
                "has_alerts": len(data.get("alerts", [])) > 0,
            },
        }


# Backward compatibility
weather_service = None


def get_weather_service() -> WeatherService:
    """Get global weather service instance."""
    global weather_service
    if weather_service is None:
        from services.core import get_service
        weather_service = get_service("weather")
    return weather_service
