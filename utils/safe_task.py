"""
Safe asyncio task utility.

Wraps asyncio.create_task with proper exception handling to prevent
silent failures in fire-and-forget background tasks.
"""

import asyncio
import logging
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


def safe_create_task(coro: Coroutine[Any, Any, Any], name: str = "") -> asyncio.Task:
    """
    Create an asyncio task with automatic exception logging.

    Unlike bare asyncio.create_task(), this ensures exceptions in
    fire-and-forget tasks are logged instead of silently swallowed.

    Args:
        coro: The coroutine to run
        name: Optional name for logging (e.g. "save_memory")

    Returns:
        The asyncio.Task object
    """
    task = asyncio.create_task(coro)

    def _handle_exception(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc:
            task_name = name or t.get_name()
            logger.error(
                "Background task '%s' failed: %s: %s",
                task_name, type(exc).__name__, exc,
            )

    task.add_done_callback(_handle_exception)
    return task
