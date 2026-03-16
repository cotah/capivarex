"""Tests for package tracking central — A10: auto-detect tracking + status monitoring."""
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.package_tracking_service import (
    detect_tracking_numbers,
    save_package,
    remove_package,
    list_packages,
    check_package_updates,
    generate_tracking_alert,
    handle_tracking_mention,
)


class TestDetection:
    """Tests for tracking number detection."""

    def test_detect_ups(self):
        result = detect_tracking_numbers("Your tracking number is 1Z999AA10123456784")
        assert len(result) == 1
        assert result[0]["carrier"] == "UPS"

    def test_detect_amazon(self):
        result = detect_tracking_numbers("Package shipped: TBA123456789012")
        assert len(result) == 1
        assert result[0]["carrier"] == "Amazon"

    def test_detect_international(self):
        result = detect_tracking_numbers("Your order has been shipped. Tracking: RR123456789PT")
        assert len(result) == 1
        assert "RR123456789PT" in result[0]["number"]

    def test_detect_with_keyword(self):
        result = detect_tracking_numbers("tracking number: RR123456789PT")
        assert len(result) >= 1

    def test_no_tracking(self):
        result = detect_tracking_numbers("bom dia, como estás?")
        assert result == []

    def test_no_tracking_random_numbers(self):
        """Random numbers without keywords should not be detected."""
        result = detect_tracking_numbers("I have 12345678901 items in stock")
        assert result == []

    def test_multiple_numbers(self):
        result = detect_tracking_numbers(
            "Your orders shipped! Tracking: 1Z999AA10123456784 and TBA123456789012"
        )
        assert len(result) == 2

    def test_dedup(self):
        result = detect_tracking_numbers(
            "Tracking 1Z999AA10123456784 - your package 1Z999AA10123456784 is on the way"
        )
        assert len(result) == 1

    def test_max_5(self):
        """Should cap at 5 tracking numbers."""
        text = "shipped: " + " ".join(f"TBA{i:012d}" for i in range(10))
        result = detect_tracking_numbers(text)
        assert len(result) <= 5


class TestStorage:
    """Tests for package storage."""

    @pytest.mark.asyncio
    async def test_save_no_db(self):
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await save_package("u1", {"number": "1Z123", "carrier": "UPS"})
        assert result is False

    @pytest.mark.asyncio
    async def test_list_no_db(self):
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await list_packages("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_remove_no_db(self):
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await remove_package("u1", "1Z123")
        assert result is False


class TestStatusCheck:
    """Tests for status checking."""

    @pytest.mark.asyncio
    async def test_no_packages(self):
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await check_package_updates("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_status_change_detected(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps([
                {"number": "1Z123", "carrier": "UPS", "last_status": "shipped", "delivered": False}
            ])}]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        mock_tracking = MagicMock()
        mock_tracking.is_initialized.return_value = True
        mock_tracking.track = AsyncMock(return_value={"status": "In Transit", "events": []})

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "tracking":
                return mock_tracking
            return None

        with patch("services.business.package_tracking_service.get_service", fake_svc):
            result = await check_package_updates("u1")
        assert len(result) == 1
        assert result[0]["new_status"] == "In Transit"

    @pytest.mark.asyncio
    async def test_delivered_detected(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps([
                {"number": "1Z123", "carrier": "UPS", "last_status": "In Transit", "delivered": False}
            ])}]
        )
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        mock_tracking = MagicMock()
        mock_tracking.is_initialized.return_value = True
        mock_tracking.track = AsyncMock(return_value={"status": "Delivered", "events": []})

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "tracking":
                return mock_tracking
            return None

        with patch("services.business.package_tracking_service.get_service", fake_svc):
            result = await check_package_updates("u1")
        assert len(result) == 1
        assert result[0]["new_status"] == "Delivered"

    @pytest.mark.asyncio
    async def test_no_change_no_update(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps([
                {"number": "1Z123", "carrier": "UPS", "last_status": "In Transit", "delivered": False}
            ])}]
        )

        mock_tracking = MagicMock()
        mock_tracking.is_initialized.return_value = True
        mock_tracking.track = AsyncMock(return_value={"status": "In Transit", "events": []})

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "tracking":
                return mock_tracking
            return None

        with patch("services.business.package_tracking_service.get_service", fake_svc):
            result = await check_package_updates("u1")
        assert result == []

    @pytest.mark.asyncio
    async def test_skip_delivered_packages(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
            data=[{"value": json.dumps([
                {"number": "1Z123", "carrier": "UPS", "last_status": "Delivered", "delivered": True}
            ])}]
        )

        mock_tracking = MagicMock()
        mock_tracking.is_initialized.return_value = True

        def fake_svc(name):
            if name == "database":
                return mock_db
            if name == "tracking":
                return mock_tracking
            return None

        with patch("services.business.package_tracking_service.get_service", fake_svc):
            result = await check_package_updates("u1")
        assert result == []
        mock_tracking.track.assert_not_called()


class TestAlertGeneration:
    """Tests for humanized alerts."""

    @pytest.mark.asyncio
    async def test_no_updates(self):
        result = await generate_tracking_alert("Marcos", [])
        assert result is None

    @pytest.mark.asyncio
    async def test_fallback_delivered(self):
        updates = [{"number": "1Z999AA10123456784", "carrier": "UPS",
                     "previous_status": "In Transit", "new_status": "Delivered"}]
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await generate_tracking_alert("Marcos", updates)
        assert "🎉" in result
        assert "Delivered" in result or "arrived" in result.lower()

    @pytest.mark.asyncio
    async def test_fallback_in_transit(self):
        updates = [{"number": "TBA123456789012", "carrier": "Amazon",
                     "previous_status": "shipped", "new_status": "In transit to destination"}]
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await generate_tracking_alert("Ana", updates)
        assert "🚚" in result

    @pytest.mark.asyncio
    async def test_fallback_generic(self):
        updates = [{"number": "RR123456789PT", "carrier": "auto",
                     "previous_status": "", "new_status": "Accepted by carrier"}]
        with patch("services.business.package_tracking_service.get_service", return_value=None):
            result = await generate_tracking_alert("Test", updates)
        assert "📦" in result


class TestHandleMention:
    """Tests for the chat flow entry point."""

    @pytest.mark.asyncio
    async def test_no_tracking(self):
        result = await handle_tracking_mention("u1", "hello", "Marcos")
        assert result is None

    @pytest.mark.asyncio
    async def test_tracking_saved(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.package_tracking_service.get_service", return_value=mock_db):
            result = await handle_tracking_mention("u1", "My package shipped tracking 1Z999AA10123456784", "Marcos")
        assert result is not None
        assert "📦" in result
        assert "tracking" in result.lower()

    @pytest.mark.asyncio
    async def test_multiple_tracking(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
        mock_db.get_client.return_value.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with patch("services.business.package_tracking_service.get_service", return_value=mock_db):
            result = await handle_tracking_mention(
                "u1", "Orders shipped: 1Z999AA10123456784 and TBA123456789012", "Ana"
            )
        assert "2 packages" in result
