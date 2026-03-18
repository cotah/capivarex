"""Tests for CyberSecurity API endpoints."""

from __future__ import annotations

from cybersecurity.api.dashboard import _score_to_grade


class TestScoreGrade:
    def test_grade_a(self):
        assert _score_to_grade(95) == "A"
        assert _score_to_grade(90) == "A"

    def test_grade_b(self):
        assert _score_to_grade(85) == "B"
        assert _score_to_grade(80) == "B"

    def test_grade_c(self):
        assert _score_to_grade(75) == "C"

    def test_grade_d(self):
        assert _score_to_grade(65) == "D"

    def test_grade_f(self):
        assert _score_to_grade(50) == "F"
        assert _score_to_grade(0) == "F"


class TestSettingsValidation:
    def test_settings_update_model(self):
        from cybersecurity.api.settings import SettingsUpdate

        update = SettingsUpdate(fast_scan_interval=120)
        assert update.fast_scan_interval == 120
        assert update.medium_scan_interval is None

    def test_finding_update_model(self):
        from cybersecurity.api.findings import FindingUpdate

        update = FindingUpdate(status="fixed")
        assert update.status == "fixed"
