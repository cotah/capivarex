"""Tests for birthday detection service — A1."""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.birthday_service import (
    detect_upcoming_birthdays,
    generate_birthday_alert,
    _is_birthday_event,
    _extract_person_name,
    check_birthdays_for_all_users,
)


def _make_event(summary, start_days=3):
    start = datetime.now(timezone.utc) + timedelta(days=start_days)
    return {
        "id": f"evt_{summary[:10]}",
        "summary": summary,
        "start": start.strftime("%Y-%m-%d"),
        "end": start.strftime("%Y-%m-%d"),
        "description": "",
    }


class TestBirthdayDetection:
    """Tests for keyword detection and name extraction."""

    def test_is_birthday_english(self):
        assert _is_birthday_event("john's birthday", "") is True

    def test_is_birthday_portuguese(self):
        assert _is_birthday_event("aniversário do joão", "") is True

    def test_is_birthday_description(self):
        assert _is_birthday_event("party", "it's a birthday celebration") is True

    def test_not_birthday(self):
        assert _is_birthday_event("team meeting", "discuss Q4") is False

    def test_extract_name_english(self):
        name = _extract_person_name("John's Birthday")
        assert "John" in name

    def test_extract_name_portuguese(self):
        name = _extract_person_name("Aniversário do João")
        assert "João" in name or "Jo" in name

    def test_extract_name_simple(self):
        name = _extract_person_name("Ana birthday")
        assert "Ana" in name


class TestDetectUpcoming:
    """Tests for calendar scanning."""

    @pytest.mark.asyncio
    async def test_no_calendar(self):
        with patch("services.business.birthday_service.get_service", return_value=None):
            result = await detect_upcoming_birthdays("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_detect_birthday_in_calendar(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                _make_event("João's Birthday", start_days=3),
                _make_event("Team Meeting", start_days=2),
            ]
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_cal
        ):
            result = await detect_upcoming_birthdays("u1")

        assert len(result) == 1
        assert "Jo" in result[0]["person_name"]
        assert result[0]["days_until"] in (2, 3)  # timezone rounding

    @pytest.mark.asyncio
    async def test_skip_past_birthdays(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                _make_event("Old birthday", start_days=-2),
            ]
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_cal
        ):
            result = await detect_upcoming_birthdays("u1")
        assert len(result) == 0


class TestBirthdayAlert:
    """Tests for alert generation."""

    @pytest.mark.asyncio
    async def test_alert_fallback(self):
        birthday = {
            "event_id": "evt-1",
            "person_name": "João",
            "date": "Mar 20",
            "days_until": 3,
            "summary": "João's birthday",
        }

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        mock_db.get_client.return_value.table.return_value.insert.return_value.execute.return_value = MagicMock()

        def fake_svc(name):
            return mock_db if name == "database" else None

        with patch("services.business.birthday_service.get_service", fake_svc):
            result = await generate_birthday_alert("u1", birthday, "Marcos")

        assert result is not None
        assert "João" in result["message"]
        assert "Marcos" in result["message"]
        assert "🎂" in result["title"]

    @pytest.mark.asyncio
    async def test_alert_dedup(self):
        birthday = {
            "event_id": "evt-dup",
            "person_name": "Ana",
            "date": "Mar 20",
            "days_until": 2,
            "summary": "Ana birthday",
        }

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "1", "metadata": '{"event_id": "evt-dup"}'}]
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_db
        ):
            result = await generate_birthday_alert("u1", birthday, "Marcos")
        assert result is None


class TestCheckAll:
    """Tests for proactivity loop runner."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.birthday_service.get_service", return_value=None):
            result = await check_birthdays_for_all_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_users(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[])

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_db
        ):
            result = await check_birthdays_for_all_users()
        assert result == 0


class TestBirthdayHelpers:
    """Extra tests for birthday helpers."""

    @pytest.mark.asyncio
    async def test_alert_no_db(self):
        from services.business.birthday_service import _alert_already_sent

        with patch("services.business.birthday_service.get_service", return_value=None):
            result = await _alert_already_sent("u1", "evt-1")
        assert result is False

    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.birthday_service import _store_alert

        with patch("services.business.birthday_service.get_service", return_value=None):
            await _store_alert("u1", "evt-1", "Title", "Message")

    @pytest.mark.asyncio
    async def test_humanize_fallback_today(self):
        from services.business.birthday_service import _humanize_birthday_alert

        with patch("services.business.birthday_service.get_service", return_value=None):
            result = await _humanize_birthday_alert("Marcos", "João", 0, "Mar 16")
        assert "today" in result.lower()
        assert "João" in result

    def test_is_birthday_niver(self):
        assert _is_birthday_event("niver do marcos", "") is True

    def test_extract_name_bday(self):
        name = _extract_person_name("Maria bday")
        assert "Maria" in name

    @pytest.mark.asyncio
    async def test_detect_birthday_with_iso_datetime(self):
        """Birthday with ISO datetime format (not date-only)."""
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        start = datetime.now(timezone.utc) + timedelta(days=5)
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                {
                    "id": "evt-iso",
                    "summary": "Ana's Birthday",
                    "start": start.isoformat(),
                    "end": start.isoformat(),
                    "description": "",
                },
            ]
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_cal
        ):
            result = await detect_upcoming_birthdays("u1")
        assert len(result) == 1
        assert "Ana" in result[0]["person_name"]

    @pytest.mark.asyncio
    async def test_detect_multiple_birthdays(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                _make_event("Birthday João", start_days=2),
                _make_event("Aniversário Maria", start_days=5),
                _make_event("Standup meeting", start_days=1),
            ]
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_cal
        ):
            result = await detect_upcoming_birthdays("u1")
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_humanize_birthday_gpt(self):
        from services.business.birthday_service import _humanize_birthday_alert

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "🎂 Hey Marcos! João's birthday is in 3 days! "
            "How about a nice gift or dinner? Want me to help?"
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_openai
        ):
            result = await _humanize_birthday_alert("Marcos", "João", 3, "Mar 20")
        assert "João" in result
        assert "Marcos" in result

    @pytest.mark.asyncio
    async def test_detect_birthday_with_description(self):
        mock_cal = MagicMock()
        mock_cal.is_initialized.return_value = True
        from datetime import datetime, timezone, timedelta

        start = (datetime.now(timezone.utc) + timedelta(days=2)).strftime("%Y-%m-%d")
        mock_cal.async_get_upcoming_events = AsyncMock(
            return_value=[
                {
                    "id": "evt-desc",
                    "summary": "Party for Pedro",
                    "start": start,
                    "end": start,
                    "description": "Birthday celebration",
                },
            ]
        )

        with patch(
            "services.business.birthday_service.get_service", return_value=mock_cal
        ):
            result = await detect_upcoming_birthdays("u1")
        assert len(result) == 1
