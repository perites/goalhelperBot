from clock import now_kyiv

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters, CallbackQueryHandler,
)

from cohort import join_cohort, put_on_waitlist
from database import User, Status
from helpers import get_message
from menu import main_menu_keyboard
from messages_texts import *
from time_slots import (
    build_keyboard,
    toggle,
    slot_key,
    save_slots,
    format_slots,
    CONTINUE,
)

CONSENT, NAME, CATEGORY, INTENTION, TIME_SLOTS, CONFIRM, READY = range(7)

TIME_SLOT_PREFIX = "time_slot"


async def begin_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    return await ask_consent(update)


async def ask_consent(update: Update):
    message = get_message(update)
    keyboard = [
        [
            InlineKeyboardButton(onboarding_personal_data_message_yes, callback_data="consent:yes"),
            InlineKeyboardButton(onboarding_personal_data_message_no, callback_data="consent:no"),
        ]
    ]

    await message.reply_text(onboarding_personal_data_message, reply_markup=InlineKeyboardMarkup(keyboard))

    return CONSENT


async def handle_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "consent:no":
        User.update(consent=False, status=Status.DECLINED).where(
            User.telegram_id == update.effective_user.id
        ).execute()
        await query.edit_message_text(onboarding_personal_data_declined_message)
        return ConversationHandler.END

    context.user_data["consent"] = True
    return await ask_name(update)


async def ask_name(update: Update):
    message = get_message(update)
    await message.reply_text(onboarding_name_message)

    return NAME


async def handle_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    return await ask_category(update)


async def ask_category(update: Update):
    message = get_message(update)
    keyboard = [
        [InlineKeyboardButton(label, callback_data=f"category:{index}")]
        for index, label in enumerate(category_labels)
    ]

    await message.reply_text(onboarding_category_message, reply_markup=InlineKeyboardMarkup(keyboard))

    return CATEGORY


async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    intention_type = int(query.data.split(":")[1])
    context.user_data["intention_type"] = intention_type
    return await ask_intention(update, intention_type)


async def ask_intention(update: Update, intention_type):
    message = get_message(update)
    await message.reply_text(onboarding_intention_message.format(intention_type=category_labels[intention_type]))

    return INTENTION


async def handle_intention(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["intention"] = update.message.text
    return await ask_time_slots(update, context)


async def ask_time_slots(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = get_message(update)
    selected = context.user_data.setdefault("time_slots", set())

    await message.reply_text(
        onboarding_time_slots_message,
        reply_markup=build_keyboard(selected, TIME_SLOT_PREFIX, onboarding_time_slots_continue_button),
    )

    return TIME_SLOTS


async def handle_time_slot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected = toggle(context.user_data.setdefault("time_slots", set()), slot_key(query.data))

    await query.edit_message_reply_markup(
        reply_markup=build_keyboard(selected, TIME_SLOT_PREFIX, onboarding_time_slots_continue_button),
    )

    return TIME_SLOTS


async def handle_time_slots_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not context.user_data.get("time_slots"):
        await query.answer(onboarding_time_slots_empty_warning, show_alert=True)
        return TIME_SLOTS

    await query.answer()
    return await ask_confirm(update, context)


async def ask_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = get_message(update)
    data = context.user_data

    text = onboarding_confirm_template.format(
        intention=data["intention"],
        name=data["name"],
        category=category_labels[data["intention_type"]],
        times=format_slots(data["time_slots"]),
    )
    keyboard = [
        [
            InlineKeyboardButton(onboarding_confirm_yes_button, callback_data="confirm:yes"),
            InlineKeyboardButton(onboarding_confirm_restart_button, callback_data="confirm:restart"),
        ]
    ]

    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    return CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "confirm:restart":
        context.user_data.clear()
        return await ask_consent(update)

    data = context.user_data
    telegram_id = update.effective_user.id
    user = User.get_by_id(telegram_id)

    # Seats are only taken on completed onboarding, so the cohort can fill up
    # while this user is still answering. Check again before claiming one.
    if not join_cohort(user):
        put_on_waitlist(user)
        await query.message.reply_text(cohort_waitlist_full_message)
        return ConversationHandler.END

    User.update(
        name=data["name"],
        intention=data["intention"],
        intention_type=data["intention_type"],
        consent=True,
        status=Status.ACTIVE,
        date_started=now_kyiv(),
    ).where(User.telegram_id == telegram_id).execute()

    save_slots(telegram_id, data["time_slots"])

    await query.edit_message_text(onboarding_confirmed_message)
    return await ask_ready(update)


async def ask_ready(update: Update):
    message = get_message(update)
    keyboard = [[InlineKeyboardButton(onboarding_ready_button, callback_data="ready:yes")]]

    await message.reply_text(onboarding_ready_message, reply_markup=InlineKeyboardMarkup(keyboard))

    return READY


async def handle_ready(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    # A reply keyboard can't ride along on an edit, so the menu needs its own message.
    await query.message.reply_text(
        onboarding_first_question_placeholder,
        reply_markup=main_menu_keyboard(),
    )

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END


onboarding_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(begin_onboarding, pattern="^start:onboarding$")
    ],
    states={
        CONSENT: [CallbackQueryHandler(handle_consent, pattern="^consent:")],
        NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_name)],
        CATEGORY: [CallbackQueryHandler(handle_category, pattern="^category:")],
        INTENTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_intention)],
        TIME_SLOTS: [
            CallbackQueryHandler(handle_time_slots_continue, pattern=f"^{TIME_SLOT_PREFIX}:{CONTINUE}$"),
            CallbackQueryHandler(handle_time_slot_toggle, pattern=f"^{TIME_SLOT_PREFIX}:"),
        ],
        CONFIRM: [CallbackQueryHandler(handle_confirm, pattern="^confirm:")],
        READY: [CallbackQueryHandler(handle_ready, pattern="^ready:yes$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],
)
