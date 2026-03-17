"""Tests for welcome service and registration with phone."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pydantic import ValidationError

from models.schemas import UserCreate
from services.business.welcome_service import (
    send_welcome_message,
    _send_whatsapp_welcome,
    _send_telegram_welcome,
)


class TestUserCreateSchema:
    """Tests for updated UserCreate with phone field."""

    def test_basic_registration(self):
        user = UserCreate(email="test@test.com", password="12345678")
        assert user.phone is None
        assert user.preferred_channel == "telegram"

    def test_with_phone(self):
        user = UserCreate(email="test@test.com", password="12345678", phone="+353891234567")
        assert user.phone == "+353891234567"

    def test_phone_cleaned(self):
        user = UserCreate(email="test@test.com", password="12345678", phone="+353 89 123 4567")
        assert user.phone == "+353891234567"

    def test_phone_dashes_cleaned(self):
        user = UserCreate(email="test@test.com", password="12345678", phone="+353-89-123-4567")
        assert user.phone == "+353891234567"

    def test_phone_too_short(self):
        with pytest.raises(ValidationError, match="too short"):
            UserCreate(email="test@test.com", password="12345678", phone="123")

    def test_phone_invalid_chars(self):
        with pytest.raises(ValidationError, match="digits"):
            UserCreate(email="test@test.com", password="12345678", phone="abc123")

    def test_preferred_channel_whatsapp(self):
        user = UserCreate(email="test@test.com", password="12345678", preferred_channel="whatsapp")
        assert user.preferred_channel == "whatsapp"

    def test_preferred_channel_both(self):
        user = UserCreate(email="test@test.com", password="12345678", preferred_channel="both")
        assert user.preferred_channel == "both"

    def test_preferred_channel_invalid(self):
        with pytest.raises(ValidationError, match="Channel"):
            UserCreate(email="test@test.com", password="12345678", preferred_channel="sms")

    def test_country_code(self):
        user = UserCreate(email="test@test.com", password="12345678", country_code="+353")
        assert user.country_code == "+353"

    def test_full_registration(self):
        user = UserCreate(
            email="henrique@capivarex.com",
            full_name="Henrique Pasquetto",
            password="securepass123",
            phone="+353899582889",
            country_code="+353",
            preferred_channel="whatsapp",
        )
        assert user.email == "henrique@capivarex.com"
        assert user.phone == "+353899582889"
        assert user.preferred_channel == "whatsapp"


class TestWelcomeService:
    """Tests for welcome message sending."""

    @pytest.mark.asyncio
    async def test_send_whatsapp_not_configured(self):
        with patch("services.integrations.whatsapp_service.is_configured", return_value=False):
            result = await _send_whatsapp_welcome("+353891234567", "John")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_whatsapp_success(self):
        with (
            patch("services.integrations.whatsapp_service.is_configured", return_value=True),
            patch("services.integrations.whatsapp_service.send_interactive_buttons", new_callable=AsyncMock) as mock_btn,
        ):
            mock_btn.return_value = {"messages": [{"id": "wamid.x"}]}
            result = await _send_whatsapp_welcome("+353891234567", "John")
        assert result is True
        mock_btn.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_whatsapp_exception(self):
        with patch("services.integrations.whatsapp_service.is_configured", side_effect=Exception("fail")):
            result = await _send_whatsapp_welcome("+353891234567", "John")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_telegram_no_db(self):
        with patch("services.core.get_service", return_value=None):
            result = await _send_telegram_welcome("+353891234567", "John")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_telegram_no_chat_id(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.or_.return_value.limit.return_value.execute.return_value = MagicMock(data=[])

        with patch("services.core.get_service", return_value=mock_db):
            result = await _send_telegram_welcome("+353891234567", "John")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_welcome_whatsapp(self):
        with (
            patch("services.business.welcome_service._send_whatsapp_welcome", new_callable=AsyncMock, return_value=True),
            patch("services.business.welcome_service._send_telegram_welcome", new_callable=AsyncMock, return_value=False),
        ):
            result = await send_welcome_message("user-123", "+353891234567", "John", "whatsapp")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_welcome_both(self):
        with (
            patch("services.business.welcome_service._send_whatsapp_welcome", new_callable=AsyncMock, return_value=True),
            patch("services.business.welcome_service._send_telegram_welcome", new_callable=AsyncMock, return_value=True),
        ):
            result = await send_welcome_message("user-123", "+353891234567", "John", "both")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_welcome_telegram(self):
        with (
            patch("services.business.welcome_service._send_telegram_welcome", new_callable=AsyncMock, return_value=True),
        ):
            result = await send_welcome_message("user-123", "+353891234567", "John", "telegram")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_welcome_no_name(self):
        with (
            patch("services.business.welcome_service._send_whatsapp_welcome", new_callable=AsyncMock, return_value=True),
        ):
            result = await send_welcome_message("user-123", "+353891234567", "", "whatsapp")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_welcome_all_fail(self):
        with (
            patch("services.business.welcome_service._send_whatsapp_welcome", new_callable=AsyncMock, return_value=False),
            patch("services.business.welcome_service._send_telegram_welcome", new_callable=AsyncMock, return_value=False),
        ):
            result = await send_welcome_message("user-123", "+353891234567", "John", "both")
        assert result is False
