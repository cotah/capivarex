# -*- coding: utf-8 -*-
"""
UNBX-BOT Autofix Core Module V4.29-GOD
Channel-agnostic triage, bug capture, and autofix logic.

This module contains all the core logic for:
- Bug/exception recording
- Ticket management
- Suggestion generation
- Patch generation and governance
- Sandbox apply
- Status calculation

Telegram, Web, API, and CLI channels should import from this module.
"""

import re
import json
import logging
import hashlib
import traceback
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

# ============================================================
# LOGGING
# ============================================================

logger = logging.getLogger("autofix.core")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s"))
    logger.addHandler(handler)

# ============================================================
# CONSTANTS
# ============================================================

BOT_VERSION = "4.29-GOD"
DEFAULT_ENCODING = "utf-8"

# Paths - workspace/autofix/
BASE_DIR = Path(__file__).parent.parent.resolve()
WORKSPACE = BASE_DIR / "workspace"
AUTOFIX_DIR = WORKSPACE / "autofix"
BUGS_FILE = AUTOFIX_DIR / "bugs.jsonl"
TICKETS_FILE = AUTOFIX_DIR / "tickets.jsonl"
SUGGESTIONS_FILE = AUTOFIX_DIR / "suggestions.jsonl"
PATCHES_FILE = AUTOFIX_DIR / "patches.jsonl"
SANDBOX_DIR = AUTOFIX_DIR / "sandbox"

# Timing constants
COOLDOWN_MINUTES = 30
ACTIVE_WINDOW_MINUTES = 60
STABLE_TO_GREEN_MINUTES = 30
STABILITY_WINDOW_SECONDS = 600
ISO_FMT = "%Y-%m-%dT%H:%M:%S"


# ============================================================
# SUPABASE HELPER
# ============================================================


def _get_supabase_client():
    """Get the Supabase client for ticket persistence. Returns None on failure."""
    try:
        from services import get_service

        db = get_service("database")
        if db and db.is_initialized():
            return db.get_client()
    except Exception:
        pass
    return None


# ============================================================
# UTILITY FUNCTIONS
# ============================================================


def _ensure_autofix_dir():
    """Ensures workspace/autofix/ exists."""
    AUTOFIX_DIR.mkdir(parents=True, exist_ok=True)


