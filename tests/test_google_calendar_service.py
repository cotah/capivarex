"""
Tests for CalendarService (OAuth2-only architecture).

The refactored CalendarService uses GoogleOAuthService for all API calls.
No Service Account fallback — all methods are async and require user_id.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from services.integrations.calendar_service import CalendarService, get_calendar_service


def _build_svc():
    """Create a CalendarService without hitting Google APIs."""
    svc = CalendarService()
    svc._initialized = True
    return svc


# ── format_event_for_briefing ───────────────────────────────────────────────


@pytest.mark.unit
def test_format_event_for_briefing_formats_time_and_location():
    """Test format_event_for_briefing formats datetime and location."""
    svc = _build_svc()
    event = {
        "summary": "Team Standup",
        "start": "2026-02-15T10:00:00",
        "location": "Office",
    }

    formatted = svc.format_event_for_briefing(event)

    assert "Team Standup" in formatted
    assert "10:00" in formatted
    assert "(Office)" in formatted


@pytest.mark.unit
def test_format_event_for_briefing_all_day():
    """Test format_event_for_briefing handles all-day events."""
    svc = _build_svc()

    formatted = svc.format_event_for_briefing(
        {"summary": "Holiday", "start": "2026-02-15"}
    )

    assert formatted == "* Holiday at All day"


# ── async_get_upcoming_events ──────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_get_upcoming_events_returns_formatted_list():
    """Test async_get_upcoming_events formats API events."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "1",
                "summary": "Meeting",
                "start": {"dateTime": "2026-02-15T15:00:00"},
                "end": {"dateTime": "2026-02-15T16:00:00"},
                "location": "Cork",
                "description": "Desc",
                "attendees": [{"email": "a@test.com"}],
            }
        ]
    }

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_get_upcoming_events(user_id="test_user", max_results=5)

    assert len(result) == 1
    assert result[0]["summary"] == "Meeting"
    assert result[0]["attendees"] == ["a@test.com"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_get_upcoming_events_empty():
    """Test async_get_upcoming_events returns [] when no items."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.list.return_value.execute.return_value = {"items": []}

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_get_upcoming_events(user_id="test_user")

    assert result == []


# ── async_get_next_meeting ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_get_next_meeting_prefers_event_with_attendees():
    """Test async_get_next_meeting prefers first event with attendees."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "1",
                "summary": "No Attendees",
                "start": {"dateTime": "2026-02-15T10:00:00"},
                "end": {"dateTime": "2026-02-15T11:00:00"},
            },
            {
                "id": "2",
                "summary": "With Attendees",
                "start": {"dateTime": "2026-02-15T12:00:00"},
                "end": {"dateTime": "2026-02-15T13:00:00"},
                "attendees": [{"email": "a@test.com"}],
            },
        ]
    }

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_get_next_meeting(user_id="test_user")

    assert result is not None
    assert result["id"] == "2"
    assert result["attendees"] == ["a@test.com"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_get_next_meeting_returns_first_when_no_attendees():
    """Test async_get_next_meeting falls back to first event when no attendees."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "1",
                "summary": "General Event",
                "start": {"dateTime": "2026-02-15T10:00:00"},
                "end": {"dateTime": "2026-02-15T11:00:00"},
            }
        ]
    }

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_get_next_meeting(user_id="test_user")

    assert result is not None
    assert result["id"] == "1"
    assert result["attendees"] == []


# ── async_get_today_events ─────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_get_today_events_success():
    """Test async_get_today_events formats events list."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.list.return_value.execute.return_value = {
        "items": [
            {
                "id": "today_1",
                "summary": "Today Event",
                "start": {"dateTime": "2026-02-15T10:00:00"},
                "end": {"dateTime": "2026-02-15T11:00:00"},
                "location": "Office",
            }
        ]
    }

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_get_today_events(user_id="test_user")

    assert len(result) == 1
    assert result[0]["summary"] == "Today Event"


# ── async_create_event ─────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_create_event_success():
    """Test async_create_event sends event body and returns created event."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.insert.return_value.execute.return_value = {
        "id": "created_1",
        "htmlLink": "http://x",
    }

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_create_event(
            user_id="test_user",
            summary="Meeting",
            start_time=datetime(2026, 2, 15, 10, 0, 0),
            end_time=datetime(2026, 2, 15, 11, 0, 0),
            location="Cork",
            description="Desc",
            attendees=["a@test.com"],
        )

    assert result["id"] == "created_1"
    body = events_resource.insert.call_args.kwargs["body"]
    assert body["summary"] == "Meeting"
    assert body["attendees"] == [{"email": "a@test.com"}]


# ── async_create_meeting ───────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_async_create_meeting_includes_conference_data():
    """Test async_create_meeting sets conferenceData for Google Meet."""
    svc = _build_svc()

    mock_service = Mock()
    events_resource = Mock()
    mock_service.events.return_value = events_resource
    events_resource.insert.return_value.execute.return_value = {
        "id": "meet_1",
        "htmlLink": "http://x",
        "conferenceData": {
            "entryPoints": [
                {
                    "entryPointType": "video",
                    "uri": "https://meet.google.com/abc-def-ghi",
                }
            ]
        },
    }

    with patch.object(svc, "_get_oauth_service", new=AsyncMock(return_value=mock_service)):
        result = await svc.async_create_meeting(
            user_id="test_user",
            summary="Meet",
            start_time=datetime(2026, 2, 15, 10, 0, 0),
            end_time=datetime(2026, 2, 15, 11, 0, 0),
        )

    assert result is not None
    assert result["meet_link"] == "https://meet.google.com/abc-def-ghi"
    body = events_resource.insert.call_args.kwargs["body"]
    assert "conferenceData" in body


# ── ServiceUnavailableError when not connected ─────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_not_connected_raises_service_unavailable():
    """Test that methods raise ServiceUnavailableError when user is not connected."""
    from services.core import ServiceUnavailableError

    svc = _build_svc()

    mock_oauth = Mock()
    mock_oauth.is_configured = True
    mock_oauth.get_valid_access_token = AsyncMock(return_value=None)
    mock_oauth.get_auth_url = Mock(return_value="http://example.com/auth")

    with (
        patch(
            "services.integrations.calendar_service.get_google_oauth",
            return_value=mock_oauth,
        ),
        pytest.raises(ServiceUnavailableError),
    ):
        await svc.async_get_upcoming_events(user_id="disconnected_user")


# ── Singleton accessor ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_calendar_service_returns_singleton(monkeypatch):
    """Test get_calendar_service memoizes instance."""
    import services.integrations.calendar_service as module
    import services.core as core_module

    # Reset cached singleton
    module._calendar_service = None

    dummy = CalendarService()
    monkeypatch.setattr(core_module, "get_service", lambda name: dummy)

    first = get_calendar_service()
    second = get_calendar_service()

    assert first is second
