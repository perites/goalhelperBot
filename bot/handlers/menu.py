from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    MessageHandler,
    ContextTypes,
    filters, CallbackQueryHandler,
)

from bot.config import CONTINUE_ACTION, EDIT_TIME_PREFIX
from bot.enums import Status
from bot.logs import get_logger
from bot.services.cycle import pause_user, resume_user
from bot.services.questions import close_open_answers
from bot.services.slots import (
    build_slots_keyboard,
    format_slots,
    save_slots,
    saved_slots,
    slot_from_callback,
    toggle_slot,
)
from bot.services.stats import build_stats_text
from bot.texts import *
from bot.utils import current_user

logger = get_logger(__name__)


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            [menu_my_info_button, menu_stats_button],
            [menu_contacts_button, menu_edit_times_button],
            [menu_pause_button, menu_finish_button],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


async def _require_participant(update):
    """A reply keyboard lives in the Telegram client, not in our database, so
    it can outlive the profile behind it — after an abandoned onboarding, or
    a rebuilt database. Answer those taps politely and clear the stale
    keyboard instead of indexing into a half-filled row.
    """
    user = current_user(update)

    if user is not None and user.intention_type is not None:
        return user

    logger.info(
        "Menu tap from user=%s with no completed profile; clearing keyboard",
        update.effective_user.id,
    )
    await update.message.reply_text(
        menu_not_participant_message,
        reply_markup=ReplyKeyboardRemove(),
    )

    return None


async def handle_my_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_participant(update)
    if user is None:
        return

    await update.message.reply_text(
        menu_my_info_template.format(
            intention=user.intention,
            name=user.name,
            category=category_labels[user.intention_type],
            times=format_slots(saved_slots(user)),
            day=user.cycle_day,
            total=user.cycle_length,
        )
    )


async def handle_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(menu_contacts_message)


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_participant(update)
    if user is None:
        return

    await update.message.reply_text(build_stats_text(user))


async def handle_edit_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_participant(update)
    if user is None:
        return

    # Start from what's actually saved, so reopening the editor never shows stale toggles.
    selected = saved_slots(user)
    context.user_data["edit_time_slots"] = selected

    await update.message.reply_text(
        slots_prompt_message,
        reply_markup=build_slots_keyboard(selected, EDIT_TIME_PREFIX, slots_save_button),
    )


async def handle_edit_time_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected = toggle_slot(context.user_data.setdefault("edit_time_slots", set()), slot_from_callback(query.data))

    await query.edit_message_reply_markup(
        reply_markup=build_slots_keyboard(selected, EDIT_TIME_PREFIX, slots_save_button),
    )


async def handle_edit_time_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("edit_time_slots", set())

    if not selected:
        await query.answer(slots_empty_warning, show_alert=True)
        return

    await query.answer()

    user = current_user(update)
    if user is None:
        return

    save_slots(user.telegram_id, selected)
    context.user_data.pop("edit_time_slots", None)

    logger.info("user=%s changed slots to %s", user.telegram_id, sorted(selected))

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(menu_edit_times_saved_template.format(times=format_slots(selected)))


async def handle_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await _require_participant(update)
    if user is None:
        return

    if user.is_paused:
        keyboard = [[InlineKeyboardButton(menu_resume_button, callback_data="pause:resume")]]
        await update.message.reply_text(
            menu_already_paused_template.format(days_left=user.pause_days_left),
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(menu_pause_confirm_yes_button, callback_data="pause:yes"),
            InlineKeyboardButton(menu_pause_confirm_no_button, callback_data="pause:no"),
        ]
    ]

    await update.message.reply_text(
        menu_pause_confirm_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_pause_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    user = current_user(update)
    if user is None or user.intention_type is None:
        return

    if query.data == "pause:no":
        await query.message.reply_text(menu_pause_cancelled_message)
        return

    if query.data == "pause:resume":
        resume_user(user)
        await query.message.reply_text(menu_resumed_message)
        return

    pause_user(user)

    await query.message.reply_text(menu_paused_message)


async def handle_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Guarded because confirming sets STOPPED, and a STOPPED user can never
    # join — a stale keyboard must not be able to lock someone out.
    if await _require_participant(update) is None:
        return

    keyboard = [
        [
            InlineKeyboardButton(menu_finish_confirm_yes_button, callback_data="finish:yes"),
            InlineKeyboardButton(menu_finish_confirm_no_button, callback_data="finish:no"),
        ]
    ]

    await update.message.reply_text(
        menu_finish_confirm_message,
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_finish_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_reply_markup(reply_markup=None)

    if query.data == "finish:no":
        await query.message.reply_text(menu_finish_cancelled_message)
        return

    user = current_user(update)
    if user is None or user.intention_type is None:
        return

    # Close out anything still open so it isn't left dangling as unanswered.
    close_open_answers(user)

    user.status = Status.STOPPED
    user.save()

    logger.info("user=%s ended participation early on day %s", user.telegram_id, user.cycle_day)

    await query.message.reply_text(
        menu_finish_confirmed_message,
        reply_markup=ReplyKeyboardRemove(),
    )


my_info_handler = MessageHandler(filters.Text([menu_my_info_button]), handle_my_info)
contacts_handler = MessageHandler(filters.Text([menu_contacts_button]), handle_contacts)
stats_handler = MessageHandler(filters.Text([menu_stats_button]), handle_stats)
edit_times_handler = MessageHandler(filters.Text([menu_edit_times_button]), handle_edit_times)
pause_handler = MessageHandler(filters.Text([menu_pause_button]), handle_pause)
pause_confirm_handler = CallbackQueryHandler(handle_pause_confirm, pattern="^pause:")
finish_handler = MessageHandler(filters.Text([menu_finish_button]), handle_finish)

edit_time_save_handler = CallbackQueryHandler(
    handle_edit_time_save, pattern=f"^{EDIT_TIME_PREFIX}:{CONTINUE_ACTION}$"
)
edit_time_toggle_handler = CallbackQueryHandler(
    handle_edit_time_toggle, pattern=f"^{EDIT_TIME_PREFIX}:"
)

finish_confirm_handler = CallbackQueryHandler(handle_finish_confirm, pattern="^finish:")