def _utc_now() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware datetime.

    Handles trailing ``Z``, missing timezone info, and falls back to
    ``ISO_FMT`` when ``fromisoformat`` fails.  Returns *None* on
    unparseable input.
    """
    if not ts:
        return None
    if isinstance(ts, str) and ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        try:
            dt = datetime.strptime(ts, ISO_FMT)
        except Exception:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_iso_ts(ts: str | None) -> datetime | None:
    """Alias for ``_parse_iso`` kept for backward compatibility."""
    return _parse_iso(ts)


def _minutes_since(ts: str | None) -> float | None:
    """Return the number of minutes elapsed since the given ISO timestamp."""
    dt = _parse_iso_ts(ts)
    if not dt:
        return None
    return (_utc_now() - dt).total_seconds() / 60.0


def _backup_jsonl(path: Path) -> Path | None:
    """Create a timestamped backup copy of a JSONL file. Returns the backup path or None."""
    if not path.exists():
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_name(f"{path.name}.bak_{ts}")
    shutil.copy2(path, backup)
    return backup


# ============================================================
# FRAME EXTRACTION
# ============================================================

_REPO_PATH_PATTERNS = [
    "clawdbot\\telegram_bot.py",
    "clawdbot/telegram_bot.py",
    "clawdbot\\bot.py",
    "clawdbot/bot.py",
]


def _is_repo_frame(filepath: str, module_name: str) -> bool:
    """Determines if a traceback frame belongs to the project repo."""
    for pattern_check in _REPO_PATH_PATTERNS:
        if pattern_check in filepath:
            return True
    if module_name in ("telegram_bot", "bot"):
        return "site-packages" not in filepath and "_bot" not in filepath
    return False


def _build_frame_result(repo_frames: list, lib_frame: str | None) -> dict:
    """Builds the frame extraction result dict."""
    repo_frame = repo_frames[-1] if repo_frames else None
    if repo_frame:
        frame_source = "repo"
    elif lib_frame:
        frame_source = "lib"
    else:
        frame_source = "unknown"
    return {
        "repo_frame": repo_frame,
        "lib_frame": lib_frame,
        "frame_source": frame_source,
    }


def _extract_frames(tb_str: str) -> dict:
    """
    Extracts frames from traceback with priority for repo code.
    Returns dict with:
      - repo_frame: first frame from telegram_bot.py or bot.py (str|None)
      - lib_frame: last frame (fallback, may be site-packages) (str|None)
      - frame_source: "repo" or "lib" indicating which was used
    """
    pattern = r'File "([^"]+)", line (\d+), in (\w+)'
    matches = re.findall(pattern, tb_str)

    if not matches:
        return _build_frame_result([], None)

    repo_frames = []
    lib_frame = None

    for filepath, line_num, func_name in matches:
        module_name = Path(filepath).stem
        frame_str = f"{module_name}:{func_name}:{line_num}"

        if _is_repo_frame(filepath, module_name):
            repo_frames.append(frame_str)

        lib_frame = frame_str

    return _build_frame_result(repo_frames, lib_frame)


def _extract_top_frame(tb_str: str) -> str:
    """
    Extracts the last 'File ... line ... in ...' line from traceback.
    Returns format: module:function:line
    """
    frames = _extract_frames(tb_str)
    return frames.get("repo_frame") or frames.get("lib_frame") or "unknown:unknown:0"


def _generate_fingerprint(error_type: str, top_frame: str) -> str:
    """Generates fingerprint based on error_type + top_frame."""
    return f"{error_type}|{top_frame}"


def _generate_ticket_id(fingerprint: str) -> str:
    """Generates short ID (8 chars) based on fingerprint hash."""
    return hashlib.md5(fingerprint.encode()).hexdigest()[:8]


# ============================================================
# TICKET MANAGEMENT
# ============================================================


def _load_tickets_from_jsonl() -> dict:
    """Loads tickets from local JSONL file (fallback source)."""
    tickets = {}
    if not TICKETS_FILE.exists():
        return tickets
    try:
        with open(TICKETS_FILE, "r", encoding=DEFAULT_ENCODING) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ticket = json.loads(line)
                    fp = ticket.get("fingerprint")
                    if fp:
                        tickets[fp] = ticket
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error loading tickets from JSONL: {e}")
    return tickets


def load_tickets() -> dict:
    """
    Loads all tickets into a dict indexed by fingerprint.
    Primary source: Supabase. Fallback: local JSONL.
    Returns: {fingerprint: ticket_dict, ...}
    """
    # Try Supabase first (survives deploys)
    try:
        client = _get_supabase_client()
        if client:
            result = (
                client.table("autofix_tickets")
                .select("*")
                .order("last_seen", desc=True)
                .limit(500)
                .execute()
            )
            if result.data:
                tickets = {}
                for row in result.data:
                    fp = row.get("fingerprint")
                    if fp:
                        tickets[fp] = row
                return tickets
    except Exception as e:
        logger.warning(f"Supabase ticket load failed, falling back to JSONL: {e}")

    # Fallback: local JSONL
    return _load_tickets_from_jsonl()


def save_tickets(tickets: dict):
    """
    Saves all tickets (rewrites the complete file + syncs to Supabase).
    tickets: {fingerprint: ticket_dict, ...}
    """
    # 1. Write to local JSONL (fallback)
    _ensure_autofix_dir()
    try:
        with open(TICKETS_FILE, "w", encoding=DEFAULT_ENCODING) as f:
            for ticket in tickets.values():
                f.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Error saving tickets to JSONL: {e}")

    # 2. Persist to Supabase (survives deploys)
    try:
        client = _get_supabase_client()
        if client:
            now = _utc_now().isoformat()
            for ticket in tickets.values():
                row = {
                    "id": ticket.get("id", ""),
                    "fingerprint": ticket.get("fingerprint", ""),
                    "error_type": ticket.get("error_type", ""),
                    "top_frame": ticket.get("top_frame", ""),
                    "status": ticket.get("status", "new"),
                    "count": ticket.get("count", 1),
                    "first_seen": ticket.get("first_seen", now),
                    "last_seen": ticket.get("last_seen", now),
                    "tenant_id": ticket.get("tenant_id") or "",
                    "user_id": ticket.get("user_id") or "",
                    "sample_text": ticket.get("sample_text", ""),
                    "last_chat_id": ticket.get("last_chat_id", ""),
                    "last_error_msg": ticket.get("last_error_msg", ""),
                    "is_test": ticket.get("is_test", False),
                    "repo_frame": ticket.get("repo_frame") or "",
                    "lib_frame": ticket.get("lib_frame") or "",
                    "frame_source": ticket.get("frame_source", "unknown"),
                    "updated_at": now,
                }
                client.table("autofix_tickets").upsert(row, on_conflict="id").execute()
    except Exception as e:
        logger.warning(f"AutoFix: failed to persist tickets to Supabase: {e}")


def _is_test_input(text: str, error_msg: str, is_test: bool) -> bool:
    """Determines if input should be flagged as a test."""
    if is_test:
        return True
    if text == "/bug_test":
        return True
    return bool(error_msg and "bug_test" in error_msg)


_NOTIFICATION_DEFAULTS = {
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
}


def _update_existing_ticket(
    ticket: dict,
    now: str,
    chat_id: str,
    error_msg: str,
    text: str,
    is_test: bool,
    repo_frame,
    lib_frame,
    frame_source: str,
) -> None:
    """Updates an existing ticket in-place with new occurrence data."""
    for key, default in _NOTIFICATION_DEFAULTS.items():
        ticket.setdefault(key, default)
    ticket["count"] = ticket.get("count", 1) + 1
    ticket["last_seen"] = now
    ticket["last_chat_id"] = chat_id
    ticket["last_error_msg"] = error_msg[:200] if error_msg else ""
    if _is_test_input(text, error_msg, is_test):
        ticket["is_test"] = True
    ticket["repo_frame"] = repo_frame
    ticket["lib_frame"] = lib_frame
    ticket["frame_source"] = frame_source


def _create_new_ticket(
    ticket_id: str,
    fingerprint: str,
    error_type: str,
    top_frame: str,
    repo_frame,
    lib_frame,
    frame_source: str,
    now: str,
    tenant_id: str,
    user_id: str,
    sample_text: str,
    chat_id: str,
    error_msg: str,
    text: str,
    is_test: bool,
) -> dict:
    """Creates a new ticket dict with all required fields."""
    return {
        "id": ticket_id,
        "fingerprint": fingerprint,
        "error_type": error_type,
        "top_frame": top_frame,
        "repo_frame": repo_frame,
        "lib_frame": lib_frame,
        "frame_source": frame_source,
        "count": 1,
        "first_seen": now,
        "last_seen": now,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "sample_text": sample_text,
        "status": "new",
        "last_chat_id": chat_id,
        "last_error_msg": error_msg[:200] if error_msg else "",
        "is_test": _is_test_input(text, error_msg, is_test),
        **_NOTIFICATION_DEFAULTS,
    }


def upsert_ticket(
    error_type: str,
    tb_str: str,
    chat_id: str,
    text: str,
    error_msg: str,
    tenant_id: str = None,
    user_id: str = None,
    is_test: bool = False,
) -> Tuple[Optional[dict], bool]:
    """
    Creates or updates ticket based on fingerprint.
    If exists, increments count and updates last_seen.
    Returns (ticket, is_new).
    """
    try:
        frames = _extract_frames(tb_str)
        repo_frame = frames.get("repo_frame")
        lib_frame = frames.get("lib_frame")
        frame_source = frames.get("frame_source", "unknown")

        top_frame = repo_frame or lib_frame or "unknown:unknown:0"
        fingerprint = _generate_fingerprint(error_type, top_frame)
        ticket_id = _generate_ticket_id(fingerprint)
        now = datetime.now().isoformat(timespec="seconds")
        sample_text = text[:80] if text else ""

        tickets = load_tickets()

        if fingerprint in tickets:
            ticket = tickets[fingerprint]
            _update_existing_ticket(
                ticket,
                now,
                chat_id,
                error_msg,
                text,
                is_test,
                repo_frame,
                lib_frame,
                frame_source,
            )
            is_new = False
        else:
            ticket = _create_new_ticket(
                ticket_id,
                fingerprint,
                error_type,
                top_frame,
                repo_frame,
                lib_frame,
                frame_source,
                now,
                tenant_id,
                user_id,
                sample_text,
                chat_id,
                error_msg,
                text,
                is_test,
            )
            tickets[fingerprint] = ticket
            is_new = True

        save_tickets(tickets)
        logger.info(
            f"Ticket upsert: {ticket_id} frame_source={frame_source} (count={tickets[fingerprint]['count']})"
        )
        return ticket, is_new

    except Exception as e:
        logger.error(f"Error creating/updating ticket: {e}")
        return None, False


def get_ticket_by_id(ticket_id: str) -> dict | None:
    """Gets ticket by ID (8 chars)."""
    tickets = load_tickets()
    for ticket in tickets.values():
        if ticket.get("id") == ticket_id:
            return ticket
    return None


def update_ticket_status(ticket_id: str, status: str) -> bool:
    """Updates ticket status. Returns True if found."""
    tickets = load_tickets()
    for fp, ticket in tickets.items():
        if ticket.get("id") == ticket_id:
            current_status = ticket.get("status")
            if status != current_status:
                now = _utc_now().replace(microsecond=0).isoformat()
                ticket["status_changed_ts"] = now
                if status == "fixed":
                    ticket["resolved_ts"] = now
                ticket["status"] = status
            save_tickets(tickets)

            # Sync status change to Supabase
            try:
                client = _get_supabase_client()
                if client:
                    update_data = {
                        "status": status,
                        "updated_at": _utc_now().isoformat(),
                    }
                    if status == "fixed":
                        update_data["resolved_ts"] = _utc_now().isoformat()
                    client.table("autofix_tickets").update(update_data).eq(
                        "id", ticket_id
                    ).execute()
            except Exception as e:
                logger.warning(
                    "AutoFix: failed to update ticket %s in Supabase: %s",
                    ticket_id,
                    e,
                )

            return True
    return False


def get_last_tickets(n: int = 5) -> list:
    """Returns last N tickets ordered by last_seen."""
    tickets = load_tickets()
    sorted_tickets = sorted(
        tickets.values(), key=lambda t: t.get("last_seen", ""), reverse=True
    )
    return sorted_tickets[:n]


def mark_ticket_fixed(
    ticket_id: str, reason: str = None, by: str = None
) -> dict | None:
    """Marks ticket as fixed. Returns updated ticket or None."""
    if not update_ticket_status(ticket_id, "fixed"):
        return None
    return get_ticket_by_id(ticket_id)


def mark_ticket_new(ticket_id: str) -> dict | None:
    """Marks ticket as new (reopens). Returns updated ticket or None."""
    if not update_ticket_status(ticket_id, "new"):
        return None
    return get_ticket_by_id(ticket_id)


# ============================================================
# NOTIFICATION FLAGS (state tracking only)
# ============================================================


def should_notify_repeat(ticket: dict, kind: str) -> bool:
    """
    Determines if a repeat notification should be sent.
    kind: "admin" or "user"
    """
    if kind == "admin":
        last_ts = ticket.get("notified_admin_last_ts")
    else:
        last_ts = ticket.get("notified_user_last_ts")

    if last_ts is None:
        return True

    status_changed_ts = ticket.get("status_changed_ts")
    if status_changed_ts:
        last_dt = _parse_iso_ts(last_ts)
        changed_dt = _parse_iso_ts(status_changed_ts)
        if last_dt and changed_dt and changed_dt > last_dt:
            return True

    mins = _minutes_since(last_ts)
    if mins is None:
        return True
    return mins >= COOLDOWN_MINUTES


def update_ticket_notification_flags(
    ticket_id: str, admin_sent: bool = False, user_sent: bool = False
) -> dict | None:
    """Updates notification flags for a ticket."""
    tickets = load_tickets()
    now = datetime.now().isoformat(timespec="seconds")
    for fp, ticket in tickets.items():
        if ticket.get("id") == ticket_id:
            changed = False
            if admin_sent:
                if not ticket.get("notified_admin"):
                    ticket["notified_admin"] = True
                    ticket["notified_admin_ts"] = now
                ticket["notified_admin_count"] = (
                    int(ticket.get("notified_admin_count") or 0) + 1
                )
                ticket["notified_admin_last_ts"] = now
                changed = True
            if user_sent:
                if not ticket.get("notified_user"):
                    ticket["notified_user"] = True
                    ticket["notified_user_ts"] = now
                ticket["notified_user_count"] = (
                    int(ticket.get("notified_user_count") or 0) + 1
                )
                ticket["notified_user_last_ts"] = now
                changed = True
            if changed:
                save_tickets(tickets)
            return ticket
    return None


def update_ticket_resolution_flags(
    ticket_id: str, admin_sent: bool = False, user_sent: bool = False
) -> dict | None:
    """Updates resolution notification flags."""
    tickets = load_tickets()
    now = datetime.now().isoformat(timespec="seconds")
    for fp, ticket in tickets.items():
        if ticket.get("id") == ticket_id:
            changed = False
            if ticket.get("resolved_ts") is None:
                ticket["resolved_ts"] = now
                changed = True
            if admin_sent and not ticket.get("resolved_notified_admin"):
                ticket["resolved_notified_admin"] = True
                changed = True
            if user_sent and not ticket.get("resolved_notified_user"):
                ticket["resolved_notified_user"] = True
                changed = True
            if changed:
                save_tickets(tickets)
            return ticket
    return None


# ============================================================
# BUG LOGGING
# ============================================================


def _load_bugs() -> list:
    """Loads all bugs from bugs.jsonl."""
    bugs = []
    if not BUGS_FILE.exists():
        return bugs

    try:
        with open(BUGS_FILE, "r", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    bugs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error loading bugs: {e}")

    return bugs


def get_last_bugs(n: int = 5) -> list:
    """Returns last N bugs from file."""
    bugs = _load_bugs()
    return bugs[-n:] if bugs else []


def record_exception(
    chat_id: str,
    text: str,
    error: Exception,
    tenant_id: str = "default",
    user_id: str = "unknown",
    is_test: bool = False,
) -> Tuple[Optional[dict], bool]:
    """
    Records an exception/bug to bugs.jsonl and upserts a ticket.

    Args:
        chat_id: Identifier for the source (can be Telegram chat_id, "api", "web", etc.)
        text: User input or context that triggered the error
        error: The exception object
        tenant_id: Tenant identifier (default: "default")
        user_id: User identifier (default: "unknown")
    """
    # Validate and normalize chat_id
    if chat_id is None or chat_id == "":
        chat_id = "unknown"
    elif not isinstance(chat_id, str):
        chat_id = str(chat_id)

    try:
        _ensure_autofix_dir()

        tb = traceback.format_exc()
        if len(tb) > 2000:
            tb = tb[:2000] + "\n... [truncated]"

        text_preview = text[:200] if text else ""
        error_msg = str(error)[:500]
        error_type = type(error).__name__

        bug_entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "text": text_preview,
            "error_type": error_type,
            "error_msg": error_msg,
            "traceback": tb,
        }

        with open(BUGS_FILE, "a", encoding=DEFAULT_ENCODING) as f:
            f.write(json.dumps(bug_entry, ensure_ascii=False) + "\n")

        logger.info(f"Bug recorded: {error_type} (chat_id={chat_id})")

        ticket, is_new = upsert_ticket(
            error_type=error_type,
            tb_str=tb,
            chat_id=chat_id,
            text=text,
            error_msg=error_msg,
            tenant_id=tenant_id,
            user_id=user_id,
            is_test=is_test,
        )
        return ticket, is_new
    except Exception as log_err:
        logger.error(f"Failed to record bug: {log_err}")
        return None, False


# ============================================================
# TICKET REINDEX
# ============================================================


def _find_bug_for_ticket(ticket: dict, bugs: list) -> dict | None:
    """
    Finds the most recent bug that matches the ticket.
    Uses match by error_type + old top_frame.
    """
    ticket_error_type = ticket.get("error_type")
    ticket_top_frame = ticket.get("top_frame", "")

    matching_bugs = []
    for bug in bugs:
        if bug.get("error_type") != ticket_error_type:
            continue

        tb = bug.get("traceback", "")
        if not tb:
            continue

        bug_frames = _extract_frames(tb)
        bug_lib_frame = bug_frames.get("lib_frame", "")

        if ticket_top_frame == bug_lib_frame:
            matching_bugs.append(bug)
            continue

        if tb:
            matching_bugs.append(bug)

    if not matching_bugs:
        return None

    matching_bugs.sort(key=lambda b: b.get("ts", ""), reverse=True)
    return matching_bugs[0]


def _reindex_single_ticket(ticket: dict, old_fp: str, bugs: list, stats: dict) -> str:
    """Reindexes a single ticket. Returns the fingerprint key to use."""
    ticket_id = ticket.get("id", "?")

    existing_repo_frame = ticket.get("repo_frame")
    if existing_repo_frame and existing_repo_frame != "N/A":
        stats["unchanged"] += 1
        stats["details"].append(f"{ticket_id}: unchanged (already has repo_frame)")
        return old_fp

    bug = _find_bug_for_ticket(ticket, bugs)

    if not bug or not bug.get("traceback"):
        ticket["frame_source"] = "unknown"
        ticket["repo_frame"] = None
        ticket["lib_frame"] = ticket.get("top_frame")
        stats["unknown"] += 1
        stats["details"].append(f"{ticket_id}: unknown (no traceback found)")
        return old_fp

    tb_str = bug.get("traceback", "")
    frames = _extract_frames(tb_str)

    repo_frame = frames.get("repo_frame")
    lib_frame = frames.get("lib_frame")
    frame_source = frames.get("frame_source", "unknown")

    ticket["repo_frame"] = repo_frame
    ticket["lib_frame"] = lib_frame
    ticket["frame_source"] = frame_source

    if not repo_frame:
        stats["unknown"] += 1
        stats["details"].append(f"{ticket_id}: lib_frame only ({lib_frame})")
        return old_fp

    old_top_frame = ticket.get("top_frame")
    ticket["top_frame"] = repo_frame
    new_fingerprint = _generate_fingerprint(ticket["error_type"], repo_frame)
    ticket["fingerprint"] = new_fingerprint

    stats["updated"] += 1
    stats["details"].append(
        f"{ticket_id}: updated repo_frame={repo_frame} (was top_frame={old_top_frame})"
    )
    return new_fingerprint


def _save_reindexed_tickets(reindexed_tickets: dict, stats: dict) -> None:
    """Atomically saves reindexed tickets using a tmp+replace strategy."""
    _ensure_autofix_dir()
    tmp_path = TICKETS_FILE.with_suffix(".jsonl.tmp")

    try:
        with open(tmp_path, "w", encoding=DEFAULT_ENCODING) as f:
            for ticket in reindexed_tickets.values():
                f.write(json.dumps(ticket, ensure_ascii=False) + "\n")

        tmp_path.replace(TICKETS_FILE)
        logger.info(
            f"Tickets reindexed: {stats['updated']} updated, {stats['unknown']} unknown"
        )

    except Exception as e:
        logger.error(f"Error saving reindexed tickets: {e}")
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def reindex_tickets() -> dict:
    """
    Reindexes tickets with repo_frame/lib_frame/frame_source.

    For each ticket without repo_frame:
    - Searches for corresponding bug in bugs.jsonl
    - Extracts frames from traceback
    - Updates ticket with repo_frame, lib_frame, frame_source
    - Recalculates top_frame and fingerprint if repo_frame found

    Returns dict with statistics:
    - total: number of tickets processed
    - updated: tickets updated with repo_frame
    - unchanged: tickets that already had repo_frame
    - unknown: tickets without available traceback
    """
    stats = {"total": 0, "updated": 0, "unchanged": 0, "unknown": 0, "details": []}

    tickets = load_tickets()
    bugs = _load_bugs()

    if not tickets:
        return stats

    if TICKETS_FILE.exists():
        backup_path = TICKETS_FILE.with_suffix(".jsonl.bak")
        shutil.copy2(TICKETS_FILE, backup_path)
        logger.info(f"Backup created: {backup_path}")

    reindexed_tickets = {}

    for old_fp, ticket in tickets.items():
        stats["total"] += 1
        new_fp = _reindex_single_ticket(ticket, old_fp, bugs, stats)
        reindexed_tickets[new_fp] = ticket

    _save_reindexed_tickets(reindexed_tickets, stats)
    return stats


# ============================================================
# STATUS CALCULATION
# ============================================================


def _is_test_ticket(ticket: dict) -> bool:
    """Return True if *ticket* was generated by test input."""
    if ticket.get("is_test") is True:
        return True
    return (
        ticket.get("sample_text") == "/bug_test"
        or ticket.get("last_error_msg") == "bug_test"
    )


def _is_test_patch(patch: dict) -> bool:
    """Return True if *patch* belongs to a test ticket."""
    ticket_id = str(patch.get("ticket_id") or "")
    if ticket_id in {"TESTPATCH", "TESTPATCH2"}:
        return True
    return ticket_id.startswith("TEST")


def _has_active_tickets() -> bool:
    """Return True if any ticket with status 'new' or 'resolving' was seen recently."""
    tickets = load_tickets()
    now = _utc_now()
    for ticket in tickets.values():
        status = str(ticket.get("status", "")).lower()
        if status in ("new", "resolving"):
            last_seen = _parse_iso_ts(ticket.get("last_seen"))
            if (
                last_seen
                and (now - last_seen).total_seconds() <= ACTIVE_WINDOW_MINUTES * 60
            ):
                return True
    return False


def _has_recent_errors() -> bool:
    """Return True if any ticket was last seen within the stability window."""
    tickets = load_tickets()
    now = _utc_now()
    for ticket in tickets.values():
        last_seen = _parse_iso_ts(ticket.get("last_seen"))
        if (
            last_seen
            and (now - last_seen).total_seconds() <= STABLE_TO_GREEN_MINUTES * 60
        ):
            return True
    return False


def _compute_ticket_counts(tickets: dict) -> Tuple[int, int, Optional[datetime]]:
    """Counts new/fixed tickets and finds the newest timestamp."""
    number_new = 0
    number_fixed = 0
    newest_dt = None

    for ticket in tickets.values():
        status = str(ticket.get("status", "")).lower()
        if status == "new":
            number_new += 1
        elif status == "fixed":
            number_fixed += 1

        ts = ticket.get("last_seen") or ticket.get("status_changed_ts")
        dt = _parse_iso(ts)
        if dt and (newest_dt is None or dt > newest_dt):
            newest_dt = dt

    return number_new, number_fixed, newest_dt


def _determine_state(
    number_new: int, seconds_since_newest: float | None
) -> Tuple[str, str]:
    """Determines system state (red/yellow/green) and reason."""
    if number_new > 0:
        return "red", "Active unresolved tickets"
    if (
        seconds_since_newest is not None
        and seconds_since_newest <= STABILITY_WINDOW_SECONDS
    ):
        return "yellow", "Monitoring stability"
    return "green", "All systems operational"


def get_status() -> dict:
    """
    Returns system status based on tickets.
    Returns dict with:
      - state: "red", "yellow", or "green"
      - reason: human-readable explanation
      - counts: {total, new, fixed, ...}
      - newest_ts: ISO timestamp of newest ticket
    """
    tickets = load_tickets()
    number_new, number_fixed, newest_dt = _compute_ticket_counts(tickets)

    now = _utc_now()
    seconds_since_newest = (now - newest_dt).total_seconds() if newest_dt else None
    state, reason = _determine_state(number_new, seconds_since_newest)

    return {
        "state": state,
        "reason": reason,
        "counts": {"total": len(tickets), "new": number_new, "fixed": number_fixed},
        "newest_ts": newest_dt.isoformat() if newest_dt else None,
    }


# ============================================================
# CLEANUP
# ============================================================


def cleanup_test_data() -> dict:
    """
    Removes test tickets and patches from data files.
    Returns dict with counts of removed items.
    """
    tickets = load_tickets()
    patches = _load_all_patches()

    ticket_keys = [fp for fp, t in tickets.items() if _is_test_ticket(t)]
    patches_filtered = [p for p in patches if not _is_test_patch(p)]
    patch_removed = len(patches) - len(patches_filtered)

    result = {
        "tickets_removed": 0,
        "patches_removed": 0,
        "tickets_backup": None,
        "patches_backup": None,
    }

    if not ticket_keys and patch_removed == 0:
        return result

    if ticket_keys:
        result["tickets_backup"] = str(_backup_jsonl(TICKETS_FILE))
        for fp in ticket_keys:
            tickets.pop(fp, None)
        save_tickets(tickets)
        result["tickets_removed"] = len(ticket_keys)

    if patch_removed:
        result["patches_backup"] = str(_backup_jsonl(PATCHES_FILE))
        _save_all_patches(patches_filtered)
        result["patches_removed"] = patch_removed

    return result


# ============================================================
# SUGGESTIONS
# ============================================================

_ERROR_HEURISTICS = {
    "BadRequest": {
        "cause": "Invalid request format to Telegram (e.g., malformed Markdown, message too long)",
        "fix": "Use escape_markdown() or send without parse_mode. Split long messages into chunks.",
        "checklist": [
            "Check for unescaped special characters (_*[]`)",
            "Check message size (max 4096 chars)",
            "Test sending without parse_mode first",
            "Use _reply_markdown_safe() if available",
        ],
    },
    "RuntimeError": {
        "cause": "Logic error or invalid state during execution",
        "fix": "Add state validations and specific exception handling.",
        "checklist": [
            "Verify all variables are initialized",
            "Check race conditions (async)",
            "Add specific try/except",
            "Log state before error",
        ],
    },
    "KeyError": {
        "cause": "Attempted to access non-existent key in dict",
        "fix": "Use .get() with default value or check existence before accessing.",
        "checklist": [
            "Replace dict[key] with dict.get(key, default)",
            "Add 'if key in dict:' before access",
            "Verify JSON/dict is in expected format",
            "Log dict contents for debug",
        ],
    },
    "TypeError": {
        "cause": "Operation with incompatible type (None, wrong type, missing argument)",
        "fix": "Validate types before operating. Check if value is not None.",
        "checklist": [
            "Add 'if value is not None:' before use",
            "Verify called function signature",
            "Check if type conversion is needed",
            "Use isinstance() to validate type",
        ],
    },
    "AttributeError": {
        "cause": "Attempted to access attribute/method on object that doesn't have it (possibly None)",
        "fix": "Verify object is not None before accessing attributes.",
        "checklist": [
            "Add guard 'if obj is not None:'",
            "Verify import was done correctly",
            "Check if object is expected type",
            "Use getattr(obj, 'attr', default) if appropriate",
        ],
    },
    "ValueError": {
        "cause": "Invalid value passed to function (wrong format, out of range)",
        "fix": "Validate input before processing. Sanitize user data.",
        "checklist": [
            "Add format/range validation",
            "Sanitize user input",
            "Use try/except for conversions",
            "Return friendly error if invalid",
        ],
    },
    "JSONDecodeError": {
        "cause": "Attempted to parse invalid or corrupted JSON",
        "fix": "Wrap json.loads() in try/except. Validate string before parsing.",
        "checklist": [
            "Verify string is not empty",
            "Check file/string encoding",
            "Add try/except JSONDecodeError",
            "Log raw content for debug",
        ],
    },
    "FileNotFoundError": {
        "cause": "File or directory doesn't exist at specified path",
        "fix": "Check existence with Path.exists() before opening. Create directory if needed.",
        "checklist": [
            "Add 'if path.exists():' before opening",
            "Use mkdir(parents=True, exist_ok=True) for directories",
            "Verify if path is absolute or relative",
            "Check access permissions",
        ],
    },
    "PermissionError": {
        "cause": "No permission to access file/resource",
        "fix": "Check file/directory permissions. Run with adequate privileges.",
        "checklist": [
            "Check file owner/permissions",
            "Verify file is not in use",
            "Test in directory with write permission",
            "Use temporary directory if appropriate",
        ],
    },
    "ConnectionError": {
        "cause": "Connection failure with external service (network, API, database)",
        "fix": "Add retry with backoff. Handle timeout. Verify connectivity.",
        "checklist": [
            "Add timeout to requests",
            "Implement retry with exponential backoff",
            "Verify URL/endpoint is correct",
            "Check firewall/proxy",
        ],
    },
    "TimeoutError": {
        "cause": "Operation exceeded time limit",
        "fix": "Increase timeout or optimize operation. Add specific handling.",
        "checklist": [
            "Verify timeout is configured adequately",
            "Optimize slow query/operation",
            "Add async/threading if blocking",
            "Implement circuit breaker",
        ],
    },
}

_LOCATION_HEURISTICS = {
    "telegram_bot": "Telegram handler code. Check Markdown escape and update handling.",
    "bot": "Bot core. Check command logic and config/ledger integration.",
    "handle_text": "Message handler. Check user input processing.",
    "handle_error": "Global error handler. Check if exception is being propagated correctly.",
    "cmd_": "Admin command. Check args parsing and formatted response.",
    "log_bug": "Bug logging system. Check file access.",
    "upsert_ticket": "Ticket system. Check JSONL read/write.",
}


def _get_cause_heuristic(error_type: str, top_frame: str) -> str:
    """Return a human-readable probable cause for *error_type*."""
    if error_type in _ERROR_HEURISTICS:
        return _ERROR_HEURISTICS[error_type]["cause"]
    return f"Error of type {error_type} occurred during execution."


def _get_fix_suggestion(error_type: str, top_frame: str) -> str:
    """Return a suggested fix for *error_type*."""
    if error_type in _ERROR_HEURISTICS:
        return _ERROR_HEURISTICS[error_type]["fix"]
    return "Add specific exception handling and logging for diagnosis."


def _get_checklist(error_type: str) -> list:
    """Return the verification checklist items for *error_type*."""
    if error_type in _ERROR_HEURISTICS:
        return _ERROR_HEURISTICS[error_type]["checklist"]
    return [
        "Check logs for more context",
        "Reproduce the error locally",
        "Add specific try/except",
        "Test after fix",
    ]


def _get_location_hint(top_frame: str) -> str:
    """Return a contextual hint about the module where the error occurred."""
    parts = top_frame.split(":")
    if len(parts) >= 2:
        module = parts[0]
        func = parts[1]

        if module in _LOCATION_HEURISTICS:
            return _LOCATION_HEURISTICS[module]

        for prefix, hint in _LOCATION_HEURISTICS.items():
            if func.startswith(prefix):
                return hint

    return "Check the file and line indicated in top_frame."


def build_suggestion(ticket: dict) -> str:
    """
    Generates suggestion text based on local heuristics.
    Does not use external AI - only deterministic rules.
    """
    ticket_id = ticket.get("id", "?")
    error_type = ticket.get("error_type", "Unknown")
    fingerprint = ticket.get("fingerprint", "?")
    top_frame = ticket.get("top_frame", "unknown:unknown:0")
    count = ticket.get("count", 0)
    status = ticket.get("status", "?")
    last_seen = ticket.get("last_seen", "?")
    last_error_msg = ticket.get("last_error_msg", "")[:150]

    repo_frame = ticket.get("repo_frame")
    lib_frame = ticket.get("lib_frame")
    frame_source = ticket.get("frame_source", "unknown")

    effective_frame = repo_frame or top_frame

    parts = effective_frame.split(":")
    module = parts[0] if len(parts) > 0 else "?"
    func = parts[1] if len(parts) > 1 else "?"
    line = parts[2] if len(parts) > 2 else "?"

    cause = _get_cause_heuristic(error_type, effective_frame)
    fix = _get_fix_suggestion(error_type, effective_frame)
    location_hint = _get_location_hint(effective_frame)
    checklist = _get_checklist(error_type)

    checklist_text = "\n".join(f"   [ ] {item}" for item in checklist)

    frame_info = f"Frame used: {effective_frame} (source: {frame_source})"
    if lib_frame and lib_frame != effective_frame:
        frame_info += f"\nLib frame: {lib_frame}"

    suggestion_text = f"""
