"""
Payment Reminder Service — A4 (P11)

Detects bills and payments from:
1. User messages ("conta da luz vence dia 20")
2. Email subjects with bill/payment keywords
3. Notes with payment mentions

When detected:
- Stores in user_context as payment entry
- 3 days before due date: sends humanized reminder
- On due date: urgent reminder
- Offers to create calendar event or set recurring reminder

All output HUMANIZED via GPT.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Payment keywords (multi-language)
PAYMENT_KEYWORDS_PT = [
    "conta", "fatura", "pagamento", "boleto", "prestação",
    "mensalidade", "anuidade", "vencimento", "vence dia",
    "pagar até", "débito", "cobrança", "parcela",
]
PAYMENT_KEYWORDS_EN = [
    "bill", "invoice", "payment", "due date", "pay by",
    "subscription", "rent", "mortgage", "installment",
    "utility bill", "electric bill", "water bill",
]
PAYMENT_KEYWORDS_ES = [
    "factura", "pago", "vencimiento", "cuota", "recibo",
]

ALL_PAYMENT_KEYWORDS = PAYMENT_KEYWORDS_PT + PAYMENT_KEYWORDS_EN + PAYMENT_KEYWORDS_ES

# Storage key in user_context
PAYMENT_CONTEXT_KEY = "payment_reminders"


# ---------------------------------------------------------------------------
# Detection: extract payment info from messages
# ---------------------------------------------------------------------------

def detect_payment_mention(message: str) -> bool:
    """Quick check if message mentions a payment/bill."""
    msg_lower = message.lower()
    return any(kw in msg_lower for kw in ALL_PAYMENT_KEYWORDS)


async def extract_payment_info(message: str) -> Optional[Dict[str, Any]]:
    """
    Use GPT to extract payment details from a message.

    Returns: {"name": "Electricity bill", "amount": "€50", "due_day": 20,
              "recurring": true, "frequency": "monthly"}
    Or None if not a payment mention.
    """
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return _fallback_extract(message)

    prompt = f"""Analyze this message and extract payment/bill information.

Message: "{message}"

If it mentions a bill, invoice, payment, or due date, return JSON:
{{"name": "bill name", "amount": "amount or empty", "due_day": day_of_month_number_or_0, "due_date": "specific date YYYY-MM-DD or empty", "recurring": true_or_false, "frequency": "monthly|weekly|yearly|once"}}

If it's NOT about a payment/bill, return: {{"is_payment": false}}

