"""
Calendar Agent - Manages calendar and schedule.

Uses OAuth2 per-user calendar only.  If the user hasn't
connected their Google account, returns a message with the
OAuth2 connect URL.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from schemas.calendar import CalendarEventInput
from services import get_service
from services.auth.google_oauth_service import get_google_oauth
from services.core import ServiceUnavailableError
from services.i18n import t


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
    - Google account connection
    """

    def __init__(self):
        super().__init__(
            name="calendar",
            description="Manages calendar, meetings, and schedule",
        )
        self._calendar_service: Optional[Any] = None

    async def _get_calendar_service(self) -> Optional[Any]:
        """Get the Calendar service, initializing if needed."""
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

    # Intent keywords mapped to handler method names
    _INTENT_KEYWORDS: Dict[str, List[str]] = {
        "next_meeting": ["next meeting", "proxima reuniao", "next event"],
        "today": ["today", "hoje", "today's", "de hoje"],
        "week": ["this week", "esta semana", "week", "semana"],
        "briefing": ["briefing", "resumo", "summary"],
        "traffic": [
            "trafego",
            "traffic",
            "sair",
            "leave",
            "quando sair",
            "when to leave",
        ],
        "connect": [
            "conectar google",
            "connect google",
            "conectar calendario",
            "conectar gmail",
        ],
    }

    def _detect_intent(self, query_lower: str) -> str:
        """Detect calendar query intent from keywords."""
        for intent, keywords in self._INTENT_KEYWORDS.items():
            if any(kw in query_lower for kw in keywords):
                return intent
        return "upcoming"

    async def execute(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        """Process calendar-related queries."""
        try:
            calendar_service = await self._get_calendar_service()
            if not calendar_service:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("calendar_service_unavailable"),
                    error="Calendar service not available",
                )

            user_id = str(
                context.get("user_id", context.get("chat_id", ""))
            )

            # Priority: explicit create event action from PromptCleaner
            if context.get("action") == "create_event":
                event_params = context.get("event_params", {})
                return await self._create_event(
                    calendar_service, event_params, user_id=user_id
                )

            # Dispatch by detected intent
            intent = self._detect_intent(prompt.lower())

            # Check if user wants to connect Google account
            if intent == "connect":
                oauth = get_google_oauth()
                if await oauth.is_connected(user_id):
                    return AgentResponse(
                        status=AgentStatus.SUCCESS,
                        response=(
                            "A tua conta Google já está conectada! "
                            "Calendar e Gmail activos."
                        ),
                    )
                auth_url = oauth.get_auth_url(user_id)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=(
                        "Clica no link para conectar a tua conta Google "
                        f"(Calendar + Gmail):\n{auth_url}"
                    ),
                    data={"auth_url": auth_url},
                )

            dispatch = {
                "next_meeting": lambda: self._get_next_meeting(
                    calendar_service, user_id=user_id
                ),
                "today": lambda: self._get_today_events(
                    calendar_service, user_id=user_id
                ),
                "week": lambda: self._get_week_events(
                    calendar_service, user_id=user_id
                ),
                "briefing": lambda: self._get_briefing(
                    calendar_service, user_id=user_id
                ),
                "traffic": lambda: self._check_traffic_for_next_event(
                    calendar_service, user_id, context.get("user_location", "Dublin")
                ),
                "upcoming": lambda: self._get_upcoming_events(
                    calendar_service, user_id=user_id
                ),
            }

            handler = dispatch[intent]
            return await handler()

        except ServiceUnavailableError as e:
            # OAuth2 not connected — return the connect message
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=str(e),
                error="Not connected",
            )
        except Exception as e:
            self.logger.error(
                f"Calendar query failed: {e}", exc_info=True
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao acessar seu calendario: {str(e)}",
                error=str(e),
            )

    async def _get_next_meeting(
        self, calendar_service: Any, user_id: str
    ) -> AgentResponse:
        """Get the next upcoming meeting."""
        next_meeting = await calendar_service.async_get_next_meeting(
            user_id=user_id
        )

        if not next_meeting:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem reunioes agendadas.",
                data={"events": []},
            )

        summary = next_meeting.get("summary", "Sem titulo")
        start = next_meeting.get("start", "")
        location = next_meeting.get("location", "")

        try:
            if "T" in start:
                start_dt = datetime.fromisoformat(
                    start.replace("Z", "+00:00")
                )
                time_str = start_dt.strftime("%d/%m/%Y as %H:%M")
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
            data={"events": [next_meeting]},
        )

    async def _get_today_events(
        self, calendar_service: Any, user_id: str
    ) -> AgentResponse:
        """Get all events for today."""
        events = await calendar_service.async_get_today_events(
            user_id=user_id
        )

        if not events:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem eventos agendados para hoje.",
                data={"events": []},
            )

        response = f"Voce tem {len(events)} evento(s) hoje:\n\n"
        for event in events:
            response += (
                calendar_service.format_event_for_briefing(event) + "\n"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"events": events},
        )

    async def _get_week_events(
        self, calendar_service: Any, user_id: str
    ) -> AgentResponse:
        """Get events for the current week."""
        events = await calendar_service.async_get_upcoming_events(
            user_id=user_id, max_results=50, days_ahead=7
        )

        if not events:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem eventos agendados para esta semana.",
                data={"events": []},
            )

        response = f"Voce tem {len(events)} evento(s) esta semana:\n\n"
        for event in events:
            response += (
                calendar_service.format_event_for_briefing(event) + "\n"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"events": events},
        )

    async def _get_upcoming_events(
        self, calendar_service: Any, user_id: str
    ) -> AgentResponse:
        """Get upcoming events (next 7 days)."""
        events = await calendar_service.async_get_upcoming_events(
            user_id=user_id, max_results=10
        )

        if not events:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Voce nao tem eventos nos proximos 7 dias.",
                data={"events": []},
            )

        response = f"Voce tem {len(events)} evento(s) proximos:\n\n"
        for event in events:
            response += (
                calendar_service.format_event_for_briefing(event) + "\n"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response.strip(),
            data={"events": events},
        )

    async def _get_briefing(
        self, calendar_service: Any, user_id: str
    ) -> AgentResponse:
        """Get calendar briefing."""
        events = await calendar_service.async_get_today_events(
            user_id=user_id
        )

        if not events:
            briefing_text = (
                "**Calendar Briefing**\n\n"
                "**Today:** No events scheduled."
            )
        else:
            briefing_text = "**Calendar Briefing**\n\n"
            briefing_text += (
                f"**Today ({datetime.now(timezone.utc).strftime('%B %d')}):**\n"
            )
            for ev in events:
                briefing_text += (
                    calendar_service.format_event_for_briefing(ev) + "\n"
                )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=briefing_text.strip(),
            data={"events": events},
        )

    async def _create_event(
        self,
        calendar_service: Any,
        event_params: Dict[str, Any],
        user_id: str,
    ) -> AgentResponse:
        """Create a new calendar event."""
        try:
            event_input = CalendarEventInput.model_validate(event_params)
        except Exception as e:
            msg = str(e)
            if "\ntitle\n" in msg:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Nao consegui identificar o titulo do evento. "
                        "Por favor, especifique o que deseja agendar."
                    ),
                    error="Missing title",
                )
            if "\nstart_datetime\n" in msg:
                if "value_error" in msg:
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response=(
                            "Erro ao processar data e hora do evento. "
                            "Por favor, use um formato valido "
                            "(ex: 2025-02-15T15:00:00)."
                        ),
                        error="Invalid start_datetime",
                    )
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Nao consegui identificar a data e hora do evento. "
                        "Por favor, especifique quando deseja agendar."
                    ),
                    error="Missing start_datetime",
                )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    f"Erro ao processar dados do evento: {msg}. "
                    "Por favor, use um formato valido."
                ),
                error=str(e),
            )

        end_dt = event_input.resolved_end()

        created_event = await calendar_service.async_create_event(
            user_id=user_id,
            summary=event_input.title,
            start_time=event_input.start_datetime,
            end_time=end_dt,
            location=event_input.location,
            description=event_input.description,
        )

        if not created_event:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Nao foi possivel criar o evento. "
                    "Por favor, tente novamente."
                ),
                error="Calendar service returned None",
            )

        self.logger.info(
            "Event created successfully: %s at %s",
            event_input.title,
            event_input.start_datetime.isoformat(),
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_event_response(event_input, end_dt),
            data={"event": created_event},
        )

    @staticmethod
    def _format_event_response(
        event: CalendarEventInput, end_dt: datetime
    ) -> str:
        """Format a human-readable confirmation for a created event."""
        response = "Evento criado com sucesso!\n\n"
        response += f"{event.title}\n"
        response += (
            f"Data: {event.start_datetime.strftime('%d/%m/%Y as %H:%M')}"
        )
        response += f" - {end_dt.strftime('%H:%M')}"

        if event.location:
            response += f"\nLocal: {event.location}"
        if event.description:
            response += f"\nDescricao: {event.description}"

        return response.strip()

    @staticmethod
    def _find_next_event_with_location(
        events: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Find the first future event with a physical location."""
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
        """Parse a timed event's start into a naive datetime."""
        start = event.get("start", "")
        if "T" not in start:
            summary = event.get("summary", "Evento")
            raise ValueError(
                f"O evento '{summary}' e um evento de dia inteiro, "
                "sem horario especifico."
            )
        return datetime.fromisoformat(
            start.replace("Z", "+00:00")
        ).replace(tzinfo=None)

    async def check_traffic_for_next_event(
        self, user_location: str, **kwargs
    ) -> AgentResponse:
        """Public wrapper for traffic check functionality."""
        calendar_service = await self._get_calendar_service()
        user_id = kwargs.get("user_id", "")
        return await self._check_traffic_for_next_event(
            calendar_service, user_id, user_location
        )

    async def _check_traffic_for_next_event(
        self,
        calendar_service: Any,
        user_id: str,
        user_location: str,
    ) -> AgentResponse:
        """Check traffic conditions for the next event with location."""
        try:
            events = await calendar_service.async_get_upcoming_events(
                user_id=user_id, max_results=10
            )
            if not events:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Voce nao tem eventos agendados.",
                    error="No events found",
                )

            target_event = self._find_next_event_with_location(events)
            if not target_event:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Nenhum evento futuro com localizacao encontrado."
                    ),
                    error="No future events with location",
                )

            event_summary = target_event.get("summary", "Evento sem titulo")
            event_location = target_event.get("location", "")

            try:
                event_time_naive = self._parse_event_time(target_event)
            except (ValueError, TypeError) as e:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=str(e),
                    error=str(e),
                )

            from agents.core import get_agent

            traffic_agent = get_agent("traffic")

            if not traffic_agent:
                return AgentResponse(
                    status=AgentStatus.PARTIAL,
                    response=(
                        f"Proximo evento com local: '{event_summary}' "
                        f"em {event_location} as "
                        f"{event_time_naive.strftime('%H:%M')}. "
                        "Servico de trafego nao disponivel "
                        "para verificar condicoes."
                    ),
                    data={"event": target_event},
                )

            traffic_context = {
                "origin": user_location,
                "destination": event_location,
                "event_time": event_time_naive.isoformat(),
            }

            traffic_response = await traffic_agent.execute(
                f"Trafego de {user_location} para {event_location}",
                traffic_context,
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
                    "traffic": traffic_response.data,
                },
            )

        except ServiceUnavailableError:
            raise
        except Exception as e:
            self.logger.error(
                f"Traffic check for event failed: {e}", exc_info=True
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao verificar trafego para evento: {str(e)}",
                error=str(e),
            )

    def get_capabilities(self) -> List[str]:
        return [
            "calendar_management",
            "meetings",
            "schedule",
            "events",
            "event_creation",
            "traffic_alerts",
        ]
