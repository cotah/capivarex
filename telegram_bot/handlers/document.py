"""Document handler for the refactored Telegram bot."""
import logging
import os
import tempfile

from telegram import Update
from telegram.ext import ContextTypes

from services.core import get_service
from telegram_bot.utils.response_sender import send_agent_response
from utils.request_processor import RequestProcessor

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
    processor = RequestProcessor(user_identifier=update.effective_user.id)
    if not await processor.process():
        return

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

        # Save to temp file
        suffix = os.path.splitext(doc.file_name)[1] if doc.file_name else ".tmp"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(doc_bytes)
            file_path = tmp.name

        # Process based on file type
        try:
            if file_path.endswith(".pdf"):
                try:
                    import PyPDF2
                    with open(file_path, "rb") as f:
                        reader = PyPDF2.PdfReader(f)
                        content = "\n".join(page.extract_text() or "" for page in reader.pages)
                except ImportError:
                    content = "(PDF reading not available - PyPDF2 not installed)"
            elif doc.file_name.endswith((".txt", ".md")):
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            elif doc.file_name.endswith((".py", ".js", ".java", ".ts", ".go", ".rs")):
                # Code file - route to dev agent
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
            else:
                await update.message.reply_text(
                    f"Tipo de arquivo nao suportado: {doc.file_name}"
                )
                return
        finally:
            os.unlink(file_path)

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
