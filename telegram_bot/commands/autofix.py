"""
AutoFix Telegram Command Handler
=================================
Provides /autofix command and inline button callbacks for patch approval.

Commands:
  /autofix          — list last 5 proposed patches
  /autofix status   — summary of all tickets
  /autofix patch N  — show details of patch N

Inline callbacks (from notify_patch_ready buttons):
  autofix_approve:<index>  — approve patch, open GitHub PR
  autofix_reject:<index>   — reject patch

Only the admin (TELEGRAM_ADMIN_CHAT_ID) can use these commands.
"""

from __future__ import annotations

import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

logger = logging.getLogger("capivarex.telegram.autofix")


def _is_admin(chat_id: int | str) -> bool:
    admin_id = os.environ.get("TELEGRAM_ADMIN_CHAT_ID", "")
    return str(chat_id) == str(admin_id)


# ---------------------------------------------------------------------------
# /autofix command
# ---------------------------------------------------------------------------


async def autofix_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /autofix command — shows pending patches."""
    chat_id = update.effective_chat.id
    if not _is_admin(chat_id):
        await update.message.reply_text("⛔ Acesso restrito ao administrador.")
        return

    args = context.args or []

    if args and args[0] == "status":
        await _send_ticket_summary(update)
        return

    if args and args[0] == "patch" and len(args) > 1:
        try:
            idx = int(args[1])
            await _send_patch_detail(update, idx)
        except ValueError:
            await update.message.reply_text("Uso: /autofix patch <número>")
        return

    # Default: show last 5 proposed patches
    await _send_pending_patches(update)


async def _send_pending_patches(update: Update) -> None:
    from autofix import get_last_patches

    patches = get_last_patches(5)
    proposed = [p for p in patches if p.get("status") == "proposed"]

    if not proposed:
        await update.message.reply_text(
            "✅ Nenhum patch pendente de aprovação.\n\n"
            "Use /autofix status para ver todos os tickets."
        )
        return

    lines = ["🔧 *Patches pendentes de aprovação:*\n"]
    for i, patch in enumerate(reversed(proposed), start=1):
        ticket_id = patch.get("ticket_id", "?")
        error_type = patch.get("error_type", "?")
        patch_type = patch.get("patch_type", "?")
        lines.append(f"{i}. `{ticket_id}` — `{error_type}` ({patch_type})")

    lines.append("\nUse /autofix patch <N> para ver detalhes e aprovar.")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def _send_ticket_summary(update: Update) -> None:
    from autofix import get_last_patches

    patches = get_last_patches(20)
    total = len(patches)
    proposed = sum(1 for p in patches if p.get("status") == "proposed")
    approved = sum(1 for p in patches if p.get("status") == "approved")
    rejected = sum(1 for p in patches if p.get("status") == "rejected")

    text = (
        f"📊 *AutoFix Status*\n\n"
        f"Total de patches: {total}\n"
        f"⏳ Pendentes: {proposed}\n"
        f"✅ Aprovados: {approved}\n"
        f"❌ Rejeitados: {rejected}\n\n"
        f"Use /autofix para ver patches pendentes."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def _send_patch_detail(update: Update, index: int) -> None:
    from autofix import get_patch_by_index

    patch = get_patch_by_index(index)
    if not patch:
        await update.message.reply_text(f"Patch #{index} não encontrado.")
        return

    ticket_id = patch.get("ticket_id", "?")
    error_type = patch.get("error_type", "?")
    patch_type = patch.get("patch_type", "?")
    status = patch.get("status", "?")
    notes = patch.get("notes", "Sem notas.")[:400]
    diff_preview = (patch.get("diff", "") or "")[:500]

    text = (
        f"🔍 *Patch #{index}*\n\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*Erro:* `{error_type}`\n"
        f"*Tipo:* `{patch_type}`\n"
        f"*Status:* `{status}`\n\n"
        f"*O que faz:*\n{notes}\n\n"
        f"*Diff:*\n```\n{diff_preview}\n```"
    )

    if status == "proposed":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Aprovar e abrir PR",
                        callback_data=f"autofix_approve:{index}",
                    ),
                    InlineKeyboardButton(
                        "❌ Rejeitar", callback_data=f"autofix_reject:{index}"
                    ),
                ]
            ]
        )
        await update.message.reply_text(
            text, parse_mode="Markdown", reply_markup=keyboard
        )
    else:
        await update.message.reply_text(text, parse_mode="Markdown")


# ---------------------------------------------------------------------------
# Inline button callbacks
# ---------------------------------------------------------------------------


async def autofix_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle ✅ Aprovar / ❌ Rejeitar button taps."""
    query = update.callback_query
    await query.answer()

    chat_id = query.from_user.id
    if not _is_admin(chat_id):
        await query.edit_message_text("⛔ Acesso restrito ao administrador.")
        return

    data = query.data or ""

    if data.startswith("autofix_approve:"):
        index = int(data.split(":")[1])
        await _handle_approve(query, index)

    elif data.startswith("autofix_reject:"):
        index = int(data.split(":")[1])
        await _handle_reject(query, index)


