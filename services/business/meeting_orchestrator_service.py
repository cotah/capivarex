"""
Meeting Orchestrator Service — S9 (C04)

User says "marca reunião com o João sobre projecto X sexta às 15h" → bot does everything:
1. Checks calendar availability
2. Creates event with Google Meet link
3. Sends invite email to attendees
4. Creates meeting prep notes with agenda
5. Returns humanized confirmation

All output HUMANIZED via GPT — sounds like a capable PA.
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from services.core import get_service

logger = logging.getLogger(__name__)


async def orchestrate_meeting(
    user_id: str,
    title: str,
    attendees: List[str],
    start_time: datetime,
    end_time: Optional[datetime] = None,
    description: str = "",
    user_name: str = "",
    user_email: str = "",
    create_notes: bool = True,
    send_invite: bool = True,
) -> Dict[str, Any]:
    """
    Full meeting orchestration: check availability → create event → send invite → create notes.

    Args:
        user_id: User ID
        title: Meeting title
        attendees: List of attendee email addresses
        start_time: Meeting start datetime
        end_time: Meeting end datetime (defaults to start + 1h)
        description: Meeting description/agenda
        user_name: User's name for emails and notes
        user_email: User's email for calendar
        create_notes: Whether to create prep notes
        send_invite: Whether to send email invites

    Returns: Result dict with status, event details, and humanized confirmation.
    """
    name = user_name.split()[0] if user_name else "there"
    if not end_time:
        end_time = start_time + timedelta(hours=1)

    result = {
        "status": "success",
        "event": None,
        "invite_sent": False,
        "notes_created": False,
        "meet_link": "",
        "errors": [],
        "confirmation": "",
    }

    # Step 1: Check availability
    conflict = await _check_availability(user_id, start_time, end_time)
    if conflict:
        result["status"] = "conflict"
        result["confirmation"] = await _humanize_conflict(
            name, title, conflict, start_time
        )
        return result

    # Step 2: Create calendar event with Meet link
    event = await _create_meeting_event(
        user_id, title, attendees, start_time, end_time, description
    )
    if event:
        result["event"] = event
        result["meet_link"] = event.get("meet_link", "")
    else:
        result["errors"].append("Failed to create calendar event")

    # Step 3: Send email invite to attendees
    if send_invite and attendees and event:
        invite_ok = await _send_invite_email(
            user_id, title, attendees, start_time, end_time,
            event.get("meet_link", ""), description, user_name,
        )
        result["invite_sent"] = invite_ok
        if not invite_ok:
            result["errors"].append("Failed to send invite email")

    # Step 4: Create meeting prep notes
    if create_notes and event:
        notes_ok = await _create_meeting_notes(
            user_id, title, attendees, start_time, description, user_name,
        )
        result["notes_created"] = notes_ok

    # Step 5: Generate humanized confirmation
    result["confirmation"] = await _humanize_confirmation(
        name, title, attendees, start_time, result
    )

    logger.info(
        "Meeting orchestrator: %s for user=%s — event=%s invite=%s notes=%s",
        title, user_id[:8],
        "✓" if result["event"] else "✗",
        "✓" if result["invite_sent"] else "✗",
        "✓" if result["notes_created"] else "✗",
    )

    return result


# ---------------------------------------------------------------------------
# Step 1: Availability Check
# ---------------------------------------------------------------------------

async def _check_availability(
    user_id: str, start: datetime, end: datetime,
) -> Optional[Dict[str, Any]]:
    """Check if the user has a conflicting event."""
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return None  # Can't check, proceed optimistically

    try:
        events = await calendar_svc.async_get_upcoming_events(
            user_id=user_id, max_results=20, days_ahead=30,
        )
        if not events:
            return None

        for event in events:
            ev_start_str = event.get("start", "")
            ev_end_str = event.get("end", "")
            if not ev_start_str or "T" not in str(ev_start_str):
                continue

            try:
                ev_start = datetime.fromisoformat(str(ev_start_str).replace("Z", "+00:00"))
                ev_end = datetime.fromisoformat(str(ev_end_str).replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            # Check overlap
            if ev_start < end and ev_end > start:
                return {
                    "summary": event.get("summary", "Event"),
                    "start": ev_start.strftime("%H:%M"),
                    "end": ev_end.strftime("%H:%M"),
                }

    except Exception as e:
        logger.warning("Meeting orchestrator: availability check failed: %s", e)

    return None  # No conflict found


# ---------------------------------------------------------------------------
# Step 2: Create Calendar Event
# ---------------------------------------------------------------------------

async def _create_meeting_event(
    user_id: str, title: str, attendees: List[str],
    start: datetime, end: datetime, description: str,
) -> Optional[Dict[str, Any]]:
    """Create calendar event with Google Meet link."""
    calendar_svc = get_service("calendar")
    if not calendar_svc or not calendar_svc.is_initialized():
        return None

    try:
        event = await calendar_svc.async_create_meeting(
            user_id=user_id,
            summary=title,
            start_time=start,
            end_time=end,
            attendees=attendees,
            description=description,
        )
        return event
    except Exception as e:
        logger.error("Meeting orchestrator: create event failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Step 3: Send Invite Email
# ---------------------------------------------------------------------------

async def _send_invite_email(
    user_id: str, title: str, attendees: List[str],
    start: datetime, end: datetime, meet_link: str,
    description: str, user_name: str,
) -> bool:
    """Send humanized invite email to all attendees."""
    gmail = get_service("gmail")
    if not gmail or not gmail.is_initialized():
        return False

    # Build email body
    body = await _build_invite_email(
        title, start, end, meet_link, description, user_name
    )

    sent_count = 0
    for email in attendees:
        try:
            await gmail.send_email(
                user_id=user_id,
                to=email,
                subject=f"Meeting: {title} — {start.strftime('%b %d at %H:%M')}",
                body=body,
            )
            sent_count += 1
        except Exception as e:
            logger.warning("Meeting invite: failed to send to %s: %s", email, e)

    return sent_count > 0


async def _build_invite_email(
    title: str, start: datetime, end: datetime,
    meet_link: str, description: str, user_name: str,
) -> str:
    """Build a warm, professional invite email."""
    openai_svc = get_service("openai")
    name = user_name or "the organizer"

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""Write a brief, professional meeting invite email.

Meeting: {title}
Date: {start.strftime('%A, %B %d at %H:%M')} - {end.strftime('%H:%M')}
Meet link: {meet_link or 'TBD'}
Agenda: {description or 'To be discussed'}
From: {name}

RULES:
- Warm but professional (not stiff corporate-speak)
- Include date, time, and Meet link
- Mention the agenda briefly
- Keep it under 8 lines
- End with "Looking forward to it!"

Write the email body (no subject line):"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=250,
                temperature=0.7,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 20:
                return text
        except Exception:
            pass

    # Fallback
    meet_line = f"\nJoin: {meet_link}" if meet_link else ""
    return (
        f"Hi,\n\n"
        f"I'd like to invite you to: {title}\n"
        f"When: {start.strftime('%A, %B %d at %H:%M')} - {end.strftime('%H:%M')}"
        f"{meet_line}\n"
        f"{f'Agenda: {description}' if description else ''}\n\n"
        f"Looking forward to it!\n{name}"
    )


# ---------------------------------------------------------------------------
# Step 4: Create Meeting Notes
# ---------------------------------------------------------------------------

async def _create_meeting_notes(
    user_id: str, title: str, attendees: List[str],
    start: datetime, description: str, user_name: str,
) -> bool:
    """Create meeting prep notes via notes agent."""
    from agents.core import get_agent

    notes_agent = get_agent("notes")
    if not notes_agent:
        return False

    attendee_str = ", ".join(attendees[:5]) if attendees else "TBD"
    date_str = start.strftime("%B %d, %H:%M")

    note_content = (
        f"create note titled 'Meeting Prep: {title}': "
        f"Meeting: {title}\n"
        f"Date: {date_str}\n"
        f"Attendees: {attendee_str}\n"
        f"Agenda: {description or 'TBD'}\n\n"
        f"Prep notes:\n- \n\nAction items:\n- "
    )

    try:
        ctx = {"user_id": user_id}
        result = await notes_agent.execute(note_content, ctx)
        return bool(result and result.response)
    except Exception as e:
        logger.warning("Meeting notes creation failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Humanized Responses
# ---------------------------------------------------------------------------

async def _humanize_conflict(
    name: str, title: str, conflict: Dict[str, Any], start: datetime,
) -> str:
    """Humanized message when there's a calendar conflict."""
    openai_svc = get_service("openai")

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a personal assistant. {name} wants to schedule '{title}' at {start.strftime('%A %H:%M')} but there's a conflict with '{conflict['summary']}' ({conflict['start']}-{conflict['end']}).

