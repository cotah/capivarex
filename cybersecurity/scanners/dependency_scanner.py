"""Dependency Scanner — pip-audit + npm audit wrappers for CVE detection."""

from __future__ import annotations

import json
import subprocess

from cybersecurity.config import BACKEND_ROOT, FRONTEND_ROOT
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.scanners.base_scanner import BaseScanner

# CVSS → severity mapping
_CVSS_SEVERITY = [
    (9.0, "critical"),
    (7.0, "high"),
    (4.0, "medium"),
    (0.0, "low"),
]


def _cvss_to_severity(score: float) -> str:
    for threshold, sev in _CVSS_SEVERITY:
        if score >= threshold:
            return sev
    return "low"


class DependencyScanner(BaseScanner):
    name = "dependency_scanner"
    schedule = "slow"

    async def scan(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        findings.extend(self._scan_pip())
        findings.extend(self._scan_npm())
        return findings

    # ------------------------------------------------------------------
    # Python dependencies (pip-audit)
    # ------------------------------------------------------------------

    def _scan_pip(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        req_file = BACKEND_ROOT / "requirements.txt"
        if not req_file.exists():
            return findings

        try:
            result = subprocess.run(
                [
                    "pip-audit",
                    "--requirement", str(req_file),
                    "--format", "json",
                    "--progress-spinner", "off",
                ],
                capture_output=True, text=True, timeout=120,
                cwd=str(BACKEND_ROOT),
            )
        except FileNotFoundError:
            self.logger.warning("pip-audit not installed — skipping Python dependency scan")
            return findings
        except subprocess.TimeoutExpired:
            self.logger.warning("pip-audit timed out after 120s")
            return findings

        # pip-audit returns exit code 1 when vulnerabilities are found
        output = result.stdout.strip()
        if not output:
            return findings

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse pip-audit JSON output")
            return findings

        dependencies = data.get("dependencies", [])
        for dep in dependencies:
            vulns = dep.get("vulns", [])
            for vuln in vulns:
                vuln_id = vuln.get("id", "UNKNOWN")
                fix_versions = vuln.get("fix_versions", [])
                description = vuln.get("description", "")

                # Determine severity from aliases or default to high
                aliases = vuln.get("aliases", [])
                severity = "high"  # default
                for alias in aliases:
                    if alias.startswith("CVE-"):
                        pass  # Could enrich via NVD API in the future

                fix_str = ", ".join(fix_versions) if fix_versions else "Sem fix disponivel"

                findings.append(SecurityFinding(
                    scanner=self.name,
                    finding_type="vulnerable_dependency",
                    severity=severity,
                    confidence=0.9,
                    title=f"CVE em {dep['name']}=={dep.get('version', '?')}: {vuln_id}",
                    description=description[:500] if description else f"Vulnerabilidade {vuln_id}",
                    file_path="capivarex-backend/requirements.txt",
                    cve_id=vuln_id,
                    suggested_fix=f"Atualizar {dep['name']} para versao: {fix_str}",
                    owasp_category="A06:2021-Vulnerable and Outdated Components",
                    evidence={
                        "package": dep["name"],
                        "installed_version": dep.get("version"),
                        "vuln_id": vuln_id,
                        "fix_versions": fix_versions,
                        "aliases": aliases,
                    },
                ))

        return findings

    # ------------------------------------------------------------------
    # NPM dependencies (npm audit)
    # ------------------------------------------------------------------

    def _scan_npm(self) -> list[SecurityFinding]:
        findings: list[SecurityFinding] = []
        pkg_lock = FRONTEND_ROOT / "package-lock.json"
        if not pkg_lock.exists():
            return findings

        try:
            result = subprocess.run(
                ["npm", "audit", "--json"],
                capture_output=True, text=True, timeout=120,
                cwd=str(FRONTEND_ROOT),
            )
        except FileNotFoundError:
            self.logger.warning("npm not found — skipping NPM dependency scan")
            return findings
        except subprocess.TimeoutExpired:
            self.logger.warning("npm audit timed out after 120s")
            return findings

        output = result.stdout.strip()
        if not output:
            return findings

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse npm audit JSON output")
            return findings

        vulnerabilities = data.get("vulnerabilities", {})
        for pkg_name, info in vulnerabilities.items():
            npm_severity = info.get("severity", "moderate")
            severity_map = {
                "critical": "critical",
                "high": "high",
                "moderate": "medium",
                "low": "low",
                "info": "info",
            }
            severity = severity_map.get(npm_severity, "medium")

            via = info.get("via", [])
            cve_id = None
            description = ""
            for v in via:
                if isinstance(v, dict):
                    cve_id = cve_id or v.get("cve")
                    description = description or v.get("title", "")

            fix_available = info.get("fixAvailable", False)
            fix_str = "npm audit fix" if fix_available else "Sem fix automatico"

            findings.append(SecurityFinding(
                scanner=self.name,
                finding_type="vulnerable_npm_dependency",
                severity=severity,
                confidence=0.9,
                title=f"Vulnerabilidade em {pkg_name}: {description or cve_id or 'sem descricao'}",
                description=f"Pacote npm {pkg_name} com vulnerabilidade {npm_severity}",
                file_path="capivarex-frontend/package.json",
                cve_id=cve_id,
                suggested_fix=fix_str,
                owasp_category="A06:2021-Vulnerable and Outdated Components",
                evidence={
                    "package": pkg_name,
                    "severity": npm_severity,
                    "fix_available": fix_available,
                    "range": info.get("range", ""),
                },
            ))

        return findings
