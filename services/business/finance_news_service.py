"""
Finance News Service — S5: Personalized news via Perplexity + GPT humanization.

Fetches daily news PERSONALIZED per user based on:
- User's stock/crypto watchlist
- User's interests from RAG memory
- User's profession/background from user_context

All output is HUMANIZED through GPT — never robotic, always conversational.

Runs 2x/day (07:00 and 18:00 UTC) via proactivity loop.
Stores articles in proactivity_feed for display on Finance → News.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# User Interest Extraction
# ---------------------------------------------------------------------------


async def _get_user_interests(user_id: str) -> Dict[str, Any]:
    """Extract user interests from watchlist + RAG + user_context.

    Returns:
        {
            "stocks": ["AAPL", "TSLA"],
            "crypto": ["bitcoin", "ethereum"],
            "topics": ["AI", "startups", "real estate"],
            "profession": "software engineer",
            "name": "Marcos",
        }
    """
    interests: Dict[str, Any] = {
        "stocks": [],
        "crypto": [],
        "topics": [],
        "profession": "",
        "name": "",
    }

    # 1. Get watchlist (stocks + crypto the user follows)
    try:
        from services.business.weekly_recap_service import get_user_watchlist

        watchlist = await get_user_watchlist(user_id)
        interests["stocks"] = watchlist.get("stocks", [])
        interests["crypto"] = watchlist.get("crypto", [])
    except Exception:
        pass

    # 2. Get user profile (name, location, profession)
    db = get_service("database")
    if db and db.is_initialized():
        try:
            client = db.get_client()
            user = (
                client.table("users")
                .select("full_name, location_preference")
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            if user.data:
                interests["name"] = user.data[0].get("full_name", "")
        except Exception:
            pass

        # 3. Get user interests from user_context
        try:
            client = db.get_client()
            ctx = (
                client.table("user_context")
                .select("context_data")
                .eq("user_id", user_id)
                .eq("context_type", "user_interests")
                .limit(1)
                .execute()
            )
            if ctx.data:
                data = ctx.data[0].get("context_data", {})
                if isinstance(data, str):
                    data = json.loads(data)
                interests["topics"] = data.get("topics", [])
                interests["profession"] = data.get("profession", "")
        except Exception:
            pass

    # 4. Try RAG for additional context
    rag = get_service("rag")
    if rag and rag.is_initialized() and not interests["topics"]:
        try:
            results = await rag.search(
                user_id, "my interests hobbies profession work", limit=3
            )
            if results and isinstance(results, list):
                # Extract keywords from RAG results
                for r in results:
                    text = r.get("content", r.get("text", ""))[:200]
                    if text:
                        interests["topics"].append(text)
        except Exception:
            pass

    return interests


def _build_personalized_query(interests: Dict[str, Any]) -> str:
    """Build a Perplexity query personalized to user's interests."""
    parts = []

    # Stock-specific news
    if interests["stocks"]:
        stock_str = ", ".join(interests["stocks"][:5])
        parts.append(f"stocks: {stock_str}")

    # Crypto-specific news
    if interests["crypto"]:
        crypto_str = ", ".join(interests["crypto"][:3])
        parts.append(f"crypto: {crypto_str}")

    # Topic-specific news
    if interests["topics"]:
        # topics might be short keywords or RAG text snippets
        topic_str = ", ".join(
            t[:50] if isinstance(t, str) else str(t) for t in interests["topics"][:5]
        )
        parts.append(f"interests: {topic_str}")

    if not parts:
        return (
            "Top 5 most important financial and business news stories today. "
            "Focus on: global macro events, stock market movements, "
            "crypto trends, central bank decisions, and tech industry. "
            "Be concise — one paragraph per story with clear title."
        )

    focus = "; ".join(parts)
    return (
        f"Top 5 most important news stories today relevant to someone who follows: {focus}. "
        "Mix financial markets + industry news + macro events. "
        "Prioritize stories that directly affect their tracked assets or interests. "
        "Be concise — one paragraph per story with clear title."
    )


# ---------------------------------------------------------------------------
# News Fetching + Humanization
# ---------------------------------------------------------------------------


