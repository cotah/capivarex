# -*- coding: utf-8 -*-
"""
Mercado Service
===============
Lista de compras inteligente + análise de notas fiscais com IA.

Features:
- Lista de compras via Supabase (multi-tenant, cada user tem a sua)
- Processamento de notas fiscais (GPT-4 Vision + Google Vision fallback)
- Histórico de preços por produto e mercado no Supabase
- Relatórios mensais de gastos
- Comparação de preços entre mercados
- Alertas automáticos de subida de preço (>20%)
"""

import base64
import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import httpx

from services.core import (
    BaseService,
    register_service,
    ServiceUnavailableError,
)

logger = logging.getLogger(__name__)

# ── Constantes ─────────────────────────────────────────────────
PRICE_ALERT_THRESHOLD = 0.20  # 20% de subida dispara alerta

# ── Categorias automáticas ─────────────────────────────────────
_CATEGORIAS: Dict[str, List[str]] = {
    "Laticínios": [
        "leite", "manteiga", "queijo", "iogurte",
        "natas", "requeijão",
    ],
    "Padaria": [
        "pão", "bolo", "croissant", "broa", "torrada",
    ],
    "Carnes": [
        "frango", "carne", "bife", "peru",
        "porco", "vaca", "alheira",
    ],
    "Peixe": [
        "peixe", "bacalhau", "atum", "sardinha",
        "salmão", "camarão",
    ],
    "Frutas": [
        "maçã", "banana", "laranja", "uva",
        "morango", "pera", "limão",
    ],
    "Legumes": [
        "alface", "tomate", "cenoura", "cebola",
        "batata", "alho",
    ],
    "Bebidas": [
        "água", "sumo", "cerveja", "vinho",
        "refrigerante", "café",
    ],
    "Limpeza": [
        "detergente", "sabão", "lixívia", "amaciador",
    ],
    "Higiene": [
        "shampoo", "gel", "pasta",
        "desodorizante", "papel higiénico",
    ],
    "Mercearia": [
        "arroz", "massa", "feijão", "lentilha",
        "grão", "açúcar", "farinha", "óleo", "azeite",
    ],
    "Ovos": ["ovo", "ovos"],
    "Snacks": [
        "bolacha", "chips", "chocolate", "biscoito",
    ],
}

_VISION_PROMPT = (
    "Analisa esta nota/recibo de supermercado e extrai "
    "TODOS os itens comprados.\n\n"
    "Responde APENAS com JSON válido, sem markdown, "
    "sem explicações:\n\n"
    "{\n"
    '  "mercado": "Nome do supermercado '
    '(ex: Lidl, Aldi, Continente, Pingo Doce)",\n'
    '  "data": "DD/MM/AAAA ou null se não visível",\n'
    '  "total": 0.00,\n'
    '  "itens": [\n'
    "    {\n"
    '      "produto": "Nome do produto normalizado '
    'em português",\n'
    '      "quantidade": 1,\n'
    '      "unidade": "un/kg/L",\n'
    '      "preco_total": 0.00,\n'
    '      "preco_unitario": 0.00\n'
    "    }\n"
    "  ]\n"
    "}\n\n"
    "Regras:\n"
    '- Normaliza nomes: "LT MIMOSA MEIO-GORD" → '
    '"Leite Mimosa Meio-Gordo"\n'
    "- Se não conseguires ler algum valor, usa null\n"
    "- preco_unitario = preco_total / quantidade\n"
    "- Inclui TODOS os itens, mesmo os que não "
    "consegues ler bem"
)


def _categorizar(produto: str) -> str:
    nome = produto.lower()
    for categoria, keywords in _CATEGORIAS.items():
        if any(kw in nome for kw in keywords):
            return categoria
    return "Outros"


