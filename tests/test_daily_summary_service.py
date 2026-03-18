"""Tests for Daily Summary service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.daily_summary_service import (
    generate_daily_summary,
    _get_today_events,
    _get_tomorrow_events,
    _get_pending_tasks,
    _get_focus_time_today,
    _generate_fallback_summary,
)


class TestGetTodayEvents:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.daily_summary_service.get_service", return_value=None
        ):
            assert await _get_today_events("u1") == []

    @pytest.mark.asyncio
    async def test_with_events(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "title": "Standup",
                    "start_time": "2026-03-17T09:00:00",
                    "end_time": "2026-03-17T09:30:00",
                }
            ]
        )
        with patch(
            "services.business.daily_summary_service.get_service", return_value=mock_db
        ):
            result = await _get_today_events("u1")
        assert len(result) == 1
        assert result[0]["title"] == "Standup"

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("DB error")
        with patch(
            "services.business.daily_summary_service.get_service", return_value=mock_db
        ):
            assert await _get_today_events("u1") == []


class TestGetTomorrowEvents:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.daily_summary_service.get_service", return_value=None
        ):
            assert await _get_tomorrow_events("u1") == []

    @pytest.mark.asyncio
    async def test_with_events(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"title": "Dentist", "start_time": "2026-03-18T10:00:00"}]
        )
        with patch(
            "services.business.daily_summary_service.get_service", return_value=mock_db
        ):
            result = await _get_tomorrow_events("u1")
        assert len(result) == 1


class TestGetPendingTasks:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.daily_summary_service.get_service", return_value=None
        ):
            assert await _get_pending_tasks("u1") == []

    @pytest.mark.asyncio
    async def test_with_pending(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"title": "Buy milk", "remind_at": "2026-03-17T12:00:00"}]
        )
        with patch(
            "services.business.daily_summary_service.get_service", return_value=mock_db
        ):
            result = await _get_pending_tasks("u1")
        assert len(result) == 1


class TestGetFocusTime:
    @pytest.mark.asyncio
    async def test_no_state(self):
        with patch(
            "services.business.focus_mode_service.get_focus_state",
            new_callable=AsyncMock,
            return_value=None,
        ):
            assert await _get_focus_time_today("u1") == 0

    @pytest.mark.asyncio
    async def test_exception(self):
        with patch(
            "services.business.focus_mode_service.get_focus_state",
            new_callable=AsyncMock,
            side_effect=Exception("err"),
        ):
            assert await _get_focus_time_today("u1") == 0


class TestFallbackSummary:
    def test_full_day(self):
        data = {
            "events_today": [{"title": "Standup"}, {"title": "Lunch"}],
            "pending_tasks": [{"title": "Buy milk"}],
            "events_tomorrow": [{"title": "Dentist"}],
            "focus_minutes": 90,
        }
        msg = _generate_fallback_summary("João", data)
        assert "Daily Summary" in msg
        assert "2 event" in msg
        assert "1 task pending" in msg
        assert "1h30min" in msg
        assert "Dentist" in msg

    def test_empty_day(self):
        data = {
            "events_today": [],
            "pending_tasks": [],
            "events_tomorrow": [],
            "focus_minutes": 0,
        }
        msg = _generate_fallback_summary("", data)
        assert "No events" in msg
        assert "schedule free" in msg

    def test_focus_minutes_only(self):
        data = {
            "events_today": [],
            "pending_tasks": [],
            "events_tomorrow": [],
            "focus_minutes": 25,
        }
        msg = _generate_fallback_summary("Ana", data)
        assert "25 minutes" in msg

    def test_multiple_pending(self):
        data = {
            "events_today": [],
            "pending_tasks": [{"title": "A"}, {"title": "B"}, {"title": "C"}],
            "events_tomorrow": [],
            "focus_minutes": 0,
        }
        msg = _generate_fallback_summary("", data)
        assert "3 tasks pending" in msg

    def test_single_event(self):
        data = {
            "events_today": [{"title": "Meeting"}],
            "pending_tasks": [],
            "events_tomorrow": [],
            "focus_minutes": 0,
        }
        msg = _generate_fallback_summary("", data)
        assert "1 event" in msg
        assert "Meeting" in msg


class TestGenerateDailySummary:
    @pytest.mark.asyncio
    async def test_full_flow(self):
        with (
            patch(
                "services.business.daily_summary_service._get_today_events",
                new_callable=AsyncMock,
                return_value=[{"title": "Meeting"}],
            ),
            patch(
                "services.business.daily_summary_service._get_tomorrow_events",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.daily_summary_service._get_pending_tasks",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.daily_summary_service._get_focus_time_today",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "services.business.daily_summary_service._generate_ai_summary",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "services.business.daily_summary_service._store_summary",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_daily_summary("u1", "João")
        assert result is not None
        assert "Daily Summary" in result["text"]
        assert result["data"]["events_today"] == [{"title": "Meeting"}]

    @pytest.mark.asyncio
    async def test_with_ai(self):
        with (
            patch(
                "services.business.daily_summary_service._get_today_events",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.daily_summary_service._get_tomorrow_events",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.daily_summary_service._get_pending_tasks",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.daily_summary_service._get_focus_time_today",
                new_callable=AsyncMock,
                return_value=60,
            ),
            patch(
                "services.business.daily_summary_service._generate_ai_summary",
                new_callable=AsyncMock,
                return_value="📊 AI generated summary here",
            ),
            patch(
                "services.business.daily_summary_service._store_summary",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_daily_summary("u1", "Ana")
        assert result["text"] == "📊 AI generated summary here"


class TestStoreSummary:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.daily_summary_service import _store_summary

        with patch(
            "services.business.daily_summary_service.get_service", return_value=None
        ):
            await _store_summary("u1", "test", {})  # Should not raise

    @pytest.mark.asyncio
    async def test_store_success(self):
        from services.business.daily_summary_service import _store_summary

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()
        with patch(
            "services.business.daily_summary_service.get_service", return_value=mock_db
        ):
            await _store_summary("u1", "Summary text", {"events_count": 3})

    @pytest.mark.asyncio
    async def test_store_exception(self):
        from services.business.daily_summary_service import _store_summary

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("DB error")
        with patch(
            "services.business.daily_summary_service.get_service", return_value=mock_db
        ):
            await _store_summary("u1", "text", {})  # Should not raise


class TestAISummary:
    @pytest.mark.asyncio
    async def test_ai_no_openai(self):
        from services.business.daily_summary_service import _generate_ai_summary

        with patch(
            "services.business.daily_summary_service.get_service", return_value=None
        ):
            result = await _generate_ai_summary("João", {"events_today": []})
        assert result is None

    @pytest.mark.asyncio
    async def test_ai_success(self):
        from services.business.daily_summary_service import _generate_ai_summary

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "📊 Resumo: dia produtivo com 3 reuniões!"
        )
        with patch(
            "services.business.daily_summary_service.get_service",
            return_value=mock_openai,
        ):
            result = await _generate_ai_summary(
                "João",
                {
                    "events_today": [{"title": "Meeting"}],
                    "pending_tasks": [],
                    "events_tomorrow": [],
                    "focus_minutes": 60,
                },
            )
        assert result is not None
        assert "Resumo" in result

    @pytest.mark.asyncio
    async def test_ai_exception(self):
        from services.business.daily_summary_service import _generate_ai_summary

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.side_effect = Exception("GPT error")
        with patch(
            "services.business.daily_summary_service.get_service",
            return_value=mock_openai,
        ):
            result = await _generate_ai_summary("João", {"events_today": []})
        assert result is None
