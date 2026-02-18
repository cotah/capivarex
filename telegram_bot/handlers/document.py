"""Document handler for the refactored Telegram bot."""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.core import get_service
from telegram_bot.utils.response_sender import send_agent_response

logger = logging.getLogger("capivarax.telegram.handlers.document")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle document uploads with processing.

    Downloads the document from Telegram, extracts content based on file type,
    then processes it through the bot orchestrator.

    Args:
        update: Telegram update object.
        context: Telegram context object.
    """
    doc = update.message.document
    logger.info(
        "Document received from user_id=%s chat_id=%s file_name=%s",
        update.effective_user.id if update.effective_user else "unknown",
        update.effective_chat.id if update.effective_chat else "unknown",
        doc.file_name if doc else "unknown",
    )

    bot = context.application.bot_data.get("capivarax_bot")
    if not bot:
        await update.message.reply_text("Bot nao inicializado.")
        return

    if not doc:
        return

    try:
        # Download document
        doc_file = await doc.get_file()
        doc_bytes = await doc_file.download_as_bytearray()

        # Get file manager service
        file_manager = get_service("file_manager")

        if not file_manager:
            await update.message.reply_text("Servico de arquivos nao disponivel.")
            return

        # Save temporarily and process
        file_path = await file_manager.save_temp_file(doc.file_name, doc_bytes)

        # Process based on file type
        if doc.file_name.endswith(".pdf"):
            content = await file_manager.extract_pdf_text(file_path)
        elif doc.file_name.endswith((".txt", ".md")):
            content = doc_bytes.decode("utf-8")
        elif doc.file_name.endswith((".py", ".js", ".java", ".ts", ".go", ".rs")):
            # Code file - route to dev agent
            content = doc_bytes.decode("utf-8")
        else:
            await update.message.reply_text(
                f"Tipo de arquivo nao suportado: {doc.file_name}"
            )
            return

        # Process content
        user_context = {
            "user_id": update.effective_user.id,
            "chat_id": update.effective_chat.id,
            "username": update.effective_user.username,
            "input_type": "document",
            "file_name": doc.file_name,
            "file_content": content,
        }

        prompt = f"Analisar documento: {doc.file_name}\n\n{content[:1000]}..."
        result = await bot.process_message(prompt, user_context)
        await send_agent_response(update, result)

    except Exception as e:
        logger.error("Error processing document: %s", e, exc_info=True)
        await update.message.reply_text("Erro ao processar documento.")

