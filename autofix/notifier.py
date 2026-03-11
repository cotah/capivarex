"""
AutoFix Notifier
================
Sends Telegram alerts to the admin when a new AutoFix ticket/patch is created.
Provides inline keyboard buttons for ✅ Aprovar / ❌ Rejeitar.

When the admin taps ✅ Aprovar:
  → approve_patch() is called
  → create_pr_for_patch() opens a GitHub PR
  → admin receives the PR URL

When the admin taps ❌ Rejeitar:
  → reject_patch() is called
  → admin receives confirmation

Environment variables:
  TELEGRAM_BOT_TOKEN        — bot token
  TELEGRAM_ADMIN_CHAT_ID    — your personal Telegram chat ID
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger("capivarex.autofix.notifier")

# ---------------------------------------------------------------------------
# Admin alert — new ticket detected
# ---------------------------------------------------------------------------

async def notify_new_ticket(ticket: dict, is_new: bool) -> None:
    """
    Sends a Telegram alert to the admin when a new (or recurring) error
    ticket is created by AutoFix.
    """
    admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin_chat_id:
        logger.warning("TELEGRAM_ADMIN_CHAT_ID not set — skipping admin notification")
        return

    ticket_id = ticket.get("id", "?")
    error_type = ticket.get("error_type", "Unknown")
    count = ticket.get("count", 1)
    top_frame = ticket.get("top_frame", "unknown")
    last_msg = ticket.get("last_error_msg", "")[:200]

    if is_new:
        header = "🚨 *AutoFix — Novo Erro Detectado*"
    else:
        header = f"⚠️ *AutoFix — Erro Recorrente* (ocorrência #{count})"

    text = (
        f"{header}\n\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*Tipo:* `{error_type}`\n"
        f"*Frame:* `{top_frame}`\n"
        f"*Mensagem:* {last_msg}\n\n"
        f"Use /autofix para ver patches propostos e aprovar/rejeitar."
    )

    from telegram_bot import send_proactive_message
    await send_proactive_message(chat_id=admin_chat_id, text=text)


async def notify_patch_ready(patch: dict, patch_index: int) -> None:
    """
    Sends a Telegram alert with inline buttons when a patch is ready for review.
    The admin can tap ✅ Aprovar or ❌ Rejeitar directly from Telegram.
    """
    admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin_chat_id:
        logger.warning("TELEGRAM_ADMIN_CHAT_ID not set — skipping patch notification")
        return

    ticket_id = patch.get("ticket_id", "?")
    error_type = patch.get("error_type", "Unknown")
    patch_type = patch.get("patch_type", "unknown")
    notes = patch.get("notes", "Sem notas.")[:300]
    diff_preview = (patch.get("diff", "") or "")[:400]

    text = (
        f"🔧 *AutoFix — Patch Pronto para Revisão*\n\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*Erro:* `{error_type}`\n"
        f"*Tipo de patch:* `{patch_type}`\n\n"
        f"*O que será feito:*\n{notes}\n\n"
        f"*Diff preview:*\n```\n{diff_preview}\n```\n\n"
        f"Deseja aplicar esta correção?"
    )

    # Inline keyboard: ✅ Aprovar | ❌ Rejeitar
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    "✅ Aprovar e abrir PR",
                    callback_data=f"autofix_approve:{patch_index}"
                ),
                InlineKeyboardButton(
                    "❌ Rejeitar",
                    callback_data=f"autofix_reject:{patch_index}"
                ),
            ]
        ])
    except ImportError:
        keyboard = None

    from telegram_bot import send_proactive_message
    await send_proactive_message(
        chat_id=admin_chat_id,
        text=text,
        reply_markup=keyboard,
    )


async def notify_pr_created(patch_index: int, pr_url: str, ticket_id: str) -> None:
    """Notifies admin that the PR was created successfully."""
    admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin_chat_id:
        return

    text = (
        f"✅ *PR Criado com Sucesso!*\n\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*PR:* {pr_url}\n\n"
        f"Revise o diff e faça o merge quando estiver pronto."
    )
    from telegram_bot import send_proactive_message
    await send_proactive_message(chat_id=admin_chat_id, text=text)


async def notify_pr_failed(patch_index: int, ticket_id: str, error: str) -> None:
    """Notifies admin that PR creation failed."""
    admin_chat_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    if not admin_chat_id:
        return

    text = (
        f"❌ *Falha ao criar PR*\n\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*Erro:* {error[:300]}\n\n"
        f"Verifique os logs do Railway para mais detalhes."
    )
    from telegram_bot import send_proactive_message
    await send_proactive_message(chat_id=admin_chat_id, text=text)
