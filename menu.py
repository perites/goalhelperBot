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

from cohort import pause_user, resume_user
from config import EDIT_TIME_PREFIX
from database import User, Answer, Status
from messages_texts import *
from stats import build_stats_text
from time_slots import (
    build_keyboard,
    toggle,
    slot_key,
    saved_slots,
    save_slots,
    format_slots,
    CONTINUE,
)



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


def _current_user(update: Update):
    return User.get_or_none(User.telegram_id == update.effective_user.id)


def _user_times(user):
    times = [slot.time for slot in user.times]

    return ", ".join(time.strftime("%H:%M") for time in sorted(times))


async def handle_my_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _current_user(update)
    if user is None:
        return

    await update.message.reply_text(
        menu_my_info_template.format(
            intention=user.intention,
            name=user.name,
            category=category_labels[user.intention_type],
            times=_user_times(user),
            day=user.cycle_day,
            total=user.cycle_length,
        )
    )


async def handle_contacts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(menu_contacts_message)


async def handle_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _current_user(update)
    if user is None:
        return

    await update.message.reply_text(build_stats_text(user))


async def handle_edit_times(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _current_user(update)
    if user is None:
        return

    # Start from what's actually saved, so reopening the editor never shows stale toggles.
    selected = saved_slots(user)
    context.user_data["edit_time_slots"] = selected

    await update.message.reply_text(
        menu_edit_times_message,
        reply_markup=build_keyboard(selected, EDIT_TIME_PREFIX, menu_edit_times_save_button),
    )


async def handle_edit_time_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    selected = toggle(context.user_data.setdefault("edit_time_slots", set()), slot_key(query.data))

    await query.edit_message_reply_markup(
        reply_markup=build_keyboard(selected, EDIT_TIME_PREFIX, menu_edit_times_save_button),
    )


async def handle_edit_time_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    selected = context.user_data.get("edit_time_slots", set())

    if not selected:
        await query.answer(onboarding_time_slots_empty_warning, show_alert=True)
        return

    await query.answer()

    user = _current_user(update)
    if user is None:
        return

    save_slots(user.telegram_id, selected)
    context.user_data.pop("edit_time_slots", None)

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(menu_edit_times_saved_template.format(times=format_slots(selected)))


async def handle_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = _current_user(update)
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

    user = _current_user(update)
    if user is None:
        return

    if query.data == "pause:no":
        await query.message.reply_text(menu_pause_cancelled_message)
        return

    if query.data == "pause:resume":
        resume_user(user)
        await query.message.reply_text(menu_resumed_message)
        return

    # Pausing shouldn't leave a question hanging open against the paused days.
    Answer.update(skipped=True).where(
        (Answer.user == user)
        & Answer.answered_at.is_null(True)
        & (Answer.skipped == False)  # noqa: E712 - peewee needs the comparison
    ).execute()

    pause_user(user)

    await query.message.reply_text(menu_paused_message)


async def handle_finish(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    user = _current_user(update)
    if user is None:
        return

    # Close out anything still open so it isn't left dangling as unanswered.
    Answer.update(skipped=True).where(
        (Answer.user == user)
        & Answer.answered_at.is_null(True)
        & (Answer.skipped == False)  # noqa: E712 - peewee needs the comparison
    ).execute()

    user.status = Status.STOPPED
    user.save()

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
    handle_edit_time_save, pattern=f"^{EDIT_TIME_PREFIX}:{CONTINUE}$"
)
edit_time_toggle_handler = CallbackQueryHandler(
    handle_edit_time_toggle, pattern=f"^{EDIT_TIME_PREFIX}:"
)
finish_confirm_handler = CallbackQueryHandler(handle_finish_confirm, pattern="^finish:")
