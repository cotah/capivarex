# -*- coding: utf-8 -*-
"""
agents/specialized/restaurant_agent.py

FIX [2025-02]:
 1. Default city Lisboa → Dublin, Ireland (Wave 2)
 2. Persistência de last_results no Redis (esta wave)
 3. GPS auto-use do Supabase (Passo 4B)

PROBLEMA: O bot é stateless. Cada mensagem cria um novo `context` dict vazio.
Quando o utilizador diz "mais detalhes sobre o 2" numa mensagem separada,
context["last_results"] está vazio → "Não tenho restaurantes em memória."

SOLUÇÃO: Após cada busca, guardar os resultados no Redis com chave
`restaurant:last_results:{user_id}` (TTL 30 minutos). Em `_handle_detail`,
se `context.get("last_results")` estiver vazio, tentar carregar do Redis
antes de falhar.

GPS AUTO-USE (Passo 4B): Quando lat/lng não estão no context, busca
coordenadas do Supabase via get_location() antes de usar cidade default.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from agents.core import AgentResponse, AgentStatus, BaseAgent, register_agent
from services import get_service
from services.business import restaurant_db_service as rdb

logger = logging.getLogger(__name__)

# ─── Constantes ───────────────────────────────────────────────────────────────
_REDIS_KEY_TTL = 1800  # 30 minutos

_SEARCH_WORDS = [
    "restaurante",
    "restaurantes",
    "comer",
    "jantar",
    "almoçar",
    "almoço",
    "comida",
    "sugere",
    "sugestão",
    "indica",
    "recomenda",
    "onde comer",
    "onde jantar",
    "pizza",
    "sushi",
    "burger",
    "hamburguer",
    "italiano",
    "japonês",
    "chinês",
    "mexicano",
    "vegetariano",
    "marisco",
    "peixe",
    "churrasco",
    "café",
    "bar",
]
_DETAIL_WORDS = [
    "mais detalhes",
    "detalhes do",
    "detalhes sobre",
    "telefone do",
    "horário do",
    "endereço do",
    "info do",
    "informações do",
    "ver o",
    "mostra o",
    "número",
    "primeiro",
    "segundo",
    "terceiro",
]
_FAVORITES_WORDS = [
    "meus favoritos",
    "favoritos",
    "restaurantes favoritos",
    "meus restaurantes",
    "my favorites",
]
_RESERVATIONS_WORDS = [
    "minhas reservas",
    "reservas",
    "meus pedidos",
    "my reservations",
]
_ADD_FAV_WORDS = [
    "guardar",
    "favoritar",
    "salvar",
    "adicionar favorito",
    "guarda esse",
    "guardar como favorito",
]
_RESERVATION_WORDS = [
    "reservar",
    "reserva",
    "fazer reserva",
    "marcar mesa",
    "book",
]
_OPEN_NOW_WORDS = ["aberto agora", "aberto hoje", "aberto", "open now"]
_RATING_RE = re.compile(
    r"rating\s+(?:acima\s+de|de|mínimo)?\s*([0-9]+(?:[.,][0-9])?)", re.I
)
_RADIUS_RE = re.compile(r"(\d+)\s*(?:km|quilómetros?|metros?|m\b)", re.I)
_DETAIL_NUM_RE = re.compile(
    r"\b([1-5]|primeiro|segundo|terceiro|quarto|quinto)\b", re.I
)
_NUM_MAP = {
    "primeiro": 0,
    "segundo": 1,
    "terceiro": 2,
    "quarto": 3,
    "quinto": 4,
    "1": 0,
    "2": 1,
    "3": 2,
    "4": 3,
    "5": 4,
}


def _detect_intent(text: str, context: Dict[str, Any]) -> str:
    t = text.lower()
    if context.get("action"):
        return context["action"]
    if any(w in t for w in _FAVORITES_WORDS):
        return "list_favorites"
    if any(w in t for w in _RESERVATIONS_WORDS):
        return "list_reservations"
    if any(w in t for w in _ADD_FAV_WORDS):
        return "add_favorite"
    if any(w in t for w in _RESERVATION_WORDS):
        return "create_reservation"
    if any(w in t for w in _DETAIL_WORDS):
        return "detail"
    if any(w in t for w in _SEARCH_WORDS):
        return "search"
    return "unknown"


def _extract_open_now(text: str) -> bool:
    return any(w in text.lower() for w in _OPEN_NOW_WORDS)


def _extract_min_rating(text: str) -> float:
    m = _RATING_RE.search(text)
    return float(m.group(1).replace(",", ".")) if m else 0.0


def _extract_radius(text: str) -> int:
    m = _RADIUS_RE.search(text)
    if not m:
        return 1500
    value = int(m.group(1))
    unit = m.group(0).lower()
    if "km" in unit or "quilómetro" in unit:
        return min(value * 1000, 50000)
    return min(value, 50000)


def _extract_detail_index(text: str) -> Optional[int]:
    m = _DETAIL_NUM_RE.search(text.lower())
    return _NUM_MAP.get(m.group(1).lower()) if m else None


def _build_search_query(text: str) -> str:
    cleaned = re.sub(
        r"\b(sugere|sugestão|indica|recomenda|preciso\s+de|quero|encontra|busca|"
        r"mostra|perto\s+de\s+mim|aqui\s+perto|perto\s+daqui|perto|em\s+|de\s+|"
        r"um\s+|uma\s+|para\s+jantar|para\s+almoço|hoje|agora)\b",
        "",
        text,
        flags=re.I,
    ).strip()
    return cleaned or text


# ─── Redis helpers ─────────────────────────────────────────────────────────────


def _redis_key(user_id: str) -> str:
    return f"restaurant:last_results:{user_id}"


async def _save_results_to_redis(user_id: str, places: List[Dict]) -> None:
    """Guarda lista de restaurantes no Redis com TTL de 30 min."""
    try:
        redis_svc = get_service("redis")
        if redis_svc:
            if not redis_svc.is_initialized():
                await redis_svc.initialize()
            await redis_svc.set(
                _redis_key(user_id),
                json.dumps(places, ensure_ascii=False),
                expire_seconds=_REDIS_KEY_TTL,
            )
    except Exception as e:
        logger.warning("Could not save restaurant results to Redis: %s", e)


async def _load_results_from_redis(user_id: str) -> Optional[List[Dict]]:
    """Carrega lista de restaurantes do Redis (se ainda válida)."""
    try:
        redis_svc = get_service("redis")
        if not redis_svc:
            return None
        if not redis_svc.is_initialized():
            await redis_svc.initialize()
        raw = await redis_svc.get(_redis_key(user_id))
        if raw:
            # RedisService pode retornar string ou já desserializado
            if isinstance(raw, str):
                return json.loads(raw)
            if isinstance(raw, list):
                return raw
    except Exception as e:
        logger.warning("Could not load restaurant results from Redis: %s", e)
    return None


@register_agent("restaurant")
class RestaurantAgent(BaseAgent):
    """
    Concierge de Restaurantes — busca, filtra e detalha restaurantes.

    Context esperado:
        user_id     (str)   ID do utilizador (UUID)
        chat_id     (str)   Chat Telegram
        lat         (float) Latitude do utilizador (opcional)
        lng         (float) Longitude do utilizador (opcional)
        city        (str)   Cidade fallback se sem coordenadas
        last_results (List) Resultados da última busca (para detalhe)

    GPS auto-use: se lat/lng não estiverem no context, busca do Supabase.
    """

    def __init__(self):
        super().__init__(
            name="restaurant",
            description=(
                "Concierge de restaurantes — sugere, filtra e detalha "
                "restaurantes por localização, tipo de cozinha e preferências"
            ),
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        try:
            svc = get_service("restaurant")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço de restaurantes não disponível.",
                    error="RestaurantService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            user_id = str(context.get("user_id", ""))
            if not user_id:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Utilizador não identificado.",
                    error="No user_id",
                )

            # ── GPS AUTO-USE (Passo 4B) ────────────────────────────────
            # Se lat/lng não estão no context, tenta GPS do Supabase
            if not (context.get("lat") and context.get("lng")):
                try:
                    from services.business.user_preferences_service import get_location

                    loc = await get_location(str(user_id), prefer="last")
                    if loc:
                        lat, lng = loc
                        context = {
                            **context,
                            "lat": lat,
                            "lng": lng,
                        }
                        self.logger.info(
                            "RestaurantAgent GPS auto-use: %s,%s for user %s",
                            lat,
                            lng,
                            user_id,
                        )
                except Exception as e:
                    self.logger.warning("Could not fetch GPS for restaurant: %s", e)
            # ── FIM GPS AUTO-USE ───────────────────────────────────────

            intent = _detect_intent(prompt, context)

            if intent == "list_favorites":
                return await self._handle_list_favorites(user_id)
            if intent == "list_reservations":
                return await self._handle_list_reservations(user_id)
            if intent == "add_favorite":
                return await self._handle_add_favorite(prompt, context, user_id)
            if intent == "create_reservation":
                return await self._handle_create_reservation(prompt, context, user_id)
            if intent == "detail":
                return await self._handle_detail(svc, prompt, context, user_id)
            if intent == "search":
                return await self._handle_search(svc, prompt, context, user_id)

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não percebi o pedido. Exemplos:\n"
                    "• *Sugere um restaurante italiano em Dublin*\n"
                    "• *Sushi perto de mim aberto agora*\n"
                    "• *Mais detalhes sobre o 2*"
                ),
                error="Could not detect intent",
            )

        except RuntimeError as e:
            self.logger.error("RestaurantAgent API error: %s", e)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao pesquisar restaurantes: {e}",
                error=str(e),
            )
        except Exception as e:
            self.logger.error("RestaurantAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro inesperado. Tenta novamente.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_search(
        self,
        svc: Any,
        prompt: str,
        context: Dict[str, Any],
        user_id: str = "",
    ) -> AgentResponse:
        lat: Optional[float] = context.get("lat")
        lng: Optional[float] = context.get("lng")
        # FIX Wave 2: default Dublin, Ireland
        city: str = context.get("city", "Dublin, Ireland")
        open_now = context.get("open_now") or _extract_open_now(prompt)
        min_rating = context.get("min_rating") or _extract_min_rating(prompt)
        radius = context.get("radius") or _extract_radius(prompt)
        max_results = context.get("max_results", 5)
        query = context.get("query") or _build_search_query(prompt)

        if lat and lng:
            places = await svc.search_nearby(
                lat=lat,
                lng=lng,
                query=query,
                radius=radius,
                min_rating=min_rating,
                open_now=open_now,
                max_results=max_results,
            )
        else:
            search_text = (
                query if city.lower() in query.lower() else f"{query} em {city}"
            )
            places = await svc.search_by_text(
                text=search_text,
                open_now=open_now,
                max_results=max_results,
            )

        if min_rating > 0:
            places = [p for p in places if (p.get("rating") or 0) >= min_rating]

        try:
            await rdb.save_search(
                user_id=user_id,
                cuisine=query,
                latitude=lat,
                longitude=lng,
                radius_km=radius // 1000 if radius >= 1000 else 1,
                open_now=open_now,
                min_rating=min_rating or None,
                results_count=len(places),
            )
        except Exception:
            pass

        if not places:
            tip = "aberto agora" if open_now else "essa pesquisa"
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f"🔍 Não encontrei restaurantes para *{tip}*.\n\n"
                    "Tenta:\n• Aumentar o raio de busca\n"
                    "• Remover o filtro 'aberto agora'\n"
                    "• Mudar o tipo de cozinha"
                ),
                data={"places": [], "query": query},
            )

        # FIX: Guardar no context E no Redis (persiste entre mensagens)
        context["last_results"] = places
        if user_id:
            await _save_results_to_redis(user_id, places)

        open_filter = " 🟢 *abertos agora*" if open_now else ""
        rating_filter = f" com rating ≥ {min_rating}" if min_rating > 0 else ""
        title = f"🍽️ *Restaurantes{open_filter}{rating_filter}*"
        response_text = svc.format_list(places, title)
        response_text += (
            "\n\n💡 *Dica:* Diz o número para ver detalhes, "
            '"guardar como favorito" ou "fazer reserva".'
        )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response_text,
            data={"places": places, "query": query, "count": len(places)},
        )

    async def _handle_detail(
        self,
        svc: Any,
        prompt: str,
        context: Dict[str, Any],
        user_id: str = "",
    ) -> AgentResponse:
        last_results: Optional[List] = context.get("last_results")

        # FIX: Se não há last_results no context (mensagem separada),
        # tenta carregar do Redis
        if not last_results and user_id:
            last_results = await _load_results_from_redis(user_id)
            if last_results:
                self.logger.info(
                    "Loaded %d restaurant results from Redis for user %s",
                    len(last_results),
                    user_id,
                )

        if not last_results:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não tenho restaurantes em memória.\n"
                    "Faz primeiro uma pesquisa, por exemplo:\n"
                    "*Restaurantes italianos perto de mim*"
                ),
                error="No last_results in context or Redis",
            )

        idx = context.get("restaurant_index") or _extract_detail_index(prompt)
        if idx is None:
            idx = 0

        if idx >= len(last_results):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Só tenho {len(last_results)} restaurante(s) na lista.",
                error="Index out of range",
            )

        place = last_results[idx]
        place_id = place.get("place_id")
        if not place_id:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível obter detalhes deste restaurante.",
                error="No place_id",
            )

        details = await svc.get_details(place_id)
        response_text = self._format_detail(details, idx)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response_text,
            data={"place": details},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Favorites & Reservations (igual ao original — sem alterações)
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_add_favorite(self, prompt, context, user_id):
        last_results = context.get("last_results")
        if not last_results and user_id:
            last_results = await _load_results_from_redis(user_id)
        if not last_results:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Faz primeiro uma pesquisa para eu poder guardar.",
                error="No last_results",
            )
        idx = _extract_detail_index(prompt)
        if idx is None:
            idx = 0
        if idx >= len(last_results):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Só tenho {len(last_results)} restaurante(s).",
                error="Index out of range",
            )
        place = last_results[idx]
        loc = place.get("location", {})
        try:
            await rdb.add_favorite(
                user_id=user_id,
                place_id=place.get("place_id", ""),
                name=place.get("name", ""),
                address=place.get("address"),
                rating=place.get("rating"),
                cuisine=place.get("cuisine"),
                latitude=loc.get("lat"),
                longitude=loc.get("lng"),
            )
        except Exception:
            pass
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"⭐ *{place.get('name', 'Restaurante')}* guardado nos favoritos!\n\n"
                'Diz *"meus favoritos"* para ver a lista completa.'
            ),
            data={"favorite": place},
        )

    async def _handle_list_favorites(self, user_id):
        try:
            favs = await rdb.get_favorites(user_id)
        except Exception:
            favs = []
        if not favs:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Ainda não tens restaurantes favoritos.",
                data={"favorites": []},
            )
        lines = [f"⭐ *Teus favoritos ({len(favs)}):*\n"]
        for i, f in enumerate(favs, 1):
            rating = f"⭐ {f['rating']}" if f.get("rating") else ""
            lines.append(f"{i}. *{f['name']}* {rating}")
            if f.get("address"):
                lines.append(f"   📍 _{f['address']}_")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"favorites": favs},
        )

    async def _handle_create_reservation(self, prompt, context, user_id):
        last_results = context.get("last_results")
        if not last_results and user_id:
            last_results = await _load_results_from_redis(user_id)
        place = context.get("reservation_place")
        if not place and last_results:
            idx = _extract_detail_index(prompt)
            if idx is None:
                idx = 0
            if idx < len(last_results):
                place = last_results[idx]
        if not place:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Faz primeiro uma pesquisa ou diz o número do restaurante.",
                error="No restaurant for reservation",
            )
        party_size = context.get("party_size")
        reservation_dt = context.get("reservation_dt")
        if not party_size or not reservation_dt:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f"🍽️ Reserva no *{place.get('name', 'restaurante')}*\n\n"
                    "Precisas de:\n• 📅 *Data e hora* (ex: sexta às 20h)\n"
                    "• 👥 *Número de pessoas* (ex: 2 pessoas)"
                ),
                data={"awaiting": "reservation_details", "reservation_place": place},
            )
        try:
            res = await rdb.create_reservation(
                user_id=user_id,
                place_id=place.get("place_id", ""),
                restaurant_name=place.get("name", ""),
                restaurant_phone=place.get("phone"),
                party_size=party_size,
                reservation_dt=reservation_dt,
                notes=context.get("notes"),
            )
        except Exception:
            res = {}
        phone_line = f"\n📞 {place['phone']}" if place.get("phone") else ""
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"✅ *Reserva criada!*\n"
                f"🍽️ {place.get('name', 'Restaurante')}\n"
                f"📅 {reservation_dt}\n"
                f"👥 {party_size} pessoa(s){phone_line}\n\n"
                "⚠️ Confirma directamente com o restaurante para garantir."
            ),
            data={"reservation": res},
        )

    async def _handle_list_reservations(self, user_id):
        try:
            reservations = await rdb.get_reservations(user_id)
        except Exception:
            reservations = []
        if not reservations:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Não tens reservas registadas.",
                data={"reservations": []},
            )
        lines = [f"📋 *Tuas reservas ({len(reservations)}):*\n"]
        for i, r in enumerate(reservations, 1):
            status_icon = {"pending": "⏳", "confirmed": "✅", "cancelled": "❌"}.get(
                r.get("status", ""), "❓"
            )
            lines.append(
                f"{i}. {status_icon} *{r['restaurant_name']}* — "
                f"{r.get('reservation_dt', 'sem data')} · "
                f"{r.get('party_size', '?')} pessoa(s)"
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"reservations": reservations},
        )

    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _format_detail(place: Dict[str, Any], idx: int = 0) -> str:
        from services.integrations.restaurant_service import RestaurantService

        header = RestaurantService.format_restaurant(place, idx)
        lines = [header, ""]
        services = place.get("services", [])
        if services:
            lines.append("*Serviços:* " + " · ".join(services))
        weekly = place.get("weekly_hours", [])
        if weekly:
            lines.append("\n📅 *Horário:*")
            for day in weekly:
                lines.append(f"  {day}")
        if place.get("website"):
            lines.append(f"\n🌐 [Website]({place['website']})")
        reviews = place.get("reviews", [])
        if reviews:
            lines.append("\n💬 *Avaliações recentes:*")
            for r in reviews[:2]:
                stars = "⭐" * (r.get("rating") or 0)
                author = r.get("author", "Anónimo")
                text = r.get("text", "")[:150]
                time_str = r.get("time", "")
                lines.append(f"\n_{author}_ {stars} _{time_str}_")
                if text:
                    lines.append(
                        f'"{text}…"' if len(r.get("text", "")) > 150 else f'"{text}"'
                    )
        if place.get("maps_url"):
            lines.append(f"\n🗺️ [Ver no Google Maps]({place['maps_url']})")
        return "\n".join(lines)

    def get_capabilities(self) -> List[str]:
        return [
            "search_restaurants_nearby",
            "search_restaurants_by_text",
            "filter_by_cuisine",
            "filter_by_rating",
            "filter_open_now",
            "get_restaurant_details",
            "get_opening_hours",
            "get_restaurant_phone",
            "get_reviews",
            "add_favorite",
            "list_favorites",
            "create_reservation",
            "list_reservations",
        ]
