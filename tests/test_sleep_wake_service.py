"""Tests for Sleep/Wake Routine service."""
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.sleep_wake_service import (
    generate_night_routine,
    generate_morning_routine,
    _calculate_sleep_schedule,
    _generate_fallback_night_message,
    _generate_fallback_morning_message,
    _get_tomorrow_events,
    _get_today_events,
)


class TestCalculateSleepSchedule:
    def test_with_early_event(self):
        event = datetime(2026, 3, 18, 8, 0, tzinfo=timezone.utc)
        schedule = _calculate_sleep_schedule(event)
        assert schedule["wake_time"] == "07:00"
        assert schedule["sleep_hours"] == 8
        assert schedule["bedtime"] == "23:00"

    def test_with_late_event(self):
        event = datetime(2026, 3, 18, 14, 0, tzinfo=timezone.utc)
        schedule = _calculate_sleep_schedule(event)
        assert schedule["wake_time"] == "13:00"

    def test_no_events(self):
        schedule = _calculate_sleep_schedule(None)
        assert schedule["bedtime"] == "23:00"
        assert schedule["wake_time"] == "07:00"
        assert schedule["sleep_hours"] == 8


class TestFallbackNight:
    def test_with_event(self):
        data = {
            "suggested_bedtime": "22:30",
            "suggested_wake": "06:30",
            "sleep_hours": 8,
            "first_event": "Standup",
            "first_event_time": "07:30",
            "events_tomorrow": 3,
        }
        msg = _generate_fallback_night_message("João", data)
        assert "Boa noite" in msg
        assert "Standup" in msg
        assert "22:30" in msg
        assert "06:30" in msg

    def test_no_events(self):
        data = {
            "suggested_bedtime": "23:00",
            "suggested_wake": "07:00",
            "sleep_hours": 8,
            "first_event": None,
            "first_event_time": None,
            "events_tomorrow": 0,
        }
        msg = _generate_fallback_night_message("", data)
        assert "agenda livre" in msg

    def test_single_event(self):
        data = {
            "suggested_bedtime": "23:00",
            "suggested_wake": "07:00",
            "sleep_hours": 8,
            "first_event": "Meeting",
            "first_event_time": "09:00",
            "events_tomorrow": 1,
        }
        msg = _generate_fallback_night_message("Ana", data)
        assert "Meeting" in msg
        assert "+0" not in msg


class TestFallbackMorning:
    def test_with_events(self):
        data = {"events_today": 3, "first_event": "Standup", "weather": "18°C, ensolarado"}
        msg = _generate_fallback_morning_message("João", data)
        assert "Bom dia" in msg
        assert "Standup" in msg
        assert "18°C" in msg

    def test_free_day(self):
        data = {"events_today": 0, "first_event": None, "weather": ""}
        msg = _generate_fallback_morning_message("", data)
        assert "Dia livre" in msg

    def test_no_weather(self):
        data = {"events_today": 1, "first_event": "Dentist", "weather": ""}
        msg = _generate_fallback_morning_message("Ana", data)
        assert "Dentist" in msg
        assert "🌤️" not in msg


class TestEventFetching:
    @pytest.mark.asyncio
    async def test_tomorrow_no_db(self):
        with patch("services.business.sleep_wake_service.get_service", return_value=None):
            assert await _get_tomorrow_events("u1") == []

    @pytest.mark.asyncio
    async def test_tomorrow_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.sleep_wake_service.get_service", return_value=mock_db):
            assert await _get_tomorrow_events("u1") == []

    @pytest.mark.asyncio
    async def test_today_no_db(self):
        with patch("services.business.sleep_wake_service.get_service", return_value=None):
            assert await _get_today_events("u1") == []


class TestGenerateRoutines:
    @pytest.mark.asyncio
    async def test_night_routine(self):
        events = [{"title": "Standup", "start_time": "2026-03-18T09:00:00Z", "end_time": "2026-03-18T09:30:00Z"}]
        with (
            patch("services.business.sleep_wake_service._get_tomorrow_events", new_callable=AsyncMock, return_value=events),
            patch("services.business.sleep_wake_service._get_morning_weather", new_callable=AsyncMock, return_value="15°C, nublado"),
            patch("services.business.sleep_wake_service._generate_ai_night_message", new_callable=AsyncMock, return_value=None),
            patch("services.business.sleep_wake_service._store_routine", new_callable=AsyncMock),
        ):
            result = await generate_night_routine("u1", "João")
        assert result is not None
        assert "Boa noite" in result["text"]
        assert result["data"]["first_event"] == "Standup"

    @pytest.mark.asyncio
    async def test_morning_routine(self):
        events = [{"title": "Meeting", "start_time": "2026-03-17T10:00:00Z"}]
        with (
            patch("services.business.sleep_wake_service._get_today_events", new_callable=AsyncMock, return_value=events),
            patch("services.business.sleep_wake_service._get_morning_weather", new_callable=AsyncMock, return_value="18°C, sol"),
            patch("services.business.sleep_wake_service._generate_ai_morning_message", new_callable=AsyncMock, return_value=None),
            patch("services.business.sleep_wake_service._store_routine", new_callable=AsyncMock),
        ):
            result = await generate_morning_routine("u1", "João")
        assert result is not None
        assert "Bom dia" in result["text"]

    @pytest.mark.asyncio
    async def test_night_with_ai(self):
        with (
            patch("services.business.sleep_wake_service._get_tomorrow_events", new_callable=AsyncMock, return_value=[]),
            patch("services.business.sleep_wake_service._get_morning_weather", new_callable=AsyncMock, return_value=""),
            patch("services.business.sleep_wake_service._generate_ai_night_message", new_callable=AsyncMock, return_value="🌙 AI night message"),
            patch("services.business.sleep_wake_service._store_routine", new_callable=AsyncMock),
        ):
            result = await generate_night_routine("u1")
        assert result["text"] == "🌙 AI night message"


class TestStoreRoutine:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.sleep_wake_service import _store_routine
        with patch("services.business.sleep_wake_service.get_service", return_value=None):
            await _store_routine("u1", "night", "text", {})

    @pytest.mark.asyncio
    async def test_store_exception(self):
        from services.business.sleep_wake_service import _store_routine
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.sleep_wake_service.get_service", return_value=mock_db):
            await _store_routine("u1", "night", "text", {})
