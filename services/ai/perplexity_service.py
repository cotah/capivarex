"""
Perplexity Service - Refactored with BaseService architecture.

Provides:
- Web search via Perplexity API
- Deep research with multiple queries
- Text summarization
- Metrics tracking
"""

import os
import time
import logging
from typing import Dict, Any, List, Optional

import httpx
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)


@register_service("perplexity")
class PerplexityService(BaseService):
    """
    Perplexity service for web search and research.

    Features:
    - Web search via Perplexity API
    - Deep research with multiple queries
    - Text summarization
    - Automatic retry on failures
    - Metrics tracking
    """

    def __init__(self, name: str = "perplexity", config: Optional[Dict[str, Any]] = None):
        """Initialise the Perplexity service."""
        super().__init__(name, config)
        self.api_key: Optional[str] = None
        self.base_url: str = "https://api.perplexity.ai"

    async def _initialize(self) -> None:
        """Initialize Perplexity service."""
        self.api_key = os.environ.get("SONAR_API_KEY")

        if not self.api_key:
            raise ServiceUnavailableError(
                "SONAR_API_KEY not found in environment variables"
            )

        self.logger.info("Perplexity service initialized successfully")

    async def _health_check(self) -> bool:
        """Check if Perplexity service is healthy."""
        return self.api_key is not None

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def search(
        self,
        query: str,
        model: str = "sonar",
    ) -> Dict[str, Any]:
        """
        Search using Perplexity API.

        Args:
            query: Search query
            model: Perplexity model (sonar, sonar-pro, sonar-reasoning)

        Returns:
            Dict with answer and sources

        Raises:
            RuntimeError: If the request fails
        """
        if not self.api_key:
            await self.initialize()

        start_time = time.time()

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a helpful research assistant. Provide accurate, well-sourced information.",
                },
                {
                    "role": "user",
                    "content": query,
                },
            ],
            "temperature": 0.2,
            "max_tokens": 2000,
        }

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            answer = data["choices"][0]["message"]["content"]
            citations = data.get("citations", [])

            self.logger.info(f"Perplexity search completed for query: {query[:50]}...")

            return {
                "answer": answer,
                "sources": citations,
                "model": model,
            }

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)
            self.logger.error(f"Perplexity search failed: {e}", exc_info=True)
            raise RuntimeError(f"Erro na pesquisa Perplexity: {str(e)}")

    async def deep_research(
        self,
        topic: str,
        queries: List[str],
        model: str = "sonar-pro",
    ) -> Dict[str, Any]:
        """
        Deep research with multiple queries.

        Args:
            topic: Main research topic
            queries: List of related queries
            model: Perplexity model

        Returns:
            Dict with results from all queries + summary
        """
        results: List[Dict[str, Any]] = []
        all_sources: List[Any] = []

        for query in queries:
            try:
                result = await self.search(query, model=model)
                results.append({
                    "query": query,
                    "answer": result["answer"],
                    "sources": result["sources"],
                })
                all_sources.extend(result["sources"])
            except Exception as e:
                self.logger.warning(f"Query failed in deep research: {query}: {e}")
                results.append({
                    "query": query,
                    "answer": f"Error: {str(e)}",
                    "sources": [],
                })

        # Generate summary of all findings
        summary_query = f"Summarize the following research on '{topic}':\n\n"
        for i, result in enumerate(results, 1):
            summary_query += f"{i}. {result['query']}\n{result['answer']}\n\n"

        try:
            summary_result = await self.search(summary_query, model=model)
            summary = summary_result["answer"]
        except Exception as e:
            self.logger.warning(f"Summary generation failed: {e}")
            summary = "Could not generate summary."

        unique_sources = set()
        for s in all_sources:
            if isinstance(s, str):
                unique_sources.add(s)
            elif isinstance(s, dict):
                unique_sources.add(s.get("url", ""))

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
        Summarize multiple texts.

        Args:
            texts: List of texts to summarize
            max_length: Maximum length of summary (in words)

        Returns:
            Dict with summary and word_count
        """
        combined_text = "\n\n---\n\n".join(texts)
        query = f"Summarize the following text in approximately {max_length} words:\n\n{combined_text}"

        result = await self.search(query, model="sonar")
        summary = result["answer"]
        word_count = len(summary.split())

        return {
            "summary": summary,
            "word_count": word_count,
        }


# Singleton getter
_perplexity_service: Optional[PerplexityService] = None


def get_perplexity_service() -> PerplexityService:
    """Get global perplexity service instance."""
    global _perplexity_service
    if _perplexity_service is None:
        from services.core import get_service
        _perplexity_service = get_service("perplexity")
    return _perplexity_service


# Backward compatibility
async def search_perplexity(query: str, model: str = "sonar") -> Dict[str, Any]:
    """Search using Perplexity (backward compatibility)."""
    from services.core import get_service
    service = get_service("perplexity")
    if service and isinstance(service, PerplexityService):
        if not service.is_initialized():
            await service.initialize()
        return await service.search(query, model=model)
    return {"answer": "", "sources": [], "model": model}


async def deep_research(
    topic: str, queries: List[str], model: str = "sonar-pro"
) -> Dict[str, Any]:
    """Deep research (backward compatibility)."""
    from services.core import get_service
    service = get_service("perplexity")
    if service and isinstance(service, PerplexityService):
        if not service.is_initialized():
            await service.initialize()
        return await service.deep_research(topic, queries, model=model)
    return {"topic": topic, "results": [], "summary": "", "total_sources": 0}
