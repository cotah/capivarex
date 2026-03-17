"""
Budget Tracker Service — Monthly spending tracker (C5).

Tracks spending mentioned in conversations and emails:
- Detects spending mentions in messages ('gastei 50 euros no almoço')
- Categorizes automatically (food, transport, entertainment, bills, shopping...)
- Monthly summary with budget vs actual
- Alerts when approaching budget limit
- Weekly spending trends

Storage: user_context table (key: budget_entries, budget_limits)
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from services.core import get_service

logger = logging.getLogger(__name__)

# Spending categories
CATEGORIES = {
    "food": ["restaurante", "restaurant", "almoço", "lunch", "jantar", "dinner", "café", "coffee", "comida", "food", "supermercado", "grocery", "mercado", "ifood", "uber eats", "deliveroo"],
    "transport": ["uber", "taxi", "bolt", "gasolina", "gasoline", "fuel", "combustível", "estacionamento", "parking", "pedágio", "toll", "bilhete", "ticket", "metro", "bus", "luas", "dart"],
    "entertainment": ["cinema", "movie", "netflix", "spotify", "disney", "show", "concerto", "concert", "bar", "pub", "jogo", "game"],
    "bills": ["conta", "bill", "aluguel", "rent", "luz", "electricity", "água", "water", "internet", "telefone", "phone", "seguro", "insurance"],
    "shopping": ["roupa", "clothes", "shopping", "compra", "bought", "amazon", "zara", "nike", "loja", "store"],
    "health": ["médico", "doctor", "farmácia", "pharmacy", "remédio", "medicine", "academia", "gym"],
    "education": ["curso", "course", "livro", "book", "escola", "school", "aula", "class"],
}

# Currency patterns
CURRENCY_PATTERNS = [
    r"€\s*(\d+[.,]?\d*)",
    r"(\d+[.,]?\d*)\s*€",
    r"(\d+[.,]?\d*)\s*euro[s]?",
    r"R\$\s*(\d+[.,]?\d*)",
    r"(\d+[.,]?\d*)\s*reai[s]?",
    r"(?<!R)\$\s*(\d+[.,]?\d*)",
    r"(\d+[.,]?\d*)\s*dollar[s]?",
]

# Spending verbs
SPENDING_VERBS = [
    "gastei", "paguei", "comprei", "custou", "spent", "paid", "bought",
    "cost", "gasto", "pago", "gastar", "cobrou", "charged",
]


def detect_spending(message: str) -> Optional[Dict[str, Any]]:
    """
    Detect spending mentioned in a message.

    Returns:
        None if no spending detected, or:
        {"amount": 50.0, "currency": "EUR", "category": "food", "description": "almoço"}
    """
    lower = message.lower().strip()

    # Check if message has spending verbs
    has_verb = any(v in lower for v in SPENDING_VERBS)
    if not has_verb:
        return None

    # Extract amount
    amount, currency = _extract_amount(lower)
    if amount is None or amount <= 0:
        return None

    # Detect category
    category = _detect_category(lower)

    # Extract description (short summary)
    description = _extract_description(message, amount)

    return {
        "amount": amount,
        "currency": currency,
        "category": category,
        "description": description,
    }


def _extract_amount(text: str) -> Tuple[Optional[float], str]:
    """Extract monetary amount from text."""
    # Check BRL first (R$ before $ to avoid confusion)
    brl_match = re.search(r"[Rr]\$\s*(\d+[.,]?\d*)", text)
    if brl_match:
        try:
            return float(brl_match.group(1).replace(",", ".")), "BRL"
        except ValueError:
            pass

    for pattern in CURRENCY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            amount_str = match.group(1).replace(",", ".")
            try:
                amount = float(amount_str)
                if "€" in text or "euro" in text:
                    return amount, "EUR"
                elif "reai" in text:
                    return amount, "BRL"
                elif "$" in text or "dollar" in text:
                    return amount, "USD"
                return amount, "EUR"  # default
            except ValueError:
                continue
    return None, ""


def _detect_category(text: str) -> str:
    """Detect spending category from text."""
    best_cat = "other"
    best_count = 0

    for cat, keywords in CATEGORIES.items():
        count = sum(1 for kw in keywords if kw in text)
        if count > best_count:
            best_count = count
            best_cat = cat

    return best_cat


def _extract_description(message: str, amount: float) -> str:
    """Extract a short description of the spending."""
    # Take first 80 chars, removing the amount
    desc = message[:100].strip()
    if len(desc) > 80:
        desc = desc[:77] + "..."
    return desc


async def save_spending(user_id: str, entry: Dict[str, Any]) -> bool:
    """Save a spending entry."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        client = db.get_client()
        now = datetime.now(timezone.utc)

        # Load existing entries for this month
        month_key = now.strftime("%Y-%m")
        entries = await _load_month_entries(user_id, month_key)

        # Add new entry
        entries.append({
            "amount": entry["amount"],
            "currency": entry.get("currency", "EUR"),
            "category": entry.get("category", "other"),
            "description": entry.get("description", ""),
            "timestamp": time.time(),
            "date": now.isoformat(),
        })

        # Save
        client.table("user_context").upsert({
            "user_id": user_id,
            "key": f"budget_{month_key}",
            "value": json.dumps(entries),
        }).execute()

        logger.info("Budget: saved %.2f %s (%s) for user=%s", entry["amount"], entry.get("currency", "EUR"), entry.get("category", "other"), user_id[:8])
        return True

    except Exception as e:
        logger.warning("Budget save failed: %s", e)
        return False


