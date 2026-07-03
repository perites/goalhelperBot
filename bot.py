import os

from dotenv import load_dotenv
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application, )
from telegram.ext import (
    CommandHandler,
    ContextTypes,
)

from database import User, Status
from database import initialize_database
from messages_texts import *
from onboarding import onboarding_conv_handler

load_dotenv()
initialize_database()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    User.get_or_create(telegram_id=update.effective_user.id, status=Status.JUSTSTARTED,
                       username=update.effective_user.username)

    keyboard = [
        [InlineKeyboardButton(start_message_button, callback_data="start:onboarding")]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(start_message, reply_markup=reply_markup)


# async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()
#     print("fdsfsdf")
#     if query.data == "begin_onboarding":
#         await query.message.reply_text("/begin_onboarding")


def main():
    app = Application.builder().token(os.getenv("BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))

    app.add_handler(onboarding_conv_handler)
    # app.add_handler(CallbackQueryHandler(button_handler))
    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
