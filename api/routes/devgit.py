"""
DevGit API Routes — Generate code + push to GitHub.

Routes:
- POST /api/v1/dev/generate — Generate project from description
- GET /api/v1/dev/preview/{preview_id} — View code in browser before pushing
- POST /api/v1/dev/push — Confirm and push to GitHub
- GET /api/v1/dev/project/{project_id} — Get project status
"""

import logging
import os
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from services.business.devgit_bridge import (
    format_push_result,
    format_summary,
    generate_project,
    get_pending_project,
    get_preview,
    push_to_github,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/generate")
async def dev_generate(request: Request):
    """
    Generate a project from a description.

    Body: {"user_id": "uuid", "description": "FastAPI task manager", "language": "python"}
    Returns: project summary + preview link
    """
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    user_id = body.get("user_id", "")
    description = body.get("description", "")
    language = body.get("language", "python")

    if not user_id or not description:
        raise HTTPException(status_code=400, detail="user_id and description required")

    project = await generate_project(user_id, description, language)
    if not project:
        raise HTTPException(status_code=500, detail="Failed to generate project")

    base_url = os.getenv(
        "API_BASE_URL",
        "https://capivarex-production.up.railway.app",
    )

    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "total_files": project["total_files"],
        "total_lines": project["total_lines"],
        "batches": project["batches"],
        "preview_url": f"{base_url}/api/v1/dev/preview/{project.get('preview_id', '')}",
        "summary": format_summary(project, base_url),
    }


@router.get("/preview/{preview_id}")
async def dev_preview(preview_id: str):
    """
    View generated code in browser — beautiful code preview page.

    Returns HTML page with syntax highlighting for all files.
    """
    preview = get_preview(preview_id)
    if not preview:
        return HTMLResponse(
            content=_error_page(
                "Preview expired or not found. Generate the project again."
            ),
            status_code=404,
        )

    files = preview.get("files", [])
    return HTMLResponse(content=_render_preview_page(files))


@router.post("/push")
async def dev_push(request: Request):
    """
    Push a generated project to GitHub.

    Body: {"project_id": "abc123", "repo_name": "optional-custom-name"}
    Returns: push result with repo URL
    """
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    project_id = body.get("project_id", "")
    repo_name = body.get("repo_name", "")

    if not project_id:
        raise HTTPException(status_code=400, detail="project_id required")

    project = get_pending_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found or expired")

    result = await push_to_github(project_id, repo_name)
    if not result:
        raise HTTPException(
            status_code=500,
            detail="Failed to push to GitHub. Check your GitHub connection.",
        )

    return {
        **result,
        "message": format_push_result(result),
    }


@router.get("/project/{project_id}")
async def dev_project_status(project_id: str):
    """Get status of a pending project."""
    project = get_pending_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return {
        "project_id": project["project_id"],
        "name": project["name"],
        "total_files": project["total_files"],
        "pushed_files": project["pushed_files"],
        "current_batch": project["current_batch"],
        "batches": project["batches"],
        "repo_url": project["repo_url"],
    }


# ---------------------------------------------------------------------------
# Code Preview Page (HTML)
# ---------------------------------------------------------------------------


def _render_preview_page(files: list) -> str:
    """Render a beautiful code preview page."""
    file_tabs = ""
    file_contents = ""

    for i, f in enumerate(files):
        path = f.get("path", "file.txt")
        content = f.get("content", "")
        lines = f.get("lines", content.count("\n") + 1)
        ext = path.rsplit(".", 1)[-1] if "." in path else "txt"
        active = "active" if i == 0 else ""

        # Escape HTML
        safe_content = (
            content.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )

        file_tabs += f'<button class="tab {active}" onclick="showFile({i})" data-idx="{i}">{path} <span class="lines">{lines}L</span></button>\n'
        file_contents += f'<div class="file-content {"" if i == 0 else "hidden"}" id="file-{i}"><pre><code class="language-{ext}">{safe_content}</code></pre></div>\n'

    total_files = len(files)
    total_lines = sum(f.get("lines", 0) for f in files)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Code Preview — Capivarex</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github-dark.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', monospace;
    background: #0d1117;
    color: #c9d1d9;
    min-height: 100vh;
  }}
  .header {{
    background: linear-gradient(135deg, #161b22 0%, #0d1117 100%);
    border-bottom: 1px solid #30363d;
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky;
    top: 0;
    z-index: 10;
  }}
  .header h1 {{
    font-size: 18px;
    font-weight: 600;
    color: #f0f6fc;
  }}
  .header h1 span {{ color: #58a6ff; }}
  .stats {{
    font-size: 13px;
    color: #8b949e;
  }}
  .stats b {{ color: #58a6ff; }}
  .logo {{
    font-size: 24px;
    margin-right: 12px;
  }}
  .tabs {{
    display: flex;
    gap: 2px;
    padding: 0 24px;
    background: #161b22;
    border-bottom: 1px solid #30363d;
    overflow-x: auto;
    white-space: nowrap;
  }}
  .tab {{
    padding: 10px 16px;
    font-size: 13px;
    color: #8b949e;
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    cursor: pointer;
    font-family: inherit;
    transition: all 0.15s;
  }}
  .tab:hover {{ color: #c9d1d9; background: #1c2128; }}
  .tab.active {{
    color: #f0f6fc;
    border-bottom-color: #58a6ff;
    background: #0d1117;
  }}
  .tab .lines {{
    font-size: 11px;
    color: #484f58;
    margin-left: 6px;
  }}
  .file-content {{
    padding: 0;
  }}
  .file-content.hidden {{ display: none; }}
  pre {{
    padding: 16px 24px;
    overflow-x: auto;
    font-size: 13px;
    line-height: 1.6;
  }}
  code {{ font-family: 'SF Mono', 'Fira Code', monospace; }}
  .powered {{
    text-align: center;
    padding: 24px;
    font-size: 12px;
    color: #484f58;
    border-top: 1px solid #30363d;
  }}
  .powered a {{ color: #58a6ff; text-decoration: none; }}
</style>
</head>
<body>
  <div class="header">
    <div style="display:flex;align-items:center;">
      <span class="logo">🧠</span>
      <h1><span>Capivarex</span> Code Preview</h1>
    </div>
    <div class="stats"><b>{total_files}</b> files | <b>{total_lines}</b> lines</div>
  </div>
  <div class="tabs">
    {file_tabs}
  </div>
  <div id="files-container">
    {file_contents}
  </div>
  <div class="powered">
    Generated by <a href="https://app.capivarex.com">Capivarex AI</a> — Your AI Life Assistant
  </div>
  <script>
    hljs.highlightAll();
    function showFile(idx) {{
      document.querySelectorAll('.file-content').forEach(el => el.classList.add('hidden'));
      document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
      document.getElementById('file-' + idx).classList.remove('hidden');
      document.querySelector('.tab[data-idx="' + idx + '"]').classList.add('active');
      hljs.highlightAll();
    }}
  </script>
</body>
</html>"""


def _error_page(message: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>Capivarex</title></head>
<body style="display:flex;justify-content:center;align-items:center;min-height:100vh;background:#0d1117;color:#c9d1d9;font-family:system-ui;">
<div style="text-align:center;">
<div style="font-size:48px;margin-bottom:16px;">⏰</div>
<p style="font-size:18px;">{message}</p>
<a href="https://app.capivarex.com" style="color:#58a6ff;margin-top:16px;display:block;">Go to Capivarex</a>
</div></body></html>"""
