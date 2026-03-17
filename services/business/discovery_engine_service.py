"""
Discovery Engine Service — Proactive personalized suggestions (N1).

The bot stops being reactive and becomes proactive: suggests things
the user might like based on their profile, interests, and context.

Categories:
- Restaurants near the user
- Local events and activities
- Articles and content matching interests
- Products and services
- Tips based on weather/calendar

Uses RAG memory to build user profile + Research for fresh content.
Triggered via proactivity loop (1-2 times per day, not spammy).
"""

import json
import logging
import random
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Discovery categories
CATEGORIES = ["restaurant", "event", "article", "tip"]

# Cooldown: max 2 discoveries per day
DISCOVERY_COOLDOWN = 12 * 3600  # 12 hours between discoveries


async def generate_discovery(
    user_id: str,
    user_name: str = "",
    location: str = "",
    category: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate a personalized discovery suggestion.

    Args:
        user_id: User ID
        user_name: User's name
        location: User's location
        category: Force a category, or auto-select based on context

    Returns: {"text": "message", "data": {discovery info}, "category": "restaurant"}
    """
    name = user_name.split()[0] if user_name else ""

    # Check cooldown
    if await _is_on_cooldown(user_id):
        return None

    # Get user interests from RAG
    interests = await _get_user_interests(user_id)

    # Pick category if not specified
    if not category:
        category = _pick_category(interests, location)

    # Generate discovery based on category
    discovery = await _generate_by_category(category, interests, location)
    if not discovery:
        return None

    # Format message
    text = await _generate_ai_discovery(name, category, discovery, interests)
    if not text:
        text = _generate_fallback_discovery(name, category, discovery)

    data = {
        "category": category,
        "discovery": discovery,
        "interests_used": interests[:3],
    }

    # Store and set cooldown
    await _store_discovery(user_id, text, data)

    return {"text": text, "data": data, "category": category}


async def _is_on_cooldown(user_id: str) -> bool:
    """Check if user had a recent discovery (prevent spam)."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        client = db.get_client()
        cutoff = (
            __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
            - __import__("datetime").timedelta(hours=12)
        ).isoformat()

        result = (
            client.table("proactivity_feed")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("type", "discovery")
            .gte("created_at", cutoff)
            .execute()
        )
        return (result.count or 0) >= 2
    except Exception:
        return False


async def _get_user_interests(user_id: str) -> List[str]:
    """Extract user interests from RAG memory and preferences."""
    interests = []

    try:
        db = get_service("database")
        if db and db.is_initialized():
            client = db.get_client()

            # Check user_context for interests
            result = (
                client.table("user_context")
                .select("value")
                .eq("user_id", user_id)
                .eq("key", "interests")
                .limit(1)
                .execute()
            )
            if result.data:
                val = result.data[0].get("value", "[]")
                stored = json.loads(val) if isinstance(val, str) else val
                if isinstance(stored, list):
                    interests.extend(stored)

    except Exception as e:
        logger.warning("Discovery: interests fetch failed: %s", e)

    if not interests:
        interests = ["technology", "food", "travel", "health"]

    return interests[:10]


def _pick_category(interests: List[str], location: str) -> str:
    """Pick a discovery category based on context."""
    weights = {
        "restaurant": 3 if location else 1,
        "event": 2 if location else 1,
        "article": 3,
        "tip": 2,
    }

    # Boost based on interests
    food_words = {"food", "cooking", "restaurant", "cuisine", "comida", "cozinha"}
    tech_words = {"technology", "tech", "programming", "ai", "software", "tecnologia"}

    if any(i.lower() in food_words for i in interests):
        weights["restaurant"] += 2
    if any(i.lower() in tech_words for i in interests):
        weights["article"] += 2

    # Weighted random selection
    categories = list(weights.keys())
    w = list(weights.values())
    return random.choices(categories, weights=w, k=1)[0]


async def _generate_by_category(
    category: str,
    interests: List[str],
    location: str,
) -> Optional[Dict[str, Any]]:
    """Generate discovery content for a specific category."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return _fallback_discovery(category, interests)

    prompts = {
        "restaurant": (
            f"Suggest ONE specific restaurant near {location or 'Dublin'} that someone interested "
            f"in {', '.join(interests[:3])} would love. Include name, cuisine type, "
            f"what makes it special, and approximate price range."
        ),
        "event": (
            f"Suggest ONE upcoming event/activity near {location or 'Dublin'} that someone "
            f"interested in {', '.join(interests[:3])} would enjoy. Include name, date, "
            f"what it is, and why it's interesting."
        ),
        "article": (
            f"Suggest ONE interesting article topic about {', '.join(interests[:3])} "
            f"that would be fascinating to read. Include title idea, a 1-sentence summary, "
            f"and why it's worth reading."
        ),
        "tip": (
            f"Share ONE useful life tip related to {', '.join(interests[:3])}. "
            f"Something practical and actionable that improves daily life."
        ),
    }

    prompt = prompts.get(category, prompts["tip"])
    prompt += "\n\nRespond ONLY in JSON: {\"title\": \"...\", \"description\": \"...\", \"why\": \"...\"}"

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=200,
            temperature=0.9,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        return json.loads(text)
    except Exception as e:
        logger.warning("Discovery generation failed: %s", e)
        return _fallback_discovery(category, interests)


def _fallback_discovery(category: str, interests: List[str]) -> Dict[str, Any]:
    """Fallback discovery without AI."""
    fallbacks = {
        "restaurant": {"title": "Novo restaurante local", "description": "Descubra um novo lugar perto de você", "why": "Experimentar coisas novas!"},
        "event": {"title": "Evento na cidade", "description": "Confira os eventos da semana", "why": "Sempre tem algo legal acontecendo"},
        "article": {"title": f"Artigo sobre {interests[0] if interests else 'algo'}", "description": "Uma leitura interessante", "why": "Baseado nos seus interesses"},
        "tip": {"title": "Dica do dia", "description": "Uma dica prática para melhorar seu dia", "why": "Pequenas mudanças, grandes resultados"},
    }
    return fallbacks.get(category, fallbacks["tip"])


async def _generate_ai_discovery(
    name: str, category: str, discovery: Dict[str, Any], interests: List[str],
) -> Optional[str]:
    """Generate discovery message via GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    prompt = (
        f"You are Capivarex. Generate a brief discovery message for {name or 'the user'}. "
        f"Max 4-5 lines, use emojis. Be excited but not pushy.\n\n"
        f"Category: {category}\n"
        f"Discovery: {json.dumps(discovery)}\n"
        f"User interests: {', '.join(interests[:3])}\n\n"
        f"Start with '💡 Achei algo pra você!' Portuguese."
    )

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=200,
            temperature=0.8,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 20:
            return text
    except Exception:
        pass
    return None


def _generate_fallback_discovery(name: str, category: str, discovery: Dict[str, Any]) -> str:
    """Fallback discovery message."""
    greeting = f"Oi {name}!" if name else ""
    title = discovery.get("title", "Algo interessante")
    desc = discovery.get("description", "")
    why = discovery.get("why", "")

    category_emoji = {
        "restaurant": "🍽️", "event": "🎭", "article": "📖", "tip": "💡",
    }
    emoji = category_emoji.get(category, "💡")

    msg = f"💡 **Achei algo pra você!** {greeting}\n\n"
    msg += f"{emoji} **{title}**\n"
    if desc:
        msg += f"{desc}\n"
    if why:
        msg += f"\n✨ *{why}*"

    return msg


async def _store_discovery(user_id: str, text: str, data: Dict[str, Any]) -> None:
    """Store discovery in proactivity feed."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "discovery",
            "content": text[:2000],
            "metadata": json.dumps(data, default=str),
        }).execute()
    except Exception as e:
        logger.warning("Discovery store failed: %s", e)
