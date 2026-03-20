# -*- coding: utf-8 -*-
"""
Billing Routes — Stripe checkout, webhook, status, portal.

Manages subscription plans (professional / executive) with daily message
quotas stored in ``public.users`` columns (plan, messages_used,
messages_limit, stripe_customer_id).

Endpoints:
- POST /api/billing/create-checkout  → Stripe Checkout session
- POST /api/billing/webhook          → Stripe webhook (public, no auth)
- GET  /api/billing/status           → current plan & usage
- POST /api/billing/portal           → Stripe billing portal
"""

import hmac
import os

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel, Field

from api.middleware.webapp_auth import verify_webapp_user
from api.routes._helpers import _get_db
from capivarex_modules.access_service import get_module_access_service

router = APIRouter(tags=["Billing"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
STRIPE_PRICE_PROFESSIONAL = os.getenv("STRIPE_PRICE_PROFESSIONAL")
STRIPE_PRICE_EXECUTIVE = os.getenv("STRIPE_PRICE_EXECUTIVE")
FRONTEND_URL = os.getenv("FRONTEND_URL", "https://app.capivarex.com")

if not STRIPE_SECRET_KEY:
    logger.warning("STRIPE_SECRET_KEY not set — billing endpoints will fail")
if not STRIPE_WEBHOOK_SECRET:
    logger.warning("STRIPE_WEBHOOK_SECRET not set — webhook verification will fail")
if not STRIPE_PRICE_PROFESSIONAL:
    logger.warning("STRIPE_PRICE_PROFESSIONAL not set")
if not STRIPE_PRICE_EXECUTIVE:
    logger.warning("STRIPE_PRICE_EXECUTIVE not set")

PLAN_LIMITS: dict[str, int] = {
    "professional": 300,
    "executive": 999999,
}

PLAN_PRICES: dict[str, str | None] = {
    "professional": STRIPE_PRICE_PROFESSIONAL,
    "executive": STRIPE_PRICE_EXECUTIVE,
}

# ---------------------------------------------------------------------------
# Capivara Module Stripe Price IDs (added March 2026)
# ---------------------------------------------------------------------------
STRIPE_PRICE_ARA = os.getenv("STRIPE_PRICE_ARA")
STRIPE_PRICE_IVI = os.getenv("STRIPE_PRICE_IVI")
STRIPE_PRICE_OKA = os.getenv("STRIPE_PRICE_OKA")
STRIPE_PRICE_YARA = os.getenv("STRIPE_PRICE_YARA")
STRIPE_PRICE_AYVU = os.getenv("STRIPE_PRICE_AYVU")
STRIPE_PRICE_MBAE = os.getenv("STRIPE_PRICE_MBAE")
STRIPE_PRICE_PORA = os.getenv("STRIPE_PRICE_PORA")

MODULE_STRIPE_PRICES: dict[str, str | None] = {
    "ara": STRIPE_PRICE_ARA,
    "ivi": STRIPE_PRICE_IVI,
    "oka": STRIPE_PRICE_OKA,
    "yara": STRIPE_PRICE_YARA,
    "ayvu": STRIPE_PRICE_AYVU,
    "mbae": STRIPE_PRICE_MBAE,
    "pora": STRIPE_PRICE_PORA,
}

# Bundle plans → modules that get unlocked automatically
# For capivarex_ultimate: all modules unlocked immediately
# For ara_plus_1 / capivarex_pro: modules stored in checkout metadata
#   (frontend shows a module picker after checkout success)
BUNDLE_MODULE_MAP: dict[str, list[str]] = {
    "capivarex_ultimate": ["ara", "ivi", "oka", "yara", "ayvu", "mbae", "pora"],
}

TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "")


def _plan_from_price(price_id: str | None) -> str | None:
    """Map a Stripe price ID back to a plan name."""
    if not price_id:
        return None
    if price_id == STRIPE_PRICE_PROFESSIONAL:
        return "professional"
    if price_id == STRIPE_PRICE_EXECUTIVE:
        return "executive"
    return None


async def _notify_admin(message: str) -> None:
    """Send a Telegram notification to the admin chat (best-effort)."""
    if not TELEGRAM_ADMIN_CHAT_ID:
        logger.debug("_notify_admin: TELEGRAM_ADMIN_CHAT_ID not set, skipping")
        return
    try:
        from services.core import get_service

        notification_svc = get_service("notification")
        if notification_svc:
            if not notification_svc.is_initialized():
                await notification_svc.initialize()
            await notification_svc.send_message(
                "telegram", TELEGRAM_ADMIN_CHAT_ID, message
            )
    except Exception as e:
        logger.warning("_notify_admin failed: {}", e)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class CreateCheckoutRequest(BaseModel):
    plan: str = Field(..., pattern=r"^(professional|executive)$")


# ---------------------------------------------------------------------------
# POST /api/billing/create-checkout
# ---------------------------------------------------------------------------


@router.post("/create-checkout")
async def create_checkout(
    body: CreateCheckoutRequest,
    request: Request,
    user_id: str = Depends(verify_webapp_user),
):
    """Create a Stripe Checkout session for the chosen plan."""
    stripe.api_key = STRIPE_SECRET_KEY
    db = _get_db()

    try:
        user_row = (
            db.table("users")
            .select("email, stripe_customer_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not user_row.data:
            # User exists in auth.users but not in public.users
            # (created before trigger was active) — extract email from
            # the JWT so the NOT NULL column is satisfied on upsert.
            import jwt as pyjwt

            token = request.headers.get("authorization", "").replace("Bearer ", "")
            try:
                payload = pyjwt.decode(token, options={"verify_signature": False})
                user_email = payload.get("email") or ""
            except Exception:
                user_email = ""

            logger.warning(
                "Billing: user={} not in public.users, upserting with email={}",
                user_id[:8],
                bool(user_email),
            )
            db.table("users").upsert(
                {
                    "id": user_id,
                    "email": user_email,
                    "plan": "professional",
                    "messages_used": 0,
                    "messages_limit": 300,
                }
            ).execute()
            user = {"email": user_email, "stripe_customer_id": None}
        else:
            user = user_row.data[0]
        customer_id = user.get("stripe_customer_id")

        # Create Stripe customer if one doesn't exist yet
        if not customer_id:
            customer = stripe.Customer.create(
                email=user.get("email"),
                metadata={"user_id": user_id},
            )
            customer_id = customer.id
            db.table("users").update({"stripe_customer_id": customer_id}).eq(
                "id", user_id
            ).execute()
            logger.info(
                f"Billing: created Stripe customer {customer_id[:16]}"
                f" for user={user_id[:8]}"
            )

        price_id = PLAN_PRICES[body.plan]
        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"user_id": user_id, "plan": body.plan},
            success_url=(
                f"{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}"
            ),
            cancel_url=f"{FRONTEND_URL}/billing/cancel",
        )

        logger.info(
            f"Billing: user={user_id[:8]} created checkout"
            f" plan={body.plan} session={session.id[:16]}"
        )
        return {"checkout_url": session.url}

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "Billing create-checkout error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to create checkout session")


