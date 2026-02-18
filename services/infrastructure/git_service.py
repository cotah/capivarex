"""
Git Service - Refactored with BaseService architecture.

Git operations via GitPython with authenticated remote support.

Provides:
- Repository initialization, commit, status, log
- Branch creation and checkout
- Remote operations: clone, add remote, push, pull
- Path-traversal validation for security
- Metrics tracking and health checks
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from git import Repo, GitCommandError
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
)

load_dotenv(override=True)


@register_service("git")
class GitService(BaseService):
    """
    Git operations service built on GitPython.

    Features:
    - Local operations: init, commit, status, log, branch, checkout
    - Remote operations: clone, add_remote, push, pull
    - GitHub token authentication via environment or per-call override
    - Path-traversal protection on all path-based operations
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "git",
        config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, config)
        self.github_token: Optional[str] = None
        self.base_workspace: Optional[Path] = None

    # ------------------------------------------------------------------
    # BaseService lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Load GitHub token from config or environment."""
        self.github_token = self._get_config(
            "github_token",
            os.environ.get("GITHUB_TOKEN"),
        )
        workspace = self._get_config("base_workspace", "./workspace")
        self.base_workspace = Path(workspace).resolve()

        if not self.github_token:
            self.logger.warning(
                "GITHUB_TOKEN not configured; remote operations will fail"
            )

        self.logger.info("Git service initialized (workspace=%s)", self.base_workspace)

    async def _health_check(self) -> bool:
        """Service is considered healthy when workspace is accessible."""
        if self.base_workspace is None:
            return False
        return self.base_workspace.exists() and self.base_workspace.is_dir()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_auth_repo_url(self, repo_url: str) -> str:
        """
        Inject the current GitHub token into an HTTPS repository URL.

        Args:
            repo_url: HTTPS URL of the repository.

        Returns:
            Authenticated URL.

        Raises:
            RuntimeError: If token is not configured.
            ValueError: If URL is not HTTPS.
        """
        if not self.github_token:
            raise RuntimeError("GITHUB_TOKEN not configured")
        if not repo_url.startswith("https://"):
            raise ValueError("Repository URL must start with https://")

        url_without_protocol = repo_url[8:]
        return f"https://{self.github_token}@{url_without_protocol}"

    def _validate_project_path(self, project_path: str) -> Path:
        """
        Validate that *project_path* resolves inside the workspace.

        This prevents path-traversal attacks.

        Args:
            project_path: Requested project directory.

        Returns:
            Resolved ``Path`` object.

        Raises:
            ValueError: If path escapes the workspace.
        """
        base = (self.base_workspace or Path("./workspace")).resolve()
        target = Path(project_path).resolve()

        if not str(target).startswith(str(base)):
            raise ValueError("Invalid project path (path traversal detected)")

        return target

    # ------------------------------------------------------------------
    # Local operations
    # ------------------------------------------------------------------

    def init_repo(self, project_path: str) -> Dict[str, Any]:
        """
        Initialize a new Git repository.

        Args:
            project_path: Directory to initialize.

        Returns:
            Dict with ``message`` and ``path``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            p.mkdir(parents=True, exist_ok=True)
            Repo.init(str(p))

            self._track_call(time.time() - start)
            self.logger.info("Repository initialized at %s", p)
            return {"message": "Repository initialized", "path": str(p)}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("init_repo failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def commit(
        self,
        project_path: str,
        message: str,
        files: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Create a commit.

        Args:
            project_path: Repository directory.
            message: Commit message.
            files: Specific files to stage (default: all).

        Returns:
            Dict with ``message`` and ``commit`` SHA.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))

            if files:
                repo.index.add(files)
            else:
                repo.git.add(A=True)

            commit_obj = repo.index.commit(message)

            self._track_call(time.time() - start)
            self.logger.info("Commit %s created in %s", commit_obj.hexsha[:8], p)
            return {"message": "Commit created", "commit": commit_obj.hexsha}
        except GitCommandError as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("commit failed (git): %s", exc)
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("commit failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def get_status(self, project_path: str) -> Dict[str, Any]:
        """
        Get repository status.

        Args:
            project_path: Repository directory.

        Returns:
            Dict with ``branch`` name and ``status`` (porcelain output).
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            porcelain = repo.git.status("--porcelain")
            branch = (
                repo.active_branch.name
                if not repo.head.is_detached
                else "DETACHED"
            )

            self._track_call(time.time() - start)
            return {"branch": branch, "status": porcelain}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("get_status failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def get_log(
        self, project_path: str, limit: int = 10
    ) -> Dict[str, Any]:
        """
        Get commit log.

        Args:
            project_path: Repository directory.
            limit: Maximum number of commits to return.

        Returns:
            Dict with ``commits`` list and ``count``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            commits = list(repo.iter_commits(max_count=limit))

            data = []
            for c in commits:
                data.append(
                    {
                        "hash": c.hexsha,
                        "message": c.message.strip(),
                        "author": str(c.author),
                        "date": c.committed_datetime.isoformat(),
                    }
                )

            self._track_call(time.time() - start)
            return {"commits": data, "count": len(data)}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("get_log failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def create_branch(
        self, project_path: str, branch_name: str
    ) -> Dict[str, Any]:
        """
        Create a new branch.

        Args:
            project_path: Repository directory.
            branch_name: Name of the new branch.

        Returns:
            Dict with ``message`` and ``branch``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            repo.git.branch(branch_name)

            self._track_call(time.time() - start)
            self.logger.info("Branch '%s' created in %s", branch_name, p)
            return {"message": "Branch created", "branch": branch_name}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("create_branch failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def checkout_branch(
        self, project_path: str, branch_name: str
    ) -> Dict[str, Any]:
        """
        Checkout an existing branch.

        Args:
            project_path: Repository directory.
            branch_name: Branch to checkout.

        Returns:
            Dict with ``message`` and ``branch``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            repo.git.checkout(branch_name)

            self._track_call(time.time() - start)
            self.logger.info("Checked out branch '%s' in %s", branch_name, p)
            return {"message": "Checked out branch", "branch": branch_name}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("checkout_branch failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Remote operations
    # ------------------------------------------------------------------

    def clone_repo(
        self,
        repo_url: str,
        target_path: str,
        user_github_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Clone a remote repository.

        Args:
            repo_url: HTTPS URL of the repository.
            target_path: Local directory to clone into.
            user_github_token: Optional per-call token override.

        Returns:
            Dict with ``message`` and ``path``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(target_path)

            if user_github_token:
                self.github_token = user_github_token

            auth_url = self._get_auth_repo_url(repo_url)
            Repo.clone_from(auth_url, str(p))

            self._track_call(time.time() - start)
            self.logger.info("Repository cloned to %s", p)
            return {"message": "Repository cloned successfully", "path": str(p)}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("clone_repo failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def add_remote(
        self,
        project_path: str,
        remote_name: str,
        remote_url: str,
        user_github_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add or update a remote in the repository.

        Args:
            project_path: Repository directory.
            remote_name: Name for the remote (e.g. ``origin``).
            remote_url: HTTPS URL of the remote.
            user_github_token: Optional per-call token override.

        Returns:
            Dict with ``message``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))

            if user_github_token:
                self.github_token = user_github_token

            # Remove existing remote with the same name
            if remote_name in [r.name for r in repo.remotes]:
                repo.delete_remote(remote_name)

            auth_url = self._get_auth_repo_url(remote_url)
            repo.create_remote(remote_name, auth_url)

            self._track_call(time.time() - start)
            self.logger.info("Remote '%s' added to %s", remote_name, p)
            return {"message": f"Remote '{remote_name}' added successfully."}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("add_remote failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def push(
        self,
        project_path: str,
        remote_name: str,
        branch_name: Optional[str] = None,
        user_github_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Push to a remote using subprocess with an authenticated URL.

        Args:
            project_path: Repository directory.
            remote_name: Remote name.
            branch_name: Branch to push (defaults to active branch).
            user_github_token: Optional per-call token override.

        Returns:
            Dict with ``message``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))

            if user_github_token:
                self.github_token = user_github_token

            if not branch_name:
                branch_name = repo.active_branch.name

            # Resolve authenticated URL from the remote
            remote = repo.remote(name=remote_name)
            original_url = list(remote.urls)[0]

            # Strip any existing token
            if "@" in original_url:
                original_url = "https://" + original_url.split("@")[1]

            auth_url = self._get_auth_repo_url(original_url)

            result = subprocess.run(
                ["git", "push", auth_url, f"{branch_name}:{branch_name}"],
                cwd=str(p),
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Push error: {result.stderr}")

            self._track_call(time.time() - start)
            self.logger.info(
                "Pushed %s to %s/%s", p, remote_name, branch_name
            )
            return {
                "message": f"Push to '{remote_name}/{branch_name}' completed successfully."
            }
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("push failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def pull(
        self,
        project_path: str,
        remote_name: str = "origin",
        user_github_token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Pull from a remote using subprocess with an authenticated URL.

        Args:
            project_path: Repository directory.
            remote_name: Remote name (default ``origin``).
            user_github_token: Optional per-call token override.

        Returns:
            Dict with ``message``.
        """
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))

            if user_github_token:
                self.github_token = user_github_token

            # Resolve authenticated URL from the remote
            remote = repo.remote(name=remote_name)
            original_url = list(remote.urls)[0]

            # Strip any existing token
            if "@" in original_url:
                original_url = "https://" + original_url.split("@")[1]

            auth_url = self._get_auth_repo_url(original_url)

            result = subprocess.run(
                ["git", "pull", auth_url],
                cwd=str(p),
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                raise RuntimeError(f"Pull error: {result.stderr}")

            self._track_call(time.time() - start)
            self.logger.info("Pulled from %s into %s", remote_name, p)
            return {
                "message": f"Pull from '{remote_name}' completed successfully."
            }
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("pull failed: %s", exc)
            raise RuntimeError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

_git_service: Optional[GitService] = None


def get_git_service() -> GitService:
    """Get the global GitService instance from the registry."""
    global _git_service
    if _git_service is None:
        from services.core import get_service

        _git_service = get_service("git")
    return _git_service
