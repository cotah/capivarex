# -*- coding: utf-8 -*-
"""Tests for Calendar Sync Service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_supabase_result(data):
    result = MagicMock()
    result.data = data
    return result


# ===========================================================================
# _get_connected_users
# ===========================================================================


class TestGetConnectedUsers:
    """Tests for finding users with active OAuth connections."""

    @pytest.mark.asyncio
    async def test_returns_google_and_microsoft_users(self):
        from services.business.calendar_sync_service import _get_connected_users

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.in_.return_value.execute.return_value = (
            _make_supabase_result([
                {"user_id": "user-1", "provider": "google"},
                {"user_id": "user-2", "provider": "microsoft"},
                {"user_id": "user-1", "provider": "google"},  # duplicate
            ])
        )

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=mock_db,
        ):
            users = await _get_connected_users()

        assert len(users) == 2  # deduplicated
        providers = {u["provider"] for u in users}
        assert providers == {"google", "microsoft"}

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_db(self):
        from services.business.calendar_sync_service import _get_connected_users

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            users = await _get_connected_users()

        assert users == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_db_error(self):
        from services.business.calendar_sync_service import _get_connected_users

        mock_db = MagicMock()
        mock_db.table.side_effect = Exception("DB down")

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=mock_db,
        ):
            users = await _get_connected_users()

        assert users == []


# ===========================================================================
# Event normalization
# ===========================================================================


class TestEventNormalization:
    """Tests for Google and Microsoft event normalization."""

    def test_normalize_google_event(self):
        from services.business.calendar_sync_service import _normalize_google_event

        event = {
            "id": "gcal_123",
            "summary": "Team standup",
            "description": "Daily sync",
            "start": "2026-03-22T09:00:00Z",
            "end": "2026-03-22T09:30:00Z",
            "location": "Zoom",
            "status": "confirmed",
        }

        result = _normalize_google_event(event)
        assert result["source"] == "google"
        assert result["source_event_id"] == "gcal_123"
        assert result["title"] == "Team standup"
        assert result["all_day"] is False
        assert result["location"] == "Zoom"

    def test_normalize_google_allday_event(self):
        from services.business.calendar_sync_service import _normalize_google_event

        event = {
            "id": "gcal_456",
            "summary": "Holiday",
            "start": "2026-03-25",  # date only = all-day
            "end": "2026-03-26",
        }

        result = _normalize_google_event(event)
        assert result["all_day"] is True

    def test_normalize_microsoft_event(self):
        from services.business.calendar_sync_service import _normalize_microsoft_event

        event = {
            "id": "ms_789",
            "summary": "Client call",
            "description": "Quarterly review",
            "start": "2026-03-22T14:00:00Z",
            "end": "2026-03-22T15:00:00Z",
            "location": "Teams",
            "isAllDay": False,
        }

        result = _normalize_microsoft_event(event)
        assert result["source"] == "microsoft"
        assert result["source_event_id"] == "ms_789"
        assert result["title"] == "Client call"
        assert result["all_day"] is False


# ===========================================================================
# _upsert_events
# ===========================================================================


class TestUpsertEvents:
    """Tests for upserting events into calendar_events table."""

    @pytest.mark.asyncio
    async def test_upserts_events_correctly(self):
        from services.business.calendar_sync_service import _upsert_events

        mock_db = MagicMock()
        mock_db.table.return_value.upsert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "row-1"}])
        )

        events = [
            {
                "title": "Meeting",
                "start_time": "2026-03-22T10:00:00Z",
                "source": "google",
                "source_event_id": "gcal_1",
            },
            {
                "title": "Lunch",
                "start_time": "2026-03-22T12:00:00Z",
                "source": "google",
                "source_event_id": "gcal_2",
            },
        ]

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=mock_db,
        ):
            count = await _upsert_events("user-1", events)

        assert count == 2
        assert mock_db.table.return_value.upsert.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_zero_for_empty_events(self):
        from services.business.calendar_sync_service import _upsert_events

        count = await _upsert_events("user-1", [])
        assert count == 0

    @pytest.mark.asyncio
    async def test_handles_partial_failure(self):
        from services.business.calendar_sync_service import _upsert_events

        mock_db = MagicMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Constraint violation")
            mock_result = MagicMock()
            mock_result.execute.return_value = _make_supabase_result([{"id": "x"}])
            return mock_result

        mock_db.table.return_value.upsert = side_effect

        events = [
            {"title": "Fail", "start_time": "X", "source": "google", "source_event_id": "1"},
            {"title": "OK", "start_time": "Y", "source": "google", "source_event_id": "2"},
        ]

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=mock_db,
        ):
            count = await _upsert_events("user-1", events)

        assert count == 1  # one succeeded, one failed gracefully


# ===========================================================================
# sync_user_calendar
# ===========================================================================


class TestSyncUserCalendar:
    """Tests for syncing a single user's calendar."""

    @pytest.mark.asyncio
    async def test_sync_google_calendar(self):
        from services.business.calendar_sync_service import sync_user_calendar

        mock_db = MagicMock()
        mock_db.table.return_value.upsert.return_value.execute.return_value = (
            _make_supabase_result([{"id": "row-1"}])
        )

        with (
            patch(
                "services.business.calendar_sync_service._fetch_google_events",
                new_callable=AsyncMock,
                return_value=[{
                    "title": "Meeting",
                    "start_time": "2026-03-22T09:00:00Z",
                    "end_time": "2026-03-22T10:00:00Z",
                    "source": "google",
                    "source_event_id": "gcal_1",
                }],
            ),
            patch(
                "services.business.calendar_sync_service._get_db",
                new_callable=AsyncMock,
                return_value=mock_db,
            ),
        ):
            count = await sync_user_calendar("user-1", "google")

        assert count == 1

    @pytest.mark.asyncio
    async def test_sync_unknown_provider_returns_zero(self):
        from services.business.calendar_sync_service import sync_user_calendar

        count = await sync_user_calendar("user-1", "yahoo")
        assert count == 0


