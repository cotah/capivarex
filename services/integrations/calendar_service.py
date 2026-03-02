"""
Calendar Service - Refactored with BaseService architecture.

Full Google Calendar API integration using Service Account authentication.

Provides:
- Google Calendar integration via Service Account
- List upcoming events, today's events, morning briefing events
- Create, update, delete events
- Next meeting lookup
- Calendar briefing generation
- Metrics tracking and health checks
"""

import os
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)
from services.auth.google_oauth_service import get_google_oauth

load_dotenv()

logger = logging.getLogger(__name__)

# Scopes required for calendar access
SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _utc_isoformat(dt: datetime) -> str:
    """Convert a datetime to an RFC 3339 UTC string ending with 'Z'.

    Handles both naive (assumed UTC) and timezone-aware datetimes correctly.
    """
    # Strip tzinfo so .isoformat() never appends '+00:00'
    return dt.replace(tzinfo=None).isoformat() + "Z"


@register_service("calendar")
class CalendarService(BaseService):
    """
    Google Calendar integration service using Service Account.

    Features:
    - Service Account authentication (no interactive OAuth)
    - Event listing (upcoming, today, date range)
    - Event creation with attendees
    - Event update / deletion
    - Next meeting lookup (prioritises events with attendees)
    - Calendar briefing generation (today + tomorrow)
    - Morning briefing events
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "calendar",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the Google Calendar integration."""
        super().__init__(name, config)
        self._service: Optional[Any] = None
        self._credentials: Optional[Any] = None
        self.service_account_file: str = ""
        self.calendar_id: str = "primary"

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """
        Initialize Google Calendar service using a Service Account JSON file.

        Environment variables used:
        - GOOGLE_SERVICE_ACCOUNT_FILE  (default: ``service_account.json``)
        - GOOGLE_CALENDAR_ID           (default: ``primary``)
        """
        try:
            from google.oauth2 import service_account as sa_module
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ServiceUnavailableError(
                f"Google Calendar dependencies not installed: {exc}"
            )

        import json
        import tempfile

        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

        # Option 1: Credentials from environment variable (recommended for Railway/production)
        google_creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
        if google_creds_json:
            try:
                creds_dict = json.loads(google_creds_json)
                # Write to a temp file so the Google SDK can read it
                tmp = tempfile.NamedTemporaryFile(
                    mode="w", suffix=".json", delete=False
                )
                json.dump(creds_dict, tmp)
                tmp.close()
                self.service_account_file = tmp.name
                self.logger.info(
                    "Using Google credentials from GOOGLE_CREDENTIALS_JSON env var"
                )
            except (json.JSONDecodeError, IOError) as e:
                raise ServiceUnavailableError(
                    f"Failed to parse GOOGLE_CREDENTIALS_JSON: {e}"
                )
        else:
            # Option 2: Credentials from file (local development)
            self.service_account_file = os.getenv(
                "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
            )
            if not os.path.exists(self.service_account_file):
                raise ServiceUnavailableError(
                    f"Service account file '{self.service_account_file}' not found. "
                    "Set GOOGLE_CREDENTIALS_JSON env var or GOOGLE_SERVICE_ACCOUNT_FILE path."
                )

        try:
            credentials = sa_module.Credentials.from_service_account_file(
                self.service_account_file,
                scopes=SCOPES,
            )
            self._credentials = credentials
            self._service = build("calendar", "v3", credentials=credentials)
            self.logger.info(
                "Google Calendar service initialised with service account "
                f"(calendar_id={self.calendar_id})"
            )
        except Exception as exc:
            self.logger.error(f"Calendar initialisation failed: {exc}", exc_info=True)
            raise ServiceUnavailableError(f"Calendar initialisation failed: {exc}")

    async def _health_check(self) -> bool:
        """Return True when the underlying API service object exists."""
        return self._service is not None

    # ------------------------------------------------------------------
    # Authentication helper (synchronous, backward-compat)
    # ------------------------------------------------------------------

    def authenticate(self) -> bool:
        """
        Synchronous authentication helper for backward compatibility.

        Returns:
            True if authentication succeeded, False otherwise.
        """
        if self._service is not None:
            return True

        try:
            from google.oauth2 import service_account as sa_module
            from googleapiclient.discovery import build

            sa_file = self.service_account_file or os.getenv(
                "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
            )
            cal_id = self.calendar_id or os.getenv("GOOGLE_CALENDAR_ID", "primary")

            if not os.path.exists(sa_file):
                self.logger.error(f"Service account file '{sa_file}' not found.")
                return False

            credentials = sa_module.Credentials.from_service_account_file(
                sa_file, scopes=SCOPES
            )
            self._credentials = credentials
            self._service = build("calendar", "v3", credentials=credentials)
            self.service_account_file = sa_file
            self.calendar_id = cal_id
            self.logger.info("Authenticated with Google Calendar API (sync)")
            return True

        except Exception as exc:
            self.logger.error(f"Authentication error: {exc}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_service(self) -> None:
        """Ensure the API service is available; attempt auth if not."""
        if self._service is None:
            if not self.authenticate():
                raise RuntimeError(
                    "Calendar service not initialised and authentication failed"
                )

    async def _get_oauth_service(self, user_id: str) -> Optional[Any]:
        """
        Tenta criar um Google Calendar service usando OAuth2 tokens do user.
        Se o user não tem OAuth2 conectado, retorna None (fallback para Service Account).

        Args:
            user_id: ID do utilizador

        Returns:
            Google Calendar service object ou None
        """
        try:
            oauth = get_google_oauth()
            access_token = await oauth.get_valid_access_token(user_id)
            if not access_token:
                return None

            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build

            creds = Credentials(token=access_token)
            service = build("calendar", "v3", credentials=creds)
            self.logger.debug("Using OAuth2 calendar for user %s", user_id)
            return service
        except Exception as e:
            self.logger.debug(
                "OAuth2 calendar not available for user %s: %s", user_id, e
            )
            return None

    def _get_service_for_user(
        self,
        user_id: Optional[str] = None,
        _oauth_service: Optional[Any] = None,
    ) -> Any:
        """
        Retorna o service object correcto:
        - Se _oauth_service fornecido -> usa esse (OAuth2 per-user)
        - Senão -> usa self._service (Service Account)

        Args:
            user_id: ID do utilizador (para logging)
            _oauth_service: Service pré-construído via OAuth2

        Returns:
            Google Calendar API service object
        """
        if _oauth_service:
            return _oauth_service
        self._ensure_service()
        return self._service

    async def _resolve_service(self, user_id: Optional[str] = None) -> Any:
        """
        Resolve qual service usar: OAuth2 (se user conectado) ou Service Account.

        Args:
            user_id: ID do utilizador (se fornecido, tenta OAuth2)

        Returns:
            Google Calendar API service object
        """
        if user_id:
            oauth_svc = await self._get_oauth_service(user_id)
            if oauth_svc:
                return oauth_svc
        # Fallback: Service Account
        self._ensure_service()
        return self._service

    @staticmethod
    def _format_event_dict(event: Dict[str, Any]) -> Dict[str, Any]:
        """Convert a raw Google Calendar event into a standardised dict."""
        return {
            "id": event.get("id"),
            "summary": event.get("summary", "No title"),
            "start": event.get("start", {}).get(
                "dateTime", event.get("start", {}).get("date")
            ),
            "end": event.get("end", {}).get(
                "dateTime", event.get("end", {}).get("date")
            ),
            "location": event.get("location", ""),
            "description": event.get("description", ""),
            "attendees": [att.get("email") for att in event.get("attendees", [])],
            "html_link": event.get("htmlLink", ""),
            "status": event.get("status", ""),
        }

    # ------------------------------------------------------------------
    # Event listing
    # ------------------------------------------------------------------

    def get_upcoming_events(
        self,
        max_results: int = 10,
        days_ahead: int = 7,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        calendar_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get upcoming events from Google Calendar.

        Args:
            max_results: Maximum number of events to return.
            days_ahead:  Number of days ahead to look for events.
            time_min:    Explicit start of the range (overrides ``now``).
            time_max:    Explicit end of the range (overrides ``days_ahead``).
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).

        Returns:
            List of formatted event dictionaries.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        start_time = time.time()

        try:
            if time_min is None:
                time_min = datetime.now(timezone.utc)
            if time_max is None:
                time_max = time_min + timedelta(days=days_ahead)

            time_min_str = (
                _utc_isoformat(time_min) if isinstance(time_min, datetime) else time_min
            )
            time_max_str = (
                _utc_isoformat(time_max) if isinstance(time_max, datetime) else time_max
            )

            events_result = (
                self._service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min_str,
                    timeMax=time_max_str,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            formatted = [self._format_event_dict(ev) for ev in events]

            latency = time.time() - start_time
            self._track_call(latency, error=False)
            self.logger.info(
                f"Fetched {len(formatted)} upcoming events (days_ahead={days_ahead})"
            )
            return formatted

        except Exception as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching upcoming events: {exc}", exc_info=True)
            return []

    def get_today_events(
        self, calendar_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all events for today (UTC).

        Args:
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).

        Returns:
            List of formatted event dictionaries.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        start_time = time.time()

        try:
            now = datetime.now(timezone.utc)
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            time_min = _utc_isoformat(start_of_day)
            time_max = _utc_isoformat(end_of_day)

            events_result = (
                self._service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])
            formatted = [self._format_event_dict(ev) for ev in events]

            latency = time.time() - start_time
            self._track_call(latency, error=False)
            self.logger.info(f"Fetched {len(formatted)} events for today")
            return formatted

        except Exception as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching today's events: {exc}", exc_info=True)
            return []

    # ------------------------------------------------------------------
    # Event CRUD
    # ------------------------------------------------------------------

    def create_event(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        calendar_id: Optional[str] = None,
        timezone: str = "UTC",
    ) -> Optional[Dict[str, Any]]:
        """
        Create a new calendar event.

        Args:
            summary:     Event title.
            start_time:  Event start as a datetime object.
            end_time:    Event end as a datetime object.
            description: Optional description.
            location:    Optional location string.
            attendees:   Optional list of attendee e-mail addresses.
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).
            timezone:    Timezone string (default ``UTC``).

        Returns:
            Created event dictionary, or None on failure.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        call_start = time.time()

        try:
            self.logger.info(
                "Creating calendar event",
                extra={
                    "title": summary,
                    "start": start_time.isoformat()
                    if isinstance(start_time, datetime)
                    else str(start_time),
                    "end": end_time.isoformat()
                    if isinstance(end_time, datetime)
                    else str(end_time),
                    "location": location,
                },
            )

            event_body: Dict[str, Any] = {
                "summary": summary,
                "location": location,
                "description": description,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": timezone,
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": timezone,
                },
            }

            if attendees:
                event_body["attendees"] = [{"email": email} for email in attendees]

            created_event = (
                self._service.events()
                .insert(calendarId=cal_id, body=event_body)
                .execute()
            )

            latency = time.time() - call_start
            self._track_call(latency, error=False)

            self.logger.info(
                "Calendar event created",
                extra={
                    "event_id": created_event.get("id"),
                    "title": summary,
                    "link": created_event.get("htmlLink"),
                },
            )
            return created_event

        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(
                f"Failed to create calendar event: {exc}",
                extra={"title": summary},
                exc_info=True,
            )
            return None

    def create_meeting(
        self,
        summary: str,
        start_time: datetime,
        end_time: datetime,
        attendees: Optional[List[str]] = None,
        description: str = "",
        timezone: str = "Europe/Dublin",
        calendar_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Cria um evento no Google Calendar COM link do Google Meet.

        Idêntico ao create_event(), mas adiciona ``conferenceData``
        para gerar automaticamente o link meet.google.com.

        Args:
            summary:     Título da reunião.
            start_time:  Início da reunião (datetime).
            end_time:    Fim da reunião (datetime).
            attendees:   Lista de emails dos participantes (opcional).
            description: Descrição/pauta da reunião (opcional).
            timezone:    Timezone do evento (default: Europe/Dublin).
            calendar_id: ID do calendário (default: self.calendar_id).

        Returns:
            Dict com os campos do evento criado incluindo:
                - ``meet_link``: URL do Google Meet (meet.google.com/xxx-yyy-zzz)
                - ``html_link``: URL do evento no Google Calendar
                - ``id``:        ID do evento
                - ``summary``:   Título
            Retorna None em caso de falha.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        call_start = time.time()

        try:
            event_body: Dict[str, Any] = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": timezone,
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": timezone,
                },
            }

            if attendees:
                event_body["attendees"] = [{"email": email} for email in attendees]

            created_event = (
                self._service.events()
                .insert(
                    calendarId=cal_id,
                    body=event_body,
                )
                .execute()
            )

            # Meet link não disponível com Gmail pessoal + service account
            meet_link = ""

            latency = time.time() - call_start
            self._track_call(latency, error=False)

            self.logger.info(
                "Meeting created with Google Meet link",
                extra={
                    "event_id": created_event.get("id"),
                    "title": summary,
                    "meet_link": meet_link,
                },
            )

            return {
                "id": created_event.get("id"),
                "summary": created_event.get("summary"),
                "html_link": created_event.get("htmlLink", ""),
                "meet_link": meet_link,
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "attendees": attendees or [],
                "status": "created",
            }

        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(
                f"Failed to create meeting: {exc}",
                extra={"title": summary},
                exc_info=True,
            )
            return None

    def update_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """
        Update an existing calendar event.

        Args:
            event_id:    ID of the event to update.
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).
            **kwargs:    Fields to update.  Supported keys:
                         ``summary``, ``description``, ``location``,
                         ``start_time`` (datetime), ``end_time`` (datetime),
                         ``attendees`` (list of emails), or any raw
                         Google Calendar event field via ``updates`` dict.

        Returns:
            Updated event dictionary, or None on failure.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        call_start = time.time()

        try:
            # Fetch the existing event
            event = (
                self._service.events()
                .get(calendarId=cal_id, eventId=event_id)
                .execute()
            )

            # Apply known keyword updates
            if "summary" in kwargs:
                event["summary"] = kwargs["summary"]
            if "description" in kwargs:
                event["description"] = kwargs["description"]
            if "location" in kwargs:
                event["location"] = kwargs["location"]
            if "start_time" in kwargs:
                event["start"] = {
                    "dateTime": kwargs["start_time"].isoformat(),
                    "timeZone": "UTC",
                }
            if "end_time" in kwargs:
                event["end"] = {
                    "dateTime": kwargs["end_time"].isoformat(),
                    "timeZone": "UTC",
                }
            if "attendees" in kwargs:
                event["attendees"] = [{"email": email} for email in kwargs["attendees"]]

            # Also accept a generic ``updates`` dict for raw fields
            if "updates" in kwargs and isinstance(kwargs["updates"], dict):
                for key, value in kwargs["updates"].items():
                    event[key] = value

            updated_event = (
                self._service.events()
                .update(calendarId=cal_id, eventId=event_id, body=event)
                .execute()
            )

            latency = time.time() - call_start
            self._track_call(latency, error=False)
            self.logger.info(f"Event updated: {event_id}")
            return {
                "id": updated_event.get("id"),
                "summary": updated_event.get("summary"),
                "html_link": updated_event.get("htmlLink"),
                "status": "updated",
            }

        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(f"Error updating event {event_id}: {exc}", exc_info=True)
            return None

    def delete_event(
        self,
        event_id: str,
        calendar_id: Optional[str] = None,
    ) -> bool:
        """
        Delete a calendar event.

        Args:
            event_id:    ID of the event to delete.
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).

        Returns:
            True if deletion succeeded, False otherwise.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        call_start = time.time()

        try:
            self._service.events().delete(calendarId=cal_id, eventId=event_id).execute()

            latency = time.time() - call_start
            self._track_call(latency, error=False)
            self.logger.info(f"Event deleted: {event_id}")
            return True

        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(f"Error deleting event {event_id}: {exc}", exc_info=True)
            return False

    # ------------------------------------------------------------------
    # Meeting / briefing helpers
    # ------------------------------------------------------------------

    def get_next_meeting(
        self, calendar_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get the next upcoming meeting.

        A *meeting* is an event that has attendees.  If no meeting with
        attendees is found among the next 10 events the first event is
        returned instead.

        Args:
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).

        Returns:
            Next meeting dictionary, or None if nothing is scheduled.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id
        call_start = time.time()

        try:
            now = datetime.now(timezone.utc)
            time_min = _utc_isoformat(now)

            events_result = (
                self._service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = events_result.get("items", [])

            # Prefer the first event that has attendees
            for event in events:
                if event.get("attendees"):
                    result = self._format_event_dict(event)
                    latency = time.time() - call_start
                    self._track_call(latency, error=False)
                    return result

            # Fallback: return the very first event even without attendees
            if events:
                result = self._format_event_dict(events[0])
                latency = time.time() - call_start
                self._track_call(latency, error=False)
                return result

            latency = time.time() - call_start
            self._track_call(latency, error=False)
            return None

        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(f"Error fetching next meeting: {exc}", exc_info=True)
            return None

    def format_event_for_briefing(self, event: Dict[str, Any]) -> str:
        """
        Format a single event dictionary into a human-readable line for
        inclusion in a calendar briefing.

        Args:
            event: Formatted event dictionary.

        Returns:
            A bullet-point string such as ``* Meeting at 09:30 (Room 4)``.
        """
        summary = event.get("summary", "No title")
        start = event.get("start", "")
        location = event.get("location", "")

        # Parse the start time for display
        try:
            if "T" in str(start):
                start_dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
                time_str = start_dt.strftime("%H:%M")
            else:
                time_str = "All day"
        except Exception:
            time_str = str(start)

        formatted = f"* {summary}"
        if time_str and time_str != start:
            formatted += f" at {time_str}"
        if location:
            formatted += f" ({location})"

        return formatted

    def generate_calendar_briefing(self, calendar_id: Optional[str] = None) -> str:
        """
        Generate a full calendar briefing string (today + tomorrow).

        Args:
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).

        Returns:
            Multi-line briefing text.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id

        try:
            # -- Today's events --
            today_events = self.get_today_events(calendar_id=cal_id)

            # -- Tomorrow's events --
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_end = tomorrow.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            time_min = _utc_isoformat(tomorrow_start)
            time_max = _utc_isoformat(tomorrow_end)

            events_result = (
                self._service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            tomorrow_events = [
                self._format_event_dict(ev) for ev in events_result.get("items", [])
            ]

            # -- Build the briefing text --
            briefing = "**Calendar Briefing**\n\n"

            if today_events:
                briefing += (
                    f"**Today ({datetime.now(timezone.utc).strftime('%B %d')}):**\n"
                )
                for ev in today_events:
                    briefing += self.format_event_for_briefing(ev) + "\n"
                briefing += "\n"
            else:
                briefing += "**Today:** No events scheduled.\n\n"

            if tomorrow_events:
                briefing += f"**Tomorrow ({tomorrow.strftime('%B %d')}):**\n"
                for ev in tomorrow_events:
                    briefing += self.format_event_for_briefing(ev) + "\n"
            else:
                briefing += "**Tomorrow:** No events scheduled."

            self.logger.info("Calendar briefing generated")
            return briefing

        except Exception as exc:
            self.logger.error(
                f"Error generating calendar briefing: {exc}", exc_info=True
            )
            return "Unable to generate calendar briefing."

    def get_morning_briefing_events(
        self, calendar_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get events for a morning briefing (today + tomorrow).

        Args:
            calendar_id: Calendar ID (defaults to instance ``self.calendar_id``).

        Returns:
            Combined list of today's and tomorrow's events.
        """
        self._ensure_service()
        cal_id = calendar_id or self.calendar_id

        try:
            today_events = self.get_today_events(calendar_id=cal_id)

            # Tomorrow
            tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
            tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            tomorrow_end = tomorrow.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            time_min = _utc_isoformat(tomorrow_start)
            time_max = _utc_isoformat(tomorrow_end)

            events_result = (
                self._service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            tomorrow_events = [
                self._format_event_dict(ev) for ev in events_result.get("items", [])
            ]

            combined = today_events + tomorrow_events
            self.logger.info(
                f"Morning briefing: {len(today_events)} today, "
                f"{len(tomorrow_events)} tomorrow"
            )
            return combined

        except Exception as exc:
            self.logger.error(
                f"Error fetching morning briefing events: {exc}", exc_info=True
            )
            return []

    # ------------------------------------------------------------------
    # Async methods with OAuth2 per-user support
    # ------------------------------------------------------------------
    # Estes métodos tentam OAuth2 primeiro, Service Account como fallback.
    # Os métodos síncronos acima continuam a funcionar para backward-compat.

    async def async_get_upcoming_events(
        self,
        user_id: Optional[str] = None,
        max_results: int = 10,
        days_ahead: int = 7,
        calendar_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Async version of get_upcoming_events with OAuth2 support.
        Se user_id fornecido e OAuth2 conectado -> calendário pessoal do user.
        Senão -> Service Account calendar.
        """
        import time as _time

        svc = await self._resolve_service(user_id)
        cal_id = calendar_id or (
            "primary" if (user_id and svc != self._service) else self.calendar_id
        )
        start = _time.time()
        try:
            now = datetime.now(timezone.utc)
            time_min = _utc_isoformat(now)
            time_max = _utc_isoformat(now + timedelta(days=days_ahead))

            result = (
                svc.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = [
                self._format_event_dict(e) for e in result.get("items", [])
            ]
            self._track_call(_time.time() - start, error=False)
            return events
        except Exception as exc:
            self._track_call(_time.time() - start, error=True)
            self.logger.error(
                "async_get_upcoming_events failed: %s", exc, exc_info=True
            )
            return []

    async def async_get_today_events(
        self,
        user_id: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Async version of get_today_events with OAuth2 support."""
        import time as _time

        svc = await self._resolve_service(user_id)
        cal_id = calendar_id or (
            "primary" if (user_id and svc != self._service) else self.calendar_id
        )
        start = _time.time()
        try:
            now = datetime.now(timezone.utc)
            time_min = _utc_isoformat(
                now.replace(hour=0, minute=0, second=0, microsecond=0)
            )
            time_max = _utc_isoformat(
                now.replace(hour=23, minute=59, second=59, microsecond=999999)
            )

            result = (
                svc.events()
                .list(
                    calendarId=cal_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = [
                self._format_event_dict(e) for e in result.get("items", [])
            ]
            self._track_call(_time.time() - start, error=False)
            return events
        except Exception as exc:
            self._track_call(_time.time() - start, error=True)
            self.logger.error(
                "async_get_today_events failed: %s", exc, exc_info=True
            )
            return []

    async def async_create_event(
        self,
        user_id: Optional[str] = None,
        summary: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        calendar_id: Optional[str] = None,
        tz: str = "UTC",
    ) -> Optional[Dict[str, Any]]:
        """Async version of create_event with OAuth2 support."""
        import time as _time

        svc = await self._resolve_service(user_id)
        cal_id = calendar_id or (
            "primary" if (user_id and svc != self._service) else self.calendar_id
        )
        call_start = _time.time()
        try:
            event_body: Dict[str, Any] = {
                "summary": summary,
                "location": location,
                "description": description,
                "start": {"dateTime": start_time.isoformat(), "timeZone": tz},
                "end": {"dateTime": end_time.isoformat(), "timeZone": tz},
            }
            if attendees:
                event_body["attendees"] = [{"email": e} for e in attendees]

            created = (
                svc.events()
                .insert(calendarId=cal_id, body=event_body)
                .execute()
            )

            self._track_call(_time.time() - call_start, error=False)
            self.logger.info("Event created (async): %s", summary)
            return created
        except Exception as exc:
            self._track_call(_time.time() - call_start, error=True)
            self.logger.error(
                "async_create_event failed: %s", exc, exc_info=True
            )
            return None

    async def async_create_meeting(
        self,
        user_id: Optional[str] = None,
        summary: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        attendees: Optional[List[str]] = None,
        description: str = "",
        tz: str = "Europe/Dublin",
        calendar_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Async version of create_meeting with OAuth2 + Google Meet support."""
        import time as _time

        svc = await self._resolve_service(user_id)
        cal_id = calendar_id or (
            "primary" if (user_id and svc != self._service) else self.calendar_id
        )
        is_oauth = user_id and svc != self._service
        call_start = _time.time()
        try:
            event_body: Dict[str, Any] = {
                "summary": summary,
                "description": description,
                "start": {"dateTime": start_time.isoformat(), "timeZone": tz},
                "end": {"dateTime": end_time.isoformat(), "timeZone": tz},
            }
            if attendees:
                event_body["attendees"] = [{"email": e} for e in attendees]

            # Google Meet só funciona com OAuth2 (não com Service Account)
            if is_oauth:
                event_body["conferenceData"] = {
                    "createRequest": {
                        "requestId": f"jarvis-{_time.time_ns()}",
                        "conferenceSolutionKey": {"type": "hangoutsMeet"},
                    }
                }

            created = (
                svc.events()
                .insert(
                    calendarId=cal_id,
                    body=event_body,
                    conferenceDataVersion=1 if is_oauth else 0,
                )
                .execute()
            )

            # Extrair Meet link
            meet_link = ""
            if is_oauth:
                conf_data = created.get("conferenceData", {})
                for ep in conf_data.get("entryPoints", []):
                    if ep.get("entryPointType") == "video":
                        meet_link = ep.get("uri", "")
                        break

            self._track_call(_time.time() - call_start, error=False)
            return {
                "id": created.get("id"),
                "summary": created.get("summary"),
                "html_link": created.get("htmlLink", ""),
                "meet_link": meet_link,
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
                "attendees": attendees or [],
                "status": "created",
            }
        except Exception as exc:
            self._track_call(_time.time() - call_start, error=True)
            self.logger.error(
                "async_create_meeting failed: %s", exc, exc_info=True
            )
            return None

    async def async_get_next_meeting(
        self,
        user_id: Optional[str] = None,
        calendar_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Async version of get_next_meeting with OAuth2 support."""
        events = await self.async_get_upcoming_events(
            user_id=user_id,
            max_results=10,
            days_ahead=7,
            calendar_id=calendar_id,
        )
        # Prefer event with attendees
        for ev in events:
            if ev.get("attendees"):
                return ev
        return events[0] if events else None


# ------------------------------------------------------------------
# Backward-compatible singleton accessor
# ------------------------------------------------------------------
_calendar_service: Optional[CalendarService] = None


def get_calendar_service() -> CalendarService:
    """Get or create the global CalendarService instance."""
    global _calendar_service
    if _calendar_service is None:
        from services.core import get_service

        _calendar_service = get_service("calendar")
    return _calendar_service


# Backward-compatible alias
GoogleCalendarService = CalendarService
