# -*- coding: utf-8 -*-
"""
services/integrations/restaurant_service.py
=============================================
Concierge de Restaurantes via Google Places API (New).

Funcionalidades:
- Buscar restaurantes por localização + tipo de cozinha + raio
- Buscar por texto livre ("pizza perto de mim", "sushi Lisboa")
- Detalhes completos: rating, horário, telefone, website, reviews
- Filtros: aberto agora, rating mínimo, distância máxima
- Cache em memória (TTL 10 min — dados de restaurante mudam pouco)

Variável de ambiente necessária:
    GOOGLE_PLACES_API_KEY=AIzaSy...

Google Places API (New) docs:
    https://developers.google.com/maps/documentation/places/web-service/overview
"""

import os
import time
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, ServiceUnavailableError, register_service

load_dotenv()

# ── Constantes ────────────────────────────────────────────────────────────────
PLACES_BASE = "https://places.googleapis.com/v1"
CACHE_TTL = 600  # 10 minutos

# Tipos de cozinha mapeados para tipos do Google Places
CUISINE_MAP: Dict[str, str] = {
    # Português
    "pizza": "pizza_restaurant",
    "sushi": "sushi_restaurant",
    "japonês": "japanese_restaurant",
    "japones": "japanese_restaurant",
    "italiano": "italian_restaurant",
    "italiana": "italian_restaurant",
    "chinês": "chinese_restaurant",
    "chines": "chinese_restaurant",
    "mexicano": "mexican_restaurant",
    "mexicana": "mexican_restaurant",
    "brasileiro": "brazilian_restaurant",
    "brasileira": "brazilian_restaurant",
    "hamburguer": "hamburger_restaurant",
    "burger": "hamburger_restaurant",
    "frango": "chicken_restaurant",
    "frutos do mar": "seafood_restaurant",
    "peixe": "seafood_restaurant",
    "marisco": "seafood_restaurant",
    "vegetariano": "vegetarian_restaurant",
    "vegetariana": "vegetarian_restaurant",
    "vegano": "vegan_restaurant",
    "vegana": "vegan_restaurant",
    "indiano": "indian_restaurant",
    "tailandês": "thai_restaurant",
    "grego": "greek_restaurant",
    "árabe": "middle_eastern_restaurant",
    "arabe": "middle_eastern_restaurant",
    "fast food": "fast_food_restaurant",
    "churrasco": "barbecue_restaurant",
    "bbq": "barbecue_restaurant",
    "café": "cafe",
    "pastelaria": "bakery",
    "bar": "bar",
}

# Campos a pedir ao Places API (New) — só o necessário para reduzir custo
FIELDS_BASIC = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.currentOpeningHours",
        "places.primaryType",
        "places.types",
        "places.location",
        "places.nationalPhoneNumber",
        "places.websiteUri",
        "places.editorialSummary",
    ]
)

FIELDS_DETAIL = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "rating",
        "userRatingCount",
        "priceLevel",
        "currentOpeningHours",
        "regularOpeningHours",
        "primaryType",
        "nationalPhoneNumber",
        "internationalPhoneNumber",
        "websiteUri",
        "editorialSummary",
        "reviews",
        "photos",
        "location",
        "googleMapsUri",
        "delivery",
        "dineIn",
        "takeout",
        "reservable",
    ]
)

# Mapa de price level para texto
PRICE_LABELS = {
    "PRICE_LEVEL_FREE": "Grátis",
    "PRICE_LEVEL_INEXPENSIVE": "€",
    "PRICE_LEVEL_MODERATE": "€€",
    "PRICE_LEVEL_EXPENSIVE": "€€€",
    "PRICE_LEVEL_VERY_EXPENSIVE": "€€€€",
}


def _price_label(level: Optional[str]) -> str:
    return PRICE_LABELS.get(level or "", "N/D")


def _resolve_cuisine_type(query: str) -> Optional[str]:
    """Tenta mapear texto livre para um tipo do Google Places."""
    q = query.lower()
    for keyword, place_type in CUISINE_MAP.items():
        if keyword in q:
            return place_type
    return None


