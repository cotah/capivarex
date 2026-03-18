# -*- coding: utf-8 -*-
"""
agents/specialized/twilio_agent.py
====================================
Twilio Agent — Fazer chamadas telefónicas via Telegram.

O utilizador pede:
  - "liga para o +353894434456"
  - "faz uma chamada para +351912345678"
  - "chama o +14061234567 e diz que estou atrasado"
  - "liga para o restaurante +353894434456 e faz reserva para 2 às 20h"

O agent:
  1. Extrai o número do prompt
  2. Detecta o país pelo prefixo
  3. Gera TwiML (mensagem a dizer) ou usa default
  4. Chama TwilioService.make_call()
  5. Retorna confirmação com SID da chamada

Depende de:
  - TwilioService (services/integrations/twilio_service.py) registado como "twilio"
  - TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN configurados no .env
"""

import asyncio
import logging
import os
import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

logger = logging.getLogger(__name__)

# ── Intelligent calls (Media Streams) ────────────────────────────────────
# When set, calls use the real-time AI conversation pipeline.
# TWILIO_STREAM_BASE_URL takes priority; BACKEND_URL is the fallback.
BACKEND_URL = os.getenv("TWILIO_STREAM_BASE_URL", os.getenv("BACKEND_URL", ""))

# ── Regex para extrair números de telefone ────────────────────────────────
# Aceita: +353894434456, +351 912 345 678, +1-406-416-4577, etc.
_PHONE_REGEX = re.compile(r"\+?\d[\d\s\-\(\)]{7,18}\d")

# ── Prefixos de país (para selecção de número do pool) ────────────────────
_COUNTRY_PREFIXES = {
    "+1": "US",
    "+351": "PT",
    "+353": "IE",
    "+44": "GB",
    "+34": "ES",
    "+33": "FR",
    "+49": "DE",
    "+55": "BR",
    "+39": "IT",
}


def _extract_phone_number(text: str) -> Optional[str]:
    """Extrai o primeiro número de telefone do texto."""
    match = _PHONE_REGEX.search(text)
    if match:
        # Limpa espaços, hífens, parêntesis
        raw = match.group()
        cleaned = re.sub(r"[\s\-\(\)]", "", raw)
        # Garante que começa com +
        if not cleaned.startswith("+"):
            cleaned = "+" + cleaned
        return cleaned
    return None


def _detect_country(phone_number: str) -> str:
    """Detecta o país pelo prefixo do número."""
    for prefix, country in sorted(_COUNTRY_PREFIXES.items(), key=lambda x: -len(x[0])):
        if phone_number.startswith(prefix):
            return country
    return "DEFAULT"


def _resolve_user_name(context: Dict[str, Any]) -> str:
    """
    Resolve the user's real name from context.

    Checks multiple sources (REST API UserContext, direct key, Telegram username)
    to ensure the bot says "calling on behalf of Henrique" instead of "User".
    """
    # 1. REST API — UserContext with full_name
    user_obj = context.get("user")
    if isinstance(user_obj, dict) and user_obj.get("full_name"):
        return user_obj["full_name"]

    # 2. Direct key (set by some callers)
    if context.get("user_name"):
        return context["user_name"]

    # 3. Telegram username
    if context.get("username"):
        return context["username"]

    return "User"


def _extract_message(text: str, phone_number: str) -> Optional[str]:
    """
    Extrai mensagem a dizer na chamada, se o user especificou.
    Ex: "liga para +353... e diz que estou atrasado" → "estou atrasado"
    """
    lower = text.lower()  # noqa: F841

    # Padrões: "e diz que ...", "e fala que ...", "e avisa que ...",
    # "diga que ...", "say ...", "and say ..."
    patterns = [
        r"(?:e\s+)?(?:diz|diga|fala|fale|avisa|avise)\s+(?:que\s+)?(.+?)$",
        r"(?:and\s+)?(?:say|tell)\s+(?:that\s+)?(.+?)$",
        r"mensagem[:\s]+(.+?)$",
        r"message[:\s]+(.+?)$",
    ]

    # Remove o número do texto para facilitar o match
    cleaned = text.replace(phone_number, "").strip()

    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            msg = match.group(1).strip()
            if len(msg) > 3:  # Ignora mensagens muito curtas
                return msg

    return None


