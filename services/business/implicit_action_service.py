"""
Implicit Action Detection Service — S7 (C07)

Detects implicit actions from voice transcriptions or text messages:
- "Nota que o Pedro disse que o orçamento é 50k" → creates note
- "Lembra-me amanhã de ligar ao banco" → creates reminder
- "Agenda reunião com a Ana sexta às 15h" → creates calendar event
- "Tenho que comprar leite e pão" → creates note/shopping list

Works by analyzing the message BEFORE the orchestrator routes it.
If an implicit action is detected, executes it via the appropriate agent
and returns a humanized confirmation.

If no implicit action is detected, returns None and the message
flows normally to the orchestrator.

All confirmations HUMANIZED via GPT.
"""

import logging
from typing import Any, Dict, Optional

from services.core import get_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword-based fast detection (no API call needed for obvious cases)
# ---------------------------------------------------------------------------

NOTE_KEYWORDS = [
    "nota que", "anota", "note that", "take note", "anote",
    "guarda que", "lembra que", "save that", "write down",
    "aponta que", "regista que", "record that",
]

REMINDER_KEYWORDS = [
    "lembra-me", "lembra me", "remind me", "reminder",
    "não esquecer", "nao esquecer", "don't forget", "dont forget",
    "me avisa", "avisa-me", "alert me", "lembrete",
    "me lembra", "me recorda",
]

CALENDAR_KEYWORDS = [
    "agenda", "agendar", "schedule", "marca reunião", "marca reuniao",
    "book meeting", "create event", "criar evento", "marcar",
    "calendar", "calendário",
]

SHOPPING_KEYWORDS = [
    "comprar", "buy", "shopping list", "lista de compras",
    "preciso de", "need to buy", "tenho que comprar",
    "ir ao supermercado", "grocery",
]


def detect_implicit_action(message: str) -> Optional[str]:
    """
    Fast keyword-based detection of implicit actions.

    Returns: "note", "reminder", "calendar", "shopping", or None
    """
    msg_lower = message.lower().strip()

    # Check reminders FIRST (more specific than notes)
    if any(kw in msg_lower for kw in REMINDER_KEYWORDS):
        return "reminder"

    # Calendar events
    if any(kw in msg_lower for kw in CALENDAR_KEYWORDS):
        return "calendar"

    # Shopping lists (subset of notes)
    if any(kw in msg_lower for kw in SHOPPING_KEYWORDS):
        return "shopping"

    # Notes (most generic — check last)
    if any(kw in msg_lower for kw in NOTE_KEYWORDS):
        return "note"

    return None


# ---------------------------------------------------------------------------
# GPT-based detection for ambiguous cases
# ---------------------------------------------------------------------------

async def detect_implicit_action_gpt(message: str) -> Optional[Dict[str, Any]]:
    """
    Use GPT to detect implicit actions in ambiguous messages.

    Returns dict with:
    - action: "note" | "reminder" | "calendar" | "shopping" | None
    - content: extracted content for the action
    - time: extracted time/date for reminders/calendar (if any)
    - title: suggested title for notes/events

    Returns None if no implicit action detected.
    """
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        # Fall back to keyword detection
        action = detect_implicit_action(message)
        if action:
            return {"action": action, "content": message, "time": "", "title": ""}
        return None

    prompt = f"""Analyze this message and determine if the user is implicitly asking to:
1. CREATE A NOTE (mentioning facts, info to remember, lists)
2. SET A REMINDER (mentioning future tasks with time)
3. CREATE A CALENDAR EVENT (mentioning meetings, appointments with specific time)
4. NONE (just a regular message/question)

Message: "{message}"

Respond with ONLY one JSON object, no markdown:
{{"action": "note|reminder|calendar|none", "content": "the core content to save", "time": "extracted time/date or empty", "title": "short title for the note/event"}}

Examples:
- "O Pedro disse que o orçamento é 50k" → {{"action": "note", "content": "Pedro said budget is 50k", "time": "", "title": "Budget info from Pedro"}}
- "Lembra-me amanhã às 10h de ligar ao banco" → {{"action": "reminder", "content": "Call the bank", "time": "tomorrow 10:00", "title": "Call bank"}}
- "Marca reunião com a Ana sexta às 15h" → {{"action": "calendar", "content": "Meeting with Ana", "time": "Friday 15:00", "title": "Meeting with Ana"}}
- "Que horas são?" → {{"action": "none", "content": "", "time": "", "title": ""}}

JSON:"""

    try:
        import asyncio
        import json

        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-4o-mini",
            max_tokens=200,
            temperature=0.1,  # Low temperature for classification
        )

        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        parsed = json.loads(text)
        if parsed.get("action") and parsed["action"] != "none":
            return parsed
        return None

    except Exception as e:
        logger.warning("Implicit action GPT detection failed: %s", e)
        # Fall back to keyword detection
        action = detect_implicit_action(message)
        if action:
            return {"action": action, "content": message, "time": "", "title": ""}
        return None


# ---------------------------------------------------------------------------
# Action Execution
# ---------------------------------------------------------------------------

