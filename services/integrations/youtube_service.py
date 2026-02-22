# -*- coding: utf-8 -*-
"""
services/integrations/youtube_service.py
==========================================
Integração com YouTube Data API v3.

Operações:
  - search_videos(query, max_results)          → busca vídeos
  - get_video_details(video_id)                → detalhes de 1 vídeo
  - get_channel_info(channel_id_or_handle)     → info do canal
  - get_latest_videos(channel_id, max_results) → últimos vídeos de um canal
  - get_trending(region_code, max_results)      → vídeos em alta

Autenticação:
  - YOUTUBE_API_KEY → variável de ambiente (YouTube Data API v3 key)
  - Sem OAuth — apenas dados públicos

Rate limits (YouTube Data API v3):
  - 10.000 unidades/dia no plano gratuito
  - search.list = 100 unidades / call  (caro — use com parcimônia)
  - videos.list = 1 unidade  / call
  - channels.list = 1 unidade / call
"""

import os
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

from services.core import BaseService, register_service, ServiceUnavailableError

load_dotenv()

_YT_BASE = "https://www.googleapis.com/youtube/v3"

# Limite de resultados por chamada
_MAX_RESULTS_CAP = 25


def _iso_to_readable(duration: str) -> str:
    """
    Converte duração ISO 8601 (PT4M13S) para formato legível (4:13).
    """
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration or "")
    if not m:
        return duration
    h, mn, s = (int(g or 0) for g in m.groups())
    if h:
        return f"{h}:{mn:02d}:{s:02d}"
    return f"{mn}:{s:02d}"


