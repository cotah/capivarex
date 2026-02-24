# -*- coding: utf-8 -*-
"""
services/business/notes_service.py
====================================
Notas pessoais persistentes via Supabase.

FIX [2025-02]: search_notes agora busca por palavras individuais.
  ANTES: `.or_("title.ilike.%seguro carro%,content.ilike.%seguro carro%")`
          → só encontra se "seguro carro" aparecer como substring exata
  DEPOIS: split em palavras → cada palavra gera um filtro ilike
          → "seguro carro" encontra notas que tenham "seguro" E "carro" em qualquer posição
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

_STOP_WORDS = {
    "anota",
    "anote",
    "escreve",
    "salva",
    "guarda",
    "nota",
    "que",
    "de",
    "o",
    "a",
    "os",
    "as",
    "um",
    "uma",
    "para",
    "por",
    "com",
    "em",
    "tenho",
    "preciso",
    "devo",
    "quero",
    "vou",
    "me",
    "minha",
    "meu",
}

# Palavras de busca genéricas a ignorar para não trazer tudo
_SEARCH_STOP_WORDS = {
    "busca",
    "buscar",
    "procura",
    "procurar",
    "encontra",
    "encontrar",
    "nota",
    "notas",
    "sobre",
    "acerca",
    "relacionado",
    "ver",
    "veja",
    "mostra",
    "mostrar",
    "lista",
    "listar",
    "minhas",
    "meus",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _auto_title(content: str) -> str:
    cleaned = re.sub(
        r"^(anota[r]?|escreve[r]?|salva[r]?|guarda[r]?|nota[r]?)\s*[:\-]?\s*",
        "",
        content,
        flags=re.I,
    ).strip()
    words = re.split(r"\s+", cleaned)
    significant = [
        w for w in words if w.lower().rstrip(".,!?:") not in _STOP_WORDS and len(w) > 1
    ]
    title = " ".join(significant[:8]).strip().rstrip(".,!?:")
    if title:
        title = title[0].upper() + title[1:]
    return title[:MAX_TITLE_LENGTH] or content[:MAX_TITLE_LENGTH]


def _extract_tags(content: str) -> List[str]:
    return [m.group(1).lower() for m in re.finditer(r"#(\w+)", content)]


def _split_query_words(query: str, min_len: int = 3) -> List[str]:
    """
    Divide a query em palavras significativas para busca multi-palavra.

    Exemplo:
        "seguro carro" → ["seguro", "carro"]
        "buscar nota sobre seguro" → ["seguro"]  (stop words removidas)
        "dentista" → ["dentista"]

    Args:
        query: Texto de busca
        min_len: Tamanho mínimo de uma palavra para ser considerada

    Returns:
        Lista de palavras significativas (lowercase, sem pontuação)
    """
    # Remove pontuação e normaliza
    cleaned = re.sub(r"[^\w\s]", " ", query.lower())
    words = cleaned.split()
    significant = [
        w
        for w in words
        if len(w) >= min_len and w not in _SEARCH_STOP_WORDS and w not in _STOP_WORDS
    ]
    # Se não sobrou nada após o filtro, usa as palavras originais sem stop words
    if not significant:
        significant = [w for w in words if len(w) >= min_len]
    # Ainda nada → usa query inteira
    return significant or [query.lower().strip()]


@register_service("notes")
class NotesService(BaseService):
    """
    Serviço de notas pessoais — CRUD completo via Supabase.

    Interface pública:
        create_note(user_id, chat_id, content, title?) → Dict
        list_notes(user_id, limit, include_archived) → List[Dict]
        search_notes(user_id, query, limit) → List[Dict]   ← FIX: busca por palavras
        get_note(user_id, note_id) → Optional[Dict]
        pin_note(user_id, note_id, pinned) → bool
        archive_note(user_id, note_id) → bool
        delete_note(user_id, note_id) → bool
        delete_all_notes(user_id) → int
    """

    def __init__(self):
        super().__init__(name="notes")
        self._db = None

    async def _initialize(self) -> None:
        from services.core import get_service

        self._db = get_service("database")
        if not self._db:
            raise ServiceUnavailableError(
                "DatabaseService indisponível para NotesService"
            )
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
        if not self.is_initialized():
            await self.initialize()

        content = (content or "").strip()
        if not content:
            raise ValueError("O conteúdo da nota não pode ser vazio.")
        if len(content) > MAX_CONTENT_LENGTH:
            raise ValueError(
                f"Nota muito longa (máximo {MAX_CONTENT_LENGTH} caracteres)."
            )

        count = await self._count_notes(user_id)
        if count >= MAX_NOTES_PER_USER:
            raise ValueError(
                f"Limite de {MAX_NOTES_PER_USER} notas atingido. Apaga algumas notas antigas."
            )

        now = _utcnow().isoformat()
        payload = {
            "user_id": str(user_id),
            "chat_id": str(chat_id),
            "title": title or _auto_title(content),
            "content": content,
            "tags": _extract_tags(content),
            "pinned": False,
            "archived": False,
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
        Busca notas por palavras-chave individuais (case-insensitive).

        FIX: Antes usava uma única substring ilike — agora divide a query em
        palavras e faz múltiplos filtros OR, garantindo que cada palavra
        seja encontrada independentemente de ordem ou contexto.

        Exemplos:
            "seguro carro" → encontra "Renovar seguro do carro em março"
            "dentista" → encontra qualquer nota que contenha "dentista"
            "ligar médico" → encontra notas com "ligar" OU "médico"

        Se a query tiver 2+ palavras significativas, executa duas estratégias:
        1. Busca pela frase completa (mais relevante — resultado no topo)
        2. Busca por cada palavra individual, merge sem duplicatas
        """
        if not self.is_initialized():
            await self.initialize()

        query = (query or "").strip()
        if not query:
            return await self.list_notes(user_id, limit)

        limit = min(limit, 50)
        words = _split_query_words(query)

        # Estratégia 1: busca pela frase completa
        exact_results = await self._search_by_phrase(user_id, query, limit)

        # Se já tem resultados suficientes ou é 1 palavra, retorna direto
        if len(exact_results) >= limit or len(words) <= 1:
            return exact_results

        # Estratégia 2: busca por palavras individuais (merge, sem duplicatas)
        seen_ids = {r["id"] for r in exact_results}
        combined = list(exact_results)

        for word in words:
            if len(combined) >= limit:
                break
            word_results = await self._search_by_phrase(user_id, word, limit)
            for r in word_results:
                if r["id"] not in seen_ids:
                    seen_ids.add(r["id"])
                    combined.append(r)

        return combined[:limit]

    async def _search_by_phrase(
        self, user_id: str, phrase: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Busca por substring exata em título e conteúdo."""
        q = phrase.lower()

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
        if not self.is_initialized():
            await self.initialize()
        return await self._update_fields(
            user_id, note_id, {"pinned": pinned, "updated_at": _utcnow().isoformat()}
        )

    async def archive_note(self, user_id: str, note_id: str) -> bool:
        if not self.is_initialized():
            await self.initialize()
        return await self._update_fields(
            user_id,
            note_id,
            {"archived": True, "pinned": False, "updated_at": _utcnow().isoformat()},
        )

    async def delete_note(self, user_id: str, note_id: str) -> bool:
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
        try:
            dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
            return dt.strftime("%d/%m/%Y %H:%M")
        except Exception:
            return created_at_str

    @staticmethod
    def short_id(note_id: str) -> str:
        return note_id[:8] if note_id else ""
