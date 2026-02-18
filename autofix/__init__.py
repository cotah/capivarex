# -*- coding: utf-8 -*-
"""
UNBX-BOT Autofix Module V4.29-GOD
Channel-agnostic triage, bug capture, and autofix logic.

This module provides the public API for all channels (Telegram, Web, API, CLI).
"""

from .core import (
    # Constants
    BOT_VERSION,
    BASE_DIR,
    WORKSPACE,
    AUTOFIX_DIR,
    BUGS_FILE,
    TICKETS_FILE,
    SUGGESTIONS_FILE,
    PATCHES_FILE,
    SANDBOX_DIR,
    COOLDOWN_MINUTES,
    ACTIVE_WINDOW_MINUTES,
    STABLE_TO_GREEN_MINUTES,
    STABILITY_WINDOW_SECONDS,

    # Bug/Exception Recording
    record_exception,
    get_last_bugs,

    # Ticket Management
    load_tickets,
    save_tickets,
    upsert_ticket,
    get_ticket_by_id,
    update_ticket_status,
    get_last_tickets,
    mark_ticket_fixed,
    mark_ticket_new,
    reindex_tickets,

    # Notification Flags
    should_notify_repeat,
    update_ticket_notification_flags,
    update_ticket_resolution_flags,

    # Status
    get_status,

    # Suggestions
    build_suggestion,
    build_suggestion_for_ticket,
    append_suggestion,
    get_last_suggestions,

    # Patches
    build_patch,
    build_patch_for_ticket,
    append_patch,
    get_last_patches,
    get_patch_by_index,
    get_patch_status_emoji,
    approve_patch,
    reject_patch,

    # Sandbox
    apply_patch_sandbox,
    get_last_apply_report,

    # Cleanup
    cleanup_test_data,
)

__all__ = [
    # Constants
    "BOT_VERSION",
    "BASE_DIR",
    "WORKSPACE",
    "AUTOFIX_DIR",
    "BUGS_FILE",
    "TICKETS_FILE",
    "SUGGESTIONS_FILE",
    "PATCHES_FILE",
    "SANDBOX_DIR",
    "COOLDOWN_MINUTES",
    "ACTIVE_WINDOW_MINUTES",
    "STABLE_TO_GREEN_MINUTES",
    "STABILITY_WINDOW_SECONDS",

    # Bug/Exception Recording
    "record_exception",
    "get_last_bugs",

    # Ticket Management
    "load_tickets",
    "save_tickets",
    "upsert_ticket",
    "get_ticket_by_id",
    "update_ticket_status",
    "get_last_tickets",
    "mark_ticket_fixed",
    "mark_ticket_new",
    "reindex_tickets",

    # Notification Flags
    "should_notify_repeat",
    "update_ticket_notification_flags",
    "update_ticket_resolution_flags",

    # Status
    "get_status",

    # Suggestions
    "build_suggestion",
    "build_suggestion_for_ticket",
    "append_suggestion",
    "get_last_suggestions",

    # Patches
    "build_patch",
    "build_patch_for_ticket",
    "append_patch",
    "get_last_patches",
    "get_patch_by_index",
    "get_patch_status_emoji",
    "approve_patch",
    "reject_patch",

    # Sandbox
    "apply_patch_sandbox",
    "get_last_apply_report",

    # Cleanup
    "cleanup_test_data",
]