=== FIX SUGGESTION ===

Ticket: {ticket_id}
Error: {error_type} (x{count})
Status: {status}
Last seen: {last_seen}

--- WHERE TO LOOK ---
File: {module}.py
Function: {func}()
Line: {line}
{frame_info}
Hint: {location_hint}

--- PROBABLE CAUSE ---
{cause}

--- ERROR MESSAGE ---
{last_error_msg}

--- FIX SUGGESTION ---
{fix}

--- VALIDATION CHECKLIST ---
{checklist_text}

--- FINGERPRINT ---
{fingerprint}
"""
    return suggestion_text.strip()


def build_suggestion_for_ticket(ticket_id: str) -> Tuple[Optional[str], Optional[dict]]:
    """
    Builds suggestion for a ticket by ID.
    Returns (suggestion_text, suggestion_record) or (None, None) if not found.
    """
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        return None, None

    suggestion_text = build_suggestion(ticket)

    record = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ticket_id": ticket_id,
        "error_type": ticket.get("error_type"),
        "fingerprint": ticket.get("fingerprint"),
        "top_frame": ticket.get("top_frame"),
        "status": ticket.get("status"),
        "count": ticket.get("count"),
        "suggestion_text": suggestion_text,
    }

    append_suggestion(record)
    return suggestion_text, record


def append_suggestion(record: dict):
    """Saves suggestion to suggestions.jsonl (append-only)."""
    _ensure_autofix_dir()
    try:
        with open(SUGGESTIONS_FILE, "a", encoding=DEFAULT_ENCODING) as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(f"Suggestion saved: ticket_id={record.get('ticket_id')}")
    except Exception as e:
        logger.error(f"Error saving suggestion: {e}")


def get_last_suggestions(n: int = 5) -> list:
    """Returns last N suggestions."""
    if not SUGGESTIONS_FILE.exists():
        return []

    suggestions = []
    try:
        with open(SUGGESTIONS_FILE, "r", encoding=DEFAULT_ENCODING) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    suggestions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception:
        return []

    return suggestions[-n:] if suggestions else []


# ============================================================
# PATCHES
# ============================================================

_PATCH_TEMPLATES = {
    "BadRequest": {
        "patch_type": "telegram_markdown_safe",
        "target_files": ["telegram_bot.py"],
        "notes": "Telegram Markdown error. Use safe send without parse_mode or with escape.",
        "checklist": [
            "Identify line that sends message with parse_mode",
            "Replace with _reply_markdown_safe() or send without parse_mode",
            "Test with special characters (_*[]`)",
            "Verify message size (max 4096)",
            "Run /bug_test and confirm it doesn't break",
        ],
    },
    "RuntimeError": {
        "patch_type": "generic_guard",
        "target_files": ["telegram_bot.py", "bot.py"],
        "notes": "Generic RuntimeError. Add specific handling or remove test code.",
        "checklist": [
            "Check if it's test code (/bug_test)",
            "If production, add specific try/except",
            "Log context before error",
            "Test scenario that caused the error",
            "Verify state is consistent after error",
        ],
    },
    "KeyError": {
        "patch_type": "dict_safe_access",
        "target_files": ["bot.py", "telegram_bot.py"],
        "notes": "Access to non-existent key. Use .get() with default.",
        "checklist": [
            "Replace dict[key] with dict.get(key, default)",
            "Verify if key is optional or required",
            "Add schema validation if needed",
            "Test with incomplete data",
        ],
    },
    "TypeError": {
        "patch_type": "none_guard",
        "target_files": ["bot.py", "telegram_bot.py"],
        "notes": "Operation with None or incorrect type. Add validation.",
        "checklist": [
            "Add 'if value is not None:' before use",
            "Verify expected type vs received",
            "Use isinstance() for validation",
            "Test with None/empty values",
        ],
    },
    "AttributeError": {
        "patch_type": "none_guard",
        "target_files": ["bot.py", "telegram_bot.py"],
        "notes": "Attribute access on None object. Add guard.",
        "checklist": [
            "Identify object that can be None",
            "Add verification before access",
            "Use getattr(obj, 'attr', default) if appropriate",
            "Test scenario where object is None",
        ],
    },
    "ValueError": {
        "patch_type": "input_validation",
        "target_files": ["bot.py", "telegram_bot.py"],
        "notes": "Invalid value. Add input validation.",
        "checklist": [
            "Identify source of invalid value",
            "Add validation before processing",
            "Return friendly error to user",
            "Test with edge-case values",
        ],
    },
    "JSONDecodeError": {
        "patch_type": "json_safe_parse",
        "target_files": ["bot.py", "telegram_bot.py"],
        "notes": "Invalid JSON. Wrap parse in try/except.",
        "checklist": [
            "Wrap json.loads() in try/except",
            "Verify string is not empty",
            "Log raw content for debug",
            "Return default value if fails",
        ],
    },
    "FileNotFoundError": {
        "patch_type": "file_exists_check",
        "target_files": ["bot.py"],
        "notes": "File doesn't exist. Check existence before opening.",
        "checklist": [
            "Add Path.exists() before opening",
            "Create parent directory if needed",
            "Use default value if file doesn't exist",
            "Test with missing file",
        ],
    },
}


def _PATCH_TEMPLATE_DEFAULT(error_type: str) -> dict:
    """Return a generic patch template for unknown error types."""
    return {
        "patch_type": "generic_guard",
        "target_files": ["telegram_bot.py", "bot.py"],
        "notes": f"Error {error_type}. Add specific handling.",
        "checklist": [
            "Identify root cause",
            "Add appropriate try/except",
            "Log context for debug",
            "Test error scenario",
        ],
    }


def _parse_frame(top_frame: str) -> tuple:
    """Parse a top_frame string into (module, func, line) components.

    Args:
        top_frame: Colon-separated frame string e.g. 'module:func:42'.

    Returns:
        Tuple of (module, func, line) with safe defaults.
    """
    parts = top_frame.split(":")
    module = parts[0] if len(parts) > 0 else "unknown"
    func = parts[1] if len(parts) > 1 else "unknown"
    line = parts[2] if len(parts) > 2 else "0"
    return module, func, line


# Diff template bodies keyed by error type.  Each value is a format string
# that receives ``module``, ``line``, and ``func`` as named placeholders.
_DIFF_TEMPLATES: Dict[str, str] = {
    "BadRequest": """--- a/{module}.py
