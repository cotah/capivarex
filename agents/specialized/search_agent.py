# -*- coding: utf-8 -*-
"""
agents/specialized/search_agent.py
=====================================
SearchAgent — busca Google estruturada via Serper API.

Diferença do ResearchAgent:
  - ResearchAgent (Perplexity) → síntese, análise, explicações longas
  - SearchAgent   (Serper)     → resultados concretos: lugares, links, produtos, preços

Exemplos de queries:
  - "Livrarias abertas agora em Dublin"          → search_places
  - "Restaurante italiano perto do centro"       → search_places
  - "Quanto custa iPhone 15 hoje"                → search + shopping
  - "Site oficial da Duffel API"                 → search
  - "Últimas notícias sobre Bitcoin"             → search_news
  - "Presente para mulher que gosta de leitura"  → search_shopping
  - "Farmácia aberta em Dublin 2"                → search_places
"""

import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


# ─── Detecção de intent ───────────────────────────────────────────────────────

# Palavras que indicam busca de LUGARES físicos
_PLACE_KEYWORDS = [
    "aberto", "aberta", "perto", "próximo", "próxima", "next to",
    "restaurante", "farmácia", "livraria", "loja", "café", "bar",
    "hotel", "hospital", "supermercado", "shopping", "cinema",
    "dentista", "médico", "clínica", "posto", "banco", "atm",
    "near me", "nearby", "open now", "where to",
    "em dublin", "in dublin", "em cork", "em galway",
]

# Palavras que indicam busca de PRODUTOS/SHOPPING
_SHOPPING_KEYWORDS = [
    "comprar", "preço", "quanto custa", "price", "buy", "shop",
    "presente", "gift", "produto", "loja online", "delivery",
    "melhor", "barato", "barata", "desconto", "oferta",
    "amazon", "ebay", "aliexpress",
]

# Palavras que indicam busca de NOTÍCIAS
_NEWS_KEYWORDS = [
    "notícia", "notícias", "news", "hoje", "agora", "recente",
    "último", "última", "breaking", "manchete", "atualidade",
]


def _has_keyword(text: str, keywords: list) -> bool:
    """Verifica se alguma keyword está no texto usando word boundaries."""
    for kw in keywords:
        # Para keywords multi-word ou com acento, usar busca literal com boundary
        if re.search(rf"\b{re.escape(kw)}\b", text):
            return True
    return False


def _detect_search_type(prompt: str) -> str:
    """
    Detecta o tipo de busca pelo conteúdo do prompt.

    Returns:
        "places" | "shopping" | "news" | "general"
    """
    text = prompt.lower()

    # Places tem prioridade (mais específico)
    if _has_keyword(text, _PLACE_KEYWORDS):
        return "places"

    if _has_keyword(text, _SHOPPING_KEYWORDS):
        return "shopping"

    if _has_keyword(text, _NEWS_KEYWORDS):
        return "news"

    return "general"


def _extract_country(prompt: str, context: Dict) -> str:
    """Detecta país alvo da busca. Default: Irlanda (ie)."""
    if context.get("country"):
        return str(context["country"])

    text = prompt.lower()
    if any(w in text for w in ["brasil", "brazil", "são paulo", "rio"]):
        return "br"
    if any(w in text for w in ["uk", "england", "london", "united kingdom"]):
        return "gb"
    if any(w in text for w in ["usa", "united states", "america", "new york"]):
        return "us"
    # Default: Irlanda (onde o usuário está)
    return "ie"


