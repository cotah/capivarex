"""Tests for CyberSecurity Intelligence Layer."""

from __future__ import annotations

import pytest
from cybersecurity.engine.finding import SecurityFinding


# ---------------------------------------------------------------------------
# Knowledge Base tests
# ---------------------------------------------------------------------------

class TestKnowledgeBase:
    @pytest.mark.asyncio
    async def test_search_returns_list_without_db(self):
        from cybersecurity.intelligence.knowledge_base import search_similar
        results = await search_similar("test query")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_similar_findings(self):
        from cybersecurity.intelligence.knowledge_base import search_similar_findings
        results = await search_similar_findings("sql injection")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_search_false_positives(self):
        from cybersecurity.intelligence.knowledge_base import search_false_positives
        results = await search_false_positives("test finding")
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_store_finding_without_db(self):
        from cybersecurity.intelligence.knowledge_base import store_finding
        result = await store_finding("Test", "Test content", "low", ["test"])
        # Returns None when DB is not available
        assert result is None

    @pytest.mark.asyncio
    async def test_store_resolution_without_db(self):
        from cybersecurity.intelligence.knowledge_base import store_resolution
        result = await store_resolution("fake-id", "Fixed it", True, "Test finding")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_finding_type_stats_without_db(self):
        from cybersecurity.intelligence.knowledge_base import get_finding_type_stats
        stats = await get_finding_type_stats("test_type")
        assert stats["total"] == 0
        assert "true_positives" in stats
        assert "false_positives" in stats


# ---------------------------------------------------------------------------
# Confidence Scorer tests
# ---------------------------------------------------------------------------

class TestConfidenceScorer:
    @pytest.mark.asyncio
    async def test_score_returns_valid_range(self):
        from cybersecurity.intelligence.confidence_scorer import score_finding
        finding = SecurityFinding(
            scanner="test", finding_type="test", severity="low",
            confidence=0.75, title="test finding",
        )
        score = await score_finding(finding)
        assert 0.0 <= score <= 1.0

    @pytest.mark.asyncio
    async def test_score_returns_base_without_db(self):
        from cybersecurity.intelligence.confidence_scorer import score_finding
        finding = SecurityFinding(
            scanner="test", finding_type="test", severity="low",
            confidence=0.6, title="test finding without db",
        )
        score = await score_finding(finding)
        # Without DB, should return close to base confidence
        assert score == pytest.approx(0.6, abs=0.2)

    @pytest.mark.asyncio
    async def test_auto_fix_not_eligible_without_db(self):
        from cybersecurity.intelligence.confidence_scorer import is_auto_fix_eligible
        result = await is_auto_fix_eligible("test_type")
        assert result is False

    def test_extract_fix_from_content(self):
        from cybersecurity.intelligence.confidence_scorer import _extract_fix_from_content
        content = "Finding: XSS in input\nResolution: Use DOMPurify\nTrue positive: True"
        fix = _extract_fix_from_content(content)
        assert fix == "Use DOMPurify"

    def test_extract_fix_fallback(self):
        from cybersecurity.intelligence.confidence_scorer import _extract_fix_from_content
        fix = _extract_fix_from_content("Some random content without resolution prefix")
        assert len(fix) > 0


# ---------------------------------------------------------------------------
# Pattern Recognition tests
# ---------------------------------------------------------------------------

class TestPatternRecognition:
    @pytest.mark.asyncio
    async def test_detect_regressions_without_db(self):
        from cybersecurity.intelligence.pattern_recognition import detect_regressions
        results = await detect_regressions()
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_detect_escalating_without_db(self):
        from cybersecurity.intelligence.pattern_recognition import detect_escalating_threats
        results = await detect_escalating_threats()
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_detect_correlated_without_db(self):
        from cybersecurity.intelligence.pattern_recognition import detect_correlated_attacks
        results = await detect_correlated_attacks()
        assert isinstance(results, list)

    @pytest.mark.asyncio
    async def test_run_all_detection(self):
        from cybersecurity.intelligence.pattern_recognition import run_all_detection
        result = await run_all_detection()
        assert "regressions" in result
        assert "escalating_threats" in result
        assert "correlated_attacks" in result
        assert "total_patterns" in result

    def test_correlation_rules_structure(self):
        from cybersecurity.intelligence.pattern_recognition import _CORRELATION_RULES
        assert len(_CORRELATION_RULES) >= 4
        for rule in _CORRELATION_RULES:
            assert "name" in rule
            assert "requires" in rule
            assert "severity" in rule
            assert "message" in rule


