"""
Dev Routes (Refactored)
Endpoints for Dev Agent (code generation, sandbox execution, and file management).

Uses services (get_service) instead of direct imports from services/.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from api.dependencies import get_current_user
from services.core import get_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------

def _get_code_executor():
    """Get the code executor service from the registry."""
    svc = get_service("code_executor")
    if svc is None:
        raise HTTPException(status_code=503, detail="Code executor service unavailable")
    return svc


def _get_file_manager():
    """Get the file manager service from the registry."""
    svc = get_service("file_manager")
    if svc is None:
        raise HTTPException(status_code=503, detail="File manager service unavailable")
    return svc


def _get_anthropic_service():
    """Get the Anthropic service from the registry."""
    svc = get_service("anthropic")
    if svc is None:
        raise HTTPException(status_code=503, detail="Anthropic service unavailable")
    return svc


def _extract_code(content: str) -> str:
    """Extract code from a markdown-fenced block if present."""
    if not content:
        return ""
    match = re.search(r"```(?:python)?\s*([\s\S]*?)\s*```", content, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return content.strip()


# ============================================
# SCHEMAS
# ============================================

class GenerateRequest(BaseModel):
    prompt: str
    model: Optional[str] = "claude-sonnet-4-5-20250929"
    language: Optional[str] = "python"
    context: Optional[str] = None


class ExecuteRequest(BaseModel):
    code: str
    timeout_seconds: Optional[int] = 10


class GenerateAndExecuteRequest(BaseModel):
    prompt: str
    model: Optional[str] = "claude-sonnet-4-5-20250929"
    language: Optional[str] = "python"
    context: Optional[str] = None
    timeout_seconds: Optional[int] = 10


class TestRequest(BaseModel):
    code: str
    tests: List[str]
    timeout_seconds: Optional[int] = 10


class FileCreateRequest(BaseModel):
    path: str
    content: Optional[str] = ""


class FileUpdateRequest(BaseModel):
    path: str
    content: str


# ============================================
# CLAUDE CODE GENERATION
# ============================================

@router.post("/generate")
async def generate_code(
    request: GenerateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Gera codigo com Claude a partir de um prompt.
    """
    anthropic_svc = _get_anthropic_service()

    system_prompt = (
        f"You are an expert {request.language} developer. "
        f"Generate clean, efficient, well-documented code."
    )

    if request.context:
        system_prompt += f" Context: {request.context}"

    system_prompt += "\n\nIMPORTANT: Return ONLY the code, without markdown code blocks or explanations."

    model_id = os.environ.get("CLAUDE_MODEL", "claude-sonnet-4-5-20250929")

    try:
        generated_code = await anthropic_svc.generate_code(
            prompt=request.prompt,
            model=model_id,
            system_prompt=system_prompt,
        )
    except Exception as e:
        logger.exception("Code generation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Code generation failed: {e}")

    generated_code = generated_code.strip()
    code = _extract_code(generated_code)
    if code != generated_code:
        logger.debug("generate_code: extracted fenced code block from model output")

    return {"code": code, "model": model_id}


# ============================================
# SANDBOX EXECUTION
# ============================================

@router.post("/execute")
async def execute_code(
    request: ExecuteRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Executa codigo Python em sandbox isolado por usuario.
    """
    executor = _get_code_executor()
    user_id = str(current_user["id"])
    result = await asyncio.to_thread(
        executor.execute_python,
        user_id=user_id,
        code=request.code,
        timeout_seconds=request.timeout_seconds or 10,
        python_executable="python",
    )
    return result


@router.post("/generate-and-execute")
async def generate_and_execute(
    request: GenerateAndExecuteRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Workflow completo: gera codigo e executa em sandbox.
    """
    # Generate
    gen_result = await generate_code(
        GenerateRequest(
            prompt=request.prompt,
            model=request.model,
            language=request.language,
            context=request.context,
        ),
        current_user=current_user,
    )

    # Extra cleanup: remove markdown if still present
    code = gen_result.get("code", "")
    if "```" in code:
        lines = code.split("\n")
        code_lines: List[str] = []
        in_code_block = False
        for line in lines:
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block or not line.strip().startswith("```"):
                code_lines.append(line)
        code = "\n".join(code_lines).strip()
        gen_result["code"] = code
        logger.debug("generate_and_execute: stripped markdown fences after generate_code")

    # Execute
    executor = _get_code_executor()
    user_id = str(current_user["id"])
    exec_result = executor.execute_python(
        user_id=user_id,
        code=code,
        timeout_seconds=request.timeout_seconds or 10,
        python_executable="python",
    )

    return {
        "code": code,
        "execution": exec_result,
        "model": gen_result.get("model", request.model),
    }


@router.post("/test")
async def test_code(
    request: TestRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Executa casos de teste simples concatenando o codigo + testes.
    Cada item em tests deve ser um bloco Python.
    """
    combined = (
        request.code
        + "\n\n# ================= TESTS =================\n\n"
        + "\n\n".join(request.tests)
    )

    executor = _get_code_executor()
    user_id = str(current_user["id"])
    result = executor.execute_python(
        user_id=user_id,
        code=combined,
        timeout_seconds=request.timeout_seconds or 10,
        python_executable="python",
    )

    passed = result.get("exit_code", 1) == 0
    return {"passed": passed, **result}


# ============================================
# FILE MANAGEMENT
# ============================================

@router.get("/files/list")
async def list_files(
    dir: str = Query("", description="Relative directory inside user projects"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """List files in the user's project directory."""
    fm = _get_file_manager()
    user_id = str(current_user["id"])
    return fm.list_files(user_id=user_id, relative_dir=dir)


@router.post("/files/create")
async def create_file(
    request: FileCreateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Create a file in the user's project directory."""
    fm = _get_file_manager()
    user_id = str(current_user["id"])
    return fm.create_file(user_id=user_id, path=request.path, content=request.content or "")


@router.get("/files/read")
async def read_file(
    path: str = Query(..., description="Relative file path inside user projects"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Read a file from the user's project directory."""
    fm = _get_file_manager()
    user_id = str(current_user["id"])
    return fm.read_file(user_id=user_id, path=path)


@router.put("/files/update")
async def update_file(
    request: FileUpdateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Update a file in the user's project directory."""
    fm = _get_file_manager()
    user_id = str(current_user["id"])
    return fm.update_file(user_id=user_id, path=request.path, content=request.content)


@router.delete("/files/delete")
async def delete_file(
    path: str = Query(..., description="Relative file path inside user projects"),
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Delete a file from the user's project directory."""
    fm = _get_file_manager()
    user_id = str(current_user["id"])
    return fm.delete_file(user_id=user_id, path=path)
