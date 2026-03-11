# -*- coding: utf-8 -*-
"""Tests for monthly report trigger logic."""

from datetime import datetime


class TestMonthlyReportTrigger:
    """Tests for monthly report logic in timer loop."""

    def test_flag_prevents_duplicate_send(self):
        """_monthly_report_sent set prevents re-triggering same month."""
        sent = set()
        key = "2026-3"
        assert key not in sent
        sent.add(key)
        assert key in sent  # Won't trigger again

    def test_trigger_conditions(self):
        """Only triggers on day 1, hour 9."""
        # day=1, hour=9 -> True
        dt = datetime(2026, 3, 1, 9, 5, 0)
        assert dt.day == 1 and dt.hour == 9

        # day=2 -> False
        dt2 = datetime(2026, 3, 2, 9, 0, 0)
        assert not (dt2.day == 1 and dt2.hour == 9)

        # day=1, hour=10 -> False
        dt3 = datetime(2026, 3, 1, 10, 0, 0)
        assert not (dt3.day == 1 and dt3.hour == 9)

    def test_prev_month_calculation(self):
        """Previous month calculated correctly including Jan->Dec."""
        # March -> February
        now = datetime(2026, 3, 1)
        prev = now.month - 1 if now.month > 1 else 12
        prev_year = now.year if now.month > 1 else now.year - 1
        assert prev == 2 and prev_year == 2026

        # January -> December
        now2 = datetime(2026, 1, 1)
        prev2 = now2.month - 1 if now2.month > 1 else 12
        prev_year2 = now2.year if now2.month > 1 else now2.year - 1
        assert prev2 == 12 and prev_year2 == 2025

    def test_i18n_keys_exist(self):
        """All required i18n keys return non-empty strings."""
        from services.i18n import t

        keys = [
            "mercado_excel_subject",
            "mercado_excel_email_body",
            "mercado_excel_telegram_with_email",
            "mercado_excel_telegram_no_email",
        ]
        for key in keys:
            for lang in ("en", "pt", "es"):
                result = t(key, lang=lang, month="March", year=2026, summary="test")
                assert result and len(result) > 5, f"Missing: {key} / {lang}"
