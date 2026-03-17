"""
WhatsApp Business Cloud API Service.

Sends and receives messages via Meta's WhatsApp Cloud API.
Works exactly like the Telegram bot — same orchestrator, same AI, same agents.

Env vars:
- WHATSAPP_TOKEN: Meta access token (permanent System User token recommended)
- WHATSAPP_PHONE_NUMBER_ID: Phone number ID from Meta dashboard
- WHATSAPP_VERIFY_TOKEN: Token for webhook verification (you choose this)

Flow:
1. User sends WhatsApp message → Meta servers → Webhook POST → our server
2. We process via orchestrator (same as Telegram/WebApp)
3. We reply via Meta Graph API → Meta servers → user's WhatsApp
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH_API_VERSION = "v21.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


def _get_token() -> str:
    return os.getenv("WHATSAPP_TOKEN", "")


def _get_phone_id() -> str:
    return os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")


def is_configured() -> bool:
    """Check if WhatsApp is properly configured."""
    return bool(_get_token() and _get_phone_id())


async def send_text_message(to: str, text: str) -> Optional[Dict[str, Any]]:
    """
    Send a text message to a WhatsApp user.

    Args:
        to: Recipient phone number with country code (e.g. "353891234567")
        text: Message text (max 4096 chars)

    Returns: API response dict or None on failure.
    """
    if not is_configured():
        logger.warning("WhatsApp not configured — missing WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID")
        return None

    # Clean phone number — remove +, spaces, dashes
    clean_to = to.replace("+", "").replace(" ", "").replace("-", "")

    url = f"{GRAPH_API_BASE}/{_get_phone_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }

    # Split long messages (WhatsApp limit is 4096 chars)
    chunks = _split_message(text, max_len=4096)

    last_response = None
    for chunk in chunks:
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": clean_to,
            "type": "text",
            "text": {"preview_url": True, "body": chunk},
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(url, json=payload, headers=headers)
                data = resp.json()

            if resp.status_code == 200 and data.get("messages"):
                msg_id = data["messages"][0].get("id", "")
                logger.info("WhatsApp: sent to %s (id=%s)", clean_to[-4:], msg_id[:16])
                last_response = data
            else:
                logger.error("WhatsApp send failed: %s %s", resp.status_code, data.get("error", data))
                return None

        except Exception as e:
            logger.error("WhatsApp send error: %s", e)
            return None

    return last_response


async def mark_as_read(message_id: str) -> bool:
    """Mark a received message as read (blue ticks)."""
    if not is_configured():
        return False

    url = f"{GRAPH_API_BASE}/{_get_phone_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
        return resp.status_code == 200
    except Exception:
        return False


def _split_message(text: str, max_len: int = 4096) -> list:
    """Split a long message into chunks that fit WhatsApp's limit."""
    if len(text) <= max_len:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break

        # Find a good split point (newline or space)
        split_at = text.rfind("\n", 0, max_len)
        if split_at < max_len // 2:
            split_at = text.rfind(" ", 0, max_len)
        if split_at < max_len // 2:
            split_at = max_len

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    return chunks


