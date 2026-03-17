"""
Context-aware Silence Service — Knows when NOT to notify (N5).

Prevents the bot from being annoying by detecting when the user is:
- In a meeting (calendar event happening now)
- Sleeping (based on sleep/wake preferences or late hours)
- In Focus Mode (B6 integration)
- Marked as "busy" or "do not disturb"

When silent: queues notifications instead of sending them.
When available again: delivers a summary of what was held.

Integration points:
- Called by proactivity service BEFORE sending any notification
- Integrates with Focus Mode (B6), Sleep/Wake (B1), Calendar
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Default quiet hours (UTC) — user can customize
DEFAULT_QUIET_START = 23  # 23:00
DEFAULT_QUIET_END = 7     # 07:00

# Max queued notifications
MAX_QUEUE = 30

# Reasons for silence
REASON_MEETING = "meeting"
REASON_FOCUS = "focus"
REASON_SLEEPING = "sleeping"
REASON_DND = "dnd"
REASON_NONE = None


async def should_be_silent(user_id: str) -> Dict[str, Any]:
    """
    Check if the bot should be silent right now for this user.

    Returns:
        {
            "silent": True/False,
            "reason": "meeting" | "focus" | "sleeping" | "dnd" | None,
            "until": "09:00" (estimated end time) or None,
            "details": "Sprint Review meeting" or None,
        }
    """
    # 1. Check Focus Mode (highest priority — user explicitly asked)
    focus = await _check_focus_mode(user_id)
    if focus["silent"]:
        return focus

    # 2. Check current meeting
    meeting = await _check_current_meeting(user_id)
    if meeting["silent"]:
        return meeting

    # 3. Check quiet hours / sleeping
    sleeping = await _check_quiet_hours(user_id)
    if sleeping["silent"]:
        return sleeping

    # 4. Check manual DND
    dnd = await _check_dnd(user_id)
    if dnd["silent"]:
        return dnd

    return {"silent": False, "reason": None, "until": None, "details": None}


async def _check_focus_mode(user_id: str) -> Dict[str, Any]:
    """Check if Focus Mode is active."""
    try:
        from services.business.focus_mode_service import is_focus_active, get_focus_state
        if await is_focus_active(user_id):
            state = await get_focus_state(user_id)
            ends_at = ""
            if state and state.get("ends_at"):
                ends_at = datetime.fromtimestamp(state["ends_at"]).strftime("%H:%M")
            return {
                "silent": True,
                "reason": REASON_FOCUS,
                "until": ends_at,
                "details": "Focus Mode ativo",
            }
    except Exception as e:
        logger.debug("Focus mode check failed: %s", e)

    return {"silent": False, "reason": None, "until": None, "details": None}


async def _check_current_meeting(user_id: str) -> Dict[str, Any]:
    """Check if user is currently in a calendar meeting."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return {"silent": False, "reason": None, "until": None, "details": None}

        client = db.get_client()
        now = datetime.now(timezone.utc).isoformat()

        result = (
            client.table("calendar_events")
            .select("title, end_time")
            .eq("user_id", user_id)
            .lte("start_time", now)
            .gte("end_time", now)
            .order("end_time")
            .limit(1)
            .execute()
        )

        if result.data:
            event = result.data[0]
            end_time = event.get("end_time", "")
            title = event.get("title", "Meeting")

            # Parse end time
            until = ""
            try:
                end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
                until = end_dt.strftime("%H:%M")
            except (ValueError, TypeError):
                pass

            return {
                "silent": True,
                "reason": REASON_MEETING,
                "until": until,
                "details": title,
            }

    except Exception as e:
        logger.debug("Meeting check failed: %s", e)

    return {"silent": False, "reason": None, "until": None, "details": None}


async def _check_quiet_hours(user_id: str) -> Dict[str, Any]:
    """Check if it's currently quiet hours (sleeping time)."""
    try:
        # Get user's quiet hours preferences
        quiet_start, quiet_end = await _get_quiet_hours(user_id)
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        is_quiet = False
        if quiet_start > quiet_end:
            # Wraps midnight: e.g. 23-07
            is_quiet = current_hour >= quiet_start or current_hour < quiet_end
        else:
            # Same day: e.g. 13-14 (nap?)
            is_quiet = quiet_start <= current_hour < quiet_end

        if is_quiet:
            return {
                "silent": True,
                "reason": REASON_SLEEPING,
                "until": f"{quiet_end:02d}:00",
                "details": "Horário de silêncio",
            }

    except Exception as e:
        logger.debug("Quiet hours check failed: %s", e)

    return {"silent": False, "reason": None, "until": None, "details": None}


