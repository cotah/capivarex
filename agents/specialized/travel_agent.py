"""
Travel Agent — Flight search/booking & hotel/stay search via Duffel API.

Handles:
- Flight search ("fly from Dublin to London on March 15")
- Hotel/stay search ("find hotel in Paris for 3 nights")
- Price comparison (returns top 5 cheapest options)
- Booking flow info (explains next steps)

Note: Actual booking (payment) requires user confirmation and is a future
enhancement. For now the agent searches and presents options.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.ai.model_config import DEFAULT_MODEL
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)


@register_agent("travel")
class TravelAgent(BaseAgent):
    """Travel agent for flights and accommodation via Duffel API."""

    def __init__(self):
        super().__init__(
            name="travel",
            description="Search flights and hotels/stays via Duffel API",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Process travel-related requests."""
        lang = get_user_lang(context)

        # Get Duffel service
        duffel = get_service("duffel")
        if not duffel:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("service_unavailable", lang=lang),
                error="Duffel service not available",
            )

        if not duffel.is_initialized():
            await duffel.initialize()

        # Use GPT to parse the travel intent
        intent = await self._parse_intent(prompt, context)

        if not intent:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=self._get_help_text(lang),
            )

        intent_type = intent.get("type", "unknown")

        try:
            if intent_type == "flight":
                return await self._handle_flight_search(duffel, intent, lang)
            elif intent_type == "stay":
                return await self._handle_stay_search(duffel, intent, context, lang)
            else:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=self._get_help_text(lang),
                )
        except Exception as e:
            self.logger.error("Travel agent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("error_processing", lang=lang),
                error=str(e),
            )

    # ------------------------------------------------------------------ #
    # Flight search                                                        #
    # ------------------------------------------------------------------ #

    async def _handle_flight_search(
        self, duffel, intent: Dict, lang: str
    ) -> AgentResponse:
        origin = intent.get("origin", "").upper()
        destination = intent.get("destination", "").upper()
        departure = intent.get("departure_date", "")
        return_date = intent.get("return_date")
        cabin = intent.get("cabin_class", "economy")
        passengers_count = intent.get("passengers", 1)

        if not origin or not destination or not departure:
            msg = (
                "I need more details to search flights. Please provide:\n"
                "• Origin (city or airport code)\n"
                "• Destination (city or airport code)\n"
                "• Departure date\n\n"
                'Example: "Fly from Dublin to London on April 15"'
                if lang == "en"
                else "Preciso de mais detalhes para buscar voos. Por favor forneça:\n"
                "• Origem (cidade ou código do aeroporto)\n"
                "• Destino (cidade ou código do aeroporto)\n"
                "• Data de partida\n\n"
                'Exemplo: "Voo de Lisboa para Londres em 15 de abril"'
            )
            return AgentResponse(status=AgentStatus.SUCCESS, response=msg)

        passengers = [{"type": "adult"} for _ in range(passengers_count)]

        result = await duffel.search_flights(
            origin=origin,
            destination=destination,
            departure_date=departure,
            return_date=return_date,
            passengers=passengers,
            cabin_class=cabin,
            max_results=5,
        )

        offers = result.get("offers", [])

        if not offers:
            msg = (
                f"No flights found from {origin} to {destination} on {departure}. "
                "Try different dates or nearby airports."
                if lang == "en"
                else f"Nenhum voo encontrado de {origin} para {destination} em {departure}. "
                "Tente datas diferentes ou aeroportos próximos."
            )
            return AgentResponse(status=AgentStatus.SUCCESS, response=msg)

        # Format results
        header = (
            f"✈️ **{result['total_found']} flights found** — showing top {len(offers)} cheapest:\n\n"
            if lang == "en"
            else f"✈️ **{result['total_found']} voos encontrados** — mostrando top {len(offers)} mais baratos:\n\n"
        )

        lines = [header]
        for i, offer in enumerate(offers, 1):
            lines.append(f"**Option {i}:**" if lang == "en" else f"**Opção {i}:**")
            lines.append(duffel.format_flight_offer(offer))
            lines.append("")

        footer = (
            "\n💡 Click the booking link on your preferred option to book directly "
            "with the airline. Prices shown are indicative and may vary on the airline's site."
            if lang == "en"
            else "\n💡 Clique no link de reserva na opção desejada para reservar "
            "diretamente com a companhia aérea. Preços indicativos, podem variar no site."
        )
        lines.append(footer)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={
                "offers": [
                    {
                        "id": o.get("id"),
                        "price": o.get("total_amount"),
                        "currency": o.get("total_currency"),
                        "airline": o.get("owner", {}).get("name"),
                    }
                    for o in offers
                ],
                "offer_request_id": result.get("offer_request_id"),
            },
        )

    # ------------------------------------------------------------------ #
    # Stay search                                                          #
    # ------------------------------------------------------------------ #

    async def _handle_stay_search(
        self, duffel, intent: Dict, context: Dict, lang: str
    ) -> AgentResponse:
        check_in = intent.get("check_in", "")
        check_out = intent.get("check_out", "")
        location_name = intent.get("location", "")
        lat = intent.get("latitude")
        lng = intent.get("longitude")
        rooms = intent.get("rooms", 1)
        guests_count = intent.get("guests", 1)

        # If no coordinates, try to use user's GPS or geocode
        if not lat or not lng:
            # Try user GPS from context
            lat = context.get("latitude")
            lng = context.get("longitude")

            if not lat or not lng:
                msg = (
                    "I need a location with coordinates to search stays. "
                    "Please include a city name or share your GPS location.\n\n"
                    'Example: "Find hotel in Paris from April 15 to April 18"'
                    if lang == "en"
                    else "Preciso de uma localização com coordenadas para buscar estadias. "
                    "Por favor inclua o nome da cidade ou compartilhe sua localização GPS.\n\n"
                    'Exemplo: "Encontrar hotel em Paris de 15 a 18 de abril"'
                )
                return AgentResponse(status=AgentStatus.SUCCESS, response=msg)

        if not check_in or not check_out:
            msg = (
                "I need check-in and check-out dates to search. "
                'Example: "Hotel in Dublin from March 20 to March 23"'
                if lang == "en"
                else "Preciso das datas de check-in e check-out. "
                'Exemplo: "Hotel em Dublin de 20 a 23 de março"'
            )
            return AgentResponse(status=AgentStatus.SUCCESS, response=msg)

        guests = [{"type": "adult"} for _ in range(guests_count)]

        results = await duffel.search_stays(
            latitude=float(lat),
            longitude=float(lng),
            check_in=check_in,
            check_out=check_out,
            guests=guests,
            rooms=rooms,
            max_results=5,
        )

        if not results:
            msg = (
                f"No accommodation found near {location_name or 'your location'} "
                f"for {check_in} to {check_out}. Try expanding dates or location."
                if lang == "en"
                else f"Nenhum alojamento encontrado perto de {location_name or 'sua localização'} "
                f"para {check_in} a {check_out}. Tente expandir datas ou localização."
            )
            return AgentResponse(status=AgentStatus.SUCCESS, response=msg)

        # Format results
        location_label = location_name or f"{lat},{lng}"
        header = (
            f"🏨 **{len(results)} stays found near {location_label}:**\n"
            f"📅 {check_in} → {check_out}\n\n"
            if lang == "en"
            else f"🏨 **{len(results)} estadias encontradas perto de {location_label}:**\n"
            f"📅 {check_in} → {check_out}\n\n"
        )

        lines = [header]
        for i, result in enumerate(results, 1):
            lines.append(f"**{i}.** {duffel.format_stay_result(result)}")
            lines.append("")

        footer = (
            "\n💡 Search for these hotels on [Booking.com](https://www.booking.com) "
            "or [Hotels.com](https://www.hotels.com) to book directly."
            if lang == "en"
            else "\n💡 Pesquise esses hotéis no [Booking.com](https://www.booking.com) "
            "ou [Hotels.com](https://www.hotels.com) para reservar diretamente."
        )
        lines.append(footer)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={
                "results": [
                    {
                        "id": r.get("id"),
                        "name": r.get("accommodation", {}).get("name"),
                        "price": r.get("cheapest_rate_total_amount"),
                        "currency": r.get("cheapest_rate_total_currency"),
                    }
                    for r in results
                ]
            },
        )

    # ------------------------------------------------------------------ #
    # Intent parsing with GPT                                              #
    # ------------------------------------------------------------------ #

    async def _parse_intent(
        self, prompt: str, context: Dict[str, Any]
    ) -> Optional[Dict]:
        """Use GPT to parse travel intent from natural language."""
        openai_svc = get_service("openai")
        if not openai_svc:
            return self._fallback_parse(prompt)

        await openai_svc.initialize()

        today = datetime.now().strftime("%Y-%m-%d")

        system_prompt = f"""You are a travel intent parser. Today is {today}.
Extract travel intent from the user message and return ONLY valid JSON, no markdown.

For FLIGHTS return:
{{"type":"flight","origin":"IATA","destination":"IATA","departure_date":"YYYY-MM-DD","return_date":"YYYY-MM-DD or null","cabin_class":"economy","passengers":1}}

For STAYS/HOTELS return:
{{"type":"stay","location":"city name","latitude":null,"longitude":null,"check_in":"YYYY-MM-DD","check_out":"YYYY-MM-DD","rooms":1,"guests":1}}

IATA codes: DUB=Dublin, LIS=Lisbon, LHR=London, CDG=Paris, JFK=New York, LAX=Los Angeles, GRU=São Paulo, etc.
For cities, use the main airport code. If unsure, use the city 3-letter code.

Coordinates for common cities:
Dublin: 53.3498,-6.2603 | London: 51.5074,-0.1278 | Paris: 48.8566,2.3522
New York: 40.7128,-74.0060 | São Paulo: -23.5505,-46.6333 | Lisbon: 38.7223,-9.1393

If "tomorrow", "next week", etc., calculate the actual date from today ({today}).
If duration like "3 nights" is given, calculate check_out from check_in.
If the request is unclear, return {{"type":"unknown"}}."""

        try:
            client = openai_svc.get_client()
            completion = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                max_completion_tokens=300,
            )
            text = (completion.choices[0].message.content or "").strip()
            # Clean markdown fences if present
            text = text.replace("```json", "").replace("```", "").strip()

            import json

            return json.loads(text)

        except Exception as e:
            self.logger.warning("GPT intent parsing failed: %s", e)
            return self._fallback_parse(prompt)

    def _fallback_parse(self, prompt: str) -> Optional[Dict]:
        """Basic regex fallback for intent parsing."""
        lower = prompt.lower()

        # Check if it's about flights or stays
        flight_words = ["flight", "fly", "voo", "voar", "avião", "airplane", "plane"]
        stay_words = [
            "hotel",
            "stay",
            "accommodation",
            "hostel",
            "alojamento",
            "estadia",
            "hospedagem",
        ]

        is_flight = any(w in lower for w in flight_words)
        is_stay = any(w in lower for w in stay_words)

        if is_flight:
            return {"type": "flight"}
        elif is_stay:
            return {"type": "stay"}

        return {"type": "unknown"}

    # ------------------------------------------------------------------ #
    # Help text                                                            #
    # ------------------------------------------------------------------ #

    def _get_help_text(self, lang: str) -> str:
        if lang == "en":
            return (
                "✈️🏨 **Travel Agent** — I can help you find flights and hotels!\n\n"
                "**Flights:**\n"
                '• "Find flights from Dublin to London on April 15"\n'
                '• "Round trip São Paulo to Lisbon, May 1 to May 15"\n'
                '• "Business class flights NYC to Paris next Friday"\n\n'
                "**Hotels/Stays:**\n"
                '• "Find hotel in Paris from April 15 to April 18"\n'
                '• "Hotels near Dublin for 3 nights starting March 20"\n\n'
                "Just tell me where and when! 🌍"
            )
        return (
            "✈️🏨 **Agente de Viagens** — Posso ajudar a encontrar voos e hotéis!\n\n"
            "**Voos:**\n"
            '• "Voos de Lisboa para Londres em 15 de abril"\n'
            '• "Ida e volta São Paulo para Dublin, 1 a 15 de maio"\n'
            '• "Voos business de Nova York para Paris na próxima sexta"\n\n'
            "**Hotéis/Estadias:**\n"
            '• "Hotel em Paris de 15 a 18 de abril"\n'
            '• "Hotéis perto de Dublin para 3 noites a partir de 20 de março"\n\n'
            "Diga-me onde e quando! 🌍"
        )

    def get_capabilities(self) -> List[str]:
        return [
            "flight_search",
            "hotel_search",
            "stay_search",
            "travel_booking",
            "price_comparison",
        ]
