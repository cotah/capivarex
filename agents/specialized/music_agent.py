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

logger = logging.getLogger(__name__)

MUSIC_INTENT_PROMPT = """You are a music assistant. \
Analyze the user's message and determine the intent.
Return a JSON object with:
- "action": one of "search_track", "search_artist", \
"search_album", "artist_top_tracks", "recommendations", \
"genres", "general_info"
- "query": the search query extracted from the message
- "artist_name": artist name if mentioned (optional)
- "genre": genre if mentioned (optional)

Examples:
- "toca Bohemian Rhapsody" -> \
{"action": "search_track", "query": "Bohemian Rhapsody"}
- "quem e o Queen" -> \
{"action": "search_artist", "query": "Queen"}
- "top musicas do Eminem" -> \
{"action": "artist_top_tracks", \
"query": "Eminem", "artist_name": "Eminem"}
- "recomenda rock" -> \
{"action": "recommendations", "genre": "rock"}
- "me indica umas musicas" -> \
{"action": "recommendations"}
- "album Thriller" -> \
{"action": "search_album", "query": "Thriller"}

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
    tracks: List[Dict],
) -> str:
    """Format a list of tracks for Telegram."""
    if not tracks:
        return "Nenhuma musica encontrada."

    lines = []
    for i, t in enumerate(tracks, 1):
        lines.append(
            f"{i}. *{t['name']}* — {t['artists']} "
            f"({t['duration']})"
        )
        lines.append(
            f"   [Ouvir no Spotify]({t['spotify_url']})"
        )
    return "\n".join(lines)


def _format_single_track(track: Dict) -> str:
    """Format a single track for Telegram."""
    lines = [
        f"*{track['name']}*",
        f"  {track['artists']}",
        f"  {track['album']}",
        f"  {track['duration']}",
        f"  Popularidade: {track['popularity']}/100",
        f"[Ouvir no Spotify]({track['spotify_url']})",
    ]
    return "\n".join(lines)


def _format_artist_response(artist: Dict) -> str:
    """Format artist info for Telegram."""
    followers = _format_number(artist["followers"])
    lines = [
        f"*{artist['name']}*",
    ]
    if artist.get("genres"):
        lines.append(f"  {artist['genres']}")
    lines.extend(
        [
            f"  {followers} seguidores",
            f"  Popularidade: "
            f"{artist['popularity']}/100",
            f"[Ver no Spotify]"
            f"({artist['spotify_url']})",
        ]
    )
    return "\n".join(lines)


def _format_album_response(album: Dict) -> str:
    """Format album info for Telegram."""
    lines = [
        f"*{album['name']}*",
        f"  {album['artists']}",
        f"  {album['release_date']}",
        f"  {album['total_tracks']} faixas",
        f"[Ver no Spotify]({album['spotify_url']})",
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
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "O servico Spotify nao esta "
                        "disponivel de momento."
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

            # ── Dispatch ──────────────────────────────
            if action == "search_track":
                return await self._search_tracks(
                    spotify, query
                )

            if action == "search_artist":
                return await self._search_artist(
                    spotify, query
                )

            if action == "search_album":
                return await self._search_album(
                    spotify, query
                )

            if action == "artist_top_tracks":
                return await self._artist_top_tracks(
                    spotify, artist_name or query
                )

            if action == "recommendations":
                return await self._recommendations(
                    spotify, genre
                )

            if action == "genres":
                return await self._list_genres(spotify)

            # general_info fallback: search track
            return await self._search_tracks(
                spotify, query
            )

        except Exception as e:
            self.logger.error(
                "MusicAgent error: %s",
                e,
                exc_info=True,
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Ocorreu um erro ao buscar musica. "
                    "Tente novamente."
                ),
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
                    max_completion_tokens=150,
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
        self, spotify, query: str
    ) -> AgentResponse:
        tracks = await spotify.search_tracks(query)
        if not tracks:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f'Nenhuma musica encontrada '
                    f'para "{query}".'
                ),
                data={"tracks": []},
            )
        text = _format_tracks_response(tracks)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"tracks": tracks},
        )

    async def _search_artist(
        self, spotify, query: str
    ) -> AgentResponse:
        artists = await spotify.search_artists(
            query, limit=1
        )
        if not artists:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f'Artista "{query}" nao encontrado.'
                ),
                data={"artists": []},
            )
        artist = artists[0]
        text = _format_artist_response(artist)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"artist": artist},
        )

    async def _search_album(
        self, spotify, query: str
    ) -> AgentResponse:
        albums = await spotify.search_albums(
            query, limit=3
        )
        if not albums:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f'Album "{query}" nao encontrado.'
                ),
                data={"albums": []},
            )
        lines = []
        for a in albums:
            lines.append(_format_album_response(a))
        text = "\n\n".join(lines)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"albums": albums},
        )

    async def _artist_top_tracks(
        self, spotify, artist_name: str
    ) -> AgentResponse:
        # First find the artist to get ID
        artists = await spotify.search_artists(
            artist_name, limit=1
        )
        if not artists:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    f'Artista "{artist_name}" '
                    f"nao encontrado."
                ),
                data={"tracks": []},
            )
        artist = artists[0]
        tracks = await spotify.get_artist_top_tracks(
            artist["id"]
        )
        header = (
            f"*Top musicas de {artist['name']}:*\n\n"
        )
        text = header + _format_tracks_response(tracks)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={
                "artist": artist,
                "tracks": tracks,
            },
        )

    async def _recommendations(
        self, spotify, genre: str
    ) -> AgentResponse:
        seed_genres = (
            [genre] if genre else None
        )
        tracks = await spotify.get_recommendations(
            seed_genres=seed_genres, limit=5
        )
        if not tracks:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Sem recomendacoes disponiveis.",
                data={"tracks": []},
            )
        header = "*Recomendacoes para voce:*\n\n"
        text = header + _format_tracks_response(tracks)
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"tracks": tracks},
        )

    async def _list_genres(
        self, spotify
    ) -> AgentResponse:
        genres = await spotify.get_available_genres()
        if not genres:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    "Nao foi possivel obter os generos."
                ),
                data={"genres": []},
            )
        text = (
            "*Generos disponiveis no Spotify:*\n\n"
            + ", ".join(genres[:50])
        )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"genres": genres},
        )
