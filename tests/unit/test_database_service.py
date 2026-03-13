"""Extended unit tests for DatabaseService — more coverage for CRUD methods."""

import asyncio
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock


def _make_service():
    """Create a DatabaseService with mocked Supabase client."""
    from services.infrastructure.database import DatabaseService

    svc = DatabaseService()
    svc.url = "https://fake.supabase.co"
    svc.key = "fake-key"
    svc._initialized = True
    svc.client = MagicMock()
    return svc


def _chain_result(data):
    """Return an execute() result with .data attribute."""
    result = Mock()
    result.data = data
    return result


# -------------------------------------------------------------------
# Initialization
# -------------------------------------------------------------------


class TestDatabaseInit:
    @pytest.mark.asyncio
    async def test_init_missing_key(self):
        from services.infrastructure.database import DatabaseService
        from services.core import ServiceConfigurationError

        svc = DatabaseService()
        with patch.dict(
            "os.environ",
            {"SUPABASE_URL": "url", "SUPABASE_SERVICE_KEY": ""},
            clear=False,
        ):
            with pytest.raises(ServiceConfigurationError, match="SUPABASE_SERVICE_KEY"):
                await svc._initialize()


# -------------------------------------------------------------------
# get_user_by_id
# -------------------------------------------------------------------


class TestGetUserById:
    _UUID = "00000000-0000-4000-8000-000000000001"

    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        user = {"id": self._UUID, "full_name": "Henri"}
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [user]
        )
        result = await svc.get_user_by_id(self._UUID)
        assert result["full_name"] == "Henri"

    @pytest.mark.asyncio
    async def test_not_found(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_user_by_id(self._UUID)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self):
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_user_by_id(self._UUID)
        assert result is None

    @pytest.mark.asyncio
    async def test_non_uuid_returns_none(self):
        """Telegram numeric IDs should be rejected gracefully."""
        svc = _make_service()
        result = await svc.get_user_by_id("6316076982")
        assert result is None
        # DB should never be queried
        svc.client.table.assert_not_called()


# -------------------------------------------------------------------
# update_user_preferences
# -------------------------------------------------------------------


class TestUpdateUserPreferences:
    @pytest.mark.asyncio
    async def test_success(self):
        svc = _make_service()
        svc.client.table.return_value.update.return_value.eq.return_value.execute.return_value = _chain_result(
            {"id": "00000000-0000-0000-0000-000000000001"}
        )
        result = await svc.update_user_preferences("00000000-0000-0000-0000-000000000001", {"locale": "pt_BR"})
        assert result is True

    @pytest.mark.asyncio
    async def test_failure(self):
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db")
        result = await svc.update_user_preferences("00000000-0000-0000-0000-000000000001", {})
        assert result is False


# -------------------------------------------------------------------
# Proactivity preferences
# -------------------------------------------------------------------


class TestProactivityPreferences:
    @pytest.mark.asyncio
    async def test_get_preferences(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"user_id": "00000000-0000-0000-0000-000000000001", "enabled": True}]
        )
        result = await svc.get_proactivity_preferences("00000000-0000-0000-0000-000000000001")
        assert result["enabled"] is True

    @pytest.mark.asyncio
    async def test_get_preferences_not_found(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_proactivity_preferences("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_create(self):
        svc = _make_service()
        # Simulate no existing record
        svc.get_proactivity_preferences = AsyncMock(return_value=None)
        svc.client.table.return_value.insert.return_value.execute.return_value = Mock()
        result = await svc.update_proactivity_preferences("00000000-0000-0000-0000-000000000001", True)
        assert result is True

    @pytest.mark.asyncio
    async def test_update_existing(self):
        svc = _make_service()
        svc.get_proactivity_preferences = AsyncMock(return_value={"user_id": "00000000-0000-0000-0000-000000000001"})
        svc.client.table.return_value.update.return_value.eq.return_value.execute.return_value = Mock()
        result = await svc.update_proactivity_preferences("00000000-0000-0000-0000-000000000001", False)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_all_enabled(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"user_id": "00000000-0000-0000-0000-000000000001"}]
        )
        result = await svc.get_all_users_with_proactivity_enabled()
        assert len(result) == 1


# -------------------------------------------------------------------
# User context
# -------------------------------------------------------------------


