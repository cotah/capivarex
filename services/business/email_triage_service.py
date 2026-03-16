"""
Email Triage Service — S8 (C08)

When user says "trata da minha inbox" or "organize my emails":
1. Fetches recent unread emails via Gmail service
2. GPT categorizes each by urgency (urgent/important/info/ignore)
3. Extracts action items (tasks, deadlines, meetings)
4. Suggests draft replies for urgent emails
5. Presents humanized summary

All output HUMANIZED via GPT — sounds like a capable, warm PA.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Urgency categories
URGENCY_LEVELS = {
    "urgent": {"emoji": "🔴", "label": "Urgent", "description": "Needs response today"},
    "important": {"emoji": "🟡", "label": "Important", "description": "Respond in 2-3 days"},
    "info": {"emoji": "🟢", "label": "Informative", "description": "Read when you can"},
    "ignore": {"emoji": "⚪", "label": "Skip", "description": "Spam/marketing/noise"},
}


async def triage_inbox(
    user_id: str,
    user_name: str = "",
    max_emails: int = 10,
) -> Optional[Dict[str, Any]]:
    """
    Main entry: triage the user's inbox.

    Returns:
        {
            "summary": "humanized summary text",
            "emails": [{"id", "subject", "from", "urgency", "action", "snippet"}],
            "actions": [{"type": "reminder|note|calendar", "content", "from_email"}],
            "stats": {"urgent": N, "important": N, "info": N, "ignore": N},
        }
    """
    gmail = get_service("gmail")
    if not gmail or not gmail.is_initialized():
        return None

    # 1. Fetch unread emails
    try:
        emails = await gmail.list_emails(
            user_id=user_id,
            max_results=max_emails,
            unread_only=True,
        )
    except Exception as e:
        logger.error("Email triage: fetch failed: %s", e)
        return None

    if not emails:
        name = user_name.split()[0] if user_name else "there"
        return {
            "summary": f"Hey {name}! 📭 Your inbox is clean — no unread emails. Nice work!",
            "emails": [],
            "actions": [],
            "stats": {"urgent": 0, "important": 0, "info": 0, "ignore": 0},
        }

    # 2. Get body snippets for better classification (first 500 chars)
    enriched = []
    for email in emails:
        body_preview = ""
        try:
            body = await gmail.get_email_body(user_id, email["id"])
            body_preview = body[:500] if body else email.get("snippet", "")
        except Exception:
            body_preview = email.get("snippet", "")

        enriched.append({
            **email,
            "body_preview": body_preview,
        })

    # 3. Classify all emails via GPT (batch for efficiency)
    classified = await _classify_emails(enriched, user_name)

    # 4. Extract action items
    actions = _extract_actions(classified)

    # 5. Count stats
    stats = {"urgent": 0, "important": 0, "info": 0, "ignore": 0}
    for e in classified:
        urgency = e.get("urgency", "info")
        if urgency in stats:
            stats[urgency] += 1

    # 6. Generate humanized summary
    summary = await _humanize_triage_summary(classified, stats, actions, user_name)

    return {
        "summary": summary,
        "emails": classified,
        "actions": actions,
        "stats": stats,
    }


async def _classify_emails(
    emails: List[Dict[str, Any]], user_name: str = "",
) -> List[Dict[str, Any]]:
    """Classify emails by urgency using GPT."""
    openai_svc = get_service("openai")

    if not openai_svc or not openai_svc.is_initialized():
        return _fallback_classify(emails)

    # Build batch prompt
    email_list = "\n".join(
        f"{i+1}. FROM: {e.get('from_name', '')} <{e.get('from_email', '')}>\n"
        f"   SUBJECT: {e.get('subject', '')}\n"
        f"   PREVIEW: {e.get('body_preview', e.get('snippet', ''))[:200]}"
        for i, e in enumerate(emails[:10])
    )

    prompt = f"""Analyze these emails and classify each by urgency. Also extract any action items.

