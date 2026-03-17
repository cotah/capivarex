"""Autofix Bridge — creates autofix tickets and patches from security findings."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from cybersecurity.engine.finding import SecurityFinding

logger = logging.getLogger("cybersecurity.autofix_bridge")

# Add backend to path for autofix imports
_BACKEND_PATH = str(Path(__file__).resolve().parent.parent.parent / "capivarex-backend")
if _BACKEND_PATH not in sys.path:
    sys.path.insert(0, _BACKEND_PATH)


async def create_ticket_from_finding(finding: SecurityFinding) -> dict | None:
    """Create an autofix ticket from a security finding.

    Returns the ticket dict if created, None on failure.
    """
    try:
        from autofix.core import record_exception, build_suggestion

        # Create a synthetic exception for the autofix system
        error_msg = f"[CyberSec] {finding.title}"
        if finding.file_path:
            error_msg += f" in {finding.file_path}"
            if finding.line_number:
                error_msg += f":{finding.line_number}"

        ticket, is_new = record_exception(
            error=RuntimeError(error_msg),
            chat_id="cybersecurity",
            text=finding.description or finding.title,
            user_id="cybersecurity_bot",
            tenant_id="system",
        )

        if ticket and is_new:
            logger.info(
                "Autofix ticket created: %s for finding: %s",
                ticket.get("id", "?"), finding.title[:60],
            )

            # Build a suggestion
            try:
                build_suggestion(ticket)
            except Exception:
                logger.debug("Failed to build suggestion for ticket")

        return ticket
    except ImportError:
        logger.debug("Autofix module not available — skipping ticket creation")
        return None
    except Exception:
        logger.exception("Failed to create autofix ticket")
        return None


async def notify_patch_ready(ticket: dict) -> None:
    """Notify admin that a patch is ready for approval."""
    try:
        from autofix.notifier import notify_patch_ready as _notify
        await _notify(ticket)
    except ImportError:
        logger.debug("Autofix notifier not available")
    except Exception:
        logger.exception("Failed to notify patch ready")
