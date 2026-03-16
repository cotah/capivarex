"""Tests for WhatsApp service + webhook — send/receive messages via Meta Cloud API."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.integrations.whatsapp_service import (
    is_configured,
    send_text_message,
    mark_as_read,
    extract_message_from_webhook,
    _split_message,
)


class TestConfiguration:
    """Tests for WhatsApp config check."""

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
    """Tests for sending messages."""

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
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "test-token", "WHATSAPP_PHONE_NUMBER_ID": "123456"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await send_text_message("+353 89 123 4567", "Hello from Capivarex!")

        assert result is not None
        assert result["messages"][0]["id"] == "wamid.test123"

    @pytest.mark.asyncio
    async def test_send_api_error(self):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.json.return_value = {"error": {"message": "Invalid token"}}

        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "bad-token", "WHATSAPP_PHONE_NUMBER_ID": "123456"}),
            patch("services.integrations.whatsapp_service.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await send_text_message("353891234567", "Hello")

        assert result is None


class TestMarkAsRead:
    """Tests for mark as read."""

    @pytest.mark.asyncio
    async def test_mark_not_configured(self):
        with patch.dict("os.environ", {"WHATSAPP_TOKEN": "", "WHATSAPP_PHONE_NUMBER_ID": ""}):
            result = await mark_as_read("wamid.test")
        assert result is False


class TestSplitMessage:
    """Tests for message splitting."""

    def test_short_message(self):
        chunks = _split_message("Hello", max_len=4096)
        assert len(chunks) == 1
        assert chunks[0] == "Hello"

    def test_long_message(self):
        text = "Hello world. " * 500  # ~6500 chars
        chunks = _split_message(text, max_len=4096)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_exact_limit(self):
        text = "a" * 4096
        chunks = _split_message(text, max_len=4096)
        assert len(chunks) == 1


class TestExtractMessage:
    """Tests for webhook payload extraction."""

    def test_text_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.abc123",
                            "timestamp": "1710000000",
                            "type": "text",
                            "text": {"body": "Hello Capivarex!"},
                        }],
                        "contacts": [{"profile": {"name": "John Doe"}}],
                    }
                }]
            }]
        }

        result = extract_message_from_webhook(payload)
        assert result is not None
        assert result["from"] == "353891234567"
        assert result["name"] == "John Doe"
        assert result["text"] == "Hello Capivarex!"
        assert result["type"] == "text"

    def test_image_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.img123",
                            "timestamp": "1710000000",
                            "type": "image",
                            "image": {"caption": "Check this out"},
                        }],
                        "contacts": [{"profile": {"name": "Ana"}}],
                    }
                }]
            }]
        }

        result = extract_message_from_webhook(payload)
        assert result is not None
        assert result["text"] == "Check this out"
        assert result["type"] == "image"

    def test_location_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.loc123",
                            "timestamp": "1710000000",
                            "type": "location",
                            "location": {"latitude": 53.3498, "longitude": -6.2603},
                        }],
                        "contacts": [{"profile": {"name": "Marcos"}}],
                    }
                }]
            }]
        }

        result = extract_message_from_webhook(payload)
        assert result is not None
        assert "53.3498" in result["text"]

    def test_status_update_ignored(self):
        """Status updates (delivered, read) should return None."""
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "statuses": [{"id": "wamid.xxx", "status": "delivered"}],
                    }
                }]
            }]
        }

        result = extract_message_from_webhook(payload)
        assert result is None

    def test_empty_payload(self):
        result = extract_message_from_webhook({})
        assert result is None

    def test_audio_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.audio",
                            "timestamp": "1710000000",
                            "type": "audio",
                            "audio": {"id": "media123"},
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }

        result = extract_message_from_webhook(payload)
        assert result is not None
        assert "Voice message" in result["text"]

    def test_button_reply(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.btn",
                            "timestamp": "1710000000",
                            "type": "interactive",
                            "interactive": {
                                "type": "button_reply",
                                "button_reply": {"id": "btn1", "title": "Yes, confirm"},
                            },
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }

        result = extract_message_from_webhook(payload)
        assert result is not None
        assert result["text"] == "Yes, confirm"


class TestWebhookRoute:
    """Tests for the FastAPI webhook endpoint."""

    def test_verify_webhook_success(self):
        from fastapi.testclient import TestClient
        from api.routes.whatsapp_webhook import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch.dict("os.environ", {"WHATSAPP_VERIFY_TOKEN": "test_token_123"}):
            client = TestClient(app)
            resp = client.get(
                "/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "test_token_123",
                    "hub.challenge": "challenge_abc",
                },
            )
        assert resp.status_code == 200
        assert resp.text == "challenge_abc"

    def test_verify_webhook_wrong_token(self):
        from fastapi.testclient import TestClient
        from api.routes.whatsapp_webhook import router
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with patch.dict("os.environ", {"WHATSAPP_VERIFY_TOKEN": "correct_token"}):
            client = TestClient(app)
            resp = client.get(
                "/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong_token",
                    "hub.challenge": "challenge_abc",
                },
            )
        assert resp.status_code == 403


class TestWebhookProcessing:
    """Tests for message processing in webhook."""

    @pytest.mark.asyncio
    async def test_process_no_user_found(self):
        from api.routes.whatsapp_webhook import _process_message

        with patch("api.routes.whatsapp_webhook._get_user_id_by_phone", return_value=""):
            result = await _process_message("353891234567", "John", "Hello")
        assert "app.capivarex.com" in result
        assert "John" in result

    @pytest.mark.asyncio
    async def test_process_no_user_no_name(self):
        from api.routes.whatsapp_webhook import _process_message

        with patch("api.routes.whatsapp_webhook._get_user_id_by_phone", return_value=""):
            result = await _process_message("353891234567", "", "Hello")
        assert "Capivarex" in result

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
        mock_db.get_client.return_value.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"id": "user-uuid-123"}]
        )

        with patch("services.core.get_service", return_value=mock_db):
            result = await _get_user_id_by_phone("353891234567")
        assert result == "user-uuid-123"

    def test_document_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.doc",
                            "timestamp": "1710000000",
                            "type": "document",
                            "document": {"caption": "Monthly report"},
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert result is not None
        assert result["text"] == "Monthly report"

    def test_video_message(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.vid",
                            "timestamp": "1710000000",
                            "type": "video",
                            "video": {"caption": "Funny clip"},
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert result["text"] == "Funny clip"

    def test_list_reply(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.list",
                            "timestamp": "1710000000",
                            "type": "interactive",
                            "interactive": {
                                "type": "list_reply",
                                "list_reply": {"id": "opt1", "title": "Option A"},
                            },
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert result["text"] == "Option A"

    def test_unknown_message_type(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.sticker",
                            "timestamp": "1710000000",
                            "type": "sticker",
                            "sticker": {"id": "media123"},
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert result is not None
        assert "sticker" in result["text"]

    def test_no_contacts_in_payload(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.noname",
                            "timestamp": "1710000000",
                            "type": "text",
                            "text": {"body": "Hello"},
                        }],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert result is not None
        assert result["name"] == ""
        assert result["text"] == "Hello"

    def test_image_no_caption(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.img2",
                            "timestamp": "1710000000",
                            "type": "image",
                            "image": {"id": "media456"},
                        }],
                        "contacts": [],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert result is not None
        assert "Image" in result["text"]

    @pytest.mark.asyncio
    async def test_mark_as_read_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200

        with (
            patch.dict("os.environ", {"WHATSAPP_TOKEN": "token", "WHATSAPP_PHONE_NUMBER_ID": "123"}),
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
    async def test_send_cleans_phone_number(self):
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

            # Verify phone was cleaned
            call_args = mock_client.post.call_args
            payload = call_args.kwargs.get("json", call_args[1].get("json", {}))
            assert payload["to"] == "353899582889"

    def test_split_at_newline(self):
        text = "Line 1\nLine 2\n" + "x" * 4090
        chunks = _split_message(text, max_len=4096)
        assert len(chunks) >= 2

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
    async def test_mark_as_read_exception(self):
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

    def test_document_no_caption(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.doc2",
                            "timestamp": "1710000000",
                            "type": "document",
                            "document": {"id": "media789"},
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert "Document" in result["text"]

    def test_video_no_caption(self):
        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "messages": [{
                            "from": "353891234567",
                            "id": "wamid.vid2",
                            "timestamp": "1710000000",
                            "type": "video",
                            "video": {"id": "media789"},
                        }],
                        "contacts": [{"profile": {"name": "Test"}}],
                    }
                }]
            }]
        }
        result = extract_message_from_webhook(payload)
        assert "Video" in result["text"]

    @pytest.mark.asyncio
    async def test_process_exception(self):
        from api.routes.whatsapp_webhook import _process_message

        with patch("api.routes.whatsapp_webhook._get_user_id_by_phone", side_effect=Exception("DB error")):
            result = await _process_message("353891234567", "John", "Hello")
        assert "went wrong" in result.lower()
