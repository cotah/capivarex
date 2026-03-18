"""Dashboard endpoints — overview, compliance score, trends."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/overview")
async def get_overview():
    """Dashboard summary: open findings by severity, scanner metrics, recent scans."""
    from cybersecurity.main import get_orchestrator

    orch = get_orchestrator()
    if not orch:
        raise HTTPException(status_code=503, detail="CyberSecurity bot not running")

    return await orch.get_overview()


@router.get("/score")
async def get_compliance_score():
    """Current compliance score with category breakdown."""
    try:
        from services import get_service

        db = get_service("database")
        if not db or not db.client:
            raise HTTPException(status_code=503, detail="Database not available")
    except Exception:
        raise HTTPException(status_code=503, detail="Database not available")

    try:
        # Get open findings
        result = (
            db.client.table("cyber_findings")
            .select("severity")
            .eq("status", "open")
            .execute()
        )

        findings = result.data or []
        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
        for f in findings:
            sev = f.get("severity", "info")
            counts[sev] = counts.get(sev, 0) + 1

        # Calculate score: start at 100, deduct per finding
        score = 100.0
        score -= counts["critical"] * 15
        score -= counts["high"] * 8
        score -= counts["medium"] * 3
        score -= counts["low"] * 1
        score = max(0.0, min(100.0, score))

        return {
            "overall_score": round(score, 1),
            "total_open": len(findings),
            "severity_counts": counts,
            "grade": _score_to_grade(score),
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to calculate score")


@router.get("/score/history")
async def get_score_history(days: int = 30):
    """Daily compliance scores for trend charts."""
    try:
        from services import get_service

        db = get_service("database")
        if not db or not db.client:
            return {"history": []}
    except Exception:
        return {"history": []}

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    try:
        result = (
            db.client.table("cyber_compliance_scores")
            .select(
                "score_date, overall_score, critical_count, high_count, medium_count, low_count"
            )
            .gte("score_date", since)
            .order("score_date")
            .execute()
        )

        return {"history": result.data or []}
    except Exception:
        return {"history": []}


def _score_to_grade(score: float) -> str:
    if score >= 90:
        return "A"
    if score >= 80:
        return "B"
    if score >= 70:
        return "C"
    if score >= 60:
        return "D"
    return "F"
