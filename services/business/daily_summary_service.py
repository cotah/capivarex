"""
Daily Summary Service — End-of-day recap (B7).

Generates a personalized evening summary combining:
- Calendar events completed today
- Pending tasks/reminders not done
- Finance: spending today (if tracked)
- Tomorrow's preview (first 3 events)
- Focus time (if focus mode was used)
- Messages/emails summary

Triggered via proactivity loop (~18:00 local time).
Complements the Morning Briefing (S1).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)


async def generate_daily_summary(
    user_id: str,
    user_name: str = "",
    location: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Generate end-of-day summary for a user.

    Returns: {"text": "formatted summary", "data": {...raw data...}}
    """
    name = user_name.split()[0] if user_name else ""
    data: Dict[str, Any] = {}

    # 1. Today's calendar events
    today_events = await _get_today_events(user_id)
    data["events_today"] = today_events

    # 2. Tomorrow's preview
    tomorrow_events = await _get_tomorrow_events(user_id)
    data["events_tomorrow"] = tomorrow_events

    # 3. Pending reminders/tasks
    pending = await _get_pending_tasks(user_id)
    data["pending_tasks"] = pending

    # 4. Focus time used today
    focus_time = await _get_focus_time_today(user_id)
    data["focus_minutes"] = focus_time

    # 5. Generate humanized summary via AI
    text = await _generate_ai_summary(name, data)
    if not text:
        text = _generate_fallback_summary(name, data)

    # 6. Store in proactivity feed
    await _store_summary(user_id, text, data)

    return {"text": text, "data": data}


async def _get_today_events(user_id: str) -> List[Dict[str, str]]:
    """Get calendar events for today."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result = (
            client.table("calendar_events")
            .select("title, start_time, end_time")
            .eq("user_id", user_id)
            .gte("start_time", f"{today}T00:00:00")
            .lte("start_time", f"{today}T23:59:59")
            .order("start_time")
            .limit(20)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Daily summary: events fetch failed: %s", e)
        return []


async def _get_tomorrow_events(user_id: str) -> List[Dict[str, str]]:
    """Get first 3 events for tomorrow."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        result = (
            client.table("calendar_events")
            .select("title, start_time")
            .eq("user_id", user_id)
            .gte("start_time", f"{tomorrow}T00:00:00")
            .lte("start_time", f"{tomorrow}T23:59:59")
            .order("start_time")
            .limit(3)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Daily summary: tomorrow events failed: %s", e)
        return []


async def _get_pending_tasks(user_id: str) -> List[Dict[str, str]]:
    """Get overdue or pending reminders/notes tasks."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        now = datetime.now(timezone.utc).isoformat()

        result = (
            client.table("reminders")
            .select("title, remind_at")
            .eq("user_id", user_id)
            .eq("completed", False)
            .lte("remind_at", now)
            .order("remind_at")
            .limit(10)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Daily summary: pending tasks failed: %s", e)
        return []


async def _get_focus_time_today(user_id: str) -> int:
    """Get total focus time used today (minutes)."""
    try:
        from services.business.focus_mode_service import get_focus_state

        state = await get_focus_state(user_id)
        if not state:
            return 0

        import time

        started = state.get("started_at", 0)
        today_start = (
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).timestamp()
        )

        if started >= today_start:
            duration = state.get("duration_minutes", 0)
            if not state.get("active"):
                return duration
            # Currently active — calculate elapsed
            elapsed = int((time.time() - started) / 60)
            return min(elapsed, duration)
        return 0
    except Exception:
        return 0


async def _generate_ai_summary(name: str, data: Dict[str, Any]) -> Optional[str]:
    """Generate humanized summary using GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    events_count = len(data.get("events_today", []))
    pending_count = len(data.get("pending_tasks", []))
    tomorrow_count = len(data.get("events_tomorrow", []))
    focus = data.get("focus_minutes", 0)

    events_list = ""
    for e in data.get("events_today", [])[:5]:
        events_list += f"  - {e.get('title', 'Event')}\n"

    pending_list = ""
    for t in data.get("pending_tasks", [])[:5]:
        pending_list += f"  - {t.get('title', 'Task')}\n"

    for e in data.get("events_tomorrow", [])[:3]:
        events_list += f"  - {e.get('title', 'Event')}\n"

    prompt = (
        f"You are Capivarex, a warm AI assistant. Generate a brief end-of-day summary "
        f"for {name or 'the user'}. Keep it concise (5-8 lines max), warm, and use emojis.\n\n"
        f"Today's data:\n"
        f"- Events today: {events_count} ({events_list.strip() or 'none'})\n"
        f"- Pending tasks: {pending_count} ({pending_list.strip() or 'none'})\n"
        f"- Tomorrow events: {tomorrow_count}\n"
        f"- Focus time: {focus} minutes\n\n"
        f"Format: Start with '📊 Daily Summary' header. Use short bullet points. "
        f"End with an encouraging note about tomorrow. Respond in English."
    )

    try:
        import asyncio

        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=300,
            temperature=0.7,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 20:
            return text
    except Exception as e:
        logger.warning("Daily summary AI failed: %s", e)

    return None


def _generate_fallback_summary(name: str, data: Dict[str, Any]) -> str:
    """Generate summary without AI (fallback)."""
    greeting = f"Hi {name}!" if name else "Hi!"
    events = data.get("events_today", [])
    pending = data.get("pending_tasks", [])
    tomorrow = data.get("events_tomorrow", [])
    focus = data.get("focus_minutes", 0)

    msg = f"📊 **Daily Summary**\n\n{greeting} Here's how your day went:\n\n"

    # Events
    if events:
        msg += f"📅 **{len(events)} event{'s' if len(events) > 1 else ''}** today"
        titles = [e.get("title", "") for e in events[:3] if e.get("title")]
        if titles:
            msg += ": " + ", ".join(titles)
        msg += "\n"
    else:
        msg += "📅 No events today\n"

    # Pending
    if pending:
        msg += f"⚠️ **{len(pending)} task{'s' if len(pending) > 1 else ''} pending**"
        titles = [t.get("title", "") for t in pending[:3] if t.get("title")]
        if titles:
            msg += ": " + ", ".join(titles)
        msg += "\n"

    # Focus
    if focus > 0:
        hours = focus // 60
        mins = focus % 60
        if hours:
            msg += f"🎯 Focus time: **{hours}h{mins}min**\n"
        else:
            msg += f"🎯 Focus time: **{mins} minutes**\n"

    # Tomorrow
    msg += "\n"
    if tomorrow:
        msg += (
            f"📆 **Tomorrow:** {len(tomorrow)} event{'s' if len(tomorrow) > 1 else ''}"
        )
        first = tomorrow[0].get("title", "")
        if first:
            msg += f" — first: {first}"
        msg += "\n"
    else:
        msg += "📆 Tomorrow: schedule free 🎉\n"

    msg += "\nRest well! Tomorrow is a new day. 😊"
    return msg


async def _store_summary(user_id: str, text: str, data: Dict[str, Any]) -> None:
    """Store daily summary in proactivity feed."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": "daily_summary",
                "content": text[:2000],
                "metadata": json.dumps(
                    {
                        "events_count": len(data.get("events_today", [])),
                        "pending_count": len(data.get("pending_tasks", [])),
                        "focus_minutes": data.get("focus_minutes", 0),
                    }
                ),
            }
        ).execute()
    except Exception as e:
        logger.warning("Daily summary store failed: %s", e)