# ===========================================================================
# sync_all_calendars
# ===========================================================================


class TestSyncAllCalendars:
    """Tests for the main sync_all_calendars entry point."""

    @pytest.mark.asyncio
    async def test_sync_all_with_no_users(self):
        from services.business.calendar_sync_service import sync_all_calendars

        with patch(
            "services.business.calendar_sync_service._get_connected_users",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await sync_all_calendars()

        assert result["users_synced"] == 0
        assert result["total_events"] == 0

    @pytest.mark.asyncio
    async def test_sync_all_with_mixed_providers(self):
        from services.business.calendar_sync_service import sync_all_calendars

        with (
            patch(
                "services.business.calendar_sync_service._get_connected_users",
                new_callable=AsyncMock,
                return_value=[
                    {"user_id": "user-1", "provider": "google"},
                    {"user_id": "user-2", "provider": "microsoft"},
                ],
            ),
            patch(
                "services.business.calendar_sync_service.sync_user_calendar",
                new_callable=AsyncMock,
                side_effect=[3, 2],  # 3 google events, 2 microsoft events
            ),
            patch(
                "services.business.calendar_sync_service._cleanup_past_events",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            result = await sync_all_calendars()

        assert result["users_synced"] == 2
        assert result["total_events"] == 5
        assert result["errors"] == 0

    @pytest.mark.asyncio
    async def test_sync_all_handles_errors_gracefully(self):
        from services.business.calendar_sync_service import sync_all_calendars

        with (
            patch(
                "services.business.calendar_sync_service._get_connected_users",
                new_callable=AsyncMock,
                return_value=[
                    {"user_id": "user-1", "provider": "google"},
                    {"user_id": "user-2", "provider": "microsoft"},
                ],
            ),
            patch(
                "services.business.calendar_sync_service.sync_user_calendar",
                new_callable=AsyncMock,
                side_effect=[Exception("OAuth expired"), 5],
            ),
            patch(
                "services.business.calendar_sync_service._cleanup_past_events",
                new_callable=AsyncMock,
                return_value=0,
            ),
        ):
            result = await sync_all_calendars()

        assert result["users_synced"] == 1
        assert result["total_events"] == 5
        assert result["errors"] == 1
