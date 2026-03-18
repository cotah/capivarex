"""Tests for Notion OAuth and Notion Service."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Notion OAuth Service
# ---------------------------------------------------------------------------


class TestNotionOAuth:
    def test_get_authorization_url(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        svc.client_id = "test-client"
        url = svc.get_authorization_url("user1")
        assert "test-client" in url
        assert "authorize" in url
        assert "state=" in url

    @pytest.mark.asyncio
    async def test_exchange_code(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        svc.client_id = "cid"
        svc.client_secret = "csec"

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "ntn_at",
            "workspace_id": "ws1",
            "workspace_name": "My Workspace",
            "bot_id": "bot1",
            "owner": {"type": "user", "user": {"person": {"email": "u@test.com"}}},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.auth.notion_oauth_service.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
            )
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc.exchange_code("test-code")

        assert result["access_token"] == "ntn_at"
        assert result["workspace_id"] == "ws1"

    @pytest.mark.asyncio
    async def test_save_tokens_no_db(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        with patch("services.auth.notion_oauth_service.get_service", return_value=None):
            result = await svc.save_tokens("u1", {"access_token": "at"})
        assert result is False

    @pytest.mark.asyncio
    async def test_get_valid_token_no_db(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        with patch("services.auth.notion_oauth_service.get_service", return_value=None):
            result = await svc.get_valid_token("u1")
        assert result is None

    @pytest.mark.asyncio
    async def test_is_connected_false(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        with patch("services.auth.notion_oauth_service.get_service", return_value=None):
            result = await svc.is_connected("u1")
        assert result is False

    @pytest.mark.asyncio
    async def test_disconnect_no_db(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        with patch("services.auth.notion_oauth_service.get_service", return_value=None):
            result = await svc.disconnect("u1")
        assert result is False

    @pytest.mark.asyncio
    async def test_get_connected_accounts_no_db(self):
        from services.auth.notion_oauth_service import NotionOAuthService

        svc = NotionOAuthService()
        with patch("services.auth.notion_oauth_service.get_service", return_value=None):
            result = await svc.get_connected_accounts("u1")
        assert result == []

    def test_singleton(self):
        import services.auth.notion_oauth_service as mod

        mod._instance = None
        s1 = mod.get_notion_oauth()
        s2 = mod.get_notion_oauth()
        assert s1 is s2
        mod._instance = None


# ---------------------------------------------------------------------------
# Notion Service
# ---------------------------------------------------------------------------


class TestNotionService:
    @pytest.mark.asyncio
    async def test_initialize(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()
        await svc._initialize()
        assert await svc._health_check() is True

    @pytest.mark.asyncio
    async def test_create_page_no_token(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()
        with patch("services.auth.notion_oauth_service.get_notion_oauth") as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.create_page("u1", "Title", "Content")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_pages_no_token(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()
        with patch("services.auth.notion_oauth_service.get_notion_oauth") as mock_oauth:
            mock_oauth.return_value.get_valid_token = AsyncMock(return_value=None)
            result = await svc.list_pages("u1")
        assert result == []

    def test_build_content_blocks(self):
        from services.integrations.notion_service import _build_content_blocks

        blocks = _build_content_blocks("Hello world\n\nSecond paragraph")
        # 2 paragraphs + divider + source tag
        assert len(blocks) == 4
        assert blocks[0]["type"] == "paragraph"
        assert blocks[1]["type"] == "paragraph"
        assert blocks[2]["type"] == "divider"
        assert "CAPIVAREX" in blocks[3]["paragraph"]["rich_text"][0]["text"]["content"]

    def test_build_content_blocks_long(self):
        from services.integrations.notion_service import _build_content_blocks

        # Content longer than 2000 chars should be chunked
        long_text = "x" * 4500
        blocks = _build_content_blocks(long_text)
        # 3 chunks (2000+2000+500) + divider + source
        assert len(blocks) == 5

    def test_get_page_title(self):
        from services.integrations.notion_service import _get_page_title

        page = {"properties": {"title": {"title": [{"text": {"content": "My Page"}}]}}}
        assert _get_page_title(page) == "My Page"

    def test_get_page_title_empty(self):
        from services.integrations.notion_service import _get_page_title

        assert _get_page_title({}) == ""
        assert _get_page_title({"properties": {}}) == ""


# ---------------------------------------------------------------------------
# Auth Routes
# ---------------------------------------------------------------------------


class TestNotionServiceEdgeCases:
    @pytest.mark.asyncio
    async def test_find_parent_page_no_results(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()

        with patch("services.integrations.notion_service.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
            )
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc._find_parent_page("fake-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_parent_page_with_capivarex(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "p1",
                    "properties": {
                        "title": {"title": [{"text": {"content": "Random"}}]}
                    },
                },
                {
                    "id": "p2",
                    "properties": {
                        "title": {"title": [{"text": {"content": "CAPIVAREX Notes"}}]}
                    },
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.integrations.notion_service.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
            )
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc._find_parent_page("fake-token")
        assert result == "p2"  # Prefers CAPIVAREX Notes page

    @pytest.mark.asyncio
    async def test_find_parent_page_first_fallback(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "p1",
                    "properties": {
                        "title": {"title": [{"text": {"content": "My Page"}}]}
                    },
                },
            ]
        }
        mock_resp.raise_for_status = MagicMock()

        with patch("services.integrations.notion_service.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(
                return_value=MagicMock(post=AsyncMock(return_value=mock_resp))
            )
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc._find_parent_page("fake-token")
        assert result == "p1"  # Falls back to first page

    @pytest.mark.asyncio
    async def test_find_parent_page_exception(self):
        from services.integrations.notion_service import NotionService

        svc = NotionService()

        with patch("services.integrations.notion_service.httpx.AsyncClient") as mc:
            mc.return_value.__aenter__ = AsyncMock(side_effect=Exception("net error"))
            mc.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await svc._find_parent_page("fake-token")
        assert result is None

    def test_headers(self):
        from services.integrations.notion_service import _headers

        h = _headers("test-token")
        assert h["Authorization"] == "Bearer test-token"
        assert "Notion-Version" in h


class TestNotionAuthRoutes:
    def test_router_prefix(self):
        from api.routes.notion_auth import router

        assert "/api/auth/notion" in router.prefix

    def test_success_html(self):
        from api.routes.notion_auth import _SUCCESS_HTML

        assert "Notion Connected" in _SUCCESS_HTML

    def test_error_html(self):
        from api.routes.notion_auth import _ERROR_HTML

        assert "Connection Failed" in _ERROR_HTML
