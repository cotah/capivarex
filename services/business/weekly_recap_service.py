"""
Weekly Finance Recap Service — S4 (P13 + C31)

Every Monday 09:00 UTC, generates a HUMANIZED weekly finance report:
1. User's personal watchlist (stocks + crypto they follow)
2. Market highlights (top movers of the week everyone's talking about)
3. Brief market context (why things moved)

The recap is passed through GPT to generate natural, emotional language
— NOT robotic templates. The bot should sound like a smart friend
who happens to be great at finance.

Watchlist stored in user_context table (context_type='finance_watchlist').
"""
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from services.core import get_service


# ---------------------------------------------------------------------------
# Watchlist Management (stored in user_context)
# ---------------------------------------------------------------------------

DEFAULT_STOCKS = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA"]
DEFAULT_CRYPTO = ["bitcoin", "ethereum", "solana"]


async def get_user_watchlist(user_id: str) -> Dict[str, List[str]]:
    """Get user's personal watchlist. Returns defaults if none set."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return {"stocks": list(DEFAULT_STOCKS), "crypto": list(DEFAULT_CRYPTO)}

    try:
        client = db.get_client()
        result = (
            client.table("user_context")
            .select("context_data")
            .eq("user_id", user_id)
            .eq("context_type", "finance_watchlist")
            .limit(1)
            .execute()
        )
        if result.data:
            data = result.data[0].get("context_data", {})
            if isinstance(data, str):
                data = json.loads(data)
            return {
                "stocks": data.get("stocks", list(DEFAULT_STOCKS)),
                "crypto": data.get("crypto", list(DEFAULT_CRYPTO)),
            }
    except Exception as e:
        logger.warning("Watchlist fetch failed for user={}: {}", user_id[:8], e)

    return {"stocks": list(DEFAULT_STOCKS), "crypto": list(DEFAULT_CRYPTO)}


async def add_to_watchlist(
    user_id: str, symbol: str, asset_type: str = "stock"
) -> Dict[str, Any]:
    """Add a stock or crypto to user's watchlist.

    Args:
        user_id: User ID
        symbol: Ticker/symbol (e.g. 'AAPL', 'bitcoin')
        asset_type: 'stock' or 'crypto'

    Returns: {"ok": True, "watchlist": {...}} or {"ok": False, "error": "..."}
    """
    watchlist = await get_user_watchlist(user_id)
    key = "stocks" if asset_type == "stock" else "crypto"
    symbol_clean = symbol.upper() if asset_type == "stock" else symbol.lower()

    if symbol_clean in watchlist[key]:
        return {"ok": False, "error": f"{symbol_clean} is already in your watchlist"}

    watchlist[key].append(symbol_clean)
    await _save_watchlist(user_id, watchlist)
    return {"ok": True, "watchlist": watchlist, "added": symbol_clean}


async def remove_from_watchlist(
    user_id: str, symbol: str, asset_type: str = "stock"
) -> Dict[str, Any]:
    """Remove a stock or crypto from user's watchlist."""
    watchlist = await get_user_watchlist(user_id)
    key = "stocks" if asset_type == "stock" else "crypto"
    symbol_clean = symbol.upper() if asset_type == "stock" else symbol.lower()

    if symbol_clean not in watchlist[key]:
        return {"ok": False, "error": f"{symbol_clean} is not in your watchlist"}

    watchlist[key].remove(symbol_clean)
    await _save_watchlist(user_id, watchlist)
    return {"ok": True, "watchlist": watchlist, "removed": symbol_clean}


async def _save_watchlist(user_id: str, watchlist: Dict[str, List[str]]) -> None:
    """Save watchlist to user_context table."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        client.table("user_context").upsert(
            {
                "user_id": user_id,
                "context_type": "finance_watchlist",
                "context_data": json.dumps(watchlist),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="user_id,context_type",
        ).execute()
    except Exception as e:
        logger.warning("Watchlist save failed for user={}: {}", user_id[:8], e)


# ---------------------------------------------------------------------------
# Weekly Recap Generation
# ---------------------------------------------------------------------------

async def generate_weekly_recap(
    user_id: str,
    user_name: str = "",
    chat_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate the weekly finance recap.

    Combines:
    1. User's watchlist performance
    2. Market top movers (biggest gainers/losers)
    3. Crypto highlights
    4. Market context (via research)

    Then passes through GPT for humanized, emotional text.
    """
    # Check if already sent this week
    if await _recap_sent_this_week(user_id):
        return None

    import asyncio

    # Gather user watchlist + market data concurrently
    watchlist = await get_user_watchlist(user_id)

    user_stocks_task = _get_stock_data(watchlist["stocks"])
    market_movers_task = _get_market_movers()
    user_crypto_task = _get_crypto_data(watchlist["crypto"])
    crypto_top_task = _get_top_crypto()

    user_stocks, market_movers, user_crypto, crypto_top = await asyncio.gather(
        user_stocks_task, market_movers_task, user_crypto_task, crypto_top_task,
        return_exceptions=True,
    )

    # Handle exceptions
    for name, val in [("user_stocks", user_stocks), ("market_movers", market_movers),
                      ("user_crypto", user_crypto), ("crypto_top", crypto_top)]:
        if isinstance(val, Exception):
            logger.warning("Weekly recap: {} failed: {}", name, val)

    # Build raw data for GPT
    raw_data = _build_raw_data(
        user_name=user_name,
        user_stocks=user_stocks if not isinstance(user_stocks, Exception) else {},
        market_movers=market_movers if not isinstance(market_movers, Exception) else [],
        user_crypto=user_crypto if not isinstance(user_crypto, Exception) else [],
        crypto_top=crypto_top if not isinstance(crypto_top, Exception) else [],
    )

    # Pass through GPT for humanized response
    message = await _humanize_recap(raw_data, user_name)

    title = f"Weekly recap — {datetime.now(timezone.utc).strftime('%b %d')}"

    # Store in proactivity_feed
    await _store_recap(user_id, title, message)

    # Send via Telegram
    if chat_id:
        try:
            notif = get_service("notification")
            if notif:
                if not notif.is_initialized():
                    await notif.initialize()
                await notif.send_message("telegram", chat_id, message)
        except Exception as e:
            logger.warning("Weekly recap: Telegram failed: {}", e)

    logger.info("Weekly recap: generated for user={} ({} chars)", user_id[:8], len(message))
    return {"title": title, "message": message}