# ---------------------------------------------------------------------------
# Threat Intelligence tests
# ---------------------------------------------------------------------------

class TestThreatIntel:
    @pytest.mark.asyncio
    async def test_enrich_cve_invalid_id(self):
        from cybersecurity.intelligence.threat_intel import enrich_cve
        result = await enrich_cve("not-a-cve")
        assert result is None

    @pytest.mark.asyncio
    async def test_enrich_cve_empty(self):
        from cybersecurity.intelligence.threat_intel import enrich_cve
        result = await enrich_cve("")
        assert result is None

    @pytest.mark.asyncio
    async def test_advisories_without_token(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        from cybersecurity.intelligence.threat_intel import get_advisories_for_package
        results = await get_advisories_for_package("requests")
        assert results == []

    def test_cvss_to_severity(self):
        from cybersecurity.intelligence.threat_intel import _cvss_to_severity
        assert _cvss_to_severity(9.5) == "critical"
        assert _cvss_to_severity(7.5) == "high"
        assert _cvss_to_severity(5.0) == "medium"
        assert _cvss_to_severity(2.0) == "low"
        assert _cvss_to_severity(None) == "medium"


# ---------------------------------------------------------------------------
# Remediation Engine tests
# ---------------------------------------------------------------------------

class TestRemediationEngine:
    @pytest.mark.asyncio
    async def test_suggest_fix_from_template(self):
        from cybersecurity.intelligence.remediation_engine import suggest_fix
        finding = SecurityFinding(
            scanner="test", finding_type="hardcoded_secret",
            severity="critical", confidence=0.9,
            title="Secret hardcoded",
        )
        fix = await suggest_fix(finding)
        assert fix is not None
        assert "variavel de ambiente" in fix

    @pytest.mark.asyncio
    async def test_suggest_fix_fallback_to_scanner(self):
        from cybersecurity.intelligence.remediation_engine import suggest_fix
        finding = SecurityFinding(
            scanner="test", finding_type="unknown_type_xyz",
            severity="low", confidence=0.5,
            title="Unknown", suggested_fix="Do the thing",
        )
        fix = await suggest_fix(finding)
        assert fix == "Do the thing"

    @pytest.mark.asyncio
    async def test_suggest_fix_sql_injection(self):
        from cybersecurity.intelligence.remediation_engine import suggest_fix
        finding = SecurityFinding(
            scanner="test", finding_type="sql_injection",
            severity="critical", confidence=0.9,
            title="SQLi found",
        )
        fix = await suggest_fix(finding)
        assert fix is not None
        assert "parametrizadas" in fix

    @pytest.mark.asyncio
    async def test_auto_remediate_disabled(self):
        from cybersecurity.intelligence.remediation_engine import auto_remediate
        finding = SecurityFinding(
            scanner="test", finding_type="test",
            severity="high", confidence=0.95,
            title="test",
        )
        result = await auto_remediate(finding)
        assert result is False

    def test_fix_templates_coverage(self):
        from cybersecurity.intelligence.remediation_engine import _FIX_TEMPLATES
        expected_types = [
            "hardcoded_secret", "sql_injection", "command_injection",
            "xss_risk", "vulnerable_dependency", "missing_jwt_secret",
            "cors_wildcard_headers", "env_file_committed", "brute_force_detected",
        ]
        for ftype in expected_types:
            assert ftype in _FIX_TEMPLATES, f"Missing fix template for {ftype}"
