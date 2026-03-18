"""Tests for agenda conflict detection service — A5."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.agenda_conflict_service import (
    detect_conflicts,
    _parse_events,
    _check_pair,
    generate_conflict_alert,
    check_conflicts_for_all_users,
)


def _make_event(summary, start_hours=0, duration_hours=1, location=""):
    """Create a test calendar event starting N hours from now."""
    start = datetime.now(timezone.utc) + timedelta(hours=start_hours)
    end = start + timedelta(hours=duration_hours)
    return {
        "id": f"evt_{summary[:10]}",
        "summary": summary,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": location,
    }


class TestParseEvents:
    """Tests for event parsing."""

    def test_parse_timed_events(self):
        events = [
            _make_event("Meeting A", start_hours=1),
            _make_event("Meeting B", start_hours=3),
        ]
        parsed = _parse_events(events)
        assert len(parsed) == 2
        assert parsed[0]["summary"] == "Meeting A"

    def test_skip_all_day_events(self):
        events = [
            {
                "id": "1",
                "summary": "Holiday",
                "start": "2026-03-20",
                "end": "2026-03-21",
            },
            _make_event("Meeting", start_hours=1),
        ]
        parsed = _parse_events(events)
        assert len(parsed) == 1
        assert parsed[0]["summary"] == "Meeting"

    def test_skip_invalid_dates(self):
        events = [
            {"id": "1", "summary": "Bad", "start": "invalid", "end": "invalid"},
        ]
        parsed = _parse_events(events)
        assert len(parsed) == 0


class TestCheckPair:
    """Tests for conflict detection between two events."""

    def test_overlapping_events(self):
        now = datetime.now(timezone.utc)
        ev_a = {
            "id": "1",
            "summary": "Meeting A",
            "location": "",
            "start_dt": now,
            "end_dt": now + timedelta(hours=1),
            "start_str": "Mon 14:00",
            "end_str": "15:00",
        }
        ev_b = {
            "id": "2",
            "summary": "Meeting B",
            "location": "",
            "start_dt": now + timedelta(minutes=30),
            "end_dt": now + timedelta(hours=1, minutes=30),
            "start_str": "Mon 14:30",
            "end_str": "15:30",
        }
        result = _check_pair(ev_a, ev_b)
        assert result is not None
        assert result["type"] == "overlap"

    def test_no_overlap(self):
        now = datetime.now(timezone.utc)
        ev_a = {
            "id": "1",
            "summary": "Meeting A",
            "location": "",
            "start_dt": now,
            "end_dt": now + timedelta(hours=1),
            "start_str": "Mon 14:00",
            "end_str": "15:00",
        }
        ev_b = {
            "id": "2",
            "summary": "Meeting B",
            "location": "",
            "start_dt": now + timedelta(hours=2),
            "end_dt": now + timedelta(hours=3),
            "start_str": "Mon 16:00",
            "end_str": "17:00",
        }
        result = _check_pair(ev_a, ev_b)
        assert result is None

    def test_tight_gap_different_locations(self):
        now = datetime.now(timezone.utc)
        ev_a = {
            "id": "1",
            "summary": "Meeting A",
            "location": "Office",
            "start_dt": now,
            "end_dt": now + timedelta(hours=1),
            "start_str": "Mon 14:00",
            "end_str": "15:00",
        }
        ev_b = {
            "id": "2",
            "summary": "Meeting B",
            "location": "Client HQ",
            "start_dt": now + timedelta(hours=1, minutes=10),
            "end_dt": now + timedelta(hours=2),
            "start_str": "Mon 15:10",
            "end_str": "16:00",
        }
        result = _check_pair(ev_a, ev_b)
        assert result is not None
        assert result["type"] == "tight_gap"
        assert result["gap_minutes"] == 10

    def test_tight_gap_same_location_no_conflict(self):
        now = datetime.now(timezone.utc)
        ev_a = {
            "id": "1",
            "summary": "Meeting A",
            "location": "Office",
            "start_dt": now,
            "end_dt": now + timedelta(hours=1),
            "start_str": "Mon 14:00",
            "end_str": "15:00",
        }
        ev_b = {
            "id": "2",
            "summary": "Meeting B",
            "location": "Office",
            "start_dt": now + timedelta(hours=1, minutes=10),
            "end_dt": now + timedelta(hours=2),
            "start_str": "Mon 15:10",
            "end_str": "16:00",
        }
        result = _check_pair(ev_a, ev_b)
        assert result is None  # Same location, gap is fine

    def test_adjacent_events_no_gap_no_location(self):
        now = datetime.now(timezone.utc)
        ev_a = {
            "id": "1",
            "summary": "Meeting A",
            "location": "",
            "start_dt": now,
            "end_dt": now + timedelta(hours=1),
            "start_str": "Mon 14:00",
            "end_str": "15:00",
        }
        ev_b = {
            "id": "2",
            "summary": "Meeting B",
            "location": "",
            "start_dt": now + timedelta(hours=1),
            "end_dt": now + timedelta(hours=2),
            "start_str": "Mon 15:00",
            "end_str": "16:00",
        }
        result = _check_pair(ev_a, ev_b)
        assert result is None  # Back-to-back without locations is fine


class TestDetectConflicts:
    """Tests for full conflict detection."""

    @pytest.mark.asyncio
    async def test_no_calendar(self):
        with patch(
            "services.business.agenda_conflict_service.get_service", return_value=None
        ):
            result = await detect_conflicts("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_single_event_no_conflicts(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                _make_event("Solo Meeting", start_hours=2),
            ]
        )

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_cal,
        ):
            result = await detect_conflicts("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_detect_overlap(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                _make_event("Meeting A", start_hours=2, duration_hours=2),
                _make_event("Meeting B", start_hours=3, duration_hours=1),
            ]
        )

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_cal,
        ):
            result = await detect_conflicts("u1")
        assert len(result) == 1
        assert result[0]["type"] == "overlap"

    @pytest.mark.asyncio
    async def test_no_conflicts(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                _make_event("Meeting A", start_hours=2, duration_hours=1),
                _make_event("Meeting B", start_hours=5, duration_hours=1),
            ]
        )

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_cal,
        ):
            result = await detect_conflicts("u1")
        assert result == []


class TestAlertGeneration:
    """Tests for humanized alerts."""

    @pytest.mark.asyncio
    async def test_no_conflicts_no_alert(self):
        result = await generate_conflict_alert("Marcos", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_alert_overlap(self):
        conflicts = [
            {
                "type": "overlap",
                "event_a": {
                    "id": "1",
                    "summary": "Meeting A",
                    "start_str": "Mon 14:00",
                    "end_str": "15:00",
                },
                "event_b": {
                    "id": "2",
                    "summary": "Meeting B",
                    "start_str": "Mon 14:30",
                    "end_str": "15:30",
                },
                "description": "'Meeting A' (Mon 14:00-15:00) overlaps with 'Meeting B' (Mon 14:30-15:30)",
            }
        ]

        with patch(
            "services.business.agenda_conflict_service.get_service", return_value=None
        ):
            result = await generate_conflict_alert("Marcos", conflicts)
        assert result is not None
        assert "Marcos" in result
        assert "Meeting A" in result
        assert "⚠️" in result

    @pytest.mark.asyncio
    async def test_fallback_alert_tight_gap(self):
        conflicts = [
            {
                "type": "tight_gap",
                "event_a": {"id": "1", "summary": "Meeting A"},
                "event_b": {"id": "2", "summary": "Meeting B"},
                "gap_minutes": 10,
                "description": "Only 10 min between 'Meeting A' at Office and 'Meeting B' at Client HQ",
            }
        ]

        with patch(
            "services.business.agenda_conflict_service.get_service", return_value=None
        ):
            result = await generate_conflict_alert("Ana", conflicts)
        assert "🚗" in result

    @pytest.mark.asyncio
    async def test_gpt_alert(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "⚠️ Hey Marcos! I noticed a scheduling conflict — "
            "Meeting A and Meeting B overlap on Monday at 14:00. "
            "Want me to reschedule one?"
        )

        conflicts = [
            {
                "type": "overlap",
                "event_a": {"id": "1", "summary": "Meeting A"},
                "event_b": {"id": "2", "summary": "Meeting B"},
                "description": "overlap test",
            }
        ]

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_openai,
        ):
            result = await generate_conflict_alert("Marcos", conflicts)
        assert "Marcos" in result


class TestProactivityLoop:
    """Tests for the proactivity loop runner."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.agenda_conflict_service.get_service", return_value=None
        ):
            result = await check_conflicts_for_all_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_users(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[])

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_db,
        ):
            result = await check_conflicts_for_all_users()
        assert result == 0


