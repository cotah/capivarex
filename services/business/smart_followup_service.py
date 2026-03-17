"""
Smart Follow-up Service — Remembers and follows up on user mentions (N4).

The WOW factor: bot remembers things the user mentioned and proactively
follows up later, creating a feeling of genuine care and attention.

Flow:
1. User says something memorable (doctor appointment, job interview, trip...)
2. Service detects the followable event and stores it with a follow-up date
3. On the follow-up date, generates a caring follow-up message

Detection keywords: appointments, trips, events, health, interviews,
exams, deadlines, meetings, celebrations, etc.

Storage: user_context table (key: smart_followups)
"""

import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Maximum stored follow-ups per user
MAX_FOLLOWUPS = 20

# Keywords that indicate a followable event (PT + EN)
FOLLOWUP_PATTERNS = [
    # Health
    (r"(?:vou|tenho|marquei|agendei)\s+(?:ao|no|uma?\s+consulta|médico|dentista|exame|cirurgia)", "health", 1),
    (r"(?:doctor|dentist|appointment|surgery|exam|checkup|hospital)\s*(?:tomorrow|next|on)", "health", 1),
    # Job/Career
    (r"(?:entrevista|interview)\s+(?:de|d[eo]|for)\s+(?:emprego|trabalho|job|work)", "career", 1),
    (r"(?:entrevista|interview)\s+(?:amanhã|tomorrow|next)", "career", 1),
    (r"(?:prova|exame|test|exam)\s+(?:é\s+)?(?:amanhã|tomorrow|next|na|no)", "education", 1),
    # Travel
    (r"(?:viajo|vou viajar|trip|flying|voo|flight)\s+(?:amanhã|tomorrow|next|para|to|on)", "travel", 1),
    (r"(?:volto|voltando|returning|coming back)\s+(?:amanhã|tomorrow|next)", "travel", 1),
    # Social
    (r"(?:casamento|wedding|aniversário|birthday party)\s+(?:amanhã|tomorrow|next|do|da|no|na)", "social", 1),
    (r"(?:encontro|date|jantar especial|special dinner)", "social", 1),
    # Work
    (r"(?:apresentação|presentation|pitch|demo)\s+(?:amanhã|tomorrow|next|important)", "work", 1),
    (r"(?:deadline|prazo)\s+(?:amanhã|tomorrow|é|is)", "work", 1),
    # General future
    (r"(?:amanhã|tomorrow)\s+(?:tenho|eu tenho|i have|vou|i'm going)", "general", 1),
    (r"(?:semana que vem|next week)\s+(?:tenho|vou|i have)", "general", 7),
]


def detect_followable_event(message: str) -> Optional[Dict[str, Any]]:
    """
    Detect if a message contains something worth following up on.

    Returns:
        None if nothing found, or:
        {"category": "health", "trigger": "matched text", "days_until_followup": 1}
    """
    lower = message.lower().strip()
    if len(lower) < 10:
        return None

    for pattern, category, days in FOLLOWUP_PATTERNS:
        match = re.search(pattern, lower)
        if match:
            return {
                "category": category,
                "trigger": match.group(0),
                "days_until_followup": days,
                "original_message": message[:300],
            }

    return None


async def store_followup(
    user_id: str,
    event: Dict[str, Any],
) -> bool:
    """
    Store a follow-up event for later.

    Args:
        user_id: User ID
        event: From detect_followable_event() + enriched data
    """
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        client = db.get_client()
        now = time.time()
        days = event.get("days_until_followup", 1)
        followup_at = now + (days * 86400)

        # Load existing followups
        existing = await _load_followups(user_id)

        # Add new
        followup = {
            "id": f"fu_{int(now)}",
            "category": event.get("category", "general"),
            "original_message": event.get("original_message", ""),
            "trigger": event.get("trigger", ""),
            "created_at": now,
            "followup_at": followup_at,
            "done": False,
        }
        existing.append(followup)

        # Keep max and remove old done ones
        existing = [f for f in existing if not f.get("done") or time.time() - f.get("created_at", 0) < 604800]
        existing = existing[-MAX_FOLLOWUPS:]

        # Save
        client.table("user_context").upsert({
            "user_id": user_id,
            "key": "smart_followups",
            "value": json.dumps(existing),
        }).execute()

        logger.info("Smart follow-up stored: user=%s cat=%s in %d days", user_id[:8], event.get("category"), days)
        return True

    except Exception as e:
        logger.warning("Smart follow-up store failed: %s", e)
        return False


