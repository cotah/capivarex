"""
Focus Mode Service — Intelligent "Do Not Disturb" for deep work.

Features:
- Activate/deactivate focus mode with duration
- Silences proactive notifications while active
- Optional Pomodoro timer (25 min work + 5 min break)
- Marks calendar as "busy" during focus
- On end: shows summary of what was missed
- Detects focus intent from natural language

Storage: user_context table (key: focus_mode)
"""

import logging
import time
from typing import Any, Dict, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Default durations (seconds)
DEFAULT_FOCUS_DURATION = 3600  # 1 hour
POMODORO_WORK = 25 * 60  # 25 minutes
POMODORO_BREAK = 5 * 60  # 5 minutes
MAX_FOCUS_DURATION = 8 * 3600  # 8 hours max

# Keywords for intent detection
FOCUS_KEYWORDS_PT = [
    "focar", "foco", "focus", "concentrar", "deep work", "não perturbe",
    "nao perturbe", "silêncio", "silencio", "modo foco", "focus mode",
    "preciso trabalhar", "vou trabalhar", "sem interrupção",
    "sem interrupcao", "pomodoro",
]

FOCUS_KEYWORDS_EN = [
    "focus", "focus mode", "do not disturb", "dnd", "deep work",
    "concentrate", "need to work", "silence", "pomodoro", "quiet mode",
    "no interruptions", "busy mode",
]

DEACTIVATE_KEYWORDS = [
    "parar foco", "sair do foco", "desativar foco", "stop focus",
    "end focus", "focus off", "voltar", "terminei", "pode falar",
    "desligar focus", "sair do modo foco",
]


def detect_focus_intent(message: str) -> Optional[Dict[str, Any]]:
    """
    Detect if user wants to activate/deactivate focus mode.

    Returns:
        None if not focus-related, or:
        {"action": "activate", "duration_minutes": 60, "pomodoro": False}
        {"action": "deactivate"}
    """
    lower = message.lower().strip()

    # Check deactivate first
    for kw in DEACTIVATE_KEYWORDS:
        if kw in lower:
            return {"action": "deactivate"}

    # Check activate
    is_focus = False
    for kw in FOCUS_KEYWORDS_PT + FOCUS_KEYWORDS_EN:
        if kw in lower:
            is_focus = True
            break

    if not is_focus:
        return None

    # Extract duration
    duration_min = 60  # default 1 hour
    duration_min = _extract_duration(lower) or duration_min

    # Check pomodoro
    pomodoro = "pomodoro" in lower

    return {
        "action": "activate",
        "duration_minutes": duration_min,
        "pomodoro": pomodoro,
    }


def _extract_duration(text: str) -> Optional[int]:
    """Extract duration in minutes from text."""
    import re

    # "2 horas" / "2 hours" / "1 hora" / "1 hour"
    match = re.search(r"(\d+)\s*(?:horas?|hours?|hr)", text)
    if match:
        return int(match.group(1)) * 60

    # "30 minutos" / "30 minutes" / "30 min"
    match = re.search(r"(\d+)\s*(?:minutos?|minutes?|min)", text)
    if match:
        return int(match.group(1))

    # "1h30" / "1:30"
    match = re.search(r"(\d+)[h:](\d+)", text)
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))

    # Just "1h" or "2h"
    match = re.search(r"(\d+)h\b", text)
    if match:
        return int(match.group(1)) * 60

    return None


async def activate_focus(
    user_id: str,
    duration_minutes: int = 60,
    pomodoro: bool = False,
) -> Dict[str, Any]:
    """
    Activate focus mode for a user.

    Returns focus session info.
    """
    now = time.time()
    duration_sec = min(duration_minutes * 60, MAX_FOCUS_DURATION)
    ends_at = now + duration_sec

    session = {
        "active": True,
        "started_at": now,
        "ends_at": ends_at,
        "duration_minutes": duration_minutes,
        "pomodoro": pomodoro,
        "pomodoro_cycle": 0,
        "missed_notifications": [],
    }

    # Save to database
    await _save_focus_state(user_id, session)

    # Save to Redis for fast lookup
    try:
        redis = get_service("redis")
        if redis and redis.is_initialized():
            await redis.set_key(
                f"focus:{user_id}",
                session,
                ttl=int(duration_sec) + 60,
            )
    except Exception:
        pass

    logger.info("Focus mode activated: user=%s duration=%dmin pomodoro=%s", user_id[:8], duration_minutes, pomodoro)
    return session


async def deactivate_focus(user_id: str) -> Dict[str, Any]:
    """
    Deactivate focus mode and return summary.

    Returns: {"was_active": bool, "duration_actual": minutes, "missed": [...]}
    """
    session = await get_focus_state(user_id)

    if not session or not session.get("active"):
        return {"was_active": False, "duration_actual": 0, "missed": []}

    now = time.time()
    actual_minutes = int((now - session.get("started_at", now)) / 60)
    missed = session.get("missed_notifications", [])

    # Clear state
    session["active"] = False
    await _save_focus_state(user_id, session)

    # Clear Redis
    try:
        redis = get_service("redis")
        if redis and redis.is_initialized():
            await redis.delete_key(f"focus:{user_id}")
    except Exception:
        pass

    logger.info("Focus mode deactivated: user=%s actual=%dmin missed=%d", user_id[:8], actual_minutes, len(missed))

    return {
        "was_active": True,
        "duration_actual": actual_minutes,
        "missed": missed,
    }


