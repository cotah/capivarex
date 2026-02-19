"""
Redis Service - Refactored with BaseService architecture.

Full Upstash Redis REST API integration for caching, conversations, and sessions.

Provides:
- Upstash Redis REST API client (async via httpx)
- Core Redis commands: SET, GET, DEL, EXISTS, LPUSH, LRANGE, EXPIRE, TTL, PING
- Pipeline support for batch commands
- Conversation message cache (save, retrieve, clear, refresh TTL)
- Session management (save, get, delete)
- Health checks and metrics tracking
"""

import os
import json
import logging
import time
from typing import Dict, Any, Optional, List

import httpx
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)


@register_service("redis")
class RedisService(BaseService):
    """
    Upstash Redis REST API service.

    Features:
    - All core Redis commands via REST API (async, non-blocking)
    - JSON serialisation / deserialisation for complex values
    - Conversation context caching with sliding TTL
    - Session storage with expiry
    - Pipeline support for batched operations
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "redis",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the Redis service."""
        super().__init__(name, config)
        self.url: Optional[str] = None
        self.token: Optional[str] = None
        self.headers: Optional[Dict[str, str]] = None
        self._client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # HTTP client management
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        """
        Get or create the async HTTP client with connection pooling.

        Returns:
            httpx.AsyncClient instance configured for Upstash REST API.
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=self.headers,
                timeout=5.0,
                limits=httpx.Limits(
                    max_keepalive_connections=5,
                    max_connections=10,
                ),
            )
        return self._client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """
        Initialise the Upstash Redis REST connection.

        Environment variables:
        - UPSTASH_REDIS_REST_URL
        - UPSTASH_REDIS_REST_TOKEN
        """
        self.url = os.getenv("UPSTASH_REDIS_REST_URL")
        self.token = os.getenv("UPSTASH_REDIS_REST_TOKEN")

        if not self.url or not self.token:
            raise ServiceUnavailableError(
                "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN "
                "must be set in environment variables"
            )

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        # Validate the connection with a PING
        try:
            result = await self._execute_command(["PING"])
            if result != "PONG":
                raise ServiceUnavailableError("Redis PING did not return PONG")
            self.logger.info("Redis service initialised (Upstash REST API)")
        except Exception as exc:
            self.logger.warning(
                f"Redis PING failed during init (service may still work): {exc}"
            )
            # Do not raise -- allow the service to be used; health_check
            # will report the real status later.

    async def _health_check(self) -> bool:
        """Return True if a PING to Upstash succeeds."""
        try:
            client = await self._get_client()
            response = await client.post(
                self.url,
                json=["PING"],
            )
            if response.status_code == 200:
                data = response.json()
                return data.get("result") == "PONG"
            return False
        except Exception:
            return False

    async def _cleanup(self) -> None:
        """Close the async HTTP client on service shutdown."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Low-level command execution (async)
    # ------------------------------------------------------------------

    async def _execute_command(self, command: List[Any]) -> Any:
        """
        Execute a single Redis command via the Upstash REST API.

        Args:
            command: List with command name and arguments,
                     e.g. ``["SET", "key", "value"]``.

        Returns:
            The ``result`` field from the Upstash JSON response.

        Raises:
            RuntimeError: If the HTTP request fails.
        """
        call_start = time.time()
        try:
            client = await self._get_client()
            response = await client.post(
                self.url,
                json=command,
            )
            response.raise_for_status()
            data = response.json()

            latency = time.time() - call_start
            self._track_call(latency, error=False)
            return data.get("result")

        except httpx.HTTPStatusError as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            raise RuntimeError(f"Redis command failed: {exc}")

    async def _execute_pipeline(self, commands: List[List[Any]]) -> List[Any]:
        """
        Execute multiple Redis commands in a single HTTP request (pipeline).

        Args:
            commands: List of command lists,
                      e.g. ``[["SET", "k1", "v1"], ["SET", "k2", "v2"]]``.

        Returns:
            List of result values, one per command.

        Raises:
            RuntimeError: If the HTTP request fails.
        """
        call_start = time.time()
        pipeline_url = f"{self.url}/pipeline"
        try:
            client = await self._get_client()
            response = await client.post(
                pipeline_url,
                json=commands,
            )
            response.raise_for_status()
            data = response.json()

            latency = time.time() - call_start
            self._track_call(latency, error=False)

            # Upstash returns a list of {result: ...} objects
            if isinstance(data, list):
                return [item.get("result") for item in data]
            return [data.get("result")]

        except httpx.HTTPStatusError as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            raise RuntimeError(f"Redis pipeline failed: {exc}")

    # ------------------------------------------------------------------
    # Core Redis commands (async)
    # ------------------------------------------------------------------

    async def set(
        self,
        key: str,
        value: Any,
        expire_seconds: Optional[int] = None,
        ex: Optional[int] = None,
    ) -> bool:
        """
        Set a value in Redis.

        Non-string values are automatically JSON-serialised.

        Args:
            key:             Redis key.
            value:           Value to store.
            expire_seconds:  TTL in seconds (optional).
            ex:              Alias for ``expire_seconds`` (takes precedence).

        Returns:
            True on success.

        Raises:
            RuntimeError: On failure.
        """
        try:
            if not isinstance(value, str):
                value = json.dumps(value)

            await self._execute_command(["SET", key, value])

            ttl = ex if ex is not None else expire_seconds
            if ttl:
                await self._execute_command(["EXPIRE", key, ttl])

            return True
        except Exception as exc:
            raise RuntimeError(f"Failed to set key {key}: {exc}")

    async def get(self, key: str, parse_json: bool = True) -> Optional[Any]:
        """
        Retrieve a value from Redis.

        Args:
            key:        Redis key.
            parse_json: Attempt to JSON-parse the result (default True).

        Returns:
            Parsed value, raw string, or None if the key does not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["GET", key])

            if result is None:
                return None

            if parse_json and isinstance(result, str):
                try:
                    return json.loads(result)
                except json.JSONDecodeError:
                    return result

            return result
        except Exception as exc:
            raise RuntimeError(f"Failed to get key {key}: {exc}")

    async def delete(self, key: str) -> bool:
        """
        Delete a key from Redis.

        Args:
            key: Redis key.

        Returns:
            True if the key was deleted, False if it did not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["DEL", key])
            return result == 1
        except Exception as exc:
            raise RuntimeError(f"Failed to delete key {key}: {exc}")

    async def exists(self, key: str) -> bool:
        """
        Check whether a key exists.

        Args:
            key: Redis key.

        Returns:
            True if the key exists, False otherwise.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["EXISTS", key])
            return result == 1
        except Exception as exc:
            raise RuntimeError(f"Failed to check existence of key {key}: {exc}")

    async def lpush(self, key: str, value: Any) -> int:
        """
        Prepend a value to a Redis list.

        Args:
            key:   List key.
            value: Value to prepend (converted to string if needed).

        Returns:
            Length of the list after the push.

        Raises:
            RuntimeError: On failure.
        """
        try:
            if not isinstance(value, str):
                value = str(value)
            result = await self._execute_command(["LPUSH", key, value])
            return int(result or 0)
        except Exception as exc:
            raise RuntimeError(f"Failed to LPUSH on key {key}: {exc}")

    async def lrange(self, key: str, start: int = 0, end: int = -1) -> List[Any]:
        """
        Retrieve elements from a Redis list.

        Args:
            key:   List key.
            start: Start index (inclusive).
            end:   End index (inclusive, -1 for all).

        Returns:
            List of values.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["LRANGE", key, start, end])
            return result or []
        except Exception as exc:
            raise RuntimeError(f"Failed to LRANGE on key {key}: {exc}")

    async def expire(self, key: str, seconds: int) -> bool:
        """
        Set the expiration time for a key.

        Args:
            key:     Redis key.
            seconds: TTL in seconds.

        Returns:
            True if the timeout was set, False if the key does not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["EXPIRE", key, seconds])
            return result == 1
        except Exception as exc:
            raise RuntimeError(f"Failed to set expiration for key {key}: {exc}")

    async def get_ttl(self, key: str) -> int:
        """
        Get the remaining TTL of a key.

        Args:
            key: Redis key.

        Returns:
            Seconds remaining, -1 if no expiry, -2 if the key does not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["TTL", key])
            return result
        except Exception as exc:
            raise RuntimeError(f"Failed to get TTL for key {key}: {exc}")

    async def ping(self) -> bool:
        """
        Test the connection to Redis.

        Returns:
            True if the server responds with ``PONG``.

        Raises:
            RuntimeError: On failure.
        """
        try:
            result = await self._execute_command(["PING"])
            return result == "PONG"
        except Exception as exc:
            raise RuntimeError(f"Failed to ping Redis: {exc}")

    async def pipeline(self, commands: List[List[Any]]) -> List[Any]:
        """
        Execute a batch of commands in a single round-trip (pipeline).

        Args:
            commands: List of Redis command lists.

        Returns:
            List of results, one per command.

        Raises:
            RuntimeError: On failure.
        """
        return await self._execute_pipeline(commands)

    # ------------------------------------------------------------------
    # Conversation cache helpers (async)
    # ------------------------------------------------------------------

    async def save_conversation_message(
        self,
        user_id: str,
        message: Dict[str, Any],
        max_messages: int = 20,
        expire_seconds: int = 3600,
    ) -> bool:
        """
        Append a message to the user's conversation cache.

        Keeps at most ``max_messages`` entries and refreshes the TTL.

        Args:
            user_id:         User identifier.
            message:         Message dict (role, content, timestamp, ...).
            max_messages:    Maximum messages to retain (default 20).
            expire_seconds:  TTL in seconds (default 3600 = 1 hour).

        Returns:
            True on success.

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"conversation:{user_id}"

            messages: List[Dict[str, Any]] = await self.get(key, parse_json=True) or []
            messages.append(message)

            if len(messages) > max_messages:
                messages = messages[-max_messages:]

            await self.set(key, messages, expire_seconds=expire_seconds)
            return True
        except Exception as exc:
            raise RuntimeError(
                f"Failed to save conversation message for user {user_id}: {exc}"
            )

    async def get_conversation_context(
        self,
        user_id: str,
        last_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve the conversation context for a user.

        Args:
            user_id: User identifier.
            last_n:  Return only the last N messages (None = all).

        Returns:
            List of message dicts (may be empty).

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"conversation:{user_id}"
            messages: List[Dict[str, Any]] = await self.get(key, parse_json=True) or []

            if last_n is not None and last_n > 0:
                messages = messages[-last_n:]

            return messages
        except Exception as exc:
            raise RuntimeError(
                f"Failed to get conversation context for user {user_id}: {exc}"
            )

    async def clear_conversation(self, user_id: str) -> bool:
        """
        Clear the conversation cache for a user.

        Args:
            user_id: User identifier.

        Returns:
            True if deleted, False if it did not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"conversation:{user_id}"
            return await self.delete(key)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to clear conversation for user {user_id}: {exc}"
            )

    async def refresh_conversation_ttl(
        self,
        user_id: str,
        expire_seconds: int = 3600,
    ) -> bool:
        """
        Refresh the TTL on a user's conversation cache.

        Args:
            user_id:        User identifier.
            expire_seconds: New TTL in seconds (default 3600).

        Returns:
            True if the timeout was set, False if the key does not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"conversation:{user_id}"
            return await self.expire(key, expire_seconds)
        except Exception as exc:
            raise RuntimeError(
                f"Failed to refresh conversation TTL for user {user_id}: {exc}"
            )

    # ------------------------------------------------------------------
    # Conversation history cache-aside helpers
    # ------------------------------------------------------------------

    async def get_conversation_history(
        self, conversation_id: str
    ) -> Optional[List[Dict[str, Any]]]:
        """Get a full conversation history from cache.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            List of message dicts, or None on cache miss.
        """
        try:
            cache_key = f"conv_history:{conversation_id}"
            return await self.get(cache_key, parse_json=True)
        except Exception as exc:
            self.logger.warning(
                f"Failed to get conversation history cache for {conversation_id}: {exc}"
            )
            return None

    async def set_conversation_history(
        self,
        conversation_id: str,
        history: List[Dict[str, Any]],
        ttl_seconds: int = 3600,
    ) -> bool:
        """Store a full conversation history in cache.

        Args:
            conversation_id: Unique conversation identifier.
            history:         List of message dicts.
            ttl_seconds:     Time-to-live in seconds (default 1 hour).

        Returns:
            True on success.
        """
        try:
            cache_key = f"conv_history:{conversation_id}"
            await self.set(cache_key, history, expire_seconds=ttl_seconds)
            return True
        except Exception as exc:
            self.logger.warning(
                f"Failed to set conversation history cache for {conversation_id}: {exc}"
            )
            return False

    async def invalidate_conversation_history(
        self, conversation_id: str
    ) -> bool:
        """Remove a conversation history from cache.

        Args:
            conversation_id: Unique conversation identifier.

        Returns:
            True if deleted, False if it did not exist.
        """
        try:
            cache_key = f"conv_history:{conversation_id}"
            return await self.delete(cache_key)
        except Exception as exc:
            self.logger.warning(
                f"Failed to invalidate conversation history cache for {conversation_id}: {exc}"
            )
            return False

    # ------------------------------------------------------------------
    # Session management helpers (async)
    # ------------------------------------------------------------------

    async def save_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        expire_seconds: int = 86400,
    ) -> bool:
        """
        Save user session data.

        Args:
            session_id:      Session identifier.
            session_data:    Arbitrary session payload.
            expire_seconds:  TTL in seconds (default 86400 = 24 hours).

        Returns:
            True on success.

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"session:{session_id}"
            await self.set(key, session_data, expire_seconds=expire_seconds)
            return True
        except Exception as exc:
            raise RuntimeError(f"Failed to save session {session_id}: {exc}")

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve session data.

        Args:
            session_id: Session identifier.

        Returns:
            Session data dict, or None if expired / not found.

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"session:{session_id}"
            return await self.get(key, parse_json=True)
        except Exception as exc:
            raise RuntimeError(f"Failed to get session {session_id}: {exc}")

    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a session.

        Args:
            session_id: Session identifier.

        Returns:
            True if deleted, False if it did not exist.

        Raises:
            RuntimeError: On failure.
        """
        try:
            key = f"session:{session_id}"
            return await self.delete(key)
        except Exception as exc:
            raise RuntimeError(f"Failed to delete session {session_id}: {exc}")


# ------------------------------------------------------------------
# Backward-compatible singleton accessor
# ------------------------------------------------------------------
_redis_service: Optional[RedisService] = None


def get_redis_client() -> RedisService:
    """Get or create the global RedisService instance."""
    global _redis_service
    if _redis_service is None:
        from services.core import get_service

        _redis_service = get_service("redis")
    return _redis_service
