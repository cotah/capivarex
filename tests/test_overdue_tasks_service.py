"""Tests for overdue tasks service — A6: detect late reminders/tasks + nudge."""
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.overdue_tasks_service import (
    detect_overdue_items,
    _check_overdue_reminders,
    _check_overdue_notes,
    generate_overdue_alert,
    check_overdue_for_all_users,
)


class TestDetectOverdueReminders:
    """Tests for overdue reminder detection."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await _check_overdue_reminders("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_no_overdue(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.gt.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        with patch("services.business.overdue_tasks_service.get_service", return_value=mock_db):
            result = await _check_overdue_reminders("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_found_overdue(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.lt.return_value.gt.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "r1", "title": "Call bank", "remind_at": yesterday, "status": "pending"}]
        )

        with patch("services.business.overdue_tasks_service.get_service", return_value=mock_db):
            result = await _check_overdue_reminders("u1")
        assert len(result) == 1
        assert result[0]["title"] == "Call bank"

    @pytest.mark.asyncio
    async def test_db_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("DB down")

        with patch("services.business.overdue_tasks_service.get_service", return_value=mock_db):
            result = await _check_overdue_reminders("u1")
        assert result == []


class TestDetectOverdueNotes:
    """Tests for overdue task/note detection."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await _check_overdue_notes("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_found_overdue_note(self):
        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.not_.is_.return_value.lt.return_value.gt.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "n1", "title": "Submit report", "due_date": yesterday}]
        )

        with patch("services.business.overdue_tasks_service.get_service", return_value=mock_db):
            result = await _check_overdue_notes("u1")
        assert len(result) == 1


class TestDetectAll:
    """Tests for combined detection."""

    @pytest.mark.asyncio
    async def test_detect_all_no_db(self):
        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await detect_overdue_items("u1")
        assert result["reminders"] == []
        assert result["notes"] == []


class TestAlertGeneration:
    """Tests for humanized nudge."""

    @pytest.mark.asyncio
    async def test_no_overdue(self):
        result = await generate_overdue_alert("Marcos", {"reminders": [], "notes": []})
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_reminders(self):
        overdue = {
            "reminders": [
                {"title": "Call bank", "remind_at": "2026-03-14T10:00:00+00:00"},
                {"title": "Send report", "remind_at": "2026-03-15T09:00:00+00:00"},
            ],
            "notes": [],
        }

        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await generate_overdue_alert("Marcos", overdue)
        assert result is not None
        assert "Marcos" in result
        assert "Call bank" in result
        assert "📋" in result

    @pytest.mark.asyncio
    async def test_fallback_mixed(self):
        overdue = {
            "reminders": [{"title": "Call bank", "remind_at": "2026-03-14T10:00:00+00:00"}],
            "notes": [{"title": "Submit report", "due_date": "2026-03-13T00:00:00+00:00"}],
        }

        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await generate_overdue_alert("Ana", overdue)
        assert "Ana" in result
        assert "⏰" in result
        assert "📝" in result

    @pytest.mark.asyncio
    async def test_fallback_many_items(self):
        overdue = {
            "reminders": [{"title": f"Task {i}", "remind_at": "2026-03-14"} for i in range(6)],
            "notes": [],
        }

        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await generate_overdue_alert("Test", overdue)
        assert "more" in result

    @pytest.mark.asyncio
    async def test_gpt_alert(self):
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = (
            "📋 Hey Marcos! Just checking in — you had a reminder to call the bank "
            "that was due yesterday. Still need to do it? I can reschedule for you."
        )

        overdue = {
            "reminders": [{"title": "Call bank", "remind_at": "2026-03-15"}],
            "notes": [],
        }

        with patch("services.business.overdue_tasks_service.get_service", return_value=mock_openai):
            result = await generate_overdue_alert("Marcos", overdue)
        assert "Marcos" in result


class TestProactivityLoop:
    """Tests for the loop runner."""

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch("services.business.overdue_tasks_service.get_service", return_value=None):
            result = await check_overdue_for_all_users()
        assert result == 0

    @pytest.mark.asyncio
    async def test_no_users(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_all_users_with_proactivity_enabled = AsyncMock(return_value=[])

        with patch("services.business.overdue_tasks_service.get_service", return_value=mock_db):
            result = await check_overdue_for_all_users()
        assert result == 0
