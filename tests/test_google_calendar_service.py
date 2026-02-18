"""
Tests for CalendarService (refactored architecture).

The refactored CalendarService inherits from BaseService.  Constructor
signature: ``CalendarService(name="calendar", config=None)``.
The underlying Google API service lives at ``svc._service``.
Most public method signatures are unchanged.
"""
from datetime import datetime, timedelta
from unittest.mock import Mock

import pytest

from services.integrations.calendar_service import CalendarService, get_calendar_service


def _build_svc():
    """Create a CalendarService without hitting Google APIs."""
    svc = CalendarService()
    svc.calendar_id = "test"
    return svc


def _build_events_api(items):
    """Build a mocked Google Calendar API service for events().list().execute()."""
    service = Mock()
    events_resource = Mock()
    service.events.return_value = events_resource
    events_resource.list.return_value.execute.return_value = {"items": items}
    return service, events_resource


# ── get_upcoming_events ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_upcoming_events_returns_formatted_list():
    """Test get_upcoming_events formats API events."""
    svc = _build_svc()
    svc._service, events_resource = _build_events_api(
        [
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
    )

    result = svc.get_upcoming_events(max_results=5)

    assert len(result) == 1
    assert result[0]["summary"] == "Meeting"
    assert result[0]["attendees"] == ["a@test.com"]
    events_resource.list.assert_called_once()


@pytest.mark.unit
def test_get_upcoming_events_accepts_time_range_datetime():
    """Test get_upcoming_events handles explicit datetime range."""
    svc = _build_svc()
    svc._service, events_resource = _build_events_api([])
    start = datetime(2026, 2, 15, 10, 0, 0)
    end = start + timedelta(days=1)

    svc.get_upcoming_events(time_min=start, time_max=end, max_results=50)

    kwargs = events_resource.list.call_args.kwargs
    assert kwargs["timeMin"].startswith("2026-02-15T10:00:00")
    assert kwargs["timeMax"].startswith("2026-02-16T10:00:00")
    assert kwargs["maxResults"] == 50


# ── get_next_meeting ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_next_meeting_prefers_event_with_attendees():
    """Test get_next_meeting prefers first event with attendees."""
    svc = _build_svc()
    svc._service, _ = _build_events_api(
        [
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
    )

    result = svc.get_next_meeting()

    assert result is not None
    assert result["id"] == "2"
    assert result["attendees"] == ["a@test.com"]


@pytest.mark.unit
def test_get_next_meeting_returns_first_event_when_no_attendees():
    """Test get_next_meeting falls back to first event when no attendees exist."""
    svc = _build_svc()
    svc._service, _ = _build_events_api(
        [
            {
                "id": "1",
                "summary": "General Event",
                "start": {"dateTime": "2026-02-15T10:00:00"},
                "end": {"dateTime": "2026-02-15T11:00:00"},
            }
        ]
    )

    result = svc.get_next_meeting()

    assert result is not None
    assert result["id"] == "1"
    assert result["attendees"] == []


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


# ── generate_calendar_briefing ──────────────────────────────────────────────


@pytest.mark.unit
def test_generate_calendar_briefing_includes_today_and_tomorrow(monkeypatch):
    """Test generate_calendar_briefing builds two sections."""
    svc = _build_svc()
    svc.get_today_events = Mock(
        return_value=[
            {
                "summary": "Today Event",
                "start": "2026-02-15T09:00:00",
                "location": "",
            }
        ]
    )
    svc._service, _ = _build_events_api(
        [
            {
                "id": "2",
                "summary": "Tomorrow Event",
                "start": {"dateTime": "2026-02-16T14:00:00"},
                "end": {"dateTime": "2026-02-16T15:00:00"},
            }
        ]
    )

    briefing = svc.generate_calendar_briefing()

    assert "Calendar Briefing" in briefing
    assert "Today" in briefing
    assert "Tomorrow" in briefing


@pytest.mark.unit
def test_generate_calendar_briefing_no_events():
    """Test generate_calendar_briefing handles empty today and tomorrow."""
    svc = _build_svc()
    svc.get_today_events = Mock(return_value=[])
    svc._service, _ = _build_events_api([])

    briefing = svc.generate_calendar_briefing()

    assert "**Today:** No events scheduled." in briefing
    assert "**Tomorrow:** No events scheduled." in briefing


# ── get_morning_briefing_events ─────────────────────────────────────────────


@pytest.mark.unit
def test_get_morning_briefing_events_combines_today_and_tomorrow():
    """Test get_morning_briefing_events combines both lists."""
    svc = _build_svc()
    svc.get_today_events = Mock(
        return_value=[
            {"id": "today_1", "summary": "Today Event", "start": "2026-02-15T09:00:00"}
        ]
    )
    svc._service, _ = _build_events_api(
        [
            {
                "id": "tmr_1",
                "summary": "Tomorrow Event",
                "start": {"dateTime": "2026-02-16T10:00:00"},
                "end": {"dateTime": "2026-02-16T11:00:00"},
            }
        ]
    )

    events = svc.get_morning_briefing_events()

    assert len(events) == 2
    assert events[0]["id"] == "today_1"
    assert events[1]["id"] == "tmr_1"


# ── authenticate ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_authenticate_returns_false_when_service_account_missing(tmp_path):
    """Test authenticate fails when service account file does not exist."""
    missing_file = tmp_path / "missing_service_account.json"
    svc = _build_svc()
    svc.service_account_file = str(missing_file)

    result = svc.authenticate()

    assert result is False


# ── get_today_events ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_today_events_success():
    """Test get_today_events formats events list."""
    svc = _build_svc()
    svc._service, _ = _build_events_api(
        [
            {
                "id": "today_1",
                "summary": "Today Event",
                "start": {"dateTime": "2026-02-15T10:00:00"},
                "end": {"dateTime": "2026-02-15T11:00:00"},
                "location": "Office",
            }
        ]
    )

    result = svc.get_today_events()

    assert len(result) == 1
    assert result[0]["summary"] == "Today Event"


# ── Event CRUD ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_create_event_success_with_attendees():
    """Test create_event sends attendees and returns created event."""
    svc = _build_svc()
    service = Mock()
    events_resource = Mock()
    service.events.return_value = events_resource
    events_resource.insert.return_value.execute.return_value = {
        "id": "created_1",
        "htmlLink": "http://x",
    }
    svc._service = service

    result = svc.create_event(
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


@pytest.mark.unit
def test_update_event_success_updates_fields():
    """Test update_event fetches and updates event payload."""
    svc = _build_svc()
    service = Mock()
    events_resource = Mock()
    service.events.return_value = events_resource
    events_resource.get.return_value.execute.return_value = {
        "id": "e1",
        "summary": "Old",
    }
    events_resource.update.return_value.execute.return_value = {
        "id": "e1",
        "summary": "New",
        "htmlLink": "http://x",
    }
    svc._service = service

    result = svc.update_event(
        "e1",
        summary="New",
        location="Office",
        start_time=datetime(2026, 2, 15, 9, 0, 0),
        end_time=datetime(2026, 2, 15, 10, 0, 0),
    )

    assert result["summary"] == "New"
    body = events_resource.update.call_args.kwargs["body"]
    assert body["summary"] == "New"
    assert body["location"] == "Office"


@pytest.mark.unit
def test_delete_event_success():
    """Test delete_event returns True on successful delete."""
    svc = _build_svc()
    service = Mock()
    events_resource = Mock()
    service.events.return_value = events_resource
    events_resource.delete.return_value.execute.return_value = {}
    svc._service = service

    result = svc.delete_event("event_1")

    assert result is True
    events_resource.delete.assert_called_once()


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
