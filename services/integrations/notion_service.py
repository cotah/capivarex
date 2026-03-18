"""
Notion Service — creates pages in the user's Notion workspace via API.

The user selects which pages to share during OAuth consent.
The token only has access to those pages. We create notes as
child pages of the first accessible page (the user's chosen parent).
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from services.core import BaseService, register_service

logger = logging.getLogger(__name__)

_API_BASE = "https://api.notion.com/v1"
_API_VERSION = "2022-06-28"
_CAPIVAREX_TAG = "capivarex-note"


def _headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": _API_VERSION,
    }


@register_service("notion")
class NotionService(BaseService):
    """Notion integration — create pages in user's workspace."""

    def __init__(self) -> None:
        super().__init__(name="notion")

    async def _initialize(self) -> None:
        self.logger.info("NotionService initialized")

    async def _health_check(self) -> bool:
        return True

    # ------------------------------------------------------------------
    # Token helper
    # ------------------------------------------------------------------

    async def _get_token(self, user_id: str) -> Optional[str]:
        from services.auth.notion_oauth_service import get_notion_oauth

        return await get_notion_oauth().get_valid_token(user_id)

    # ------------------------------------------------------------------
    # Find parent page (the page user shared during OAuth)
    # ------------------------------------------------------------------

    async def _find_parent_page(self, token: str) -> Optional[str]:
        """Find a suitable parent page for notes.

        Searches for a page the user shared during OAuth.
        The Notion integration token only has access to pages
        the user explicitly selected.
        """
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Search for pages accessible to this integration
                resp = await client.post(
                    f"{_API_BASE}/search",
                    headers=_headers(token),
                    json={
                        "filter": {"value": "page", "property": "object"},
                        "sort": {
                            "direction": "descending",
                            "timestamp": "last_edited_time",
                        },
                        "page_size": 10,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                results = data.get("results", [])
                if not results:
                    return None

                # Prefer a page named "CAPIVAREX Notes" if it exists
                for page in results:
                    title = _get_page_title(page)
                    if title and "capivarex" in title.lower():
                        return page["id"]

                # Otherwise use the first accessible page
                return results[0]["id"]

        except Exception as e:
            logger.warning("Failed to find Notion parent page: %s", e)
            return None

    # ------------------------------------------------------------------
    # Create page (note)
    # ------------------------------------------------------------------

    async def create_page(
        self,
        user_id: str,
        title: str,
        content: str,
    ) -> Optional[str]:
        """Create a note as a Notion page.

        Returns the page URL on success, None on failure.
        """
        token = await self._get_token(user_id)
        if not token:
            logger.debug("No Notion token for user %s", user_id[:8])
            return None

        parent_id = await self._find_parent_page(token)
        if not parent_id:
            logger.warning(
                "No accessible Notion page for user %s — "
                "user needs to share a page during OAuth",
                user_id[:8],
            )
            return None

        # Build Notion page payload
        page_body: Dict[str, Any] = {
            "parent": {"page_id": parent_id},
            "properties": {
                "title": {
                    "title": [{"text": {"content": title[:100]}}],
                },
            },
            "children": _build_content_blocks(content),
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/pages",
                    headers=_headers(token),
                    json=page_body,
                )
                resp.raise_for_status()
                data = resp.json()

                page_url = data.get("url", "")
                logger.info(
                    "Notion page created for user %s: %s",
                    user_id[:8],
                    page_url,
                )
                return page_url

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Notion API error creating page: %s %s",
                e.response.status_code,
                e.response.text[:200],
            )
            return None
        except Exception as e:
            logger.warning("Failed to create Notion page: %s", e)
            return None

    # ------------------------------------------------------------------
    # List pages (for future use)
    # ------------------------------------------------------------------

    async def list_pages(
        self,
        user_id: str,
        max_results: int = 10,
    ) -> List[Dict[str, Any]]:
        """List accessible Notion pages."""
        token = await self._get_token(user_id)
        if not token:
            return []

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{_API_BASE}/search",
                    headers=_headers(token),
                    json={
                        "filter": {"value": "page", "property": "object"},
                        "sort": {
                            "direction": "descending",
                            "timestamp": "last_edited_time",
                        },
                        "page_size": max_results,
                    },
                )
                resp.raise_for_status()
                data = resp.json()

                return [
                    {
                        "id": page["id"],
                        "title": _get_page_title(page),
                        "url": page.get("url", ""),
                        "last_edited": page.get("last_edited_time", ""),
                    }
                    for page in data.get("results", [])
                ]
        except Exception as e:
            logger.warning("Failed to list Notion pages: %s", e)
            return []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_page_title(page: Dict[str, Any]) -> str:
    """Extract title from a Notion page object."""
    props = page.get("properties", {})
    title_prop = props.get("title", {})
    if isinstance(title_prop, dict):
        title_arr = title_prop.get("title", [])
        if title_arr and isinstance(title_arr, list):
            return title_arr[0].get("text", {}).get("content", "")
    return ""


def _build_content_blocks(content: str) -> List[Dict[str, Any]]:
    """Convert plain text content into Notion block objects.

    Splits content into paragraphs and creates a paragraph block for each.
    Max 2000 chars per block (Notion limit).
    """
    blocks: List[Dict[str, Any]] = []
    paragraphs = content.split("\n\n") if "\n\n" in content else content.split("\n")

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue

        # Notion has a 2000 char limit per rich_text element
        chunks = [para[i : i + 2000] for i in range(0, len(para), 2000)]

        for chunk in chunks:
            blocks.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}],
                    },
                }
            )

    # Add a divider and source tag at the end
    blocks.append({"object": "block", "type": "divider", "divider": {}})
    blocks.append(
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [
                    {
                        "type": "text",
                        "text": {"content": "Created by CAPIVAREX"},
                        "annotations": {"italic": True, "color": "gray"},
                    }
                ],
            },
        }
    )

    return blocks