def extract_message_from_webhook(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Extract message data from a WhatsApp webhook payload.

    Returns:
        {"from": "353891234567", "name": "John", "text": "hello",
         "message_id": "wamid.xxx", "timestamp": "1234567890"}
        Or None if not a user message.
    """
    try:
        entry = body.get("entry", [])
        if not entry:
            return None

        changes = entry[0].get("changes", [])
        if not changes:
            return None

        value = changes[0].get("value", {})

        # Only process incoming messages (not status updates)
        messages = value.get("messages", [])
        if not messages:
            return None

        msg = messages[0]
        msg_type = msg.get("type", "")

        # Extract sender info
        contacts = value.get("contacts", [])
        sender_name = contacts[0].get("profile", {}).get("name", "") if contacts else ""
        sender_phone = msg.get("from", "")

        # Extract text based on message type
        text = ""
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "image":
            text = msg.get("image", {}).get("caption", "[Image received]")
        elif msg_type == "audio":
            text = "[Voice message received]"
        elif msg_type == "video":
            text = msg.get("video", {}).get("caption", "[Video received]")
        elif msg_type == "document":
            text = msg.get("document", {}).get("caption", "[Document received]")
        elif msg_type == "location":
            loc = msg.get("location", {})
            text = f"[Location: {loc.get('latitude')}, {loc.get('longitude')}]"
        elif msg_type == "interactive":
            interactive = msg.get("interactive", {})
            if interactive.get("type") == "button_reply":
                text = interactive.get("button_reply", {}).get("title", "")
            elif interactive.get("type") == "list_reply":
                text = interactive.get("list_reply", {}).get("title", "")
        else:
            text = f"[{msg_type} message]"

        if not text:
            return None

        return {
            "from": sender_phone,
            "name": sender_name,
            "text": text,
            "message_id": msg.get("id", ""),
            "timestamp": msg.get("timestamp", ""),
            "type": msg_type,
        }

    except (IndexError, KeyError, TypeError) as e:
        logger.warning("WhatsApp webhook parse error: %s", e)
        return None


async def send_interactive_buttons(
    to: str,
    body_text: str,
    buttons: List[Dict[str, str]],
    header: str = "",
    footer: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Send an interactive message with reply buttons (max 3).

    Args:
        to: Recipient phone number
        body_text: Main message text
        buttons: List of {"id": "btn_id", "title": "Button Text"} (max 3)
        header: Optional header text
        footer: Optional footer text
    """
    if not is_configured():
        return None

    clean_to = to.replace("+", "").replace(" ", "").replace("-", "")

    action_buttons = [
        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"][:20]}}
        for btn in buttons[:3]
    ]

    interactive = {
        "type": "button",
        "body": {"text": body_text[:1024]},
        "action": {"buttons": action_buttons},
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "interactive",
        "interactive": interactive,
    }

    url = f"{GRAPH_API_BASE}/{_get_phone_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

        if resp.status_code == 200 and data.get("messages"):
            logger.info("WhatsApp: sent buttons to %s", clean_to[-4:])
            return data
        else:
            logger.error("WhatsApp buttons failed: %s %s", resp.status_code, data.get("error", data))
            return None

    except Exception as e:
        logger.error("WhatsApp buttons error: %s", e)
        return None


async def send_link_button(
    to: str,
    body_text: str,
    button_text: str,
    url_link: str,
    header: str = "",
    footer: str = "",
) -> Optional[Dict[str, Any]]:
    """
    Send a CTA URL button (clickable link).

    Args:
        to: Recipient phone number
        body_text: Main message text
        button_text: Button label (max 20 chars)
        url_link: URL to open when clicked
    """
    if not is_configured():
        return None

    clean_to = to.replace("+", "").replace(" ", "").replace("-", "")

    interactive = {
        "type": "cta_url",
        "body": {"text": body_text[:1024]},
        "action": {
            "name": "cta_url",
            "parameters": {
                "display_text": button_text[:20],
                "url": url_link,
            },
        },
    }
    if header:
        interactive["header"] = {"type": "text", "text": header[:60]}
    if footer:
        interactive["footer"] = {"text": footer[:60]}

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": clean_to,
        "type": "interactive",
        "interactive": interactive,
    }

    url = f"{GRAPH_API_BASE}/{_get_phone_id()}/messages"
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            data = resp.json()

        if resp.status_code == 200 and data.get("messages"):
            logger.info("WhatsApp: sent link button to %s", clean_to[-4:])
            return data
        else:
            logger.error("WhatsApp link button failed: %s %s", resp.status_code, data.get("error", data))
            return None

    except Exception as e:
        logger.error("WhatsApp link button error: %s", e)
        return None


async def update_business_profile(
    about: str = "",
    description: str = "",
    vertical: str = "TECH",
    websites: Optional[List[str]] = None,
) -> bool:
    """Update WhatsApp Business Profile info."""
    if not is_configured():
        return False

    url = f"{GRAPH_API_BASE}/{_get_phone_id()}/whatsapp_business_profile"
    headers = {
        "Authorization": f"Bearer {_get_token()}",
        "Content-Type": "application/json",
    }

    data: Dict[str, Any] = {"messaging_product": "whatsapp"}
    if about:
        data["about"] = about[:139]
    if description:
        data["description"] = description[:512]
    if vertical:
        data["vertical"] = vertical
    if websites:
        data["websites"] = websites[:2]

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(url, json=data, headers=headers)
        return resp.status_code == 200
    except Exception:
        return False
