"""
ACTIONS_JSON parser and validator for DEV Agent.

Handles:
- Extraction of ACTIONS_JSON from Claude responses
- Validation of action schema
- Normalization of action types and paths
- Dry-run reporting
"""

import json
import re
import logging
from typing import Dict, List, Tuple
from pathlib import Path

logger = logging.getLogger("unbx_bot.dev.actions")

# Action type aliases
DEV_ACTION_ALIASES = {
    "write": "overwrite_file",
    "overwrite": "overwrite_file",
    "append": "append_file",
    "replace": "replace_in_file",
    "create": "create_file",
}

# Valid action types after normalization
VALID_ACTION_TYPES = {"create_file", "overwrite_file", "append_file", "replace_in_file"}


def extract_actions_json(text: str) -> Dict:
    """
    Extract ACTIONS_JSON from text (LAST-BLOCK-WINS strategy).

    Handles:
    - Multiple ```json blocks (uses last valid one)
    - Loose JSON objects with "actions" key
    - Malformed/duplicated blocks

    Args:
        text: Text containing ACTIONS_JSON

    Returns:
        Parsed ACTIONS_JSON dict or empty dict
    """
    if not text:
        return {}

    candidates = []

    # 1) Collect all ```json ... ``` blocks
    json_blocks = re.findall(
        r"```json\s*(\{[\s\S]*?\})\s*```", text, flags=re.IGNORECASE
    )
    for block in json_blocks:
        try:
            obj = json.loads(block)
            if isinstance(obj, dict):
                candidates.append(obj)
        except Exception:
            pass

    # 2) Fallback: find loose JSON objects with "actions" key
    loose_matches = re.findall(
        r'(\{[^`]*?"actions"\s*:\s*\[[^\]]*\][^`]*?\})', text, flags=re.DOTALL
    )
    for match in loose_matches:
        try:
            obj = json.loads(match)
            if isinstance(obj, dict) and obj not in candidates:
                candidates.append(obj)
        except Exception:
            pass

    # 3) Aggressive fallback
    if not candidates:
        aggressive = re.search(r'(\{[\s\S]*"actions"[\s\S]*\})', text)
        if aggressive:
            try:
                obj = json.loads(aggressive.group(1))
                if isinstance(obj, dict):
                    candidates.append(obj)
            except Exception:
                pass

    # 4) LAST-BLOCK-WINS: prefer last valid schema
    for candidate in reversed(candidates):
        if is_valid_actions_schema(candidate):
            return candidate

    # 5) Fallback: last dict with "actions" key
    for candidate in reversed(candidates):
        if isinstance(candidate, dict) and "actions" in candidate:
            return candidate

    return {}


def is_valid_actions_schema(obj: Dict) -> bool:
    """
    Validate ACTIONS_JSON schema.

    Requirements:
    - Must be dict
    - Must have "actions" key
    - "actions" must be non-empty list
    - Each action must be dict with "type" and "path"

    Args:
        obj: Object to validate

    Returns:
        True if valid schema
    """
    if not isinstance(obj, dict):
        return False

    actions = obj.get("actions")
    if not isinstance(actions, list) or not actions:
        return False

    for act in actions:
        if not isinstance(act, dict):
            return False
        if not act.get("type") or not act.get("path"):
            return False

    return True


def normalize_action(action: Dict) -> Tuple[str, str, str, str, str]:
    """
    Normalize action type and path.

    Args:
        action: Action dict

    Returns:
        Tuple of (type_raw, type_normalized, path_raw, path_normalized, error_msg)
    """
    t = (action.get("type") or "").strip()
    path = (action.get("path") or "").strip()

    if not t or not path:
        return t, t, path, path, "missing type/path"

    # Normalize type using aliases
    t_norm = DEV_ACTION_ALIASES.get(t, t)

    # Normalize path
    path_norm = path.replace("\\", "/").lstrip("/")

    return t, t_norm, path, path_norm, ""


