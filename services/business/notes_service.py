# -*- coding: utf-8 -*-
"""
services/business/notes_service.py
====================================
Notas pessoais persistentes via Supabase.

Diferença vs ReminderService:
- ReminderService → "me lembra às 10h de fazer X" (tem data de disparo)
- NotesService    → "anota que preciso ligar ao dentista" (texto livre, sem data)

Funcionalidades:
- Criar nota (texto livre, título auto-gerado das primeiras palavras)
- Listar notas (fixadas primeiro, depois por data DESC)
- Buscar notas por texto (título + conteúdo)
- Fixar nota (pinned) para aparecer sempre no topo
- Arquivar nota (some da listagem normal, mas não é apagada)
- Apagar nota permanentemente
- Apagar todas as notas

Tabela Supabase esperada:
    CREATE TABLE notes (
        id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id     TEXT NOT NULL,
        chat_id     TEXT NOT NULL,
        title       TEXT NOT NULL,
        content     TEXT NOT NULL,
        tags        TEXT[] DEFAULT '{}',
        pinned      BOOLEAN DEFAULT FALSE,
        archived    BOOLEAN DEFAULT FALSE,
        created_at  TIMESTAMPTZ DEFAULT NOW(),
        updated_at  TIMESTAMPTZ DEFAULT NOW()
    );
    CREATE INDEX notes_user_idx ON notes(user_id);
"""

import asyncio
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.core import BaseService, ServiceUnavailableError, register_service

NOTES_TABLE = "notes"
MAX_CONTENT_LENGTH = 2000
MAX_TITLE_LENGTH = 100
MAX_NOTES_PER_USER = 500

