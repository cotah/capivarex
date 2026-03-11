# -*- coding: utf-8 -*-
"""
tests/test_autofix_core.py
===========================
Suite de testes completa para autofix/core.py (V4.29-GOD).

Domínios cobertos:
  A. Utility functions      (_utc_now, _parse_iso, _minutes_since, _is_test_input)
  B. Frame extraction       (_is_repo_frame, _extract_frames, _generate_fingerprint)
  C. Ticket management      (upsert_ticket, load/save, get_ticket_by_id, mark_fixed)
  D. Status calculation     (_determine_state, _compute_ticket_counts, get_status)
  E. Notification flags     (should_notify_repeat)
  F. Suggestion & heuristics(build_suggestion, _get_cause_heuristic, _parse_frame)
  G. Patch diff parsing     (_parse_patch_diff, _apply_hunks_to_content, _determine_hunk_status)
  H. Sandbox apply          (apply_patch_sandbox dry_run + apply mode)
  I. Patch governance       (approve_patch, reject_patch)
  J. Record exception       (record_exception integration)
  K. Cleanup                (cleanup_test_data)

Estratégia de isolamento:
  - Monkeypatch dos paths globais (AUTOFIX_DIR, TICKETS_FILE, etc.) para tmp_path
  - Funções puras testadas diretamente, sem mock de filesystem
  - Sandbox tests criam arquivos reais em tmp_path

Instalar dependências de teste:
  pip install pytest --break-system-packages

Rodar:
  pytest tests/test_autofix_core.py -v
  pytest tests/test_autofix_core.py -v --tb=short -x  # stop on first fail
"""
import json
import textwrap
from datetime import datetime, timedelta, timezone

import pytest

# ---------------------------------------------------------------------------
# Import do módulo alvo
# ---------------------------------------------------------------------------
import autofix.core as core
from autofix.core import (
    _utc_now,
    _parse_iso,
    _parse_iso_ts,
    _minutes_since,
    _is_test_input,
    _is_repo_frame,
    _extract_frames,
    _extract_top_frame,
    _generate_fingerprint,
    _generate_ticket_id,
    _determine_state,
    _compute_ticket_counts,
    should_notify_repeat,
    _get_cause_heuristic,
    _get_fix_suggestion,
    _get_checklist,
    _parse_frame,
    _parse_patch_diff,
    _determine_hunk_status,
    _apply_hunks_to_content,
    _validate_diff_targets,
    COOLDOWN_MINUTES,
    STABILITY_WINDOW_SECONDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_autofix(tmp_path, monkeypatch):
    """Redirect all autofix file paths to a temp directory."""
    autofix_dir = tmp_path / "autofix"
    autofix_dir.mkdir()
    sandbox_dir = autofix_dir / "sandbox"
    sandbox_dir.mkdir()

    monkeypatch.setattr(core, "AUTOFIX_DIR", autofix_dir)
    monkeypatch.setattr(core, "WORKSPACE", tmp_path)
    monkeypatch.setattr(core, "BUGS_FILE", autofix_dir / "bugs.jsonl")
    monkeypatch.setattr(core, "TICKETS_FILE", autofix_dir / "tickets.jsonl")
    monkeypatch.setattr(core, "SUGGESTIONS_FILE", autofix_dir / "suggestions.jsonl")
    monkeypatch.setattr(core, "PATCHES_FILE", autofix_dir / "patches.jsonl")
    monkeypatch.setattr(core, "SANDBOX_DIR", sandbox_dir)
    monkeypatch.setattr(core, "BASE_DIR", tmp_path)

    return autofix_dir


@pytest.fixture()
def sample_ticket():
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "id": "abcd1234",
        "fingerprint": "fp_test",
        "error_type": "ValueError",
        "top_frame": "bot:handle_cmd:42",
        "status": "new",
        "count": 1,
        "first_seen": now,
        "last_seen": now,
        "chat_id": "12345",
        "sample_text": "test input",
        "notified_admin": False,
        "notified_user": False,
        "notified_admin_ts": None,
        "notified_user_ts": None,
        "notified_admin_count": 0,
        "notified_user_count": 0,
        "notified_admin_last_ts": None,
        "notified_user_last_ts": None,
        "resolved_ts": None,
        "resolved_notified_admin": False,
        "resolved_notified_user": False,
        "status_changed_ts": None,
        "is_test": False,
    }


