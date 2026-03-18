"""Runtime Monitor — polls security_events table + Sentry for anomalies."""

from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner


class RuntimeMonitorScanner(BaseScanner):
    name = "runtime_monitor"
    schedule = "fast"

    # Thresholds for anomaly detection
    BRUTE_FORCE_THRESHOLD = 10  # auth_failures from same IP in window
    BRUTE_FORCE_WINDOW_MIN = 5  # minutes
    RATE_LIMIT_SPIKE_THRESHOLD = 50  # rate_limit_exceeded events in window
    SUSPICIOUS_THRESHOLD = 3  # suspicious_request events in window

    async def scan(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        findings.extend(await self._check_security_events())
        findings.extend(await self._check_sentry_issues())
        return findings

    # ------------------------------------------------------------------
    # Security Events analysis
    # ------------------------------------------------------------------

    async def _check_security_events(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []

        try:
            from services import get_service

            db = get_service("database")
            if not db or not db.client:
                return findings
        except Exception:
            self.logger.debug(
                "Database service not available — skipping security events check"
            )
            return findings

        now = datetime.now(timezone.utc)
        window_start = (
            now - timedelta(minutes=self.BRUTE_FORCE_WINDOW_MIN)
        ).isoformat()

        try:
            result = (
                db.client.table("security_events")
                .select(
                    "event_type, severity, ip_address, user_id, endpoint, created_at"
                )
                .gte("created_at", window_start)
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            )
            events = result.data or []
        except Exception:
            self.logger.debug("Failed to query security_events")
            return findings

        if not events:
            return findings

        # --- Brute force detection ---
        auth_failures_by_ip: dict[str, list] = defaultdict(list)
        rate_limit_count = 0
        suspicious_count = 0

        for ev in events:
            etype = ev.get("event_type", "")
            ip = ev.get("ip_address", "unknown")

            if etype == "auth_failure":
                auth_failures_by_ip[ip].append(ev)
            elif etype == "rate_limit_exceeded":
                rate_limit_count += 1
            elif etype == "suspicious_request":
                suspicious_count += 1

        # Check brute force per IP
        for ip, failures in auth_failures_by_ip.items():
            if len(failures) >= self.BRUTE_FORCE_THRESHOLD:
                endpoints = {f.get("endpoint", "") for f in failures}
                findings.append(
                    SecurityFinding(
                        scanner=self.name,
                        finding_type="brute_force_detected",
                        severity="critical",
                        confidence=0.9,
                        title=f"Brute force detectado: {len(failures)} falhas de auth do IP {ip}",
                        description=(
                            f"{len(failures)} tentativas de auth falhadas do IP {ip} "
                            f"nos ultimos {self.BRUTE_FORCE_WINDOW_MIN} minutos. "
                            f"Endpoints alvos: {', '.join(endpoints)}"
                        ),
                        evidence={
                            "ip_address": ip,
                            "failure_count": len(failures),
                            "window_minutes": self.BRUTE_FORCE_WINDOW_MIN,
                            "endpoints": list(endpoints),
                        },
                        suggested_fix=f"Bloquear IP {ip} temporariamente e investigar",
                        owasp_category="A07:2021-Identification and Authentication Failures",
                    )
                )

        # Check rate limit spike
        if rate_limit_count >= self.RATE_LIMIT_SPIKE_THRESHOLD:
            findings.append(
                SecurityFinding(
                    scanner=self.name,
                    finding_type="rate_limit_spike",
                    severity="high",
                    confidence=0.8,
                    title=f"Spike de rate limiting: {rate_limit_count} eventos em {self.BRUTE_FORCE_WINDOW_MIN} min",
                    description="Volume anormal de rate limit — possivel DDoS ou abuso de API",
                    evidence={"count": rate_limit_count},
                    owasp_category="A05:2021-Security Misconfiguration",
                )
            )

        # Check suspicious requests
        if suspicious_count >= self.SUSPICIOUS_THRESHOLD:
            findings.append(
                SecurityFinding(
                    scanner=self.name,
                    finding_type="suspicious_activity_spike",
                    severity="high",
                    confidence=0.75,
                    title=f"Atividade suspeita: {suspicious_count} eventos nos ultimos {self.BRUTE_FORCE_WINDOW_MIN} min",
                    evidence={"count": suspicious_count},
                    owasp_category="A09:2021-Security Logging and Monitoring Failures",
                )
            )

        return findings

    # ------------------------------------------------------------------
    # Sentry issues (optional, if token configured)
    # ------------------------------------------------------------------

    async def _check_sentry_issues(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        token = os.getenv("SENTRY_AUTH_TOKEN", "")
        org = os.getenv("SENTRY_ORG", "")
        project = os.getenv("SENTRY_PROJECT", "")

        if not (token and org and project):
            return findings

        try:
            import httpx

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://sentry.io/api/0/projects/{org}/{project}/issues/",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"query": "is:unresolved", "limit": 20},
                )
                if resp.status_code != 200:
                    self.logger.warning("Sentry API returned %d", resp.status_code)
                    return findings

                issues = resp.json()
        except Exception:
            self.logger.debug("Failed to query Sentry API")
            return findings

        for issue in issues:
            title = issue.get("title", "Unknown error")
            count = issue.get("count", "0")
            level = issue.get("level", "error")

            # Map Sentry levels to severity
            sev_map = {
                "fatal": "critical",
                "error": "high",
                "warning": "medium",
                "info": "low",
            }
            severity = sev_map.get(level, "medium")

            # Only report issues with significant occurrence
            try:
                event_count = int(count)
            except (ValueError, TypeError):
                event_count = 1

            if event_count < 3:
                continue

            findings.append(
                SecurityFinding(
                    scanner=self.name,
                    finding_type="sentry_unresolved_issue",
                    severity=severity,
                    confidence=0.6,
                    title=f"Sentry issue nao resolvida: {title}",
                    description=f"Issue com {event_count} ocorrencias. Level: {level}",
                    evidence={
                        "sentry_id": issue.get("id"),
                        "event_count": event_count,
                        "level": level,
                        "first_seen": issue.get("firstSeen"),
                        "last_seen": issue.get("lastSeen"),
                    },
                    owasp_category="A09:2021-Security Logging and Monitoring Failures",
                )
            )

        return findings
