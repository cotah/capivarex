"""
Monitoring configuration using Sentry.
"""
from __future__ import annotations

import os
from typing import Any, Dict

import sentry_sdk
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.logging import LoggingIntegration


_SENTRY_INITIALIZED = False


def init_sentry() -> None:
    """
    Initialize Sentry monitoring.

    Environment Variables Required:
        SENTRY_DSN: Sentry Data Source Name
        ENVIRONMENT: Environment name (development, staging, production)
        RELEASE: Release version (e.g., "unbx-bot@4.29-god")
    """
    global _SENTRY_INITIALIZED
    if _SENTRY_INITIALIZED:
        return

    sentry_dsn = os.getenv("SENTRY_DSN")
    environment = os.getenv("ENVIRONMENT", "development")
    release = os.getenv("RELEASE", "unbx-bot@4.29-god")

    if not sentry_dsn:
        print("WARNING: SENTRY_DSN not configured. Monitoring disabled.")
        return
    if "your-sentry-dsn" in sentry_dsn or "project-id" in sentry_dsn:
        print("WARNING: SENTRY_DSN placeholder detected. Monitoring disabled.")
        return

    try:
        sentry_sdk.init(
            dsn=sentry_dsn,
            environment=environment,
            release=release,
            traces_sample_rate=1.0 if environment == "development" else 0.1,
            profiles_sample_rate=1.0 if environment == "development" else 0.1,
            integrations=[
                LoggingIntegration(level=None, event_level=None),
                AsyncioIntegration(),
            ],
            sample_rate=1.0,
            attach_stacktrace=True,
            send_default_pii=False,
            max_breadcrumbs=50,
            debug=environment == "development",
        )
    except Exception as exc:
        print(f"WARNING: Failed to initialize Sentry: {exc}")
        return

    _SENTRY_INITIALIZED = True
    print(f"Sentry monitoring initialized (env: {environment}, release: {release})")


def set_user_context(user_id: str, **kwargs: Any) -> None:
    """
    Set user context for error tracking.
    """
    sentry_sdk.set_user({"id": user_id, **kwargs})


def set_context(name: str, data: Dict[str, Any]) -> None:
    """
    Set custom context for error tracking.
    """
    sentry_sdk.set_context(name, data)


def add_breadcrumb(message: str, category: str = "default", level: str = "info", **data: Any) -> None:
    """
    Add breadcrumb for error context.
    """
    sentry_sdk.add_breadcrumb(message=message, category=category, level=level, data=data)


def capture_exception(exception: Exception, **kwargs: Any) -> None:
    """
    Manually capture an exception.
    """
    with sentry_sdk.push_scope() as scope:
        extras = kwargs.pop("extra", None)
        if isinstance(extras, dict):
            for key, value in extras.items():
                scope.set_extra(key, value)
        for key, value in kwargs.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_exception(exception)


def capture_message(message: str, level: str = "info", **kwargs: Any) -> None:
    """
    Capture a message.
    """
    with sentry_sdk.push_scope() as scope:
        extras = kwargs.pop("extra", None)
        if isinstance(extras, dict):
            for key, value in extras.items():
                scope.set_extra(key, value)
        for key, value in kwargs.items():
            scope.set_extra(key, value)
        sentry_sdk.capture_message(message, level=level)


__all__ = [
    "init_sentry",
    "set_user_context",
    "set_context",
    "add_breadcrumb",
    "capture_exception",
    "capture_message",
]
