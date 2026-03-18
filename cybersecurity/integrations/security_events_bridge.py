"""Security Events Bridge — reads from the existing security_events table."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("cybersecurity.security_events_bridge")


async def get_recent_events(
    minutes: int = 60,
    event_type: str | None = None,
    severity: str | None = None,
    limit: int = 500,
) -> list[dict]:
    """Fetch recent security events from Supabase."""
    try:
        from services import get_service

        db = get_service("database")
        if not db or not db.client:
            return []
    except Exception:
        return []

    window_start = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()

    try:
        query = (
            db.client.table("security_events")
            .select("*")
            .gte("created_at", window_start)
            .order("created_at", desc=True)
            .limit(limit)
        )

        if event_type:
            query = query.eq("event_type", event_type)
        if severity:
            query = query.eq("severity", severity)

        result = query.execute()
        return result.data or []
    except Exception:
        logger.debug("Failed to query security_events")
        return []


async def get_event_counts_by_type(minutes: int = 60) -> dict[str, int]:
    """Get aggregated event counts by type."""
    events = await get_recent_events(minutes=minutes)
    counts: dict[str, int] = {}
    for ev in events:
        etype = ev.get("event_type", "unknown")
        counts[etype] = counts.get(etype, 0) + 1
    return counts


async def get_top_offending_ips(minutes: int = 60, limit: int = 10) -> list[dict]:
    """Get IPs with most security events."""
    events = await get_recent_events(minutes=minutes)
    ip_counts: dict[str, int] = {}
    for ev in events:
        ip = ev.get("ip_address", "unknown")
        if ip and ip != "unknown":
            ip_counts[ip] = ip_counts.get(ip, 0) + 1

    sorted_ips = sorted(ip_counts.items(), key=lambda x: x[1], reverse=True)[:limit]
    return [{"ip": ip, "count": count} for ip, count in sorted_ips]
