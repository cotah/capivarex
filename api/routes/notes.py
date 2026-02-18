"""
Notes Routes (Refactored)
CRUD de notas do usuario.

Uses services (get_service) instead of direct imports from services/.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_current_user
from models.schemas import Note, NoteCreate, NoteUpdate
from services.core import get_service

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Service helpers
# ---------------------------------------------------------------------------

def _get_db():
    """Get the Supabase client from the database service."""
    db_service = get_service("database")
    if db_service is None:
        raise HTTPException(status_code=503, detail="Database service unavailable")
    return db_service.get_client()


# ============================================
# NOTES CRUD
# ============================================

@router.get("/", response_model=List[Note])
async def list_notes(
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Lista todas as notas do usuario autenticado."""
    db = _get_db()
    response = (
        db.table("notes")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("updated_at", desc=True)
        .execute()
    )
    return response.data


@router.post("/", response_model=Note, status_code=status.HTTP_201_CREATED)
async def create_note(
    data: NoteCreate,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Cria uma nova nota."""
    db = _get_db()
    new_note: Dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "user_id": current_user["id"],
        "title": data.title,
        "content": data.content,
    }

    response = db.table("notes").insert(new_note).execute()

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to create note")

    return response.data[0]


@router.get("/{note_id}", response_model=Note)
async def get_note(
    note_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Retorna uma nota especifica."""
    db = _get_db()
    response = (
        db.table("notes")
        .select("*")
        .eq("id", note_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Note not found")

    return response.data[0]


@router.put("/{note_id}", response_model=Note)
async def update_note(
    note_id: str,
    data: NoteUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, Any]:
    """Atualiza uma nota existente."""
    db = _get_db()

    # Verifica se a nota pertence ao usuario
    existing = (
        db.table("notes")
        .select("id")
        .eq("id", note_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Note not found")

    update_data: Dict[str, Any] = {}
    if data.title is not None:
        update_data["title"] = data.title
    if data.content is not None:
        update_data["content"] = data.content

    if not update_data:
        raise HTTPException(status_code=400, detail="No data to update")

    response = (
        db.table("notes")
        .update(update_data)
        .eq("id", note_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=500, detail="Failed to update note")

    return response.data[0]


@router.delete("/{note_id}")
async def delete_note(
    note_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
) -> Dict[str, str]:
    """Deleta uma nota."""
    db = _get_db()

    existing = (
        db.table("notes")
        .select("id")
        .eq("id", note_id)
        .eq("user_id", current_user["id"])
        .execute()
    )

    if not existing.data:
        raise HTTPException(status_code=404, detail="Note not found")

    db.table("notes").delete().eq("id", note_id).execute()

    return {"message": "Note deleted successfully"}
