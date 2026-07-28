"""Catch-all for exceptions raised inside handlers.

This only logs — the alert handler is what forwards it to the admin chats, so
there's one delivery path rather than two competing ones. Notably it no longer
dumps the Update, whose repr contains the user's message text.
"""
from telegram import Update

from app.logs import get_logger

logger = get_logger(__name__)


async def error_handler(update, context):
    where = "no user"

    if isinstance(update, Update) and update.effective_user:
        where = f"user={update.effective_user.id}"

    logger.error(
        "Unhandled exception while processing update (%s)",
        where,
        exc_info=context.error,
    )