Write a warm 2-3 sentence message explaining the conflict and suggesting alternatives. Use 1 emoji."""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=150,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 10:
                return text
        except Exception:
            pass

    return (
        f"⚠️ Hey {name}, that time slot is taken — you have "
        f"**{conflict['summary']}** from {conflict['start']} to {conflict['end']}. "
        f"Want me to find a free slot or schedule it for a different time?"
    )


async def _humanize_confirmation(
    name: str, title: str, attendees: List[str],
    start: datetime, result: Dict[str, Any],
) -> str:
    """Humanized confirmation after successful orchestration."""
    openai_svc = get_service("openai")
    meet_link = result.get("meet_link", "")
    invite_sent = result.get("invite_sent", False)
    notes_created = result.get("notes_created", False)

    raw = (
        f"User: {name}\nMeeting: {title}\n"
        f"Time: {start.strftime('%A, %B %d at %H:%M')}\n"
        f"Attendees: {', '.join(attendees[:3]) if attendees else 'none'}\n"
        f"Meet link: {'yes' if meet_link else 'no'}\n"
        f"Invite sent: {'yes' if invite_sent else 'no'}\n"
        f"Notes created: {'yes' if notes_created else 'no'}\n"
        f"Errors: {', '.join(result.get('errors', [])) or 'none'}"
    )

    if openai_svc and openai_svc.is_initialized():
        prompt = f"""You are CAPIVAREX, a warm personal assistant. Generate a brief confirmation that everything is set up for {name}'s meeting.

