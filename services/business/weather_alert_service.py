"""
Unexpected Weather Alert Service — A7 (P17)

Proactively alerts users about sudden weather changes:
1. Rain starting within 2 hours (user might not have umbrella)
2. Temperature drop > 10°C from morning
3. Strong wind warnings (> 50 km/h)
4. Snow/ice alerts
5. Extreme heat warnings (> 35°C)

Runs in proactivity loop. Checks user's saved location.
Only alerts ONCE per weather event (dedup by event type + date).

All output HUMANIZED via GPT.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Weather alert thresholds
RAIN_CHANCE_THRESHOLD = 70  # % chance of rain to alert
WIND_SPEED_THRESHOLD = 50  # km/h
TEMP_DROP_THRESHOLD = 10  # °C drop from morning
EXTREME_HEAT_THRESHOLD = 35  # °C
SNOW_KEYWORDS = {"snow", "sleet", "ice", "blizzard", "freezing", "neve", "gelo", "geada"}


async def check_weather_alerts(
    user_id: str,
    location: str = "",
) -> List[Dict[str, Any]]:
    """
    Check for severe weather conditions at user's location.

    Returns list of weather alerts.
    """
    if not location:
        location = await _get_user_location(user_id)
    if not location:
        return []

    weather_svc = get_service("weather")
    if not weather_svc or not weather_svc.is_initialized():
        return []

    try:
        data = await weather_svc.get_weather(location)
        if not data:
            return []
    except Exception as e:
        logger.warning("Weather alert check failed: %s", e)
        return []

    alerts = []

    # 1. Rain alert
    rain_chance = data.get("rain_chance", 0) or data.get("pop", 0)
    if isinstance(rain_chance, (int, float)) and rain_chance >= RAIN_CHANCE_THRESHOLD:
        alerts.append({
            "type": "rain",
            "severity": "warning",
            "message": f"Rain likely ({int(rain_chance)}% chance)",
            "advice": "Bring an umbrella!",
        })

    # 2. Strong wind
    wind_speed = data.get("wind_speed", 0) or 0
    if isinstance(wind_speed, (int, float)) and wind_speed >= WIND_SPEED_THRESHOLD:
        alerts.append({
            "type": "wind",
            "severity": "warning",
            "message": f"Strong wind ({int(wind_speed)} km/h)",
            "advice": "Secure outdoor items and be careful driving.",
        })

    # 3. Extreme heat
    temp = data.get("temperature", 0) or 0
    if isinstance(temp, (int, float)) and temp >= EXTREME_HEAT_THRESHOLD:
        alerts.append({
            "type": "heat",
            "severity": "warning",
            "message": f"Extreme heat ({temp}°C)",
            "advice": "Stay hydrated and avoid sun exposure.",
        })

    # 4. Snow/Ice
    description = (data.get("description", "") or "").lower()
    if any(kw in description for kw in SNOW_KEYWORDS):
        alerts.append({
            "type": "snow",
            "severity": "alert",
            "message": f"Snow/ice conditions: {data.get('description', '')}",
            "advice": "Drive carefully and dress warm.",
        })

    # 5. Temperature drop (check feels_like vs temp)
    feels_like = data.get("feels_like", temp)
    if isinstance(temp, (int, float)) and isinstance(feels_like, (int, float)):
        if temp - feels_like >= TEMP_DROP_THRESHOLD:
            alerts.append({
                "type": "temp_drop",
                "severity": "info",
                "message": f"Feels much colder than expected ({temp}°C but feels like {feels_like}°C)",
                "advice": "Wear extra layers.",
            })

    return alerts


async def _get_user_location(user_id: str) -> str:
    """Get user's saved location from preferences."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return ""

    try:
        client = db.get_client()
        result = (
            client.table("user_preferences")
            .select("location, city")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("location") or result.data[0].get("city", "")
    except Exception:
        pass
    return ""


# ---------------------------------------------------------------------------
# Alert Generation
# ---------------------------------------------------------------------------

async def generate_weather_alert(
    user_name: str,
    alerts: List[Dict[str, Any]],
    location: str = "",
) -> Optional[str]:
    """Generate humanized weather alert."""
    if not alerts:
        return None

    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    raw = f"User: {name}\nLocation: {location or 'unknown'}\n"
    for a in alerts:
        raw += f"- [{a['severity']}] {a['message']} — {a['advice']}\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} needs a weather alert.

RULES:
- Be warm and helpful, not alarming
- Start with something like "Heads up!" or "Quick weather update!"
- Mention each alert with practical advice
- Keep under 5 lines
- Use 2-3 weather emojis: 🌧️ rain, 💨 wind, 🌡️ heat, ❄️ snow, 🧥 cold
- End with "Stay safe!" or similar

RAW DATA:
{raw}

Generate:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=200,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    emoji_map = {"rain": "🌧️", "wind": "💨", "heat": "🌡️", "snow": "❄️", "temp_drop": "🧥"}
    lines = [f"⚠️ Weather heads up, {name}!\n"]
    for a in alerts:
        emoji = emoji_map.get(a["type"], "⚠️")
        lines.append(f"{emoji} {a['message']} — {a['advice']}")
    lines.append("\nStay safe! 👋")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Proactivity Loop Runner
# ---------------------------------------------------------------------------

async def check_weather_for_all_users() -> int:
    """Run weather check for all proactivity-enabled users."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return 0

    try:
        pref_users = await db.get_all_users_with_proactivity_enabled()
    except Exception:
        return 0

    alerts_sent = 0
    for pref in (pref_users or []):
        user_id = pref["user_id"]
        try:
            user_data = await db.get_user_by_id(user_id)
            if not user_data:
                continue

            alerts = await check_weather_alerts(user_id)
            if not alerts:
                continue

            # Dedup: check if we already alerted today for this type
            new_alerts = await _filter_already_alerted(user_id, alerts)
            if not new_alerts:
                continue

            msg = await generate_weather_alert(
                user_name=user_data.get("full_name", ""),
                alerts=new_alerts,
            )
            if msg:
                chat_id = str(user_data.get("telegram_chat_id")) if user_data.get("telegram_chat_id") else None
                if chat_id:
                    try:
                        notif = get_service("notification")
                        if notif:
                            if not notif.is_initialized():
                                await notif.initialize()
                            await notif.send_message("telegram", chat_id, msg)
                    except Exception:
                        pass
                await _store_weather_alert(user_id, new_alerts)
                alerts_sent += 1

        except Exception as e:
            logger.warning("Weather check failed for user=%s: %s", user_id[:8], e)

    if alerts_sent:
        logger.info("Weather alerter: %d alerts sent", alerts_sent)
    return alerts_sent


async def _filter_already_alerted(
    user_id: str, alerts: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Filter out alerts already sent today."""
    import json

    db = get_service("database")
    if not db or not db.is_initialized():
        return alerts

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    try:
        client = db.get_client()
        result = (
            client.table("proactivity_feed")
            .select("metadata")
            .eq("user_id", user_id)
            .eq("type", "weather_alert")
            .gte("created_at", f"{today}T00:00:00Z")
            .limit(10)
            .execute()
        )

        alerted_types = set()
        for item in (result.data or []):
            try:
                meta = json.loads(item.get("metadata", "{}") if isinstance(item.get("metadata"), str) else "{}")
                for t in meta.get("alert_types", []):
                    alerted_types.add(t)
            except (json.JSONDecodeError, TypeError):
                pass

        return [a for a in alerts if a["type"] not in alerted_types]

    except Exception:
        return alerts


async def _store_weather_alert(user_id: str, alerts: List[Dict[str, Any]]) -> None:
    """Store weather alert in proactivity_feed for dedup."""
    import json

    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        alert_types = [a["type"] for a in alerts]
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "weather_alert",
            "title": f"⚠️ Weather alert: {', '.join(alert_types)}",
            "message": "; ".join(a["message"] for a in alerts),
            "metadata": json.dumps({"alert_types": alert_types}),
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("Store weather alert failed: %s", e)