async def fetch_and_store_news(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """Fetch PERSONALIZED news per user via Perplexity, humanize via GPT.

    Args:
        user_id: If provided, fetch/store only for this user.
                 If None, fetch for all users with proactivity enabled.

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

    # Get target users
    user_ids = []
    if user_id:
        user_ids = [user_id]
    else:
        try:
            result = (
                client.table("proactivity_preferences")
                .select("user_id")
                .eq("enabled", True)
                .execute()
            )
            user_ids = [r["user_id"] for r in (result.data or [])]
        except Exception:
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
        return []

    all_articles: List[Dict[str, Any]] = []
    now = datetime.now(timezone.utc).isoformat()

    for uid in user_ids:
        try:
            # 1. Get this user's interests
            interests = await _get_user_interests(uid)

            # 2. Build personalized query
            query = _build_personalized_query(interests)
            logger.info("News: fetching for user=%s query_len=%d", uid[:8], len(query))

            # 3. Fetch from Perplexity
            result = await perplexity.search(query=query, model="sonar")
            answer = result.get("answer", "")
            sources = result.get("sources", [])

            if not answer:
                continue

            # 4. Parse into individual articles
            articles = _parse_news_response(answer, sources)
            if not articles:
                continue

            # 5. Humanize through GPT
            user_name = interests.get("name", "")
            humanized = await _humanize_news(articles, user_name, interests)

            # 6. Store in proactivity_feed
            for article in humanized:
                try:
                    client.table("proactivity_feed").insert(
                        {
                            "user_id": uid,
                            "type": "news",
                            "title": article["title"],
                            "message": article["summary"],
                            "metadata": json.dumps(
                                {
                                    "source": article.get("source", ""),
                                    "sources": article.get("sources", []),
                                    "category": "finance",
                                    "personalized": True,
                                }
                            ),
                            "is_read": False,
                            "created_at": now,
                        }
                    ).execute()
                except Exception as e:
                    logger.warning("News: store failed user=%s: %s", uid[:8], e)

            all_articles.extend(humanized)
            logger.info("News: stored %d articles for user=%s", len(humanized), uid[:8])

        except Exception as e:
            logger.error("News: fetch failed for user=%s: %s", uid[:8], e)

    return all_articles


async def _humanize_news(
    articles: List[Dict[str, Any]],
    user_name: str,
    interests: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Pass raw articles through GPT to humanize titles and summaries.

    Each article gets a warm, conversational summary instead of dry text.
    """
    openai_svc = get_service("openai")
    name = user_name.split()[0] if user_name else "friend"

    if not openai_svc or not openai_svc.is_initialized():
        # Fallback: return articles with light touch-up
        return _light_humanize(articles, name)

    # Build all articles into one prompt for efficiency
    raw_articles = "\n".join(
        f"{i + 1}. TITLE: {a['title']}\n   BODY: {a['summary']}"
        for i, a in enumerate(articles[:5])
    )

    prompt = f"""You are CAPIVAREX, a personal AI assistant with personality. Rewrite these news articles for {name}.

RULES:
- Rewrite each title to be engaging and conversational (not clickbait)
- Rewrite each summary in 2-3 sentences, warm and relatable
- If the news affects {name}'s stocks ({", ".join(interests.get("stocks", [])[:3])}) or crypto ({", ".join(interests.get("crypto", [])[:2])}), mention it personally: "This could affect your TSLA position"
- Use emojis naturally (1-2 per article max)
- Sound like a smart friend telling you the news over coffee
- Keep the factual accuracy — don't invent information

BAD (robotic): "Apple Inc. reported Q4 earnings of $1.46 per share, beating estimates."
GOOD (human): "Your Apple stock had a great day 📈 They crushed their Q4 earnings — $1.46 per share vs $1.39 expected. The market loved it."

ORIGINAL ARTICLES:
{raw_articles}

Respond with ONLY a JSON array. Each item: {{"title": "...", "summary": "..."}}
No markdown, no backticks, no extra text. Just the JSON array."""

    try:
        import asyncio

        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=800,
            temperature=0.8,
        )

        # Extract text from response
        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        parsed = json.loads(text)
        if isinstance(parsed, list):
            # Merge humanized text with original metadata
            humanized = []
            for i, item in enumerate(parsed[: len(articles)]):
                original = articles[i] if i < len(articles) else {}
                humanized.append(
                    {
                        "title": item.get("title", original.get("title", "")),
                        "summary": item.get("summary", original.get("summary", "")),
                        "source": original.get("source", "Perplexity"),
                        "sources": original.get("sources", []),
                    }
                )
            return humanized

    except Exception as e:
        logger.warning("News: GPT humanization failed: %s", e)

    # Fallback
    return _light_humanize(articles, name)


