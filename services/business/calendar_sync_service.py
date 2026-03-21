# -*- coding: utf-8 -*-
"""
services/business/calendar_sync_service.py
==========================================
Synchronizes calendar events from Google Calendar and Microsoft Outlook
into the local `calendar_events` Supabase table.

This service is designed to run as a periodic job (e.g., every 15 minutes
via ARQ cron). It:
1. Finds all users with active Google or Microsoft OAuth tokens
2. Fetches upcoming events (next 14 days) from each provider
3. Upserts into `calendar_events` using (user_id, source, source_event_id)
   as the unique key — preventing duplicates

The proactivity services (daily_summary, commute_optimizer, sleep_wake,
weekly_planner, etc.) read from this table instead of calling the
calendar APIs directly, reducing API calls and latency.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("capivarex.calendar_sync")

# How many days ahead to sync
SYNC_DAYS_AHEAD = 14


async def _get_db():
    """Get Supabase client."""
    from services.core import get_service

    db = get_service("database")
    if db and not db.is_initialized():
        await db.initialize()
    return db.get_client() if db else None


async def _get_connected_users() -> List[Dict[str, Any]]:
    """Find all users with active Google or Microsoft OAuth tokens.

    Returns list of dicts: [{user_id, provider}, ...]
    """
    db = await _get_db()
    if not db:
        logger.warning("calendar_sync: database not available")
        return []

    try:
        result = (
            db.table("user_oauth_tokens")
            .select("user_id, provider")
            .eq("active", True)
            .in_("provider", ["google", "microsoft"])
            .execute()
        )
        # Deduplicate: one entry per (user_id, provider)
        seen = set()
        users = []
        for row in result.data or []:
            key = (row["user_id"], row["provider"])
            if key not in seen:
                seen.add(key)
                users.append(row)
        return users
    except Exception as e:
        logger.error("calendar_sync: failed to get connected users: %s", e)
        return []


async def _fetch_google_events(user_id: str) -> List[Dict[str, Any]]:
    """Fetch upcoming events from Google Calendar for a user."""
    try:
        from services.integrations.calendar_service import get_calendar_service

        cal = get_calendar_service()
        if not cal.is_initialized():
            await cal.initialize()

        events = await cal.async_get_upcoming_events(
            user_id=user_id,
            max_results=50,
            days_ahead=SYNC_DAYS_AHEAD,
        )
        return [_normalize_google_event(e) for e in events]
    except Exception as e:
        logger.debug("calendar_sync: Google Calendar failed for user=%s: %s", user_id[:8], e)
        return []


async def _fetch_microsoft_events(user_id: str) -> List[Dict[str, Any]]:
    """Fetch upcoming events from Outlook Calendar for a user."""
    try:
        from services.core import get_service

        outlook_cal = get_service("outlook_calendar")
        if not outlook_cal:
            return []
        if not outlook_cal.is_initialized():
            await outlook_cal.initialize()

        events = await outlook_cal.async_get_upcoming_events(
            user_id=user_id,
            max_results=50,
            days_ahead=SYNC_DAYS_AHEAD,
        )
        return [_normalize_microsoft_event(e) for e in events]
    except Exception as e:
        logger.debug("calendar_sync: Outlook Calendar failed for user=%s: %s", user_id[:8], e)
        return []


def _normalize_google_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Google Calendar event to calendar_events table format."""
    start_raw = event.get("start", "")
    end_raw = event.get("end", "")
    all_day = False

    # Google sends date for all-day, dateTime for timed events
    if isinstance(start_raw, str) and len(start_raw) == 10:
        all_day = True

    return {
        "title": event.get("summary", "No title"),
        "description": (event.get("description") or "")[:2000],
        "start_time": start_raw,
        "end_time": end_raw,
        "location": event.get("location", ""),
        "source": "google",
        "source_event_id": event.get("id", ""),
        "all_day": all_day,
        "recurring": bool(event.get("recurringEventId")),
        "status": event.get("status", "confirmed"),
    }


