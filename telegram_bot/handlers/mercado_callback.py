"""
Callback handler for mercado inline-keyboard buttons.

Handles callbacks with pattern ``mr:{action}:{params}``
"""

import logging
import os
import tempfile
from datetime import date
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.ext import ContextTypes

from services.core import get_service
from services.i18n import t

logger = logging.getLogger("capivarex.telegram.handlers.mercado_callback")


async def handle_mercado_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Main dispatcher for mercado inline button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data or ""
    parts = data.split(":")
    if len(parts) < 2:
        return

    action = parts[1]
    lang = "en"  # Will be resolved below

    # Resolve user language from user_preferences table
    try:
        user_id = update.effective_user.id
        db_svc = get_service("database")
        if db_svc and db_svc.is_initialized():
            # First resolve telegram_chat_id → user UUID
            user_row = await db_svc.get_user_by_telegram_id(str(user_id))
            if user_row:
                uuid = user_row.get("id")
                if uuid:
                    pref_res = (
                        db_svc.client.table("user_preferences")
                        .select("preferred_language")
                        .eq("user_id", uuid)
                        .limit(1)
                        .execute()
                    )
                    if pref_res.data:
                        lang = pref_res.data[0].get("preferred_language", "en") or "en"
    except Exception:
        pass

    chat_id = str(update.effective_chat.id)

    try:
        if action == "months":
            await _show_months(query, chat_id, lang)
        elif action == "report" and len(parts) >= 4:
            year = int(parts[2])
            month = int(parts[3])
            await _show_report(query, chat_id, year, month, lang)
        elif action == "export" and len(parts) >= 4:
            year = int(parts[2])
            month = int(parts[3])
            await _send_excel(query, chat_id, year, month, lang)
        elif action == "view_list":
            await _show_list(query, chat_id, lang)
        elif action == "clear_done":
            await _clear_list(query, chat_id, lang)
        elif action == "snooze":
            await _snooze_reminder(query, lang)
        elif action == "ranking":
            await _show_ranking(query, chat_id, lang)
        elif action == "back":
            await _show_months(query, chat_id, lang)
        else:
            await query.edit_message_text("❓")
    except Exception as e:
        logger.error("Mercado callback error: %s", e, exc_info=True)
        await query.edit_message_text(t("mercado_report_error", lang=lang))