@register_service("restaurant")
class RestaurantService(BaseService):
    """
    Serviço de restaurantes via Google Places API (New).

    Interface pública:
        search_nearby(lat, lng, query?, cuisine?, radius?, min_rating?, open_now?)
            → List[Dict]  — top restaurantes próximos

        search_by_text(text, location_bias?)
            → List[Dict]  — busca por texto livre

        get_details(place_id)
            → Dict        — detalhes completos (horário, telefone, reviews)

        format_restaurant(place)
            → str         — texto formatado para Telegram
    """

    def __init__(self):
        super().__init__(name="restaurant")
        self._api_key: Optional[str] = None
        self._cache: Dict[str, Dict] = {}

    async def _initialize(self) -> None:
        self._api_key = os.getenv("GOOGLE_PLACES_API_KEY")
        if not self._api_key:
            raise ServiceUnavailableError(
                "GOOGLE_PLACES_API_KEY não encontrada nas variáveis de ambiente."
            )
        self.logger.info("RestaurantService initialized (Google Places API New)")

    async def _health_check(self) -> bool:
        return bool(self._api_key)

    def _headers(self, fields: str) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": fields,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def search_nearby(
        self,
        lat: float,
        lng: float,
        query: Optional[str] = None,
        cuisine: Optional[str] = None,
        radius: int = 1500,
        min_rating: float = 0.0,
        open_now: bool = False,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Busca restaurantes próximos a uma localização.

        Args:
            lat, lng:     Coordenadas do utilizador
            query:        Texto livre opcional ("pizza", "sushi barato")
            cuisine:      Tipo de cozinha (sobrepõe query para o tipo)
            radius:       Raio em metros (max 50000)
            min_rating:   Rating mínimo (0.0–5.0)
            open_now:     Se True, apenas restaurantes abertos agora
            max_results:  Máximo de resultados (max 20)

        Returns:
            Lista de restaurantes formatados
        """
        if not self.is_initialized():
            await self.initialize()

        cache_key = f"nearby:{lat:.4f}:{lng:.4f}:{query}:{cuisine}:{radius}:{open_now}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        # Resolve tipo de cozinha
        place_type = cuisine or (_resolve_cuisine_type(query) if query else None)

        payload: Dict[str, Any] = {
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": min(radius, 50000),
                }
            },
            "maxResultCount": min(max_results, 20),
            "languageCode": "pt",
        }

        if place_type:
            payload["includedTypes"] = [place_type]
        else:
            # Sem tipo específico → qualquer restaurante
            payload["includedTypes"] = ["restaurant"]

        # FIX: searchNearby NÃO suporta textQuery — removido.
        # textQuery só funciona em searchByText (search_by_text).

        if open_now:
            payload["openNow"] = True

        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{PLACES_BASE}/places:searchNearby",
                    json=payload,
                    headers=self._headers(FIELDS_BASIC),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ClientResponseError as e:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(f"Google Places API erro {e.status}: {e.message}")
        except Exception as e:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(f"Erro ao buscar restaurantes: {e}")

        self._track_call(time.time() - start, error=False)

        places = data.get("places", [])
        results = [self._parse_place(p) for p in places]

        # Filtra por rating mínimo
        if min_rating > 0:
            results = [r for r in results if r.get("rating", 0) >= min_rating]

        # Ordena por rating DESC
        results.sort(key=lambda r: r.get("rating", 0), reverse=True)

        self._set_cache(cache_key, results)
        self.logger.info(
            "Nearby search: %d results for (%f, %f) type=%s",
            len(results),
            lat,
            lng,
            place_type,
        )
        return results

    async def search_by_text(
        self,
        text: str,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        max_results: int = 5,
        open_now: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Busca restaurantes por texto livre.

        Args:
            text:        Query (ex: "sushi perto do Marquês de Pombal")
            lat, lng:    Coordenadas para bias (opcional)
            max_results: Máximo de resultados
            open_now:    Apenas abertos agora

        Returns:
            Lista de restaurantes
        """
        if not self.is_initialized():
            await self.initialize()

        cache_key = f"text:{text}:{lat}:{lng}:{open_now}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        payload: Dict[str, Any] = {
            "textQuery": text,
            "maxResultCount": min(max_results, 20),
            "languageCode": "pt",
            "includedType": "restaurant",
        }

        if open_now:
            payload["openNow"] = True

        # Bias de localização (não restringe, apenas favorece)
        if lat is not None and lng is not None:
            payload["locationBias"] = {
                "circle": {
                    "center": {"latitude": lat, "longitude": lng},
                    "radius": 5000,
                }
            }

        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{PLACES_BASE}/places:searchText",
                    json=payload,
                    headers=self._headers(FIELDS_BASIC),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ClientResponseError as e:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(f"Google Places API erro {e.status}: {e.message}")
        except Exception as e:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(f"Erro na busca de restaurantes: {e}")

        self._track_call(time.time() - start, error=False)

        places = data.get("places", [])
        results = [self._parse_place(p) for p in places]
        results.sort(key=lambda r: r.get("rating", 0), reverse=True)

        self._set_cache(cache_key, results)
        self.logger.info("Text search '%s': %d results", text, len(results))
        return results

    async def get_details(self, place_id: str) -> Dict[str, Any]:
        """
        Retorna detalhes completos de um restaurante.

        Args:
            place_id: ID do Google Places (ex: "ChIJ...")

        Returns:
            Dict com todos os detalhes: horário completo, telefone, reviews, etc.
        """
        if not self.is_initialized():
            await self.initialize()

        cache_key = f"detail:{place_id}"
        cached = self._get_cache(cache_key)
        if cached is not None:
            return cached

        start = time.time()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{PLACES_BASE}/places/{place_id}",
                    headers=self._headers(FIELDS_DETAIL),
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    resp.raise_for_status()
                    data = await resp.json()
        except aiohttp.ClientResponseError as e:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(f"Erro ao buscar detalhes: {e.status}")
        except Exception as e:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(f"Erro ao buscar detalhes: {e}")

        self._track_call(time.time() - start, error=False)
        result = self._parse_place_detail(data)
        self._set_cache(cache_key, result)
        return result

    # ──────────────────────────────────────────────────────────────────────────
    # FORMATAÇÃO
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def format_restaurant(place: Dict[str, Any], index: int = 0) -> str:
        """Formata um restaurante para exibição no Telegram."""
        emoji = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][index] if index < 5 else "🍽️"
        name = place.get("name", "Desconhecido")
        rating = place.get("rating")
        rating_str = f"⭐ {rating:.1f}" if rating else "⭐ N/D"
        review_count = place.get("review_count", 0)
        price = place.get("price", "")
        price_str = f" · {price}" if price else ""
        address = place.get("address", "")
        address_short = address.split(",")[0] if address else ""
        is_open = place.get("is_open")
        open_str = (
            " · 🟢 Aberto"
            if is_open is True
            else (" · 🔴 Fechado" if is_open is False else "")
        )
        phone = place.get("phone", "")
        phone_str = f"\n📞 {phone}" if phone else ""
        maps_url = place.get("maps_url", "")
        maps_str = f"\n🗺️ [Ver no Maps]({maps_url})" if maps_url else ""

        return (
            f"{emoji} *{name}*\n"
            f"{rating_str} ({review_count} reviews){price_str}{open_str}\n"
            f"📍 {address_short}"
            f"{phone_str}"
            f"{maps_str}"
        )

    @staticmethod
    def format_list(
        places: List[Dict[str, Any]], title: str = "🍽️ Restaurantes encontrados"
    ) -> str:
        """Formata lista de restaurantes para Telegram."""
        if not places:
            return "Nenhum restaurante encontrado."
        lines = [f"{title} ({len(places)}):\n"]
        for i, place in enumerate(places):
            lines.append(RestaurantService.format_restaurant(place, i))
            lines.append("")
        lines.append("_Diz o número para ver mais detalhes ou reservar._")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # PARSERS INTERNOS
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_place(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza dados brutos do Places API para formato interno."""
        name = raw.get("displayName", {}).get("text", "Desconhecido")
        place_id = raw.get("id", "")
        rating = raw.get("rating")
        review_count = raw.get("userRatingCount", 0)
        price_level = raw.get("priceLevel")
        address = raw.get("formattedAddress", "")
        phone = raw.get("nationalPhoneNumber", "")
        website = raw.get("websiteUri", "")
        summary = raw.get("editorialSummary", {}).get("text", "")
        primary_type = raw.get("primaryType", "")

        # Aberto agora
        opening = raw.get("currentOpeningHours", {})
        is_open = opening.get("openNow") if opening else None

        # Horário de hoje
        today_hours = ""
        periods = opening.get("weekdayDescriptions", [])
        if periods:
            today_hours = periods[0] if periods else ""

        # Localização
        loc = raw.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")

        # Google Maps URL
        maps_url = ""
        if place_id:
            maps_url = f"https://www.google.com/maps/place/?q=place_id:{place_id}"

        return {
            "place_id": place_id,
            "name": name,
            "rating": rating,
            "review_count": review_count,
            "price": _price_label(price_level),
            "price_level": price_level,
            "address": address,
            "phone": phone,
            "website": website,
            "summary": summary,
            "primary_type": primary_type,
            "is_open": is_open,
            "today_hours": today_hours,
            "lat": lat,
            "lng": lng,
            "maps_url": maps_url,
        }

    @staticmethod
    def _parse_place_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza detalhes completos de um lugar."""
        base = RestaurantService._parse_place(raw)

        # Horário completo da semana
        regular = raw.get("regularOpeningHours", {})
        weekly = regular.get("weekdayDescriptions", [])

        # Reviews (máx 3)
        reviews_raw = raw.get("reviews", [])[:3]
        reviews = [
            {
                "author": r.get("authorAttribution", {}).get("displayName", ""),
                "rating": r.get("rating"),
                "text": r.get("text", {}).get("text", "")[:200],
                "time": r.get("relativePublishTimeDescription", ""),
            }
            for r in reviews_raw
        ]

        # Serviços disponíveis
        services = []
        if raw.get("dineIn"):
            services.append("🍽️ Comer no local")
        if raw.get("takeout"):
            services.append("🥡 Take away")
        if raw.get("delivery"):
            services.append("🛵 Entrega")
        if raw.get("reservable"):
            services.append("📅 Aceita reservas")

        # Maps URL completo
        maps_url = raw.get("googleMapsUri", base.get("maps_url", ""))

        base.update(
            {
                "weekly_hours": weekly,
                "reviews": reviews,
                "services": services,
                "maps_url": maps_url,
                "reservable": raw.get("reservable", False),
                "delivery": raw.get("delivery", False),
                "takeout": raw.get("takeout", False),
                "dine_in": raw.get("dineIn", False),
            }
        )
        return base

    # ──────────────────────────────────────────────────────────────────────────
    # CACHE
    # ──────────────────────────────────────────────────────────────────────────

    def _get_cache(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and time.time() < entry["expires_at"]:
            return entry["data"]
        return None

    def _set_cache(self, key: str, data: Any) -> None:
        self._cache[key] = {
            "data": data,
            "expires_at": time.time() + CACHE_TTL,
        }
