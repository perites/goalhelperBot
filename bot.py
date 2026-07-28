import os

from dotenv import load_dotenv

load_dotenv()

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    Application
)

from askquestions import (
    seed_questions,
    ask_command_handler,
    answer_button_handler,
    skip_button_handler,
    option_button_handler,
    answer_text_handler,
)
from database import User, Status, initialize_database
from menu import (
    main_menu_keyboard,
    my_info_handler,
    contacts_handler,
    stats_handler,
    edit_times_handler,
    edit_time_save_handler,
    edit_time_toggle_handler,
    finish_handler,
    finish_confirm_handler,
)
from messages_texts import *
from onboarding import onboarding_conv_handler

initialize_database()
seed_questions()


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, _ = User.get_or_create(
        telegram_id=update.effective_user.id,
        defaults={"status": Status.ONBOARDING, "username": update.effective_user.username},
    )

    # Re-running onboarding would reset an active participant's cycle, so just
    # restore their menu instead.
    if user.status == Status.ACTIVE:
        await update.message.reply_text(start_message, reply_markup=main_menu_keyboard())
        return

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

    # Registered after the onboarding conversation so it claims its own text input first.
    app.add_handler(ask_command_handler)

    # Menu handlers must precede answer_text_handler, which otherwise catches all text.
    app.add_handler(my_info_handler)
    app.add_handler(contacts_handler)
    app.add_handler(stats_handler)
    app.add_handler(edit_times_handler)
    app.add_handler(finish_handler)

    # Save must be matched before the toggle pattern, which is a prefix of it.
    app.add_handler(edit_time_save_handler)
    app.add_handler(edit_time_toggle_handler)
    app.add_handler(finish_confirm_handler)

    app.add_handler(answer_button_handler)
    app.add_handler(skip_button_handler)
    app.add_handler(option_button_handler)
    app.add_handler(answer_text_handler)
    # app.add_handler(CallbackQueryHandler(button_handler))
    # app.add_error_handler(error_handler)

    print("Bot started...")
    app.run_polling()


if __name__ == "__main__":
    main()
