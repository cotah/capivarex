"""Notification Bridge — sends alerts to admin via Telegram and Email."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from cybersecurity.config import SEVERITY_EMOJI, ALERT_SEVERITIES, TELEGRAM_ADMIN_CHAT_ID
from cybersecurity.engine.finding import SecurityFinding

logger = logging.getLogger("cybersecurity.notifications")


async def alert_finding(finding: SecurityFinding) -> bool:
    """Send a Telegram alert for a security finding."""
    if finding.severity not in ALERT_SEVERITIES:
        return False

    chat_id = TELEGRAM_ADMIN_CHAT_ID or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
    if not chat_id:
        logger.warning("TELEGRAM_ADMIN_CHAT_ID not configured — cannot send alert")
        return False

    message = _format_finding_alert(finding)

    try:
        from services import get_service
        svc = get_service("notification")
        if svc:
            await svc.send_message("telegram", chat_id, message)
            logger.info("Alert sent for finding: %s", finding.title[:60])
            return True
    except Exception:
        logger.exception("Failed to send Telegram alert")

    return False


async def send_weekly_digest(
    total_findings: int,
    critical: int,
    high: int,
    medium: int,
    low: int,
    fixed_this_week: int,
    compliance_score: float,
    top_issues: list[str],
) -> bool:
    """Send weekly security digest to admin."""
    chat_id = TELEGRAM_ADMIN_CHAT_ID or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
    if not chat_id:
        return False

    now = datetime.now(timezone.utc)
    lines = [
        f"\U0001f6e1\ufe0f *CYBERSECURITY WEEKLY DIGEST*",
        f"_{now.strftime('%d/%m/%Y')}_\n",
        f"\U0001f4ca *Compliance Score:* {compliance_score:.0f}/100\n",
        f"\U0001f50d *Findings Abertos:* {total_findings}",
        f"  \u2620\ufe0f Critical: {critical}",
        f"  \ud83d\udd34 High: {high}",
        f"  \u26a0\ufe0f Medium: {medium}",
        f"  \u2139\ufe0f Low: {low}\n",
        f"\u2705 *Corrigidos esta semana:* {fixed_this_week}\n",
    ]

    if top_issues:
        lines.append("*Top Issues:*")
        for issue in top_issues[:5]:
            lines.append(f"  \u2022 {issue}")

    message = "\n".join(lines)

    try:
        from services import get_service
        svc = get_service("notification")
        if svc:
            await svc.send_message("telegram", chat_id, message)
            return True
    except Exception:
        logger.exception("Failed to send weekly digest")

    return False


async def send_scan_error(scanner_name: str, error: str) -> None:
    """Notify admin of a scanner failure."""
    chat_id = TELEGRAM_ADMIN_CHAT_ID or os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
    if not chat_id:
        return

    message = (
        f"\u26a0\ufe0f *CyberSecurity Scanner Error*\n\n"
        f"Scanner: `{scanner_name}`\n"
        f"Error: {error[:300]}"
    )

    try:
        from services import get_service
        svc = get_service("notification")
        if svc:
            await svc.send_message("telegram", chat_id, message)
    except Exception:
        logger.debug("Failed to send scanner error notification")


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_finding_alert(finding: SecurityFinding) -> str:
    emoji = SEVERITY_EMOJI.get(finding.severity, "\u2753")
    lines = [
        f"{emoji} *CYBERSECURITY ALERT — {finding.severity.upper()}*\n",
        f"*{finding.title}*\n",
    ]

    if finding.description:
        lines.append(f"{finding.description[:300]}\n")

    if finding.file_path:
        loc = f"`{finding.file_path}"
        if finding.line_number:
            loc += f":{finding.line_number}"
        loc += "`"
        lines.append(f"\U0001f4c1 {loc}")

    if finding.owasp_category:
        lines.append(f"\U0001f3f7\ufe0f OWASP: `{finding.owasp_category}`")

    lines.append(f"\U0001f3af Confidence: {finding.confidence:.0%}")
    lines.append(f"\U0001f50d Scanner: `{finding.scanner}`")

    if finding.suggested_fix:
        lines.append(f"\n\U0001f4a1 *Suggested Fix:*\n{finding.suggested_fix[:300]}")

    return "\n".join(lines)
