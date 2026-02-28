"""
services/ai/call_brain.py
===========================
GPT-powered brain for AI phone calls.

Responsibilities:
1. Extract call objective from user's Telegram message
2. Generate initial greeting when person answers
3. Generate conversational responses during the call
4. Detect when objective is complete or call should end

Uses GPT-4.1-mini via OpenAI async API (same as rest of project).

Usage:
    from services.ai.call_brain import CallBrain

    brain = CallBrain()

    # Before the call: extract objective
    plan = await brain.extract_call_plan(
        user_prompt="liga pro restaurante e reserva para 2 as 20h",
        user_name="Henrique",
    )

    # During the call: generate responses
    response = await brain.generate_response(session)

    # Check if objective complete
    if response.objective_complete:
        session.mark_objective_complete(response.text)
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# -- Configuration ------------------------------------------------------------

_MODEL = os.getenv("CALL_BRAIN_MODEL", "gpt-4.1-mini")
_MAX_TOKENS = int(os.getenv("CALL_BRAIN_MAX_TOKENS", "200"))
_TEMPERATURE = float(os.getenv("CALL_BRAIN_TEMPERATURE", "0.7"))


# -- Data classes -------------------------------------------------------------


@dataclass
class CallPlan:
    """Extracted from user's Telegram message before making the call."""

    objective: str
    language: str
    greeting: str
    key_details: str
    extra_context: str


@dataclass
class BrainResponse:
    """Response from the Call Brain during a call."""

    text: str
    objective_complete: bool
    should_end_call: bool
    reasoning: str
    latency_s: float


# -- Prompts ------------------------------------------------------------------

_EXTRACT_PLAN_PROMPT = """\
You are an AI assistant that prepares phone calls on behalf of users.

The user sent this message in a chat asking you to make a phone call:
"{user_prompt}"

The user's name is: {user_name}

Extract the following information and respond in JSON only (no markdown, no backticks):
{{
    "objective": "Clear, specific description of what the call should accomplish",
    "language": "Language code for the call: pt, en, or es (detect from the user's message)",
    "greeting": "Natural opening line in the detected language (e.g., 'Boa noite! Estou a ligar em nome de...')",
    "key_details": "Important details: times, dates, number of people, names, addresses, etc.",
    "extra_context": "Any other useful context for the conversation"
}}

Rules:
- The greeting should be natural and polite, like a real person calling
- Include the user's name in the greeting when appropriate
- Detect the language from the user's message (Portuguese -> pt, English -> en, Spanish -> es)
- Be specific about the objective -- include all details the user mentioned
- If the user says "diz que..." or "say that...", the objective is to deliver that message\
"""

_CALL_SYSTEM_PROMPT = """\
You are an AI assistant making a phone call on behalf of {user_name}.

YOUR OBJECTIVE: {objective}

KEY DETAILS: {key_details}
LANGUAGE: Respond in {language_name}. Be natural, polite, conversational.
{extra_context_block}

RULES:
1. Be polite and natural -- sound like a real person, not a robot.
2. Keep responses SHORT -- 1-2 sentences max. This is a phone call, not an essay.
3. Listen carefully and respond appropriately to what the person says.
4. Confirm important details before ending (date, time, name, etc.).
5. If the person asks something you don't know, say so politely.
6. If the person seems confused, briefly explain why you're calling.
7. Never say you're an AI or a bot. You're calling on behalf of {user_name}.
8. Be respectful of the person's time.

SPECIAL TAGS (add at the END of your response when appropriate):
- [OBJECTIVE_COMPLETE] -- when the objective has been fulfilled \
(reservation confirmed, message delivered, info obtained, etc.)
- [END_CALL] -- when the call should end \
(after goodbye, if objective failed, if person is unresponsive)
- [OBJECTIVE_FAILED] -- when it's clear the objective cannot be fulfilled \
(restaurant full, service unavailable, etc.)

You can combine tags, e.g.: "Muito obrigado, boa noite! [OBJECTIVE_COMPLETE][END_CALL]"

Only add tags when truly appropriate. Don't rush to end the call.\
"""