+++ b/{module}.py
@@ -{line},6 +{line},12 @@
 # BEFORE: Direct send with Markdown that may fail
-    await update.message.reply_text(text, parse_mode="Markdown")
+    # AFTER: Safe send with fallback
+    try:
+        await update.message.reply_text(text, parse_mode="Markdown")
+    except Exception:
+        # Fallback: send without formatting
+        await update.message.reply_text(text)

# OR use existing helper:
-    await update.message.reply_text(formatted_text, parse_mode="Markdown")
+    await _reply_markdown_safe(update, formatted_text)
""",
    "KeyError": """--- a/{module}.py
+++ b/{module}.py
@@ -{line},3 +{line},5 @@
 # BEFORE: Direct access that may fail
-value = data["key"]
+# AFTER: Safe access with default
+value = data.get("key", None)
+if value is None:
+    logger.warning("Key 'key' not found in data")
""",
    "TypeError": """--- a/{module}.py
+++ b/{module}.py
@@ -{line},3 +{line},6 @@
 # BEFORE: Direct use that may fail with None
-result = obj.method()
+# AFTER: Guard against None
+if obj is not None:
+    result = obj.method()
+else:
+    result = None  # or appropriate default
+    logger.warning("Object was None in {func}()")
""",
    "ValueError": """--- a/{module}.py
