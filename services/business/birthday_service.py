"""
Birthday Detection Service — A1 (P02)

Proactively detects upcoming birthdays from:
1. Calendar events (birthday/aniversário keywords)
2. User contacts mentioned in emails/conversations (via RAG)

When detected (3-5 days before):
- Sends humanized alert: "O João faz anos daqui a 3 dias!"
- Suggests: gift ideas, message to send, restaurant reservation
- Offers to help: "Queres que eu pesquise presentes ou reserve um restaurante?"

All output HUMANIZED via GPT.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Birthday keywords (multi-language)
BIRTHDAY_KEYWORDS = {
    "birthday",
    "aniversário",
    "aniversario",
    "anos",
    "bday",
    "cumpleaños",
    "geburtstag",
    "anniversaire",
    "niver",
}


async def detect_upcoming_birthdays(user_id: str) -> List[Dict[str, Any]]:
    """
    Scan calendar for birthdays in the next 7 days.

    Returns list of detected birthdays.
    """
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return []

    try:
        events = await calendar_svc.async_get_upcoming_events(
            user_id=user_id,
            max_results=30,
            days_ahead=7,
        )
        if not events:
            return []
    except Exception as e:
        logger.warning("Birthday detect: calendar failed: %s", e)
        return []

    now = datetime.now(timezone.utc)
    birthdays = []

    for event in events:
        summary = (event.get("summary", "") or "").lower()
        description = (event.get("description", "") or "").lower()

        # Check if it's a birthday event
        if not _is_birthday_event(summary, description):
            continue

        # Parse date
        start_str = event.get("start", "")
        try:
            if "T" in str(start_str):
                start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
            else:
                start_dt = datetime.strptime(str(start_str)[:10], "%Y-%m-%d").replace(
                    tzinfo=timezone.utc
                )
        except (ValueError, TypeError):
            continue

        days_until = (start_dt - now).days
        if days_until < 0 or days_until > 7:
            continue

        # Extract the person's name from summary
        person_name = _extract_person_name(event.get("summary", ""))

        birthdays.append(
            {
                "event_id": event.get("id", ""),
                "person_name": person_name,
                "date": start_dt.strftime("%B %d"),
                "days_until": days_until,
                "summary": event.get("summary", ""),
            }
        )

    return birthdays


def _is_birthday_event(summary: str, description: str) -> bool:
    """Check if event is a birthday."""
    combined = f"{summary} {description}"
    return any(kw in combined for kw in BIRTHDAY_KEYWORDS)


def _extract_person_name(summary: str) -> str:
    """Extract person's name from birthday event summary."""
    clean = summary
    # Remove common birthday words
    for word in [
        "birthday",
        "aniversário",
        "aniversario",
        "bday",
        "'s",
        "do ",
        "da ",
        "de ",
    ]:
        clean = clean.lower().replace(word, "")
    clean = clean.strip(" -:–'").title()
    return clean if clean else "Someone"


async def generate_birthday_alert(
    user_id: str,
    birthday: Dict[str, Any],
    user_name: str = "",
    chat_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate humanized birthday alert with action suggestions.
    Deduplicates: 1 alert per birthday event_id.
    """
    event_id = birthday.get("event_id", "")

    # Check dedup
    if await _alert_already_sent(user_id, event_id):
        return None

    name = user_name.split()[0] if user_name else "there"
    person = birthday.get("person_name", "someone")
    days = birthday.get("days_until", 0)
    date = birthday.get("date", "")

    # Humanize via GPT
    message = await _humanize_birthday_alert(name, person, days, date)

    title = f"🎂 {person}'s birthday in {days} day{'s' if days != 1 else ''}!"

    # Store in proactivity_feed
    await _store_alert(user_id, event_id, title, message)

    # Send via Telegram
    if chat_id:
        try:
            notif = get_service("notification")
            if notif:
                if not notif.is_initialized():
                    await notif.initialize()
                await notif.send_message("telegram", chat_id, message)
        except Exception as e:
            logger.warning("Birthday alert: Telegram failed: %s", e)

    return {"title": title, "message": message, "birthday": birthday}


async def _humanize_birthday_alert(
    name: str,
    person: str,
    days: int,
    date: str,
) -> str:
    """Generate warm birthday reminder via GPT."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} has a contact ({person}) whose birthday is {when} ({date}).

Generate a friendly birthday reminder. RULES:
- Be warm and helpful
- If today: "It's {person}'s birthday today! 🎂"
- If soon: excitement about the upcoming birthday
- Suggest 2-3 actionable ideas: send a message, gift idea, dinner reservation
- Offer to help with any of those
- Keep under 6 lines, use 2-3 emojis
- Sound like a friend reminding you, not a robot notification

Generate:"""

        try:
            import asyncio

            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=250,
                temperature=0.85,
            )
            text = (
                response if isinstance(response, str) else response.get("content", "")
            )
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    when = "today! 🎉" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
    return (
        f"🎂 Hey {name}! {person}'s birthday is {when}\n\n"
        f"Some ideas:\n"
        f"• Send a heartfelt message\n"
        f"• Research a gift they'd love\n"
        f"• Book a dinner to celebrate\n\n"
        f"Want me to help with any of these? 💬"
    )


# ---------------------------------------------------------------------------
# Storage & Dedup
# ---------------------------------------------------------------------------


async def _alert_already_sent(user_id: str, event_id: str) -> bool:
    """Check if birthday alert already sent for this event."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        result = (
            client.table("proactivity_feed")
            .select("id")
            .eq("user_id", user_id)
            .eq("type", "birthday_alert")
            .limit(20)
            .execute()
        )
        for item in result.data or []:
            try:
                meta = json.loads(
                    item.get("metadata", "{}")
                    if isinstance(item.get("metadata"), str)
                    else "{}"
                )
                if meta.get("event_id") == event_id:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
        return False
    except Exception:
        return False


async def _store_alert(user_id: str, event_id: str, title: str, message: str) -> None:
    """Store birthday alert in proactivity_feed."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": "birthday_alert",
                "title": title,
                "message": message,
                "metadata": json.dumps({"event_id": event_id}),
                "is_read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as e:
        logger.warning("Birthday alert: store failed: %s", e)


# ---------------------------------------------------------------------------
# Proactivity Loop Runner
# ---------------------------------------------------------------------------


async def check_birthdays_for_all_users() -> int:
    """Run birthday detection for all proactivity-enabled users.
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

            birthdays = await detect_upcoming_birthdays(user_id)
            for bday in birthdays:
                result = await generate_birthday_alert(
                    user_id=user_id,
                    birthday=bday,
                    user_name=user_data.get("full_name", ""),
                    chat_id=str(user_data.get("telegram_chat_id"))
                    if user_data.get("telegram_chat_id")
                    else None,
                )
                if result:
                    alerts_sent += 1
        except Exception as e:
            logger.warning("Birthday check failed for user=%s: %s", user_id[:8], e)

    if alerts_sent:
        logger.info("Birthday detector: %d alerts sent", alerts_sent)
    return alerts_sent