async def _show_months(query, chat_id: str, lang: str) -> None:
    """Show grid of last 6 months as buttons."""
    today = date.today()
    buttons = []
    row = []

    for i in range(6):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1

        month_name = t(f"month_{m}", lang=lang)
        # Short label: "Mar 26" or "Dez 25"
        short_label = f"{month_name[:3]} {y % 100:02d}"
        row.append(
            InlineKeyboardButton(
                short_label,
                callback_data=f"mr:report:{y}:{m}",
            )
        )
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    text = t("mercado_interactive_choose_month", lang=lang)
    await query.edit_message_text(
        text=text,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _show_report(query, chat_id: str, year: int, month: int, lang: str) -> None:
    """Show monthly report with action buttons."""
    svc = get_service("mercado")
    if not svc:
        await query.edit_message_text(t("mercado_report_error", lang=lang))
        return

    if not svc.is_initialized():
        await svc.initialize()

    result = await svc.relatorio_mensal(chat_id, mes=month, ano=year, lang=lang)
    report_text = result.get("mensagem", t("mercado_report_error", lang=lang))

    # Action buttons
    buttons = [
        [
            InlineKeyboardButton(
                t("mercado_btn_export", lang=lang),
                callback_data=f"mr:export:{year}:{month}",
            ),
            InlineKeyboardButton(
                t("mercado_btn_ranking", lang=lang),
                callback_data="mr:ranking",
            ),
        ],
        [
            InlineKeyboardButton(
                t("mercado_btn_back", lang=lang),
                callback_data="mr:back",
            ),
        ],
    ]

    await query.edit_message_text(
        text=report_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def _send_excel(query, chat_id: str, year: int, month: int, lang: str) -> None:
    """Generate and send Excel file."""
    svc = get_service("mercado")
    if not svc:
        await query.edit_message_text(t("mercado_report_error", lang=lang))
        return

    if not svc.is_initialized():
        await svc.initialize()

    await query.edit_message_text(t("mercado_export_generating", lang=lang))

    result = await svc.gerar_excel_mensal(
        chat_id=chat_id, mes=month, ano=year, lang=lang
    )

    if not result.get("sucesso"):
        month_name = t(f"month_{month}", lang=lang)
        await query.edit_message_text(
            result.get(
                "mensagem",
                t(
                    "mercado_no_purchases_month",
                    lang=lang,
                    month=month_name,
                    year=year,
                ),
            )
        )
        return

    # Save to temp file and send
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx", prefix="mercado_")
    tmp.write(result["excel_bytes"])
    tmp.close()

    try:
        with open(tmp.name, "rb") as f:
            await query.message.reply_document(
                document=f,
                filename=result["filename"],
                caption=f"📊 {result.get('resumo', '')}",
            )
        # Update the "generating..." message
        await query.edit_message_text(t("mercado_excel_sent", lang=lang))
    finally:
        os.unlink(tmp.name)


async def _show_ranking(query, chat_id: str, lang: str) -> None:
    """Show store ranking with back button."""
    svc = get_service("mercado")
    if not svc:
        await query.edit_message_text(t("mercado_report_error", lang=lang))
        return

    if not svc.is_initialized():
        await svc.initialize()

    result = await svc.ranking_mercados(chat_id, lang=lang)
    ranking_text = result.get("mensagem", t("mercado_ranking_error", lang=lang))

    buttons = [
        [
            InlineKeyboardButton(
                t("mercado_btn_back", lang=lang),
                callback_data="mr:back",
            ),
        ]
    ]

    await query.edit_message_text(
        text=ranking_text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


def build_months_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """
    Build the initial months keyboard.

    Used by mercado_agent to send the first message with buttons.
    """
    today = date.today()
    buttons = []
    row = []

    for i in range(6):
        m = today.month - i
        y = today.year
        while m <= 0:
            m += 12
            y -= 1

        month_name = t(f"month_{m}", lang=lang)
        short_label = f"{month_name[:3]} {y % 100:02d}"
        row.append(
            InlineKeyboardButton(
                short_label,
                callback_data=f"mr:report:{y}:{m}",
            )
        )
        if len(row) == 3:
            buttons.append(row)
            row = []

    if row:
        buttons.append(row)

    return InlineKeyboardMarkup(buttons)


# ── Shopping Reminder Keyboard & Handlers ─────────────────────────────────────


def build_shopping_reminder_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Build inline keyboard for shopping reminder notification."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    t("mercado_btn_view_list", lang=lang),
                    callback_data="mr:view_list",
                ),
                InlineKeyboardButton(
                    t("mercado_btn_clear_done", lang=lang),
                    callback_data="mr:clear_done",
                ),
            ],
            [
                InlineKeyboardButton(
                    t("mercado_btn_snooze", lang=lang),
                    callback_data="mr:snooze",
                ),
            ],
        ]
    )


async def _show_list(query, chat_id: str, lang: str) -> None:
    """Show current shopping list."""
    svc = get_service("mercado")
    if not svc:
        await query.edit_message_text(t("mercado_service_unavailable", lang=lang))
        return

    if not svc.is_initialized():
        await svc.initialize()

    result = await svc.ver_lista(user_id=chat_id, lang=lang)
    list_text = result.get("mensagem", t("mercado_list_empty", lang=lang))

    buttons = [
        [
            InlineKeyboardButton(
                t("mercado_btn_clear_done", lang=lang),
                callback_data="mr:clear_done",
            ),
        ]
    ]
    await query.edit_message_text(
        text=list_text,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _clear_list(query, chat_id: str, lang: str) -> None:
    """Clear shopping list (user went shopping)."""
    svc = get_service("mercado")
    if not svc:
        await query.edit_message_text(t("mercado_service_unavailable", lang=lang))
        return

    if not svc.is_initialized():
        await svc.initialize()

    await svc.limpar_lista(user_id=chat_id, lang=lang)
    await query.edit_message_text(t("mercado_list_cleared_done", lang=lang))


async def _snooze_reminder(query, lang: str) -> None:
    """Snooze: just dismiss the notification."""
    await query.edit_message_text(t("mercado_reminder_snoozed", lang=lang))