_LANGUAGE_NAMES = {
    "pt": "Portuguese",
    "en": "English",
    "es": "Spanish",
}

_GOODBYE_PROMPT = """\
The phone call is ending. Generate a brief, polite goodbye in {language_name}.
Context: {result_context}
Keep it to ONE short sentence. Be warm and natural.\
"""


# -- CallBrain class ----------------------------------------------------------


class CallBrain:
    """
    GPT-powered brain for conducting AI phone calls.

    Stateless -- all state lives in CallSession.
    This class just generates text responses given conversation context.
    """

    def __init__(self) -> None:
        self._client: Optional[AsyncOpenAI] = None

    def _get_client(self) -> AsyncOpenAI:
        """Lazy-initialize OpenAI client."""
        if self._client is None:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY not set")
            self._client = AsyncOpenAI(api_key=api_key)
        return self._client

    # -- Pre-call: Extract plan -----------------------------------------------

    async def extract_call_plan(
        self,
        user_prompt: str,
        user_name: str,
    ) -> CallPlan:
        """
        Extract call objective and plan from user's Telegram message.

        Called by TwilioAgent BEFORE making the call.

        Args:
            user_prompt: What the user said in Telegram
            user_name: User's name

        Returns:
            CallPlan with objective, language, greeting, and key details
        """
        start = time.time()
        client = self._get_client()

        prompt = _EXTRACT_PLAN_PROMPT.format(
            user_prompt=user_prompt,
            user_name=user_name,
        )

        try:
            response = await client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=300,
                temperature=0.3,
            )

            raw = response.choices[0].message.content.strip()
            latency = time.time() - start
            logger.info("CallBrain.extract_call_plan: %.2fs", latency)

            # Parse JSON response — clean potential markdown code fences
            cleaned = (
                raw.replace("```json", "").replace("```", "").strip()
            )
            data = json.loads(cleaned)

            return CallPlan(
                objective=data.get("objective", user_prompt),
                language=data.get("language", "en"),
                greeting=data.get("greeting", ""),
                key_details=data.get("key_details", ""),
                extra_context=data.get("extra_context", ""),
            )

        except json.JSONDecodeError as e:
            logger.warning(
                "CallBrain: failed to parse plan JSON: %s — raw: %s",
                e,
                raw[:200],
            )
            return CallPlan(
                objective=user_prompt,
                language=_detect_language_simple(user_prompt),
                greeting="",
                key_details="",
                extra_context="",
            )
        except Exception as e:
            logger.error(
                "CallBrain.extract_call_plan failed: %s",
                e,
                exc_info=True,
            )
            return CallPlan(
                objective=user_prompt,
                language=_detect_language_simple(user_prompt),
                greeting="",
                key_details="",
                extra_context="",
            )

    # -- During call: Generate response ---------------------------------------

    async def generate_response(
        self,
        objective: str,
        user_name: str,
        language: str,
        key_details: str,
        extra_context: str,
        conversation_history: List[Dict[str, str]],
        latest_speech: str,
    ) -> BrainResponse:
        """
        Generate the bot's response to what the person just said.

        Called each time the person finishes speaking (after STT).

        Args:
            objective: What the call should accomplish
            user_name: Who the bot is calling for
            language: Language code (pt, en, es)
            key_details: Important details for the call
            extra_context: Additional context
            conversation_history: Previous turns [{role, content}, ...]
            latest_speech: What the person just said (from STT)

        Returns:
            BrainResponse with text, tags, and latency
        """
        start = time.time()
        client = self._get_client()

        language_name = _LANGUAGE_NAMES.get(language, "English")

        extra_block = ""
        if extra_context:
            extra_block = f"\nADDITIONAL CONTEXT: {extra_context}"

        system_prompt = _CALL_SYSTEM_PROMPT.format(
            user_name=user_name,
            objective=objective,
            key_details=key_details or "None provided",
            language_name=language_name,
            extra_context_block=extra_block,
        )

        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        messages.extend(conversation_history)
        messages.append({"role": "user", "content": latest_speech})

        try:
            response = await client.chat.completions.create(
                model=_MODEL,
                messages=messages,
                max_completion_tokens=_MAX_TOKENS,
                temperature=_TEMPERATURE,
            )

            raw_text = response.choices[0].message.content.strip()
            latency = time.time() - start

            # Parse tags
            objective_complete = "[OBJECTIVE_COMPLETE]" in raw_text
            objective_failed = "[OBJECTIVE_FAILED]" in raw_text
            should_end = "[END_CALL]" in raw_text

            # Remove tags from spoken text
            clean_text = raw_text
            for tag in (
                "[OBJECTIVE_COMPLETE]",
                "[OBJECTIVE_FAILED]",
                "[END_CALL]",
            ):
                clean_text = clean_text.replace(tag, "")
            clean_text = clean_text.strip()

            # If objective failed, mark should_end too
            if objective_failed:
                should_end = True

            logger.info(
                "CallBrain.generate_response: %.2fs | complete=%s "
                "end=%s | %s",
                latency,
                objective_complete,
                should_end,
                clean_text[:80],
            )

            return BrainResponse(
                text=clean_text,
                objective_complete=objective_complete,
                should_end_call=should_end,
                reasoning=(
                    f"tags: complete={objective_complete}, "
                    f"failed={objective_failed}, end={should_end}"
                ),
                latency_s=latency,
            )

        except Exception as e:
            latency = time.time() - start
            logger.error(
                "CallBrain.generate_response failed: %s",
                e,
                exc_info=True,
            )
            fallback_text = _FALLBACK_RESPONSES.get(
                language, _FALLBACK_RESPONSES["en"]
            )
            return BrainResponse(
                text=fallback_text,
                objective_complete=False,
                should_end_call=False,
                reasoning=f"GPT error: {e}",
                latency_s=latency,
            )

    # -- Convenience: Generate from CallSession -------------------------------

    async def respond_to_session(self, session: Any) -> BrainResponse:
        """
        Convenience method: generate response using CallSession state.

        Args:
            session: CallSession instance (from call_session.py)

        Returns:
            BrainResponse
        """
        return await self.generate_response(
            objective=session.objective,
            user_name=session.user_name,
            language=session.language,
            key_details=getattr(session, "extra_context", ""),
            extra_context="",
            conversation_history=session.get_conversation_history(),
            latest_speech=session.get_last_user_message(),
        )

    # -- Generate greeting ----------------------------------------------------

    async def generate_greeting(
        self,
        objective: str,
        user_name: str,
        language: str,
        key_details: str = "",
        custom_greeting: str = "",
    ) -> BrainResponse:
        """
        Generate the opening line when the person answers the phone.

        If a custom greeting was extracted in the plan, uses that directly.
        Otherwise asks GPT to generate one.

        Args:
            objective: What the call should accomplish
            user_name: Who's calling
            language: Language code
            key_details: Key details about the call
            custom_greeting: Pre-extracted greeting (from CallPlan)

        Returns:
            BrainResponse with the greeting text
        """
        if custom_greeting:
            return BrainResponse(
                text=custom_greeting,
                objective_complete=False,
                should_end_call=False,
                reasoning="Using pre-extracted greeting",
                latency_s=0.0,
            )

        start = time.time()
        client = self._get_client()

        language_name = _LANGUAGE_NAMES.get(language, "English")

        prompt = (
            f"Generate a brief, natural phone greeting in "
            f"{language_name}.\n"
            f"You're calling on behalf of {user_name}.\n"
            f"Purpose: {objective}\n"
            f"Details: {key_details or 'None'}\n\n"
            f"Rules:\n"
            f"- ONE or TWO sentences max\n"
            f"- Natural and polite\n"
            f"- Include the user's name\n"
            f"- State why you're calling\n"
            f"- Don't say you're an AI"
        )

        try:
            response = await client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=100,
                temperature=0.7,
            )

            text = response.choices[0].message.content.strip()
            latency = time.time() - start

            logger.info(
                "CallBrain.generate_greeting: %.2fs | %s",
                latency,
                text[:80],
            )

            return BrainResponse(
                text=text,
                objective_complete=False,
                should_end_call=False,
                reasoning="Generated greeting",
                latency_s=latency,
            )

        except Exception as e:
            logger.error(
                "CallBrain.generate_greeting failed: %s", e
            )
            fallback = _GREETING_FALLBACKS.get(
                language, _GREETING_FALLBACKS["en"]
            ).format(user_name=user_name)
            return BrainResponse(
                text=fallback,
                objective_complete=False,
                should_end_call=False,
                reasoning=f"Fallback greeting: {e}",
                latency_s=0.0,
            )

    # -- Generate goodbye -----------------------------------------------------

    async def generate_goodbye(
        self,
        language: str,
        result: str = "success",
        result_details: str = "",
    ) -> BrainResponse:
        """
        Generate a goodbye message when the call is ending.

        Args:
            language: Language code
            result: Call result (success, failed, timeout)
            result_details: Details about the result

        Returns:
            BrainResponse with goodbye text
        """
        start = time.time()
        client = self._get_client()

        language_name = _LANGUAGE_NAMES.get(language, "English")
        context = (
            f"Result: {result}. {result_details}"
            if result_details
            else f"Result: {result}"
        )

        prompt = _GOODBYE_PROMPT.format(
            language_name=language_name,
            result_context=context,
        )

        try:
            response = await client.chat.completions.create(
                model=_MODEL,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=60,
                temperature=0.7,
            )

            text = response.choices[0].message.content.strip()
            latency = time.time() - start

            return BrainResponse(
                text=text,
                objective_complete=False,
                should_end_call=True,
                reasoning="Generated goodbye",
                latency_s=latency,
            )

        except Exception as e:
            logger.error(
                "CallBrain.generate_goodbye failed: %s", e
            )
            fallback = _GOODBYE_FALLBACKS.get(
                language, _GOODBYE_FALLBACKS["en"]
            )
            return BrainResponse(
                text=fallback,
                objective_complete=False,
                should_end_call=True,
                reasoning=f"Fallback goodbye: {e}",
                latency_s=0.0,
            )


