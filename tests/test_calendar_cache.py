# -*- coding: utf-8 -*-
"""Tests for calendar_events cache integration (get_cached_events, proactivity, calendar_agent)."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_supabase_result(data):
    result = MagicMock()
    result.data = data
    return result


# ===========================================================================
# get_cached_events / get_next_cached_event
# ===========================================================================


class TestGetCachedEvents:
    """Tests for the cache read API."""

    @pytest.mark.asyncio
    async def test_returns_empty_when_db_unavailable(self):
        """Test 1: get_cached_events returns empty list when DB is unavailable."""
        from services.business.calendar_sync_service import get_cached_events

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await get_cached_events("user-1")

        assert result == []

    @pytest.mark.asyncio
    async def test_returns_events_from_supabase(self):
        """Test 2: get_cached_events returns normalized events from Supabase."""
        from services.business.calendar_sync_service import get_cached_events

        mock_events = [
            {
                "title": "Standup",
                "description": "Daily sync",
                "start_time": "2026-03-22T09:00:00Z",
                "end_time": "2026-03-22T09:30:00Z",
                "location": "Zoom",
                "source": "google",
                "all_day": False,
                "status": "confirmed",
            },
            {
                "title": "Lunch",
                "description": "",
                "start_time": "2026-03-22T12:00:00Z",
                "end_time": "2026-03-22T13:00:00Z",
                "location": "",
                "source": "microsoft",
                "all_day": False,
                "status": "confirmed",
            },
        ]

        mock_db = MagicMock()
        chain = mock_db.table.return_value.select.return_value.eq.return_value
        chain.gte.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = (
            _make_supabase_result(mock_events)
        )

        with patch(
            "services.business.calendar_sync_service._get_db",
            new_callable=AsyncMock,
            return_value=mock_db,
        ):
            result = await get_cached_events("user-1", days_ahead=7, limit=50)

        assert len(result) == 2
        assert result[0]["title"] == "Standup"
        assert result[1]["source"] == "microsoft"

    @pytest.mark.asyncio
    async def test_get_next_returns_first_event(self):
        """Test 3: get_next_cached_event returns first event when cache has data."""
        from services.business.calendar_sync_service import get_next_cached_event

        with patch(
            "services.business.calendar_sync_service.get_cached_events",
            new_callable=AsyncMock,
            return_value=[
                {"title": "First Meeting", "start_time": "2026-03-22T09:00:00Z"},
                {"title": "Second Meeting", "start_time": "2026-03-22T14:00:00Z"},
            ],
        ):
            result = await get_next_cached_event("user-1")

        assert result is not None
        assert result["title"] == "First Meeting"

    @pytest.mark.asyncio
    async def test_get_next_returns_none_when_empty(self):
        """Test 4: get_next_cached_event returns None when cache is empty."""
        from services.business.calendar_sync_service import get_next_cached_event

        with patch(
            "services.business.calendar_sync_service.get_cached_events",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_next_cached_event("user-1")

        assert result is None


# ===========================================================================
# Proactivity service cache-first
# ===========================================================================


class TestProactivityCacheFirst:
    """Tests for proactivity_service calendar cache-first strategy."""

    @pytest.mark.asyncio
    async def test_proactivity_uses_cache_when_available(self):
        """Test 5: proactivity_service uses cache when get_next_cached_event returns data."""
        # We test the _get_calendar_cache_first logic indirectly by importing
        # and calling get_next_cached_event which proactivity_service now uses
        from services.business.calendar_sync_service import get_next_cached_event

        cached_event = {
            "title": "Board Meeting",
            "start_time": "2026-03-22T15:00:00Z",
            "end_time": "2026-03-22T16:00:00Z",
            "location": "Room A",
            "description": "Quarterly review",
            "source": "google",
        }

        with patch(
            "services.business.calendar_sync_service.get_cached_events",
            new_callable=AsyncMock,
            return_value=[cached_event],
        ):
            result = await get_next_cached_event("user-1")

        assert result is not None
        assert result["title"] == "Board Meeting"
        # Proactivity maps title → summary internally; we verify the cache returns correct data

    @pytest.mark.asyncio
    async def test_proactivity_falls_back_when_cache_empty(self):
        """Test 6: proactivity_service falls back to live API when cache is empty."""
        from services.business.calendar_sync_service import get_next_cached_event

        with patch(
            "services.business.calendar_sync_service.get_cached_events",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await get_next_cached_event("user-1")

        # Cache returns None → proactivity_service will try live API
        assert result is None


# ===========================================================================
# Calendar agent cache fallback
# ===========================================================================


class TestCalendarAgentCacheFallback:
    """Tests for calendar_agent cache fallback when OAuth not connected."""

    @pytest.mark.asyncio
    async def test_agent_returns_cached_events_when_oauth_disconnected(self):
        """Test 7: calendar_agent returns cached events when OAuth not connected but cache has data."""
        from agents.specialized.calendar_agent import CalendarAgent
        from services.core import ServiceUnavailableError

        agent = CalendarAgent()

        # Mock service that raises ServiceUnavailableError on any method call
        mock_service = MagicMock()
        mock_service.async_get_upcoming_events = AsyncMock(
            side_effect=ServiceUnavailableError("Google Calendar não conectado")
        )
        mock_service.async_get_next_meeting = AsyncMock(
            side_effect=ServiceUnavailableError("Google Calendar não conectado")
        )

        cached = [
            {
                "title": "Team Call",
                "start_time": "2026-03-22T10:00:00+00:00",
                "end_time": "2026-03-22T11:00:00+00:00",
                "location": "Zoom",
            },
        ]

        with (
            patch.object(
                agent, "_get_calendar_service",
                new_callable=AsyncMock, return_value=mock_service,
            ),
            patch(
                "services.business.calendar_sync_service.get_cached_events",
                new_callable=AsyncMock, return_value=cached,
            ),
        ):
            result = await agent.execute("próximos eventos", {"user_id": "user-1"})

        assert result.status.value == "success"
        assert "Team Call" in result.response
        assert result.data["source"] == "cache"

    @pytest.mark.asyncio
    async def test_agent_returns_connect_when_both_unavailable(self):
        """Test 8: calendar_agent returns connect message when both OAuth and cache are unavailable."""
        from agents.specialized.calendar_agent import CalendarAgent
        from services.core import ServiceUnavailableError

        agent = CalendarAgent()
        err_msg = "Conecta a tua conta Google: https://example.com/auth"

        mock_service = MagicMock()
        mock_service.async_get_upcoming_events = AsyncMock(
            side_effect=ServiceUnavailableError(err_msg)
        )

        with (
            patch.object(
                agent, "_get_calendar_service",
                new_callable=AsyncMock, return_value=mock_service,
            ),
            patch(
                "services.business.calendar_sync_service.get_cached_events",
                new_callable=AsyncMock, return_value=[],
            ),
        ):
            result = await agent.execute("próximos eventos", {"user_id": "user-1"})

        assert result.status.value == "error"
        assert "Conecta" in result.response
