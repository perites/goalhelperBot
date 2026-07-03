from telegram import Update, Message, MaybeInaccessibleMessage


def get_message(update: Update) -> Message | MaybeInaccessibleMessage:
    if update.message:
        return update.message

    if update.callback_query:
        return update.callback_query.message
