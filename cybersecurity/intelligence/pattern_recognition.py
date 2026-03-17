"""Pattern Recognition — detects recurring issues and escalating threats.

Analyzes cyber_findings history for:
- Same finding recurring after being fixed (regression)
- Increasing frequency of a finding type (escalating threat)
- Correlated findings (e.g., auth failures + unauthorized access = active attack)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("cybersecurity.pattern_recognition")


def _get_db():
    try:
        from services import get_service
        db = get_service("database")
        if db and db.client:
            return db.client
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Regression detection
# ---------------------------------------------------------------------------


async def detect_regressions() -> list[dict]:
    """Find findings that recur after being marked as fixed.

    A regression is when:
    1. A finding was marked 'fixed'
    2. A new 'open' finding has the same (scanner, finding_type, file_path)
    """
    client = _get_db()
    if not client:
        return []

    try:
        # Get recently fixed findings (last 30 days)
        thirty_days_ago = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        fixed_result = client.table("cyber_findings").select(
            "scanner, finding_type, file_path, title, resolved_at"
        ).eq("status", "fixed").gte("resolved_at", thirty_days_ago).execute()

        if not fixed_result.data:
            return []

        # Get currently open findings
        open_result = client.table("cyber_findings").select(
            "id, scanner, finding_type, file_path, title, first_seen"
        ).eq("status", "open").execute()

        if not open_result.data:
            return []

        # Cross-reference: open findings that match fixed ones
        regressions = []
        fixed_set = {
            (f["scanner"], f["finding_type"], f.get("file_path"))
            for f in fixed_result.data
        }

        for finding in open_result.data:
            key = (finding["scanner"], finding["finding_type"], finding.get("file_path"))
            if key in fixed_set:
                regressions.append({
                    "type": "regression",
                    "finding_id": finding["id"],
                    "title": finding["title"],
                    "scanner": finding["scanner"],
                    "finding_type": finding["finding_type"],
                    "file_path": finding.get("file_path"),
                    "message": f"Regression: '{finding['title']}' foi corrigido mas voltou",
                })

        if regressions:
            logger.warning("Detected %d regressions", len(regressions))

            # Store patterns in knowledge base
            try:
                from cybersecurity.intelligence.knowledge_base import store_pattern
                for reg in regressions[:5]:  # Limit to avoid spam
                    await store_pattern(
                        pattern_title=f"Regression: {reg['title'][:80]}",
                        pattern_description=reg["message"],
                        related_finding_ids=[reg["finding_id"]],
                        severity="high",
                    )
            except Exception:
                pass

        return regressions
    except Exception:
        logger.debug("Failed to detect regressions")
        return []


# ---------------------------------------------------------------------------
# Escalating threats
# ---------------------------------------------------------------------------


async def detect_escalating_threats(window_days: int = 7) -> list[dict]:
    """Find finding types with increasing frequency over time.

    Compares finding count in current window vs previous window.
    If current > 2x previous, it's escalating.
    """
    client = _get_db()
    if not client:
        return []

    try:
        now = datetime.now(timezone.utc)
        current_start = (now - timedelta(days=window_days)).isoformat()
        previous_start = (now - timedelta(days=window_days * 2)).isoformat()

        # Current window
        current_result = client.table("cyber_findings").select(
            "finding_type, first_seen"
        ).gte("first_seen", current_start).execute()

        # Previous window
        previous_result = client.table("cyber_findings").select(
            "finding_type, first_seen"
        ).gte("first_seen", previous_start).lt("first_seen", current_start).execute()

        # Count by type
        current_counts: dict[str, int] = defaultdict(int)
        for f in (current_result.data or []):
            current_counts[f["finding_type"]] += 1

        previous_counts: dict[str, int] = defaultdict(int)
        for f in (previous_result.data or []):
            previous_counts[f["finding_type"]] += 1

        escalating = []
        for ftype, current_count in current_counts.items():
            previous_count = previous_counts.get(ftype, 0)
            if current_count > 2 and (previous_count == 0 or current_count >= previous_count * 2):
                escalating.append({
                    "type": "escalating_threat",
                    "finding_type": ftype,
                    "current_count": current_count,
                    "previous_count": previous_count,
                    "increase_factor": round(current_count / max(previous_count, 1), 1),
                    "message": (
                        f"Escalating: '{ftype}' aumentou de {previous_count} para "
                        f"{current_count} em {window_days} dias"
                    ),
                })

        if escalating:
            logger.warning("Detected %d escalating threats", len(escalating))

        return escalating
    except Exception:
        logger.debug("Failed to detect escalating threats")
        return []


# ---------------------------------------------------------------------------
# Correlated attacks
# ---------------------------------------------------------------------------

# Known attack correlation patterns
_CORRELATION_RULES = [
    {
        "name": "Active brute force attack",
        "requires": ["brute_force_detected", "rate_limit_spike"],
        "severity": "critical",
        "message": "Brute force + rate limit spike indica ataque ativo",
    },
    {
        "name": "Credential stuffing",
        "requires": ["brute_force_detected", "suspicious_activity_spike"],
        "severity": "critical",
        "message": "Brute force + atividade suspeita indica credential stuffing",
    },
    {
        "name": "Reconnaissance + exploitation",
        "requires": ["unprotected_endpoint", "suspicious_activity_spike"],
        "severity": "high",
        "message": "Endpoint desprotegido + atividade suspeita indica tentativa de exploração",
    },
    {
        "name": "Secret leak + unauthorized access",
        "requires": ["hardcoded_secret", "brute_force_detected"],
        "severity": "critical",
        "message": "Secret vazado + brute force indica que credenciais podem ter sido comprometidas",
    },
]


async def detect_correlated_attacks(window_hours: int = 24) -> list[dict]:
    """Find correlated findings that indicate active attacks.

    Uses predefined correlation rules to detect multi-stage attacks.
    """
    client = _get_db()
    if not client:
        return []

    try:
        window_start = (
            datetime.now(timezone.utc) - timedelta(hours=window_hours)
        ).isoformat()

        result = client.table("cyber_findings").select(
            "id, finding_type, title, severity"
        ).eq("status", "open").gte("last_seen", window_start).execute()

        if not result.data:
            return []

        # Collect active finding types
        active_types = {f["finding_type"] for f in result.data}
        finding_ids = {f["finding_type"]: f["id"] for f in result.data}

        correlations = []
        for rule in _CORRELATION_RULES:
            required = set(rule["requires"])
            if required.issubset(active_types):
                related_ids = [finding_ids[t] for t in required if t in finding_ids]
                correlations.append({
                    "type": "correlated_attack",
                    "name": rule["name"],
                    "severity": rule["severity"],
                    "correlated_findings": list(required),
                    "related_finding_ids": related_ids,
                    "message": rule["message"],
                })

        if correlations:
            logger.warning("Detected %d correlated attack patterns", len(correlations))

            # Store in knowledge base
            try:
                from cybersecurity.intelligence.knowledge_base import store_pattern
                for corr in correlations:
                    await store_pattern(
                        pattern_title=corr["name"],
                        pattern_description=corr["message"],
                        related_finding_ids=corr["related_finding_ids"],
                        severity=corr["severity"],
                    )
            except Exception:
                pass

        return correlations
    except Exception:
        logger.debug("Failed to detect correlated attacks")
        return []


# ---------------------------------------------------------------------------
# Run all pattern detection
# ---------------------------------------------------------------------------


async def run_all_detection() -> dict:
    """Run all pattern detection and return results."""
    regressions = await detect_regressions()
    escalating = await detect_escalating_threats()
    correlations = await detect_correlated_attacks()

    total = len(regressions) + len(escalating) + len(correlations)
    if total:
        logger.info(
            "Pattern detection: %d regressions, %d escalating, %d correlations",
            len(regressions), len(escalating), len(correlations),
        )

    return {
        "regressions": regressions,
        "escalating_threats": escalating,
        "correlated_attacks": correlations,
        "total_patterns": total,
    }
