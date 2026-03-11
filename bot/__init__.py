"""
CapivaraX Bot - Refactored modular architecture.

Main modules:
- bot.core: Configuration, memory, multi-tenancy
- bot.utils: File operations, safety, Git
- bot.modes: Bot modes/personas
- bot.dev: DEV Agent system
- bot.commands: CLI commands (to be implemented)
- bot.cli: CLI interface (to be implemented)
"""

__version__ = "4.29-GOD-REFACTORED"

from .core import ConfigManager, MemoryManager, TenancyManager, TenantContext
from .modes import MODES, get_mode, list_modes, get_mode_names
from .dev import (
    claude_dev_call,
    claude_dev_strict_call,
    claude_dev_explain_call,
    is_claude_available,
    extract_actions_json,
    is_valid_actions_schema,
    normalize_action,
    dry_run_actions,
    dry_run_has_rejections,
    apply_actions,
    generate_receipt,
)
from .utils import (
    is_forbidden_path,
    safe_path,
    read_text_safe,
    write_text_safe,
    backup_file,
    list_workspace_files,
    confirm_action,
    safe_read_json,
    safe_write_json,
    run_git_command,
    git_status,
    git_add_all,
    git_commit,
    git_push,
    git_init,
    git_log,
    git_diff,
    git_branch,
    suggest_commit_message,
    has_uncommitted_changes,
)

__all__ = [
    # Version
    "__version__",
    # Core
    "ConfigManager",
    "MemoryManager",
    "TenancyManager",
    "TenantContext",
    # Modes
    "MODES",
    "get_mode",
    "list_modes",
    "get_mode_names",
    # DEV Agent
    "claude_dev_call",
    "claude_dev_strict_call",
    "claude_dev_explain_call",
    "is_claude_available",
    "extract_actions_json",
    "is_valid_actions_schema",
    "normalize_action",
    "dry_run_actions",
    "dry_run_has_rejections",
    "apply_actions",
    "generate_receipt",
    # Utils
    "is_forbidden_path",
    "safe_path",
    "read_text_safe",
    "write_text_safe",
    "backup_file",
    "list_workspace_files",
    "confirm_action",
    "safe_read_json",
    "safe_write_json",
    "run_git_command",
    "git_status",
    "git_add_all",
    "git_commit",
    "git_push",
    "git_init",
    "git_log",
    "git_diff",
    "git_branch",
    "suggest_commit_message",
    "has_uncommitted_changes",
]
