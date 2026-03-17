"""Scan endpoints — history and manual trigger."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

router = APIRouter()


class ScanTriggerRequest(BaseModel):
    scanner: str


@router.get("/scans")
async def list_scans(
    scanner: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """Scan run history."""
    try:
        from services import get_service
        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        query = db.client.table("cyber_scan_runs").select("*").order(
            "started_at", desc=True
        ).limit(limit)

        if scanner:
            query = query.eq("scanner", scanner)

        result = query.execute()
        return {"scans": result.data or []}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to fetch scans")


@router.post("/scans/trigger")
async def trigger_scan(body: ScanTriggerRequest):
    """Manually trigger a specific scanner."""
    from cybersecurity.main import get_orchestrator

    orch = get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="CyberSecurity bot not running")

    available = orch.get_scanner_names()
    if body.scanner not in available:
        raise HTTPException(
            status_code=400,
            detail=f"Scanner '{body.scanner}' not found. Available: {available}",
        )

    try:
        findings = await orch.trigger_scan(body.scanner)
        return {
            "scanner": body.scanner,
            "findings_count": len(findings),
            "findings": [
                {
                    "title": f.title,
                    "severity": f.severity,
                    "confidence": f.confidence,
                    "file_path": f.file_path,
                }
                for f in findings
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Scan failed: {e}")
