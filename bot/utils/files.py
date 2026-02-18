"""
File operation utilities for CapivaraX Bot.

Provides:
- Safe file reading/writing
- Path validation
- File listing
- Backup operations
"""

import os
import shutil
import logging
from pathlib import Path
from typing import List, Optional
from datetime import datetime

logger = logging.getLogger("unbx_bot.utils.files")

DEFAULT_ENCODING = "utf-8"

# Security constants
DEV_FORBIDDEN_PREFIXES = (".git/", "venv/", "__pycache__/")
DEV_FORBIDDEN_FILES = (".env",)
DEV_MAX_FILE_CHARS = 400_000


def is_forbidden_path(path_str: str) -> Optional[str]:
    """
    Check if path is forbidden.

    Args:
        path_str: Path string to check

    Returns:
        Reason string if forbidden, None otherwise
    """
    # Check forbidden prefixes
    for prefix in DEV_FORBIDDEN_PREFIXES:
        if prefix in path_str:
            return f"área proibida: {prefix}"

    # Check forbidden files
    path = Path(path_str)
    if path.name in DEV_FORBIDDEN_FILES:
        return f"arquivo proibido: {path.name}"

    return None


def safe_path(path_str: str, base_dir: Path) -> Path:
    """
    Resolve path safely within base directory.

    Args:
        path_str: Path string to resolve
        base_dir: Base directory to resolve against

    Returns:
        Resolved Path object

    Raises:
        ValueError: If path is outside base directory
    """
    # Normalize path
    path_norm = path_str.replace("\\", "/").lstrip("/")

    # Resolve against base
    resolved = (base_dir / path_norm).resolve()

    # Check if within base
    try:
        resolved.relative_to(base_dir.resolve())
    except ValueError:
        raise ValueError(f"Path outside project: {path_str}")

    return resolved


def read_text_safe(path: Path) -> str:
    """
    Safely read text file.

    Args:
        path: Path to file

    Returns:
        File content or empty string
    """
    if not path.exists():
        return ""

    try:
        return path.read_text(encoding=DEFAULT_ENCODING)
    except Exception as e:
        logger.error(f"Failed to read file {path}: {e}")
        return ""


def write_text_safe(path: Path, content: str):
    """
    Safely write text file.

    Args:
        path: Path to file
        content: Content to write
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=DEFAULT_ENCODING)
    except Exception as e:
        logger.error(f"Failed to write file {path}: {e}")
        raise


def backup_file(path: Path, backup_dir: Path):
    """
    Create backup of file.

    Args:
        path: Path to file to backup
        backup_dir: Directory to store backups
    """
    if not path.exists():
        return

    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"{path.name}.{timestamp}.bak"
        backup_path = backup_dir / backup_name

        shutil.copy2(path, backup_path)
        logger.info(f"Backup created: {backup_path}")
    except Exception as e:
        logger.error(f"Failed to backup file {path}: {e}")


def list_workspace_files(workspace: Path, limit: int = 50) -> List[str]:
    """
    List files in workspace.

    Args:
        workspace: Workspace directory
        limit: Maximum number of files to list

    Returns:
        List of file paths (relative to workspace)
    """
    if not workspace.exists():
        return []

    files = []
    try:
        for root, dirs, filenames in os.walk(workspace):
            # Skip hidden and forbidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ['venv', '__pycache__']]

            for filename in filenames:
                if filename.startswith('.'):
                    continue

                full_path = Path(root) / filename
                try:
                    rel_path = full_path.relative_to(workspace)
                    files.append(str(rel_path))
                except ValueError:
                    continue

                if len(files) >= limit:
                    return files

    except Exception as e:
        logger.error(f"Failed to list workspace files: {e}")

    return files


def get_file_size(path: Path) -> int:
    """
    Get file size in bytes.

    Args:
        path: Path to file

    Returns:
        File size in bytes, or 0 if file doesn't exist
    """
    if not path.exists():
        return 0

    try:
        return path.stat().st_size
    except Exception as e:
        logger.error(f"Failed to get file size for {path}: {e}")
        return 0


def ensure_directory(path: Path):
    """
    Ensure directory exists.

    Args:
        path: Path to directory
    """
    try:
        path.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error(f"Failed to create directory {path}: {e}")
        raise


def delete_file(path: Path):
    """
    Delete file safely.

    Args:
        path: Path to file
    """
    if not path.exists():
        return

    try:
        path.unlink()
        logger.info(f"File deleted: {path}")
    except Exception as e:
        logger.error(f"Failed to delete file {path}: {e}")
        raise


def move_file(src: Path, dst: Path):
    """
    Move file safely.

    Args:
        src: Source path
        dst: Destination path
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        logger.info(f"File moved: {src} -> {dst}")
    except Exception as e:
        logger.error(f"Failed to move file {src} to {dst}: {e}")
        raise


def copy_file(src: Path, dst: Path):
    """
    Copy file safely.

    Args:
        src: Source path
        dst: Destination path
    """
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        logger.info(f"File copied: {src} -> {dst}")
    except Exception as e:
        logger.error(f"Failed to copy file {src} to {dst}: {e}")
        raise
