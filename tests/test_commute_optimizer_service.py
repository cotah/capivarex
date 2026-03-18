"""Tests for Commute Optimizer service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.business.commute_optimizer_service import (
    generate_commute_alert,
    _get_upcoming_events,
    _get_home_location,
    _estimate_commute,
    _generate_commute_message,
)


class TestCommuteMessage:
    def test_light_traffic(self):
        data = {
            "event_title": "Standup",
            "leave_at": "08:30",
            "arrival_estimate": "08:45",
            "duration_minutes": 15,
            "traffic": "light",
            "route_summary": "M50 → N11",
        }
        msg = _generate_commute_message("João", data)
        assert "Hora de sair" in msg
        assert "Standup" in msg
        assert "08:30" in msg
        assert "🟢" in msg
        assert "livre" in msg.lower()

    def test_heavy_traffic(self):
        data = {
            "event_title": "Meeting",
            "leave_at": "07:00",
            "arrival_estimate": "08:00",
            "duration_minutes": 50,
            "traffic": "heavy",
            "route_summary": "",
        }
        msg = _generate_commute_message("", data)
        assert "🔴" in msg
        assert "pesado" in msg.lower()
        assert "mais cedo" in msg.lower()

    def test_unknown_traffic(self):
        data = {
            "event_title": "Event",
            "leave_at": "09:00",
            "arrival_estimate": "09:30",
            "duration_minutes": 30,
            "traffic": "unknown",
            "route_summary": "",
        }
        msg = _generate_commute_message("Ana", data)
        assert "⚪" in msg


class TestEventFetching:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.commute_optimizer_service.get_service", return_value=None
        ):
            assert await _get_upcoming_events("u1") == []

    @pytest.mark.asyncio
    async def test_exception(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.commute_optimizer_service.get_service",
            return_value=mock_db,
        ):
            assert await _get_upcoming_events("u1") == []


class TestHomeLocation:
    @pytest.mark.asyncio
    async def test_no_db(self):
        with patch(
            "services.business.commute_optimizer_service.get_service", return_value=None
        ):
            assert await _get_home_location("u1") == ""

    @pytest.mark.asyncio
    async def test_found(self):
        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[{"value": "123 Main St, Dublin"}]
        )
        with patch(
            "services.business.commute_optimizer_service.get_service",
            return_value=mock_db,
        ):
            assert await _get_home_location("u1") == "123 Main St, Dublin"


class TestEstimateCommute:
    @pytest.mark.asyncio
    async def test_no_origin(self):
        result = await _estimate_commute("", "destination")
        assert result["traffic"] == "unknown"

    @pytest.mark.asyncio
    async def test_no_maps(self):
        with patch(
            "services.business.commute_optimizer_service.get_service", return_value=None
        ):
            result = await _estimate_commute("home", "work")
        assert result["duration_minutes"] == 30


class TestGenerateCommuteAlert:
    @pytest.mark.asyncio
    async def test_no_events(self):
        with patch(
            "services.business.commute_optimizer_service._get_upcoming_events",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await generate_commute_alert("u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_no_location_events(self):
        events = [
            {"title": "Standup", "start_time": "2026-03-17T10:00:00Z", "location": ""}
        ]
        with patch(
            "services.business.commute_optimizer_service._get_upcoming_events",
            new_callable=AsyncMock,
            return_value=events,
        ):
            result = await generate_commute_alert("u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_with_commute(self):
        events = [
            {
                "title": "Meeting",
                "start_time": "2026-03-17T10:00:00Z",
                "location": "123 Business Park, Dublin",
            }
        ]
        with (
            patch(
                "services.business.commute_optimizer_service._get_upcoming_events",
                new_callable=AsyncMock,
                return_value=events,
            ),
            patch(
                "services.business.commute_optimizer_service._get_home_location",
                new_callable=AsyncMock,
                return_value="456 Home St",
            ),
            patch(
                "services.business.commute_optimizer_service._estimate_commute",
                new_callable=AsyncMock,
                return_value={
                    "duration_minutes": 25,
                    "traffic": "light",
                    "route_summary": "M50",
                },
            ),
            patch(
                "services.business.commute_optimizer_service._store_commute",
                new_callable=AsyncMock,
            ),
        ):
            result = await generate_commute_alert("u1", "João")
        assert result is not None
        assert "Meeting" in result["text"]
        assert result["data"]["traffic"] == "light"


class TestStoreCommute:
    @pytest.mark.asyncio
    async def test_store_no_db(self):
        from services.business.commute_optimizer_service import _store_commute

        with patch(
            "services.business.commute_optimizer_service.get_service", return_value=None
        ):
            await _store_commute("u1", "text", {})

    @pytest.mark.asyncio
    async def test_store_exception(self):
        from services.business.commute_optimizer_service import _store_commute

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.side_effect = Exception("err")
        with patch(
            "services.business.commute_optimizer_service.get_service",
            return_value=mock_db,
        ):
            await _store_commute("u1", "text", {})
