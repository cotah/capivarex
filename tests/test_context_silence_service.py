"""Tests for Context-aware Silence service."""

import pytest
import time
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from services.business.context_silence_service import (
    should_be_silent,
    _check_focus_mode,
    _check_current_meeting,
    _check_quiet_hours,
    _check_dnd,
    queue_notification,
    flush_queue,
    _get_queue,
)


class TestCheckFocusMode:
    @pytest.mark.asyncio
    async def test_focus_active(self):
        with (
            patch(
                "services.business.focus_mode_service.is_focus_active",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "services.business.focus_mode_service.get_focus_state",
                new_callable=AsyncMock,
                return_value={"ends_at": time.time() + 3600},
            ),
        ):
            result = await _check_focus_mode("u1")
        assert result["silent"] is True
        assert result["reason"] == "focus"

    @pytest.mark.asyncio
    async def test_focus_not_active(self):
        with patch(
            "services.business.focus_mode_service.is_focus_active",
            new_callable=AsyncMock,
            return_value=False,
        ):
            result = await _check_focus_mode("u1")
        assert result["silent"] is False

    @pytest.mark.asyncio
    async def test_focus_error(self):
        with patch(
            "services.business.focus_mode_service.is_focus_active",
            new_callable=AsyncMock,
            side_effect=Exception("err"),
        ):
            result = await _check_focus_mode("u1")
        assert result["silent"] is False


class TestCheckMeeting:
    @pytest.mark.asyncio
    async def test_in_meeting(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.lte.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"title": "Sprint Review", "end_time": "2026-03-17T15:00:00+00:00"}]
        )
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            result = await _check_current_meeting("u1")
        assert result["silent"] is True
        assert result["reason"] == "meeting"
        assert "Sprint Review" in result["details"]

    @pytest.mark.asyncio
    async def test_no_meeting(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.lte.return_value.gte.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            result = await _check_current_meeting("u1")
        assert result["silent"] is False

    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.context_silence_service.get_service", return_value=None
        ):
            result = await _check_current_meeting("u1")
        assert result["silent"] is False


class TestCheckQuietHours:
    @pytest.mark.asyncio
    async def test_during_quiet(self):
        # Dynamically compute quiet hours that always include current hour
        now_hour = datetime.now(timezone.utc).hour
        quiet_start = (now_hour - 2) % 24
        quiet_end = (now_hour + 2) % 24
        with patch(
            "services.business.context_silence_service._get_quiet_hours",
            new_callable=AsyncMock,
            return_value=(quiet_start, quiet_end),
        ):
            result = await _check_quiet_hours("u1")
        assert result["silent"] is True
        assert result["reason"] == "sleeping"

    @pytest.mark.asyncio
    async def test_outside_quiet(self):
        # Set quiet hours to a window that's definitely not now
        now_hour = datetime.now(timezone.utc).hour
        quiet_start = (now_hour + 2) % 24
        quiet_end = (now_hour + 4) % 24
        with patch(
            "services.business.context_silence_service._get_quiet_hours",
            new_callable=AsyncMock,
            return_value=(quiet_start, quiet_end),
        ):
            result = await _check_quiet_hours("u1")
        assert result["silent"] is False

    @pytest.mark.asyncio
    async def test_error(self):
        with patch(
            "services.business.context_silence_service._get_quiet_hours",
            new_callable=AsyncMock,
            side_effect=Exception("err"),
        ):
            result = await _check_quiet_hours("u1")
        assert result["silent"] is False


