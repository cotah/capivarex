"""
Weather Agent - Provides weather forecasts.

Refactored to use new BaseAgent architecture.
"""

import logging
import re
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)

# Regex to extract location from prompt
LOCATION_PATTERN = re.compile(r"(?:em|in)\s+([a-zA-Z0-9 ,.-]{2,})", re.IGNORECASE)


@register_agent("weather")
class WeatherAgent(BaseAgent):
    """
    Weather agent for weather forecasts and conditions.

    Handles:
    - Current weather
    - Weather forecasts
    - Temperature queries
    - Precipitation probability
    """

    def __init__(self):
        super().__init__(
            name="weather",
            description="Provides weather forecasts and current conditions"
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Get weather forecast for location.

        Args:
            prompt: User's weather query
            context: Context with optional location

        Returns:
            AgentResponse with weather data
        """
        # Extract location
        location = self._extract_location(prompt, context)

        if not location:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao foi possivel identificar a localizacao para previsao do tempo.",
                error="No location provided"
            )

        try:
            # Get weather service from registry
            weather_svc = get_service("weather")
            if not weather_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Servico de clima nao disponivel.",
                    error="Weather service not available"
                )

            await weather_svc.initialize()

            # Get forecast (async call via refactored service)
            weather = await weather_svc.get_forecast(location)

            location_data = weather.get("location", {})
            forecast_days = weather.get("forecast", [])

            if not forecast_days:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=f"Nao foi possivel obter previsao detalhada para {location}.",
                    error="No forecast data available"
                )

            # Format response
            today = forecast_days[0]
            location_name = location_data.get('name', location)
            location_region = location_data.get('region', '')

            response_text = (
                f"Previsao para {location_name}, {location_region}: "
                f"{today.get('condition', 'N/A')}. "
                f"Max {today.get('max_temp_c', 'N/A')}C, "
                f"Min {today.get('min_temp_c', 'N/A')}C, "
                f"Chance de chuva {today.get('chance_of_rain', 'N/A')}%."
            )

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=response_text,
                data={
                    "location": location_data,
                    "forecast": forecast_days,
                    "today": today
                }
            )

        except Exception as e:
            self.logger.error(
                f"Weather query failed for location '{location}': {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Nao foi possivel consultar o clima para {location}.",
                error=str(e),
                metadata={"location": location}
            )

    def _extract_location(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> str:
        """
        Extract location from prompt or context.

        Args:
            prompt: User's prompt
            context: Execution context

        Returns:
            Location string
        """
        # Check context first
        if "location" in context and context["location"]:
            return str(context["location"]).strip()

        # Try to extract from prompt
        match = LOCATION_PATTERN.search(prompt or "")
        if match:
            return match.group(1).strip(" .,!?:;")

        # Fallback to entire prompt as location
        return prompt.strip()

    def get_capabilities(self) -> List[str]:
        """Get weather agent capabilities."""
        return [
            "current_weather",
            "weather_forecast",
            "temperature",
            "precipitation",
            "conditions"
        ]
