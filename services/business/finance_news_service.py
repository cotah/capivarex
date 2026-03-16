"""
Finance News Service — fetches daily news via Perplexity API.

Runs 2x/day (07:00 and 18:00 UTC) via proactivity loop.
Stores articles in proactivity_feed for display on Finance → News.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Default news query (used when no user-specific context)
DEFAULT_NEWS_QUERY = (
    "Top 5 most important financial and business news stories today. "
    "Focus on: global macro events that affect markets, stock market movements, "
    "crypto trends, central bank decisions, and geopolitical events with economic impact. "
    "Be concise — one paragraph per story with clear title."
)


def _build_news_query(user_assets: list[str] | None = None) -> str:
    """Build a personalized news query based on user's tracked assets."""
    if not user_assets:
        return DEFAULT_NEWS_QUERY

    assets_str = ", ".join(user_assets[:10])  # Max 10 to keep prompt short
    return (
        f"Top 5 most important financial news today, with special attention to: {assets_str}. "
        "Include global macro events that could affect these assets, "
        "central bank decisions, geopolitical events, and market-moving developments. "
        "Be concise — one paragraph per story with clear title."
    )


async def fetch_and_store_news(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch news via Perplexity and store in proactivity_feed.

    Args:
        user_id: If provided, store only for this user. If None, store for all
                 users with proactivity enabled.

    Returns:
        List of news articles fetched.
    """
    perplexity = get_service("perplexity")
    if not perplexity:
        logger.warning("News: Perplexity service not available")
        return []

    try:
        await perplexity.initialize()
    except Exception as e:
        logger.warning("News: Perplexity init failed: %s", e)
        return []

    db_service = get_service("database")
    if not db_service:
        logger.warning("News: Database service not available")
        return []

    await db_service.initialize()
    client = db_service.get_client()
    if not client:
        return []

    articles: List[Dict[str, Any]] = []

    try:
        query = _build_news_query()
        result = await perplexity.search(
            query=query,
            model="sonar",
        )

        answer = result.get("answer", "")
        sources = result.get("sources", [])

        if answer:
            parsed = _parse_news_response(answer, sources)
            articles.extend(parsed)

    except Exception as e:
        logger.error("News: fetch failed: %s", e)

    if not articles:
        logger.info("News: no articles fetched")
        return []

    # Get target users
    user_ids = []
    if user_id:
        user_ids = [user_id]
    else:
        # Get all users with proactivity enabled
        try:
            result = (
                client.table("proactivity_preferences")
                .select("user_id")
                .eq("enabled", True)
                .execute()
            )
            user_ids = [r["user_id"] for r in (result.data or [])]
        except Exception:
            # Fallback: get all webapp users active in last 7 days
            try:
                from datetime import timedelta
                cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
                result = (
                    client.table("webapp_messages")
                    .select("user_id")
                    .eq("role", "user")
                    .gte("created_at", cutoff)
                    .execute()
                )
                user_ids = list(set(r["user_id"] for r in (result.data or [])))
            except Exception as e2:
                logger.error("News: failed to get users: %s", e2)

    if not user_ids:
        logger.info("News: no users to deliver to")
        return articles

    # Store articles in proactivity_feed for each user
    now = datetime.now(timezone.utc).isoformat()
    for uid in user_ids:
        for article in articles:
            try:
                client.table("proactivity_feed").insert({
                    "user_id": uid,
                    "type": "news",
                    "title": article["title"],
                    "message": article["summary"],
                    "metadata": json.dumps({
                        "source": article.get("source", ""),
                        "sources": article.get("sources", []),
                        "category": "finance",
                    }),
                    "is_read": False,
                    "created_at": now,
                }).execute()
            except Exception as e:
                logger.warning("News: failed to store for user=%s: %s", uid[:8], e)

    logger.info("News: stored %d articles for %d users", len(articles), len(user_ids))
    return articles


def _parse_news_response(
    answer: str, sources: List[str]
) -> List[Dict[str, Any]]:
    """Parse Perplexity response into individual news articles."""
    import re
    articles = []

    # Split on numbered items OR bold headers at start of line/paragraph
    # Handles: "**1. Title** body", "1. Title. Body", "**Title**\nBody"
    parts = re.split(r'\n(?=\s*\*{0,2}\s*\d+[\.\)]\s)', answer)

    # If only 1 part, try splitting on double-newline + bold header
    if len(parts) <= 1:
        parts = re.split(r'\n\n(?=\*\*)', answer)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Remove leading number: "1. " or "**1. " or "**1) "
        cleaned = re.sub(r'^\s*\*{0,2}\s*\d+[\.\)]\s*', '', part)
        if not cleaned:
            continue

        # Extract title and body
        # Handle "**Title** body" or "**Title.**\nbody"
        bold_match = re.match(r'\*\*(.+?)\*\*\.?\s*(.*)', cleaned, re.DOTALL)
        if bold_match:
            title = bold_match.group(1).strip().rstrip('.')
            body = bold_match.group(2).strip()
        else:
            # No bold — first sentence is title
            sentences = re.split(r'(?<=[.!?])\s+', cleaned, maxsplit=1)
            title = sentences[0].strip().rstrip('.').strip('* ')
            body = sentences[1].strip('* ') if len(sentences) > 1 else ''

        # Clean markdown
        title = re.sub(r'\*{1,2}', '', title).strip()
        body = re.sub(r'\*{1,2}', '', body).strip()
        body = re.sub(r'\[?\d+\]?', '', body).strip()  # Remove citation numbers [1]

        if title and len(title) > 5:
            articles.append({
                "title": title[:120],
                "summary": body[:500] if body else title[:500],
                "source": "Perplexity",
                "sources": sources[:3],
            })

    # Fallback: paragraph split
    if not articles and answer.strip():
        paragraphs = [p.strip() for p in answer.split('\n\n') if p.strip()]
        for para in paragraphs[:5]:
            clean = re.sub(r'\*{1,2}', '', para).strip()
            clean = re.sub(r'^\d+[\.\)]\s*', '', clean)
            if len(clean) > 10:
                first_sentence = re.split(r'(?<=[.!?])\s', clean, maxsplit=1)
                articles.append({
                    "title": first_sentence[0][:120].rstrip('.'),
                    "summary": clean[:500],
                    "source": "Perplexity",
                    "sources": sources[:3],
                })

    return articles

    # If parsing didn't produce good results, use the whole answer as one article
    if not articles and answer:
        first_line = answer.split("\n")[0][:120]
        articles.append({
            "title": first_line.rstrip("."),
            "summary": answer[:500],
            "source": "Perplexity",
            "sources": sources[:3],
        })

    return articles


async def get_cached_news(user_id: str, limit: int = 15) -> List[Dict[str, Any]]:
    """Get recent news from proactivity_feed for display."""
    db_service = get_service("database")
    if not db_service:
        return []

    await db_service.initialize()
    client = db_service.get_client()
    if not client:
        return []

    try:
        result = (
            client.table("proactivity_feed")
            .select("id, title, message, metadata, created_at, is_read")
            .eq("user_id", user_id)
            .eq("type", "news")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        articles = []
        for row in result.data or []:
            metadata = {}
            try:
                metadata = json.loads(row.get("metadata", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass

            created = row.get("created_at", "")
            time_ago = _time_ago(created) if created else ""

            articles.append({
                "id": row.get("id", ""),
                "title": row.get("title", ""),
                "summary": row.get("message", ""),
                "source": metadata.get("source", "Perplexity"),
                "time_ago": time_ago,
                "is_read": row.get("is_read", False),
            })

        return articles

    except Exception as e:
        logger.error("News: failed to get cached news: %s", e)
        return []


def _time_ago(dt_str: str) -> str:
    """Convert ISO datetime to human-readable 'X ago' string."""
    try:
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        diff = now - dt
        minutes = int(diff.total_seconds() / 60)
        if minutes < 1:
            return "just now"
        if minutes < 60:
            return f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except Exception:
        return ""
