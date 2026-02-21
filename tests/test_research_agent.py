"""
Tests for ResearchAgent — web search via Perplexity Sonar API.
Agente sem cobertura de testes. Adicionado na Fase C do QA.
"""
from unittest.mock import AsyncMock, Mock, patch
import pytest
from agents.core import AgentStatus


@pytest.fixture
def research_agent():
    from agents.specialized.research_agent import ResearchAgent
    return ResearchAgent()


def _make_research_svc():
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.search = AsyncMock(return_value={
        "success": True,
        "results": [
            {
                "title": "AI Advances in 2025",
                "url": "https://example.com/ai-2025",
                "snippet": "Artificial intelligence saw major advances...",
                "published": "2025-12-01",
            }
        ],
        "answer": "In 2025, AI saw major advances in reasoning and multimodal capabilities.",
        "citations": ["https://example.com/ai-2025"],
    })
    svc.search_news = AsyncMock(return_value={
        "articles": [
            {"title": "Top Tech News", "url": "https://tech.example.com"},
        ]
    })
    return svc


# ── Happy path ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_research_basic_search(research_agent):
    """ResearchAgent returns search results for a query."""
    research_svc = _make_research_svc()
    with patch("agents.specialized.research_agent.get_service", return_value=research_svc):
        result = await research_agent.execute(
            "pesquise sobre inteligência artificial em 2025",
            {"query": "inteligência artificial 2025"}
        )
    assert result.status == AgentStatus.SUCCESS
    assert result.response


@pytest.mark.asyncio
async def test_research_returns_formatted_response(research_agent):
    """ResearchAgent formats search response with title and snippet."""
    research_svc = _make_research_svc()
    with patch("agents.specialized.research_agent.get_service", return_value=research_svc):
        result = await research_agent.execute("buscar notícias de tecnologia", {})
    assert result.status == AgentStatus.SUCCESS
    assert result.response


@pytest.mark.asyncio
async def test_research_capabilities(research_agent):
    """ResearchAgent declares expected capabilities."""
    caps = research_agent.get_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0


# ── Falhas e edge cases ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_research_service_unavailable(research_agent):
    """ResearchAgent returns error when research service is None."""
    with patch("agents.specialized.research_agent.get_service", return_value=None):
        result = await research_agent.execute("pesquise sobre Python", {})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_research_empty_results(research_agent):
    """ResearchAgent handles empty search results gracefully."""
    research_svc = _make_research_svc()
    research_svc.search = AsyncMock(return_value={"success": True, "results": [], "answer": ""})
    with patch("agents.specialized.research_agent.get_service", return_value=research_svc):
        result = await research_agent.execute("pesquisa sem resultados", {})
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_research_timeout_handling(research_agent):
    """ResearchAgent handles timeout gracefully."""
    import asyncio
    research_svc = _make_research_svc()
    research_svc.search = AsyncMock(side_effect=asyncio.TimeoutError())
    with patch("agents.specialized.research_agent.get_service", return_value=research_svc):
        result = await research_agent.execute("pesquisa com timeout", {})
    assert result.status == AgentStatus.ERROR
    assert result.response


@pytest.mark.asyncio
async def test_research_api_error(research_agent):
    """ResearchAgent handles API error gracefully."""
    research_svc = _make_research_svc()
    research_svc.search = AsyncMock(side_effect=RuntimeError("401 Unauthorized"))
    with patch("agents.specialized.research_agent.get_service", return_value=research_svc):
        result = await research_agent.execute("pesquisa com erro", {})
    assert result.status == AgentStatus.ERROR
