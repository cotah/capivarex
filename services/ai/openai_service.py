"""
OpenAI Service - Refactored with BaseService architecture.

Provides:
- Chat completions (streaming and non-streaming)
- Action orchestration
- Automatic retry and error handling
- Metrics tracking
"""

import asyncio
import os
import json
import time
import logging
from typing import Dict, List, Any, AsyncGenerator
from openai import AsyncOpenAI
from dotenv import load_dotenv

from services.core import (
    BaseService,
    register_service,
    retry_on_failure,
    ServiceUnavailableError
)


load_dotenv()

logger = logging.getLogger(__name__)

# System prompt for action orchestration
RESEARCH_SYSTEM_PROMPT = """
Você é um orquestrador de IA de elite. Sua tarefa é analisar a mensagem do usuário e o histórico da conversa para decidir a próxima ação com precisão cirúrgica. Responda APENAS com um objeto JSON válido.

As ações possíveis são:
1.  'chat': Para saudações, conversas gerais, perguntas que não se encaixam em outras categorias ou quando a intenção não for clara.
2.  'search': Para perguntas sobre eventos atuais, notícias, pessoas, lugares ou informações que exijam uma busca na web.
3.  'dev': Para qualquer pedido que envolva criar, explicar, depurar ou modificar código em qualquer linguagem de programação.
4.  'image': Para qualquer pedido que envolva gerar ou criar uma imagem.
5.  'finance': Para perguntas sobre cotações de ações, preços de ativos ou dados do mercado financeiro. Extraia apenas o ticker da ação (ex: "Apple" -> "AAPL", "Petrobras" -> "PETR4.SA").
6.  'weather': Para perguntas sobre o clima ou previsão do tempo.
7.  'calendar': Para perguntas sobre agenda, calendário, compromissos, reuniões, eventos ou horários marcados.
8.  'traffic': Para perguntas sobre tráfego, rotas, tempo de viagem, condições de trânsito entre dois lugares.
9.  'car': Para perguntas sobre veículo elétrico, bateria do carro, carregamento, localização do carro, trancar/destrancar veículo.

### Exemplos de Respostas JSON:

- User: "Olá, tudo bem?"
- {"action": "chat", "response": "Olá! Tudo ótimo por aqui. Como posso te ajudar hoje?"}

- User: "Qual a capital da Mongólia?"
- {"action": "search", "query": "capital da Mongólia"}

- User: "Crie uma função em Python para calcular o fatorial de um número"
- {"action": "dev", "prompt": "Crie uma função em Python para calcular o fatorial de um número, incluindo docstrings e exemplos de uso."}

- User: "gere uma imagem de um gato de óculos escuros"
- {"action": "image", "prompt": "um gato fofo usando óculos escuros, estilo cartoon"}

- User: "quanto está a ação da petrobras?"
- {"action": "finance", "symbol": "PETR4.SA"}

- User: "como está o tempo em salvador amanhã?"
- {"action": "weather", "location": "Salvador, Bahia"}

- User: "o que tenho na minha agenda hoje?"
- {"action": "calendar", "query": "eventos de hoje"}

- User: "crie um compromisso amanhã às 15h"
- {"action": "calendar", "query": "criar evento amanhã 15h"}

- User: "como está o trânsito de Dublin para Cork?"
- {"action": "traffic", "origin": "Dublin", "destination": "Cork"}

- User: "quanto tempo leva para ir ao aeroporto?"
- {"action": "traffic", "query": "tempo de viagem ao aeroporto"}

- User: "qual o nível de bateria do meu carro?"
- {"action": "car", "query": "nível de bateria"}

- User: "tranque meu carro"
- {"action": "car", "query": "trancar veículo"}
"""


