"""
Research Agent - Handles web research and news queries.

Refactored to use new BaseAgent architecture.
"""

import logging
from typing import Any, Dict, List

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)


@register_agent("research")
class ResearchAgent(BaseAgent):
    """
    Research agent for web research and news queries.

    Handles:
    - Web search
    - News queries
    - Deep research with multiple queries
    - Source citations
    """

    def __init__(self):
        super().__init__(
            name="research",
            description="Handles web research, news queries, and information retrieval"
        )

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Perform research query.

        Args:
            prompt: User's research query
            context: Context with optional queries list for deep research

        Returns:
            AgentResponse with research results and sources
        """
        query = str(context.get("query") or prompt).strip()

        if not query:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao recebi uma consulta para pesquisa.",
                error="Empty query"
            )

        try:
            # Check if deep research is requested
            queries = context.get("queries")
            if isinstance(queries, list) and queries:
                return await self._deep_research(query, queries, context)

            # Standard search
            return await self._standard_search(query)

        except Exception as e:
            self.logger.error(
                f"Research failed: {e}",
                exc_info=True
            )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao foi possivel concluir a pesquisa no momento.",
                error=str(e)
            )

    async def _deep_research(
        self,
        query: str,
        queries: List[str],
        context: Dict[str, Any]
    ) -> AgentResponse:
        """
        Perform deep research with multiple queries.

        Args:
            query: Main topic
            queries: List of sub-queries
            context: Execution context

        Returns:
            AgentResponse with research summary
        """
        topic = str(context.get("topic") or query)

        # Get perplexity service for deep research
        perplexity_svc = get_service("perplexity")
        if not perplexity_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Servico de pesquisa nao disponivel.",
                error="Perplexity service not available"
            )

        await perplexity_svc.initialize()

        # Perform search for each sub-query and aggregate results
        all_answers: List[str] = []
        for sub_query in queries:
            try:
                result = await perplexity_svc.search(sub_query)
                answer = (result.get("answer") or "").strip()
                if answer:
                    all_answers.append(answer)
            except Exception as e:
                self.logger.warning(f"Sub-query failed: {sub_query}: {e}")

        if not all_answers:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao foi possivel gerar um resumo da pesquisa.",
                error="Empty summary from deep research"
            )

        summary = f"Pesquisa sobre: {topic}\n\n" + "\n\n".join(all_answers)

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=summary,
            data={
                "topic": topic,
                "queries": queries,
                "results_count": len(all_answers)
            }
        )

    async def _standard_search(self, query: str) -> AgentResponse:
        """
        Perform standard search via Perplexity service.

        Args:
            query: Search query

        Returns:
            AgentResponse with answer and sources
        """
        perplexity_svc = get_service("perplexity")
        if not perplexity_svc:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Servico de pesquisa nao disponivel.",
                error="Perplexity service not available"
            )

        await perplexity_svc.initialize()

        result = await perplexity_svc.search(query)
        answer = (result.get("answer") or "").strip()
        sources = result.get("sources") or []

        if not answer:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Nao encontrei resultados suficientes para esta pesquisa.",
                error="Empty answer from search"
            )

        # Format sources
        source_items: List[str] = []
        for source in sources[:5]:
            if isinstance(source, dict):
                url = source.get("url")
                if url:
                    source_items.append(str(url))
            elif source:
                source_items.append(str(source))

        # Build response text
        if source_items:
            response_text = f"{answer}\n\nFontes: {', '.join(source_items)}"
        else:
            response_text = answer

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=response_text,
            data={
                "answer": answer,
                "sources": sources,
                "query": query
            }
        )

    def get_capabilities(self) -> List[str]:
        """Get research agent capabilities."""
        return [
            "web_search",
            "news_queries",
            "deep_research",
            "source_citations",
            "information_retrieval"
        ]
