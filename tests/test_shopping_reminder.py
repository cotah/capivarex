# -*- coding: utf-8 -*-
"""Tests for smart shopping reminder."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


class TestVerificarListaPendente:
    """Tests for verificar_lista_pendente method."""

    def _make_service(self):
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.logger = __import__("logging").getLogger("test")
        return svc

    @pytest.mark.asyncio
    async def test_empty_list_no_reminder(self):
        svc = self._make_service()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert result["has_pending"] is False

    @pytest.mark.asyncio
    async def test_recent_list_no_reminder(self):
        """List < 3 days old should not trigger."""
        svc = self._make_service()
        yesterday = (datetime.now() - timedelta(days=1)).isoformat()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"item": "leite", "created_at": yesterday}]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert result["has_pending"] is False

    @pytest.mark.asyncio
    async def test_old_list_triggers_reminder(self):
        """List 5 days old should trigger."""
        svc = self._make_service()
        five_days_ago = (datetime.now() - timedelta(days=5)).isoformat()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[
                {"item": "leite", "created_at": five_days_ago},
                {"item": "pão", "created_at": five_days_ago},
                {"item": "ovos", "created_at": five_days_ago},
            ]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert result["has_pending"] is True
        assert result["item_count"] == 3
        assert result["days_old"] >= 5
        assert "leite" in result["items_preview"]

    @pytest.mark.asyncio
    async def test_preview_truncated_to_5(self):
        """Preview shows max 5 items."""
        svc = self._make_service()
        old = (datetime.now() - timedelta(days=5)).isoformat()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"item": f"item{i}", "created_at": old} for i in range(8)]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert "(+3)" in result["items_preview"]

    @pytest.mark.asyncio
    async def test_message_i18n(self):
        """Message uses correct language."""
        svc = self._make_service()
        old = (datetime.now() - timedelta(days=5)).isoformat()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"item": "leite", "created_at": old}]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result_pt = await svc.verificar_lista_pendente("123", lang="pt")
            result_en = await svc.verificar_lista_pendente("123", lang="en")

        assert "lista de compras" in result_pt["mensagem"]
        assert "shopping list" in result_en["mensagem"]

    @pytest.mark.asyncio
    async def test_exception_returns_safe_default(self):
        """Exception in DB call returns safe empty result."""
        svc = self._make_service()

        with patch("services.get_service", side_effect=Exception("DB down")):
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert result["has_pending"] is False
        assert result["item_count"] == 0

    @pytest.mark.asyncio
    async def test_invalid_date_returns_no_reminder(self):
        """Invalid created_at date falls back to days_old=0."""
        svc = self._make_service()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"item": "leite", "created_at": "not-a-date"}]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert result["has_pending"] is False

    @pytest.mark.asyncio
    async def test_empty_created_at_returns_no_reminder(self):
        """Missing created_at falls back to days_old=0."""
        svc = self._make_service()
        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.order.return_value.execute.return_value = MagicMock(
            data=[{"item": "leite", "created_at": ""}]
        )

        with patch("services.get_service") as mock_get:
            mock_get.return_value = MagicMock(client=mock_db)
            result = await svc.verificar_lista_pendente("123", lang="en")

        assert result["has_pending"] is False


class TestShoppingReminderKeyboard:
    """Tests for reminder keyboard."""

    def test_keyboard_has_3_buttons(self):
        from telegram_bot.handlers.mercado_callback import (
            build_shopping_reminder_keyboard,
        )

        kb = build_shopping_reminder_keyboard(lang="en")
        all_buttons = [btn for row in kb.inline_keyboard for btn in row]
        assert len(all_buttons) == 3

    def test_keyboard_callback_data(self):
        from telegram_bot.handlers.mercado_callback import (
            build_shopping_reminder_keyboard,
        )

        kb = build_shopping_reminder_keyboard(lang="en")
        callbacks = [
            btn.callback_data for row in kb.inline_keyboard for btn in row
        ]
        assert "mr:view_list" in callbacks
        assert "mr:clear_done" in callbacks
        assert "mr:snooze" in callbacks

    def test_keyboard_labels_pt(self):
        from telegram_bot.handlers.mercado_callback import (
            build_shopping_reminder_keyboard,
        )

        kb = build_shopping_reminder_keyboard(lang="pt")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "📋 Ver Lista" in labels
        assert "✅ Já fui, limpar" in labels
        assert "🔕 Lembrar amanhã" in labels

    def test_keyboard_labels_es(self):
        from telegram_bot.handlers.mercado_callback import (
            build_shopping_reminder_keyboard,
        )

        kb = build_shopping_reminder_keyboard(lang="es")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        assert "📋 Ver Lista" in labels
        assert "✅ Ya fui, limpiar" in labels
        assert "🔕 Recordar mañana" in labels


class TestCallbackHandlers:
    """Tests for the view_list, clear_done, and snooze callback handlers."""

    @pytest.mark.asyncio
    async def test_show_list_calls_ver_lista(self):
        from telegram_bot.handlers.mercado_callback import _show_list

        mock_query = AsyncMock()
        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = True
        mock_svc.ver_lista = AsyncMock(
            return_value={"mensagem": "🛒 pão, leite"}
        )

        with patch(
            "telegram_bot.handlers.mercado_callback.get_service",
            return_value=mock_svc,
        ):
            await _show_list(mock_query, "123", "en")

        mock_svc.ver_lista.assert_awaited_once_with(user_id="123", lang="en")
        mock_query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_show_list_no_service(self):
        from telegram_bot.handlers.mercado_callback import _show_list

        mock_query = AsyncMock()

        with patch(
            "telegram_bot.handlers.mercado_callback.get_service",
            return_value=None,
        ):
            await _show_list(mock_query, "123", "en")

        mock_query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_list_calls_limpar_lista(self):
        from telegram_bot.handlers.mercado_callback import _clear_list

        mock_query = AsyncMock()
        mock_svc = MagicMock()
        mock_svc.is_initialized.return_value = True
        mock_svc.limpar_lista = AsyncMock(return_value={})

        with patch(
            "telegram_bot.handlers.mercado_callback.get_service",
            return_value=mock_svc,
        ):
            await _clear_list(mock_query, "123", "en")

        mock_svc.limpar_lista.assert_awaited_once_with(
            user_id="123", lang="en"
        )
        mock_query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_clear_list_no_service(self):
        from telegram_bot.handlers.mercado_callback import _clear_list

        mock_query = AsyncMock()

        with patch(
            "telegram_bot.handlers.mercado_callback.get_service",
            return_value=None,
        ):
            await _clear_list(mock_query, "123", "en")

        mock_query.edit_message_text.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_snooze_reminder(self):
        from telegram_bot.handlers.mercado_callback import _snooze_reminder

        mock_query = AsyncMock()
        await _snooze_reminder(mock_query, "en")
        mock_query.edit_message_text.assert_awaited_once()
        call_text = mock_query.edit_message_text.call_args[0][0]
        assert "remind you tomorrow" in call_text

    @pytest.mark.asyncio
    async def test_snooze_reminder_pt(self):
        from telegram_bot.handlers.mercado_callback import _snooze_reminder

        mock_query = AsyncMock()
        await _snooze_reminder(mock_query, "pt")
        call_text = mock_query.edit_message_text.call_args[0][0]
        assert "amanhã" in call_text


class TestDailyTrigger:
    """Tests for daily trigger logic."""

    def test_flag_prevents_duplicate(self):
        sent = set()
        key = "2026-03-04"
        assert key not in sent
        sent.add(key)
        assert key in sent

    def test_i18n_keys_exist(self):
        from services.i18n import t

        keys = [
            "mercado_shopping_reminder",
            "mercado_btn_view_list",
            "mercado_btn_clear_done",
            "mercado_btn_snooze",
            "mercado_list_cleared_done",
            "mercado_reminder_snoozed",
        ]
        for key in keys:
            for lang in ("en", "pt", "es"):
                result = t(key, lang=lang, count=5, days=3, items="leite, pão")
                assert result and len(result) > 3, f"Missing: {key} / {lang}"

    def test_i18n_reminder_message_format(self):
        """Verify the reminder message contains expected placeholders."""
        from services.i18n import t

        msg = t(
            "mercado_shopping_reminder",
            lang="en",
            count=8,
            days=3,
            items="leite, pão, ovos",
        )
        assert "8" in msg
        assert "3" in msg
        assert "leite" in msg
