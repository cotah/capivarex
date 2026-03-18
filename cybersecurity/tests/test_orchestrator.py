"""Tests for the CyberSecurity Orchestrator."""

from __future__ import annotations

import pytest

from cybersecurity.engine.finding import SecurityFinding
from cybersecurity.engine.orchestrator import CyberSecurityOrchestrator, _deduplicate


class TestDeduplication:
    def test_removes_duplicates(self):
        f1 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.8,
            title="XSS",
            file_path="a.py",
            line_number=10,
        )
        f2 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.9,
            title="XSS duplicate",
            file_path="a.py",
            line_number=10,
        )
        result = _deduplicate([f1, f2])
        assert len(result) == 1
        # Keeps higher confidence
        assert result[0].confidence == 0.9

    def test_keeps_different_findings(self):
        f1 = SecurityFinding(
            scanner="test",
            finding_type="xss",
            severity="high",
            confidence=0.8,
            title="XSS",
            file_path="a.py",
            line_number=10,
        )
        f2 = SecurityFinding(
            scanner="test",
            finding_type="sqli",
            severity="critical",
            confidence=0.9,
            title="SQLi",
            file_path="b.py",
            line_number=20,
        )
        result = _deduplicate([f1, f2])
        assert len(result) == 2

    def test_empty_list(self):
        assert _deduplicate([]) == []


class TestOrchestrator:
    @pytest.mark.asyncio
    async def test_initialize(self):
        orch = CyberSecurityOrchestrator()
        await orch.initialize()
        names = orch.get_scanner_names()
        assert "static_analysis" in names
        assert "secret_scanner" in names
        assert "config_auditor" in names
        assert "auth_auditor" in names
        assert "runtime_monitor" in names
        assert "dependency_scanner" in names
        assert len(names) == 6

    @pytest.mark.asyncio
    async def test_trigger_scan_invalid_scanner(self):
        orch = CyberSecurityOrchestrator()
        await orch.initialize()
        with pytest.raises(ValueError, match="not found"):
            await orch.trigger_scan("nonexistent_scanner")

    @pytest.mark.asyncio
    async def test_trigger_scan_valid_scanner(self):
        orch = CyberSecurityOrchestrator()
        await orch.initialize()
        # Config auditor is safe to run without external deps
        findings = await orch.trigger_scan("config_auditor")
        assert isinstance(findings, list)

    @pytest.mark.asyncio
    async def test_overview_without_db(self):
        orch = CyberSecurityOrchestrator()
        await orch.initialize()
        overview = await orch.get_overview()
        assert "total_open" in overview
        assert "scanners" in overview
        assert "is_running" in overview
