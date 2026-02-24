"""
Git Service - Refactored with BaseService architecture.

Git operations via GitPython with authenticated remote support.

FIX [2025-02]: O Railway não tem `./workspace` no filesystem.
  ANTES: `workspace = self._get_config("base_workspace", "./workspace")`
         `_health_check()` retornava False porque a pasta não existia → git falha
  DEPOIS: Cria a pasta na inicialização se não existir.
          Usa `/tmp/workspace` como fallback seguro (Railway tem /tmp).
"""

from __future__ import annotations

import os
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

    async def _initialize(self) -> None:
        """Load GitHub token and ensure workspace directory exists."""
        self.github_token = self._get_config(
            "github_token",
            os.environ.get("GITHUB_TOKEN"),
        )

        # FIX: Railway não tem ./workspace. Usamos /tmp/workspace como fallback seguro.
        # /tmp existe sempre em containers Railway e tem permissão de escrita.
        env_workspace = os.environ.get("GITHUB_WORKSPACE_PATH")
        config_workspace = self._get_config("base_workspace", None)

        if env_workspace:
            workspace_str = env_workspace
        elif config_workspace:
            workspace_str = config_workspace
        else:
            # FIX: default seguro para Railway: /tmp/workspace
            workspace_str = "/tmp/workspace"

        self.base_workspace = Path(workspace_str).resolve()

        # FIX: Cria a pasta se não existir (antes assumia que existia)
        try:
            self.base_workspace.mkdir(parents=True, exist_ok=True)
            self.logger.info("Git workspace ready: %s", self.base_workspace)
        except OSError as e:
            # Fallback final: /tmp/capivarex_workspace
            self.logger.warning(
                "Failed to create workspace at %s (%s), falling back to /tmp/capivarex_workspace",
                self.base_workspace,
                e,
            )
            self.base_workspace = Path("/tmp/capivarex_workspace")
            self.base_workspace.mkdir(parents=True, exist_ok=True)

        if not self.github_token:
            self.logger.warning(
                "GITHUB_TOKEN not configured; remote operations will fail"
            )

        self.logger.info("Git service initialized (workspace=%s)", self.base_workspace)

    async def _health_check(self) -> bool:
        """Service is healthy when workspace exists and is accessible."""
        if self.base_workspace is None:
            return False
        # FIX: Cria o workspace se não existir antes de verificar (Railway restart)
        try:
            self.base_workspace.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return self.base_workspace.exists() and self.base_workspace.is_dir()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_auth_repo_url(self, repo_url: str) -> str:
        if not self.github_token:
            raise RuntimeError("GITHUB_TOKEN not configured")
        if not repo_url.startswith("https://"):
            raise ValueError("Repository URL must start with https://")
        url_without_protocol = repo_url[8:]
        return f"https://{self.github_token}@{url_without_protocol}"

    def _validate_project_path(self, project_path: str) -> Path:
        """Validate that project_path resolves inside the workspace."""
        base = (self.base_workspace or Path("/tmp/workspace")).resolve()
        target = Path(project_path).resolve()

        # FIX: Se o path não começa com /tmp ou com base, rejeita (path traversal)
        if not str(target).startswith(str(base)):
            # Tenta resolver como subpath relativo ao workspace
            candidate = (base / project_path).resolve()
            if str(candidate).startswith(str(base)):
                return candidate
            raise ValueError(
                f"Invalid project path '{project_path}' (path traversal detected). "
                f"Workspace: {base}"
            )

        return target

    def _get_or_create_path(self, project_path: str) -> Path:
        """Resolve e cria o path se necessário."""
        p = self._validate_project_path(project_path)
        p.mkdir(parents=True, exist_ok=True)
        return p

    # ------------------------------------------------------------------
    # Local operations
    # ------------------------------------------------------------------

    def init_repo(self, project_path: str) -> Dict[str, Any]:
        start = time.time()
        try:
            p = self._get_or_create_path(project_path)
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
            self.logger.error("commit failed: %s", exc)
            raise RuntimeError(str(exc)) from exc
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    def status(self, project_path: str) -> Dict[str, Any]:
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            self._track_call(time.time() - start)
            return {
                "branch": repo.active_branch.name,
                "is_dirty": repo.is_dirty(),
                "untracked": repo.untracked_files,
                "modified": [item.a_path for item in repo.index.diff(None)],
                "staged": [item.a_path for item in repo.index.diff("HEAD")]
                if repo.head.is_valid()
                else [],
            }
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            self.logger.error("status failed: %s", exc)
            raise RuntimeError(str(exc)) from exc

    def log(self, project_path: str, max_count: int = 10) -> List[Dict[str, Any]]:
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            commits = []
            for c in repo.iter_commits(max_count=max_count):
                commits.append(
                    {
                        "sha": c.hexsha[:8],
                        "message": c.message.strip(),
                        "author": str(c.author),
                        "date": c.committed_datetime.isoformat(),
                    }
                )
            self._track_call(time.time() - start)
            return commits
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    def create_branch(self, project_path: str, branch_name: str) -> Dict[str, Any]:
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            repo.git.checkout("-b", branch_name)
            self._track_call(time.time() - start)
            return {
                "message": f"Branch '{branch_name}' created and checked out",
                "branch": branch_name,
            }
        except GitCommandError as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    def checkout(self, project_path: str, branch_name: str) -> Dict[str, Any]:
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            repo.git.checkout(branch_name)
            self._track_call(time.time() - start)
            return {
                "message": f"Checked out branch '{branch_name}'",
                "branch": branch_name,
            }
        except GitCommandError as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Remote operations
    # ------------------------------------------------------------------

    def clone(self, repo_url: str, project_path: str) -> Dict[str, Any]:
        start = time.time()
        try:
            auth_url = self._get_auth_repo_url(repo_url)
            p = self._get_or_create_path(project_path)
            Repo.clone_from(auth_url, str(p))
            self._track_call(time.time() - start)
            self.logger.info("Cloned %s to %s", repo_url, p)
            return {"message": "Repository cloned", "path": str(p)}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    def add_remote(
        self, project_path: str, remote_name: str, repo_url: str
    ) -> Dict[str, Any]:
        start = time.time()
        try:
            auth_url = self._get_auth_repo_url(repo_url)
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            repo.create_remote(remote_name, auth_url)
            self._track_call(time.time() - start)
            return {"message": f"Remote '{remote_name}' added"}
        except Exception as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    def push(
        self, project_path: str, remote: str = "origin", branch: str = "main"
    ) -> Dict[str, Any]:
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            origin = repo.remote(remote)
            origin.push(branch)
            self._track_call(time.time() - start)
            return {"message": f"Pushed to {remote}/{branch}"}
        except GitCommandError as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc

    def pull(
        self, project_path: str, remote: str = "origin", branch: str = "main"
    ) -> Dict[str, Any]:
        start = time.time()
        try:
            p = self._validate_project_path(project_path)
            repo = Repo(str(p))
            origin = repo.remote(remote)
            origin.pull(branch)
            self._track_call(time.time() - start)
            return {"message": f"Pulled from {remote}/{branch}"}
        except GitCommandError as exc:
            self._track_call(time.time() - start, error=True)
            raise RuntimeError(str(exc)) from exc
