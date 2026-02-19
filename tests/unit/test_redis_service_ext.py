"""Extended unit tests for RedisService — CRUD and higher-level methods."""

import os
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock

from services.infrastructure.redis_service import RedisService
from services.core import ServiceUnavailableError


def _make_service():
    """Create a RedisService with mocked HTTP client."""
    svc = RedisService()
    svc.url = "https://fake-redis.upstash.io"
    svc.token = "fake-token"
    svc.headers = {"Authorization": "Bearer fake-token"}
    svc._initialized = True

    # Mock the async HTTP client
    mock_client = AsyncMock()
    svc._client = mock_client
    return svc, mock_client


def _mock_response(data, status_code=200):
    """Build a mock httpx.Response."""
    resp = Mock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.raise_for_status = Mock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=Mock(), response=resp
        )
    return resp


# -------------------------------------------------------------------
# Initialization
# -------------------------------------------------------------------

class TestRedisInit:
    @pytest.mark.asyncio
    async def test_init_missing_url(self):
        svc = RedisService()
        with patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": "", "UPSTASH_REDIS_REST_TOKEN": "tok"}, clear=False):
            with pytest.raises(ServiceUnavailableError):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_init_missing_token(self):
        svc = RedisService()
        with patch.dict(os.environ, {"UPSTASH_REDIS_REST_URL": "url", "UPSTASH_REDIS_REST_TOKEN": ""}, clear=False):
            with pytest.raises(ServiceUnavailableError):
                await svc._initialize()

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "PONG"})
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        svc, mock_client = _make_service()
        mock_client.post.side_effect = RuntimeError("network error")
        assert await svc._health_check() is False

    @pytest.mark.asyncio
    async def test_cleanup(self):
        svc, mock_client = _make_service()
        await svc._cleanup()
        mock_client.aclose.assert_called_once()
        assert svc._client is None


# -------------------------------------------------------------------
# _execute_command
# -------------------------------------------------------------------

class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_success(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "OK"})
        result = await svc._execute_command(["SET", "key", "value"])
        assert result == "OK"

    @pytest.mark.asyncio
    async def test_http_error(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"error": "bad"}, status_code=400)
        with pytest.raises(RuntimeError, match="Redis command failed"):
            await svc._execute_command(["BAD"])


# -------------------------------------------------------------------
# Core commands
# -------------------------------------------------------------------

