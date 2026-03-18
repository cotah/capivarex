"""
Weekly Planner Service — Plans the week ahead every Sunday (B8).

Every Sunday morning, generates a personalized week overview:
- Events per day (Mon-Sun)
- Key deadlines
- Birthdays and celebrations
- Empty slots (free time)
- Suggestions for the week

Triggered via proactivity loop (Sunday ~09:00 local time).
Complements Morning Briefing (daily) and Weekly Wins (Saturday).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

DAYS_PT = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


async def generate_weekly_plan(
    user_id: str,
    user_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Generate a week plan for the upcoming Mon-Sun.

    Returns: {"text": "formatted plan", "data": {days with events}}
    """
    name = user_name.split()[0] if user_name else ""

    # Get all events for next 7 days
    week_events = await _get_week_events(user_id)

    # Organize by day
    days_data = _organize_by_day(week_events)

    # Get pending reminders
    pending_reminders = await _get_pending_reminders(user_id)

    data = {
        "days": days_data,
        "total_events": len(week_events),
        "pending_reminders": len(pending_reminders),
        "reminders": pending_reminders,
    }

    # Generate message
    text = await _generate_ai_plan(name, data)
    if not text:
        text = _generate_fallback_plan(name, data)

    # Store
    await _store_plan(user_id, text, data)

    return {"text": text, "data": data}


async def _get_week_events(user_id: str) -> List[Dict[str, Any]]:
    """Get all calendar events for the next 7 days."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        now = datetime.now(timezone.utc)
        # Start from tomorrow (Monday)
        start = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        end = (now + timedelta(days=7)).strftime("%Y-%m-%d")

        result = (
            client.table("calendar_events")
            .select("title, start_time, end_time, description")
            .eq("user_id", user_id)
            .gte("start_time", f"{start}T00:00:00")
            .lte("start_time", f"{end}T23:59:59")
            .order("start_time")
            .limit(50)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Weekly planner: events fetch failed: %s", e)
        return []


async def _get_pending_reminders(user_id: str) -> List[Dict[str, str]]:
    """Get pending reminders for the week."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        now = datetime.now(timezone.utc)
        end = (now + timedelta(days=7)).isoformat()

        result = (
            client.table("reminders")
            .select("title, remind_at")
            .eq("user_id", user_id)
            .eq("completed", False)
            .lte("remind_at", end)
            .order("remind_at")
            .limit(20)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Weekly planner: reminders failed: %s", e)
        return []


def _organize_by_day(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
    """Organize events by day of the week."""
    days: Dict[str, List[Dict[str, str]]] = {}

    for event in events:
        start_time = event.get("start_time", "")
        if not start_time:
            continue

        try:
            dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
            day_idx = dt.weekday()
            day_name = DAYS_PT[day_idx]
            time_str = dt.strftime("%H:%M")

            if day_name not in days:
                days[day_name] = []

            days[day_name].append(
                {
                    "title": event.get("title", "Evento"),
                    "time": time_str,
                }
            )
        except (ValueError, IndexError):
            continue

    return days


async def _generate_ai_plan(name: str, data: Dict[str, Any]) -> Optional[str]:
    """Generate weekly plan via GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    days = data.get("days", {})
    total = data.get("total_events", 0)
    reminders = data.get("pending_reminders", 0)

    days_summary = ""
    for day_name in DAYS_PT:
        events = days.get(day_name, [])
        if events:
            items = ", ".join(f"{e['time']} {e['title']}" for e in events)
            days_summary += f"  {day_name}: {items}\n"
        else:
            days_summary += f"  {day_name}: livre\n"

    prompt = (
        f"You are Capivarex, a warm AI assistant. Generate a concise weekly plan "
        f"for {name or 'the user'}. Max 12 lines, use emojis.\n\n"
        f"Week overview:\n{days_summary}\n"
        f"Total events: {total}\n"
        f"Pending reminders: {reminders}\n\n"
        f"Format: Start with '📅 Plano da Semana'. Show each day with events "
        f"(skip empty days or group them). End with encouragement. Portuguese."
    )

    try:
        import asyncio

        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=350,
            temperature=0.7,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 20:
            return text
    except Exception as e:
        logger.warning("Weekly planner AI failed: %s", e)
    return None


def _generate_fallback_plan(name: str, data: Dict[str, Any]) -> str:
    """Generate weekly plan without AI."""
    greeting = f"Oi {name}!" if name else "Oi!"
    days = data.get("days", {})
    total = data.get("total_events", 0)
    reminders_count = data.get("pending_reminders", 0)
    reminders = data.get("reminders", [])

    msg = f"📅 **Plano da Semana**\n\n{greeting} Aqui está sua semana:\n\n"

    busy_days = 0
    free_days = 0

    for day_name in DAYS_PT:
        events = days.get(day_name, [])
        if events:
            busy_days += 1
            items = ", ".join(f"{e['time']} {e['title']}" for e in events[:3])
            extra = f" (+{len(events) - 3})" if len(events) > 3 else ""
            msg += f"📌 **{day_name}:** {items}{extra}\n"
        else:
            free_days += 1

    if free_days > 0:
        msg += f"\n🟢 **{free_days} dia{'s' if free_days > 1 else ''} livre{'s' if free_days > 1 else ''}** na agenda\n"

    if reminders_count > 0:
        msg += f"\n⏰ **{reminders_count} lembrete{'s' if reminders_count > 1 else ''}** pendente{'s' if reminders_count > 1 else ''}:\n"
        for r in reminders[:3]:
            msg += f"  • {r.get('title', 'Lembrete')}\n"

    # Summary
    if total == 0:
        msg += "\n🎉 Semana tranquila! Aproveite para descansar ou começar algo novo."
    elif total <= 5:
        msg += "\n👍 Semana equilibrada. Bom ritmo!"
    elif total <= 10:
        msg += "\n💪 Semana produtiva pela frente! Organize-se bem."
    else:
        msg += "\n🔥 Semana intensa! Não esqueça de fazer pausas."

    msg += "\n\nQuer ajustar algo? É só falar!"

    return msg


async def _store_plan(user_id: str, text: str, data: Dict[str, Any]) -> None:
    """Store weekly plan in proactivity feed."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": "weekly_plan",
                "content": text[:2000],
                "metadata": json.dumps(
                    {
                        "total_events": data.get("total_events", 0),
                        "pending_reminders": data.get("pending_reminders", 0),
                    }
                ),
            }
        ).execute()
    except Exception as e:
        logger.warning("Weekly planner store failed: %s", e)
