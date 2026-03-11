"""
RAG Service — Retrieval-Augmented Generation for user memory.
"""
from __future__ import annotations

import json
import logging
import os
import re
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


async def extract_and_save_memory(
    user_id: str,
    user_msg: str,
) -> None:
    """
    Background task: use GPT-4o-mini to extract memorable facts from user message
    and save them to user_memory with embeddings.
    Only runs if message likely contains personal information.
    """
    MEMORY_TRIGGERS = [
        "me chamo",
        "meu nome",
        "moro em",
        "moro na",
        "moro no",
        "trabalho",
        "minha profiss\u00e3o",
        "tenho",
        "anos",
        "meu email",
        "meu telefone",
        "minha fam\u00edlia",
        "meu filho",
        "minha filha",
        "meu marido",
        "minha esposa",
        "meu parceiro",
        "minha parceira",
        "gosto de",
        "n\u00e3o gosto",
        "prefiro",
        "odeio",
        "adoro",
        "my name",
        "i live",
        "i work",
        "i am",
        "i'm",
        "me llamo",
        "vivo en",
        "trabajo",
        "minha cidade",
        "meu bairro",
        "meu carro",
        "meu pet",
        "meu cachorro",
        "meu gato",
        "sou de",
        "nasci em",
        "tenho filho",
        "tenho filha",
    ]
    msg_lower = user_msg.lower()
    if not any(trigger in msg_lower for trigger in MEMORY_TRIGGERS):
        return

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        extraction_prompt = (
            "Extract personal facts from this user message that are worth"
            " remembering long-term.\n"
            "Return a JSON array of objects with 'key', 'value', and"
            " 'category' fields.\n"
            "Category must be one of: personal, location, preference,"
            " family, work, other.\n"
            "Maximum 3 items. Only extract clear, factual personal"
            " information.\n"
            "If nothing worth saving, return [].\n\n"
            f'User message: "{user_msg}"\n\nJSON array:'
        )

        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": extraction_prompt}],
            max_tokens=200,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()

        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return
        facts = json.loads(json_match.group())

        for fact in facts[:3]:
            if isinstance(fact, dict) and fact.get("key") and fact.get("value"):
                await upsert_memory_with_embedding(
                    user_id=user_id,
                    key=str(fact["key"]),
                    value=str(fact["value"]),
                    source="webapp_chat",
                    category=str(fact.get("category", "general")),
                )
    except Exception as e:
        logger.debug(f"Memory extraction failed (non-fatal): {e}")
