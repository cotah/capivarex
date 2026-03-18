"""
Morning Briefing Service — P01 + C01

Generates a personalized morning briefing combining:
- Weather for user's location
- Calendar events for today
- Finance portfolio summary
- Top news headlines

Triggered on first interaction of the day or via proactivity loop (08:00 UTC).
Stored in proactivity_feed for bell notification display.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from services.core import get_service


async def generate_morning_briefing(
    user_id: str,
    user_name: str = "",
    location: str = "Dublin",
    chat_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate a complete morning briefing for a user.

    Returns dict with title + message, or None if briefing was already sent today.
    """
    # Check if briefing already sent today
    if await _briefing_sent_today(user_id):
        logger.info("Morning briefing: already sent today for user={}", user_id[:8])
        return None

    logger.info(
        "Morning briefing: generating for user={} location={}", user_id[:8], location
    )

    # Gather all data concurrently
    import asyncio

    weather_task = _get_weather(location)
    calendar_task = _get_today_events(user_id)
    finance_task = _get_finance_summary(user_id)

    weather, events, finance = await asyncio.gather(
        weather_task,
        calendar_task,
        finance_task,
        return_exceptions=True,
    )

    # Handle exceptions gracefully
    if isinstance(weather, Exception):
        logger.warning("Morning briefing: weather failed: {}", weather)
        weather = None
    if isinstance(events, Exception):
        logger.warning("Morning briefing: calendar failed: {}", events)
        events = []
    if isinstance(finance, Exception):
        logger.warning("Morning briefing: finance failed: {}", finance)
        finance = None

    # Build raw data for GPT humanization
    name = user_name.split()[0] if user_name else "there"
    greeting = _get_greeting()
    raw_data = _build_briefing_raw_data(
        name, greeting, location, weather, events, finance
    )

    # Humanize through GPT
    message = await _humanize_briefing(raw_data, name)

    title = f"{greeting} briefing — {datetime.now(timezone.utc).strftime('%b %d')}"

    # Store in proactivity_feed
    await _store_briefing(user_id, title, message)

    # Send via Telegram if chat_id available
    if chat_id:
        try:
            notification_svc = get_service("notification")
            if notification_svc:
                if not notification_svc.is_initialized():
                    await notification_svc.initialize()
                await notification_svc.send_message("telegram", chat_id, message)
                logger.info("Morning briefing: sent to Telegram chat={}", chat_id)
        except Exception as e:
            logger.warning("Morning briefing: Telegram send failed: {}", e)

    logger.info(
        "Morning briefing: generated for user={} ({} chars)", user_id[:8], len(message)
    )
    return {"title": title, "message": message}


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Humanization — GPT makes it feel like a friend, not a robot
# ---------------------------------------------------------------------------


def _build_briefing_raw_data(
    name: str,
    greeting: str,
    location: str,
    weather: Any,
    events: Any,
    finance: Any,
) -> str:
    """Build structured raw data for GPT to humanize."""
    parts = [f"User name: {name}", f"Greeting: {greeting}", f"Location: {location}"]

    if weather:
        parts.append(
            f"Weather: {weather.get('temperature', '?')}°C, {weather.get('description', '?')}"
        )

    if events and isinstance(events, list) and len(events) > 0:
        parts.append(f"Calendar: {len(events)} events today")
        for ev in events[:5]:
            parts.append(f"  - {ev.get('time', '')} {ev.get('summary', 'Event')}")
    else:
        parts.append("Calendar: No events today")

    if finance and isinstance(finance, dict):
        if finance.get("stocks_summary"):
            parts.append(f"Stocks: {finance['stocks_summary']}")
        if finance.get("crypto_summary"):
            parts.append(f"Crypto: {finance['crypto_summary']}")

    return "\n".join(parts)


async def _humanize_briefing(raw_data: str, name: str) -> str:
    """Pass raw briefing data through GPT for warm, human-like output."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a personal AI assistant with warm personality. Generate a morning briefing for {name}.

RULES:
- Be warm, friendly, like a good friend waking you up with useful info
- Use emojis naturally (not excessively — 4-5 total)
- Start with a warm greeting mentioning the weather naturally
- Mention calendar events conversationally, not as a list
- Mention market highlights briefly if available
- End with a warm question or encouragement
- Keep it under 12 lines
- Sound HUMAN, not robotic. Feel the user. Have emotion.

BAD (robotic): "Weather: 12°C, cloudy. Events: 2. Stocks: AAPL +3.2%"
GOOD (human): "Morning Marcos! ☀️ It's 12°C outside with some clouds — grab a jacket if you're heading out. You've got a busy one: meeting with Pedro at 13h and that client call at 15h. Oh, and your Apple stock is having a nice day — up 3.2%! Ready to take on the day?"

RAW DATA:
{raw_data}

Generate the morning briefing:"""

        try:
            import asyncio

            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=400,
                temperature=0.8,
            )
            text = (
                response if isinstance(response, str) else response.get("content", "")
            )
            if text and len(text) > 20:
                return text
        except Exception as e:
            logger.warning("Morning briefing: GPT humanization failed: {}", e)

    # Fallback: template-based (still warm)
    return _fallback_briefing(raw_data, name)