# ---------------------------------------------------------------------------
# Data Fetchers
# ---------------------------------------------------------------------------

async def _get_stock_data(symbols: List[str]) -> Dict[str, Any]:
    """Get stock data for user's watchlist."""
    finance_svc = get_service("finance")
    if not finance_svc or not finance_svc.is_initialized():
        return {}

    import asyncio
    try:
        result = await asyncio.to_thread(finance_svc.get_watchlist_summary, symbols)
        return result if isinstance(result, dict) else {}
    except Exception:
        return {}


async def _get_market_movers() -> List[Dict[str, Any]]:
    """Get top market movers of the week (biggest gainers/losers)."""
    # Use a broad set of popular stocks to find movers
    popular = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META",
               "NFLX", "AMD", "INTC", "BA", "DIS", "JPM", "V", "COIN"]
    finance_svc = get_service("finance")
    if not finance_svc or not finance_svc.is_initialized():
        return []

    import asyncio
    try:
        result = await asyncio.to_thread(finance_svc.get_watchlist_summary, popular)
        if not isinstance(result, dict):
            return []

        items = result.get("watchlist", [])
        if not items and isinstance(result, dict):
            # Try alternative format
            items = [{"symbol": k, **v} for k, v in result.items()
                     if isinstance(v, dict) and "change_pct" in v]

        # Sort by absolute change to find biggest movers
        items.sort(key=lambda x: abs(x.get("change_pct", 0)), reverse=True)
        return items[:6]  # Top 6 movers
    except Exception:
        return []


async def _get_crypto_data(coins: List[str]) -> List[Dict[str, Any]]:
    """Get crypto data for user's watchlist."""
    crypto_svc = get_service("crypto")
    if not crypto_svc or not crypto_svc.is_initialized():
        return []

    import asyncio
    try:
        all_coins = await asyncio.to_thread(crypto_svc.get_top_coins, 20)
        if not isinstance(all_coins, list):
            return []
        # Filter to user's watchlist
        return [c for c in all_coins if c.get("id", "").lower() in [x.lower() for x in coins]]
    except Exception:
        return []


async def _get_top_crypto() -> List[Dict[str, Any]]:
    """Get top crypto movers of the week."""
    crypto_svc = get_service("crypto")
    if not crypto_svc or not crypto_svc.is_initialized():
        return []

    import asyncio
    try:
        all_coins = await asyncio.to_thread(crypto_svc.get_top_coins, 10)
        if not isinstance(all_coins, list):
            return []
        # Sort by 24h change
        all_coins.sort(key=lambda x: abs(x.get("price_change_percentage_24h", 0)), reverse=True)
        return all_coins[:5]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Humanization — Pass through GPT for natural language
# ---------------------------------------------------------------------------

def _build_raw_data(
    user_name: str,
    user_stocks: Dict[str, Any],
    market_movers: List[Dict[str, Any]],
    user_crypto: List[Dict[str, Any]],
    crypto_top: List[Dict[str, Any]],
) -> str:
    """Build structured raw data string for GPT to humanize."""
    parts = [f"User name: {user_name or 'friend'}"]

    # User's stocks
    stocks_list = user_stocks.get("watchlist", [])
    if not stocks_list and isinstance(user_stocks, dict):
        stocks_list = [{"symbol": k, **v} for k, v in user_stocks.items()
                       if isinstance(v, dict)]

    if stocks_list:
        parts.append("\nUSER'S STOCKS (their personal watchlist):")
        for s in stocks_list:
            sym = s.get("symbol", "?")
            price = s.get("price", s.get("current_price", "?"))
            change = s.get("change_pct", s.get("change_percent", 0))
            parts.append(f"  {sym}: ${price} ({change:+.2f}%)")

    # Market movers
    if market_movers:
        parts.append("\nMARKET HIGHLIGHTS (top movers everyone is talking about):")
        for m in market_movers:
            sym = m.get("symbol", "?")
            change = m.get("change_pct", m.get("change_percent", 0))
            parts.append(f"  {sym}: {change:+.2f}%")

    # User's crypto
    if user_crypto:
        parts.append("\nUSER'S CRYPTO (their personal list):")
        for c in user_crypto:
            name = c.get("name", c.get("symbol", "?"))
            price = c.get("current_price", "?")
            change = c.get("price_change_percentage_24h", 0)
            parts.append(f"  {name}: ${price} ({change:+.2f}% 24h)")

    # Top crypto movers
    if crypto_top:
        parts.append("\nCRYPTO HIGHLIGHTS (biggest movers):")
        for c in crypto_top:
            name = c.get("name", "?")
            change = c.get("price_change_percentage_24h", 0)
            parts.append(f"  {name}: {change:+.2f}% 24h")

    return "\n".join(parts)


