"""Security Knowledge Base — RAG with pgvector for learning from incidents.

Follows the same pattern as rag_service.py: embeds findings and resolutions,
then uses semantic search to inform future confidence scoring.

Uses:
- OpenAI text-embedding-3-small (1536 dims) via embed_text()
- Supabase cyber_knowledge table with pgvector
- match_cyber_knowledge RPC for semantic search
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from cybersecurity.config import KNOWLEDGE_MAX_RESULTS, KNOWLEDGE_SIMILARITY_THRESHOLD

logger = logging.getLogger("cybersecurity.knowledge_base")

# ---------------------------------------------------------------------------
# Embedding helper (same pattern as services/ai/embedding_service.py)
# ---------------------------------------------------------------------------

_openai_client = None


def _get_openai_client():
    global _openai_client
    if _openai_client is None:
        try:
            from openai import AsyncOpenAI
            api_key = os.getenv("OPENAI_API_KEY", "")
            if api_key:
                _openai_client = AsyncOpenAI(api_key=api_key)
        except ImportError:
            logger.warning("openai package not installed — knowledge base embeddings disabled")
    return _openai_client


async def _embed_text(text: str) -> list[float] | None:
    """Embed text using OpenAI text-embedding-3-small (1536 dims)."""
    client = _get_openai_client()
    if not client:
        return None
    try:
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text.strip()[:8000],
        )
        return response.data[0].embedding
    except Exception:
        logger.debug("Failed to generate embedding")
        return None


def _get_db():
    """Get database service client."""
    try:
        from services import get_service
        db = get_service("database")
        if db and db.client:
            return db.client
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Store operations
# ---------------------------------------------------------------------------


async def store_finding(
    finding_title: str,
    finding_content: str,
    severity: str,
    tags: list[str],
    metadata: dict | None = None,
) -> str | None:
    """Store a finding in the knowledge base with embedding.

    Returns the record ID or None on failure.
    """
    client = _get_db()
    if not client:
        logger.debug("Database not available — skipping knowledge store")
        return None

    embedding = await _embed_text(f"{finding_title}\n{finding_content}")

    row = {
        "category": "finding",
        "title": finding_title,
        "content": finding_content[:5000],
        "source": "scanner",
        "severity": severity,
        "tags": tags,
        "metadata": metadata or {},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if embedding:
        row["embedding"] = embedding

    try:
        result = client.table("cyber_knowledge").insert(row).execute()
        if result.data:
            logger.info("Knowledge stored: %s", finding_title[:60])
            return result.data[0].get("id")
    except Exception:
        logger.debug("Failed to store finding in knowledge base")

    return None


async def store_resolution(
    finding_id: str,
    resolution: str,
    was_true_positive: bool,
    finding_title: str = "",
    tags: list[str] | None = None,
) -> str | None:
    """Store a resolution (fix or false_positive) for future learning.

    This is the core learning mechanism — every admin decision gets stored
    so future confidence scoring can reference historical resolutions.
    """
    client = _get_db()
    if not client:
        return None

    category = "fix" if was_true_positive else "false_positive"
    content = f"Finding: {finding_title}\nResolution: {resolution}\nTrue positive: {was_true_positive}"

    embedding = await _embed_text(content)

    row = {
        "category": category,
        "title": f"Resolution for: {finding_title[:100]}",
        "content": content[:5000],
        "source": "admin",
        "severity": None,
        "tags": tags or [],
        "metadata": {"finding_id": finding_id, "was_true_positive": was_true_positive},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if embedding:
        row["embedding"] = embedding

    try:
        result = client.table("cyber_knowledge").insert(row).execute()
        if result.data:
            logger.info("Resolution stored for finding %s (true_positive=%s)", finding_id[:8], was_true_positive)
            return result.data[0].get("id")
    except Exception:
        logger.debug("Failed to store resolution in knowledge base")

    return None


async def store_pattern(
    pattern_title: str,
    pattern_description: str,
    related_finding_ids: list[str],
    severity: str = "medium",
) -> str | None:
    """Store a detected pattern (regression, escalation, correlation)."""
    client = _get_db()
    if not client:
        return None

    content = f"{pattern_title}\n{pattern_description}"
    embedding = await _embed_text(content)

    row = {
        "category": "pattern",
        "title": pattern_title,
        "content": pattern_description[:5000],
        "source": "pattern_recognition",
        "severity": severity,
        "tags": ["pattern"],
        "metadata": {"related_findings": related_finding_ids},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if embedding:
        row["embedding"] = embedding

    try:
        result = client.table("cyber_knowledge").insert(row).execute()
        if result.data:
            return result.data[0].get("id")
    except Exception:
        logger.debug("Failed to store pattern in knowledge base")

    return None


# ---------------------------------------------------------------------------
# Search operations
# ---------------------------------------------------------------------------


async def search_similar(
    query: str,
    threshold: float | None = None,
    limit: int | None = None,
    category: str | None = None,
) -> list[dict]:
    """Semantic search for similar findings/resolutions in the knowledge base.

    Returns list of dicts with: id, category, title, content, severity, tags, similarity
    """
    client = _get_db()
    if not client:
        return []

    embedding = await _embed_text(query)
    if not embedding:
        return []

    _threshold = threshold or KNOWLEDGE_SIMILARITY_THRESHOLD
    _limit = limit or KNOWLEDGE_MAX_RESULTS

    try:
        result = client.rpc("match_cyber_knowledge", {
            "query_embedding": embedding,
            "match_threshold": _threshold,
            "match_count": _limit,
        }).execute()

        results = result.data or []

        # Filter by category if specified
        if category:
            results = [r for r in results if r.get("category") == category]

        return results
    except Exception:
        logger.debug("Failed to search knowledge base")
        return []


async def search_similar_findings(query: str, limit: int = 5) -> list[dict]:
    """Search for similar past findings."""
    return await search_similar(query, category="finding", limit=limit)


async def search_similar_fixes(query: str, limit: int = 5) -> list[dict]:
    """Search for similar past fixes/resolutions."""
    return await search_similar(query, category="fix", limit=limit)


async def search_false_positives(query: str, limit: int = 5) -> list[dict]:
    """Search for similar past false positives."""
    return await search_similar(query, category="false_positive", limit=limit)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


async def get_finding_type_stats(finding_type: str) -> dict:
    """Get stats for a finding type — used to determine auto-fix eligibility.

    Returns: {total, true_positives, false_positives, fixed, true_positive_rate, fix_success_rate}
    """
    client = _get_db()
    if not client:
        return {"total": 0, "true_positives": 0, "false_positives": 0, "fixed": 0}

    try:
        # Count total findings of this type
        total_result = client.table("cyber_findings").select(
            "id", count="exact"
        ).eq("finding_type", finding_type).execute()
        total = total_result.count or 0

        # Count by status
        fixed_result = client.table("cyber_findings").select(
            "id", count="exact"
        ).eq("finding_type", finding_type).eq("status", "fixed").execute()
        fixed = fixed_result.count or 0

        fp_result = client.table("cyber_findings").select(
            "id", count="exact"
        ).eq("finding_type", finding_type).eq("status", "false_positive").execute()
        false_positives = fp_result.count or 0

        true_positives = total - false_positives
        tp_rate = true_positives / total if total > 0 else 0
        fix_rate = fixed / true_positives if true_positives > 0 else 0

        return {
            "total": total,
            "true_positives": true_positives,
            "false_positives": false_positives,
            "fixed": fixed,
            "true_positive_rate": round(tp_rate, 3),
            "fix_success_rate": round(fix_rate, 3),
        }
    except Exception:
        logger.debug("Failed to get finding type stats")
        return {"total": 0, "true_positives": 0, "false_positives": 0, "fixed": 0}
