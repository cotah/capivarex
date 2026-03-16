"""
Travel Planner Service — S6 (P33): Proactive Trip Detection & Planning.

Phase 1: Detection
- Scans calendar for events 14-30 days ahead
- Detects trips by: location abroad, keywords (viagem, trip, férias, voo)
- Min 3 days duration to avoid false positives (business day trips)
- Sends humanized proactive message via GPT
- Deduplicates: only 1 alert per trip

Phase 2 (future): Preference gathering (3-4 questions)
Phase 3 (future): Itinerary building via research + weather + maps
Phase 4 (future): During-trip alerts

All output HUMANIZED through GPT — sounds like a friend who loves travel.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from services.core import get_service


# Trip detection keywords (multi-language)
TRIP_KEYWORDS = {
    "viagem", "trip", "travel", "férias", "vacation", "holiday", "holidays",
    "voo", "flight", "voos", "flights", "hotel", "resort", "airbnb",
    "aeroporto", "airport", "passagem", "booking", "reserva", "cruzeiro",
    "cruise", "mochilão", "backpack", "road trip", "roadtrip", "getaway",
    "escapadinha", "excursão", "tour", "safari",
}

# Countries and major cities to detect international travel
MAJOR_DESTINATIONS = {
    # Countries
    "thailand", "tailândia", "japan", "japão", "brazil", "brasil", "portugal",
    "spain", "espanha", "france", "frança", "italy", "itália", "germany",
    "alemanha", "uk", "england", "inglaterra", "usa", "estados unidos",
    "mexico", "méxico", "colombia", "colômbia", "argentina", "australia",
    "austrália", "india", "índia", "china", "south korea", "coreia",
    "indonesia", "indonésia", "vietnam", "vietnã", "turkey", "turquia",
    "egypt", "egito", "morocco", "marrocos", "south africa", "greece",
    "grécia", "croatia", "croácia", "dubai", "maldives", "maldivas",
    "iceland", "islândia", "norway", "noruega", "sweden", "suécia",
    "switzerland", "suíça", "austria", "áustria", "netherlands", "holanda",
    "belgium", "bélgica", "czech", "checa", "poland", "polônia",
    "ireland", "irlanda", "scotland", "escócia", "canada", "canadá",
    "new zealand", "nova zelândia", "peru", "chile", "cuba", "jamaica",
    "costa rica", "bali", "phuket", "cancun", "cancún",
    # Major cities
    "bangkok", "tokyo", "paris", "london", "londres", "new york", "nova york",
    "los angeles", "barcelona", "rome", "roma", "amsterdam", "berlin",
    "berlim", "lisbon", "lisboa", "madrid", "milan", "milão", "dubai",
    "singapore", "singapura", "hong kong", "sydney", "rio de janeiro",
    "são paulo", "buenos aires", "istanbul", "istambul", "cairo",
    "marrakech", "cape town", "seoul", "osaka", "kyoto", "chiang mai",
    "bali", "ubud", "hanoi", "ho chi minh", "kuala lumpur", "prague",
    "praga", "vienna", "viena", "budapest", "dubrovnik", "santorini",
    "mykonos", "ibiza", "mallorca", "tenerife", "porto", "algarve",
}


# ---------------------------------------------------------------------------
# Trip Detection
# ---------------------------------------------------------------------------

async def detect_upcoming_trips(user_id: str) -> List[Dict[str, Any]]:
    """
    Scan calendar for upcoming trips (14-30 days ahead).

    Returns list of detected trips with:
    - event_id, summary, location, start, end, duration_days, destination
    """
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return []

    try:
        # Get events 14-30 days ahead
        events = await calendar_svc.async_get_upcoming_events(
            user_id=user_id,
            max_results=30,
            days_ahead=30,
        )
        if not events:
            return []
    except Exception as e:
        logger.warning("Travel detect: calendar failed for user={}: {}", user_id[:8], e)
        return []

    now = datetime.now(timezone.utc)
    min_days_ahead = 14
    detected = []

    for event in events:
        summary = (event.get("summary", "") or "").lower()
        location = (event.get("location", "") or "").lower()
        description = (event.get("description", "") or "").lower()
        start_str = event.get("start", "")
        end_str = event.get("end", "")

        # Parse dates
        start_dt = _parse_date(start_str)
        end_dt = _parse_date(end_str)
        if not start_dt or not end_dt:
            continue

        # Check if event is 14-30 days from now
        days_until = (start_dt - now).days
        if days_until < min_days_ahead or days_until > 30:
            continue

        # Calculate duration
        duration_days = (end_dt - start_dt).days
        if duration_days < 3:
            continue  # Skip short events (day trips, business meetings)

        # Detect if it's a trip
        destination = _detect_destination(summary, location, description)
        is_trip = destination is not None or _has_trip_keywords(summary, location, description)

        if is_trip:
            detected.append({
                "event_id": event.get("id", ""),
                "summary": event.get("summary", "Trip"),
                "location": event.get("location", ""),
                "start": start_str,
                "end": end_str,
                "start_date": start_dt.strftime("%b %d"),
                "end_date": end_dt.strftime("%b %d"),
                "duration_days": duration_days,
                "days_until": days_until,
                "destination": destination or _extract_destination_from_text(summary, location),
            })

    logger.info(
        "Travel detect: user={} found {} trips in {} events",
        user_id[:8], len(detected), len(events),
    )
    return detected


def _detect_destination(summary: str, location: str, description: str) -> Optional[str]:
    """Check if any text mentions a known destination."""
    combined = f"{summary} {location} {description}"
    for dest in MAJOR_DESTINATIONS:
        if dest in combined:
            return dest.title()
    return None


def _has_trip_keywords(summary: str, location: str, description: str) -> bool:
    """Check if any text contains trip-related keywords."""
    combined = f"{summary} {location} {description}"
    return any(kw in combined for kw in TRIP_KEYWORDS)


def _extract_destination_from_text(summary: str, location: str) -> str:
    """Best-effort destination extraction from event text."""
    # If location field is set, use it
    if location and len(location) > 2:
        return location.title()
    # Otherwise use the summary, stripping common prefixes
    clean = summary
    for prefix in ["viagem", "trip to", "férias em", "vacation in", "flight to", "voo para"]:
        if clean.startswith(prefix):
            clean = clean[len(prefix):].strip(" -:–")
    return clean.title() if clean else "Unknown destination"


def _parse_date(date_str: Any) -> Optional[datetime]:
    """Parse ISO date or datetime string."""
    if not date_str:
        return None
    try:
        s = str(date_str)
        if "T" in s:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        # Date only (all-day event) — treat as start of day
        return datetime.strptime(s[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Proactive Message Generation (humanized)
# ---------------------------------------------------------------------------

async def generate_trip_alert(
    user_id: str,
    trip: Dict[str, Any],
    user_name: str = "",
    chat_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate a humanized proactive message about a detected trip.
    
    Deduplicates: only sends once per trip event_id.
    """
    event_id = trip.get("event_id", "")

    # Check if already alerted for this trip
    if await _trip_alert_sent(user_id, event_id):
        return None

    name = user_name.split()[0] if user_name else "there"
    destination = trip.get("destination", "your trip")
    duration = trip.get("duration_days", 0)
    start_date = trip.get("start_date", "")
    end_date = trip.get("end_date", "")
    days_until = trip.get("days_until", 0)

    # Build raw data for GPT
    raw = (
        f"User name: {name}\n"
        f"Destination: {destination}\n"
        f"Dates: {start_date} to {end_date} ({duration} days)\n"
        f"Days until trip: {days_until}\n"
        f"Event summary: {trip.get('summary', '')}\n"
        f"Location field: {trip.get('location', '')}"
    )

    message = await _humanize_trip_alert(raw, name, destination, duration)
    title = f"Trip to {destination} detected!"

    # Store in proactivity_feed
    await _store_trip_alert(user_id, event_id, title, message, trip)

    # Send via Telegram
    if chat_id:
        try:
            notif = get_service("notification")
            if notif:
                if not notif.is_initialized():
                    await notif.initialize()
                await notif.send_message("telegram", chat_id, message)
        except Exception as e:
            logger.warning("Travel alert: Telegram failed: {}", e)

    logger.info(
        "Travel alert: sent for user={} destination={} in {} days",
        user_id[:8], destination, days_until,
    )
    return {"title": title, "message": message, "trip": trip}


