"""Tests for Focus Mode service."""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.focus_mode_service import (
    detect_focus_intent,
    activate_focus,
    deactivate_focus,
    is_focus_active,
    add_missed_notification,
    format_activate_response,
    format_deactivate_response,
    _extract_duration,
)


class TestDetectFocusIntent:
    def test_activate_pt(self):
        result = detect_focus_intent("Vou focar por 2 horas")
        assert result["action"] == "activate"
        assert result["duration_minutes"] == 120

    def test_activate_en(self):
        result = detect_focus_intent("Enable focus mode for 30 minutes")
        assert result["action"] == "activate"
        assert result["duration_minutes"] == 30

    def test_activate_deep_work(self):
        result = detect_focus_intent("preciso de deep work agora")
        assert result["action"] == "activate"

    def test_activate_dnd(self):
        result = detect_focus_intent("do not disturb please")
        assert result["action"] == "activate"

    def test_activate_pomodoro(self):
        result = detect_focus_intent("quero fazer pomodoro")
        assert result["action"] == "activate"
        assert result["pomodoro"] is True

    def test_deactivate_pt(self):
        result = detect_focus_intent("parar foco")
        assert result["action"] == "deactivate"

    def test_deactivate_en(self):
        result = detect_focus_intent("stop focus mode")
        assert result["action"] == "deactivate"

    def test_deactivate_terminei(self):
        result = detect_focus_intent("terminei")
        assert result["action"] == "deactivate"

    def test_not_focus(self):
        assert detect_focus_intent("qual a previsão do tempo?") is None

    def test_not_focus_empty(self):
        assert detect_focus_intent("") is None

    def test_default_duration(self):
        result = detect_focus_intent("focus mode")
        assert result["duration_minutes"] == 60

    def test_silence_keyword(self):
        result = detect_focus_intent("modo silêncio por favor")
        assert result["action"] == "activate"

    def test_busy_mode(self):
        result = detect_focus_intent("busy mode for 1 hour")
        assert result["action"] == "activate"
        assert result["duration_minutes"] == 60


class TestExtractDuration:
    def test_hours_pt(self):
        assert _extract_duration("2 horas") == 120

    def test_hours_en(self):
        assert _extract_duration("3 hours") == 180

    def test_minutes_pt(self):
        assert _extract_duration("45 minutos") == 45

    def test_minutes_en(self):
        assert _extract_duration("30 minutes") == 30

    def test_min_abbrev(self):
        assert _extract_duration("15 min") == 15

    def test_h_abbrev(self):
        assert _extract_duration("1h") == 60

    def test_combined(self):
        assert _extract_duration("1h30") == 90

    def test_colon(self):
        assert _extract_duration("2:00") == 120

    def test_no_duration(self):
        assert _extract_duration("vou focar agora") is None


