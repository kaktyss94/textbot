import logging
from telegram import Update
from telegram.ext import ContextTypes

def handle_error(error: Exception, message: str, update: Update = None, context: ContextTypes.DEFAULT_TYPE = None):
    logging.error(f"{message}: {error}")
    if update and context:
        context.bot.send_message(chat_id=update.effective_chat.id, text=f"Произошла ошибка: {message}")