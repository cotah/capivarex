"""Tests for telegram_bot.handlers.photo — handle_photo handler."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers — build Telegram-like mock objects
# ---------------------------------------------------------------------------

def _make_photo(file_id="file_123", width=1280, height=960):
    """Create a mock PhotoSize object."""
    photo = MagicMock()
    photo.file_id = file_id
    photo.width = width
    photo.height = height
    photo_file = AsyncMock()
    photo_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"\xff\xd8fake_jpeg"))
    photo.get_file = AsyncMock(return_value=photo_file)
    return photo


def _make_update(user_id=42, chat_id=100, username="testuser", photos=None, caption=None):
    """Create a mock Telegram Update for photo messages."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    update.effective_user.username = username
    update.message.photo = photos if photos is not None else [_make_photo(width=320, height=240), _make_photo()]
    update.message.caption = caption
    update.message.reply_text = AsyncMock()
    return update


def _make_context(bot_instance=None):
    """Create a mock Telegram context."""
    ctx = MagicMock()
    ctx.application.bot_data = {}
    if bot_instance is not None:
        ctx.application.bot_data["capivarax_bot"] = bot_instance
    ctx.bot.send_chat_action = AsyncMock()
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHandlePhoto:
    """Tests for the handle_photo function."""

    @pytest.mark.asyncio
    async def test_rate_limit_blocks(self):
        """When RequestProcessor.process() returns False, handler exits early."""
        from telegram_bot.handlers.photo import handle_photo

        update = _make_update()
        ctx = _make_context(bot_instance=AsyncMock())

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP:
            MockRP.return_value.process = AsyncMock(return_value=False)
            await handle_photo(update, ctx)

        # Bot should never be called
        update.message.reply_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_not_initialized(self):
        """When bot is not in bot_data, replies with error message."""
        from telegram_bot.handlers.photo import handle_photo

        update = _make_update()
        ctx = _make_context(bot_instance=None)  # no bot

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP:
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        update.message.reply_text.assert_awaited_once_with("Bot não inicializado.")

    @pytest.mark.asyncio
    async def test_no_photos_in_message(self):
        """When update.message.photo is empty, handler returns silently."""
        from telegram_bot.handlers.photo import handle_photo

        update = _make_update(photos=[])
        bot_mock = AsyncMock()
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP:
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        bot_mock.process_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_with_caption(self):
        """Photo with caption uses caption as prompt."""
        from telegram_bot.handlers.photo import handle_photo

        agent_response = MagicMock()
        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=agent_response)

        update = _make_update(caption="minha nota fiscal")
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        # Verify prompt is the caption
        bot_mock.process_message.assert_awaited_once()
        call_args = bot_mock.process_message.call_args
        assert call_args[0][0] == "minha nota fiscal"

        # Verify context has image_data
        user_ctx = call_args[0][1]
        assert user_ctx["input_type"] == "photo"
        assert user_ctx["image_mime"] == "image/jpeg"
        assert isinstance(user_ctx["image_data"], bytes)
        assert user_ctx["user_id"] == 42
        assert user_ctx["chat_id"] == 100
        assert user_ctx["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_happy_path_without_caption(self):
        """Photo without caption uses default prompt 'processar imagem'."""
        from telegram_bot.handlers.photo import handle_photo

        agent_response = MagicMock()
        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=agent_response)

        update = _make_update(caption=None)
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        call_args = bot_mock.process_message.call_args
        assert call_args[0][0] == "processar imagem"

    @pytest.mark.asyncio
    async def test_happy_path_empty_caption(self):
        """Photo with empty string caption uses default prompt."""
        from telegram_bot.handlers.photo import handle_photo

        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=MagicMock())

        update = _make_update(caption="")
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        call_args = bot_mock.process_message.call_args
        assert call_args[0][0] == "processar imagem"

    @pytest.mark.asyncio
    async def test_sends_chat_action(self):
        """Handler sends 'upload_photo' chat action while processing."""
        from telegram_bot.handlers.photo import handle_photo

        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=MagicMock())

        update = _make_update()
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        ctx.bot.send_chat_action.assert_awaited_once_with(
            chat_id=100,
            action="upload_photo",
        )

    @pytest.mark.asyncio
    async def test_picks_highest_resolution_photo(self):
        """Handler selects the last photo (highest resolution)."""
        from telegram_bot.handlers.photo import handle_photo

        small = _make_photo(file_id="small", width=160, height=120)
        medium = _make_photo(file_id="medium", width=640, height=480)
        large = _make_photo(file_id="large", width=1920, height=1080)

        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=MagicMock())

        update = _make_update(photos=[small, medium, large])
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        # The large photo's get_file should be called (last in list)
        large.get_file.assert_awaited_once()
        small.get_file.assert_not_called()
        medium.get_file.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_agent_response_called(self):
        """Handler calls send_agent_response with the result."""
        from telegram_bot.handlers.photo import handle_photo

        agent_response = MagicMock()
        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=agent_response)

        update = _make_update()
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock) as mock_send:
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        mock_send.assert_awaited_once_with(update, agent_response)

    @pytest.mark.asyncio
    async def test_exception_sends_error_message(self):
        """When an exception occurs, handler replies with error message."""
        from telegram_bot.handlers.photo import handle_photo

        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(side_effect=RuntimeError("boom"))

        update = _make_update()
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        update.message.reply_text.assert_awaited_once()
        error_msg = update.message.reply_text.call_args[0][0]
        assert "Erro" in error_msg

    @pytest.mark.asyncio
    async def test_download_failure_sends_error(self):
        """When photo download fails, handler catches and replies with error."""
        from telegram_bot.handlers.photo import handle_photo

        photo = _make_photo()
        photo.get_file = AsyncMock(side_effect=Exception("download failed"))

        bot_mock = AsyncMock()
        update = _make_update(photos=[photo])
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        update.message.reply_text.assert_awaited_once()
        assert "Erro" in update.message.reply_text.call_args[0][0]

    @pytest.mark.asyncio
    async def test_image_bytes_are_actual_bytes(self):
        """user_context['image_data'] must be bytes, not bytearray."""
        from telegram_bot.handlers.photo import handle_photo

        bot_mock = AsyncMock()
        bot_mock.process_message = AsyncMock(return_value=MagicMock())

        update = _make_update()
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP, \
             patch("telegram_bot.handlers.photo.send_agent_response", new_callable=AsyncMock):
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        user_ctx = bot_mock.process_message.call_args[0][1]
        assert type(user_ctx["image_data"]) is bytes


class TestHandlePhotoNoneAttributes:
    """Edge cases where effective_user or effective_chat may have None-ish values."""

    @pytest.mark.asyncio
    async def test_none_photos_returns_early(self):
        """If photos is None (not just empty), handler returns silently."""
        from telegram_bot.handlers.photo import handle_photo

        update = _make_update()
        update.message.photo = None
        bot_mock = AsyncMock()
        ctx = _make_context(bot_instance=bot_mock)

        with patch("telegram_bot.handlers.photo.RequestProcessor") as MockRP:
            MockRP.return_value.process = AsyncMock(return_value=True)
            await handle_photo(update, ctx)

        bot_mock.process_message.assert_not_called()