@register_service("openai")
class OpenAIService(BaseService):
    """
    OpenAI service for chat completions and action orchestration.

    Features:
    - Streaming and non-streaming chat completions
    - Action decision making
    - Automatic retry on failures
    - Metrics tracking
    """

    def __init__(self, name: str = "openai", config: Dict[str, Any] = None):
        super().__init__(name, config)
        self.client: AsyncOpenAI = None
        self.api_key: str = None

    async def _initialize(self):
        """Initialize OpenAI client."""
        self.api_key = os.environ.get("OPENAI_API_KEY")

        if not self.api_key:
            raise ServiceUnavailableError(
                "OPENAI_API_KEY not found in environment variables"
            )

        self.client = AsyncOpenAI(api_key=self.api_key)
        self.logger.info("OpenAI client initialized successfully")

    async def _health_check(self) -> bool:
        """Check if OpenAI service is healthy."""
        if not self.client:
            return False

        try:
            await asyncio.wait_for(
                self.client.models.list(),
                timeout=5.0
            )
            return True
        except asyncio.TimeoutError:
            self.logger.warning("OpenAI health check timed out")
            return False
        except Exception as e:
            self.logger.error(f"OpenAI health check failed: {e}")
            return False

    @retry_on_failure(max_retries=3, backoff_factor=2.0)
    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2000,
        **kwargs
    ) -> str:
        """
        Get chat completion from OpenAI.

        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            model: Model name
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response
            **kwargs: Additional parameters for OpenAI API

        Returns:
            Response text
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs
            )

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            content = response.choices[0].message.content or ""

            self.logger.debug(
                "Chat completion successful",
                extra={
                    "model": model,
                    "latency_ms": latency * 1000,
                    "tokens": response.usage.total_tokens if response.usage else None
                }
            )

            return content

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.error(
                f"Chat completion failed: {e}",
                exc_info=True
            )
            raise

    async def stream_chat_completion(
        self,
        messages: List[Dict[str, str]],
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 2000
    ) -> AsyncGenerator[str, None]:
        """
        Stream chat completion from OpenAI.

        Args:
            messages: List of message dicts
            model: Model name
            temperature: Sampling temperature
            max_tokens: Maximum tokens in response

        Yields:
            Response tokens
        """
        if not self.client:
            await self.initialize()

        start_time = time.time()

        try:
            stream = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                stream=True,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            async for chunk in stream:
                if chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            self.logger.debug(
                "Streaming completion successful",
                extra={"model": model, "latency_ms": latency * 1000}
            )

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.error(f"Streaming completion failed: {e}", exc_info=True)
            yield f"[ERROR: {str(e)}]"

    @retry_on_failure(max_retries=2, backoff_factor=1.5)
    async def decide_next_action(
        self,
        history: List[Dict[str, str]],
        user_message: str
    ) -> Dict[str, Any]:
        """
        Decide next action based on user message and history.

        Args:
            history: Conversation history
            user_message: Current user message

        Returns:
            Action dict with "action" key and additional parameters
        """
        if not self.client:
            await self.initialize()

        messages = [{"role": "system", "content": RESEARCH_SYSTEM_PROMPT}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})

        start_time = time.time()

        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0.3,
            )

            latency = time.time() - start_time
            self._track_call(latency, error=False)

            decision_str = response.choices[0].message.content
            decision = json.loads(decision_str)

            self.logger.info(
                f"Action decided: {decision.get('action')}",
                extra={"decision": decision, "latency_ms": latency * 1000}
            )

            return decision

        except Exception as e:
            latency = time.time() - start_time
            self._track_call(latency, error=True)

            self.logger.error(f"Action decision failed: {e}", exc_info=True)

            # Safe fallback
            return {
                "action": "chat",
                "response": "Desculpe, ocorreu um erro ao processar sua solicitação."
            }

    def get_client(self) -> AsyncOpenAI:
        """
        Get the underlying OpenAI client.

        Returns:
            AsyncOpenAI client instance
        """
        return self.client


# Convenience functions for backward compatibility
def get_client() -> AsyncOpenAI:
    """Get OpenAI client (backward compatibility)."""
    from services.core import get_service
    service = get_service("openai")
    if service and isinstance(service, OpenAIService):
        if not service.is_initialized():
            import asyncio
            asyncio.create_task(service.initialize())
        return service.get_client()
    return None


async def stream_chat_completion(
    messages: List[Dict[str, str]],
    model: str = "gpt-4o-mini"
) -> AsyncGenerator[str, None]:
    """Stream chat completion (backward compatibility)."""
    from services.core import get_service
    service = get_service("openai")
    if service and isinstance(service, OpenAIService):
        if not service.is_initialized():
            await service.initialize()
        async for token in service.stream_chat_completion(messages, model):
            yield token


async def decide_next_action(
    history: List[Dict[str, str]],
    user_message: str
) -> Dict[str, Any]:
    """Decide next action (backward compatibility)."""
    from services.core import get_service
    service = get_service("openai")
    if service and isinstance(service, OpenAIService):
        if not service.is_initialized():
            await service.initialize()
        return await service.decide_next_action(history, user_message)
    return {"action": "chat", "response": "Service not available"}