def _format_count(n: Any) -> str:
    """Formata número grande: 1500000 → '1.5M'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return "N/A"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


@register_service("youtube")
class YouTubeService(BaseService):
    """
    YouTube Data API v3 service.

    Requer: YOUTUBE_API_KEY no .env
    """

    def __init__(self):
        super().__init__(name="youtube")
        self._api_key: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _initialize(self) -> None:
        self._api_key = os.getenv("YOUTUBE_API_KEY")
        if not self._api_key:
            raise ServiceUnavailableError(
                "YOUTUBE_API_KEY não encontrada nas variáveis de ambiente."
            )
        self._client = httpx.AsyncClient(timeout=10.0)
        self.logger.info("YouTubeService initialized")

    async def _health_check(self) -> bool:
        if not self._api_key or not self._client:
            return False
        try:
            resp = await self._client.get(
                f"{_YT_BASE}/videos",
                params={"part": "id", "chart": "mostPopular",
                        "maxResults": 1, "key": self._api_key},
            )
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

    async def search_videos(
        self,
        query: str,
        max_results: int = 5,
        order: str = "relevance",   # relevance | date | viewCount | rating
        region_code: str = "BR",
    ) -> List[Dict[str, Any]]:
        """
        Busca vídeos pelo termo de pesquisa.

        Args:
            query:       Termo de busca
            max_results: Máximo de resultados (cap: 25)
            order:       Critério de ordenação
            region_code: Código de região (BR, US, etc.)

        Returns:
            Lista de dicts com id, title, channel, published_at, thumbnail, url
        """
        if not self.is_initialized():
            await self.initialize()

        max_results = min(max_results, _MAX_RESULTS_CAP)
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": max_results,
            "order": order,
            "regionCode": region_code,
            "key": self._api_key,
        }

        data = await self._get(_YT_BASE + "/search", params)
        items = data.get("items", [])
        return [self._format_search_item(i) for i in items]

    async def get_video_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Retorna detalhes completos de um vídeo.

        Args:
            video_id: ID do vídeo (ex: 'dQw4w9WgXcQ')

        Returns:
            Dict com title, channel, views, likes, duration, description, url
        """
        if not self.is_initialized():
            await self.initialize()

        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": self._api_key,
        }
        data = await self._get(_YT_BASE + "/videos", params)
        items = data.get("items", [])
        if not items:
            return None
        return self._format_video_item(items[0])

    async def get_channel_info(self, channel: str) -> Optional[Dict[str, Any]]:
        """
        Busca informações de um canal pelo ID ou handle (@handle).

        Args:
            channel: ID do canal (UCxxxxxxx) ou handle (@nomecanal)

        Returns:
            Dict com id, name, subscribers, video_count, description, thumbnail
        """
        if not self.is_initialized():
            await self.initialize()

        # Handle (@username) ou ID (UC...)
        if channel.startswith("@"):
            params = {"part": "snippet,statistics", "forHandle": channel[1:], "key": self._api_key}
        elif channel.startswith("UC"):
            params = {"part": "snippet,statistics", "id": channel, "key": self._api_key}
        else:
            # Tenta como forHandle sem @
            params = {"part": "snippet,statistics", "forHandle": channel, "key": self._api_key}

        data = await self._get(_YT_BASE + "/channels", params)
        items = data.get("items", [])
        if not items:
            return None
        return self._format_channel_item(items[0])

    async def get_latest_videos(
        self, channel_id: str, max_results: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Retorna os vídeos mais recentes de um canal.

        Args:
            channel_id:  ID do canal (UCxxxxxxx)
            max_results: Máximo de resultados

        Returns:
            Lista de vídeos ordenados do mais recente ao mais antigo
        """
        if not self.is_initialized():
            await self.initialize()

        max_results = min(max_results, _MAX_RESULTS_CAP)
        params = {
            "part": "snippet",
            "channelId": channel_id,
            "type": "video",
            "order": "date",
            "maxResults": max_results,
            "key": self._api_key,
        }
        data = await self._get(_YT_BASE + "/search", params)
        items = data.get("items", [])
        return [self._format_search_item(i) for i in items]

    async def get_trending(
        self,
        region_code: str = "BR",
        max_results: int = 5,
        category_id: str = "0",   # 0=all, 10=music, 20=gaming, 28=tech
    ) -> List[Dict[str, Any]]:
        """
        Retorna vídeos em alta de uma região.

        Args:
            region_code:  Código de região (BR, US, PT...)
            max_results:  Máximo de resultados
            category_id:  ID de categoria (0=todos, 10=música, 20=games, 28=tech)

        Returns:
            Lista de vídeos em alta
        """
        if not self.is_initialized():
            await self.initialize()

        max_results = min(max_results, _MAX_RESULTS_CAP)
        params = {
            "part": "snippet,statistics,contentDetails",
            "chart": "mostPopular",
            "regionCode": region_code,
            "maxResults": max_results,
            "videoCategoryId": category_id,
            "key": self._api_key,
        }
        data = await self._get(_YT_BASE + "/videos", params)
        items = data.get("items", [])
        return [self._format_video_item(i) for i in items]

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ──────────────────────────────────────────────────────────────────────────

    async def _get(self, url: str, params: Dict) -> Dict:
        """Executa GET na YouTube API e retorna JSON."""
        try:
            resp = await self._client.get(url, params=params)
            if resp.status_code == 403:
                raise RuntimeError(
                    "YouTube API: quota excedida ou chave inválida (403)."
                )
            if resp.status_code == 400:
                raise RuntimeError(
                    f"YouTube API: requisição inválida (400): {resp.text[:200]}"
                )
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            raise RuntimeError("YouTube API: timeout na requisição.")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"YouTube API error: {e}")

    @staticmethod
    def _video_url(video_id: str) -> str:
        return f"https://youtu.be/{video_id}"

    @staticmethod
    def _channel_url(channel_id: str) -> str:
        return f"https://youtube.com/channel/{channel_id}"

    def _format_search_item(self, item: Dict) -> Dict[str, Any]:
        """Formata item de search.list."""
        snippet = item.get("snippet", {})
        vid_id = item.get("id", {})
        if isinstance(vid_id, dict):
            vid_id = vid_id.get("videoId", "")

        thumbs = snippet.get("thumbnails", {})
        thumbnail = (
            thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url")
            or thumbs.get("default", {}).get("url", "")
        )

        return {
            "id": vid_id,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "published_at": snippet.get("publishedAt", "")[:10],
            "description": snippet.get("description", "")[:200],
            "thumbnail": thumbnail,
            "url": self._video_url(vid_id) if vid_id else "",
        }

    def _format_video_item(self, item: Dict) -> Dict[str, Any]:
        """Formata item de videos.list (com statistics + contentDetails)."""
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        details = item.get("contentDetails", {})
        vid_id = item.get("id", "")

        thumbs = snippet.get("thumbnails", {})
        thumbnail = (
            thumbs.get("maxres", {}).get("url")
            or thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url", "")
        )

        return {
            "id": vid_id,
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "channel_id": snippet.get("channelId", ""),
            "published_at": snippet.get("publishedAt", "")[:10],
            "description": snippet.get("description", "")[:300],
            "thumbnail": thumbnail,
            "url": self._video_url(vid_id),
            "duration": _iso_to_readable(details.get("duration", "")),
            "duration_raw": details.get("duration", ""),
            "views": _format_count(stats.get("viewCount")),
            "views_raw": int(stats.get("viewCount", 0) or 0),
            "likes": _format_count(stats.get("likeCount")),
            "comments": _format_count(stats.get("commentCount")),
        }

    def _format_channel_item(self, item: Dict) -> Dict[str, Any]:
        """Formata item de channels.list."""
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        chan_id = item.get("id", "")

        thumbs = snippet.get("thumbnails", {})
        thumbnail = (
            thumbs.get("high", {}).get("url")
            or thumbs.get("medium", {}).get("url", "")
        )

        return {
            "id": chan_id,
            "name": snippet.get("title", ""),
            "handle": snippet.get("customUrl", ""),
            "description": snippet.get("description", "")[:300],
            "thumbnail": thumbnail,
            "url": self._channel_url(chan_id),
            "subscribers": _format_count(stats.get("subscriberCount")),
            "subscribers_raw": int(stats.get("subscriberCount", 0) or 0),
            "video_count": _format_count(stats.get("videoCount")),
            "view_count": _format_count(stats.get("viewCount")),
            "country": snippet.get("country", ""),
            "created_at": snippet.get("publishedAt", "")[:10],
        }
