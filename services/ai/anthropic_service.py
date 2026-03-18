"""
Anthropic Service - Refactored with BaseService architecture.

Provides:
- Code generation via Claude with streaming
- Automatic retry and error handling
- Metrics tracking
"""

import os
import logging
import time
from typing import AsyncGenerator, Dict, Any, Optional

import anthropic
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError,
)

load_dotenv()

logger = logging.getLogger(__name__)

DEV_SYSTEM_PROMPT = """
Voce e um desenvolvedor de software expert. Sua tarefa e gerar codigo limpo, eficiente e bem documentado com base no prompt do usuario.
Sempre envolva o codigo em blocos de Markdown (ex: ```python ... ```).
Adicione comentarios ao codigo para explicar partes complexas.
Se a linguagem nao for especificada, use Python por padrao.
"""


@register_service("anthropic")
class AnthropicService(BaseService):
    """
    Anthropic service for code generation via Claude.

    Features:
    - Streaming code generation
    - Automatic retry on failures
    - Metrics tracking
    """

    def __init__(
        self, name: str = "anthropic", config: Optional[Dict[str, Any]] = None
    ):
        """Initialise the Anthropic service."""
        super().__init__(name, config)
        self.client: Optional[anthropic.AsyncAnthropic] = None
        self.api_key: Optional[str] = None

    async def _initialize(self) -> None:
        """Initialize Anthropic client."""
        self.api_key = os.environ.get("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ServiceUnavailableError(
                "ANTHROPIC_API_KEY not found in environment variables"
            )

        self.client = anthropic.AsyncAnthropic(api_key=self.api_key)
        self.logger.info("Anthropic client initialized successfully")

    async def _health_check(self) -> bool:
        """Check if Anthropic service is healthy."""
        return self.client is not None and self.api_key is not None

    async def generate_code_stream(
        self,
        prompt: str,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 2048,
        system_prompt: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Generate code using Anthropic API with streaming.

        Args:
            prompt: User prompt for code generation
            model: Model name to use
            max_tokens: Maximum tokens in response
            system_prompt: Optional custom system prompt

        Yields:
            Generated code tokens
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()
        system = system_prompt or DEV_SYSTEM_PROMPT

        try:
            async with self.client.messages.stream(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                async for text in stream.text_stream:
                    yield text

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            self.logger.debug(
                "Code generation stream completed",
                extra={"model": model, "latency_ms": latency * 1000},
            )

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.error(f"Code generation failed: {e}", exc_info=True)
            yield f"\n\nErro ao gerar codigo: {e}"

    @retry_on_failure(max_retries=2, backoff_factor=2.0)
    async def generate_code(
        self,
        prompt: str,
        model: str = "claude-sonnet-4-5-20250929",
        max_tokens: int = 2048,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        Generate code using Anthropic API (non-streaming).

        Args:
            prompt: User prompt for code generation
            model: Model name to use
            max_tokens: Maximum tokens in response
            system_prompt: Optional custom system prompt

        Returns:
            Generated code text
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()
        system = system_prompt or DEV_SYSTEM_PROMPT

        try:
            response = await self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
            )

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            content = response.content[0].text if response.content else ""

            self.logger.debug(
                "Code generation completed",
                extra={"model": model, "latency_ms": latency * 1000},
            )

            return content

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.error(f"Code generation failed: {e}", exc_info=True)
            raise

    def get_client(self) -> Optional[anthropic.AsyncAnthropic]:
        """
        Get the underlying Anthropic client.

        Returns:
            AsyncAnthropic client instance
        """
        return self.client


# Singleton getter
_anthropic_service: Optional[AnthropicService] = None


def get_anthropic_service() -> AnthropicService:
    """Get global anthropic service instance."""
    global _anthropic_service
    if _anthropic_service is None:
        from services.core import get_service

        _anthropic_service = get_service("anthropic")
    return _anthropic_service


# Backward compatibility
async def generate_code_stream(prompt: str) -> AsyncGenerator[str, None]:
    """Generate code stream (backward compatibility)."""
    from services.core import get_service

    service = get_service("anthropic")
    if service and isinstance(service, AnthropicService):
        if not service.is_initialized():
            await service.initialize()
        async for token in service.generate_code_stream(prompt):
            yield token
