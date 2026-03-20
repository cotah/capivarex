"""
Sleep/Wake Routine Service — Adaptive night and morning routines (B1).

Night routine (~22:00):
- Checks tomorrow's first event
- Suggests bedtime for optimal sleep (7-8 hours before wake-up)
- Optionally triggers smart home: lights off, thermostat down, DND mode
- Stores sleep schedule in user preferences

Morning routine (~wake time):
- Gradual light increase (smart home)
- Quick morning briefing (weather + first events)
- Gentle alarm notification

Triggered via proactivity loop (checks user's sleep preferences).
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

DEFAULT_SLEEP_HOURS = 8
DEFAULT_NIGHT_CHECK_HOUR = 22
DEFAULT_WAKE_BUFFER_MINUTES = 60  # wake up 1h before first event


async def generate_night_routine(
    user_id: str,
    user_name: str = "",
    location: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Generate night routine suggestion.

    Returns: {"text": "message", "data": {"suggested_bedtime": "23:00", ...}}
    """
    name = user_name.split()[0] if user_name else ""

    # Get tomorrow's events
    tomorrow_events = await _get_tomorrow_events(user_id)

    # Calculate ideal bedtime
    first_event_time = None
    if tomorrow_events:
        first = tomorrow_events[0]
        try:
            first_event_time = datetime.fromisoformat(
                first.get("start_time", "").replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    # Calculate suggested bedtime and wake time
    schedule = _calculate_sleep_schedule(first_event_time)

    # Get weather for tomorrow morning
    weather_summary = await _get_morning_weather(location)

    data = {
        "suggested_bedtime": schedule["bedtime"],
        "suggested_wake": schedule["wake_time"],
        "sleep_hours": schedule["sleep_hours"],
        "first_event": tomorrow_events[0].get("title", "") if tomorrow_events else None,
        "first_event_time": first_event_time.strftime("%H:%M")
        if first_event_time
        else None,
        "events_tomorrow": len(tomorrow_events),
        "weather": weather_summary,
    }

    # Generate message
    text = await _generate_ai_night_message(name, data)
    if not text:
        text = _generate_fallback_night_message(name, data)

    # Store
    await _store_routine(user_id, "night_routine", text, data)

    return {"text": text, "data": data}


async def generate_morning_routine(
    user_id: str,
    user_name: str = "",
    location: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Generate morning routine / wake-up briefing.

    Returns: {"text": "message", "data": {...}}
    """
    name = user_name.split()[0] if user_name else ""

    today_events = await _get_today_events(user_id)
    weather = await _get_morning_weather(location)

    data = {
        "events_today": len(today_events),
        "first_event": today_events[0].get("title", "") if today_events else None,
        "weather": weather,
    }

    text = await _generate_ai_morning_message(name, data)
    if not text:
        text = _generate_fallback_morning_message(name, data)

    await _store_routine(user_id, "morning_routine", text, data)
    return {"text": text, "data": data}


def _calculate_sleep_schedule(
    first_event: Optional[datetime],
) -> Dict[str, str]:
    """Calculate ideal bedtime and wake time."""
    now = datetime.now(timezone.utc)

    if first_event:
        # Wake up 1 hour before first event
        wake_dt = first_event - timedelta(minutes=DEFAULT_WAKE_BUFFER_MINUTES)
        # Bedtime = wake time - sleep hours
        bed_dt = wake_dt - timedelta(hours=DEFAULT_SLEEP_HOURS)

        # Don't suggest going to bed before 21:00
        earliest_bed = now.replace(hour=21, minute=0, second=0, microsecond=0)
        if bed_dt.hour < 21:
            bed_dt = earliest_bed

        return {
            "bedtime": bed_dt.strftime("%H:%M"),
            "wake_time": wake_dt.strftime("%H:%M"),
            "sleep_hours": DEFAULT_SLEEP_HOURS,
        }
    else:
        # No events — suggest standard schedule
        return {
            "bedtime": "23:00",
            "wake_time": "07:00",
            "sleep_hours": DEFAULT_SLEEP_HOURS,
        }


async def _get_tomorrow_events(user_id: str) -> List[Dict[str, Any]]:
    """Get tomorrow's events ordered by start time."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")

        result = (
            client.table("calendar_events")
            .select("title, start_time, end_time")
            .eq("user_id", user_id)
            .gte("start_time", f"{tomorrow}T00:00:00")
            .lte("start_time", f"{tomorrow}T23:59:59")
            .order("start_time")
            .limit(10)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Sleep routine: events failed: %s", e)
        return []


async def _get_today_events(user_id: str) -> List[Dict[str, Any]]:
    """Get today's events."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        result = (
            client.table("calendar_events")
            .select("title, start_time")
            .eq("user_id", user_id)
            .gte("start_time", f"{today}T00:00:00")
            .lte("start_time", f"{today}T23:59:59")
            .order("start_time")
            .limit(5)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Wake routine: events failed: %s", e)
        return []


async def _get_morning_weather(location: str) -> str:
    """Get brief weather summary."""
    if not location:
        return ""
    try:
        weather_svc = get_service("weather")
        if weather_svc and weather_svc.is_initialized():
            data = await weather_svc.get_weather(location)
            if data:
                temp = data.get("temperature", "")
                desc = data.get("description", "")
                return f"{temp}°C, {desc}" if temp else ""
    except Exception:
        pass
    return ""


async def _generate_ai_night_message(name: str, data: Dict[str, Any]) -> Optional[str]:
    """Generate night routine via GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    prompt = (
        f"You are Capivarex, a caring AI assistant. Generate a brief night routine "
        f"message for {name or 'the user'}. Max 5-6 lines, warm, use emojis.\n\n"
        f"Data:\n"
        f"- Suggested bedtime: {data.get('suggested_bedtime', '23:00')}\n"
        f"- Wake time: {data.get('suggested_wake', '07:00')}\n"
        f"- First event tomorrow: {data.get('first_event', 'none')} at {data.get('first_event_time', 'N/A')}\n"
        f"- Events tomorrow: {data.get('events_tomorrow', 0)}\n"
        f"- Weather: {data.get('weather', 'N/A')}\n\n"
        f"Start with '🌙 Boa noite'. Suggest the bedtime, mention tomorrow briefly. "
        f"Respond in Portuguese."
    )

    try:
        import asyncio

        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5.4-mini",
            max_tokens=200,
            temperature=0.7,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 20:
            return text
    except Exception:
        pass
    return None


async def _generate_ai_morning_message(
    name: str, data: Dict[str, Any]
) -> Optional[str]:
    """Generate morning routine via GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    prompt = (
        f"You are Capivarex. Generate a brief, energizing morning message "
        f"for {name or 'the user'}. Max 4-5 lines.\n\n"
        f"- Events today: {data.get('events_today', 0)}\n"
        f"- First event: {data.get('first_event', 'none')}\n"
        f"- Weather: {data.get('weather', 'N/A')}\n\n"
        f"Start with '☀️ Bom dia'. Brief, positive. Portuguese."
    )

    try:
        import asyncio

        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5.4-mini",
            max_tokens=150,
            temperature=0.7,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 20:
            return text
    except Exception:
        pass
    return None


def _generate_fallback_night_message(name: str, data: Dict[str, Any]) -> str:
    """Fallback night message."""
    greeting = f"Oi {name}!" if name else ""
    bedtime = data.get("suggested_bedtime", "23:00")
    wake = data.get("suggested_wake", "07:00")
    first_event = data.get("first_event")
    event_time = data.get("first_event_time")
    events = data.get("events_tomorrow", 0)

    msg = f"🌙 **Boa noite!** {greeting}\n\n"

    if first_event and event_time:
        msg += f"📅 Amanhã: **{first_event}** às {event_time}"
        if events > 1:
            msg += f" (+{events - 1} evento{'s' if events > 2 else ''})"
        msg += "\n"
    elif events > 0:
        msg += f"📅 Amanhã: {events} evento{'s' if events > 1 else ''}\n"
    else:
        msg += "📅 Amanhã: agenda livre! 🎉\n"

    msg += f"⏰ Sugiro dormir às **{bedtime}** e acordar às **{wake}**\n"
    msg += f"💤 {data.get('sleep_hours', 8)}h de sono para um dia produtivo\n\n"
    msg += "Boa noite e bons sonhos! 🌟"

    return msg


def _generate_fallback_morning_message(name: str, data: Dict[str, Any]) -> str:
    """Fallback morning message."""
    greeting = f"{name}!" if name else ""
    events = data.get("events_today", 0)
    first_event = data.get("first_event")
    weather = data.get("weather", "")

    msg = f"☀️ **Bom dia** {greeting}\n\n"

    if weather:
        msg += f"🌤️ {weather}\n"

    if first_event:
        msg += f"📅 Primeiro compromisso: **{first_event}**\n"
    if events > 1:
        msg += f"📋 Total: {events} eventos hoje\n"
    elif events == 0:
        msg += "📅 Dia livre — aproveite! 🎉\n"

    msg += "\nVamos ter um ótimo dia! 💪"
    return msg


async def _store_routine(
    user_id: str, routine_type: str, text: str, data: Dict[str, Any]
) -> None:
    """Store routine in proactivity feed."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": routine_type,
                "content": text[:2000],
                "metadata": json.dumps(data),
            }
        ).execute()
    except Exception as e:
        logger.warning("Store %s failed: %s", routine_type, e)
