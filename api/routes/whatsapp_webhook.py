"""
WhatsApp Webhook Route — Professional Onboarding.

Flow:
1. New user sends first message → Welcome with buttons
2. User clicks "Link Account" → Gets 6-digit code to enter on app.capivarex.com
3. User clicks "Try as Guest" → Gets limited AI assistant
4. Linked user → Full AI assistant (same as Telegram)

Handles:
- GET /api/webhooks/whatsapp — Meta webhook verification
- POST /api/webhooks/whatsapp — Incoming messages
"""

import logging
import os
import random
import string
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

from services.integrations.whatsapp_service import (
    extract_message_from_webhook,
    mark_as_read,
    send_interactive_buttons,
    send_link_button,
    send_text_message,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory store for link codes {code: {phone, created_at, expires_at}}
_link_codes: Dict[str, Dict[str, Any]] = {}

# Track which phones have seen the welcome message
_welcomed_phones: Dict[str, float] = {}


# ---------------------------------------------------------------------------
# Webhook Verification
# ---------------------------------------------------------------------------


@router.get("/whatsapp")
async def verify_webhook(
    hub_mode: str = Query(None, alias="hub.mode"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
    hub_challenge: str = Query(None, alias="hub.challenge"),
):
    """Meta webhook verification (challenge-response)."""
    verify_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")

    if hub_mode == "subscribe" and hub_verify_token == verify_token:
        logger.info("WhatsApp webhook verified successfully")
        return PlainTextResponse(content=hub_challenge, status_code=200)

    logger.warning("WhatsApp webhook verification failed: mode=%s", hub_mode)
    raise HTTPException(status_code=403, detail="Verification failed")


# ---------------------------------------------------------------------------
# Incoming Messages
# ---------------------------------------------------------------------------


@router.post("/whatsapp")
async def receive_message(request: Request):
    """Receive and process incoming WhatsApp messages."""
    try:
        body: Dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    msg_data = extract_message_from_webhook(body)
    if not msg_data:
        return {"status": "ok"}

    sender_phone = msg_data["from"]
    sender_name = msg_data["name"]
    user_text = msg_data["text"]
    message_id = msg_data["message_id"]

    logger.info(
        "WhatsApp from %s (%s): %s",
        sender_name or "unknown",
        sender_phone[-4:],
        user_text[:80],
    )

    # Mark as read (blue ticks)
    await mark_as_read(message_id)

    # Check if user has a linked Capivarex account
    user_id = await _get_user_id_by_phone(sender_phone)

    if user_id:
        # Check plan — only Everywhere/Family get WhatsApp bot
        plan = await _get_user_plan(user_id)

        # Handle FOMO button clicks regardless of plan
        text_lower = user_text.lower().strip()
        if text_lower in ("🚀 ver plano executive", "btn_upgrade", "upgrade"):
            await send_link_button(
                to=sender_phone,
                body_text="🚀 *Conheça o plano Executive!*\n\nAssistente no WhatsApp, Smart Home, agentes ilimitados e muito mais.",
                button_text="Ver Planos",
                url_link="https://app.capivarex.com/pricing",
            )
            return {"status": "ok"}

        if text_lower in ("💬 ir para o telegram", "btn_telegram", "telegram"):
            await send_link_button(
                to=sender_phone,
                body_text="💬 *Fale comigo no Telegram!*\n\nEstou lá te esperando. Clique abaixo para abrir:",
                button_text="Abrir Telegram",
                url_link="https://t.me/CapivarexBot",
            )
            return {"status": "ok"}

        if plan in ("executive", "family"):
            # PREMIUM USER — full AI assistant
            await _process_linked_user(user_id, sender_phone, sender_name, user_text)
        else:
            # PROFESSIONAL USER — FOMO message, then stop
            await _handle_free_user_fomo(sender_phone, sender_name, plan)
    else:
        # NOT LINKED — onboarding flow
        await _handle_unlinked_user(sender_phone, sender_name, user_text)

    return {"status": "ok"}


# Track FOMO messages sent (don't spam — max 1 per 24h)
_fomo_sent: Dict[str, float] = {}


# ---------------------------------------------------------------------------
# PLAN CHECK + FOMO (Free/Me users on WhatsApp)
# ---------------------------------------------------------------------------


async def _get_user_plan(user_id: str) -> str:
    """Get user's subscription plan."""
    try:
        from services.core import get_service

        db = get_service("database")
        if not db or not db.is_initialized():
            return "professional"

        client = db.get_client()
        result = (
            client.table("users").select("plan").eq("id", user_id).limit(1).execute()
        )
        if result.data:
            return result.data[0].get("plan", "professional")
    except Exception:
        pass
    return "professional"


async def _handle_free_user_fomo(phone: str, name: str, plan: str) -> None:
    """
    Send FOMO message to free/basic/me users trying WhatsApp.

    Only sends once every 24 hours — not spammy.
    After the FOMO message, the bot does NOT respond to further messages.
    """
    now = time.time()
    last_fomo = _fomo_sent.get(phone, 0)

    # Only send FOMO once per 24 hours
    if now - last_fomo < 86400:
        return  # Silently ignore — already sent FOMO today

    first_name = name.split()[0] if name else ""
    greeting = f"Oi {first_name}! " if first_name else "Oi! "

    plan_display = "Professional"

    await send_interactive_buttons(
        to=phone,
        body_text=(
            f"{greeting}Que bom que está aqui! 😊\n\n"
            f"Seu plano atual (*{plan_display}*) inclui o Capivarex no *Telegram*. "
            f"Para usar o assistente aqui no *WhatsApp*, faça upgrade para o plano "
            f"*Executive*! 🚀\n\n"
            f"Com o Executive você ganha:\n"
            f"✅ Capivarex no WhatsApp 24/7\n"
            f"✅ Smart Home (controle por voz)\n"
            f"✅ Agentes ilimitados\n"
            f"✅ Prioridade no suporte\n\n"
            f"Enquanto isso, me manda mensagem no *Telegram* — estou lá te esperando! 💬"
        ),
        buttons=[
            {"id": "btn_upgrade", "title": "🚀 Conhecer Executive"},
            {"id": "btn_telegram", "title": "💬 Ir para o Telegram"},
        ],
        header="Desbloqueie o WhatsApp! 🔓",
        footer="app.capivarex.com/pricing",
    )

    _fomo_sent[phone] = now
    logger.info("WhatsApp FOMO sent to %s (plan=%s)", phone[-4:], plan)


# ---------------------------------------------------------------------------
# 1. WELCOME MESSAGE (Professional Onboarding)
# ---------------------------------------------------------------------------


async def _send_welcome(phone: str, name: str) -> None:
    """Send professional welcome message with interactive buttons."""
    first_name = name.split()[0] if name else ""
    greeting = f"Olá {first_name}! " if first_name else "Olá! "

    body = (
        f"{greeting}Eu sou o *Capivarex* 🧠✨\n\n"
        "Seu assistente pessoal com inteligência artificial. "
        "Posso te ajudar com:\n\n"
        "📅 Agenda e compromissos\n"
        "💰 Finanças pessoais\n"
        "🏠 Casa inteligente\n"
        "📧 Emails e lembretes\n"
        "🌤️ Previsão do tempo\n"
        "📦 Rastreio de encomendas\n\n"
        "Para ter acesso completo, vincule sua conta!"
    )

    await send_interactive_buttons(
        to=phone,
        body_text=body,
        buttons=[
            {"id": "btn_link", "title": "🔗 Vincular Conta"},
            {"id": "btn_guest", "title": "💬 Modo Visitante"},
            {"id": "btn_create", "title": "📱 Criar Conta"},
        ],
        header="Bem-vindo ao Capivarex!",
        footer="app.capivarex.com",
    )

    _welcomed_phones[phone] = time.time()


# ---------------------------------------------------------------------------
# 2. LINK ACCOUNT (Code System)
# ---------------------------------------------------------------------------


async def _handle_link_request(phone: str) -> None:
    """Generate a 6-digit link code and send to user."""
    code = _generate_link_code(phone)

    await send_text_message(
        phone,
        f"🔗 *Código de vinculação:* `{code}`\n\n"
        f"Agora faça o seguinte:\n\n"
        f"1️⃣ Abra *app.capivarex.com*\n"
        f"2️⃣ Vá em *Configurações* → *WhatsApp*\n"
        f"3️⃣ Digite o código: *{code}*\n\n"
        f"⏰ O código expira em *10 minutos*.\n\n"
        f"Se ainda não tem uma conta, crie uma gratuitamente!",
    )

    await send_link_button(
        to=phone,
        body_text="Clique abaixo para abrir o app:",
        button_text="Abrir Capivarex",
        url_link="https://app.capivarex.com/settings",
        footer="O código expira em 10 minutos",
    )


def _generate_link_code(phone: str) -> str:
    """Generate a 6-digit code for phone linking."""
    now = time.time()
    expired = [c for c, d in _link_codes.items() if d["expires_at"] < now]
    for c in expired:
        del _link_codes[c]

    existing = [c for c, d in _link_codes.items() if d["phone"] == phone]
    for c in existing:
        del _link_codes[c]

    code = "".join(random.choices(string.digits, k=6))
    while code in _link_codes:
        code = "".join(random.choices(string.digits, k=6))

    _link_codes[code] = {
        "phone": phone,
        "created_at": now,
        "expires_at": now + 600,
    }

    return code


# ---------------------------------------------------------------------------
# 3. GUEST MODE (Limited AI)
# ---------------------------------------------------------------------------


async def _handle_guest_message(phone: str, name: str, text: str) -> None:
    """Process message in guest mode (limited, no personal data)."""
    first_name = name.split()[0] if name else "você"

    openai_svc = None
    try:
        from services.core import get_service

        openai_svc = get_service("openai")
    except Exception:
        pass

    if openai_svc and openai_svc.is_initialized():
        import asyncio

        try:
            prompt = (
                f"You are Capivarex, a warm and helpful AI personal assistant. "
                f"The user's name is {first_name}. They are using WhatsApp in guest mode "
                f"(no account linked). Answer their question helpfully but briefly "
                f"(max 3-4 sentences). Respond in the same language the user writes. "
                f"At the end, if relevant, gently mention they can type 'vincular' "
                f"to link their account for personalized features.\n\n"
                f"User: {text}"
            )

            response = await asyncio.to_thread(
                openai_svc.chat_completion,
                [{"role": "user", "content": prompt}],
                model="gpt-4o-mini",
                max_tokens=300,
                temperature=0.7,
            )
            reply = (
                response if isinstance(response, str) else response.get("content", "")
            )
            if reply and len(reply) > 10:
                await send_text_message(phone, reply)
                return
        except Exception as e:
            logger.warning("WhatsApp guest GPT failed: %s", e)

    await send_text_message(
        phone,
        f"Oi {first_name}! 😊 Estou no modo visitante. "
        f"Vincule sua conta para acesso completo!\n\n"
        f"Digite *vincular* para conectar.",
    )


# ---------------------------------------------------------------------------
# FLOW ROUTER (Unlinked Users)
# ---------------------------------------------------------------------------


async def _handle_unlinked_user(phone: str, name: str, text: str) -> None:
    """Route unlinked user messages through onboarding flow."""
    text_lower = text.lower().strip()

    # Button clicks
    if text_lower in (
        "🔗 vincular conta",
        "vincular conta",
        "btn_link",
        "vincular",
        "link",
        "conectar",
    ):
        await _handle_link_request(phone)
        return

    if text_lower in (
        "📱 criar conta",
        "criar conta",
        "btn_create",
        "criar",
        "registrar",
        "signup",
        "sign up",
    ):
        await send_link_button(
            to=phone,
            body_text=(
                "📱 *Crie sua conta gratuita!*\n\n"
                "Leva menos de 1 minuto. Depois vincule "
                "seu WhatsApp para ter acesso completo."
            ),
            button_text="Criar Conta Grátis",
            url_link="https://app.capivarex.com",
            footer="Grátis — sem cartão de crédito",
        )
        return

    if text_lower in (
        "💬 modo visitante",
        "usar como visitante",
        "btn_guest",
        "visitante",
        "guest",
        "teste",
    ):
        await send_text_message(
            phone,
            "💬 *Modo Visitante ativado!*\n\n"
            "Pode me perguntar qualquer coisa! Porém, "
            "para funcionalidades personalizadas (agenda, finanças, "
            "smart home), vincule sua conta.\n\n"
            "Digite *vincular* a qualquer momento para conectar.",
        )
        return

    # Help / Menu
    if text_lower in ("menu", "ajuda", "help", "oi", "olá", "ola", "hi", "hello"):
        last_welcome = _welcomed_phones.get(phone, 0)
        await _send_welcome(phone, name)
        return

    # 6-digit code hint
    if text_lower.isdigit() and len(text_lower) == 6:
        await send_text_message(
            phone,
            f"O código *{text_lower}* deve ser digitado no site "
            f"*app.capivarex.com* → Configurações → WhatsApp.\n\n"
            f"Não é para digitar aqui 😉",
        )
        return

    # First interaction — show welcome
    last_welcome = _welcomed_phones.get(phone, 0)
    if time.time() - last_welcome > 3600:
        await _send_welcome(phone, name)
        return

    # Subsequent messages — guest mode AI
    await _handle_guest_message(phone, name, text)


# ---------------------------------------------------------------------------
# FULL AI (Linked Users)
# ---------------------------------------------------------------------------


async def _process_linked_user(
    user_id: str,
    phone: str,
    name: str,
    text: str,
) -> Optional[str]:
    """Process message for a linked Capivarex user — full AI."""
    try:
        from services.core import get_service

        db = get_service("database")
        user_name = name
        if db and db.is_initialized():
            user_data = await db.get_user_by_id(user_id)
            if user_data:
                user_name = user_data.get("full_name", name)

        from agents.core import get_agent

        orchestrator = get_agent("orchestrator")
        if not orchestrator:
            await send_text_message(
                phone, "Estou com um probleminha técnico. Tente novamente! 🔧"
            )
            return None

        context = {
            "user_id": user_id,
            "user_name": user_name,
            "interface": "whatsapp",
            "phone": phone,
        }

        try:
            redis = get_service("redis")
            if redis and redis.is_initialized():
                context["history"] = await redis.get_conversation_context(
                    user_id, limit=10
                )
        except Exception:
            pass

        result = await orchestrator.execute(text, context)

        if result and result.response:
            await send_text_message(phone, result.response)

            try:
                from utils.safe_task import safe_create_task

                redis = get_service("redis")
                if redis and redis.is_initialized():
                    safe_create_task(
                        redis.save_conversation_message(
                            user_id, {"role": "user", "content": text}
                        ),
                        name="wa_redis_user",
                    )
                    safe_create_task(
                        redis.save_conversation_message(
                            user_id, {"role": "assistant", "content": result.response}
                        ),
                        name="wa_redis_assistant",
                    )

                from services.business.rag_service import extract_and_save_memory

                safe_create_task(
                    extract_and_save_memory(user_id, text),
                    name="wa_rag_memory",
                )
            except Exception:
                pass

            return result.response

        await send_text_message(phone, "Não entendi. Pode reformular? 🤔")
        return None

    except Exception as e:
        logger.error("WhatsApp linked user error: %s", e, exc_info=True)
        await send_text_message(phone, "Algo deu errado. Tente novamente! 🔄")
        return None


# ---------------------------------------------------------------------------
# Phone → User ID Lookup
# ---------------------------------------------------------------------------


async def _get_user_id_by_phone(phone: str) -> str:
    """Look up Capivarex user ID by WhatsApp phone number."""
    from services.core import get_service

    db = get_service("database")
    if not db or not db.is_initialized():
        return ""

    try:
        client = db.get_client()
        clean_phone = phone.replace("+", "").replace(" ", "")

        result = (
            client.table("users")
            .select("id")
            .or_(f"phone.eq.{clean_phone},phone.eq.+{clean_phone}")
            .limit(1)
            .execute()
        )
        if result.data:
            return result.data[0]["id"]

        result2 = (
            client.table("user_preferences")
            .select("user_id")
            .eq("whatsapp_phone", clean_phone)
            .limit(1)
            .execute()
        )
        if result2.data:
            return result2.data[0]["user_id"]

    except Exception as e:
        logger.warning("WhatsApp user lookup failed: %s", e)

    return ""


# ---------------------------------------------------------------------------
# API: Verify Link Code (called from frontend)
# ---------------------------------------------------------------------------


@router.post("/whatsapp/link")
async def verify_link_code(request: Request):
    """
    Verify a WhatsApp link code from the frontend.

    Body: {"code": "123456", "user_id": "uuid-xxx"}
    Returns: {"success": true, "phone": "353891234567"}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    code = str(body.get("code", "")).strip()
    user_id = str(body.get("user_id", "")).strip()

    if not code or not user_id:
        raise HTTPException(status_code=400, detail="code and user_id required")

    code_data = _link_codes.get(code)
    if not code_data:
        raise HTTPException(status_code=404, detail="Invalid or expired code")

    if code_data["expires_at"] < time.time():
        del _link_codes[code]
        raise HTTPException(status_code=410, detail="Code expired")

    phone = code_data["phone"]

    try:
        from services.core import get_service

        db = get_service("database")
        if db and db.is_initialized():
            client = db.get_client()
            client.table("users").update({"phone": phone}).eq("id", user_id).execute()

            client.table("user_preferences").upsert(
                {
                    "user_id": user_id,
                    "whatsapp_phone": phone,
                }
            ).execute()

    except Exception as e:
        logger.error("WhatsApp link save failed: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save link")

    del _link_codes[code]

    await send_text_message(
        phone,
        "✅ *Conta vinculada com sucesso!*\n\n"
        "Agora você tem acesso completo ao Capivarex no WhatsApp! "
        "Pergunte qualquer coisa — estou aqui pra ajudar. 🧠✨",
    )

    logger.info("WhatsApp linked: user=%s phone=%s", user_id[:8], phone[-4:])
    return {"success": True, "phone": phone}


# ---------------------------------------------------------------------------
# API: Save phone + send welcome (called from frontend after registration)
# ---------------------------------------------------------------------------


@router.post("/whatsapp/register-phone")
async def register_phone(request: Request):
    """
    Save user phone and send welcome message after frontend registration.

    Body: {"user_id": "uuid", "phone": "+353891234567", "name": "John", "plan": "professional"}
    Called by frontend after Supabase signUp succeeds.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    user_id = str(body.get("user_id", "")).strip()
    phone = str(body.get("phone", "")).strip()
    name = str(body.get("name", "")).strip()
    plan = str(body.get("plan", "professional")).strip()

    if not user_id or not phone:
        raise HTTPException(status_code=400, detail="user_id and phone required")

    # Clean phone
    clean_phone = (
        phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    )

    # Save phone to database
    try:
        from services.core import get_service

        db = get_service("database")
        if db and db.is_initialized():
            client = db.get_client()

            # Update users table
            client.table("users").update({"phone": clean_phone}).eq(
                "id", user_id
            ).execute()

            # Save to preferences
            client.table("user_preferences").upsert(
                {
                    "user_id": user_id,
                    "whatsapp_phone": clean_phone,
                }
            ).execute()

    except Exception as e:
        logger.error("Register phone save failed: %s", e)

    # Send welcome message (background)
    try:
        from utils.safe_task import safe_create_task
        from services.business.welcome_service import send_welcome_message

        safe_create_task(
            send_welcome_message(
                user_id=user_id,
                phone=clean_phone,
                name=name,
                channel="whatsapp",
                plan=plan,
            ),
            name="register_welcome",
        )
    except Exception:
        pass

    return {"success": True, "phone": clean_phone}
