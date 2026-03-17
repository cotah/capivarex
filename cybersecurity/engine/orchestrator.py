"""CyberSecurity Orchestrator — the heart of the 24/7 security guardian.

Schedules scanners, deduplicates findings, persists results, and triggers alerts.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

from cybersecurity.config import (
    ALERT_SEVERITIES,
    AUTOFIX_SUGGEST_THRESHOLD,
    FAST_SCAN_INTERVAL,
    MEDIUM_SCAN_INTERVAL,
    SLOW_SCAN_INTERVAL,
)
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner

logger = logging.getLogger("cybersecurity")


class CyberSecurityOrchestrator:
    """Main orchestrator — manages scanner lifecycle and finding pipeline."""

    def __init__(self) -> None:
        self._scanners: dict[str, BaseScanner] = {}
        self._running = False
        self._last_run: dict[str, float] = {}  # scanner_name -> last run monotonic
        self._scan_count = 0

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Register all available scanners."""
        from cybersecurity.scanners.static_analysis import StaticAnalysisScanner
        from cybersecurity.scanners.secret_scanner import SecretScanner
        from cybersecurity.scanners.config_auditor import ConfigAuditorScanner
        from cybersecurity.scanners.dependency_scanner import DependencyScanner
        from cybersecurity.scanners.runtime_monitor import RuntimeMonitorScanner
        from cybersecurity.scanners.auth_auditor import AuthAuditorScanner

        scanners = [
            RuntimeMonitorScanner(),
            AuthAuditorScanner(),
            ConfigAuditorScanner(),
            StaticAnalysisScanner(),
            SecretScanner(),
            DependencyScanner(),
        ]
        for s in scanners:
            self._scanners[s.name] = s
            self._last_run[s.name] = 0.0

        logger.info(
            "CyberSecurity Orchestrator initialized with %d scanners: %s",
            len(self._scanners),
            ", ".join(self._scanners.keys()),
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def run_loop(self) -> None:
        """Main 24/7 loop — runs scanners on schedule."""
        self._running = True
        logger.info("CyberSecurity loop STARTED")

        # Initial full scan on startup
        await self._run_cycle(force_all=True)

        while self._running:
            try:
                await asyncio.sleep(FAST_SCAN_INTERVAL)
                await self._run_cycle()
            except asyncio.CancelledError:
                logger.info("CyberSecurity loop cancelled — shutting down")
                break
            except Exception:
                logger.exception("CyberSecurity loop error — continuing")
                await asyncio.sleep(30)

        self._running = False
        logger.info("CyberSecurity loop STOPPED")

    def stop(self) -> None:
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Cycle execution
    # ------------------------------------------------------------------

    async def _run_cycle(self, force_all: bool = False) -> None:
        """Run one scan cycle — executes scanners that are due."""
        self._scan_count += 1
        now = time.monotonic()
        scanners_to_run: list[BaseScanner] = []

        for name, scanner in self._scanners.items():
            interval = _get_interval(scanner.schedule)
            elapsed = now - self._last_run[name]
            if force_all or elapsed >= interval:
                scanners_to_run.append(scanner)

        if not scanners_to_run:
            return

        logger.info(
            "Cycle #%d — running %d scanners: %s",
            self._scan_count,
            len(scanners_to_run),
            ", ".join(s.name for s in scanners_to_run),
        )

        all_findings: list[SecurityFinding] = []

        for scanner in scanners_to_run:
            self._last_run[scanner.name] = now
            scan_run_id = await self._record_scan_start(scanner.name)

            t0 = time.monotonic()
            findings = await scanner.execute()
            duration_ms = int((time.monotonic() - t0) * 1000)

            all_findings.extend(findings)
            await self._record_scan_end(scan_run_id, scanner.name, findings, duration_ms)

        if all_findings:
            # Deduplicate
            unique = _deduplicate(all_findings)
            logger.info(
                "Cycle #%d — %d findings (%d unique after dedup)",
                self._scan_count, len(all_findings), len(unique),
            )

            # Persist and alert
            await self._process_findings(unique)
        else:
            logger.info("Cycle #%d — no findings", self._scan_count)

    # ------------------------------------------------------------------
    # Triggered scan (manual or webhook)
    # ------------------------------------------------------------------

    async def trigger_scan(self, scanner_name: str) -> list[SecurityFinding]:
        """Manually trigger a specific scanner."""
        scanner = self._scanners.get(scanner_name)
        if not scanner:
            raise ValueError(f"Scanner '{scanner_name}' not found")

        scan_run_id = await self._record_scan_start(scanner_name, scan_type="manual")
        t0 = time.monotonic()
        findings = await scanner.execute()
        duration_ms = int((time.monotonic() - t0) * 1000)

        await self._record_scan_end(scan_run_id, scanner_name, findings, duration_ms)

        if findings:
            unique = _deduplicate(findings)
            await self._process_findings(unique)

        return findings

    # ------------------------------------------------------------------
    # Finding pipeline
    # ------------------------------------------------------------------

    async def _process_findings(self, findings: list[SecurityFinding]) -> None:
        """Persist findings, send alerts, create autofix tickets."""
        for finding in findings:
            # 1. Persist to database
            _db_id = await self._upsert_finding(finding)

            # 2. Alert on high/critical
            if finding.severity in ALERT_SEVERITIES:
                try:
                    from cybersecurity.integrations.notification_bridge import alert_finding
                    await alert_finding(finding)
                except Exception:
                    logger.debug("Failed to send alert for finding")

            # 3. Create autofix ticket for high-confidence findings
            if finding.confidence >= AUTOFIX_SUGGEST_THRESHOLD and finding.severity in {"high", "critical"}:
                try:
                    from cybersecurity.integrations.autofix_bridge import create_ticket_from_finding
                    await create_ticket_from_finding(finding)
                except Exception:
                    logger.debug("Failed to create autofix ticket")

    async def _upsert_finding(self, finding: SecurityFinding) -> str | None:
        """Insert or update finding in cyber_findings table."""
        try:
            from services import get_service
            db = get_service("database")
            if not db or not db.client:
                return None
        except Exception:
            return None

        fingerprint = finding.fingerprint

        try:
            # Check if finding already exists
            existing = (
                db.client.table("cyber_findings")
                .select("id, first_seen")
                .eq("metadata->>fingerprint", fingerprint)
                .eq("status", "open")
                .limit(1)
                .execute()
            )

            row = finding.to_db_row()

            if existing.data:
                # Update existing — bump last_seen, update confidence
                record = existing.data[0]
                db.client.table("cyber_findings").update({
                    "last_seen": row["last_seen"],
                    "confidence": max(row["confidence"], 0),  # Don't decrease
                    "evidence": row["evidence"],
                }).eq("id", record["id"]).execute()
                return record["id"]
            else:
                # Insert new finding
                result = db.client.table("cyber_findings").insert(row).execute()
                if result.data:
                    return result.data[0].get("id")
        except Exception:
            logger.debug("Failed to upsert finding: %s", finding.title[:60])

        return None

    # ------------------------------------------------------------------
    # Scan run tracking
    # ------------------------------------------------------------------

    async def _record_scan_start(
        self, scanner_name: str, scan_type: str = "scheduled",
    ) -> str | None:
        try:
            from services import get_service
            db = get_service("database")
            if not db or not db.client:
                return None

            result = db.client.table("cyber_scan_runs").insert({
                "scanner": scanner_name,
                "scan_type": scan_type,
                "status": "running",
            }).execute()

            if result.data:
                return result.data[0].get("id")
        except Exception:
            pass
        return None

    async def _record_scan_end(
        self,
        scan_run_id: str | None,
        scanner_name: str,
        findings: list[SecurityFinding],
        duration_ms: int,
    ) -> None:
        if not scan_run_id:
            return
        try:
            from services import get_service
            db = get_service("database")
            if not db or not db.client:
                return

            db.client.table("cyber_scan_runs").update({
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "findings_count": len(findings),
                "new_findings": len(findings),  # Dedup happens later
                "duration_ms": duration_ms,
            }).eq("id", scan_run_id).execute()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Dashboard data
    # ------------------------------------------------------------------

    async def get_overview(self) -> dict:
        """Get dashboard overview data."""
        try:
            from services import get_service
            db = get_service("database")
            if not db or not db.client:
                return self._empty_overview()
        except Exception:
            return self._empty_overview()

        try:
            # Open findings by severity
            result = db.client.table("cyber_findings").select(
                "severity, status"
            ).eq("status", "open").execute()

            findings = result.data or []
            severity_counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
            for f in findings:
                sev = f.get("severity", "info")
                severity_counts[sev] = severity_counts.get(sev, 0) + 1

            # Last scan runs
            scans = db.client.table("cyber_scan_runs").select(
                "scanner, status, started_at, duration_ms, findings_count"
            ).order("started_at", desc=True).limit(20).execute()

            return {
                "total_open": len(findings),
                "severity_counts": severity_counts,
                "scanners": {s.name: s.get_metrics() for s in self._scanners.values()},
                "recent_scans": scans.data or [],
                "cycle_count": self._scan_count,
                "is_running": self._running,
            }
        except Exception:
            return self._empty_overview()

    def _empty_overview(self) -> dict:
        return {
            "total_open": 0,
            "severity_counts": {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0},
            "scanners": {s.name: s.get_metrics() for s in self._scanners.values()},
            "recent_scans": [],
            "cycle_count": self._scan_count,
            "is_running": self._running,
        }

    def get_scanner_names(self) -> list[str]:
        return list(self._scanners.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_interval(schedule: str) -> float:
    return {
        "fast": FAST_SCAN_INTERVAL,
        "medium": MEDIUM_SCAN_INTERVAL,
        "slow": SLOW_SCAN_INTERVAL,
        "triggered": float("inf"),  # Never auto-runs
    }.get(schedule, MEDIUM_SCAN_INTERVAL)


def _deduplicate(findings: list[SecurityFinding]) -> list[SecurityFinding]:
    """Deduplicate findings by fingerprint, keeping highest confidence."""
    seen: dict[str, SecurityFinding] = {}
    for f in findings:
        fp = f.fingerprint
        if fp not in seen or f.confidence > seen[fp].confidence:
            seen[fp] = f
    return list(seen.values())