JSON only, no markdown:"""

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=200,
            temperature=0.1,
        )

        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        parsed = json.loads(text)
        if parsed.get("is_payment") is False:
            return None
        return parsed

    except Exception as e:
        logger.warning("Payment extraction failed: %s", e)
        return _fallback_extract(message)


def _fallback_extract(message: str) -> Optional[Dict[str, Any]]:
    """Simple fallback extraction when GPT unavailable."""
    import re

    msg_lower = message.lower()
    if not detect_payment_mention(msg_lower):
        return None

    # Try to extract day number
    day_match = re.search(r"(?:dia|day|due)\s*(\d{1,2})", msg_lower)
    due_day = int(day_match.group(1)) if day_match else 0

    # Try to extract amount
    amount_match = re.search(r"[€$£]\s*[\d,.]+|[\d,.]+\s*[€$£]", message)
    amount = amount_match.group(0) if amount_match else ""

    return {
        "name": message[:80],
        "amount": amount,
        "due_day": due_day,
        "recurring": True,
        "frequency": "monthly",
    }


# ---------------------------------------------------------------------------
# Storage: persist payments in user_context
# ---------------------------------------------------------------------------

async def save_payment(user_id: str, payment: Dict[str, Any]) -> bool:
    """Save a payment reminder to user_context."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()

        # Get existing payments
        existing = await _get_payments(user_id)

        # Dedup by name (case insensitive)
        name_lower = payment.get("name", "").lower().strip()
        existing = [p for p in existing if p.get("name", "").lower().strip() != name_lower]

        # Add new
        payment["created_at"] = datetime.now(timezone.utc).isoformat()
        existing.append(payment)

        # Save
        client.table("user_context").upsert({
            "user_id": user_id,
            "key": PAYMENT_CONTEXT_KEY,
            "value": json.dumps(existing),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()

        return True

    except Exception as e:
        logger.error("Save payment failed: %s", e)
        return False


async def _get_payments(user_id: str) -> List[Dict[str, Any]]:
    """Get stored payments from user_context."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return []

    try:
        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", PAYMENT_CONTEXT_KEY)
            .execute()
        )
        if result.data and result.data[0].get("value"):
            return json.loads(result.data[0]["value"])
    except Exception:
        pass
    return []


async def remove_payment(user_id: str, payment_name: str) -> bool:
    """Remove a payment by name."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        existing = await _get_payments(user_id)
        name_lower = payment_name.lower().strip()
        filtered = [p for p in existing if p.get("name", "").lower().strip() != name_lower]

        if len(filtered) == len(existing):
            return False  # Not found

        client = db.get_client()
        client.table("user_context").upsert({
            "user_id": user_id,
            "key": PAYMENT_CONTEXT_KEY,
            "value": json.dumps(filtered),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True

    except Exception as e:
        logger.error("Remove payment failed: %s", e)
        return False


async def list_payments(user_id: str) -> List[Dict[str, Any]]:
    """List all payment reminders for a user."""
    return await _get_payments(user_id)


# ---------------------------------------------------------------------------
# Check & Alert: proactivity loop runner
# ---------------------------------------------------------------------------

async def check_payments_due(user_id: str, user_name: str = "") -> List[Dict[str, Any]]:
    """
    Check if any payments are due soon (within 3 days) or overdue.

    Returns list of alerts to send.
    """
    payments = await _get_payments(user_id)
    if not payments:
        return []

    now = datetime.now(timezone.utc)
    current_month = now.month

    alerts = []
    for payment in payments:
        due_day = payment.get("due_day", 0)
        due_date_str = payment.get("due_date", "")

        if due_date_str:
            # Specific date
            try:
                due_dt = datetime.strptime(due_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                days_until = (due_dt - now).days
            except ValueError:
                continue
        elif due_day > 0:
            # Monthly recurring — calculate days until due_day this month
            try:
                due_dt = now.replace(day=due_day)
                if due_dt < now:
                    # Already passed this month, check next month
                    if current_month == 12:
                        due_dt = due_dt.replace(year=now.year + 1, month=1)
                    else:
                        due_dt = due_dt.replace(month=current_month + 1)
                days_until = (due_dt - now).days
            except ValueError:
                continue
        else:
            continue

        # Alert logic
        urgency = None
        if days_until == 0:
            urgency = "today"
        elif days_until == 1:
            urgency = "tomorrow"
        elif 0 < days_until <= 3:
            urgency = "soon"
        elif days_until < 0 and days_until >= -3:
            urgency = "overdue"

        if urgency:
            alerts.append({
                **payment,
                "days_until": days_until,
                "urgency": urgency,
            })

    return alerts


async def generate_payment_alert(
    user_name: str,
    alerts: List[Dict[str, Any]],
) -> Optional[str]:
    """Generate humanized payment reminder from alerts."""
    if not alerts:
        return None

    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    raw = f"User: {name}\nPayments due:\n"
    for a in alerts:
        raw += (
            f"  - {a.get('name', '?')}: {a.get('amount', '?')} "
            f"({a['urgency']}, {a['days_until']} days)\n"
        )

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} has payment(s) coming up. Generate a brief, helpful reminder.

RULES:
- Be warm, not alarming (unless overdue)
- Mention each payment name + amount + when
- If overdue: gentle but clear urgency
- If today: "don't forget!"
- If soon: casual reminder
- Offer to set a calendar reminder
- Keep under 5 lines, use 2 emojis max (💰 📅)

RAW DATA:
{raw}

Generate:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=250,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    lines = [f"💰 Hey {name}! Quick payment heads-up:\n"]
    for a in alerts:
        emoji = "🔴" if a["urgency"] == "overdue" else "🟡" if a["urgency"] == "today" else "📅"
        amount = f" ({a['amount']})" if a.get("amount") else ""
        if a["urgency"] == "overdue":
            lines.append(f"{emoji} **{a['name']}**{amount} — overdue by {abs(a['days_until'])} day(s)!")
        elif a["urgency"] == "today":
            lines.append(f"{emoji} **{a['name']}**{amount} — due TODAY!")
        elif a["urgency"] == "tomorrow":
            lines.append(f"{emoji} **{a['name']}**{amount} — due tomorrow")
        else:
            lines.append(f"{emoji} **{a['name']}**{amount} — due in {a['days_until']} days")

    lines.append("\n💬 Want me to set a calendar reminder?")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point for implicit detection
# ---------------------------------------------------------------------------

async def handle_payment_mention(
    user_id: str,
    message: str,
    user_name: str = "",
) -> Optional[str]:
    """
    Detect and save payment from user message. Returns confirmation or None.
    Call from implicit_action_service or chat flow.
    """
    if not detect_payment_mention(message):
        return None

    payment = await extract_payment_info(message)
    if not payment:
        return None

    saved = await save_payment(user_id, payment)
    if not saved:
        return None

    name = user_name.split()[0] if user_name else "there"
    payment_name = payment.get("name", "payment")
    due_info = ""
    if payment.get("due_day"):
        due_info = f" (due day {payment['due_day']} every month)"
    elif payment.get("due_date"):
        due_info = f" (due {payment['due_date']})"

    return (
        f"💰 Got it, {name}! I'll remember **{payment_name}**{due_info}. "
        f"I'll remind you 3 days before it's due."
    )
