"""
Shared fixtures for tests — aligned with refactored BaseAgent/BaseService architecture.
"""
from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI async client with chat completions."""
    client = Mock()
    client.chat = Mock()
    client.chat.completions = Mock()

    async def mock_create(*args, **kwargs):
        response = Mock()
        response.choices = [Mock()]
        response.choices[0].message = Mock()
        response.choices[0].message.content = (
            '{"title": "Test Event", "start_datetime": "2026-02-15T15:00:00", '
            '"end_datetime": "2026-02-15T16:00:00", "location": "Cork", "description": ""}'
        )
        return response

    client.chat.completions.create = mock_create
    return client


@pytest.fixture
def mock_calendar_service():
    """Mock calendar service (CalendarService)."""
    service = Mock()
    service._service = Mock()  # underlying Google API service object
    service.authenticate = Mock(return_value=True)
    service._initialized = True

    service.create_event = Mock(
        return_value={
            "id": "test_event_123",
            "summary": "Test Event",
            "start": {"dateTime": "2026-02-15T15:00:00"},
            "end": {"dateTime": "2026-02-15T16:00:00"},
            "location": "Cork",
        }
    )

    service.get_upcoming_events = Mock(
        return_value=[
            {
                "id": "event_1",
                "summary": "Meeting",
                "start": "2026-02-15T15:00:00+00:00",
                "end": "2026-02-15T16:00:00+00:00",
                "location": "Cork, Ireland",
                "description": "",
                "attendees": [],
            }
        ]
    )
    service.get_next_meeting = Mock(
        return_value={
            "id": "event_1",
            "summary": "Meeting",
            "start": "2026-02-15T15:00:00+00:00",
            "location": "Cork, Ireland",
        }
    )
    service.get_today_events = Mock(return_value=[])
    service.generate_calendar_briefing = Mock(return_value="📅 **Calendar Briefing**")
    service.format_event_for_briefing = Mock(
        side_effect=lambda e: f"• {e.get('summary', 'No title')}"
    )

    return service


@pytest.fixture
def mock_traffic_service():
    """Mock traffic service object."""
    svc = Mock()
    svc.get_route_with_traffic = AsyncMock(
        return_value={
            "success": True,
            "route": {"duration_minutes": 30, "distance_km": 12.5},
            "traffic": {"level": "moderate"},
        }
    )
    svc.get_traffic_summary = AsyncMock(return_value="Resumo de tráfego")
    svc.check_traffic_before_event = AsyncMock(
        return_value={
            "success": True,
            "message": "⏰ Prepare-se! Saia em 25 minutos.",
            "travel_time_minutes": 30,
            "distance_km": 12.5,
            "suggested_departure": "2026-02-15T14:15:00",
            "event_time": "2026-02-15T15:00:00",
            "urgency": "BREVE",
        }
    )
    return svc


@pytest.fixture
def sample_event_params():
    """Sample event parameters for testing."""
    return {
        "title": "Test Meeting",
        "start_datetime": "2026-02-15T15:00:00",
        "end_datetime": "2026-02-15T16:00:00",
        "location": "Cork",
        "description": "Test description",
    }


@pytest.fixture
def sample_context():
    """Sample context for testing."""
    return {
        "user_id": "test_user_123",
        "tenant_id": "default",
        "channel": "websocket",
        "user_location": "Dublin",
    }
