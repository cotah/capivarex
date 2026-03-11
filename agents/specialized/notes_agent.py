# -*- coding: utf-8 -*-
"""
agents/specialized/notes_agent.py
====================================
NotesAgent — bloco de notas pessoal do Jarvis.

Exemplos de comandos suportados:
    Criar:
        "Anota que tenho de ligar ao dentista"
        "Escreve: renovar seguro do carro até março"
        "Nota: reunião com o João sexta às 10h"
        "Guarda este número: 912 345 678"

    Listar:
        "Minhas notas"
        "Ver notas"
        "Mostra as notas"

    Buscar:
        "Busca nota sobre dentista"
        "Procura nas notas: seguro"
        "Encontra nota sobre reunião"

    Fixar (aparecer sempre no topo):
        "Fixa a nota abc12345"
        "Desfixa a nota abc12345"

    Apagar:
        "Apaga a nota abc12345"
        "Remove a nota sobre dentista"
        "Apaga todas as notas"
"""

import logging
import re
from typing import Any, Dict, List, Optional

from agents.core import AgentResponse, AgentStatus, BaseAgent, register_agent
from services import get_service
from services.i18n import t, get_user_lang

logger = logging.getLogger(__name__)

# ─── Palavras-chave de intenção ─────────────────────────────────────────────

_CREATE_WORDS = [
    "anota",
    "anotar",
    "escreve",
    "escrever",
    "salva",
    "salvar",
    "guarda",
    "guardar",
    "nota:",
    "nova nota",
    "cria nota",
    "registar",
    "regista",
    "add nota",
]
_LIST_WORDS = [
    "minhas notas",
    "meus notas",
    "ver notas",
    "mostra notas",
    "listar notas",
    "lista notas",
    "minhas anotações",
    "quais notas",
    "mostrar notas",
    "todas as notas",
    "notas ativas",
]
_SEARCH_WORDS = [
    "busca nota",
    "buscar nota",
    "busca nas notas",
    "procura nota",
    "procura nas notas",
    "encontra nota",
    "pesquisa nota",
    "nota sobre",
    "notas sobre",
    "search nota",
]
_PIN_WORDS = ["fixa", "fixar", "marca como importante", "pin nota", "destaca"]
_UNPIN_WORDS = ["desfixa", "desfixar", "remove destaque", "unpin"]
_DELETE_WORDS = [
    "apaga",
    "apagar",
    "remove",
    "remover",
    "deleta",
    "deletar",
    "elimina",
    "eliminar",
]
_DELETE_ALL_WORDS = [
    "apaga todas",
    "apagar todas",
    "limpa notas",
    "limpar notas",
    "remove todas",
    "deletar tudo",
    "apaga tudo",
]

# UUID parcial (8 chars hex) para identificar notas
_RE_NOTE_ID = re.compile(r"\b([0-9a-f]{8})\b", re.I)

# Extrai query de busca
_RE_SEARCH_QUERY = re.compile(
    r"(?:sobre|busca|procura|pesquisa|nota[s]?)\s+([^\n]{3,})", re.I
)
# Extrai conteúdo após "nota:" ou "anota:"
_RE_AFTER_COLON = re.compile(r"(?:nota|note|escreve|anota)[:\s]+(.+)", re.I | re.S)


def _detect_intent(text: str) -> str:
    t = text.lower()
    if any(w in t for w in _DELETE_ALL_WORDS):
        return "delete_all"
    if any(w in t for w in _DELETE_WORDS):
        return "delete"
    if any(w in t for w in _UNPIN_WORDS):
        return "unpin"
    if any(w in t for w in _PIN_WORDS):
        return "pin"
    if any(w in t for w in _SEARCH_WORDS):
        return "search"
    if any(w in t for w in _LIST_WORDS):
        return "list"
    if any(w in t for w in _CREATE_WORDS):
        return "create"
    return "unknown"


def _extract_note_id(text: str) -> Optional[str]:
    m = _RE_NOTE_ID.search(text)
    return m.group(1).lower() if m else None


def _extract_content(text: str) -> str:
    m = _RE_AFTER_COLON.search(text)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(
        r"^(anota[r]?|escreve[r]?|salva[r]?|guarda[r]?|nota[r]?|"
        r"cria\s+nota|nova\s+nota|registar?)\s*",
        "",
        text,
        flags=re.I,
    ).strip()
    return cleaned or text


