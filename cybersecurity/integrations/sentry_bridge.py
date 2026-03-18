"""Sentry Bridge — polls Sentry API for unresolved issues."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("cybersecurity.sentry_bridge")


async def get_unresolved_issues(limit: int = 20) -> list[dict]:
    """Fetch unresolved issues from Sentry API.

    Returns list of issue dicts or empty list if not configured.
    """
    token = os.getenv("SENTRY_AUTH_TOKEN", "")
    org = os.getenv("SENTRY_ORG", "")
    project = os.getenv("SENTRY_PROJECT", "")

    if not (token and org and project):
        return []

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://sentry.io/api/0/projects/{org}/{project}/issues/",
                headers={"Authorization": f"Bearer {token}"},
                params={"query": "is:unresolved", "limit": limit},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning("Sentry API returned %d", resp.status_code)
    except Exception:
        logger.debug("Failed to query Sentry API")

    return []


async def get_issue_events(issue_id: str, limit: int = 5) -> list[dict]:
    """Fetch recent events for a Sentry issue."""
    token = os.getenv("SENTRY_AUTH_TOKEN", "")
    org = os.getenv("SENTRY_ORG", "")
    project = os.getenv("SENTRY_PROJECT", "")

    if not (token and org and project):
        return []

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://sentry.io/api/0/issues/{issue_id}/events/",
                headers={"Authorization": f"Bearer {token}"},
                params={"limit": limit},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        logger.debug("Failed to query Sentry events for issue %s", issue_id)

    return []