URGENCY LEVELS:
- "urgent": needs response TODAY (client requests, deadlines, boss/manager, time-sensitive)
- "important": respond in 2-3 days (proposals, follow-ups, project updates)
- "info": read when free (newsletters, notifications, FYI emails)
- "ignore": skip (spam, marketing, promotions, automated notifications)

EMAILS:
{email_list}

Respond with ONLY a JSON array. Each item:
{{"index": 1, "urgency": "urgent|important|info|ignore", "reason": "brief reason", "action": "extracted task or empty string", "suggested_reply": "brief reply suggestion for urgent/important, empty for others"}}

JSON array:"""

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=1000,
            temperature=0.2,
        )

        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        parsed = json.loads(text)
        if isinstance(parsed, list):
            for item in parsed:
                idx = item.get("index", 0) - 1
                if 0 <= idx < len(emails):
                    emails[idx]["urgency"] = item.get("urgency", "info")
                    emails[idx]["urgency_reason"] = item.get("reason", "")
                    emails[idx]["action"] = item.get("action", "")
                    emails[idx]["suggested_reply"] = item.get("suggested_reply", "")
            return emails

    except Exception as e:
        logger.warning("Email triage: GPT classification failed: %s", e)

    return _fallback_classify(emails)


def _fallback_classify(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Simple keyword-based classification when GPT unavailable."""
    urgent_senders = ["boss", "ceo", "cto", "manager", "client", "urgent"]
    ignore_words = ["unsubscribe", "newsletter", "promotion", "marketing", "noreply", "no-reply"]

    for email in emails:
        from_str = (email.get("from_name", "") + " " + email.get("from_email", "")).lower()
        subject = email.get("subject", "").lower()
        combined = f"{from_str} {subject}"

        if any(w in combined for w in urgent_senders) or "urgent" in subject:
            email["urgency"] = "urgent"
        elif any(w in combined for w in ignore_words):
            email["urgency"] = "ignore"
        elif email.get("is_unread", True):
            email["urgency"] = "important"
        else:
            email["urgency"] = "info"

        email["urgency_reason"] = ""
        email["action"] = ""
        email["suggested_reply"] = ""

    return emails