async def _humanize_recap(raw_data: str, user_name: str) -> str:
    """Pass raw data through GPT to generate humanized, emotional recap."""
    openai_svc = get_service("openai")
    name = user_name.split()[0] if user_name else "friend"

    prompt = f"""You are CAPIVAREX, a personal AI assistant with personality. Generate a weekly finance recap message.

RULES:
- Address the user as {name}
- Be warm, conversational, like a smart friend who's great at finance
- Use emojis naturally (not excessively)
- Show emotion: celebrate wins, be supportive on losses, be encouraging
- Keep it concise: max 15 lines
- Structure: greeting → their stocks → their crypto → market highlights → closing question
- If something went up a lot, be excited. If it went down, be reassuring.
- Don't just list numbers — give PERSONALITY and CONTEXT
- Use "your" when talking about their assets, "the market" for general

BAD example (robotic):
"Weekly Report: AAPL +3.2%. TSLA -1.8%. BTC +5.1%."

GOOD example (humanized):
"Hey Marcos! Great week for your portfolio 📈 Apple had a stellar week, up 3.2% — those Q4 earnings really delivered. Tesla dipped a bit (-1.8%) but honestly that's just Tesla being Tesla, nothing to worry about. On the crypto side, Bitcoin is on fire! Up 5.1% this week. The market overall is feeling optimistic. Anything you want to adjust in your watchlist?"

RAW DATA:
{raw_data}

Generate the weekly recap message:"""

    if openai_svc and openai_svc.is_initialized():
        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=500,
                temperature=0.8,
            )
            if response and isinstance(response, str) and len(response) > 20:
                return response
            if response and isinstance(response, dict):
                text = response.get("content", response.get("message", ""))
                if text and len(text) > 20:
                    return text
        except Exception as e:
            logger.warning("Weekly recap: GPT humanization failed: {}", e)

    # Fallback: generate without GPT (still decent)
    return _fallback_recap(raw_data, name)


def _fallback_recap(raw_data: str, name: str) -> str:
    """Fallback recap if GPT is unavailable. Still warm, not robotic."""
    lines = raw_data.split("\n")
    parts = [f"Hey {name}! 📊 Here's your weekly finance update:\n"]

    for line in lines:
        if "USER'S STOCKS" in line:
            parts.append("**Your stocks this week:**")
        elif "MARKET HIGHLIGHTS" in line:
            parts.append("\n**What the market is talking about:**")
        elif "USER'S CRYPTO" in line:
            parts.append("\n**Your crypto:**")
        elif "CRYPTO HIGHLIGHTS" in line:
            parts.append("\n**Crypto movers:**")
        elif line.startswith("  ") and "User name" not in line:
            clean = line.strip()
            if not clean:
                continue
            if "+" in clean:
                parts.append(f"  🟢 {clean}")
            elif "-" in clean and "%" in clean:
                parts.append(f"  🔴 {clean}")
            else:
                parts.append(f"  • {clean}")

    parts.append("\n💬 Want me to dive deeper into any of these, or adjust your watchlist?")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

async def _recap_sent_this_week(user_id: str) -> bool:
    """Check if recap was already sent this week (since last Monday)."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return False

    try:
        client = db.get_client()
        # Find last Monday
        now = datetime.now(timezone.utc)
        days_since_monday = now.weekday()  # 0=Monday
        last_monday = now.replace(hour=0, minute=0, second=0) - __import__("datetime").timedelta(days=days_since_monday)

        result = (
            client.table("proactivity_feed")
            .select("id")
            .eq("user_id", user_id)
            .eq("type", "weekly_finance_recap")
            .gte("created_at", last_monday.isoformat())
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception:
        return False


async def _store_recap(user_id: str, title: str, message: str) -> None:
    """Store recap in proactivity_feed."""
    db = get_service("database")
    if not db or not db.is_initialized():
        return

    try:
        client = db.get_client()
        client.table("proactivity_feed").insert({
            "user_id": user_id,
            "type": "weekly_finance_recap",
            "title": title,
            "message": message,
            "metadata": json.dumps({"version": "1.0"}),
            "is_read": False,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as e:
        logger.warning("Weekly recap: failed to store: {}", e)
