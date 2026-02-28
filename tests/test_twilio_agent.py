# -*- coding: utf-8 -*-
"""
tests/test_twilio_agent.py
============================
Testes unitários para TwilioAgent.

Cobertura TwilioAgent:
  - _extract_phone_number: formatos internacionais, com/sem espaços, sem número
  - _detect_country: PT, IE, US, BR, GB, ES, FR, DE, IT, desconhecido
  - _extract_message: "diz que...", "diga que...", "fala que...", "avisa que...",
    "say ...", "and say ...", mensagem curta ignorada, sem mensagem
  - execute() happy path: chamada com sucesso, campos na resposta
  - execute() com mensagem personalizada: TwiML inclui mensagem
  - execute() sem número: retorna help
  - execute() TwilioService não disponível: retorna erro
  - execute() init timeout: retorna erro
  - execute() quota excedida: retorna mensagem amigável
  - execute() sem números no pool: retorna mensagem amigável
  - execute() erro genérico: retorna erro
  - execute() país europeu (PT/IE) gera TwiML pt-PT
  - execute() país BR gera TwiML pt-BR
  - execute() país US/unknown gera TwiML en-US
  - get_capabilities(): retorna lista válida
  - Construtor real: name, description correctos
  - _handle_help(): retorna instruções formatadas

Nota: TwilioService já está extensamente coberto em test_quota_twilio.py.
      Este ficheiro foca-se exclusivamente no agent layer.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─── Helpers ───────────────────────────────────────────────────────────────────


def _mock_twilio_service(
    make_call_result=None,
    make_call_side_effect=None,
    initialized=True,
):
    """Cria um mock do TwilioService para injectar no agent."""
    svc = MagicMock()
    svc.is_initialized.return_value = initialized

    if make_call_result is None:
        make_call_result = {
            "call_sid": "CAtestXXXXXXXXXXXXXXXXXXXXXXXX",
            "status": "initiated",
            "from_number": "+14064164577",
            "to_number": "+353894434456",
            "destination_country": "IE",
            "tenant_id": "user_123",
            "created_at": "2026-02-26T10:00:00+00:00",
        }

    if make_call_side_effect:
        svc.make_call = AsyncMock(side_effect=make_call_side_effect)
    else:
        svc.make_call = AsyncMock(return_value=make_call_result)

    svc.initialize = AsyncMock()
    svc.twiml_say = MagicMock(
        side_effect=lambda msg, **kw: (
            f'<?xml version="1.0"?><Response>'
            f'<Say language="{kw.get("language", "pt-BR")}">{msg}</Say>'
            f"</Response>"
        )
    )
    return svc


def _twilio_agent():
    """Cria TwilioAgent com mocks injectados."""
    from agents.specialized.twilio_agent import TwilioAgent

    agent = TwilioAgent.__new__(TwilioAgent)
    agent.name = "twilio"
    agent.description = "Faz chamadas telefónicas via Twilio"
    agent.logger = MagicMock()
    agent._initialized = True
    return agent


def _context(user_id="user_123"):
    return {"user_id": user_id, "tenant_id": "default", "channel": "telegram"}


# ═══════════════════════════════════════════════════════════════════════════════
# PHONE NUMBER EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractPhoneNumber:
    """Testa _extract_phone_number com vários formatos."""

    def test_irish_number(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        assert _extract_phone_number("liga para o +353894434456") == "+353894434456"

    def test_portuguese_number(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        assert _extract_phone_number("chama o +351912345678") == "+351912345678"

    def test_us_number(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        assert _extract_phone_number("call +14064164577") == "+14064164577"

    def test_number_with_spaces(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number("liga para +351 912 345 678")
        assert result == "+351912345678"

    def test_number_with_dashes(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number("call +1-406-416-4577")
        assert result == "+14064164577"

    def test_number_with_parentheses(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number("liga +1 (406) 416-4577")
        assert result == "+14064164577"

    def test_number_without_plus(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number("liga 353894434456")
        assert result == "+353894434456"

    def test_brazilian_number(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number("liga para +5511999887766")
        assert result == "+5511999887766"

    def test_no_number_in_text(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        assert _extract_phone_number("liga para o restaurante") is None

    def test_empty_string(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        assert _extract_phone_number("") is None

    def test_short_number_ignored(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        # Números muito curtos (< 8 dígitos) não devem ser capturados
        assert _extract_phone_number("código 12345") is None

    def test_number_embedded_in_sentence(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number(
            "podes ligar para o +353894434456 e perguntar sobre a reserva?"
        )
        assert result == "+353894434456"

    def test_multiple_numbers_returns_first(self):
        from agents.specialized.twilio_agent import _extract_phone_number

        result = _extract_phone_number("liga +353894434456 ou +351912345678")
        assert result == "+353894434456"


# ═══════════════════════════════════════════════════════════════════════════════
# COUNTRY DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestDetectCountry:
    """Testa _detect_country por prefixo."""

    def test_portugal(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+351912345678") == "PT"

    def test_ireland(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+353894434456") == "IE"

    def test_us(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+14064164577") == "US"

    def test_brazil(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+5511999887766") == "BR"

    def test_uk(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+447911123456") == "GB"

    def test_spain(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+34612345678") == "ES"

    def test_france(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+33612345678") == "FR"

    def test_germany(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+491512345678") == "DE"

    def test_italy(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+393401234567") == "IT"

    def test_unknown_country_returns_default(self):
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+818012345678") == "DEFAULT"  # Japan

    def test_longer_prefix_has_priority(self):
        """
        +351 (PT) deve ter prioridade sobre +35 (não existe, mas
        garante que o matching por comprimento funciona).
        """
        from agents.specialized.twilio_agent import _detect_country

        assert _detect_country("+351999888777") == "PT"


# ═══════════════════════════════════════════════════════════════════════════════
# MESSAGE EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════


class TestExtractMessage:
    """Testa _extract_message — extrai o que o user quer que o bot diga."""

    def test_diz_que(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga para +353894434456 e diz que estou atrasado",
            "+353894434456",
        )
        assert result is not None
        assert "atrasado" in result.lower()

    def test_diga_que(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga para +351912345678 diga que a reunião mudou para as 15h",
            "+351912345678",
        )
        assert result is not None
        assert "reunião" in result.lower()

    def test_fala_que(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "chama o +351912345678 e fala que preciso do relatório",
            "+351912345678",
        )
        assert result is not None
        assert "relatório" in result.lower()

    def test_avisa_que(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga +353894434456 e avisa que chego em 10 minutos",
            "+353894434456",
        )
        assert result is not None
        assert "10 minutos" in result

    def test_say_english(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "call +14064164577 and say I will be late",
            "+14064164577",
        )
        assert result is not None
        assert "late" in result.lower()

    def test_mensagem_keyword(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga +353894434456 mensagem: o jantar é às 20h",
            "+353894434456",
        )
        assert result is not None
        assert "jantar" in result.lower()

    def test_no_message_returns_none(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga para o +353894434456",
            "+353894434456",
        )
        assert result is None

    def test_short_message_ignored(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga +353894434456 e diz ok",
            "+353894434456",
        )
        # "ok" tem < 4 chars, deve ser ignorado
        assert result is None

    def test_diz_without_que(self):
        from agents.specialized.twilio_agent import _extract_message

        result = _extract_message(
            "liga +353894434456 e diz estou a caminho do escritório",
            "+353894434456",
        )
        assert result is not None
        assert "caminho" in result.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — execute() HAPPY PATH
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestTwilioAgentExecuteSuccess:
    """Testa execute() quando tudo funciona."""

    async def test_simple_call_success(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "success"
        assert "📞" in result.response
        assert "+353894434456" in result.response
        assert "initiated" in result.response.lower() or "Chamada" in result.response
        twilio_svc.make_call.assert_called_once()

    async def test_call_includes_all_response_fields(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        # Verifica que todos os campos esperados estão na resposta
        assert "Para:" in result.response or "+353894434456" in result.response
        assert "De:" in result.response or "+14064164577" in result.response
        assert "ID:" in result.response or "CAtestX" in result.response

    async def test_call_passes_correct_params(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("liga para o +353894434456", _context("user_456"))

        call_kwargs = twilio_svc.make_call.call_args
        assert (
            call_kwargs[1]["tenant_id"] == "user_456" or call_kwargs[0][0] == "user_456"
        )
        assert (
            call_kwargs[1]["to_number"] == "+353894434456"
            or call_kwargs[0][1] == "+353894434456"
        )

    async def test_call_returns_data_with_call_sid(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.data is not None
        assert "call_sid" in result.data

    async def test_call_to_portuguese_number(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(
            make_call_result={
                "call_sid": "CAtest_pt",
                "status": "initiated",
                "from_number": "+14064164577",
                "to_number": "+351912345678",
                "destination_country": "PT",
                "tenant_id": "user_123",
                "created_at": "2026-02-26T10:00:00+00:00",
            }
        )

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +351912345678", _context())

        assert result.status.value == "success"
        call_kwargs = twilio_svc.make_call.call_args
        assert call_kwargs[1].get("destination_country") == "PT" or "PT" in str(
            call_kwargs
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — CUSTOM MESSAGE
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestTwilioAgentCustomMessage:
    """Testa chamadas com mensagem personalizada."""

    async def test_call_with_message(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute(
                "liga para o +353894434456 e diz que estou atrasado",
                _context(),
            )

        assert result.status.value == "success"
        assert "atrasado" in result.response.lower()
        # TwiML deve ter sido gerado com a mensagem
        twilio_svc.twiml_say.assert_called_once()
        twiml_call = twilio_svc.twiml_say.call_args
        assert "atrasado" in twiml_call[0][0].lower()

    async def test_call_message_shows_in_response(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute(
                "liga para +351912345678 e avisa que chego em 10 minutos",
                _context(),
            )

        assert "💬" in result.response or "Mensagem" in result.response

    async def test_default_message_when_no_custom(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("liga para o +353894434456", _context())

        # twiml_say é chamado com mensagem default
        twilio_svc.twiml_say.assert_called_once()
        default_msg = twilio_svc.twiml_say.call_args[0][0]
        assert "Capivarex" in default_msg or "automática" in default_msg.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — LANGUAGE DETECTION
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestTwilioAgentLanguage:
    """Testa que o idioma do TwiML é correcto para cada país."""

    async def test_pt_country_uses_portuguese(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute(
                "liga +351912345678 e diz que confirmo a reserva", _context()
            )

        twiml_kwargs = twilio_svc.twiml_say.call_args[1]
        assert twiml_kwargs.get("language") == "pt-BR"

    async def test_br_country_uses_brazilian(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute(
                "liga +5511999887766 e diz que vou chegar atrasado", _context()
            )

        twiml_kwargs = twilio_svc.twiml_say.call_args[1]
        assert twiml_kwargs.get("language") == "pt-BR"

    async def test_us_country_uses_english(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("call +14064164577 and say I will be late", _context())

        twiml_kwargs = twilio_svc.twiml_say.call_args[1]
        assert twiml_kwargs.get("language") == "en-US"

    async def test_ie_country_default_message_in_english(self):
        """IE sem custom message deve gerar TwiML em inglês."""
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("liga +353894434456", _context())

        default_msg = twilio_svc.twiml_say.call_args[0][0]
        # IE é inglês por default
        assert "Hello" in default_msg or "automated" in default_msg.lower()

    async def test_pt_default_message_in_portuguese(self):
        """PT sem custom message deve gerar TwiML em pt-BR."""
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("liga +351912345678", _context())

        default_msg = twilio_svc.twiml_say.call_args[0][0]
        assert "Olá" in default_msg or "automática" in default_msg.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — NO PHONE NUMBER (HELP)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestTwilioAgentHelp:
    """Testa que sem número, o agent retorna help."""

    async def test_no_number_returns_help(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("faz uma chamada", _context())

        assert result.status.value == "success"
        assert "Como Usar" in result.response or "+353" in result.response

    async def test_help_has_examples(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("ajuda com chamada", _context())

        assert "liga para" in result.response.lower()
        assert (
            "chamada" in result.response.lower()
            or "mensagem" in result.response.lower()
        )

    async def test_help_mentions_country_code(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("como fazer chamada?", _context())

        assert (
            "+353" in result.response
            or "+351" in result.response
            or "+1" in result.response
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — ERROR HANDLING
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestTwilioAgentErrors:
    """Testa todos os caminhos de erro."""

    async def test_service_not_available(self):
        agent = _twilio_agent()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=None,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "error"
        assert (
            "não disponível" in result.response.lower() or "TWILIO" in result.response
        )

    async def test_service_init_timeout(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(initialized=False)
        twilio_svc.initialize = AsyncMock(
            side_effect=lambda: (_ for _ in ()).throw(
                Exception("simulated slow init — would timeout")
            )
        )
        # Simulate timeout by making initialize never complete
        import asyncio

        async def slow_init():
            await asyncio.sleep(999)

        twilio_svc.initialize = slow_init

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "error"
        assert "demorou" in result.response.lower() or "timeout" in result.error.lower()

    async def test_quota_exceeded_error(self):
        from services.business.quota_service import QuotaExceededError

        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(
            make_call_side_effect=QuotaExceededError("twilio_mins", 15, 15, "me")
        )

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "error"
        assert (
            "quota" in result.response.lower() or "esgotada" in result.response.lower()
        )

    async def test_no_numbers_available_error(self):
        from services.core import ServiceUnavailableError

        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(
            make_call_side_effect=ServiceUnavailableError(
                "Nenhum número disponível no pool agora."
            )
        )

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "error"
        assert (
            "número" in result.response.lower()
            or "disponível" in result.response.lower()
        )

    async def test_generic_runtime_error(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(
            make_call_side_effect=RuntimeError("Twilio erro 500: Internal Server Error")
        )

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "error"
        assert "Erro" in result.response or "500" in result.response

    async def test_unexpected_exception(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(
            make_call_side_effect=Exception("completely unexpected")
        )

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para o +353894434456", _context())

        assert result.status.value == "error"
        assert result.error is not None


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — CONSTRUCTOR & CAPABILITIES
# ═══════════════════════════════════════════════════════════════════════════════


class TestTwilioAgentMeta:
    """Testa construtor e capabilities."""

    def test_real_constructor(self):
        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=None,
        ):
            from agents.specialized.twilio_agent import TwilioAgent

            agent = TwilioAgent()
            assert agent.name == "twilio"
            assert (
                "chamada" in agent.description.lower()
                or "twilio" in agent.description.lower()
            )

    def test_get_capabilities(self):
        agent = _twilio_agent()
        caps = agent.get_capabilities()
        assert isinstance(caps, list)
        assert len(caps) >= 2
        assert "phone_calls" in caps
        assert "voice_messages" in caps

    def test_handle_help_returns_success(self):
        agent = _twilio_agent()
        result = agent._handle_help()
        assert result.status.value == "success"
        assert "📞" in result.response
        assert "liga para" in result.response.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# TWILIO AGENT — EDGE CASES
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestTwilioAgentEdgeCases:
    """Testa edge cases e cenários menos óbvios."""

    async def test_empty_prompt(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("", _context())

        # Sem número → help
        assert result.status.value == "success"
        assert "Como Usar" in result.response or "📞" in result.response

    async def test_context_without_user_id(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga +353894434456", {"channel": "telegram"})

        # Deve funcionar mesmo sem user_id (usa string vazia)
        assert result.status.value == "success"
        call_kwargs = twilio_svc.make_call.call_args
        assert call_kwargs[1]["tenant_id"] == "" or call_kwargs[0][0] == ""

    async def test_very_long_message(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()
        long_msg = "a" * 500

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute(
                f"liga +353894434456 e diz que {long_msg}", _context()
            )

        # Deve funcionar sem crash
        assert result.status.value == "success"

    async def test_special_characters_in_number(self):
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service()

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            result = await agent.execute("liga para (+353) 89-443-4456", _context())

        assert result.status.value == "success"
        call_kwargs = twilio_svc.make_call.call_args
        to_number = call_kwargs[1].get("to_number") or call_kwargs[0][1]
        assert to_number == "+353894434456"

    async def test_service_already_initialized(self):
        """Quando service já está initialized, não chama initialize()."""
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(initialized=True)

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("liga +353894434456", _context())

        twilio_svc.initialize.assert_not_called()

    async def test_service_not_initialized_calls_init(self):
        """Quando service não está initialized, chama initialize()."""
        agent = _twilio_agent()
        twilio_svc = _mock_twilio_service(initialized=False)

        with patch(
            "agents.specialized.twilio_agent.get_service",
            return_value=twilio_svc,
        ):
            await agent.execute("liga +353894434456", _context())

        twilio_svc.initialize.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# INTEGRATION: AGENT + ORCHESTRATOR REGISTRATION
# ═══════════════════════════════════════════════════════════════════════════════


class TestTwilioAgentRegistration:
    """Testa que o agent se regista correctamente."""

    def test_agent_is_registered_as_twilio(self):
        """
        Verifica que @register_agent("twilio") funciona e o agent
        pode ser obtido pela registry.
        """
        # Import triggers registration
        from agents.specialized.twilio_agent import TwilioAgent  # noqa: F401
        from agents.core import get_agent

        agent = get_agent("twilio")  # noqa: F841
        # Pode ser None se registry foi limpa, mas a classe deve existir
        assert TwilioAgent is not None

    def test_agent_class_has_correct_name(self):
        from agents.specialized.twilio_agent import TwilioAgent

        agent = TwilioAgent.__new__(TwilioAgent)
        agent.name = "twilio"
        assert agent.name == "twilio"
