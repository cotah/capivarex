"""GitHub Bridge — receives push webhooks and fetches commit diffs."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("cybersecurity.github_bridge")


async def get_commit_diff(repo: str, sha: str) -> str | None:
    """Fetch the diff for a specific commit from GitHub API."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return None

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/commits/{sha}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.diff",
                },
            )
            if resp.status_code == 200:
                return resp.text
            logger.warning(
                "GitHub API returned %d for commit %s", resp.status_code, sha[:8]
            )
    except Exception:
        logger.debug("Failed to fetch commit diff for %s", sha[:8])

    return None


async def get_recent_commits(repo: str, since_hours: int = 6) -> list[dict]:
    """Fetch recent commits from GitHub API."""
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        return []

    from datetime import datetime, timedelta, timezone

    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    try:
        import httpx

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{repo}/commits",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"since": since, "per_page": 20},
            )
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        logger.debug("Failed to fetch recent commits")

    return []