async def _humanize_trip_alert(
    raw: str, name: str, destination: str, duration: int
) -> str:
    """Generate warm, excited message about detected trip."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a personal AI assistant who LOVES helping with travel. Generate a proactive message about a trip you detected in {name}'s calendar.

RULES:
- Be genuinely excited for them! This is a trip, it's fun!
- Mention the destination and dates naturally
- If it's a long trip ({duration} days), comment on how amazing that is
- Offer to help plan — "Want me to put together a travel plan?"
- Mention you can research restaurants, activities, hotels, weather
- Keep it under 6 lines
- Use 2-3 emojis (travel themed: ✈️ 🌴 🗺️ 🏖️ 🌍 🎒)
- Sound like a friend who's excited about YOUR trip
- End with a question to engage the user

BAD: "I detected event: Thailand 15 Mar - 15 Apr. Duration: 30 days. Would you like assistance?"
GOOD: "Hey {name}! ✈️ I noticed you're heading to Thailand — a whole month, from March 15 to April 15! That's going to be incredible. I already have some ideas for your itinerary. Want me to put together a personalized travel plan? I can research the best spots, restaurants, and activities based on your style. 🌴"

RAW DATA:
{raw}

Generate the trip detection message:"""

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
        except Exception as e:
            logger.warning("Travel alert: GPT failed: {}", e)

    # Fallback — still warm and excited
    return (
        f"✈️ Hey {name}! I noticed you have a trip to **{destination}** coming up "
        f"({duration} days)! That's going to be amazing.\n\n"
        f"Want me to put together a personalized travel plan? I can research "
        f"the best restaurants, activities, and hidden gems based on your style. 🌴"
    )