# -- Fallbacks ----------------------------------------------------------------

_FALLBACK_RESPONSES = {
    "pt": "Desculpe, pode repetir por favor?",
    "en": "Sorry, could you repeat that please?",
    "es": "Disculpe, \u00bfpuede repetir por favor?",
}

_GREETING_FALLBACKS = {
    "pt": "Boa noite! Estou a ligar em nome de {user_name}.",
    "en": "Hello! I'm calling on behalf of {user_name}.",
    "es": "\u00a1Buenas noches! Llamo en nombre de {user_name}.",
}

_GOODBYE_FALLBACKS = {
    "pt": "Muito obrigado! Boa noite.",
    "en": "Thank you very much! Goodbye.",
    "es": "\u00a1Muchas gracias! Buenas noches.",
}


# -- Helpers ------------------------------------------------------------------


def _detect_language_simple(text: str) -> str:
    """Simple language detection by keyword presence."""
    lower = text.lower()

    pt_indicators = [
        "liga", "ligar", "chama", "reserva", "diz que", "faz",
        "pra", "pro", "restaurante", "por favor", "obrigado",
        "boa noite", "pessoas",
    ]
    es_indicators = [
        "llama", "reserva", "dice que", "personas", "por favor",
        "gracias", "buenas noches", "restaurante",
    ]

    pt_score = sum(1 for kw in pt_indicators if kw in lower)
    es_score = sum(1 for kw in es_indicators if kw in lower)

    if pt_score > es_score and pt_score > 0:
        return "pt"
    if es_score > pt_score and es_score > 0:
        return "es"
    return "en"
