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

# Categories to fetch
NEWS_CATEGORIES = [
    {
        "query": "Top 5 most important financial and business news stories today. Include stock market movements, crypto trends, and major economic events. Be concise — one paragraph per story.",
        "type": "finance_news",
    },
]


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

    for category in NEWS_CATEGORIES:
        try:
            result = await perplexity.search(
                query=category["query"],
                model="sonar",
            )

            answer = result.get("answer", "")
            sources = result.get("sources", [])

            if not answer:
                continue

            # Parse the answer into individual articles
            parsed = _parse_news_response(answer, sources)
            articles.extend(parsed)

        except Exception as e:
            logger.error("News: fetch failed for %s: %s", category["type"], e)

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
    articles = []

    # Split by numbered items or double newlines
    paragraphs = [p.strip() for p in answer.split("\n") if p.strip()]

    current_title = ""
    current_body = ""

    for para in paragraphs:
        # Check if it starts with a number (numbered list)
        stripped = para.lstrip("0123456789.-) ")
        if para != stripped and len(stripped) > 10:
            # Save previous article
            if current_title and current_body:
                articles.append({
                    "title": current_title[:120],
                    "summary": current_body[:500],
                    "source": "Perplexity",
                    "sources": sources[:3],
                })
            # Start new article
            # Title is first sentence, body is the rest
            sentences = stripped.split(". ", 1)
            current_title = sentences[0].rstrip(".") if sentences else stripped[:80]
            current_body = sentences[1] if len(sentences) > 1 else stripped
        elif para.startswith("**") and para.endswith("**"):
            # Bold header = title
            if current_title and current_body:
                articles.append({
                    "title": current_title[:120],
                    "summary": current_body[:500],
                    "source": "Perplexity",
                    "sources": sources[:3],
                })
            current_title = para.strip("*").strip()
            current_body = ""
        else:
            current_body += " " + para if current_body else para

    # Don't forget the last article
    if current_title and current_body:
        articles.append({
            "title": current_title[:120],
            "summary": current_body[:500],
            "source": "Perplexity",
            "sources": sources[:3],
        })

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
