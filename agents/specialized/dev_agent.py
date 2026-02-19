"""
Dev Agent - Handles code generation, analysis, and programming queries.

Refactored to use intent classification with Anthropic/OpenAI dual-backend
and robust error handling.
"""

import json
import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service


logger = logging.getLogger(__name__)

# Valid intents for dev commands
VALID_INTENTS = {
    "generate_code", "explain_code", "review_code", "debug_code",
    "optimize_code", "help",
}

# System prompts per intent
_SYSTEM_PROMPTS: Dict[str, str] = {
    "generate_code": (
        "You are an expert software developer. Generate clean, "
        "well-documented code with explanations.  Include docstrings, "
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
        """Initialise the dev agent."""
        super().__init__(
            name="dev",
            description="Handles code generation and programming queries",
        )

    # ------------------------------------------------------------------
    # Intent classification
    # ------------------------------------------------------------------

    async def _analyze_intent(self, user_message: str) -> Dict[str, Any]:
        """Classify the developer's request into an intent.

        Returns:
            Dict with ``intent``, ``language``, ``code``, and ``description``.
        """
        openai_svc = get_service("openai")
        if not openai_svc:
            return {"intent": "generate_code"}

        try:
            if not openai_svc.is_initialized():
                await openai_svc.initialize()

            client = openai_svc.get_client()
            if not client:
                return {"intent": "generate_code"}

            system_prompt = (
                "You are an intent classifier for software development commands.\n\n"
                "Analyze the user's message and return a JSON object with:\n"
                '- "intent": one of: generate_code, explain_code, review_code, '
                "debug_code, optimize_code, help\n"
                '- "language": programming language if mentioned, or null\n'
                '- "code": code snippet if provided by the user, or null\n'
                '- "description": what the user wants, or null\n\n'
                "Examples:\n"
                '"crie uma função Python para calcular fibonacci" → '
                '{"intent":"generate_code","language":"python",...}\n'
                '"explique este código: def foo(): pass" → '
                '{"intent":"explain_code","code":"def foo(): pass",...}\n'
                '"faça code review deste código" → {"intent":"review_code",...}\n'
                '"como debugar este erro?" → {"intent":"debug_code",...}\n'
                '"otimize este código" → {"intent":"optimize_code",...}\n\n'
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

            # Strip markdown fences if present
            if result_text.startswith("```"):
                result_text = result_text.split("```")[1]
                if result_text.startswith("json"):
                    result_text = result_text[4:]

            result = json.loads(result_text)

            intent = result.get("intent", "generate_code")
            if intent not in VALID_INTENTS:
                intent = "generate_code"

            return {
                "intent": intent,
                "language": result.get("language"),
                "code": result.get("code"),
                "description": result.get("description"),
            }

        except Exception as e:
            self.logger.warning(f"Intent classification failed, defaulting to generate_code: {e}")
            return {"intent": "generate_code"}

    # ------------------------------------------------------------------
    # AI back-ends
    # ------------------------------------------------------------------

    async def _generate_with_anthropic(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
    ) -> Optional[str]:
        """Try to generate a response using Anthropic (Claude).

        Returns the response text or ``None`` if unavailable / failed.
        """
        try:
            anthropic_svc = get_service("anthropic")
            if not anthropic_svc:
                self.logger.debug("DevAgent: Anthropic service not registered")
                return None

            if not anthropic_svc.is_initialized():
                await anthropic_svc.initialize()

            # Prefer the non-streaming method for simplicity & reliability
            if hasattr(anthropic_svc, "generate_code"):
                self.logger.info("DevAgent: Calling Anthropic generate_code")
                text = await anthropic_svc.generate_code(
                    prompt,
                    system_prompt=system_prompt,
                )
                if text and text.strip():
                    return text.strip()

            # Fallback: streaming
            if hasattr(anthropic_svc, "generate_code_stream"):
                self.logger.info("DevAgent: Calling Anthropic generate_code_stream")
                chunks: List[str] = []
                async for chunk in anthropic_svc.generate_code_stream(
                    prompt,
                    system_prompt=system_prompt,
                ):
                    chunks.append(chunk)
                text = "".join(chunks).strip()
                if text:
                    return text

            self.logger.warning("DevAgent: Anthropic returned empty response")
            return None

        except Exception as e:
            self.logger.warning(f"DevAgent: Anthropic failed: {e}")
            return None

    async def _generate_with_openai(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 4000,
    ) -> Optional[str]:
        """Try to generate a response using OpenAI.

        Returns the response text or ``None`` if unavailable / failed.
        """
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

            text = await openai_svc.chat_completion(
                messages=messages,
                model="gpt-4o-mini",
                temperature=0.3,
                max_tokens=max_tokens,
            )

            text = (text or "").strip()
            return text if text else None

        except Exception as e:
            self.logger.warning(f"DevAgent: OpenAI failed: {e}")
            return None

    async def _call_ai(
        self,
        prompt: str,
        system_prompt: str,
        max_tokens: int = 4000,
    ) -> Optional[str]:
        """Try Anthropic first, then OpenAI.  Returns None if both fail."""
        # Anthropic (custom system prompt forwarded)
        text = await self._generate_with_anthropic(prompt, system_prompt=system_prompt)
        if text:
            return text

        # OpenAI fallback
        text = await self._generate_with_openai(prompt, system_prompt, max_tokens)
        return text

    # ------------------------------------------------------------------
    # Main execute
    # ------------------------------------------------------------------

    async def execute(
        self,
        prompt: str,
        context: Dict[str, Any],
    ) -> AgentResponse:
        """Process a development / programming command.

        Args:
            prompt: User's message.
            context: Execution context.

        Returns:
            AgentResponse with code or explanation.
        """
        dev_prompt = str(context.get("prompt") or prompt).strip()

        if not dev_prompt:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não recebi um prompt de desenvolvimento.",
                error="Empty dev prompt",
            )

        try:
            # Classify intent
            analysis = await self._analyze_intent(dev_prompt)
            intent = analysis["intent"]
            self.logger.info(f"DevAgent: intent={intent}")

            # Dispatch
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
            self.logger.error(f"DevAgent failed: {e}", exc_info=True)
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
        """Handle code generation."""
        system = _SYSTEM_PROMPTS["generate_code"]
        text = await self._call_ai(prompt, system)

        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível gerar código no momento. Serviços de IA indisponíveis.",
                error="No AI response",
            )

        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=text,
            data={"intent": "generate_code", "language": analysis.get("language")},
        )

    async def _handle_explain_code(
        self, prompt: str, analysis: Dict[str, Any]
    ) -> AgentResponse:
        """Handle code explanation."""
        system = _SYSTEM_PROMPTS["explain_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)

        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível explicar o código no momento.",
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
        """Handle code review."""
        system = _SYSTEM_PROMPTS["review_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)

        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível realizar o code review no momento.",
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
        """Handle debugging assistance."""
        system = _SYSTEM_PROMPTS["debug_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)

        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível ajudar com debugging no momento.",
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
        """Handle code optimization."""
        system = _SYSTEM_PROMPTS["optimize_code"]
        text = await self._call_ai(prompt, system, max_tokens=3000)

        if not text:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response="Não foi possível otimizar o código no momento.",
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
        """Show help message."""
        help_text = (
            "💻 **Dev Agent — Comandos Disponíveis**\n\n"
            "**Geração de Código:**\n"
            '• "crie uma função Python para [tarefa]"\n'
            '• "gere código JavaScript para [tarefa]"\n\n'
            "**Explicação:**\n"
            '• "explique este código: [código]"\n'
            '• "o que este código faz?"\n\n'
            "**Code Review:**\n"
            '• "faça code review deste código: [código]"\n'
            '• "revise este arquivo"\n\n'
            "**Debugging:**\n"
            '• "como debugar este erro: [erro]"\n'
            '• "ajude a corrigir este bug"\n\n'
            "**Otimização:**\n"
            '• "otimize este código: [código]"\n'
            '• "melhore a performance deste código"'
        )
        return AgentResponse(
            status=AgentStatus.SUCCESS,
            response=help_text,
        )

    def get_capabilities(self) -> List[str]:
        """Get dev agent capabilities."""
        return [
            "code_generation",
            "code_explanation",
            "code_review",
            "debugging",
            "optimization",
        ]
