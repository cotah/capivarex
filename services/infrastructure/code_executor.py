"""
Code Executor Service - Refactored with BaseService architecture.

Executes Python code in an isolated per-user sandbox using subprocesses.

Provides:
- Per-user sandbox directories under a configurable workspace
- Subprocess execution with timeout support
- Automatic cleanup of temporary run directories
- Metrics tracking and health checks
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from services.core import (
    BaseService,
    register_service,
    ServiceConfigurationError,
)


@dataclass
class ExecutionResult:
    """Result of a code execution run."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    duration_ms: int = 0


@register_service("code_executor")
class CodeExecutorService(BaseService):
    """
    Code execution service with per-user sandboxing.

    Features:
    - Isolated sandbox directories per user
    - Subprocess execution with configurable timeout
    - Automatic temporary directory cleanup
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "code_executor",
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialise the code executor service."""
        super().__init__(name, config)
        self.base_workspace: Optional[Path] = None
        self.default_timeout: int = 10
        self.python_executable: str = "python"

    # ------------------------------------------------------------------
    # BaseService lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Set up workspace directory from config or default."""
        workspace_path = self._get_config("base_workspace", "./workspace")
        self.base_workspace = Path(workspace_path).resolve()
        self.default_timeout = self._get_config("default_timeout", 10)
        self.python_executable = self._get_config("python_executable", "python")

        # Ensure base workspace exists
        try:
            self.base_workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ServiceConfigurationError(
                f"Cannot create workspace directory {self.base_workspace}: {exc}"
            ) from exc

        self.logger.info(
            "Code executor initialized – workspace=%s, timeout=%ss",
            self.base_workspace,
            self.default_timeout,
        )

    async def _health_check(self) -> bool:
        """Verify the workspace directory is accessible."""
        if self.base_workspace is None:
            return False
        return self.base_workspace.exists() and self.base_workspace.is_dir()

    # ------------------------------------------------------------------
    # Sandbox helpers
    # ------------------------------------------------------------------

    def _get_user_sandbox_dir(self, user_id: str) -> Path:
        """
        Return (and create if needed) the sandbox directory for a user.

        Args:
            user_id: Unique user identifier.

        Returns:
            Path to ``<workspace>/<user_id>/sandbox/``.
        """
        if self.base_workspace is None:
            raise RuntimeError("Code executor service not initialized")

        sandbox_dir = self.base_workspace / str(user_id) / "sandbox"
        sandbox_dir.mkdir(parents=True, exist_ok=True)
        return sandbox_dir

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_python(
        self,
        user_id: str,
        code: str,
        timeout_seconds: Optional[int] = None,
        python_executable: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute Python code inside the user's sandbox via subprocess.

        A unique run directory is created for every invocation and is
        automatically cleaned up when execution completes.

        Args:
            user_id: Owner of the sandbox.
            code: Python source code to execute.
            timeout_seconds: Maximum execution time (defaults to
                ``self.default_timeout``).
            python_executable: Python binary to use (defaults to
                ``self.python_executable``).

        Returns:
            Dictionary with keys ``stdout``, ``stderr``, ``exit_code``,
            and ``duration_ms``.
        """
        if timeout_seconds is None:
            timeout_seconds = self.default_timeout
        if python_executable is None:
            python_executable = self.python_executable

        sandbox_dir = self._get_user_sandbox_dir(user_id)

        # Create an ephemeral run directory
        run_id = str(uuid.uuid4())
        run_dir = sandbox_dir / f"run_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)

        file_path = run_dir / "main.py"

        start_time = time.time()

        try:
            file_path.write_text(code, encoding="utf-8")

            t0 = time.time()

            # SECURITY: Sandbox env — only expose PATH and PYTHONPATH
            # Prevents user code from accessing API keys, DB credentials, etc.
            safe_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONPATH": str(run_dir),
                "HOME": str(run_dir),
                "LANG": "en_US.UTF-8",
            }

            proc = subprocess.run(
                [python_executable, file_path.name],
                cwd=str(run_dir),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=safe_env,
            )

            t1 = time.time()
            duration_ms = int((t1 - t0) * 1000)

            result = ExecutionResult(
                stdout=proc.stdout or "",
                stderr=proc.stderr or "",
                exit_code=proc.returncode,
                duration_ms=duration_ms,
            )

            latency = time.time() - start_time
            self._track_call(latency, error=(result.exit_code != 0))

            self.logger.debug(
                "Execution for user=%s exit_code=%d duration=%dms",
                user_id,
                result.exit_code,
                result.duration_ms,
            )

            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            }

        except subprocess.TimeoutExpired as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.warning(
                "Execution timed out for user=%s after %ds",
                user_id,
                timeout_seconds,
            )

            return {
                "stdout": (exc.stdout or "") if isinstance(exc.stdout, str) else "",
                "stderr": (
                    ((exc.stderr or "") if isinstance(exc.stderr, str) else "")
                    + "\n[ERROR] Execution timed out."
                ),
                "exit_code": 124,
                "duration_ms": timeout_seconds * 1000,
            }

        except Exception as exc:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.error("Execution error for user=%s: %s", user_id, exc)

            return {
                "stdout": "",
                "stderr": f"[ERROR] {str(exc)}",
                "exit_code": 1,
                "duration_ms": 0,
            }

        finally:
            # Cleanup the ephemeral run directory
            try:
                if run_dir.exists():
                    shutil.rmtree(run_dir, ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Convenience accessor
# ---------------------------------------------------------------------------

_code_executor_service: Optional[CodeExecutorService] = None


def get_code_executor_service() -> CodeExecutorService:
    """Get the global CodeExecutorService instance from the registry."""
    global _code_executor_service
    if _code_executor_service is None:
        from services.core import get_service

        _code_executor_service = get_service("code_executor")
    return _code_executor_service