async def check_pending_followups(user_id: str) -> List[Dict[str, Any]]:
    """
    Check for follow-ups that are due today.

    Returns list of pending follow-up events.
    """
    followups = await _load_followups(user_id)
    now = time.time()

    pending = []
    for f in followups:
        if f.get("done"):
            continue
        if f.get("followup_at", 0) <= now:
            pending.append(f)

    return pending


async def mark_followup_done(user_id: str, followup_id: str) -> None:
    """Mark a follow-up as done after sending."""
    try:
        followups = await _load_followups(user_id)
        for f in followups:
            if f.get("id") == followup_id:
                f["done"] = True
                break

        db = get_service("database")
        if db and db.is_initialized():
            client = db.get_client()
            client.table("user_context").upsert({
                "user_id": user_id,
                "key": "smart_followups",
                "value": json.dumps(followups),
            }).execute()
    except Exception as e:
        logger.warning("Mark followup done failed: %s", e)


async def generate_followup_message(
    user_name: str,
    followup: Dict[str, Any],
) -> str:
    """Generate a caring follow-up message."""
    name = user_name.split()[0] if user_name else ""
    category = followup.get("category", "general")
    original = followup.get("original_message", "")

    # Try AI first
    msg = await _generate_ai_followup(name, category, original)
    if msg:
        return msg

    # Fallback
    return _generate_fallback_followup(name, category, original)


async def _generate_ai_followup(name: str, category: str, original: str) -> Optional[str]:
    """Generate follow-up via GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    prompt = (
        f"You are Capivarex, a caring AI assistant. The user ({name or 'user'}) "
        f"mentioned something recently. Generate a short, warm follow-up message "
        f"(2-3 sentences max). Use emojis. Be caring, not intrusive.\n\n"
        f"Category: {category}\n"
        f"What they said: \"{original}\"\n\n"
        f"Generate a follow-up question asking how it went. Respond in Portuguese."
    )

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=150,
            temperature=0.8,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 15:
            return text
    except Exception:
        pass
    return None


def _generate_fallback_followup(name: str, category: str, original: str) -> str:
    """Generate follow-up without AI."""
    greeting = f"Oi {name}!" if name else "Oi!"

    templates = {
        "health": f"{greeting} 🏥 Lembrei que você mencionou uma consulta. Como foi? Espero que esteja tudo bem!",
        "career": f"{greeting} 🤞 Como foi a entrevista? Tô na torcida por você!",
        "education": f"{greeting} 📚 E a prova, como foi? Espero que tenha corrido bem!",
        "travel": f"{greeting} ✈️ Como está a viagem? Espero que esteja aproveitando!",
        "social": f"{greeting} 🎉 Como foi o evento? Conta tudo!",
        "work": f"{greeting} 💼 Como foi a apresentação? Espero que tenha arrasado!",
    }

    return templates.get(category, f"{greeting} 💭 Lembrei que você mencionou algo. Como está? Tudo certo? 😊")


async def _load_followups(user_id: str) -> List[Dict[str, Any]]:
    """Load stored follow-ups from database."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "smart_followups")
            .limit(1)
            .execute()
        )
        if result.data:
            val = result.data[0].get("value", "[]")
            return json.loads(val) if isinstance(val, str) else val
    except Exception as e:
        logger.warning("Load followups failed: %s", e)
    return []
