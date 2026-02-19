"""
Prompt Cleaner Service (Refactored) - CapivaraX Bot.

Preprocesses and cleans user prompts before sending to specialized agents.
Fully standalone implementation that extends BaseService and uses the
service registry decorator. Does NOT import from services/.

Features:
- Agent-specific prompt cleaning (chat, search, dev, weather, finance, etc.)
- OpenAI-powered entity extraction (locations, stock symbols, event params)
- Prefix stripping for natural language commands (PT-BR and EN)
- Graceful fallback when OpenAI client is unavailable
"""

import json
import os
import re
import time
from datetime import datetime
from typing import Any, Callable, Coroutine, Dict, List, Optional

from openai import AsyncOpenAI

from services.core import BaseService, register_service


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------
CleanerFunc = Callable[
    [str, Dict[str, Any]],
    Coroutine[Any, Any, Dict[str, Any]],
]


@register_service("prompt_cleaner")
class PromptCleanerService(BaseService):
    """
    Cleans and preprocesses user prompts for specialised agents.

    Extends :class:`BaseService` to provide standardised initialisation,
    health-checking, metrics tracking, and logging.  All OpenAI calls use
    the service's own :pyattr:`_openai_client` that is created during
    initialisation from the ``OPENAI_API_KEY`` environment variable.
    """

    # Default model for lightweight extraction tasks
    _EXTRACTION_MODEL: str = "gpt-4o-mini"

    def __init__(
        self,
        name: str = "prompt_cleaner",
        config: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Initialise the prompt cleaner service."""
        super().__init__(name, config)
        self._openai_client: Optional[AsyncOpenAI] = None

        # Map normalised agent type -> cleaner coroutine
        self._cleaners: Dict[str, CleanerFunc] = {
            "chat": self._clean_chat,
            "search": self._clean_research,
            "research": self._clean_research,
            "dev": self._clean_dev,
            "weather": self._clean_weather,
            "finance": self._clean_finance,
            "image": self._clean_image,
            "video": self._clean_video,
            "voice": self._clean_voice,
            "calendar": self._clean_calendar,
            "traffic": self._clean_traffic,
            "car": self._clean_car,
        }

    # ------------------------------------------------------------------
    # BaseService abstract methods
    # ------------------------------------------------------------------

    async def _initialize(self) -> None:
        """Create the OpenAI async client from environment variables."""
        api_key = self._get_config("openai_api_key") or os.environ.get(
            "OPENAI_API_KEY"
        )
        if api_key:
            self._openai_client = AsyncOpenAI(api_key=api_key)
            self.logger.info("OpenAI client created for prompt_cleaner")
        else:
            self.logger.warning(
                "OPENAI_API_KEY not set -- LLM-based extraction will be disabled"
            )

    async def _health_check(self) -> bool:
        """
        Return ``True`` when the service can operate.

        The service is still *functional* without an OpenAI key (it falls
        back to defaults), so we report healthy as long as initialisation
        completed.
        """
        return self._initialized

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def clean_for_agent(
        self,
        agent_type: str,
        user_message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Clean and preprocess a prompt for a specific agent type.

        Args:
            agent_type: Type of agent (chat, search, dev, weather, finance, ...).
            user_message: Raw user message.
            context: Optional context dict (history, user_plan, etc.).

        Returns:
            Dict with at least a ``"prompt"`` key plus agent-specific params.
        """
        start = time.monotonic()
        error_occurred = False

        context = context or {}
        message = (user_message or "").strip()
        normalised_agent = (agent_type or "").strip().lower()

        try:
            cleaner_func = self._cleaners.get(normalised_agent, self._clean_default)
            cleaned: Dict[str, Any] = await cleaner_func(message, context)

            if "prompt" not in cleaned:
                cleaned["prompt"] = message

            return cleaned

        except Exception as exc:
            error_occurred = True
            self.logger.error(
                "Prompt cleaning failed for agent '%s': %s",
                normalised_agent,
                exc,
                exc_info=True,
            )
            # Graceful fallback -- always return something usable
            return {"prompt": message, "action": normalised_agent or "chat"}

        finally:
            latency = time.monotonic() - start
            self._track_call(latency, error=error_occurred)

    # ------------------------------------------------------------------
    # Agent-specific cleaners
    # ------------------------------------------------------------------

    async def _clean_chat(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for ChatAgent."""
        return {"prompt": user_message, "action": "chat"}

    async def _clean_research(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for ResearchAgent."""
        query = self._strip_prefix(
            user_message,
            [
                "pesquise sobre",
                "pesquise",
                "busque",
                "procure",
                "search for",
                "search",
                "find",
                "look up",
                "buscar",
                "encontre",
                "me diga sobre",
                "tell me about",
            ],
        )
        return {"prompt": query, "action": "search", "query": query}

    async def _clean_dev(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for DevAgent."""
        return {"prompt": user_message, "action": "dev"}

    async def _clean_weather(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for WeatherAgent."""
        location = await self._extract_location(user_message)
        return {
            "prompt": user_message,
            "action": "weather",
            "location": location or "Dublin",
        }

    async def _clean_finance(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for FinanceAgent."""
        symbol = await self._extract_stock_symbol(user_message)
        return {
            "prompt": user_message,
            "action": "finance",
            "symbol": symbol or "AAPL",
        }

    async def _clean_image(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for ImageAgent."""
        description = self._strip_prefix(
            user_message,
            [
                "gere uma imagem de",
                "gere uma imagem",
                "crie uma imagem de",
                "crie uma imagem",
                "desenhe",
                "ilustre",
                "generate an image of",
                "generate an image",
                "create an image of",
                "create an image",
                "draw",
                "illustrate",
            ],
        )
        return {"prompt": description, "action": "image", "description": description}

    async def _clean_video(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for VideoAgent."""
        description = self._strip_prefix(
            user_message,
            [
                "gere um video de",
                "gere um video",
                "crie um video de",
                "crie um video",
                "filme",
                "generate a video of",
                "generate a video",
                "create a video of",
                "create a video",
                "film",
            ],
        )
        return {"prompt": description, "action": "video", "description": description}

    async def _clean_voice(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for VoiceAgent."""
        text = self._strip_prefix(
            user_message,
            [
                "gere um audio dizendo",
                "gere um audio",
                "fale",
                "narre",
                "leia em voz alta",
                "generate audio saying",
                "generate audio",
                "speak",
                "narrate",
                "read aloud",
                "diga",
                "say",
            ],
        )
        return {
            "prompt": text,
            "action": "text_to_speech",
            "text": text,
            "voice": "rachel",
        }

    async def _clean_calendar(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Clean prompt for CalendarAgent and extract event parameters via LLM.

        If the user message contains creation keywords, the service uses
        the OpenAI client to extract structured event parameters (title,
        start/end datetimes, location, description).
        """
        self.logger.debug(
            "Cleaning calendar query",
            extra={"query": user_message, "user_id": context.get("user_id")},
        )

        create_keywords: List[str] = [
            "criar",
            "create",
            "agendar",
            "schedule",
            "marcar",
            "mark",
            "adicionar",
            "add",
        ]
        is_create_query = any(kw in user_message.lower() for kw in create_keywords)

        if not is_create_query:
            return {"prompt": user_message, "action": "calendar"}

        self.logger.info(
            "Detected event creation query", extra={"query": user_message}
        )

        # Use LLM to extract event parameters
        try:
            if not self._openai_client:
                return {
                    "prompt": user_message,
                    "action": "calendar",
                    "error": "OpenAI client unavailable",
                }

            system_prompt = (
                "You are an event parameter extractor. Extract structured event "
                "information from user messages.\n\n"
                "Return a JSON object with these fields:\n"
                '- "title": Event title/summary (required)\n'
                '- "start_datetime": Start date and time in ISO format '
                "YYYY-MM-DDTHH:MM:SS (required)\n"
                '- "end_datetime": End date and time in ISO format '
                "YYYY-MM-DDTHH:MM:SS (optional, default: start + 1 hour)\n"
                '- "location": Event location (optional)\n'
                '- "description": Event description (optional)\n\n'
                "Current date and time: {current_datetime}\n\n"
                "Rules:\n"
                "1. If only date is mentioned, use 09:00 as default time\n"
                "2. If only time is mentioned, use today's date\n"
                '3. "amanha" = tomorrow, "hoje" = today, "segunda" = next Monday, etc.\n'
                "4. If end time not specified, set end_datetime = start_datetime + 1 hour\n"
                "5. Return ONLY valid JSON, no explanations\n\n"
                'Example input: "Crie reuniao amanha as 15h em Cork"\n'
                "Example output: "
                '{{"title": "Reuniao", "start_datetime": "2026-02-15T15:00:00", '
                '"end_datetime": "2026-02-15T16:00:00", "location": "Cork", '
                '"description": ""}}'
            )

            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            system_prompt = system_prompt.format(current_datetime=current_datetime)

            response = await self._openai_client.chat.completions.create(
                model=self._EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                temperature=0.1,
                response_format={"type": "json_object"},
            )

            extracted: Dict[str, Any] = json.loads(
                response.choices[0].message.content or "{}"
            )

            self.logger.info(
                "Extracted event parameters",
                extra={
                    "title": extracted.get("title"),
                    "start_datetime": extracted.get("start_datetime"),
                    "location": extracted.get("location"),
                },
            )

            return {
                "prompt": user_message,
                "action": "create_event",
                "event_params": extracted,
            }

        except Exception as exc:
            self.logger.error(
                "Failed to extract event parameters",
                extra={"error": str(exc), "query": user_message},
                exc_info=True,
            )
            # Fallback: return as regular calendar query
            return {
                "prompt": user_message,
                "action": "calendar",
                "error": str(exc),
            }

    async def _clean_traffic(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for TrafficAgent."""
        locations = await self._extract_traffic_locations(user_message)
        return {
            "prompt": user_message,
            "action": "traffic",
            "origin": locations.get("origin", "Dublin"),
            "destination": locations.get("destination", "Cork"),
        }

    async def _clean_car(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Clean prompt for CarAgent."""
        return {"prompt": user_message, "action": "car"}

    async def _clean_default(
        self, user_message: str, context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Default cleaner for unknown agent types."""
        return {"prompt": user_message, "action": "chat"}

    # ------------------------------------------------------------------
    # LLM-powered extraction helpers
    # ------------------------------------------------------------------

    async def _extract_location(self, user_message: str) -> Optional[str]:
        """Extract a location name from *user_message* using GPT."""
        try:
            if not self._openai_client:
                return None

            system_prompt = (
                "You are a location extractor. Extract the location name from "
                "the user's message. Return only the location name. "
                "If no location is found, return Dublin."
            )

            response = await self._openai_client.chat.completions.create(
                model=self._EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=20,
                temperature=0.0,
            )

            location = (response.choices[0].message.content or "").strip()
            location = re.sub(r"\s+", " ", location).strip().strip(".")
            if not location:
                return None
            return location[:80]

        except Exception as exc:
            self.logger.error("Failed to extract location: %s", exc)
            return None

    async def _extract_stock_symbol(self, user_message: str) -> Optional[str]:
        """Extract a stock ticker symbol from *user_message* using GPT."""
        try:
            if not self._openai_client:
                return None

            system_prompt = (
                "You are a stock symbol extractor. Extract the ticker symbol "
                "from the user's message. Return only one ticker in uppercase "
                "(e.g., AAPL, TSLA, PETR4.SA). If no symbol is found, return AAPL."
            )

            response = await self._openai_client.chat.completions.create(
                model=self._EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=10,
                temperature=0.0,
            )

            symbol = (response.choices[0].message.content or "").strip().upper()
            symbol = symbol.split()[0] if symbol else ""
            symbol = re.sub(r"[^A-Z0-9.\-]", "", symbol)
            if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", symbol):
                return None
            return symbol

        except Exception as exc:
            self.logger.error("Failed to extract stock symbol: %s", exc)
            return None

    async def _extract_traffic_locations(
        self, user_message: str
    ) -> Dict[str, str]:
        """Extract origin and destination from *user_message* using GPT."""
        default_locations: Dict[str, str] = {
            "origin": "Dublin",
            "destination": "Cork",
        }

        try:
            if not self._openai_client:
                return default_locations

            system_prompt = (
                "You extract traffic route locations from user text. "
                "Return only in the format origin|destination. "
                "If only one location exists, use Dublin as the missing endpoint."
            )

            response = await self._openai_client.chat.completions.create(
                model=self._EXTRACTION_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
                max_tokens=30,
                temperature=0.0,
            )

            result = (response.choices[0].message.content or "").strip()
            parts = [part.strip() for part in result.split("|", maxsplit=1)]

            if len(parts) != 2 or not parts[0] or not parts[1]:
                return default_locations

            origin = re.sub(r"\s+", " ", parts[0]).strip()[:80]
            destination = re.sub(r"\s+", " ", parts[1]).strip()[:80]

            if not origin or not destination:
                return default_locations

            return {"origin": origin, "destination": destination}

        except Exception as exc:
            self.logger.error("Failed to extract traffic locations: %s", exc)
            return default_locations

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _strip_prefix(text: str, prefixes: List[str]) -> str:
        """Remove common command-style prefixes from a user message."""
        cleaned = (text or "").strip()
        lowered = cleaned.casefold()

        for prefix in prefixes:
            candidate = prefix.strip().casefold()
            if lowered.startswith(candidate):
                cleaned = cleaned[len(prefix) :].strip(" \t\n\r:,-")
                break

        return cleaned or text.strip()


# Backward-compatible alias
PromptCleaner = PromptCleanerService
