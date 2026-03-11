# -*- coding: utf-8 -*-
"""
tests/test_notes.py
===================
Testes unitários para NotesService e NotesAgent.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helpers de mock ────────────────────────────────────────────────────────

def _make_note(
    note_id="abc12345-0000-0000-0000-000000000000",
    user_id="user1",
    title="Ligar ao dentista",
    content="Ligar ao dentista amanhã",
    pinned=False,
    archived=False,
):
    return {
        "id": note_id,
        "user_id": user_id,
        "chat_id": user_id,
        "title": title,
        "content": content,
        "tags": [],
        "pinned": pinned,
        "archived": archived,
        "created_at": "2026-02-22T10:00:00+00:00",
        "updated_at": "2026-02-22T10:00:00+00:00",
    }


def _mock_resp(data, count=None):
    resp = MagicMock()
    resp.data = data if isinstance(data, list) else [data]
    resp.count = count if count is not None else len(resp.data)
    return resp


# ─── NotesService helpers estáticos ─────────────────────────────────────────

class TestNotesServiceHelpers:

    def test_auto_title_preserves_content(self):
        from services.business.notes_service import _auto_title
        assert "dentista" in _auto_title("Ligar ao dentista amanhã").lower()

    def test_auto_title_strips_command_word(self):
        from services.business.notes_service import _auto_title
        title = _auto_title("Anota: renovar seguro do carro")
        assert "anota" not in title.lower()

    def test_auto_title_max_length(self):
        from services.business.notes_service import _auto_title, MAX_TITLE_LENGTH
        assert len(_auto_title("palavra " * 50)) <= MAX_TITLE_LENGTH

    def test_extract_tags_found(self):
        from services.business.notes_service import _extract_tags
        tags = _extract_tags("Nota importante #saúde #urgente")
        assert "saúde" in tags
        assert "urgente" in tags

    def test_extract_tags_empty(self):
        from services.business.notes_service import _extract_tags
        assert _extract_tags("Nota sem hashtags") == []

    def test_format_date_valid(self):
        from services.business.notes_service import NotesService
        result = NotesService.format_date("2026-02-22T10:30:00+00:00")
        assert "22/02/2026" in result
        assert "10:30" in result

    def test_format_date_invalid(self):
        from services.business.notes_service import NotesService
        bad = "data-inválida"
        assert NotesService.format_date(bad) == bad

    def test_short_id(self):
        from services.business.notes_service import NotesService
        assert NotesService.short_id("abc12345-0000-0000-0000-000000000000") == "abc12345"

    def test_short_id_empty(self):
        from services.business.notes_service import NotesService
        assert NotesService.short_id("") == ""


# ─── NotesService validações ─────────────────────────────────────────────────

@pytest.mark.asyncio
class TestNotesServiceValidation:

    def _svc(self):
        from services.business.notes_service import NotesService
        svc = NotesService.__new__(NotesService)
        svc.name = "notes"
        svc.logger = MagicMock()
        svc._initialized = True
        svc._db = MagicMock()
        svc._db.is_initialized.return_value = True
        return svc

    async def test_create_empty_raises(self):
        svc = self._svc()
        with pytest.raises(ValueError, match="vazio"):
            await svc.create_note("u1", "u1", "")

    async def test_create_too_long_raises(self):
        from services.business.notes_service import MAX_CONTENT_LENGTH
        svc = self._svc()
        with pytest.raises(ValueError, match="longa"):
            await svc.create_note("u1", "u1", "x" * (MAX_CONTENT_LENGTH + 1))

    async def test_create_limit_reached_raises(self):
        from services.business.notes_service import MAX_NOTES_PER_USER
        svc = self._svc()
        with patch.object(svc, "_count_notes", new=AsyncMock(return_value=MAX_NOTES_PER_USER)):
            with pytest.raises(ValueError, match="Limite"):
                await svc.create_note("u1", "u1", "nova nota")


# ─── NotesAgent — detecção de intenção ──────────────────────────────────────

class TestNotesAgentIntentDetection:

    def test_create(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Anota que tenho de ligar ao dentista") == "create"
        assert _detect_intent("Nota: renovar seguro") == "create"
        assert _detect_intent("Escreve: reunião com João") == "create"

    def test_list(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Minhas notas") == "list"
        assert _detect_intent("Ver notas") == "list"
        assert _detect_intent("Mostra notas") == "list"
        assert _detect_intent("Listar notas") == "list"

    def test_search(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Busca nota sobre dentista") == "search"
        assert _detect_intent("Procura nas notas: seguro") == "search"
        assert _detect_intent("nota sobre reunião") == "search"

    def test_pin(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Fixa a nota abc12345") == "pin"

    def test_unpin(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Desfixa a nota abc12345") == "unpin"

    def test_delete(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Apaga a nota abc12345") == "delete"
        assert _detect_intent("Remove a nota sobre dentista") == "delete"

    def test_delete_all(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Apaga todas as notas") == "delete_all"
        assert _detect_intent("Limpa notas") == "delete_all"

    def test_unknown(self):
        from agents.specialized.notes_agent import _detect_intent
        assert _detect_intent("Olá tudo bem?") == "unknown"


class TestNotesAgentExtraction:

    def test_content_after_colon(self):
        from agents.specialized.notes_agent import _extract_content
        assert "médico" in _extract_content("Nota: ligar ao médico amanhã")

    def test_content_strips_command(self):
        from agents.specialized.notes_agent import _extract_content
        content = _extract_content("Anota que preciso renovar o seguro")
        assert "renovar" in content
        assert "anota" not in content.lower()

    def test_search_query_extracted(self):
        from agents.specialized.notes_agent import _extract_search_query
        assert "dentista" in _extract_search_query("Busca nota sobre dentista")

    def test_note_id_extracted(self):
        from agents.specialized.notes_agent import _extract_note_id
        assert _extract_note_id("Apaga a nota abc12345 por favor") == "abc12345"

    def test_note_id_none(self):
        from agents.specialized.notes_agent import _extract_note_id
        assert _extract_note_id("Apaga todas as notas") is None


# ─── NotesAgent — execute ────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestNotesAgentExecute:

    def _agent(self):
        from agents.specialized.notes_agent import NotesAgent
        a = NotesAgent.__new__(NotesAgent)
        a.name = "notes"
        a.logger = MagicMock()
        return a

    def _svc(self):
        svc = MagicMock()
        svc.is_initialized.return_value = True
        svc.short_id = lambda nid: nid[:8]
        svc.format_date = lambda _: "22/02/2026 10:00"
        return svc

    def _ctx(self, user_id="user1"):
        return {"user_id": user_id, "chat_id": user_id}

    async def test_create_success(self):
        agent = self._agent()
        svc = self._svc()
        svc.create_note = AsyncMock(return_value=_make_note())
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Anota: ligar ao dentista", self._ctx())
        assert r.status.value == "success"
        assert "guardada" in r.response.lower()

    async def test_list_with_notes(self):
        agent = self._agent()
        svc = self._svc()
        svc.list_notes = AsyncMock(return_value=[_make_note(), _make_note("def67890-0000-0000-0000-000000000000")])
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Minhas notas", self._ctx())
        assert r.status.value == "success"
        assert "2" in r.response or "notas" in r.response.lower()

    async def test_list_empty(self):
        agent = self._agent()
        svc = self._svc()
        svc.list_notes = AsyncMock(return_value=[])
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Minhas notas", self._ctx())
        assert r.status.value == "success"
        assert "não tens" in r.response.lower() or "sem notas" in r.response.lower() or "não" in r.response.lower()

    async def test_search_found(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_notes = AsyncMock(return_value=[_make_note()])
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Busca nota sobre dentista", self._ctx())
        assert r.status.value == "success"

    async def test_search_not_found(self):
        agent = self._agent()
        svc = self._svc()
        svc.search_notes = AsyncMock(return_value=[])
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Busca nota sobre dentista", self._ctx())
        assert r.status.value == "success"
        assert "nenhuma" in r.response.lower()

    async def test_delete_success(self):
        agent = self._agent()
        svc = self._svc()
        svc.list_notes = AsyncMock(return_value=[_make_note()])
        svc.delete_note = AsyncMock(return_value=True)
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Apaga a nota abc12345", self._ctx())
        assert r.status.value == "success"
        assert "apagada" in r.response.lower()

    async def test_delete_not_found(self):
        agent = self._agent()
        svc = self._svc()
        svc.list_notes = AsyncMock(return_value=[])
        svc.delete_note = AsyncMock(return_value=False)
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Apaga a nota abc12345", self._ctx())
        assert r.status.value == "error"

    async def test_pin_success(self):
        agent = self._agent()
        svc = self._svc()
        svc.list_notes = AsyncMock(return_value=[_make_note()])
        svc.pin_note = AsyncMock(return_value=True)
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Fixa a nota abc12345", self._ctx())
        assert r.status.value == "success"
        assert "fixada" in r.response.lower()

    async def test_delete_all(self):
        agent = self._agent()
        svc = self._svc()
        svc.delete_all_notes = AsyncMock(return_value=5)
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Apaga todas as notas", self._ctx())
        assert r.status.value == "success"
        assert "5" in r.response

    async def test_no_user_id_returns_error(self):
        agent = self._agent()
        svc = self._svc()
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("Anota: algo", {"user_id": "", "chat_id": ""})
        assert r.status.value == "error"

    async def test_service_unavailable(self):
        agent = self._agent()
        with patch("agents.specialized.notes_agent.get_service", return_value=None):
            r = await agent.execute("Minhas notas", self._ctx())
        assert r.status.value == "error"
        assert "não disponível" in r.response.lower()

    async def test_unknown_intent_with_content_creates_note(self):
        """Fallback: texto solto com >=3 chars cria nota."""
        agent = self._agent()
        svc = self._svc()
        svc.create_note = AsyncMock(return_value=_make_note(content="comprar leite"))
        with patch("agents.specialized.notes_agent.get_service", return_value=svc):
            r = await agent.execute("comprar leite", self._ctx())
        assert r.status.value == "success"
