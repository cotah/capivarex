"""
Dev Agent - Handles code generation, analysis, and programming queries.
Refactored to use intent classification with Anthropic/OpenAI dual-backend
and robust error handling.

FIXES [2025-02]:
  FIX 1 (TIMEOUT): Anthropic demora 3-4 minutos para código longo.
    ANTES: await anthropic_svc.generate_code(prompt) → sem timeout → Railway
           mata a conexão HTTP antes de responder.
    DEPOIS: asyncio.wait_for(..., timeout=90) → fallback para OpenAI se >90s.

  FIX 2 (HELP FALSO): "Fetch JS" e "cria função Python" retornam help.
    CAUSA: GPT-4o-mini classifica "fetch" como 'help' às vezes.
    DEPOIS: Se a query contém palavras de geração de código (cria, gera, escreve,
            fetch, function, etc.) força intent='generate_code', ignorando o LLM.

  FIX 3 (RESPOSTA VAZIA): Se Anthropic e OpenAI falharem, resposta clara ao
           utilizador em vez de string vazia.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service

logger = logging.getLogger(__name__)

VALID_INTENTS = {
    "generate_code",
    "explain_code",
    "review_code",
    "debug_code",
    "optimize_code",
    "help",
}

# FIX 2: Palavras que FORÇAM generate_code independentemente do LLM
_FORCE_GENERATE_WORDS = {
    "cria",
    "crie",
    "gera",
    "gere",
    "escreve",
    "escreva",
    "faz",
    "faça",
    "faze",
    "implemente",
    "implementa",
    "código",
    "code",
    "função",
    "function",
    "script",
    "fetch",
    "classe",
    "class",
    "método",
    "method",
    "endpoint",
    "api",
    "rest",
    "graphql",
    "lambda",
    "decorator",
}

_SYSTEM_PROMPTS: Dict[str, str] = {
    "generate_code": (
        "You are an expert software developer. Generate clean, "
        "well-documented code with explanations. Include docstrings, "
        "type hints, and usage examples when appropriate. "
        "Respond in the same language as the user's request."
    ),
    "explain_code": (
        "You are an expert programmer. Explain the provided code clearly "
        "and concisely, highlighting key concepts, patterns, and potential "
        "pitfalls. Respond in the same language as the user's request."
    ),
    "review_code": (
        "You are a senior code reviewer. Analyze the code for quality, "
        "security, performance, readability, and best practices. Provide "
        "actionable feedback. Respond in the same language as the user's request."
    ),
    "debug_code": (
        "You are an expert debugger. Help identify the root cause of the "
        "problem and suggest concrete fixes. Walk through the issue "
        "systematically. Respond in the same language as the user's request."
    ),
    "optimize_code": (
        "You are a performance optimization expert. Analyze the code and "
        "suggest concrete improvements for speed, memory usage, and "
        "algorithmic efficiency. Respond in the same language as the user's request."
    ),
}

# Timeout em segundos para chamadas ao Anthropic (Claude gera código longo)
_ANTHROPIC_TIMEOUT_SECONDS = 90
# Timeout para OpenAI (mais rápido por padrão)
_OPENAI_TIMEOUT_SECONDS = 60


@register_agent("dev")
class DevAgent(BaseAgent):
    """
    Dev agent for code generation and programming queries.

    Handles:
    - Code generation (Python, JavaScript, etc.)
    - Code explanation
    - Code review
    - Debugging assistance
    - Performance optimization
    """

    def __init__(self):
        super().__init__(
            name="dev",
            description="Handles code generation and programming queries",
        )

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    def _force_intent_from_keywords(self, text: str) -> Optional[str]:
        """
        FIX 2: Verifica se o texto contém palavras que indicam geração de código.
        Evita que o LLM classifique "crie uma função" ou "fetch JS" como 'help'.

        Returns:
            'generate_code' se palavras forçadas encontradas, None caso contrário.
        """
        text_lower = text.lower()
        words = set(text_lower.replace(",", " ").replace(".", " ").split())
        if words & _FORCE_GENERATE_WORDS:
            return "generate_code"
        return None

    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """
        Classify the developer's request into an intent.

        FIX 2: Verifica keywords ANTES de chamar o LLM para evitar
        classificação errada de pedidos de geração de código.
        """
        # FIX 2: override por keyword antes do LLM
        forced = self._force_intent_from_keywords(user_message)
        if forced:
            self.logger.debug("DevAgent: forced intent=%s (keyword match)", forced)
            return {
                "intent": forced,
                "language": None,
                "code": None,
                "description": None,
            }

        openai_svc = get_service("openai")
        if not openai_svc:
            return {
                "intent": "generate_code",
                "language": None,
                "code": None,
                "description": None,
            }

        try:
            if not openai_svc.is_initialized():
                await openai_svc.initialize()
            client = openai_svc.get_client()
            if not client:
                return {
                    "intent": "generate_code",
                    "language": None,
                    "code": None,
                    "description": None,
                }

            system_prompt = (
                "You are an intent classifier for software development commands.\n\n"
                "Analyze the user's message and return a JSON object with:\n"
                '- "intent": one of: generate_code, explain_code, review_code, '
                "debug_code, optimize_code, help\n"
                '- "language": programming language if mentioned, or null\n'
                '- "code": code snippet if provided by the user, or null\n'
                '- "description": what the user wants, or null\n\n'
                "IMPORTANT: Only use 'help' when the user explicitly asks for help "
                "or documentation about what the agent can do. "
                "If the user wants to CREATE, GENERATE, WRITE, or FETCH code → generate_code.\n\n"
                "Examples:\n"
                '"crie uma função Python para calcular fibonacci" → '
                '{"intent":"generate_code","language":"python"}\n'
                '"fetch data from API in JS" → {"intent":"generate_code","language":"javascript"}\n'
                '"explique este código: def foo(): pass" → '
                '{"intent":"explain_code","code":"def foo(): pass"}\n'
                '"faça code review deste código" → {"intent":"review_code"}\n'
                '"o que você pode fazer?" → {"intent":"help"}\n\n'
                "Return ONLY the JSON object, no other text."
            )

            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.0,
                max_tokens=200,
            )

            result_text = (response.choices[0].message.content or "").strip()
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            result = json.loads(result_text)
            intent = result.get("intent", "generate_code")
            if intent not in VALID_INTENTS:
                intent = "generate_code"

            # FIX 2: Extra-safety: se LLM diz 'help' mas há keywords de código, sobrescreve
            if intent == "help":
                override = self._force_intent_from_keywords(user_message)
                if override:
                    intent = override
                    self.logger.info(
                        "DevAgent: LLM said 'help' but keywords suggest '%s', overriding",
                        override,
                    )

            return {
                "intent": intent,
                "language": result.get("language"),
                "code": result.get("code"),
                "description": result.get("description"),
            }

        except Exception as e:
            self.logger.warning(
                "Intent classification failed, defaulting to generate_code: %s", e
            )
            return {
                "intent": "generate_code",
                "language": None,
                "code": None,
                "description": None,
            }

    # ------------------------------------------------------------------
    # AI back-ends com timeout
    # ------------------------------------------------------------------

    async def _generate_with_anthropic(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """
        Try to generate a response using Anthropic (Claude).

        FIX 1: Agora com timeout de 90s. Se Claude demorar mais do que isso,
        retorna None e o caller faz fallback para OpenAI.
        """
        try:
            anthropic_svc = get_service("anthropic")
            if not anthropic_svc:
                self.logger.debug("DevAgent: Anthropic service not registered")
                return None

            if not anthropic_svc.is_initialized():
                await anthropic_svc.initialize()

            # FIX 1: Wrap com timeout para não bloquear o event loop indefinidamente
            if hasattr(anthropic_svc, "generate_code"):
                self.logger.info(
                    "DevAgent: Calling Anthropic generate_code (timeout=%ds)",
                    _ANTHROPIC_TIMEOUT_SECONDS,
                )
                try:
                    text = await asyncio.wait_for(
                        anthropic_svc.generate_code(
                            prompt, system_prompt=system_prompt
                        ),
                        timeout=_ANTHROPIC_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "DevAgent: Anthropic timed out after %ds, falling back to OpenAI",
                        _ANTHROPIC_TIMEOUT_SECONDS,
                    )
                    return None

                if text and text.strip():
                    return text.strip()

            # Fallback: streaming
            if hasattr(anthropic_svc, "generate_code_stream"):
                self.logger.info("DevAgent: Calling Anthropic generate_code_stream")
                chunks: List[str] = []
                try:
                    async for chunk in asyncio.wait_for(
                        anthropic_svc.generate_code_stream(
                            prompt, system_prompt=system_prompt
                        ),
                        timeout=_ANTHROPIC_TIMEOUT_SECONDS,
                    ):
                        chunks.append(chunk)
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "DevAgent: Anthropic stream timed out after %ds",
                        _ANTHROPIC_TIMEOUT_SECONDS,
                    )
                    # Se já temos chunks, retorna o que temos
                    partial = "".join(chunks).strip()
                    if partial:
                        self.logger.info(
                            "DevAgent: Returning partial Anthropic response (%d chars)",
                            len(partial),
                        )
                        return partial
                    return None

                text = "".join(chunks).strip()
                if text:
                    return text

            self.logger.warning("DevAgent: Anthropic returned empty response")
            return None

        except Exception as e:
            self.logger.warning("DevAgent: Anthropic failed: %s", e)
            return None

    async def _generate_with_openai(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 4000,
    ) -> Optional[str]:
        """Try to generate a response using OpenAI (with timeout)."""
        try:
            openai_svc = get_service("openai")
            if not openai_svc:
                self.logger.debug("DevAgent: OpenAI service not registered")
                return None

            if not openai_svc.is_initialized():
                await openai_svc.initialize()

            self.logger.info("DevAgent: Calling OpenAI chat_completion")
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            # FIX 1: timeout também para OpenAI
            try:
                text = await asyncio.wait_for(
                    openai_svc.chat_completion(
                        messages=messages,
                        model="gpt-4o-mini",
                        temperature=0.3,
                        max_tokens=max_tokens,
                    ),
                    timeout=_OPENAI_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "DevAgent: OpenAI timed out after %ds", _OPENAI_TIMEOUT_SECONDS
                )
                return None

            text = (text or "").strip()
            return text if text else None

        except Exception as e:
            self.logger.warning("DevAgent: OpenAI failed: %s", e)
            return None

    async def _call_ai(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 4000,
    ) -> Optional[str]:
        """Try Anthropic first (with timeout), then OpenAI. Returns None if both fail."""
        text = await self._generate_with_anthropic(prompt, system_prompt=system_prompt)
        if text:
            return text
        text = await self._generate_with_openai(prompt, system_prompt, max_tokens)
        return text

    # ------------------------------------------------------------------
    # Main execute
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """Process a development/programming command."""
        dev_prompt = str(context.get("prompt") or prompt).strip()
        if not dev_prompt:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não recebi um prompt de desenvolvimento.",
                error="Empty dev prompt",
            )

        try:
            analysis = await self._analyze_intent(dev_prompt)
            intent = analysis["intent"]
            self.logger.info("DevAgent: intent=%s", intent)

            dispatch = {
                "generate_code": self._handle_generate_code,
                "explain_code": self._handle_explain_code,
                "review_code": self._handle_review_code,
                "debug_code": self._handle_debug_code,
                "optimize_code": self._handle_optimize_code,
                "help": self._handle_help,
            }

            handler = dispatch.get(intent, self._handle_generate_code)
            return await handler(dev_prompt, analysis)

        except Exception as e:
            self.logger.error("DevAgent failed: %s", e, exc_info=True)
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=f"Erro ao processar comando de desenvolvimento: {e}",
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    async def _handle_generate_code(
        self, prompt: str, analysis: Dict[str, Any]
    ) -> AgentResponse:
        system = _SYSTEM_PROMPTS["generate_code"]
        text = await self._call_ai(prompt, system)
        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                # FIX 3: Mensagem clara com diagnóstico
                response=(
                    "⚠️ Não foi possível gerar o código no momento.\n"
                    "Os serviços de IA (Anthropic e OpenAI) não responderam a tempo.\n"
                    "Tenta novamente em alguns instantes."
                ),
                error="No AI response (both Anthropic and OpenAI failed or timed out)",
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"intent": "generate_code", "language": analysis.get("language")},
        )

    async def _handle_explain_code(
        self, prompt: str, analysis: Dict[str, Any]
    ) -> AgentResponse:
        system = _SYSTEM_PROMPTS["explain_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)
        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="⚠️ Não foi possível explicar o código no momento. Tenta novamente.",
                error="No AI response",
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"intent": "explain_code"},
        )

    async def _handle_review_code(
        self, prompt: str, analysis: Dict[str, Any]
    ) -> AgentResponse:
        system = _SYSTEM_PROMPTS["review_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)
        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="⚠️ Não foi possível fazer o code review no momento. Tenta novamente.",
                error="No AI response",
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"intent": "review_code"},
        )

    async def _handle_debug_code(
        self, prompt: str, analysis: Dict[str, Any]
    ) -> AgentResponse:
        system = _SYSTEM_PROMPTS["debug_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)
        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="⚠️ Não foi possível ajudar com debugging no momento. Tenta novamente.",
                error="No AI response",
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"intent": "debug_code"},
        )

    async def _handle_optimize_code(
        self, prompt: str, analysis: Dict[str, Any]
    ) -> AgentResponse:
        system = _SYSTEM_PROMPTS["optimize_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)
        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="⚠️ Não foi possível otimizar o código no momento. Tenta novamente.",
                error="No AI response",
            )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"intent": "optimize_code"},
        )

    async def _handle_help(
        self, prompt: str = "", analysis: Dict[str, Any] = None
    ) -> AgentResponse:
        help_text = (
            "💻 **Dev Agent — Comandos Disponíveis**\n\n"
            "**Geração de Código:**\n"
            '• "crie uma função Python para [tarefa]"\n'
            '• "gere código JavaScript para [tarefa]"\n'
            '• "escreve um script para [tarefa]"\n\n'
            "**Explicação:**\n"
            '• "explique este código: [código]"\n'
            '• "o que este código faz?"\n\n'
            "**Code Review:**\n"
            '• "faça code review deste código: [código]"\n\n'
            "**Debugging:**\n"
            '• "como debugar este erro: [erro]"\n'
            '• "ajude a corrigir este bug"\n\n'
            "**Otimização:**\n"
            '• "otimize este código: [código]"\n'
            '• "melhore a performance deste código"'
        )
        return AgentResponse(status=AgentStatus.SUCCESS, response=help_text)

    def get_capabilities(self) -> List[str]:
        return [
            "code_generation",
            "code_explanation",
            "code_review",
            "debugging",
            "optimization",
        ]
