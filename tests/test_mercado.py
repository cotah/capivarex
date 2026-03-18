# -*- coding: utf-8 -*-
"""
tests/test_mercado.py
======================
Testes para MercadoAgent e MercadoService.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agents.core import AgentStatus


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_mercado_svc():
    svc = MagicMock()
    svc.is_initialized = MagicMock(return_value=True)
    svc.initialize = AsyncMock()
    svc.adicionar = AsyncMock(
        return_value={"mensagem": "✅ Adicionado: leite", "sucesso": True}
    )
    svc.ver_lista = AsyncMock(
        return_value={"mensagem": "🛒 Lista: leite", "lista": ["leite"]}
    )
    svc.remover = AsyncMock(
        return_value={"mensagem": "🗑️ leite removido.", "removeu": True}
    )
    svc.limpar_lista = AsyncMock(
        return_value={"mensagem": "🗑️ Lista limpa!", "totalRemovido": 1}
    )
    svc.historico_lista = AsyncMock(return_value={"mensagem": "📖 Histórico vazio."})
    svc.relatorio_mensal = AsyncMock(
        return_value={"mensagem": "📊 Relatório fevereiro"}
    )
    svc.comparar_produto = AsyncMock(return_value={"mensagem": "💰 Leite: Lidl €0.89"})
    svc.ranking_mercados = AsyncMock(return_value={"mensagem": "🏪 Ranking: Lidl 1º"})
    svc.processar_nota = AsyncMock(
        return_value={"mensagem": "🧾 Nota registada", "sucesso": True}
    )
    return svc


@pytest.fixture
def mercado_agent(mock_mercado_svc):
    from agents.specialized.mercado_agent import MercadoAgent

    agent = MercadoAgent()
    with patch(
        "agents.specialized.mercado_agent.get_service", return_value=mock_mercado_svc
    ):
        yield agent, mock_mercado_svc


# ── Testes: detecção de intenção ──────────────────────────────────────────────


class TestIntencoes:
    @pytest.mark.parametrize(
        "msg",
        [
            "adicionar leite e pão",
            "coloca manteiga na lista",
            "põe ovos",
            "acrescenta arroz",
        ],
    )
    @pytest.mark.asyncio
    async def test_adicionar(self, msg, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute(msg, {})
        svc.adicionar.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.parametrize(
        "msg",
        [
            "ver lista",
            "mostra a lista",
            "o que tem na lista",
            "minha lista de compras",
        ],
    )
    @pytest.mark.asyncio
    async def test_ver_lista(self, msg, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute(msg, {})
        svc.ver_lista.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.parametrize(
        "msg",
        [
            "remover leite",
            "apaga o pão",
            "tira manteiga da lista",
        ],
    )
    @pytest.mark.asyncio
    async def test_remover(self, msg, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute(msg, {})
        svc.remover.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.parametrize(
        "msg",
        [
            "limpar lista",
            "zera tudo",
            "apaga tudo",
            "clear",
        ],
    )
    @pytest.mark.asyncio
    async def test_limpar(self, msg, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute(msg, {})
        svc.limpar_lista.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_historico_lista(self, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute("histórico lista", {})
        svc.historico_lista.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_relatorio_mensal(self, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute("relatório mensal", {"chat_id": "chat123"})
        # Now returns inline keyboard instead of calling service directly
        assert result.status == AgentStatus.SUCCESS
        assert result.metadata.get("type") == "inline_keyboard"
        assert result.metadata.get("reply_markup") is not None

    @pytest.mark.asyncio
    async def test_comparar_produto(self, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute("comparar leite", {"chat_id": "chat123"})
        svc.comparar_produto.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_ranking_mercados(self, mercado_agent):
        agent, svc = mercado_agent
        result = await agent.execute("ranking mercados", {"chat_id": "chat123"})
        svc.ranking_mercados.assert_called_once()
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_nota_fiscal_com_imagem(self, mercado_agent):
        agent, svc = mercado_agent
        ctx = {"image_data": b"fake_image_bytes", "chat_id": "chat123"}
        result = await agent.execute("", ctx)
        svc.processar_nota.assert_called_once_with(
            b"fake_image_bytes", "chat123", mime_type="image/jpeg", lang="en"
        )
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_fallback_adiciona(self, mercado_agent):
        """Texto curto sem padrão → fallback para adicionar."""
        agent, svc = mercado_agent
        result = await agent.execute("bananas", {})
        svc.adicionar.assert_called_once_with("bananas", user_id="default", lang="en")
        assert result.status == AgentStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_service_unavailable(self):
        """Sem serviço disponível → erro gracioso."""
        from agents.specialized.mercado_agent import MercadoAgent

        agent = MercadoAgent()
        with patch("agents.specialized.mercado_agent.get_service", return_value=None):
            result = await agent.execute("ver lista", {})
        assert result.status == AgentStatus.ERROR
        assert "unavailable" in result.response.lower()

    @pytest.mark.asyncio
    async def test_ajuda_texto_longo(self, mercado_agent):
        """Texto muito longo → retorna ajuda."""
        agent, svc = mercado_agent
        result = await agent.execute("x" * 200, {})
        assert "Mercado Inteligente" in result.response


# ── Testes: MercadoService (categorização) ────────────────────────────────────


class TestCategorizacao:
    def test_categorias_conhecidas(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Leite Mimosa") == "Laticínios"
        assert _categorizar("Pão de Forma") == "Padaria"
        assert _categorizar("Frango Inteiro") == "Carnes"
        assert _categorizar("Arroz Carolino") == "Mercearia"
        assert _categorizar("Água 1.5L") == "Bebidas"

    def test_categoria_outros(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Produto Desconhecido XYZ") == "Outros"

    def test_categorias_peixe(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Salmão Fresco") == "Peixe"
        assert _categorizar("Bacalhau da Noruega") == "Peixe"

    def test_categorias_higiene(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Shampoo H&S") == "Higiene"

    def test_categorias_ovos(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Ovos M 12un") == "Ovos"


# ── Testes: normalização de nota ──────────────────────────────────────────────


class TestNormalizacaoNota:
    def _make_svc(self):
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        return svc

    def test_normalizar_preco_unitario(self):
        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data": "22/02/2026",
            "total": 5.00,
            "itens": [
                {
                    "produto": "Leite",
                    "quantidade": 2,
                    "preco_total": 2.18,
                    "preco_unitario": 0,
                }
            ],
        }
        result = svc._normalizar_nota(nota)
        assert result["itens"][0]["preco_unitario"] == pytest.approx(1.09, 0.01)
        assert result["itens"][0]["categoria"] == "Laticínios"

    def test_normalizar_data_padrao(self):
        from datetime import date

        svc = self._make_svc()
        nota = {"mercado": "Aldi", "total": 10.0, "data": None, "itens": []}
        result = svc._normalizar_nota(nota)
        assert result["data_obj"] == date.today()

    def test_normalizar_total_calculado(self):
        svc = self._make_svc()
        nota = {
            "mercado": "Pingo Doce",
            "data": "01/02/2026",
            "total": None,
            "itens": [
                {
                    "produto": "Pão",
                    "quantidade": 1,
                    "preco_total": 1.35,
                    "preco_unitario": 1.35,
                },
                {
                    "produto": "Leite",
                    "quantidade": 1,
                    "preco_total": 0.99,
                    "preco_unitario": 0.99,
                },
            ],
        }
        result = svc._normalizar_nota(nota)
        assert result["total"] == pytest.approx(2.34, 0.01)

    def test_normalizar_data_formato_iso(self):
        from datetime import date

        svc = self._make_svc()
        nota = {"mercado": "Aldi", "total": 10.0, "data": "2026-02-22", "itens": []}
        result = svc._normalizar_nota(nota)
        assert result["data_obj"] == date(2026, 2, 22)

    def test_normalizar_preco_total_from_unitario(self):
        svc = self._make_svc()
        nota = {
            "mercado": "Aldi",
            "data": "01/01/2026",
            "total": 10.0,
            "itens": [
                {
                    "produto": "Arroz",
                    "quantidade": 3,
                    "preco_total": 0,
                    "preco_unitario": 1.50,
                }
            ],
        }
        result = svc._normalizar_nota(nota)
        assert result["itens"][0]["preco_total"] == pytest.approx(4.50, 0.01)

    def test_normalizar_mercado_desconhecido(self):
        svc = self._make_svc()
        nota = {"mercado": None, "total": 5.0, "data": "01/01/2026", "itens": []}
        result = svc._normalizar_nota(nota)
        assert result["mercado"] == "Desconhecido"

    def test_normalizar_ignora_item_sem_produto(self):
        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data": "01/01/2026",
            "total": 5.0,
            "itens": [
                {"produto": "", "quantidade": 1, "preco_total": 1.0},
                {
                    "produto": "Leite",
                    "quantidade": 1,
                    "preco_total": 1.0,
                    "preco_unitario": 1.0,
                },
            ],
        }
        result = svc._normalizar_nota(nota)
        assert len(result["itens"]) == 1
        assert result["itens"][0]["produto"] == "Leite"

    def test_normalizar_data_formato_curto(self):
        """Testa data dd/mm/yy (2 dígitos)."""
        from datetime import date

        svc = self._make_svc()
        nota = {"mercado": "Aldi", "total": 10.0, "data": "22/02/26", "itens": []}
        result = svc._normalizar_nota(nota)
        assert result["data_obj"] == date(2026, 2, 22)

    def test_normalizar_unidade_padrao(self):
        """Item sem unidade deve receber 'un' por padrão."""
        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data": "01/01/2026",
            "total": 5.0,
            "itens": [
                {
                    "produto": "Leite",
                    "quantidade": 1,
                    "preco_total": 1.0,
                    "preco_unitario": 1.0,
                }
            ],
        }
        result = svc._normalizar_nota(nota)
        assert result["itens"][0]["unidade"] == "un"

    def test_normalizar_item_quantidade_none(self):
        """Item sem quantidade deve usar 1 por padrão."""
        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data": "01/01/2026",
            "total": 5.0,
            "itens": [
                {
                    "produto": "Pão",
                    "quantidade": None,
                    "preco_total": 0.80,
                    "preco_unitario": 0.80,
                }
            ],
        }
        result = svc._normalizar_nota(nota)
        assert result["itens"][0]["quantidade"] == 1.0


# ── Testes: _nome_mes ──────────────────────────────────────────────────────


class TestNomeMes:
    def _make_svc(self):
        from services.business.mercado_service import MercadoService

        return MercadoService.__new__(MercadoService)

    def test_meses_validos(self):
        svc = self._make_svc()
        assert svc._nome_mes(1) == "January"
        assert svc._nome_mes(2) == "February"
        assert svc._nome_mes(6) == "June"
        assert svc._nome_mes(12) == "December"

    def test_mes_invalido(self):
        svc = self._make_svc()
        assert svc._nome_mes(0) == "0"
        assert svc._nome_mes(13) == "13"


# ── Testes: _formatar_resposta_nota ─────────────────────────────────────────


class TestFormatarRespostaNota:
    def _make_svc(self):
        from services.business.mercado_service import MercadoService

        return MercadoService.__new__(MercadoService)

    def test_formato_basico(self):
        from datetime import date

        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data_obj": date(2026, 2, 22),
            "total": 15.50,
            "itens": [
                {
                    "produto": "Leite",
                    "quantidade": 2.0,
                    "preco_total": 2.18,
                    "preco_unitario": 1.09,
                    "unidade": "un",
                    "categoria": "Laticínios",
                },
                {
                    "produto": "Pão",
                    "quantidade": 1.0,
                    "preco_total": 0.80,
                    "preco_unitario": 0.80,
                    "unidade": "un",
                    "categoria": "Padaria",
                },
            ],
        }
        result = svc._formatar_resposta_nota(nota, alertas=[], compra_id="abc123")
        assert result["sucesso"] is True
        assert result["compra_id"] == "abc123"
        assert result["mercado"] == "Lidl"
        assert result["total"] == 15.50
        assert result["n_itens"] == 2
        assert result["alertas"] == []
        assert "Lidl" in result["mensagem"]
        assert "22/02/2026" in result["mensagem"]
        assert "Leite" in result["mensagem"]
        assert "×2" in result["mensagem"]  # quantidade != 1

    def test_formato_com_alertas(self):
        from datetime import date

        svc = self._make_svc()
        nota = {
            "mercado": "Aldi",
            "data_obj": date(2026, 2, 20),
            "total": 5.0,
            "itens": [
                {
                    "produto": "Arroz",
                    "quantidade": 1.0,
                    "preco_total": 2.50,
                    "preco_unitario": 2.50,
                    "unidade": "kg",
                    "categoria": "Mercearia",
                },
            ],
        }
        alertas = ["⚠️ *Arroz* went up 25% (was €2.00, now €2.50)"]
        result = svc._formatar_resposta_nota(nota, alertas=alertas, compra_id="x1")
        assert result["alertas"] == alertas
        assert "Price alerts" in result["mensagem"]
        assert "went up 25%" in result["mensagem"]

    def test_formato_mais_de_15_itens(self):
        from datetime import date

        svc = self._make_svc()
        itens = [
            {
                "produto": f"Produto {i}",
                "quantidade": 1.0,
                "preco_total": 1.0,
                "preco_unitario": 1.0,
                "unidade": "un",
                "categoria": "Outros",
            }
            for i in range(20)
        ]
        nota = {
            "mercado": "Continente",
            "data_obj": date(2026, 1, 15),
            "total": 20.0,
            "itens": itens,
        }
        result = svc._formatar_resposta_nota(nota, alertas=[], compra_id=None)
        assert result["n_itens"] == 20
        assert "...and 5 more items" in result["mensagem"]
        assert result["compra_id"] is None

    def test_formato_quantidade_1_sem_multiplicador(self):
        from datetime import date

        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data_obj": date(2026, 2, 22),
            "total": 1.50,
            "itens": [
                {
                    "produto": "Pão",
                    "quantidade": 1.0,
                    "preco_total": 1.50,
                    "preco_unitario": 1.50,
                    "unidade": "un",
                    "categoria": "Padaria",
                },
            ],
        }
        result = svc._formatar_resposta_nota(nota, alertas=[], compra_id=None)
        assert "×" not in result["mensagem"]


# ── Testes: Supabase list operations ───────────────────────────────────────


class TestSupabaseList:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        svc._initialized = True
        svc._call_count = 0
        svc._error_count = 0
        svc._total_latency = 0.0
        svc._http = AsyncMock()

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.get_client.return_value = MagicMock()
        svc._db = mock_db
        return svc

    def test_get_client_returns_supabase(self):
        svc = self._make_svc()
        client = svc._get_client()
        assert client is not None

    def test_get_client_raises_if_no_db(self):
        from services.core import ServiceUnavailableError

        svc = self._make_svc()
        svc._db = None
        with pytest.raises(ServiceUnavailableError):
            svc._get_client()

    def test_get_client_raises_if_not_initialized(self):
        from services.core import ServiceUnavailableError

        svc = self._make_svc()
        svc._db.is_initialized.return_value = False
        with pytest.raises(ServiceUnavailableError):
            svc._get_client()

    @pytest.mark.asyncio
    async def test_ver_lista_empty(self):
        svc = self._make_svc()
        with patch.object(
            svc,
            "_get_lista",
            new_callable=AsyncMock,
            return_value=[],
        ):
            result = await svc.ver_lista(user_id="u1")
            assert result["total"] == 0
            assert "empty" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_ver_lista_with_items(self):
        svc = self._make_svc()
        with patch.object(
            svc,
            "_get_lista",
            new_callable=AsyncMock,
            return_value=["leite", "pão"],
        ):
            result = await svc.ver_lista(user_id="u1")
            assert result["total"] == 2
            assert "leite" in result["mensagem"]


# ── Testes: _initialize e _health_check ─────────────────────────────────────


class TestServiceInit:
    @pytest.mark.asyncio
    async def test_initialize_creates_http_client(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        svc._http = None
        svc._db = None

        mock_db = MagicMock()
        with patch(
            "services.get_service",
            return_value=mock_db,
        ):
            await svc._initialize()
        assert svc._http is not None
        assert svc._db is mock_db
        await svc._http.aclose()

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        svc._db = mock_db

        result = await svc._health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_no_db(self):
        """Health check deve retornar False se db não disponível."""
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        svc._db = None

        result = await svc._health_check()
        assert result is False


# ── Testes: processar_nota (pipeline completo) ──────────────────────────────


class TestProcessarNota:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        svc._initialized = True
        svc._http = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_processar_nota_gpt4_sucesso(self):
        """Gemini fails, GPT-4 succeeds."""
        svc = self._make_svc()
        nota_raw = {
            "mercado": "Lidl",
            "data": "22/02/2026",
            "total": 5.00,
            "itens": [
                {
                    "produto": "Leite",
                    "quantidade": 1,
                    "preco_total": 1.09,
                    "preco_unitario": 1.09,
                }
            ],
        }

        with (
            patch.object(
                svc, "_extrair_gemini", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                svc, "_extrair_gpt4", new_callable=AsyncMock, return_value=nota_raw
            ),
            patch.object(
                svc, "_verificar_duplicata", new_callable=AsyncMock, return_value=False
            ),
            patch.object(
                svc,
                "_guardar_compra",
                new_callable=AsyncMock,
                return_value="compra-001",
            ),
            patch.object(
                svc, "_verificar_alertas", new_callable=AsyncMock, return_value=[]
            ),
        ):
            result = await svc.processar_nota(b"image_bytes", "chat1")
            assert result["sucesso"] is True
            assert result["mercado"] == "Lidl"
            assert result["compra_id"] == "compra-001"

    @pytest.mark.asyncio
    async def test_processar_nota_fallback_google_vision(self):
        """Gemini and GPT-4 fail, Google Vision succeeds."""
        svc = self._make_svc()
        nota_raw = {
            "mercado": "Aldi",
            "data": "20/02/2026",
            "total": 3.00,
            "itens": [
                {
                    "produto": "Pão",
                    "quantidade": 1,
                    "preco_total": 0.80,
                    "preco_unitario": 0.80,
                }
            ],
        }

        with (
            patch.object(
                svc, "_extrair_gemini", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                svc, "_extrair_gpt4", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                svc,
                "_extrair_google_vision",
                new_callable=AsyncMock,
                return_value=nota_raw,
            ),
            patch.object(
                svc, "_verificar_duplicata", new_callable=AsyncMock, return_value=False
            ),
            patch.object(
                svc,
                "_guardar_compra",
                new_callable=AsyncMock,
                return_value="compra-002",
            ),
            patch.object(
                svc, "_verificar_alertas", new_callable=AsyncMock, return_value=[]
            ),
        ):
            result = await svc.processar_nota(b"image_bytes", "chat1")
            assert result["sucesso"] is True
            svc._extrair_google_vision.assert_called_once()

    @pytest.mark.asyncio
    async def test_processar_nota_gpt4_sem_itens_fallback(self):
        """GPT-4 retorna nota sem itens -> fallback para Google Vision."""
        svc = self._make_svc()
        nota_vazia = {"mercado": "Lidl", "data": "22/02/2026", "total": 0, "itens": []}
        nota_ok = {
            "mercado": "Lidl",
            "data": "22/02/2026",
            "total": 2.0,
            "itens": [
                {
                    "produto": "Leite",
                    "quantidade": 1,
                    "preco_total": 2.0,
                    "preco_unitario": 2.0,
                }
            ],
        }

        with (
            patch.object(
                svc, "_extrair_gemini", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                svc, "_extrair_gpt4", new_callable=AsyncMock, return_value=nota_vazia
            ),
            patch.object(
                svc,
                "_extrair_google_vision",
                new_callable=AsyncMock,
                return_value=nota_ok,
            ),
            patch.object(
                svc, "_verificar_duplicata", new_callable=AsyncMock, return_value=False
            ),
            patch.object(
                svc, "_guardar_compra", new_callable=AsyncMock, return_value="c3"
            ),
            patch.object(
                svc, "_verificar_alertas", new_callable=AsyncMock, return_value=[]
            ),
        ):
            result = await svc.processar_nota(b"img", "chat1")
            assert result["sucesso"] is True

    @pytest.mark.asyncio
    async def test_processar_nota_todos_falham(self):
        """All three OCR providers fail -> graceful error."""
        svc = self._make_svc()

        with (
            patch.object(
                svc, "_extrair_gemini", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                svc, "_extrair_gpt4", new_callable=AsyncMock, return_value=None
            ),
            patch.object(
                svc, "_extrair_google_vision", new_callable=AsyncMock, return_value=None
            ),
        ):
            result = await svc.processar_nota(b"img", "chat1")
            assert result["sucesso"] is False
            assert "Could not read the receipt" in result["mensagem"]


# ── Testes: _extrair_gpt4 ──────────────────────────────────────────────────


class TestExtrairGpt4:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_extrair_gpt4_sucesso(self):
        svc = self._make_svc()
        import json

        nota_json = json.dumps(
            {
                "mercado": "Lidl",
                "data": "22/02/2026",
                "total": 5.0,
                "itens": [
                    {
                        "produto": "Leite",
                        "quantidade": 1,
                        "preco_total": 1.09,
                        "preco_unitario": 1.09,
                    }
                ],
            }
        )

        mock_msg = MagicMock()
        mock_msg.content = nota_json
        mock_choice = MagicMock()
        mock_choice.message = mock_msg
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.client = mock_client

        with patch("services.get_service", return_value=mock_openai):
            result = await svc._extrair_gpt4(b"fake_image", "image/jpeg")
            assert result is not None
            assert result["mercado"] == "Lidl"
            assert len(result["itens"]) == 1

    @pytest.mark.asyncio
    async def test_extrair_gpt4_openai_indisponivel(self):
        svc = self._make_svc()
        with patch("services.get_service", return_value=None):
            result = await svc._extrair_gpt4(b"fake_image", "image/jpeg")
            assert result is None

    @pytest.mark.asyncio
    async def test_extrair_gpt4_openai_nao_inicializado(self):
        svc = self._make_svc()
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = False
        with patch("services.get_service", return_value=mock_openai):
            result = await svc._extrair_gpt4(b"fake_image", "image/jpeg")
            assert result is None

    @pytest.mark.asyncio
    async def test_extrair_gpt4_exception(self):
        svc = self._make_svc()
        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )

        with patch("services.get_service", return_value=mock_openai):
            result = await svc._extrair_gpt4(b"fake_image", "image/jpeg")
            assert result is None

    @pytest.mark.asyncio
    async def test_extrair_gpt4_json_com_markdown(self):
        """GPT-4 pode retornar JSON envolto em ```json ... ```."""
        svc = self._make_svc()
        import json

        nota_json = (
            "```json\n"
            + json.dumps(
                {
                    "mercado": "Aldi",
                    "data": "01/01/2026",
                    "total": 3.0,
                    "itens": [
                        {
                            "produto": "Pão",
                            "quantidade": 1,
                            "preco_total": 0.80,
                            "preco_unitario": 0.80,
                        }
                    ],
                }
            )
            + "\n```"
        )

        mock_msg = MagicMock()
        mock_msg.content = nota_json
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_msg)]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.client = mock_client

        with patch("services.get_service", return_value=mock_openai):
            result = await svc._extrair_gpt4(b"img", "image/jpeg")
            assert result is not None
            assert result["mercado"] == "Aldi"


# ── Testes: _extrair_google_vision ─────────────────────────────────────────


class TestExtrairGoogleVision:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_google_vision_sucesso(self):
        import json

        svc = self._make_svc()

        ocr_response = {
            "responses": [
                {
                    "textAnnotations": [
                        {"description": "LIDL\nLeite 1.09\nPão 0.80\nTOTAL 1.89"}
                    ]
                }
            ]
        }
        nota_json = json.dumps(
            {
                "mercado": "Lidl",
                "data": "22/02/2026",
                "total": 1.89,
                "itens": [
                    {
                        "produto": "Leite",
                        "quantidade": 1,
                        "preco_total": 1.09,
                        "preco_unitario": 1.09,
                    },
                    {
                        "produto": "Pão",
                        "quantidade": 1,
                        "preco_total": 0.80,
                        "preco_unitario": 0.80,
                    },
                ],
            }
        )

        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 200
        mock_http_resp.json.return_value = ocr_response

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_http_resp)
        svc._http = mock_http

        mock_msg = MagicMock()
        mock_msg.content = nota_json
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=mock_msg)]

        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        mock_openai = MagicMock()
        mock_openai.is_initialized.return_value = True
        mock_openai.client = mock_client

        with patch("services.get_service", return_value=mock_openai):
            result = await svc._extrair_google_vision(b"img_data")
            assert result is not None
            assert result["mercado"] == "Lidl"

    @pytest.mark.asyncio
    async def test_google_vision_api_error(self):
        svc = self._make_svc()
        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 403

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_http_resp)
        svc._http = mock_http

        result = await svc._extrair_google_vision(b"img_data")
        assert result is None

    @pytest.mark.asyncio
    async def test_google_vision_texto_curto(self):
        """OCR com texto muito curto (<20 chars) deve retornar None."""
        svc = self._make_svc()
        ocr_response = {"responses": [{"textAnnotations": [{"description": "short"}]}]}

        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 200
        mock_http_resp.json.return_value = ocr_response

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_http_resp)
        svc._http = mock_http

        result = await svc._extrair_google_vision(b"img_data")
        assert result is None

    @pytest.mark.asyncio
    async def test_google_vision_openai_indisponivel(self):
        """OCR OK mas OpenAI indisponível → None."""
        svc = self._make_svc()
        ocr_response = {
            "responses": [
                {
                    "textAnnotations": [
                        {
                            "description": "LIDL\nLeite 1.09\nPão 0.80\nTOTAL 1.89 long enough text"
                        }
                    ]
                }
            ]
        }

        mock_http_resp = MagicMock()
        mock_http_resp.status_code = 200
        mock_http_resp.json.return_value = ocr_response

        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_http_resp)
        svc._http = mock_http

        with patch("services.get_service", return_value=None):
            result = await svc._extrair_google_vision(b"img_data")
            assert result is None

    @pytest.mark.asyncio
    async def test_google_vision_exception(self):
        """Qualquer exceção → None (graceful)."""
        svc = self._make_svc()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=RuntimeError("connection failed"))
        svc._http = mock_http

        result = await svc._extrair_google_vision(b"img_data")
        assert result is None


# ── Testes: _guardar_compra ─────────────────────────────────────────────────


class TestGuardarCompra:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_guardar_compra_sucesso(self):
        from datetime import date

        svc = self._make_svc()

        mock_compra_res = MagicMock()
        mock_compra_res.data = [{"id": "compra-abc"}]

        mock_itens_res = MagicMock()

        mock_table = MagicMock()
        mock_table.insert.return_value.execute.side_effect = [
            mock_compra_res,
            mock_itens_res,
        ]

        mock_db = MagicMock()
        mock_db.table.return_value = mock_table

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        nota = {
            "mercado": "Lidl",
            "data_obj": date(2026, 2, 22),
            "total": 5.0,
            "itens": [
                {
                    "produto": "Leite",
                    "categoria": "Laticínios",
                    "quantidade": 1.0,
                    "unidade": "un",
                    "preco_total": 1.09,
                    "preco_unitario": 1.09,
                },
            ],
        }

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc._guardar_compra(nota, "chat1", "gpt4_vision")
            assert result == "compra-abc"

    @pytest.mark.asyncio
    async def test_guardar_compra_supabase_indisponivel(self):
        from datetime import date

        svc = self._make_svc()

        with patch("services.get_service", return_value=None):
            result = await svc._guardar_compra(
                {"mercado": "X", "data_obj": date.today(), "total": 5, "itens": []},
                "chat1",
                "gpt4",
            )
            assert result is None

    @pytest.mark.asyncio
    async def test_guardar_compra_exception(self):
        from datetime import date

        svc = self._make_svc()

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client.table.return_value.insert.return_value.execute.side_effect = RuntimeError(
            "DB error"
        )

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc._guardar_compra(
                {"mercado": "X", "data_obj": date.today(), "total": 5, "itens": []},
                "chat1",
                "gpt4",
            )
            assert result is None


# ── Testes: _verificar_alertas ──────────────────────────────────────────────


class TestVerificarAlertas:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_alerta_subida_preco(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [
            {"preco_unitario": 1.00, "mercado": "Lidl", "data_compra": "2026-01-01"}
        ]

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.ilike.return_value.order.return_value.limit.return_value.execute.return_value = mock_res

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        itens = [
            {"produto": "Leite Mimosa", "preco_unitario": 1.80}
        ]  # 80% subida, €0.80 diff

        with patch("services.get_service", return_value=mock_supabase):
            alertas = await svc._verificar_alertas(itens, "chat1")
            assert len(alertas) == 1
            assert "went up" in alertas[0]

    @pytest.mark.asyncio
    async def test_sem_alerta_preco_estavel(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [
            {"preco_unitario": 1.00, "mercado": "Lidl", "data_compra": "2026-01-01"}
        ]

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.ilike.return_value.order.return_value.limit.return_value.execute.return_value = mock_res

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        itens = [
            {"produto": "Leite Mimosa", "preco_unitario": 1.10}
        ]  # 10% — abaixo do threshold

        with patch("services.get_service", return_value=mock_supabase):
            alertas = await svc._verificar_alertas(itens, "chat1")
            assert len(alertas) == 0

    @pytest.mark.asyncio
    async def test_sem_alerta_supabase_indisponivel(self):
        svc = self._make_svc()
        with patch("services.get_service", return_value=None):
            alertas = await svc._verificar_alertas(
                [{"produto": "X", "preco_unitario": 2.0}], "c1"
            )
            assert alertas == []

    @pytest.mark.asyncio
    async def test_sem_alerta_sem_historico(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = []

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.ilike.return_value.order.return_value.limit.return_value.execute.return_value = mock_res

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            alertas = await svc._verificar_alertas(
                [{"produto": "Pão", "preco_unitario": 0.80}], "c1"
            )
            assert alertas == []

    @pytest.mark.asyncio
    async def test_alerta_ignora_preco_zero(self):
        svc = self._make_svc()

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = MagicMock()

        with patch("services.get_service", return_value=mock_supabase):
            alertas = await svc._verificar_alertas(
                [{"produto": "X", "preco_unitario": 0}], "c1"
            )
            assert alertas == []

    @pytest.mark.asyncio
    async def test_alerta_ignora_preco_anterior_zero(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [
            {"preco_unitario": 0, "mercado": "Lidl", "data_compra": "2026-01-01"}
        ]

        mock_db = MagicMock()
        mock_db.table.return_value.select.return_value.eq.return_value.ilike.return_value.order.return_value.limit.return_value.execute.return_value = mock_res

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            alertas = await svc._verificar_alertas(
                [{"produto": "Leite", "preco_unitario": 1.50}], "c1"
            )
            assert alertas == []


# ── Testes: relatorio_mensal ────────────────────────────────────────────────


class TestRelatorioMensal:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_relatorio_com_dados(self):
        svc = self._make_svc()

        compras_res = MagicMock()
        compras_res.data = [
            {"mercado": "Lidl", "total": 25.50, "data_compra": "2026-02-10"},
            {"mercado": "Aldi", "total": 18.30, "data_compra": "2026-02-15"},
            {"mercado": "Lidl", "total": 12.00, "data_compra": "2026-02-20"},
        ]

        itens_res = MagicMock()
        itens_res.data = [
            {"categoria": "Laticínios", "preco_total": 5.50},
            {"categoria": "Padaria", "preco_total": 3.20},
            {"categoria": "Laticínios", "preco_total": 2.80},
        ]

        call_count = [0]

        def mock_execute():
            call_count[0] += 1
            if call_count[0] == 1:
                return compras_res
            return itens_res

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute = mock_execute
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.gte.return_value = mock_chain
        mock_chain.lte.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.relatorio_mensal("chat1", mes=2, ano=2026)
            assert "Report" in result["mensagem"]
            assert "Lidl" in result["mensagem"]
            assert "total" in result

    @pytest.mark.asyncio
    async def test_relatorio_sem_compras(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = []

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.gte.return_value = mock_chain
        mock_chain.lte.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.relatorio_mensal("chat1", mes=2, ano=2026)
            assert "No purchases" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_relatorio_exception(self):
        svc = self._make_svc()

        with patch("services.get_service", side_effect=RuntimeError("DB error")):
            result = await svc.relatorio_mensal("chat1")
            assert "Error" in result["mensagem"]


# ── Testes: comparar_produto ────────────────────────────────────────────────


class TestCompararProduto:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_comparar_com_dados(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [
            {
                "mercado": "Lidl",
                "preco_unitario": 1.09,
                "data_compra": "2026-02-20",
                "unidade": "un",
            },
            {
                "mercado": "Aldi",
                "preco_unitario": 1.19,
                "data_compra": "2026-02-18",
                "unidade": "un",
            },
            {
                "mercado": "Lidl",
                "preco_unitario": 1.05,
                "data_compra": "2026-02-15",
                "unidade": "un",
            },
        ]

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.ilike.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.comparar_produto("leite", "chat1")
            assert "Price comparison" in result["mensagem"]
            assert "poupanca" in result

    @pytest.mark.asyncio
    async def test_comparar_sem_dados(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = []

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.ilike.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.comparar_produto("xyz", "chat1")
            assert "don't have data" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_comparar_sem_precos_validos(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [
            {
                "mercado": "Lidl",
                "preco_unitario": 0,
                "data_compra": "2026-02-20",
                "unidade": "un",
            },
        ]

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_chain.ilike.return_value = mock_chain
        mock_chain.order.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.comparar_produto("leite", "chat1")
            assert "No price data" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_comparar_exception(self):
        svc = self._make_svc()

        with patch("services.get_service", side_effect=RuntimeError("DB")):
            result = await svc.comparar_produto("leite", "chat1")
            assert "Error" in result["mensagem"]


# ── Testes: ranking_mercados ────────────────────────────────────────────────


class TestRankingMercados:
    def _make_svc(self):
        import logging
        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        return svc

    @pytest.mark.asyncio
    async def test_ranking_com_dados(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [
            {"mercado": "Lidl", "total": 50.00},
            {"mercado": "Aldi", "total": 30.00},
            {"mercado": "Lidl", "total": 25.00},
            {"mercado": "Continente", "total": 80.00},
        ]

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.ranking_mercados("chat1")
            assert "Store Ranking" in result["mensagem"]
            assert "ranking" in result
            assert "Where you spend least" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_ranking_sem_dados(self):
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = []

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.ranking_mercados("chat1")
            assert "No purchase history" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_ranking_exception(self):
        svc = self._make_svc()

        with patch("services.get_service", side_effect=RuntimeError("DB")):
            result = await svc.ranking_mercados("chat1")
            assert "Error" in result["mensagem"]

    @pytest.mark.asyncio
    async def test_ranking_mercado_unico(self):
        """Com apenas um mercado, não deve ter 'Onde gastas menos'."""
        svc = self._make_svc()

        mock_res = MagicMock()
        mock_res.data = [{"mercado": "Lidl", "total": 50.00}]

        mock_db = MagicMock()
        mock_chain = MagicMock()
        mock_chain.execute.return_value = mock_res
        mock_chain.select.return_value = mock_chain
        mock_chain.eq.return_value = mock_chain
        mock_db.table.return_value = mock_chain

        mock_supabase = MagicMock()
        mock_supabase.is_initialized.return_value = True
        mock_supabase.client = mock_db

        with patch("services.get_service", return_value=mock_supabase):
            result = await svc.ranking_mercados("chat1")
            assert "Store Ranking" in result["mensagem"]
            assert "Where you spend least" not in result["mensagem"]


# ── Testes: mais categorias ────────────────────────────────────────────────


class TestCategorizacaoCompleta:
    def test_frutas(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Banana Madeira") == "Frutas"
        assert _categorizar("Maçã Royal Gala") == "Frutas"

    def test_legumes(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Tomate Cherry") == "Legumes"
        assert _categorizar("Batata") == "Legumes"

    def test_limpeza(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Detergente Fairy") == "Limpeza"

    def test_snacks(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Chocolate Milka") == "Snacks"
        assert _categorizar("Bolacha Maria") == "Snacks"

    def test_carnes_variadas(self):
        from services.business.mercado_service import _categorizar

        assert _categorizar("Bife de Peru") == "Carnes"
        assert _categorizar("Carne Picada") == "Carnes"


# ── Testes: _extrair_gemini ──────────────────────────────────────────────────


class TestExtrairGemini:
    """Tests for Gemini OCR extraction."""

    def _make_svc(self):
        import logging

        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        svc._initialized = True
        svc._http = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_gemini_success(self):
        """Gemini returns valid receipt data."""
        import json

        svc = self._make_svc()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "mercado": "Lidl",
                                        "data": "04/03/2026",
                                        "total": 25.50,
                                        "itens": [
                                            {
                                                "produto": "Leite",
                                                "quantidade": 2,
                                                "unidade": "un",
                                                "preco_total": 1.98,
                                                "preco_unitario": 0.99,
                                            },
                                            {
                                                "produto": "Pao",
                                                "quantidade": 1,
                                                "unidade": "un",
                                                "preco_total": 0.89,
                                                "preco_unitario": 0.89,
                                            },
                                        ],
                                    }
                                )
                            }
                        ]
                    }
                }
            ]
        }
        svc._http.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = await svc._extrair_gemini(b"fake_image", "image/jpeg")

        assert result is not None
        assert result["mercado"] == "Lidl"
        assert len(result["itens"]) == 2

    @pytest.mark.asyncio
    async def test_gemini_no_api_key(self):
        """Returns None when GEMINI_API_KEY not set."""
        svc = self._make_svc()
        with patch.dict("os.environ", {}, clear=True):
            result = await svc._extrair_gemini(b"fake", "image/jpeg")
        assert result is None

    @pytest.mark.asyncio
    async def test_gemini_http_error(self):
        """Returns None on HTTP error."""
        svc = self._make_svc()
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        svc._http.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = await svc._extrair_gemini(b"fake", "image/jpeg")
        assert result is None

    @pytest.mark.asyncio
    async def test_gemini_invalid_json(self):
        """Returns None when Gemini returns invalid JSON."""
        svc = self._make_svc()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": "not json"}]}}]
        }
        svc._http.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = await svc._extrair_gemini(b"fake", "image/jpeg")
        assert result is None

    @pytest.mark.asyncio
    async def test_gemini_empty_text(self):
        """Returns None when Gemini returns empty text."""
        svc = self._make_svc()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "candidates": [{"content": {"parts": [{"text": ""}]}}]
        }
        svc._http.post = AsyncMock(return_value=mock_response)

        with patch.dict("os.environ", {"GEMINI_API_KEY": "test-key"}):
            result = await svc._extrair_gemini(b"fake", "image/jpeg")
        assert result is None

    @pytest.mark.asyncio
    async def test_processar_nota_gemini_primary(self):
        """processar_nota uses Gemini as primary."""
        svc = self._make_svc()
        nota = {
            "mercado": "Aldi",
            "data": "01/03/2026",
            "total": 10.0,
            "itens": [
                {
                    "produto": "Arroz",
                    "quantidade": 1,
                    "unidade": "un",
                    "preco_total": 1.50,
                    "preco_unitario": 1.50,
                }
            ],
        }
        svc._extrair_gemini = AsyncMock(return_value=nota)
        svc._extrair_gpt4 = AsyncMock()  # should NOT be called
        svc._verificar_duplicata = AsyncMock(return_value=False)
        svc._guardar_compra = AsyncMock(return_value="123")
        svc._verificar_alertas = AsyncMock(return_value=[])

        result = await svc.processar_nota(b"img", "chat1")

        svc._extrair_gemini.assert_called_once()
        svc._extrair_gpt4.assert_not_called()
        assert result["sucesso"] is True

    @pytest.mark.asyncio
    async def test_processar_nota_gemini_fails_gpt4_fallback(self):
        """Falls back to GPT-4 when Gemini fails."""
        svc = self._make_svc()
        nota = {
            "mercado": "Pingo Doce",
            "data": "01/03/2026",
            "total": 5.0,
            "itens": [
                {
                    "produto": "Banana",
                    "quantidade": 1,
                    "unidade": "un",
                    "preco_total": 0.50,
                    "preco_unitario": 0.50,
                }
            ],
        }
        svc._extrair_gemini = AsyncMock(return_value=None)
        svc._extrair_gpt4 = AsyncMock(return_value=nota)
        svc._verificar_duplicata = AsyncMock(return_value=False)
        svc._guardar_compra = AsyncMock(return_value="456")
        svc._verificar_alertas = AsyncMock(return_value=[])

        result = await svc.processar_nota(b"img", "chat2")

        svc._extrair_gemini.assert_called_once()
        svc._extrair_gpt4.assert_called_once()
        assert result["sucesso"] is True


# ── Testes: _verificar_duplicata ─────────────────────────────────────────────


class TestVerificarDuplicata:
    """Tests for duplicate receipt detection."""

    def _make_svc(self):
        import logging

        from services.business.mercado_service import MercadoService

        svc = MercadoService.__new__(MercadoService)
        svc.name = "mercado"
        svc.logger = logging.getLogger("test.mercado")
        svc._initialized = True
        svc._http = AsyncMock()
        return svc

    @pytest.mark.asyncio
    async def test_duplicata_found(self):
        """Returns True when duplicate exists."""
        svc = self._make_svc()
        from datetime import date

        mock_result = MagicMock()
        mock_result.data = [{"id": "existing-123"}]

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.client.table.return_value = mock_query

        with patch(
            "services.get_service",
            return_value=mock_db,
        ):
            result = await svc._verificar_duplicata(
                "chat1", "Lidl", date(2026, 3, 4), 25.50
            )
        assert result is True

    @pytest.mark.asyncio
    async def test_duplicata_not_found(self):
        """Returns False when no duplicate."""
        svc = self._make_svc()
        from datetime import date

        mock_result = MagicMock()
        mock_result.data = []

        mock_query = MagicMock()
        mock_query.select.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.limit.return_value = mock_query
        mock_query.execute.return_value = mock_result

        mock_db = MagicMock()
        mock_db.is_initialized.return_value = True
        mock_db.client.table.return_value = mock_query

        with patch(
            "services.get_service",
            return_value=mock_db,
        ):
            result = await svc._verificar_duplicata(
                "chat1", "Lidl", date(2026, 3, 4), 25.50
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_duplicata_exception_returns_false(self):
        """Returns False on exception (let it save)."""
        svc = self._make_svc()
        from datetime import date

        with patch(
            "services.get_service",
            side_effect=Exception("db down"),
        ):
            result = await svc._verificar_duplicata(
                "chat1", "Lidl", date(2026, 3, 4), 10.0
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_duplicata_no_db_returns_false(self):
        """Returns False when database unavailable."""
        svc = self._make_svc()
        from datetime import date

        with patch(
            "services.get_service",
            return_value=None,
        ):
            result = await svc._verificar_duplicata(
                "chat1", "Lidl", date(2026, 3, 4), 5.0
            )
        assert result is False

    @pytest.mark.asyncio
    async def test_processar_nota_duplicata_skips_save(self):
        """Duplicate receipt returns warning, does NOT save."""
        svc = self._make_svc()
        nota = {
            "mercado": "Lidl",
            "data": "04/03/2026",
            "total": 25.50,
            "itens": [
                {
                    "produto": "Leite",
                    "quantidade": 1,
                    "preco_total": 1.09,
                    "preco_unitario": 1.09,
                }
            ],
        }
        svc._extrair_gemini = AsyncMock(return_value=nota)
        svc._verificar_duplicata = AsyncMock(return_value=True)
        svc._guardar_compra = AsyncMock()
        svc._verificar_alertas = AsyncMock()

        result = await svc.processar_nota(b"img", "chat1")

        assert result["sucesso"] is True
        assert result["duplicada"] is True
        assert "was already registered" in result["mensagem"]
        svc._guardar_compra.assert_not_called()
        svc._verificar_alertas.assert_not_called()
