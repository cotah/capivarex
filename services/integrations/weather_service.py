"""
Weather Service - Refactored
Serviço para integração com WeatherAPI.com
"""
import os
import time
from typing import Dict, Any
import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, register_service, retry_on_failure

load_dotenv()


@register_service("weather")
class WeatherService(BaseService):
    """Serviço para buscar informações de clima via WeatherAPI.com"""

    def __init__(self, name: str = "weather", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.api_key = None
        self.base_url = "http://api.weatherapi.com/v1"

    async def _initialize(self):
        """Initialize weather service."""
        self.api_key = os.getenv("WEATHER_API_KEY")
        if not self.api_key:
            raise ValueError("WEATHER_API_KEY not found in environment variables")
        self.logger.info("Weather service initialized successfully")

    async def _health_check(self) -> bool:
        """Check if weather service is healthy."""
        return self.api_key is not None

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_current_weather(self, location: str) -> Dict[str, Any]:
        """
        Busca o clima atual para uma localização.

        Args:
            location: Cidade, CEP, IP, ou coordenadas (lat,lon)

        Returns:
            Dicionário com informações do clima atual

        Raises:
            RuntimeError: Se a requisição falhar
        """
        if not self.api_key:
            await self.initialize()

        start_time = time.time()

        try:
            url = f"{self.base_url}/current.json"
            params = {
                "key": self.api_key,
                "q": location,
                "aqi": "no"  # Air Quality Index (opcional)
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    data = await response.json()

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            # Formatar resposta
            result = {
                "location": {
                    "name": data["location"]["name"],
                    "region": data["location"]["region"],
                    "country": data["location"]["country"],
                    "lat": data["location"]["lat"],
                    "lon": data["location"]["lon"],
                    "localtime": data["location"]["localtime"]
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
                    "feels_like_f": data["current"]["feelslike_f"]
                }
            }

            self.logger.info(f"Current weather fetched for {location}")
            return result

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching current weather: {e}", exc_info=True)
            raise RuntimeError(f"Erro ao buscar clima: {str(e)}")

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def get_forecast(self, location: str, days: int = 3) -> Dict[str, Any]:
        """
        Busca a previsão do tempo para os próximos dias.

        Args:
            location: Cidade, CEP, IP, ou coordenadas (lat,lon)
            days: Número de dias de previsão (1-14, padrão: 3)

        Returns:
            Dicionário com previsão do tempo

        Raises:
            RuntimeError: Se a requisição falhar
        """
        if not self.api_key:
            await self.initialize()

        start_time = time.time()

        try:
            url = f"{self.base_url}/forecast.json"
            params = {
                "key": self.api_key,
                "q": location,
                "days": min(days, 14),  # Máximo 14 dias no plano gratuito
                "aqi": "no"
            }

            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    response.raise_for_status()
                    data = await response.json()

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            # Formatar resposta
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
                    "chance_of_rain": day["day"]["daily_chance_of_rain"]
                })

            result = {
                "location": {
                    "name": data["location"]["name"],
                    "region": data["location"]["region"],
                    "country": data["location"]["country"]
                },
                "forecast": forecast_days
            }

            self.logger.info(f"Forecast fetched for {location} ({days} days)")
            return result

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching forecast: {e}", exc_info=True)
            raise RuntimeError(f"Erro ao buscar previsão: {str(e)}")

    # Alias for backward compatibility
    async def get_weather(self, location: str) -> Dict[str, Any]:
        """Alias for get_current_weather (backward compatibility)."""
        return await self.get_current_weather(location)


# Backward compatibility - global instance
weather_service = None

def get_weather_service() -> WeatherService:
    """Get global weather service instance."""
    global weather_service
    if weather_service is None:
        from services.core import get_service
        weather_service = get_service("weather")
    return weather_service