# ---------------------------------------------------------------------------
# POST /api/billing/webhook  (NO auth — called by Stripe)
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events.

    Supported events:
    - ``checkout.session.completed`` → upgrade user plan
    - ``customer.subscription.deleted`` → reset to free
    - ``customer.subscription.updated`` → sync plan on upgrade/downgrade
    - ``invoice.payment_succeeded`` → confirm renewal
    - ``invoice.payment_failed`` → notify admin of failure
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    # SECURITY: Fail-closed — reject immediately if webhook secret is not configured
    if not STRIPE_WEBHOOK_SECRET:
        logger.error("Billing webhook: STRIPE_WEBHOOK_SECRET not configured — rejecting")
        raise HTTPException(status_code=500, detail="Webhook not configured")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.SignatureVerificationError):
        logger.warning("Billing webhook: invalid signature")
        raise HTTPException(status_code=400, detail="Invalid signature")

    db = _get_db()
    event_type = event.get("type", "")

    if event_type == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata", {})
        uid = meta.get("user_id")
        plan = meta.get("plan")
        customer_id = session.get("customer")

        if uid and plan and plan in PLAN_LIMITS:
            limit = PLAN_LIMITS[plan]
            db.table("users").update(
                {
                    "plan": plan,
                    "messages_limit": limit,
                    "stripe_customer_id": customer_id,
                }
            ).eq("id", uid).execute()
            logger.info(
                f"Billing: user={uid[:8]} upgraded to plan={plan} limit={limit}"
            )

        # If this checkout was for a module add-on, unlock it
        module_name = meta.get("module_name")
        if module_name and uid:
            access_svc = get_module_access_service()
            await access_svc.unlock_module(uid, module_name)
            logger.info(
                "Module {} unlocked for user {} via Stripe webhook",
                module_name, uid[:8],
            )

        # If this checkout was for a bundle plan, unlock all bundle modules
        if uid and plan and plan in BUNDLE_MODULE_MAP:
            access_svc = get_module_access_service()
            for _mod in BUNDLE_MODULE_MAP[plan]:
                await access_svc.unlock_module(uid, _mod)
            logger.info(
                "Bundle %s: unlocked %d modules for user %s",
                plan, len(BUNDLE_MODULE_MAP[plan]), uid[:8],
            )

        # If checkout metadata contains explicit module list (ara_plus_1 / capivarex_pro)
        modules_csv = meta.get("modules")
        if modules_csv and uid:
            access_svc = get_module_access_service()
            for _mod in modules_csv.split(","):
                _mod = _mod.strip()
                if _mod:
                    await access_svc.unlock_module(uid, _mod)
            logger.info(
                "Metadata modules unlocked for user %s: %s", uid[:8], modules_csv,
            )

    elif event_type == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")

        if customer_id:
            db.table("users").update(
                {
                    "plan": "professional",
                    "messages_limit": PLAN_LIMITS["professional"],
                }
            ).eq("stripe_customer_id", customer_id).execute()
            logger.info(
                f"Billing: customer={customer_id[:16]}"
                f" subscription deleted, reset to professional"
            )

            # Lock all modules tied to this subscription's item IDs
            items = subscription.get("items", {}).get("data", [])
            if items:
                sub_item_ids = [
                    item.get("id") for item in items if item.get("id")
                ]
                if sub_item_ids:
                    try:
                        # Find user_id from customer_id
                        user_row = (
                            db.table("users")
                            .select("id")
                            .eq("stripe_customer_id", customer_id)
                            .limit(1)
                            .execute()
                        )
                        if user_row.data:
                            _uid = user_row.data[0]["id"]
                            access_svc = get_module_access_service()
                            # Lock modules matching these subscription item IDs
                            module_rows = (
                                db.table("user_modules")
                                .select("module_name, stripe_subscription_item_id")
                                .eq("user_id", _uid)
                                .in_("stripe_subscription_item_id", sub_item_ids)
                                .execute()
                            )
                            for row in (module_rows.data or []):
                                await access_svc.lock_module(_uid, row["module_name"])
                            if module_rows.data:
                                logger.info(
                                    "Locked %d modules for user %s on subscription cancel",
                                    len(module_rows.data), _uid[:8],
                                )
                    except Exception as e:
                        logger.warning(
                            "Failed to lock modules on subscription cancel: %s", e
                        )

    elif event_type == "customer.subscription.updated":
        subscription = event["data"]["object"]
        customer_id = subscription.get("customer")
        items = subscription.get("items", {}).get("data", [])
        price_id = items[0].get("price", {}).get("id") if items else None
        plan = _plan_from_price(price_id)
        if customer_id and plan:
            limit = PLAN_LIMITS[plan]
            db.table("users").update(
                {
                    "plan": plan,
                    "messages_limit": limit,
                }
            ).eq("stripe_customer_id", customer_id).execute()
            logger.info(
                f"Billing: customer={customer_id[:16]}"
                f" subscription updated → {plan} (limit={limit})"
            )
            await _notify_admin(
                f"\U0001f504 Plano atualizado: customer={customer_id[:16]} → {plan.upper()}"
            )

    elif event_type == "invoice.payment_succeeded":
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        amount = invoice.get("amount_paid", 0) / 100
        logger.info(f"Billing: payment succeeded customer={customer_id} R${amount:.2f}")
        await _notify_admin(
            f"\u2705 Pagamento confirmado: customer={customer_id} R${amount:.2f}"
        )

    elif event_type == "invoice.payment_failed":
        invoice = event["data"]["object"]
        customer_id = invoice.get("customer")
        logger.warning(f"Billing: payment failed customer={customer_id}")
        await _notify_admin(
            f"\u274c Pagamento falhou: customer={customer_id} \u2014 verificar conta"
        )

    return {"status": "ok"}


