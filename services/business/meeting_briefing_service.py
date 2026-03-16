"""
Meeting Briefing Service — P14

Generates a proactive briefing 2 hours before calendar meetings:
- Meeting details (who, when, where)
- Context from past notes about this person/topic
- Suggested talking points via research
- Action items from previous meetings

Triggered by proactivity loop checking calendar events.
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from services.core import get_service


async def check_upcoming_meetings(user_id: str, chat_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Check if user has meetings in the next 2 hours and generate briefings.

    Returns list of briefings generated.
    """
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return []

    try:
        events = await calendar_svc.async_get_today_events(user_id=user_id)
        if not events or not isinstance(events, list):
            return []
    except Exception:
        return []

    now = datetime.now(timezone.utc)
    briefings = []

    for event in events:
        # Parse event start time
        start_str = event.get("start", event.get("time", ""))
        if not start_str:
            continue

        try:
            if "T" in str(start_str):
                start = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            else:
                continue  # All-day event, skip
        except (ValueError, TypeError):
            continue

        # Check if meeting is 1.5-2.5 hours from now (window to send briefing)
        time_until = start - now
        hours_until = time_until.total_seconds() / 3600

        if 1.5 <= hours_until <= 2.5:
            # Check if briefing already sent for this event
            event_id = event.get("id", event.get("summary", "")[:30])
            if await _briefing_sent_for_event(user_id, event_id):
                continue

            briefing = await _generate_meeting_briefing(user_id, event, hours_until)
            if briefing:
                await _store_briefing(user_id, event_id, briefing)
                briefings.append(briefing)

                # Send via Telegram
                if chat_id:
                    try:
                        notif = get_service("notification")
                        if notif:
                            if not notif.is_initialized():
                                await notif.initialize()
                            await notif.send_message("telegram", chat_id, briefing["message"])
                    except Exception as e:
                        logger.warning("Meeting briefing: Telegram failed: {}", e)

    return briefings


async def _generate_meeting_briefing(
    user_id: str, event: Dict[str, Any], hours_until: float
) -> Optional[Dict[str, Any]]:
    """Generate briefing for a specific meeting."""
    summary = event.get("summary", "Meeting")
    location = event.get("location", "")
    description = event.get("description", "")
    attendees = event.get("attendees", [])
    start = event.get("start", event.get("time", ""))

    # Format time
    try:
        if "T" in str(start):
            dt = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
            time_str = dt.strftime("%H:%M")
        else:
            time_str = str(start)
    except Exception:
        time_str = str(start)

    hours_text = f"{hours_until:.0f}h" if hours_until >= 1 else f"{hours_until * 60:.0f}min"

    # Build briefing
    parts = [
        f"📋 **Meeting briefing** — in {hours_text}\n",
        f"📌 **{summary}**",
        f"🕐 {time_str}",
    ]

    if location:
        parts.append(f"📍 {location}")

    if attendees:
        if isinstance(attendees, list):
            names = [a.get("email", a) if isinstance(a, dict) else str(a) for a in attendees[:5]]
            parts.append(f"👥 {', '.join(names)}")

    if description:
        parts.append(f"\n📝 **Notes:** {description[:200]}")

    # Try to get context from RAG/notes about this topic
    context = await _get_meeting_context(user_id, summary, attendees)
    if context:
        parts.append(f"\n💡 **Context:** {context}")

    parts.append("\n💬 Need me to prepare anything for this meeting?")

    message = "\n".join(parts)
    title = f"Meeting in {hours_text}: {summary[:50]}"

    return {"title": title, "message": message, "event_summary": summary}


async def _get_meeting_context(
    user_id: str, summary: str, attendees: List
) -> Optional[str]:
    """Try to get relevant context from RAG about the meeting topic or attendees."""
    rag_svc = get_service("rag")
    if not rag_svc or not rag_svc.is_initialized():
        return None

    try:
        # Search for context about the meeting topic
        query = f"meeting about {summary}"
        if attendees:
            names = [a.get("email", a) if isinstance(a, dict) else str(a) for a in attendees[:3]]
            query += f" with {', '.join(names)}"

        results = await rag_svc.search(user_id, query, limit=2)
        if results and isinstance(results, list) and len(results) > 0:
            # Combine top results into brief context
            contexts = [r.get("content", r.get("text", ""))[:150] for r in results[:2]]
            return " | ".join(c for c in contexts if c)
    except Exception as e:
        logger.debug("Meeting context RAG search failed: {}", e)

    return None


async def _briefing_sent_for_event(user_id: str, event_id: str) -> bool:
    """Check if briefing already sent for this event today."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
        result = (
            client.table("proactivity_feed")
            .select("id")
            .eq("user_id", user_id)
            .eq("type", "meeting_briefing")
            .gte("created_at", today_start)
            .limit(10)
            .execute()
        )
        # Check if any briefing matches this event
        for item in (result.data or []):
            metadata = item.get("metadata", "{}")
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            if metadata.get("event_id") == event_id:
                return True
        return False
    except Exception:
        return False


async def _store_briefing(user_id: str, event_id: str, briefing: Dict[str, Any]) -> None:
    """Store briefing in proactivity_feed."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "meeting_briefing",
            "title": briefing["title"],
            "message": briefing["message"],
            "metadata": json.dumps({"event_id": event_id, "event": briefing.get("event_summary", "")}),
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("Meeting briefing: failed to store: {}", e)
