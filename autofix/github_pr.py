"""
AutoFix GitHub PR Module
========================
Creates GitHub Pull Requests for approved AutoFix patches.

Flow:
  1. patch is approved via Telegram (admin clicks ✅ Aprovar)
  2. autofix_notifier calls create_pr_for_patch()
  3. This module:
     a. Clones the repo to /tmp/autofix_workspace/<ticket_id>
     b. Creates a branch: autofix/<ticket_id>-<error_type>
     c. Applies the diff from the patch
     d. Commits and pushes the branch
     e. Opens a PR via GitHub REST API
     f. Returns the PR URL

Environment variables required (already in Railway):
  GITHUB_TOKEN          — personal access token (repo scope)
  GITHUB_REPO_OWNER     — e.g. "cotah"  (auto-detected from remote URL)
  GITHUB_REPO_NAME      — e.g. "capivarex" (auto-detected from remote URL)
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
import requests

logger = logging.getLogger("capivarex.autofix.github_pr")

# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _get_token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError("GITHUB_TOKEN environment variable is not set")
    return token


def _get_repo_owner_name() -> tuple[str, str]:
    """
    Returns (owner, repo_name) by reading GITHUB_REPO_OWNER / GITHUB_REPO_NAME
    env vars, or by parsing GITHUB_REPO_URL, or by falling back to the
    well-known cotah/capivarex default.
    """
    owner = os.environ.get("GITHUB_REPO_OWNER", "")
    name = os.environ.get("GITHUB_REPO_NAME", "")
    if owner and name:
        return owner, name

    repo_url = os.environ.get("GITHUB_REPO_URL", "")
    if repo_url:
        m = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", repo_url)
        if m:
            return m.group(1), m.group(2).removesuffix(".git")

    # Hard-coded fallback (safe — this is the only repo we deploy)
    return "cotah", "capivarex"


# ---------------------------------------------------------------------------
# Core PR creation
# ---------------------------------------------------------------------------

def create_pr_for_patch(patch: dict) -> dict:
    """
    Given an *approved* patch dict, clones the repo, applies the diff,
    pushes a branch, and opens a GitHub PR.

    Returns a result dict:
        {
            "success": bool,
            "pr_url": str | None,
            "branch": str | None,
            "error": str | None,
        }
    """
    ticket_id = patch.get("ticket_id", "unknown")
    error_type = patch.get("error_type", "unknown").lower().replace(" ", "_")
    diff_text: str = patch.get("diff", "")
    target_files: list = patch.get("target_files", [])

    if not diff_text and not target_files:
        return {"success": False, "pr_url": None, "branch": None,
                "error": "Patch has no diff or target_files — nothing to apply"}

    token = _get_token()
    owner, repo_name = _get_repo_owner_name()
    branch_name = f"autofix/{ticket_id}-{error_type}"[:72]  # GitHub branch name limit

    with tempfile.TemporaryDirectory(prefix="autofix_") as tmpdir:
        workspace = Path(tmpdir) / "repo"
        try:
            _clone_repo(owner, repo_name, token, workspace)
            _create_branch(workspace, branch_name)
            applied = _apply_diff(workspace, diff_text, target_files)
            if not applied:
                return {"success": False, "pr_url": None, "branch": branch_name,
                        "error": "Diff could not be applied cleanly — manual review needed"}
            _commit_and_push(workspace, branch_name, ticket_id, error_type, token,
                             owner, repo_name)
            pr_url = _open_pull_request(owner, repo_name, token, branch_name,
                                        ticket_id, error_type, patch)
            logger.info("AutoFix PR created: %s", pr_url)
            return {"success": True, "pr_url": pr_url, "branch": branch_name, "error": None}

        except Exception as exc:
            logger.exception("create_pr_for_patch failed for ticket %s", ticket_id)
            return {"success": False, "pr_url": None, "branch": branch_name,
                    "error": str(exc)}


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd), capture_output=True, text=True, check=check
    )


def _clone_repo(owner: str, repo: str, token: str, dest: Path) -> None:
    auth_url = f"https://{token}@github.com/{owner}/{repo}.git"
    _run(["git", "clone", "--depth", "1", auth_url, str(dest)], cwd=dest.parent)
    _run(["git", "config", "user.email", "autofix@capivarex.ai"], cwd=dest)
    _run(["git", "config", "user.name", "CapivaraX AutoFix"], cwd=dest)


def _create_branch(repo_path: Path, branch_name: str) -> None:
    _run(["git", "checkout", "-b", branch_name], cwd=repo_path)


def _apply_diff(repo_path: Path, diff_text: str, target_files: list) -> bool:
    """
    Tries to apply the diff via `git apply`.
    Falls back to writing target_files content directly if diff is a
    full-file replacement (patch_type == "full_replace").
    Returns True if something was changed.
    """
    if not diff_text or diff_text.strip() == "":
        return False

    # Write diff to a temp file and try git apply
    diff_file = repo_path / ".autofix_patch.diff"
    diff_file.write_text(diff_text, encoding="utf-8")

    result = _run(
        ["git", "apply", "--check", str(diff_file)],
        cwd=repo_path,
        check=False,
    )
    if result.returncode == 0:
        _run(["git", "apply", str(diff_file)], cwd=repo_path)
        diff_file.unlink(missing_ok=True)
        return True

    # git apply --check failed — try with --reject (partial apply)
    result2 = _run(
        ["git", "apply", "--reject", str(diff_file)],
        cwd=repo_path,
        check=False,
    )
    diff_file.unlink(missing_ok=True)
    if result2.returncode == 0:
        return True

    logger.warning("git apply failed: %s", result.stderr)
    return False


def _commit_and_push(
    repo_path: Path,
    branch_name: str,
    ticket_id: str,
    error_type: str,
    token: str,
    owner: str,
    repo: str,
) -> None:
    _run(["git", "add", "-A"], cwd=repo_path)
    commit_msg = (
        f"fix(autofix): resolve {error_type} — ticket {ticket_id}\n\n"
        f"Auto-generated patch by CapivaraX AutoFix.\n"
        f"Approved by admin via Telegram.\n"
        f"Ticket: {ticket_id}"
    )
    _run(["git", "commit", "-m", commit_msg], cwd=repo_path)

    auth_url = f"https://{token}@github.com/{owner}/{repo}.git"
    _run(["git", "push", auth_url, branch_name], cwd=repo_path)


# ---------------------------------------------------------------------------
# GitHub REST API — open PR
# ---------------------------------------------------------------------------

def _open_pull_request(
    owner: str,
    repo: str,
    token: str,
    branch_name: str,
    ticket_id: str,
    error_type: str,
    patch: dict,
) -> str:
    """Opens a PR via GitHub REST API and returns the PR HTML URL."""
    notes = patch.get("notes", "")
    checklist = patch.get("validation_checklist", [])
    checklist_md = "\n".join(f"- [ ] {item}" for item in checklist) if checklist else "- [ ] Review diff carefully"

    body = (
        f"## AutoFix — {error_type}\n\n"
        f"**Ticket ID:** `{ticket_id}`\n"
        f"**Error type:** `{error_type}`\n"
        f"**Top frame:** `{patch.get('top_frame', 'unknown')}`\n\n"
        f"### What this patch does\n{notes or 'See diff below.'}\n\n"
        f"### Validation checklist\n{checklist_md}\n\n"
        f"> This PR was auto-generated by CapivaraX AutoFix and approved by the admin via Telegram.\n"
        f"> **Always review the diff before merging.**"
    )

    payload = {
        "title": f"[AutoFix] {error_type} — ticket {ticket_id}",
        "head": branch_name,
        "base": "main",
        "body": body,
        "draft": False,
    }

    resp = requests.post(
        f"https://api.github.com/repos/{owner}/{repo}/pulls",
        json=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        timeout=15,
    )

    if resp.status_code not in (200, 201):
        raise RuntimeError(
            f"GitHub API returned {resp.status_code}: {resp.text[:300]}"
        )

    return resp.json()["html_url"]
