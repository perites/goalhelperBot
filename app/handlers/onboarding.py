from app import clock

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters, CallbackQueryHandler,
)

from app.services.cohort import join_cohort, put_on_waitlist
from app.config import CONTINUE_ACTION, TIME_SLOT_PREFIX
from app.models import User
from app.enums import Status
from app.logs import describe, get_logger
from app.services.questions import deliver_question
from app.utils import current_user, get_message
from app.handlers.menu import main_menu_keyboard
from app.texts import *
from app.services.slots import (
    build_slots_keyboard,
    format_slots,
    save_slots,
    slot_key,
    toggle_slot,
)

logger = get_logger(__name__)

FREE_TEXT = filters.TEXT & ~filters.COMMAND & ~filters.Text(main_menu_buttons)

CONSENT, NAME, CATEGORY, INTENTION, TIME_SLOTS, CONFIRM, READY = range(7)


async def begin_onboarding(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    return await ask_consent(update)


async def ask_consent(update: Update):
    message = get_message(update)
    keyboard = [
        [
            InlineKeyboardButton(consent_yes_button, callback_data="consent:yes"),
            InlineKeyboardButton(consent_no_button, callback_data="consent:no"),
        ]
    ]

    await message.reply_text(consent_message, reply_markup=InlineKeyboardMarkup(keyboard))

    return CONSENT


async def handle_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "consent:no":
        User.update(consent=False, status=Status.DECLINED).where(
            User.telegram_id == update.effective_user.id
        ).execute()
        logger.info("user=%s declined data processing", update.effective_user.id)
        await query.edit_message_text(consent_declined_message)
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
        slots_prompt_message,
        reply_markup=build_slots_keyboard(selected, TIME_SLOT_PREFIX, slots_continue_button),
    )

    return TIME_SLOTS


async def handle_time_slot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected = toggle_slot(context.user_data.setdefault("time_slots", set()), slot_key(query.data))

    await query.edit_message_reply_markup(
        reply_markup=build_slots_keyboard(selected, TIME_SLOT_PREFIX, slots_continue_button),
    )

    return TIME_SLOTS


async def handle_time_slots_continue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    if not context.user_data.get("time_slots"):
        await query.answer(slots_empty_warning, show_alert=True)
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
        logger.warning(
            "user=%s finished onboarding but the cohort filled up meanwhile", telegram_id
        )
        put_on_waitlist(user)
        await query.message.reply_text(cohort_waitlist_full_message)
        return ConversationHandler.END

    User.update(
        name=data["name"],
        intention=data["intention"],
        intention_type=data["intention_type"],
        consent=True,
        status=Status.ACTIVE,
        date_started=clock.now_kyiv(),
    ).where(User.telegram_id == telegram_id).execute()

    save_slots(telegram_id, data["time_slots"])

    logger.info(
        "user=%s completed onboarding: category=%s slots=%s intention=%s",
        telegram_id, data["intention_type"], sorted(data["time_slots"]),
        describe(data["intention"]),
    )

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

    user = current_user(update)

    # The menu is a reply keyboard, which can't ride along on an edit and
    # can't share a message with the question's inline buttons — so it gets
    # its own short message, sent before the question lands.
    await query.message.reply_text(
        onboarding_menu_ready_message,
        reply_markup=main_menu_keyboard(),
    )

    logger.info("user=%s finished onboarding; sending first question", user.telegram_id)
    await deliver_question(context.bot, user, reason="onboarding")

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
        # Menu buttons are plain text, and a reply keyboard can still be on
        # screen from an earlier run — excluding them stops "📊 Моя
        # статистика" being saved as somebody's name.
        NAME: [MessageHandler(FREE_TEXT, handle_name)],
        CATEGORY: [CallbackQueryHandler(handle_category, pattern="^category:")],
        INTENTION: [MessageHandler(FREE_TEXT, handle_intention)],
        TIME_SLOTS: [
            CallbackQueryHandler(handle_time_slots_continue, pattern=f"^{TIME_SLOT_PREFIX}:{CONTINUE_ACTION}$"),
            CallbackQueryHandler(handle_time_slot_toggle, pattern=f"^{TIME_SLOT_PREFIX}:"),
        ],
        CONFIRM: [CallbackQueryHandler(handle_confirm, pattern="^confirm:")],
        READY: [CallbackQueryHandler(handle_ready, pattern="^ready:yes$")],
    },
    fallbacks=[CommandHandler("cancel", cancel)],

    # Without this, tapping "Почати" a second time is silently dropped:
    # entry points are only consulted when the user isn't already inside a
    # conversation, so someone part-way through onboarding has no way back to
    # the start and the button just appears dead.
    allow_reentry=True,
)

