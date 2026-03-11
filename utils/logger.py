"""
Structured logging configuration using loguru.

Provides:
- Console output with colours
- Daily rotated file logs (general + errors)
- JSON-formatted file logs for monitoring tools
- Sensitive data redaction (API keys, tokens)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger as _loguru_logger


# ---------------------------------------------------------------------------
# Sensitive data redaction
# ---------------------------------------------------------------------------

_SENSITIVE_PATTERNS = [
    (re.compile(r"(sk-[a-zA-Z0-9]{20,})"), "[REDACTED_API_KEY]"),
    (
        re.compile(r"(token[\"']?\s*[:=]\s*[\"']?)([^\"'\s]+)", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(Bearer\s+)([A-Za-z0-9\-._~+/]+=*)"), r"\1[REDACTED]"),
    (
        re.compile(r"(password[\"']?\s*[:=]\s*[\"']?)([^\"'\s]+)", re.IGNORECASE),
        r"\1[REDACTED]",
    ),
]


def _redact_sensitive(text: str) -> str:
    """Redact sensitive information from log messages."""
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class StructuredLogger:
    """Compatibility wrapper to support legacy logging styles with loguru."""

    def __init__(self, inner_logger):
        """Wrap a loguru logger so callers can use stdlib-style ``%s`` formatting."""
        self._inner = inner_logger

    def bind(self, **kwargs: Any) -> "StructuredLogger":
        """Return a new logger with extra context key-value pairs bound."""
        return StructuredLogger(self._inner.bind(**kwargs))

    def _log(self, level: str, message: Any, *args: Any, **kwargs: Any) -> None:
        """Format *message* with ``%`` or ``.format()``, redact secrets, and emit."""
        extra_data = kwargs.pop("extra", {}) or {}
        exc_info = kwargs.pop("exc_info", False)
        fmt_kwargs = kwargs

        text = str(message)
        if args:
            try:
                text = text % args
            except Exception:
                try:
                    text = text.format(*args)
                except Exception:
                    text = f"{text} | args={args}"

        if fmt_kwargs:
            try:
                text = text.format(**fmt_kwargs)
            except Exception:
                extra_data = dict(extra_data)
                extra_data["format_kwargs"] = fmt_kwargs

        # Redact sensitive data before logging
        text = _redact_sensitive(text)

        target = self._inner.bind(**extra_data) if extra_data else self._inner
        target.opt(depth=2, exception=exc_info).log(level, text)

    def debug(self, message: Any, *args: Any, **kwargs: Any) -> None:
        """Emit a DEBUG-level log message."""
        self._log("DEBUG", message, *args, **kwargs)

    def info(self, message: Any, *args: Any, **kwargs: Any) -> None:
        """Emit an INFO-level log message."""
        self._log("INFO", message, *args, **kwargs)

    def warning(self, message: Any, *args: Any, **kwargs: Any) -> None:
        """Emit a WARNING-level log message."""
        self._log("WARNING", message, *args, **kwargs)

    def error(self, message: Any, *args: Any, **kwargs: Any) -> None:
        """Emit an ERROR-level log message."""
        self._log("ERROR", message, *args, **kwargs)

    def critical(self, message: Any, *args: Any, **kwargs: Any) -> None:
        """Emit a CRITICAL-level log message."""
        self._log("CRITICAL", message, *args, **kwargs)

    def exception(self, message: Any, *args: Any, **kwargs: Any) -> None:
        """Emit an ERROR-level log message with traceback (``exc_info=True``)."""
        kwargs.setdefault("exc_info", True)
        self._log("ERROR", message, *args, **kwargs)


# Remove default handler
_loguru_logger.remove()

# Create logs directory
logs_dir = Path("logs")
logs_dir.mkdir(exist_ok=True)

# Console handler (colored, human-readable)
_loguru_logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True,
)

# File handler - General logs
_loguru_logger.add(
    logs_dir / "unbx_bot_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    compression=None,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="DEBUG",
    enqueue=True,
)

# File handler - Errors only
_loguru_logger.add(
    logs_dir / "errors_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="90 days",
    compression=None,
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
    level="ERROR",
    enqueue=True,
)

# File handler - JSON format (for monitoring tools)
_loguru_logger.add(
    logs_dir / "unbx_bot_json_{time:YYYY-MM-DD}.log",
    rotation="00:00",
    retention="30 days",
    compression=None,
    serialize=True,
    level="INFO",
    enqueue=True,
)


def get_logger(name: str) -> StructuredLogger:
    """
    Get a logger instance with the specified name.

    Args:
        name: Name of the logger (usually __name__)

    Returns:
        Structured logger instance.
    """
    return StructuredLogger(_loguru_logger.bind(logger_name=name))


# Export logger
logger = StructuredLogger(_loguru_logger)

__all__ = ["logger", "get_logger"]