async def _handle_approve(query, index: int) -> None:
    from autofix import approve_patch
    from autofix.github_pr import create_pr_for_patch
    from autofix.notifier import notify_pr_created, notify_pr_failed

    await query.edit_message_text(
        f"⏳ Aprovando patch #{index} e criando PR no GitHub...",
        parse_mode="Markdown",
    )

    patch = approve_patch(
        index, by=str(query.from_user.id), reason="Approved via Telegram"
    )
    if not patch:
        await query.edit_message_text(
            f"❌ Patch #{index} não encontrado ou já processado."
        )
        return

    ticket_id = patch.get("ticket_id", "?")

    # Run PR creation in a thread to avoid blocking the event loop
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, create_pr_for_patch, patch)

    if result["success"]:
        pr_url = result["pr_url"]
        await query.edit_message_text(
            f"✅ *Patch #{index} aprovado!*\n\n"
            f"*Ticket:* `{ticket_id}`\n"
            f"*PR criado:* {pr_url}\n\n"
            f"Revise o diff e faça o merge quando estiver pronto.",
            parse_mode="Markdown",
        )
        await notify_pr_created(index, pr_url, ticket_id)
    else:
        error = result.get("error", "Erro desconhecido")
        await query.edit_message_text(
            f"⚠️ *Patch aprovado, mas PR falhou*\n\n"
            f"*Ticket:* `{ticket_id}`\n"
            f"*Erro:* {error}\n\n"
            f"O patch foi marcado como aprovado. Abra o PR manualmente se necessário.",
            parse_mode="Markdown",
        )
        await notify_pr_failed(index, ticket_id, error)


async def _handle_reject(query, index: int) -> None:
    from autofix import reject_patch

    patch = reject_patch(
        index, by=str(query.from_user.id), reason="Rejected via Telegram"
    )
    if not patch:
        await query.edit_message_text(
            f"❌ Patch #{index} não encontrado ou já processado."
        )
        return

    ticket_id = patch.get("ticket_id", "?")
    error_type = patch.get("error_type", "?")

    await query.edit_message_text(
        f"❌ *Patch #{index} rejeitado.*\n\n"
        f"*Ticket:* `{ticket_id}`\n"
        f"*Erro:* `{error_type}`\n\n"
        f"Nenhuma alteração foi feita no código.",
        parse_mode="Markdown",
    )


# ---------------------------------------------------------------------------
# Handler registration
# ---------------------------------------------------------------------------


def register_autofix_handlers(application) -> None:
    """Register /autofix command and callback handlers with the bot application."""
    application.add_handler(CommandHandler("autofix", autofix_command))
    application.add_handler(
        CallbackQueryHandler(autofix_callback, pattern=r"^autofix_(approve|reject):")
    )
    logger.info("AutoFix Telegram handlers registered")
