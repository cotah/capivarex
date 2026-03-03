# -*- coding: utf-8 -*-
"""
Sentry Integration
==================
Initialises the Sentry SDK for error tracking and performance
monitoring.  Call :func:`init_sentry` once at process startup
(before the FastAPI app or Telegram bot is created).

If ``SENTRY_DSN`` is empty or unset the function returns silently,
so local development works without a Sentry account.
"""

import os

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from utils.logger import get_logger

logger = get_logger(__name__)

# HTTP paths whose errors we don't want in Sentry
_IGNORED_PATHS = frozenset({"/health", "/healthz", "/ready"})

# Exception types that are "expected" and shouldn't create alerts
_IGNORED_EXCEPTIONS = (
    KeyboardInterrupt,
    SystemExit,
)


def _before_send(event, hint):
    """Filter noisy events before they reach Sentry."""
    # Drop health-check errors
    request = event.get("request", {})
    url = request.get("url", "")
    if any(url.endswith(p) for p in _IGNORED_PATHS):
        return None

    # Drop expected / control-flow exceptions
    exc_info = hint.get("exc_info")
    if exc_info:
        exc_type = exc_info[0]
        if exc_type and issubclass(exc_type, _IGNORED_EXCEPTIONS):
            return None

    return event


def init_sentry() -> None:
    """Initialise Sentry SDK from environment variables.

    Reads:
    - ``SENTRY_DSN`` — project DSN (skip silently if empty)
    - ``SENTRY_ENVIRONMENT`` / ``ENVIRONMENT`` — e.g. production
    - ``SENTRY_TRACES_SAMPLE_RATE`` — 0.0-1.0 (default 0.3)
    - ``RELEASE`` — application version tag
    """
    dsn = os.getenv("SENTRY_DSN", "")
    if not dsn:
        logger.debug("SENTRY_DSN not set — Sentry disabled")
        return

    environment = os.getenv(
        "SENTRY_ENVIRONMENT",
        os.getenv("ENVIRONMENT", "development"),
    )

    try:
        traces_rate = float(
            os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.3")
        )
    except (ValueError, TypeError):
        traces_rate = 0.3

    release = os.getenv("RELEASE")

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        traces_sample_rate=traces_rate,
        send_default_pii=True,
        integrations=[FastApiIntegration()],
        release=release,
        before_send=_before_send,
    )

    logger.info(
        "Sentry initialised: env=%s, traces=%.0f%%, release=%s",
        environment,
        traces_rate * 100,
        release or "unset",
    )