def _light_humanize(articles: List[Dict[str, Any]], name: str) -> List[Dict[str, Any]]:
    """Light humanization when GPT is unavailable — add emojis and warmth."""
    icons = ["📰", "📈", "🌍", "💡", "🔔"]
    result = []
    for i, article in enumerate(articles):
        icon = icons[i % len(icons)]
        title = article.get("title", "")
        summary = article.get("summary", "")
        result.append(
            {
                "title": f"{icon} {title}",
                "summary": summary,
                "source": article.get("source", "Perplexity"),
                "sources": article.get("sources", []),
            }
        )
    return result


def _parse_news_response(answer: str, sources: List[str]) -> List[Dict[str, Any]]:
    """Parse Perplexity response into individual news articles."""
    import re

    articles = []

    # Split on numbered items OR bold headers at start of line/paragraph
    # Handles: "**1. Title** body", "1. Title. Body", "**Title**\nBody"
    parts = re.split(r"\n(?=\s*\*{0,2}\s*\d+[\.\)]\s)", answer)

    # If only 1 part, try splitting on double-newline + bold header
    if len(parts) <= 1:
        parts = re.split(r"\n\n(?=\*\*)", answer)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Remove leading number: "1. " or "**1. " or "**1) "
        cleaned = re.sub(r"^\s*\*{0,2}\s*\d+[\.\)]\s*", "", part)
        if not cleaned:
            continue

        # Extract title and body
        # Handle "**Title** body" or "**Title.**\nbody"
        bold_match = re.match(r"\*\*(.+?)\*\*\.?\s*(.*)", cleaned, re.DOTALL)
        if bold_match:
            title = bold_match.group(1).strip().rstrip(".")
            body = bold_match.group(2).strip()
        else:
            # No bold — first sentence is title
            sentences = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)
            title = sentences[0].strip().rstrip(".").strip("* ")
            body = sentences[1].strip("* ") if len(sentences) > 1 else ""

        # Clean markdown
        title = re.sub(r"\*{1,2}", "", title).strip()
        body = re.sub(r"\*{1,2}", "", body).strip()
        body = re.sub(r"\[?\d+\]?", "", body).strip()  # Remove citation numbers [1]

        if title and len(title) > 5:
            articles.append(
                {
                    "title": title[:120],
                    "summary": body[:500] if body else title[:500],
                    "source": "Perplexity",
                    "sources": sources[:3],
                }
            )

    # Fallback: paragraph split
    if not articles and answer.strip():
        paragraphs = [p.strip() for p in answer.split("\n\n") if p.strip()]
        for para in paragraphs[:5]:
            clean = re.sub(r"\*{1,2}", "", para).strip()
            clean = re.sub(r"^\d+[\.\)]\s*", "", clean)
            if len(clean) > 10:
                first_sentence = re.split(r"(?<=[.!?])\s", clean, maxsplit=1)
                articles.append(
                    {
                        "title": first_sentence[0][:120].rstrip("."),
                        "summary": clean[:500],
                        "source": "Perplexity",
                        "sources": sources[:3],
                    }
                )

    return articles

    # If parsing didn't produce good results, use the whole answer as one article
    if not articles and answer:
        first_line = answer.split("\n")[0][:120]
        articles.append(
            {
                "title": first_line.rstrip("."),
                "summary": answer[:500],
                "source": "Perplexity",
                "sources": sources[:3],
            }
        )

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

            articles.append(
                {
                    "id": row.get("id", ""),
                    "title": row.get("title", ""),
                    "summary": row.get("message", ""),
                    "source": metadata.get("source", "Perplexity"),
                    "time_ago": time_ago,
                    "is_read": row.get("is_read", False),
                }
            )

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
