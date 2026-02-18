"""
File Manager Service - Refactored with BaseService architecture.

Workspace file management with path-traversal protection.

Provides:
- Per-user workspace / project directories
- Safe path resolution with traversal detection
- File CRUD: create, read, update, delete
- Directory listing with metadata
- File metadata (size, modified_at, is_dir)
- Raw-path convenience helpers for internal use
- Health checks and metrics tracking
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)


@register_service("file_manager")
class FileManagerService(BaseService):
    """
    Workspace file manager with path-traversal protection.

    Features:
    - Per-user project directories under a configurable base workspace
    - Path-traversal prevention via resolved-path validation
    - Create, read, update, delete files
    - List directory contents with metadata
    - Raw-path convenience helpers (read_raw, write_raw, list_raw)
    - Configurable base workspace via environment variable or config
    - Metrics tracking via BaseService
    """

    def __init__(
        self,
        name: str = "file_manager",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(name, config)
        self.base_workspace: Optional[Path] = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """
        Initialise the file manager.

        The base workspace directory is resolved from (in priority order):
        1. ``config["base_workspace"]`` passed to the constructor
        2. The ``FILE_MANAGER_WORKSPACE`` environment variable
        3. ``./workspace`` relative to the current working directory

        The directory is created if it does not exist.
        """
        workspace_path = self._get_config("base_workspace") or os.getenv(
            "FILE_MANAGER_WORKSPACE", "./workspace"
        )
        self.base_workspace = Path(workspace_path).resolve()

        try:
            self.base_workspace.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ServiceUnavailableError(
                f"Cannot create workspace directory '{self.base_workspace}': {exc}"
            )

        self.logger.info(
            f"File manager initialised (workspace={self.base_workspace})"
        )

    async def _health_check(self) -> bool:
        """Return True if the base workspace directory exists and is writable."""
        if self.base_workspace is None:
            return False
        return self.base_workspace.exists() and os.access(
            str(self.base_workspace), os.W_OK
        )

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    def _get_user_projects_dir(self, user_id: str) -> Path:
        """
        Return the projects directory for a given user, creating it if needed.

        Args:
            user_id: User identifier.

        Returns:
            Absolute ``Path`` to ``<workspace>/<user_id>/projects``.
        """
        if self.base_workspace is None:
            raise RuntimeError("File manager service not initialised")

        projects_dir = self.base_workspace / str(user_id) / "projects"
        projects_dir.mkdir(parents=True, exist_ok=True)
        return projects_dir

    def _safe_path(self, base_dir: Path, relative_path: str) -> Path:
        """
        Resolve *relative_path* under *base_dir* and ensure the result does
        not escape *base_dir* (path-traversal protection).

        Args:
            base_dir:      Trusted base directory.
            relative_path: Untrusted relative path from the user.

        Returns:
            Resolved ``Path`` guaranteed to be inside *base_dir*.

        Raises:
            ValueError: If the resolved path escapes *base_dir*.
        """
        target = (base_dir / relative_path).resolve()
        base = base_dir.resolve()

        if not str(target).startswith(str(base)):
            raise ValueError("Invalid path (path traversal detected)")

        return target

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    @staticmethod
    def _metadata(path: Path) -> Dict[str, Any]:
        """
        Build a metadata dictionary for a filesystem entry.

        Args:
            path: Absolute path to a file or directory.

        Returns:
            Dict with keys: ``path``, ``name``, ``size``, ``modified_at``,
            ``is_dir``.
        """
        stat = path.stat()
        return {
            "path": str(path),
            "name": path.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(
                stat.st_mtime, tz=timezone.utc
            ).isoformat(),
            "is_dir": path.is_dir(),
        }

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    def list_files(
        self, user_id: str, relative_dir: str = ""
    ) -> Dict[str, Any]:
        """
        List the contents of a directory inside the user's project space.

        Args:
            user_id:      User identifier.
            relative_dir: Relative path within the user's projects directory
                          (default: root of projects dir).

        Returns:
            Dict with ``directory``, ``items`` (list of metadata dicts), and
            ``count``.

        Raises:
            FileNotFoundError: If the target directory does not exist.
            ValueError:        If the target is not a directory or escapes
                               the base path.
        """
        call_start = time.time()

        base_dir = self._get_user_projects_dir(user_id)
        target_dir = self._safe_path(base_dir, relative_dir or "")

        if not target_dir.exists():
            raise FileNotFoundError("Directory not found")

        if not target_dir.is_dir():
            raise ValueError("Target is not a directory")

        items: List[Dict[str, Any]] = []
        for p in sorted(target_dir.iterdir(), key=lambda x: x.name.lower()):
            items.append(self._metadata(p))

        latency = time.time() - call_start
        self._track_call(latency, error=False)
        self.logger.info(
            f"Listed {len(items)} items in {target_dir} for user {user_id}"
        )

        return {
            "directory": str(target_dir),
            "items": items,
            "count": len(items),
        }

    # ------------------------------------------------------------------
    # File CRUD
    # ------------------------------------------------------------------

    def create_file(
        self, user_id: str, path: str, content: str = ""
    ) -> Dict[str, Any]:
        """
        Create a new file inside the user's project space.

        Parent directories are created automatically.

        Args:
            user_id: User identifier.
            path:    Relative file path.
            content: Initial file content (default empty).

        Returns:
            Dict with ``message`` and ``file`` metadata.

        Raises:
            FileExistsError: If the file already exists.
            ValueError:      If path traversal detected.
        """
        call_start = time.time()

        base_dir = self._get_user_projects_dir(user_id)
        target = self._safe_path(base_dir, path)

        target.parent.mkdir(parents=True, exist_ok=True)

        if target.exists():
            raise FileExistsError("File already exists")

        target.write_text(content, encoding="utf-8")

        latency = time.time() - call_start
        self._track_call(latency, error=False)
        self.logger.info(f"File created: {target} for user {user_id}")

        return {"message": "File created", "file": self._metadata(target)}

    def read_file(self, user_id: str, path: str) -> Dict[str, Any]:
        """
        Read a file from the user's project space.

        Args:
            user_id: User identifier.
            path:    Relative file path.

        Returns:
            Dict with ``file`` metadata and ``content`` string.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError:        If path traversal detected.
        """
        call_start = time.time()

        base_dir = self._get_user_projects_dir(user_id)
        target = self._safe_path(base_dir, path)

        if not target.exists() or not target.is_file():
            raise FileNotFoundError("File not found")

        content = target.read_text(encoding="utf-8")

        latency = time.time() - call_start
        self._track_call(latency, error=False)
        self.logger.info(f"File read: {target} for user {user_id}")

        return {"file": self._metadata(target), "content": content}

    def update_file(
        self, user_id: str, path: str, content: str
    ) -> Dict[str, Any]:
        """
        Overwrite the content of an existing file.

        Args:
            user_id: User identifier.
            path:    Relative file path.
            content: New content to write.

        Returns:
            Dict with ``message`` and ``file`` metadata.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError:        If path traversal detected.
        """
        call_start = time.time()

        base_dir = self._get_user_projects_dir(user_id)
        target = self._safe_path(base_dir, path)

        if not target.exists() or not target.is_file():
            raise FileNotFoundError("File not found")

        target.write_text(content, encoding="utf-8")

        latency = time.time() - call_start
        self._track_call(latency, error=False)
        self.logger.info(f"File updated: {target} for user {user_id}")

        return {"message": "File updated", "file": self._metadata(target)}

    def delete_file(self, user_id: str, path: str) -> Dict[str, Any]:
        """
        Delete a file from the user's project space.

        Directories cannot be deleted through this method for safety.

        Args:
            user_id: User identifier.
            path:    Relative file path.

        Returns:
            Dict with ``message`` and ``path``.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError:        If the target is a directory or escapes the
                               base directory.
        """
        call_start = time.time()

        base_dir = self._get_user_projects_dir(user_id)
        target = self._safe_path(base_dir, path)

        if not target.exists():
            raise FileNotFoundError("File not found")

        if target.is_dir():
            raise ValueError("Deleting directories is not allowed")

        target.unlink()

        latency = time.time() - call_start
        self._track_call(latency, error=False)
        self.logger.info(f"File deleted: {target} for user {user_id}")

        return {"message": "File deleted", "path": str(target)}

    # ------------------------------------------------------------------
    # Convenience / raw-path helpers (no user scoping)
    # ------------------------------------------------------------------

    def read_raw(self, absolute_path: str) -> Optional[str]:
        """
        Read a file by absolute path (no user-scoping).

        This is a convenience method for internal use where the caller
        already has a trusted, validated path.

        Args:
            absolute_path: Absolute file path.

        Returns:
            File content as a string, or None if the file cannot be read.
        """
        call_start = time.time()
        try:
            content = Path(absolute_path).read_text(encoding="utf-8")
            latency = time.time() - call_start
            self._track_call(latency, error=False)
            return content
        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(f"Failed to read file {absolute_path}: {exc}")
            return None

    def write_raw(self, absolute_path: str, content: str) -> bool:
        """
        Write to a file by absolute path (no user-scoping).

        Parent directories are created automatically.  This is a convenience
        method for internal use where the caller already has a trusted,
        validated path.

        Args:
            absolute_path: Absolute file path.
            content:       Content to write.

        Returns:
            True on success, False on failure.
        """
        call_start = time.time()
        try:
            p = Path(absolute_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            latency = time.time() - call_start
            self._track_call(latency, error=False)
            return True
        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(f"Failed to write file {absolute_path}: {exc}")
            return False

    def list_raw(self, directory: str) -> List[Dict[str, Any]]:
        """
        List directory contents by absolute path (no user-scoping).

        Args:
            directory: Absolute directory path.

        Returns:
            List of metadata dicts, or an empty list if the directory is
            missing or unreadable.
        """
        call_start = time.time()
        try:
            dir_path = Path(directory)
            if not dir_path.exists() or not dir_path.is_dir():
                return []

            items = [
                self._metadata(p)
                for p in sorted(dir_path.iterdir(), key=lambda x: x.name.lower())
            ]
            latency = time.time() - call_start
            self._track_call(latency, error=False)
            return items
        except Exception as exc:
            latency = time.time() - call_start
            self._track_call(latency, error=True)
            self.logger.error(f"Failed to list directory {directory}: {exc}")
            return []


# ------------------------------------------------------------------
# Backward-compatible singleton accessor
# ------------------------------------------------------------------
_file_manager_service: Optional[FileManagerService] = None


def get_file_manager() -> FileManagerService:
    """Get or create the global FileManagerService instance."""
    global _file_manager_service
    if _file_manager_service is None:
        from services.core import get_service

        _file_manager_service = get_service("file_manager")
    return _file_manager_service