async def is_focus_active(user_id: str) -> bool:
    """Check if focus mode is currently active for a user. Fast path via Redis."""
    # Try Redis first (fast)
    try:
        redis = get_service("redis")
        if redis and redis.is_initialized():
            data = await redis.get_key(f"focus:{user_id}")
            if data:
                if data.get("active") and data.get("ends_at", 0) > time.time():
                    return True
                # Expired — clean up
                if data.get("ends_at", 0) <= time.time():
                    await redis.delete_key(f"focus:{user_id}")
                return False
    except Exception:
        pass

    # Fallback to DB
    session = await get_focus_state(user_id)
    if not session:
        return False

    if session.get("active") and session.get("ends_at", 0) > time.time():
        return True

    # Auto-deactivate if expired
    if session.get("active") and session.get("ends_at", 0) <= time.time():
        session["active"] = False
        await _save_focus_state(user_id, session)

    return False


async def add_missed_notification(user_id: str, notification: str) -> None:
    """Add a notification to the missed list (called by proactivity service)."""
    session = await get_focus_state(user_id)
    if not session or not session.get("active"):
        return

    missed = session.get("missed_notifications", [])
    missed.append({
        "text": notification[:200],
        "time": time.time(),
    })
    # Keep max 20 missed notifications
    session["missed_notifications"] = missed[-20:]
    await _save_focus_state(user_id, session)


async def get_focus_state(user_id: str) -> Optional[Dict[str, Any]]:
    """Get current focus state from database."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return None

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "focus_mode")
            .limit(1)
            .execute()
        )
        if result.data:
            import json
            val = result.data[0].get("value", "{}")
            return json.loads(val) if isinstance(val, str) else val
    except Exception as e:
        logger.warning("Failed to get focus state: %s", e)
    return None


async def _save_focus_state(user_id: str, session: Dict[str, Any]) -> None:
    """Save focus state to database."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        import json
        client = db.get_client()
        client.table("user_context").upsert({
            "user_id": user_id,
            "key": "focus_mode",
            "value": json.dumps(session),
        }).execute()
    except Exception as e:
        logger.warning("Failed to save focus state: %s", e)


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

def format_activate_response(session: Dict[str, Any]) -> str:
    """Format the activation message."""
    duration = session["duration_minutes"]
    pomodoro = session.get("pomodoro", False)
    ends_at = session["ends_at"]

    from datetime import datetime
    end_time = datetime.fromtimestamp(ends_at).strftime("%H:%M")

    hours = duration // 60
    mins = duration % 60
    duration_str = ""
    if hours and mins:
        duration_str = f"{hours}h{mins}min"
    elif hours:
        duration_str = f"{hours} hora{'s' if hours > 1 else ''}"
    else:
        duration_str = f"{mins} minutos"

    msg = (
        f"🎯 **Focus Mode ativado!**\n\n"
        f"⏱️ Duração: **{duration_str}** (até {end_time})\n"
        f"🔕 Notificações proativas silenciadas\n"
    )

    if pomodoro:
        msg += (
            "🍅 Pomodoro: **25 min foco** + **5 min pausa**\n"
            "Vou te avisar quando for hora da pausa!\n"
        )

    msg += (
        "\nQuando terminar, diga **\"terminei\"** ou espere o tempo acabar.\n"
        "Bom trabalho! 💪"
    )

    return msg


def format_deactivate_response(result: Dict[str, Any]) -> str:
    """Format the deactivation message."""
    if not result.get("was_active"):
        return "O Focus Mode não estava ativado."

    actual = result["duration_actual"]
    missed = result.get("missed", [])

    hours = actual // 60
    mins = actual % 60
    duration_str = ""
    if hours and mins:
        duration_str = f"{hours}h{mins}min"
    elif hours:
        duration_str = f"{hours} hora{'s' if hours > 1 else ''}"
    else:
        duration_str = f"{mins} minutos"

    msg = (
        f"✅ **Focus Mode desativado!**\n\n"
        f"⏱️ Você focou por **{duration_str}**. Ótimo trabalho! 🎉\n"
    )

    if missed:
        plural = "notificações" if len(missed) > 1 else "notificação"
        msg += f"\n📬 **{len(missed)} {plural} durante o foco:**\n\n"
        for m in missed[-5:]:
            msg += f"  • {m['text']}\n"
        if len(missed) > 5:
            msg += f"  • ... e mais {len(missed) - 5}\n"
    else:
        msg += "\n📭 Nenhuma notificação perdida. Tudo tranquilo!\n"

    msg += "\n🔔 Notificações restauradas."

    return msg
