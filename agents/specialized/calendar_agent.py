"""
Calendar Agent - Manages calendar and schedule.

Refactored to use new BaseAgent architecture.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)


@register_agent("calendar")
class CalendarAgent(BaseAgent):
    """
    Calendar agent for managing calendar, meetings, and schedule.

    Handles:
    - Next meeting queries
    - Today's events
    - Weekly schedule
    - Calendar briefings
    - Event creation
    - Traffic alerts for events
    """

    def __init__(self):
        super().__init__(
            name="calendar",
            description="Manages calendar, meetings, and schedule"
        )
        self._calendar_service: Optional[Any] = None

    async def _get_calendar_service(self) -> Optional[Any]:
        """
        Get the Google Calendar service, initializing if needed.

        Returns:
            Calendar service instance or None
        """
        if self._calendar_service:
            return self._calendar_service

        try:
            cal_svc = get_service("calendar")
            if cal_svc:
                if not cal_svc.is_initialized():
                    await cal_svc.initialize()
                self._calendar_service = cal_svc
                return self._calendar_service
        except Exception as e:
            self.logger.warning(f"Calendar service not available: {e}")

        return None

    async def _load_stored_credentials(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Load Google Calendar credentials from DB for a user."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.get_calendar_credentials(user_id)
        except Exception as e:
            self.logger.warning(f"Could not load calendar credentials: {e}")
        return None

    async def _save_credentials(self, user_id: str, credentials: Dict[str, Any]) -> bool:
        """Persist Google Calendar credentials to DB."""
        try:
            db = get_service("database")
            if db:
                if not db.is_initialized():
                    await db.initialize()
                return await db.save_calendar_credentials(user_id, credentials)
        except Exception as e:
            self.logger.warning(f"Could not save calendar credentials: {e}")
        return False

    # Intent keywords mapped to handler method names
    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        "next_meeting": ["next meeting", "proxima reuniao", "next event"],
        "today": ["today", "hoje", "today's", "de hoje"],
        "week": ["this week", "esta semana", "week", "semana"],
        "briefing": ["briefing", "resumo", "summary"],
        "traffic": [
            "trafego", "traffic", "sair", "leave",
            "quando sair", "when to leave",
        ],
    }

    def _detect_intent(self, query_lower: str) -> str:
        """Detect calendar query intent from keywords.

        Args:
            query_lower: Lowercased user query.

        Returns:
            Intent key (e.g. 'today', 'traffic') or 'upcoming' as default.
        """
        for intent, keywords in self._INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                return intent
        return "upcoming"

    async def _ensure_authenticated(
        self,
    ) -> Optional[AgentResponse]:
        """Ensure the calendar service is available and authenticated.

        Returns:
            An error AgentResponse if unavailable, or None on success.
            When None is returned, ``self._calendar_service`` is ready.
        """
        calendar_service = await self._get_calendar_service()
        if not calendar_service:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Servico de calendario nao disponivel. Verifique a autorizacao.",
                error="Calendar service not available"
            )

        if not calendar_service._service:
            auth_success = calendar_service.authenticate()
            if not auth_success:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Nao consegui conectar ao seu calendario. Verifique a autorizacao.",
                    error="Authentication failed"
                )
        return None

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Process calendar-related queries.

        Args:
            prompt: User's calendar query
            context: Execution context with optional action parameters

        Returns:
            AgentResponse with calendar data
        """
        try:
            auth_error = await self._ensure_authenticated()
            if auth_error:
                return auth_error

            calendar_service = self._calendar_service

            # Priority: explicit create event action from PromptCleaner
            if context.get("action") == "create_event":
                event_params = context.get("event_params", {})
                return await self._create_event(calendar_service, event_params)

            # Dispatch by detected intent
            intent = self._detect_intent(prompt.lower())

            dispatch = {
                "next_meeting": lambda: self._get_next_meeting(calendar_service),
                "today": lambda: self._get_today_events(calendar_service),
                "week": lambda: self._get_week_events(calendar_service),
                "briefing": lambda: self._get_briefing(calendar_service),
                "traffic": lambda: self._check_traffic_for_next_event(
                    calendar_service, context.get("user_location", "Dublin")
                ),
                "upcoming": lambda: self._get_upcoming_events(calendar_service),
            }

            handler = dispatch[intent]
            return await handler()

        except Exception as e:
            self.logger.error(
                f"Calendar query failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao acessar seu calendario: {str(e)}",
                error=str(e)
            )

    async def _get_next_meeting(
        self,
        calendar_service: Any
    ) -> AgentResponse:
        """Get the next upcoming meeting."""
        next_meeting = calendar_service.get_next_meeting()

        if not next_meeting:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem reunioes agendadas.",
                data={"events": []}
            )

        summary = next_meeting.get('summary', 'Sem titulo')
        start = next_meeting.get('start', '')
        location = next_meeting.get('location', '')

        # Format start time
        try:
            if 'T' in start:
                start_dt = datetime.fromisoformat(start.replace('Z', '+00:00'))
                time_str = start_dt.strftime('%d/%m/%Y as %H:%M')
            else:
                time_str = start
        except (ValueError, TypeError):
            time_str = start

        response = f"Sua proxima reuniao e '{summary}' em {time_str}"
        if location:
            response += f" em {location}"
        response += "."

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data={"events": [next_meeting]}
        )

    async def _get_today_events(
        self,
        calendar_service: Any
    ) -> AgentResponse:
        """Get all events for today."""
        events = calendar_service.get_today_events()

        if not events:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem eventos agendados para hoje.",
                data={"events": []}
            )

        response = f"Voce tem {len(events)} evento(s) hoje:\n\n"
        for event in events:
            response += calendar_service.format_event_for_briefing(event) + "\n"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"events": events}
        )

    async def _get_week_events(
        self,
        calendar_service: Any
    ) -> AgentResponse:
        """Get events for the current week."""
        now = datetime.utcnow()
        end_of_week = now + timedelta(days=7)

        events = calendar_service.get_upcoming_events(
            max_results=50,
            time_min=now,
            time_max=end_of_week
        )

        if not events:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem eventos agendados para esta semana.",
                data={"events": []}
            )

        response = f"Voce tem {len(events)} evento(s) esta semana:\n\n"
        for event in events:
            response += calendar_service.format_event_for_briefing(event) + "\n"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"events": events}
        )

    async def _get_upcoming_events(
        self,
        calendar_service: Any
    ) -> AgentResponse:
        """Get upcoming events (next 7 days)."""
        events = calendar_service.get_upcoming_events(max_results=10)

        if not events:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem eventos nos proximos 7 dias.",
                data={"events": []}
            )

        response = f"Voce tem {len(events)} evento(s) proximos:\n\n"
        for event in events:
            response += calendar_service.format_event_for_briefing(event) + "\n"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"events": events}
        )

    async def _get_briefing(
        self,
        calendar_service: Any
    ) -> AgentResponse:
        """Get calendar briefing."""
        briefing_text = calendar_service.generate_calendar_briefing()
        events = calendar_service.get_morning_briefing_events()

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=briefing_text,
            data={"events": events}
        )

    async def _create_event(
        self,
        calendar_service: Any,
        event_params: Dict[str, Any]
    ) -> AgentResponse:
        """
        Create a new calendar event.

        Args:
            calendar_service: Calendar service instance
            event_params: Event parameters (title, start_datetime, etc.)

        Returns:
            AgentResponse with creation result
        """
        # Validate required parameters
        if not event_params.get("title"):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao consegui identificar o titulo do evento. Por favor, especifique o que deseja agendar.",
                error="Missing title"
            )

        if not event_params.get("start_datetime"):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao consegui identificar a data e hora do evento. Por favor, especifique quando deseja agendar.",
                error="Missing start_datetime"
            )

        title = event_params["title"]

        try:
            # Parse start datetime
            start_str = event_params["start_datetime"]
            if isinstance(start_str, str):
                start_dt = datetime.fromisoformat(start_str.replace('Z', '+00:00'))
                start_dt = start_dt.replace(tzinfo=None)
            else:
                start_dt = start_str

            # Parse or calculate end datetime
            if event_params.get("end_datetime"):
                end_str = event_params["end_datetime"]
                if isinstance(end_str, str):
                    end_dt = datetime.fromisoformat(end_str.replace('Z', '+00:00'))
                    end_dt = end_dt.replace(tzinfo=None)
                else:
                    end_dt = end_str
            else:
                # Default: 1 hour after start
                end_dt = start_dt + timedelta(hours=1)

        except (ValueError, TypeError) as e:
            self.logger.error(f"Failed to parse event datetime: {e}")
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar data e hora: {str(e)}. Por favor, use um formato valido.",
                error=str(e)
            )

        # Extract optional parameters
        location = event_params.get("location", "")
        description = event_params.get("description", "")

        # Create event
        created_event = calendar_service.create_event(
            summary=title,
            start_time=start_dt,
            end_time=end_dt,
            location=location,
            description=description
        )

        if not created_event:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao foi possivel criar o evento. Por favor, tente novamente.",
                error="Calendar service returned None"
            )

        self.logger.info(
            f"Event created successfully: {title} at {start_dt.isoformat()}"
        )

        # Format success response
        response = "Evento criado com sucesso!\n\n"
        response += f"{title}\n"
        response += f"Data: {start_dt.strftime('%d/%m/%Y as %H:%M')}"

        if end_dt:
            response += f" - {end_dt.strftime('%H:%M')}"

        if location:
            response += f"\nLocal: {location}"

        if description:
            response += f"\nDescricao: {description}"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"event": created_event}
        )

    @staticmethod
    def _find_next_event_with_location(
        events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Find the first future event that has a physical location.

        Args:
            events: List of calendar event dicts.

        Returns:
            The matching event dict, or None.
        """
        now = datetime.now()
        for event in events:
            location = event.get("location", "").strip()
            if not location:
                continue
            start = event.get("start", "")
            try:
                if "T" in start:
                    event_time = datetime.fromisoformat(
                        start.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    if event_time > now:
                        return event
            except (ValueError, TypeError):
                continue
        return None

    @staticmethod
    def _parse_event_time(event: Dict[str, Any]) -> datetime:
        """Parse a timed event's start into a naive datetime.

        Args:
            event: Calendar event dict.

        Returns:
            Naive datetime of the event start.

        Raises:
            ValueError: If the event is all-day or the time cannot be parsed.
        """
        start = event.get("start", "")
        if "T" not in start:
            summary = event.get("summary", "Evento")
            raise ValueError(
                f"O evento '{summary}' e um evento de dia inteiro, sem horario especifico."
            )
        return datetime.fromisoformat(
            start.replace("Z", "+00:00")
        ).replace(tzinfo=None)

    async def _check_traffic_for_next_event(
        self,
        calendar_service: Any,
        user_location: str
    ) -> AgentResponse:
        """
        Check traffic conditions for the next event with location.

        Args:
            calendar_service: Calendar service instance
            user_location: User's current location

        Returns:
            AgentResponse with traffic alert and recommendations
        """
        try:
            events = calendar_service.get_upcoming_events(max_results=10)
            if not events:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Voce nao tem eventos agendados.",
                    error="No events found"
                )

            target_event = self._find_next_event_with_location(events)
            if not target_event:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Nenhum evento futuro com localizacao encontrado.",
                    error="No future events with location"
                )

            event_summary = target_event.get("summary", "Evento sem titulo")
            event_location = target_event.get("location", "")

            try:
                event_time_naive = self._parse_event_time(target_event)
            except (ValueError, TypeError) as e:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=str(e),
                    error=str(e)
                )

            # Check traffic via traffic agent
            from agents.core import get_agent
            traffic_agent = get_agent("traffic")

            if not traffic_agent:
                return AgentResponse(
                    status=AgentStatus.PARTIAL,
                    response=(
                        f"Proximo evento com local: '{event_summary}' "
                        f"em {event_location} as {event_time_naive.strftime('%H:%M')}. "
                        f"Servico de trafego nao disponivel para verificar condicoes."
                    ),
                    data={"event": target_event}
                )

            traffic_context = {
                "origin": user_location,
                "destination": event_location,
                "event_time": event_time_naive.isoformat(),
            }

            traffic_response = await traffic_agent.execute(
                f"Trafego de {user_location} para {event_location}",
                traffic_context
            )

            response = "Alerta de Trafego para Evento\n\n"
            response += f"Evento: {event_summary}\n"
            response += f"Horario: {event_time_naive.strftime('%H:%M')}\n"
            response += f"Local: {event_location}\n\n"
            response += traffic_response.response

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=response,
                data={
                    "event": target_event,
                    "traffic": traffic_response.data
                }
            )

        except Exception as e:
            self.logger.error(
                f"Traffic check for event failed: {e}",
                exc_info=True
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao verificar trafego para evento: {str(e)}",
                error=str(e)
            )

    def get_capabilities(self) -> List[str]:
        """Get calendar agent capabilities."""
        return [
            "calendar_management",
            "meetings",
            "schedule",
            "events",
            "event_creation",
            "traffic_alerts"
        ]