def dry_run_actions(actions_obj: Dict, base_dir: Path, bot_version: str) -> str:
    """
    Generate dry-run report showing impact of actions without applying them.

    Args:
        actions_obj: ACTIONS_JSON object
        base_dir: Base directory for resolving paths
        bot_version: Bot version string

    Returns:
        Formatted dry-run report
    """
    if not isinstance(actions_obj, dict):
        return "❌ ACTIONS_JSON invalid (not a dict)"

    actions = actions_obj.get("actions", [])
    if not isinstance(actions, list) or not actions:
        return "❌ No actions found in ACTIONS_JSON"

    lines = []
    lines.append(f"🧪 DRY-RUN ({bot_version}) — Preview of changes")
    lines.append("-" * 50)

    touched_files = []
    warnings = []

    for i, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            warnings.append(f"- Action {i}: invalid (not a dict)")
            continue

        t_raw, t_norm, path_raw, path_norm, err = normalize_action(action)
        if err:
            warnings.append(f"- Action {i}: {err}")
            continue

        # Check if type is valid
        if t_norm not in VALID_ACTION_TYPES:
            warnings.append(f"- Action {i}: unknown type '{t_raw}' — {path_norm}")
            continue

        # Resolve path
        try:
            from bot.utils import safe_path, is_forbidden_path

            reason = is_forbidden_path(path_norm)
            if reason:
                warnings.append(f"- Action {i}: REJECTED ({reason}) — {path_norm}")
                continue

            p = safe_path(path_norm, base_dir)
        except Exception:
            warnings.append(f"- Action {i}: REJECTED (unsafe path) — {path_norm}")
            continue

        exists = p.exists()
        size = p.stat().st_size if exists else 0

        # Format action description
        if t_norm == "create_file":
            desc = f"CREATE {path_norm}"
            if exists:
                desc += " (already exists, will skip)"
        elif t_norm == "overwrite_file":
            desc = f"OVERWRITE {path_norm}"
            if exists:
                desc += f" (current: {size} bytes)"
        elif t_norm == "append_file":
            desc = f"APPEND to {path_norm}"
            if exists:
                desc += f" (current: {size} bytes)"
        elif t_norm == "replace_in_file":
            find = action.get("find") or action.get("old_text", "")
            desc = f"REPLACE in {path_norm}"
            if not find:
                warnings.append(f"- Action {i}: missing 'find' field")
                continue
        else:
            desc = f"{t_norm} {path_norm}"

        lines.append(f"{i}. {desc}")
        touched_files.append(path_norm)

    lines.append("")
    lines.append(f"📁 Files to be touched: {len(set(touched_files))}")

    if warnings:
        lines.append("")
        lines.append("⚠️ WARNINGS:")
        lines.extend(warnings)

    return "\n".join(lines)


def dry_run_has_rejections(actions_obj: Dict, base_dir: Path) -> Tuple[bool, List[str]]:
    """
    Check if dry-run has any rejections.

    Args:
        actions_obj: ACTIONS_JSON object
        base_dir: Base directory for resolving paths

    Returns:
        Tuple of (has_rejections, list_of_reasons)
    """
    reasons = []

    if not isinstance(actions_obj, dict):
        return True, ["ACTIONS_JSON invalid (not a dict)"]

    actions = actions_obj.get("actions", [])
    if not isinstance(actions, list) or not actions:
        return True, ["No actions found in ACTIONS_JSON"]

    for i, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            reasons.append(f"Action {i}: INVALID (not a dict)")
            continue

        t_raw, t_norm, path_raw, path_norm, err = normalize_action(action)
        if err:
            reasons.append(f"Action {i}: INVALID ({err})")
            continue

        # Check type
        if t_norm not in VALID_ACTION_TYPES:
            reasons.append(
                f"Action {i}: REJECTED (unknown type: '{t_raw}') — {path_norm}"
            )
            continue

        # Check path
        try:
            from bot.utils import safe_path, is_forbidden_path

            reason = is_forbidden_path(path_norm)
            if reason:
                reasons.append(f"Action {i}: REJECTED ({reason}) — {path_norm}")
                continue

            _ = safe_path(path_norm, base_dir)
        except Exception:
            reasons.append(f"Action {i}: REJECTED (unsafe path) — {path_norm}")
            continue

    return (len(reasons) > 0), reasons
