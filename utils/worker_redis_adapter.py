# utils/worker_redis_adapter.py
"""
Arq-compatible adapter that routes all Redis operations through
the Upstash REST-based RedisService.

This ensures 100% of Redis access goes through a single code path
(the RedisService), eliminating the need for a separate socket-based
Redis connection for the arq worker.
"""

from typing import Any, List

from services.core import get_service


class ArqRedisRestAdapter:
    """
    Adapts the Upstash REST-based RedisService to be used by arq.

    arq expects a redis-py-like interface.  We proxy the methods it
    actually calls through our existing RedisService.
    """

    def __init__(self):
        self._redis_service = None

    async def _get_redis(self):
        """Lazily resolve and initialise the RedisService."""
        if self._redis_service is None:
            self._redis_service = get_service("redis")
        if self._redis_service and not self._redis_service.is_initialized():
            await self._redis_service.initialize()
        return self._redis_service

    async def enqueue_job(
        self,
        queue_name: str,
        job_id: str,
        job_payload: bytes,
        score: int,
    ) -> None:
        """
        Mimic arq's internal enqueue using ZADD + HSET + PUBLISH.

        arq adds jobs to a sorted set and stores payloads in a hash.
        """
        redis = await self._get_redis()
        if not redis:
            raise RuntimeError("RedisService not available for arq adapter")

        commands: List[List[Any]] = [
            ["HSET", f"arq:job:{job_id}", "payload", job_payload.decode("utf-8", errors="replace")],
            ["ZADD", f"arq:queue:{queue_name}", score, job_id],
            ["PUBLISH", f"arq:q:{queue_name}", "1"],
        ]
        await redis.pipeline(commands)

    async def initialize(self) -> None:
        """Ensure the underlying RedisService is initialised."""
        await self._get_redis()
