"""
Package Tracking Central — A10 (C18)

Auto-detects tracking numbers from emails and messages, monitors delivery status:
1. Scans emails for tracking numbers (regex patterns for major carriers)
2. Stores in user_context with carrier + source info
3. Periodically checks status via 17TRACK API (existing tracking service)
4. Alerts on status changes: shipped → in transit → out for delivery → delivered

All output HUMANIZED via GPT.
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# Tracking number patterns (regex) for major carriers
TRACKING_PATTERNS = [
    # UPS: 1Z + 6 alphanumeric + check digit (18 chars)
    (r"\b(1Z[0-9A-Z]{16})\b", "UPS"),
    # FedEx: 12-22 digits
    (r"\b(\d{12,22})\b", None),  # Generic long number
    # DHL: 10-11 digits or JD + 18 digits
    (r"\b(JD\d{18})\b", "DHL"),
    (r"\b(\d{10,11})\b", None),
    # USPS: 20-22 digits or starts with 94/92/93
    (r"\b(9[2-4]\d{18,20})\b", "USPS"),
    # Royal Mail / CTT / An Post: 2 letters + 9 digits + 2 letters
    (r"\b([A-Z]{2}\d{9}[A-Z]{2})\b", None),
    # Amazon: TBA + digits
    (r"\b(TBA\d{10,12})\b", "Amazon"),
    # Generic: any alphanumeric 10-30 chars near tracking keywords
    (r"(?:tracking|rastreio|seguimiento)[:\s#]*([A-Z0-9]{10,30})", None),
]

# Keywords that indicate a tracking number is nearby
TRACKING_KEYWORDS = [
    "tracking", "track", "rastreio", "rastrear", "shipped", "enviado",
    "dispatch", "delivery", "entrega", "encomenda", "package", "parcel",
    "courier", "carrier", "transportadora", "seguimiento",
    "order shipped", "your order", "a sua encomenda",
]

STORAGE_KEY = "tracked_packages"


def detect_tracking_numbers(text: str) -> List[Dict[str, str]]:
    """
    Extract tracking numbers from text using regex patterns.

    Returns list of {"number": "...", "carrier": "..." or "auto"}
    """
    found = []
    seen = set()
    text_upper = text.upper()

    # Only look for tracking numbers if tracking keywords are present
    has_keywords = any(kw in text.lower() for kw in TRACKING_KEYWORDS)

    for pattern, carrier in TRACKING_PATTERNS:
        matches = re.findall(pattern, text_upper)
        for match in matches:
            num = match.strip()
            if num in seen:
                continue
            if len(num) < 8:
                continue
            # For generic patterns, only accept if tracking keywords present
            if carrier is None and not has_keywords:
                continue
            seen.add(num)
            found.append({
                "number": num,
                "carrier": carrier or "auto",
            })

    return found[:5]  # Max 5 per message


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

async def save_package(user_id: str, package: Dict[str, Any]) -> bool:
    """Save a tracked package to user_context."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        existing = await _get_packages(user_id)

        # Dedup by tracking number
        num = package.get("number", "").upper()
        existing = [p for p in existing if p.get("number", "").upper() != num]

        package["added_at"] = datetime.now(timezone.utc).isoformat()
        package["last_status"] = ""
        package["delivered"] = False
        existing.append(package)

        client.table("user_context").upsert({
            "user_id": user_id,
            "key": STORAGE_KEY,
            "value": json.dumps(existing),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
        return True

    except Exception as e:
        logger.error("Save package failed: %s", e)
        return False


async def _get_packages(user_id: str) -> List[Dict[str, Any]]:
    """Get stored packages."""
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


async def remove_package(user_id: str, tracking_number: str) -> bool:
    """Remove a tracked package."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        existing = await _get_packages(user_id)
        num = tracking_number.upper()
        filtered = [p for p in existing if p.get("number", "").upper() != num]
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
        logger.error("Remove package failed: %s", e)
        return False


async def list_packages(user_id: str) -> List[Dict[str, Any]]:
    """List all tracked packages (active + delivered)."""
    return await _get_packages(user_id)


# ---------------------------------------------------------------------------
# Status Checking
# ---------------------------------------------------------------------------

async def check_package_updates(user_id: str) -> List[Dict[str, Any]]:
    """
    Check all tracked packages for status updates.

    Returns list of packages with new status changes.
    """
    packages = await _get_packages(user_id)
    if not packages:
        return []

    tracking_svc = get_service("tracking")
    if not tracking_svc or not tracking_svc.is_initialized():
        return []

    updates = []
    updated_packages = []

    for pkg in packages:
        if pkg.get("delivered"):
            updated_packages.append(pkg)
            continue

        try:
            result = await tracking_svc.track(pkg["number"])
            current_status = result.get("status", "")
            previous_status = pkg.get("last_status", "")

            if current_status and current_status != previous_status:
                pkg["last_status"] = current_status
                pkg["last_checked"] = datetime.now(timezone.utc).isoformat()

                if "delivered" in current_status.lower() or "entregue" in current_status.lower():
                    pkg["delivered"] = True

                updates.append({
                    **pkg,
                    "previous_status": previous_status,
                    "new_status": current_status,
                    "events": result.get("events", [])[:3],
                })

        except Exception as e:
            logger.warning("Track check failed for %s: %s", pkg.get("number", "?")[:8], e)

        updated_packages.append(pkg)

    # Save updated statuses
    if updates:
        db = get_service("database")
        if db and db.is_initialized():
            try:
                client = db.get_client()
                client.table("user_context").upsert({
                    "user_id": user_id,
                    "key": STORAGE_KEY,
                    "value": json.dumps(updated_packages),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception:
                pass

    return updates


# ---------------------------------------------------------------------------
# Alert Generation
# ---------------------------------------------------------------------------

async def generate_tracking_alert(
    user_name: str, updates: List[Dict[str, Any]],
) -> Optional[str]:
    """Generate humanized tracking update alert."""
    if not updates:
        return None

    name = user_name.split()[0] if user_name else "there"
    openai_svc = get_service("openai")

    raw = f"User: {name}\nPackage updates:\n"
    for u in updates:
        raw += (
            f"  - {u.get('number', '?')[:12]}... ({u.get('carrier', 'auto')}): "
            f"{u.get('previous_status', 'unknown')} → {u.get('new_status', '?')}\n"
        )
        if u.get("source"):
            raw += f"    Source: {u['source']}\n"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. {name} has package tracking updates.

RULES:
- Be excited about deliveries: "Your package is on its way!"
- For delivered: celebrate "It's arrived! 🎉"
- Mention carrier and status change briefly
- Keep under 5 lines, use 📦 and 🚚 emojis
- If multiple packages, list each briefly

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
    lines = [f"📦 Hey {name}! Package update:\n"]
    for u in updates:
        num_short = u.get("number", "?")[:12]
        carrier = u.get("carrier", "")
        carrier_str = f" ({carrier})" if carrier and carrier != "auto" else ""
        new_status = u.get("new_status", "unknown")

        if "delivered" in new_status.lower():
            lines.append(f"🎉 **{num_short}...**{carrier_str} — Delivered! It's arrived!")
        elif "transit" in new_status.lower():
            lines.append(f"🚚 **{num_short}...**{carrier_str} — In transit: {new_status}")
        else:
            lines.append(f"📦 **{num_short}...**{carrier_str} — {new_status}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point: detect tracking from messages/emails
# ---------------------------------------------------------------------------

async def handle_tracking_mention(
    user_id: str, message: str, user_name: str = "", source: str = "chat",
) -> Optional[str]:
    """Detect and save tracking numbers from user message or email."""
    numbers = detect_tracking_numbers(message)
    if not numbers:
        return None

    saved_count = 0
    for num_info in numbers:
        pkg = {
            "number": num_info["number"],
            "carrier": num_info["carrier"],
            "source": source,
        }
        if await save_package(user_id, pkg):
            saved_count += 1

    if saved_count == 0:
        return None

    name = user_name.split()[0] if user_name else "there"
    if saved_count == 1:
        num = numbers[0]["number"]
        return f"📦 Got it, {name}! I'm tracking **{num[:12]}...**. I'll notify you when the status changes."
    return f"📦 Got it, {name}! I'm tracking **{saved_count} packages**. I'll keep you updated on each one."