class TestActivateFocus:
    @pytest.mark.asyncio
    async def test_activate_basic(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.focus_mode_service.get_service") as mock_get:
            mock_get.side_effect = lambda name: mock_db if name == "database" else None
            result = await activate_focus("user-123", 60, False)

        assert result["active"] is True
        assert result["duration_minutes"] == 60
        assert result["pomodoro"] is False

    @pytest.mark.asyncio
    async def test_activate_pomodoro(self):
        with patch("services.business.focus_mode_service.get_service", return_value=None):
            result = await activate_focus("user-123", 120, True)
        assert result["pomodoro"] is True

    @pytest.mark.asyncio
    async def test_activate_max_duration(self):
        with patch("services.business.focus_mode_service.get_service", return_value=None):
            result = await activate_focus("user-123", 1000)
        # Max 8 hours = 480 minutes
        assert result["ends_at"] - result["started_at"] <= 8 * 3600 + 1


class TestDeactivateFocus:
    @pytest.mark.asyncio
    async def test_deactivate_not_active(self):
        with patch("services.business.focus_mode_service.get_focus_state", new_callable=AsyncMock, return_value=None):
            result = await deactivate_focus("user-123")
        assert result["was_active"] is False

    @pytest.mark.asyncio
    async def test_deactivate_active(self):
        session = {
            "active": True,
            "started_at": time.time() - 1800,
            "ends_at": time.time() + 1800,
            "missed_notifications": [{"text": "Email novo", "time": time.time()}],
        }
        with (
            patch("services.business.focus_mode_service.get_focus_state", new_callable=AsyncMock, return_value=session),
            patch("services.business.focus_mode_service._save_focus_state", new_callable=AsyncMock),
            patch("services.business.focus_mode_service.get_service", return_value=None),
        ):
            result = await deactivate_focus("user-123")
        assert result["was_active"] is True
        assert result["duration_actual"] >= 29  # ~30 minutes
        assert len(result["missed"]) == 1


class TestIsFocusActive:
    @pytest.mark.asyncio
    async def test_active_via_redis(self):
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.get_key = AsyncMock(return_value={"active": True, "ends_at": time.time() + 3600})

        with patch("services.business.focus_mode_service.get_service", return_value=mock_redis):
            assert await is_focus_active("user-123") is True

    @pytest.mark.asyncio
    async def test_expired_via_redis(self):
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = True
        mock_redis.get_key = AsyncMock(return_value={"active": True, "ends_at": time.time() - 100})
        mock_redis.delete_key = AsyncMock()

        with patch("services.business.focus_mode_service.get_service", return_value=mock_redis):
            assert await is_focus_active("user-123") is False

    @pytest.mark.asyncio
    async def test_not_active(self):
        with patch("services.business.focus_mode_service.get_service", return_value=None):
            with patch("services.business.focus_mode_service.get_focus_state", new_callable=AsyncMock, return_value=None):
                assert await is_focus_active("user-123") is False

    @pytest.mark.asyncio
    async def test_db_fallback_active(self):
        session = {"active": True, "ends_at": time.time() + 3600}
        mock_redis = MagicMock()
        mock_redis.is_initialized.return_value = False

        with (
            patch("services.business.focus_mode_service.get_service", return_value=mock_redis),
            patch("services.business.focus_mode_service.get_focus_state", new_callable=AsyncMock, return_value=session),
        ):
            assert await is_focus_active("user-123") is True


class TestAddMissed:
    @pytest.mark.asyncio
    async def test_add_missed(self):
        session = {"active": True, "ends_at": time.time() + 3600, "missed_notifications": []}
        with (
            patch("services.business.focus_mode_service.get_focus_state", new_callable=AsyncMock, return_value=session),
            patch("services.business.focus_mode_service._save_focus_state", new_callable=AsyncMock) as mock_save,
        ):
            await add_missed_notification("user-123", "Novo email de João")
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][1]
        assert len(saved["missed_notifications"]) == 1

    @pytest.mark.asyncio
    async def test_add_missed_not_active(self):
        with patch("services.business.focus_mode_service.get_focus_state", new_callable=AsyncMock, return_value=None):
            await add_missed_notification("user-123", "test")  # Should not raise


class TestFormatResponses:
    def test_activate_response(self):
        session = {
            "duration_minutes": 60,
            "ends_at": time.time() + 3600,
            "pomodoro": False,
        }
        msg = format_activate_response(session)
        assert "Focus Mode ativado" in msg
        assert "1 hora" in msg
        assert "Pomodoro" not in msg

    def test_activate_pomodoro(self):
        session = {
            "duration_minutes": 120,
            "ends_at": time.time() + 7200,
            "pomodoro": True,
        }
        msg = format_activate_response(session)
        assert "Pomodoro" in msg
        assert "25 min" in msg

    def test_activate_minutes(self):
        session = {
            "duration_minutes": 30,
            "ends_at": time.time() + 1800,
            "pomodoro": False,
        }
        msg = format_activate_response(session)
        assert "30 minutos" in msg

    def test_deactivate_response_with_missed(self):
        result = {
            "was_active": True,
            "duration_actual": 45,
            "missed": [
                {"text": "Email de João", "time": time.time()},
                {"text": "Reunião em 1h", "time": time.time()},
            ],
        }
        msg = format_deactivate_response(result)
        assert "desativado" in msg
        assert "45 minutos" in msg
        assert "2 notificações" in msg

    def test_deactivate_no_missed(self):
        result = {"was_active": True, "duration_actual": 120, "missed": []}
        msg = format_deactivate_response(result)
        assert "2 horas" in msg
        assert "Nenhuma notificação" in msg

    def test_deactivate_not_active(self):
        result = {"was_active": False, "duration_actual": 0, "missed": []}
        msg = format_deactivate_response(result)
        assert "não estava ativado" in msg

    def test_format_hours_and_minutes(self):
        session = {
            "duration_minutes": 90,
            "ends_at": time.time() + 5400,
            "pomodoro": False,
        }
        msg = format_activate_response(session)
        assert "1h30min" in msg
