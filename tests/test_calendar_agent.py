"""
Tests for CalendarAgent — refactored architecture.

The refactored CalendarAgent uses ``_get_calendar_service()`` to obtain the
calendar service wrapper (via ``get_service("calendar")``).  Tests inject the
mock calendar service directly on ``agent._calendar_service``.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch

import pytest

from agents.core import AgentStatus, AgentResponse
from agents.specialized.calendar_agent import CalendarAgent


def _build_agent(mock_calendar_service):
    """Create CalendarAgent with mocked calendar service injected."""
    agent = CalendarAgent()
    agent._calendar_service = mock_calendar_service
    return agent


# ── Event Creation ──────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_event_success(
    mock_calendar_service, sample_event_params, sample_context
):
    """Test successful event creation."""
    agent = _build_agent(mock_calendar_service)
    context = {
        **sample_context,
        "action": "create_event",
        "event_params": sample_event_params,
    }

    result = await agent.execute("Create event", context)

    assert result.is_success()
    assert "Evento criado com sucesso" in result.response
    assert "event" in result.data
    mock_calendar_service.async_create_event.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_event_missing_title(mock_calendar_service, sample_context):
    """Test event creation with missing title."""
    agent = _build_agent(mock_calendar_service)
    context = {
        **sample_context,
        "action": "create_event",
        "event_params": {"start_datetime": "2026-02-15T15:00:00"},
    }

    result = await agent.execute("Create event", context)

    assert result.status == AgentStatus.ERROR
    assert (
        "tulo" in result.response.lower()
        or "title" in result.response.lower()
    )
    mock_calendar_service.async_create_event.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_event_missing_datetime(mock_calendar_service, sample_context):
    """Test event creation with missing datetime."""
    agent = _build_agent(mock_calendar_service)
    context = {
        **sample_context,
        "action": "create_event",
        "event_params": {"title": "Test Event"},
    }

    result = await agent.execute("Create event", context)

    assert result.status == AgentStatus.ERROR
    assert "data e hora" in result.response.lower()
    mock_calendar_service.async_create_event.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_event_default_end_time(mock_calendar_service, sample_context):
    """Test event creation uses default +1h when end_datetime is missing."""
    agent = _build_agent(mock_calendar_service)
    context = {
        **sample_context,
        "action": "create_event",
        "event_params": {
            "title": "Test Event",
            "start_datetime": "2026-02-15T15:00:00",
            "location": "Cork",
        },
    }

    result = await agent.execute("Create event", context)

    assert result.is_success()
    kwargs = mock_calendar_service.async_create_event.call_args.kwargs
    assert kwargs["end_time"] - kwargs["start_time"] == timedelta(hours=1)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_event_invalid_datetime(mock_calendar_service, sample_context):
    """Test create event returns validation error for invalid datetime."""
    agent = _build_agent(mock_calendar_service)
    context = {
        **sample_context,
        "action": "create_event",
        "event_params": {
            "title": "Bad Event",
            "start_datetime": "not-a-date",
        },
    }

    result = await agent.execute("Create event", context)

    assert result.status == AgentStatus.ERROR
    assert "Erro ao processar data e hora" in result.response
    mock_calendar_service.async_create_event.assert_not_called()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_create_event_calendar_service_returns_none(
    mock_calendar_service, sample_context
):
    """Test create event handles calendar service failure."""
    mock_calendar_service.async_create_event.return_value = None
    agent = _build_agent(mock_calendar_service)
    context = {
        **sample_context,
        "action": "create_event",
        "event_params": {
            "title": "Event",
            "start_datetime": "2026-02-15T15:00:00",
        },
    }

    result = await agent.execute("Create event", context)

    assert result.status == AgentStatus.ERROR
    assert (
        "criar o evento" in result.response.lower()
        or "create the event" in result.response.lower()
    )


# ── Query Routing ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_unavailable_error_returns_connect_message(sample_context):
    """Test that ServiceUnavailableError returns connect message."""
    from services.core import ServiceUnavailableError

    mock_svc = Mock()
    mock_svc.async_get_today_events = AsyncMock(
        side_effect=ServiceUnavailableError(
            "Google Calendar não conectado. "
            "Conecta a tua conta: http://localhost:8000/api/auth/google/connect?user_id=test"
        )
    )
    agent = _build_agent(mock_svc)

    result = await agent.execute("What's on my calendar today?", sample_context)

    assert result.status == AgentStatus.ERROR
    assert "conecta" in result.response.lower() or "connect" in result.response.lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_next_meeting_no_results(mock_calendar_service, sample_context):
    """Test next meeting response when no meetings are found."""
    mock_calendar_service.async_get_next_meeting.return_value = None
    agent = _build_agent(mock_calendar_service)

    result = await agent.execute("next meeting", sample_context)

    assert result.is_success()
    assert (
        "reuni" in result.response.lower()
        or "meeting" in result.response.lower()
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_today_events_with_items(mock_calendar_service, sample_context):
    """Test today events formatting path."""
    mock_calendar_service.async_get_today_events.return_value = [
        {"summary": "Daily", "start": "2026-02-15T09:00:00"}
    ]
    mock_calendar_service.format_event_for_briefing.side_effect = lambda e: (
        "• Daily at 09:00"
    )
    agent = _build_agent(mock_calendar_service)

    result = await agent.execute("today", sample_context)

    assert result.is_success()
    assert "evento(s) hoje" in result.response
    assert "• Daily at 09:00" in result.response


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_week_events_routes_with_time_range(
    mock_calendar_service, sample_context
):
    """Test weekly query calls async_get_upcoming_events with time range."""
    mock_calendar_service.async_get_upcoming_events.return_value = []
    agent = _build_agent(mock_calendar_service)

    result = await agent.execute("this week", sample_context)

    assert result.is_success()
    kwargs = mock_calendar_service.async_get_upcoming_events.call_args.kwargs
    assert kwargs["max_results"] == 50
    assert kwargs["days_ahead"] == 7


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_briefing_path(mock_calendar_service, sample_context):
    """Test briefing path returns calendar briefing text built from today events."""
    mock_calendar_service.async_get_today_events.return_value = [
        {"summary": "Standup", "start": "2026-02-15T09:00:00"}
    ]
    mock_calendar_service.format_event_for_briefing.side_effect = lambda e: (
        f"* {e.get('summary', 'No title')} at 09:00"
    )
    agent = _build_agent(mock_calendar_service)

    result = await agent.execute("briefing", sample_context)

    assert result.is_success()
    assert "Briefing" in result.response
    assert "Standup" in result.response


# ── Traffic Check ───────────────────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traffic_check_success(mock_calendar_service):
    """Test traffic check for next event reaches traffic agent."""
    from datetime import datetime, timedelta

    # Use a date that is guaranteed to be in the future
    future_dt = datetime.now() + timedelta(days=1)
    future_iso = future_dt.isoformat()

    mock_calendar_service.async_get_upcoming_events = AsyncMock(
        return_value=[
            {
                "id": "event_future",
                "summary": "Future Meeting",
                "start": future_iso,
                "end": (future_dt + timedelta(hours=1)).isoformat(),
                "location": "Cork, Ireland",
                "description": "",
                "attendees": [],
            }
        ]
    )

    mock_traffic_agent = AsyncMock()
    mock_traffic_agent.execute = AsyncMock(
        return_value=AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Trafego moderado",
            data={"travel_time": 30},
        )
    )

    agent = _build_agent(mock_calendar_service)

    with patch("agents.core.get_agent", return_value=mock_traffic_agent):
        result = await agent.execute(
            "traffic", {"user_location": "Dublin", "user_id": "test_user", "lang": "pt"}
        )

    assert result.is_success()
    assert (
        "Alerta de Tr" in result.response
        or "Traffic Alert" in result.response
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_traffic_check_no_events(mock_calendar_service):
    """Test traffic check returns error when there are no events."""
    mock_calendar_service.async_get_upcoming_events = AsyncMock(return_value=[])
    agent = _build_agent(mock_calendar_service)

    result = await agent.execute(
        "traffic", {"user_location": "Dublin", "user_id": "test_user", "lang": "pt"}
    )

    assert result.status == AgentStatus.ERROR
    assert (
        "eventos" in result.response.lower()
        or "no events" in result.response.lower()
        or "no upcoming" in result.response.lower()
    )


# ── Calendar Service Unavailable ────────────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_unavailable():
    """Test execute returns error when calendar service is not available."""
    agent = CalendarAgent()
    agent._calendar_service = None

    with patch("agents.specialized.calendar_agent.get_service", return_value=None):
        result = await agent.execute("today", {"lang": "pt"})

    assert result.status == AgentStatus.ERROR
    assert (
        "unavailable" in result.response.lower()
        or "calendario" in result.response.lower()
    )
