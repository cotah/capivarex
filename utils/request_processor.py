# utils/request_processor.py
"""
Unified Request Processor - Gateway layer for all incoming requests.

Centralizes request_id generation, rate limiting, UserContext fetching,
and TenantContext resolution for both Telegram handlers and FastAPI routes.
"""

import logging
import time
import uuid
from typing import Dict, Optional

import structlog.contextvars

from bot.core.tenancy import TenancyManager, TenantContext
from schemas.context import UserContext
from services.core import get_service

logger = logging.getLogger("capivarax.request_processor")

# In-memory per-user rate limiter (simple, effective for single worker)
_user_last_message_time: Dict[int, float] = {}
RATE_LIMIT_SECONDS = 2


class RequestProcessor:
    """
    Unified pre-processor for all incoming requests.

    Centralizes:
    - request_id generation and structlog binding
    - Per-user rate limiting
    - UserContext fetching and validation
    - TenantContext resolution (database-backed, no global state)
    """

    def __init__(self, user_identifier: int, source: str = "telegram"):
        """Initialise the request processor for a specific user and source."""
        self.user_identifier = user_identifier
        self.source = source
        self.request_id: Optional[str] = None
        self.user_context: Optional[UserContext] = None
        self.tenant_context: Optional[TenantContext] = None

    def _bind_context_vars(self) -> None:
        """Bind request_id, user_id, and tenant_id to the structlog context.

        Should be called after user_context and tenant_context are resolved
        so that all subsequent log entries include the full tracing context.
        """
        context_data: Dict[str, str] = {"request_id": self.request_id}

        if self.user_context:
            context_data["user_id"] = self.user_context.user_id
        if self.tenant_context:
            context_data["tenant_id"] = self.tenant_context.tenant_id

        structlog.contextvars.bind_contextvars(**context_data)

    def _is_rate_limited(self) -> bool:
        """Check if the user is sending messages too fast."""
        current_time = time.time()
        last_time = _user_last_message_time.get(self.user_identifier)

        if last_time and (current_time - last_time) < RATE_LIMIT_SECONDS:
            return True

        _user_last_message_time[self.user_identifier] = current_time
        return False

    async def _fetch_user_context(self) -> Optional[UserContext]:
        """Fetch and validate user context from the database."""
        db_service = get_service("database")
        if not db_service or not db_service.is_initialized():
            logger.warning("Database service not available for context fetching")
            return None

        user_data = await db_service.get_user_by_telegram_id(
            str(self.user_identifier)
        )
        if not user_data:
            logger.debug("User with identifier %s not found.", self.user_identifier)
            return None

        try:
            self.user_context = UserContext.model_validate(user_data)
            return self.user_context
        except Exception as e:
            logger.error(
                "Failed to validate user context for %s: %s",
                self.user_identifier, e,
            )
            return None

    async def _resolve_tenant(self) -> Optional[TenantContext]:
        """Resolve TenantContext via the database-backed TenancyManager."""
        db_service = get_service("database")
        if not db_service or not db_service.is_initialized():
            return None

        tenancy = TenancyManager(db_service)

        channel = self.source  # "telegram" or "api"
        identifier = str(self.user_identifier)

        self.tenant_context = await tenancy.resolve_context(channel, identifier)
        return self.tenant_context

    async def process(self) -> bool:
        """
        Execute the full pre-processing pipeline.

        Returns:
            True if the request should proceed, False if it should be blocked.
        """
        # Initial bind with request_id only (user/tenant unknown yet)
        self.request_id = str(uuid.uuid4())
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=self.request_id)

        if self._is_rate_limited():
            logger.debug("Rate limit hit for user %s", self.user_identifier)
            return False

        await self._fetch_user_context()
        await self._resolve_tenant()

        # Re-bind with full context (user_id + tenant_id now available)
        self._bind_context_vars()
        return True


# ---------------------------------------------------------------------------
# FastAPI Dependency
# ---------------------------------------------------------------------------


async def get_request_processor(
    current_user: Dict = None,
) -> RequestProcessor:
    """
    FastAPI dependency that creates and executes the RequestProcessor.

    Usage in routes:
        from api.dependencies import get_current_user
        from utils.request_processor import get_request_processor, RequestProcessor

        @router.post("/endpoint")
        async def my_endpoint(
            processor: RequestProcessor = Depends(get_request_processor),
        ):
            ...

    Note: This dependency must be combined with get_current_user
    via a route-level wrapper. See api/dependencies/__init__.py
    for the composed dependency.
    """
    from fastapi import HTTPException, status

    # Extract user_id; the int hash is used for rate limiting
    user_id = 0
    if current_user:
        user_id = hash(current_user.get("id", current_user.get("email", "")))

    processor = RequestProcessor(user_identifier=user_id, source="api")
    if not await processor.process():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
        )
    return processor
