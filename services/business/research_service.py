"""
Research Service - Refactored Architecture.

Provides news search, deep research, and text summarization by delegating
to the PerplexityService registered in the service registry.

Features:
- News search with structured results (summary + sources)
- Deep multi-query research with aggregated summaries
- Text summarization
- Full BaseService lifecycle (initialize / health_check / metrics)
- No imports from the legacy ``services/`` package

Architecture:
    ResearchService  -->  PerplexityService (via registry)
                              |
                        Perplexity API
"""

import logging
import time
from typing import Any, Dict, List, Optional

from services.core import (
    BaseService,
    register_service,
    get_service,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)


@register_service("research")
class ResearchService(BaseService):
    """
    Service for news research and web searches.

    Delegates the actual Perplexity API calls to the registered
    ``perplexity`` service, adding a higher-level research-oriented API
    with structured return values.

    Methods:
    - search_news        -- single-query news search
    - deep_research      -- multi-query research with summary
    - summarize_texts    -- summarise a list of texts
    """

    def __init__(
        self,
        name: str = "research",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, config)
        self._perplexity: Optional[Any] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """
        Resolve and initialise the underlying PerplexityService.

        Raises:
            ServiceUnavailableError: If the perplexity service cannot be
                found or initialised.
        """
        perplexity = get_service("perplexity")

        if perplexity is None:
            raise ServiceUnavailableError(
                "PerplexityService is not registered in the service registry. "
                "Make sure the 'ai' package is loaded before 'business'."
            )

        if not perplexity.is_initialized():
            await perplexity.initialize()

        self._perplexity = perplexity
        self.logger.info("ResearchService initialised (perplexity delegate ready)")

    async def _health_check(self) -> bool:
        """
        Check health by verifying the perplexity delegate is available
        and healthy.
        """
        if self._perplexity is None:
            return False

        try:
            await self._perplexity.health_check()
            return self._perplexity.is_healthy()
        except Exception as exc:
            self.logger.warning(f"Perplexity health-check failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _ensure_perplexity(self) -> Any:
        """
        Ensure the perplexity delegate is available, attempting lazy
        initialisation if necessary.

        Returns:
            The PerplexityService instance.

        Raises:
            ServiceUnavailableError: If still unavailable after attempt.
        """
        if self._perplexity is not None and self._perplexity.is_initialized():
            return self._perplexity

        # Attempt late initialisation
        if not self._initialized:
            await self.initialize()

        if self._perplexity is None:
            raise ServiceUnavailableError(
                "PerplexityService is not available. Cannot perform research."
            )
        return self._perplexity

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def search_news(self, query: str) -> Dict[str, Any]:
        """
        Search news and return a structured result.

        This is the primary method consumed by other services (e.g. the
        ProactivityService).

        Args:
            query: News search query.

        Returns:
            Dict with keys ``summary``, ``sources``, and ``query``.

        Raises:
            RuntimeError: If the underlying search fails.
        """
        perplexity = await self._ensure_perplexity()
        start_time = time.time()

        try:
            result = await perplexity.search(query, model="sonar")
            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "summary": result.get("answer", ""),
                "sources": result.get("sources", []),
                "query": query,
            }

        except Exception as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"News search failed for query '{query}': {exc}")
            raise RuntimeError(f"News search failed: {exc}") from exc

    async def deep_research(
        self,
        topic: str,
        queries: List[str],
        model: str = "sonar-pro",
    ) -> Dict[str, Any]:
        """
        Perform deep research with multiple queries and an aggregated
        summary.

        Args:
            topic: Main research topic.
            queries: List of related sub-queries.
            model: Perplexity model to use (default ``sonar-pro``).

        Returns:
            Dict with ``topic``, ``results`` (per-query), ``summary``,
            and ``total_sources``.
        """
        perplexity = await self._ensure_perplexity()
        start_time = time.time()

        results: List[Dict[str, Any]] = []
        all_sources: List[Any] = []

        for query in queries:
            try:
                result = await perplexity.search(query, model=model)
                results.append({
                    "query": query,
                    "answer": result["answer"],
                    "sources": result["sources"],
                })
                all_sources.extend(result["sources"])
            except Exception as exc:
                self.logger.warning(
                    f"Sub-query failed in deep research: '{query}': {exc}"
                )
                results.append({
                    "query": query,
                    "answer": f"Error: {exc}",
                    "sources": [],
                })

        # Generate an aggregated summary
        summary_query = f"Summarize the following research on '{topic}':\n\n"
        for idx, res in enumerate(results, 1):
            summary_query += f"{idx}. {res['query']}\n{res['answer']}\n\n"

        try:
            summary_result = await perplexity.search(summary_query, model=model)
            summary = summary_result["answer"]
        except Exception as exc:
            self.logger.warning(f"Summary generation failed: {exc}")
            summary = "Could not generate summary."

        # Deduplicate sources
        unique_sources: set = set()
        for src in all_sources:
            if isinstance(src, str):
                unique_sources.add(src)
            elif isinstance(src, dict):
                unique_sources.add(src.get("url", ""))

        latency = time.time() - start_time
        self._track_call(latency, error=False)

        self.logger.info(
            f"Deep research completed for topic '{topic}' "
            f"({len(queries)} queries, {len(unique_sources)} unique sources)"
        )

        return {
            "topic": topic,
            "results": results,
            "summary": summary,
            "total_sources": len(unique_sources),
        }

    async def summarize_texts(
        self,
        texts: List[str],
        max_length: int = 500,
    ) -> Dict[str, Any]:
        """
        Summarise multiple texts into a single summary.

        Args:
            texts: List of texts to summarise.
            max_length: Approximate maximum length in words.

        Returns:
            Dict with ``summary`` and ``word_count``.
        """
        perplexity = await self._ensure_perplexity()
        start_time = time.time()

        combined_text = "\n\n---\n\n".join(texts)
        query = (
            f"Summarize the following text in approximately "
            f"{max_length} words:\n\n{combined_text}"
        )

        try:
            result = await perplexity.search(query, model="sonar")
            summary = result["answer"]
            word_count = len(summary.split())

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            return {
                "summary": summary,
                "word_count": word_count,
            }

        except Exception as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Text summarisation failed: {exc}")
            raise RuntimeError(f"Text summarisation failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Backward-compatibility helpers
# ---------------------------------------------------------------------------

def get_research_service() -> ResearchService:
    """
    Get the ResearchService singleton from the global registry.

    Returns:
        ResearchService instance (creates a default one if not registered).
    """
    service = get_service("research")
    if isinstance(service, ResearchService):
        return service

    # Fallback: return a fresh instance (will still need initialisation)
    logger.warning(
        "ResearchService not found in registry, creating standalone instance"
    )
    return ResearchService()
