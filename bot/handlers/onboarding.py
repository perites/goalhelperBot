from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters, CallbackQueryHandler,
)

from bot import callbacks
from bot.delivery import deliver_question
from bot.handlers import slot_picker
from bot.handlers.menu import main_menu_keyboard
from core import clock
from core.enums import IntentionCategory, Status
from core.logs import describe, get_logger
from core.models import User
from core.services.cohort import join_cohort, put_on_waitlist
from core.services.slots import format_slots, save_slots
from bot.texts import *
from bot.utils import current_user, get_message

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
            InlineKeyboardButton(
                consent_yes_button,
                callback_data=callbacks.encode(callbacks.CONSENT, callbacks.YES),
            ),
            InlineKeyboardButton(
                consent_no_button,
                callback_data=callbacks.encode(callbacks.CONSENT, callbacks.NO),
            ),
        ]
    ]

    await message.reply_text(consent_message, reply_markup=InlineKeyboardMarkup(keyboard))

    return CONSENT


async def handle_consent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if callbacks.payload(query.data) == callbacks.NO:
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
        [InlineKeyboardButton(
            label, callback_data=callbacks.encode(callbacks.CATEGORY, index),
        )]
        for index, label in enumerate(category_labels)
    ]

    await message.reply_text(onboarding_category_message, reply_markup=InlineKeyboardMarkup(keyboard))

    return CATEGORY


async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chosen = callbacks.indexes(query.data)

    # The keyboard only ever offers the nine, but the data comes back from the
    # client — and this index is stored on the participant and later used to
    # look a label up by position.
    if chosen is None or chosen[0] not in set(IntentionCategory):
        return CATEGORY

    intention_type = chosen[0]
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
    selected = context.user_data.setdefault("time_slots", set())

    await slot_picker.show(
        get_message(update), selected, callbacks.TIME_SLOT, slots_continue_button,
    )

    return TIME_SLOTS


async def handle_time_slot_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await slot_picker.toggle(
        query,
        context.user_data.setdefault("time_slots", set()),
        callbacks.TIME_SLOT,
        slots_continue_button,
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
            InlineKeyboardButton(
                onboarding_confirm_yes_button,
                callback_data=callbacks.encode(callbacks.CONFIRM, callbacks.YES),
            ),
            InlineKeyboardButton(
                onboarding_confirm_restart_button,
                callback_data=callbacks.encode(callbacks.CONFIRM, callbacks.RESTART),
            ),
        ]
    ]

    await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    return CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if callbacks.payload(query.data) == callbacks.RESTART:
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
    keyboard = [[InlineKeyboardButton(
        onboarding_ready_button,
        callback_data=callbacks.encode(callbacks.READY, callbacks.YES),
    )]]

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

    # slot=None deliberately: this one belongs to no slot's run, so it neither
    # consumes a quota nor chains. The scheduler starts the real runs.
    await deliver_question(context.bot, user, reason="onboarding", slot=None)

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/cancel — leaves onboarding without finishing it.

    The reply used to be the English "Cancelled.", which any participant could
    reach by typing the command.
    """
    await update.message.reply_text(onboarding_cancelled_message)

    return ConversationHandler.END


onboarding_conv_handler = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(
            begin_onboarding,
            pattern=callbacks.exact(callbacks.START_ONBOARDING, callbacks.ONBOARDING),
        )
    ],
    states={
        CONSENT: [CallbackQueryHandler(
            handle_consent, pattern=callbacks.pattern(callbacks.CONSENT)
        )],
        # Menu buttons are plain text, and a reply keyboard can still be on
        # screen from an earlier run — excluding them stops "📊 Моя
        # статистика" being saved as somebody's name.
        NAME: [MessageHandler(FREE_TEXT, handle_name)],
        CATEGORY: [CallbackQueryHandler(
            handle_category, pattern=callbacks.pattern(callbacks.CATEGORY)
        )],
        INTENTION: [MessageHandler(FREE_TEXT, handle_intention)],
        TIME_SLOTS: [
            # Continue must be matched before the toggle pattern, which is a
            # prefix of it.
            CallbackQueryHandler(
                handle_time_slots_continue,
                pattern=callbacks.exact(callbacks.TIME_SLOT, callbacks.CONTINUE),
            ),
            CallbackQueryHandler(
                handle_time_slot_toggle,
                pattern=callbacks.pattern(callbacks.TIME_SLOT),
            ),
        ],
        CONFIRM: [CallbackQueryHandler(
            handle_confirm, pattern=callbacks.pattern(callbacks.CONFIRM)
        )],
        READY: [CallbackQueryHandler(
            handle_ready, pattern=callbacks.exact(callbacks.READY, callbacks.YES)
        )],
    },
    fallbacks=[CommandHandler("cancel", cancel)],

    # Survives a restart. Every button below is registered only inside this
    # conversation, so without the state on disk a restart mid-onboarding
    # leaves the participant tapping buttons that match no handler at all.
    # `name` is what the state is filed under, and changing it abandons
    # whatever is already stored.
    persistent=True,
    name="onboarding",

    # Without this, tapping "Почати" a second time is silently dropped:
    # entry points are only consulted when the user isn't already inside a
    # conversation, so someone part-way through onboarding has no way back to
    # the start and the button just appears dead.
    allow_reentry=True,
)
