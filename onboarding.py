from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters, CallbackQueryHandler,
)

from helpers import get_message
from messages_texts import *

PERSONAL_DATA_PROCESSING, NAME, AGE = range(3)


async def begin_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await ask_personal_data_processing(update)


async def ask_personal_data_processing(update: Update):
    message = get_message(update)
    keyboard = [
        [
            InlineKeyboardButton(onboarding_personal_data_message_yes, callback_data="personal_data:yes"),
            InlineKeyboardButton(onboarding_personal_data_message_no, callback_data="personal_data:no"),
        ]
    ]

    await message.reply_text(onboarding_personal_data_message, reply_markup=InlineKeyboardMarkup(keyboard), )

    return PERSONAL_DATA_PROCESSING


async def handle_personal_data_processing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "notifications_yes":
        context.user_data["notifications"] = True
    else:
        context.user_data["notifications"] = False

    await query.edit_message_text(
        f"Notifications: {context.user_data['notifications']}"
    )
    print(context.user_data)

    await context.bot.send_message(text=
                                   f"Thank you!\n\n"
                                   f"Name: {context.user_data['name']}\n"
                                   f"Age: {context.user_data['age']}"
                                   f"Notifications: {context.user_data['notifications']}",
                                   chat_id=update.effective_chat.id
                                   )

    return ConversationHandler.END


async def ask_name(update):
    message = get_message(update)
    await message.reply_text("Great! Let's begin.\n\n"
                             "What is your name?"
                             )

    return NAME


async def ask_age(update, context):
    message = get_message(update)
    await message.reply_text(
        f"Nice to meet you, {context.user_data['name']}!\n"
        "How old are you?"
    )

    return AGE


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    return await ask_age(update, context)


async def handle_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    age = update.message.text

    if not age.isdigit():
        await update.message.reply_text("Please enter a valid age.")
        return AGE

    context.user_data["age"] = int(age)

    return await ask_personal_data_processing(update)


# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text(
#         'Привіт. Я — “Я хочу бот”.'
#         'Я допоможу тобі протягом 30 днів тримати фокус на твоєму намірі, помічати свій стан, фіксувати маленькі кроки й бачити власний рух.'
#     )
#
#     keyboard = [
#         [InlineKeyboardButton("🚀 Start", callback_data="start_form")]
#     ]
#
#     reply_markup = InlineKeyboardMarkup(keyboard)
#
#     return NAME


# async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     context.user_data["name"] = update.message.text
#
#     await update.message.reply_text(
#         f"Nice to meet you, {context.user_data['name']}!\n"
#         "How old are you?"
#     )
#
#     return AGE


# async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     age = update.message.text
#
#     if not age.isdigit():
#         await update.message.reply_text("Please enter a valid age.")
#         return AGE
#
#     context.user_data["age"] = int(age)
#
#     keyboard = [
#         [
#             InlineKeyboardButton("✅ Yes", callback_data="notifications_yes"),
#             InlineKeyboardButton("❌ No", callback_data="notifications_no"),
#         ]
#     ]
#
#     await update.message.reply_text(
#         "Would you like to receive notifications?",
#         reply_markup=InlineKeyboardMarkup(keyboard),
#     )
#
#     return NOTIFICATIONS


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


onboarding_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(begin_onboarding, pattern="^start:onboarding$")
    ],
    states={
        PERSONAL_DATA_PROCESSING: [
            CallbackQueryHandler(handle_personal_data_processing)
        ],

        NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)
        ],
        AGE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_age)
        ],

    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