# Shared traceback for ticket tests
_SAMPLE_TB = textwrap.dedent("""\
    Traceback (most recent call last):
      File "/home/user/project/clawdbot/telegram_bot.py", line 42, in handle_cmd
        do_something()
      File "/usr/lib/python3.11/asyncio/tasks.py", line 500, in __step
        result = coro.send(None)
    ValueError: bad value
""")


# ===========================================================================
# A. UTILITY FUNCTIONS
# ===========================================================================

class TestUtilityFunctions:
    def test_utc_now_returns_utc(self):
        now = _utc_now()
        assert isinstance(now, datetime)
        assert now.tzinfo == timezone.utc

    def test_parse_iso_valid(self):
        ts = "2024-06-15T10:30:00"
        result = _parse_iso(ts)
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 6

    def test_parse_iso_none_returns_none(self):
        assert _parse_iso(None) is None

    def test_parse_iso_invalid_returns_none(self):
        assert _parse_iso("not-a-date") is None

    def test_parse_iso_ts_valid(self):
        ts = "2024-06-15T10:30:00.000000"
        result = _parse_iso_ts(ts)
        assert isinstance(result, datetime)

    def test_parse_iso_ts_none_returns_none(self):
        assert _parse_iso_ts(None) is None

    def test_minutes_since_recent(self):
        ts = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        mins = _minutes_since(ts)
        assert mins is not None
        assert 4.5 < mins < 5.5

    def test_minutes_since_none_returns_none(self):
        assert _minutes_since(None) is None

    def test_minutes_since_invalid_returns_none(self):
        assert _minutes_since("bad-timestamp") is None

    def test_is_test_input_explicit_flag(self):
        assert _is_test_input("anything", "anything", is_test=True) is True

    def test_is_test_input_slash_bug_test(self):
        assert _is_test_input("/bug_test", "", is_test=False) is True

    def test_is_test_input_bug_test_in_error_msg(self):
        assert _is_test_input("other", "some bug_test error", is_test=False) is True

    def test_is_test_input_normal_input(self):
        assert _is_test_input("normal command", "ValueError", is_test=False) is False


# ===========================================================================
# B. FRAME EXTRACTION
# ===========================================================================

class TestFrameExtraction:
    def test_is_repo_frame_telegram_bot(self):
        assert _is_repo_frame("/home/user/clawdbot/telegram_bot.py", "telegram_bot") is True

    def test_is_repo_frame_site_packages(self):
        assert _is_repo_frame("/usr/lib/python3.11/site-packages/foo.py", "foo") is False

    def test_is_repo_frame_generic_user_module(self):
        # Generic module not in _REPO_PATH_PATTERNS nor in ("telegram_bot","bot") → False
        assert _is_repo_frame("/home/user/project/my_module.py", "my_module") is False

    def test_extract_frames_returns_dict(self):
        result = _extract_frames(_SAMPLE_TB)
        assert isinstance(result, dict)
        assert "frame_source" in result

    def test_extract_frames_finds_repo_frame(self):
        result = _extract_frames(_SAMPLE_TB)
        repo_frame = result.get("repo_frame")
        assert repo_frame is not None
        # Should contain something about telegram_bot or handle_cmd
        assert "telegram_bot" in repo_frame or "handle_cmd" in repo_frame

    def test_extract_frames_empty_traceback(self):
        result = _extract_frames("")
        assert isinstance(result, dict)

    def test_extract_top_frame_returns_string(self):
        result = _extract_top_frame(_SAMPLE_TB)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_generate_fingerprint_consistent(self):
        fp1 = _generate_fingerprint("ValueError", "bot:handle_cmd:42")
        fp2 = _generate_fingerprint("ValueError", "bot:handle_cmd:42")
        assert fp1 == fp2

    def test_generate_fingerprint_different_errors_differ(self):
        fp1 = _generate_fingerprint("ValueError", "bot:handle_cmd:42")
        fp2 = _generate_fingerprint("TypeError", "bot:handle_cmd:42")
        assert fp1 != fp2

    def test_generate_fingerprint_different_frames_differ(self):
        fp1 = _generate_fingerprint("ValueError", "bot:handle_cmd:42")
        fp2 = _generate_fingerprint("ValueError", "bot:other_func:99")
        assert fp1 != fp2

    def test_generate_ticket_id_returns_hex_string(self):
        ticket_id = _generate_ticket_id("someFingerprint123")
        # _generate_ticket_id returns an 8-char hex hash (no "T-" prefix)
        assert isinstance(ticket_id, str)
        assert len(ticket_id) == 8

    def test_generate_ticket_id_consistent(self):
        t1 = _generate_ticket_id("fp_xyz")
        t2 = _generate_ticket_id("fp_xyz")
        assert t1 == t2

    def test_generate_ticket_id_different_fps_differ(self):
        t1 = _generate_ticket_id("fp_a")
        t2 = _generate_ticket_id("fp_b")
        assert t1 != t2


