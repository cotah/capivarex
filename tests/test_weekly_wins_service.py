"""Tests for Weekly Wins Recap service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.weekly_wins_service import (
    generate_weekly_wins,
    _count_week_events,
    _count_completed_tasks,
    _count_conversations,
    _get_week_focus_time,
    _generate_fallback_wins,
)


class TestCounters:
    @pytest.mark.asyncio
    async def test_events_no_db(self):
        with patch("services.business.weekly_wins_service.get_service", return_value=None):
            assert await _count_week_events("u1") == 0

    @pytest.mark.asyncio
    async def test_events_with_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.gte.return_value.lte.return_value.execute.return_value = MagicMock(count=5)
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            assert await _count_week_events("u1") == 5

    @pytest.mark.asyncio
    async def test_events_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            assert await _count_week_events("u1") == 0

    @pytest.mark.asyncio
    async def test_tasks_no_db(self):
        with patch("services.business.weekly_wins_service.get_service", return_value=None):
            assert await _count_completed_tasks("u1") == 0

    @pytest.mark.asyncio
    async def test_tasks_with_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(count=8)
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            assert await _count_completed_tasks("u1") == 8

    @pytest.mark.asyncio
    async def test_conversations_no_db(self):
        with patch("services.business.weekly_wins_service.get_service", return_value=None):
            assert await _count_conversations("u1") == 0

    @pytest.mark.asyncio
    async def test_conversations_with_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(count=15)
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            assert await _count_conversations("u1") == 15

    @pytest.mark.asyncio
    async def test_focus_no_db(self):
        with patch("services.business.weekly_wins_service.get_service", return_value=None):
            assert await _get_week_focus_time("u1") == 0

    @pytest.mark.asyncio
    async def test_focus_with_data(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.gte.return_value.execute.return_value = MagicMock(
            data=[
                {"metadata": '{"focus_minutes": 60}'},
                {"metadata": '{"focus_minutes": 45}'},
            ]
        )
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            assert await _get_week_focus_time("u1") == 105

    @pytest.mark.asyncio
    async def test_focus_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            assert await _get_week_focus_time("u1") == 0


class TestFallbackWins:
    def test_great_week(self):
        stats = {"events_attended": 10, "tasks_completed": 8, "conversations": 20, "focus_minutes": 180}
        msg = _generate_fallback_wins("João", stats)
        assert "Conquistas da Semana" in msg
        assert "10 eventos" in msg
        assert "8 tarefas" in msg
        assert "20 conversas" in msg
        assert "3h0min" in msg
        assert "incrível" in msg.lower()

    def test_good_week(self):
        stats = {"events_attended": 5, "tasks_completed": 3, "conversations": 5, "focus_minutes": 60}
        msg = _generate_fallback_wins("Ana", stats)
        assert "Boa semana" in msg or "sólida" in msg.lower()

    def test_quiet_week(self):
        stats = {"events_attended": 0, "tasks_completed": 0, "conversations": 0, "focus_minutes": 0}
        msg = _generate_fallback_wins("", stats)
        assert "tranquila" in msg.lower()

    def test_single_items(self):
        stats = {"events_attended": 1, "tasks_completed": 1, "conversations": 1, "focus_minutes": 25}
        msg = _generate_fallback_wins("Test", stats)
        assert "1 evento" in msg
        assert "1 tarefa" in msg
        assert "25 minutos" in msg

    def test_focus_hours(self):
        stats = {"events_attended": 0, "tasks_completed": 0, "conversations": 0, "focus_minutes": 150}
        msg = _generate_fallback_wins("", stats)
        assert "2h30min" in msg


class TestGenerateWeeklyWins:
    @pytest.mark.asyncio
    async def test_full_flow(self):
        with (
            patch("services.business.weekly_wins_service._count_week_events", new_callable=AsyncMock, return_value=5),
            patch("services.business.weekly_wins_service._count_completed_tasks", new_callable=AsyncMock, return_value=3),
            patch("services.business.weekly_wins_service._count_conversations", new_callable=AsyncMock, return_value=10),
            patch("services.business.weekly_wins_service._get_week_focus_time", new_callable=AsyncMock, return_value=120),
            patch("services.business.weekly_wins_service._generate_ai_wins", new_callable=AsyncMock, return_value=None),
            patch("services.business.weekly_wins_service._store_wins", new_callable=AsyncMock),
        ):
            result = await generate_weekly_wins("u1", "João")
        assert result is not None
        assert "Conquistas" in result["text"]
        assert result["data"]["events_attended"] == 5
        assert result["data"]["tasks_completed"] == 3

    @pytest.mark.asyncio
    async def test_with_ai(self):
        with (
            patch("services.business.weekly_wins_service._count_week_events", new_callable=AsyncMock, return_value=0),
            patch("services.business.weekly_wins_service._count_completed_tasks", new_callable=AsyncMock, return_value=0),
            patch("services.business.weekly_wins_service._count_conversations", new_callable=AsyncMock, return_value=0),
            patch("services.business.weekly_wins_service._get_week_focus_time", new_callable=AsyncMock, return_value=0),
            patch("services.business.weekly_wins_service._generate_ai_wins", new_callable=AsyncMock, return_value="🏆 AI celebration!"),
            patch("services.business.weekly_wins_service._store_wins", new_callable=AsyncMock),
        ):
            result = await generate_weekly_wins("u1")
        assert result["text"] == "🏆 AI celebration!"


class TestStoreWins:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.weekly_wins_service import _store_wins
        with patch("services.business.weekly_wins_service.get_service", return_value=None):
            await _store_wins("u1", "text", {})

    @pytest.mark.asyncio
    async def test_store_exception(self):
        from services.business.weekly_wins_service import _store_wins
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch("services.business.weekly_wins_service.get_service", return_value=mock_db):
            await _store_wins("u1", "text", {})
