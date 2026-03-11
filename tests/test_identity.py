# -*- coding: utf-8 -*-
"""Tests for the unified identity resolution helper."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from utils.identity import _is_uuid, resolve_user_uuid, resolve_user_uuid_sync


# ---------------------------------------------------------------------------
# _is_uuid
# ---------------------------------------------------------------------------


class TestIsUuid:
    def test_valid_uuid4(self):
        assert _is_uuid("550e8400-e29b-41d4-a716-446655440000") is True

    def test_valid_uuid_no_dashes(self):
        assert _is_uuid("550e8400e29b41d4a716446655440000") is True

    def test_numeric_telegram_id(self):
        assert _is_uuid("6316076982") is False

    def test_empty_string(self):
        assert _is_uuid("") is False

    def test_random_string(self):
        assert _is_uuid("not-a-uuid-at-all") is False


# ---------------------------------------------------------------------------
# resolve_user_uuid (async)
# ---------------------------------------------------------------------------


class TestResolveUserUuid:
    @pytest.mark.asyncio
    async def test_uuid_passthrough(self):
        """Valid UUID is returned without any DB lookup."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = await resolve_user_uuid(uuid, context="test")
        assert result == uuid

    @pytest.mark.asyncio
    async def test_numeric_resolves_to_uuid(self):
        """Numeric Telegram ID is resolved to UUID via DB."""
        expected_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            return_value={"id": expected_uuid, "telegram_chat_id": "6316076982"}
        )

        with patch(
            "services.core.get_service", return_value=mock_db
        ):
            result = await resolve_user_uuid("6316076982", context="test")

        assert result == expected_uuid
        mock_db.get_user_by_telegram_id.assert_awaited_once_with("6316076982")

    @pytest.mark.asyncio
    async def test_numeric_not_found_returns_original(self):
        """Numeric ID not found in DB returns original ID (no crash)."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(return_value=None)

        with patch(
            "services.core.get_service", return_value=mock_db
        ):
            result = await resolve_user_uuid("9999999999", context="test")

        assert result == "9999999999"

    @pytest.mark.asyncio
    async def test_numeric_db_error_returns_original(self):
        """DB error during resolution returns original ID (fail-open)."""
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_user_by_telegram_id = AsyncMock(
            side_effect=RuntimeError("DB down")
        )

        with patch(
            "services.core.get_service", return_value=mock_db
        ):
            result = await resolve_user_uuid("6316076982", context="test")

        assert result == "6316076982"

    @pytest.mark.asyncio
    async def test_invalid_string_returns_original(self):
        """Random non-UUID, non-numeric string returns as-is."""
        result = await resolve_user_uuid("some-random-string")
        assert result == "some-random-string"

    @pytest.mark.asyncio
    async def test_empty_string_returns_empty(self):
        """Empty string returns empty string."""
        result = await resolve_user_uuid("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_whitespace_stripped(self):
        """Whitespace around UUID is stripped."""
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        result = await resolve_user_uuid(f"  {uuid}  ")
        assert result == uuid

    @pytest.mark.asyncio
    async def test_db_service_unavailable_returns_original(self):
        """When database service is None, returns original."""
        with patch(
            "services.core.get_service", return_value=None
        ):
            result = await resolve_user_uuid("6316076982", context="test")

        assert result == "6316076982"


# ---------------------------------------------------------------------------
# resolve_user_uuid_sync
# ---------------------------------------------------------------------------


class TestResolveUserUuidSync:
    def test_valid_uuid(self):
        uuid = "550e8400-e29b-41d4-a716-446655440000"
        assert resolve_user_uuid_sync(uuid) == uuid

    def test_numeric_returns_none(self):
        assert resolve_user_uuid_sync("6316076982") is None

    def test_empty_returns_none(self):
        assert resolve_user_uuid_sync("") is None

    def test_random_string_returns_none(self):
        assert resolve_user_uuid_sync("not-a-uuid") is None