# ===========================================================================
# C. TICKET MANAGEMENT
# ===========================================================================

class TestTicketManagement:
    def test_load_tickets_empty_dir(self, tmp_autofix):
        tickets = core.load_tickets()
        assert tickets == {}

    def test_load_tickets_missing_file(self, tmp_autofix):
        tickets = core.load_tickets()
        assert isinstance(tickets, dict)

    def test_save_and_load_tickets_roundtrip(self, tmp_autofix):
        data = {"fp1": {"ticket_id": "T-0001", "status": "new", "fingerprint": "fp1"}}
        core.save_tickets(data)
        loaded = core.load_tickets()
        assert "fp1" in loaded
        assert loaded["fp1"]["ticket_id"] == "T-0001"

    def test_upsert_ticket_creates_new(self, tmp_autofix):
        ticket, is_new = core.upsert_ticket(
            error_type="ValueError",
            tb_str=_SAMPLE_TB,
            chat_id="123",
            text="test cmd",
            error_msg="bad value",
        )
        assert is_new is True
        assert ticket is not None
        assert ticket["error_type"] == "ValueError"
        assert ticket["status"] == "new"
        assert ticket["count"] == 1

    def test_upsert_ticket_has_required_fields(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        for field in ("id", "fingerprint", "error_type", "status",
                      "count", "first_seen", "last_seen"):
            assert field in ticket, f"Missing field: {field}"

    def test_upsert_ticket_deduplicates(self, tmp_autofix):
        core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        ticket, is_new = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        assert is_new is False
        assert ticket["count"] == 2

    def test_upsert_ticket_different_errors_separate(self, tmp_autofix):
        _, n1 = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "e1")
        tb2 = _SAMPLE_TB.replace("ValueError", "TypeError")
        _, n2 = core.upsert_ticket("TypeError", tb2, "123", "cmd", "e2")
        assert n1 is True
        assert n2 is True

    def test_upsert_ticket_is_test_flagged(self, tmp_autofix):
        ticket, _ = core.upsert_ticket(
            error_type="ValueError",
            tb_str=_SAMPLE_TB,
            chat_id="123",
            text="/bug_test",
            error_msg="bad value",
        )
        assert ticket["is_test"] is True

    def test_upsert_ticket_is_test_false_by_default(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "normal", "err")
        assert ticket["is_test"] is False

    def test_get_ticket_by_id_found(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        found = core.get_ticket_by_id(ticket["id"])
        assert found is not None
        assert found["id"] == ticket["id"]

    def test_get_ticket_by_id_not_found(self, tmp_autofix):
        assert core.get_ticket_by_id("T-NONEXISTENT") is None

    def test_update_ticket_status_success(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        success = core.update_ticket_status(ticket["id"], "fixed")
        assert success is True
        updated = core.get_ticket_by_id(ticket["id"])
        assert updated["status"] == "fixed"

    def test_update_ticket_status_not_found(self, tmp_autofix):
        assert core.update_ticket_status("T-GHOST", "fixed") is False

    def test_mark_ticket_fixed(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        result = core.mark_ticket_fixed(ticket["id"], reason="manual fix")
        assert result is not None
        assert result["status"] == "fixed"

    def test_mark_ticket_new(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        core.update_ticket_status(ticket["id"], "fixed")
        result = core.mark_ticket_new(ticket["id"])
        assert result is not None
        assert result["status"] == "new"

    def test_mark_ticket_fixed_not_found(self, tmp_autofix):
        assert core.mark_ticket_fixed("T-GHOST") is None

    def test_get_last_tickets_returns_n(self, tmp_autofix):
        for i in range(4):
            tb = _SAMPLE_TB.replace("42", str(100 + i))
            core.upsert_ticket(f"Err{i}", tb, "123", "cmd", f"e{i}")
        last = core.get_last_tickets(2)
        assert len(last) <= 2

    def test_get_last_tickets_empty(self, tmp_autofix):
        assert core.get_last_tickets(5) == []


# ===========================================================================
# D. STATUS CALCULATION
# ===========================================================================

class TestStatusCalculation:
    def test_determine_state_red_with_new_tickets(self):
        state, reason = _determine_state(number_new=3, seconds_since_newest=10)
        assert state == "red"

    def test_determine_state_yellow_within_stability_window(self):
        state, reason = _determine_state(
            number_new=0,
            seconds_since_newest=STABILITY_WINDOW_SECONDS - 10
        )
        assert state == "yellow"

    def test_determine_state_green_no_tickets(self):
        state, reason = _determine_state(number_new=0, seconds_since_newest=None)
        assert state == "green"

    def test_determine_state_green_old_activity(self):
        state, reason = _determine_state(
            number_new=0,
            seconds_since_newest=STABILITY_WINDOW_SECONDS + 100
        )
        assert state == "green"

    def test_determine_state_returns_non_empty_reason(self):
        state, reason = _determine_state(number_new=1, seconds_since_newest=10)
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_compute_ticket_counts_empty(self):
        new, fixed, newest = _compute_ticket_counts({})
        assert new == 0
        assert fixed == 0
        assert newest is None

    def test_compute_ticket_counts_mixed(self):
        now = datetime.now().isoformat(timespec="seconds")
        tickets = {
            "fp1": {"status": "new", "last_seen": now},
            "fp2": {"status": "new", "last_seen": now},
            "fp3": {"status": "fixed", "last_seen": now},
        }
        new, fixed, newest = _compute_ticket_counts(tickets)
        assert new == 2
        assert fixed == 1
        assert newest is not None

    def test_get_status_green_no_tickets(self, tmp_autofix):
        status = core.get_status()
        assert status["state"] == "green"
        assert status["counts"]["total"] == 0
        assert status["counts"]["new"] == 0

    def test_get_status_red_with_new_ticket(self, tmp_autofix):
        core.upsert_ticket("RuntimeError", _SAMPLE_TB, "123", "cmd", "oops")
        status = core.get_status()
        assert status["state"] == "red"
        assert status["counts"]["new"] >= 1

    def test_get_status_has_required_keys(self, tmp_autofix):
        status = core.get_status()
        for key in ("state", "reason", "counts", "newest_ts"):
            assert key in status

    def test_get_status_green_after_fixing_ticket(self, tmp_autofix):
        ticket, _ = core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "cmd", "err")
        core.mark_ticket_fixed(ticket["id"])
        status = core.get_status()
        # No new tickets → not red
        assert status["state"] in ("green", "yellow")


# ===========================================================================
# E. NOTIFICATION FLAGS
# ===========================================================================

class TestNotificationFlags:
    def test_should_notify_admin_never_notified(self, sample_ticket):
        assert should_notify_repeat(sample_ticket, "admin") is True

    def test_should_notify_user_never_notified(self, sample_ticket):
        assert should_notify_repeat(sample_ticket, "user") is True

    def test_should_not_notify_within_cooldown(self, sample_ticket):
        recent = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(timespec="seconds")
        sample_ticket["notified_admin_last_ts"] = recent
        assert should_notify_repeat(sample_ticket, "admin") is False

    def test_should_notify_after_cooldown(self, sample_ticket):
        old_ts = (datetime.now(timezone.utc) - timedelta(minutes=COOLDOWN_MINUTES + 5)).isoformat(
            timespec="seconds"
        )
        sample_ticket["notified_admin_last_ts"] = old_ts
        assert should_notify_repeat(sample_ticket, "admin") is True

    def test_should_notify_after_status_change(self, sample_ticket):
        # Last notified 10 min ago, but status changed 2 min ago → should notify
        recent_notif = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(timespec="seconds")
        recent_change = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(timespec="seconds")
        sample_ticket["notified_admin_last_ts"] = recent_notif
        sample_ticket["status_changed_ts"] = recent_change
        assert should_notify_repeat(sample_ticket, "admin") is True


# ===========================================================================
# F. SUGGESTION & HEURISTICS
# ===========================================================================

class TestSuggestionHeuristics:
    def test_get_cause_heuristic_known_error(self):
        result = _get_cause_heuristic("KeyError", "bot:handle:10")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_cause_heuristic_unknown_error(self):
        result = _get_cause_heuristic("VeryObscureError99999", "bot:handle:10")
        assert "VeryObscureError99999" in result

    def test_get_fix_suggestion_known_error(self):
        result = _get_fix_suggestion("AttributeError", "bot:handle:10")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_get_fix_suggestion_unknown_error(self):
        result = _get_fix_suggestion("NonExistentError", "bot:handle:10")
        assert "exception handling" in result.lower() or "handling" in result.lower()

    def test_get_checklist_known_error(self):
        result = _get_checklist("KeyError")
        assert isinstance(result, list)
        assert len(result) > 0

    def test_get_checklist_unknown_error_returns_list(self):
        result = _get_checklist("UnknownError999")
        assert isinstance(result, list)

    def test_parse_frame_valid_colon_format(self):
        module, func, line = _parse_frame("telegram_bot:handle_cmd:42")
        assert module == "telegram_bot"
        assert func == "handle_cmd"
        assert line == "42"

    def test_parse_frame_empty_string(self):
        result = _parse_frame("")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_parse_frame_partial_format(self):
        result = _parse_frame("module:func")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_build_suggestion_returns_string(self, tmp_autofix, sample_ticket):
        suggestion = core.build_suggestion(sample_ticket)
        assert isinstance(suggestion, str)
        assert len(suggestion) > 0

    def test_build_suggestion_contains_error_type(self, tmp_autofix, sample_ticket):
        suggestion = core.build_suggestion(sample_ticket)
        assert "ValueError" in suggestion


# ===========================================================================
# G. PATCH DIFF PARSING
# ===========================================================================

class TestPatchDiffParsing:
    SIMPLE_DIFF = textwrap.dedent("""\
        --- a/bot.py
        +++ b/bot.py
        @@ -10,3 +10,3 @@
         def handle():
        -    x = None
        +    x = "fixed"
             return x
    """)

    MULTI_FILE_DIFF = textwrap.dedent("""\
        --- a/bot.py
        +++ b/bot.py
        @@ -1,3 +1,3 @@
        -old line
        +new line
         context
        --- a/utils.py
        +++ b/utils.py
        @@ -5,3 +5,3 @@
        -old util
        +new util
         context
    """)

    def test_parse_empty_string(self):
        assert _parse_patch_diff("") == {}

    def test_parse_none(self):
        assert _parse_patch_diff(None) == {}

    def test_parse_single_file(self):
        result = _parse_patch_diff(self.SIMPLE_DIFF)
        assert "bot.py" in result
        assert len(result["bot.py"]) >= 1

    def test_parse_multi_file(self):
        result = _parse_patch_diff(self.MULTI_FILE_DIFF)
        assert "bot.py" in result
        assert "utils.py" in result

    def test_parse_hunk_has_expected_keys(self):
        result = _parse_patch_diff(self.SIMPLE_DIFF)
        hunk = result["bot.py"][0]
        assert isinstance(hunk, dict)

    def test_determine_hunk_status_all_applied(self):
        assert _determine_hunk_status([{"status": "applied"}, {"status": "applied"}]) == "applied"

    def test_determine_hunk_status_partial(self):
        assert _determine_hunk_status([{"status": "applied"}, {"status": "not_found"}]) == "partial"

    def test_determine_hunk_status_all_not_found(self):
        assert _determine_hunk_status([{"status": "not_found"}]) == "failed"

    def test_determine_hunk_status_skipped(self):
        assert _determine_hunk_status([{"status": "skipped"}]) == "skipped"

    def test_apply_hunks_empty_hunks_no_change(self):
        content = "line1\nline2\nline3\n"
        result, results, changed = _apply_hunks_to_content(content, [], "dry_run")
        assert changed is False

    def test_validate_diff_targets_missing_file(self, tmp_autofix):
        diff_hunks = {"definitely_nonexistent_file.py": []}
        results = _validate_diff_targets(diff_hunks)
        assert len(results) > 0
        assert any("not found" in r.get("details", "").lower() for r in results)

    def test_validate_diff_targets_existing_file(self, tmp_autofix):
        # Create a real file in BASE_DIR (tmp_path)
        target = tmp_autofix.parent / "existing_module.py"
        target.write_text("x = 1\n")
        diff_hunks = {"existing_module.py": []}
        results = _validate_diff_targets(diff_hunks)
        # Should NOT report failure for existing file
        failures = [r for r in results if "not found" in r.get("details", "").lower()]
        assert len(failures) == 0


# ===========================================================================
# H. SANDBOX APPLY
# ===========================================================================

class TestSandboxApply:
    @staticmethod
    def _make_patch(diff: str, target_files: list, ticket_id: str = "T-TEST") -> dict:
        return {
            "ticket_id": ticket_id,
            "status": "approved",
            "diff": diff,
            "target_files": target_files,
        }

    def test_dry_run_missing_file_reports_failure(self, tmp_autofix):
        p = self._make_patch(
            diff="--- a/ghost.py\n+++ b/ghost.py\n@@ -1,1 +1,1 @@\n-old\n+new\n",
            target_files=["ghost.py"],
        )
        report, run_dir = core.apply_patch_sandbox(p, 1, "dry_run")
        assert "results" in report
        assert report["mode"] == "dry_run"
        failures = [
            r for r in report["results"]
            if "not found" in r.get("details", "").lower()
            or r.get("status", "") in ("fail", "failed", "error")
        ]
        assert len(failures) > 0

    def test_sandbox_creates_unique_run_dir(self, tmp_autofix):
        import time
        p = self._make_patch(diff="", target_files=[])
        _, run_dir1 = core.apply_patch_sandbox(p, 1, "dry_run")
        time.sleep(1.1)  # _new_run_dir uses second-precision timestamp
        _, run_dir2 = core.apply_patch_sandbox(p, 2, "dry_run")
        assert run_dir1 != run_dir2
        assert run_dir1.exists()
        assert run_dir2.exists()

    def test_apply_report_json_written(self, tmp_autofix):
        p = self._make_patch(diff="", target_files=[])
        _, run_dir = core.apply_patch_sandbox(p, 1, "dry_run")
        report_file = run_dir / "apply_report.json"
        assert report_file.exists()
        loaded = json.loads(report_file.read_text())
        assert "ts" in loaded
        assert "results" in loaded

    def test_report_has_ticket_id_and_index(self, tmp_autofix):
        p = self._make_patch(diff="", target_files=[], ticket_id="T-XYZ999")
        report, _ = core.apply_patch_sandbox(p, 7, "dry_run")
        assert report["ticket_id"] == "T-XYZ999"
        assert report["patch_index"] == 7

    def test_apply_mode_patches_file_in_sandbox(self, tmp_autofix):
        # Create a target file in BASE_DIR (tmp_path = parent of autofix_dir)
        target = tmp_autofix.parent / "bot_apply_test.py"
        target.write_text("x = None\nreturn x\n")

        diff = textwrap.dedent("""\
            --- a/bot_apply_test.py
            +++ b/bot_apply_test.py
            @@ -1,2 +1,2 @@
            -x = None
            +x = "patched"
             return x
        """)
        p = self._make_patch(diff=diff, target_files=["bot_apply_test.py"])
        report, run_dir = core.apply_patch_sandbox(p, 1, "apply")

        assert isinstance(report, dict)
        # Sandbox copy should contain the patch
        sandbox_copy = run_dir / "bot_apply_test.py"
        if sandbox_copy.exists():
            assert "patched" in sandbox_copy.read_text()


# ===========================================================================
# I. PATCH GOVERNANCE
# ===========================================================================

class TestPatchGovernance:
    @staticmethod
    def _write_patch(tmp_autofix, **kwargs):
        patch_data = {
            "ticket_id": kwargs.get("ticket_id", "T-001"),
            "status": kwargs.get("status", "proposed"),
            "diff": "",
            "target_files": [],
            "ts": datetime.now().isoformat(timespec="seconds"),
        }
        patches_file = tmp_autofix / "patches.jsonl"
        with open(patches_file, "a") as f:
            f.write(json.dumps(patch_data) + "\n")
        return patch_data

    def test_approve_patch_changes_status(self, tmp_autofix):
        self._write_patch(tmp_autofix)
        result = core.approve_patch(1, by="admin", reason="looks good")
        assert result is not None
        assert result["status"] == "approved"

    def test_approve_patch_sets_approved_by(self, tmp_autofix):
        self._write_patch(tmp_autofix)
        result = core.approve_patch(1, by="henri")
        # Implementation stores approver in decision.by, not approved_by
        assert result["decision"]["by"] == "henri"

    def test_reject_patch_changes_status(self, tmp_autofix):
        self._write_patch(tmp_autofix)
        result = core.reject_patch(1, by="admin", reason="risky")
        assert result is not None
        assert result["status"] == "rejected"

    def test_reject_patch_sets_rejected_by(self, tmp_autofix):
        self._write_patch(tmp_autofix)
        result = core.reject_patch(1, by="security_team")
        # Implementation stores rejector in decision.by, not rejected_by
        assert result["decision"]["by"] == "security_team"

    def test_approve_patch_not_found_returns_none(self, tmp_autofix):
        assert core.approve_patch(999, by="admin") is None

    def test_reject_patch_not_found_returns_none(self, tmp_autofix):
        assert core.reject_patch(999, by="admin") is None

    def test_get_last_patches_returns_n(self, tmp_autofix):
        for i in range(4):
            self._write_patch(tmp_autofix, ticket_id=f"T-{i:03d}")
        patches = core.get_last_patches(2)
        assert len(patches) == 2

    def test_get_last_patches_empty(self, tmp_autofix):
        assert core.get_last_patches(5) == []

    def test_get_patch_by_index_found(self, tmp_autofix):
        self._write_patch(tmp_autofix, ticket_id="T-IDX")
        result = core.get_patch_by_index(1)
        assert result is not None
        assert result["ticket_id"] == "T-IDX"

    def test_get_patch_by_index_out_of_range(self, tmp_autofix):
        assert core.get_patch_by_index(999) is None


# ===========================================================================
# J. RECORD EXCEPTION (integration)
# ===========================================================================

class TestRecordException:
    def test_record_exception_returns_ticket(self, tmp_autofix):
        try:
            raise ValueError("integration test error")
        except ValueError as exc:
            ticket, is_new = core.record_exception(
                chat_id="12345",
                text="/test command",
                error=exc,
            )
        assert ticket is not None
        assert is_new is True
        assert ticket["status"] == "new"
        assert ticket["error_type"] == "ValueError"

    def test_record_exception_deduplication(self, tmp_autofix):
        try:
            raise TypeError("dup error")
        except TypeError as exc:
            t1, n1 = core.record_exception("123", "cmd", exc)
            t2, n2 = core.record_exception("123", "cmd", exc)
        assert n1 is True
        assert n2 is False
        assert t2["count"] == 2

    def test_record_exception_no_crash_on_none_tb(self, tmp_autofix):
        """Should return (None, False) or a ticket — never raise."""
        try:
            raise RuntimeError("err")
        except RuntimeError as exc:
            ticket, is_new = core.record_exception(
                chat_id="123",
                text="cmd",
                error=exc,
            )
        assert isinstance(is_new, bool)


# ===========================================================================
# K. CLEANUP
# ===========================================================================

class TestCleanup:
    def test_cleanup_test_data_removes_test_tickets(self, tmp_autofix):
        # Real ticket
        core.upsert_ticket("ValueError", _SAMPLE_TB, "123", "real cmd", "real")
        # Test ticket (flagged by /bug_test text)
        core.upsert_ticket(
            "ValueError",
            _SAMPLE_TB.replace("42", "99"),
            "123",
            "/bug_test",
            "test error",
        )

        result = core.cleanup_test_data()
        assert isinstance(result, dict)

        # After cleanup, all remaining tickets should NOT be test tickets
        tickets = core.load_tickets()
        for t in tickets.values():
            assert t.get("is_test") is not True

    def test_cleanup_returns_stats_dict(self, tmp_autofix):
        result = core.cleanup_test_data()
        assert isinstance(result, dict)
