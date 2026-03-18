"""
Dev Agent - Handles code generation, analysis, and programming queries.
Refactored to use intent classification with Anthropic Claude (primary)
and OpenAI Codex (fallback) dual-backend with robust error handling.

AI Stack:
  - PRIMARY: Anthropic Claude (claude-sonnet-4.5) — ANTHROPIC_API_KEY
  - FALLBACK: OpenAI Codex (codex-mini-latest) — OPENAI_API_KEY
  - INTENT CLASSIFICATION: OpenAI GPT-4o-mini (fast, cheap)

FIXES [2025-02]:
FIX 1 (TIMEOUT): Anthropic demora 3-4 minutos para código longo.
  ANTES: await anthropic_svc.generate_code(prompt) → sem timeout → Railway mata a conexão HTTP antes de responder.
  DEPOIS: asyncio.wait_for(..., timeout=30) → fallback para OpenAI Codex se >30s.

FIX 2 (HELP FALSO): "Fetch JS" e "cria função Python" retornam help.
  CAUSA: GPT-4o-mini classifica "fetch" como 'help' às vezes.
  DEPOIS: Se a query contém palavras de geração de código (cria, gera, escreve, fetch, function, etc.)
  força intent='generate_code', ignorando o LLM.

FIX 3 (RESPOSTA VAZIA): Se Anthropic e OpenAI falharem, resposta clara ao utilizador em vez de string vazia.

FIX 4 (SEM RESPOSTA NO TELEGRAM): Anthropic 90s + OpenAI 60s = 150s total.
  Telegram connection morre antes da resposta. User não recebe NADA.
  DEPOIS: Global timeout de 45s no execute(). Redução de timeouts individuais.
  Timeout na inicialização dos serviços. Resposta garantida em ≤45s.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services.ai.model_config import INTENT_MODEL
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
    "programa",
    "programe",
    "desenvolve",
    "desenvolva",
    "python",
    "javascript",
    "typescript",
    "java",
    "html",
    "css",
    "react",
    "fastapi",
    "django",
    "flask",
    "node",
    "fibonacci",
    "algoritmo",
    "algorithm",
    "sort",
    "loop",
    "calcular",
    "calculate",
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

# FIX 4: Timeouts reduzidos para garantir resposta rápida
_ANTHROPIC_TIMEOUT_SECONDS = 30
_OPENAI_TIMEOUT_SECONDS = 25
_INIT_TIMEOUT_SECONDS = 10
_GLOBAL_TIMEOUT_SECONDS = 45


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

    FIX 4: Global timeout of 45s ensures the user ALWAYS gets a response,
    even if both AI backends are slow or down.
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
                # FIX 4: Timeout na inicialização
                try:
                    await asyncio.wait_for(
                        openai_svc.initialize(), timeout=_INIT_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    self.logger.warning("DevAgent: OpenAI init timed out for intent")
                    return {
                        "intent": "generate_code",
                        "language": None,
                        "code": None,
                        "description": None,
                    }

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

            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=INTENT_MODEL,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.0,
                    max_completion_tokens=200,
                ),
                timeout=15,  # 15s max para classificação
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

        FIX 1: Timeout de 30s (era 90s).
        FIX 4: Timeout de 10s na inicialização.
        """
        try:
            anthropic_svc = get_service("anthropic")
            if not anthropic_svc:
                self.logger.debug("DevAgent: Anthropic service not registered")
                return None

            if not anthropic_svc.is_initialized():
                # FIX 4: Timeout na inicialização
                try:
                    await asyncio.wait_for(
                        anthropic_svc.initialize(), timeout=_INIT_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "DevAgent: Anthropic init timed out after %ds",
                        _INIT_TIMEOUT_SECONDS,
                    )
                    return None

            # FIX 1: Wrap com timeout reduzido
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
        """Fallback: generate response using OpenAI Codex."""
        try:
            openai_svc = get_service("openai")
            if not openai_svc:
                self.logger.debug("DevAgent: OpenAI service not registered")
                return None

            if not openai_svc.is_initialized():
                # FIX 4: Timeout na inicialização
                try:
                    await asyncio.wait_for(
                        openai_svc.initialize(), timeout=_INIT_TIMEOUT_SECONDS
                    )
                except asyncio.TimeoutError:
                    self.logger.warning(
                        "DevAgent: OpenAI init timed out after %ds",
                        _INIT_TIMEOUT_SECONDS,
                    )
                    return None

            import os

            codex_model = os.getenv("OPENAI_CODEX_MODEL", "codex-mini-latest")

            self.logger.info(
                "DevAgent: Calling OpenAI Codex fallback (model=%s)", codex_model
            )
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ]

            try:
                text = await asyncio.wait_for(
                    openai_svc.chat_completion(
                        messages=messages,
                        model=codex_model,
                        temperature=0.3,
                        max_tokens=max_tokens,
                    ),
                    timeout=_OPENAI_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                self.logger.warning(
                    "DevAgent: OpenAI Codex timed out after %ds",
                    _OPENAI_TIMEOUT_SECONDS,
                )
                return None

            text = (text or "").strip()
            return text if text else None

        except Exception as e:
            self.logger.warning("DevAgent: OpenAI Codex failed: %s", e)
            return None

    async def _call_ai(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 4000,
    ) -> Optional[str]:
        """Try Anthropic Claude first (with timeout), then OpenAI Codex. Returns None if both fail."""
        text = await self._generate_with_anthropic(prompt, system_prompt=system_prompt)
        if text:
            return text
        text = await self._generate_with_openai(prompt, system_prompt, max_tokens)
        return text

    # ------------------------------------------------------------------
    # Main execute — FIX 4: Global timeout wrapper
    # ------------------------------------------------------------------
    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """
        Process a development/programming command.

        FIX 4: Wrapped in global timeout of 45s to guarantee a response
        is always sent back to the user, even if AI backends are slow.
        """
        try:
            return await asyncio.wait_for(
                self._execute_inner(prompt, context),
                timeout=_GLOBAL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            self.logger.error(
                "DevAgent: GLOBAL TIMEOUT after %ds for prompt: %s",
                _GLOBAL_TIMEOUT_SECONDS,
                prompt[:80],
            )
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=(
                    "⚠️ Code request took too long (>45s).\n"
                    "AI services are slow right now.\n"
                    "Please try again in a moment."
                ),
                error=f"Global timeout ({_GLOBAL_TIMEOUT_SECONDS}s)",
            )

    async def _execute_inner(
        self, prompt: str, context: Dict[str, Any]
    ) -> AgentResponse:
        """Internal execute logic (called within global timeout)."""
        dev_prompt = str(context.get("prompt") or prompt).strip()
        if not dev_prompt:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="I didn't receive a development prompt.",
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
                response=f"Error processing development command: {e}",
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
                    "⚠️ Unable to generate code right now.\n"
                    "AI services (Claude and Codex) did not respond in time.\n"
                    "Please try again in a moment."
                ),
                error="No AI response (both Anthropic Claude and OpenAI Codex failed or timed out)",
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
                response="⚠️ Unable to explain the code right now. Please try again.",
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
                response="⚠️ Unable to perform code review right now. Please try again.",
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
                response="⚠️ Unable to help with debugging right now. Please try again.",
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
                response="⚠️ Unable to optimize code right now. Please try again.",
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
            "💻 **Dev Agent — Available Commands**\n\n"
            "**Code Generation:**\n"
            '• "create a Python function for [task]"\n'
            '• "generate JavaScript code for [task]"\n'
            '• "write a script for [task]"\n\n'
            "**Explanation:**\n"
            '• "explain this code: [code]"\n'
            '• "what does this code do?"\n\n'
            "**Code Review:**\n"
            '• "review this code: [code]"\n\n'
            "**Debugging:**\n"
            '• "how to debug this error: [error]"\n'
            '• "help fix this bug"\n\n'
            "**Optimization:**\n"
            '• "optimize this code: [code]"\n'
            '• "improve performance of this code"'
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
