# -*- coding: utf-8 -*-
"""Tests for mercado interactive report callbacks."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


class TestBuildMonthsKeyboard:
    """Tests for build_months_keyboard helper."""

    def test_returns_inline_keyboard_markup(self):
        from telegram_bot.handlers.mercado_callback import build_months_keyboard

        kb = build_months_keyboard(lang="en")
        assert kb is not None
        # Should have 2 rows of 3 buttons each
        assert len(kb.inline_keyboard) == 2
        assert len(kb.inline_keyboard[0]) == 3

    def test_buttons_have_correct_callback_data(self):
        from telegram_bot.handlers.mercado_callback import build_months_keyboard

        kb = build_months_keyboard(lang="en")
        first_btn = kb.inline_keyboard[0][0]
        assert first_btn.callback_data.startswith("mr:report:")

    def test_months_keyboard_pt(self):
        from telegram_bot.handlers.mercado_callback import build_months_keyboard

        kb = build_months_keyboard(lang="pt")
        # Just verify it doesn't crash with PT
        assert kb is not None


class TestMercadoCallbackDispatch:
    """Tests for callback routing."""

    @pytest.mark.asyncio
    async def test_months_action(self):
        """mr:months triggers _show_months."""
        from telegram_bot.handlers.mercado_callback import handle_mercado_callback

        mock_update = MagicMock()
        mock_update.callback_query.data = "mr:months"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_user.id = 123
        mock_update.effective_chat.id = 123

        mock_context = MagicMock()

        with patch("telegram_bot.handlers.mercado_callback.get_service") as mock_svc:
            mock_db = MagicMock()
            mock_db.is_initialized.return_value = True
            mock_db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"preferred_language": "en"}]
            )
            mock_svc.return_value = mock_db

            await handle_mercado_callback(mock_update, mock_context)

        mock_update.callback_query.answer.assert_called_once()
        mock_update.callback_query.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_report_action(self):
        """mr:report:2026:3 triggers _show_report."""
        from telegram_bot.handlers.mercado_callback import handle_mercado_callback

        mock_update = MagicMock()
        mock_update.callback_query.data = "mr:report:2026:3"
        mock_update.callback_query.answer = AsyncMock()
        mock_update.callback_query.edit_message_text = AsyncMock()
        mock_update.effective_user.id = 123
        mock_update.effective_chat.id = 123

        mock_context = MagicMock()

        with patch("telegram_bot.handlers.mercado_callback.get_service") as mock_svc:
            mock_mercado = MagicMock()
            mock_mercado.is_initialized.return_value = True
            mock_mercado.relatorio_mensal = AsyncMock(
                return_value={"mensagem": "test report"}
            )

            mock_db = MagicMock()
            mock_db.is_initialized.return_value = True
            mock_db.client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
                data=[{"preferred_language": "en"}]
            )

            def side_effect(name):
                if name == "mercado":
                    return mock_mercado
                return mock_db

            mock_svc.side_effect = side_effect

            await handle_mercado_callback(mock_update, mock_context)

        mock_update.callback_query.edit_message_text.assert_called()


class TestInlineKeyboardResponseSender:
    """Tests for inline_keyboard type in response_sender."""

    @pytest.mark.asyncio
    async def test_sends_with_reply_markup(self):
        """response_sender sends reply_text with reply_markup for inline_keyboard type."""
        from agents.core import AgentResponse, AgentStatus
        from telegram_bot.utils.response_sender import send_agent_response

        kb = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Test", callback_data="mr:test")]]
        )

        result = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Pick one",
            data={"inline_keyboard": True},
            metadata={"type": "inline_keyboard", "reply_markup": kb},
        )

        mock_update = MagicMock()
        mock_update.message.reply_text = AsyncMock()

        await send_agent_response(mock_update, result)

        mock_update.message.reply_text.assert_called_once()
        call_kwargs = mock_update.message.reply_text.call_args
        assert call_kwargs.kwargs.get("reply_markup") == kb
