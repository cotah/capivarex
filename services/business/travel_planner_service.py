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

    # Start a planning session so user can respond "yes" in chat
    await start_planning_session(user_id, trip)

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


# ===========================================================================
# PHASE 2 — Preference Gathering + Itinerary Building
# ===========================================================================

async def gather_travel_profile(user_id: str) -> Dict[str, Any]:
    """
    Gather what we already know about the user from RAG + user_context.

    Returns profile dict with known preferences (may be partially empty).
    The bot only asks questions about what's MISSING.
    """
    profile: Dict[str, Any] = {
        "travel_style": "",      # relaxed, adventurous, cultural, mixed
        "budget_level": "",      # budget, mid-range, luxury
        "accommodation": "",     # hotel, hostel, airbnb, resort
        "food_prefs": [],        # vegetarian, seafood, local cuisine, etc.
        "interests": [],         # trekking, beaches, nightlife, museums, shopping
        "past_trips": [],        # countries/cities visited before
        "travel_companion": "",  # solo, couple, family, group
        "pace": "",              # relaxed, moderate, packed
    }

    # 1. Check user_context for saved travel preferences
    db = get_service("database")
    if db and db.is_initialized():
        try:
            import json as _json
            client = db.get_client()
            ctx = (
                client.table("user_context")
                .select("context_data")
                .eq("user_id", user_id)
                .eq("context_type", "travel_preferences")
                .limit(1)
                .execute()
            )
            if ctx.data:
                data = ctx.data[0].get("context_data", {})
                if isinstance(data, str):
                    data = _json.loads(data)
                profile.update({k: v for k, v in data.items() if v and k in profile})
        except Exception:
            pass

    # 2. Query RAG for travel-related memories
    rag = get_service("rag")
    if rag and rag.is_initialized():
        try:
            results = await rag.search(
                user_id,
                "travel preferences vacation trip hotel food activities hobbies",
                limit=5,
            )
            if results and isinstance(results, list):
                rag_texts = [r.get("content", r.get("text", "")) for r in results[:5]]
                profile["_rag_context"] = " | ".join(t[:150] for t in rag_texts if t)
        except Exception:
            pass

    return profile


def build_preference_questions(
    profile: Dict[str, Any], destination: str, duration_days: int
) -> str:
    """
    Build 3-4 targeted questions based on what we DON'T know yet.

    If RAG already tells us the user likes adventure and seafood,
    we skip those questions and only ask what's missing.
    """
    questions = []

    if not profile.get("travel_companion"):
        questions.append("Are you traveling solo, as a couple, with family, or in a group?")

    if not profile.get("travel_style") and not profile.get("interests"):
        questions.append(
            f"For {destination}, do you prefer a more relaxed vibe (beaches, spa, gastronomy) "
            "or adventurous (trekking, diving, extreme sports)? Or a mix of both?"
        )

    if not profile.get("budget_level"):
        questions.append(
            "What's your budget style — backpacker/budget, comfortable mid-range, or luxury/splurge?"
        )

    # Always ask this — it's specific to the destination
    if duration_days >= 7:
        questions.append(
            f"Any specific cities or regions in {destination} you already know you want to visit, "
            "or should I surprise you with my suggestions?"
        )

    # Max 4 questions
    return questions[:4]


