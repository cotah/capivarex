"""Tests for Weekly Planner service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.weekly_planner_service import (
    generate_weekly_plan,
    _get_week_events,
    _get_pending_reminders,
    _organize_by_day,
    _generate_fallback_plan,
)


class TestGetWeekEvents:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.weekly_planner_service.get_service", return_value=None
        ):
            assert await _get_week_events("u1") == []

    @pytest.mark.asyncio
    async def test_with_events(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[
                {
                    "title": "Standup",
                    "start_time": "2026-03-18T09:00:00Z",
                    "end_time": "2026-03-18T09:30:00Z",
                    "description": "",
                }
            ]
        )
        with patch(
            "services.business.weekly_planner_service.get_service", return_value=mock_db
        ):
            result = await _get_week_events("u1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.weekly_planner_service.get_service", return_value=mock_db
        ):
            assert await _get_week_events("u1") == []


class TestGetPendingReminders:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.weekly_planner_service.get_service", return_value=None
        ):
            assert await _get_pending_reminders("u1") == []

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.weekly_planner_service.get_service", return_value=mock_db
        ):
            assert await _get_pending_reminders("u1") == []


class TestOrganizeByDay:
    def test_organize_events(self):
        events = [
            {
                "title": "Meeting",
                "start_time": "2026-03-18T09:00:00+00:00",
            },  # Wednesday
            {"title": "Lunch", "start_time": "2026-03-18T12:00:00+00:00"},
            {"title": "Dentist", "start_time": "2026-03-19T10:00:00+00:00"},  # Thursday
        ]
        result = _organize_by_day(events)
        assert "Quarta" in result
        assert len(result["Quarta"]) == 2
        assert "Quinta" in result
        assert len(result["Quinta"]) == 1

    def test_empty(self):
        assert _organize_by_day([]) == {}

    def test_invalid_date(self):
        events = [{"title": "Bad", "start_time": "not-a-date"}]
        assert _organize_by_day(events) == {}

    def test_no_start_time(self):
        events = [{"title": "No time"}]
        assert _organize_by_day(events) == {}


class TestFallbackPlan:
    def test_busy_week(self):
        data = {
            "days": {
                "Segunda": [
                    {"title": "Standup", "time": "09:00"},
                    {"title": "Sprint", "time": "14:00"},
                ],
                "Terça": [{"title": "Dentist", "time": "10:00"}],
                "Quarta": [{"title": "Meeting", "time": "11:00"}],
            },
            "total_events": 12,
            "pending_reminders": 2,
            "reminders": [{"title": "Buy milk"}, {"title": "Call mom"}],
        }
        msg = _generate_fallback_plan("João", data)
        assert "Plano da Semana" in msg
        assert "Segunda" in msg
        assert "Standup" in msg
        assert "Dentist" in msg
        assert "2 lembretes" in msg
        assert "intensa" in msg.lower()

    def test_empty_week(self):
        data = {"days": {}, "total_events": 0, "pending_reminders": 0, "reminders": []}
        msg = _generate_fallback_plan("Ana", data)
        assert "tranquila" in msg.lower()
        assert "7 dias livres" in msg

    def test_moderate_week(self):
        data = {
            "days": {"Segunda": [{"title": "A", "time": "09:00"}]},
            "total_events": 3,
            "pending_reminders": 0,
            "reminders": [],
        }
        msg = _generate_fallback_plan("", data)
        assert "equilibrada" in msg.lower() or "ritmo" in msg.lower()

    def test_free_days_count(self):
        data = {
            "days": {"Segunda": [{"title": "A", "time": "09:00"}]},
            "total_events": 1,
            "pending_reminders": 0,
            "reminders": [],
        }
        msg = _generate_fallback_plan("", data)
        assert "6 dias livres" in msg


class TestGenerateWeeklyPlan:
    @pytest.mark.asyncio
    async def test_full_flow(self):
        events = [{"title": "Meeting", "start_time": "2026-03-18T09:00:00+00:00"}]
        with (
            patch(
                "services.business.weekly_planner_service._get_week_events",
                new_callable=AsyncMock,
                return_value=events,
            ),
            patch(
                "services.business.weekly_planner_service._get_pending_reminders",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.weekly_planner_service._generate_ai_plan",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "services.business.weekly_planner_service._store_plan",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_weekly_plan("u1", "João")
        assert result is not None
        assert "Plano da Semana" in result["text"]
        assert result["data"]["total_events"] == 1

    @pytest.mark.asyncio
    async def test_with_ai(self):
        with (
            patch(
                "services.business.weekly_planner_service._get_week_events",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.weekly_planner_service._get_pending_reminders",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "services.business.weekly_planner_service._generate_ai_plan",
                new_callable=AsyncMock,
                return_value="📅 AI weekly plan!",
            ),
            patch(
                "services.business.weekly_planner_service._store_plan",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_weekly_plan("u1")
        assert result["text"] == "📅 AI weekly plan!"


class TestStorePlan:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.weekly_planner_service import _store_plan

        with patch(
            "services.business.weekly_planner_service.get_service", return_value=None
        ):
            await _store_plan("u1", "text", {})

    @pytest.mark.asyncio
    async def test_store_exception(self):
        from services.business.weekly_planner_service import _store_plan

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.weekly_planner_service.get_service", return_value=mock_db
        ):
            await _store_plan("u1", "text", {})
