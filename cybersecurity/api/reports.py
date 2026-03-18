"""Report endpoints — weekly digest and incident reports."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/reports/weekly")
async def get_weekly_report():
    """Generate or retrieve weekly security digest."""
    try:
        from services import get_service

        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)

    try:
        # Open findings
        open_result = (
            db.client.table("cyber_findings")
            .select("severity")
            .eq("status", "open")
            .execute()
        )

        open_findings = open_result.data or []
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in open_findings:
            sev = f.get("severity", "info")
            counts[sev] = counts.get(sev, 0) + 1

        # Fixed this week
        fixed_result = (
            db.client.table("cyber_findings")
            .select("id")
            .in_("status", ["fixed", "false_positive"])
            .gte("resolved_at", week_ago.isoformat())
            .execute()
        )

        fixed_count = len(fixed_result.data or [])

        # New findings this week
        new_result = (
            db.client.table("cyber_findings")
            .select("title, severity")
            .gte("first_seen", week_ago.isoformat())
            .order("severity")
            .limit(10)
            .execute()
        )

        # Scan runs this week
        scans_result = (
            db.client.table("cyber_scan_runs")
            .select("scanner, status, findings_count")
            .gte("started_at", week_ago.isoformat())
            .execute()
        )

        total_scans = len(scans_result.data or [])

        # Compliance score
        score = 100.0
        score -= counts["critical"] * 15
        score -= counts["high"] * 8
        score -= counts["medium"] * 3
        score -= counts["low"] * 1
        score = max(0.0, min(100.0, score))

        return {
            "period": {
                "start": week_ago.isoformat(),
                "end": now.isoformat(),
            },
            "compliance_score": round(score, 1),
            "total_open": len(open_findings),
            "severity_counts": counts,
            "fixed_this_week": fixed_count,
            "new_findings_this_week": new_result.data or [],
            "total_scans": total_scans,
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate report")


@router.get("/reports/incident/{finding_id}")
async def get_incident_report(finding_id: str):
    """Full incident report for a finding."""
    try:
        from services import get_service

        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        # Get finding detail
        finding_result = (
            db.client.table("cyber_findings")
            .select("*")
            .eq("id", finding_id)
            .limit(1)
            .execute()
        )

        if not finding_result.data:
            raise HTTPException(status_code=404, detail="Finding not found")

        finding = finding_result.data[0]

        # Get related scan runs
        scans_result = (
            db.client.table("cyber_scan_runs")
            .select("*")
            .eq("scanner", finding["scanner"])
            .order("started_at", desc=True)
            .limit(5)
            .execute()
        )

        # Get similar findings (same finding_type)
        similar_result = (
            db.client.table("cyber_findings")
            .select("id, title, severity, status, file_path, first_seen")
            .eq("finding_type", finding["finding_type"])
            .neq("id", finding_id)
            .limit(10)
            .execute()
        )

        return {
            "finding": finding,
            "related_scans": scans_result.data or [],
            "similar_findings": similar_result.data or [],
            "timeline": {
                "first_detected": finding.get("first_seen"),
                "last_seen": finding.get("last_seen"),
                "resolved_at": finding.get("resolved_at"),
            },
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=500, detail="Failed to generate incident report"
        )
