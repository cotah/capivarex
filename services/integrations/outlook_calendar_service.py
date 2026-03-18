"""
Microsoft Calendar Service — reads and creates events via Microsoft Graph API.

Follows the same pattern as calendar_service.py.
Uses microsoft_oauth_service for token management.
Supports Teams meeting link generation.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from services.core import BaseService, register_service

logger = logging.getLogger(__name__)

_GRAPH_BASE = "https://graph.microsoft.com/v1.0"


@register_service("microsoft_calendar")
class MicrosoftCalendarService(BaseService):
    """Microsoft Calendar operations via Graph API."""

    def __init__(self) -> None:
        super().__init__(name="microsoft_calendar")

    async def _initialize(self) -> None:
        self.logger.info("MicrosoftCalendarService initialized")

    async def _health_check(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Internal: authenticated Graph API call
    # ------------------------------------------------------------------

    async def _api(
        self,
        user_id: str,
        method: str,
        path: str,
        json_body: Optional[Dict] = None,
        params: Optional[Dict] = None,
    ) -> Optional[Dict[str, Any]]:
        from services.auth.microsoft_oauth_service import get_microsoft_oauth

        token = await get_microsoft_oauth().get_valid_token(user_id)
        if not token:
            return None

        url = f"{_GRAPH_BASE}{path}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.request(
                method,
                url,
                headers=headers,
                json=json_body,
                params=params,
            )
            if resp.status_code == 401:
                return None
            if resp.status_code == 204:
                return {"status": "ok"}
            resp.raise_for_status()
            return resp.json()

    # ------------------------------------------------------------------
    # Read Operations
    # ------------------------------------------------------------------

    async def async_get_upcoming_events(
        self,
        user_id: str,
        max_results: int = 10,
        days_ahead: int = 7,
    ) -> List[Dict[str, Any]]:
        """Get upcoming calendar events."""
        now = datetime.now(timezone.utc)
        end = now + timedelta(days=days_ahead)

        params = {
            "$top": max_results,
            "$orderby": "start/dateTime",
            "$select": "id,subject,start,end,location,bodyPreview,attendees,webLink,isOnlineMeeting,onlineMeetingUrl",
            "$filter": (
                f"start/dateTime ge '{now.isoformat()}' and "
                f"start/dateTime le '{end.isoformat()}'"
            ),
        }

        data = await self._api(user_id, "GET", "/me/calendar/events", params=params)
        if not data:
            return []

        events = data.get("value", [])
        return [_format_event(ev) for ev in events]

    async def async_get_today_events(self, user_id: str) -> List[Dict[str, Any]]:
        """Get today's calendar events."""
        return await self.async_get_upcoming_events(
            user_id, max_results=20, days_ahead=1
        )

    async def async_get_next_meeting(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get the next upcoming meeting."""
        events = await self.async_get_upcoming_events(
            user_id, max_results=1, days_ahead=3
        )
        return events[0] if events else None

    # ------------------------------------------------------------------
    # Write Operations
    # ------------------------------------------------------------------

    async def async_create_event(
        self,
        user_id: str,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        location: str = "",
        attendees: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a calendar event."""
        event_body: Dict[str, Any] = {
            "subject": summary,
            "start": {"dateTime": start_time, "timeZone": "UTC"},
            "end": {"dateTime": end_time, "timeZone": "UTC"},
        }

        if description:
            event_body["body"] = {"contentType": "Text", "content": description}
        if location:
            event_body["location"] = {"displayName": location}
        if attendees:
            event_body["attendees"] = [
                {
                    "emailAddress": {"address": email},
                    "type": "required",
                }
                for email in attendees
            ]

        result = await self._api(
            user_id, "POST", "/me/calendar/events", json_body=event_body
        )
        if result:
            return _format_event(result)
        return None

    async def async_create_meeting(
        self,
        user_id: str,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = "",
        attendees: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Create a meeting with Teams link."""
        event_body: Dict[str, Any] = {
            "subject": summary,
            "start": {"dateTime": start_time, "timeZone": "UTC"},
            "end": {"dateTime": end_time, "timeZone": "UTC"},
            "isOnlineMeeting": True,
            "onlineMeetingProvider": "teamsForBusiness",
        }

        if description:
            event_body["body"] = {"contentType": "Text", "content": description}
        if attendees:
            event_body["attendees"] = [
                {
                    "emailAddress": {"address": email},
                    "type": "required",
                }
                for email in attendees
            ]

        result = await self._api(
            user_id, "POST", "/me/calendar/events", json_body=event_body
        )
        if result:
            formatted = _format_event(result)
            formatted["teams_link"] = result.get("onlineMeetingUrl", "")
            return formatted
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_event(ev: Dict[str, Any]) -> Dict[str, Any]:
    """Format a Microsoft Graph event to match our standard format."""
    start = ev.get("start", {})
    end = ev.get("end", {})
    attendees = ev.get("attendees", [])
    location = ev.get("location", {})

    return {
        "id": ev.get("id", ""),
        "summary": ev.get("subject", ""),
        "start": start.get("dateTime", ""),
        "end": end.get("dateTime", ""),
        "location": location.get("displayName", "")
        if isinstance(location, dict)
        else "",
        "description": ev.get("bodyPreview", ""),
        "attendees": [a.get("emailAddress", {}).get("address", "") for a in attendees],
        "html_link": ev.get("webLink", ""),
        "status": "confirmed",
        "provider": "microsoft",
        "is_online": ev.get("isOnlineMeeting", False),
        "meeting_url": ev.get("onlineMeetingUrl", ""),
    }
