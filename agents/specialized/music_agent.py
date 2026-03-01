"""
agents/specialized/music_agent.py
==================================
Music agent powered by SpotifyService.

Interprets the user's intent via GPT, calls the appropriate
SpotifyService method, and formats a Telegram-friendly response.

Capabilities:
  - Search tracks, artists, albums
  - Artist top tracks
  - Music recommendations by genre
  - Available genre listing
  - i18n: PT / EN / ES responses + market-aware search
"""

import json
import logging
from typing import Any, Dict, List

from agents.core import (
    AgentResponse,
    AgentStatus,
    BaseAgent,
    register_agent,
)
from services import get_service
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)

# ── Language → Spotify market mapping ─────────────
LANGUAGE_MARKET = {"pt": "BR", "en": "US", "es": "ES"}

MUSIC_INTENT_PROMPT = """You are a music assistant. \
Analyze the user's message and determine the intent.
Return a JSON object with:
- "action": one of "search_track", "search_artist", \
"search_album", "artist_top_tracks", "recommendations", \
"genres", "general_info"
- "query": the search query extracted from the message
- "artist_name": artist name if mentioned (optional)
- "genre": genre if mentioned (optional)
- "language": the language the user wrote in — \
one of "pt", "en", "es" (detect from the message text)

CRITICAL RULES for action selection:
- "search_artist": Use when the user asks WHO an \
artist is, or wants info ABOUT an artist. Examples: \
"quem é o X", "who is X", "quién es X", "fala sobre X", \
"tell me about X", "cuéntame sobre X".
- "artist_top_tracks": Use ONLY when the user \
explicitly asks for TOP/BEST/MOST POPULAR songs. \
Examples: "top músicas de X", "top tracks by X", \
"top canciones de X", "melhores músicas de X", \
"best songs by X", "mejores canciones de X".
- When in doubt between search_artist and \
artist_top_tracks, choose "search_artist".

Examples:
- "toca Bohemian Rhapsody" -> \
{{"action": "search_track", "query": "Bohemian Rhapsody", \
"language": "pt"}}
- "who is Queen" -> \
{{"action": "search_artist", "query": "Queen", \
"language": "en"}}
- "quem é o Eminem" -> \
{{"action": "search_artist", "query": "Eminem", \
"language": "pt"}}
- "quién es Eminem" -> \
{{"action": "search_artist", "query": "Eminem", \
"language": "es"}}
- "top musicas do Eminem" -> \
{{"action": "artist_top_tracks", \
"query": "Eminem", "artist_name": "Eminem", \
"language": "pt"}}
- "best songs by Drake" -> \
{{"action": "artist_top_tracks", \
"query": "Drake", "artist_name": "Drake", \
"language": "en"}}
- "recomenda rock" -> \
{{"action": "recommendations", "genre": "rock", \
"language": "pt"}}
- "recomienda pop" -> \
{{"action": "recommendations", "genre": "pop", \
"language": "es"}}
- "suggest me some music" -> \
{{"action": "recommendations", "language": "en"}}
- "album Thriller" -> \
{{"action": "search_album", "query": "Thriller", \
"language": "en"}}

User message: {message}
Respond ONLY with JSON, no markdown."""


