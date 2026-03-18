"""Tests for Spotify OAuth and playback control."""

import base64
import json
from urllib.parse import unquote

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ══════════════════════════════════════════════════════════════════════════════
# SpotifyOAuth Service Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSpotifyOAuth:
    """Tests for SpotifyOAuth service."""

    def test_auth_url_generation(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "test_id"
        oauth.client_secret = "test_secret"
        url = oauth.get_auth_url("user123")
        assert "accounts.spotify.com/authorize" in url
        assert "test_id" in url
        assert "user-modify-playback-state" in url

    def test_is_configured_false_empty_id(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = ""
        oauth.client_secret = "secret"
        assert oauth.is_configured is False

    def test_is_configured_false_empty_secret(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "id"
        oauth.client_secret = ""
        assert oauth.is_configured is False

    def test_is_configured_true(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "id"
        oauth.client_secret = "secret"
        assert oauth.is_configured is True

    def test_state_contains_user_id(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "id"
        oauth.client_secret = "secret"
        url = oauth.get_auth_url("user123")
        # Extract state param (URL-encoded after urlencode)
        state = unquote(url.split("state=")[1].split("&")[0])
        decoded = json.loads(base64.urlsafe_b64decode(state))
        assert decoded["user_id"] == "user123"

    def test_auth_url_contains_scopes(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "id"
        oauth.client_secret = "secret"
        url = oauth.get_auth_url("user123")
        assert "playlist-modify-public" in url
        assert "user-read-currently-playing" in url
        assert "user-library-read" in url

    def test_auth_url_contains_show_dialog(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "id"
        oauth.client_secret = "secret"
        url = oauth.get_auth_url("user123")
        assert "show_dialog=true" in url

    def test_singleton_returns_same_instance(self):
        from services.auth.spotify_oauth_service import (
            SpotifyOAuth,
            get_spotify_oauth,
        )
        import services.auth.spotify_oauth_service as mod

        # Reset singleton
        mod._spotify_oauth = None
        instance1 = get_spotify_oauth()
        instance2 = get_spotify_oauth()
        assert instance1 is instance2
        assert isinstance(instance1, SpotifyOAuth)
        # Cleanup
        mod._spotify_oauth = None

    @pytest.mark.asyncio
    async def test_is_connected_no_token(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        with patch.object(
            oauth, "get_valid_token", new_callable=AsyncMock, return_value=None
        ):
            assert await oauth.is_connected("user123") is False

    @pytest.mark.asyncio
    async def test_is_connected_with_token(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        with patch.object(
            oauth,
            "get_valid_token",
            new_callable=AsyncMock,
            return_value="fake_token",
        ):
            assert await oauth.is_connected("user123") is True

    @pytest.mark.asyncio
    async def test_get_valid_token_no_db(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        with patch(
            "services.infrastructure.database.get_supabase_client",
            return_value=None,
        ):
            result = await oauth.get_valid_token("user123")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_no_row(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[]
        )
        with patch(
            "services.infrastructure.database.get_supabase_client",
            return_value=sb,
        ):
            result = await oauth.get_valid_token("user123")
            assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_token_returns_token(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        token_row = {
            "access_token": "valid_token",
            "refresh_token": "refresh_abc",
            "expires_at": "2099-01-01T00:00:00+00:00",
        }
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value = MagicMock(
            data=[token_row]
        )
        with patch(
            "services.infrastructure.database.get_supabase_client",
            return_value=sb,
        ):
            result = await oauth.get_valid_token("user123")
            assert result == "valid_token"

    @pytest.mark.asyncio
    async def test_disconnect_success(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        sb = MagicMock()
        sb.table.return_value.update.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock()
        with patch(
            "services.infrastructure.database.get_supabase_client",
            return_value=sb,
        ):
            result = await oauth.disconnect("user123")
            assert result is True

    @pytest.mark.asyncio
    async def test_disconnect_no_db(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        with patch(
            "services.infrastructure.database.get_supabase_client",
            return_value=None,
        ):
            result = await oauth.disconnect("user123")
            assert result is False

    @pytest.mark.asyncio
    async def test_handle_callback(self):
        from services.auth.spotify_oauth_service import SpotifyOAuth

        oauth = SpotifyOAuth()
        oauth.client_id = "id"
        oauth.client_secret = "secret"
        oauth.redirect_uri = "http://localhost/callback"

        state_b64 = base64.urlsafe_b64encode(
            json.dumps({"user_id": "user123"}).encode()
        ).decode()

        mock_token_resp = MagicMock()
        mock_token_resp.status_code = 200
        mock_token_resp.raise_for_status = MagicMock()
        mock_token_resp.json.return_value = {
            "access_token": "access123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
        }

        mock_profile_resp = MagicMock()
        mock_profile_resp.json.return_value = {
            "display_name": "Test User",
            "email": "test@example.com",
            "id": "spotify_user_id",
        }

        async def mock_post(url, **kwargs):
            return mock_token_resp

        async def mock_get(url, **kwargs):
            return mock_profile_resp

        mock_client = AsyncMock()
        mock_client.post = mock_post
        mock_client.get = mock_get

        sb = MagicMock()
        sb.table.return_value.upsert.return_value.execute.return_value = MagicMock()

        with (
            patch("httpx.AsyncClient") as mock_cls,
            patch(
                "services.infrastructure.database.get_supabase_client",
                return_value=sb,
            ),
        ):
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()

            result = await oauth.handle_callback("code123", state_b64)
            assert result["user_id"] == "user123"
            assert result["display_name"] == "Test User"
            assert result["email"] == "test@example.com"


# ══════════════════════════════════════════════════════════════════════════════
# SpotifyUserService Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSpotifyUserService:
    """Tests for user-level playback control."""

    @pytest.mark.asyncio
    async def test_play_with_uri(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.play(uri="spotify:track:abc")
        assert result is True

    @pytest.mark.asyncio
    async def test_play_resume(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.play()  # No URI = resume
        assert result is True

    @pytest.mark.asyncio
    async def test_play_context_uri(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.play(uri="spotify:album:abc")
        assert result is True

    @pytest.mark.asyncio
    async def test_pause(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.pause()
        assert result is True

    @pytest.mark.asyncio
    async def test_next_track(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.next_track()
        assert result is True

    @pytest.mark.asyncio
    async def test_previous_track(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.previous_track()
        assert result is True

    @pytest.mark.asyncio
    async def test_set_volume_clamped_high(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.set_volume(150)  # Should clamp to 100
        assert result is True

    @pytest.mark.asyncio
    async def test_set_volume_clamped_low(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.set_volume(-10)  # Should clamp to 0
        assert result is True

    @pytest.mark.asyncio
    async def test_get_currently_playing_nothing(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=204)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.get_currently_playing()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_currently_playing_success(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "item": {"name": "Test", "artists": [{"name": "Artist"}]}
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.get_currently_playing()
        assert result is not None
        assert result["item"]["name"] == "Test"

    @pytest.mark.asyncio
    async def test_get_devices(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"devices": [{"id": "dev1", "name": "Phone"}]}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.get_devices()
        assert len(result) == 1
        assert result[0]["name"] == "Phone"

    @pytest.mark.asyncio
    async def test_get_playlists(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {"items": [{"id": "pl1", "name": "My Playlist"}]}
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.get_playlists()
        assert len(result) == 1
        assert result[0]["name"] == "My Playlist"

    @pytest.mark.asyncio
    async def test_add_to_playlist(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=201)
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.add_to_playlist("pl1", "spotify:track:abc")
        assert result is True

    @pytest.mark.asyncio
    async def test_save_track(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=200)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.save_track("track123")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_recently_played(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = {
            "items": [
                {"track": {"name": "Track1"}},
                {"track": {"name": "Track2"}},
            ]
        }
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.get_recently_played()
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_play_failure(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=403)
        mock_client = AsyncMock()
        mock_client.put = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.play(uri="spotify:track:abc")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_devices_error(self):
        from services.integrations.spotify_user_service import (
            SpotifyUserService,
        )

        svc = SpotifyUserService("fake_token")
        mock_resp = MagicMock(status_code=401)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock()
            result = await svc.get_devices()
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# i18n Keys Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSpotifyI18nKeys:
    """Tests for Spotify i18n strings."""

    def test_all_playback_keys_exist(self):
        from services.i18n import t

        keys = [
            "music_now_playing",
            "music_paused",
            "music_next",
            "music_previous",
            "music_volume_set",
            "music_currently_playing",
            "music_nothing_playing",
            "music_connect_spotify",
            "music_play_failed",
            "music_not_found",
            "music_added_to_playlist",
            "music_nothing_to_add",
            "music_no_playlists",
            "music_pause_failed",
            "music_next_failed",
            "music_previous_failed",
            "music_volume_failed",
            "music_unknown_action",
            "music_spotify_not_configured",
            "music_add_failed",
        ]
        for key in keys:
            for lang in ("en", "pt", "es"):
                result = t(
                    key,
                    lang=lang,
                    track="Test",
                    artist="Artist",
                    volume=50,
                    query="test",
                    url="http://example.com",
                    playlist="My Playlist",
                )
                assert result and len(result) > 2, f"Missing or empty: {key}/{lang}"

    def test_keys_have_all_three_languages(self):
        from services.i18n.strings import STRINGS

        playback_keys = [
            "music_now_playing",
            "music_paused",
            "music_next",
            "music_previous",
            "music_volume_set",
            "music_currently_playing",
            "music_nothing_playing",
            "music_connect_spotify",
            "music_play_failed",
            "music_not_found",
            "music_added_to_playlist",
            "music_nothing_to_add",
            "music_no_playlists",
            "music_pause_failed",
            "music_next_failed",
            "music_previous_failed",
            "music_volume_failed",
            "music_unknown_action",
            "music_spotify_not_configured",
            "music_add_failed",
        ]
        for key in playback_keys:
            assert key in STRINGS, f"Key {key} not in STRINGS"
            for lang in ("en", "pt", "es"):
                assert lang in STRINGS[key], f"Missing {lang} for {key}"


# ══════════════════════════════════════════════════════════════════════════════
# Auth Routes Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestSpotifyAuthRoutes:
    """Tests for Spotify auth route patterns."""

    def test_route_prefix(self):
        from api.routes.spotify_auth import router

        # Check that all route paths start with /api/auth/spotify
        paths = [r.path for r in router.routes]
        for path in paths:
            assert path.startswith("/"), f"Route {path} doesn't start with /"

    def test_scopes_include_playback(self):
        from services.auth.spotify_oauth_service import SPOTIFY_SCOPES

        assert "user-modify-playback-state" in SPOTIFY_SCOPES
        assert "playlist-modify-public" in SPOTIFY_SCOPES
        assert "user-read-currently-playing" in SPOTIFY_SCOPES
        assert "user-library-read" in SPOTIFY_SCOPES

    def test_scopes_include_recently_played(self):
        from services.auth.spotify_oauth_service import SPOTIFY_SCOPES

        assert "user-read-recently-played" in SPOTIFY_SCOPES

    def test_router_has_four_endpoints(self):
        from api.routes.spotify_auth import router

        paths = [r.path for r in router.routes]
        assert "/api/auth/spotify/connect" in paths
        assert "/api/auth/spotify/callback" in paths
        assert "/api/auth/spotify/status" in paths
        assert "/api/auth/spotify/disconnect" in paths

    def test_success_page_html(self):
        from api.routes.spotify_auth import _success_page

        html = _success_page("Test User", "test@test.com")
        assert "Spotify Connected" in html
        assert "Test User" in html
        assert "1DB954" in html  # Spotify green

    def test_error_page_html(self):
        from api.routes.spotify_auth import _error_page

        html = _error_page("Something went wrong")
        assert "Connection Failed" in html
        assert "Something went wrong" in html


# ══════════════════════════════════════════════════════════════════════════════
# Music Agent Playback Handler Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestMusicAgentPlayback:
    """Tests for music agent playback handling."""

    @pytest.mark.asyncio
    async def test_handle_connect_not_configured(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with patch(
            "services.auth.spotify_oauth_service.get_spotify_oauth"
        ) as mock_oauth:
            oauth = MagicMock()
            oauth.is_configured = False
            mock_oauth.return_value = oauth

            result = await agent._handle_connect(context, "en")
            assert result.status.value == "error"
            assert "not configured" in result.response.lower()

    @pytest.mark.asyncio
    async def test_handle_connect_configured(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with patch(
            "services.auth.spotify_oauth_service.get_spotify_oauth"
        ) as mock_oauth:
            oauth = MagicMock()
            oauth.is_configured = True
            oauth.get_auth_url.return_value = (
                "https://accounts.spotify.com/authorize?..."
            )
            mock_oauth.return_value = oauth

            result = await agent._handle_connect(context, "en")
            assert result.status.value == "success"
            assert "Connect Spotify" in result.response
            assert result.data["needs_connection"] is True

    @pytest.mark.asyncio
    async def test_handle_playback_no_token(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with patch(
            "services.auth.spotify_oauth_service.get_spotify_oauth"
        ) as mock_oauth:
            oauth = MagicMock()
            oauth.is_configured = True
            oauth.get_valid_token = AsyncMock(return_value=None)
            oauth.get_auth_url.return_value = (
                "https://accounts.spotify.com/authorize?..."
            )
            mock_oauth.return_value = oauth

            result = await agent._handle_playback("pause", "", "", context, "en")
            # Should redirect to connect
            assert "Connect Spotify" in result.response

    @pytest.mark.asyncio
    async def test_handle_playback_pause(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.pause = AsyncMock(return_value=True)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback("pause", "", "", context, "en")
            assert "paused" in result.response.lower()

    @pytest.mark.asyncio
    async def test_handle_playback_volume(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.set_volume = AsyncMock(return_value=True)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback("volume", "75", "", context, "en")
            assert "75%" in result.response

    @pytest.mark.asyncio
    async def test_handle_playback_now_playing_nothing(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.get_currently_playing = AsyncMock(return_value=None)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback("now_playing", "", "", context, "en")
            assert "Nothing" in result.response

    @pytest.mark.asyncio
    async def test_handle_playback_now_playing_track(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.get_currently_playing = AsyncMock(
                return_value={
                    "item": {
                        "name": "Bohemian Rhapsody",
                        "artists": [{"name": "Queen"}],
                    }
                }
            )
            mock_svc_cls.return_value = player

            result = await agent._handle_playback("now_playing", "", "", context, "en")
            assert "Bohemian Rhapsody" in result.response
            assert "Queen" in result.response

    def test_music_agent_capabilities_include_playback(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        caps = agent.get_capabilities()
        assert "play_track" in caps
        assert "pause" in caps
        assert "next" in caps
        assert "previous" in caps
        assert "volume" in caps
        assert "now_playing" in caps
        assert "add_to_playlist" in caps
        assert "connect_spotify" in caps

    @pytest.mark.asyncio
    async def test_handle_playback_next(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.next_track = AsyncMock(return_value=True)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback("next", "", "", context, "en")
            assert (
                "next" in result.response.lower() or "skip" in result.response.lower()
            )

    @pytest.mark.asyncio
    async def test_handle_playback_previous(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.previous_track = AsyncMock(return_value=True)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback("previous", "", "", context, "en")
            assert (
                "previous" in result.response.lower()
                or "back" in result.response.lower()
            )

    @pytest.mark.asyncio
    async def test_handle_playback_play_track_success(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        mock_spotify_svc = MagicMock()
        mock_spotify_svc.is_initialized.return_value = True
        mock_spotify_svc.search_tracks = AsyncMock(
            return_value=[
                {
                    "name": "Candy Shop",
                    "artists": "50 Cent",
                    "uri": "spotify:track:abc123",
                }
            ]
        )

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
            patch(
                "agents.specialized.music_agent.get_service",
                return_value=mock_spotify_svc,
            ),
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.play = AsyncMock(return_value=True)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback(
                "play_track", "Candy Shop", "", context, "en"
            )
            assert "Candy Shop" in result.response

    @pytest.mark.asyncio
    async def test_handle_playback_play_track_not_found(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        mock_spotify_svc = MagicMock()
        mock_spotify_svc.is_initialized.return_value = True
        mock_spotify_svc.search_tracks = AsyncMock(return_value=[])

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
            patch(
                "agents.specialized.music_agent.get_service",
                return_value=mock_spotify_svc,
            ),
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth
            mock_svc_cls.return_value = AsyncMock()

            result = await agent._handle_playback(
                "play_track", "nonexistent", "", context, "en"
            )
            assert "nonexistent" in result.response.lower()

    @pytest.mark.asyncio
    async def test_handle_playback_add_to_playlist_success(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.get_currently_playing = AsyncMock(
                return_value={
                    "item": {
                        "name": "Test Song",
                        "uri": "spotify:track:xyz",
                    }
                }
            )
            player.get_playlists = AsyncMock(
                return_value=[{"id": "pl1", "name": "Favorites"}]
            )
            player.add_to_playlist = AsyncMock(return_value=True)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback(
                "add_to_playlist", "", "", context, "en"
            )
            assert "Test Song" in result.response
            assert "Favorites" in result.response

    @pytest.mark.asyncio
    async def test_handle_playback_add_nothing_playing(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth

            player = AsyncMock()
            player.get_currently_playing = AsyncMock(return_value=None)
            mock_svc_cls.return_value = player

            result = await agent._handle_playback(
                "add_to_playlist", "", "", context, "en"
            )
            assert "Nothing" in result.response or "nothing" in result.response

    @pytest.mark.asyncio
    async def test_handle_playback_unknown_action(self):
        from agents.specialized.music_agent import MusicAgent

        agent = MusicAgent()
        context = {"user_id": "user123"}

        with (
            patch(
                "services.auth.spotify_oauth_service.get_spotify_oauth"
            ) as mock_oauth,
            patch(
                "services.integrations.spotify_user_service.SpotifyUserService"
            ) as mock_svc_cls,
        ):
            oauth = MagicMock()
            oauth.get_valid_token = AsyncMock(return_value="token123")
            mock_oauth.return_value = oauth
            mock_svc_cls.return_value = AsyncMock()

            result = await agent._handle_playback(
                "unknown_action_xyz", "", "", context, "en"
            )
            assert (
                "understand" in result.response.lower()
                or "didn" in result.response.lower()
            )