def _normalize_microsoft_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Outlook Calendar event to calendar_events table format."""
    return {
        "title": event.get("summary", "No title"),
        "description": (event.get("description") or "")[:2000],
        "start_time": event.get("start", ""),
        "end_time": event.get("end", ""),
        "location": event.get("location", ""),
        "source": "microsoft",
        "source_event_id": event.get("id", ""),
        "all_day": event.get("isAllDay", False),
        "recurring": False,
        "status": event.get("status", "confirmed"),
    }


async def _upsert_events(
    user_id: str, events: List[Dict[str, Any]]
) -> int:
    """Upsert events into calendar_events table. Returns count of upserted rows."""
    if not events:
        return 0

    db = await _get_db()
    if not db:
        return 0

    upserted = 0
    for event in events:
        try:
            row = {
                "user_id": user_id,
                "title": event["title"],
                "description": event.get("description", ""),
                "start_time": event["start_time"],
                "end_time": event.get("end_time"),
                "location": event.get("location", ""),
                "source": event["source"],
                "source_event_id": event["source_event_id"],
                "all_day": event.get("all_day", False),
                "recurring": event.get("recurring", False),
                "status": event.get("status", "confirmed"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            db.table("calendar_events").upsert(
                row, on_conflict="user_id,source,source_event_id"
            ).execute()
            upserted += 1
        except Exception as e:
            logger.debug("calendar_sync: upsert failed for event %s: %s", event.get("source_event_id", "?")[:12], e)

    return upserted


async def _cleanup_past_events(user_id: str, days_ago: int = 7) -> int:
    """Remove events older than N days to keep the table clean."""
    db = await _get_db()
    if not db:
        return 0

    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        result = (
            db.table("calendar_events")
            .delete()
            .eq("user_id", user_id)
            .lt("end_time", cutoff)
            .execute()
        )
        return len(result.data or [])
    except Exception as e:
        logger.debug("calendar_sync: cleanup failed for user=%s: %s", user_id[:8], e)
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════


async def sync_user_calendar(user_id: str, provider: str) -> int:
    """Sync a single user's calendar from the given provider.

    Returns number of events synced.
    """
    if provider == "google":
        events = await _fetch_google_events(user_id)
    elif provider == "microsoft":
        events = await _fetch_microsoft_events(user_id)
    else:
        logger.warning("calendar_sync: unknown provider '%s'", provider)
        return 0

    count = await _upsert_events(user_id, events)
    if count > 0:
        logger.info(
            "calendar_sync: user=%s provider=%s synced %d events",
            user_id[:8], provider, count,
        )
    return count


async def sync_all_calendars() -> Dict[str, Any]:
    """Sync calendars for ALL users with active OAuth connections.

    This is the main entry point — call from ARQ cron job.
    Returns summary stats.
    """
    users = await _get_connected_users()
    if not users:
        logger.debug("calendar_sync: no connected users found")
        return {"users_synced": 0, "total_events": 0}

    total_events = 0
    users_synced = 0
    errors = 0

    for user_info in users:
        user_id = user_info["user_id"]
        provider = user_info["provider"]

        try:
            count = await sync_user_calendar(user_id, provider)
            if count > 0:
                users_synced += 1
                total_events += count

            # Clean up old events while we're at it
            await _cleanup_past_events(user_id)
        except Exception as e:
            errors += 1
            logger.warning(
                "calendar_sync: failed for user=%s provider=%s: %s",
                user_id[:8], provider, e,
            )

    logger.info(
        "calendar_sync: completed — %d users, %d events synced, %d errors",
        users_synced, total_events, errors,
    )
    return {
        "users_synced": users_synced,
        "total_events": total_events,
        "errors": errors,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Cache read API — used by proactivity_service and calendar_agent
# ═══════════════════════════════════════════════════════════════════════════


async def get_cached_events(
    user_id: str,
    days_ahead: int = 7,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Read upcoming events from the local calendar_events cache (Supabase).

    Returns events from now until `days_ahead` days ahead, ordered by start_time.
    Returns empty list if the cache is empty or unavailable.
    """
    db = await _get_db()
    if not db:
        return []
    try:
        now = datetime.now(timezone.utc).isoformat()
        future = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
        result = (
            db.table("calendar_events")
            .select("title, description, start_time, end_time, location, source, all_day, status")
            .eq("user_id", user_id)
            .gte("start_time", now)
            .lte("start_time", future)
            .order("start_time", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.debug("calendar_sync: get_cached_events failed for user=%s: %s", user_id[:8], e)
        return []


async def get_next_cached_event(user_id: str) -> Optional[Dict[str, Any]]:
    """Return the next upcoming event from the local cache.

    Returns None if no events are cached.
    """
    events = await get_cached_events(user_id, days_ahead=7, limit=1)
    return events[0] if events else None