@register_agent("twilio")
class TwilioAgent(BaseAgent):
    """
    Agent para chamadas telefónicas via Twilio.

    Funcionalidades:
    - Fazer chamadas para qualquer número
    - Chamadas com mensagem personalizada (TwiML Say)
    - Detecção automática de país para selecção de número
    - Help com exemplos de uso
    """

    def __init__(self):
        super().__init__(
            name="twilio",
            description="Faz chamadas telefónicas via Twilio",
        )

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Processa pedido de chamada telefónica."""
        try:
            # Obter TwilioService
            twilio_svc = get_service("twilio")
            if not twilio_svc:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "📞 Serviço de chamadas não disponível.\n"
                        "Verifique se TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN "
                        "estão configurados."
                    ),
                    error="TwilioService not registered",
                )

            if not twilio_svc.is_initialized():
                try:
                    await asyncio.wait_for(twilio_svc.initialize(), timeout=10)
                except asyncio.TimeoutError:
                    return AgentResponse(
                        status=AgentStatus.ERROR,
                        response="📞 Serviço de chamadas demorou a inicializar. Tente novamente.",
                        error="Twilio init timeout",
                    )

            # Extrair número de telefone
            phone_number = _extract_phone_number(prompt)
            if not phone_number:
                return self._handle_help()

            # Route: intelligent (Media Streams) or static (TwiML <Say>)
            return await self._execute_call(twilio_svc, phone_number, prompt, context)

        except Exception as e:
            error_msg = str(e)
            self.logger.error("TwilioAgent failed: %s", e, exc_info=True)

            # Mensagens amigáveis para erros comuns
            if "quota" in error_msg.lower():
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "📞 Quota de chamadas esgotada.\n"
                        "Verifique seu plano ou aguarde a renovação."
                    ),
                    error=error_msg,
                )
            if "número" in error_msg.lower() or "disponível" in error_msg.lower():
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "📞 Nenhum número disponível para chamadas neste momento.\n"
                        "Tente novamente em alguns minutos."
                    ),
                    error=error_msg,
                )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"📞 Erro ao fazer chamada: {error_msg}",
                error=error_msg,
            )

    # ------------------------------------------------------------------
    # Call routing — intelligent vs static
    # ------------------------------------------------------------------

    async def _execute_call(
        self,
        twilio_svc,
        phone_number: str,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Execute a phone call — intelligent (Media Streams) or static (fallback)."""
        if BACKEND_URL:
            try:
                return await self._execute_intelligent_call(
                    twilio_svc, phone_number, prompt, context
                )
            except Exception as e:
                logger.warning("Intelligent call failed, falling back to static: %s", e)

        return await self._execute_static_call(
            twilio_svc, phone_number, prompt, context
        )

    # ------------------------------------------------------------------
    # Intelligent call (Media Streams + real-time AI conversation)
    # ------------------------------------------------------------------

    async def _execute_intelligent_call(
        self,
        twilio_svc,
        phone_number: str,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """
        Make an intelligent AI call using Twilio Media Streams.

        Pipeline:
        1. Extract call plan via CallBrain (objective, language, greeting)
        2. Register pending call session (in-memory, for WebSocket to pick up)
        3. Generate TwiML with <Connect><Stream> (points to our WebSocket)
        4. Make the call via Twilio API
        5. Return confirmation (WebSocket handler takes over from here)
        """
        from services.ai.call_brain import CallBrain
        from services.business.call_session import register_pending_call

        user_name = _resolve_user_name(context)

        # Fallback: fetch name from Supabase if unresolved
        chat_id = context.get("chat_id", 0)
        user_id = context.get("user_id", 0)
        if user_name == "User":
            try:
                db_svc = get_service("database")
                if db_svc:
                    tg_chat_id = context.get("chat_id") or context.get(
                        "telegram_chat_id"
                    )
                    if tg_chat_id:
                        user_data = await db_svc.get_user_by_telegram_id(
                            str(tg_chat_id)
                        )
                        if user_data and user_data.get("full_name"):
                            user_name = user_data["full_name"]
            except Exception as e:
                logger.warning(
                    "Could not fetch user name from DB: %s",
                    e,
                )

        country = _detect_country(phone_number)

        # 1. Extract call plan
        brain = CallBrain()
        plan = await brain.extract_call_plan(
            user_prompt=prompt,
            user_name=user_name,
        )

        logger.info(
            "Call plan: objective=%s language=%s greeting=%s",
            plan.objective[:80],
            plan.language,
            plan.greeting[:50] if plan.greeting else "(auto)",
        )

        # 2. Register pending call
        session_id = register_pending_call(
            objective=plan.objective,
            user_name=user_name,
            language=plan.language,
            phone_number=phone_number,
            telegram_chat_id=chat_id,
            telegram_user_id=user_id,
            extra_context=plan.key_details,
            greeting=plan.greeting,
        )

        # 3. Generate TwiML with Media Stream
        ws_url = BACKEND_URL.replace("https://", "wss://").replace("http://", "ws://")
        stream_url = f"{ws_url}/ws/twilio-stream"

        twiml = twilio_svc.twiml_media_stream(
            stream_url=stream_url,
            session_id=session_id,
        )

        # 4. Make the call
        tenant_id = str(user_id) if user_id else ""
        result = await twilio_svc.make_call(
            tenant_id=tenant_id,
            to_number=phone_number,
            twiml_or_url=twiml,
            destination_country=country,
        )

        call_sid = result.get("call_sid", "unknown")

        logger.info(
            "Intelligent call initiated: session=%s call_sid=%s -> %s",
            session_id[:8],
            call_sid,
            phone_number,
        )

        # 5. Return confirmation
        lines = [
            "📞 **Chamada inteligente iniciada!**\n",
            f"📱 Para: `{phone_number}`",
            f"🎯 Objetivo: {plan.objective}",
            f"🌍 Idioma: {plan.language.upper()}",
            "⏳ O bot vai conduzir a conversa e reportar quando terminar.",
        ]

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={
                **result,
                "mode": "intelligent",
                "session_id": session_id,
                "objective": plan.objective,
                "language": plan.language,
            },
        )

    # ------------------------------------------------------------------
    # Static call (original TwiML <Say> behavior — fallback)
    # ------------------------------------------------------------------

    async def _execute_static_call(
        self,
        twilio_svc,
        phone_number: str,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Original static call logic — TwiML <Say> with a fixed message."""
        country = _detect_country(phone_number)
        custom_message = _extract_message(prompt, phone_number)

        # Gerar TwiML
        if custom_message:
            lang = (
                "pt-BR"
                if country in ("PT", "BR")
                else ("en-IE" if country in ("IE",) else "en-US")
            )
            twiml = twilio_svc.twiml_say(custom_message, language=lang)
        else:
            if country in ("PT", "BR"):
                twiml = twilio_svc.twiml_say(
                    "Olá! Esta é uma chamada automática do Capivarex. "
                    "O usuário pediu para entrar em contato com você. "
                    "Por favor, aguarde enquanto tentamos conectar.",
                    language="pt-BR",
                )
            else:
                twiml = twilio_svc.twiml_say(
                    "Hello! This is an automated call from Capivarex. "
                    "The user asked to get in touch with you. "
                    "Please hold while we try to connect.",
                    language="en-US",
                )

        # Fazer chamada
        tenant_id = str(context.get("user_id", ""))
        self.logger.info(
            "TwilioAgent: calling %s (country=%s, tenant=%s)",
            phone_number,
            country,
            tenant_id,
        )

        result = await twilio_svc.make_call(
            tenant_id=tenant_id,
            to_number=phone_number,
            twiml_or_url=twiml,
            destination_country=country,
        )

        # Formatar resposta
        call_sid = result.get("call_sid", "?")
        from_number = result.get("from_number", "?")
        status = result.get("status", "initiated")

        lines = [
            "📞 **Chamada iniciada!**\n",
            f"📱 Para: `{phone_number}`",
            f"📲 De: `{from_number}`",
            f"🌍 País: {country}",
            f"📊 Status: {status}",
        ]

        if custom_message:
            lines.append(f'\n💬 Mensagem: "{custom_message}"')

        lines.append(f"\n🔑 ID: `{call_sid[:20]}...`")

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response="\n".join(lines),
            data={**result, "mode": "static"},
        )

    def _handle_help(self) -> AgentResponse:
        """Retorna instruções de uso."""
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                "📞 **Chamadas Telefônicas — Como Usar**\n\n"
                "**Chamada simples:**\n"
                '• "liga para o +353894434456"\n'
                '• "chama o +351912345678"\n\n'
                "**Chamada com mensagem:**\n"
                '• "liga para +353... e diz que estou atrasado"\n'
                '• "chama +351... e avisa que a reunião mudou para as 15h"\n\n'
                "**Importante:**\n"
                "• Inclua o código do país (+353, +351, +1, etc.)\n"
                "• A chamada é feita pelo sistema Twilio\n"
                "• O destinatário ouve a mensagem por voz"
            ),
        )

    def get_capabilities(self) -> List[str]:
        return [
            "phone_calls",
            "voice_messages",
            "twiml_generation",
            "multi_country",
        ]
