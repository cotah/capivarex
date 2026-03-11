# -*- coding: utf-8 -*-
"""
Admin Routes — Protected management endpoints.

All endpoints require ``Depends(get_admin_user)`` — the caller must
have role=admin|superuser **or** plan=everywhere.

Endpoints:
- GET  /api/admin/tenants               → paginated user list with plan/usage
- GET  /api/admin/tenants/{uid}         → single tenant detail
- POST /api/admin/tenants/{uid}/quota   → override message limit
- POST /api/admin/tenants/{uid}/reset-usage → zero daily usage counter
- GET  /api/admin/security-events       → recent security events
- GET  /api/admin/autofix/tickets       → AutoFix tickets with patch status
- GET  /api/admin/health                → health check of all services
"""

from __future__ import annotations

import os
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from api.dependencies.auth import get_admin_user
from api.routes._helpers import _get_db

router = APIRouter(tags=["Admin"])


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class QuotaOverrideRequest(BaseModel):
    messages_limit: int = Field(..., ge=0, description="New daily message limit")


# ---------------------------------------------------------------------------
# GET /api/admin/tenants
# ---------------------------------------------------------------------------


@router.get("/tenants")
async def list_tenants(
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(50, ge=1, le=200, description="Items per page"),
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """List all users with plan, usage, and quota info (paginated)."""
    db = _get_db()

    try:
        offset = (page - 1) * per_page

        # Count total
        count_result = (
            db.table("users")
            .select("id", count="exact")
            .execute()
        )
        total = count_result.count if count_result.count is not None else 0

        # Fetch page
        result = (
            db.table("users")
            .select(
                "id, email, plan, messages_used, messages_limit, "
                "stripe_customer_id, role, created_at"
            )
            .order("created_at", desc=True)
            .range(offset, offset + per_page - 1)
            .execute()
        )

        logger.info(
            "Admin list_tenants: admin={} page={} per_page={} total={}",
            admin.get("id", "?")[:8],
            page,
            per_page,
            total,
        )

        return {
            "tenants": result.data or [],
            "total": total,
            "page": page,
            "per_page": per_page,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Admin list_tenants error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to list tenants")


# ---------------------------------------------------------------------------
# GET /api/admin/tenants/{uid}
# ---------------------------------------------------------------------------


@router.get("/tenants/{uid}")
async def get_tenant(
    uid: str,
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """Get detailed information for a single tenant."""
    db = _get_db()

    try:
        result = (
            db.table("users")
            .select("*")
            .eq("id", uid)
            .limit(1)
            .execute()
        )

        if not result.data:
            raise HTTPException(status_code=404, detail="Tenant not found")

        logger.info(
            "Admin get_tenant: admin={} tenant={}",
            admin.get("id", "?")[:8],
            uid[:8],
        )

        return {"tenant": result.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Admin get_tenant error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to get tenant")


# ---------------------------------------------------------------------------
# POST /api/admin/tenants/{uid}/quota
# ---------------------------------------------------------------------------


@router.post("/tenants/{uid}/quota")
async def override_quota(
    uid: str,
    body: QuotaOverrideRequest,
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """Override a tenant's daily message limit."""
    db = _get_db()

    try:
        # Verify tenant exists
        check = (
            db.table("users")
            .select("id, plan, messages_limit")
            .eq("id", uid)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Tenant not found")

        old_limit = check.data[0].get("messages_limit", 0)

        db.table("users").update({
            "messages_limit": body.messages_limit,
        }).eq("id", uid).execute()

        logger.info(
            "Admin override_quota: admin={} tenant={} {} → {}",
            admin.get("id", "?")[:8],
            uid[:8],
            old_limit,
            body.messages_limit,
        )

        return {
            "status": "ok",
            "uid": uid,
            "old_limit": old_limit,
            "new_limit": body.messages_limit,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Admin override_quota error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to override quota")


# ---------------------------------------------------------------------------
# POST /api/admin/tenants/{uid}/reset-usage
# ---------------------------------------------------------------------------


@router.post("/tenants/{uid}/reset-usage")
async def reset_usage(
    uid: str,
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """Reset a tenant's daily message usage counter to zero."""
    db = _get_db()

    try:
        # Verify tenant exists
        check = (
            db.table("users")
            .select("id, messages_used")
            .eq("id", uid)
            .limit(1)
            .execute()
        )
        if not check.data:
            raise HTTPException(status_code=404, detail="Tenant not found")

        old_used = check.data[0].get("messages_used", 0)

        db.table("users").update({
            "messages_used": 0,
        }).eq("id", uid).execute()

        logger.info(
            "Admin reset_usage: admin={} tenant={} was={}",
            admin.get("id", "?")[:8],
            uid[:8],
            old_used,
        )

        return {
            "status": "ok",
            "uid": uid,
            "old_usage": old_used,
            "new_usage": 0,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.opt(exception=True).error("Admin reset_usage error: {}", e)
        raise HTTPException(status_code=500, detail="Failed to reset usage")


# ---------------------------------------------------------------------------
# GET /api/admin/security-events
# ---------------------------------------------------------------------------


@router.get("/security-events")
async def list_security_events(
    limit: int = Query(50, ge=1, le=500, description="Max events to return"),
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """List recent security events from the security_events table."""
    db = _get_db()

    try:
        result = (
            db.table("security_events")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )

        logger.info(
            "Admin list_security_events: admin={} count={}",
            admin.get("id", "?")[:8],
            len(result.data or []),
        )

        return {"events": result.data or [], "count": len(result.data or [])}

    except Exception as e:
        logger.opt(exception=True).error("Admin security_events error: {}", e)
        raise HTTPException(
            status_code=500, detail="Failed to list security events"
        )


# ---------------------------------------------------------------------------
# GET /api/admin/autofix/tickets
# ---------------------------------------------------------------------------


@router.get("/autofix/tickets")
async def list_autofix_tickets(
    n: int = Query(20, ge=1, le=200, description="Number of tickets to return"),
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """List recent AutoFix tickets with patch status."""
    try:
        from autofix.core import get_last_tickets

        tickets = get_last_tickets(n=n)

        logger.info(
            "Admin list_autofix_tickets: admin={} count={}",
            admin.get("id", "?")[:8],
            len(tickets),
        )

        return {"tickets": tickets, "count": len(tickets)}

    except Exception as e:
        logger.opt(exception=True).error("Admin autofix_tickets error: {}", e)
        raise HTTPException(
            status_code=500, detail="Failed to list autofix tickets"
        )


# ---------------------------------------------------------------------------
# GET /api/admin/health
# ---------------------------------------------------------------------------


@router.get("/health")
async def admin_health(
    admin: Dict[str, Any] = Depends(get_admin_user),
):
    """Health check of all registered services."""
    try:
        from services.core import registry as service_registry
        from agents.core import registry as agent_registry

        # Service health
        service_metrics = {}
        try:
            metrics = service_registry.get_all_metrics()
            for name, m in metrics.items():
                service_metrics[name] = {
                    "status": m.get("status"),
                    "initialized": m.get("initialized"),
                    "call_count": m.get("call_count"),
                    "error_rate": m.get("error_rate"),
                }
        except Exception as e:
            service_metrics["_error"] = str(e)

        # Agent list
        agent_info = {}
        try:
            agents = agent_registry.list_agents()
            agent_info = {"registered": agents, "count": len(agents)}
        except Exception as e:
            agent_info["_error"] = str(e)

        # Environment info
        env_info = {
            "environment": os.getenv("ENVIRONMENT", "development"),
            "railway": bool(os.getenv("RAILWAY_ENVIRONMENT_NAME")),
        }

        logger.info(
            "Admin health: admin={} services={} agents={}",
            admin.get("id", "?")[:8],
            len(service_metrics),
            agent_info.get("count", 0),
        )

        return {
            "status": "healthy",
            "services": service_metrics,
            "agents": agent_info,
            "environment": env_info,
        }

    except Exception as e:
        logger.opt(exception=True).error("Admin health error: {}", e)
        raise HTTPException(
            status_code=500, detail="Failed to check health"
        )
