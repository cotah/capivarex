"""
Overdue Tasks Service — A6 (P16)

Detects overdue reminders and tasks:
1. Reminders past their fire_at time that weren't completed
2. Notes tagged as "todo" or "task" with past due dates

When detected:
- Sends humanized nudge: "Hey, you had 3 tasks for yesterday that are still open"
- Suggests: complete, reschedule, or cancel
- Gentle tone — not nagging, just helpful

All output HUMANIZED via GPT.
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)


async def detect_overdue_items(user_id: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Scan for overdue reminders and tasks.

    Returns:
        {"reminders": [...], "notes": [...]}
    """
    overdue_reminders = await _check_overdue_reminders(user_id)
    overdue_notes = await _check_overdue_notes(user_id)

    return {
        "reminders": overdue_reminders,
        "notes": overdue_notes,
    }


async def _check_overdue_reminders(user_id: str) -> List[Dict[str, Any]]:
    """Check for reminders that fired but weren't marked done."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return []

    try:
        client = db.get_client()
        now = datetime.now(timezone.utc)
        yesterday = (now - timedelta(days=3)).isoformat()

        result = (
            client.table("reminders")
            .select("id, title, description, remind_at, status")
            .eq("user_id", user_id)
            .eq("status", "pending")
            .lt("remind_at", now.isoformat())
            .gt("remind_at", yesterday)
            .order("remind_at", desc=True)
            .limit(10)
            .execute()
        )

        return result.data or []

    except Exception as e:
        logger.warning("Overdue reminders check failed: %s", e)
        return []


async def _check_overdue_notes(user_id: str) -> List[Dict[str, Any]]:
    """Check for notes with todo/task that have past due dates."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return []

    try:
        client = db.get_client()
        now = datetime.now(timezone.utc)
        week_ago = (now - timedelta(days=7)).isoformat()

        # Notes with "todo" or "task" in title that have a due_date in the past
        result = (
            client.table("notes")
            .select("id, title, content, due_date, created_at")
            .eq("user_id", user_id)
            .eq("is_completed", False)
            .not_.is_("due_date", "null")
            .lt("due_date", now.isoformat())
            .gt("due_date", week_ago)
            .order("due_date", desc=True)
            .limit(10)
            .execute()
        )

        return result.data or []

    except Exception as e:
        logger.warning("Overdue notes check failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# Alert Generation
# ---------------------------------------------------------------------------

async def generate_overdue_alert(
    user_name: str,
    overdue: Dict[str, List[Dict[str, Any]]],
) -> Optional[str]:
    """Generate humanized nudge for overdue items."""
    reminders = overdue.get("reminders", [])
    notes = overdue.get("notes", [])
    total = len(reminders) + len(notes)

    if total == 0:
        return None

    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    raw = f"User: {name}\nOverdue items: {total}\n"
    if reminders:
        raw += "\nOverdue reminders:\n"
        for r in reminders[:5]:
            raw += f"  - {r.get('title', '?')} (was due {r.get('remind_at', '?')[:10]})\n"
    if notes:
        raw += "\nOverdue tasks/notes:\n"
        for n in notes[:5]:
            raw += f"  - {n.get('title', '?')} (was due {n.get('due_date', '?')[:10]})\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} has overdue tasks/reminders. Give a gentle nudge.

RULES:
- Be warm and supportive, NOT nagging or guilt-tripping
- Tone: "Just checking in..." not "You forgot to..."
- Mention the most important 2-3 items by name
- Suggest: complete now, reschedule, or cancel if no longer needed
- Keep under 5 lines
- Use 1-2 emojis: 📋 tasks, ⏰ reminders
- End with an offer to help reschedule

RAW DATA:
{raw}

Generate:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=250,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    lines = [f"📋 Hey {name}! Just checking in — you have {total} overdue item{'s' if total > 1 else ''}:\n"]

    for r in reminders[:2]:
        lines.append(f"⏰ {r.get('title', 'Reminder')} (was due {r.get('remind_at', '?')[:10]})")
    for n in notes[:2]:
        lines.append(f"📝 {n.get('title', 'Task')} (was due {n.get('due_date', '?')[:10]})")

    if total > 4:
        lines.append(f"  ...and {total - 4} more")

    lines.append("\n💬 Want me to reschedule these or mark them done?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Proactivity Loop Runner
# ---------------------------------------------------------------------------

async def check_overdue_for_all_users() -> int:
    """Run overdue check for all proactivity-enabled users.
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
    for pref in (pref_users or []):
        user_id = pref["user_id"]
        try:
            user_data = await db.get_user_by_id(user_id)
            if not user_data:
                continue

            overdue = await detect_overdue_items(user_id)
            total = len(overdue.get("reminders", [])) + len(overdue.get("notes", []))
            if total == 0:
                continue

            alert = await generate_overdue_alert(
                user_name=user_data.get("full_name", ""),
                overdue=overdue,
            )
            if alert:
                chat_id = str(user_data.get("telegram_chat_id")) if user_data.get("telegram_chat_id") else None
                if chat_id:
                    try:
                        notif = get_service("notification")
                        if notif:
                            if not notif.is_initialized():
                                await notif.initialize()
                            await notif.send_message("telegram", chat_id, alert)
                    except Exception:
                        pass
                alerts_sent += 1

        except Exception as e:
            logger.warning("Overdue check failed for user=%s: %s", user_id[:8], e)

    if alerts_sent:
        logger.info("Overdue detector: %d alerts sent", alerts_sent)
    return alerts_sent
