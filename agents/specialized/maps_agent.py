# -*- coding: utf-8 -*-
"""
agents/specialized/maps_agent.py
================================
Maps Agent — directions, places search, nearby POIs.

Uses MapsService for Google Maps integration.
Intent classification via GPT for accurate routing.

Examples:
  - "como chegar de Dublin a Cork de carro"
  - "directions from home to airport walking"
  - "farmácia perto de mim"
  - "postos de gasolina perto de Swords"
  - "hospital mais perto"
  - "o que tem perto de Connolly Station"
  - "detalhes sobre O'Connell Pharmacy Dublin"
"""

import json
import re
from typing import Any, Dict, List

from agents.core import AgentResponse, AgentStatus, BaseAgent, register_agent
from services import get_service
from services.i18n import get_user_lang, t

# ── Intent patterns (regex fallback if GPT unavailable) ────────────────
_RE_DIRECTIONS = re.compile(
    r"(?:como\s+(?:ir|chegar)|directions?|rota|route|navega[rç]|"
    r"cómo\s+(?:ir|llegar)|caminho|ir\s+de|de\s+.+?\s+(?:a|para|to|até)\s+)"
    r"\s*(.+)",
    re.IGNORECASE,
)

_RE_NEARBY = re.compile(
    r"(?:perto\s+de|near(?:by)?|próximo\s+(?:a|de)?|cerca\s+de|"
    r"o\s+que\s+(?:tem|há)\s+perto|what'?s?\s+near)"
    r"\s*(.*)",
    re.IGNORECASE,
)

_RE_SEARCH_PLACE = re.compile(
    r"(?:busca[r]?|find|search|procura[r]?|onde\s+(?:fica|tem|é)|"
    r"dónde\s+(?:está|hay|queda))\s+(.+)",
    re.IGNORECASE,
)

# GPT prompt for intent classification
MAPS_INTENT_PROMPT = """You are a maps/navigation assistant.
Analyze the user's message and determine the intent.

Return a JSON object with:
- "action": one of "directions", "search_place", "nearby", "place_details"
- "origin": starting point (for directions; empty string if not mentioned)
- "destination": end point (for directions) or search query (for search/nearby)
- "mode": travel mode if mentioned ("drive", "walk", "bike", "transit") — default ""
- "query": the search query for places (for search_place/nearby)
- "place_type": Google place type if identifiable (e.g. "pharmacy", "gas_station", \
"hospital", "supermarket", "restaurant", "parking", "ev_charging_station", \
"bank", "atm", "post_office", "police", "fire_station", "school", "gym", \
"shopping_mall", "movie_theater", "park", "church", "mosque", "synagogue")
- "location_context": any location mentioned for nearby/search (e.g. "Dublin", "Swords")
- "language": detected language ("pt", "en", "es")

Examples:
- "como chegar de casa ao aeroporto de carro" -> \
{{"action": "directions", "origin": "casa", "destination": "aeroporto", \
"mode": "drive", "query": "", "place_type": "", "location_context": "", "language": "pt"}}
- "directions from Connolly to Heuston walking" -> \
{{"action": "directions", "origin": "Connolly Station Dublin", \
"destination": "Heuston Station Dublin", "mode": "walk", \
"query": "", "place_type": "", "location_context": "", "language": "en"}}
- "farmácia perto de Swords" -> \
{{"action": "nearby", "origin": "", "destination": "", "mode": "", \
"query": "farmácia perto de Swords", "place_type": "pharmacy", \
"location_context": "Swords", "language": "pt"}}
- "posto de gasolina mais perto" -> \
{{"action": "nearby", "origin": "", "destination": "", "mode": "", \
"query": "posto de gasolina", "place_type": "gas_station", \
"location_context": "", "language": "pt"}}
- "find a gym near Dublin city centre" -> \
{{"action": "search_place", "origin": "", "destination": "", "mode": "", \
"query": "gym near Dublin city centre", "place_type": "gym", \
"location_context": "Dublin city centre", "language": "en"}}
- "o que tem perto da Connolly Station" -> \
{{"action": "nearby", "origin": "", "destination": "", "mode": "", \
"query": "pontos de interesse perto da Connolly Station", "place_type": "", \
"location_context": "Connolly Station Dublin", "language": "pt"}}

User message: {message}
Respond ONLY with JSON, no markdown."""

