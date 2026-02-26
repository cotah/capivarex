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
import re
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

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
                        "Verifica se TWILIO_ACCOUNT_SID e TWILIO_AUTH_TOKEN "
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
                        response="📞 Serviço de chamadas demorou a inicializar. Tenta novamente.",
                        error="Twilio init timeout",
                    )

            # Extrair número de telefone
            phone_number = _extract_phone_number(prompt)
            if not phone_number:
                return self._handle_help()

            # Detectar país
            country = _detect_country(phone_number)

            # Extrair mensagem personalizada (se houver)
            custom_message = _extract_message(prompt, phone_number)

            # Gerar TwiML
            if custom_message:
                # Detectar idioma pela mensagem/país
                lang = (
                    "pt-PT"
                    if country in ("PT",)
                    else (
                        "pt-BR"
                        if country in ("BR",)
                        else ("en-IE" if country in ("IE",) else "en-US")
                    )
                )
                twiml = twilio_svc.twiml_say(custom_message, language=lang)
            else:
                # Mensagem default baseada no idioma
                if country in ("PT", "BR"):
                    twiml = twilio_svc.twiml_say(
                        "Olá! Esta é uma chamada automática do Capivarex. "
                        "O utilizador pediu para entrar em contacto consigo. "
                        "Por favor, aguarde enquanto tentamos conectar.",
                        language="pt-PT" if country == "PT" else "pt-BR",
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
                data=result,
            )

        except Exception as e:
            error_msg = str(e)
            self.logger.error("TwilioAgent failed: %s", e, exc_info=True)

            # Mensagens amigáveis para erros comuns
            if "quota" in error_msg.lower():
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "📞 Quota de chamadas esgotada.\n"
                        "Verifica o teu plano ou aguarda a renovação."
                    ),
                    error=error_msg,
                )
            if "número" in error_msg.lower() or "disponível" in error_msg.lower():
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=(
                        "📞 Nenhum número disponível para chamadas neste momento.\n"
                        "Tenta novamente em alguns minutos."
                    ),
                    error=error_msg,
                )

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"📞 Erro ao fazer chamada: {error_msg}",
                error=error_msg,
            )

    def _handle_help(self) -> AgentResponse:
        """Retorna instruções de uso."""
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=(
                "📞 **Chamadas Telefónicas — Como Usar**\n\n"
                "**Chamada simples:**\n"
                '• "liga para o +353894434456"\n'
                '• "chama o +351912345678"\n\n'
                "**Chamada com mensagem:**\n"
                '• "liga para +353... e diz que estou atrasado"\n'
                '• "chama +351... e avisa que a reunião mudou para as 15h"\n\n'
                "**Importante:**\n"
                "• Inclui o código do país (+353, +351, +1, etc.)\n"
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
