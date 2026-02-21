# -*- coding: utf-8 -*-
"""
agents/specialized/youtube_agent.py
======================================
YouTubeAgent — busca vídeos, detalhes, canais e tendências.

Exemplos de queries:
  - "Busca vídeos de Python no YouTube"
  - "Últimos vídeos do canal Código Fonte TV"
  - "Vídeos em alta hoje no Brasil"
  - "Detalhes do vídeo dQw4w9WgXcQ"
  - "Info do canal @FilipeDeschamps"
  - "Trending de música no YouTube"
  - "Vídeos mais vistos de IA"
"""

import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

# ─── Intenções ────────────────────────────────────────────────────────────────

_TRENDING_WORDS = [
    "em alta", "trending", "populares", "mais vistos", "virais",
    "tendência", "tendencias",
]
_CHANNEL_WORDS = [
    "canal", "channel", "inscritos", "subscribers", "info do canal",
    "últimos vídeos do canal", "ultimos videos do canal",
]
_LATEST_WORDS = [
    "últimos vídeos", "ultimos videos", "recentes", "novidades",
    "últimas postagens", "novo video",
]
_DETAIL_WORDS = [
    "detalhes", "details", "info do vídeo", "sobre o vídeo",
    "esse vídeo", "estatísticas",
]
_SEARCH_WORDS = [
    "busca", "pesquisa", "procura", "search", "acha", "encontra",
    "vídeos de", "videos de", "vídeos sobre", "videos sobre",
    "youtube",
]

# IDs de categoria para trending
_CATEGORY_MAP = {
    "música": "10", "musica": "10", "music": "10",
    "games": "20", "gaming": "20", "jogos": "20",
    "tecnologia": "28", "tech": "28",
    "esporte": "17", "esportes": "17", "sport": "17",
    "notícias": "25", "noticias": "25", "news": "25",
    "entretenimento": "24", "entertainment": "24",
}

# Regex para extrair video ID de URL ou ID direto
_RE_VIDEO_ID = re.compile(
    r"(?:youtu\.be/|youtube\.com/watch\?v=|/v/|embed/)([a-zA-Z0-9_-]{11})"
    r"|(?<!\w)([a-zA-Z0-9_-]{11})(?!\w)"
)

# Regex para extrair handle (@handle) ou canal
_RE_HANDLE = re.compile(r"@([\w\-.]{3,})")
_RE_CHANNEL_ID = re.compile(r"\b(UC[a-zA-Z0-9_-]{22})\b")

# Número de resultados: "5 vídeos", "top 3"
_RE_COUNT = re.compile(r"\b(top\s*)?(\d{1,2})\s*v[ií]deos?\b", re.I)


def _extract_category(text: str) -> str:
    """Retorna ID de categoria a partir do texto."""
    text_lower = text.lower()
    for kw, cat_id in _CATEGORY_MAP.items():
        if kw in text_lower:
            return cat_id
    return "0"  # todos


def _extract_count(text: str, default: int = 5) -> int:
    m = _RE_COUNT.search(text)
    if m:
        return min(int(m.group(2)), 25)
    return default


def _extract_query(text: str) -> str:
    """Remove palavras de comando e retorna o termo de busca."""
    cleaned = text
    # Remove palavras de comando
    for w in _SEARCH_WORDS + _TRENDING_WORDS:
        cleaned = re.sub(rf"\b{re.escape(w)}\b", "", cleaned, flags=re.I)
    # Remove "no youtube", "do youtube"
    cleaned = re.sub(r"\b(?:no|do|no)\s+youtube\b", "", cleaned, flags=re.I)
    # Remove "hoje", "agora"
    cleaned = re.sub(r"\b(hoje|agora|brazil|brasil)\b", "", cleaned, flags=re.I)
    return cleaned.strip()


def _extract_channel_query(text: str) -> str:
    """Extrai nome ou handle do canal do texto."""
    # Handle @xxx
    m = _RE_HANDLE.search(text)
    if m:
        return "@" + m.group(1)
    # "canal XYZ" / "do canal XYZ"
    m2 = re.search(r"(?:canal|channel)\s+(.+?)(?:\s+(?:últimos|novo|info|vídeos|$))?$",
                   text, re.I)
    if m2:
        return m2.group(1).strip()
    return text.strip()