async def get_monthly_summary(user_id: str, month: Optional[str] = None) -> Dict[str, Any]:
    """
    Get monthly spending summary.

    Returns: {"total": 450.0, "by_category": {"food": 200, ...}, "entries": [...]}
    """
    if not month:
        month = datetime.now(timezone.utc).strftime("%Y-%m")

    entries = await _load_month_entries(user_id, month)

    total = sum(e.get("amount", 0) for e in entries)
    by_category: Dict[str, float] = {}
    for e in entries:
        cat = e.get("category", "other")
        by_category[cat] = by_category.get(cat, 0) + e.get("amount", 0)

    # Get budget limits
    limits = await _get_budget_limits(user_id)

    return {
        "month": month,
        "total": round(total, 2),
        "by_category": {k: round(v, 2) for k, v in sorted(by_category.items(), key=lambda x: -x[1])},
        "entry_count": len(entries),
        "limits": limits,
        "currency": entries[0].get("currency", "EUR") if entries else "EUR",
    }


def format_monthly_summary(summary: Dict[str, Any], name: str = "") -> str:
    """Format monthly summary as a user-friendly message."""
    greeting = f"Oi {name}!" if name else ""
    total = summary["total"]
    currency = summary.get("currency", "EUR")
    month = summary.get("month", "")
    by_cat = summary.get("by_category", {})
    limits = summary.get("limits", {})

    currency_symbol = {"EUR": "€", "BRL": "R$", "USD": "$"}.get(currency, "€")

    msg = f"💰 **Resumo Financeiro** — {month}\n\n{greeting}\n\n"
    msg += f"📊 **Total gasto:** {currency_symbol}{total:.2f}\n\n"

    if by_cat:
        category_emojis = {
            "food": "🍽️", "transport": "🚗", "entertainment": "🎭",
            "bills": "📄", "shopping": "🛍️", "health": "🏥",
            "education": "📚", "other": "📦",
        }
        for cat, amount in by_cat.items():
            emoji = category_emojis.get(cat, "📦")
            cat_label = cat.capitalize()
            limit = limits.get(cat)
            limit_str = f" / {currency_symbol}{limit:.0f}" if limit else ""
            pct = f" ({amount/limit*100:.0f}%)" if limit else ""
            msg += f"{emoji} **{cat_label}:** {currency_symbol}{amount:.2f}{limit_str}{pct}\n"

    # Budget warnings
    total_limit = limits.get("total")
    if total_limit:
        pct = total / total_limit * 100
        msg += f"\n📈 Orçamento mensal: {currency_symbol}{total:.2f} / {currency_symbol}{total_limit:.2f} ({pct:.0f}%)\n"
        if pct >= 90:
            msg += "⚠️ **Atenção!** Quase no limite do orçamento!\n"
        elif pct >= 75:
            msg += "🟡 75% do orçamento utilizado. Cuidado!\n"

    return msg


async def set_budget_limit(user_id: str, category: str, limit: float) -> bool:
    """Set a budget limit for a category (or 'total')."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return False

        client = db.get_client()
        limits = await _get_budget_limits(user_id)
        limits[category] = limit

        client.table("user_context").upsert({
            "user_id": user_id,
            "key": "budget_limits",
            "value": json.dumps(limits),
        }).execute()
        return True
    except Exception as e:
        logger.warning("Budget limit save failed: %s", e)
        return False


async def _load_month_entries(user_id: str, month_key: str) -> List[Dict[str, Any]]:
    """Load spending entries for a specific month."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return []

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", f"budget_{month_key}")
            .limit(1)
            .execute()
        )
        if result.data:
            val = result.data[0].get("value", "[]")
            return json.loads(val) if isinstance(val, str) else val
    except Exception as e:
        logger.warning("Budget load failed: %s", e)
    return []


async def _get_budget_limits(user_id: str) -> Dict[str, float]:
    """Get user's budget limits."""
    try:
        db = get_service("database")
        if not db or not db.is_initialized():
            return {}

        client = db.get_client()
        result = (
            client.table("user_context")
            .select("value")
            .eq("user_id", user_id)
            .eq("key", "budget_limits")
            .limit(1)
            .execute()
        )
        if result.data:
            val = result.data[0].get("value", "{}")
            return json.loads(val) if isinstance(val, str) else val
    except Exception:
        pass
    return {}
