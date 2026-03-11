"""
tests/test_music_agent.py
==========================
Unit tests for MusicAgent with i18n support.
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
    def test_empty_list_pt(self):
        result = _format_tracks_response([], lang="pt")
        assert "Nenhuma" in result

    def test_empty_list_en(self):
        result = _format_tracks_response([], lang="en")
        assert "No music found" in result

    def test_empty_list_es(self):
        result = _format_tracks_response([], lang="es")
        assert "No se encontró" in result

    def test_single_track_pt(self, sample_track):
        result = _format_tracks_response(
            [sample_track], lang="pt"
        )
        assert "Bohemian Rhapsody" in result
        assert "Queen" in result
        assert "Ouvir no Spotify" in result

    def test_single_track_en(self, sample_track):
        result = _format_tracks_response(
            [sample_track], lang="en"
        )
        assert "Bohemian Rhapsody" in result
        assert "Listen on Spotify" in result

    def test_single_track_es(self, sample_track):
        result = _format_tracks_response(
            [sample_track], lang="es"
        )
        assert "Bohemian Rhapsody" in result
        assert "Escuchar en Spotify" in result

    def test_multiple_tracks(self, sample_track):
        tracks = [sample_track, sample_track]
        result = _format_tracks_response(
            tracks, lang="en"
        )
        assert "1." in result
        assert "2." in result


class TestFormatArtistResponse:
    def test_format_pt(self, sample_artist):
        result = _format_artist_response(
            sample_artist, lang="pt"
        )
        assert "Queen" in result
        assert "48.0M" in result
        assert "seguidores" in result
        assert "Popularidade" in result
        assert "Ver no Spotify" in result

    def test_format_en(self, sample_artist):
        result = _format_artist_response(
            sample_artist, lang="en"
        )
        assert "Queen" in result
        assert "followers" in result
        assert "Popularity" in result
        assert "View on Spotify" in result

    def test_format_es(self, sample_artist):
        result = _format_artist_response(
            sample_artist, lang="es"
        )
        assert "Queen" in result
        assert "seguidores" in result
        assert "Popularidad" in result
        assert "Ver en Spotify" in result


class TestFormatAlbumResponse:
    def test_format_pt(self):
        album = {
            "type": "album",
            "id": "al1",
            "name": "Thriller",
            "artists": "Michael Jackson",
            "release_date": "1982-11-30",
            "total_tracks": 9,
            "image": "img",
            "spotify_url": (
                "https://open.spotify.com/album/al1"
            ),
        }
        result = _format_album_response(
            album, lang="pt"
        )
        assert "Thriller" in result
        assert "Michael Jackson" in result
        assert "9 faixas" in result
        assert "Ver no Spotify" in result

    def test_format_en(self):
        album = {
            "type": "album",
            "id": "al1",
            "name": "Thriller",
            "artists": "Michael Jackson",
            "release_date": "1982-11-30",
            "total_tracks": 9,
            "image": "img",
            "spotify_url": (
                "https://open.spotify.com/album/al1"
            ),
        }
        result = _format_album_response(
            album, lang="en"
        )
        assert "9 tracks" in result
        assert "View on Spotify" in result

    def test_format_es(self):
        album = {
            "type": "album",
            "id": "al1",
            "name": "Thriller",
            "artists": "Michael Jackson",
            "release_date": "1982-11-30",
            "total_tracks": 9,
            "image": "img",
            "spotify_url": (
                "https://open.spotify.com/album/al1"
            ),
        }
        result = _format_album_response(
            album, lang="es"
        )
        assert "9 canciones" in result
        assert "Ver en Spotify" in result


# -- Agent execution ------------------------------------------


def _make_openai_mock(intent_json: str):
    """Helper to create a mock openai service."""
    mock = MagicMock()
    mock.is_initialized = MagicMock(
        return_value=True
    )
    mock_completion = MagicMock()
    mock_completion.choices = [
        MagicMock(
            message=MagicMock(content=intent_json)
        )
    ]
    mock.client = MagicMock()
    mock.client.chat.completions.create = AsyncMock(
        return_value=mock_completion
    )
    return mock


class TestMusicAgentExecution:
    @pytest.mark.asyncio
    async def test_search_track_pt(
        self, music_agent, mock_spotify, sample_track
    ):
        """Search track returns PT response."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_track", '
            '"query": "Bohemian Rhapsody", '
            '"language": "pt"}'
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
        assert "Ouvir no Spotify" in result.response

    @pytest.mark.asyncio
    async def test_search_track_en(
        self, music_agent, mock_spotify, sample_track
    ):
        """Search track returns EN response."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_track", '
            '"query": "Bohemian Rhapsody", '
            '"language": "en"}'
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
                "search Bohemian Rhapsody", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Listen on Spotify" in result.response

    @pytest.mark.asyncio
    async def test_search_track_es(
        self, music_agent, mock_spotify, sample_track
    ):
        """Search track returns ES response."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_track", '
            '"query": "Bohemian Rhapsody", '
            '"language": "es"}'
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
        assert "Escuchar en Spotify" in result.response

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
        # Always fetches full profile after search
        mock_spotify.get_artist = AsyncMock(
            return_value=sample_artist
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_artist", '
            '"query": "Queen", "language": "pt"}'
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
        assert "seguidores" in result.response

    @pytest.mark.asyncio
    async def test_search_artist_always_fetches_full(
        self, music_agent, mock_spotify
    ):
        """Always fetch full artist profile by ID."""
        # Search returns sparse artist
        sparse_artist = {
            "type": "artist",
            "id": "a1",
            "name": "Eminem",
            "genres": "hip-hop, rap",
            "popularity": 0,
            "followers": 0,
            "image": "",
            "spotify_url": "url",
            "uri": "uri",
        }
        # Full profile has real data
        full_artist = {
            "type": "artist",
            "id": "a1",
            "name": "Eminem",
            "genres": "hip-hop, rap",
            "popularity": 95,
            "followers": 70000000,
            "image": "img",
            "spotify_url": "url",
            "uri": "uri",
        }
        mock_spotify.search_artists = AsyncMock(
            return_value=[sparse_artist]
        )
        mock_spotify.get_artist = AsyncMock(
            return_value=full_artist
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_artist", '
            '"query": "Eminem", "language": "en"}'
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
                "who is Eminem", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Eminem" in result.response
        assert "70.0M" in result.response
        assert "95/100" in result.response
        # Always fetches full profile regardless
        mock_spotify.get_artist.assert_called_once_with(
            "a1"
        )

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
                "busca musica",
                {"language_code": "pt"},
            )

        assert result.status == AgentStatus.ERROR
        assert "Spotify" in result.response

    @pytest.mark.asyncio
    async def test_no_results_pt(
        self, music_agent, mock_spotify
    ):
        """Returns PT message when no results found."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[]
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_track", '
            '"query": "xyz", "language": "pt"}'
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
    async def test_no_results_en(
        self, music_agent, mock_spotify
    ):
        """Returns EN message when no results found."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[]
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_track", '
            '"query": "xyz", "language": "en"}'
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
                "search xyz", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "No music found" in result.response

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
                "busca algo",
                {"language_code": "en"},
            )

        assert result.status == AgentStatus.ERROR
        assert "error" in result.response.lower()

    @pytest.mark.asyncio
    async def test_recommendations_pt(
        self, music_agent, mock_spotify, sample_track
    ):
        """Recommendations in PT."""
        mock_spotify.get_recommendations = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "recommendations",'
            ' "genre": "rock", "language": "pt"}'
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
        assert "Recomendações" in result.response

    @pytest.mark.asyncio
    async def test_recommendations_en(
        self, music_agent, mock_spotify, sample_track
    ):
        """Recommendations in EN."""
        mock_spotify.get_recommendations = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "recommendations",'
            ' "genre": "rock", "language": "en"}'
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
                "recommend rock", {}
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Recommendations" in result.response

    @pytest.mark.asyncio
    async def test_artist_top_tracks(
        self, music_agent, mock_spotify, sample_track
    ):
        """Top tracks uses search-based method."""
        mock_spotify.get_artist_top_tracks = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "artist_top_tracks",'
            ' "query": "Eminem",'
            ' "artist_name": "Eminem",'
            ' "language": "pt"}'
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
        assert "Top músicas" in result.response
        mock_spotify.get_artist_top_tracks.assert_called_once_with(
            "Eminem", market="BR"
        )

    @pytest.mark.asyncio
    async def test_lang_fallback_to_context(
        self, music_agent, mock_spotify, sample_track
    ):
        """Falls back to context lang when GPT omits it."""
        mock_spotify.search_tracks = AsyncMock(
            return_value=[sample_track]
        )
        mock_openai = _make_openai_mock(
            '{"action": "search_track", '
            '"query": "test"}'
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
                "test",
                {"language_code": "es"},
            )

        assert result.status == AgentStatus.SUCCESS
        assert "Escuchar en Spotify" in result.response


class TestCapabilities:
    def test_get_capabilities(self, music_agent):
        caps = music_agent.get_capabilities()
        assert isinstance(caps, list)
        assert len(caps) > 0
        assert "search_tracks" in caps
        assert "recommendations" in caps
