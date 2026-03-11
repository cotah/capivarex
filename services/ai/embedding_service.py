"""
Embedding Service — OpenAI text-embedding-3-small for RAG Memory.
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_client: Optional[AsyncOpenAI] = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    return _client


async def embed_text(text: str) -> Optional[List[float]]:
    """
    Generate embedding for a text string using text-embedding-3-small.
    Returns a list of 1536 floats, or None on failure.
    """
    try:
        client = _get_client()
        response = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text.strip()[:8000],
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning(f"Embedding failed: {e}")
        return None
