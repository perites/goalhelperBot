"""Small helpers shared across handlers."""
from telegram import MaybeInaccessibleMessage, Message, Update

from core.models import User


def get_message(update: Update) -> Message | MaybeInaccessibleMessage:
    """The message to reply to, whether the update came from a message or a
    button tap."""
    if update.message:
        return update.message

    if update.callback_query:
        return update.callback_query.message


def current_user(update: Update):
    return User.get_or_none(User.telegram_id == update.effective_user.id)
