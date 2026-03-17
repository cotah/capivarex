"""
Subscription Expiring Service — A9 (P27)

Detects subscription renewals from emails and user messages:
1. Scans emails for renewal/subscription keywords
2. Extracts: service name, amount, renewal date
3. Alerts 5 days before: "Netflix renews in 5 days (€15.99). Keep or cancel?"

Storage: user_context table (key: subscriptions)

All output HUMANIZED via GPT.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Subscription keywords (multi-language)
SUBSCRIPTION_KEYWORDS = [
    # English
    "subscription", "renewal", "renew", "auto-renew", "recurring",
    "billing cycle", "next payment", "will be charged", "membership",
    "plan expires", "trial ends", "trial ending",
    # Portuguese
    "assinatura", "renovação", "renovar", "renovação automática",
    "cobrança recorrente", "próximo pagamento", "plano expira",
    "período de teste", "subscrição",
    # Spanish
    "suscripción", "renovación", "pago recurrente",
]

# Common subscription services (for better detection)
KNOWN_SERVICES = [
    "netflix", "spotify", "youtube", "disney", "hbo", "amazon prime",
    "apple music", "apple tv", "icloud", "google one", "dropbox",
    "adobe", "microsoft 365", "office 365", "chatgpt", "openai",
    "github", "notion", "figma", "canva", "grammarly", "slack",
    "zoom", "linkedin", "twitter", "x premium", "twitch",
    "nordvpn", "expressvpn", "1password", "lastpass", "bitwarden",
    "gym", "ginásio", "academia",
]

STORAGE_KEY = "subscriptions"
ALERT_DAYS_BEFORE = 5


def detect_subscription_mention(message: str) -> bool:
    """Quick check if message mentions a subscription."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in SUBSCRIPTION_KEYWORDS)


async def extract_subscription_info(message: str) -> Optional[Dict[str, Any]]:
    """Extract subscription details from a message via GPT."""
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return _fallback_extract(message)

    prompt = f"""Analyze this message and extract subscription/renewal information.

Message: "{message}"

If it mentions a subscription, renewal, or recurring payment, return JSON:
{{"name": "service name", "amount": "price or empty", "renewal_day": day_of_month_or_0, "renewal_date": "YYYY-MM-DD or empty", "frequency": "monthly|yearly|weekly", "auto_renew": true_or_false}}

If NOT about a subscription, return: {{"is_subscription": false}}

JSON only:"""

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=200,
            temperature=0.1,
        )

        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        parsed = json.loads(text)
        if parsed.get("is_subscription") is False:
            return None
        return parsed

    except Exception as e:
        logger.warning("Subscription extraction failed: %s", e)
        return _fallback_extract(message)


def _fallback_extract(message: str) -> Optional[Dict[str, Any]]:
    """Simple fallback extraction."""
    msg_lower = message.lower()
    if not detect_subscription_mention(msg_lower):
        return None

    # Try to find known service name
    name = ""
    for svc in KNOWN_SERVICES:
        if svc in msg_lower:
            name = svc.title()
            break

    if not name:
        name = message[:60]

    # Try to extract amount
    amount_match = re.search(r"[€$£]\s*[\d,.]+|[\d,.]+\s*[€$£]", message)
    amount = amount_match.group(0) if amount_match else ""

    # Try to extract day
    day_match = re.search(r"(?:dia|day|on the)\s*(\d{1,2})", msg_lower)
    renewal_day = int(day_match.group(1)) if day_match else 0

    return {
        "name": name,
        "amount": amount,
        "renewal_day": renewal_day,
        "frequency": "monthly",
        "auto_renew": True,
    }


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

async def save_subscription(user_id: str, sub: Dict[str, Any]) -> bool:
    """Save a subscription to user_context."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        existing = await _get_subscriptions(user_id)

        # Dedup by name
        name_lower = sub.get("name", "").lower().strip()
        existing = [s for s in existing if s.get("name", "").lower().strip() != name_lower]

        sub["created_at"] = datetime.now(timezone.utc).isoformat()
        existing.append(sub)

        client.table("user_context").upsert({
            "user_id": user_id,
            "key": STORAGE_KEY,
            "value": json.dumps(existing),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True

    except Exception as e:
        logger.error("Save subscription failed: %s", e)
        return False


async def _get_subscriptions(user_id: str) -> List[Dict[str, Any]]:
    """Get stored subscriptions."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return []

    try:
        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", STORAGE_KEY)
            .execute()
        )
        if result.data and result.data[0].get("value"):
            return json.loads(result.data[0]["value"])
    except Exception:
        pass
    return []


