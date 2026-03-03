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

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

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


# ── Data structures ──────────────────────────────────────────────────────────


@dataclass
class EmailAnalysis:
    """LLM analysis of whether an email needs a reply."""

    needs_reply: bool = False
    suggested_reply: str = ""
    urgency: str = "low"  # high / medium / low


@dataclass
class EmailNotification:
    """Rich notification for a single email."""

    text: str = ""
    email_id: str = ""
    thread_id: str = ""
    message_id: str = ""
    from_email: str = ""
    from_name: str = ""
    subject: str = ""
    analysis: Optional[EmailAnalysis] = None
    user_id: str = ""
    lang: str = "en"


@dataclass
class EmailNotificationBatch:
    """Container for one polling cycle's notifications."""

    notifications: List[EmailNotification] = field(
        default_factory=list
    )
    is_multiple: bool = False
    grouped_text: str = ""


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
    ) -> EmailNotificationBatch:
        """
        Build rich notification batch with LLM analysis.

        - 0 emails → empty batch
        - 1 email → single notification with LLM summary + analysis
        - 2+ emails → grouped compact list (no per-email analysis)
        """
        if not emails:
            return EmailNotificationBatch()

        if len(emails) == 1:
            notif = await self._format_single_rich(
                emails[0], user_id, lang
            )
            return EmailNotificationBatch(
                notifications=[notif]
            )

        # Multiple emails: grouped text + basic notifications
        grouped_text = self._format_multiple(emails, lang)
        notifications = []
        for email in emails:
            notifications.append(
                EmailNotification(
                    email_id=email.get("id", ""),
                    thread_id=email.get("thread_id", ""),
                    message_id=email.get("message_id", ""),
                    from_email=email.get("from_email", ""),
                    from_name=email.get("from_name")
                    or email.get("from_email", ""),
                    subject=email.get("subject", ""),
                    user_id=user_id,
                    lang=lang,
                )
            )
        return EmailNotificationBatch(
            notifications=notifications,
            is_multiple=True,
            grouped_text=grouped_text,
        )

    async def _format_single_rich(
        self,
        email: Dict[str, Any],
        user_id: str,
        lang: str,
    ) -> EmailNotification:
        """Format single email with LLM summary + reply analysis."""
        sender = email.get("from_name") or email.get(
            "from_email", "Unknown"
        )
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")

        # LLM summary
        summary = await self._get_llm_summary(
            email, user_id, lang
        )
        if not summary:
            summary = snippet[:120] if snippet else subject

        # LLM analysis (needs_reply, suggested_reply, urgency)
        analysis = await self._analyze_email(
            email, user_id, summary, lang
        )

        # Build notification text
        if analysis.needs_reply:
            text = t(
                "email_poll_single_reply",
                lang=lang,
                sender=sender,
                subject=subject,
                summary=summary,
                urgency=self._urgency_emoji(analysis.urgency),
                suggested_reply=analysis.suggested_reply,
            )
        else:
            text = t(
                "email_poll_single_noreply",
                lang=lang,
                sender=sender,
                subject=subject,
                summary=summary,
            )

        return EmailNotification(
            text=text,
            email_id=email.get("id", ""),
            thread_id=email.get("thread_id", ""),
            message_id=email.get("message_id", ""),
            from_email=email.get("from_email", ""),
            from_name=sender,
            subject=subject,
            analysis=analysis,
            user_id=user_id,
            lang=lang,
        )

    async def _format_single(
        self,
        email: Dict[str, Any],
        user_id: str,
        lang: str,
    ) -> str:
        """Format single email notification with optional LLM summary.

        Kept for backward compatibility — prefer _format_single_rich.
        """
        sender = email.get("from_name") or email.get(
            "from_email", "Unknown"
        )
        subject = email.get("subject", "")
        snippet = email.get("snippet", "")

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

    # ── LLM helpers ───────────────────────────────────────────────────────────

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

    async def _analyze_email(
        self,
        email: Dict[str, Any],
        user_id: str,
        summary: str,
        lang: str,
    ) -> EmailAnalysis:
        """Ask LLM to classify email and suggest a reply.

        Returns EmailAnalysis with safe defaults on failure.
        """
        ai = self._get_ai()
        if not ai:
            return EmailAnalysis()

        try:
            prompt = t(
                "email_poll_analysis_prompt",
                lang=lang,
                sender=email.get("from_name", ""),
                subject=email.get("subject", ""),
                summary=summary,
            )

            if not ai.is_initialized():
                await ai.initialize()

            response = await ai.generate_text(
                prompt=prompt,
                max_tokens=200,
                temperature=0.2,
            )
            return self._parse_analysis(response or "")

        except Exception as e:
            logger.debug("Email analysis failed: %s", e)
            return EmailAnalysis()

    @staticmethod
    def _parse_analysis(response: str) -> EmailAnalysis:
        """Parse LLM JSON response into EmailAnalysis."""
        try:
            clean = response.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[-1].rsplit(
                    "```", 1
                )[0]
            data = json.loads(clean)
            return EmailAnalysis(
                needs_reply=bool(data.get("needs_reply", False)),
                suggested_reply=str(
                    data.get("suggested_reply", "")
                ),
                urgency=str(
                    data.get("urgency", "low")
                ).lower(),
            )
        except (json.JSONDecodeError, AttributeError, KeyError):
            return EmailAnalysis()

    @staticmethod
    def _urgency_emoji(urgency: str) -> str:
        """Return colored circle emoji for urgency level."""
        return {
            "high": "\U0001f534",
            "medium": "\U0001f7e1",
            "low": "\U0001f7e2",
        }.get(urgency, "\U0001f7e2")

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
