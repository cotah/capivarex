"""
Unit tests for RedisService — async Upstash REST API client.

Updated for per-request httpx.AsyncClient pattern (no more self._client).
"""

from unittest.mock import AsyncMock, MagicMock, patch
import json

import pytest


def _make_service():
    """Create a RedisService with fake credentials (no real connection)."""
    from services.infrastructure.redis_service import RedisService

    svc = RedisService()
    svc.url = "https://fake-upstash.redislabs.com"
    svc.token = "fake-token"
    svc.headers = {
        "Authorization": "Bearer fake-token",
        "Content-Type": "application/json",
    }
    svc._initialized = True
    return svc


def _mock_response(result_value):
    """Return a mock httpx.Response with JSON result."""
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"result": result_value}
    resp.raise_for_status = MagicMock()
    return resp


def _mock_client(post_return=None, post_side_effect=None):
    """Create an AsyncMock httpx client with __aenter__/__aexit__ for async-with."""
    client = AsyncMock()
    if post_side_effect is not None:
        client.post = AsyncMock(side_effect=post_side_effect)
    elif post_return is not None:
        client.post = AsyncMock(return_value=post_return)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _patch(mock_client):
    """Shorthand to patch httpx.AsyncClient at the source module."""
    return patch(
        "services.infrastructure.redis_service.httpx.AsyncClient",
        return_value=mock_client,
    )


# -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_set_and_get():
    """SET stores a value and GET retrieves it."""
    svc = _make_service()
    mc = _mock_client(post_return=_mock_response("OK"))

    with _patch(mc):
        result = await svc.set("key1", "value1", expire_seconds=60)
    assert result is True
    assert mc.post.call_count == 2  # SET + EXPIRE


@pytest.mark.asyncio
async def test_redis_get_json():
    """GET parses JSON-encoded values."""
    svc = _make_service()
    payload = json.dumps({"name": "test"})
    mc = _mock_client(post_return=_mock_response(payload))

    with _patch(mc):
        result = await svc.get("key1")
    assert result == {"name": "test"}


@pytest.mark.asyncio
async def test_redis_get_none():
    """GET returns None when key does not exist."""
    svc = _make_service()
    mc = _mock_client(post_return=_mock_response(None))

    with _patch(mc):
        result = await svc.get("missing_key")
    assert result is None


@pytest.mark.asyncio
async def test_redis_delete():
    """DEL returns True when key was deleted."""
    svc = _make_service()
    mc = _mock_client(post_return=_mock_response(1))

    with _patch(mc):
        result = await svc.delete("key1")
    assert result is True


@pytest.mark.asyncio
async def test_redis_pipeline():
    """Pipeline executes multiple commands in one round-trip."""
    svc = _make_service()
    pipeline_resp = MagicMock()
    pipeline_resp.status_code = 200
    pipeline_resp.json.return_value = [{"result": "OK"}, {"result": "OK"}]
    pipeline_resp.raise_for_status = MagicMock()
    mc = _mock_client(post_return=pipeline_resp)

    with _patch(mc):
        results = await svc.pipeline(
            [
                ["SET", "k1", "v1"],
                ["SET", "k2", "v2"],
            ]
        )
    assert len(results) == 2
    assert all(r == "OK" for r in results)


@pytest.mark.asyncio
async def test_redis_conversation_cache():
    """save_conversation_message and get_conversation_context work together."""
    svc = _make_service()

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

    mc = _mock_client()
    mc.post = _mock_post

    with _patch(mc):
        msg = {"role": "user", "content": "hello", "timestamp": "2026-01-01T00:00:00Z"}
        await svc.save_conversation_message(
            "user1", msg, max_messages=10, expire_seconds=3600
        )
        context = await svc.get_conversation_context("user1", last_n=5)

    assert len(context) == 1
    assert context[0]["content"] == "hello"