# ---------------------------------------------------------------------------
# GET /api/billing/status
# ---------------------------------------------------------------------------


@router.get("/status")
async def billing_status(user_id: str = Depends(verify_webapp_user)):
    """Return current plan, message usage, and quota percentage."""
    db = _get_db()

    try:
        result = (
            db.table("users")
            .select("plan, messages_used, messages_limit")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found")

        user = result.data[0]
        plan = user.get("plan") or "professional"
        used = user.get("messages_used") or 0
        limit = user.get("messages_limit") or PLAN_LIMITS["professional"]
        is_unlimited = limit >= 999999

        if is_unlimited:
            quota_pct = 0.0
        else:
            quota_pct = round((used / limit) * 100, 1) if limit > 0 else 100.0

        logger.info(
            f"Billing status: user={user_id[:8]} plan={plan} used={used}/{limit}"
        )
        return {
            "plan": plan,
            "messages_used": used,
            "messages_limit": limit,
            "quota_pct": quota_pct,
            "is_unlimited": is_unlimited,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "Billing status error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to get billing status")


# ---------------------------------------------------------------------------
# POST /api/billing/portal
# ---------------------------------------------------------------------------


@router.post("/portal")
async def billing_portal(user_id: str = Depends(verify_webapp_user)):
    """Create a Stripe billing portal session for managing subscriptions."""
    stripe.api_key = STRIPE_SECRET_KEY
    db = _get_db()

    try:
        result = (
            db.table("users")
            .select("stripe_customer_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="User not found")

        customer_id = result.data[0].get("stripe_customer_id")
        if not customer_id:
            raise HTTPException(status_code=400, detail="No billing account found")

        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"{FRONTEND_URL}/settings",
        )

        logger.info(f"Billing portal: user={user_id[:8]} session created")
        return {"portal_url": session.url}

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error(
            "Billing portal error: {name}: {msg}",
            name=type(e).__name__,
            msg=str(e),
        )
        raise HTTPException(status_code=500, detail="Failed to create portal session")


# ---------------------------------------------------------------------------
# POST /api/billing/cron/reset-daily  (called by Railway cron or external scheduler)
# ---------------------------------------------------------------------------

CRON_SECRET = os.getenv("CRON_SECRET") or os.getenv("ADMIN_SECRET_TOKEN", "")


@router.post("/cron/reset-daily")
async def reset_daily_usage(request: Request):
    """Reset messages_used to 0 for ALL users.

    Called once per day at midnight by Railway cron job or external scheduler.
    Protected by CRON_SECRET (or ADMIN_SECRET_TOKEN as fallback).

    Railway cron config:
        curl -X POST https://capivarex-production.up.railway.app/api/billing/cron/reset-daily \
             -H "Authorization: Bearer $CRON_SECRET"
    """
    # Auth check
    auth = request.headers.get("authorization", "")
    token = auth.replace("Bearer ", "").strip()
    if not CRON_SECRET or not token or not hmac.compare_digest(token, CRON_SECRET):
        raise HTTPException(status_code=401, detail="Invalid cron token")

    db = _get_db()

    try:
        # Reset messages_used for all users
        result = (
            db.table("users")
            .update({"messages_used": 0})
            .gt("messages_used", 0)  # only update users who actually used messages
            .execute()
        )

        reset_count = len(result.data) if result.data else 0

        logger.info("Cron reset-daily: reset messages_used for {} users", reset_count)

        await _notify_admin(
            f"\U0001f504 Reset diário: {reset_count} users zeraram messages_used"
        )

        return {
            "status": "ok",
            "users_reset": reset_count,
        }

    except Exception as e:
        logger.opt(exception=True).error("Cron reset-daily error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to reset daily usage")


# ===========================================================================
# CAPIVARA MODULE BILLING (added March 2026)
# ===========================================================================


# ---------------------------------------------------------------------------
# GET /api/billing/modules — list all modules with user's access status
# ---------------------------------------------------------------------------
@router.get("/modules")
async def get_user_modules(
    user_id: str = Depends(verify_webapp_user),
):
    """Returns all capivara modules with the user's access status."""
    access_svc = get_module_access_service()
    modules = await access_svc.get_user_modules(user_id)
    return {"modules": modules}


# ---------------------------------------------------------------------------
# POST /api/billing/create-module-checkout — checkout for a module add-on
# ---------------------------------------------------------------------------
class CreateModuleCheckoutRequest(BaseModel):
    module_name: str = Field(..., pattern=r"^(ivi|oka|yara|ayvu|mbae|pora)$")


@router.post("/create-module-checkout")
async def create_module_checkout(
    body: CreateModuleCheckoutRequest,
    request: Request,
    user_id: str = Depends(verify_webapp_user),
):
    """Create a Stripe Checkout session for a capivara module add-on."""
    stripe.api_key = STRIPE_SECRET_KEY
    db = _get_db()

    price_id = MODULE_STRIPE_PRICES.get(body.module_name)
    if not price_id:
        raise HTTPException(
            status_code=400,
            detail=f"Module '{body.module_name}' is not yet available for purchase or price not configured.",
        )

    try:
        user_row = (
            db.table("users")
            .select("email, stripe_customer_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        if not user_row.data:
            raise HTTPException(status_code=404, detail="User not found")
        user = user_row.data[0]
        customer_id = user.get("stripe_customer_id")

        if not customer_id:
            customer = stripe.Customer.create(
                email=user.get("email"),
                metadata={"user_id": user_id},
            )
            customer_id = customer.id
            db.table("users").update(
                {"stripe_customer_id": customer_id}
            ).eq("id", user_id).execute()

        session = stripe.checkout.Session.create(
            customer=customer_id,
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            metadata={"user_id": user_id, "module_name": body.module_name},
            success_url=f"{FRONTEND_URL}/billing/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{FRONTEND_URL}/billing/cancel",
        )
        logger.info(
            "Module checkout: user={} module={} session={}",
            user_id[:8],
            body.module_name,
            session.id[:16],
        )
        return {"checkout_url": session.url}
    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Module checkout error: {}", e)
        raise HTTPException(
            status_code=500,
            detail="Failed to create module checkout session",
        )


# ---------------------------------------------------------------------------
# POST /api/billing/activate-bundle-modules — post-purchase module selection
# ---------------------------------------------------------------------------
# For ARA + 1 and CAPIVAREX Pro bundles, the frontend shows a module picker
# after checkout success. The selected modules are sent here to be unlocked.
# ---------------------------------------------------------------------------

class ActivateBundleModulesRequest(BaseModel):
    modules: list[str] = Field(
        ...,
        description="List of module names to activate (e.g. ['ivi', 'yara'])",
    )


@router.post("/activate-bundle-modules")
async def activate_bundle_modules(
    body: ActivateBundleModulesRequest,
    user_id: str = Depends(verify_webapp_user),
):
    """Activate selected modules after a bundle purchase (ara_plus_1 / capivarex_pro).

    Called by the frontend after the user picks which capivaras to unlock.
    """
    valid_modules = {"ivi", "oka", "yara", "ayvu", "mbae", "pora"}
    invalid = [m for m in body.modules if m not in valid_modules]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid module names: {invalid}. Valid: {sorted(valid_modules)}",
        )

    if not body.modules:
        raise HTTPException(status_code=400, detail="No modules specified")

    access_svc = get_module_access_service()
    unlocked = []
    for module_name in body.modules:
        success = await access_svc.unlock_module(user_id, module_name)
        if success:
            unlocked.append(module_name)

    logger.info(
        "Bundle activation: user=%s unlocked=%s",
        user_id[:8],
        ",".join(unlocked),
    )
    return {"status": "ok", "unlocked": unlocked}

