"""Findings endpoints — CRUD for security findings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class FindingUpdate(BaseModel):
    status: str | None = None
    notes: str | None = None


@router.get("/findings")
async def list_findings(
    severity: str | None = Query(None, description="Filter by severity"),
    scanner: str | None = Query(None, description="Filter by scanner"),
    status: str | None = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Paginated list of security findings with filters."""
    try:
        from services import get_service
        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        query = db.client.table("cyber_findings").select(
            "id, scanner, finding_type, severity, confidence, status, title, "
            "file_path, line_number, owasp_category, first_seen, last_seen, cve_id"
        ).order("created_at", desc=True)

        if severity:
            query = query.eq("severity", severity)
        if scanner:
            query = query.eq("scanner", scanner)
        if status:
            query = query.eq("status", status)

        query = query.range(offset, offset + limit - 1)
        result = query.execute()

        return {
            "findings": result.data or [],
            "count": len(result.data or []),
            "offset": offset,
            "limit": limit,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch findings")


@router.get("/findings/{finding_id}")
async def get_finding(finding_id: str):
    """Get full detail of a single finding including evidence."""
    try:
        from services import get_service
        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        result = db.client.table("cyber_findings").select("*").eq(
            "id", finding_id
        ).limit(1).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Finding not found")

        return result.data[0]
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch finding")


@router.patch("/findings/{finding_id}")
async def update_finding(finding_id: str, body: FindingUpdate):
    """Update finding status (acknowledge, mark false positive, etc.)."""
    try:
        from services import get_service
        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    valid_statuses = {"open", "acknowledged", "in_progress", "fixed", "false_positive", "wont_fix"}

    update_data: dict = {}
    if body.status:
        if body.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"Invalid status. Must be one of: {valid_statuses}")
        update_data["status"] = body.status
        if body.status in {"fixed", "false_positive", "wont_fix"}:
            from datetime import datetime, timezone
            update_data["resolved_at"] = datetime.now(timezone.utc).isoformat()

    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    try:
        result = db.client.table("cyber_findings").update(
            update_data
        ).eq("id", finding_id).execute()

        if not result.data:
            raise HTTPException(status_code=404, detail="Finding not found")

        return {"status": "updated", "finding": result.data[0]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to update finding")