async def build_itinerary(
    user_id: str,
    destination: str,
    start_date: str,
    end_date: str,
    duration_days: int,
    user_name: str = "",
    preferences: Dict[str, Any] = None,
    profile: Dict[str, Any] = None,
) -> Optional[Dict[str, Any]]:
    """
    Build a complete personalized travel itinerary.

    Combines:
    - User preferences (from questions)
    - User profile (from RAG)
    - Research (via Perplexity)
    - Weather data

    Returns humanized itinerary via GPT.
    """
    prefs = preferences or {}
    prof = profile or {}
    name = user_name.split()[0] if user_name else "traveler"

    # Build research query
    research_query = _build_research_query(destination, duration_days, prefs, prof)

    # Research via Perplexity
    research_result = ""
    perplexity = get_service("perplexity")
    if perplexity:
        try:
            await perplexity.initialize()
            result = await perplexity.search(query=research_query, model="sonar")
            research_result = result.get("answer", "")
        except Exception as e:
            logger.warning("Travel itinerary: Perplexity failed: {}", e)

    # Get weather forecast
    weather_info = ""
    weather_svc = get_service("weather")
    if weather_svc and weather_svc.is_initialized():
        try:
            import asyncio
            w = await asyncio.to_thread(weather_svc.get_current_weather, destination)
            if w and not isinstance(w, Exception):
                weather_info = f"Current weather in {destination}: {w.get('temperature', '?')}°C, {w.get('description', '')}"
        except Exception:
            pass

    # Build raw itinerary data
    raw_data = (
        f"Destination: {destination}\n"
        f"Dates: {start_date} to {end_date} ({duration_days} days)\n"
        f"Traveler: {name}\n"
        f"Companion: {prefs.get('companion', prof.get('travel_companion', 'not specified'))}\n"
        f"Style: {prefs.get('style', prof.get('travel_style', 'not specified'))}\n"
        f"Budget: {prefs.get('budget', prof.get('budget_level', 'not specified'))}\n"
        f"Interests: {prefs.get('interests', ', '.join(prof.get('interests', [])) or 'not specified')}\n"
        f"Specific cities: {prefs.get('cities', 'let me suggest')}\n"
        f"Food preferences: {', '.join(prof.get('food_prefs', [])) or 'not specified'}\n"
        f"Past trips: {', '.join(prof.get('past_trips', [])) or 'not specified'}\n"
        f"RAG context: {prof.get('_rag_context', 'none')}\n"
        f"Weather: {weather_info or 'unknown'}\n\n"
        f"RESEARCH RESULTS:\n{research_result[:3000]}"
    )

    # Humanize through GPT
    itinerary = await _humanize_itinerary(raw_data, name, destination, duration_days)

    # Save preferences for future trips
    await _save_travel_preferences(user_id, prefs, prof)

    # Store itinerary in proactivity_feed
    title = f"Travel plan: {destination} ({duration_days} days)"
    await _store_itinerary(user_id, title, itinerary, destination)

    return {
        "title": title,
        "itinerary": itinerary,
        "destination": destination,
        "duration_days": duration_days,
    }


