"""/start — the front door, which also gates on the enrollment window."""
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CommandHandler, ContextTypes

from bot import callbacks
from bot.handlers.menu import main_menu_keyboard
from bot.texts import (
    cohort_already_stopped_message,
    cohort_finished_message,
    cohort_waitlist_closed_message,
    cohort_waitlist_full_message,
    cohort_waitlist_not_open_message,
    start_message,
    start_message_button,
)
from core.enums import EnrollmentState, Status
from core.logs import get_logger
from core.models import User
from core.services.cohort import enrollment_state, put_on_waitlist

logger = get_logger(__name__)

WAITLIST_MESSAGES = {
    EnrollmentState.FULL: cohort_waitlist_full_message,
    EnrollmentState.CLOSED: cohort_waitlist_closed_message,
    EnrollmentState.NOT_OPEN_YET: cohort_waitlist_not_open_message,
    EnrollmentState.NO_COHORT: cohort_waitlist_closed_message,
}


async def handle_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user, _ = User.get_or_create(
        telegram_id=update.effective_user.id,
        defaults={"status": Status.ONBOARDING},
    )

    # Re-running onboarding would reset an active participant's cycle, so just
    # restore their menu instead.
    if user.status in (Status.ACTIVE, Status.PAUSED):
        logger.info("/start from active user=%s on day %s", user.telegram_id, user.cycle_day)
        await update.message.reply_text(start_message, reply_markup=main_menu_keyboard())
        return

    if user.status == Status.STOPPED:
        await update.message.reply_text(cohort_already_stopped_message)
        return

    if user.status == Status.FINISHED:
        await update.message.reply_text(cohort_finished_message)
        return

    state = enrollment_state()
    if state != EnrollmentState.OPEN:
        logger.info(
            "/start from user=%s refused: enrollment is %s", user.telegram_id, state.name
        )
        put_on_waitlist(user)
        await update.message.reply_text(WAITLIST_MESSAGES[state])
        return

    logger.info("/start from new user=%s; enrollment open", user.telegram_id)

    keyboard = [[InlineKeyboardButton(
        start_message_button,
        callback_data=callbacks.encode(callbacks.START_ONBOARDING, callbacks.ONBOARDING),
    )]]

    await update.message.reply_text(start_message, reply_markup=InlineKeyboardMarkup(keyboard))


start_handler = CommandHandler("start", handle_start)
