"""
User Profile Service — Persistent memory for CAPIVAREX.

Loads user profile from Supabase and injects it into every system prompt,
so the bot never forgets the user's name or personal info.

Also auto-extracts personal info when the user shares it, saving to DB
for future reference.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from services import get_service
from services.ai.model_config import INTENT_MODEL

logger = logging.getLogger(__name__)


async def build_user_profile_prompt(user_id: str) -> str:
    """
    Load user profile from Supabase, return string to inject into system prompt.

    Args:
        user_id: The user's UUID (primary key in users table).

    Returns:
        A formatted string block to append to the system prompt, or empty
        string if no profile data is available.
    """
    if not user_id:
        return ""

    # Guard: only accept UUIDs, never raw telegram IDs
    import uuid as _uuid
    try:
        _uuid.UUID(str(user_id))
    except (ValueError, AttributeError):
        logger.warning("build_user_profile_prompt: non-UUID user_id=%s, skipping", user_id)
        return ""

    db = get_service("database")
    if not db:
        return ""

    try:
        if not db.is_initialized():
            await db.initialize()
    except Exception as exc:
        logger.warning("Could not initialize database for profile: %s", exc)
        return ""

    parts: list[str] = []

    # 1. Basic info from users table
    try:
        user = await db.get_user_by_id(user_id)
        if user:
            if user.get("full_name"):
                parts.append(f"Name: {user['full_name']}")
            if user.get("preferred_language"):
                parts.append(f"Language: {user['preferred_language']}")
    except Exception as exc:
        logger.warning("Could not load user basic info: %s", exc)

    # 2. Personal info from user_context (context_type = "personal_info")
    try:
        personal = await db.get_user_context(user_id, "personal_info")
        if personal and isinstance(personal, dict):
            for key, value in personal.items():
                if value:
                    parts.append(f"{key}: {value}")
    except Exception as exc:
        logger.warning("Could not load personal_info context: %s", exc)

    if not parts:
        return ""

    return (
        "\n\n## User Profile (ALWAYS remember this — never ask for info already here):\n"
        + "\n".join(f"- {p}" for p in parts)
    )


# ── Trigger keywords (multi-language) ────────────────────────────────────
_TRIGGERS = [
    # ── Existing: Personal info ──
    # English
    "my name",
    "i'm called",
    "i am called",
    "my birthday",
    "i live",
    "my address",
    "my job",
    "i work",
    # Portuguese
    "me chamo",
    "meu nome",
    "meu aniversário",
    "moro em",
    "meu endereço",
    "meu trabalho",
    "trabalho como",
    "trabalho na",
    # Spanish
    "mi nombre",
    "me llamo",
    "mi cumpleaños",
    "vivo en",
    "mi dirección",
    "mi trabajo",
    "trabajo como",
    "trabajo en",
    # ── NEW: Location triggers (PT) ──
    "minha casa e",
    "minha casa fica",
    "meu endereco e",
    "moro na",
    "moro no",
    "moro perto",
    "meu trabalho e",
    "meu trabalho fica",
    "trabalho em",
    "trabalho no",
    "trabalho perto",
    "minha academia e",
    "minha academia fica",
    "minha escola e",
    "minha faculdade e",
    "minha faculdade fica",
    "estudo na",
    "estudo no",
    # ── NEW: Location triggers (EN) ──
    "my home is",
    "i live in",
    "i live at",
    "i live near",
    "my house is",
    "my address is",
    "my work is",
    "i work at",
    "i work in",
    "i work near",
    "my office is",
    "my gym is",
    "my school is",
    "i study at",
    # ── NEW: Location triggers (ES) ──
    "mi casa es",
    "mi casa esta",
    "mi direccion es",
    "mi trabajo es",
    "mi gimnasio es",
    "mi escuela es",
    "estudio en",
]


async def extract_and_save_personal_info(
    user_id: str, user_message: str
) -> None:
    """
    Use a quick GPT call to detect if user shared personal info, save to DB.

    Should be called via ``asyncio.create_task()`` so it doesn't block
    the main response pipeline.

    Args:
        user_id: The user's UUID.
        user_message: The raw message the user sent.
    """
    # Quick keyword gate — skip API call if no trigger words found
    msg_lower = user_message.lower()
    if not any(trigger in msg_lower for trigger in _TRIGGERS):
        return

    # Get OpenAI service
    openai_svc = get_service("openai")
    if not openai_svc:
        return

    try:
        await openai_svc.initialize()
        client = openai_svc.get_client()
        if not client:
            return
    except Exception:
        return

    extraction_prompt = (
        "Extract personal info from this message. "
        "Return ONLY valid JSON, no markdown.\n"
        "If no personal info found, return {}.\n"
        "Possible fields: name, birthday, nickname, city, country, "
        "address, job, interests (as comma-separated string), "
        "home_address, work_address, gym_address, school_address.\n"
        "Only include fields explicitly mentioned.\n"
        "Examples:\n"
        '  "moro em Swords, Dublin" -> '
        '{"city": "Swords", "home_address": "Swords, Dublin"}\n'
        '  "trabalho no city centre" -> '
        '{"work_address": "City Centre, Dublin"}\n'
        '  "minha academia fica no FlyeFit Swords" -> '
        '{"gym_address": "FlyeFit Swords"}\n'
        "\n"
        f'Message: "{user_message}"'
    )

    try:
        response = await client.chat.completions.create(
            model=INTENT_MODEL,
            messages=[
                {"role": "system", "content": extraction_prompt},
            ],
            temperature=0.0,
            max_completion_tokens=150,
        )

        raw = (response.choices[0].message.content or "").strip()
        # Remove markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        extracted: Dict[str, Any] = json.loads(raw)

        if not extracted or not isinstance(extracted, dict):
            return

        # Filter out empty values
        extracted = {k: v for k, v in extracted.items() if v}
        if not extracted:
            return

    except Exception as exc:
        logger.debug("Personal info extraction failed: %s", exc)
        return

    # Merge with existing personal_info context
    db = get_service("database")
    if not db:
        return

    try:
        if not db.is_initialized():
            await db.initialize()

        existing: Optional[Dict[str, Any]] = (
            await db.get_user_context(user_id, "personal_info") or {}
        )
        if not isinstance(existing, dict):
            existing = {}

        existing.update(extracted)
        await db.save_user_context(user_id, "personal_info", existing)
        logger.info(
            "Saved personal info for user %s: %s",
            user_id[:8],
            list(extracted.keys()),
        )

        # Also update full_name in users table if we learned the name
        if extracted.get("name"):
            user = await db.get_user_by_id(user_id)
            if user and not user.get("full_name"):
                await db.update_user_preferences(
                    user_id, {"full_name": extracted["name"]}
                )
                logger.info("Updated full_name for user %s", user_id[:8])

        # Also save location aliases if extracted
        location_fields = {
            "home_address": "home",
            "work_address": "work",
            "gym_address": "gym",
            "school_address": "school",
        }

        for field, key in location_fields.items():
            address = extracted.get(field)
            if address:
                try:
                    from services.business.saved_locations_service import (
                        get_saved_locations_service,
                    )

                    loc_svc = get_saved_locations_service()
                    await loc_svc.save_location(user_id, key, address)
                    logger.info(
                        "Auto-saved location '%s'='%s' for user %s",
                        key,
                        address,
                        user_id[:8],
                    )
                except Exception as loc_exc:
                    logger.debug(
                        "Could not auto-save location: %s", loc_exc
                    )

    except Exception as exc:
        logger.warning("Could not save personal info: %s", exc)
