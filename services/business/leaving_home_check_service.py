"""
Leaving Home Check — A2 (P04)

When user says "vou sair" / "I'm leaving" / "leaving now":
1. Weather: "Vai chover às 14h — leva guarda-chuva!"
2. Traffic: "Trânsito normal, 25 min até ao escritório"
3. Calendar: "Próximo evento: reunião às 15h no escritório"
4. Smart Home: "Queres que eu desligue as luzes e tranque a porta?"
5. Departure: "Deves sair às 14:30 para chegar a tempo"

All output HUMANIZED via GPT — one warm, actionable message.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Trigger keywords (multi-language)
LEAVING_KEYWORDS = {
    # Portuguese
    "vou sair", "estou a sair", "saindo de casa", "vou embora",
    "estou saindo", "vou sair de casa", "a sair de casa",
    # English
    "i'm leaving", "im leaving", "leaving now", "heading out",
    "i am leaving", "leaving home", "going out",
    # Spanish
    "me voy", "salgo", "voy a salir",
}


def is_leaving_trigger(message: str) -> bool:
    """Check if the message is a leaving-home trigger."""
    msg_lower = message.lower().strip()
    return any(kw in msg_lower for kw in LEAVING_KEYWORDS)


async def generate_departure_briefing(
    user_id: str,
    user_name: str = "",
    user_location: str = "",
    message: str = "",
) -> Optional[str]:
    """
    Generate a comprehensive departure briefing.

    Combines weather, traffic, calendar, and smart home into one
    warm, actionable message.

    Returns: Humanized briefing text, or None if nothing useful to say.
    """
    name = user_name.split()[0] if user_name else "there"
    parts: Dict[str, str] = {}

    # 1. Weather check
    weather_info = await _check_weather(user_location)
    if weather_info:
        parts["weather"] = weather_info

    # 2. Next event + departure time
    event_info = await _check_next_event(user_id, user_location)
    if event_info:
        parts["event"] = event_info

    # 3. Smart home status
    smarthome_info = await _check_smart_home(user_id)
    if smarthome_info:
        parts["smarthome"] = smarthome_info

    if not parts:
        return None

    # Humanize everything into one message
    return await _humanize_briefing(name, parts)


# ---------------------------------------------------------------------------
# Individual Checks
# ---------------------------------------------------------------------------

async def _check_weather(location: str) -> Optional[str]:
    """Get weather summary for departure."""
    weather_svc = get_service("weather")
    if not weather_svc or not weather_svc.is_initialized():
        return None

    if not location:
        return None

    try:
        data = await weather_svc.get_weather(location)
        if not data:
            return None

        temp = data.get("temperature", "")
        desc = data.get("description", "")
        feels_like = data.get("feels_like", "")
        rain = data.get("rain_chance", 0) or data.get("pop", 0)
        wind = data.get("wind_speed", 0)

        parts = []
        if temp:
            parts.append(f"{temp}°C")
        if feels_like and feels_like != temp:
            parts.append(f"feels like {feels_like}°C")
        if desc:
            parts.append(desc)

        result = ", ".join(parts) if parts else ""

        # Add warnings
        warnings = []
        if isinstance(rain, (int, float)) and rain > 50:
            warnings.append("rain likely — bring an umbrella")
        elif isinstance(rain, (int, float)) and rain > 30:
            warnings.append("slight chance of rain")
        if isinstance(wind, (int, float)) and wind > 40:
            warnings.append("strong wind")

        if warnings:
            result += f". ⚠️ {', '.join(warnings)}"

        return result

    except Exception as e:
        logger.warning("Departure weather check failed: %s", e)
        return None


async def _check_next_event(user_id: str, user_location: str) -> Optional[str]:
    """Get next event info + departure time."""
    leaving_svc = get_service("leaving_now")

    if leaving_svc and leaving_svc.is_initialized() and user_location:
        try:
            result = await leaving_svc.calculate_for_next_event(
                user_location=user_location,
                user_id=user_id,
                transport_mode="driving",
            )
            if result:
                parts = [f"Next: {result.event_name}"]
                if result.event_time:
                    parts.append(f"at {result.event_time}")
                if result.travel_minutes:
                    parts.append(f"({int(result.travel_minutes)} min drive)")
                if result.leave_by:
                    parts.append(f"→ leave by {result.leave_by}")
                if result.weather_warning:
                    parts.append(f"⚠️ {result.weather_warning}")
                return " ".join(parts)
        except Exception as e:
            logger.warning("Departure event check failed: %s", e)

    # Fallback: just get next event from calendar
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return None

    try:
        events = await calendar_svc.async_get_upcoming_events(
            user_id=user_id, max_results=3, days_ahead=1,
        )
        if not events:
            return "No events today — enjoy your day!"

        now = datetime.now(timezone.utc)
        for event in events:
            start_str = event.get("start", "")
            if "T" not in str(start_str):
                continue
            try:
                start_dt = datetime.fromisoformat(str(start_str).replace("Z", "+00:00"))
                if start_dt > now:
                    summary = event.get("summary", "Event")
                    time_str = start_dt.strftime("%H:%M")
                    location = event.get("location", "")
                    loc_part = f" at {location}" if location else ""
                    return f"Next: {summary} at {time_str}{loc_part}"
            except (ValueError, TypeError):
                continue
        return None

    except Exception as e:
        logger.warning("Departure calendar check failed: %s", e)
        return None


async def _check_smart_home(user_id: str) -> Optional[str]:
    """Check smart home devices that should be turned off/locked."""
    smarthome_svc = get_service("smarthome")
    if not smarthome_svc or not smarthome_svc.is_initialized():
        return None

    try:
        # Get device status
        devices = await smarthome_svc.get_devices(user_id)
        if not devices:
            return None

        lights_on = []
        unlocked = []

        for device in devices:
            name = device.get("name", device.get("label", "device"))
            dev_type = device.get("type", "").lower()
            status = device.get("status", {})

            if "light" in dev_type or "lamp" in dev_type:
                if status.get("switch", status.get("power", "")) == "on":
                    lights_on.append(name)

            if "lock" in dev_type:
                if status.get("lock", "") == "unlocked":
                    unlocked.append(name)

        parts = []
        if lights_on:
            names = ", ".join(lights_on[:3])
            extra = f" +{len(lights_on)-3} more" if len(lights_on) > 3 else ""
            parts.append(f"Lights on: {names}{extra}")
        if unlocked:
            parts.append(f"Unlocked: {', '.join(unlocked[:3])}")

        if parts:
            return ". ".join(parts) + ". Want me to turn them off/lock?"

        return None

    except Exception as e:
        logger.warning("Departure smart home check failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Humanized Output
# ---------------------------------------------------------------------------

async def _humanize_briefing(name: str, parts: Dict[str, str]) -> str:
    """Generate one warm departure briefing from all parts."""
    openai_svc = get_service("openai")

    raw = f"User: {name}\n"
    for key, val in parts.items():
        raw += f"{key}: {val}\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} is about to leave home. Give them a quick departure briefing.

RAW DATA:
{raw}

RULES:
- Be warm and efficient — like a friend at the door giving you a quick summary
- Start with a greeting: "Have a great day!" or "Safe travels!" or similar
- Weather first (with umbrella/jacket warning if needed)
- Calendar/event next (with departure time if available)
- Smart home last (offer to turn off lights/lock doors)
- Keep under 6 lines total
- Use 3-4 emojis: 🌤️ weather, 📅 calendar, 🏠 smart home, 🚗 travel
- If nothing important, just wish them a good day

Generate:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=300,
                temperature=0.85,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    lines = [f"🚪 Heads up before you go, {name}!\n"]
    if "weather" in parts:
        lines.append(f"🌤️ {parts['weather']}")
    if "event" in parts:
        lines.append(f"📅 {parts['event']}")
    if "smarthome" in parts:
        lines.append(f"🏠 {parts['smarthome']}")
    lines.append("\n👋 Have a great day!")
    return "\n".join(lines)