@register_agent("search")
class SearchAgent(BaseAgent):
    """
    Search agent — busca Google estruturada via Serper API.

    Intents:
        places   → lugares físicos com endereço, telefone, horário
        shopping → produtos com preço e loja
        news     → notícias recentes
        general  → links e snippets genéricos

    Base para:
        - Concierge de Restaurantes (#11)
        - Concierge de Presentes (#21)
    """

    def __init__(self):
        super().__init__(
            name="search",
            description=(
                "Busca Google estruturada: lugares, produtos, preços, links. "
                "Para análises e sínteses use o ResearchAgent."
            ),
        )

    async def execute(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        try:
            svc = get_service("search")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "Serviço de busca não disponível.\n"
                        "Configure a `SERPER_API_KEY` no `.env`.\n"
                        "Cadastro gratuito: https://serper.dev"
                    ),
                    error="SearchService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            query = (context.get("query") or prompt).strip()
            if not query:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="O que devo buscar? Tente: *Busca restaurantes italianos em Dublin*",
                    error="Empty query",
                )

            # Tipo de busca — context tem prioridade sobre auto-detect
            search_type = context.get("search_type") or _detect_search_type(query)
            country = _extract_country(query, context)
            num_results = int(context.get("num_results", 5))

            # ── Dispatch por tipo ──────────────────────────────────────────
            if search_type == "places":
                return await self._handle_places(svc, query, country)

            if search_type == "shopping":
                return await self._handle_shopping(svc, query, country)

            if search_type == "news":
                return await self._handle_news(svc, query, num_results, country)

            # general
            return await self._handle_general(svc, query, num_results, country)

        except RuntimeError as e:
            msg = str(e)
            # Erros conhecidos da API
            if "SERPER_API_KEY" in msg or "inválida" in msg.lower():
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "⚙️ Serviço de busca não configurado.\n"
                        "Adicione a `SERPER_API_KEY` no `.env`.\n"
                        "Cadastro gratuito: https://serper.dev"
                    ),
                    error=msg,
                )
            if "quota" in msg.lower() or "429" in msg:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "⚠️ Limite de buscas Serper atingido (2.500/mês no plano free).\n"
                        "Verifique em serper.dev → Usage."
                    ),
                    error=msg,
                )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro na busca: {msg}",
                error=msg,
            )
        except Exception as e:
            self.logger.error("SearchAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro inesperado na busca. Tente novamente.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers por tipo
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_places(
        self, svc: Any, query: str, country: str
    ) -> AgentResponse:
        data = await svc.search_places(query, country=country)
        places = data.get("places", [])

        if not places:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Não encontrei nenhum lugar para: *{query}*",
                error="No places found",
            )

        response = self._format_places(query, places)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=data,
        )

    async def _handle_shopping(
        self, svc: Any, query: str, country: str
    ) -> AgentResponse:
        data = await svc.search_shopping(query, country=country)
        products = data.get("products", [])

        if not products:
            # Fallback para busca geral
            data = await svc.search(query, country=country)
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=self._format_general(query, data),
                data=data,
            )

        response = self._format_shopping(query, products)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=data,
        )

    async def _handle_news(
        self, svc: Any, query: str, num_results: int, country: str
    ) -> AgentResponse:
        data = await svc.search_news(query, num_results=num_results, country=country)
        news = data.get("news", [])

        if not news:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Não encontrei notícias recentes sobre: *{query}*",
                error="No news found",
            )

        response = self._format_news(query, news)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=data,
        )

    async def _handle_general(
        self, svc: Any, query: str, num_results: int, country: str
    ) -> AgentResponse:
        data = await svc.search(query, num_results=num_results, country=country)
        results = data.get("results", [])
        answer_box = data.get("answer_box", {})

        if not results and not answer_box:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Não encontrei resultados para: *{query}*",
                error="No results found",
            )

        response = self._format_general(query, data)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response,
            data=data,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Formatação das respostas
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_places(query: str, places: List[Dict]) -> str:
        lines = [f"📍 **Lugares encontrados para: _{query}_**\n"]
        for i, p in enumerate(places[:5], 1):
            name = p.get("title", "")
            addr = p.get("address", "")
            phone = p.get("phone", "")
            rating = p.get("rating")
            reviews = p.get("reviews")
            open_now = p.get("open_now", "")
            website = p.get("website", "")

            # Linha principal
            lines.append(f"**{i}. {name}**")

            if rating:
                stars = "⭐" * round(float(rating))
                rev_str = f" ({reviews} avaliações)" if reviews else ""
                lines.append(f"   {stars} {rating}{rev_str}")

            if addr:
                lines.append(f"   📍 {addr}")

            if phone:
                lines.append(f"   📞 {phone}")

            if open_now:
                emoji = "🟢" if "open" in open_now.lower() else "🔴"
                lines.append(f"   {emoji} {open_now}")

            if website:
                lines.append(f"   🌐 {website}")

            lines.append("")  # linha em branco entre lugares

        return "\n".join(lines).strip()

    @staticmethod
    def _format_shopping(query: str, products: List[Dict]) -> str:
        lines = [f"🛍️ **Produtos encontrados para: _{query}_**\n"]
        for i, p in enumerate(products[:5], 1):
            title = p.get("title", "")
            price = p.get("price", "")
            source = p.get("source", "")
            link = p.get("link", "")
            rating = p.get("rating")
            delivery = p.get("delivery", "")

            lines.append(f"**{i}. {title}**")
            if price:
                lines.append(f"   💰 **{price}** — {source}")
            if rating:
                lines.append(f"   ⭐ {rating}")
            if delivery:
                lines.append(f"   🚚 {delivery}")
            if link:
                lines.append(f"   🔗 {link}")
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _format_news(query: str, news: List[Dict]) -> str:
        lines = [f"📰 **Notícias sobre: _{query}_**\n"]
        for i, n in enumerate(news[:5], 1):
            title = n.get("title", "")
            source = n.get("source", "")
            date = n.get("date", "")
            snippet = n.get("snippet", "")
            link = n.get("link", "")

            header = f"**{i}. {title}**"
            if source or date:
                meta = " — ".join(filter(None, [source, date]))
                header += f" _{meta}_"
            lines.append(header)

            if snippet:
                lines.append(f"   {snippet}")
            if link:
                lines.append(f"   🔗 {link}")
            lines.append("")

        return "\n".join(lines).strip()

    @staticmethod
    def _format_general(query: str, data: Dict) -> str:
        lines = []

        # Answer box primeiro (resposta direta do Google)
        ab = data.get("answer_box", {})
        if ab.get("answer"):
            lines.append(f"💡 **{ab.get('title', query)}**")
            lines.append(ab["answer"])
            if ab.get("link"):
                lines.append(f"🔗 {ab['link']}")
            lines.append("")

        # Knowledge graph
        kg = data.get("knowledge_graph", {})
        if kg.get("description"):
            lines.append(f"📚 **{kg.get('title', '')}** — {kg['description']}")
            lines.append("")

        # Resultados orgânicos
        results = data.get("results", [])
        if results:
            if not lines:  # sem answer box
                lines.append(f"🔍 **Resultados para: _{query}_**\n")
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "")
                link = r.get("link", "")
                snippet = r.get("snippet", "")
                lines.append(f"**{i}. {title}**")
                if snippet:
                    lines.append(f"   {snippet}")
                if link:
                    lines.append(f"   🔗 {link}")
                lines.append("")

        return "\n".join(lines).strip()

    def get_capabilities(self) -> List[str]:
        return [
            "web_search",
            "places_search",
            "shopping_search",
            "news_search",
            "price_lookup",
            "business_finder",
            "product_finder",
        ]
