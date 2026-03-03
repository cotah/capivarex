# -*- coding: utf-8 -*-
"""
Email Polling Service
=====================
Polls Gmail for new emails and generates Telegram notifications.

Integrates with the proactivity loop (no separate loop).
Uses ``email_poll_state`` table in Supabase for per-user state.

Dependencies (lazy via get_service):
- DatabaseService — poll state persistence
- GmailService — email listing
- OpenAI / Anthropic — LLM summary (optional)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

from services.core import (
    BaseService,
    ServiceUnavailableError,
    get_service,
    register_service,
)
from services.i18n import t

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

EXCLUDED_LABELS: Set[str] = {
    "SPAM",
    "TRASH",
    "CATEGORY_PROMOTIONS",
    "CATEGORY_SOCIAL",
    "CATEGORY_FORUMS",
}

ALLOWED_LABELS: Set[str] = {"INBOX"}

ALLOWED_CATEGORIES: Set[str] = {
    "CATEGORY_PRIMARY",
    "CATEGORY_UPDATES",
    "CATEGORY_PERSONAL",
}

MAX_NOTIFICATIONS_PER_CYCLE = 5
POLL_TIMEOUT_SECONDS = 10
ROLLING_IDS_WINDOW = 50


@register_service("email_polling")
class EmailPollingService(BaseService):
    """Polls Gmail for new unread emails and prepares notifications."""

    def __init__(self):
        super().__init__(name="email_polling")

    async def _initialize(self) -> None:
        db = self._get_db()
        if not db:
            logger.warning(
                "EmailPollingService: DatabaseService unavailable at init"
            )
        self.logger.info("EmailPollingService initialized")

    async def _health_check(self) -> bool:
        return self._get_db() is not None

    # ── Dependency helpers ───────────────────────────────────────────────────

    @staticmethod
    def _get_db():
        return get_service("database")

    @staticmethod
    def _get_gmail():
        return get_service("gmail")

    @staticmethod
    def _get_ai():
        return get_service("openai") or get_service("anthropic")

    # ── Pollable users ───────────────────────────────────────────────────────

    async def get_pollable_users(self) -> List[Dict[str, Any]]:
        """Return users with email polling enabled and Gmail connected."""
        db = self._get_db()
        if not db or not db.is_initialized():
            return []

        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return []

            res = (
                sb.table("email_poll_state")
                .select("user_id, check_interval_minutes, last_checked_at")
                .eq("notify_enabled", True)
                .execute()
            )
            rows = res.data or []

            # Verify Gmail is still connected for each user
            from services.auth.google_oauth_service import get_google_oauth

            oauth = get_google_oauth()
            pollable = []
            for row in rows:
                uid = row["user_id"]
                try:
                    if await oauth.is_connected(uid):
                        pollable.append(row)
                    else:
                        logger.debug(
                            "User %s has polling enabled but Gmail "
                            "not connected — skipping",
                            uid,
                        )
                except Exception:
                    logger.debug(
                        "Could not verify Gmail for user %s", uid
                    )
            return pollable

        except Exception as e:
            logger.error("get_pollable_users failed: %s", e)
            return []

    # ── Poll new emails ──────────────────────────────────────────────────────

    async def poll_new_emails(
        self, user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Fetch unread emails and return only NEW ones (not yet notified).

        Returns at most MAX_NOTIFICATIONS_PER_CYCLE emails.
        On token expiry, disables polling and returns [].
        """
        gmail = self._get_gmail()
        if not gmail:
            return []

        if not gmail.is_initialized():
            try:
                await gmail.initialize()
            except Exception:
                return []

        # Get known message IDs from DB
        known_ids = await self._get_known_ids(user_id)

        try:
            emails = await gmail.list_emails(
                user_id=user_id,
                query="is:unread newer_than:10m",
                label="INBOX",
                max_results=10,
            )
        except ServiceUnavailableError:
            await self._handle_token_expiry(user_id)
            return []
        except Exception as e:
            logger.warning(
                "poll_new_emails failed for %s: %s", user_id, e
            )
            return []

        # Filter: only NEW (not in known_ids)
        new_emails = [
            e for e in emails if e.get("id") not in known_ids
        ]

        # Apply smart label filtering
        new_emails = self.filter_by_labels(new_emails)

        # Cap at max
        return new_emails[:MAX_NOTIFICATIONS_PER_CYCLE]

    # ── Smart label filtering ────────────────────────────────────────────────

    @staticmethod
    def filter_by_labels(
        emails: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        Filter emails by label rules:
        - Must be in INBOX
        - Must NOT have SPAM/TRASH/PROMOTIONS/SOCIAL/FORUMS
        - If has a CATEGORY_ label, must be PRIMARY/UPDATES/PERSONAL
        - No category label → passes
        """
        filtered = []
        for email in emails:
            labels = set(email.get("labels", []))

            # Must be in INBOX
            if not labels & ALLOWED_LABELS:
                continue

            # Must not have excluded labels
            if labels & EXCLUDED_LABELS:
                continue

            # Check category labels
            category_labels = {
                lbl for lbl in labels if lbl.startswith("CATEGORY_")
            }
            if category_labels and not (
                category_labels & ALLOWED_CATEGORIES
            ):
                continue

            filtered.append(email)
        return filtered

    # ── Mark as notified ─────────────────────────────────────────────────────

    async def mark_as_notified(
        self, user_id: str, message_ids: List[str]
    ) -> None:
        """Merge new IDs into known set and update last_checked_at."""
        known = await self._get_known_ids(user_id)
        merged = list(known | set(message_ids))

        # Rolling window: keep only the most recent IDs
        if len(merged) > ROLLING_IDS_WINDOW:
            merged = merged[-ROLLING_IDS_WINDOW:]

        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return

            sb.table("email_poll_state").update(
                {
                    "last_message_ids": merged,
                    "last_checked_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                }
            ).eq("user_id", user_id).execute()

        except Exception as e:
            logger.error(
                "mark_as_notified failed for %s: %s", user_id, e
            )

    # ── Notification formatting ──────────────────────────────────────────────

    async def summarize_for_notification(
        self,
        emails: List[Dict[str, Any]],
        user_id: str,
        lang: str = "en",
    ) -> str:
        """
        Build notification text.

        - 0 emails → ""
        - 1 email → single notification with LLM summary
        - 2+ emails → grouped compact list
        """
        if not emails:
            return ""

        if len(emails) == 1:
            return await self._format_single(
                emails[0], user_id, lang
            )

        return self._format_multiple(emails, lang)

    async def _format_single(
        self,
        email: Dict[str, Any],
        user_id: str,
        lang: str,
    ) -> str:
        """Format single email notification with optional LLM summary."""
        sender = email.get("from_name") or email.get(
            "from_email", "Unknown"
        )
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")

        # Try LLM summary
        summary = await self._get_llm_summary(
            email, user_id, lang
        )
        if not summary:
            summary = snippet[:120] if snippet else subject

        return t(
            "email_poll_single",
            lang=lang,
            sender=sender,
            subject=subject,
            summary=summary,
        )

    @staticmethod
    def _format_multiple(
        emails: List[Dict[str, Any]], lang: str
    ) -> str:
        """Format grouped notification for multiple emails."""
        lines = []
        for email in emails:
            sender = email.get("from_name") or email.get(
                "from_email", "Unknown"
            )
            subject = email.get("subject", "")
            lines.append(f"  \u2022 {sender} \u2014 {subject}")

        email_list = "\n".join(lines)
        return t(
            "email_poll_multiple",
            lang=lang,
            count=len(emails),
            email_list=email_list,
        )

    async def _get_llm_summary(
        self,
        email: Dict[str, Any],
        user_id: str,
        lang: str,
    ) -> str:
        """Get LLM summary of an email body. Returns '' on failure."""
        ai = self._get_ai()
        if not ai:
            return ""

        gmail = self._get_gmail()
        if not gmail:
            return ""

        try:
            body = await gmail.get_email_body(
                user_id, email["id"]
            )
            if not body:
                return ""

            # Truncate body for prompt
            body_truncated = body[:2000]

            prompt = t(
                "email_poll_summary_prompt",
                lang=lang,
                sender=email.get("from_name", ""),
                subject=email.get("subject", ""),
                body=body_truncated,
            )

            if not ai.is_initialized():
                await ai.initialize()

            response = await ai.generate_text(
                prompt=prompt,
                max_tokens=100,
                temperature=0.3,
            )
            return (response or "").strip()

        except Exception as e:
            logger.debug("LLM summary failed: %s", e)
            return ""

    # ── Enable / Disable ─────────────────────────────────────────────────────

    async def enable_polling(self, user_id: str) -> bool:
        """Enable email polling for a user. Returns True on success."""
        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return False

            sb.table("email_poll_state").upsert(
                {
                    "user_id": user_id,
                    "notify_enabled": True,
                    "check_interval_minutes": 5,
                },
                on_conflict="user_id",
            ).execute()
            return True
        except Exception as e:
            logger.error(
                "enable_polling failed for %s: %s", user_id, e
            )
            return False

    async def disable_polling(self, user_id: str) -> bool:
        """Disable email polling for a user. Returns True on success."""
        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return False

            sb.table("email_poll_state").update(
                {"notify_enabled": False}
            ).eq("user_id", user_id).execute()
            return True
        except Exception as e:
            logger.error(
                "disable_polling failed for %s: %s", user_id, e
            )
            return False

    async def is_polling_enabled(self, user_id: str) -> bool:
        """Check whether polling is enabled for a user."""
        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return False

            res = (
                sb.table("email_poll_state")
                .select("notify_enabled")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if res.data:
                return bool(res.data[0].get("notify_enabled"))
            return False
        except Exception:
            return False

    async def create_poll_state(self, user_id: str) -> None:
        """
        Create default poll state for a user (called on Gmail connect).
        Uses upsert so it's safe to call multiple times.
        """
        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return

            sb.table("email_poll_state").upsert(
                {
                    "user_id": user_id,
                    "notify_enabled": True,
                    "check_interval_minutes": 5,
                    "last_message_ids": [],
                    "last_checked_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                },
                on_conflict="user_id",
            ).execute()

            logger.info(
                "Email poll state created for user %s", user_id
            )
        except Exception as e:
            logger.warning(
                "Failed to create poll state for %s: %s",
                user_id,
                e,
            )

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _get_known_ids(self, user_id: str) -> Set[str]:
        """Fetch set of already-notified message IDs from DB."""
        try:
            from services.infrastructure.database import (
                get_supabase_client,
            )

            sb = get_supabase_client()
            if not sb:
                return set()

            res = (
                sb.table("email_poll_state")
                .select("last_message_ids")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if res.data:
                ids = res.data[0].get("last_message_ids") or []
                return set(ids)
            return set()
        except Exception as e:
            logger.debug(
                "Could not fetch known IDs for %s: %s", user_id, e
            )
            return set()

    async def _handle_token_expiry(self, user_id: str) -> None:
        """Disable polling when Gmail token has expired."""
        logger.warning(
            "Gmail token expired for user %s — disabling polling",
            user_id,
        )
        await self.disable_polling(user_id)