class TestDedup:
    """Tests for dedup and storage."""

    @pytest.mark.asyncio
    async def test_filter_returns_all_by_default(self):
        from services.business.agenda_conflict_service import _filter_already_alerted

        conflicts = [
            {"type": "overlap", "event_a": {"id": "1"}, "event_b": {"id": "2"}}
        ]
        result = await _filter_already_alerted("u1", conflicts)
        assert result == conflicts

    @pytest.mark.asyncio
    async def test_store_alert_no_db(self):
        from services.business.agenda_conflict_service import _store_conflict_alert

        with patch(
            "services.business.agenda_conflict_service.get_service", return_value=None
        ):
            await _store_conflict_alert(
                "u1",
                "alert text",
                [{"type": "overlap", "event_a": {"id": "1"}, "event_b": {"id": "2"}}],
            )

    @pytest.mark.asyncio
    async def test_store_alert_success(self):
        from services.business.agenda_conflict_service import _store_conflict_alert

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_db,
        ):
            await _store_conflict_alert(
                "u1",
                "test",
                [{"type": "overlap", "event_a": {"id": "a"}, "event_b": {"id": "b"}}],
            )

    @pytest.mark.asyncio
    async def test_calendar_exception(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            side_effect=Exception("Calendar error")
        )

        with patch(
            "services.business.agenda_conflict_service.get_service",
            return_value=mock_cal,
        ):
            result = await detect_conflicts("u1")
        assert result == []