async def remove_subscription(user_id: str, name: str) -> bool:
    """Remove a subscription by name."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        existing = await _get_subscriptions(user_id)
        name_lower = name.lower().strip()
        filtered = [s for s in existing if s.get("name", "").lower().strip() != name_lower]
        if len(filtered) == len(existing):
            return False

        client = db.get_client()
        client.table("user_context").upsert({
            "user_id": user_id,
            "key": STORAGE_KEY,
            "value": json.dumps(filtered),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True

    except Exception as e:
        logger.error("Remove subscription failed: %s", e)
        return False


async def list_subscriptions(user_id: str) -> List[Dict[str, Any]]:
    """List all tracked subscriptions."""
    return await _get_subscriptions(user_id)


# ---------------------------------------------------------------------------
# Check & Alert
# ---------------------------------------------------------------------------

async def check_expiring_subscriptions(user_id: str) -> List[Dict[str, Any]]:
    """Check for subscriptions renewing within ALERT_DAYS_BEFORE days."""
    subs = await _get_subscriptions(user_id)
    if not subs:
        return []

    now = datetime.now(timezone.utc)
    alerts = []

    for sub in subs:
        renewal_day = sub.get("renewal_day", 0)
        renewal_date_str = sub.get("renewal_date", "")

        if renewal_date_str:
            try:
                renewal_dt = datetime.strptime(renewal_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_until = (renewal_dt - now).days
            except ValueError:
                continue
        elif renewal_day > 0:
            try:
                renewal_dt = now.replace(day=renewal_day)
                if renewal_dt < now:
                    month = now.month + 1
                    year = now.year
                    if month > 12:
                        month = 1
                        year += 1
                    renewal_dt = renewal_dt.replace(month=month, year=year)
                days_until = (renewal_dt - now).days
            except ValueError:
                continue
        else:
            continue

        if 0 <= days_until <= ALERT_DAYS_BEFORE:
            urgency = "today" if days_until == 0 else "tomorrow" if days_until == 1 else "soon"
            alerts.append({**sub, "days_until": days_until, "urgency": urgency})

    return alerts


async def generate_subscription_alert(
    user_name: str, alerts: List[Dict[str, Any]],
) -> Optional[str]:
    """Generate humanized subscription alert."""
    if not alerts:
        return None

    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    raw = f"User: {name}\nSubscriptions renewing soon:\n"
    for a in alerts:
        raw += f"  - {a.get('name', '?')}: {a.get('amount', '?')} ({a['urgency']}, {a['days_until']} days)\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} has subscriptions renewing soon.

RULES:
- Be helpful: "Just a heads up about your subscriptions..."
- Mention each: name + amount + when
- Ask if they want to keep, cancel, or review alternatives
- Keep under 5 lines, use 💳 and 📅 emojis
- Don't be pushy about cancelling

RAW DATA:
{raw}

Generate:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=250,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    lines = [f"💳 Hey {name}! Subscription reminder:\n"]
    for a in alerts:
        amount = f" ({a['amount']})" if a.get("amount") else ""
        if a["urgency"] == "today":
            lines.append(f"📅 **{a.get('name', '?')}**{amount} — renews TODAY!")
        elif a["urgency"] == "tomorrow":
            lines.append(f"📅 **{a.get('name', '?')}**{amount} — renews tomorrow")
        else:
            lines.append(f"📅 **{a.get('name', '?')}**{amount} — renews in {a['days_until']} days")
    lines.append("\n💬 Want to keep, cancel, or look for alternatives?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point for chat flow
# ---------------------------------------------------------------------------

async def handle_subscription_mention(
    user_id: str, message: str, user_name: str = "",
) -> Optional[str]:
    """Detect and save subscription from user message."""
    if not detect_subscription_mention(message):
        return None

    sub = await extract_subscription_info(message)
    if not sub:
        return None

    saved = await save_subscription(user_id, sub)
    if not saved:
        return None

    name = user_name.split()[0] if user_name else "there"
    sub_name = sub.get("name", "subscription")
    amount = f" ({sub['amount']})" if sub.get("amount") else ""
    renewal = ""
    if sub.get("renewal_day"):
        renewal = f", renews day {sub['renewal_day']}"
    elif sub.get("renewal_date"):
        renewal = f", renews {sub['renewal_date']}"

    return (
        f"💳 Got it, {name}! I'll track **{sub_name}**{amount}{renewal}. "
        f"I'll remind you {ALERT_DAYS_BEFORE} days before it renews."
    )
