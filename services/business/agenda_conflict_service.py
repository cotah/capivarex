"""
Agenda Conflict Detection Service — A5 (P15)

Proactively scans calendar for conflicts:
1. Overlapping events (same time slot)
2. Back-to-back meetings without travel time
3. Events at different locations without enough gap

When detected:
- Sends humanized alert: "Tens 2 reuniões sobrepostas sexta às 15h!"
- Suggests: reschedule, cancel, or make one virtual
- Offers to help resolve

All output HUMANIZED via GPT.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Minimum gap between events at different locations (minutes)
MIN_TRAVEL_GAP = 30


async def detect_conflicts(
    user_id: str,
    days_ahead: int = 7,
) -> List[Dict[str, Any]]:
    """
    Scan calendar for conflicts in the next N days.

    Returns list of conflicts found.
    """
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return []

    try:
        events = await calendar_svc.async_get_upcoming_events(
            user_id=user_id,
            max_results=50,
            days_ahead=days_ahead,
        )
        if not events or len(events) < 2:
            return []
    except Exception as e:
        logger.warning("Conflict detection: calendar failed: %s", e)
        return []

    # Parse events into time ranges
    parsed = _parse_events(events)
    if len(parsed) < 2:
        return []

    # Sort by start time
    parsed.sort(key=lambda e: e["start_dt"])

    # Detect overlaps and tight gaps
    conflicts = []

    for i in range(len(parsed)):
        for j in range(i + 1, len(parsed)):
            ev_a = parsed[i]
            ev_b = parsed[j]

            # Skip if too far apart (optimization)
            if ev_b["start_dt"] > ev_a["end_dt"] + timedelta(hours=2):
                break

            conflict = _check_pair(ev_a, ev_b)
            if conflict:
                conflicts.append(conflict)

    return conflicts


def _parse_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Parse raw calendar events into structured time ranges."""
    parsed = []

    for event in events:
        start_str = event.get("start", "")
        end_str = event.get("end", "")

        # Skip all-day events (no time component)
        if "T" not in str(start_str):
            continue

        try:
            start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(str(end_str).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        parsed.append(
            {
                "id": event.get("id", ""),
                "summary": event.get("summary", "Event"),
                "location": event.get("location", ""),
                "start_dt": start_dt,
                "end_dt": end_dt,
                "start_str": start_dt.strftime("%a %b %d, %H:%M"),
                "end_str": end_dt.strftime("%H:%M"),
            }
        )

    return parsed


def _check_pair(
    ev_a: Dict[str, Any],
    ev_b: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Check if two events conflict."""
    a_start, a_end = ev_a["start_dt"], ev_a["end_dt"]
    b_start, b_end = ev_b["start_dt"], ev_b["end_dt"]

    # Check overlap (a starts before b ends AND b starts before a ends)
    if a_start < b_end and b_start < a_end:
        return {
            "type": "overlap",
            "event_a": ev_a,
            "event_b": ev_b,
            "description": (
                f"'{ev_a['summary']}' ({ev_a['start_str']}-{ev_a['end_str']}) "
                f"overlaps with '{ev_b['summary']}' ({ev_b['start_str']}-{ev_b['end_str']})"
            ),
        }

    # Check tight gap with different locations
    gap_minutes = (b_start - a_end).total_seconds() / 60
    loc_a = ev_a.get("location", "")
    loc_b = ev_b.get("location", "")

    if (
        0 <= gap_minutes < MIN_TRAVEL_GAP
        and loc_a
        and loc_b
        and loc_a.lower() != loc_b.lower()
    ):
        return {
            "type": "tight_gap",
            "event_a": ev_a,
            "event_b": ev_b,
            "gap_minutes": int(gap_minutes),
            "description": (
                f"Only {int(gap_minutes)} min between "
                f"'{ev_a['summary']}' at {loc_a} and "
                f"'{ev_b['summary']}' at {loc_b}"
            ),
        }

    return None


# ---------------------------------------------------------------------------
# Alert Generation
# ---------------------------------------------------------------------------


async def generate_conflict_alert(
    user_name: str,
    conflicts: List[Dict[str, Any]],
) -> Optional[str]:
    """Generate humanized conflict alert."""
    if not conflicts:
        return None

    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    raw = f"User: {name}\nConflicts found: {len(conflicts)}\n"
    for i, c in enumerate(conflicts[:5], 1):
        raw += f"{i}. [{c['type']}] {c['description']}\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} has calendar conflicts. Generate a brief, helpful alert.

RULES:
- Be warm, proactive: "I noticed something in your calendar..."
- For overlaps: suggest rescheduling one, making one virtual, or cancelling
- For tight gaps: suggest adding travel time or making one virtual
- Keep under 6 lines
- Use 2 emojis: ⚠️ for the alert, 📅 for calendar
- Sound like a helpful PA, not an error message

RAW DATA:
{raw}

Generate:"""

        try:
            import asyncio

            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=300,
                temperature=0.8,
            )
            text = (
                response if isinstance(response, str) else response.get("content", "")
            )
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    lines = [
        f"⚠️ Hey {name}, I found {len(conflicts)} calendar conflict{'s' if len(conflicts) > 1 else ''}:\n"
    ]
    for c in conflicts[:3]:
        if c["type"] == "overlap":
            lines.append(f"📅 {c['description']}")
        else:
            lines.append(f"🚗 {c['description']}")

    lines.append("\n💬 Want me to help reschedule or make one virtual?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Proactivity Loop Runner
# ---------------------------------------------------------------------------


async def check_conflicts_for_all_users() -> int:
    """Run conflict detection for all proactivity-enabled users.
    Returns number of alerts sent.
    """
    db = get_service("database")
    if not db or not db.is_initialized():
        return 0

    try:
        pref_users = await db.get_all_users_with_proactivity_enabled()
    except Exception:
        return 0

    alerts_sent = 0
    for pref in pref_users or []:
        user_id = pref["user_id"]
        try:
            user_data = await db.get_user_by_id(user_id)
            if not user_data:
                continue

            conflicts = await detect_conflicts(user_id, days_ahead=3)
            if not conflicts:
                continue

            # Dedup: only alert once per conflict pair per day
            new_conflicts = await _filter_already_alerted(user_id, conflicts)
            if not new_conflicts:
                continue

            alert = await generate_conflict_alert(
                user_name=user_data.get("full_name", ""),
                conflicts=new_conflicts,
            )
            if alert:
                # Send via notification
                chat_id = (
                    str(user_data.get("telegram_chat_id"))
                    if user_data.get("telegram_chat_id")
                    else None
                )
                if chat_id:
                    try:
                        notif = get_service("notification")
                        if notif:
                            if not notif.is_initialized():
                                await notif.initialize()
                            await notif.send_message("telegram", chat_id, alert)
                    except Exception:
                        pass

                # Store in proactivity feed
                await _store_conflict_alert(user_id, alert, new_conflicts)
                alerts_sent += 1

        except Exception as e:
            logger.warning("Conflict check failed for user=%s: %s", user_id[:8], e)

    if alerts_sent:
        logger.info("Conflict detector: %d alerts sent", alerts_sent)
    return alerts_sent


async def _filter_already_alerted(
    user_id: str,
    conflicts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Filter out conflicts that were already alerted today."""
    # Simple dedup: use event IDs to check
    # For now, return all — can add DB dedup later
    return conflicts


async def _store_conflict_alert(
    user_id: str,
    alert: str,
    conflicts: List[Dict[str, Any]],
) -> None:
    """Store conflict alert in proactivity_feed."""
    import json

    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        conflict_ids = [
            f"{c['event_a']['id']}-{c['event_b']['id']}" for c in conflicts[:5]
        ]
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": "agenda_conflict",
                "title": f"⚠️ {len(conflicts)} calendar conflict(s) detected",
                "message": alert,
                "metadata": json.dumps({"conflict_ids": conflict_ids}),
                "is_read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as e:
        logger.warning("Store conflict alert failed: %s", e)
