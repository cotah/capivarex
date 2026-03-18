"""Tests for CyberSecurity scanners."""

from __future__ import annotations

import pytest
from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.engine.severity import Severity, FindingStatus


# ---------------------------------------------------------------------------
# Finding tests
# ---------------------------------------------------------------------------


class TestSecurityFinding:
    def test_fingerprint_deterministic(self):
        f1 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.8,
            title="XSS in input",
            file_path="src/app.py",
            line_number=42,
        )
        f2 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.9,
            title="XSS different title",
            file_path="src/app.py",
            line_number=42,
        )
        assert f1.fingerprint == f2.fingerprint

    def test_fingerprint_different_for_different_files(self):
        f1 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.8,
            title="XSS",
            file_path="a.py",
            line_number=1,
        )
        f2 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.8,
            title="XSS",
            file_path="b.py",
            line_number=1,
        )
        assert f1.fingerprint != f2.fingerprint

    def test_to_db_row(self):
        f = SecurityFinding(
            scanner="static_analysis",
            finding_type="sqli",
            severity="critical",
            confidence=0.95,
            title="SQL Injection found",
            file_path="api/routes/auth.py",
            line_number=50,
        )
        row = f.to_db_row()
        assert row["scanner"] == "static_analysis"
        assert row["severity"] == "critical"
        assert row["status"] == "open"
        assert "fingerprint" in row["metadata"]

    def test_code_snippet_truncated(self):
        f = SecurityFinding(
            scanner="test",
            finding_type="test",
            severity="low",
            confidence=0.5,
            title="test",
            code_snippet="x" * 5000,
        )
        row = f.to_db_row()
        assert len(row["code_snippet"]) <= 2000


# ---------------------------------------------------------------------------
# Severity tests
# ---------------------------------------------------------------------------


class TestSeverity:
    def test_ordering(self):
        assert Severity.CRITICAL > Severity.HIGH
        assert Severity.HIGH > Severity.MEDIUM
        assert Severity.MEDIUM > Severity.LOW
        assert Severity.LOW > Severity.INFO

    def test_numeric(self):
        assert Severity.CRITICAL.numeric == 5
        assert Severity.INFO.numeric == 1

    def test_status_values(self):
        assert FindingStatus.OPEN.value == "open"
        assert FindingStatus.FIXED.value == "fixed"
        assert FindingStatus.FALSE_POSITIVE.value == "false_positive"


# ---------------------------------------------------------------------------
# Static Analysis Scanner tests
# ---------------------------------------------------------------------------


class TestStaticAnalysisScanner:
    @pytest.mark.asyncio
    async def test_scan_returns_list(self):
        from cybersecurity.scanners.static_analysis import StaticAnalysisScanner

        scanner = StaticAnalysisScanner()
        findings = await scanner.scan()
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_execute_wraps_scan(self):
        from cybersecurity.scanners.static_analysis import StaticAnalysisScanner

        scanner = StaticAnalysisScanner()
        findings = await scanner.execute()
        assert isinstance(findings, list)
        assert scanner._run_count == 1


# ---------------------------------------------------------------------------
# Secret Scanner tests
# ---------------------------------------------------------------------------


class TestSecretScanner:
    @pytest.mark.asyncio
    async def test_scan_returns_list(self):
        from cybersecurity.scanners.secret_scanner import SecretScanner

        scanner = SecretScanner()
        findings = await scanner.scan()
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# Config Auditor tests
# ---------------------------------------------------------------------------


class TestConfigAuditor:
    @pytest.mark.asyncio
    async def test_scan_returns_list(self):
        from cybersecurity.scanners.config_auditor import ConfigAuditorScanner

        scanner = ConfigAuditorScanner()
        findings = await scanner.scan()
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_detects_missing_jwt(self, monkeypatch):
        monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
        from cybersecurity.scanners.config_auditor import ConfigAuditorScanner

        scanner = ConfigAuditorScanner()
        findings = await scanner.scan()
        jwt_findings = [f for f in findings if f.finding_type == "missing_jwt_secret"]
        assert len(jwt_findings) >= 1


# ---------------------------------------------------------------------------
# Auth Auditor tests
# ---------------------------------------------------------------------------


class TestAuthAuditor:
    @pytest.mark.asyncio
    async def test_scan_returns_list(self):
        from cybersecurity.scanners.auth_auditor import AuthAuditorScanner

        scanner = AuthAuditorScanner()
        findings = await scanner.scan()
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_detects_empty_jwt_secret(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET_KEY", "")
        from cybersecurity.scanners.auth_auditor import AuthAuditorScanner

        scanner = AuthAuditorScanner()
        findings = await scanner.scan()
        jwt_findings = [f for f in findings if "jwt" in f.finding_type.lower()]
        assert len(jwt_findings) >= 1


# ---------------------------------------------------------------------------
# Dependency Scanner tests
# ---------------------------------------------------------------------------


class TestDependencyScanner:
    @pytest.mark.asyncio
    async def test_scan_returns_list(self):
        from cybersecurity.scanners.dependency_scanner import DependencyScanner

        scanner = DependencyScanner()
        findings = await scanner.scan()
        assert isinstance(findings, list)


# ---------------------------------------------------------------------------
# Base Scanner tests
# ---------------------------------------------------------------------------


class TestBaseScanner:
    @pytest.mark.asyncio
    async def test_metrics(self):
        from cybersecurity.scanners.static_analysis import StaticAnalysisScanner

        scanner = StaticAnalysisScanner()
        metrics = scanner.get_metrics()
        assert metrics["name"] == "static_analysis"
        assert metrics["run_count"] == 0

        await scanner.execute()
        metrics = scanner.get_metrics()
        assert metrics["run_count"] == 1
        assert metrics["last_run"] is not None
