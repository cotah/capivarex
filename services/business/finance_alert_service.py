"""
Finance Alert Service — monitors stock/crypto prices and sends alerts.

Default threshold: 5% change in 24h.
User can change via chat: "set my stock alerts to 3%"
Config stored in user_context table (context_type='finance_alerts_config').

Runs as Step 4 in proactivity_loop (every 5 minutes).
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.core import get_service

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD_PCT = 5.0  # 5% default — not too noisy


async def get_alert_config(user_id: str) -> Dict[str, Any]:
    """Get user's finance alert configuration."""
    db = get_service("database")
    if not db:
        return _default_config()

    await db.initialize()
    client = db.get_client()
    if not client:
        return _default_config()

    try:
        result = (
            client.table("user_context")
            .select("data")
            .eq("user_id", user_id)
            .eq("context_type", "finance_alerts_config")
            .limit(1)
            .execute()
        )
        if result.data:
            data = result.data[0].get("data", {})
            if isinstance(data, str):
                data = json.loads(data)
            return {**_default_config(), **data}
    except Exception as e:
        logger.warning("Finance alerts: failed to get config: %s", e)

    return _default_config()


async def set_alert_config(user_id: str, config: Dict[str, Any]) -> bool:
    """Update user's finance alert configuration."""
    db = get_service("database")
    if not db:
        return False

    await db.initialize()
    client = db.get_client()
    if not client:
        return False

    try:
        # Merge with existing config
        current = await get_alert_config(user_id)
        merged = {**current, **config}

        now = datetime.now(timezone.utc).isoformat()
        client.table("user_context").upsert(
            {
                "user_id": user_id,
                "context_type": "finance_alerts_config",
                "data": json.dumps(merged),
                "last_updated": now,
            },
            on_conflict="user_id,context_type",
        ).execute()

        logger.info("Finance alerts: config updated for user=%s: %s", user_id[:8], merged)
        return True
    except Exception as e:
        logger.error("Finance alerts: failed to set config: %s", e)
        return False


async def check_price_alerts() -> int:
    """Check all users' watchlists for price movements exceeding threshold.

    Returns number of alerts sent.
    """
    db = get_service("database")
    if not db:
        return 0

    await db.initialize()
    client = db.get_client()
    if not client:
        return 0

    # Get users with proactivity enabled
    try:
        result = (
            client.table("proactivity_preferences")
            .select("user_id")
            .eq("enabled", True)
            .execute()
        )
        user_ids = [r["user_id"] for r in (result.data or [])]
    except Exception:
        return 0

    if not user_ids:
        return 0

    alerts_sent = 0

    # Get crypto prices (shared across all users — same data)
    crypto_data = await _get_crypto_prices()
    stock_data = await _get_stock_prices()

    for user_id in user_ids:
        try:
            config = await get_alert_config(user_id)
            if not config.get("enabled", True):
                continue

            threshold = config.get("threshold_pct", DEFAULT_THRESHOLD_PCT)
            alerts = []

            # Check crypto
            for coin in crypto_data:
                change = abs(coin.get("change_24h", 0) or 0)
                if change >= threshold:
                    direction = "📈" if coin.get("change_24h", 0) > 0 else "📉"
                    alerts.append({
                        "title": f"{direction} {coin['symbol']} {'+' if coin.get('change_24h', 0) > 0 else ''}{coin.get('change_24h', 0):.1f}%",
                        "message": f"{coin['name']} is at ${coin.get('price', 0):,.2f} — moved {change:.1f}% in 24h.",
                        "category": "crypto",
                    })

            # Check stocks
            for stock in stock_data:
                change = abs(stock.get("percent_change", 0) or 0)
                if change >= threshold:
                    direction = "📈" if stock.get("percent_change", 0) > 0 else "📉"
                    alerts.append({
                        "title": f"{direction} {stock['symbol']} {'+' if stock.get('percent_change', 0) > 0 else ''}{stock.get('percent_change', 0):.1f}%",
                        "message": f"{stock.get('name', stock['symbol'])} is at ${stock.get('price', 0):,.2f} — moved {change:.1f}% today.",
                        "category": "stock",
                    })

            # Store alerts in proactivity_feed (deduplicate — 1 alert per asset per day)
            now = datetime.now(timezone.utc)
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()

            for alert in alerts:
                try:
                    # Check if already alerted today for this asset
                    existing = (
                        client.table("proactivity_feed")
                        .select("id")
                        .eq("user_id", user_id)
                        .eq("type", "finance_alert")
                        .eq("title", alert["title"])
                        .gte("created_at", today_start)
                        .limit(1)
                        .execute()
                    )
                    if existing.data:
                        continue  # Already sent today

                    client.table("proactivity_feed").insert({
                        "user_id": user_id,
                        "type": "finance_alert",
                        "title": alert["title"],
                        "message": alert["message"],
                        "metadata": json.dumps({"category": alert["category"]}),
                        "is_read": False,
                        "created_at": now.isoformat(),
                    }).execute()
                    alerts_sent += 1
                except Exception as e:
                    logger.warning("Finance alerts: insert failed: %s", e)

        except Exception as e:
            logger.warning("Finance alerts: check failed for user=%s: %s", user_id[:8], e)

    if alerts_sent > 0:
        logger.info("Finance alerts: sent %d alerts", alerts_sent)
    return alerts_sent


async def _get_crypto_prices() -> List[Dict[str, Any]]:
    """Get top crypto prices from CoinGecko service."""
    try:
        crypto_svc = get_service("crypto")
        if not crypto_svc:
            return []
        await crypto_svc.initialize()
        coins = await crypto_svc.get_top_coins(n=20, vs_currency="usd")
        return [
            {
                "symbol": c.get("symbol", "").upper(),
                "name": c.get("name", ""),
                "price": c.get("price", 0),
                "change_24h": c.get("change_24h", 0),
            }
            for c in coins
        ]
    except Exception as e:
        logger.warning("Finance alerts: crypto prices failed: %s", e)
        return []


async def _get_stock_prices() -> List[Dict[str, Any]]:
    """Get major stock prices from Twelve Data."""
    symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META"]
    try:
        finance_svc = get_service("finance")
        if not finance_svc:
            return []
        await finance_svc.initialize()
        stocks = []
        for sym in symbols:
            try:
                quote = await finance_svc.get_quote(sym)
                stocks.append({
                    "symbol": quote.get("symbol", sym),
                    "name": quote.get("name", sym),
                    "price": quote.get("price", 0),
                    "percent_change": quote.get("percent_change", 0),
                })
            except Exception:
                pass
        return stocks
    except Exception as e:
        logger.warning("Finance alerts: stock prices failed: %s", e)
        return []


def _default_config() -> Dict[str, Any]:
    """Default alert configuration."""
    return {
        "enabled": True,
        "threshold_pct": DEFAULT_THRESHOLD_PCT,
    }
