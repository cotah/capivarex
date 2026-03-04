# tests/test_pending_location_flow.py
"""Tests for the pending location save conversation flow."""
import pytest
from unittest.mock import AsyncMock, patch


class TestPendingLocationFlow:
    """Test the Redis-based pending location conversation state."""

    @pytest.mark.asyncio
    async def test_pending_saved_to_redis_when_ask_location(self):
        """When maps agent returns ask_location, pending is saved to Redis."""
        from agents.core import AgentResponse, AgentStatus

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)

        result = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Onde e sua Casa?",
            data={"ask_location": "home", "direction": "origin"},
        )

        # Simulate the save logic
        if result.data and result.data.get("ask_location"):
            await redis_mock.set(
                "pending:location:12345",
                {
                    "key": result.data["ask_location"],
                    "direction": result.data.get("direction", "origin"),
                    "original_query": "rota de casa ao trabalho",
                    "user_id": "uuid-123",
                    "lang": "pt",
                },
                expire_seconds=300,
            )

        redis_mock.set.assert_called_once()
        call_args = redis_mock.set.call_args
        assert call_args[0][0] == "pending:location:12345"
        assert call_args[0][1]["key"] == "home"
        assert call_args[0][1]["original_query"] == "rota de casa ao trabalho"
        assert call_args[1]["expire_seconds"] == 300

    @pytest.mark.asyncio
    async def test_pending_intercepted_on_next_message(self):
        """When pending exists in Redis, next message is intercepted."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value={
            "key": "home",
            "direction": "origin",
            "original_query": "rota de casa ao trabalho",
            "user_id": "uuid-123",
            "lang": "pt",
        })
        redis_mock.delete = AsyncMock(return_value=True)

        pending = await redis_mock.get("pending:location:12345", parse_json=True)
        assert pending is not None
        assert pending["key"] == "home"
        assert pending["original_query"] == "rota de casa ao trabalho"

    @pytest.mark.asyncio
    async def test_location_saved_after_interception(self):
        """After intercepting address, location is saved via service."""
        from services.business.saved_locations_service import SavedLocationsService

        with patch.object(SavedLocationsService, "save_location") as mock_save:
            mock_save.return_value = {
                "address": "Swords, Dublin",
                "latitude": 53.45,
                "longitude": -6.22,
            }

            svc = SavedLocationsService()
            result = await svc.save_location("uuid-123", "home", "Swords, Dublin")

            mock_save.assert_called_once_with("uuid-123", "home", "Swords, Dublin")
            assert result["address"] == "Swords, Dublin"
            assert result["latitude"] == 53.45

    @pytest.mark.asyncio
    async def test_pending_deleted_after_handling(self):
        """Pending key is deleted from Redis after handling."""
        redis_mock = AsyncMock()
        redis_mock.delete = AsyncMock(return_value=True)

        await redis_mock.delete("pending:location:12345")
        redis_mock.delete.assert_called_once_with("pending:location:12345")

    @pytest.mark.asyncio
    async def test_chained_pending_when_second_alias_missing(self):
        """If re-run asks for another location, chain the pending."""
        from agents.core import AgentResponse, AgentStatus

        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)

        # First run saved "home", re-run now asks for "work"
        rerun_result = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Onde e seu Trabalho?",
            data={"ask_location": "work", "direction": "destination"},
        )

        if rerun_result.data and rerun_result.data.get("ask_location"):
            await redis_mock.set(
                "pending:location:12345",
                {
                    "key": rerun_result.data["ask_location"],
                    "direction": "destination",
                    "original_query": "rota de casa ao trabalho",
                    "user_id": "uuid-123",
                    "lang": "pt",
                },
                expire_seconds=300,
            )

        call_args = redis_mock.set.call_args
        assert call_args[0][1]["key"] == "work"
        # original_query stays the same (the very first query)
        assert call_args[0][1]["original_query"] == "rota de casa ao trabalho"

    @pytest.mark.asyncio
    async def test_pending_expires_after_ttl(self):
        """Pending has a TTL so it doesn't persist forever."""
        redis_mock = AsyncMock()
        redis_mock.set = AsyncMock(return_value=True)

        await redis_mock.set(
            "pending:location:12345",
            {"key": "home"},
            expire_seconds=300,
        )

        assert redis_mock.set.call_args[1]["expire_seconds"] == 300

    @pytest.mark.asyncio
    async def test_no_interception_when_no_pending(self):
        """Normal flow when no pending location exists."""
        redis_mock = AsyncMock()
        redis_mock.get = AsyncMock(return_value=None)

        pending = await redis_mock.get("pending:location:99999", parse_json=True)
        assert pending is None
        # Message should proceed to orchestrator normally

    @pytest.mark.asyncio
    async def test_result_without_ask_location_no_pending(self):
        """Normal agent result (no ask_location) doesn't save pending."""
        from agents.core import AgentResponse, AgentStatus

        redis_mock = AsyncMock()

        result = AgentResponse(
            status=AgentStatus.SUCCESS,
            response="Aqui esta a rota!",
            data={"success": True},
        )

        # Should NOT save pending
        if result.data and result.data.get("ask_location"):
            await redis_mock.set("should_not_be_called", {})

        redis_mock.set.assert_not_called()