class TestUserContext:
    @pytest.mark.asyncio
    async def test_save_context_create(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        svc.client.table.return_value.insert.return_value.execute.return_value = Mock()
        result = await svc.save_user_context("00000000-0000-0000-0000-000000000001", "location", {"lat": 53.3})
        assert result is True

    @pytest.mark.asyncio
    async def test_save_context_update(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"id": "existing"}]
        )
        svc.client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = Mock()
        result = await svc.save_user_context("00000000-0000-0000-0000-000000000001", "location", {"lat": 53.3})
        assert result is True

    @pytest.mark.asyncio
    async def test_get_context_found(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"data": {"lat": 53.3}}]
        )
        result = await svc.get_user_context("00000000-0000-0000-0000-000000000001", "location")
        assert result == {"lat": 53.3}

    @pytest.mark.asyncio
    async def test_get_context_not_found(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_user_context("00000000-0000-0000-0000-000000000001", "location")
        assert result is None


# -------------------------------------------------------------------
# Calendar credentials
# -------------------------------------------------------------------


class TestCalendarCredentials:
    @pytest.mark.asyncio
    async def test_save_new(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        svc.client.table.return_value.insert.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_calendar_credentials("00000000-0000-0000-0000-000000000001", {"token": "tok"})
        assert result is True

    @pytest.mark.asyncio
    async def test_get_creds(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"credentials": "encrypted_data"}]
        )
        with patch(
            "services.infrastructure.database.decrypt_token",
            return_value='{"token":"tok"}',
        ):
            result = await svc.get_calendar_credentials("00000000-0000-0000-0000-000000000001")
        assert result == {"token": "tok"}

    @pytest.mark.asyncio
    async def test_get_creds_not_found(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_calendar_credentials("00000000-0000-0000-0000-000000000001")
        assert result is None


# -------------------------------------------------------------------
# Car connections
# -------------------------------------------------------------------


class TestCarConnections:
    @pytest.mark.asyncio
    async def test_save_new(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        svc.client.table.return_value.insert.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_car_connection("00000000-0000-0000-0000-000000000001", "v1", "at", "rt", "2026-12-31")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_connection(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"access_token": "enc_at", "refresh_token": "enc_rt"}]
        )
        with patch(
            "services.infrastructure.database.decrypt_token", side_effect=["at", "rt"]
        ):
            result = await svc.get_car_connection("00000000-0000-0000-0000-000000000001")
        assert result["access_token"] == "at"

    @pytest.mark.asyncio
    async def test_get_connection_none(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_car_connection("00000000-0000-0000-0000-000000000001")
        assert result is None


# -------------------------------------------------------------------
# SmartThings connections
# -------------------------------------------------------------------


class TestSmartThingsConnections:
    @pytest.mark.asyncio
    async def test_save_new(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        svc.client.table.return_value.insert.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_smartthings_connection(
                "00000000-0000-0000-0000-000000000001", "at", "rt", "2026-12-31", "app1", "loc1"
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_get_connection(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"access_token": "enc_at", "refresh_token": "enc_rt"}]
        )
        with patch(
            "services.infrastructure.database.decrypt_token", side_effect=["at", "rt"]
        ):
            result = await svc.get_smartthings_connection("00000000-0000-0000-0000-000000000001")
        assert result["access_token"] == "at"


# -------------------------------------------------------------------
# GitHub connections
# -------------------------------------------------------------------


class TestGithubConnections:
    @pytest.mark.asyncio
    async def test_save_new(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        svc.client.table.return_value.insert.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_github_connection("00000000-0000-0000-0000-000000000001", "ghuser", "gh_token")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_connection(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"access_token": "enc", "github_username": "ghuser"}]
        )
        with patch(
            "services.infrastructure.database.decrypt_token", return_value="gh_token"
        ):
            result = await svc.get_github_connection("00000000-0000-0000-0000-000000000001")
        assert result["access_token"] == "gh_token"

    @pytest.mark.asyncio
    async def test_get_connection_none(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_github_connection("00000000-0000-0000-0000-000000000001")
        assert result is None


# -------------------------------------------------------------------
# Messages
# -------------------------------------------------------------------


class TestMessages:
    @pytest.mark.asyncio
    async def test_get_messages(self):
        svc = _make_service()
        msgs = [{"role": "user", "content": "hi", "created_at": "2026-01-01"}]
        svc.client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _chain_result(
            msgs
        )
        result = await svc.get_messages_for_conversation("conv1")
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_get_messages_empty(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_messages_for_conversation("conv1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_messages_exception(self):
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db down")
        result = await svc.get_messages_for_conversation("conv1")
        assert result == []


# -------------------------------------------------------------------
# get_client
# -------------------------------------------------------------------


class TestGetClient:
    def test_returns_client(self):
        svc = _make_service()
        assert svc.get_client() is svc.client

    def test_raises_when_not_initialized(self):
        from services.infrastructure.database import DatabaseService
        from services.core import ServiceUnavailableError

        svc = DatabaseService()
        with pytest.raises(ServiceUnavailableError):
            svc.get_client()


# -------------------------------------------------------------------
# Health check
# -------------------------------------------------------------------


class TestDatabaseHealthCheck:
    @pytest.mark.asyncio
    async def test_no_client(self):
        from services.infrastructure.database import DatabaseService

        svc = DatabaseService()
        result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_timeout(self):
        """Lines 82-84: _health_check returns False on asyncio.TimeoutError."""
        svc = _make_service()
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_generic_exception(self):
        """Lines 85-87: _health_check returns False on generic Exception."""
        svc = _make_service()
        with patch("asyncio.wait_for", side_effect=RuntimeError("connection refused")):
            result = await svc._health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """Lines 72-81: _health_check returns True on successful query."""
        svc = _make_service()
        with patch("asyncio.wait_for", return_value=_chain_result([{"id": "1"}])):
            result = await svc._health_check()
        assert result is True


# -------------------------------------------------------------------
# _initialize success and failure
# -------------------------------------------------------------------


class TestDatabaseInitialize:
    @pytest.mark.asyncio
    async def test_init_missing_url(self):
        from services.infrastructure.database import DatabaseService
        from services.core import ServiceConfigurationError

        svc = DatabaseService()
        with patch.dict(
            "os.environ",
            {"SUPABASE_URL": "", "SUPABASE_SERVICE_KEY": "key"},
            clear=False,
        ):
            with pytest.raises(ServiceConfigurationError, match="SUPABASE_URL"):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_init_success(self):
        """Lines 61-65: _initialize creates client successfully."""
        from services.infrastructure.database import DatabaseService

        svc = DatabaseService()
        mock_client = MagicMock()
        with patch.dict(
            "os.environ",
            {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "key123"},
            clear=False,
        ):
            with patch(
                "services.infrastructure.database.create_client",
                return_value=mock_client,
            ) as mock_create:
                await svc._initialize()
        mock_create.assert_called_once_with("https://x.supabase.co", "key123")
        assert svc.client is mock_client

    @pytest.mark.asyncio
    async def test_init_create_client_fails(self):
        """Lines 64-65: _initialize wraps create_client failure in ServiceUnavailableError."""
        from services.infrastructure.database import DatabaseService
        from services.core import ServiceUnavailableError

        svc = DatabaseService()
        with patch.dict(
            "os.environ",
            {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "key123"},
            clear=False,
        ):
            with patch(
                "services.infrastructure.database.create_client",
                side_effect=RuntimeError("boom"),
            ):
                with pytest.raises(
                    ServiceUnavailableError, match="Failed to create Supabase client"
                ):
                    await svc._initialize()


# -------------------------------------------------------------------
# get_all_users_with_preferences
# -------------------------------------------------------------------


class TestGetAllUsersWithPreferences:
    @pytest.mark.asyncio
    async def test_success_with_proactivity(self):
        svc = _make_service()
        users = [
            {"id": "00000000-0000-0000-0000-000000000001", "proactivity_preferences": {"enabled": True}},
            {"id": "u2", "proactivity_preferences": {"enabled": False}},
            {"id": "u3", "proactivity_preferences": {}},
        ]
        svc.client.table.return_value.select.return_value.neq.return_value.execute.return_value = _chain_result(
            users
        )
        result = await svc.get_all_users_with_preferences()
        assert len(result) == 1
        assert result[0]["id"] == "00000000-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_empty_response(self):
        """Line 118: returns [] when response.data is empty."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.neq.return_value.execute.return_value = _chain_result(
            None
        )
        result = await svc.get_all_users_with_preferences()
        assert result == []

    @pytest.mark.asyncio
    async def test_exception(self):
        """Lines 132-134: exception returns []."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db down")
        result = await svc.get_all_users_with_preferences()
        assert result == []

    @pytest.mark.asyncio
    async def test_client_none_triggers_initialize(self):
        """Line 108: client is None triggers await self.initialize()."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        # After initialize, client is still None so code will hit exception path
        await svc.get_all_users_with_preferences()
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# get_user_by_telegram_id
# -------------------------------------------------------------------


class TestGetUserByTelegramId:
    @pytest.mark.asyncio
    async def test_found(self):
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"id": "00000000-0000-0000-0000-000000000001", "telegram_chat_id": "123"}]
        )
        result = await svc.get_user_by_telegram_id("123")
        assert result["id"] == "00000000-0000-0000-0000-000000000001"

    @pytest.mark.asyncio
    async def test_not_found(self):
        """Line 157: returns None when no data."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_user_by_telegram_id("unknown")
        assert result is None

    @pytest.mark.asyncio
    async def test_exception(self):
        """Lines 159-164: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_user_by_telegram_id("123")
        assert result is None

    @pytest.mark.asyncio
    async def test_client_none_triggers_initialize(self):
        """Line 147: client is None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_user_by_telegram_id("123")
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# get_user_by_id – client None path
# -------------------------------------------------------------------


class TestGetUserByIdClientNone:
    _UUID = "00000000-0000-4000-8000-000000000001"

    @pytest.mark.asyncio
    async def test_client_none_triggers_initialize(self):
        """client is None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_user_by_id(self._UUID)
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# update_user_preferences – client None path
# -------------------------------------------------------------------


class TestUpdateUserPreferencesClientNone:
    @pytest.mark.asyncio
    async def test_client_none_triggers_initialize(self):
        """Line 212: client is None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.update_user_preferences("00000000-0000-0000-0000-000000000001", {})
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# Proactivity preferences – error paths and client None
# -------------------------------------------------------------------


class TestProactivityPreferencesErrors:
    @pytest.mark.asyncio
    async def test_get_preferences_exception(self):
        """Lines 247-249: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_proactivity_preferences("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_preferences_client_none(self):
        """Line 240: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_proactivity_preferences("00000000-0000-0000-0000-000000000001")
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_preferences_exception(self):
        """Lines 267-269: exception returns False."""
        svc = _make_service()
        svc.get_proactivity_preferences = AsyncMock(side_effect=RuntimeError("db"))
        result = await svc.update_proactivity_preferences("00000000-0000-0000-0000-000000000001", True)
        assert result is False

    @pytest.mark.asyncio
    async def test_update_preferences_client_none(self):
        """Line 254: client None triggers initialize (also via get_proactivity_preferences)."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.update_proactivity_preferences("00000000-0000-0000-0000-000000000001", True)
        # initialize is called twice: once inside update_, once inside get_
        assert svc.initialize.await_count >= 1

    @pytest.mark.asyncio
    async def test_get_all_enabled_exception(self):
        """Lines 281-283: exception returns []."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_all_users_with_proactivity_enabled()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_all_enabled_client_none(self):
        """Line 274: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_all_users_with_proactivity_enabled()
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_all_enabled_empty(self):
        """Line 280: returns [] when response.data is empty."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            None
        )
        result = await svc.get_all_users_with_proactivity_enabled()
        assert result == []


# -------------------------------------------------------------------
# User context – error paths and client None
# -------------------------------------------------------------------


class TestUserContextErrors:
    @pytest.mark.asyncio
    async def test_save_context_exception(self):
        """Lines 312-314: exception returns False."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.save_user_context("00000000-0000-0000-0000-000000000001", "type", {"k": "v"})
        assert result is False

    @pytest.mark.asyncio
    async def test_save_context_client_none(self):
        """Line 294: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.save_user_context("00000000-0000-0000-0000-000000000001", "type", {"k": "v"})
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_context_exception(self):
        """Lines 328-330: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_user_context("00000000-0000-0000-0000-000000000001", "type")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_context_client_none(self):
        """Line 321: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_user_context("00000000-0000-0000-0000-000000000001", "type")
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# Car connections – error paths, update path, client None
# -------------------------------------------------------------------


class TestCarConnectionErrors:
    @pytest.mark.asyncio
    async def test_save_update_existing(self):
        """Line 360: update path when existing.data is truthy."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"id": "existing"}]
        )
        svc.client.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_car_connection("00000000-0000-0000-0000-000000000001", "v1", "at", "rt", "2026-12-31")
        assert result is True

    @pytest.mark.asyncio
    async def test_save_exception(self):
        """Lines 368-370: exception returns False."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_car_connection("00000000-0000-0000-0000-000000000001", "v1", "at", "rt", "2026-12-31")
        assert result is False

    @pytest.mark.asyncio
    async def test_save_client_none(self):
        """Line 346: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.save_car_connection("00000000-0000-0000-0000-000000000001", "v1", "at", "rt", "2026-12-31")
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_exception(self):
        """Lines 387-389: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_car_connection("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_client_none(self):
        """Line 375: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_car_connection("00000000-0000-0000-0000-000000000001")
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# SmartThings connections – error paths, update path, client None
# -------------------------------------------------------------------


class TestSmartThingsConnectionErrors:
    @pytest.mark.asyncio
    async def test_save_update_existing(self):
        """Line 422: update path when existing.data is truthy."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"id": "existing"}]
        )
        svc.client.table.return_value.update.return_value.eq.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_smartthings_connection(
                "00000000-0000-0000-0000-000000000001", "at", "rt", "2026-12-31", "app1", "loc1"
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_save_exception(self):
        """Lines 429-431: exception returns False."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_smartthings_connection(
                "00000000-0000-0000-0000-000000000001", "at", "rt", "2026-12-31", "app1", "loc1"
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_save_client_none(self):
        """Line 406: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.save_smartthings_connection(
            "00000000-0000-0000-0000-000000000001", "at", "rt", "2026-12-31", "app1", "loc1"
        )
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_not_found(self):
        """Line 445: returns None when response.data is empty."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            []
        )
        result = await svc.get_smartthings_connection("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_exception(self):
        """Lines 450-452: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_smartthings_connection("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_client_none(self):
        """Line 438: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_smartthings_connection("00000000-0000-0000-0000-000000000001")
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# Calendar credentials – error paths, update path, client None
# -------------------------------------------------------------------


class TestCalendarCredentialsErrors:
    @pytest.mark.asyncio
    async def test_save_update_existing(self):
        """Line 473: update path when existing.data is truthy."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"id": "existing"}]
        )
        svc.client.table.return_value.update.return_value.eq.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_calendar_credentials("00000000-0000-0000-0000-000000000001", {"token": "tok"})
        assert result is True

    @pytest.mark.asyncio
    async def test_save_exception(self):
        """Lines 482-484: exception returns False."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.save_calendar_credentials("00000000-0000-0000-0000-000000000001", {"token": "tok"})
        assert result is False

    @pytest.mark.asyncio
    async def test_save_client_none(self):
        """Line 463: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.save_calendar_credentials("00000000-0000-0000-0000-000000000001", {"token": "tok"})
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_exception(self):
        """Lines 502-504: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_calendar_credentials("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_client_none(self):
        """Line 491: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_calendar_credentials("00000000-0000-0000-0000-000000000001")
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# GitHub connections – error paths, update path, client None
# -------------------------------------------------------------------


class TestGithubConnectionErrors:
    @pytest.mark.asyncio
    async def test_save_update_existing(self):
        """Line 528: update path when existing.data is truthy."""
        svc = _make_service()
        svc.client.table.return_value.select.return_value.eq.return_value.execute.return_value = _chain_result(
            [{"id": "existing"}]
        )
        svc.client.table.return_value.update.return_value.eq.return_value.execute.return_value = Mock()
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_github_connection("00000000-0000-0000-0000-000000000001", "ghuser", "gh_token")
        assert result is True

    @pytest.mark.asyncio
    async def test_save_exception(self):
        """Lines 535-537: exception returns False."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        with patch(
            "services.infrastructure.database.encrypt_token", return_value="enc"
        ):
            result = await svc.save_github_connection("00000000-0000-0000-0000-000000000001", "ghuser", "gh_token")
        assert result is False

    @pytest.mark.asyncio
    async def test_save_client_none(self):
        """Line 515: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.save_github_connection("00000000-0000-0000-0000-000000000001", "ghuser", "gh_token")
        svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_exception(self):
        """Lines 555-557: exception returns None."""
        svc = _make_service()
        svc.client.table.side_effect = RuntimeError("db error")
        result = await svc.get_github_connection("00000000-0000-0000-0000-000000000001")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_client_none(self):
        """Line 544: client None triggers initialize."""
        svc = _make_service()
        svc.client = None
        svc.initialize = AsyncMock()
        await svc.get_github_connection("00000000-0000-0000-0000-000000000001")
        svc.initialize.assert_awaited_once()


# -------------------------------------------------------------------
# Messages – client None path
# -------------------------------------------------------------------


class TestMessagesClientNone:
    @pytest.mark.asyncio
    async def test_client_none_returns_empty(self):
        """get_client() raises when client is None; method catches and returns []."""
        svc = _make_service()
        svc.client = None
        result = await svc.get_messages_for_conversation("conv1")
        assert result == []


# -------------------------------------------------------------------
# Backward compatibility functions
# -------------------------------------------------------------------


class TestBackwardCompatGetDb:
    def test_get_db_returns_client(self):
        """Lines 596-603: get_db returns client when service exists and is initialized."""
        from services.infrastructure.database import get_db

        mock_svc = _make_service()
        with patch("services.core.get_service", return_value=mock_svc):
            result = get_db()
        assert result is mock_svc.client

    def test_get_db_returns_none_when_no_service(self):
        """Line 603: get_db returns None when service is not found."""
        from services.infrastructure.database import get_db

        with patch("services.core.get_service", return_value=None):
            result = get_db()
        assert result is None

    def test_get_db_triggers_initialize_when_not_initialized(self):
        """Lines 599-601: get_db creates task to initialize when not yet initialized."""
        from services.infrastructure.database import get_db

        mock_svc = _make_service()
        mock_svc._initialized = False
        with patch("services.core.get_service", return_value=mock_svc):
            with patch("asyncio.create_task") as mock_task:
                result = get_db()
        mock_task.assert_called_once()
        assert result is mock_svc.client

    def test_get_db_returns_none_for_wrong_type(self):
        """Line 598: get_db returns None when service is not a DatabaseService."""
        from services.infrastructure.database import get_db

        with patch("services.core.get_service", return_value=Mock()):
            result = get_db()
        assert result is None


class TestBackwardCompatGetAllUsers:
    @pytest.mark.asyncio
    async def test_returns_users(self):
        """Lines 608-613: backward compat returns users from service."""
        from services.infrastructure.database import (
            get_all_users_with_preferences as compat_fn,
        )

        mock_svc = _make_service()
        mock_svc.get_all_users_with_preferences = AsyncMock(return_value=[{"id": "00000000-0000-0000-0000-000000000001"}])
        with patch("services.core.get_service", return_value=mock_svc):
            result = await compat_fn()
        assert result == [{"id": "00000000-0000-0000-0000-000000000001"}]

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_service(self):
        """Line 614: returns [] when no service found."""
        from services.infrastructure.database import (
            get_all_users_with_preferences as compat_fn,
        )

        with patch("services.core.get_service", return_value=None):
            result = await compat_fn()
        assert result == []

    @pytest.mark.asyncio
    async def test_initializes_service_if_needed(self):
        """Lines 611-612: calls initialize when service not yet initialized."""
        from services.infrastructure.database import (
            get_all_users_with_preferences as compat_fn,
        )

        mock_svc = _make_service()
        mock_svc._initialized = False
        mock_svc.initialize = AsyncMock()
        mock_svc.get_all_users_with_preferences = AsyncMock(return_value=[])
        with patch("services.core.get_service", return_value=mock_svc):
            await compat_fn()
        mock_svc.initialize.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_empty_for_wrong_type(self):
        """Line 610: returns [] when service is not a DatabaseService."""
        from services.infrastructure.database import (
            get_all_users_with_preferences as compat_fn,
        )

        with patch("services.core.get_service", return_value=Mock()):
            result = await compat_fn()
        assert result == []
