# -*- coding: utf-8 -*-
"""
services/business/search_service.py
=====================================
SearchService — busca Google via Serper API.

Diferença do ResearchAgent (Perplexity):
  - ResearchAgent → resposta sintetizada, explicativa (jornalista)
  - SearchService  → resultados estruturados: links, lugares, imagens (GPS)

Operações:
  - search(query)               → busca geral Google (links + snippets)
  - search_places(query)        → lugares físicos (nome, endereço, telefone, horário)
  - search_news(query)          → notícias recentes
  - search_images(query)        → links de imagens
  - search_shopping(query)      → produtos com preço e loja

Autenticação:
  - SERPER_API_KEY → variável de ambiente
  - Cadastro gratuito: serper.dev (2.500 buscas/mês grátis)

Rate limits Serper:
  - Plano free: 2.500 buscas/mês
  - Pago: $50/mês → 50.000 buscas
  - Sem rate limit por segundo relevante para uso pessoal
"""

import os
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

from services.core import BaseService, register_service, ServiceUnavailableError

load_dotenv()

_BASE = "https://google.serper.dev"


@register_service("search")
class SearchService(BaseService):
    """
    Search service — busca Google estruturada via Serper API.

    Requer: SERPER_API_KEY no .env
    Cadastro: https://serper.dev (grátis, 2.500 buscas/mês)
    """

    def __init__(self):
        super().__init__(name="search")
        self._api_key: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _initialize(self) -> None:
        self._api_key = os.getenv("SERPER_API_KEY")
        if not self._api_key:
            raise ServiceUnavailableError(
                "SERPER_API_KEY não encontrada. "
                "Cadastre-se em serper.dev e adicione ao .env:\n"
                "SERPER_API_KEY=sua_chave_aqui"
            )
        self._client = httpx.AsyncClient(
            base_url=_BASE,
            timeout=10.0,
            headers={
                "X-API-KEY": self._api_key,
                "Content-Type": "application/json",
            },
        )
        self.logger.info("SearchService initialized (Serper API)")

    async def _health_check(self) -> bool:
        if not self._client or not self._api_key:
            return False
        try:
            resp = await self._client.post("/search", json={"q": "test"})
            return resp.status_code == 200
        except Exception:
            return False

    async def _cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        num_results: int = 5,
        country: str = "ie",
        language: str = "pt",
    ) -> Dict[str, Any]:
        """
        Busca geral Google — retorna links, títulos e snippets.

        Ideal para:
          - "Site oficial da Duffel API"
          - "Preço do iPhone 15 hoje"
          - Qualquer busca genérica de links

        Args:
            query:       Termo de busca
            num_results: Número de resultados (máx 10)
            country:     Código do país (ie=Irlanda, br=Brasil, us=EUA)
            language:    Idioma dos resultados

        Returns:
            Dict com:
              - results: lista de {title, link, snippet, position}
              - answer_box: resposta direta se disponível (ex: "Bitcoin = $95.000")
              - knowledge_graph: info estruturada se disponível
        """
        if not self.is_initialized():
            await self.initialize()

        resp = await self._client.post(
            "/search",
            json={
                "q": query,
                "num": min(num_results, 10),
                "gl": country,
                "hl": language,
            },
        )
        self._raise_for_status(resp, query)
        data = resp.json()
        return self._parse_organic(data)

    async def search_places(
        self,
        query: str,
        country: str = "ie",
    ) -> Dict[str, Any]:
        """
        Busca lugares físicos — retorna nome, endereço, telefone, rating, horário.

        Ideal para:
          - "Livrarias abertas em Dublin"
          - "Restaurante italiano perto do centro"
          - "Farmácia aberta agora"
          - Base do Concierge de Restaurantes e Presentes

        Args:
            query:   Termo de busca (ex: "italian restaurant Dublin city centre")
            country: Código do país

        Returns:
            Dict com:
              - places: lista de {
                  title, address, phone, rating, reviews,
                  hours, website, type, coordinates
                }
        """
        if not self.is_initialized():
            await self.initialize()

        resp = await self._client.post(
            "/places",
            json={"q": query, "gl": country},
        )
        self._raise_for_status(resp, query)
        data = resp.json()
        return self._parse_places(data)

    async def search_news(
        self,
        query: str,
        num_results: int = 5,
        country: str = "ie",
    ) -> Dict[str, Any]:
        """
        Busca notícias recentes.

        Complementa o ResearchAgent para queries que precisam de
        resultados de notícias rápidos e estruturados (não sintetizados).

        Args:
            query:       Termo de busca
            num_results: Número de notícias
            country:     Código do país

        Returns:
            Dict com:
              - news: lista de {title, link, snippet, source, date}
        """
        if not self.is_initialized():
            await self.initialize()

        resp = await self._client.post(
            "/news",
            json={"q": query, "num": min(num_results, 10), "gl": country},
        )
        self._raise_for_status(resp, query)
        data = resp.json()
        return self._parse_news(data)

    async def search_shopping(
        self,
        query: str,
        country: str = "ie",
    ) -> Dict[str, Any]:
        """
        Busca produtos com preço — ideal para sugestões de presentes.

        Args:
            query:   Produto a buscar (ex: "livro ficção científica", "headphones")
            country: Código do país

        Returns:
            Dict com:
              - products: lista de {title, price, source, link, rating, delivery}
        """
        if not self.is_initialized():
            await self.initialize()

        resp = await self._client.post(
            "/shopping",
            json={"q": query, "gl": country},
        )
        self._raise_for_status(resp, query)
        data = resp.json()
        return self._parse_shopping(data)

    async def search_images(
        self,
        query: str,
        num_results: int = 5,
        country: str = "ie",
    ) -> Dict[str, Any]:
        """
        Busca imagens — retorna links, título e dimensões.

        Ideal para:
        - "Fotos de Dublin"
        - "Imagens de capivara"
        - Complementar respostas com visual

        Args:
            query: Termo de busca
            num_results: Número de imagens (máx 10)
            country: Código do país

        Returns:
            Dict com:
            - images: lista de {title, link, source, thumbnail, width, height}
        """
        if not self.is_initialized():
            await self.initialize()

        resp = await self._client.post(
            "/images",
            json={
                "q": query,
                "num": min(num_results, 10),
                "gl": country,
            },
        )
        self._raise_for_status(resp, query)
        data = resp.json()
        return self._parse_images(data)

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE — parsers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _raise_for_status(resp: httpx.Response, query: str) -> None:
        """Levanta exceções claras para erros da Serper API."""
        if resp.status_code == 401:
            raise RuntimeError(
                "SERPER_API_KEY inválida. Verifique em serper.dev → Dashboard → API Key."
            )
        if resp.status_code == 429:
            raise RuntimeError(
                "Quota Serper esgotada (2.500/mês no plano free). "
                "Verifique em serper.dev → Usage."
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Serper API erro HTTP {resp.status_code} para query: '{query}'"
            )

    @staticmethod
    def _parse_organic(data: Dict) -> Dict[str, Any]:
        """Parseia resultados orgânicos de busca geral."""
        organic = data.get("organic", [])
        results = [
            {
                "position": r.get("position", i + 1),
                "title": r.get("title", ""),
                "link": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "date": r.get("date", ""),
            }
            for i, r in enumerate(organic)
        ]

        # Answer box (resposta direta do Google, ex: "Bitcoin hoje = $95k")
        answer_box = {}
        if "answerBox" in data:
            ab = data["answerBox"]
            answer_box = {
                "title": ab.get("title", ""),
                "answer": ab.get("answer") or ab.get("snippet", ""),
                "link": ab.get("link", ""),
            }

        # Knowledge graph (info estruturada, ex: dados de uma empresa)
        knowledge_graph = {}
        if "knowledgeGraph" in data:
            kg = data["knowledgeGraph"]
            knowledge_graph = {
                "title": kg.get("title", ""),
                "type": kg.get("type", ""),
                "description": kg.get("description", ""),
                "website": kg.get("website", ""),
            }

        return {
            "results": results,
            "total_results": len(results),
            "answer_box": answer_box,
            "knowledge_graph": knowledge_graph,
        }

    @staticmethod
    def _parse_places(data: Dict) -> Dict[str, Any]:
        """Parseia resultados de lugares (Google Places via Serper)."""
        raw_places = data.get("places", [])
        places = []
        for p in raw_places:
            # Horário de funcionamento
            hours_raw = p.get("openingHours", [])
            hours = hours_raw if isinstance(hours_raw, list) else []

            places.append(
                {
                    "title": p.get("title", ""),
                    "address": p.get("address", ""),
                    "phone": p.get("phoneNumber", ""),
                    "rating": p.get("rating"),
                    "reviews": p.get("ratingCount"),
                    "type": p.get("type", ""),
                    "website": p.get("website", ""),
                    "hours": hours,
                    "open_now": p.get("openState", ""),
                    "coordinates": {
                        "lat": p.get("latitude"),
                        "lng": p.get("longitude"),
                    },
                    "thumbnail": p.get("thumbnailUrl", ""),
                }
            )

        return {
            "places": places,
            "total_places": len(places),
        }

    @staticmethod
    def _parse_news(data: Dict) -> Dict[str, Any]:
        """Parseia resultados de notícias."""
        raw_news = data.get("news", [])
        news = [
            {
                "title": n.get("title", ""),
                "link": n.get("link", ""),
                "snippet": n.get("snippet", ""),
                "source": n.get("source", ""),
                "date": n.get("date", ""),
                "image": n.get("imageUrl", ""),
            }
            for n in raw_news
        ]
        return {
            "news": news,
            "total_news": len(news),
        }

    @staticmethod
    def _parse_shopping(data: Dict) -> Dict[str, Any]:
        """Parseia resultados de shopping/produtos."""
        raw_products = data.get("shopping", [])
        products = [
            {
                "title": p.get("title", ""),
                "price": p.get("price", ""),
                "source": p.get("source", ""),
                "link": p.get("link", ""),
                "rating": p.get("rating"),
                "reviews": p.get("ratingCount"),
                "delivery": p.get("delivery", ""),
                "image": p.get("imageUrl", ""),
            }
            for p in raw_products
        ]
        return {
            "products": products,
            "total_products": len(products),
        }

    @staticmethod
    def _parse_images(data: Dict) -> Dict[str, Any]:
        """Parseia resultados de busca de imagens."""
        raw_images = data.get("images", [])
        images = [
            {
                "title": img.get("title", ""),
                "link": img.get("imageUrl", ""),
                "source": img.get("source", ""),
                "source_url": img.get("link", ""),
                "thumbnail": img.get("thumbnailUrl", ""),
                "width": img.get("imageWidth"),
                "height": img.get("imageHeight"),
            }
            for img in raw_images
        ]
        return {
            "images": images,
            "total_images": len(images),
        }