+++ b/{module}.py
@@ -{line},3 +{line},8 @@
 # BEFORE: Direct conversion
-value = int(user_input)
+# AFTER: Validation before convert
+try:
+    value = int(user_input)
+except ValueError:
+    logger.warning(f"Invalid value: {{user_input}}")
+    value = 0  # or raise with friendly message
""",
    "JSONDecodeError": """--- a/{module}.py
+++ b/{module}.py
@@ -{line},3 +{line},9 @@
 # BEFORE: Direct parse
-data = json.loads(raw_string)
+# AFTER: Safe parse
+try:
+    data = json.loads(raw_string) if raw_string else {{}}
+except json.JSONDecodeError as e:
+    logger.error(f"Invalid JSON: {{e}}")
+    data = {{}}  # or re-raise with context
""",
    "FileNotFoundError": """--- a/{module}.py
+++ b/{module}.py
@@ -{line},3 +{line},7 @@
 # BEFORE: Direct open
-with open(filepath, "r") as f:
+# AFTER: Check existence
+if filepath.exists():
+    with open(filepath, "r") as f:
+        content = f.read()
+else:
+    logger.warning(f"File not found: {{filepath}}")
+    content = ""  # or default value
""",
}

# AttributeError reuses the TypeError template
_DIFF_TEMPLATES["AttributeError"] = _DIFF_TEMPLATES["TypeError"]

# RuntimeError (bug_test variant) handled separately via key
_DIFF_TEMPLATES["RuntimeError:bug_test"] = """--- a/{module}.py
+++ b/{module}.py
@@ -{line},4 +{line},6 @@
 # This is an intentional test error
 # In production, consider:
 # 1. Remove /bug_test or
 # 2. Protect with environment flag

