"""
Push Notification Routes — Subscribe, unsubscribe, and send web push.

Endpoints:
- POST /api/webapp/notifications/subscribe    → save push subscription
- POST /api/webapp/notifications/unsubscribe  → remove push subscription
- POST /api/webapp/notifications/test         → send test notification (dev only)
"""

import os

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from api.middleware.webapp_auth import verify_webapp_user
from api.routes._helpers import _get_db

router = APIRouter(tags=["Notifications"])

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
VAPID_CLAIMS_EMAIL = os.getenv("VAPID_CLAIMS_EMAIL", "mailto:support@capivarex.com")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscriptionRequest(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys
    expirationTime: float | None = None


class PushMessageRequest(BaseModel):
    title: str = Field(default="CAPIVAREX")
    body: str
    url: str = Field(default="/chat")


# ---------------------------------------------------------------------------
# POST /notifications/subscribe
# ---------------------------------------------------------------------------


@router.post("/notifications/subscribe")
async def subscribe_push(
    body: PushSubscriptionRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Save a web push subscription for the user."""
    db = _get_db()

    try:
        db.table("push_subscriptions").upsert(
            {
                "user_id": user_id,
                "endpoint": body.endpoint,
                "p256dh": body.keys.p256dh,
                "auth": body.keys.auth,
            },
            on_conflict="user_id,endpoint",
        ).execute()

        logger.info(
            "Push: user={} subscribed (endpoint={}...)",
            user_id[:8],
            body.endpoint[:40],
        )
        return {"status": "subscribed"}

    except Exception as e:
        logger.error("Push subscribe error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to save subscription")


# ---------------------------------------------------------------------------
# POST /notifications/unsubscribe
# ---------------------------------------------------------------------------


@router.post("/notifications/unsubscribe")
async def unsubscribe_push(
    body: PushSubscriptionRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Remove a web push subscription."""
    db = _get_db()

    try:
        db.table("push_subscriptions").delete().eq(
            "user_id", user_id
        ).eq("endpoint", body.endpoint).execute()

        logger.info("Push: user={} unsubscribed", user_id[:8])
        return {"status": "unsubscribed"}

    except Exception as e:
        logger.error("Push unsubscribe error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to remove subscription")


# ---------------------------------------------------------------------------
# Internal: send push to a user (called by other services)
# ---------------------------------------------------------------------------


async def send_push_to_user(
    user_id: str,
    title: str = "CAPIVAREX",
    body: str = "",
    url: str = "/chat",
) -> int:
    """
    Send a web push notification to all subscriptions for a user.

    Args:
        user_id: Target user UUID.
        title: Notification title.
        body: Notification body text.
        url: URL to open when clicked.

    Returns:
        Number of successful deliveries.
    """
    if not VAPID_PRIVATE_KEY:
        logger.debug("Push: VAPID_PRIVATE_KEY not set, skipping")
        return 0

    try:
        from pywebpush import webpush, WebPushException
        import json
    except ImportError:
        logger.warning("Push: pywebpush not installed")
        return 0

    db = _get_db()
    result = (
        db.table("push_subscriptions")
        .select("endpoint, p256dh, auth")
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        return 0

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "icon": "/icons/icon-192x192.png",
        "badge": "/icons/icon-72x72.png",
    })

    sent = 0
    expired = []

    for sub in result.data:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"],
            },
        }
        try:
            webpush(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims={"sub": VAPID_CLAIMS_EMAIL},
            )
            sent += 1
        except WebPushException as e:
            status_code = getattr(e, "response", None)
            status = getattr(status_code, "status_code", 0) if status_code else 0
            if status in (404, 410):
                # Subscription expired — remove it
                expired.append(sub["endpoint"])
            else:
                logger.warning("Push send failed: {}", e)
        except Exception as e:
            logger.warning("Push send error: {}", e)

    # Clean up expired subscriptions
    for endpoint in expired:
        try:
            db.table("push_subscriptions").delete().eq(
                "user_id", user_id
            ).eq("endpoint", endpoint).execute()
        except Exception:
            pass

    if expired:
        logger.info("Push: cleaned {} expired subscriptions for user={}", len(expired), user_id[:8])

    logger.info("Push: sent {} notifications to user={}", sent, user_id[:8])
    return sent


# ---------------------------------------------------------------------------
# POST /notifications/test (dev only)
# ---------------------------------------------------------------------------


@router.post("/notifications/test")
async def test_push(
    user_id: str = Depends(verify_webapp_user),
):
    """Send a test push notification to the current user."""
    sent = await send_push_to_user(
        user_id=user_id,
        title="CAPIVAREX",
        body="Push notifications are working! 🎉",
        url="/settings",
    )
    return {"status": "ok", "sent": sent}
