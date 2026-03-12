"""
RAG Service — Retrieval-Augmented Generation for user memory.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import List

logger = logging.getLogger(__name__)


def _get_db():
    from services import get_service
    return get_service("database")


def _get_client():
    """Get the raw Supabase client from the database service."""
    db = _get_db()
    if not db:
        return None
    return db.get_client()


async def upsert_memory_with_embedding(
    user_id: str,
    key: str,
    value: str,
    source: str = "webapp",
    category: str = "general",
) -> bool:
    """
    Upsert a memory entry with its embedding vector.
    Returns True on success, False on failure.
    """
    from services.ai.embedding_service import embed_text

    client = _get_client()
    if not client:
        return False

    embedding = await embed_text(f"{key}: {value}")

    try:
        row = {
            "user_id": user_id,
            "key": key,
            "value": value,
            "source": source,
            "category": category,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if embedding is not None:
            row["embedding"] = embedding

        client.table("user_memory").upsert(
            row,
            on_conflict="user_id,key",
        ).execute()
        logger.info(f"RAG: upserted memory user={user_id[:8]} key={key[:30]}")
        return True
    except Exception as e:
        logger.error(f"RAG: upsert failed: {e}")
        return False


async def retrieve_relevant_memories(
    user_id: str,
    query: str,
    threshold: float = 0.72,
    limit: int = 5,
) -> List[dict]:
    """
    Find memories semantically similar to the query via pgvector RPC.
    Returns list of dicts with keys: key, value, category, similarity.
    Falls back to empty list on any error.
    """
    from services.ai.embedding_service import embed_text

    client = _get_client()
    if not client:
        return []

    query_embedding = await embed_text(query)
    if query_embedding is None:
        return []

    try:
        result = client.rpc(
            "match_user_memories",
            {
                "query_embedding": query_embedding,
                "match_user_id": user_id,
                "match_threshold": threshold,
                "match_count": limit,
            },
        ).execute()
        return result.data or []
    except Exception as e:
        logger.warning(f"RAG: similarity search failed: {e}")
        return []


def format_memories_for_prompt(memories: List[dict]) -> str:
    """
    Format retrieved memories into a string block for the system prompt.
    """
    if not memories:
        return ""
    lines = [f"- {m['key']}: {m['value']}" for m in memories]
    return (
        "\n\n## Relevant Memories (retrieved from long-term memory"
        " \u2014 use these naturally in conversation):\n"
        + "\n".join(lines)
    )


async def extract_and_save_memory(user_id: str, message: str) -> None:
    """Extrai e salva memória de uma mensagem do usuário. Non-blocking."""
    try:
        from services.ai.embedding_service import embed_text

        client = _get_client()
        if not client:
            return

        from openai import AsyncOpenAI

        ai = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # Passo 1: Classificar se a mensagem tem informação memorável
        classification = await ai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract memorable personal facts from user messages. "
                        'Reply with JSON: {"memorable": true/false, "fact": "...", '
                        '"category": "preference|habit|goal|personal|work|health|other"}. '
                        "Only mark as memorable if it's a clear personal fact worth "
                        "remembering. fact should be a clean, concise statement in "
                        "third person."
                    ),
                },
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},
            max_tokens=150,
        )

        result = json.loads(classification.choices[0].message.content)

        if not result.get("memorable"):
            return

        fact = result.get("fact", "").strip()
        category = result.get("category", "general")

        if not fact:
            return

        # Passo 2: Gerar embedding do facto
        embedding = await embed_text(fact)
        if embedding is None:
            return

        # Passo 3: Verificar se já existe memória similar (evitar duplicatas)
        existing = (
            client.table("user_memory")
            .select("id, content")
            .eq("user_id", user_id)
            .eq("category", category)
            .execute()
        )

        for mem in existing.data or []:
            if _text_similarity(mem.get("content", ""), fact) > 0.85:
                return  # já existe memória similar

        # Passo 4: Salvar no banco
        client.table("user_memory").insert(
            {
                "user_id": user_id,
                "content": fact,
                "category": category,
                "confidence": 0.9,
                "source": "chat",
                "embedding": embedding,
            }
        ).execute()

        logger.info(
            "Memory saved for user %s: [%s] %s",
            user_id[:8],
            category,
            fact[:50],
        )

    except Exception as e:
        logger.warning("Memory extraction failed (non-blocking): %s", e)


def _text_similarity(a: str, b: str) -> float:
    """Similaridade simples por palavras comuns (Jaccard, sem dependências extras)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


async def get_relevant_memories(
    user_id: str,
    query: str,
    limit: int = 5,
    min_similarity: float = 0.75,
) -> list[dict]:
    """Busca memórias relevantes para o contexto actual via pgvector."""
    try:
        from services.ai.embedding_service import embed_text

        client = _get_client()
        if not client:
            return []

        query_embedding = await embed_text(query)
        if query_embedding is None:
            return []

        result = client.rpc(
            "match_user_memories",
            {
                "query_embedding": query_embedding,
                "match_user_id": user_id,
                "match_threshold": min_similarity,
                "match_count": limit,
            },
        ).execute()

        return result.data or []

    except Exception as e:
        logger.warning("Memory retrieval failed (non-blocking): %s", e)
        return []


def format_memories_for_context(memories: list[dict]) -> str:
    """Formata memórias para injeção no contexto do agente."""
    if not memories:
        return ""
    lines = ["[O que eu sei sobre você:]"]
    for mem in memories:
        category = mem.get("category", "general")
        content = mem.get("content", "") or mem.get("value", "")
        lines.append(f"- [{category}] {content}")
    return "\n".join(lines)
