"""Tests for meeting orchestrator service — S9: full meeting setup."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.meeting_orchestrator_service import (
    orchestrate_meeting,
    _check_availability,
    _create_meeting_event,
    _send_invite_email,
    _create_meeting_notes,
    _humanize_conflict,
    _humanize_confirmation,
    parse_meeting_request,
    _build_invite_email,
)

FUTURE = datetime.now(timezone.utc) + timedelta(days=3)
FUTURE_END = FUTURE + timedelta(hours=1)


class TestAvailability:
    """Tests for calendar availability check."""

    @pytest.mark.asyncio
    async def test_no_calendar(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await _check_availability("u1", FUTURE, FUTURE_END)
        assert result is None  # No service, proceed optimistically

    @pytest.mark.asyncio
    async def test_no_conflict(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            {"summary": "Other meeting", "start": (FUTURE + timedelta(hours=3)).isoformat(),
             "end": (FUTURE + timedelta(hours=4)).isoformat()},
        ])

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_cal):
            result = await _check_availability("u1", FUTURE, FUTURE_END)
        assert result is None

    @pytest.mark.asyncio
    async def test_conflict_detected(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            {"summary": "Existing meeting", "start": FUTURE.isoformat(), "end": FUTURE_END.isoformat()},
        ])

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_cal):
            result = await _check_availability("u1", FUTURE, FUTURE_END)
        assert result is not None
        assert result["summary"] == "Existing meeting"


class TestCreateEvent:
    """Tests for calendar event creation."""

    @pytest.mark.asyncio
    async def test_no_calendar(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await _create_meeting_event("u1", "Test", ["a@b.com"], FUTURE, FUTURE_END, "")
        assert result is None

    @pytest.mark.asyncio
    async def test_create_success(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_create_meeting = AsyncMock(return_value={
            "id": "evt-1", "summary": "Test", "meet_link": "https://meet.google.com/abc",
            "html_link": "https://calendar.google.com/event", "start": FUTURE.isoformat(),
            "end": FUTURE_END.isoformat(), "attendees": ["a@b.com"], "status": "created",
        })

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_cal):
            result = await _create_meeting_event("u1", "Test", ["a@b.com"], FUTURE, FUTURE_END, "Agenda")
        assert result is not None
        assert result["meet_link"] == "https://meet.google.com/abc"


class TestSendInvite:
    """Tests for invite email sending."""

    @pytest.mark.asyncio
    async def test_no_gmail(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await _send_invite_email("u1", "Test", ["a@b.com"], FUTURE, FUTURE_END, "", "", "Marcos")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_success(self):
        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.send_email = AsyncMock(return_value=True)

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_gmail):
            result = await _send_invite_email(
                "u1", "Project Review", ["john@test.com"],
                FUTURE, FUTURE_END, "https://meet.google.com/abc", "Q4 review", "Marcos",
            )
        assert result is True


class TestCreateNotes:
    """Tests for meeting notes creation."""

    @pytest.mark.asyncio
    async def test_no_notes_agent(self):
        with patch("agents.core.get_agent", return_value=None):
            result = await _create_meeting_notes("u1", "Test", ["a@b.com"], FUTURE, "", "Marcos")
        assert result is False

    @pytest.mark.asyncio
    async def test_notes_created(self):
        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="Note saved"))

        with patch("agents.core.get_agent", return_value=mock_agent):
            result = await _create_meeting_notes("u1", "Project Review", ["john@test.com"], FUTURE, "Q4 review", "Marcos")
        assert result is True


class TestOrchestrateFullFlow:
    """Tests for full orchestration flow."""

    @pytest.mark.asyncio
    async def test_successful_orchestration(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[])
        mock_cal.async_create_meeting = AsyncMock(return_value={
            "id": "evt-1", "summary": "Project Review", "meet_link": "https://meet.google.com/abc",
            "start": FUTURE.isoformat(), "end": FUTURE_END.isoformat(),
            "attendees": ["john@test.com"], "status": "created",
        })

        mock_gmail = MagicMock()
        mock_gmail.is_initialized.return_value = True
        mock_gmail.send_email = AsyncMock(return_value=True)

        mock_agent = MagicMock()
        mock_agent.execute = AsyncMock(return_value=MagicMock(response="Done"))

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            if name == "gmail":
                return mock_gmail
            return None

        with (
            patch("services.business.meeting_orchestrator_service.get_service", fake_svc),
            patch("agents.core.get_agent", return_value=mock_agent),
        ):
            result = await orchestrate_meeting(
                user_id="u1", title="Project Review",
                attendees=["john@test.com"], start_time=FUTURE,
                user_name="Marcos Silva",
            )

        assert result["status"] == "success"
        assert result["event"] is not None
        assert result["invite_sent"] is True
        assert result["notes_created"] is True
        assert "Marcos" in result["confirmation"] or "Project" in result["confirmation"]

    @pytest.mark.asyncio
    async def test_conflict_stops_flow(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(return_value=[
            {"summary": "Existing", "start": FUTURE.isoformat(), "end": FUTURE_END.isoformat()},
        ])

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_cal):
            result = await orchestrate_meeting(
                user_id="u1", title="New Meeting",
                attendees=["a@b.com"], start_time=FUTURE,
                user_name="Ana",
            )

        assert result["status"] == "conflict"
        assert result["event"] is None

    @pytest.mark.asyncio
    async def test_no_services_still_confirms(self):
        """Even with no services, returns a confirmation (with errors)."""
        with (
            patch("services.business.meeting_orchestrator_service.get_service", return_value=None),
            patch("agents.core.get_agent", return_value=None),
        ):
            result = await orchestrate_meeting(
                user_id="u1", title="Test",
                attendees=["a@b.com"], start_time=FUTURE,
                user_name="Test",
            )

        assert result["confirmation"] != ""
        assert len(result["errors"]) > 0


class TestHumanization:
    """Tests for humanized responses."""

    @pytest.mark.asyncio
    async def test_conflict_fallback(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await _humanize_conflict("Marcos", "Meeting", {"summary": "Other", "start": "14:00", "end": "15:00"}, FUTURE)
        assert "Marcos" in result
        assert "Other" in result

    @pytest.mark.asyncio
    async def test_confirmation_fallback(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await _humanize_confirmation(
                "Ana", "Review", ["john@test.com"], FUTURE,
                {"meet_link": "https://meet.google.com/abc", "invite_sent": True, "notes_created": True, "errors": []},
            )
        assert "Ana" in result
        assert "📅" in result

    @pytest.mark.asyncio
    async def test_invite_email_fallback(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await _build_invite_email("Review", FUTURE, FUTURE_END, "https://meet.google.com/abc", "Q4", "Marcos")
        assert "Review" in result
        assert "meet.google.com" in result


class TestParseRequest:
    """Tests for meeting request parsing."""

    @pytest.mark.asyncio
    async def test_no_openai(self):
        with patch("services.business.meeting_orchestrator_service.get_service", return_value=None):
            result = await parse_meeting_request("marca reunião com o João")
        assert result is None

    @pytest.mark.asyncio
    async def test_parse_success(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            '{"title": "Project Review", "attendees_text": "João", '
            '"date": "2026-03-20", "time": "15:00", "duration_minutes": 60, "description": "Q4 review"}'
        )

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_openai):
            result = await parse_meeting_request("marca reunião com o João sobre projecto X sexta às 15h")
        assert result is not None
        assert result["title"] == "Project Review"

    @pytest.mark.asyncio
    async def test_parse_not_meeting(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = '{"is_meeting": false}'

        with patch("services.business.meeting_orchestrator_service.get_service", return_value=mock_openai):
            result = await parse_meeting_request("que horas são?")
        assert result is None
