"""
Safety utilities for CapivaraX Bot.

Provides:
- User confirmation prompts
- Safe file operations
- Input validation
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("unbx_bot.utils.safety")

DEFAULT_ENCODING = "utf-8"


def confirm_action(message: str) -> bool:
    """
    Ask user for confirmation (s/n).

    Args:
        message: Confirmation message to display

    Returns:
        True if user confirms (s), False otherwise (n)
    """
    while True:
        resp = input(f"{message} (s/n): ").strip().lower()
        if resp == "s":
            return True
        if resp == "n":
            return False
        logger.warning("Invalid confirmation response '%s', expected 's' or 'n'", resp)


def safe_read_json(path: Path, default: Any) -> Any:
    """
    Safely read JSON file with fallback to default.

    Args:
        path: Path to JSON file
        default: Default value if file doesn't exist or is invalid

    Returns:
        Parsed JSON data or default value
    """
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, indent=2), encoding=DEFAULT_ENCODING)
        return default

    try:
        return json.loads(path.read_text(encoding=DEFAULT_ENCODING))
    except Exception as e:
        logger.error(f"Failed to read JSON from {path}: {e}")
        return default


def safe_write_json(path: Path, data: Any):
    """
    Safely write JSON file.

    Args:
        path: Path to JSON file
        data: Data to write
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding=DEFAULT_ENCODING
        )
    except Exception as e:
        logger.error(f"Failed to write JSON to {path}: {e}")


def safe_read_text(path: Path, default: str = "") -> str:
    """
    Safely read text file with fallback to default.

    Args:
        path: Path to text file
        default: Default value if file doesn't exist

    Returns:
        File content or default value
    """
    if not path.exists():
        return default

    try:
        return path.read_text(encoding=DEFAULT_ENCODING)
    except Exception as e:
        logger.error(f"Failed to read text from {path}: {e}")
        return default


def safe_write_text(path: Path, content: str):
    """
    Safely write text file.

    Args:
        path: Path to text file
        content: Content to write
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding=DEFAULT_ENCODING)
    except Exception as e:
        logger.error(f"Failed to write text to {path}: {e}")


def validate_path_safety(path: Path, workspace: Path) -> bool:
    """
    Validate that path is safe (within workspace, not forbidden).

    Args:
        path: Path to validate
        workspace: Workspace root directory

    Returns:
        True if path is safe, False otherwise
    """
    # Forbidden prefixes
    forbidden_prefixes = (".git/", "venv/", "__pycache__/")
    forbidden_files = (".env",)

    path_str = str(path)

    # Check forbidden prefixes
    for prefix in forbidden_prefixes:
        if prefix in path_str:
            logger.warning(f"Path contains forbidden prefix: {prefix}")
            return False

    # Check forbidden files
    if path.name in forbidden_files:
        logger.warning(f"Path is forbidden file: {path.name}")
        return False

    # Check if within workspace (optional, can be removed if too restrictive)
    try:
        path.resolve().relative_to(workspace.resolve())
    except ValueError:
        logger.warning(f"Path is outside workspace: {path}")
        return False

    return True


def sanitize_input(text: str, max_length: int = 10000) -> str:
    """
    Sanitize user input.

    Args:
        text: Input text to sanitize
        max_length: Maximum allowed length

    Returns:
        Sanitized text
    """
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length]

    # Remove null bytes
    text = text.replace('\x00', '')

    return text.strip()