def _build_research_query(
    destination: str, duration_days: int,
    prefs: Dict[str, Any], profile: Dict[str, Any],
) -> str:
    """Build a detailed Perplexity query for trip research."""
    style = prefs.get("style", profile.get("travel_style", "mixed"))
    companion = prefs.get("companion", profile.get("travel_companion", ""))
    budget = prefs.get("budget", profile.get("budget_level", "mid-range"))
    cities = prefs.get("cities", "")
    interests = prefs.get("interests", ", ".join(profile.get("interests", [])))

    weeks = max(1, duration_days // 7)

    query = (
        f"Create a detailed {duration_days}-day travel itinerary for {destination}. "
        f"Split into {weeks} week(s) by region/city. "
    )

    if cities:
        query += f"Must include: {cities}. "
    if style:
        query += f"Style: {style}. "
    if companion:
        query += f"Traveling: {companion}. "
    if budget:
        query += f"Budget: {budget}. "
    if interests:
        query += f"Interests: {interests}. "

    query += (
        "For each city/region include: top attractions (include hidden gems), "
        "best restaurants (local authentic food), nightlife if relevant, "
        "activities with estimated prices, accommodation suggestions, "
        "transportation between cities, practical tips. "
        "Be specific with names and prices."
    )

    return query


async def _humanize_itinerary(
    raw_data: str, name: str, destination: str, duration_days: int,
) -> str:
    """Pass raw itinerary through GPT for warm, friend-like writing."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a personal AI assistant who LOVES travel. Create a travel itinerary for {name} going to {destination} for {duration_days} days.

RULES:
- Write like a friend who's been there and is excited to share their favorite spots
- Structure by WEEK or by CITY (whichever makes more sense for the destination)
- For each city/region include:
  • Best attractions (mix tourist must-sees + hidden gems locals love)
  • Restaurant recommendations (with cuisine type and price range)
  • Activities based on their style preferences
  • Practical tips (transport, money, cultural etiquette)
- Use emojis naturally to mark sections (🏛️ culture, 🍜 food, 🌊 beach, 🎉 nightlife, etc.)
- Be specific: real names of places, real price estimates, real transport options
- Include "Pro tip:" sections with insider knowledge
- End each day/section with a personality touch ("Trust me, the sunset here is worth the hike")
- Keep it readable on mobile — not too dense, good spacing
- Maximum ~50 lines (they can ask for more detail on specific parts)
- End with: "Want me to detail any specific day, or adjust anything?"

TRAVELER DATA:
{raw_data}

Generate the personalized itinerary:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=2000,
                temperature=0.85,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 50:
                return text
        except Exception as e:
            logger.warning("Travel itinerary: GPT humanization failed: {}", e)

    # Fallback
    return (
        f"✈️ **Your {destination} Trip Plan ({duration_days} days)**\n\n"
        f"Hey {name}! I researched everything for your trip. "
        f"Here's what I found:\n\n{raw_data[:2000]}\n\n"
        f"💬 Want me to adjust or detail any part?"
    )


async def _save_travel_preferences(
    user_id: str, prefs: Dict[str, Any], profile: Dict[str, Any],
) -> None:
    """Save learned travel preferences for future trips."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    # Merge new prefs with existing profile
    merged = {k: v for k, v in profile.items() if v and not k.startswith("_")}
    if prefs.get("companion"):
        merged["travel_companion"] = prefs["companion"]
    if prefs.get("style"):
        merged["travel_style"] = prefs["style"]
    if prefs.get("budget"):
        merged["budget_level"] = prefs["budget"]

    if not merged:
        return

    try:
        import json as _json
        client = db.get_client()
        client.table("user_context").upsert(
            {
                "user_id": user_id,
                "context_type": "travel_preferences",
                "context_data": _json.dumps(merged),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,context_type",
        ).execute()
    except Exception as e:
        logger.warning("Travel: save prefs failed: {}", e)


async def _store_itinerary(
    user_id: str, title: str, itinerary: str, destination: str,
) -> None:
    """Store itinerary in proactivity_feed."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        import json as _json
        client = db.get_client()
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "travel_itinerary",
            "title": title,
            "message": itinerary[:5000],  # Supabase text limit safety
            "metadata": _json.dumps({"destination": destination}),
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("Travel: store itinerary failed: {}", e)


# ===========================================================================
# PHASE 3 — Presentation + Approval + Final Document
# ===========================================================================

async def generate_trip_summary(
    itinerary: str,
    destination: str,
    duration_days: int,
    user_name: str = "",
) -> str:
    """
    Generate a brief, exciting summary of the itinerary for first presentation.

    Instead of dumping the full 50-line itinerary, we show a teaser:
    cities covered, highlights, and ask if they want the full plan.
    """
    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX. Summarize this travel itinerary for {name} in a SHORT, exciting teaser message.

RULES:
- Max 8 lines
- Mention the main cities/regions and how many days in each
- Pick 2-3 highlights that will excite them ("...including that rooftop bar with skyline views")
- Be enthusiastic! This is their trip!
- End with: "Want me to show the full day-by-day plan, or adjust anything first?"
- Use 3-4 emojis naturally
- Sound like a friend presenting their surprise gift

FULL ITINERARY:
{itinerary[:3000]}

DESTINATION: {destination}
DURATION: {duration_days} days
USER: {name}

Generate the teaser summary:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=400,
                temperature=0.85,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception as e:
            logger.warning("Trip summary: GPT failed: {}", e)

    # Fallback
    return (
        f"🗺️ {name}, your **{destination}** plan is ready! "
        f"I've mapped out {duration_days} amazing days for you.\n\n"
        f"Want me to show the full day-by-day plan, or adjust anything first?"
    )


async def adjust_itinerary(
    user_id: str,
    current_itinerary: str,
    user_feedback: str,
    destination: str,
    duration_days: int,
    user_name: str = "",
) -> Dict[str, Any]:
    """
    Adjust the itinerary based on user feedback.

    User might say:
    - "Swap Chiang Mai for Pai"
    - "Add more beach time"
    - "I want fewer restaurants and more adventure"
    - "Can we skip the temples?"

    Returns the adjusted itinerary, humanized through GPT.
    """
    name = user_name.split()[0] if user_name else "traveler"
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a travel-loving AI. {name} asked you to adjust their {destination} trip plan.

THEIR FEEDBACK: "{user_feedback}"

CURRENT ITINERARY:
{current_itinerary[:3000]}

RULES:
- Apply the requested changes while keeping the overall structure
- If they want to swap a city, research the replacement and fill in details
- If they want more of something (beaches, food, adventure), redistribute days
- Keep the same warm, friend-like writing style
- Mention what you changed: "I swapped Chiang Mai for Pai like you asked — great choice!"
- Keep all practical info (transport, prices, tips)
- End with "How does this look now? Anything else you'd like to tweak?"
- Max ~50 lines

Generate the adjusted itinerary:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=2000,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 50:
                # Store the updated itinerary
                title = f"Travel plan (updated): {destination}"
                await _store_itinerary(user_id, title, text, destination)
                return {"itinerary": text, "adjusted": True}
        except Exception as e:
            logger.warning("Trip adjust: GPT failed: {}", e)

    # Fallback
    return {
        "itinerary": (
            f"I noted your feedback: \"{user_feedback}\"\n\n"
            f"Let me research this adjustment and update your {destination} plan. "
            f"Give me a moment! 🔄"
        ),
        "adjusted": False,
    }


async def finalize_itinerary(
    user_id: str,
    itinerary: str,
    destination: str,
    duration_days: int,
    user_name: str = "",
) -> Dict[str, Any]:
    """
    User approved the itinerary. Generate final formatted document and save to notes.

    Returns the final document text + confirmation message.
    """
    name = user_name.split()[0] if user_name else "traveler"
    openai_svc = get_service("openai")

    # Generate a polished final document
    final_doc = itinerary  # Start with current version

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX. {name} approved their {destination} trip plan. Create the FINAL polished version.

APPROVED ITINERARY:
{itinerary[:4000]}

RULES:
- Clean up formatting for a final document
- Add a warm header: "🗺️ {name}'s {destination} Adventure — {duration_days} Days"
- Organize by day/week with clear headers
- Include all practical info (transport, prices, tips)
- Add a "Packing Essentials" section at the end (3-5 items based on destination/activities)
- Add a "Useful Phrases" section if the destination speaks a different language (5 phrases max)
- Add "Emergency Info" (embassy number, local emergency number)
- End with a warm send-off: "Have an incredible trip, {name}! 🌍✈️"
- Keep it readable and well-structured

Generate the final travel document:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=2500,
                temperature=0.7,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 50:
                final_doc = text
        except Exception as e:
            logger.warning("Trip finalize: GPT failed: {}", e)

    # Save to notes
    await _save_to_notes(user_id, destination, duration_days, final_doc)

    # Store final version in proactivity_feed
    title = f"✅ Final plan: {destination} ({duration_days} days)"
    await _store_itinerary(user_id, title, final_doc, destination)

    # Confirmation message
    confirmation = await _humanize_confirmation(name, destination, duration_days)

    return {
        "document": final_doc,
        "confirmation": confirmation,
        "destination": destination,
    }


async def _save_to_notes(
    user_id: str, destination: str, duration_days: int, content: str,
) -> None:
    """Save the final itinerary to the user's notes."""
    notes_svc = get_service("notes")
    if notes_svc and notes_svc.is_initialized():
        try:
            await notes_svc.create_note(
                user_id=user_id,
                title=f"Travel Plan: {destination} ({duration_days} days)",
                content=content,
                tags=["travel", destination.lower().replace(" ", "-")],
            )
            logger.info("Travel: saved final itinerary to notes for user={}", user_id[:8])
        except Exception as e:
            logger.warning("Travel: save to notes failed: {}", e)

    # Also save to user_context as last itinerary
    db = get_service("database")
    if db and db.is_initialized():
        try:
            import json as _json
            client = db.get_client()
            client.table("user_context").upsert(
                {
                    "user_id": user_id,
                    "context_type": "last_travel_itinerary",
                    "context_data": _json.dumps({
                        "destination": destination,
                        "duration_days": duration_days,
                        "content": content[:5000],
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                on_conflict="user_id,context_type",
            ).execute()
        except Exception as e:
            logger.warning("Travel: save to user_context failed: {}", e)


async def _humanize_confirmation(name: str, destination: str, duration_days: int) -> str:
    """Generate a warm confirmation message after user approves the plan."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX. {name} just approved their {destination} trip plan ({duration_days} days). Generate a SHORT, warm confirmation.

RULES:
- Max 4 lines
- Be genuinely excited for them
- Mention you saved it to their notes
- Tease Phase 4: "I'll send you reminders before each city change during the trip"
- Use 2-3 travel emojis

Generate:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=200,
                temperature=0.85,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 10:
                return text
        except Exception as e:
            logger.warning("Trip confirm: GPT failed: {}", e)

    # Fallback
    return (
        f"✅ Your **{destination}** plan is saved to your notes, {name}! 🗺️\n\n"
        f"I'll send you reminders before each city change during the trip. "
        f"Have an incredible time! ✈️🌴"
    )


# ===========================================================================
# PHASE 3 — Conversation Session Manager
# ===========================================================================
# Tracks the state of a travel planning conversation so the bot knows
# where we are in the flow: detecting → asking questions → building → reviewing.

PLANNING_STATES = {
    "detected": "Trip detected, waiting for user confirmation",
    "gathering": "Asking preference questions",
    "building": "Building itinerary (research in progress)",
    "reviewing": "Itinerary presented, waiting for feedback",
    "adjusting": "User requested changes",
    "finalized": "User approved, plan saved",
}


async def get_planning_session(user_id: str) -> Optional[Dict[str, Any]]:
    """Get active travel planning session for user, or None."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return None

    try:
        import json as _json
        client = db.get_client()
        result = (
            client.table("user_context")
            .select("context_data")
            .eq("user_id", user_id)
            .eq("context_type", "travel_planning_session")
            .limit(1)
            .execute()
        )
        if result.data:
            data = result.data[0].get("context_data", {})
            if isinstance(data, str):
                data = _json.loads(data)
            # Check if session is still active (not finalized/expired)
            if data.get("state") in ("detected", "gathering", "building", "reviewing", "adjusting"):
                return data
    except Exception:
        pass
    return None


async def save_planning_session(user_id: str, session: Dict[str, Any]) -> None:
    """Save/update travel planning session."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        import json as _json
        client = db.get_client()
        client.table("user_context").upsert(
            {
                "user_id": user_id,
                "context_type": "travel_planning_session",
                "context_data": _json.dumps(session),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,context_type",
        ).execute()
    except Exception as e:
        logger.warning("Travel session save failed: {}", e)


async def handle_travel_planning_message(
    user_id: str,
    message: str,
    user_name: str = "",
) -> Optional[str]:
    """
    Process a user message in the context of travel planning.

    This is the main conversational handler. Called by the travel agent
    when it detects an active planning session.

    Returns:
        Response text to send to user, or None if not a planning message.
    """
    session = await get_planning_session(user_id)
    if not session:
        return None

    state = session.get("state", "")
    name = user_name.split()[0] if user_name else "there"

    # ── STATE: detected — user responding to trip detection ──
    if state == "detected":
        msg_lower = message.lower()
        # Check if user says YES
        yes_words = ["sim", "yes", "yeah", "sure", "claro", "bora", "vamos",
                     "plan", "planeia", "organiza", "quero", "lets go", "please"]
        no_words = ["não", "no", "nao", "skip", "depois", "later", "not now"]

        if any(w in msg_lower for w in no_words):
            session["state"] = "finalized"  # Mark as done
            await save_planning_session(user_id, session)
            return f"No worries, {name}! If you change your mind later, just say 'plan my trip to {session.get('destination', 'your destination')}' and I'll be ready. Have a great trip! ✈️"

        if any(w in msg_lower for w in yes_words):
            # Move to gathering state
            profile = await gather_travel_profile(user_id)
            questions = build_preference_questions(
                profile, session.get("destination", ""), session.get("duration_days", 7),
            )

            session["state"] = "gathering"
            session["profile"] = {k: v for k, v in profile.items() if not k.startswith("_")}
            session["rag_context"] = profile.get("_rag_context", "")
            session["questions"] = questions
            session["answers"] = {}
            session["current_question"] = 0
            await save_planning_session(user_id, session)

            # Ask first question (humanized)
            return await _humanize_question(questions[0], name, session.get("destination", ""))

        return None  # Not a planning response

    # ── STATE: gathering — collecting answers to preference questions ──
    if state == "gathering":
        questions = session.get("questions", [])
        current_q = session.get("current_question", 0)

        # Store the answer
        session["answers"][f"q{current_q}"] = message
        session["current_question"] = current_q + 1
        await save_planning_session(user_id, session)

        # More questions?
        if current_q + 1 < len(questions):
            next_q = questions[current_q + 1]
            return await _humanize_question(next_q, name, session.get("destination", ""))

        # All questions answered — build itinerary!
        session["state"] = "building"
        await save_planning_session(user_id, session)

        # Parse answers into preferences
        prefs = _parse_answers(session.get("answers", {}), questions)

        # Build the itinerary
        result = await build_itinerary(
            user_id=user_id,
            destination=session.get("destination", ""),
            start_date=session.get("start_date", ""),
            end_date=session.get("end_date", ""),
            duration_days=session.get("duration_days", 7),
            user_name=user_name,
            preferences=prefs,
            profile=session.get("profile", {}),
        )

        if result:
            session["state"] = "reviewing"
            session["itinerary"] = result.get("itinerary", "")[:5000]
            await save_planning_session(user_id, session)

            # Present summary (teaser, not full plan)
            summary = await generate_trip_summary(
                result["itinerary"],
                session.get("destination", ""),
                session.get("duration_days", 7),
                user_name,
            )
            return summary

        return f"I'm having trouble building the itinerary right now, {name}. Let me try again in a moment! 🔄"

    # ── STATE: reviewing — user reviewing the itinerary ──
    if state == "reviewing":
        msg_lower = message.lower()

        # User wants full plan
        full_words = ["full", "completo", "todo", "day by day", "dia a dia",
                      "show me", "mostra", "ver tudo", "details", "detalhes"]
        if any(w in msg_lower for w in full_words):
            return session.get("itinerary", "No itinerary available.")

        # User approves
        approve_words = ["perfect", "perfeito", "love it", "adorei", "approve",
                         "aprovo", "looks great", "save", "guarda", "finaliz",
                         "ótimo", "excelente", "top"]
        if any(w in msg_lower for w in approve_words):
            result = await finalize_itinerary(
                user_id=user_id,
                itinerary=session.get("itinerary", ""),
                destination=session.get("destination", ""),
                duration_days=session.get("duration_days", 7),
                user_name=user_name,
            )
            session["state"] = "finalized"
            await save_planning_session(user_id, session)
            return result.get("confirmation", f"Your plan is saved, {name}! ✈️")

        # User wants changes — treat as adjustment
        session["state"] = "adjusting"
        await save_planning_session(user_id, session)
        result = await adjust_itinerary(
            user_id=user_id,
            current_itinerary=session.get("itinerary", ""),
            user_feedback=message,
            destination=session.get("destination", ""),
            duration_days=session.get("duration_days", 7),
            user_name=user_name,
        )

        if result.get("adjusted"):
            session["state"] = "reviewing"
            session["itinerary"] = result["itinerary"][:5000]
            await save_planning_session(user_id, session)

        return result.get("itinerary", "Let me adjust that for you...")

    # ── STATE: adjusting — same as reviewing after adjustment ──
    if state == "adjusting":
        # Re-route to reviewing state
        session["state"] = "reviewing"
        await save_planning_session(user_id, session)
        return await handle_travel_planning_message(user_id, message, user_name)

    return None


async def start_planning_session(
    user_id: str, trip: Dict[str, Any],
) -> None:
    """Start a new travel planning session from a detected trip."""
    session = {
        "state": "detected",
        "destination": trip.get("destination", ""),
        "start_date": trip.get("start_date", ""),
        "end_date": trip.get("end_date", ""),
        "duration_days": trip.get("duration_days", 0),
        "event_id": trip.get("event_id", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await save_planning_session(user_id, session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _humanize_question(question: str, name: str, destination: str) -> str:
    """Wrap a preference question in warm, conversational language."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, excited to plan {name}'s trip to {destination}. Rewrite this question in a warm, conversational way.

ORIGINAL QUESTION: {question}

RULES:
- Be casual and friendly
- Add 1 emoji
- Max 2-3 lines
- Sound like a friend who loves planning trips
- Don't change the core question, just make it warmer

Rewrite:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=100,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 10:
                return text
        except Exception:
            pass

    return f"🌍 {question}"


def _parse_answers(
    answers: Dict[str, str], questions: List[str],
) -> Dict[str, str]:
    """Parse user's answers into structured preferences."""
    prefs: Dict[str, str] = {}

    for key, answer in answers.items():
        answer_lower = answer.lower()

        # Detect companion
        if "solo" in answer_lower or "sozinho" in answer_lower:
            prefs["companion"] = "solo"
        elif "couple" in answer_lower or "casal" in answer_lower or "namorad" in answer_lower:
            prefs["companion"] = "couple"
        elif "famil" in answer_lower or "filh" in answer_lower or "kids" in answer_lower:
            prefs["companion"] = "family"
        elif "group" in answer_lower or "grupo" in answer_lower or "amigos" in answer_lower:
            prefs["companion"] = "group"

        # Detect style
        if "relax" in answer_lower or "praia" in answer_lower or "beach" in answer_lower or "spa" in answer_lower:
            prefs["style"] = "relaxed"
        elif "adventure" in answer_lower or "aventur" in answer_lower or "trek" in answer_lower or "diving" in answer_lower:
            prefs["style"] = "adventurous"
        elif "cultur" in answer_lower or "museum" in answer_lower or "museu" in answer_lower or "histor" in answer_lower:
            prefs["style"] = "cultural"
        elif "mix" in answer_lower or "both" in answer_lower or "ambos" in answer_lower:
            prefs["style"] = "mixed"

        # Detect budget
        if "budget" in answer_lower or "barato" in answer_lower or "backpack" in answer_lower or "mochil" in answer_lower:
            prefs["budget"] = "budget"
        elif "luxury" in answer_lower or "luxo" in answer_lower or "splurge" in answer_lower or "5 star" in answer_lower:
            prefs["budget"] = "luxury"
        elif "mid" in answer_lower or "comfort" in answer_lower or "confort" in answer_lower or "médio" in answer_lower:
            prefs["budget"] = "mid-range"

        # Detect specific cities (last question usually)
        if any(dest in answer_lower for dest in MAJOR_DESTINATIONS):
            prefs["cities"] = answer

        # Catch-all: store interests from longer answers
        if len(answer) > 20 and "interests" not in prefs:
            prefs["interests"] = answer

    return prefs