class TestCheckDND:
    @pytest.mark.asyncio
    async def test_dnd_active(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        future_ts = str(time.time() + 3600)
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps({"active": True, "until": future_ts})}]
        )
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            result = await _check_dnd("u1")
        assert result["silent"] is True
        assert result["reason"] == "dnd"

    @pytest.mark.asyncio
    async def test_dnd_expired(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        past_ts = str(time.time() - 3600)
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps({"active": True, "until": past_ts})}]
        )
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            result = await _check_dnd("u1")
        assert result["silent"] is False

    @pytest.mark.asyncio
    async def test_no_dnd(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            result = await _check_dnd("u1")
        assert result["silent"] is False


class TestShouldBeSilent:
    @pytest.mark.asyncio
    async def test_focus_takes_priority(self):
        with (
            patch(
                "services.business.context_silence_service._check_focus_mode",
                new_callable=AsyncMock,
                return_value={
                    "silent": True,
                    "reason": "focus",
                    "until": "16:00",
                    "details": "Focus Mode",
                },
            ),
        ):
            result = await should_be_silent("u1")
        assert result["silent"] is True
        assert result["reason"] == "focus"

    @pytest.mark.asyncio
    async def test_meeting_if_no_focus(self):
        with (
            patch(
                "services.business.context_silence_service._check_focus_mode",
                new_callable=AsyncMock,
                return_value={
                    "silent": False,
                    "reason": None,
                    "until": None,
                    "details": None,
                },
            ),
            patch(
                "services.business.context_silence_service._check_current_meeting",
                new_callable=AsyncMock,
                return_value={
                    "silent": True,
                    "reason": "meeting",
                    "until": "15:00",
                    "details": "Standup",
                },
            ),
        ):
            result = await should_be_silent("u1")
        assert result["reason"] == "meeting"

    @pytest.mark.asyncio
    async def test_not_silent(self):
        not_silent = {"silent": False, "reason": None, "until": None, "details": None}
        with (
            patch(
                "services.business.context_silence_service._check_focus_mode",
                new_callable=AsyncMock,
                return_value=not_silent,
            ),
            patch(
                "services.business.context_silence_service._check_current_meeting",
                new_callable=AsyncMock,
                return_value=not_silent,
            ),
            patch(
                "services.business.context_silence_service._check_quiet_hours",
                new_callable=AsyncMock,
                return_value=not_silent,
            ),
            patch(
                "services.business.context_silence_service._check_dnd",
                new_callable=AsyncMock,
                return_value=not_silent,
            ),
        ):
            result = await should_be_silent("u1")
        assert result["silent"] is False


class TestQueueNotification:
    @pytest.mark.asyncio
    async def test_queue_no_db(self):
        with patch(
            "services.business.context_silence_service.get_service", return_value=None
        ):
            await queue_notification("u1", "Test notification")  # Should not raise

    @pytest.mark.asyncio
    async def test_queue_success(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": "[]"}]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            await queue_notification("u1", "New email from João", "email")


class TestFlushQueue:
    @pytest.mark.asyncio
    async def test_empty_queue(self):
        with patch(
            "services.business.context_silence_service._get_queue",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await flush_queue("u1", "João")
        assert result is None

    @pytest.mark.asyncio
    async def test_flush_with_items(self):
        queue = [
            {"text": "Email de Ana", "source": "email", "time": time.time()},
            {"text": "Encomenda atualizada", "source": "tracking", "time": time.time()},
            {"text": "Lembrete: compras", "source": "reminder", "time": time.time()},
        ]
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with (
            patch(
                "services.business.context_silence_service._get_queue",
                new_callable=AsyncMock,
                return_value=queue,
            ),
            patch(
                "services.business.context_silence_service.get_service",
                return_value=mock_db,
            ),
        ):
            result = await flush_queue("u1", "João")

        assert result is not None
        assert "3 notificações" in result
        assert "Email de Ana" in result
        assert "Encomenda atualizada" in result
        assert "João" in result

    @pytest.mark.asyncio
    async def test_flush_single(self):
        queue = [{"text": "Alerta", "source": "", "time": time.time()}]
        with (
            patch(
                "services.business.context_silence_service._get_queue",
                new_callable=AsyncMock,
                return_value=queue,
            ),
            patch(
                "services.business.context_silence_service.get_service",
                return_value=None,
            ),
        ):
            result = await flush_queue("u1")
        assert "1 notificação" in result


class TestGetQueue:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.context_silence_service.get_service", return_value=None
        ):
            assert await _get_queue("u1") == []

    @pytest.mark.asyncio
    async def test_with_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": '[{"text": "test", "time": 1}]'}]
        )
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            result = await _get_queue("u1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.context_silence_service.get_service",
            return_value=mock_db,
        ):
            assert await _get_queue("u1") == []
