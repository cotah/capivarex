"""Tests for WhatsApp service + webhook — send/receive/onboarding."""
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from services.integrations.whatsapp_service import (
    is_configured,
    send_text_message,
    mark_as_read,
    extract_message_from_webhook,
    _split_message,
    send_interactive_buttons,
    send_link_button,
)


class TestConfiguration:
    def test_not_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            assert is_configured() is False

    def test_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "test", "WHATSAPP_PHONE_NUMBER_ID": "123"}):
            assert is_configured() is True

    def test_partial_config(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "test", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            assert is_configured() is False


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_send_not_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            result = await send_text_message("353891234567", "Hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.test123"}]}

        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_text_message("+353 89 123 4567", "Hello!")
        assert result is not None

    @pytest.mark.asyncio
    async def test_send_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": {"message": "Invalid token"}}

        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "bad", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_text_message("353891234567", "Hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_exception(self):
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("Network error")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_text_message("353891234567", "test")
        assert result is None

    @pytest.mark.asyncio
    async def test_send_cleans_phone(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.x"}]}

        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            await send_text_message("+353 89-958 2889", "test")
            payload = mock_client.post.call_args.kwargs.get("json", {})
            assert payload["to"] == "353899582889"


class TestInteractiveMessages:
    @pytest.mark.asyncio
    async def test_buttons_not_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            result = await send_interactive_buttons("353891234567", "test", [{"id": "1", "title": "OK"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_buttons_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.btn1"}]}

        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_interactive_buttons(
                "353891234567", "Choose:", [{"id": "1", "title": "Yes"}, {"id": "2", "title": "No"}],
                header="Question", footer="footer",
            )
        assert result is not None

    @pytest.mark.asyncio
    async def test_link_button_not_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            result = await send_link_button("353891234567", "test", "Click", "https://example.com")
        assert result is None


class TestMarkAsRead:
    @pytest.mark.asyncio
    async def test_mark_not_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            result = await mark_as_read("wamid.test")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await mark_as_read("wamid.test123")
        assert result is True

    @pytest.mark.asyncio
    async def test_mark_exception(self):
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("fail")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await mark_as_read("wamid.test")
        assert result is False


class TestSplitMessage:
    def test_short_message(self):
        assert len(_split_message("Hello", max_len=4096)) == 1

    def test_long_message(self):
        text = "Hello world. " * 500
        chunks = _split_message(text, max_len=4096)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c) <= 4096

    def test_split_at_newline(self):
        text = "Line 1\nLine 2\n" + "x" * 4090
        assert len(_split_message(text, max_len=4096)) >= 2


class TestExtractMessage:
    def test_text_message(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.abc", "timestamp": "1710000000", "type": "text", "text": {"body": "Hello!"}}],
            "contacts": [{"profile": {"name": "John Doe"}}],
        }}]}]}
        result = extract_message_from_webhook(payload)
        assert result["text"] == "Hello!"
        assert result["name"] == "John Doe"

    def test_image_message(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.img", "timestamp": "1710000000", "type": "image", "image": {"caption": "Look!"}}],
            "contacts": [{"profile": {"name": "Ana"}}],
        }}]}]}
        assert extract_message_from_webhook(payload)["text"] == "Look!"

    def test_image_no_caption(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.img2", "timestamp": "1710000000", "type": "image", "image": {"id": "m1"}}],
            "contacts": [],
        }}]}]}
        assert "Image" in extract_message_from_webhook(payload)["text"]

    def test_location_message(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.loc", "timestamp": "1710000000", "type": "location", "location": {"latitude": 53.3498, "longitude": -6.2603}}],
            "contacts": [{"profile": {"name": "M"}}],
        }}]}]}
        assert "53.3498" in extract_message_from_webhook(payload)["text"]

    def test_audio_message(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.a", "timestamp": "1710000000", "type": "audio", "audio": {"id": "m1"}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert "Voice" in extract_message_from_webhook(payload)["text"]

    def test_button_reply(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.b", "timestamp": "1710000000", "type": "interactive", "interactive": {"type": "button_reply", "button_reply": {"id": "btn1", "title": "Yes"}}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert extract_message_from_webhook(payload)["text"] == "Yes"

    def test_list_reply(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.l", "timestamp": "1710000000", "type": "interactive", "interactive": {"type": "list_reply", "list_reply": {"id": "o1", "title": "Option A"}}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert extract_message_from_webhook(payload)["text"] == "Option A"

    def test_status_update_ignored(self):
        payload = {"entry": [{"changes": [{"value": {"statuses": [{"id": "wamid.x", "status": "delivered"}]}}]}]}
        assert extract_message_from_webhook(payload) is None

    def test_empty_payload(self):
        assert extract_message_from_webhook({}) is None

    def test_unknown_type(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.s", "timestamp": "1710000000", "type": "sticker", "sticker": {"id": "m1"}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert "sticker" in extract_message_from_webhook(payload)["text"]

    def test_document(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.d", "timestamp": "1710000000", "type": "document", "document": {"caption": "Report"}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert extract_message_from_webhook(payload)["text"] == "Report"

    def test_video(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.v", "timestamp": "1710000000", "type": "video", "video": {"caption": "Funny"}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert extract_message_from_webhook(payload)["text"] == "Funny"

    def test_no_contacts(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.nc", "timestamp": "1710000000", "type": "text", "text": {"body": "Hello"}}],
        }}]}]}
        assert extract_message_from_webhook(payload)["name"] == ""


class TestWebhookRoute:
    def test_verify_success(self):
        from fastapi.testclient import TestClient
        from api.routes.whatsapp_webhook import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        with patch.dict("os.environ", {"WHATSAPP_VERIFY_TOKEN": "tok123"}):
            client = TestClient(app)
            resp = client.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "tok123", "hub.challenge": "abc"})
        assert resp.status_code == 200
        assert resp.text == "abc"

    def test_verify_wrong_token(self):
        from fastapi.testclient import TestClient
        from api.routes.whatsapp_webhook import router
        from fastapi import FastAPI
        app = FastAPI()
        app.include_router(router)
        with patch.dict("os.environ", {"WHATSAPP_VERIFY_TOKEN": "correct"}):
            client = TestClient(app)
            resp = client.get("/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "abc"})
        assert resp.status_code == 403


class TestOnboarding:
    def test_generate_link_code(self):
        from api.routes.whatsapp_webhook import _generate_link_code, _link_codes
        code = _generate_link_code("353891234567")
        assert len(code) == 6
        assert code.isdigit()
        assert code in _link_codes
        assert _link_codes[code]["phone"] == "353891234567"

    def test_generate_replaces_existing(self):
        from api.routes.whatsapp_webhook import _generate_link_code, _link_codes
        code1 = _generate_link_code("353891234567")
        code2 = _generate_link_code("353891234567")
        assert code1 != code2
        assert code1 not in _link_codes

    def test_expired_codes_cleaned(self):
        from api.routes.whatsapp_webhook import _generate_link_code, _link_codes
        _link_codes["999999"] = {"phone": "123", "created_at": 0, "expires_at": 0}
        _generate_link_code("353891234567")
        assert "999999" not in _link_codes

    @pytest.mark.asyncio
    async def test_unlinked_user_welcome(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user, _welcomed_phones
        _welcomed_phones.pop("353891234567", None)
        with patch("api.routes.whatsapp_webhook.send_interactive_buttons", new_callable=AsyncMock) as mock_btn:
            await _handle_unlinked_user("353891234567", "John", "hey there")
        mock_btn.assert_called_once()
        assert "Bem-vindo" in str(mock_btn.call_args)

    @pytest.mark.asyncio
    async def test_unlinked_user_link_request(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user
        with (
            patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt,
            patch("api.routes.whatsapp_webhook.send_link_button", new_callable=AsyncMock),
        ):
            await _handle_unlinked_user("353891234567", "John", "vincular")
        mock_txt.assert_called_once()
        assert "código" in mock_txt.call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_unlinked_user_create(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user
        with patch("api.routes.whatsapp_webhook.send_link_button", new_callable=AsyncMock) as mock_btn:
            await _handle_unlinked_user("353891234567", "John", "criar conta")
        mock_btn.assert_called_once()
        assert "app.capivarex.com" in str(mock_btn.call_args)

    @pytest.mark.asyncio
    async def test_unlinked_user_guest(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user
        with patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt:
            await _handle_unlinked_user("353891234567", "John", "visitante")
        mock_txt.assert_called_once()
        assert "Modo Visitante" in mock_txt.call_args[0][1]

    @pytest.mark.asyncio
    async def test_unlinked_code_hint(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user, _welcomed_phones
        _welcomed_phones["353891234567"] = time.time()
        with patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt:
            await _handle_unlinked_user("353891234567", "John", "123456")
        assert "app.capivarex.com" in mock_txt.call_args[0][1]

    @pytest.mark.asyncio
    async def test_get_user_by_phone_no_db(self):
        from api.routes.whatsapp_webhook import _get_user_id_by_phone
        with patch("services.core.get_service", return_value=None):
            result = await _get_user_id_by_phone("353891234567")
        assert result == ""

    @pytest.mark.asyncio
    async def test_get_user_by_phone_found(self):
        from api.routes.whatsapp_webhook import _get_user_id_by_phone
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value = MagicMock(data=[{"id": "user-123"}])
        with patch("services.core.get_service", return_value=mock_db):
            result = await _get_user_id_by_phone("353891234567")
        assert result == "user-123"

    @pytest.mark.asyncio
    async def test_guest_fallback(self):
        from api.routes.whatsapp_webhook import _handle_guest_message
        with (
            patch("services.core.get_service", return_value=None),
            patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt,
        ):
            await _handle_guest_message("353891234567", "John", "what is 2+2?")
        assert "vincular" in mock_txt.call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_process_linked_error(self):
        from api.routes.whatsapp_webhook import _process_linked_user
        with (
            patch("services.core.get_service", side_effect=Exception("DB error")),
            patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt,
        ):
            await _process_linked_user("u1", "353891234567", "John", "hello")
        assert "errado" in mock_txt.call_args[0][1].lower()


class TestInteractiveEdgeCases:
    @pytest.mark.asyncio
    async def test_buttons_error(self):
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("fail")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_interactive_buttons("353891234567", "test", [{"id": "1", "title": "OK"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_buttons_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"message": "bad"}}
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_interactive_buttons("353891234567", "test", [{"id": "1", "title": "OK"}])
        assert result is None

    @pytest.mark.asyncio
    async def test_link_button_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messages": [{"id": "wamid.lnk"}]}
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_link_button("353891234567", "test", "Click", "https://app.capivarex.com", header="H", footer="F")
        assert result is not None

    @pytest.mark.asyncio
    async def test_link_button_error(self):
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("fail")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_link_button("353891234567", "test", "Click", "https://x.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_link_button_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {"error": {"message": "bad"}}
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await send_link_button("353891234567", "test", "Click", "https://x.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_menu_shows_welcome(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user
        with patch("api.routes.whatsapp_webhook.send_interactive_buttons", new_callable=AsyncMock) as mock_btn:
            await _handle_unlinked_user("353000000000", "Test", "menu")
        mock_btn.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_profile_not_configured(self):
        from services.integrations.whatsapp_service import update_business_profile
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            result = await update_business_profile(about="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_profile_success(self):
        from services.integrations.whatsapp_service import update_business_profile
        mock_response = MagicMock()
        mock_response.status_code = 200
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await update_business_profile(about="Capivarex AI", description="Your AI assistant", websites=["https://app.capivarex.com"])
        assert result is True

    @pytest.mark.asyncio
    async def test_guest_with_gpt(self):
        from api.routes.whatsapp_webhook import _handle_guest_message
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.return_value = "2+2 equals 4! Math is fun."
        with (
            patch("services.core.get_service", return_value=mock_openai),
            patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt,
        ):
            await _handle_guest_message("353891234567", "John", "what is 2+2?")
        assert "4" in mock_txt.call_args[0][1]

    @pytest.mark.asyncio
    async def test_guest_gpt_failure(self):
        from api.routes.whatsapp_webhook import _handle_guest_message
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.chat_completion.side_effect = Exception("GPT down")
        with (
            patch("services.core.get_service", return_value=mock_openai),
            patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt,
        ):
            await _handle_guest_message("353891234567", "", "hello")
        assert "vincular" in mock_txt.call_args[0][1].lower()

    def test_document_no_caption(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.d2", "timestamp": "1710000000", "type": "document", "document": {"id": "m1"}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert "Document" in extract_message_from_webhook(payload)["text"]

    def test_video_no_caption(self):
        payload = {"entry": [{"changes": [{"value": {
            "messages": [{"from": "353891234567", "id": "wamid.v2", "timestamp": "1710000000", "type": "video", "video": {"id": "m1"}}],
            "contacts": [{"profile": {"name": "T"}}],
        }}]}]}
        assert "Video" in extract_message_from_webhook(payload)["text"]

    @pytest.mark.asyncio
    async def test_update_profile_exception(self):
        from services.integrations.whatsapp_service import update_business_profile
        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "t", "WHATSAPP_PHONE_NUMBER_ID": "1"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.side_effect = Exception("fail")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client
            result = await update_business_profile(about="test")
        assert result is False

    @pytest.mark.asyncio
    async def test_guest_mode_subsequent_message(self):
        from api.routes.whatsapp_webhook import _handle_unlinked_user, _welcomed_phones
        _welcomed_phones["353000111222"] = time.time()  # Already welcomed
        with (
            patch("services.core.get_service", return_value=None),
            patch("api.routes.whatsapp_webhook.send_text_message", new_callable=AsyncMock) as mock_txt,
        ):
            await _handle_unlinked_user("353000111222", "Test", "what time is it?")
        mock_txt.assert_called_once()
