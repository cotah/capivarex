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
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)

# Scopes required for calendar access
SCOPES = ["https://www.googleapis.com/auth/calendar"]


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

        self.service_account_file = os.getenv(
            "GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json"
        )
        self.calendar_id = os.getenv("GOOGLE_CALENDAR_ID", "primary")

        if not os.path.exists(self.service_account_file):
            raise ServiceUnavailableError(
                f"Service account file '{self.service_account_file}' not found. "
                "Set GOOGLE_SERVICE_ACCOUNT_FILE to the correct path."
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
            raise ServiceUnavailableError(
                f"Calendar initialisation failed: {exc}"
            )

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
                raise RuntimeError("Calendar service not initialised and authentication failed")

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
            "attendees": [
                att.get("email") for att in event.get("attendees", [])
            ],
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
                time_min = datetime.utcnow()
            if time_max is None:
                time_max = time_min + timedelta(days=days_ahead)

            time_min_str = (
                time_min.isoformat() + "Z"
                if isinstance(time_min, datetime)
                else time_min
            )
            time_max_str = (
                time_max.isoformat() + "Z"
                if isinstance(time_max, datetime)
                else time_max
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
            now = datetime.utcnow()
            start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)

            time_min = start_of_day.isoformat() + "Z"
            time_max = end_of_day.isoformat() + "Z"

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
                    "start": start_time.isoformat() if isinstance(start_time, datetime) else str(start_time),
                    "end": end_time.isoformat() if isinstance(end_time, datetime) else str(end_time),
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
                event["attendees"] = [
                    {"email": email} for email in kwargs["attendees"]
                ]

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
            self._service.events().delete(
                calendarId=cal_id, eventId=event_id
            ).execute()

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
            now = datetime.utcnow()
            time_min = now.isoformat() + "Z"

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

    def generate_calendar_briefing(
        self, calendar_id: Optional[str] = None
    ) -> str:
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
            tomorrow = datetime.utcnow() + timedelta(days=1)
            tomorrow_start = tomorrow.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            tomorrow_end = tomorrow.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            time_min = tomorrow_start.isoformat() + "Z"
            time_max = tomorrow_end.isoformat() + "Z"

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
                self._format_event_dict(ev)
                for ev in events_result.get("items", [])
            ]

            # -- Build the briefing text --
            briefing = "**Calendar Briefing**\n\n"

            if today_events:
                briefing += f"**Today ({datetime.utcnow().strftime('%B %d')}):**\n"
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
            tomorrow = datetime.utcnow() + timedelta(days=1)
            tomorrow_start = tomorrow.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            tomorrow_end = tomorrow.replace(
                hour=23, minute=59, second=59, microsecond=999999
            )

            time_min = tomorrow_start.isoformat() + "Z"
            time_max = tomorrow_end.isoformat() + "Z"

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
                self._format_event_dict(ev)
                for ev in events_result.get("items", [])
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
