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
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

import sentry_sdk

from services.core import (
    BaseService,
    ServiceUnavailableError,
    get_service,
    register_service,
)
from services.i18n import t
from utils.logger import get_logger

logger = get_logger(__name__)

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
    event_request: bool = False
    proposed_datetime: Optional[str] = None  # ISO 8601
    proposed_location: str = ""


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

    @staticmethod
    async def _call_llm(
        ai,
        prompt: str,
        max_tokens: int = 200,
        temperature: float = 0.3,
    ) -> str:
        """Call the correct text-generation method on the AI service.

        OpenAIService exposes ``chat_completion(messages=...)``;
        AnthropicService exposes ``generate_code(prompt=...)``.
        """
        if hasattr(ai, "chat_completion"):
            return await ai.chat_completion(
                messages=[
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        if hasattr(ai, "generate_code"):
            return await ai.generate_code(
                prompt=prompt,
                max_tokens=max_tokens,
            )
        raise AttributeError(
            f"{type(ai).__name__} has no compatible "
            "text generation method"
        )

    @staticmethod
    def _get_calendar():
        return get_service("calendar")

    # ── Calendar conflict check ───────────────────────────────────────────

    async def _check_calendar_conflicts(
        self,
        user_id: str,
        proposed_dt: str,
    ) -> Optional[Dict[str, Any]]:
        """Check if a proposed meeting time conflicts with calendar events.

        Returns dict with conflict info, or None if calendar is unavailable.
        """
        cal = self._get_calendar()
        if not cal:
            return None

        # Parse proposed datetime
        try:
            proposed = datetime.fromisoformat(proposed_dt)
        except (ValueError, TypeError):
            logger.debug(
                "Invalid proposed_datetime: %r", proposed_dt
            )
            return None

        # Make timezone-aware if naive
        if proposed.tzinfo is None:
            proposed = proposed.replace(tzinfo=timezone.utc)

        proposed_end = proposed + timedelta(hours=1)

        # Fetch upcoming events
        try:
            events = await cal.async_get_upcoming_events(
                user_id=user_id, max_results=20, days_ahead=2
            )
        except ServiceUnavailableError:
            logger.debug(
                "Calendar not connected for user %s", user_id
            )
            return None
        except Exception as e:
            logger.warning(
                "Calendar fetch failed for %s: %s", user_id, e
            )
            return None

        # Check for overlap
        conflict_event = None
        conflict_time = ""
        for ev in events:
            ev_start_raw = ev.get("start", "")
            ev_end_raw = ev.get("end", "")
            try:
                ev_start = datetime.fromisoformat(
                    str(ev_start_raw).replace("Z", "+00:00")
                )
                ev_end = datetime.fromisoformat(
                    str(ev_end_raw).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue

            # Overlap: proposed < ev_end AND proposed_end > ev_start
            if proposed < ev_end and proposed_end > ev_start:
                conflict_event = ev.get("summary", "Event")
                s = ev_start.strftime("%H:%M")
                e = ev_end.strftime("%H:%M")
                conflict_time = f"{s}-{e}"
                break

        # Find free 30-min slots (09:00-18:00 on the proposed day)
        proposed_day = proposed.replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        free_slots = []
        for h in range(9, 18):
            for m in (0, 30):
                slot_start = proposed_day.replace(
                    hour=h, minute=m, tzinfo=proposed.tzinfo
                )
                slot_end = slot_start + timedelta(minutes=30)
                # Skip past slots
                if slot_end <= datetime.now(timezone.utc):
                    continue
                is_free = True
                for ev in events:
                    try:
                        es = datetime.fromisoformat(
                            str(ev.get("start", "")).replace(
                                "Z", "+00:00"
                            )
                        )
                        ee = datetime.fromisoformat(
                            str(ev.get("end", "")).replace(
                                "Z", "+00:00"
                            )
                        )
                        if slot_start < ee and slot_end > es:
                            is_free = False
                            break
                    except (ValueError, TypeError):
                        continue
                if is_free:
                    free_slots.append(slot_start.strftime("%H:%M"))
                    if len(free_slots) >= 5:
                        break
            if len(free_slots) >= 5:
                break

        has_conflict = conflict_event is not None
        next_free = free_slots[0] if free_slots else None

        return {
            "has_conflict": has_conflict,
            "conflicting_event": conflict_event or "",
            "conflict_time": conflict_time,
            "next_free_slot": next_free,
            "free_slots_today": free_slots,
        }

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
            sentry_sdk.capture_exception(e)
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
        logger.info(
            "summarize_for_notification: %d emails, "
            "user=%s, lang=%s",
            len(emails),
            user_id,
            lang,
        )

        if not emails:
            return EmailNotificationBatch()

        logger.info(
            "Notification path: %s",
            "single" if len(emails) == 1 else "multiple",
        )

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
        logger.info(
            "_format_single_rich called for: %s (id=%s)",
            email.get("subject", "?"),
            email.get("id", "?"),
        )
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

        # Calendar conflict check for event requests
        cal_text = ""
        if (
            analysis.event_request
            and analysis.proposed_datetime
        ):
            cal_info = await self._check_calendar_conflicts(
                user_id, analysis.proposed_datetime
            )
            if cal_info is not None:
                if cal_info["has_conflict"]:
                    free = ", ".join(
                        cal_info.get("free_slots_today", [])
                    ) or "—"
                    cal_text = t(
                        "email_cal_conflict",
                        lang=lang,
                        event=cal_info["conflicting_event"],
                        time=cal_info["conflict_time"],
                        free_slots=free,
                    )
                    # Re-prompt LLM for smarter reply
                    analysis = await self._reprompt_with_conflict(
                        email, summary, cal_info, analysis, lang
                    )
                else:
                    cal_text = t(
                        "email_cal_free", lang=lang
                    )

        # Build notification text
        if analysis.event_request and analysis.needs_reply:
            text = t(
                "email_poll_single_event",
                lang=lang,
                sender=sender,
                subject=subject,
                summary=summary,
                proposed_datetime=(
                    analysis.proposed_datetime or "?"
                ),
                urgency=self._urgency_emoji(
                    analysis.urgency
                ),
                suggested_reply=analysis.suggested_reply,
            )
        elif analysis.needs_reply:
            text = t(
                "email_poll_single_reply",
                lang=lang,
                sender=sender,
                subject=subject,
                summary=summary,
                urgency=self._urgency_emoji(
                    analysis.urgency
                ),
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

        # Append calendar info if present
        if cal_text:
            text = f"{text}\n\n{cal_text}"

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

    async def _reprompt_with_conflict(
        self,
        email: Dict[str, Any],
        summary: str,
        cal_info: Dict[str, Any],
        analysis: EmailAnalysis,
        lang: str,
    ) -> EmailAnalysis:
        """Re-prompt LLM with conflict info for a smarter reply."""
        ai = self._get_ai()
        if not ai:
            return analysis

        free = ", ".join(
            cal_info.get("free_slots_today", [])
        ) or "—"
        try:
            prompt = t(
                "email_poll_conflict_reprompt",
                lang=lang,
                sender=email.get("from_name", ""),
                subject=email.get("subject", ""),
                summary=summary,
                conflict_event=cal_info.get(
                    "conflicting_event", ""
                ),
                conflict_time=cal_info.get(
                    "conflict_time", ""
                ),
                free_slots=free,
            )

            if not ai.is_initialized():
                await ai.initialize()

            response = await self._call_llm(
                ai,
                prompt=prompt,
                max_tokens=200,
                temperature=0.3,
            )

            if response:
                clean = response.strip()
                if clean.startswith("```"):
                    clean = clean.split("\n", 1)[
                        -1
                    ].rsplit("```", 1)[0]
                data = json.loads(clean)
                new_reply = str(
                    data.get("suggested_reply", "")
                )
                if new_reply:
                    analysis.suggested_reply = new_reply
                    logger.info(
                        "Re-prompted reply with conflict "
                        "info for %s",
                        email.get("from_name", "?"),
                    )
        except Exception as e:
            logger.debug(
                "Conflict re-prompt failed: %s", e
            )

        return analysis

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

            response = await self._call_llm(
                ai,
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
            logger.warning(
                "AI service unavailable, skipping analysis "
                "for: %s",
                email.get("subject", "?"),
            )
            return EmailAnalysis()

        try:
            prompt = t(
                "email_poll_analysis_prompt",
                lang=lang,
                sender=email.get("from_name", ""),
                subject=email.get("subject", ""),
                summary=summary,
                today=datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d"
                ),
            )

            if not ai.is_initialized():
                await ai.initialize()

            logger.info(
                "Calling AI for email analysis: %s "
                "(sender=%s)",
                email.get("subject", "?"),
                email.get("from_name", "?"),
            )

            response = await self._call_llm(
                ai,
                prompt=prompt,
                max_tokens=300,
                temperature=0.2,
            )

            logger.info(
                "AI raw response length=%d for: %s",
                len(response or ""),
                email.get("subject", "?"),
            )

            analysis = self._parse_analysis(response or "")
            logger.info(
                "Email analysis result for %s: "
                "needs_reply=%s, urgency=%s, event=%s, "
                "suggested_reply_len=%d, subject=%r",
                email.get("from_name", "?"),
                analysis.needs_reply,
                analysis.urgency,
                analysis.event_request,
                len(analysis.suggested_reply),
                email.get("subject", ""),
            )
            return analysis

        except Exception as e:
            logger.warning(
                "Email analysis failed for %s: %s",
                email.get("subject", "?"),
                e,
            )
            sentry_sdk.capture_exception(e)
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
                event_request=bool(
                    data.get(
                        "event_request",
                        data.get("meeting_request", False),
                    )
                ),
                proposed_datetime=data.get(
                    "proposed_datetime"
                ),
                proposed_location=str(
                    data.get("proposed_location", "")
                ),
            )
        except (
            json.JSONDecodeError,
            AttributeError,
            KeyError,
        ) as exc:
            logger.warning(
                "Failed to parse email analysis JSON: "
                "%s — raw=%r",
                exc,
                response[:200],
            )
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
