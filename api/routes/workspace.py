"""
Workspace Routes (Refactored)
CRUD de projetos + operacoes Git.

Uses services (get_service) instead of direct imports from services/.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_current_user
from api.routes._helpers import _get_db, _get_service_or_503
from models.schemas import (
    CreateProjectRequest,
    GitCloneRequest,
    GitCommitRequest,
    GitInitRequest,
    GitPushRequest,
    GitRemoteRequest,
    Project,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------


def _get_file_manager():
    """Get the file manager service from the registry."""
    return _get_service_or_503("file_manager", "File manager")


def _git_op(operation: str, *args, **kwargs) -> Any:
    """Execute a git service method, converting RuntimeError to HTTP 500.

    Args:
        operation: Name of the method on the git service.
        *args, **kwargs: Forwarded to the service method.
    """
    git_svc = _get_service_or_503("git", "Git")
    try:
        return getattr(git_svc, operation)(*args, **kwargs)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============================================
# PROJECT CRUD
# ============================================


@router.get("/projects", response_model=List[Project])
async def list_projects(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Lista todos os projetos do usuario."""
    db = _get_db()
    response = (
        db.table("projects")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .execute()
    )
    return response.data


@router.post("/projects", response_model=Project, status_code=201)
async def create_project(
    request: CreateProjectRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cria um novo projeto e sua estrutura de diretorios."""
    db = _get_db()
    fm = _get_file_manager()

    # Verifica duplicidade de nome
    existing = (
        db.table("projects")
        .select("id")
        .eq("user_id", current_user["id"])
        .eq("name", request.name)
        .execute()
    )

    if existing.data:
        raise HTTPException(
            status_code=400, detail="Project with this name already exists"
        )

    user_id = str(current_user["id"])

    # Cria diretorio do projeto usando o file_manager
    try:
        fm.create_file(
            user_id=user_id,
            path=f"{request.name}/.gitkeep",
            content="",
        )
    except FileExistsError:
        pass

    # Salva no banco
    project_data: Dict[str, Any] = {
        "user_id": current_user["id"],
        "name": request.name,
        "description": request.description or "",
        "language": request.language or "",
    }

    response = db.table("projects").insert(project_data).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create project")

    return response.data[0]


@router.get("/projects/{project_id}", response_model=Project)
async def get_project(
    project_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Obtem detalhes de um projeto."""
    db = _get_db()
    response = (
        db.table("projects")
        .select("*")
        .eq("id", project_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Project not found")

    return response.data[0]


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    """Remove um projeto."""
    db = _get_db()

    response = (
        db.table("projects")
        .select("id")
        .eq("id", project_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Project not found")

    db.table("projects").delete().eq("id", project_id).execute()

    return {"message": "Project deleted successfully"}


# ============================================
# GIT OPERATIONS
# ============================================


@router.post("/git/init")
async def git_init(
    request: GitInitRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Inicializa um repositorio Git no diretorio do projeto."""
    return _git_op("init_repo", project_path=request.project_path)


@router.post("/git/commit")
async def git_commit(
    request: GitCommitRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cria um commit no repositorio."""
    return _git_op(
        "commit",
        project_path=request.project_path,
        message=request.message,
        files=getattr(request, "files", None),
    )


@router.get("/git/status")
async def git_status(
    project_path: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna o status do repositorio."""
    return _git_op("get_status", project_path=project_path)


@router.get("/git/log")
async def git_log(
    project_path: str,
    limit: int = 10,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna o log de commits."""
    return _git_op("get_log", project_path=project_path, limit=limit)


@router.post("/git/branch")
async def git_create_branch(
    project_path: str,
    branch_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cria uma nova branch."""
    return _git_op("create_branch", project_path=project_path, branch_name=branch_name)


@router.post("/git/checkout")
async def git_checkout(
    project_path: str,
    branch_name: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Faz checkout de uma branch."""
    return _git_op(
        "checkout_branch", project_path=project_path, branch_name=branch_name
    )


@router.post("/git/clone")
async def git_clone(
    request: GitCloneRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Clona um repositorio remoto."""
    return _git_op(
        "clone_repo",
        repo_url=request.repo_url,
        target_path=request.target_path,
        user_github_token=getattr(request, "github_token", None),
    )


@router.post("/git/remote")
async def git_add_remote(
    request: GitRemoteRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Adiciona ou atualiza um remote."""
    return _git_op(
        "add_remote",
        project_path=request.project_path,
        remote_name=request.remote_name,
        remote_url=request.remote_url,
        user_github_token=getattr(request, "github_token", None),
    )


@router.post("/git/push")
async def git_push(
    request: GitPushRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Push para o remote."""
    return _git_op(
        "push",
        project_path=request.project_path,
        remote_name=getattr(request, "remote_name", "origin"),
        branch_name=getattr(request, "branch_name", None),
        user_github_token=getattr(request, "github_token", None),
    )


@router.post("/git/pull")
async def git_pull(
    project_path: str,
    remote_name: str = "origin",
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Pull do remote."""
    return _git_op(
        "pull",
        project_path=project_path,
        remote_name=remote_name,
    )