# Palavras a ignorar ao gerar título automático
_STOP_WORDS = {
    "anota", "anote", "escreve", "salva", "guarda", "nota", "que", "de",
    "o", "a", "os", "as", "um", "uma", "para", "por", "com", "em",
    "tenho", "preciso", "devo", "quero", "vou", "me", "minha", "meu",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _auto_title(content: str) -> str:
    """
    Gera título curto e significativo a partir do conteúdo.

    Exemplos:
        "Ligar ao dentista amanhã"            → "Ligar ao dentista amanhã"
        "Anota: renovar seguro carro em março" → "Renovar seguro carro em março"
    """
    # Remove prefixos de comando
    cleaned = re.sub(
        r"^(anota[r]?|escreve[r]?|salva[r]?|guarda[r]?|nota[r]?)\s*[:\-]?\s*",
        "",
        content,
        flags=re.I,
    ).strip()

    words = re.split(r"\s+", cleaned)
    significant = [
        w for w in words
        if w.lower().rstrip(".,!?:") not in _STOP_WORDS and len(w) > 1
    ]
    title = " ".join(significant[:8]).strip().rstrip(".,!?:")
    if title:
        title = title[0].upper() + title[1:]
    return title[:MAX_TITLE_LENGTH] or content[:MAX_TITLE_LENGTH]


def _extract_tags(content: str) -> List[str]:
    """Extrai hashtags: "nota importante #saúde #urgente" → ["saúde", "urgente"]"""
    return [m.group(1).lower() for m in re.finditer(r"#(\w+)", content)]


@register_service("notes")
class NotesService(BaseService):
    """
    Serviço de notas pessoais — CRUD completo via Supabase.

    Interface pública:
        create_note(user_id, chat_id, content, title?)   → Dict
        list_notes(user_id, limit, include_archived)     → List[Dict]
        search_notes(user_id, query, limit)              → List[Dict]
        get_note(user_id, note_id)                       → Optional[Dict]
        pin_note(user_id, note_id, pinned)               → bool
        archive_note(user_id, note_id)                   → bool
        delete_note(user_id, note_id)                    → bool
        delete_all_notes(user_id)                        → int
    """

    def __init__(self):
        super().__init__(name="notes")
        self._db = None

    async def _initialize(self) -> None:
        from services.core import get_service
        self._db = get_service("database")
        if not self._db:
            raise ServiceUnavailableError("DatabaseService indisponível para NotesService")
        if not self._db.is_initialized():
            await self._db.initialize()
        self.logger.info("NotesService initialized")

    async def _health_check(self) -> bool:
        return self._db is not None and self._db.is_initialized()

    def _client(self):
        return self._db.get_client()

    def _loop(self):
        return asyncio.get_event_loop()

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def create_note(
        self,
        user_id: str,
        chat_id: str,
        content: str,
        title: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Cria uma nova nota pessoal.

        Args:
            user_id:  ID do utilizador
            chat_id:  Chat ID Telegram
            content:  Texto da nota (suporta #hashtags)
            title:    Título opcional — gerado automaticamente se omitido

        Returns:
            Dict com a nota criada (id, title, content, created_at, ...)

        Raises:
            ValueError: conteúdo vazio, muito longo, ou limite atingido
        """
        if not self.is_initialized():
            await self.initialize()

        content = (content or "").strip()
        if not content:
            raise ValueError("O conteúdo da nota não pode ser vazio.")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(f"Nota muito longa (máximo {MAX_CONTENT_LENGTH} caracteres).")

        count = await self._count_notes(user_id)
        if count >= MAX_NOTES_PER_USER:
            raise ValueError(
                f"Limite de {MAX_NOTES_PER_USER} notas atingido. Apaga algumas notas antigas."
            )

        now = _utcnow().isoformat()
        payload = {
            "user_id":    str(user_id),
            "chat_id":    str(chat_id),
            "title":      title or _auto_title(content),
            "content":    content,
            "tags":       _extract_tags(content),
            "pinned":     False,
            "archived":   False,
            "created_at": now,
            "updated_at": now,
        }

        response = await self._loop().run_in_executor(
            None,
            lambda: self._client().table(NOTES_TABLE).insert(payload).execute(),
        )
        if not response.data:
            raise RuntimeError("Falha ao criar nota no banco de dados.")

        note = response.data[0]
        self.logger.info("Note created: %s for user %s", note["id"], user_id)
        return note

    async def list_notes(
        self,
        user_id: str,
        limit: int = 10,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Lista notas do utilizador (fixadas primeiro, depois data DESC).

        Args:
            user_id:          ID do utilizador
            limit:            Máximo de resultados (max 50)
            include_archived: Se True, inclui notas arquivadas

        Returns:
            Lista de notas ordenada
        """
        if not self.is_initialized():
            await self.initialize()

        limit = min(limit, 50)

        def _query():
            q = (
                self._client()
                .table(NOTES_TABLE)
                .select("*")
                .eq("user_id", str(user_id))
            )
            if not include_archived:
                q = q.eq("archived", False)
            return (
                q.order("pinned", desc=True)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )

        response = await self._loop().run_in_executor(None, _query)
        return response.data or []

    async def search_notes(
        self,
        user_id: str,
        query: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Busca notas por texto no título e conteúdo (case-insensitive).

        Args:
            user_id: ID do utilizador
            query:   Texto a pesquisar
            limit:   Máximo de resultados

        Returns:
            Lista de notas correspondentes
        """
        if not self.is_initialized():
            await self.initialize()

        query = (query or "").strip()
        if not query:
            return await self.list_notes(user_id, limit)

        limit = min(limit, 50)
        q = query.lower()

        def _search():
            return (
                self._client()
                .table(NOTES_TABLE)
                .select("*")
                .eq("user_id", str(user_id))
                .eq("archived", False)
                .or_(f"title.ilike.%{q}%,content.ilike.%{q}%")
                .order("pinned", desc=True)
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )

        response = await self._loop().run_in_executor(None, _search)
        return response.data or []

    async def get_note(self, user_id: str, note_id: str) -> Optional[Dict[str, Any]]:
        """Retorna uma nota pelo ID (deve pertencer ao utilizador)."""
        if not self.is_initialized():
            await self.initialize()

        response = await self._loop().run_in_executor(
            None,
            lambda: (
                self._client()
                .table(NOTES_TABLE)
                .select("*")
                .eq("id", note_id)
                .eq("user_id", str(user_id))
                .execute()
            ),
        )
        return response.data[0] if response.data else None

    async def pin_note(self, user_id: str, note_id: str, pinned: bool = True) -> bool:
        """
        Fixa ou desfixa uma nota.

        Returns:
            True se actualizado, False se não encontrado
        """
        if not self.is_initialized():
            await self.initialize()
        return await self._update_fields(
            user_id, note_id, {"pinned": pinned, "updated_at": _utcnow().isoformat()}
        )

    async def archive_note(self, user_id: str, note_id: str) -> bool:
        """
        Arquiva uma nota (some da listagem, mas não é apagada).

        Returns:
            True se arquivada, False se não encontrada
        """
        if not self.is_initialized():
            await self.initialize()
        return await self._update_fields(
            user_id,
            note_id,
            {"archived": True, "pinned": False, "updated_at": _utcnow().isoformat()},
        )

    async def delete_note(self, user_id: str, note_id: str) -> bool:
        """
        Apaga uma nota permanentemente.

        Returns:
            True se apagada, False se não encontrada
        """
        if not self.is_initialized():
            await self.initialize()

        note = await self.get_note(user_id, note_id)
        if not note:
            return False

        await self._loop().run_in_executor(
            None,
            lambda: (
                self._client()
                .table(NOTES_TABLE)
                .delete()
                .eq("id", note_id)
                .eq("user_id", str(user_id))
                .execute()
            ),
        )
        self.logger.info("Note %s deleted for user %s", note_id, user_id)
        return True

    async def delete_all_notes(self, user_id: str) -> int:
        """
        Apaga TODAS as notas do utilizador.

        Returns:
            Número de notas apagadas
        """
        if not self.is_initialized():
            await self.initialize()

        notes = await self.list_notes(user_id, limit=500, include_archived=True)
        count = 0
        for note in notes:
            if await self.delete_note(user_id, note["id"]):
                count += 1
        self.logger.info("Deleted %d notes for user %s", count, user_id)
        return count

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS INTERNOS
    # ──────────────────────────────────────────────────────────────────────────

    async def _count_notes(self, user_id: str) -> int:
        response = await self._loop().run_in_executor(
            None,
            lambda: (
                self._client()
                .table(NOTES_TABLE)
                .select("id", count="exact")
                .eq("user_id", str(user_id))
                .eq("archived", False)
                .execute()
            ),
        )
        return response.count or 0

    async def _update_fields(
        self, user_id: str, note_id: str, updates: Dict[str, Any]
    ) -> bool:
        """Actualiza campos de uma nota. Retorna True se encontrada."""
        check = await self._loop().run_in_executor(
            None,
            lambda: (
                self._client()
                .table(NOTES_TABLE)
                .select("id")
                .eq("id", note_id)
                .eq("user_id", str(user_id))
                .execute()
            ),
        )
        if not check.data:
            return False

        await self._loop().run_in_executor(
            None,
            lambda: (
                self._client()
                .table(NOTES_TABLE)
                .update(updates)
                .eq("id", note_id)
                .eq("user_id", str(user_id))
                .execute()
            ),
        )
        return True

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS DE FORMATAÇÃO (usados pelo agente)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def format_date(created_at_str: str) -> str:
        """Formata data de criação: '2026-02-22T10:30:00+00:00' → '22/02/2026 10:30'"""
        try:
            dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return created_at_str

    @staticmethod
    def short_id(note_id: str) -> str:
        """Primeiros 8 chars do UUID para exibição: 'abc12345-...' → 'abc12345'"""
        return note_id[:8] if note_id else ""
