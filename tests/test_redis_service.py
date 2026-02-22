"""
Unit tests for RedisService — async Upstash REST API client.
"""
from unittest.mock import AsyncMock, MagicMock
import json

import pytest


def _make_service():
    """Create a RedisService with mocked httpx client."""
    from services.infrastructure.redis_service import RedisService

    svc = RedisService()
    svc.url = "https://fake-upstash.redislabs.com"
    svc.token = "fake-token"
    svc.headers = {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}
    svc._initialized = True
    return svc


def _mock_response(result_value):
    """Return a mock httpx.Response with JSON result."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": result_value}
    resp.raise_for_status = MagicMock()
    return resp


# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_set_and_get():
    """SET stores a value and GET retrieves it."""
    svc = _make_service()
    client = AsyncMock()
    client.post = AsyncMock(return_value=_mock_response("OK"))
    svc._client = client

    result = await svc.set("key1", "value1", expire_seconds=60)
    assert result is True
    assert client.post.call_count == 2  # SET + EXPIRE


@pytest.mark.asyncio
async def test_redis_get_json():
    """GET parses JSON-encoded values."""
    svc = _make_service()
    client = AsyncMock()
    payload = json.dumps({"name": "test"})
    client.post = AsyncMock(return_value=_mock_response(payload))
    svc._client = client

    result = await svc.get("key1")
    assert result == {"name": "test"}


@pytest.mark.asyncio
async def test_redis_get_none():
    """GET returns None when key does not exist."""
    svc = _make_service()
    client = AsyncMock()
    client.post = AsyncMock(return_value=_mock_response(None))
    svc._client = client

    result = await svc.get("missing_key")
    assert result is None


@pytest.mark.asyncio
async def test_redis_delete():
    """DEL returns True when key was deleted."""
    svc = _make_service()
    client = AsyncMock()
    client.post = AsyncMock(return_value=_mock_response(1))
    svc._client = client

    result = await svc.delete("key1")
    assert result is True


@pytest.mark.asyncio
async def test_redis_pipeline():
    """Pipeline executes multiple commands in one round-trip."""
    svc = _make_service()
    client = AsyncMock()
    client.post = AsyncMock(return_value=MagicMock(
        status_code=200,
        json=MagicMock(return_value=[
            {"result": "OK"},
            {"result": "OK"},
        ]),
        raise_for_status=MagicMock(),
    ))
    svc._client = client

    results = await svc.pipeline([
        ["SET", "k1", "v1"],
        ["SET", "k2", "v2"],
    ])
    assert len(results) == 2
    assert all(r == "OK" for r in results)


@pytest.mark.asyncio
async def test_redis_conversation_cache():
    """save_conversation_message and get_conversation_context work together."""
    svc = _make_service()
    client = AsyncMock()

    stored = {}

    async def _mock_post(url, **kwargs):
        cmd = kwargs.get("json", [])
        if isinstance(cmd, list) and len(cmd) >= 2:
            if cmd[0] == "SET":
                stored[cmd[1]] = cmd[2]
                return _mock_response("OK")
            if cmd[0] == "GET":
                val = stored.get(cmd[1])
                return _mock_response(val)
            if cmd[0] == "EXPIRE":
                return _mock_response(1)
        return _mock_response(None)

    client.post = _mock_post
    svc._client = client

    msg = {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00Z"}
    await svc.save_conversation_message("user1", msg, max_messages=10, expire_seconds=3600)

    context = await svc.get_conversation_context("user1", last_n=5)
    assert len(context) == 1
    assert context[0]["content"] == "hello"
