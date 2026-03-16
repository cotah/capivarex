"""
Resilience Service — Supabase Outage Protection.

When Supabase is healthy:
- All queries go to Supabase normally
- Critical data is cached in Redis automatically (user profiles, auth, preferences)

When Supabase is down:
- Cached data served from Redis (login, chat, finance all keep working)
- Non-cacheable features show "temporarily unavailable"
- Health endpoint reports "degraded" instead of "down"

When Supabase recovers:
- Auto-detects recovery (circuit breaker already in place)
- Resumes normal operation seamlessly

Zero extra cost — uses existing Redis (Upstash).
"""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, TypeVar

from services.core import get_service

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Cache TTLs (seconds)
CACHE_TTL_USER = 3600  # 1 hour — user profiles change rarely
CACHE_TTL_PREFS = 3600  # 1 hour — preferences
CACHE_TTL_AUTH = 1800  # 30 min — auth tokens/sessions
CACHE_TTL_SHORT = 300  # 5 min — frequently changing data

# Track Supabase health
_supabase_healthy = True
_last_health_check = 0.0
_consecutive_failures = 0


def is_supabase_healthy() -> bool:
    """Check if Supabase is currently considered healthy."""
    return _supabase_healthy


def get_resilience_status() -> Dict[str, Any]:
    """Get current resilience status for health endpoint."""
    return {
        "supabase_healthy": _supabase_healthy,
        "mode": "normal" if _supabase_healthy else "degraded",
        "consecutive_failures": _consecutive_failures,
        "cache_backend": "redis",
    }


def _mark_supabase_down() -> None:
    """Mark Supabase as unhealthy."""
    global _supabase_healthy, _consecutive_failures
    _consecutive_failures += 1
    if _consecutive_failures >= 3:
        if _supabase_healthy:
            logger.warning(
                "RESILIENCE: Supabase marked DOWN after %d consecutive failures. "
                "Switching to Redis cache fallback.",
                _consecutive_failures,
            )
        _supabase_healthy = False


def _mark_supabase_up() -> None:
    """Mark Supabase as healthy again."""
    global _supabase_healthy, _consecutive_failures
    if not _supabase_healthy:
        logger.info("RESILIENCE: Supabase is back UP. Resuming normal operation.")
    _supabase_healthy = True
    _consecutive_failures = 0


# ---------------------------------------------------------------------------
# Cache Operations
# ---------------------------------------------------------------------------

async def cache_set(key: str, data: Any, ttl: int = CACHE_TTL_USER) -> bool:
    """Store data in Redis cache."""
    redis = get_service("redis")
    if not redis or not redis.is_initialized():
        return False

    try:
        cache_key = f"resilience:{key}"
        await redis.set(cache_key, json.dumps(data, default=str), ttl=ttl)
        return True
    except Exception:
        return False


async def cache_get(key: str) -> Optional[Any]:
    """Retrieve data from Redis cache."""
    redis = get_service("redis")
    if not redis or not redis.is_initialized():
        return None

    try:
        cache_key = f"resilience:{key}"
        data = await redis.get(cache_key, parse_json=True)
        return data
    except Exception:
        return None


async def cache_delete(key: str) -> bool:
    """Delete data from Redis cache."""
    redis = get_service("redis")
    if not redis or not redis.is_initialized():
        return False

    try:
        cache_key = f"resilience:{key}"
        await redis.delete(cache_key)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Resilient Query Wrapper
# ---------------------------------------------------------------------------

async def resilient_query(
    cache_key: str,
    supabase_fn: Callable,
    ttl: int = CACHE_TTL_USER,
    cache_empty: bool = False,
) -> Optional[Any]:
    """
    Execute a Supabase query with automatic Redis cache fallback.

    1. Try Supabase first
    2. On success: cache result in Redis, mark Supabase healthy
    3. On failure: serve from Redis cache, mark Supabase unhealthy

    Args:
        cache_key: Unique key for this data (e.g. "user:abc123")
        supabase_fn: Async callable that fetches from Supabase
        ttl: Cache TTL in seconds
        cache_empty: Whether to cache empty/None results (default False)

    Returns: Data from Supabase (fresh) or Redis (cached), or None if both fail.
    """
    # Try Supabase first
    try:
        result = await supabase_fn()
        _mark_supabase_up()

        # Cache successful result
        if result is not None or cache_empty:
            await cache_set(cache_key, result, ttl=ttl)

        return result

    except Exception as e:
        _mark_supabase_down()
        logger.warning(
            "RESILIENCE: Supabase query failed for key=%s: %s. Trying Redis cache.",
            cache_key, type(e).__name__,
        )

    # Fallback to Redis cache
    cached = await cache_get(cache_key)
    if cached is not None:
        logger.info("RESILIENCE: Serving cached data for key=%s", cache_key)
        return cached

    logger.warning("RESILIENCE: No cache available for key=%s", cache_key)
    return None


# ---------------------------------------------------------------------------
# Pre-built Resilient Operations (most common queries)
# ---------------------------------------------------------------------------

async def get_user_resilient(user_id: str) -> Optional[Dict[str, Any]]:
    """Get user profile with Redis fallback."""
    db = get_service("database")
    if not db:
        return await cache_get(f"user:{user_id}")

    return await resilient_query(
        cache_key=f"user:{user_id}",
        supabase_fn=lambda: db.get_user_by_id(user_id),
        ttl=CACHE_TTL_USER,
    )


async def get_proactivity_users_resilient() -> List[Dict[str, Any]]:
    """Get all users with proactivity enabled, with cache fallback."""
    db = get_service("database")
    if not db:
        cached = await cache_get("proactivity_users")
        return cached or []

    result = await resilient_query(
        cache_key="proactivity_users",
        supabase_fn=lambda: db.get_all_users_with_proactivity_enabled(),
        ttl=CACHE_TTL_SHORT,
    )
    return result or []


async def cache_user_on_login(user_id: str, user_data: Dict[str, Any]) -> None:
    """Cache user profile on successful login (proactive caching)."""
    await cache_set(f"user:{user_id}", user_data, ttl=CACHE_TTL_USER)


async def cache_auth_token(user_id: str, token_data: Dict[str, Any]) -> None:
    """Cache auth token data for session continuity during outages."""
    await cache_set(f"auth:{user_id}", token_data, ttl=CACHE_TTL_AUTH)


async def get_auth_cached(user_id: str) -> Optional[Dict[str, Any]]:
    """Get cached auth data during Supabase outage."""
    return await cache_get(f"auth:{user_id}")
