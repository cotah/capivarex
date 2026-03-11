"""
Media Cast Agent — play content on TV.

Combines YouTube search + SmartThings TV control + cast-ready deep links.
Handles intents like:
- "play X on TV"
- "put YouTube video Y on TV"
- "turn on TV and play Z"
"""

import logging
import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)

# Regex patterns for media cast intent
_RE_PLAY_ON_TV = re.compile(
    r"(?:p[oõ]e|coloca|play|reproduz[a-z]*|toca|assistir|watch|ver|pon)\s+"
    r"(.+?)\s+"
    r"(?:na\s+(?:tv|televis[aã]o|tela)"
    r"|on\s+(?:tv|television|screen|chromecast)"
    r"|en\s+(?:la\s+)?(?:tv|televisi[oó]n))",
    re.IGNORECASE,
)

_RE_TURN_ON_TV = re.compile(
    r"(?:liga|turn\s+on|enciende|ligar)\s+"
    r"(?:(?:a|the|la)\s+)?(?:tv|televis[aã]o|televisi[oó]n)",
    re.IGNORECASE,
)

_RE_YOUTUBE_SEARCH = re.compile(
    r"(?:youtube|yt)\s+(.+)",
    re.IGNORECASE,
)


@register_agent("media_cast")
class MediaCastAgent(BaseAgent):
    """
    Media Cast agent — finds content and helps cast to TV.

    Flow:
    1. Parse intent (play on TV, turn on TV, search)
    2. If TV control needed → delegate to SmartThings
    3. If content search needed → use YouTube API
    4. Return cast-ready response with deep links
    """

    def __init__(self):
        super().__init__(
            name="media_cast",
            description=(
                "Play content on TV, cast YouTube videos, "
                "turn on/off TV, media control"
            ),
        )

    async def execute(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        lang = get_user_lang(context)
        texto = prompt.strip()

        # ── 1. Turn on TV + play content ──────────────────────
        # "liga a TV e põe X no YouTube"
        m_play = _RE_PLAY_ON_TV.search(texto)
        has_turn_on = bool(_RE_TURN_ON_TV.search(texto))

        if has_turn_on:
            tv_result = await self._turn_on_tv(context, lang)
        else:
            tv_result = None

        # ── 2. Find content to play ───────────────────────────
        search_query = None
        if m_play:
            search_query = m_play.group(1).strip()
        elif not has_turn_on:
            # Try to extract any content mention
            m_yt = _RE_YOUTUBE_SEARCH.search(texto)
            if m_yt:
                search_query = m_yt.group(1).strip()
            else:
                # Fallback: try to use the whole text as search
                search_query = self._extract_content_query(texto)

        if search_query:
            videos = await self._search_youtube(search_query, lang)
            if videos:
                msg = self._build_cast_response(
                    videos, search_query, tv_result, lang
                )
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=msg,
                    data={
                        "videos": videos,
                        "tv_turned_on": has_turn_on,
                    },
                )
            else:
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=t(
                        "media_no_results", lang=lang, query=search_query
                    ),
                )

        # ── 3. Just turn on TV (no content) ───────────────────
        if tv_result:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=tv_result,
            )

        # ── 4. Fallback ──────────────────────────────────────
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=t("media_cast_help", lang=lang),
        )

    async def _turn_on_tv(
        self, context: Dict[str, Any], lang: str
    ) -> Optional[str]:
        """Turn on TV via SmartThings if available."""
        try:
            from agents.core import get_agent

            smarthome = get_agent("smarthome")
            if smarthome:
                result = await smarthome.process(
                    "turn on the TV", context
                )
                if result.status == AgentStatus.SUCCESS:
                    return t("media_tv_turned_on", lang=lang)
        except Exception as e:
            logger.warning("Failed to turn on TV: %s", e)
        return None

    async def _search_youtube(
        self, query: str, lang: str, max_results: int = 3
    ) -> List[Dict[str, Any]]:
        """Search YouTube for videos matching query."""
        try:
            youtube_svc = get_service("youtube")
            if not youtube_svc:
                return []
            if not youtube_svc.is_initialized():
                await youtube_svc.initialize()

            results = await youtube_svc.search_videos(
                query=query, max_results=max_results
            )
            return results or []
        except Exception as e:
            logger.warning("YouTube search failed: %s", e)
            return []

    @staticmethod
    def _extract_content_query(text: str) -> Optional[str]:
        """Try to extract content query from text."""
        # Remove TV-related words
        cleaned = re.sub(
            r"\b(tv|televis[aã]o|television|chromecast|cast|screen|tela"
            r"|liga[r]?|turn\s+on|p[oõ]e|coloca|play|assistir|watch"
            r"|na|no|on|the|a|o)\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
        cleaned = " ".join(cleaned.split()).strip()
        return cleaned if len(cleaned) > 2 else None

    @staticmethod
    def _build_cast_response(
        videos: List[Dict],
        query: str,
        tv_msg: Optional[str],
        lang: str,
    ) -> str:
        """Build response with video results and cast links."""
        parts = []

        if tv_msg:
            parts.append(tv_msg + "\n")

        parts.append(t("media_found_videos", lang=lang, query=query))

        for i, video in enumerate(videos[:3], 1):
            title = video.get("title", "Unknown")
            channel = video.get("channel", "")
            duration = video.get("duration", "")
            views = video.get("views", "")
            video_id = video.get("id", "")
            video_url = video.get("url", "")

            line = f"\n{i}. 🎬 **{title}**"
            if channel:
                line += f"\n   📺 {channel}"
            if duration:
                line += f" | ⏱ {duration}"
            if views:
                line += f" | 👁 {views}"

            url = video_url or (
                f"https://www.youtube.com/watch?v={video_id}"
                if video_id
                else ""
            )
            if url:
                line += f"\n   [▶️ {t('media_watch', lang=lang)}]({url})"

            parts.append(line)

        parts.append("\n" + t("media_cast_tip", lang=lang))

        return "\n".join(parts)
