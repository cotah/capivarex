"""
DevGit Bridge Service — Connects Dev Agent to GitHub Agent.

Flow:
1. User asks to create code + push to GitHub
2. Dev Agent generates structured code output (files list)
3. Bridge shows summary to user → asks for confirmation
4. On confirm → GitHub Agent creates repo + commits + pushes
5. Returns link to the repo

Supports batching for large projects (max 10 files per batch).

Preview: generates a temporary link where user can view code before pushing.
"""

import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

MAX_FILES_PER_BATCH = 10
MAX_LINES_PER_FILE = 500
CODE_PREVIEW_TTL = 600  # 10 minutes

# In-memory store for pending projects and previews
# In production → Redis
_pending_projects: Dict[str, Dict[str, Any]] = {}
_code_previews: Dict[str, Dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# 1. Generate code via Dev Agent (structured output)
# ---------------------------------------------------------------------------

async def generate_project(
    user_id: str,
    description: str,
    language: str = "python",
) -> Optional[Dict[str, Any]]:
    """
    Ask Dev Agent to generate a project as structured files.

    Returns:
        {
            "project_id": "abc123",
            "name": "task-api",
            "description": "FastAPI task manager",
            "language": "python",
            "files": [
                {"path": "main.py", "content": "...", "lines": 45},
                {"path": "models.py", "content": "...", "lines": 30},
            ],
            "total_files": 5,
            "total_lines": 120,
            "batches": 1,
        }
    """
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    prompt = f"""You are a senior developer. Generate a complete project based on this description:

DESCRIPTION: {description}
LANGUAGE: {language}

RULES:
- Generate ALL necessary files for a working project
- Include a README.md with setup instructions
- Include requirements.txt / package.json if applicable
- Each file must be complete and functional
- Max {MAX_FILES_PER_BATCH * 2} files, max {MAX_LINES_PER_FILE} lines per file
- Use best practices for the language

RESPOND ONLY WITH JSON (no markdown, no backticks):
{{
    "name": "project-name-kebab-case",
    "description": "One line description",
    "files": [
        {{"path": "relative/path/file.ext", "content": "full file content here"}},
        ...
    ]
}}"""

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=4000,
            temperature=0.3,
        )

        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

        data = json.loads(text)

    except (json.JSONDecodeError, Exception) as e:
        logger.error("DevGit generate failed: %s", e)
        return None

    files = data.get("files", [])
    if not files:
        return None

    # Add line counts
    for f in files:
        f["lines"] = f.get("content", "").count("\n") + 1

    project_id = _make_id(user_id, data.get("name", "project"))
    total_lines = sum(f["lines"] for f in files)
    total_files = len(files)
    batches = (total_files + MAX_FILES_PER_BATCH - 1) // MAX_FILES_PER_BATCH

    project = {
        "project_id": project_id,
        "user_id": user_id,
        "name": data.get("name", "my-project"),
        "description": data.get("description", description[:100]),
        "language": language,
        "files": files,
        "total_files": total_files,
        "total_lines": total_lines,
        "batches": batches,
        "current_batch": 0,
        "pushed_files": 0,
        "repo_url": "",
        "created_at": time.time(),
    }

    _pending_projects[project_id] = project

    # Also create preview
    preview_id = _create_preview(project_id, files)
    project["preview_id"] = preview_id

    return project


# ---------------------------------------------------------------------------
# 2. Summary message for user
# ---------------------------------------------------------------------------

def format_summary(project: Dict[str, Any], base_url: str = "") -> str:
    """Format a project summary for the user."""
    name = project["name"]
    total_files = project["total_files"]
    total_lines = project["total_lines"]
    language = project["language"]
    batches = project["batches"]
    preview_id = project.get("preview_id", "")

    file_list = ""
    for f in project["files"][:10]:
        file_list += f"  • `{f['path']}` — {f['lines']} linhas\n"
    if total_files > 10:
        file_list += f"  • ... e mais {total_files - 10} arquivos\n"

    summary = (
        f"🧠 Terminei de gerar o projeto **{name}**!\n\n"
        f"📁 **{total_files} arquivo{'s' if total_files > 1 else ''}** | "
        f"**{total_lines} linhas** | **{language.title()}**\n\n"
        f"{file_list}\n"
    )

    if batches > 1:
        summary += f"📦 Dividido em **{batches} lotes** de {MAX_FILES_PER_BATCH} arquivos\n\n"

    if preview_id and base_url:
        preview_url = f"{base_url}/api/v1/dev/preview/{preview_id}"
        summary += f"👀 [Ver código antes de subir]({preview_url})\n\n"

    summary += "Quer que eu suba para o seu GitHub?"

    return summary


# ---------------------------------------------------------------------------
# 3. Push to GitHub
# ---------------------------------------------------------------------------

