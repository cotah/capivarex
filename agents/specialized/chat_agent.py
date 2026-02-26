"""
Chat Agent - Handles general conversation with Redis cache-aside pattern.

Refactored to use new BaseAgent architecture.
"""

import logging
from typing import Any, Dict, List, Optional

from agents.core import BaseAgent, AgentResponse, AgentStatus, register_agent
from services import get_service
from services.i18n import t, get_user_lang


logger = logging.getLogger(__name__)


@register_agent("chat")
class ChatAgent(BaseAgent):
    """
    Chat agent for general conversation.

    Handles:
    - General questions
    - Casual conversation
    - Knowledge queries
    - Greetings and small talk

    Uses Redis cache-aside pattern for conversation history:
    1. Check Redis cache first
    2. On cache miss, fetch from DB and populate cache
    3. Invalidate cache after new messages are stored
    """

    def __init__(self):
        """Initialise the chat agent."""
        super().__init__(
            name="chat",
            description="Handles general conversation and knowledge queries",
        )

    # ------------------------------------------------------------------
    # Cache-aside helpers
    # ------------------------------------------------------------------

    async def _get_redis(self) -> Optional[Any]:
        """Get Redis service, initializing if needed."""
        try:
            svc = get_service("redis")
            if svc and not svc.is_initialized():
                await svc.initialize()
            return svc
        except Exception as e:
            self.logger.debug(f"Redis not available: {e}")
            return None

    async def _get_history_with_cache(
        self,
        conversation_id: Optional[str],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Get conversation history using cache-aside pattern.

        1. Try Redis cache
        2. On miss, try DB
        3. Populate cache on DB hit
        4. Fall back to context['history']
        """
        # If no conversation_id, use in-memory history from context
        if not conversation_id:
            return context.get("history") or []

        # 1. Try Redis cache
        redis_svc = await self._get_redis()
        if redis_svc:
            try:
                cached = await redis_svc.get_conversation_history(conversation_id)
                if cached is not None:
                    self.logger.info(f"Cache HIT for conversation {conversation_id}")
                    return cached
            except Exception as e:
                self.logger.debug(f"Redis cache read failed: {e}")

        # 2. Cache miss — try DB
        self.logger.info(
            f"Cache MISS for conversation {conversation_id}, fetching from DB"
        )
        db_svc = get_service("database")
        if db_svc:
            try:
                if not db_svc.is_initialized():
                    await db_svc.initialize()
                db_history = await db_svc.get_messages_for_conversation(conversation_id)
                if db_history:
                    # 3. Populate cache
                    if redis_svc:
                        try:
                            await redis_svc.set_conversation_history(
                                conversation_id, db_history
                            )
                        except Exception as e:
                            self.logger.debug(f"Redis cache write failed: {e}")
                    return db_history
            except Exception as e:
                self.logger.warning(f"DB history fetch failed: {e}")

        # 4. Fallback to in-memory context
        return context.get("history") or []

    async def _invalidate_cache(self, conversation_id: Optional[str]) -> None:
        """Invalidate the cache after a new message is stored."""
        if not conversation_id:
            return
        redis_svc = await self._get_redis()
        if redis_svc:
            try:
                await redis_svc.invalidate_conversation_history(conversation_id)
            except Exception as e:
                self.logger.debug(f"Cache invalidation failed: {e}")

    # ------------------------------------------------------------------
    # Main execute
    # ------------------------------------------------------------------

    async def execute(self, prompt: str, context: Dict[str, Any]) -> AgentResponse:
        """
        Process chat request.

        Args:
            prompt: User's message
            context: Execution context with optional conversation history

        Returns:
            AgentResponse with chat reply
        """
        conversation_id = context.get("conversation_id")

        # Get history via cache-aside pattern
        history = await self._get_history_with_cache(conversation_id, context)

        # Build message list
        messages = self._build_messages(prompt, history)

        # Get OpenAI service
        openai_service = get_service("openai")
        if not openai_service:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("error_processing", lang=get_user_lang(context)),
                error="OpenAI service not available",
            )

        await openai_service.initialize()

        # Try streaming first (preferred)
        try:
            chunks: List[str] = []
            async for token in openai_service.stream_chat_completion(messages):
                chunks.append(token)

            response_text = "".join(chunks).strip()

            if response_text and not response_text.startswith("[ERROR:"):
                # Invalidate cache so next request picks up the new message
                await self._invalidate_cache(conversation_id)
                return AgentResponse(
                    status=AgentStatus.SUCCESS,
                    response=response_text,
                    data={"method": "streaming"},
                )
        except Exception as e:
            self.logger.warning(f"Streaming failed, falling back to completion: {e}")

        # Fallback to standard completion
        client = openai_service.get_client()
        if not client:
            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("error_processing", lang=get_user_lang(context)),
                error="OpenAI client not available",
            )

        try:
            completion = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )

            content = (completion.choices[0].message.content or "").strip()

            if not content:
                return AgentResponse(
                    status=AgentStatus.ERROR,
                    response=t("error_processing", lang=get_user_lang(context)),
                    error="Empty response from OpenAI",
                )

            # Invalidate cache after successful response
            await self._invalidate_cache(conversation_id)

            return AgentResponse(
                status=AgentStatus.SUCCESS,
                response=content,
                data={"method": "completion"},
            )

        except Exception as e:
            self.logger.error(f"Chat completion failed: {e}", exc_info=True)

            return AgentResponse(
                status=AgentStatus.ERROR,
                response=t("error_processing", lang=get_user_lang(context)),
                error=str(e),
            )

    def _build_messages(self, prompt: str, history: Any) -> List[Dict[str, str]]:
        """
        Build message list from history.

        Args:
            prompt: Current user prompt
            history: Conversation history list

        Returns:
            List of message dicts
        """
        messages: List[Dict[str, str]] = []

        # Add history if available
        if isinstance(history, list):
            for item in history:
                if not isinstance(item, dict):
                    continue

                role = item.get("role")
                content = item.get("content")

                if role in {"system", "user", "assistant"} and content is not None:
                    messages.append({"role": role, "content": str(content)})

        # Add current prompt
        messages.append({"role": "user", "content": prompt})

        return messages

    def get_capabilities(self) -> List[str]:
        """Get chat agent capabilities."""
        return [
            "conversation",
            "knowledge_queries",
            "general_questions",
            "greetings",
            "small_talk",
        ]
