# -*- coding: utf-8 -*-
"""
Mercado Service
===============
Lista de compras inteligente + análise de notas fiscais com IA.

Features:
  - Lista de compras via n8n → Google Sheets (visual)
  - Processamento de notas fiscais (GPT-4 Vision + Google Vision fallback)
  - Histórico de preços por produto e mercado no Supabase
  - Relatórios mensais de gastos
  - Comparação de preços entre mercados
  - Alertas automáticos de subida de preço (>20%)
"""

import base64
import logging
import time
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

# ── Constantes ────────────────────────────────────────────────────────────────
N8N_WEBHOOK = "https://btrix.app.n8n.cloud/webhook/mercado"
SPREADSHEET_ID = "1OFBqEmc8SFTsB-DWrxZWEvbk3Pt3MR2exribuXNtVzs"
PRICE_ALERT_THRESHOLD = 0.20  # 20% de subida dispara alerta

# ── Categorias automáticas ────────────────────────────────────────────────────
_CATEGORIAS: Dict[str, List[str]] = {
    "Laticínios":   ["leite", "manteiga", "queijo", "iogurte", "natas", "requeijão"],
    "Padaria":      ["pão", "bolo", "croissant", "broa", "torrada"],
    "Carnes":       ["frango", "carne", "bife", "peru", "porco", "vaca", "alheira"],
    "Peixe":        ["peixe", "bacalhau", "atum", "sardinha", "salmão", "camarão"],
    "Frutas":       ["maçã", "banana", "laranja", "uva", "morango", "pera", "limão"],
    "Legumes":      ["alface", "tomate", "cenoura", "cebola", "batata", "alho"],
    "Bebidas":      ["água", "sumo", "cerveja", "vinho", "refrigerante", "café"],
    "Limpeza":      ["detergente", "sabão", "lixívia", "amaciador"],
    "Higiene":      ["shampoo", "gel", "pasta", "desodorizante", "papel higiénico"],
    "Mercearia":    ["arroz", "massa", "feijão", "lentilha", "grão", "açúcar", "farinha", "óleo", "azeite"],
    "Ovos":         ["ovo", "ovos"],
    "Snacks":       ["bolacha", "chips", "chocolate", "biscoito"],
}

_VISION_PROMPT = """Analisa esta nota/recibo de supermercado e extrai TODOS os itens comprados.

Responde APENAS com JSON válido, sem markdown, sem explicações:

{
  "mercado": "Nome do supermercado (ex: Lidl, Aldi, Continente, Pingo Doce)",
  "data": "DD/MM/AAAA ou null se não visível",
  "total": 0.00,
  "itens": [
    {
      "produto": "Nome do produto normalizado em português",
      "quantidade": 1,
      "unidade": "un/kg/L",
      "preco_total": 0.00,
      "preco_unitario": 0.00
    }
  ]
}

Regras:
- Normaliza nomes: "LT MIMOSA MEIO-GORD" → "Leite Mimosa Meio-Gordo"
- Se não conseguires ler algum valor, usa null
- preco_unitario = preco_total / quantidade
- Inclui TODOS os itens, mesmo os que não consegues ler bem"""


def _categorizar(produto: str) -> str:
    nome = produto.lower()
    for categoria, keywords in _CATEGORIAS.items():
        if any(kw in nome for kw in keywords):
            return categoria
    return "Outros"


