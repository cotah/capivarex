"""
Git utilities for CAPIVAREX Bot.

Provides:
- Git command wrappers
- Status checking
- Commit and push operations
"""

import subprocess
import logging
from typing import List, Optional

logger = logging.getLogger("unbx_bot.utils.git")


def run_git_command(cmd: List[str], cwd: Optional[str] = None) -> str:
    """
    Run a git command and return output.

    Args:
        cmd: Git command as list (e.g., ["git", "status"])
        cwd: Working directory (optional)

    Returns:
        Command output or error message
    """
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"❌ Git error: {result.stderr.strip()}"

    except subprocess.TimeoutExpired:
        return "❌ Git command timed out"
    except Exception as e:
        logger.error(f"Git command failed: {e}")
        return f"❌ Git error: {e}"


def git_status(cwd: Optional[str] = None) -> str:
    """Get git status."""
    return run_git_command(["git", "status"], cwd=cwd)


def git_add_all(cwd: Optional[str] = None) -> str:
    """Stage all changes."""
    return run_git_command(["git", "add", "."], cwd=cwd)


def git_commit(message: str, cwd: Optional[str] = None) -> str:
    """Commit staged changes."""
    return run_git_command(["git", "commit", "-m", message], cwd=cwd)


def git_push(cwd: Optional[str] = None) -> str:
    """Push commits to remote."""
    return run_git_command(["git", "push"], cwd=cwd)


def git_init(cwd: Optional[str] = None) -> str:
    """Initialize git repository."""
    return run_git_command(["git", "init"], cwd=cwd)


def git_log(limit: int = 10, cwd: Optional[str] = None) -> str:
    """Get git log."""
    return run_git_command(
        ["git", "log", f"--max-count={limit}", "--oneline"],
        cwd=cwd
    )


def git_diff(cwd: Optional[str] = None) -> str:
    """Get git diff."""
    return run_git_command(["git", "diff"], cwd=cwd)


def git_branch(cwd: Optional[str] = None) -> str:
    """Get current branch."""
    return run_git_command(["git", "branch", "--show-current"], cwd=cwd)


def suggest_commit_message(mode: str, version: str) -> str:
    """
    Suggest a commit message based on mode and version.

    Args:
        mode: Current bot mode
        version: Bot version

    Returns:
        Suggested commit message
    """
    return f"v{version}: atualizações no modo {mode}"


def has_uncommitted_changes(cwd: Optional[str] = None) -> bool:
    """
    Check if there are uncommitted changes.

    Args:
        cwd: Working directory (optional)

    Returns:
        True if there are uncommitted changes
    """
    status = git_status(cwd=cwd)
    return "nothing to commit" not in status.lower()
