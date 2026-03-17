"""
Weekly Wins Recap Service — Celebrates weekly achievements (N3).

Every Saturday morning, generates a personalized celebration of the week:
- Tasks/reminders completed
- Calendar events attended
- Focus time accumulated
- Streaks maintained
- Positive reinforcement and encouragement

Triggered via proactivity loop (Saturday ~09:00 local time).
Stored in proactivity_feed.
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from services.core import get_service

logger = logging.getLogger(__name__)


async def generate_weekly_wins(
    user_id: str,
    user_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Generate weekly wins recap for a user.

    Returns: {"text": "formatted recap", "data": {...stats...}}
    """
    name = user_name.split()[0] if user_name else ""

    # Gather week stats
    stats: Dict[str, Any] = {}
    stats["events_attended"] = await _count_week_events(user_id)
    stats["tasks_completed"] = await _count_completed_tasks(user_id)
    stats["conversations"] = await _count_conversations(user_id)
    stats["focus_minutes"] = await _get_week_focus_time(user_id)

    # Generate message
    text = await _generate_ai_wins(name, stats)
    if not text:
        text = _generate_fallback_wins(name, stats)

    # Store
    await _store_wins(user_id, text, stats)

    return {"text": text, "data": stats}


async def _count_week_events(user_id: str) -> int:
    """Count calendar events in the past 7 days."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return 0

        client = db.get_client()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        now = datetime.now(timezone.utc).isoformat()

        result = (
            client.table("calendar_events")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("start_time", week_ago)
            .lte("start_time", now)
            .execute()
        )
        return result.count if result.count else 0
    except Exception as e:
        logger.warning("Weekly wins: events count failed: %s", e)
        return 0


async def _count_completed_tasks(user_id: str) -> int:
    """Count reminders completed in the past 7 days."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return 0

        client = db.get_client()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        result = (
            client.table("reminders")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("completed", True)
            .gte("completed_at", week_ago)
            .execute()
        )
        return result.count if result.count else 0
    except Exception as e:
        logger.warning("Weekly wins: tasks count failed: %s", e)
        return 0


async def _count_conversations(user_id: str) -> int:
    """Count conversations with Capivarex this week."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return 0

        client = db.get_client()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        result = (
            client.table("conversations")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .gte("created_at", week_ago)
            .execute()
        )
        return result.count if result.count else 0
    except Exception as e:
        logger.warning("Weekly wins: conversations count failed: %s", e)
        return 0


async def _get_week_focus_time(user_id: str) -> int:
    """Get total focus time this week (minutes). Approximate from daily summaries."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return 0

        client = db.get_client()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        result = (
            client.table("proactivity_feed")
            .select("metadata")
            .eq("user_id", user_id)
            .eq("type", "daily_summary")
            .gte("created_at", week_ago)
            .execute()
        )

        total = 0
        for row in (result.data or []):
            meta = row.get("metadata", "{}")
            if isinstance(meta, str):
                meta = json.loads(meta)
            total += meta.get("focus_minutes", 0)
        return total
    except Exception as e:
        logger.warning("Weekly wins: focus time failed: %s", e)
        return 0


async def _generate_ai_wins(name: str, stats: Dict[str, Any]) -> Optional[str]:
    """Generate celebratory wins message using GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    prompt = (
        f"You are Capivarex, a warm and encouraging AI assistant. "
        f"Generate a short weekly wins celebration for {name or 'the user'}. "
        f"Be positive, use emojis, and celebrate their achievements.\n\n"
        f"Stats this week:\n"
        f"- Events attended: {stats.get('events_attended', 0)}\n"
        f"- Tasks completed: {stats.get('tasks_completed', 0)}\n"
        f"- Conversations with Capivarex: {stats.get('conversations', 0)}\n"
        f"- Focus time: {stats.get('focus_minutes', 0)} minutes\n\n"
        f"Format: Start with '🏆 Conquistas da Semana'. Use bullet points with emojis. "
        f"End with encouragement for next week. Max 8 lines. Respond in Portuguese."
    )

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
    except Exception as e:
        logger.warning("Weekly wins AI failed: %s", e)

    return None


def _generate_fallback_wins(name: str, stats: Dict[str, Any]) -> str:
    """Generate wins message without AI (fallback)."""
    greeting = f"Oi {name}!" if name else "Oi!"
    events = stats.get("events_attended", 0)
    tasks = stats.get("tasks_completed", 0)
    convos = stats.get("conversations", 0)
    focus = stats.get("focus_minutes", 0)

    msg = f"🏆 **Conquistas da Semana**\n\n{greeting} Hora de celebrar!\n\n"

    achievements = []

    if events > 0:
        achievements.append(f"📅 **{events} evento{'s' if events > 1 else ''}** na agenda")
    if tasks > 0:
        achievements.append(f"✅ **{tasks} tarefa{'s' if tasks > 1 else ''}** completada{'s' if tasks > 1 else ''}")
    if convos > 0:
        achievements.append(f"💬 **{convos} conversa{'s' if convos > 1 else ''}** comigo")
    if focus > 0:
        hours = focus // 60
        mins = focus % 60
        if hours:
            achievements.append(f"🎯 **{hours}h{mins}min** de focus time")
        else:
            achievements.append(f"🎯 **{mins} minutos** de focus time")

    if achievements:
        for a in achievements:
            msg += f"{a}\n"
    else:
        msg += "Esta semana foi mais tranquila — e tudo bem! 😊\n"

    # Encouragement
    total_score = events + tasks + convos + (focus // 30)
    if total_score >= 20:
        msg += "\n🌟 **Semana incrível!** Você arrasou! Continue assim! 🚀"
    elif total_score >= 10:
        msg += "\n💪 **Boa semana!** Produtivo e organizado. Parabéns!"
    elif total_score >= 5:
        msg += "\n👍 **Semana sólida!** Cada passo conta. Continue!"
    else:
        msg += "\n🌱 **Nova semana, novas oportunidades!** Vamos juntos! 💪"

    return msg


async def _store_wins(user_id: str, text: str, stats: Dict[str, Any]) -> None:
    """Store weekly wins in proactivity feed."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "weekly_wins",
            "content": text[:2000],
            "metadata": json.dumps(stats),
        }).execute()
    except Exception as e:
        logger.warning("Weekly wins store failed: %s", e)
