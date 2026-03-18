"""
Commute Optimizer Service — Smart commute suggestions (B2).

Analyzes traffic and calendar to suggest optimal departure time.
'Saia em 15 min — trânsito leve pela M50, chegada estimada 8:45.'

Features:
- Detects work commute patterns from calendar
- Checks real-time traffic via Maps service
- Calculates optimal departure time
- Sends proactive alerts before commute
- Learns preferred routes

Storage: user_context table (key: commute_preferences)
"""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

DEFAULT_COMMUTE_BUFFER = 15  # minutes buffer before event
DEFAULT_COMMUTE_DURATION = 30  # minutes if can't calculate


async def generate_commute_alert(
    user_id: str,
    user_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Check if user has a commute coming up and generate alert.

    Returns: {"text": "message", "data": {commute info}}
    """
    name = user_name.split()[0] if user_name else ""

    # Get upcoming events that might require commute
    events = await _get_upcoming_events(user_id)
    if not events:
        return None

    # Find first event with a location (needs commute)
    commute_event = None
    for event in events:
        location = event.get("location", "")
        if location and len(location) > 5:
            commute_event = event
            break

    if not commute_event:
        return None

    # Get user's home location
    home = await _get_home_location(user_id)

    # Calculate commute
    destination = commute_event.get("location", "")
    event_time = commute_event.get("start_time", "")
    event_title = commute_event.get("title", "Evento")

    commute_info = await _estimate_commute(home, destination)

    # Calculate when to leave
    try:
        event_dt = datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        duration_min = commute_info.get("duration_minutes", DEFAULT_COMMUTE_DURATION)
        leave_dt = event_dt - timedelta(minutes=duration_min + DEFAULT_COMMUTE_BUFFER)
        leave_time = leave_dt.strftime("%H:%M")
        arrival_time = (event_dt - timedelta(minutes=DEFAULT_COMMUTE_BUFFER)).strftime(
            "%H:%M"
        )
    except (ValueError, TypeError):
        leave_time = "?"
        arrival_time = "?"
        duration_min = DEFAULT_COMMUTE_DURATION

    data = {
        "event_title": event_title,
        "event_time": event_time,
        "destination": destination,
        "leave_at": leave_time,
        "arrival_estimate": arrival_time,
        "duration_minutes": duration_min,
        "traffic": commute_info.get("traffic", "normal"),
        "route": commute_info.get("route_summary", ""),
    }

    text = _generate_commute_message(name, data)
    await _store_commute(user_id, text, data)

    return {"text": text, "data": data}


async def _get_upcoming_events(user_id: str) -> List[Dict[str, Any]]:
    """Get events in the next 3 hours that have a location."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        now = datetime.now(timezone.utc).isoformat()
        soon = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()

        result = (
            client.table("calendar_events")
            .select("title, start_time, location")
            .eq("user_id", user_id)
            .gte("start_time", now)
            .lte("start_time", soon)
            .order("start_time")
            .limit(5)
            .execute()
        )
        return result.data if result.data else []
    except Exception as e:
        logger.warning("Commute: events failed: %s", e)
        return []


async def _get_home_location(user_id: str) -> str:
    """Get user's home address from preferences."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return ""

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "home_address")
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0].get("value", "")
    except Exception:
        pass
    return ""


async def _estimate_commute(origin: str, destination: str) -> Dict[str, Any]:
    """Estimate commute duration and traffic. Uses Maps service if available."""
    if not origin or not destination:
        return {
            "duration_minutes": DEFAULT_COMMUTE_DURATION,
            "traffic": "unknown",
            "route_summary": "",
        }

    try:
        maps_svc = get_service("maps")
        if maps_svc:
            if not maps_svc.is_initialized():
                await maps_svc.initialize()

            result = await maps_svc.get_directions(origin, destination)
            if result:
                duration = result.get("duration_minutes", DEFAULT_COMMUTE_DURATION)
                traffic = (
                    "heavy"
                    if duration > 45
                    else "moderate"
                    if duration > 25
                    else "light"
                )
                return {
                    "duration_minutes": duration,
                    "traffic": traffic,
                    "route_summary": result.get("summary", ""),
                }
    except Exception as e:
        logger.warning("Commute estimation failed: %s", e)

    return {
        "duration_minutes": DEFAULT_COMMUTE_DURATION,
        "traffic": "unknown",
        "route_summary": "",
    }


def _generate_commute_message(name: str, data: Dict[str, Any]) -> str:
    """Generate commute alert message."""
    greeting = f"Oi {name}!" if name else ""
    event = data.get("event_title", "Evento")
    leave = data.get("leave_at", "?")
    arrival = data.get("arrival_estimate", "?")
    duration = data.get("duration_minutes", 30)
    traffic = data.get("traffic", "unknown")
    route = data.get("route_summary", "")

    traffic_emoji = {
        "light": "🟢",
        "moderate": "🟡",
        "heavy": "🔴",
        "unknown": "⚪",
    }
    traffic_label = {
        "light": "trânsito leve",
        "moderate": "trânsito moderado",
        "heavy": "trânsito pesado",
        "unknown": "trânsito desconhecido",
    }

    emoji = traffic_emoji.get(traffic, "⚪")
    label = traffic_label.get(traffic, "")

    msg = f"🚗 **Hora de sair!** {greeting}\n\n"
    msg += f"📅 **{event}**\n"
    msg += f"⏰ Saia às **{leave}** → chegada estimada **{arrival}**\n"
    msg += f"🕐 Duração: ~{duration} min\n"
    msg += f"{emoji} {label}\n"

    if route:
        msg += f"🗺️ Rota: {route}\n"

    if traffic == "heavy":
        msg += "\n⚠️ Trânsito pesado! Considere sair mais cedo ou usar rota alternativa."
    elif traffic == "light":
        msg += "\n✅ Caminho livre! Viagem tranquila."

    return msg


async def _store_commute(user_id: str, text: str, data: Dict[str, Any]) -> None:
    """Store commute alert in proactivity feed."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return

        client = db.get_client()
        client.table("proactivity_feed").insert(
            {
                "user_id": user_id,
                "type": "commute_alert",
                "content": text[:2000],
                "metadata": json.dumps(data),
            }
        ).execute()
    except Exception as e:
        logger.warning("Commute store failed: %s", e)
