"""
DEV Agent system for CapivaraX Bot.

Provides:
- Claude client for code generation
- ACTIONS_JSON parser and validator
- Action executor with rollback support
"""

from .claude_client import (
    claude_dev_call,
    claude_dev_strict_call,
    claude_dev_explain_call,
    is_claude_available,
)

from .actions import (
    extract_actions_json,
    is_valid_actions_schema,
    normalize_action,
    dry_run_actions,
    dry_run_has_rejections,
    DEV_ACTION_ALIASES,
    VALID_ACTION_TYPES,
)

from .executor import (
    apply_actions,
    generate_receipt,
)

__all__ = [
    # Claude client
    "claude_dev_call",
    "claude_dev_strict_call",
    "claude_dev_explain_call",
    "is_claude_available",
    # Actions
    "extract_actions_json",
    "is_valid_actions_schema",
    "normalize_action",
    "dry_run_actions",
    "dry_run_has_rejections",
    "DEV_ACTION_ALIASES",
    "VALID_ACTION_TYPES",
    # Executor
    "apply_actions",
    "generate_receipt",
]