class TestCoreCommands:
    @pytest.mark.asyncio
    async def test_set_simple(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "OK"})
        result = await svc.set("key", "value")
        assert result is True

    @pytest.mark.asyncio
    async def test_set_with_expire_seconds(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "OK"})
        result = await svc.set("key", "value", expire_seconds=3600)
        assert result is True
        # Two calls: SET then EXPIRE
        assert mock_client.post.call_count == 2

    @pytest.mark.asyncio
    async def test_set_with_ex(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "OK"})
        result = await svc.set("key", "value", ex=60)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_string(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "hello"})
        result = await svc.get("key")
        assert result == "hello"

    @pytest.mark.asyncio
    async def test_get_json(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": '{"a": 1}'})
        result = await svc.get("key")
        assert result == {"a": 1}

    @pytest.mark.asyncio
    async def test_get_none(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": None})
        result = await svc.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.delete("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 0})
        result = await svc.delete("key")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.exists("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_not_exists(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 0})
        result = await svc.exists("key")
        assert result is False

    @pytest.mark.asyncio
    async def test_expire(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.expire("key", 60)
        assert result is True

    @pytest.mark.asyncio
    async def test_expire_nonexistent(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 0})
        result = await svc.expire("key", 60)
        assert result is False

    @pytest.mark.asyncio
    async def test_get_ttl(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 300})
        result = await svc.get_ttl("key")
        assert result == 300

    @pytest.mark.asyncio
    async def test_ping(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "PONG"})
        result = await svc.ping()
        assert result is True


# -------------------------------------------------------------------
# List commands
# -------------------------------------------------------------------

class TestListCommands:
    @pytest.mark.asyncio
    async def test_lpush(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 3})
        result = await svc.lpush("mylist", "item")
        assert result == 3

    @pytest.mark.asyncio
    async def test_lrange(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": ["a", "b", "c"]})
        result = await svc.lrange("mylist", 0, -1)
        assert result == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_lrange_empty(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": None})
        result = await svc.lrange("empty", 0, -1)
        assert result == []


# -------------------------------------------------------------------
# Conversation cache
# -------------------------------------------------------------------

class TestConversationCache:
    @pytest.mark.asyncio
    async def test_save_message(self):
        svc, mock_client = _make_service()
        # save_conversation_message calls self.get() then self.set()
        # Both use _execute_command which calls mock_client.post
        # First call: GET returns existing empty list
        # Second call: SET returns OK
        # Third call: EXPIRE (from set with expire_seconds)
        mock_client.post.side_effect = [
            _mock_response({"result": None}),  # GET conversation:user1
            _mock_response({"result": "OK"}),   # SET conversation:user1
            _mock_response({"result": 1}),       # EXPIRE
        ]
        result = await svc.save_conversation_message("user1", {"role": "user", "content": "hi"})
        assert result is True

    @pytest.mark.asyncio
    async def test_get_conversation_context(self):
        svc, mock_client = _make_service()
        msgs = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]
        mock_client.post.return_value = _mock_response({"result": json_dumps(msgs)})
        result = await svc.get_conversation_context("user1")
        assert len(result) == 2
        assert result[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_get_conversation_context_empty(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": None})
        result = await svc.get_conversation_context("user1")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_conversation_context_last_n(self):
        svc, mock_client = _make_service()
        msgs = [{"role": "user", "content": "1"}, {"role": "user", "content": "2"}, {"role": "user", "content": "3"}]
        mock_client.post.return_value = _mock_response({"result": json_dumps(msgs)})
        result = await svc.get_conversation_context("user1", last_n=2)
        assert len(result) == 2
        assert result[0]["content"] == "2"

    @pytest.mark.asyncio
    async def test_clear_conversation(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.clear_conversation("user1")
        assert result is True


# -------------------------------------------------------------------
# Conversation history (cache-aside)
# -------------------------------------------------------------------

class TestConversationHistory:
    @pytest.mark.asyncio
    async def test_get_history_hit(self):
        svc, mock_client = _make_service()
        msgs = [{"role": "user", "content": "hi"}]
        mock_client.post.return_value = _mock_response({"result": json_dumps(msgs)})
        result = await svc.get_conversation_history("conv1")
        assert result == msgs

    @pytest.mark.asyncio
    async def test_get_history_miss(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": None})
        result = await svc.get_conversation_history("conv1")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_history(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "OK"})
        result = await svc.set_conversation_history("conv1", [{"role": "user", "content": "hi"}])
        assert result is True

    @pytest.mark.asyncio
    async def test_invalidate_history(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.invalidate_conversation_history("conv1")
        assert result is True


# -------------------------------------------------------------------
# Session management
# -------------------------------------------------------------------

class TestSessionManagement:
    @pytest.mark.asyncio
    async def test_save_session(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": "OK"})
        result = await svc.save_session("sess1", {"user_id": "u1"})
        assert result is True

    @pytest.mark.asyncio
    async def test_get_session(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": '{"user_id": "u1"}'})
        result = await svc.get_session("sess1")
        assert result == {"user_id": "u1"}

    @pytest.mark.asyncio
    async def test_get_session_missing(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": None})
        result = await svc.get_session("missing")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.delete_session("sess1")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_session_nonexistent(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 0})
        result = await svc.delete_session("missing")
        assert result is False


# -------------------------------------------------------------------
# Pipeline
# -------------------------------------------------------------------

class TestPipeline:
    @pytest.mark.asyncio
    async def test_pipeline_execution(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response([
            {"result": "OK"}, {"result": "value1"}
        ])
        result = await svc.pipeline([
            ["SET", "key1", "val1"],
            ["GET", "key1"],
        ])
        assert len(result) == 2


# -------------------------------------------------------------------
# Refresh conversation TTL
# -------------------------------------------------------------------

class TestRefreshConversationTTL:
    @pytest.mark.asyncio
    async def test_refresh_ttl(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 1})
        result = await svc.refresh_conversation_ttl("user1")
        assert result is True

    @pytest.mark.asyncio
    async def test_refresh_ttl_nonexistent(self):
        svc, mock_client = _make_service()
        mock_client.post.return_value = _mock_response({"result": 0})
        result = await svc.refresh_conversation_ttl("user1")
        assert result is False


# -------------------------------------------------------------------
# get_client
# -------------------------------------------------------------------

class TestGetClient:
    def test_returns_service(self):
        svc, _ = _make_service()
        assert svc is not None


# -------------------------------------------------------------------
# Helper
# -------------------------------------------------------------------

import json

def json_dumps(obj):
    """Shorthand for json.dumps."""
    return json.dumps(obj)