# Common POI types for generic "what's nearby" queries
_GENERIC_NEARBY_TYPES = [
    "restaurant",
    "cafe",
    "pharmacy",
    "supermarket",
    "gas_station",
    "bank",
    "park",
]


def _is_generic_nearby_query(query: str) -> bool:
    """Check if the query is a generic 'what's nearby' without a specific type."""
    generic_patterns = [
        "o que tem perto",
        "o que há perto",
        "o que ha perto",
        "que tem perto",
        "whats near",
        "what's near",
        "what is near",
        "nearby",
        "perto de mim",
        "near me",
        "que hay cerca",
        "qué hay cerca",
        "pontos de interesse",
        "places of interest",
    ]
    lower = query.lower()
    return any(p in lower for p in generic_patterns)


@register_agent("maps")
class MapsAgent(BaseAgent):
    """
    Maps agent — directions, places search, nearby POIs.

    Intents:
    - directions: step-by-step route between two places
    - search_place: find a specific place or type of place
    - nearby: find places near a location
    - place_details: get details about a specific place
    """

    def __init__(self) -> None:
        super().__init__(
            name="maps",
            description=(
                "Directions, routes, places search, nearby POIs "
                "via Google Maps. Supports drive, walk, bike, transit."
            ),
        )

    async def execute(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        """Route user request to appropriate maps action."""
        lang = get_user_lang(context)

        try:
            maps_svc = get_service("maps")
            if not maps_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("maps_service_unavailable", lang=lang),
                    error="MapsService not found",
                )
            if not maps_svc.is_initialized():
                await maps_svc.initialize()

            # Classify intent
            intent = await self._classify_intent(prompt)
            action = intent.get("action", "search_place")

            if action == "directions":
                return await self._handle_directions(
                    maps_svc, intent, context, lang
                )
            elif action == "nearby":
                return await self._handle_nearby(
                    maps_svc, intent, context, lang
                )
            elif action == "place_details":
                return await self._handle_place_details(
                    maps_svc, intent, lang
                )
            else:  # search_place or fallback
                return await self._handle_search(
                    maps_svc, intent, context, lang
                )

        except Exception as e:
            self.logger.error("MapsAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("maps_error", lang=lang),
                error=str(e),
            )

    def get_capabilities(self) -> List[str]:
        return [
            "directions",
            "places_search",
            "nearby_search",
            "place_details",
            "reverse_geocode",
        ]

    # ── Intent Classification ─────────────────────────────────────────

    async def _classify_intent(self, message: str) -> Dict[str, Any]:
        """Classify maps intent via GPT, with regex fallback."""
        openai = get_service("openai")
        if openai and openai.is_initialized():
            try:
                filled = MAPS_INTENT_PROMPT.replace("{message}", message)
                resp = await openai.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": filled}],
                    response_format={"type": "json_object"},
                    max_completion_tokens=250,
                    temperature=0.0,
                )
                text = resp.choices[0].message.content or ""
                return json.loads(text)
            except Exception as e:
                self.logger.warning(
                    "Maps intent classification failed: %s — using regex", e
                )

        # Regex fallback
        return self._regex_classify(message)

    def _regex_classify(self, text: str) -> Dict[str, Any]:
        """Regex-based intent classification (fallback)."""
        m = _RE_DIRECTIONS.search(text)
        if m:
            # Try to split "de X a/para Y"
            parts = re.split(
                r"\s+(?:a|para|to|até|toward)\s+",
                m.group(1),
                maxsplit=1,
            )
            origin = parts[0].strip() if len(parts) > 1 else ""
            destination = parts[-1].strip()
            return {
                "action": "directions",
                "origin": origin,
                "destination": destination,
                "mode": "",
                "query": "",
                "place_type": "",
                "location_context": "",
                "language": "pt",
            }

        m = _RE_NEARBY.search(text)
        if m:
            return {
                "action": "nearby",
                "query": text,
                "place_type": "",
                "location_context": m.group(1).strip() if m.group(1) else "",
                "origin": "",
                "destination": "",
                "mode": "",
                "language": "pt",
            }

        m = _RE_SEARCH_PLACE.search(text)
        if m:
            return {
                "action": "search_place",
                "query": m.group(1).strip(),
                "place_type": "",
                "location_context": "",
                "origin": "",
                "destination": "",
                "mode": "",
                "language": "pt",
            }

        return {
            "action": "search_place",
            "query": text,
            "place_type": "",
            "location_context": "",
            "origin": "",
            "destination": "",
            "mode": "",
            "language": "pt",
        }

    # ── Location Alias Resolution ─────────────────────────────────────

    async def _resolve_location_alias(
        self,
        text: str,
        user_id: str,
        lang: str,
    ):
        """
        Resolve a location alias to a saved address.

        Returns:
            tuple: (resolved_address: str | None, alias_key: str | None)
            - If alias found and saved: (address, key)
            - If alias found but NOT saved: (None, key)
            - If not an alias: (None, None)
        """
        from services.business.saved_locations_service import (
            get_saved_locations_service,
            resolve_alias,
        )

        key = resolve_alias(text)
        if not key:
            return None, None

        svc = get_saved_locations_service()
        location = await svc.get_location(user_id, key)
        if location and location.get("address"):
            return location["address"], key

        # Alias recognized but no saved address
        return None, key

    # ── Action Handlers ───────────────────────────────────────────────

    async def _handle_directions(
        self,
        svc: Any,
        intent: Dict,
        context: Dict,
        lang: str,
    ) -> AgentResponse:
        """Handle directions request — with location alias support."""
        origin = intent.get("origin", "")
        destination = intent.get("destination", "")
        mode = intent.get("mode", "drive") or "drive"
        user_id = context.get("user_id", "")

        # ── Resolve aliases for origin ────────────────────────────────
        if origin:
            resolved, alias_key = await self._resolve_location_alias(
                origin, str(user_id), lang
            )
            if resolved:
                origin = resolved
            elif alias_key:
                # Alias recognized but not saved — ask user
                from services.business.saved_locations_service import (
                    get_label,
                )

                label = get_label(alias_key, lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=t(
                        "maps_ask_save_location",
                        lang=lang,
                        alias=label,
                    ),
                    data={
                        "ask_location": alias_key,
                        "direction": "origin",
                    },
                )

        # ── Resolve aliases for destination ───────────────────────────
        if destination:
            resolved, alias_key = await self._resolve_location_alias(
                destination, str(user_id), lang
            )
            if resolved:
                destination = resolved
            elif alias_key:
                from services.business.saved_locations_service import (
                    get_label,
                )

                label = get_label(alias_key, lang)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=t(
                        "maps_ask_save_location",
                        lang=lang,
                        alias=label,
                    ),
                    data={
                        "ask_location": alias_key,
                        "direction": "destination",
                    },
                )

        # ── Fallback: user location / GPS coords ─────────────────────
        if not origin:
            origin = context.get("user_location", "")
        if not origin:
            lat = context.get("latitude")
            lng = context.get("longitude")
            if lat and lng:
                addr = await svc.reverse_geocode(float(lat), float(lng))
                if addr:
                    origin = addr
        if not destination:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("maps_need_destination", lang=lang),
                error="No destination provided",
            )
        if not origin:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("maps_need_location", lang=lang),
                data={"request_location": True},
            )

        result = await svc.get_directions(
            origin=origin,
            destination=destination,
            mode=mode,
        )

        if not result.get("success"):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=result.get("error", t("maps_error", lang=lang)),
                error=result.get("error", "directions failed"),
            )

        summary = result["summary"]
        steps = result["steps"]
        emoji = summary["mode_emoji"]

        # Build response
        lines = [
            f"{emoji} **{summary['origin']}** → **{summary['destination']}**",
            f"📏 {summary['distance']} · ⏱️ {summary['duration']} "
            f"({summary['mode_label']})",
            f"🕐 Chegada estimada: {summary['estimated_arrival']} UTC",
            "",
        ]

        # Show steps (max 15 to avoid message too long)
        if steps:
            lines.append(t("maps_steps_header", lang=lang))
            for i, step in enumerate(steps[:15], 1):
                instruction = step["instruction"]
                dist = step["distance"]

                # Transit step with line info
                transit_info = step.get("transit")
                if transit_info:
                    line_name = transit_info.get("line_name", "")
                    dep_stop = transit_info.get("departure_stop", "")
                    arr_stop = transit_info.get("arrival_stop", "")
                    num_stops = transit_info.get("num_stops", 0)
                    lines.append(
                        f"  {i}. 🚌 {line_name}: {dep_stop} → {arr_stop} "
                        f"({num_stops} stops)"
                    )
                else:
                    lines.append(f"  {i}. {instruction} ({dist})")

            if len(steps) > 15:
                remaining = len(steps) - 15
                lines.append(
                    f"  _...+{remaining} "
                    + t("maps_more_steps", lang=lang)
                    + "_"
                )

        text = "\n".join(lines)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data=result,
        )

    async def _handle_search(
        self,
        svc: Any,
        intent: Dict,
        context: Dict,
        lang: str,
    ) -> AgentResponse:
        """Handle places text search."""
        query = intent.get("query", "")
        location_ctx = intent.get("location_context", "")

        if not query:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("maps_need_query", lang=lang),
                error="No query provided",
            )

        # If location context, geocode it for bias
        location = None
        if location_ctx:
            location = await svc.geocode(location_ctx)

        result = await svc.search_places(
            query=query,
            location=location,
            max_results=5,
        )

        if not result.get("success") or not result.get("places"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("maps_no_results", lang=lang, query=query),
                data=result,
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_places_response(result["places"], query, lang),
            data=result,
        )

    async def _handle_nearby(
        self,
        svc: Any,
        intent: Dict,
        context: Dict,
        lang: str,
    ) -> AgentResponse:
        """Handle nearby search with diversified results for generic queries."""
        location_ctx = intent.get("location_context", "")
        place_type = intent.get("place_type", "")
        query = intent.get("query", "")

        # Get coordinates — from location context, user lat/lng, or user_location
        coords = None
        if location_ctx:
            coords = await svc.geocode(location_ctx)
        if not coords:
            lat = context.get("latitude")
            lng = context.get("longitude")
            if lat and lng:
                coords = {"latitude": float(lat), "longitude": float(lng)}
        if not coords:
            user_loc = context.get("user_location", "")
            if user_loc:
                coords = await svc.geocode(user_loc)

        # Generic nearby query (e.g. "o que tem perto") — diversified search
        if not place_type and _is_generic_nearby_query(query) and coords:
            result = await svc.nearby_search(
                latitude=coords["latitude"],
                longitude=coords["longitude"],
                included_types=_GENERIC_NEARBY_TYPES,
                max_results=8,
            )
        elif coords and place_type:
            result = await svc.nearby_search(
                latitude=coords["latitude"],
                longitude=coords["longitude"],
                included_types=[place_type],
                max_results=5,
            )
        else:
            # Fallback to text search with location bias
            search_query = query or place_type or "pontos de interesse"
            if location_ctx and location_ctx.lower() not in search_query.lower():
                search_query += f" em {location_ctx}"
            result = await svc.search_places(
                query=search_query,
                location=coords,
                max_results=5,
            )

        if not result.get("success") or not result.get("places"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("maps_no_results", lang=lang, query=query),
                data=result,
            )

        title = query or place_type or "Nearby"
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_places_response(
                result["places"], title, lang
            ),
            data=result,
        )

    async def _handle_place_details(
        self,
        svc: Any,
        intent: Dict,
        lang: str,
    ) -> AgentResponse:
        """Handle place details request."""
        # First search for the place to get its ID
        query = intent.get("query", "")
        if not query:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("maps_need_query", lang=lang),
                error="No query for place details",
            )

        search = await svc.search_places(query=query, max_results=1)
        if not search.get("success") or not search.get("places"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t("maps_no_results", lang=lang, query=query),
                data=search,
            )

        place_id = search["places"][0]["id"]
        result = await svc.get_place_details(place_id=f"places/{place_id}")

        if not result.get("success"):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("maps_error", lang=lang),
                error=result.get("error", "details failed"),
            )

        place = result["place"]
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=self._format_place_detail_response(place, lang),
            data=result,
        )

    # ── Response Formatters ───────────────────────────────────────────

    @staticmethod
    def _format_places_response(
        places: List[Dict], title: str, lang: str
    ) -> str:
        """Format a list of places for Telegram."""
        header = t("maps_results_header", lang=lang, query=title)
        lines = [header, ""]

        for i, p in enumerate(places, 1):
            name = p.get("name", "Unknown")
            address = p.get("address", "")
            rating = p.get("rating")
            rating_count = p.get("rating_count", 0)
            is_open = p.get("is_open")
            phone = p.get("phone", "")

            # Rating stars
            stars = ""
            if rating:
                full = int(rating)
                stars = "⭐" * full + f" {rating}"
                if rating_count:
                    stars += f" ({rating_count})"

            # Open status
            status_icon = ""
            if is_open is True:
                status_icon = " · 🟢 " + t("maps_open_now", lang=lang)
            elif is_open is False:
                status_icon = " · 🔴 " + t("maps_closed", lang=lang)

            line = f"**{i}. {name}**"
            if stars:
                line += f"\n   {stars}"
            if address:
                line += f"\n   📍 {address}"
            if phone:
                line += f"\n   📞 {phone}"
            if status_icon:
                line += status_icon

            lines.append(line)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_place_detail_response(place: Dict, lang: str) -> str:
        """Format detailed place info for Telegram."""
        name = place.get("name", "Unknown")
        lines = [f"📍 **{name}**", ""]

        if place.get("summary"):
            lines.append(f"_{place['summary']}_")
            lines.append("")

        if place.get("address"):
            lines.append(f"🏠 {place['address']}")
        if place.get("phone"):
            lines.append(f"📞 {place['phone']}")
        if place.get("rating"):
            stars = "⭐" * int(place["rating"])
            count = place.get("rating_count", 0)
            lines.append(f"{stars} {place['rating']} ({count} avaliações)")

        is_open = place.get("is_open")
        if is_open is True:
            lines.append(f"🟢 {t('maps_open_now', lang=lang)}")
        elif is_open is False:
            lines.append(f"🔴 {t('maps_closed', lang=lang)}")

        # Opening hours
        hours = place.get("weekday_hours", [])
        if hours:
            lines.append("")
            lines.append(f"🕐 {t('maps_opening_hours', lang=lang)}:")
            for h in hours:
                lines.append(f"  {h}")

        # Reviews
        reviews = place.get("reviews", [])
        if reviews:
            lines.append("")
            lines.append(f"💬 {t('maps_reviews', lang=lang)}:")
            for r in reviews:
                author = r.get("author", "")
                rating = r.get("rating", "")
                text = r.get("text", "")
                if text:
                    short = text[:120] + "..." if len(text) > 120 else text
                    lines.append(f'  ⭐{rating} _{author}_: "{short}"')

        # Links
        if place.get("website"):
            lines.append(f"\n🌐 [Website]({place['website']})")
        if place.get("google_maps_url"):
            lines.append(
                f"🗺️ [{t('maps_view_on_maps', lang=lang)}]"
                f"({place['google_maps_url']})"
            )

        return "\n".join(lines)

    # ── Save Location Response ─────────────────────────────────────────

    async def _handle_save_location_response(
        self,
        user_id: str,
        key: str,
        address: str,
        lang: str,
    ) -> AgentResponse:
        """Save a location and confirm to user."""
        from services.business.saved_locations_service import (
            get_saved_locations_service,
            get_label,
        )

        svc = get_saved_locations_service()
        location_data = await svc.save_location(
            str(user_id), key, address
        )
        label = get_label(key, lang)

        if location_data.get("latitude"):
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "maps_location_saved",
                    lang=lang,
                    alias=label,
                    address=address,
                ),
            )
        else:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "maps_location_saved_no_coords",
                    lang=lang,
                    alias=label,
                    address=address,
                ),
            )