@register_service("mercado")
class MercadoService(BaseService):
    """
    Mercado inteligente: lista de compras + notas
    fiscais + análise de preços.
    Agora usa Supabase directamente para lista de
    compras (sem N8N).
    """

    def __init__(self):
        super().__init__(name="mercado")
        self._http: Optional[httpx.AsyncClient] = None
        self._db = None

    async def _initialize(self) -> None:
        self._http = httpx.AsyncClient(timeout=20.0)
        from services import get_service

        self._db = get_service("database")
        self.logger.info(
            "MercadoService initialized (Supabase mode)"
        )

    async def _health_check(self) -> bool:
        return (
            self._db is not None
            and self._db.is_initialized()
        )

    def _get_client(self):
        """Retorna o cliente Supabase."""
        if not self._db or not self._db.is_initialized():
            raise ServiceUnavailableError(
                "Database service not available"
            )
        return self._db.get_client()

    # ── Lista de compras (via Supabase) ────────────────

    async def adicionar(
        self,
        itens: str,
        user_id: str = "default",
    ) -> Dict[str, Any]:
        """Adiciona item(s) à lista de compras."""
        import asyncio
        import re

        itens_list = re.split(r"[,;\n]|\se\s", itens)
        itens_list = [
            i.strip() for i in itens_list if i.strip()
        ]

        if not itens_list:
            return {
                "mensagem": "❓ Que itens queres adicionar?"
            }

        db = self._get_client()
        adicionados = []
        duplicados = []

        for item in itens_list:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda i=item: db.table(
                        "shopping_list"
                    )
                    .insert(
                        {
                            "user_id": user_id,
                            "item": i,
                            "status": "pendente",
                        }
                    )
                    .execute(),
                )
                adicionados.append(item)
            except Exception as e:
                if (
                    "idx_shopping_list_unique" in str(e)
                    or "duplicate" in str(e).lower()
                ):
                    duplicados.append(item)
                else:
                    self.logger.warning(
                        "Erro ao adicionar '%s': %s",
                        item,
                        e,
                    )
                    duplicados.append(item)

        lista = await self._get_lista(user_id)

        mensagem = ""
        if adicionados:
            mensagem += (
                f"✅ Adicionado: {', '.join(adicionados)}"
            )
        if duplicados:
            mensagem += (
                f"\n⚠️ Já na lista: {', '.join(duplicados)}"
            )
        mensagem += (
            f"\n\n📋 Lista actual ({len(lista)} itens):\n"
        )
        mensagem += "\n".join(
            f"{i+1}. {item}"
            for i, item in enumerate(lista)
        )

        return {
            "action": "adicionar",
            "adicionados": adicionados,
            "duplicados": duplicados,
            "lista": lista,
            "total": len(lista),
            "mensagem": mensagem,
        }

    async def ver_lista(
        self, user_id: str = "default"
    ) -> Dict[str, Any]:
        """Mostra a lista de compras actual."""
        lista = await self._get_lista(user_id)

        if not lista:
            mensagem = (
                "🛒 A tua lista de compras está vazia."
                "\n\nDiz-me o que devo adicionar!"
            )
        else:
            mensagem = (
                f"🛒 *Lista de Compras* "
                f"({len(lista)} itens):\n\n"
            )
            mensagem += "\n".join(
                f"{i+1}. {item}"
                for i, item in enumerate(lista)
            )
            mensagem += (
                '\n\n_Diz "limpar lista" quando terminares._'
            )

        return {
            "action": "lista",
            "lista": lista,
            "total": len(lista),
            "mensagem": mensagem,
        }

    async def remover(
        self,
        item: str,
        user_id: str = "default",
    ) -> Dict[str, Any]:
        """Remove um item da lista."""
        import asyncio

        if not item:
            return {
                "action": "remover",
                "erro": True,
                "mensagem": "❓ Qual item queres remover?",
            }

        db = self._get_client()

        try:
            result = (
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: db.table("shopping_list")
                    .delete()
                    .eq("user_id", user_id)
                    .eq("status", "pendente")
                    .ilike("item", item)
                    .execute(),
                )
            )
            removeu = bool(result.data)
        except Exception as e:
            self.logger.warning(
                "Erro ao remover '%s': %s", item, e
            )
            removeu = False

        lista = await self._get_lista(user_id)

        if removeu:
            mensagem = (
                f'🗑️ "{item}" removido.'
                f"\n\n📋 Restam {len(lista)} itens."
            )
        else:
            mensagem = (
                f'❌ "{item}" não encontrado na lista.'
            )

        return {
            "action": "remover",
            "item": item,
            "removeu": removeu,
            "lista": lista,
            "total": len(lista),
            "mensagem": mensagem,
        }

    async def limpar_lista(
        self, user_id: str = "default"
    ) -> Dict[str, Any]:
        """Limpa a lista toda e guarda no histórico."""
        import asyncio

        lista = await self._get_lista(user_id)
        total_antes = len(lista)

        db = self._get_client()

        # Guardar no histórico antes de limpar
        if lista:
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: db.table(
                        "shopping_list_history"
                    )
                    .insert(
                        {
                            "user_id": user_id,
                            "items": lista,
                        }
                    )
                    .execute(),
                )
            except Exception as e:
                self.logger.warning(
                    "Erro ao guardar histórico: %s", e
                )

        # Limpar lista
        try:
            await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: db.table("shopping_list")
                .delete()
                .eq("user_id", user_id)
                .eq("status", "pendente")
                .execute(),
            )
        except Exception as e:
            self.logger.error(
                "Erro ao limpar lista: %s", e
            )
            return {
                "mensagem": "❌ Erro ao limpar a lista."
            }

        return {
            "action": "limpar",
            "totalRemovido": total_antes,
            "lista": [],
            "mensagem": (
                f"🗑️ Lista limpa! {total_antes} "
                f"item(s) removido(s).\n\n"
                "✅ Prontos para a próxima compra!"
            ),
        }

    async def historico_lista(
        self, user_id: str = "default"
    ) -> Dict[str, Any]:
        """Mostra o histórico de listas limpas."""
        import asyncio

        db = self._get_client()

        try:
            result = (
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: db.table(
                        "shopping_list_history"
                    )
                    .select("items, cleared_at")
                    .eq("user_id", user_id)
                    .order("cleared_at", desc=True)
                    .limit(5)
                    .execute(),
                )
            )
            historico = result.data or []
        except Exception as e:
            self.logger.warning(
                "Erro ao buscar histórico: %s", e
            )
            historico = []

        if not historico:
            mensagem = (
                "📖 Sem histórico de compras ainda."
            )
        else:
            mensagem = "📖 *Últimas compras:*\n\n"
            for i, h in enumerate(historico):
                data = h.get("cleared_at", "")[:10]
                items = h.get("items", [])
                if isinstance(items, list):
                    items_str = ", ".join(items[:10])
                    if len(items) > 10:
                        items_str += (
                            f" (+{len(items) - 10})"
                        )
                else:
                    items_str = str(items)
                mensagem += (
                    f"{i + 1}. {data}: {items_str}\n"
                )

        return {
            "action": "historico",
            "historico": historico,
            "mensagem": mensagem,
        }

    async def _get_lista(
        self, user_id: str = "default"
    ) -> List[str]:
        """Helper: retorna lista de itens pendentes."""
        import asyncio

        db = self._get_client()
        try:
            result = (
                await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: db.table("shopping_list")
                    .select("item")
                    .eq("user_id", user_id)
                    .eq("status", "pendente")
                    .order("created_at")
                    .execute(),
                )
            )
            return [
                r["item"] for r in (result.data or [])
            ]
        except Exception as e:
            self.logger.warning(
                "Erro ao buscar lista: %s", e
            )
            return []

    # ═══════════════════════════════════════════════════
    # TUDO ABAIXO FICA EXACTAMENTE IGUAL — SEM ALTERAÇÕES
    # ═══════════════════════════════════════════════════

    # ── Processamento de nota fiscal ───────────────────

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
        self.logger.info(
            "Processando nota fiscal chat_id=%s", chat_id
        )

        # 1) Gemini 2.5 Flash (primario — 16x mais barato)
        nota = await self._extrair_gemini(
            image_data, mime_type
        )
        fonte = "gemini_flash"

        # 2) GPT-4o Vision (fallback 1)
        if not nota or not nota.get("itens"):
            self.logger.warning(
                "Gemini OCR falhou, tentando "
                "GPT-4 Vision"
            )
            nota = await self._extrair_gpt4(
                image_data, mime_type
            )
            fonte = "gpt4_vision"

        # 3) Google Vision OCR (fallback 2)
        if not nota or not nota.get("itens"):
            self.logger.warning(
                "GPT-4 Vision falhou, tentando "
                "Google Vision"
            )
            nota = await self._extrair_google_vision(
                image_data
            )
            fonte = "google_vision"

        if not nota or not nota.get("itens"):
            return {
                "sucesso": False,
                "mensagem": (
                    "❌ Não consegui ler a nota fiscal."
                    "\n\n💡 Dicas: boa iluminação, nota "
                    "plana, câmera estável."
                ),
            }

        nota = self._normalizar_nota(nota)
        compra_id = await self._guardar_compra(
            nota, chat_id, fonte
        )
        alertas = await self._verificar_alertas(
            nota["itens"], chat_id
        )

        return self._formatar_resposta_nota(
            nota, alertas, compra_id
        )

    async def _extrair_gemini(
        self, image_data: bytes, mime_type: str
    ) -> Optional[Dict[str, Any]]:
        """Extrai dados da nota via Gemini 2.5 Flash (primario, mais barato)."""
        try:
            import json
            import os

            api_key = os.environ.get("GEMINI_API_KEY")
            if not api_key:
                self.logger.warning(
                    "GEMINI_API_KEY not set, skipping Gemini OCR"
                )
                return None

            b64 = base64.b64encode(image_data).decode()

            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": _VISION_PROMPT},
                            {
                                "inline_data": {
                                    "mime_type": mime_type,
                                    "data": b64,
                                }
                            },
                        ]
                    }
                ],
                "generationConfig": {
                    "temperature": 0.1,
                    "maxOutputTokens": 2000,
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            }

            resp = await self._http.post(
                "https://generativelanguage.googleapis.com"
                "/v1beta/models/"
                "gemini-2.5-flash"
                ":generateContent"
                f"?key={api_key}",
                json=payload,
                timeout=30.0,
            )

            if resp.status_code != 200:
                self.logger.warning(
                    "Gemini OCR HTTP %d: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                return None

            data = resp.json()
            text = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )

            if not text:
                return None

            text = (
                text.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            result = json.loads(text)

            self.logger.info(
                "Gemini OCR: %d itens extraidos, mercado=%s",
                len(result.get("itens", [])),
                result.get("mercado", "?"),
            )
            return result

        except Exception as e:
            self.logger.error("Gemini OCR error: %s", e)
            return None

    async def _extrair_gpt4(
        self, image_data: bytes, mime_type: str
    ) -> Optional[Dict[str, Any]]:
        """Extrai dados da nota via GPT-4 Vision."""
        try:
            import json

            from services import get_service

            openai_svc = get_service("openai")
            if (
                not openai_svc
                or not openai_svc.is_initialized()
            ):
                return None

            b64 = base64.b64encode(image_data).decode()
            client = openai_svc.client

            response = (
                await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "text",
                                    "text": _VISION_PROMPT,
                                },
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": (
                                            f"data:{mime_type}"
                                            f";base64,{b64}"
                                        ),
                                        "detail": "high",
                                    },
                                },
                            ],
                        }
                    ],
                    max_completion_tokens=2000,
                    temperature=0.1,
                )
            )

            text = (
                response.choices[0]
                .message.content.strip()
            )
            text = (
                text.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            return json.loads(text)

        except Exception as e:
            self.logger.error(
                "GPT-4 Vision error: %s", e
            )
            return None

    async def _extrair_google_vision(
        self, image_data: bytes
    ) -> Optional[Dict[str, Any]]:
        """Fallback: Google Vision OCR + GPT-4 text."""
        try:
            import json

            b64 = base64.b64encode(image_data).decode()
            resp = await self._http.post(
                "https://vision.googleapis.com"
                "/v1/images:annotate",
                json={
                    "requests": [
                        {
                            "image": {"content": b64},
                            "features": [
                                {"type": "TEXT_DETECTION"}
                            ],
                        }
                    ]
                },
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
            if (
                not openai_svc
                or not openai_svc.is_initialized()
            ):
                return None

            prompt = (
                f"{_VISION_PROMPT}\n\n"
                f"Texto OCR extraído:\n{text_ocr}"
            )
            response = (
                await openai_svc.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        }
                    ],
                    max_completion_tokens=2000,
                    temperature=0.1,
                )
            )
            raw = (
                response.choices[0]
                .message.content.strip()
            )
            raw = (
                raw.replace("```json", "")
                .replace("```", "")
                .strip()
            )
            return json.loads(raw)

        except Exception as e:
            self.logger.error(
                "Google Vision fallback error: %s", e
            )
            return None

    def _normalizar_nota(
        self, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normaliza dados extraídos."""
        data_raw = data.get("data")
        data_obj = date.today()
        if data_raw:
            for fmt in (
                "%d/%m/%Y",
                "%d/%m/%y",
                "%Y-%m-%d",
            ):
                try:
                    data_obj = datetime.strptime(
                        data_raw, fmt
                    ).date()
                    break
                except ValueError:
                    continue
        data["data_obj"] = data_obj

        if not data.get("total"):
            data["total"] = round(
                sum(
                    float(i.get("preco_total") or 0)
                    for i in data.get("itens", [])
                ),
                2,
            )

        if not data.get("mercado"):
            data["mercado"] = "Desconhecido"

        itens_ok = []
        for item in data.get("itens", []):
            if not item.get("produto"):
                continue
            qtd = float(item.get("quantidade") or 1)
            p_total = float(
                item.get("preco_total") or 0
            )
            p_unit = float(
                item.get("preco_unitario") or 0
            )
            if p_unit == 0 and p_total > 0 and qtd > 0:
                p_unit = round(p_total / qtd, 4)
            if p_total == 0 and p_unit > 0:
                p_total = round(p_unit * qtd, 2)
            item.update(
                {
                    "preco_total": p_total,
                    "preco_unitario": p_unit,
                    "quantidade": qtd,
                    "unidade": (
                        item.get("unidade") or "un"
                    ),
                    "categoria": _categorizar(
                        item["produto"]
                    ),
                }
            )
            itens_ok.append(item)
        data["itens"] = itens_ok
        return data

    async def _guardar_compra(
        self,
        nota: Dict[str, Any],
        chat_id: str,
        fonte: str,
    ) -> Optional[str]:
        """Insere compra e itens no Supabase."""
        try:
            from services import get_service

            supabase_svc = get_service("database")
            if (
                not supabase_svc
                or not supabase_svc.is_initialized()
            ):
                self.logger.warning(
                    "Supabase não disponível — "
                    "compra não guardada"
                )
                return None

            db = supabase_svc.client

            compra_res = (
                db.table("mercado_compras")
                .insert(
                    {
                        "chat_id": chat_id,
                        "mercado": nota["mercado"],
                        "data_compra": (
                            nota["data_obj"].isoformat()
                        ),
                        "total": float(
                            nota.get("total") or 0
                        ),
                        "fonte_extracao": fonte,
                    }
                )
                .execute()
            )
            compra_id = compra_res.data[0]["id"]

            itens_payload = [
                {
                    "compra_id": compra_id,
                    "chat_id": chat_id,
                    "produto": i["produto"],
                    "categoria": i["categoria"],
                    "quantidade": float(
                        i["quantidade"]
                    ),
                    "unidade": i["unidade"],
                    "preco_total": float(
                        i["preco_total"]
                    ),
                    "preco_unitario": float(
                        i["preco_unitario"]
                    ),
                    "mercado": nota["mercado"],
                    "data_compra": (
                        nota["data_obj"].isoformat()
                    ),
                }
                for i in nota["itens"]
                if float(i.get("preco_total") or 0) > 0
            ]

            if itens_payload:
                db.table("mercado_itens").insert(
                    itens_payload
                ).execute()

            self.logger.info(
                "Compra guardada: id=%s, %d itens, "
                "€%.2f",
                compra_id,
                len(itens_payload),
                nota.get("total", 0),
            )
            return compra_id

        except Exception as e:
            self.logger.error(
                "Erro ao guardar compra: %s",
                e,
                exc_info=True,
            )
            return None

    async def _verificar_alertas(
        self, itens: List[Dict], chat_id: str
    ) -> List[str]:
        """Detecta subidas de preço > 20%."""
        alertas: List[str] = []
        try:
            from services import get_service

            supabase_svc = get_service("database")
            if (
                not supabase_svc
                or not supabase_svc.is_initialized()
            ):
                return alertas
            db = supabase_svc.client

            for item in itens:
                preco_atual = float(
                    item.get("preco_unitario") or 0
                )
                if preco_atual <= 0:
                    continue
                res = (
                    db.table("mercado_itens")
                    .select(
                        "preco_unitario, mercado, "
                        "data_compra"
                    )
                    .eq("chat_id", chat_id)
                    .ilike(
                        "produto",
                        f"%{item['produto'].split()[0]}%",
                    )
                    .order("data_compra", desc=True)
                    .limit(1)
                    .execute()
                )
                if not res.data:
                    continue
                preco_anterior = float(
                    res.data[0]["preco_unitario"]
                )
                if preco_anterior <= 0:
                    continue
                variacao = (
                    (preco_atual - preco_anterior)
                    / preco_anterior
                )
                if variacao >= PRICE_ALERT_THRESHOLD:
                    alertas.append(
                        f"⚠️ *{item['produto']}* "
                        f"subiu {variacao:.0%} "
                        f"(era €{preco_anterior:.2f}, "
                        f"agora €{preco_atual:.2f})"
                    )
        except Exception as e:
            self.logger.warning(
                "Erro ao verificar alertas: %s", e
            )
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
            (
                f"📅 {data_str} · {len(itens)} itens "
                f"· *€{total:.2f}*"
            ),
            "",
            "📋 *Itens:*",
        ]
        for item in itens[:15]:
            linha = f" • {item['produto']}"
            if float(item.get("quantidade", 1)) != 1:
                linha += (
                    f" ×{item['quantidade']:.0f}"
                    f"{item.get('unidade', '')}"
                )
            linha += (
                f" — €{item.get('preco_total', 0):.2f}"
            )
            linhas.append(linha)
        if len(itens) > 15:
            linhas.append(
                f" _...e mais {len(itens) - 15} itens_"
            )

        if alertas:
            linhas += [
                "",
                "🔔 *Alertas de preço:*",
            ] + alertas

        linhas += [
            "",
            (
                "_Usa 'relatório mensal' para ver "
                "gastos do mês._"
            ),
            (
                "_Usa 'comparar [produto]' para ver "
                "onde é mais barato._"
            ),
        ]

        return {
            "sucesso": True,
            "compra_id": compra_id,
            "mercado": mercado,
            "total": total,
            "n_itens": len(itens),
            "alertas": alertas,
            "mensagem": "\n".join(linhas),
        }

    # ── Relatórios ─────────────────────────────────────

    async def relatorio_mensal(
        self,
        chat_id: str,
        mes: Optional[int] = None,
        ano: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Relatório de gastos do mês."""
        try:
            from services import get_service

            db = get_service("database").client
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
                        "📊 Sem compras registadas em "
                        f"{nome_mes} {ano}.\n\n"
                        "Tira uma foto da próxima "
                        "nota fiscal!"
                    )
                }

            por_mercado: Dict[str, Dict] = {}
            total_geral = 0.0
            for c in compras:
                m = c["mercado"]
                v = float(c.get("total") or 0)
                if m not in por_mercado:
                    por_mercado[m] = {
                        "total": 0.0,
                        "visitas": 0,
                    }
                por_mercado[m]["total"] += v
                por_mercado[m]["visitas"] += 1
                total_geral += v

            ranking = sorted(
                por_mercado.items(),
                key=lambda x: x[1]["total"],
                reverse=True,
            )
            nome_mes = self._nome_mes(mes)
            linhas = [
                f"📊 *Relatório — {nome_mes} {ano}*",
                (
                    "💶 Total gasto: "
                    f"*€{total_geral:.2f}*"
                ),
                (
                    "🏪 Mercados visitados: "
                    f"{len(por_mercado)}"
                ),
                "",
                "🏆 *Gastos por mercado:*",
            ]
            medalhas = ["🥇", "🥈", "🥉"]
            for i, (mercado, dados) in enumerate(
                ranking
            ):
                emoji = (
                    medalhas[i] if i < 3 else " "
                )
                pct = (
                    (dados["total"] / total_geral * 100)
                    if total_geral
                    else 0
                )
                linhas.append(
                    f"{emoji} *{mercado}*: "
                    f"€{dados['total']:.2f} "
                    f"({pct:.0f}%) — "
                    f"{dados['visitas']} visita(s)"
                )

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
                    cat = item.get(
                        "categoria", "Outros"
                    )
                    cats[cat] = cats.get(
                        cat, 0
                    ) + float(
                        item.get("preco_total") or 0
                    )
                top = sorted(
                    cats.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:5]
                linhas += [
                    "",
                    "🛒 *Top categorias:*",
                ]
                for cat, val in top:
                    linhas.append(
                        f" • {cat}: €{val:.2f}"
                    )

            return {
                "mensagem": "\n".join(linhas),
                "total": total_geral,
            }

        except Exception as e:
            self.logger.error(
                "Erro no relatório mensal: %s",
                e,
                exc_info=True,
            )
            return {
                "mensagem": (
                    "❌ Erro ao gerar relatório. "
                    "Tente novamente."
                )
            }

    async def comparar_produto(
        self, produto: str, chat_id: str
    ) -> Dict[str, Any]:
        """Compara preços entre mercados."""
        try:
            from services import get_service

            db = get_service("database").client
            res = (
                db.table("mercado_itens")
                .select(
                    "mercado, preco_unitario, "
                    "data_compra, unidade"
                )
                .eq("chat_id", chat_id)
                .ilike("produto", f"%{produto}%")
                .order("data_compra", desc=True)
                .execute()
            )
            itens = res.data or []
            if not itens:
                return {
                    "mensagem": (
                        "🔍 Ainda não tenho dados "
                        f"sobre *{produto}*.\n\n"
                        "Regista algumas notas "
                        "fiscais primeiro!"
                    )
                }

            por_mercado: Dict[str, List[float]] = {}
            for i in itens:
                p = float(
                    i.get("preco_unitario") or 0
                )
                if p > 0:
                    por_mercado.setdefault(
                        i["mercado"], []
                    ).append(p)

            if not por_mercado:
                return {
                    "mensagem": (
                        "❌ Sem dados de preço "
                        f"para *{produto}*."
                    )
                }

            medias = {
                m: round(sum(ps) / len(ps), 2)
                for m, ps in por_mercado.items()
            }
            ranking = sorted(
                medias.items(), key=lambda x: x[1]
            )
            mais_barato = ranking[0]
            mais_caro = ranking[-1]
            poupanca = mais_caro[1] - mais_barato[1]
            unidade = itens[0].get("unidade", "un")

            linhas = [
                (
                    "💰 *Comparação de preços "
                    f"— {produto}*"
                ),
                "",
            ]
            for i, (mercado, preco) in enumerate(
                ranking
            ):
                emoji = (
                    "✅"
                    if i == 0
                    else (
                        "❌"
                        if i == len(ranking) - 1
                        else "➡️"
                    )
                )
                n = len(por_mercado[mercado])
                linhas.append(
                    f"{emoji} *{mercado}*: "
                    f"€{preco:.2f}/{unidade} "
                    f"({n} compra(s))"
                )

            if len(ranking) > 1 and poupanca > 0.01:
                linhas += [
                    "",
                    (
                        f"💡 No *{mais_barato[0]}* "
                        f"poupas *€{poupanca:.2f}* "
                        f"por {unidade} vs "
                        f"*{mais_caro[0]}*."
                    ),
                ]

            return {
                "mensagem": "\n".join(linhas),
                "ranking": ranking,
                "poupanca": poupanca,
            }

        except Exception as e:
            self.logger.error(
                "Erro ao comparar produto: %s",
                e,
                exc_info=True,
            )
            return {
                "mensagem": (
                    "❌ Erro ao comparar preços."
                )
            }

    async def ranking_mercados(
        self, chat_id: str
    ) -> Dict[str, Any]:
        """Ranking geral de mercados."""
        try:
            from services import get_service

            db = get_service("database").client
            res = (
                db.table("mercado_compras")
                .select("mercado, total")
                .eq("chat_id", chat_id)
                .execute()
            )
            compras = res.data or []
            if not compras:
                return {
                    "mensagem": (
                        "📊 Ainda sem histórico. "
                        "Regista a primeira nota!"
                    )
                }

            totais: Dict[str, Dict] = {}
            for c in compras:
                m = c["mercado"]
                v = float(c.get("total") or 0)
                if m not in totais:
                    totais[m] = {
                        "total": 0.0,
                        "visitas": 0,
                    }
                totais[m]["total"] += v
                totais[m]["visitas"] += 1

            ranking = sorted(
                totais.items(),
                key=lambda x: x[1]["total"],
                reverse=True,
            )
            total_geral = sum(
                v["total"] for _, v in ranking
            )

            linhas = [
                (
                    "🏪 *Ranking de Mercados "
                    "(histórico total)*"
                ),
                "",
            ]
            medalhas = ["🥇", "🥈", "🥉"]
            for i, (mercado, dados) in enumerate(
                ranking
            ):
                emoji = (
                    medalhas[i]
                    if i < 3
                    else f"{i + 1}."
                )
                pct = (
                    (dados["total"] / total_geral * 100)
                    if total_geral
                    else 0
                )
                ticket = (
                    dados["total"] / dados["visitas"]
                )
                linhas.append(
                    f"{emoji} *{mercado}*\n"
                    f" 💶 €{dados['total']:.2f} "
                    f"({pct:.0f}%) · "
                    f"{dados['visitas']} visita(s) "
                    f"· ticket médio €{ticket:.2f}"
                )
            if len(ranking) > 1:
                linhas += [
                    "",
                    (
                        "💡 Onde gastas menos: "
                        f"*{ranking[-1][0]}*"
                    ),
                ]

            return {
                "mensagem": "\n".join(linhas),
                "ranking": ranking,
            }

        except Exception as e:
            self.logger.error(
                "Erro no ranking: %s",
                e,
                exc_info=True,
            )
            return {
                "mensagem": "❌ Erro ao gerar ranking."
            }

    @staticmethod
    def _nome_mes(mes: int) -> str:
        nomes = [
            "",
            "Janeiro",
            "Fevereiro",
            "Março",
            "Abril",
            "Maio",
            "Junho",
            "Julho",
            "Agosto",
            "Setembro",
            "Outubro",
            "Novembro",
            "Dezembro",
        ]
        return nomes[mes] if 1 <= mes <= 12 else str(mes)
