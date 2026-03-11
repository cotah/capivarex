"""
SecurityEventService — Structured security event logging.

Records authentication failures, rate limit violations, suspicious
requests, and other security-relevant events to the ``security_events``
Supabase table and optionally notifies admins via Telegram.

Usage::

    from services.infrastructure.security_event_service import record_security_event

    await record_security_event(
        event_type="auth_failure",
        severity="medium",
        user_id=user_id,
        ip_address=request.client.host,
        details={"reason": "invalid_password", "email": email},
    )
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional

from services.core import BaseService, register_service

logger = logging.getLogger("capivarex.security")

# Event severity levels
Severity = Literal["low", "medium", "high", "critical"]

# Event types
EventType = Literal[
    "auth_failure",
    "auth_success",
    "rate_limit_exceeded",
    "invalid_token",
    "suspicious_request",
    "code_execution",
    "admin_action",
    "quota_exceeded",
    "unauthorized_access",
    "data_export",
]

# Severities that trigger an admin Telegram alert
_ALERT_SEVERITIES = {"high", "critical"}


@register_service("security_events")
class SecurityEventService(BaseService):
    """
    Records security events to Supabase and alerts admins on high-severity events.

    Features:
    - Structured logging to ``security_events`` table
    - Telegram admin alerts for high/critical events
    - Graceful degradation: never raises, always logs
    """

    async def _initialize(self) -> None:
        """Verify database connectivity."""
        from services.core import get_service
        self._db = get_service("database")
        self._notification = get_service("notification")
        self._admin_chat_id = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")
        self.logger.info("SecurityEventService ready")

    async def _health_check(self) -> bool:
        return self._db is not None and self._db.is_initialized()

    async def record(
        self,
        event_type: EventType,
        severity: Severity,
        *,
        user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        endpoint: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """
        Record a security event.

        Args:
            event_type: Category of the security event.
            severity: Severity level (low/medium/high/critical).
            user_id: Authenticated user ID, if known.
            ip_address: Client IP address.
            endpoint: API endpoint that triggered the event.
            details: Additional structured context.
            tenant_id: Tenant ID for multi-tenant context.
        """
        # Always log to application logger
        log_fn = logger.warning if severity in ("high", "critical") else logger.info
        log_fn(
            "SECURITY_EVENT type=%s severity=%s user=%s ip=%s endpoint=%s details=%s",
            event_type,
            severity,
            (user_id or "anonymous")[:12],
            ip_address or "unknown",
            endpoint or "unknown",
            details or {},
        )

        # Persist to Supabase (non-blocking, best-effort)
        try:
            if self._db and self._db.is_initialized():
                client = self._db.get_client()
                row: Dict[str, Any] = {
                    "event_type": event_type,
                    "severity": severity,
                    "user_id": user_id,
                    "tenant_id": tenant_id,
                    "ip_address": ip_address,
                    "endpoint": endpoint,
                    "details": details or {},
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                client.table("security_events").insert(row).execute()
        except Exception as exc:
            logger.debug("SecurityEventService: DB insert failed (non-fatal): %s", exc)

        # Alert admin on high/critical events
        if severity in _ALERT_SEVERITIES and self._admin_chat_id:
            try:
                await self._send_admin_alert(event_type, severity, user_id, ip_address, details)
            except Exception as exc:
                logger.debug("SecurityEventService: admin alert failed (non-fatal): %s", exc)

    async def _send_admin_alert(
        self,
        event_type: str,
        severity: str,
        user_id: Optional[str],
        ip_address: Optional[str],
        details: Optional[Dict[str, Any]],
    ) -> None:
        """Send a Telegram alert to the admin for high-severity events."""
        emoji = "🚨" if severity == "critical" else "⚠️"
        msg_lines = [
            f"{emoji} *Security Alert* — `{severity.upper()}`",
            f"Event: `{event_type}`",
            f"User: `{(user_id or 'anonymous')[:16]}`",
            f"IP: `{ip_address or 'unknown'}`",
        ]
        if details:
            for k, v in list(details.items())[:3]:
                msg_lines.append(f"{k}: `{str(v)[:50]}`")

        message = "\n".join(msg_lines)

        if self._notification:
            await self._notification.send_message(
                channel="telegram",
                recipient=self._admin_chat_id,
                message=message,
            )


# ---------------------------------------------------------------------------
# Module-level convenience function
# ---------------------------------------------------------------------------

async def record_security_event(
    event_type: EventType,
    severity: Severity,
    *,
    user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    endpoint: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    tenant_id: Optional[str] = None,
) -> None:
    """
    Convenience wrapper: record a security event via the service registry.

    Safe to call from anywhere — silently no-ops if the service is unavailable.
    """
    try:
        from services.core import get_service
        svc = get_service("security_events")
        if svc and svc.is_initialized():
            await svc.record(
                event_type=event_type,
                severity=severity,
                user_id=user_id,
                ip_address=ip_address,
                endpoint=endpoint,
                details=details,
                tenant_id=tenant_id,
            )
        else:
            # Fallback: just log
            logger.info(
                "SECURITY_EVENT [no-svc] type=%s severity=%s user=%s ip=%s",
                event_type,
                severity,
                (user_id or "anonymous")[:12],
                ip_address or "unknown",
            )
    except Exception as exc:
        logger.debug("record_security_event failed (non-fatal): %s", exc)
