"""
Tests for GithubAgent — Git and GitHub operations.
Agente sem cobertura de testes. Adicionado na Fase C do QA.
"""

from unittest.mock import AsyncMock, Mock, patch
import pytest
from agents.core import AgentStatus


@pytest.fixture
def github_agent():
    from agents.specialized.github_agent import GitHubAgent

    return GitHubAgent()


def _make_git_svc():
    svc = AsyncMock()
    svc.initialize = AsyncMock()
    svc.is_initialized = Mock(return_value=True)
    svc.get_status = AsyncMock(
        return_value={
            "branch": "main",
            "modified": ["README.md", "requirements.txt"],
            "untracked": ["new_file.py"],
            "staged": [],
            "clean": False,
        }
    )
    svc.commit = AsyncMock(return_value={"success": True, "commit_hash": "abc1234"})
    svc.push = AsyncMock(return_value={"success": True, "branch": "main"})
    svc.create_branch = AsyncMock(
        return_value={"success": True, "branch": "feature/test"}
    )
    svc.clone_repo = AsyncMock(return_value={"success": True, "path": "/tmp/repo"})
    svc.list_repos = AsyncMock(
        return_value=[
            {"name": "capivarex", "private": True, "stars": 0},
            {"name": "other-repo", "private": False, "stars": 5},
        ]
    )
    return svc


# ── Happy path ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_github_status(github_agent):
    """GithubAgent returns git status."""
    git_svc = _make_git_svc()
    with patch("agents.specialized.github_agent.get_service", return_value=git_svc):
        result = await github_agent.execute("status do git", {})
    assert result.status == AgentStatus.SUCCESS
    assert result.response


@pytest.mark.asyncio
async def test_github_commit(github_agent):
    """GithubAgent handles commit command."""
    git_svc = _make_git_svc()
    with patch("agents.specialized.github_agent.get_service", return_value=git_svc):
        result = await github_agent.execute(
            "faça um commit com a mensagem 'fix: update'", {}
        )
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_github_push(github_agent):
    """GithubAgent handles push command."""
    git_svc = _make_git_svc()
    with patch("agents.specialized.github_agent.get_service", return_value=git_svc):
        result = await github_agent.execute("faça push para o GitHub", {})
    assert result.status in (AgentStatus.SUCCESS, AgentStatus.ERROR)
    assert result.response


@pytest.mark.asyncio
async def test_github_capabilities(github_agent):
    """GithubAgent declares expected capabilities."""
    caps = github_agent.get_capabilities()
    assert isinstance(caps, list)
    assert len(caps) > 0


# ── Falhas e edge cases ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_github_service_unavailable(github_agent):
    """GithubAgent returns error when git service is None."""
    with patch("agents.specialized.github_agent.get_service", return_value=None):
        result = await github_agent.execute("status do git", {})
    assert result.status == AgentStatus.ERROR


@pytest.mark.asyncio
async def test_github_exception_handling(github_agent):
    """GitHubAgent handles exceptions gracefully."""
    # Make _get_git_service raise to trigger the top-level except in execute()
    with patch.object(
        github_agent, "_get_git_service", side_effect=RuntimeError("git not found")
    ):
        result = await github_agent.execute("status do git", {})
    assert result.status == AgentStatus.ERROR
    assert result.response
