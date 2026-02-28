"""
tests/test_music_agent.py
==========================
Unit tests for MusicAgent.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.core import AgentStatus
from agents.specialized.music_agent import (
    MusicAgent,
    _format_number,
    _format_tracks_response,
    _format_artist_response,
    _format_album_response,
)


@pytest.fixture
def music_agent():
    return MusicAgent()


@pytest.fixture
def mock_spotify():
    """Mock SpotifyService with common methods."""
    svc = AsyncMock()
    svc.is_initialized = MagicMock(return_value=True)
    svc.initialize = AsyncMock()
    return svc


@pytest.fixture
def sample_track():
    return {
        "type": "track",
        "id": "t1",
        "name": "Bohemian Rhapsody",
        "artists": "Queen",
        "album": "A Night at the Opera",
        "album_image": "https://img.com/album.jpg",
        "duration": "5:54",
        "duration_ms": 354000,
        "popularity": 92,
        "preview_url": "https://preview.url",
        "spotify_url": (
            "https://open.spotify.com/track/t1"
        ),
        "uri": "spotify:track:t1",
    }


@pytest.fixture
def sample_artist():
    return {
        "type": "artist",
        "id": "a1",
        "name": "Queen",
        "genres": "rock, classic rock",
        "popularity": 89,
        "followers": 48000000,
        "image": "https://img.com/queen.jpg",
        "spotify_url": (
            "https://open.spotify.com/artist/a1"
        ),
        "uri": "spotify:artist:a1",
    }


# -- Formatting helpers ----------------------------------------


class TestFormatNumber:
    def test_millions(self):
        assert _format_number(48000000) == "48.0M"

    def test_thousands(self):
        assert _format_number(1500) == "1.5K"

    def test_small(self):
        assert _format_number(42) == "42"


class TestFormatTracksResponse:
    def test_empty_list(self):
        result = _format_tracks_response([])
        assert "Nenhuma" in result

    def test_single_track(self, sample_track):
        result = _format_tracks_response([sample_track])
        assert "Bohemian Rhapsody" in result
        assert "Queen" in result
        assert "Ouvir no Spotify" in result

    def test_multiple_tracks(self, sample_track):
        tracks = [sample_track, sample_track]
        result = _format_tracks_response(tracks)
        assert "1." in result
        assert "2." in result


class TestFormatArtistResponse:
    def test_format(self, sample_artist):
        result = _format_artist_response(sample_artist)
        assert "Queen" in result
        assert "48.0M" in result
        assert "Ver no Spotify" in result


class TestFormatAlbumResponse:
    def test_format(self):
        album = {
            "type": "album",
            "id": "al1",
            "name": "Thriller",
            "artists": "Michael Jackson",
            "release_date": "1982-11-30",
            "total_tracks": 9,
            "image": "img",
            "spotify_url": "https://open.spotify.com/album/al1",
        }
        result = _format_album_response(album)
        assert "Thriller" in result
        assert "Michael Jackson" in result
        assert "9 faixas" in result


# -- Agent execution ------------------------------------------


class TestMusicAgentExecution:
    @pytest.mark.asyncio
    async def test_search_track_success(
        self, music_agent, mock_spotify, sample_track
    ):
        """Search track returns formatted response."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[sample_track]
        )

        mock_openai = MagicMock()
        mock_openai.is_initialized = MagicMock(
            return_value=True
        )
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"action": "search_track", '
                        '"query": "Bohemian Rhapsody"}'
                    )
                )
            )
        ]
        mock_openai.client = MagicMock()
        mock_openai.client.chat.completions.create = (
            AsyncMock(return_value=mock_completion)
        )

        def _get_svc(name):
            if name == "spotify":
                return mock_spotify
            if name == "openai":
                return mock_openai
            return None

        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            side_effect=_get_svc,
        ):
            result = await music_agent.execute(
                "busca Bohemian Rhapsody", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Bohemian Rhapsody" in result.response
        assert result.data.get("tracks")

    @pytest.mark.asyncio
    async def test_search_artist_success(
        self,
        music_agent,
        mock_spotify,
        sample_artist,
    ):
        """Search artist returns formatted response."""
        mock_spotify.search_artists = AsyncMock(
            return_value=[sample_artist]
        )

        mock_openai = MagicMock()
        mock_openai.is_initialized = MagicMock(
            return_value=True
        )
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"action": "search_artist", '
                        '"query": "Queen"}'
                    )
                )
            )
        ]
        mock_openai.client = MagicMock()
        mock_openai.client.chat.completions.create = (
            AsyncMock(return_value=mock_completion)
        )

        def _get_svc(name):
            if name == "spotify":
                return mock_spotify
            if name == "openai":
                return mock_openai
            return None

        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            side_effect=_get_svc,
        ):
            result = await music_agent.execute(
                "quem e Queen", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Queen" in result.response

    @pytest.mark.asyncio
    async def test_spotify_unavailable(
        self, music_agent
    ):
        """Returns error when Spotify is unavailable."""
        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            return_value=None,
        ):
            result = await music_agent.execute(
                "busca musica", {}
            )

        assert result.status == AgentStatus.ERROR
        assert "Spotify" in result.response

    @pytest.mark.asyncio
    async def test_no_results(
        self, music_agent, mock_spotify
    ):
        """Returns message when no results found."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[]
        )

        mock_openai = MagicMock()
        mock_openai.is_initialized = MagicMock(
            return_value=True
        )
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"action": "search_track", '
                        '"query": "xyz"}'
                    )
                )
            )
        ]
        mock_openai.client = MagicMock()
        mock_openai.client.chat.completions.create = (
            AsyncMock(return_value=mock_completion)
        )

        def _get_svc(name):
            if name == "spotify":
                return mock_spotify
            if name == "openai":
                return mock_openai
            return None

        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            side_effect=_get_svc,
        ):
            result = await music_agent.execute(
                "busca xyz", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Nenhuma" in result.response

    @pytest.mark.asyncio
    async def test_exception_handling(
        self, music_agent, mock_spotify
    ):
        """Agent handles exceptions gracefully."""
        mock_spotify.search_tracks = AsyncMock(
            side_effect=RuntimeError("API down")
        )

        # No openai service → fallback to search_track
        def _get_svc(name):
            if name == "spotify":
                return mock_spotify
            return None

        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            side_effect=_get_svc,
        ):
            result = await music_agent.execute(
                "busca algo", {}
            )

        assert result.status == AgentStatus.ERROR
        assert "erro" in result.response.lower()

    @pytest.mark.asyncio
    async def test_recommendations(
        self, music_agent, mock_spotify, sample_track
    ):
        """Recommendations action returns tracks."""
        mock_spotify.get_recommendations = AsyncMock(
            return_value=[sample_track]
        )

        mock_openai = MagicMock()
        mock_openai.is_initialized = MagicMock(
            return_value=True
        )
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"action": "recommendations",'
                        ' "genre": "rock"}'
                    )
                )
            )
        ]
        mock_openai.client = MagicMock()
        mock_openai.client.chat.completions.create = (
            AsyncMock(return_value=mock_completion)
        )

        def _get_svc(name):
            if name == "spotify":
                return mock_spotify
            if name == "openai":
                return mock_openai
            return None

        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            side_effect=_get_svc,
        ):
            result = await music_agent.execute(
                "recomenda rock", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Recomendacoes" in result.response

    @pytest.mark.asyncio
    async def test_artist_top_tracks(
        self, music_agent, mock_spotify, sample_track
    ):
        """Top tracks action finds artist then tracks."""
        mock_spotify.search_artists = AsyncMock(
            return_value=[
                {
                    "id": "a1",
                    "name": "Eminem",
                    "genres": "hip-hop",
                    "popularity": 95,
                    "followers": 70000000,
                    "image": "",
                    "spotify_url": "url",
                    "uri": "uri",
                }
            ]
        )
        mock_spotify.get_artist_top_tracks = AsyncMock(
            return_value=[sample_track]
        )

        mock_openai = MagicMock()
        mock_openai.is_initialized = MagicMock(
            return_value=True
        )
        mock_completion = MagicMock()
        mock_completion.choices = [
            MagicMock(
                message=MagicMock(
                    content=(
                        '{"action": '
                        '"artist_top_tracks",'
                        ' "query": "Eminem",'
                        ' "artist_name": "Eminem"}'
                    )
                )
            )
        ]
        mock_openai.client = MagicMock()
        mock_openai.client.chat.completions.create = (
            AsyncMock(return_value=mock_completion)
        )

        def _get_svc(name):
            if name == "spotify":
                return mock_spotify
            if name == "openai":
                return mock_openai
            return None

        with patch(
            "agents.specialized.music_agent"
            ".get_service",
            side_effect=_get_svc,
        ):
            result = await music_agent.execute(
                "top musicas do Eminem", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Eminem" in result.response


class TestCapabilities:
    def test_get_capabilities(self, music_agent):
        caps = music_agent.get_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0
        assert "search_tracks" in caps
        assert "recommendations" in caps
