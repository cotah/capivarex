"""
Research Routes - Refactored to use services.

Endpoints for web search, deep research, and text summarization via
the registered ``perplexity`` service from the refactored service registry.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from api.dependencies import get_current_user
from api.middleware.rate_limit import limiter
from services.core import get_service

logger = logging.getLogger("capivarex.api.routes.research")

router = APIRouter()


# ============================================
# SCHEMAS
# ============================================

class DeepResearchRequest(BaseModel):
    """Request body for the deep research endpoint."""
    topic: str
    queries: List[str]
    model: Optional[str] = "sonar-pro"


class SummarizeRequest(BaseModel):
    """Request body for the summarize endpoint."""
    texts: List[str]
    max_length: Optional[int] = 500


# ============================================
# HELPERS
# ============================================

async def _get_perplexity_service():
    """Resolve and lazily initialise the perplexity service."""
    service = get_service("perplexity")
    if service is None:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=503,
            detail="Perplexity service is not available",
        )
    if not service.is_initialized():
        await service.initialize()
    return service


# ============================================
# ENDPOINTS
# ============================================

@router.get("/search")
@limiter.limit("10/minute")
async def search(
    request: Request,
    q: str = Query(..., description="Search query"),
    model: str = Query("sonar", description="Perplexity model"),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Simple search with Perplexity.

    Args:
        q: Search query string.
        model: Perplexity model to use (sonar, sonar-pro, sonar-reasoning).
        current_user: Authenticated user information.

    Returns:
        Search results with answer and sources.
    """
    service = await _get_perplexity_service()
    result = await service.search(q, model=model)

    return {
        "query": q,
        **result,
    }


@router.post("/deep")
async def deep_search(
    request: DeepResearchRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Deep research with multiple queries.

    Args:
        request: DeepResearchRequest with topic, queries, and model.
        current_user: Authenticated user information.

    Returns:
        Aggregated research results with per-query answers and summary.
    """
    service = await _get_perplexity_service()
    result = await service.deep_research(
        topic=request.topic,
        queries=request.queries,
        model=request.model,
    )

    return result


@router.post("/summarize")
async def summarize(
    request: SummarizeRequest,
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Summarize multiple texts.

    Args:
        request: SummarizeRequest with texts and max_length.
        current_user: Authenticated user information.

    Returns:
        Summary and word count.
    """
    service = await _get_perplexity_service()
    result = await service.summarize_texts(
        texts=request.texts,
        max_length=request.max_length,
    )

    return result