def _extract_search_query(text: str) -> str:
    m = _RE_SEARCH_QUERY.search(text)
    if m:
        return m.group(1).strip()
    cleaned = re.sub(
        r"(busca[r]?|procura[r]?|pesquisa[r]?|encontra[r]?)\s*(nota[s]?\s*)?",
        "",
        text,
        flags=re.I,
    ).strip()
    return cleaned or text


@register_agent("notes")
class NotesAgent(BaseAgent):
    """
    Agente de notas pessoais — cria, lista, busca, fixa e apaga notas.

    Intents:
        create     → cria nota com conteúdo extraído do prompt
        list       → lista notas activas (fixadas primeiro)
        search     → busca por texto no título e conteúdo
        pin        → fixa nota no topo
        unpin      → desfixa nota
        delete     → apaga nota por ID (ou busca pelo texto)
        delete_all → apaga todas as notas
    """

    def __init__(self):
        super().__init__(
            name="notes",
            description="Bloco de notas pessoal — anota, lista, busca e apaga notas",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        lang = get_user_lang(context)
        try:
            svc = get_service("notes")
            if not svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response="Serviço de notas não disponível.",
                    error="NotesService unavailable",
                )
            if not svc.is_initialized():
                await svc.initialize()

            user_id = str(context.get("user_id", ""))
            chat_id = str(context.get("chat_id", user_id))

            if not user_id:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("user_not_identified", lang=lang),
                    error="No user_id in context",
                )

            intent = context.get("action") or _detect_intent(prompt)

            if intent == "create":
                content = context.get("content") or _extract_content(prompt)
                return await self._handle_create(
                    svc, user_id, chat_id, content, context.get("title")
                )

            if intent == "list":
                return await self._handle_list(svc, user_id)

            if intent == "search":
                query = context.get("query") or _extract_search_query(prompt)
                return await self._handle_search(svc, user_id, query)

            if intent == "pin":
                note_id = context.get("note_id") or _extract_note_id(prompt)
                if not note_id:
                    return self._missing_id_response("fixar")
                return await self._handle_pin(svc, user_id, note_id, pinned=True)

            if intent == "unpin":
                note_id = context.get("note_id") or _extract_note_id(prompt)
                if not note_id:
                    return self._missing_id_response("desfixar")
                return await self._handle_pin(svc, user_id, note_id, pinned=False)

            if intent == "delete":
                note_id = context.get("note_id") or _extract_note_id(prompt)
                if not note_id:
                    query = _extract_search_query(prompt)
                    if len(query) >= 3:
                        return await self._handle_delete_by_search(svc, user_id, query)
                    return self._missing_id_response("apagar")
                return await self._handle_delete(svc, user_id, note_id)

            if intent == "delete_all":
                return await self._handle_delete_all(svc, user_id)

            # Fallback: tenta criar com o prompt inteiro
            content = _extract_content(prompt)
            if len(content) >= 3:
                return await self._handle_create(svc, user_id, chat_id, content, None)

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "Não entendi o que você quer fazer. Exemplos:\n"
                    "• *Anota: ligar ao dentista*\n"
                    "• *Minhas notas*\n"
                    "• *Busca nota sobre seguro*\n"
                    "• *Apaga a nota abc12345*"
                ),
                error="Could not detect intent",
            )

        except ValueError as e:
            return AgentResponse(
                status=AgentStatus.ERROR, response=str(e), error=str(e)
            )
        except Exception as e:
            self.logger.error("NotesAgent error: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Erro ao processar nota. Tente novamente.",
                error=str(e),
            )

    # ──────────────────────────────────────────────────────────────────────────
    # Handlers
    # ──────────────────────────────────────────────────────────────────────────

    async def _handle_create(
        self, svc: Any, user_id: str, chat_id: str, content: str, title: Optional[str]
    ) -> AgentResponse:
        note = await svc.create_note(
            user_id=user_id, chat_id=chat_id, content=content, title=title
        )
        short = svc.short_id(note["id"])
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                f"📝 **Nota guardada!**\n"
                f"🏷️ _{note['title']}_\n"
                f"ID: `{short}`\n\n"
                f"_Usa 'apaga nota {short}' para remover._"
            ),
            data=note,
        )

    async def _handle_list(self, svc: Any, user_id: str) -> AgentResponse:
        notes = await svc.list_notes(user_id, limit=15)
        if not notes:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=(
                    "📭 Você não tem notas salvas.\n\n"
                    "_Tente: 'Anota que tenho de ligar ao dentista'_"
                ),
                data={"notes": []},
            )
        lines = [f"📓 **Suas notas ({len(notes)}):**\n"]
        for note in notes:
            short = svc.short_id(note["id"])
            pin_icon = "📌 " if note.get("pinned") else ""
            date_str = svc.format_date(note.get("created_at", ""))
            preview = note["content"][:80].replace("\n", " ")
            if len(note["content"]) > 80:
                preview += "…"
            lines.append(f"{pin_icon}`{short}` {date_str}\n_{preview}_\n")
        lines.append("_'Busca nota sobre X' | 'Apaga nota ID' | 'Fixa nota ID'_")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"notes": notes},
        )

    async def _handle_search(self, svc: Any, user_id: str, query: str) -> AgentResponse:
        notes = await svc.search_notes(user_id, query, limit=10)
        if not notes:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=f"🔍 Nenhuma nota encontrada sobre *{query}*.",
                data={"notes": [], "query": query},
            )
        lines = [f"🔍 **Notas sobre '{query}' ({len(notes)}):**\n"]
        for note in notes:
            short = svc.short_id(note["id"])
            date_str = svc.format_date(note.get("created_at", ""))
            preview = note["content"][:100].replace("\n", " ")
            if len(note["content"]) > 100:
                preview += "…"
            lines.append(f"`{short}` {date_str}\n_{preview}_\n")
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={"notes": notes, "query": query},
        )

    async def _handle_pin(
        self, svc: Any, user_id: str, note_id: str, pinned: bool
    ) -> AgentResponse:
        full_id = await self._resolve_id(svc, user_id, note_id)
        if not full_id:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Nota `{note_id}` não encontrada.",
                error="Note not found",
            )
        await svc.pin_note(user_id, full_id, pinned)
        action = "fixada 📌" if pinned else "desafixada"
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"✅ Nota `{note_id}` {action}.",
            data={"note_id": full_id, "pinned": pinned},
        )

    async def _handle_delete(
        self, svc: Any, user_id: str, note_id: str
    ) -> AgentResponse:
        full_id = await self._resolve_id(svc, user_id, note_id)
        if not full_id or not await svc.delete_note(user_id, full_id):
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Nota `{note_id}` não encontrada.",
                error="Note not found",
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"🗑️ Nota `{note_id}` apagada.",
            data={"note_id": full_id, "deleted": True},
        )

    async def _handle_delete_by_search(
        self, svc: Any, user_id: str, query: str
    ) -> AgentResponse:
        notes = await svc.search_notes(user_id, query, limit=1)
        if not notes:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Nenhuma nota encontrada sobre *{query}*.",
                error="Note not found by search",
            )
        note = notes[0]
        short = svc.short_id(note["id"])
        await svc.delete_note(user_id, note["id"])
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"🗑️ Nota apagada:\n`{short}` — _{note['title']}_",
            data={"note_id": note["id"], "deleted": True},
        )

    async def _handle_delete_all(self, svc: Any, user_id: str) -> AgentResponse:
        count = await svc.delete_all_notes(user_id)
        if count == 0:
            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response="Não tinhas notas para apagar.",
                data={"deleted_count": 0},
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=f"🗑️ {count} nota(s) apagada(s).",
            data={"deleted_count": count},
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    async def _resolve_id(self, svc: Any, user_id: str, short_id: str) -> Optional[str]:
        """Resolve ID parcial (8 chars) para UUID completo."""
        notes = await svc.list_notes(user_id, limit=500, include_archived=True)
        for note in notes:
            if note["id"].startswith(short_id.lower()):
                return note["id"]
        return None

    @staticmethod
    def _missing_id_response(action: str) -> AgentResponse:
        return AgentResponse(
            status=AgentStatus.ERROR,
            response=(
                f"Para {action} uma nota, precisas do ID.\n"
                "Usa *'minhas notas'* para ver os IDs.\n\n"
                f"Ex: *'{action.capitalize()} nota abc12345'*"
            ),
            error="No note ID provided",
        )

    def get_capabilities(self) -> List[str]:
        return [
            "create_note",
            "list_notes",
            "search_notes",
            "pin_note",
            "unpin_note",
            "delete_note",
            "delete_all_notes",
        ]