@register_agent("youtube")
class YouTubeAgent(BaseAgent):
    """
    YouTube agent — busca, detalhes, canais e trending.

    Intents:
        search   → busca vídeos por termo
        trending → vídeos em alta (por região/categoria)
        channel  → informações de canal
        latest   → últimos vídeos de canal
        detail   → detalhes de vídeo específico
    """

    def __init__(self):
        super().__init__(
            name="youtube",
            description="Busca vídeos, canais e tendências no YouTube",
        )

    async def execute(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        try:
            svc = get_service("youtube")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço do YouTube não disponível.",
                    error="YouTubeService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            prompt_lower = (prompt or "").lower()

            # ── Context override ──────────────────────────────────────────────
            action = context.get("action")
            if action == "search":
                return await self._handle_search(svc, context.get("query", prompt), context)
            if action == "trending":
                return await self._handle_trending(svc, context)
            if action == "channel":
                return await self._handle_channel(svc, context.get("channel", prompt), context)
            if action == "latest":
                return await self._handle_latest(svc, context.get("channel_id", ""), context)
            if action == "detail":
                return await self._handle_detail(svc, context.get("video_id", ""))

            # ── Intent: detalhe de vídeo ──────────────────────────────────────
            if any(w in prompt_lower for w in _DETAIL_WORDS):
                video_id = self._extract_video_id(prompt)
                if video_id:
                    return await self._handle_detail(svc, video_id)

            # URL direta de vídeo no prompt
            if "youtu" in prompt_lower:
                video_id = self._extract_video_id(prompt)
                if video_id:
                    return await self._handle_detail(svc, video_id)

            # ── Intent: últimos vídeos de canal ───────────────────────────────
            if any(w in prompt_lower for w in _LATEST_WORDS) and \
               any(w in prompt_lower for w in _CHANNEL_WORDS):
                chan = _extract_channel_query(prompt)
                return await self._handle_latest_by_name(svc, chan, context)

            # ── Intent: info de canal ─────────────────────────────────────────
            if any(w in prompt_lower for w in _CHANNEL_WORDS):
                chan = _extract_channel_query(prompt)
                return await self._handle_channel(svc, chan, context)

            # ── Intent: trending ──────────────────────────────────────────────
            if any(w in prompt_lower for w in _TRENDING_WORDS):
                return await self._handle_trending(svc, context, prompt)

            # ── Intent: busca (padrão) ────────────────────────────────────────
            if any(w in prompt_lower for w in _SEARCH_WORDS):
                query = _extract_query(prompt)
                return await self._handle_search(svc, query, context, prompt)

            # ── Fallback: trata o prompt como query de busca ──────────────────
            return await self._handle_search(svc, prompt, context)

        except RuntimeError as e:
            msg = str(e)
            if "quota" in msg.lower() or "403" in msg:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="⚠️ Quota da YouTube API excedida. Tente novamente amanhã.",
                    error=msg,
                )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao consultar o YouTube: {msg}",
                error=msg,
            )
        except Exception as e:
            self.logger.error("YouTubeAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro inesperado ao consultar o YouTube.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_search(
        self,
        svc: Any,
        query: str,
        context: Dict,
        raw_prompt: str = "",
    ) -> AgentResponse:
        if not query or len(query.strip()) < 2:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="O que você quer buscar no YouTube?",
                error="Empty query",
            )

        max_results = context.get("max_results") or _extract_count(raw_prompt, 5)
        region = context.get("region_code", "BR")
        order = context.get("order", "relevance")

        videos = await svc.search_videos(
            query=query.strip(),
            max_results=max_results,
            order=order,
            region_code=region,
        )

        if not videos:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"Nenhum vídeo encontrado para *{query}*.",
                data={"videos": [], "query": query},
            )

        lines = [f"🎬 **YouTube: {query}** ({len(videos)} resultado(s))\n"]
        for i, v in enumerate(videos, 1):
            lines.append(
                f"{i}. [{v['title']}]({v['url']})\n"
                f"   📺 {v['channel']} · 📅 {v['published_at']}"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"videos": videos, "query": query},
        )

    async def _handle_trending(
        self,
        svc: Any,
        context: Dict,
        raw_prompt: str = "",
    ) -> AgentResponse:
        region = context.get("region_code", "BR")
        category_id = context.get("category_id") or _extract_category(raw_prompt)
        max_results = context.get("max_results", 5)

        videos = await svc.get_trending(
            region_code=region,
            max_results=max_results,
            category_id=category_id,
        )

        if not videos:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Nenhum vídeo em alta encontrado.",
                data={"videos": []},
            )

        cat_labels = {v: k.title() for k, v in _CATEGORY_MAP.items()}
        cat_label = cat_labels.get(category_id, "Todos")
        lines = [f"🔥 **Em alta no YouTube — {cat_label} ({region})**\n"]

        for i, v in enumerate(videos, 1):
            lines.append(
                f"{i}. [{v['title']}]({v['url']})\n"
                f"   👁️ {v['views']} views · ⏱️ {v['duration']} · 📺 {v['channel']}"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"videos": videos},
        )

    async def _handle_channel(
        self, svc: Any, channel: str, context: Dict
    ) -> AgentResponse:
        info = await svc.get_channel_info(channel)

        if not info:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Canal *{channel}* não encontrado.",
                error="Channel not found",
            )

        handle = f" ({info['handle']})" if info.get("handle") else ""
        country = f" 🌍 {info['country']}" if info.get("country") else ""

        msg = (
            f"📺 **{info['name']}**{handle}\n"
            f"👥 {info['subscribers']} inscritos · "
            f"🎬 {info['video_count']} vídeos{country}\n"
            f"🔗 {info['url']}\n"
        )
        if info.get("description"):
            msg += f"\n_{info['description'][:200]}_"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=msg,
            data=info,
        )

    async def _handle_latest(
        self, svc: Any, channel_id: str, context: Dict
    ) -> AgentResponse:
        max_results = context.get("max_results", 5)
        videos = await svc.get_latest_videos(channel_id, max_results)

        if not videos:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Nenhum vídeo recente encontrado.",
                data={"videos": []},
            )

        lines = [f"📹 **Últimos vídeos do canal** ({len(videos)})\n"]
        for i, v in enumerate(videos, 1):
            lines.append(
                f"{i}. [{v['title']}]({v['url']})\n"
                f"   📅 {v['published_at']}"
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"videos": videos},
        )

    async def _handle_latest_by_name(
        self, svc: Any, channel_name: str, context: Dict
    ) -> AgentResponse:
        """Busca canal por nome/handle, depois pega últimos vídeos."""
        info = await svc.get_channel_info(channel_name)
        if not info:
            # Fallback: busca vídeos do canal pelo nome
            return await self._handle_search(
                svc, f"canal {channel_name}", context
            )
        return await self._handle_latest(svc, info["id"], context)

    async def _handle_detail(
        self, svc: Any, video_id: str
    ) -> AgentResponse:
        if not video_id:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Informe o ID ou URL do vídeo.",
                error="No video ID",
            )

        video = await svc.get_video_details(video_id)
        if not video:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Vídeo `{video_id}` não encontrado.",
                error="Video not found",
            )

        msg = (
            f"🎬 **{video['title']}**\n"
            f"📺 {video['channel']} · 📅 {video['published_at']}\n"
            f"👁️ {video['views']} views · 👍 {video['likes']} · "
            f"💬 {video['comments']} comentários · ⏱️ {video['duration']}\n"
            f"🔗 {video['url']}\n"
        )
        if video.get("description"):
            msg += f"\n_{video['description'][:200]}_"

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=msg,
            data=video,
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _extract_video_id(self, text: str) -> Optional[str]:
        """Extrai ID de vídeo de URL ou texto."""
        # URL completa
        m = re.search(
            r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|v/))([a-zA-Z0-9_-]{11})",
            text,
        )
        if m:
            return m.group(1)
        # ID direto (11 chars alfanuméricos)
        m2 = re.search(r"\b([a-zA-Z0-9_-]{11})\b", text)
        if m2:
            candidate = m2.group(1)
            # Filtra IDs que claramente não são YouTube (ex: "dQw4w9WgXcQ")
            if re.match(r"^[a-zA-Z0-9_-]{11}$", candidate):
                return candidate
        return None

    def get_capabilities(self) -> List[str]:
        return [
            "search_videos",
            "get_video_details",
            "get_channel_info",
            "get_latest_videos",
            "get_trending",
        ]