async def execute_implicit_action(
    user_id: str,
    action_data: Dict[str, Any],
    user_name: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Execute the detected implicit action and return a humanized confirmation.

    Args:
        user_id: User ID
        action_data: {"action": "note|reminder|calendar|shopping",
                      "content": "...", "time": "...", "title": "..."}
        user_name: User's name for humanized response
        context: Agent context dict

    Returns: Humanized confirmation message, or None if execution failed.
    """

    action = action_data.get("action", "")
    content = action_data.get("content", "")
    title = action_data.get("title", "")
    time_str = action_data.get("time", "")
    name = user_name.split()[0] if user_name else "there"

    ctx = context or {"user_id": user_id}
    ctx["user_id"] = user_id

    try:
        if action == "note" or action == "shopping":
            return await _execute_note(ctx, content, title, name, is_shopping=(action == "shopping"))

        elif action == "reminder":
            return await _execute_reminder(ctx, content, time_str, name)

        elif action == "calendar":
            return await _execute_calendar(ctx, content, time_str, title, name)

    except Exception as e:
        logger.error("Implicit action execution failed: %s", e, exc_info=True)

    return None


async def _execute_note(
    ctx: Dict, content: str, title: str, name: str, is_shopping: bool = False,
) -> Optional[str]:
    """Create a note via notes agent."""
    from agents.core import get_agent

    notes_agent = get_agent("notes")
    if not notes_agent:
        return None

    # Build prompt for notes agent
    if is_shopping:
        prompt = f"create shopping list: {content}"
    else:
        prompt = f"create note titled '{title}': {content}" if title else f"create note: {content}"

    result = await notes_agent.execute(prompt, ctx)

    if result and result.response:
        return await _humanize_confirmation(name, "note", content, title)
    return None


async def _execute_reminder(
    ctx: Dict, content: str, time_str: str, name: str,
) -> Optional[str]:
    """Create a reminder via reminder agent."""
    from agents.core import get_agent

    reminder_agent = get_agent("reminder")
    if not reminder_agent:
        return None

    prompt = f"remind me {time_str}: {content}" if time_str else f"remind me: {content}"
    result = await reminder_agent.execute(prompt, ctx)

    if result and result.response:
        return await _humanize_confirmation(name, "reminder", content, time_str)
    return None


async def _execute_calendar(
    ctx: Dict, content: str, time_str: str, title: str, name: str,
) -> Optional[str]:
    """Create a calendar event via calendar agent."""
    from agents.core import get_agent

    calendar_agent = get_agent("calendar")
    if not calendar_agent:
        return None

    prompt = f"create event: {title or content} at {time_str}" if time_str else f"create event: {content}"
    result = await calendar_agent.execute(prompt, ctx)

    if result and result.response:
        return await _humanize_confirmation(name, "calendar", title or content, time_str)
    return None


# ---------------------------------------------------------------------------
# Humanized Confirmations
# ---------------------------------------------------------------------------

async def _humanize_confirmation(
    name: str, action_type: str, content: str, extra: str = "",
) -> str:
    """Generate warm, human confirmation for the action taken."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        action_desc = {
            "note": "saved a note",
            "reminder": "set a reminder",
            "calendar": "created a calendar event",
            "shopping": "created a shopping list",
        }.get(action_type, "done something")

        prompt = f"""You are CAPIVAREX, a warm personal assistant. Generate a SHORT confirmation (1-2 sentences max) that you {action_desc} for {name}.

Content: {content}
Extra info: {extra or 'none'}

RULES:
- Be warm and brief — max 2 sentences
- Use 1 emoji related to the action (📝 note, ⏰ reminder, 📅 calendar, 🛒 shopping)
- Sound natural: "Done!" or "Got it!" not "I have successfully created..."
- If it's a reminder, mention when
- If it's a note, mention what was saved

Generate the confirmation:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=100,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 5:
                return text
        except Exception:
            pass

    # Fallback confirmations
    if action_type == "note":
        return f"📝 Got it, {name}! Saved: \"{content[:60]}\"."
    elif action_type == "reminder":
        time_part = f" for {extra}" if extra else ""
        return f"⏰ Done, {name}! I'll remind you{time_part}: \"{content[:60]}\"."
    elif action_type == "calendar":
        time_part = f" at {extra}" if extra else ""
        return f"📅 All set, {name}! Event created{time_part}: \"{content[:60]}\"."
    elif action_type == "shopping":
        return f"🛒 Shopping list saved, {name}! \"{content[:60]}\"."
    return f"✅ Done, {name}!"


# ---------------------------------------------------------------------------
# Main Entry Point — call this from chat flow
# ---------------------------------------------------------------------------

async def check_and_execute_implicit_action(
    user_id: str,
    message: str,
    user_name: str = "",
    context: Optional[Dict[str, Any]] = None,
    use_gpt: bool = True,
) -> Optional[str]:
    """
    Main entry point: check message for implicit actions and execute if found.

    Call this BEFORE the normal orchestrator routing.
    If an implicit action is found and executed, returns the confirmation message.
    If no implicit action is found, returns None (message should go to orchestrator).

    Args:
        user_id: User ID
        message: The user's message (voice transcription or text)
        user_name: User's name
        context: Agent context
        use_gpt: Whether to use GPT for ambiguous detection (default True)

    Returns: Confirmation message string, or None if no action detected.
    """
    # Step 1: Fast keyword detection
    fast_action = detect_implicit_action(message)

    if fast_action:
        action_data = {"action": fast_action, "content": message, "time": "", "title": ""}

        # If GPT available, refine the detection (extract content, time, title)
        if use_gpt:
            gpt_data = await detect_implicit_action_gpt(message)
            if gpt_data:
                action_data = gpt_data

        return await execute_implicit_action(
            user_id=user_id,
            action_data=action_data,
            user_name=user_name,
            context=context,
        )

    # Step 2: If keywords didn't match, try GPT for ambiguous cases
    if use_gpt:
        gpt_data = await detect_implicit_action_gpt(message)
        if gpt_data:
            return await execute_implicit_action(
                user_id=user_id,
                action_data=gpt_data,
                user_name=user_name,
                context=context,
            )

    return None  # No implicit action — let orchestrator handle