RULES:
- Be warm, efficient, like a great PA
- Mention what was done (event, invite, notes, Meet link)
- If something failed, mention it gently and offer to retry
- Keep it under 5 lines
- Use 2-3 emojis (📅 ✉️ 📝 🔗)

RAW DATA:
{raw}

Generate confirmation:"""

        try:
            import asyncio
            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-5-mini",
                max_tokens=200,
                temperature=0.8,
            )
            text = response if isinstance(response, str) else response.get("content", "")
            if text and len(text) > 10:
                return text
        except Exception:
            pass

    # Fallback
    parts = [f"✅ All set, {name}! Here's what I did:\n"]
    parts.append(f"📅 Created **{title}** for {start.strftime('%A at %H:%M')}")
    if meet_link:
        parts.append("🔗 Google Meet link ready")
    if invite_sent:
        parts.append(f"✉️ Invite sent to {', '.join(attendees[:3])}")
    if notes_created:
        parts.append("📝 Meeting prep notes created")
    if result.get("errors"):
        parts.append(f"\n⚠️ Note: {'; '.join(result['errors'])}")
    parts.append("\n💬 Need me to adjust anything?")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Parse Meeting Request (GPT-powered)
# ---------------------------------------------------------------------------

async def parse_meeting_request(message: str) -> Optional[Dict[str, Any]]:
    """
    Use GPT to parse a natural language meeting request.

    Input: "marca reunião com o João sobre projecto X sexta às 15h"
    Output: {"title": "Project X", "attendees": ["joao@..."], "datetime": "...", "description": "..."}

    Returns None if the message is not a meeting request.
    """
    openai_svc = get_service("openai")
    if not openai_svc or not openai_svc.is_initialized():
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d (%A)")

    prompt = f"""Parse this meeting request into structured data. Today is {today}.

Message: "{message}"

If this is a meeting request, return JSON:
{{"title": "meeting title", "attendees_text": "names/emails mentioned", "date": "YYYY-MM-DD", "time": "HH:MM", "duration_minutes": 60, "description": "topic/agenda"}}

If this is NOT a meeting request, return: {{"is_meeting": false}}

Only return JSON, no markdown:"""

    try:
        import asyncio
        response = await asyncio.to_thread(
            openai_svc.chat_completion,
            [{"role": "user", "content": prompt}],
            model="gpt-5-mini",
            max_tokens=200,
            temperature=0.1,
        )

        text = response if isinstance(response, str) else response.get("content", "")
        text = text.strip().strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()

        parsed = json.loads(text)
        if parsed.get("is_meeting") is False:
            return None
        return parsed

    except Exception as e:
        logger.warning("Meeting parse failed: %s", e)
        return None
