"""
Traffic Agent - Provides traffic and navigation information.

Refactored to use new BaseAgent architecture.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)


@register_agent("traffic")
class TrafficAgent(BaseAgent):
    """
    Traffic agent for traffic and navigation queries.

    Handles:
    - Route traffic conditions
    - Travel time estimation
    - Traffic summaries
    - Event-based traffic checks
    """

    def __init__(self):
        super().__init__(
            name="traffic",
            description="Provides traffic and navigation information"
        )

    async def _get_traffic_service(self) -> Optional[Any]:
        """
        Get the traffic service, initializing if needed.

        Returns:
            Traffic service instance or None
        """
        try:
            traffic_svc = get_service("traffic")
            if traffic_svc:
                await traffic_svc.initialize()
                return traffic_svc
            return None
        except Exception as e:
            self.logger.warning(f"Could not get traffic service: {e}")
            return None

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Process traffic and navigation queries.

        Args:
            prompt: User's traffic query
            context: Execution context with optional origin/destination

        Returns:
            AgentResponse with traffic information
        """
        try:
            # Extract origin and destination from prompt first, then context
            origin, destination = self._extract_locations(prompt)
            origin = origin or context.get("origin")
            destination = destination or context.get("destination")

            # If still missing, request more info
            if not origin or not destination:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Por favor, informe a origem e o destino da sua rota.\n\n"
                        "Exemplo: 'Como esta o trafego de Dublin para Cork?'"
                    ),
                    error="Missing origin or destination",
                    data={"needs_location": True}
                )

            # Get traffic service
            traffic_service = await self._get_traffic_service()
            if not traffic_service:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Servico de trafego nao disponivel.",
                    error="Traffic service not available"
                )

            # Fetch traffic information
            self.logger.info(f"Fetching traffic from {origin} to {destination}")

            result = await traffic_service.get_route_with_traffic(origin, destination)

            if not result.get("success"):
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Nao foi possivel obter informacoes de trafego no momento.",
                    error=result.get("error", "Traffic query failed")
                )

            # Generate formatted response
            summary = await traffic_service.get_traffic_summary(origin, destination)

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=summary,
                data={
                    "route_data": result.get("route"),
                    "traffic_data": result.get("traffic"),
                    "origin": origin,
                    "destination": destination
                }
            )

        except Exception as e:
            self.logger.error(
                f"TrafficAgent failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao buscar informacoes de trafego: {str(e)}",
                error=str(e)
            )

    async def check_traffic_for_event(
        self,
        event_location: str,
        user_location: str,
        event_time: datetime,
        preparation_minutes: int = 15
    ) -> AgentResponse:
        """
        Check traffic conditions before a calendar event.

        Args:
            event_location: Event location address
            user_location: User's current location
            event_time: Event start time
            preparation_minutes: Minutes for preparation before departure

        Returns:
            AgentResponse with traffic recommendations
        """
        try:
            self.logger.info(
                f"Checking traffic for event: {user_location} -> {event_location}"
            )

            traffic_service = await self._get_traffic_service()
            if not traffic_service:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Servico de trafego nao disponivel.",
                    error="Traffic service not available"
                )

            result = await traffic_service.check_traffic_before_event(
                event_location=event_location,
                user_location=user_location,
                event_time=event_time,
                preparation_minutes=preparation_minutes
            )

            if not result.get("success"):
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Nao foi possivel verificar o trafego para este evento.",
                    error=result.get("error", "Traffic check failed")
                )

            # Format response
            response = f"{result.get('message', '')}\n\n"
            response += f"Destino: {event_location}\n"
            response += f"Tempo de viagem: {result.get('travel_time_minutes', 0)} minutos\n"
            response += f"Distancia: {result.get('distance_km', 0)} km\n"

            if result.get('suggested_departure'):
                try:
                    departure_time = datetime.fromisoformat(
                        result['suggested_departure']
                    )
                    response += f"Horario sugerido de saida: {departure_time.strftime('%H:%M')}\n"
                except (ValueError, TypeError):
                    pass

            if result.get('event_time'):
                try:
                    evt_time = datetime.fromisoformat(result['event_time'])
                    response += f"Horario do evento: {evt_time.strftime('%H:%M')}"
                except (ValueError, TypeError):
                    pass

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=response.strip(),
                data={
                    "urgency": result.get("urgency"),
                    "travel_time_minutes": result.get("travel_time_minutes"),
                    "distance_km": result.get("distance_km"),
                    "suggested_departure": result.get("suggested_departure"),
                    "message": result.get("message")
                }
            )

        except Exception as e:
            self.logger.error(
                f"Traffic check for event failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao verificar trafego: {str(e)}",
                error=str(e)
            )

    def get_capabilities(self) -> List[str]:
        """Get traffic agent capabilities."""
        return [
            "traffic_info",
            "navigation",
            "routes",
            "travel_time",
            "event_traffic_check"
        ]

    def _extract_locations(self, prompt: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Extract origin and destination from the user's prompt.

        Supports Portuguese ('de X para Y') and English ('from X to Y') patterns.

        Args:
            prompt: User's traffic query

        Returns:
            Tuple of (origin, destination), either may be None
        """
        if not prompt:
            return None, None

        # Portuguese: "de X para Y"
        match = re.search(
            r'de\s+(.+?)\s+para\s+(.+?)\s*[\?\.!]*\s*$',
            prompt,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

        # English: "from X to Y"
        match = re.search(
            r'from\s+(.+?)\s+to\s+(.+?)\s*[\?\.!]*\s*$',
            prompt,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).strip(), match.group(2).strip()

        return None, None