async def _check_dnd(user_id: str) -> Dict[str, Any]:
    """Check if user manually set DND mode."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return {"silent": False, "reason": None, "until": None, "details": None}

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "dnd_mode")
            .limit(1)
            .execute()
        )

        if result.data:
            import json
            val = result.data[0].get("value", "{}")
            data = json.loads(val) if isinstance(val, str) else val
            if data.get("active"):
                until = data.get("until", "")
                # Check if expired
                if until:
                    try:
                        until_ts = float(until)
                        if until_ts < time.time():
                            return {"silent": False, "reason": None, "until": None, "details": None}
                        until = datetime.fromtimestamp(until_ts).strftime("%H:%M")
                    except (ValueError, TypeError):
                        pass

                return {
                    "silent": True,
                    "reason": REASON_DND,
                    "until": until,
                    "details": "Modo não perturbe",
                }

    except Exception as e:
        logger.debug("DND check failed: %s", e)

    return {"silent": False, "reason": None, "until": None, "details": None}


async def _get_quiet_hours(user_id: str) -> tuple:
    """Get user's configured quiet hours. Returns (start_hour, end_hour)."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return DEFAULT_QUIET_START, DEFAULT_QUIET_END

        client = db.get_client()
        result = (
            client.table("user_preferences")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "quiet_hours")
            .limit(1)
            .execute()
        )

        if result.data:
            import json
            val = result.data[0].get("value", "{}")
            data = json.loads(val) if isinstance(val, str) else val
            return data.get("start", DEFAULT_QUIET_START), data.get("end", DEFAULT_QUIET_END)

    except Exception:
        pass

    return DEFAULT_QUIET_START, DEFAULT_QUIET_END


# ---------------------------------------------------------------------------
# Notification Queue — hold notifications during silence
# ---------------------------------------------------------------------------

async def queue_notification(user_id: str, notification: str, source: str = "") -> None:
    """Queue a notification to be delivered when user is available."""
    try:
        import json
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        queue = await _get_queue(user_id)

        queue.append({
            "text": notification[:500],
            "source": source,
            "time": time.time(),
        })

        # Keep max
        queue = queue[-MAX_QUEUE:]

        client.table("user_context").upsert({
            "user_id": user_id,
            "key": "notification_queue",
            "value": json.dumps(queue),
        }).execute()

    except Exception as e:
        logger.warning("Queue notification failed: %s", e)


async def flush_queue(user_id: str, user_name: str = "") -> Optional[str]:
    """
    Deliver all queued notifications as a summary.
    Called when user becomes available (meeting ends, wakes up, focus ends).

    Returns summary message or None if queue is empty.
    """
    queue = await _get_queue(user_id)
    if not queue:
        return None

    name = user_name.split()[0] if user_name else ""

    # Clear queue
    try:
        import json
        db = get_service("database")
        if db and db.is_initialized():
            client = db.get_client()
            client.table("user_context").upsert({
                "user_id": user_id,
                "key": "notification_queue",
                "value": json.dumps([]),
            }).execute()
    except Exception:
        pass

    # Format summary
    count = len(queue)
    plural = "notificações" if count > 1 else "notificação"
    msg = f"🔔 **Enquanto você estava ocupado** ({count} {plural}):\n\n"

    for item in queue[-10:]:  # Show last 10
        text = item.get("text", "")
        source = item.get("source", "")
        if source:
            msg += f"  • [{source}] {text}\n"
        else:
            msg += f"  • {text}\n"

    if count > 10:
        msg += f"\n  ... e mais {count - 10} notificações\n"

    msg += f"\n{name}, estou de volta! Como posso ajudar? 😊"

    return msg


async def _get_queue(user_id: str) -> List[Dict[str, Any]]:
    """Get queued notifications."""
    try:
        import json
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "notification_queue")
            .limit(1)
            .execute()
        )

        if result.data:
            val = result.data[0].get("value", "[]")
            return json.loads(val) if isinstance(val, str) else val
    except Exception:
        pass
    return []