@register_service("mercado")
class MercadoService(BaseService):
    """
    Mercado inteligente: lista de compras + notas fiscais + análise de preços.
    """

    def __init__(self):
        super().__init__(name="mercado")
        self._http: Optional[httpx.AsyncClient] = None

    async def _initialize(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        self.logger.info("MercadoService initialized")

    async def _health_check(self) -> bool:
        try:
            _ = await self._http.get(N8N_WEBHOOK.replace("/webhook/", "/webhook-test/") + "/health")
            return True  # n8n pode não ter health endpoint — só verificar conexão
        except Exception:
            return True  # não bloquear o serviço se o n8n não responder

    # ── Lista de compras (via n8n → Google Sheets) ────────────────────────────

    async def _n8n_call(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Chama o webhook n8n da lista de compras."""
        if not self.is_initialized():
            await self.initialize()
        start = time.time()
        try:
            resp = await self._http.post(N8N_WEBHOOK, json=payload)
            resp.raise_for_status()
            self._track_call(time.time() - start, error=False)
            return resp.json()
        except httpx.HTTPStatusError as e:
            self._track_call(time.time() - start, error=True)
            raise ServiceUnavailableError(f"n8n webhook error: {e.response.status_code}")
        except Exception as e:
            self._track_call(time.time() - start, error=True)
            raise ServiceUnavailableError(f"n8n connection error: {e}")

    async def adicionar(self, itens: str) -> Dict[str, Any]:
        return await self._n8n_call({"action": "adicionar", "itens": itens})

    async def ver_lista(self) -> Dict[str, Any]:
        return await self._n8n_call({"action": "lista"})

    async def remover(self, item: str) -> Dict[str, Any]:
        return await self._n8n_call({"action": "remover", "item": item})

    async def limpar_lista(self) -> Dict[str, Any]:
        return await self._n8n_call({"action": "limpar"})

    async def historico_lista(self) -> Dict[str, Any]:
        return await self._n8n_call({"action": "historico"})

    # ── Processamento de nota fiscal ──────────────────────────────────────────

    async def processar_nota(
        self,
        image_data: bytes,
        chat_id: str,
        mime_type: str = "image/jpeg",
    ) -> Dict[str, Any]:
        """
        Processa foto de nota fiscal.
        GPT-4 Vision primeiro, Google Vision como fallback.
        Guarda no Supabase e verifica alertas de preço.
        """
        self.logger.info("Processando nota fiscal chat_id=%s", chat_id)

        nota = await self._extrair_gpt4(image_data, mime_type)
        fonte = "gpt4_vision"

        if not nota or not nota.get("itens"):
            self.logger.warning("GPT-4 Vision falhou, tentando Google Vision")
            nota = await self._extrair_google_vision(image_data)
            fonte = "google_vision"

        if not nota or not nota.get("itens"):
            return {
                "sucesso": False,
                "mensagem": (
                    "❌ Não consegui ler a nota fiscal.\n\n"
                    "💡 Dicas: boa iluminação, nota plana, câmera estável."
                ),
            }

        nota = self._normalizar_nota(nota)
        compra_id = await self._guardar_compra(nota, chat_id, fonte)
        alertas = await self._verificar_alertas(nota["itens"], chat_id)

        return self._formatar_resposta_nota(nota, alertas, compra_id)

    async def _extrair_gpt4(
        self, image_data: bytes, mime_type: str
    ) -> Optional[Dict[str, Any]]:
        """Extrai dados da nota via GPT-4 Vision."""
        try:
            from services import get_service
            openai_svc = get_service("openai")
            if not openai_svc or not openai_svc.is_initialized():
                return None

            import json
            b64 = base64.b64encode(image_data).decode()
            client = openai_svc.client

            response = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _VISION_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }],
                max_tokens=2000,
                temperature=0.1,
            )
            text = response.choices[0].message.content.strip()
            text = text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
        except Exception as e:
            self.logger.error("GPT-4 Vision error: %s", e)
            return None

    async def _extrair_google_vision(
        self, image_data: bytes
    ) -> Optional[Dict[str, Any]]:
        """Fallback: Google Vision OCR + GPT-4 text para parsear."""
        try:
            import json
            b64 = base64.b64encode(image_data).decode()

            resp = await self._http.post(
                "https://vision.googleapis.com/v1/images:annotate",
                json={"requests": [{
                    "image": {"content": b64},
                    "features": [{"type": "TEXT_DETECTION"}],
                }]},
            )
            if resp.status_code != 200:
                return None

            text_ocr = (
                resp.json()
                .get("responses", [{}])[0]
                .get("textAnnotations", [{}])[0]
                .get("description", "")
            )
            if not text_ocr or len(text_ocr) < 20:
                return None

            from services import get_service
            openai_svc = get_service("openai")
            if not openai_svc or not openai_svc.is_initialized():
                return None

            prompt = f"{_VISION_PROMPT}\n\nTexto OCR extraído:\n{text_ocr}"
            response = await openai_svc.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=2000,
                temperature=0.1,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            return json.loads(raw)
        except Exception as e:
            self.logger.error("Google Vision fallback error: %s", e)
            return None

    def _normalizar_nota(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normaliza dados extraídos: datas, preços, categorias."""
        # Data
        data_raw = data.get("data")
        data_obj = date.today()
        if data_raw:
            for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
                try:
                    data_obj = datetime.strptime(data_raw, fmt).date()
                    break
                except ValueError:
                    continue
        data["data_obj"] = data_obj

        # Total
        if not data.get("total"):
            data["total"] = round(
                sum(float(i.get("preco_total") or 0) for i in data.get("itens", [])), 2
            )

        # Mercado
        if not data.get("mercado"):
            data["mercado"] = "Desconhecido"

        # Itens
        itens_ok = []
        for item in data.get("itens", []):
            if not item.get("produto"):
                continue
            qtd = float(item.get("quantidade") or 1)
            p_total = float(item.get("preco_total") or 0)
            p_unit = float(item.get("preco_unitario") or 0)
            if p_unit == 0 and p_total > 0 and qtd > 0:
                p_unit = round(p_total / qtd, 4)
            if p_total == 0 and p_unit > 0:
                p_total = round(p_unit * qtd, 2)
            item.update({
                "preco_total":    p_total,
                "preco_unitario": p_unit,
                "quantidade":     qtd,
                "unidade":        item.get("unidade") or "un",
                "categoria":      _categorizar(item["produto"]),
            })
            itens_ok.append(item)

        data["itens"] = itens_ok
        return data

    async def _guardar_compra(
        self, nota: Dict[str, Any], chat_id: str, fonte: str
    ) -> Optional[str]:
        """Insere compra e itens no Supabase."""
        try:
            from services import get_service
            supabase_svc = get_service("supabase")
            if not supabase_svc or not supabase_svc.is_initialized():
                self.logger.warning("Supabase não disponível — compra não guardada")
                return None

            db = supabase_svc.client

            compra_res = db.table("mercado_compras").insert({
                "chat_id":        chat_id,
                "mercado":        nota["mercado"],
                "data_compra":    nota["data_obj"].isoformat(),
                "total":          float(nota.get("total") or 0),
                "fonte_extracao": fonte,
            }).execute()

            compra_id = compra_res.data[0]["id"]

            itens_payload = [
                {
                    "compra_id":      compra_id,
                    "chat_id":        chat_id,
                    "produto":        i["produto"],
                    "categoria":      i["categoria"],
                    "quantidade":     float(i["quantidade"]),
                    "unidade":        i["unidade"],
                    "preco_total":    float(i["preco_total"]),
                    "preco_unitario": float(i["preco_unitario"]),
                    "mercado":        nota["mercado"],
                    "data_compra":    nota["data_obj"].isoformat(),
                }
                for i in nota["itens"]
                if float(i.get("preco_total") or 0) > 0
            ]
            if itens_payload:
                db.table("mercado_itens").insert(itens_payload).execute()

            self.logger.info(
                "Compra guardada: id=%s, %d itens, €%.2f",
                compra_id, len(itens_payload), nota.get("total", 0),
            )
            return compra_id
        except Exception as e:
            self.logger.error("Erro ao guardar compra: %s", e, exc_info=True)
            return None

    async def _verificar_alertas(
        self, itens: List[Dict], chat_id: str
    ) -> List[str]:
        """Detecta subidas de preço > 20% vs última compra."""
        alertas: List[str] = []
        try:
            from services import get_service
            supabase_svc = get_service("supabase")
            if not supabase_svc or not supabase_svc.is_initialized():
                return alertas

            db = supabase_svc.client
            for item in itens:
                preco_atual = float(item.get("preco_unitario") or 0)
                if preco_atual <= 0:
                    continue

                res = (
                    db.table("mercado_itens")
                    .select("preco_unitario, mercado, data_compra")
                    .eq("chat_id", chat_id)
                    .ilike("produto", f"%{item['produto'].split()[0]}%")
                    .order("data_compra", desc=True)
                    .limit(1)
                    .execute()
                )
                if not res.data:
                    continue

                preco_anterior = float(res.data[0]["preco_unitario"])
                if preco_anterior <= 0:
                    continue

                variacao = (preco_atual - preco_anterior) / preco_anterior
                if variacao >= PRICE_ALERT_THRESHOLD:
                    alertas.append(
                        f"⚠️ *{item['produto']}* subiu {variacao:.0%} "
                        f"(era €{preco_anterior:.2f}, agora €{preco_atual:.2f})"
                    )
        except Exception as e:
            self.logger.warning("Erro ao verificar alertas: %s", e)
        return alertas

    def _formatar_resposta_nota(
        self,
        nota: Dict[str, Any],
        alertas: List[str],
        compra_id: Optional[str],
    ) -> Dict[str, Any]:
        itens = nota["itens"]
        mercado = nota["mercado"]
        data_str = nota["data_obj"].strftime("%d/%m/%Y")
        total = nota.get("total", 0)

        linhas = [
            f"🧾 *Nota registada — {mercado}*",
            f"📅 {data_str} · {len(itens)} itens · *€{total:.2f}*",
            "",
            "📋 *Itens:*",
        ]
        for item in itens[:15]:
            linha = f"  • {item['produto']}"
            if float(item.get("quantidade", 1)) != 1:
                linha += f" ×{item['quantidade']:.0f}{item.get('unidade','')}"
            linha += f" — €{item.get('preco_total', 0):.2f}"
            linhas.append(linha)

        if len(itens) > 15:
            linhas.append(f"  _...e mais {len(itens) - 15} itens_")

        if alertas:
            linhas += ["", "🔔 *Alertas de preço:*"] + alertas

        linhas += [
            "",
            "_Usa 'relatório mensal' para ver gastos do mês._",
            "_Usa 'comparar [produto]' para ver onde é mais barato._",
        ]

        return {
            "sucesso":   True,
            "compra_id": compra_id,
            "mercado":   mercado,
            "total":     total,
            "n_itens":   len(itens),
            "alertas":   alertas,
            "mensagem":  "\n".join(linhas),
        }

    # ── Relatórios ────────────────────────────────────────────────────────────

    async def relatorio_mensal(
        self,
        chat_id: str,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Relatório de gastos do mês com breakdown por mercado e categorias."""
        try:
            from services import get_service
            db = get_service("supabase").client

            hoje = date.today()
            mes = mes or hoje.month
            ano = ano or hoje.year
            mes_str = f"{ano}-{mes:02d}"

            res = (
                db.table("mercado_compras")
                .select("mercado, total, data_compra")
                .eq("chat_id", chat_id)
                .gte("data_compra", f"{mes_str}-01")
                .lte("data_compra", f"{mes_str}-31")
                .execute()
            )
            compras = res.data or []
            if not compras:
                nome_mes = self._nome_mes(mes)
                return {
                    "mensagem": (
                        f"📊 Sem compras registadas em {nome_mes} {ano}.\n\n"
                        "Tira uma foto da próxima nota fiscal!"
                    )
                }

            por_mercado: Dict[str, Dict] = {}
            total_geral = 0.0
            for c in compras:
                m = c["mercado"]
                v = float(c.get("total") or 0)
                if m not in por_mercado:
                    por_mercado[m] = {"total": 0.0, "visitas": 0}
                por_mercado[m]["total"] += v
                por_mercado[m]["visitas"] += 1
                total_geral += v

            ranking = sorted(por_mercado.items(), key=lambda x: x[1]["total"], reverse=True)
            nome_mes = self._nome_mes(mes)

            linhas = [
                f"📊 *Relatório — {nome_mes} {ano}*",
                f"💶 Total gasto: *€{total_geral:.2f}*",
                f"🏪 Mercados visitados: {len(por_mercado)}",
                "",
                "🏆 *Gastos por mercado:*",
            ]
            medalhas = ["🥇", "🥈", "🥉"]
            for i, (mercado, dados) in enumerate(ranking):
                emoji = medalhas[i] if i < 3 else "  "
                pct = (dados["total"] / total_geral * 100) if total_geral else 0
                linhas.append(
                    f"{emoji} *{mercado}*: €{dados['total']:.2f} "
                    f"({pct:.0f}%) — {dados['visitas']} visita(s)"
                )

            # Top categorias
            res2 = (
                db.table("mercado_itens")
                .select("categoria, preco_total")
                .eq("chat_id", chat_id)
                .gte("data_compra", f"{mes_str}-01")
                .lte("data_compra", f"{mes_str}-31")
                .execute()
            )
            if res2.data:
                cats: Dict[str, float] = {}
                for item in res2.data:
                    cat = item.get("categoria", "Outros")
                    cats[cat] = cats.get(cat, 0) + float(item.get("preco_total") or 0)
                top = sorted(cats.items(), key=lambda x: x[1], reverse=True)[:5]
                linhas += ["", "🛒 *Top categorias:*"]
                for cat, val in top:
                    linhas.append(f"  • {cat}: €{val:.2f}")

            return {"mensagem": "\n".join(linhas), "total": total_geral}
        except Exception as e:
            self.logger.error("Erro no relatório mensal: %s", e, exc_info=True)
            return {"mensagem": "❌ Erro ao gerar relatório. Tenta novamente."}

    async def comparar_produto(self, produto: str, chat_id: str) -> Dict[str, Any]:
        """Compara preços de um produto entre mercados."""
        try:
            from services import get_service
            db = get_service("supabase").client

            res = (
                db.table("mercado_itens")
                .select("mercado, preco_unitario, data_compra, unidade")
                .eq("chat_id", chat_id)
                .ilike("produto", f"%{produto}%")
                .order("data_compra", desc=True)
                .execute()
            )
            itens = res.data or []
            if not itens:
                return {
                    "mensagem": (
                        f"🔍 Ainda não tenho dados sobre *{produto}*.\n\n"
                        "Regista algumas notas fiscais primeiro!"
                    )
                }

            por_mercado: Dict[str, List[float]] = {}
            for i in itens:
                p = float(i.get("preco_unitario") or 0)
                if p > 0:
                    por_mercado.setdefault(i["mercado"], []).append(p)

            if not por_mercado:
                return {"mensagem": f"❌ Sem dados de preço para *{produto}*."}

            medias = {m: round(sum(ps) / len(ps), 2) for m, ps in por_mercado.items()}
            ranking = sorted(medias.items(), key=lambda x: x[1])
            mais_barato, mais_caro = ranking[0], ranking[-1]
            poupanca = mais_caro[1] - mais_barato[1]
            unidade = itens[0].get("unidade", "un")

            linhas = [f"💰 *Comparação de preços — {produto}*", ""]
            for i, (mercado, preco) in enumerate(ranking):
                emoji = "✅" if i == 0 else ("❌" if i == len(ranking) - 1 else "➡️")
                n = len(por_mercado[mercado])
                linhas.append(f"{emoji} *{mercado}*: €{preco:.2f}/{unidade} ({n} compra(s))")

            if len(ranking) > 1 and poupanca > 0.01:
                linhas += [
                    "",
                    f"💡 No *{mais_barato[0]}* poupas *€{poupanca:.2f}* "
                    f"por {unidade} vs *{mais_caro[0]}*.",
                ]

            return {"mensagem": "\n".join(linhas), "ranking": ranking, "poupanca": poupanca}
        except Exception as e:
            self.logger.error("Erro ao comparar produto: %s", e, exc_info=True)
            return {"mensagem": "❌ Erro ao comparar preços."}

    async def ranking_mercados(self, chat_id: str) -> Dict[str, Any]:
        """Ranking geral de mercados por gasto total histórico."""
        try:
            from services import get_service
            db = get_service("supabase").client

            res = (
                db.table("mercado_compras")
                .select("mercado, total")
                .eq("chat_id", chat_id)
                .execute()
            )
            compras = res.data or []
            if not compras:
                return {"mensagem": "📊 Ainda sem histórico. Regista a primeira nota!"}

            totais: Dict[str, Dict] = {}
            for c in compras:
                m = c["mercado"]
                v = float(c.get("total") or 0)
                if m not in totais:
                    totais[m] = {"total": 0.0, "visitas": 0}
                totais[m]["total"] += v
                totais[m]["visitas"] += 1

            ranking = sorted(totais.items(), key=lambda x: x[1]["total"], reverse=True)
            total_geral = sum(v["total"] for _, v in ranking)

            linhas = ["🏪 *Ranking de Mercados (histórico total)*", ""]
            medalhas = ["🥇", "🥈", "🥉"]
            for i, (mercado, dados) in enumerate(ranking):
                emoji = medalhas[i] if i < 3 else f"{i+1}."
                pct = (dados["total"] / total_geral * 100) if total_geral else 0
                ticket = dados["total"] / dados["visitas"]
                linhas.append(
                    f"{emoji} *{mercado}*\n"
                    f"   💶 €{dados['total']:.2f} ({pct:.0f}%) · "
                    f"{dados['visitas']} visita(s) · ticket médio €{ticket:.2f}"
                )

            if len(ranking) > 1:
                linhas += ["", f"💡 Onde gastas menos: *{ranking[-1][0]}*"]

            return {"mensagem": "\n".join(linhas), "ranking": ranking}
        except Exception as e:
            self.logger.error("Erro no ranking: %s", e, exc_info=True)
            return {"mensagem": "❌ Erro ao gerar ranking."}

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _nome_mes(mes: int) -> str:
        nomes = [
            "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
        ]
        return nomes[mes] if 1 <= mes <= 12 else str(mes)
