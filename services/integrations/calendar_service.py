"""
Calendar Service — OAuth2 per-user only.

Google Calendar integration via OAuth2 per-user tokens
managed by GoogleOAuthService.  There is no Service Account
fallback — if the user hasn't connected Google, the caller
is told to redirect them through the OAuth2 connect flow.

Provides:
- List upcoming events, today's events
- Create events / meetings (with Google Meet link)
- Next meeting lookup
- Calendar briefing generation
- Event formatting helpers
- Metrics tracking via BaseService
"""

import logging
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)
from services.auth.google_oauth_service import get_google_oauth

load_dotenv()

logger = logging.getLogger(__name__)


def _utc_isoformat(dt: datetime) -> str:
    """Convert a datetime to an RFC 3339 UTC string ending with 'Z'."""
    return dt.replace(tzinfo=None).isoformat() + "Z"


@register_service("calendar")
class CalendarService(BaseService):
    """
    Google Calendar integration service — OAuth2 per-user only.

    Each user accesses their OWN Google Calendar via OAuth2 tokens.
    If a user hasn't connected, callers should direct them to the
    OAuth2 connect URL provided by ``get_google_oauth().get_auth_url()``.
    """

    def __init__(
        self,
        name: str = "calendar",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, config)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Check that Google OAuth2 is configured."""
        oauth = get_google_oauth()
        if not oauth.is_configured:
            raise ServiceUnavailableError(
                "GOOGLE_OAUTH_CLIENT_ID e GOOGLE_OAUTH_CLIENT_SECRET "
                "não configurados. Calendar OAuth2 não disponível."
            )
        self.logger.info("CalendarService initialized (OAuth2 per-user only)")

    async def _health_check(self) -> bool:
        return get_google_oauth().is_configured

    # ------------------------------------------------------------------
    # OAuth2 service builder
    # ------------------------------------------------------------------

    async def _get_oauth_service(self, user_id: str) -> Any:
        """
        Build a Google Calendar API service using the user's OAuth2 token.

        Raises ServiceUnavailableError if the user is not connected.
        """
        oauth = get_google_oauth()
        access_token = await oauth.get_valid_access_token(user_id)
        if not access_token:
            auth_url = oauth.get_auth_url(user_id)
            raise ServiceUnavailableError(
                "Google Calendar não conectado. "
                f"Conecta a tua conta Google:\n{auth_url}"
            )

        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(token=access_token)
        return build("calendar", "v3", credentials=creds)

    # ------------------------------------------------------------------
    # Formatting helpers (no auth needed)
    # ------------------------------------------------------------------

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

    def format_event_for_briefing(self, event: Dict[str, Any]) -> str:
        """Format a single event into a bullet-point briefing line."""
        summary = event.get("summary", "No title")
        start = event.get("start", "")
        location = event.get("location", "")

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

    # ------------------------------------------------------------------
    # Async methods — OAuth2 per-user
    # ------------------------------------------------------------------

    async def async_get_upcoming_events(
        self,
        user_id: str,
        max_results: int = 10,
        days_ahead: int = 7,
        calendar_id: str = "primary",
    ) -> List[Dict[str, Any]]:
        """Get upcoming events from the user's Google Calendar."""
        svc = await self._get_oauth_service(user_id)
        start = _time.time()
        try:
            now = datetime.now(timezone.utc)
            time_min = _utc_isoformat(now)
            time_max = _utc_isoformat(now + timedelta(days=days_ahead))

            result = (
                svc.events()
                .list(
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    maxResults=max_results,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = [self._format_event_dict(e) for e in result.get("items", [])]
            self._track_call(_time.time() - start, error=False)
            return events
        except ServiceUnavailableError:
            raise
        except Exception as exc:
            self._track_call(_time.time() - start, error=True)
            self.logger.error(
                "async_get_upcoming_events failed: %s", exc, exc_info=True
            )
            return []

    async def async_get_today_events(
        self,
        user_id: str,
        calendar_id: str = "primary",
    ) -> List[Dict[str, Any]]:
        """Get all events for today from the user's Google Calendar."""
        svc = await self._get_oauth_service(user_id)
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
                    calendarId=calendar_id,
                    timeMin=time_min,
                    timeMax=time_max,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )

            events = [self._format_event_dict(e) for e in result.get("items", [])]
            self._track_call(_time.time() - start, error=False)
            return events
        except ServiceUnavailableError:
            raise
        except Exception as exc:
            self._track_call(_time.time() - start, error=True)
            self.logger.error("async_get_today_events failed: %s", exc, exc_info=True)
            return []

    async def async_create_event(
        self,
        user_id: str,
        summary: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
        calendar_id: str = "primary",
        tz: str = "UTC",
    ) -> Optional[Dict[str, Any]]:
        """Create a new event on the user's Google Calendar."""
        svc = await self._get_oauth_service(user_id)
        call_start = _time.time()
        try:
            event_body: Dict[str, Any] = {
                "summary": summary,
                "location": location,
                "description": description,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": tz,
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": tz,
                },
            }
            if attendees:
                event_body["attendees"] = [{"email": e} for e in attendees]

            created = (
                svc.events().insert(calendarId=calendar_id, body=event_body).execute()
            )

            self._track_call(_time.time() - call_start, error=False)
            self.logger.info("Event created: %s", summary)
            return created
        except ServiceUnavailableError:
            raise
        except Exception as exc:
            self._track_call(_time.time() - call_start, error=True)
            self.logger.error("async_create_event failed: %s", exc, exc_info=True)
            return None

    async def async_create_meeting(
        self,
        user_id: str,
        summary: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        attendees: Optional[List[str]] = None,
        description: str = "",
        tz: str = "Europe/Dublin",
        calendar_id: str = "primary",
    ) -> Optional[Dict[str, Any]]:
        """Create a meeting with Google Meet link on the user's Calendar."""
        svc = await self._get_oauth_service(user_id)
        call_start = _time.time()
        try:
            event_body: Dict[str, Any] = {
                "summary": summary,
                "description": description,
                "start": {
                    "dateTime": start_time.isoformat(),
                    "timeZone": tz,
                },
                "end": {
                    "dateTime": end_time.isoformat(),
                    "timeZone": tz,
                },
                "conferenceData": {
                    "createRequest": {
                        "requestId": f"jarvis-{_time.time_ns()}",
                        "conferenceSolutionKey": {
                            "type": "hangoutsMeet",
                        },
                    }
                },
            }
            if attendees:
                event_body["attendees"] = [{"email": e} for e in attendees]

            created = (
                svc.events()
                .insert(
                    calendarId=calendar_id,
                    body=event_body,
                    conferenceDataVersion=1,
                )
                .execute()
            )

            meet_link = ""
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
        except ServiceUnavailableError:
            raise
        except Exception as exc:
            self._track_call(_time.time() - call_start, error=True)
            self.logger.error("async_create_meeting failed: %s", exc, exc_info=True)
            return None

    async def async_get_next_meeting(
        self,
        user_id: str,
        calendar_id: str = "primary",
    ) -> Optional[Dict[str, Any]]:
        """Get the next upcoming meeting (prefers events with attendees)."""
        events = await self.async_get_upcoming_events(
            user_id=user_id,
            max_results=10,
            days_ahead=7,
            calendar_id=calendar_id,
        )
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
