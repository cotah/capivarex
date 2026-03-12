"""
Utility modules for CAPIVAREX Bot.

Provides:
- File operations (files.py)
- Safety utilities (safety.py)
- Git operations (git.py)
"""

from .files import (
    is_forbidden_path,
    safe_path,
    read_text_safe,
    write_text_safe,
    backup_file,
    list_workspace_files,
    get_file_size,
    ensure_directory,
    delete_file,
    move_file,
    copy_file,
    DEV_FORBIDDEN_PREFIXES,
    DEV_FORBIDDEN_FILES,
    DEV_MAX_FILE_CHARS,
)

from .safety import (
    confirm_action,
    safe_read_json,
    safe_write_json,
    safe_read_text,
    safe_write_text,
    validate_path_safety,
    sanitize_input,
)

from .git import (
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
    # Files
    "is_forbidden_path",
    "safe_path",
    "read_text_safe",
    "write_text_safe",
    "backup_file",
    "list_workspace_files",
    "get_file_size",
    "ensure_directory",
    "delete_file",
    "move_file",
    "copy_file",
    "DEV_FORBIDDEN_PREFIXES",
    "DEV_FORBIDDEN_FILES",
    "DEV_MAX_FILE_CHARS",
    # Safety
    "confirm_action",
    "safe_read_json",
    "safe_write_json",
    "safe_read_text",
    "safe_write_text",
    "validate_path_safety",
    "sanitize_input",
    # Git
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
