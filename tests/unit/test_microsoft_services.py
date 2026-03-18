"""Tests for Microsoft OAuth, Outlook, and Microsoft Calendar services."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Microsoft OAuth Service
# ---------------------------------------------------------------------------


class TestMicrosoftOAuth:
    def test_get_authorization_url(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        svc.client_id = "test-client-id"
        url = svc.get_authorization_url("user123")
        assert "test-client-id" in url
        assert "authorize" in url
        assert "state=" in url  # user_id is base64-encoded in state

    def test_get_authorization_url_with_extra(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        svc.client_id = "cid"
        url = svc.get_authorization_url("u1", extra_state="test")
        assert "authorize" in url

    @pytest.mark.asyncio
    async def test_exchange_code(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "services.auth.microsoft_oauth_service.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc.exchange_code("test-code")
        assert result["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_get_user_info(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "mail": "user@outlook.com",
            "displayName": "Test",
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "services.auth.microsoft_oauth_service.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_resp))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc.get_user_info("fake-token")
        assert result["mail"] == "user@outlook.com"

    @pytest.mark.asyncio
    async def test_save_tokens_no_db(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        with patch(
            "services.auth.microsoft_oauth_service.get_service", return_value=None
        ):
            result = await svc.save_tokens("u1", {"access_token": "at"})
        assert result is False

    @pytest.mark.asyncio
    async def test_get_valid_token_no_db(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        with patch(
            "services.auth.microsoft_oauth_service.get_service", return_value=None
        ):
            result = await svc.get_valid_token("u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_disconnect_no_db(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        with patch(
            "services.auth.microsoft_oauth_service.get_service", return_value=None
        ):
            result = await svc.disconnect("u1")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_connected_empty(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        with patch(
            "services.auth.microsoft_oauth_service.get_service", return_value=None
        ):
            result = await svc.is_connected("u1")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_connected_accounts_no_db(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        with patch(
            "services.auth.microsoft_oauth_service.get_service", return_value=None
        ):
            result = await svc.get_connected_accounts("u1")
        assert result == []

    def test_singleton(self):
        import services.auth.microsoft_oauth_service as mod

        mod._instance = None
        svc1 = mod.get_microsoft_oauth()
        svc2 = mod.get_microsoft_oauth()
        assert svc1 is svc2
        mod._instance = None  # cleanup


# ---------------------------------------------------------------------------
# Outlook Service
# ---------------------------------------------------------------------------


class TestOutlookService:
    @pytest.mark.asyncio
    async def test_initialize(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        await svc._initialize()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_list_emails_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.list_emails("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_list_emails_success(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "id": "msg1",
                    "subject": "Test Email",
                    "from": {
                        "emailAddress": {"address": "sender@test.com", "name": "Sender"}
                    },
                    "receivedDateTime": "2026-03-17T10:00:00Z",
                    "bodyPreview": "Hello world",
                    "isRead": False,
                    "hasAttachments": False,
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(
                return_value="fake-token"
            )
            with patch(
                "services.integrations.outlook_service.httpx.AsyncClient"
            ) as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(request=AsyncMock(return_value=mock_resp))
                )
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await svc.list_emails("u1")

        assert len(result) == 1
        assert result[0]["subject"] == "Test Email"
        assert result[0]["provider"] == "microsoft"

    @pytest.mark.asyncio
    async def test_send_email_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.send_email("u1", "to@test.com", "Subject", "Body")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_profile_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.get_profile("u1")
        assert result is None


# ---------------------------------------------------------------------------
# Microsoft Calendar Service
# ---------------------------------------------------------------------------


class TestMicrosoftCalendarService:
    @pytest.mark.asyncio
    async def test_initialize(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        await svc._initialize()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_get_upcoming_no_token(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.async_get_upcoming_events("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_upcoming_success(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "value": [
                {
                    "id": "ev1",
                    "subject": "Team Meeting",
                    "start": {"dateTime": "2026-03-18T14:00:00"},
                    "end": {"dateTime": "2026-03-18T15:00:00"},
                    "location": {"displayName": "Room A"},
                    "bodyPreview": "Agenda",
                    "attendees": [],
                    "webLink": "https://outlook.com/ev1",
                    "isOnlineMeeting": True,
                    "onlineMeetingUrl": "https://teams.microsoft.com/meet/123",
                }
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(
                return_value="fake-token"
            )
            with patch(
                "services.integrations.outlook_calendar_service.httpx.AsyncClient"
            ) as mock_client:
                mock_client.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(request=AsyncMock(return_value=mock_resp))
                )
                mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await svc.async_get_upcoming_events("u1")

        assert len(result) == 1
        assert result[0]["summary"] == "Team Meeting"
        assert result[0]["provider"] == "microsoft"

    @pytest.mark.asyncio
    async def test_create_event_no_token(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.async_create_event(
                "u1", "Test", "2026-03-18T10:00:00", "2026-03-18T11:00:00"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_get_next_meeting_empty(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.async_get_next_meeting("u1")
        assert result is None

    def test_format_event(self):
        from services.integrations.outlook_calendar_service import _format_event

        ev = {
            "id": "ev1",
            "subject": "Test",
            "start": {"dateTime": "2026-03-18T10:00:00"},
            "end": {"dateTime": "2026-03-18T11:00:00"},
            "location": {"displayName": "Room B"},
            "bodyPreview": "Notes",
            "attendees": [{"emailAddress": {"address": "a@b.com"}}],
            "webLink": "https://link",
            "isOnlineMeeting": False,
            "onlineMeetingUrl": "",
        }
        result = _format_event(ev)
        assert result["summary"] == "Test"
        assert result["location"] == "Room B"
        assert result["provider"] == "microsoft"
        assert result["attendees"] == ["a@b.com"]


# ---------------------------------------------------------------------------
# Microsoft Auth Routes
# ---------------------------------------------------------------------------


class TestOutlookHelpers:
    def test_extract_sender(self):
        from services.integrations.outlook_service import (
            _extract_sender,
            _extract_sender_name,
        )

        msg = {"from": {"emailAddress": {"address": "a@b.com", "name": "Alice"}}}
        assert _extract_sender(msg) == "a@b.com"
        assert _extract_sender_name(msg) == "Alice"

    def test_extract_sender_missing(self):
        from services.integrations.outlook_service import (
            _extract_sender,
            _extract_sender_name,
        )

        assert _extract_sender({}) == "unknown"
        assert _extract_sender_name({}) == ""

    @pytest.mark.asyncio
    async def test_mark_as_read_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.mark_as_read("u1", "msg1")
        assert result is False

    @pytest.mark.asyncio
    async def test_archive_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.archive("u1", "msg1")
        assert result is False

    @pytest.mark.asyncio
    async def test_trash_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.trash("u1", "msg1")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_email_body_no_token(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.get_email_body("u1", "msg1")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_today_events(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.async_get_today_events("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_create_meeting_no_token(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.async_create_meeting(
                "u1", "Meeting", "2026-03-18T10:00:00", "2026-03-18T11:00:00"
            )
        assert result is None

    @pytest.mark.asyncio
    async def test_refresh_token(self):
        from services.auth.microsoft_oauth_service import MicrosoftOAuthService

        svc = MicrosoftOAuthService()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"access_token": "new_at", "expires_in": 3600}
        mock_resp.raise_for_status = MagicMock()
        with patch(
            "services.auth.microsoft_oauth_service.httpx.AsyncClient"
        ) as mock_client:
            mock_client.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
            )
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc.refresh_token("old_rt")
        assert result["access_token"] == "new_at"


class TestOutlookApi401:
    @pytest.mark.asyncio
    async def test_api_401_returns_none(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value="tok")
            with patch("services.integrations.outlook_service.httpx.AsyncClient") as mc:
                mc.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(request=AsyncMock(return_value=mock_resp))
                )
                mc.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await svc.list_emails("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_api_204_returns_ok(self):
        from services.integrations.outlook_service import OutlookService

        svc = OutlookService()
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value="tok")
            with patch("services.integrations.outlook_service.httpx.AsyncClient") as mc:
                mc.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(request=AsyncMock(return_value=mock_resp))
                )
                mc.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await svc.mark_as_read("u1", "msg1")
        assert result is True

    @pytest.mark.asyncio
    async def test_calendar_api_401(self):
        from services.integrations.outlook_calendar_service import (
            MicrosoftCalendarService,
        )

        svc = MicrosoftCalendarService()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        with patch(
            "services.auth.microsoft_oauth_service.get_microsoft_oauth"
        ) as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value="tok")
            with patch(
                "services.integrations.outlook_calendar_service.httpx.AsyncClient"
            ) as mc:
                mc.return_value.__aenter__ = AsyncMock(
                    return_value=MagicMock(request=AsyncMock(return_value=mock_resp))
                )
                mc.return_value.__aexit__ = AsyncMock(return_value=False)
                result = await svc.async_get_upcoming_events("u1")
        assert result == []


class TestMicrosoftAuthRoutes:
    def test_router_prefix(self):
        from api.routes.microsoft_auth import router

        assert "/api/v1/auth/microsoft" in router.prefix

    def test_success_html(self):
        from api.routes.microsoft_auth import _SUCCESS_HTML

        assert "Microsoft Connected" in _SUCCESS_HTML

    def test_error_html(self):
        from api.routes.microsoft_auth import _ERROR_HTML

        assert "Connection Failed" in _ERROR_HTML
