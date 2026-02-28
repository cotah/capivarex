# -*- coding: utf-8 -*-
"""
services/integrations/twilio_service.py
=========================================
Serviço Twilio para chamadas de voz — pool de números com quota por tenant.

Números configurados:
    🇺🇸 +1 406 416 4577  (Montana, US) — activo
    🇮🇪 +353 XX XXX XXXX (Irlanda)     — pendente aprovação bundle

Arquitectura de pool:
    - Pool de números partilhado entre todos os tenants
    - Cada número tem estado: free | in_use
    - Após chamada → número volta ao pool automaticamente
    - Selecção por país do destino (PT/IE → IE, outros → US)
    - Quota por tenant via QuotaService (twilio_mins)

Fluxo completo:
    1. check_and_consume quota (twilio_mins) via QuotaService
    2. acquire_number() → pega número livre do pool
    3. make_call() → Twilio REST API
    4. release_number() → devolve ao pool (sempre, mesmo em erro)
    5. log chamada no Supabase

Variáveis de ambiente necessárias:
    TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_AUTH_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    TWILIO_WEBHOOK_BASE_URL=https://teu-dominio.com   (para callbacks)

Tabela Supabase necessária: ver create_quota_tables.sql
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import aiohttp
from dotenv import load_dotenv

from services.core import BaseService, ServiceUnavailableError, register_service

load_dotenv()

# ─── Pool de números ─────────────────────────────────────────────────────────

PHONE_POOL: List[Dict[str, Any]] = [
    {
        "id": "us_1",
        "number": "+14064164577",
        "country": "US",
        "region": ["US", "CA", "BR", "DEFAULT"],  # países que atende bem
        "active": True,
        "label": "US Montana",
    },
    {
        "id": "ie_1",
        "number": None,  # ← preencher quando bundle aprovado
        "country": "IE",
        "region": ["IE", "PT", "GB", "ES", "FR", "DE"],  # Europa
        "active": False,  # ← mudar para True quando tiver número
        "label": "Ireland (pending)",
    },
]

CALLS_TABLE = "twilio_calls"
TWILIO_API = "https://api.twilio.com/2010-04-01"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _best_number(destination_country: str) -> Optional[Dict[str, Any]]:
    """
    Escolhe o melhor número do pool para ligar a um país.
    Prioridade: mesmo país/região → activo → menos usado hoje.
    """
    available = [n for n in PHONE_POOL if n["active"] and n["number"]]
    if not available:
        return None

    # Prefere número da mesma região
    country = (destination_country or "DEFAULT").upper()
    regional = [n for n in available if country in n["region"]]
    if regional:
        return regional[0]

    # Fallback: qualquer número activo
    return available[0]


@register_service("twilio")
class TwilioService(BaseService):
    """
    Serviço de chamadas de voz via Twilio com pool de números e quota por tenant.

    Interface pública:
        make_call(tenant_id, to_number, twiml_or_url, destination_country?)
            → Dict com call_sid, status, from_number, duration_estimate

        get_call_status(call_sid)
            → Dict com status, duration, price

        hangup_call(call_sid)
            → bool

        get_tenant_calls(tenant_id, limit?)
            → List[Dict] histórico de chamadas

        get_pool_status()
            → Dict estado do pool (para admin)

        add_ireland_number(number)
            → None (activa número IE quando aprovado)
    """

    def __init__(self):
        super().__init__(name="twilio")
        self._account_sid: Optional[str] = None
        self._auth_token: Optional[str] = None
        self._webhook_base: Optional[str] = None
        self._db = None
        self._quota_svc = None
        # Estado in-memory do pool (complementa Supabase)
        self._pool_state: Dict[str, bool] = {}  # number_id → in_use

    async def _initialize(self) -> None:
        self._account_sid = os.getenv("TWILIO_ACCOUNT_SID")
        self._auth_token = os.getenv("TWILIO_AUTH_TOKEN")
        self._webhook_base = os.getenv("TWILIO_WEBHOOK_BASE_URL", "")

        if not self._account_sid or not self._auth_token:
            raise ServiceUnavailableError(
                "TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN são obrigatórios."
            )

        from services.core import get_service

        self._db = get_service("database")
        if self._db and not self._db.is_initialized():
            await self._db.initialize()

        self._quota_svc = get_service("quota")
        if self._quota_svc and not self._quota_svc.is_initialized():
            await self._quota_svc.initialize()

        # Inicializa estado do pool
        for num in PHONE_POOL:
            self._pool_state[num["id"]] = False  # todos livres

        active = [n for n in PHONE_POOL if n["active"] and n["number"]]
        pending = [n for n in PHONE_POOL if not n["active"]]
        self.logger.info(
            "TwilioService initialized. Pool: %d activo(s), %d pendente(s)",
            len(active),
            len(pending),
        )
        if pending:
            for p in pending:
                self.logger.info("  ⏳ Pendente: %s (%s)", p["label"], p["country"])

    async def _health_check(self) -> bool:
        return bool(self._account_sid and self._auth_token)

    def _client(self):
        return self._db.get_client() if self._db else None

    def _loop(self):
        return asyncio.get_event_loop()

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API — CHAMADAS
    # ──────────────────────────────────────────────────────────────────────────

    async def make_call(
        self,
        tenant_id: str,
        to_number: str,
        twiml_or_url: str,
        destination_country: str = "DEFAULT",
        estimated_duration_mins: int = 3,
    ) -> Dict[str, Any]:
        """
        Faz uma chamada de voz.

        Args:
            tenant_id:              ID do tenant (para quota e billing)
            to_number:              Número a ligar (formato E.164: +351...)
            twiml_or_url:           TwiML XML ou URL de webhook com instruções de voz
            destination_country:    País de destino (ex: "PT", "IE", "US")
            estimated_duration_mins: Estimativa de duração para verificar quota

        Returns:
            Dict com call_sid, status, from_number

        Raises:
            QuotaExceededError: se tenant sem minutos no plano
            ServiceUnavailableError: se sem números disponíveis
            RuntimeError: se Twilio retornar erro
        """
        if not self.is_initialized():
            await self.initialize()

        # 1. Verifica e consome quota
        if self._quota_svc:
            from services.business.quota_service import QuotaExceededError

            try:
                await self._quota_svc.check_and_consume(
                    tenant_id, "twilio_mins", estimated_duration_mins
                )
            except QuotaExceededError:
                raise

        # 2. Adquire número do pool
        number_info = self._acquire_number(destination_country)
        if not number_info:
            raise ServiceUnavailableError(
                "Nenhum número disponível no pool agora. Tenta em alguns minutos."
            )

        from_number = number_info["number"]

        try:
            # 3. Determina se é TwiML ou URL
            is_url = twiml_or_url.startswith("http")
            payload = {
                "To": to_number,
                "From": from_number,
            }
            if is_url:
                payload["Url"] = twiml_or_url
            else:
                payload["Twiml"] = twiml_or_url

            # 4. Faz chamada via Twilio REST
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{TWILIO_API}/Accounts/{self._account_sid}/Calls.json",
                    data=payload,
                    auth=aiohttp.BasicAuth(self._account_sid, self._auth_token),
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    data = await resp.json()
                    if resp.status not in (200, 201):
                        raise RuntimeError(
                            f"Twilio erro {resp.status}: {data.get('message', 'unknown')}"
                        )

            call_sid = data.get("sid", "")
            result = {
                "call_sid": call_sid,
                "status": data.get("status", "initiated"),
                "from_number": from_number,
                "to_number": to_number,
                "destination_country": destination_country,
                "tenant_id": tenant_id,
                "created_at": _utcnow().isoformat(),
            }

            # 5. Log no Supabase
            await self._log_call(result)

            self.logger.info(
                "Call initiated: %s → %s (tenant=%s sid=%s)",
                from_number,
                to_number,
                tenant_id,
                call_sid,
            )
            return result

        finally:
            # 6. Liberta número do pool (sempre, mesmo em erro)
            self._release_number(number_info["id"])

    async def get_call_status(self, call_sid: str) -> Dict[str, Any]:
        """
        Retorna estado actual de uma chamada.

        Args:
            call_sid: SID da chamada (retornado por make_call)

        Returns:
            Dict com status, duration, price
        """
        if not self.is_initialized():
            await self.initialize()

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{TWILIO_API}/Accounts/{self._account_sid}/Calls/{call_sid}.json",
                auth=aiohttp.BasicAuth(self._account_sid, self._auth_token),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    raise RuntimeError(
                        f"Twilio erro {resp.status}: {data.get('message')}"
                    )

        return {
            "call_sid": call_sid,
            "status": data.get("status"),
            "duration": data.get("duration"),
            "price": data.get("price"),
            "price_unit": data.get("price_unit"),
            "start_time": data.get("start_time"),
            "end_time": data.get("end_time"),
        }

    async def hangup_call(self, call_sid: str) -> bool:
        """
        Encerra uma chamada em curso.

        Returns:
            True se encerrada com sucesso
        """
        if not self.is_initialized():
            await self.initialize()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{TWILIO_API}/Accounts/{self._account_sid}/Calls/{call_sid}.json",
                data={"Status": "completed"},
                auth=aiohttp.BasicAuth(self._account_sid, self._auth_token),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                return resp.status == 200

    async def get_tenant_calls(
        self, tenant_id: str, limit: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Histórico de chamadas de um tenant.

        Returns:
            Lista ordenada por data DESC
        """
        if not self.is_initialized():
            await self.initialize()

        if not self._client():
            return []

        response = await self._loop().run_in_executor(
            None,
            lambda: (
                self._client()
                .table(CALLS_TABLE)
                .select("*")
                .eq("tenant_id", str(tenant_id))
                .order("created_at", desc=True)
                .limit(min(limit, 50))
                .execute()
            ),
        )
        return response.data or []

    # ──────────────────────────────────────────────────────────────────────────
    # POOL MANAGEMENT
    # ──────────────────────────────────────────────────────────────────────────

    def get_pool_status(self) -> Dict[str, Any]:
        """
        Retorna estado actual do pool (para admin/monitoring).

        Returns:
            Dict com números activos, pendentes, in_use, disponíveis
        """
        active = []
        pending = []

        for num in PHONE_POOL:
            info = {
                "id": num["id"],
                "number": num["number"] or "TBD",
                "country": num["country"],
                "label": num["label"],
                "in_use": self._pool_state.get(num["id"], False),
            }
            if num["active"] and num["number"]:
                active.append(info)
            else:
                pending.append(info)

        available = sum(1 for n in active if not n["in_use"])

        return {
            "total_active": len(active),
            "total_pending": len(pending),
            "available_now": available,
            "numbers": active,
            "pending": pending,
        }

    def add_ireland_number(self, number: str) -> None:
        """
        Activa o número irlandês quando o bundle for aprovado.

        Args:
            number: Número no formato E.164 (ex: "+353539407368")

        Uso:
            twilio_svc.add_ireland_number("+353539407368")
            # Ou via variável de ambiente TWILIO_IE_NUMBER
        """
        for num in PHONE_POOL:
            if num["id"] == "ie_1":
                num["number"] = number
                num["active"] = True
                num["label"] = f"Ireland {number}"
                self._pool_state["ie_1"] = False
                self.logger.info("🇮🇪 Número irlandês activado: %s", number)
                return
        self.logger.warning("Número IE não encontrado no pool para activar.")

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS DO POOL
    # ──────────────────────────────────────────────────────────────────────────

    def _acquire_number(self, destination_country: str) -> Optional[Dict[str, Any]]:
        """
        Reserva o melhor número disponível do pool.
        Thread-safe via asyncio (single-threaded event loop).
        """
        # Candidatos: activos, com número, não em uso
        candidates = [
            n
            for n in PHONE_POOL
            if n["active"] and n["number"] and not self._pool_state.get(n["id"], False)
        ]

        if not candidates:
            return None

        # Prefere número da mesma região
        country = (destination_country or "DEFAULT").upper()
        regional = [n for n in candidates if country in n.get("region", [])]
        chosen = regional[0] if regional else candidates[0]

        self._pool_state[chosen["id"]] = True
        self.logger.debug(
            "Number acquired: %s for country %s", chosen["number"], country
        )
        return chosen

    def _release_number(self, number_id: str) -> None:
        """Liberta um número do pool."""
        self._pool_state[number_id] = False
        self.logger.debug("Number released: %s", number_id)

    @asynccontextmanager
    async def number_context(self, destination_country: str = "DEFAULT"):
        """
        Context manager para adquirir/libertar número automaticamente.

        Uso:
            async with twilio_svc.number_context("PT") as number:
                # usa number["number"]
        """
        number_info = self._acquire_number(destination_country)
        if not number_info:
            raise ServiceUnavailableError("Sem números disponíveis no pool.")
        try:
            yield number_info
        finally:
            self._release_number(number_info["id"])

    # ──────────────────────────────────────────────────────────────────────────
    # HELPERS DE LOG
    # ──────────────────────────────────────────────────────────────────────────

    async def _log_call(self, call_data: Dict[str, Any]) -> None:
        """Regista chamada no Supabase para histórico e billing."""
        if not self._client():
            return
        try:
            await self._loop().run_in_executor(
                None,
                lambda: self._client().table(CALLS_TABLE).insert(call_data).execute(),
            )
        except Exception as e:
            self.logger.warning("Erro ao log chamada: %s", e)

    # ──────────────────────────────────────────────────────────────────────────
    # TWIML HELPERS (para não ter de lembrar a sintaxe)
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def twiml_say(
        message: str,
        language: str = "pt-PT",
        voice: str = "Polly.Ines-Neural",
    ) -> str:
        """
        Gera TwiML para dizer uma mensagem.

        Exemplos de voice (AWS Polly via Twilio):
            pt-PT: Polly.Ines-Neural
            pt-BR: Polly.Camila-Neural
            en-US: Polly.Joanna-Neural
            en-IE: Polly.Niamh-Neural (irlandesa!)
        """
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>'
            f"<Response>"
            f'<Say language="{language}" voice="{voice}">{message}</Say>'
            f"</Response>"
        )

    @staticmethod
    def twiml_media_stream(stream_url: str, session_id: str) -> str:
        """
        Generate TwiML to connect a call to a Media Stream (WebSocket).

        Used for intelligent AI calls where we need bidirectional audio.
        The stream_url points to our /ws/twilio-stream WebSocket endpoint.
        The session_id is passed as a custom parameter so the WebSocket handler
        knows which CallSession to load.

        Args:
            stream_url: WebSocket URL (wss://capivarex.up.railway.app/ws/twilio-stream)
            session_id: Call session ID (from register_pending_call)

        Returns:
            TwiML XML string
        """
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            "<Connect>"
            f'<Stream url="{stream_url}">'
            f'<Parameter name="session_id" value="{session_id}"/>'
            "</Stream>"
            "</Connect>"
            "</Response>"
        )

    @staticmethod
    def twiml_restaurant_reservation(
        restaurant_name: str,
        party_size: int,
        date_time: str,
        client_name: str,
        language: str = "pt-PT",
    ) -> str:
        """
        TwiML para reserva de restaurante — o bot diz a mensagem de reserva.

        Args:
            restaurant_name: Nome do restaurante
            party_size:      Número de pessoas
            date_time:       Data e hora formatada (ex: "sábado dia 22 às 20 horas")
            client_name:     Nome do cliente para a reserva
            language:        Idioma da mensagem
        """
        if language.startswith("pt"):
            msg = (
                f"Olá, bom dia! Estou a ligar para fazer uma reserva. "
                f"Gostaria de reservar uma mesa para {party_size} pessoas "
                f"para {date_time}. "
                f"O nome da reserva é {client_name}. "
                f"Podem confirmar por favor?"
            )
            voice = (
                "Polly.Ines-Neural" if language == "pt-PT" else "Polly.Camila-Neural"
            )
        else:
            msg = (
                f"Hello! I'm calling to make a reservation. "
                f"I'd like to book a table for {party_size} people "
                f"on {date_time}. "
                f"The name for the reservation is {client_name}. "
                f"Can you confirm please?"
            )
            voice = "Polly.Joanna-Neural"

        return TwilioService.twiml_say(msg, language, voice)