async def push_to_github(
    project_id: str,
    repo_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Push a pending project to the user's GitHub.

    Returns: {"repo_url": "https://github.com/user/repo", "files_pushed": 5}
    """
    project = _pending_projects.get(project_id)
    if not project:
        return None

    user_id = project["user_id"]
    name = repo_name or project["name"]
    files = project["files"]

    # Get user's GitHub connection
    db = get_service("database")
    if not db or not db.is_initialized():
        return None

    github_conn = await db.get_github_connection(user_id)
    if not github_conn:
        return None

    access_token = github_conn.get("access_token", "")
    github_username = github_conn.get("github_username", "")

    if not access_token:
        return None

    import httpx

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
    }

    # Step 1: Create repo
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                "https://api.github.com/user/repos",
                json={
                    "name": name,
                    "description": project["description"],
                    "private": False,
                    "auto_init": True,
                },
                headers=headers,
            )
            repo_data = resp.json()

        if resp.status_code not in (201, 422):
            logger.error("GitHub create repo failed: %s", repo_data)
            return None

        # 422 = repo already exists, that's ok
        repo_url = f"https://github.com/{github_username}/{name}"

    except Exception as e:
        logger.error("GitHub create repo error: %s", e)
        return None

    # Step 2: Push files (using Contents API for simplicity)
    pushed = 0
    batch_start = project["current_batch"] * MAX_FILES_PER_BATCH
    batch_end = min(batch_start + MAX_FILES_PER_BATCH, len(files))
    batch_files = files[batch_start:batch_end]

    for f in batch_files:
        try:
            import base64
            content_b64 = base64.b64encode(f["content"].encode("utf-8")).decode("utf-8")

            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.put(
                    f"https://api.github.com/repos/{github_username}/{name}/contents/{f['path']}",
                    json={
                        "message": f"Add {f['path']}",
                        "content": content_b64,
                    },
                    headers=headers,
                )

            if resp.status_code in (200, 201):
                pushed += 1
            else:
                logger.warning("GitHub push file failed: %s %s", f["path"], resp.status_code)

        except Exception as e:
            logger.warning("GitHub push error for %s: %s", f["path"], e)

    # Update project state
    project["current_batch"] += 1
    project["pushed_files"] += pushed
    project["repo_url"] = repo_url

    result = {
        "repo_url": repo_url,
        "files_pushed": pushed,
        "total_pushed": project["pushed_files"],
        "total_files": project["total_files"],
        "batch": project["current_batch"],
        "batches": project["batches"],
        "done": project["current_batch"] >= project["batches"],
    }

    # Clean up if all batches done
    if result["done"]:
        _pending_projects.pop(project_id, None)

    return result


def format_push_result(result: Dict[str, Any]) -> str:
    """Format push result message."""
    if result["done"]:
        return (
            f"✅ Projeto subido para o GitHub!\n\n"
            f"🔗 **{result['repo_url']}**\n\n"
            f"📁 {result['total_pushed']} arquivo{'s' if result['total_pushed'] > 1 else ''} commitados. Tudo pronto!"
        )
    else:
        return (
            f"✅ Lote {result['batch']}/{result['batches']} subido! "
            f"({result['files_pushed']} arquivos)\n\n"
            f"Posso continuar com o próximo lote?"
        )


# ---------------------------------------------------------------------------
# 4. Code Preview
# ---------------------------------------------------------------------------

def _create_preview(project_id: str, files: List[Dict[str, Any]]) -> str:
    """Create a preview entry for code viewing."""
    preview_id = hashlib.md5(f"{project_id}{time.time()}".encode()).hexdigest()[:12]
    _code_previews[preview_id] = {
        "project_id": project_id,
        "files": files,
        "created_at": time.time(),
        "expires_at": time.time() + CODE_PREVIEW_TTL,
    }
    return preview_id


def get_preview(preview_id: str) -> Optional[Dict[str, Any]]:
    """Get preview data. Returns None if expired or not found."""
    preview = _code_previews.get(preview_id)
    if not preview:
        return None
    if preview["expires_at"] < time.time():
        _code_previews.pop(preview_id, None)
        return None
    return preview


def get_pending_project(project_id: str) -> Optional[Dict[str, Any]]:
    """Get a pending project by ID."""
    return _pending_projects.get(project_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_id(user_id: str, name: str) -> str:
    """Generate a unique project ID."""
    raw = f"{user_id}{name}{time.time()}"
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def cleanup_expired():
    """Clean up expired previews and old projects."""
    now = time.time()
    expired_previews = [k for k, v in _code_previews.items() if v["expires_at"] < now]
    for k in expired_previews:
        del _code_previews[k]

    old_projects = [k for k, v in _pending_projects.items() if now - v["created_at"] > 3600]
    for k in old_projects:
        del _pending_projects[k]
