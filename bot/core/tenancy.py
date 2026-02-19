"""
Multi-tenancy system for CapivaraX Bot.

Handles:
- Tenant context management via Supabase identity_map table
- Identity mapping (telegram, webapp, cli)
- Context resolution without global state
"""

import logging
from typing import Any, Dict, Optional
from dataclasses import dataclass

logger = logging.getLogger("capivarax.tenancy")


@dataclass
class TenantContext:
    """Represents a tenant/user context."""
    tenant_id: str
    user_id: str
    channel: str  # "cli", "telegram", "webapp"
    session_id: Optional[str] = None
    chat_id: Optional[str] = None


class TenancyManager:
    """
    Manages multi-tenancy and identity mapping.

    Uses the Supabase `identity_map` table instead of a local JSON file.
    No global mutable state — every method receives or returns context
    explicitly.
    """

    def __init__(self, db_service: Any):
        """
        Args:
            db_service: An initialized DatabaseService instance
                        (must expose `.client` with Supabase operations).
        """
        self.db = db_service

    # ------------------------------------------------------------------
    # Context resolution
    # ------------------------------------------------------------------

    async def resolve_context(
        self, channel: str, channel_identifier: str
    ) -> Optional[TenantContext]:
        """
        Resolve a TenantContext from the identity_map table.

        Args:
            channel: Communication channel ('telegram', 'webapp', etc.)
            channel_identifier: Channel-specific ID (chat_id, session_id, email, …)

        Returns:
            TenantContext if a mapping exists, None otherwise.
        """
        try:
            response = (
                self.db.client.table("identity_map")
                .select("user_id")
                .eq("channel", channel)
                .eq("channel_identifier", channel_identifier)
                .execute()
            )

            if response.data:
                mapping = response.data[0]
                return TenantContext(
                    tenant_id=str(mapping["user_id"]),
                    user_id=str(mapping["user_id"]),
                    channel=channel,
                    chat_id=channel_identifier if channel == "telegram" else None,
                    session_id=channel_identifier if channel == "webapp" else None,
                )

            return None

        except Exception as e:
            logger.error("Failed to resolve context for %s/%s: %s", channel, channel_identifier, e)
            return None

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    async def get_context_for_telegram(self, chat_id: str) -> Optional[TenantContext]:
        """Get context for a Telegram chat_id."""
        return await self.resolve_context("telegram", chat_id)

    async def get_context_for_webapp(
        self,
        session_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> Optional[TenantContext]:
        """Get context for a webapp user (try session_id first, then email)."""
        if session_id:
            ctx = await self.resolve_context("webapp", session_id)
            if ctx:
                return ctx

        if email:
            return await self.resolve_context("webapp", email)

        return None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    async def register_telegram_user(
        self, chat_id: str, user_id: str
    ) -> bool:
        """
        Register (or update) a Telegram identity mapping.

        Args:
            chat_id: Telegram chat ID.
            user_id: Internal user UUID.

        Returns:
            True on success.
        """
        return await self._upsert_identity("telegram", chat_id, user_id)

    async def register_webapp_user(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        email: Optional[str] = None,
    ) -> bool:
        """
        Register (or update) a webapp identity mapping.

        Args:
            user_id: Internal user UUID.
            session_id: Optional webapp session ID.
            email: Optional user email.

        Returns:
            True if at least one mapping was created.
        """
        success = False
        if session_id:
            success = await self._upsert_identity("webapp", session_id, user_id) or success
        if email:
            success = await self._upsert_identity("webapp", email, user_id) or success
        return success

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _upsert_identity(
        self, channel: str, channel_identifier: str, user_id: str
    ) -> bool:
        """Insert or update an identity_map row."""
        try:
            self.db.client.table("identity_map").upsert(
                {
                    "channel": channel,
                    "channel_identifier": channel_identifier,
                    "user_id": user_id,
                },
                on_conflict="channel,channel_identifier",
            ).execute()
            return True
        except Exception as e:
            logger.error(
                "Failed to upsert identity for %s/%s: %s",
                channel, channel_identifier, e,
            )
            return False
