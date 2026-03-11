"""
Action executor for DEV Agent.

Handles:
- Applying actions with rollback support
- Backup management
- Receipt generation for audit
"""

import os
import json
import logging
from pathlib import Path
from typing import Dict, List
from datetime import datetime

from bot.utils import (
    safe_path,
    is_forbidden_path,
    read_text_safe,
    write_text_safe,
    backup_file,
    DEV_MAX_FILE_CHARS,
)
from bot.dev.actions import normalize_action, VALID_ACTION_TYPES

logger = logging.getLogger("unbx_bot.dev.executor")


def _validate_action(
    action: dict, index: int, base_dir: Path
) -> tuple:
    """
    Validates a single action. Returns (normalized_tuple, error_str).
    normalized_tuple = (index, t_raw, t_norm, path_norm, action) or None on error.
    """
    if not isinstance(action, dict):
        return None, f"❌ Action {index}: invalid (not a dict)"

    t_raw, t_norm, _, path_norm, err = normalize_action(action)
    if err:
        return None, f"❌ Action {index}: {err}"

    if t_norm not in VALID_ACTION_TYPES:
        return None, f"❌ Action {index}: unknown type '{t_raw}'"

    reason = is_forbidden_path(path_norm)
    if reason:
        return None, f"❌ Action {index}: forbidden path: {path_norm} ({reason})"

    try:
        safe_path(path_norm, base_dir)
    except Exception as e:
        return None, f"❌ Action {index}: unsafe path: {path_norm} ({e})"

    content = action.get("content", "")
    if isinstance(content, str) and len(content) > DEV_MAX_FILE_CHARS:
        return None, f"❌ Action {index}: content too large ({len(content)} chars)"

    return (index, t_raw, t_norm, path_norm, action), None


def _snapshot_file(
    path_norm: str, base_dir: Path,
    originals: Dict[str, str], created: Dict[str, bool],
) -> None:
    """Creates a snapshot for a single file if not already captured."""
    if path_norm in originals or path_norm in created:
        return
    p = safe_path(path_norm, base_dir)
    if p.exists():
        originals[path_norm] = read_text_safe(p)
    else:
        created[path_norm] = True


def _rollback(
    originals: Dict[str, str], created: Dict[str, bool], base_dir: Path,
) -> None:
    """Rollback all changes: restore originals and remove created files."""
    for path_norm, old_content in originals.items():
        try:
            p = safe_path(path_norm, base_dir)
            write_text_safe(p, old_content)
        except Exception:
            pass

    for path_norm in created:
        try:
            p = safe_path(path_norm, base_dir)
            if p.exists():
                p.unlink()
        except Exception:
            pass


