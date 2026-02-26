# -*- coding: utf-8 -*-
"""
agents/specialized/youtube_agent.py

FIX [2025-02]: Região padrão alterada de "BR" para "IE" (Irlanda).
  ANTES: region = context.get("region_code", "BR")   → vídeos em português BR
  DEPOIS: region = context.get("region_code", "IE")  → vídeos relevantes para Irlanda

  O utilizador está em Dublin, IE. Trending "BR" nunca seria relevante.
  A busca de vídeos específicos (por query) não é afectada pela região —
  só o trending e os defaults de busca sem query específica mudam.
"""

import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

# ─── Intenções ────────────────────────────────────────────────────────────────
_TRENDING_WORDS = [
    "em alta",
    "trending",
    "populares",
    "mais vistos",
    "virais",
    "tendência",
    "tendencias",
]
_CHANNEL_WORDS = [
    "canal",
    "channel",
    "inscritos",
    "subscribers",
    "info do canal",
    "últimos vídeos do canal",
    "ultimos videos do canal",
]
_LATEST_WORDS = [
    "últimos vídeos",
    "ultimos videos",
    "recentes",
    "novidades",
    "últimas postagens",
    "novo video",
]
_DETAIL_WORDS = [
    "detalhes",
    "details",
    "info do vídeo",
    "sobre o vídeo",
    "esse vídeo",
    "estatísticas",
]
_SEARCH_WORDS = [
    "busca",
    "pesquisa",
    "procura",
    "search",
    "acha",
    "encontra",
    "vídeos de",
    "videos de",
    "vídeos sobre",
    "videos sobre",
    "youtube",
]

_CATEGORY_MAP = {
    "música": "10",
    "musica": "10",
    "music": "10",
    "games": "20",
    "gaming": "20",
    "jogos": "20",
    "tecnologia": "28",
    "tech": "28",
    "esporte": "17",
    "esportes": "17",
    "sport": "17",
    "notícias": "25",
    "noticias": "25",
    "news": "25",
    "entretenimento": "24",
    "entertainment": "24",
}

_RE_COUNT = re.compile(r"\b(top\s*)?(\d{1,2})\s*v[ií]deos?\b", re.I)
_RE_HANDLE = re.compile(r"@([\w\-.]{3,})")


def _extract_category(text: str) -> str:
    text_lower = text.lower()
    for kw, cat_id in _CATEGORY_MAP.items():
        if kw in text_lower:
            return cat_id
    return "0"


def _extract_count(text: str, default: int = 5) -> int:
    m = _RE_COUNT.search(text)
    if m:
        return min(int(m.group(2)), 25)
    return default


def _extract_query(text: str) -> str:
    cleaned = text
    for w in _SEARCH_WORDS + _TRENDING_WORDS:
        cleaned = re.sub(rf"\b{re.escape(w)}\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(?:no|do|no)\s+youtube\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(hoje|agora|brazil|brasil)\b", "", cleaned, flags=re.I)
    return cleaned.strip()


def _extract_channel_query(text: str) -> str:
    m = _RE_HANDLE.search(text)
    if m:
        return "@" + m.group(1)
    m2 = re.search(
        r"(?:canal|channel)\s+(.+?)(?:\s+(?:últimos|novo|info|vídeos|$))?$",
        text,
        re.I,
    )
    if m2:
        return m2.group(1).strip()
    return text.strip()


@register_agent("youtube")
class YouTubeAgent(BaseAgent):
    """YouTube agent — busca, detalhes, canais e trending."""

    def __init__(self):
        super().__init__(
            name="youtube",
            description="Busca vídeos, canais e tendências no YouTube",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        lang = get_user_lang(context)
        try:
            svc = get_service("youtube")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("youtube_service_unavailable", lang=lang),
                    error="YouTubeService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            prompt_lower = (prompt or "").lower()
            action = context.get("action")

            if action == "search":
                return await self._handle_search(
                    svc, context.get("query", prompt), context
                )
            if action == "trending":
                return await self._handle_trending(svc, context)
            if action == "channel":
                return await self._handle_channel(
                    svc, context.get("channel", prompt), context
                )
            if action == "latest":
                return await self._handle_latest(
                    svc, context.get("channel_id", ""), context
                )
            if action == "detail":
                return await self._handle_detail(svc, context.get("video_id", ""))

            if any(w in prompt_lower for w in _DETAIL_WORDS):
                video_id = self._extract_video_id(prompt)
                if video_id:
                    return await self._handle_detail(svc, video_id)

            if "youtu" in prompt_lower:
                video_id = self._extract_video_id(prompt)
                if video_id:
                    return await self._handle_detail(svc, video_id)

            if any(w in prompt_lower for w in _LATEST_WORDS) and any(
                w in prompt_lower for w in _CHANNEL_WORDS
            ):
                chan = _extract_channel_query(prompt)
                return await self._handle_latest_by_name(svc, chan, context)

            if any(w in prompt_lower for w in _CHANNEL_WORDS):
                chan = _extract_channel_query(prompt)
                return await self._handle_channel(svc, chan, context)

            if any(w in prompt_lower for w in _TRENDING_WORDS):
                return await self._handle_trending(svc, context, prompt)

            if any(w in prompt_lower for w in _SEARCH_WORDS):
                query = _extract_query(prompt)
                return await self._handle_search(svc, query, context, prompt)

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
        # FIX: default "IE" (Irlanda) em vez de "BR" (Brasil)
        region = context.get("region_code", "IE")
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
        # FIX: default "IE" em vez de "BR"
        region = context.get("region_code", "IE")
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
        return AgentResponse(status=AgentStatus.SUCCESS, response=msg, data=info)

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
            lines.append(f"{i}. [{v['title']}]({v['url']})\n   📅 {v['published_at']}")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"videos": videos},
        )

    async def _handle_latest_by_name(self, svc, channel_name, context):
        info = await svc.get_channel_info(channel_name)
        if not info:
            return await self._handle_search(svc, f"canal {channel_name}", context)
        return await self._handle_latest(svc, info["id"], context)

    async def _handle_detail(self, svc: Any, video_id: str) -> AgentResponse:
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
        return AgentResponse(status=AgentStatus.SUCCESS, response=msg, data=video)

    def _extract_video_id(self, text: str) -> Optional[str]:
        m = re.search(
            r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/|v/))([a-zA-Z0-9_-]{11})",
            text,
        )
        if m:
            return m.group(1)
        m2 = re.search(r"\b([a-zA-Z0-9_-]{11})\b", text)
        if m2:
            candidate = m2.group(1)
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
