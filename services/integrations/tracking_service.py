# -*- coding: utf-8 -*-
"""
services/integrations/tracking_service.py
==========================================
Rastreamento de encomendas via 17TRACK API v2.

Operações:
  - track(tracking_number)                    → rastreia (auto-detect carrier)
  - track_with_carrier(number, carrier)       → rastreia com carrier específica
  - get_quota()                               → consulta quota restante

Autenticação:
  - 17TRACK_API_KEY → variável de ambiente
  - Header: 17token: <sua_chave>

Cobertura:
  - 2.600+ transportadoras globais
  - An Post (IE), DPD, DHL, FedEx, UPS, Correios (BR), Amazon, etc.
  - Auto-detecção de carrier pelo formato do código (~80% dos casos)

Quota 17TRACK:
  - Contas novas (pós Jan 2026): 200 rastreios gratuitos (crédito único)
  - Planos pagos disponíveis para volume maior
  - Rate limit: 3 req/s

Fluxo de uso (Standard — sem RealTime Endpoint):
  1. /gettrackinfo → busca info já registrada (sem custo)
  2. Se não encontrada → /register → registra tracking number (-1 quota)
  3. Após registro, 17TRACK busca dados automaticamente
  4. Próxima consulta via /gettrackinfo retorna dados completos
  5. Webhook recebe push updates automáticos (se configurado)
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

import httpx
from dotenv import load_dotenv

from services.core import BaseService, register_service, ServiceUnavailableError

load_dotenv()

_BASE = "https://api.17track.net/track/v2"

# Status principal 17TRACK → (emoji, label PT-BR)
_STATUS_MAP: Dict[int, tuple] = {
    0: ("❓", "Não encontrado"),
    10: ("📋", "Informação recebida"),
    20: ("🚚", "Em trânsito"),
    30: ("📦", "Disponível para retirada"),
    35: ("⚠️", "Tentativa de entrega falhou"),
    40: ("✅", "Entregue"),
    50: ("🕰️", "Prazo expirado"),
    60: ("❌", "Exceção / Problema"),
}

# Sub-status mais relevantes → label PT-BR
_SUBSTATUS_MAP: Dict[str, str] = {
    "20.01": "Em trânsito doméstico",
    "20.02": "Em trânsito internacional",
    "20.03": "Em alfândega",
    "20.04": "Aguardando desembaraço",
    "20.05": "Saiu da origem",
    "20.06": "Chegou ao destino",
    "35.01": "Endereço incorreto",
    "35.02": "Destinatário ausente",
    "35.03": "Recusado pelo destinatário",
    "40.01": "Entregue ao destinatário",
    "40.02": "Entregue a um vizinho",
    "40.03": "Entregue em ponto de coleta",
    "60.01": "Danificado",
    "60.02": "Perdido",
    "60.03": "Retornado ao remetente",
}

# Carriers comuns — nome → código numérico 17TRACK
# Lista completa: https://res.17track.net/asset/carrier/info/apicarrier.all.json
CARRIER_CODES: Dict[str, int] = {
    # Irlanda
    "an post": 100011,
    "anpost": 100011,
    "dpd ireland": 100065,
    "dpd": 100065,
    "fastway ireland": 100070,
    "evri ireland": 100073,
    # Reino Unido
    "royal mail": 190004,
    "parcelforce": 190005,
    "evri": 190010,
    "hermes": 190010,
    # Europa / Global
    "dhl": 300004,
    "fedex": 300002,
    "ups": 300003,
    "tnt": 300006,
    "gls": 300012,
    "dpd europe": 300020,
    "postnl": 301002,
    # EUA
    "usps": 100003,
    # Brasil
    "correios": 3011,
    "jadlog": 3042,
    # China / E-commerce
    "cainiao": 190200,
    "yunexpress": 190193,
    "amazon": 190120,
    "aliexpress": 190193,
}


def _fmt_date(date_str: Optional[str]) -> str:
    """Converte timestamp UTC para formato legível dd/mm/aaaa HH:MM."""
    if not date_str:
        return ""
    try:
        clean = str(date_str).replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return str(date_str)[:16]


def _parse_event(ev: Dict) -> Dict[str, str]:
    """
    Normaliza um evento de rastreio do 17TRACK.

    Campos do 17TRACK:
      a = timestamp UTC
      b = descrição do evento
      c = cidade
      d = país
      z = mensagem formatada
    """
    return {
        "date": _fmt_date(ev.get("a")),
        "location": ev.get("c") or ev.get("d") or "",
        "message": ev.get("z") or ev.get("b") or "",
    }


@register_service("tracking")
class TrackingService(BaseService):
    """
    Tracking service — rastreamento de encomendas via 17TRACK API v2.

    Requer: 17TRACK_API_KEY no .env
    Cadastro: https://api.17track.net
    """

    def __init__(self):
        super().__init__(name="tracking")
        self._api_key: Optional[str] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _initialize(self) -> None:
        self._api_key = os.getenv("17TRACK_API_KEY")
        if not self._api_key:
            raise ServiceUnavailableError(
                "17TRACK_API_KEY não encontrada. "
                "Cadastre-se em api.17track.net e adicione ao .env:\n"
                "17TRACK_API_KEY=sua_chave_aqui"
            )
        self._client = httpx.AsyncClient(
            base_url=_BASE,
            timeout=20.0,
            headers={
                "17token": self._api_key,
                "Content-Type": "application/json",
            },
        )
        self.logger.info("TrackingService initialized (17TRACK API v2)")

    async def _health_check(self) -> bool:
        if not self._client or not self._api_key:
            return False
        try:
            resp = await self._client.post("/getquota", json={})
            return resp.status_code == 200
        except Exception:
            return False

    async def _cleanup(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────

    async def track(self, tracking_number: str) -> Dict[str, Any]:
        """
        Rastreia uma encomenda com auto-detecção de carrier.

        Estratégia de custo mínimo:
          1. /gettrackinfo → busca cache sem custo
          2. Se não encontrado → /register → registra (-1 quota) + tenta buscar info

        Args:
            tracking_number: Código de rastreio (qualquer formato)

        Returns:
            Dict normalizado: status, carrier, eventos, estimativa

        Raises:
            ValueError: Código inválido ou rejeitado pela API
            RuntimeError: Erro de conexão ou API
        """
        if not self.is_initialized():
            await self.initialize()

        number = tracking_number.strip().upper()
        self._validate_number(number)

        # Tenta buscar info já registrada (não consome quota)
        cached = await self._get_track_info(number)
        if cached:
            return cached

        # Não encontrado → busca em tempo real (consome 1 quota)
        return await self._register_and_track(number)

    async def track_with_carrier(
        self, tracking_number: str, carrier: Any
    ) -> Dict[str, Any]:
        """
        Rastreia especificando a transportadora.

        Args:
            tracking_number: Código de rastreio
            carrier: Nome (str) ou código numérico (int) da carrier
                     Exemplos: 'an post', 'dhl', 100011

        Returns:
            Dict normalizado com rastreamento
        """
        if not self.is_initialized():
            await self.initialize()

        number = tracking_number.strip().upper()
        self._validate_number(number)
        carrier_code = self._resolve_carrier_code(carrier)

        cached = await self._get_track_info(number, carrier_code)
        if cached:
            return cached

        return await self._register_and_track(number, carrier_code)

    async def get_quota(self) -> Dict[str, int]:
        """
        Consulta quota restante na conta 17TRACK.

        Returns:
            Dict com quota_remaining, quota_total, quota_used
        """
        if not self.is_initialized():
            await self.initialize()

        resp = await self._client.post("/getquota", json={})
        data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"17TRACK erro ao consultar quota: {data}")

        q = data.get("data", {})
        return {
            "quota_remaining": q.get("quota_remain", q.get("quotaleft", 0)),
            "quota_total": q.get("quota_total", q.get("quotatotal", 0)),
            "quota_used": q.get("quota_used", q.get("quotaused", 0)),
        }

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE — chamadas 17TRACK
    # ──────────────────────────────────────────────────────────────────────────

    async def _register_and_track(
        self, number: str, carrier_code: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        POST /register — register tracking number for monitoring.
        Then POST /gettrackinfo to fetch available data.

        This is the standard flow (no RealTime endpoint needed).
        Consumes 1 quota per new tracking number.

        Note: After registration, 17TRACK may take a few minutes to fetch
        the first tracking data. If no data yet, returns a "registered" status.
        """
        # Step 1: Register the tracking number
        payload: Dict = {"number": number}
        if carrier_code:
            payload["carrier"] = carrier_code

        try:
            resp = await self._client.post("/register", json=[payload])
            data = resp.json()

            if resp.status_code == 429:
                raise RuntimeError(
                    "⏱️ Rate limit da 17TRACK (3 req/s). Aguarde 1 segundo e tente novamente."
                )

            if resp.status_code != 200:
                raise RuntimeError(f"17TRACK HTTP {resp.status_code}")

            # Check for rejections (17TRACK can return code:0 with rejected items)
            rejected = data.get("data", {}).get("rejected", [])
            if rejected:
                err = rejected[0].get("error", {})
                err_code = str(err.get("code", ""))
                # -18010012 = already registered (that's ok!)
                if "-18010012" not in err_code:
                    raise ValueError(
                        f"17TRACK rejeitou '{number}': {err.get('message', 'erro desconhecido')}"
                    )

            if data.get("code") != 0 and not rejected:
                self.logger.warning(
                    "17TRACK register unexpected code: %s", data.get("code")
                )

        except (ValueError, RuntimeError):
            raise
        except Exception as e:
            self.logger.warning("17TRACK register failed: %s", e)

        # Step 2: Try to get tracking info (may have data if already registered before)
        import asyncio

        await asyncio.sleep(1)  # Brief pause to let 17TRACK process

        cached = await self._get_track_info(number, carrier_code)
        if cached:
            return cached

        # No data yet — return "registered, waiting" status
        return {
            "tracking_number": number,
            "carrier": "Auto-detect",
            "carrier_code": carrier_code,
            "status_code": 0,
            "status_emoji": "📋",
            "status_label": "Registrado — aguardando dados",
            "sub_status": "Encomenda registrada no sistema. Dados de rastreio chegam em breve.",
            "last_location": "",
            "last_message": "Acabei de registrar este código. O 17TRACK vai buscar os dados em alguns minutos.",
            "last_update": "",
            "estimated_delivery": "",
            "origin_country": "",
            "destination_country": "",
            "events": [],
            "total_events": 0,
            "delivered": False,
            "just_registered": True,
        }

    async def _get_track_info(
        self, number: str, carrier_code: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """POST /gettrackinfo — busca info já registrada. Não consome quota."""
        try:
            payload: Dict = {"number": number}
            if carrier_code:
                payload["carrier"] = carrier_code

            resp = await self._client.post("/gettrackinfo", json=[payload])
            data = resp.json()

            accepted = data.get("data", {}).get("accepted", [])
            if not accepted:
                return None

            # Verifica se tem dados de rastreio (pode estar registrado mas sem info)
            track = accepted[0].get("track")
            if not track or not track.get("b"):
                return None

            return self._normalize(number, accepted[0])
        except Exception as e:
            self.logger.debug("_get_track_info: %s → %s", number, e)
            return None

    def _parse_api_response(self, resp: httpx.Response, number: str) -> Dict[str, Any]:
        """Processa resposta da API 17TRACK e levanta exceções claras."""
        if resp.status_code == 429:
            raise RuntimeError(
                "⏱️ Rate limit da 17TRACK (3 req/s). Aguarde 1 segundo e tente novamente."
            )

        if resp.status_code != 200:
            raise RuntimeError(
                f"17TRACK HTTP {resp.status_code}: tente novamente em instantes."
            )

        try:
            data = resp.json()
        except Exception:
            raise RuntimeError("17TRACK retornou resposta inválida (não é JSON).")

        if data.get("code") != 0:
            raise RuntimeError(f"17TRACK erro interno code={data.get('code')}")

        accepted = data.get("data", {}).get("accepted", [])
        rejected = data.get("data", {}).get("rejected", [])

        if rejected and not accepted:
            err = rejected[0].get("error", {})
            err_code = str(err.get("code", ""))
            if "-18010013" in err_code:
                raise ValueError(
                    f"Código '{number}' inválido ou transportadora não suportada."
                )
            raise ValueError(
                f"17TRACK rejeitou '{number}': {err.get('message', 'erro desconhecido')}"
            )

        if not accepted:
            raise ValueError(f"Nenhuma informação encontrada para '{number}'.")

        return self._normalize(number, accepted[0])

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE — normalização
    # ──────────────────────────────────────────────────────────────────────────

    def _normalize(self, number: str, item: Dict) -> Dict[str, Any]:
        """
        Converte resposta 17TRACK em formato padronizado.

        Campos da track 17TRACK:
          b  = status code (inteiro)
          c  = sub-status  (string "20.01", etc.)
          d  = país de destino
          e  = país de origem
          na = estimated delivery (timestamp)
          w1 = carrier code
          w2 = carrier name
          z0 = último evento (dict)
          z1 = lista de todos os eventos (list)
        """
        track = item.get("track") or {}

        # Status
        status_code = int(track.get("b") or 0)
        emoji, label = _STATUS_MAP.get(status_code, ("📦", f"Status {status_code}"))

        # Sub-status
        sub_key = str(track.get("c") or "")
        sub_label = _SUBSTATUS_MAP.get(sub_key, "")

        # Carrier
        carrier_name = track.get("w2") or str(item.get("carrier") or "")

        # Eventos
        events_raw = track.get("z1") or []
        events = [_parse_event(ev) for ev in events_raw]
        last_event_raw = track.get("z0") or (events_raw[0] if events_raw else {})
        last_event = _parse_event(last_event_raw) if last_event_raw else {}

        return {
            "tracking_number": number,
            "carrier": carrier_name or "Auto-detect",
            "carrier_code": item.get("carrier"),
            "status_code": status_code,
            "status_emoji": emoji,
            "status_label": label,
            "sub_status": sub_label,
            "last_location": last_event.get("location", ""),
            "last_message": last_event.get("message", ""),
            "last_update": last_event.get("date", ""),
            "estimated_delivery": _fmt_date(track.get("na")),
            "origin_country": track.get("e") or "",
            "destination_country": track.get("d") or "",
            "events": events,
            "total_events": len(events),
            "delivered": status_code == 40,
        }

    # ──────────────────────────────────────────────────────────────────────────
    # PRIVATE — helpers
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _validate_number(number: str) -> None:
        if not number or len(number) < 5 or len(number) > 50:
            raise ValueError(
                f"Código de rastreio inválido: '{number}' "
                "(deve ter entre 5 e 50 caracteres alfanuméricos)"
            )

    @staticmethod
    def _resolve_carrier_code(carrier: Any) -> Optional[int]:
        """Resolve nome ou código numérico da carrier para int 17TRACK."""
        if isinstance(carrier, int):
            return carrier
        if isinstance(carrier, str):
            if carrier.strip().isdigit():
                return int(carrier.strip())
            return CARRIER_CODES.get(carrier.strip().lower())
        return None