+# Option: Disable in production
+# if os.environ.get("DEBUG_MODE") != "1":
+#     await update.message.reply_text("Command disabled.")
+#     return
"""

_DIFF_GENERIC = """--- a/{module}.py
+++ b/{module}.py
@@ -{line},3 +{line},8 @@
 # Error: {error_type}
 # Location: {func}() line {line}
 #
 # Generic suggestion:
+try:
+    # code that may fail
+    pass
+except {error_type} as e:
+    logger.error(f"Error in {func}: {{e}}")
+    # appropriate handling
"""


def _generate_diff_for_error(error_type: str, top_frame: str, error_msg: str) -> str:
    """Generate an approximate contextual diff suggestion based on error type.

    Uses a template lookup instead of a long if/elif chain.
    NOT a real diff — it's a suggested change.

    Args:
        error_type: The exception class name (e.g. 'KeyError').
        top_frame: Colon-separated frame string 'module:func:line'.
        error_msg: The original error message (used for variant matching).

    Returns:
        A unified-diff-style string with the suggested fix.
    """
    module, func, line = _parse_frame(top_frame)
    fmt = {"module": module, "func": func, "line": line, "error_type": error_type}

    # Check for special RuntimeError variant first
    if error_type == "RuntimeError" and "bug_test" in error_msg.lower():
        return _DIFF_TEMPLATES["RuntimeError:bug_test"].format(**fmt)

    template = _DIFF_TEMPLATES.get(error_type)
    if template:
        return template.format(**fmt)

    return _DIFF_GENERIC.format(**fmt)


def build_patch(ticket: dict) -> dict:
    """
    Generates patch (draft) based on local heuristics.
    Returns dict with metadata and diff.
    Does NOT apply any changes - only generates the draft.
    """
    ticket_id = ticket.get("id", "?")
    error_type = ticket.get("error_type", "Unknown")
    fingerprint = ticket.get("fingerprint", "?")
    top_frame = ticket.get("top_frame", "unknown:unknown:0")
    count = ticket.get("count", 0)
    ticket_status = ticket.get("status", "?")
    error_msg = ticket.get("last_error_msg", "")

    repo_frame = ticket.get("repo_frame")
    lib_frame = ticket.get("lib_frame")
    frame_source = ticket.get("frame_source", "unknown")

    effective_frame = repo_frame or top_frame

    template = _PATCH_TEMPLATES.get(error_type, _PATCH_TEMPLATE_DEFAULT(error_type))

    diff = _generate_diff_for_error(error_type, effective_frame, error_msg)

    truncated = False
    if len(diff) > 12000:
        diff = diff[:12000] + "\n\n... [TRUNCATED - diff too large]"
        truncated = True

    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "ticket_id": ticket_id,
        "error_type": error_type,
        "fingerprint": fingerprint,
        "top_frame": top_frame,
        "repo_frame": repo_frame,
        "lib_frame": lib_frame,
        "frame_source": frame_source,
        "ticket_status": ticket_status,
        "count": count,
        "patch_type": template["patch_type"],
        "target_files": template["target_files"],
        "diff": diff,
        "truncated": truncated,
        "notes": template["notes"],
        "validation_checklist": template["checklist"],
        "status": "proposed",
        "decision": None,
    }


def build_patch_for_ticket(ticket_id: str) -> Tuple[Optional[dict], Optional[dict]]:
    """
    Builds patch for a ticket by ID.
    Returns (patch, ticket) or (None, None) if not found.
    """
    ticket = get_ticket_by_id(ticket_id)
    if not ticket:
        return None, None

    patch = build_patch(ticket)
    append_patch(patch)
    return patch, ticket


def append_patch(record: dict):
    """Saves patch to patches.jsonl (append-only). Does NOT apply any code changes."""
    _ensure_autofix_dir()
    try:
        with open(PATCHES_FILE, "a", encoding=DEFAULT_ENCODING) as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            f"Patch saved: ticket_id={record.get('ticket_id')} type={record.get('patch_type')}"
        )
    except Exception as e:
        logger.error(f"Error saving patch: {e}")


def _load_all_patches() -> list:
    """Loads all patches from patches.jsonl."""
    if not PATCHES_FILE.exists():
        return []

    patches = []
    try:
        with open(PATCHES_FILE, "r", encoding=DEFAULT_ENCODING) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    patches.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        logger.error(f"Error loading patches: {e}")
        return []

    return patches


def _save_all_patches(patches: list):
    """Saves all patches (rewrites the file)."""
    _ensure_autofix_dir()
    try:
        with open(PATCHES_FILE, "w", encoding=DEFAULT_ENCODING) as f:
            for patch in patches:
                f.write(json.dumps(patch, ensure_ascii=False) + "\n")
    except Exception as e:
        logger.error(f"Error saving patches: {e}")
        raise


def get_last_patches(n: int = 5) -> list:
    """Returns last N patches."""
    patches = _load_all_patches()
    return patches[-n:] if patches else []


def get_patch_by_index(n: int) -> dict | None:
    """Returns patch by index (1 = most recent)."""
    patches = _load_all_patches()
    if not patches:
        return None

    patches = list(reversed(patches))

    if n < 1 or n > len(patches):
        return None

    return patches[n - 1]


def get_patch_status_emoji(status: str) -> str:
    """Returns emoji based on patch status."""
    status_emojis = {"proposed": "Y", "approved": "V", "rejected": "X"}
    return status_emojis.get(status, "?")


def approve_patch(index: int, by: str, reason: str = None) -> dict | None:
    """
    Approves a patch (human governance).
    Returns updated patch or None if not found or already processed.
    """
    patch = get_patch_by_index(index)
    if not patch:
        return None

    if patch.get("status") != "proposed":
        return None

    return _update_patch_status(index, "approved", by, reason)


def reject_patch(index: int, by: str, reason: str = None) -> dict | None:
    """
    Rejects a patch (human governance).
    Returns updated patch or None if not found or already processed.
    """
    patch = get_patch_by_index(index)
    if not patch:
        return None

    if patch.get("status") != "proposed":
        return None

    return _update_patch_status(index, "rejected", by, reason)


def _update_patch_status(
    index: int, new_status: str, admin_id: str, reason: str = None
) -> dict | None:
    """
    Updates governance status of a patch.
    """
    patches = _load_all_patches()
    if not patches:
        return None

    patches_reversed = list(reversed(patches))

    if index < 1 or index > len(patches_reversed):
        return None

    real_index = len(patches) - index

    patch = patches[real_index]
    patch["status"] = new_status
    patch["decision"] = {
        "by": admin_id,
        "ts": datetime.now().isoformat(timespec="seconds"),
        "reason": reason,
    }

    _save_all_patches(patches)

    logger.info(f"Patch {index} updated: status={new_status} by={admin_id}")

    return patch


# ============================================================
# SANDBOX APPLY
# ============================================================


def _ensure_sandbox_dir():
    """Create the sandbox directory tree if it does not exist."""
    SANDBOX_DIR.mkdir(parents=True, exist_ok=True)


def _new_run_dir() -> Path:
    """Create and return a timestamped run directory inside the sandbox."""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = SANDBOX_DIR / f"run_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def _safe_repo_path(rel_path: str) -> Path:
    """Resolve *rel_path* against the repo root, raising if it escapes the repo."""
    rp = rel_path.replace("\\", "/").lstrip("/")
    p = (BASE_DIR / rp).resolve()
    if not str(p).startswith(str(BASE_DIR)):
        raise ValueError("path outside repo")
    return p


def _parse_patch_diff(diff_text: str) -> dict:
    """Parse unified diff text into ``{filepath: [hunk, ...]}``."""
    file_hunks = {}
    current_file = None
    current_hunk = None
    pending_old = ""

    def _finish_hunk():
        """Flush the current hunk into *file_hunks*."""
        if current_file and current_hunk is not None:
            file_hunks.setdefault(current_file, []).append(current_hunk)

    for line in (diff_text or "").splitlines():
        if line.startswith("--- "):
            _finish_hunk()
            current_hunk = None
            old_path = line[4:].strip()
            if old_path.startswith("a/"):
                old_path = old_path[2:]
            pending_old = old_path
            if not current_file:
                current_file = old_path
            continue
        if line.startswith("+++ "):
            _finish_hunk()
            current_hunk = None
            new_path = line[4:].strip()
            if new_path.startswith("b/"):
                new_path = new_path[2:]
            current_file = new_path or pending_old
            continue
        if line.startswith("@@"):
            _finish_hunk()
            current_hunk = {"removed": [], "added": []}
            continue
        if current_hunk is None:
            continue
        if line.startswith("-") and not line.startswith("--- "):
            current_hunk["removed"].append(line[1:])
        elif line.startswith("+") and not line.startswith("+++ "):
            current_hunk["added"].append(line[1:])

    _finish_hunk()
    return file_hunks


def _apply_single_hunk(
    content: str,
    hunk: dict,
    mode: str,
) -> tuple[str, dict, bool]:
    """Apply a single hunk to *content*.

    Returns ``(new_content, result_dict, was_applied)``.

    Extracted from _apply_hunks_to_content to keep each hunk's logic
    self-contained and independently testable.
    """
    removed = hunk.get("removed", [])
    added = hunk.get("added", [])
    n_removed = len(removed)
    n_added = len(added)

    if not removed:
        return (
            content,
            {
                "status": "not_supported",
                "removed_lines": n_removed,
                "added_lines": n_added,
            },
            False,
        )

    removed_block = "\n".join(removed)
    if removed_block not in content:
        return (
            content,
            {"status": "not_found", "removed_lines": n_removed, "added_lines": n_added},
            False,
        )

    added_block = "\n".join(added)
    if mode == "apply":
        content = content.replace(removed_block, added_block, 1)
    return (
        content,
        {"status": "applied", "removed_lines": n_removed, "added_lines": n_added},
        True,
    )


def _apply_hunks_to_content(
    content: str, hunks: list, mode: str
) -> tuple[str, list, bool]:
    """Apply a list of hunks to *content*, delegating each to ``_apply_single_hunk``."""
    hunk_results = []
    applied_any = False

    for h in hunks:
        content, result, was_applied = _apply_single_hunk(content, h, mode)
        hunk_results.append(result)
        applied_any = applied_any or was_applied

    return content, hunk_results, applied_any


def _select_file_hunks(target_file: str, diff_hunks: dict) -> list:
    """Return the hunks for *target_file*, falling back to basename lookup."""
    if target_file in diff_hunks:
        return diff_hunks[target_file]
    base = Path(target_file).name
    return diff_hunks.get(base, [])


def _make_fail_result(filepath: str, sandbox_path: str, detail: str) -> dict:
    """Creates a standard failure result dict."""
    return {
        "file": filepath,
        "sandbox_path": sandbox_path,
        "status": "failed",
        "details": detail,
        "hunks": [],
    }


def _validate_diff_targets(diff_hunks: dict) -> list:
    """Validates that diff target files exist in repo. Returns failure results."""
    results = []
    for df in diff_hunks.keys():
        try:
            p = _safe_repo_path(df)
            if not p.exists():
                results.append(
                    _make_fail_result(df, "", "diff target not found in repo")
                )
        except Exception as e:
            results.append(_make_fail_result(df, "", f"invalid diff target: {e}"))
    return results


def _determine_hunk_status(hunk_results: list) -> str:
    """Classifies overall hunk application status."""
    statuses = [h["status"] for h in hunk_results]
    if all(s == "applied" for s in statuses):
        return "applied"
    if any(s == "applied" for s in statuses):
        return "partial"
    if any(s == "not_found" for s in statuses):
        return "failed"
    return "skipped"


def _process_target_file(tf: str, diff_hunks: dict, run_dir: Path, mode: str) -> dict:
    """Processes a single target file in the sandbox. Returns result dict."""
    try:
        repo_path = _safe_repo_path(tf)
    except Exception as e:
        return _make_fail_result(tf, "", f"invalid path: {e}")

    if not repo_path.exists():
        return _make_fail_result(tf, "", "file not found in repo")

    sandbox_path = run_dir / tf
    sandbox_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_path, sandbox_path)

    hunks = _select_file_hunks(tf, diff_hunks)
    if not hunks:
        return {
            "file": tf,
            "sandbox_path": str(sandbox_path),
            "status": "skipped",
            "details": "no hunks for this file",
            "hunks": [],
        }

    content = sandbox_path.read_text(encoding=DEFAULT_ENCODING)
    new_content, hunk_results, applied_any = _apply_hunks_to_content(
        content, hunks, mode
    )

    status = _determine_hunk_status(hunk_results)

    if mode == "apply" and applied_any:
        sandbox_path.write_text(new_content, encoding=DEFAULT_ENCODING)

    return {
        "file": tf,
        "sandbox_path": str(sandbox_path),
        "status": status,
        "details": f"hunks={len(hunk_results)} applied={[h['status'] for h in hunk_results].count('applied')}",
        "hunks": hunk_results,
    }


def apply_patch_sandbox(patch: dict, patch_index: int, mode: str) -> tuple[dict, Path]:
    """
    Applies patch in sandbox environment.
    mode: "dry_run" or "apply"
    Returns (report, run_dir)
    """
    _ensure_sandbox_dir()
    run_dir = _new_run_dir()
    diff_hunks = _parse_patch_diff(patch.get("diff", ""))
    target_files = patch.get("target_files", []) or []

    results = _validate_diff_targets(diff_hunks)

    for tf in target_files:
        results.append(_process_target_file(tf, diff_hunks, run_dir, mode))

    report = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "patch_index": patch_index,
        "ticket_id": patch.get("ticket_id"),
        "patch_status": patch.get("status", "proposed"),
        "mode": "apply" if mode == "apply" else "dry_run",
        "target_files": target_files,
        "results": results,
    }

    report_path = run_dir / "apply_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding=DEFAULT_ENCODING
    )
    return report, run_dir


def get_last_apply_report() -> dict | None:
    """Returns the most recent apply report."""
    report_path = _find_last_apply_report()
    if not report_path or not report_path.exists():
        return None

    try:
        return json.loads(report_path.read_text(encoding=DEFAULT_ENCODING))
    except Exception:
        return None


def _find_last_apply_report() -> Path | None:
    """Locate the most recently modified ``apply_report.json`` in the sandbox."""
    if not SANDBOX_DIR.exists():
        return None
    reports = list(SANDBOX_DIR.glob("run_*/apply_report.json"))
    if not reports:
        return None
    return max(reports, key=lambda p: p.stat().st_mtime)