def _fallback_briefing(raw_data: str, name: str) -> str:
    """Fallback briefing when GPT unavailable — still warm, with emojis."""
    lines = raw_data.split("\n")
    parts = [f"**Good morning, {name}!** ☀️\n"]

    for line in lines:
        if line.startswith("Weather:"):
            parts.append(f"🌤️ {line}")
        elif line.startswith("Calendar: No"):
            parts.append("📅 No events today — enjoy the free time!")
        elif line.startswith("Calendar:"):
            parts.append(f"📅 {line}")
        elif line.strip().startswith("- "):
            parts.append(f"  • {line.strip()[2:]}")
        elif line.startswith("Stocks:"):
            parts.append(f"📈 {line}")
        elif line.startswith("Crypto:"):
            parts.append(f"₿ {line}")

    parts.append("\n💬 What would you like to do today?")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


async def _get_weather(location: str) -> Optional[Dict[str, Any]]:
    """Get current weather for location."""
    weather_svc = get_service("weather")
    if not weather_svc or not weather_svc.is_initialized():
        return None

    import asyncio

    result = await asyncio.to_thread(weather_svc.get_current_weather, location)
    if not result or "error" in result:
        return None
    return result


async def _get_today_events(user_id: str) -> List[Dict[str, Any]]:
    """Get today's calendar events."""
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return []

    try:
        events = await calendar_svc.async_get_today_events(user_id=user_id)
        if not events:
            # Try alternative method
            event = await calendar_svc.async_get_next_meeting(user_id=user_id)
            if event and not isinstance(event, dict):
                return []
            if event and event.get("summary"):
                return [event]
        return events if isinstance(events, list) else []
    except Exception:
        return []


async def _get_finance_summary(user_id: str) -> Optional[Dict[str, Any]]:
    """Get brief finance summary using user's personal watchlist."""
    from services.business.weekly_recap_service import get_user_watchlist

    watchlist = await get_user_watchlist(user_id)
    finance_svc = get_service("finance")
    crypto_svc = get_service("crypto")
    result = {}

    # Stocks (from user's watchlist)
    if finance_svc and finance_svc.is_initialized() and watchlist.get("stocks"):
        try:
            import asyncio

            summary = await asyncio.to_thread(
                finance_svc.get_watchlist_summary,
                watchlist["stocks"][:5],  # Top 5 from their list
            )
            if summary and isinstance(summary, dict):
                changes = []
                for ticker, data in summary.items():
                    change = data.get("change_pct", 0)
                    arrow = "🟢" if change >= 0 else "🔴"
                    changes.append(f"{ticker} {arrow}{change:+.1f}%")
                result["stocks_summary"] = " · ".join(changes[:4])
        except Exception:
            pass

    # Crypto
    if crypto_svc and crypto_svc.is_initialized():
        try:
            import asyncio

            top = await asyncio.to_thread(crypto_svc.get_top_coins, 3)
            if top and isinstance(top, list):
                changes = []
                for coin in top[:3]:
                    name = coin.get("symbol", "").upper()
                    change = coin.get("price_change_percentage_24h", 0)
                    arrow = "🟢" if change >= 0 else "🔴"
                    changes.append(f"{name} {arrow}{change:+.1f}%")
                result["crypto_summary"] = " · ".join(changes)
        except Exception:
            pass

    return result if result else None


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


async def _briefing_sent_today(user_id: str) -> bool:
    """Check if morning briefing was already sent today."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        today_start = (
            datetime.now(timezone.utc).replace(hour=0, minute=0, second=0).isoformat()
        )
        result = (
            client.table("proactivity_feed")
            .select("id")
            .eq("user_id", user_id)
            .eq("type", "morning_briefing")
            .gte("created_at", today_start)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


async def _store_briefing(user_id: str, title: str, message: str) -> None:
    """Store briefing in proactivity_feed."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": "morning_briefing",
                "title": title,
                "message": message,
                "metadata": json.dumps({"version": "1.0"}),
                "is_read": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
        ).execute()
    except Exception as e:
        logger.warning("Morning briefing: failed to store: {}", e)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_greeting() -> str:
    """Get time-appropriate greeting."""
    hour = datetime.now(timezone.utc).hour
    if hour < 12:
        return "Good morning"
    elif hour < 18:
        return "Good afternoon"
    return "Good evening"


def _weather_icon(description: str) -> str:
    """Map weather description to emoji."""
    desc = description.lower()
    if "rain" in desc or "drizzle" in desc:
        return "🌧️"
    if "cloud" in desc or "overcast" in desc:
        return "☁️"
    if "snow" in desc:
        return "❄️"
    if "thunder" in desc or "storm" in desc:
        return "⛈️"
    if "fog" in desc or "mist" in desc:
        return "🌫️"
    if "clear" in desc or "sun" in desc:
        return "☀️"
    return "🌤️"
