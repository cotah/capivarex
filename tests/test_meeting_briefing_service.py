"""Tests for meeting briefing service."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.meeting_briefing_service import (
    check_upcoming_meetings,
    _generate_meeting_briefing,
)


class TestMeetingBriefing:
    """Tests for meeting briefing generation."""

    @pytest.mark.asyncio
    async def test_generate_briefing_basic(self):
        """Test briefing generation for a meeting."""
        event = {
            "summary": "Team standup",
            "start": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "location": "Meeting Room 3",
            "attendees": [{"email": "john@test.com"}, {"email": "ana@test.com"}],
            "description": "Weekly sync on project status",
        }

        with patch("services.business.meeting_briefing_service.get_service", return_value=None):
            result = await _generate_meeting_briefing("user-123", event, 2.0)

        assert result is not None
        assert "Team standup" in result["message"]
        assert "2h" in result["message"]

    @pytest.mark.asyncio
    async def test_generate_briefing_no_location(self):
        """Test briefing without location."""
        event = {
            "summary": "Quick call",
            "start": (datetime.now(timezone.utc) + timedelta(hours=1.5)).isoformat(),
        }

        with patch("services.business.meeting_briefing_service.get_service", return_value=None):
            result = await _generate_meeting_briefing("user-123", event, 1.5)

        assert result is not None
        assert "Quick call" in result["message"]

    @pytest.mark.asyncio
    async def test_check_upcoming_no_calendar(self):
        """Test with no calendar service."""
        with patch("services.business.meeting_briefing_service.get_service", return_value=None):
            result = await check_upcoming_meetings("user-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_check_upcoming_no_events(self):
        """Test with empty calendar."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_today_events = AsyncMock(return_value=[])

        with patch("services.business.meeting_briefing_service.get_service", return_value=mock_cal):
            result = await check_upcoming_meetings("user-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_check_upcoming_meeting_in_window(self):
        """Test detection of meeting within 2h window."""
        meeting_time = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_today_events = AsyncMock(return_value=[
            {
                "id": "evt-123",
                "summary": "Client call",
                "start": meeting_time.isoformat(),
            },
        ])

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(data=[])
        # For insert
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock(data=[])

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            if name == "database":
                return mock_db
            return None

        with patch("services.business.meeting_briefing_service.get_service", fake_svc):
            result = await check_upcoming_meetings("user-123")

        assert len(result) == 1
        assert "Client call" in result[0]["message"]

    @pytest.mark.asyncio
    async def test_meeting_too_far_away(self):
        """Test that meetings >2.5h away don't trigger briefing."""
        meeting_time = datetime.now(timezone.utc) + timedelta(hours=5)
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_today_events = AsyncMock(return_value=[
            {"summary": "Later meeting", "start": meeting_time.isoformat()},
        ])

        with patch("services.business.meeting_briefing_service.get_service", return_value=mock_cal):
            result = await check_upcoming_meetings("user-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_briefing_with_rag_context(self):
        """Test briefing works when RAG context is available."""
        event = {
            "summary": "Budget review",
            "start": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "attendees": [{"email": "cfo@company.com"}],
        }

        mock_rag = MagicMock()
        mock_rag.is_initialized.return_value = True
        mock_rag.search = AsyncMock(return_value=[
            {"content": "Last budget meeting: agreed to cut Q3 spending by 10%"},
        ])

        def fake_svc(name):
            return mock_rag if name == "rag" else None

        with patch("services.business.meeting_briefing_service.get_service", fake_svc):
            result = await _generate_meeting_briefing("user-123", event, 2.0)

        assert result is not None
        assert "Budget review" in result["message"]


class TestMeetingBriefingEdgeCases:
    """Edge case tests for meeting briefing."""

    @pytest.mark.asyncio
    async def test_all_day_event_skipped(self):
        """All-day events (no time) are skipped."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_today_events = AsyncMock(return_value=[
            {"summary": "Holiday", "start": "2026-03-16"},  # No T = all-day
        ])

        with patch("services.business.meeting_briefing_service.get_service", return_value=mock_cal):
            result = await check_upcoming_meetings("user-123")
        assert result == []

    @pytest.mark.asyncio
    async def test_meeting_already_briefed(self):
        """Meeting that was already briefed is skipped."""
        meeting_time = datetime.now(timezone.utc) + timedelta(hours=2)
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_today_events = AsyncMock(return_value=[
            {"id": "evt-456", "summary": "Repeat meeting", "start": meeting_time.isoformat()},
        ])

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        # Return existing briefing
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "metadata": '{"event_id": "evt-456"}'}]
        )

        def fake_svc(name):
            if name == "calendar":
                return mock_cal
            if name == "database":
                return mock_db
            return None

        with patch("services.business.meeting_briefing_service.get_service", fake_svc):
            result = await check_upcoming_meetings("user-123")
        assert result == []


class TestMeetingBriefingHelpers:
    """Tests for meeting briefing helper functions."""

    @pytest.mark.asyncio
    async def test_briefing_sent_no_db(self):
        from services.business.meeting_briefing_service import _briefing_sent_for_event
        with patch("services.business.meeting_briefing_service.get_service", return_value=None):
            result = await _briefing_sent_for_event("u1", "evt-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_store_briefing_no_db(self):
        from services.business.meeting_briefing_service import _store_briefing
        with patch("services.business.meeting_briefing_service.get_service", return_value=None):
            await _store_briefing("u1", "evt-1", {"title": "t", "message": "m"})

    @pytest.mark.asyncio
    async def test_get_context_no_rag(self):
        from services.business.meeting_briefing_service import _get_meeting_context
        with patch("services.business.meeting_briefing_service.get_service", return_value=None):
            result = await _get_meeting_context("u1", "Budget review", [])
        assert result is None