def _format_number(n: int) -> str:
    """Format large numbers: 48000000 -> '48.0M'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def _format_tracks_response(
    tracks: List[Dict], lang: str = "en"
) -> str:
    """Format a list of tracks for Telegram."""
    if not tracks:
        return t("music_no_results", lang=lang)

    listen = t("music_listen_on_spotify", lang=lang)
    lines = []
    for i, tr in enumerate(tracks, 1):
        lines.append(
            f"{i}. *{tr['name']}* — {tr['artists']} "
            f"({tr['duration']})"
        )
        lines.append(
            f"   [{listen}]({tr['spotify_url']})"
        )
    return "\n".join(lines)


def _format_single_track(
    track: Dict, lang: str = "en"
) -> str:
    """Format a single track for Telegram."""
    listen = t("music_listen_on_spotify", lang=lang)
    popularity = t("music_popularity", lang=lang)
    lines = [
        f"*{track['name']}*",
        f"  {track['artists']}",
        f"  {track['album']}",
        f"  {track['duration']}",
        f"  {popularity}: {track['popularity']}/100",
        f"[{listen}]({track['spotify_url']})",
    ]
    return "\n".join(lines)


def _format_artist_response(
    artist: Dict, lang: str = "en"
) -> str:
    """Format artist info for Telegram."""
    followers = _format_number(artist["followers"])
    followers_label = t("music_followers", lang=lang)
    popularity = t("music_popularity", lang=lang)
    view = t("music_view_on_spotify", lang=lang)
    lines = [
        f"🎤 *{artist['name']}*",
    ]
    if artist.get("genres"):
        lines.append(f"  {artist['genres']}")
    lines.extend(
        [
            f"  {followers} {followers_label}",
            f"  {popularity}: "
            f"{artist['popularity']}/100",
            f"[{view}]"
            f"({artist['spotify_url']})",
        ]
    )
    return "\n".join(lines)


def _format_album_response(
    album: Dict, lang: str = "en"
) -> str:
    """Format album info for Telegram."""
    tracks_label = t("music_tracks_count", lang=lang)
    view = t("music_view_on_spotify", lang=lang)
    lines = [
        f"💿 *{album['name']}*",
        f"  {album['artists']}",
        f"  {album['release_date']}",
        f"  {album['total_tracks']} {tracks_label}",
        f"[{view}]({album['spotify_url']})",
    ]
    return "\n".join(lines)


@register_agent("music")
class MusicAgent(BaseAgent):
    """Music agent: search, discover and recommend music."""

    def __init__(self):
        super().__init__(
            name="music",
            description=(
                "Search tracks, artists, albums and "
                "get music recommendations via Spotify"
            ),
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Interpret user intent and call Spotify."""
        try:
            spotify = get_service("spotify")
            if not spotify:
                lang = get_user_lang(context)
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t(
                        "music_spotify_unavailable",
                        lang=lang,
                    ),
                    error="Spotify service not found",
                )

            if not spotify.is_initialized():
                await spotify.initialize()

            # ── Classify intent via GPT ───────────────
            intent = await self._classify_intent(prompt)

            action = intent.get("action", "general_info")
            query = intent.get("query", prompt)
            artist_name = intent.get("artist_name", "")
            genre = intent.get("genre", "")

            # ── Language: GPT-detected > context ──────
            gpt_lang = intent.get("language", "")
            if gpt_lang in ("pt", "en", "es"):
                lang = gpt_lang
            else:
                lang = get_user_lang(context)

            market = LANGUAGE_MARKET.get(lang, "US")

            # ── Dispatch ──────────────────────────────
            if action == "search_track":
                return await self._search_tracks(
                    spotify, query, lang, market
                )

            if action == "search_artist":
                return await self._search_artist(
                    spotify, query, lang, market
                )

            if action == "search_album":
                return await self._search_album(
                    spotify, query, lang, market
                )

            if action == "artist_top_tracks":
                return await self._artist_top_tracks(
                    spotify,
                    artist_name or query,
                    lang,
                    market,
                )

            if action == "recommendations":
                return await self._recommendations(
                    spotify, genre, lang, market
                )

            if action == "genres":
                return await self._list_genres(lang)

            # general_info fallback: search track
            return await self._search_tracks(
                spotify, query, lang, market
            )

        except Exception as e:
            self.logger.error(
                "MusicAgent error: %s",
                e,
                exc_info=True,
            )
            lang = get_user_lang(context)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("music_error", lang=lang),
                error=str(e),
            )

    def get_capabilities(self) -> List[str]:
        return [
            "search_tracks",
            "search_artists",
            "search_albums",
            "artist_top_tracks",
            "recommendations",
            "available_genres",
        ]

    # ──────────────────────────────────────────────────
    # INTENT CLASSIFICATION
    # ──────────────────────────────────────────────────

    async def _classify_intent(
        self, message: str
    ) -> Dict[str, Any]:
        """Use GPT to classify the music intent."""
        openai = get_service("openai")
        if not openai or not openai.is_initialized():
            # Fallback: treat as track search
            return {
                "action": "search_track",
                "query": message,
            }

        try:
            filled_prompt = MUSIC_INTENT_PROMPT.replace(
                "{message}", message
            )
            response = (
                await openai.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": filled_prompt,
                        },
                    ],
                    response_format={
                        "type": "json_object"
                    },
                    max_completion_tokens=200,
                    temperature=0.0,
                )
            )
            text = (
                response.choices[0].message.content or ""
            )
            return json.loads(text)
        except Exception as e:
            self.logger.warning(
                "Intent classification failed: %s — "
                "defaulting to search_track",
                e,
            )
            return {
                "action": "search_track",
                "query": message,
            }

    # ──────────────────────────────────────────────────
    # ACTION HANDLERS
    # ──────────────────────────────────────────────────

    async def _search_tracks(
        self,
        spotify,
        query: str,
        lang: str,
        market: str,
    ) -> AgentResponse:
        tracks = await spotify.search_tracks(
            query, limit=5
        )
        if not tracks:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "music_no_results_for",
                    lang=lang,
                    query=query,
                ),
                data={"tracks": []},
            )
        text = _format_tracks_response(tracks, lang)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"tracks": tracks},
        )

    async def _search_artist(
        self,
        spotify,
        query: str,
        lang: str,
        market: str,
    ) -> AgentResponse:
        artists = await spotify.search_artists(
            query, limit=1
        )
        if not artists:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "music_artist_not_found",
                    lang=lang,
                    query=query,
                ),
                data={"artists": []},
            )
        artist = artists[0]
        self.logger.debug(
            "Artist search result (lang=%s): %s",
            lang,
            artist,
        )
        # Always fetch full artist profile — search
        # results often lack followers/popularity data.
        artist_id = artist.get("id")
        if artist_id:
            try:
                artist = await spotify.get_artist(
                    artist_id
                )
                self.logger.debug(
                    "Full artist profile: %s", artist
                )
            except Exception:
                pass  # keep search result as fallback
        text = _format_artist_response(artist, lang)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"artist": artist},
        )

    async def _search_album(
        self,
        spotify,
        query: str,
        lang: str,
        market: str,
    ) -> AgentResponse:
        albums = await spotify.search_albums(
            query, limit=3
        )
        if not albums:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "music_album_not_found",
                    lang=lang,
                    query=query,
                ),
                data={"albums": []},
            )
        lines = []
        for a in albums:
            lines.append(
                _format_album_response(a, lang)
            )
        text = "\n\n".join(lines)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"albums": albums},
        )

    async def _artist_top_tracks(
        self,
        spotify,
        artist_name: str,
        lang: str,
        market: str,
    ) -> AgentResponse:
        tracks = await spotify.get_artist_top_tracks(
            artist_name, market=market
        )
        if not tracks:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "music_no_results_for",
                    lang=lang,
                    query=artist_name,
                ),
                data={"tracks": []},
            )
        header = t(
            "music_top_tracks_header",
            lang=lang,
            artist=artist_name,
        )
        text = header + _format_tracks_response(
            tracks, lang
        )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"tracks": tracks},
        )

    async def _recommendations(
        self,
        spotify,
        genre: str,
        lang: str,
        market: str,
    ) -> AgentResponse:
        seed_genres = (
            [genre] if genre else None
        )
        tracks = await spotify.get_recommendations(
            seed_genres=seed_genres,
            limit=5,
            market=market,
        )
        if not tracks:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=t(
                    "music_no_recommendations",
                    lang=lang,
                ),
                data={"tracks": []},
            )
        header = t(
            "music_recommendations_header", lang=lang
        )
        text = header + _format_tracks_response(
            tracks, lang
        )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"tracks": tracks},
        )

    async def _list_genres(
        self, lang: str
    ) -> AgentResponse:
        # Static list — /recommendations/available-genre-seeds
        # returns 404 with Client Credentials flow.
        genres = [
            "acoustic", "afrobeat", "alt-rock",
            "alternative", "ambient", "anime", "blues",
            "bossa-nova", "brazil", "breakbeat",
            "british", "chill", "classical", "club",
            "comedy", "country", "dance", "deep-house",
            "disco", "drum-and-bass", "dub", "dubstep",
            "edm", "electro", "electronic", "emo",
            "folk", "funk", "garage", "gospel",
            "goth", "grindcore", "groove", "grunge",
            "guitar", "happy", "hard-rock", "hardcore",
            "hardstyle", "heavy-metal", "hip-hop",
            "house", "indie", "indie-pop", "industrial",
            "j-pop", "j-rock", "jazz", "k-pop",
            "latin", "latino", "metal", "mpb",
            "new-age", "opera", "pagode", "party",
            "piano", "pop", "pop-film", "punk",
            "punk-rock", "r-n-b", "rainy-day", "reggae",
            "reggaeton", "rock", "rock-n-roll",
            "romance", "sad", "samba", "sertanejo",
            "show-tunes", "ska", "sleep", "soul",
            "soundtracks", "spanish", "study",
            "synth-pop", "tango", "techno", "trance",
            "trip-hop", "world-music",
        ]
        header = t("music_genres_header", lang=lang)
        text = header + ", ".join(genres)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"genres": genres},
        )