# ---------------------------------------------------------------------------
# Storage & Deduplication
# ---------------------------------------------------------------------------

async def _trip_alert_sent(user_id: str, event_id: str) -> bool:
    """Check if trip alert was already sent for this event."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        result = (
            client.table("proactivity_feed")
            .select("id")
            .eq("user_id", user_id)
            .eq("type", "travel_alert")
            .limit(20)
            .execute()
        )
        for item in (result.data or []):
            try:
                meta = json.loads(item.get("metadata", "{}") if isinstance(item.get("metadata"), str) else "{}")
                if meta.get("event_id") == event_id:
                    return True
            except (json.JSONDecodeError, TypeError):
                pass
        return False
    except Exception:
        return False


async def _store_trip_alert(
    user_id: str, event_id: str, title: str, message: str, trip: Dict[str, Any]
) -> None:
    """Store trip alert in proactivity_feed."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "travel_alert",
            "title": title,
            "message": message,
            "metadata": json.dumps({
                "event_id": event_id,
                "destination": trip.get("destination", ""),
                "start": trip.get("start", ""),
                "end": trip.get("end", ""),
                "duration_days": trip.get("duration_days", 0),
            }),
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("Travel alert: store failed: {}", e)


# ---------------------------------------------------------------------------
# Proactivity Loop Runner
# ---------------------------------------------------------------------------

async def check_travel_for_all_users() -> int:
    """Run travel detection for all users with proactivity enabled.

    Called by proactivity loop (once daily).
    Returns number of alerts sent.
    """
    db = get_service("database")
    if not db or not db.is_initialized():
        return 0

    try:
        pref_users = await db.get_all_users_with_proactivity_enabled()
    except Exception:
        return 0

    if not pref_users:
        return 0

    alerts_sent = 0

    for pref in pref_users:
        user_id = pref["user_id"]
        try:
            user_data = await db.get_user_by_id(user_id)
            if not user_data:
                continue

            trips = await detect_upcoming_trips(user_id)
            if not trips:
                continue

            user_name = user_data.get("full_name", "")
            chat_id = str(user_data.get("telegram_chat_id")) if user_data.get("telegram_chat_id") else None

            for trip in trips:
                result = await generate_trip_alert(
                    user_id=user_id,
                    trip=trip,
                    user_name=user_name,
                    chat_id=chat_id,
                )
                if result:
                    alerts_sent += 1

        except Exception as e:
            logger.warning("Travel check failed for user={}: {}", user_id[:8], e)

    if alerts_sent:
        logger.info("Travel planner: {} alerts sent across all users", alerts_sent)
    return alerts_sent