def _execute_single_action(
    i: int, t_raw: str, t_norm: str, path_norm: str, action: dict,
    base_dir: Path, backup_dir: Path, report: List[str], touched: List[str],
) -> None:
    """Executes a single action (create/overwrite/append/replace). Raises on error."""
    p = safe_path(path_norm, base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    backup_file(p, backup_dir)
    touched.append(path_norm)

    if t_norm == "create_file":
        if p.exists():
            report.append(f"⚠️ Action {i}: create_file ignored (already exists): {path_norm}")
            logger.info(f"create_file ignored | index={i} | path={path_norm}")
        else:
            write_text_safe(p, action.get("content", "") or "")
            report.append(f"✅ Action {i}: create_file: {path_norm}")
            logger.info(f"create_file ok | index={i} | path={path_norm}")

    elif t_norm == "overwrite_file":
        write_text_safe(p, action.get("content", "") or "")
        report.append(f"✅ Action {i}: overwrite_file: {path_norm}")
        logger.info(f"overwrite_file ok | index={i} | path={path_norm}")

    elif t_norm == "append_file":
        cur = read_text_safe(p) if p.exists() else ""
        write_text_safe(p, cur + (action.get("content", "") or ""))
        report.append(f"✅ Action {i}: append_file: {path_norm}")
        logger.info(f"append_file ok | index={i} | path={path_norm}")

    elif t_norm == "replace_in_file":
        find = action.get("find") or action.get("old_text", "")
        replace = action.get("replace") or action.get("new_text", "")

        if not isinstance(find, str) or find == "":
            raise ValueError("replace_in_file: 'find' is empty")
        if not p.exists():
            raise FileNotFoundError("replace_in_file: file does not exist")

        file_text = read_text_safe(p)
        if find not in file_text:
            raise ValueError("replace_in_file: text not found")

        write_text_safe(p, file_text.replace(find, str(replace), 1))
        report.append(f"✅ Action {i}: replace_in_file: {path_norm}")
        logger.info(f"replace_in_file ok | index={i} | path={path_norm}")

    else:
        raise ValueError(f"unknown type: {t_raw} (normalized: {t_norm})")


def apply_actions(
    actions_obj: Dict,
    base_dir: Path,
    backup_dir: Path,
    bot_version: str
) -> str:
    """
    Apply actions with rollback support (robust executor).

    Features:
    - Pre-validation
    - Automatic backups
    - Transactional (rollback on any failure)
    - Detailed logging

    Args:
        actions_obj: ACTIONS_JSON object
        base_dir: Base directory for resolving paths
        backup_dir: Directory for backups
        bot_version: Bot version string

    Returns:
        Formatted report string
    """
    if not isinstance(actions_obj, dict):
        return "❌ ACTIONS_JSON invalid (not a dict)"

    actions = actions_obj.get("actions", [])
    if not isinstance(actions, list) or not actions:
        return "❌ No actions found in ACTIONS_JSON"

    report = [f"🛡️ Applying actions ({bot_version} with dry-run + backups)..."]
    logger.info(f"apply_actions start | actions={len(actions)}")

    originals: Dict[str, str] = {}
    created: Dict[str, bool] = {}
    touched: List[str] = []

    # Pre-validation + snapshot
    normalized_actions = []
    for i, action in enumerate(actions, start=1):
        result, error = _validate_action(action, i, base_dir)
        if error:
            report.append(error)
            logger.error(f"action validation failed | index={i}")
            return "\n".join(report)
        normalized_actions.append(result)
        _snapshot_file(result[3], base_dir, originals, created)

    # Apply actions
    for (i, t_raw, t_norm, path_norm, action) in normalized_actions:
        try:
            _execute_single_action(
                i, t_raw, t_norm, path_norm, action,
                base_dir, backup_dir, report, touched,
            )
        except Exception as e:
            report.append(f"❌ Action {i}: error applying {t_norm} on {path_norm}: {e}")
            logger.error(f"apply failed | index={i} | type={t_norm} | path={path_norm} | err={e}")

            _rollback(originals, created, base_dir)
            report.append(f"↩️ Rollback executed: changes reverted ({bot_version})")
            logger.info("rollback executed")
            return "\n".join(report)

    # Success
    report.append(f"🎉 All actions applied successfully ({bot_version})")
    report.append(f"📌 Files touched: {len(set(touched))}")
    logger.info(f"apply_actions success | touched={len(set(touched))}")
    return "\n".join(report)


def generate_receipt(
    source: str,
    actions_obj: Dict,
    dry_run_report: str,
    apply_report: str,
    success: bool,
    errors: List[str],
    files_touched: List[str],
    backups_created: List[str],
    rejections: List[str],
    receipts_dir: Path,
    bot_version: str,
    tenant_id: str,
    user_id: str
) -> str:
    """
    Generate audit receipt for action application.

    Args:
        source: Source of actions (e.g., "cli", "telegram")
        actions_obj: ACTIONS_JSON object
        dry_run_report: Dry-run report text
        apply_report: Apply report text
        success: Whether application was successful
        errors: List of error messages
        files_touched: List of touched file paths
        backups_created: List of backup file paths
        rejections: List of rejection reasons
        receipts_dir: Directory to save receipts
        bot_version: Bot version string
        tenant_id: Tenant ID
        user_id: User ID

    Returns:
        Path to generated receipt file
    """
    now = datetime.now()
    receipt_id = now.strftime("%Y%m%d_%H%M%S") + f"_{os.getpid()}"

    actions = actions_obj.get("actions", []) if isinstance(actions_obj, dict) else []

    receipt = {
        "receipt_id": receipt_id,
        "created_at": now.isoformat(),
        "bot_version": bot_version,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "source": source,
        "actions_total": len(actions),
        "actions_validated": len([
            a for a in actions
            if isinstance(a, dict) and a.get("type") and a.get("path")
        ]),
        "actions_rejected": rejections,
        "files_touched": list(set(files_touched)),
        "backups_created": list(set(backups_created)),
        "dry_run_report": dry_run_report,
        "apply_report": apply_report,
        "success": success,
        "errors": errors
    }

    receipts_dir.mkdir(parents=True, exist_ok=True)
    receipt_file = receipts_dir / f"{receipt_id}_receipt.json"

    try:
        with open(receipt_file, 'w', encoding='utf-8') as f:
            json.dump(receipt, f, indent=2, ensure_ascii=False)
        logger.info(f"receipt generated | id={receipt_id} | success={success}")
    except Exception as e:
        logger.error(f"Failed to generate receipt: {e}")

    return str(receipt_file)
