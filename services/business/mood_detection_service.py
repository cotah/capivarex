"""
Mood Detection Service — Emotional intelligence for the bot (N2).

Detects the user's emotional state from messages and provides:
1. A mood label (happy, sad, stressed, angry, neutral, excited, anxious)
2. A mood score (-1.0 to 1.0, negative to positive)
3. Tone guidance for the bot's response

Detection uses:
- Keyword matching (PT + EN + ES)
- Emoji analysis
- Capitalization/punctuation patterns
- Message length patterns

Storage: user_context table (key: mood_history) — tracks last 10 moods
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from services.core import get_service

logger = logging.getLogger(__name__)

# Mood categories
MOODS = {
    "excited": {"score": 1.0, "emoji": "🎉", "tone": "enthusiastic and celebratory"},
    "happy": {"score": 0.7, "emoji": "😊", "tone": "warm and cheerful"},
    "neutral": {"score": 0.0, "emoji": "😐", "tone": "friendly and balanced"},
    "anxious": {"score": -0.3, "emoji": "😰", "tone": "calm and reassuring"},
    "stressed": {"score": -0.5, "emoji": "😓", "tone": "supportive and soothing"},
    "sad": {"score": -0.7, "emoji": "😢", "tone": "empathetic and gentle"},
    "angry": {"score": -0.8, "emoji": "😤", "tone": "patient and understanding"},
}

# Keywords per mood (PT + EN)
MOOD_KEYWORDS: Dict[str, List[str]] = {
    "excited": [
        "incrível",
        "maravilhoso",
        "fantástico",
        "consegui",
        "passei",
        "amazing",
        "incredible",
        "awesome",
        "fantastic",
        "yesss",
        "woohoo",
        "ganhei",
        "aprovado",
        "promoted",
        "aceite",
        "accepted",
    ],
    "happy": [
        "feliz",
        "contente",
        "bem",
        "ótimo",
        "legal",
        "bom dia",
        "happy",
        "great",
        "good",
        "wonderful",
        "love",
        "nice",
        "obrigado",
        "thanks",
        "adoro",
        "gosto",
    ],
    "anxious": [
        "nervoso",
        "ansioso",
        "preocupado",
        "medo",
        "receio",
        "anxious",
        "nervous",
        "worried",
        "scared",
        "afraid",
        "uneasy",
        "e se",
        "what if",
        "será que",
    ],
    "stressed": [
        "estressado",
        "cansado",
        "exausto",
        "sobrecarregado",
        "pressão",
        "stressed",
        "tired",
        "exhausted",
        "overwhelmed",
        "pressure",
        "não aguento",
        "can't take",
        "demais",
        "too much",
    ],
    "sad": [
        "triste",
        "mal",
        "horrível",
        "péssimo",
        "chorar",
        "solidão",
        "sad",
        "terrible",
        "awful",
        "cry",
        "lonely",
        "depressed",
        "difícil",
        "difficult",
        "hard day",
        "dia ruim",
    ],
    "angry": [
        "raiva",
        "irritado",
        "furioso",
        "ódio",
        "inacreditável",
        "angry",
        "furious",
        "hate",
        "pissed",
        "unbelievable",
        "absurdo",
        "ridiculo",
        "ridiculous",
        "unfair",
        "injusto",
    ],
}

# Emoji mood indicators
EMOJI_MOODS: Dict[str, str] = {
    "😊": "happy",
    "😁": "happy",
    "🥰": "happy",
    "❤️": "happy",
    "💪": "happy",
    "🎉": "excited",
    "🥳": "excited",
    "🏆": "excited",
    "✨": "excited",
    "🔥": "excited",
    "😢": "sad",
    "😭": "sad",
    "💔": "sad",
    "🥺": "sad",
    "😤": "angry",
    "🤬": "angry",
    "😡": "angry",
    "😰": "anxious",
    "😨": "anxious",
    "😬": "anxious",
    "😓": "stressed",
    "😩": "stressed",
    "🤯": "stressed",
    "😫": "stressed",
}


def detect_mood(message: str) -> Dict[str, Any]:
    """
    Detect mood from a message.

    Returns:
        {
            "mood": "happy",
            "score": 0.7,
            "confidence": 0.8,
            "tone_guidance": "warm and cheerful",
            "emoji": "😊",
        }
    """
    if not message or len(message.strip()) == 0:
        return _mood_result("neutral", 0.3)

    lower = message.lower().strip()

    # 1. Check emojis first (strong signal — works even for single emoji)
    emoji_mood = _detect_emoji_mood(message)

    if len(lower) < 3 and not emoji_mood:
        return _mood_result("neutral", 0.3)

    # 2. Check keywords
    keyword_mood, keyword_score = _detect_keyword_mood(lower)

    # 3. Check patterns (caps, punctuation)
    pattern_mood = _detect_pattern_mood(message)

    # 4. Combine signals
    if emoji_mood and keyword_mood and emoji_mood == keyword_mood:
        return _mood_result(emoji_mood, 0.9)
    elif keyword_mood and keyword_score >= 2:
        confidence = min(0.9, 0.5 + keyword_score * 0.1)
        return _mood_result(keyword_mood, confidence)
    elif emoji_mood:
        return _mood_result(emoji_mood, 0.6)
    elif keyword_mood:
        return _mood_result(keyword_mood, 0.5)
    elif pattern_mood:
        return _mood_result(pattern_mood, 0.4)

    return _mood_result("neutral", 0.3)


def _detect_emoji_mood(message: str) -> Optional[str]:
    """Detect mood from emojis in message."""
    for emoji, mood in EMOJI_MOODS.items():
        if emoji in message:
            return mood
    return None


def _detect_keyword_mood(text: str) -> Tuple[Optional[str], int]:
    """Detect mood from keywords. Returns (mood, match_count)."""
    best_mood = None
    best_count = 0

    for mood, keywords in MOOD_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_mood = mood

    return best_mood, best_count


def _detect_pattern_mood(message: str) -> Optional[str]:
    """Detect mood from text patterns."""
    # ALL CAPS = excited or angry
    upper_ratio = sum(1 for c in message if c.isupper()) / max(len(message), 1)
    if upper_ratio > 0.6 and len(message) > 5:
        if "!" in message:
            return "excited"
        return "angry"

    # Multiple exclamation marks = excited
    if message.count("!") >= 3:
        return "excited"

    # Ellipsis = sad or anxious
    if "..." in message and len(message) < 50:
        return "sad"

    # Question marks + short = anxious
    if message.count("?") >= 2 and len(message) < 100:
        return "anxious"

    return None


def _mood_result(mood: str, confidence: float) -> Dict[str, Any]:
    """Build mood result dict."""
    mood_info = MOODS.get(mood, MOODS["neutral"])
    return {
        "mood": mood,
        "score": mood_info["score"],
        "confidence": round(confidence, 2),
        "tone_guidance": mood_info["tone"],
        "emoji": mood_info["emoji"],
    }


def get_tone_instruction(mood_result: Dict[str, Any]) -> str:
    """
    Generate a tone instruction to prepend to bot's system prompt.

    This tells the AI how to respond based on detected mood.
    """
    mood = mood_result.get("mood", "neutral")
    confidence = mood_result.get("confidence", 0)

    if confidence < 0.4:
        return ""  # Not confident enough to adjust

    instructions = {
        "excited": (
            "The user seems very excited and happy! Match their energy. "
            "Be enthusiastic, use celebratory language and emojis. Celebrate with them!"
        ),
        "happy": (
            "The user is in a good mood. Be warm, friendly, and cheerful. "
            "Keep the positive energy going."
        ),
        "anxious": (
            "The user seems anxious or worried. Be calm and reassuring. "
            "Offer practical help and perspective. Don't minimize their concerns."
        ),
        "stressed": (
            "The user seems stressed or overwhelmed. Be supportive and soothing. "
            "Suggest taking it one step at a time. Offer to help prioritize."
        ),
        "sad": (
            "The user seems sad or going through a difficult time. Be empathetic and gentle. "
            "Acknowledge their feelings. Don't try to immediately fix things — listen first."
        ),
        "angry": (
            "The user seems frustrated or angry. Be patient and understanding. "
            "Validate their feelings. Help constructively without being dismissive."
        ),
        "neutral": "",
    }

    return instructions.get(mood, "")


async def save_mood(user_id: str, mood_result: Dict[str, Any]) -> None:
    """Save mood to history for trend tracking."""
    try:
        import json

        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()

        # Load existing history
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "mood_history")
            .limit(1)
            .execute()
        )

        history = []
        if result.data:
            val = result.data[0].get("value", "[]")
            history = json.loads(val) if isinstance(val, str) else val

        # Add new entry
        history.append(
            {
                "mood": mood_result["mood"],
                "score": mood_result["score"],
                "confidence": mood_result["confidence"],
                "timestamp": time.time(),
            }
        )

        # Keep last 10
        history = history[-10:]

        client.table("user_context").upsert(
            {
                "user_id": user_id,
                "key": "mood_history",
                "value": json.dumps(history),
            }
        ).execute()

    except Exception as e:
        logger.warning("Save mood failed: %s", e)


async def get_mood_trend(user_id: str) -> Optional[str]:
    """Get mood trend (improving, declining, stable)."""
    try:
        import json

        db = get_service("database")
        if not db or not db.is_initialized():
            return None

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "mood_history")
            .limit(1)
            .execute()
        )

        if not result.data:
            return None

        val = result.data[0].get("value", "[]")
        history = json.loads(val) if isinstance(val, str) else val

        if len(history) < 3:
            return None

        recent = [h["score"] for h in history[-3:]]
        older = (
            [h["score"] for h in history[-6:-3]]
            if len(history) >= 6
            else [h["score"] for h in history[:3]]
        )

        avg_recent = sum(recent) / len(recent)
        avg_older = sum(older) / len(older)

        diff = avg_recent - avg_older
        if diff > 0.3:
            return "improving"
        elif diff < -0.3:
            return "declining"
        return "stable"

    except Exception:
        return None