def _extract_actions(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract action items from classified emails."""
    actions = []
    for email in emails:
        action_text = email.get("action", "")
        if action_text and len(action_text) > 5:
            actions.append({
                "type": "task",
                "content": action_text,
                "from_email": email.get("from_email", ""),
                "from_name": email.get("from_name", ""),
                "subject": email.get("subject", ""),
                "email_id": email.get("id", ""),
            })
    return actions


async def _humanize_triage_summary(
    emails: List[Dict[str, Any]],
    stats: Dict[str, int],
    actions: List[Dict[str, Any]],
    user_name: str = "",
) -> str:
    """Generate warm, humanized triage summary via GPT."""
    openai_svc = get_service("openai")
    name = user_name.split()[0] if user_name else "there"
    total = len(emails)

    # Build raw data
    urgent_list = [e for e in emails if e.get("urgency") == "urgent"]
    important_list = [e for e in emails if e.get("urgency") == "important"]

    raw = (
        f"User: {name}\n"
        f"Total unread: {total}\n"
        f"Urgent: {stats['urgent']}, Important: {stats['important']}, "
        f"Info: {stats['info']}, Ignore: {stats['ignore']}\n"
    )

    if urgent_list:
        raw += "\nURGENT EMAILS:\n"
        for e in urgent_list:
            raw += f"  - From {e.get('from_name', '?')}: {e.get('subject', '?')} — {e.get('urgency_reason', '')}\n"

    if important_list:
        raw += "\nIMPORTANT EMAILS:\n"
        for e in important_list[:3]:
            raw += f"  - From {e.get('from_name', '?')}: {e.get('subject', '?')}\n"

    if actions:
        raw += "\nACTION ITEMS FOUND:\n"
        for a in actions:
            raw += f"  - {a['content']} (from {a.get('from_name', '?')})\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant acting as {name}'s email PA. Generate an inbox triage summary.

RULES:
- Start with a warm greeting and overall status
- Highlight urgent emails first with actionable advice
- Mention important ones briefly
- Skip info/ignore in the summary (just mention count)
- If there are action items, list them as "things to do"
- End with an offer to help (draft reply, create reminder, etc.)
- Keep it under 15 lines
- Use emojis sparingly (🔴 urgent, 🟡 important, 📬 inbox)
- Sound like a capable PA who has your back

RAW DATA:
{raw}

Generate the triage summary:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=500,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception as e:
            logger.warning("Email triage: GPT summary failed: %s", e)

    # Fallback
    return _fallback_summary(name, stats, urgent_list, important_list, actions)


def _fallback_summary(
    name: str,
    stats: Dict[str, int],
    urgent: List[Dict],
    important: List[Dict],
    actions: List[Dict],
) -> str:
    """Fallback summary when GPT unavailable."""
    total = sum(stats.values())
    parts = [f"📬 Hey {name}! I've gone through your inbox — {total} unread emails.\n"]

    if stats["urgent"]:
        parts.append(f"🔴 **{stats['urgent']} urgent** — need attention today:")
        for e in urgent[:3]:
            parts.append(f"  • {e.get('from_name', '?')}: {e.get('subject', '?')}")

    if stats["important"]:
        parts.append(f"\n🟡 **{stats['important']} important** — respond in a few days")
        for e in important[:3]:
            parts.append(f"  • {e.get('from_name', '?')}: {e.get('subject', '?')}")

    if stats["info"]:
        parts.append(f"\n🟢 {stats['info']} informative — read when you can")

    if stats["ignore"]:
        parts.append(f"⚪ {stats['ignore']} to skip (newsletters, promotions)")

    if actions:
        parts.append("\n📋 **Action items I found:**")
        for a in actions[:3]:
            parts.append(f"  • {a['content']}")

    parts.append("\n💬 Want me to draft a reply, create a reminder, or archive the noise?")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Draft Reply Generation
# ---------------------------------------------------------------------------

async def generate_reply_draft(
    user_id: str,
    email_id: str,
    user_name: str = "",
    tone: str = "professional",
) -> Optional[str]:
    """
    Generate a humanized reply draft for an email.

    Args:
        user_id: User ID
        email_id: Gmail message ID
        user_name: User's name for signature
        tone: "professional", "casual", "formal"

    Returns: Draft reply text, or None if failed.
    """
    gmail = get_service("gmail")
    if not gmail:
        return None

    # Get the full email
    try:
        body = await gmail.get_email_body(user_id, email_id)
        emails = await gmail.list_emails(user_id, max_results=1, query=f"rfc822msgid:{email_id}")
        email_meta = emails[0] if emails else {}
    except Exception:
        body = ""
        email_meta = {}

    if not body:
        return None

    openai_svc = get_service("openai")
    name = user_name.split()[0] if user_name else ""

    if not openai_svc or not openai_svc.is_initialized():
        return None

    subject = email_meta.get("subject", "")
    from_name = email_meta.get("from_name", "")

    prompt = f"""You are helping {name or 'the user'} draft a reply to an email.

TONE: {tone}
FROM: {from_name}
SUBJECT: {subject}
ORIGINAL EMAIL:
{body[:2000]}

RULES:
- Write a natural, {tone} reply
- Address the sender by name if known
- Be concise but thorough
- Don't over-apologize or be overly formal
- Sign off with {name or 'Best regards'}
- Keep it under 10 sentences

Draft the reply:"""

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=400,
            temperature=0.7,
        )
        text = response if isinstance(response, str) else response.get("content", "")
        if text and len(text) > 10:
            return text
    except Exception as e:
        logger.warning("Email reply draft failed: %s", e)

    return None
