"""Capturing replies to questions.

Nothing here holds conversation state: the pending Answer row in the database
is the state, so a restart between question and reply is invisible.
"""
from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from bot import clock
from bot.config import BACK_ACTION
from bot.enums import Status
from bot.logs import describe, get_logger
from bot.models import Answer, User
from bot.services.cycle import complete_cycle, reached_final_day, send_closing_summary
from bot.services.questions import (
    build_question_keyboard,
    deliver_question,
    option_at,
    send_follow_up,
    send_next_in_slot,
    pending_answer,
    pending_final_answer,
    show_resolved_answer,
    show_resolved_final_answer,
)
from bot.texts import (
    main_menu_buttons,
    question_already_closed_message,
    question_answer_prompt,
    question_saved_message,
    question_skipped_message,
)
from bot.utils import current_user

logger = get_logger(__name__)


def _resolvable_answer(answer_id):
    """The Answer row for this callback, or None if it's already resolved."""
    answer = Answer.get_or_none(Answer.id == answer_id)

    if answer is None or answer.answered_at is not None or answer.skipped:
        return None

    return answer


async def _hand_off_if_final_day(bot, user):
    """Answering on the last day goes straight to the closing block.
    Returns True if an end-of-cycle message was sent."""
    if not reached_final_day(user):
        return False

    await complete_cycle(bot, user)

    return True


async def _after_daily_answer(bot, user, answer):
    """Three things can follow an answer, in this order of precedence:
    reaching the last day beats everything; then a follow-up, so the current
    unit finishes before a new one starts; then the next question in the
    slot's run. Returns True when a message was sent, which tells the caller
    to skip the plain acknowledgement.
    """
    if await _hand_off_if_final_day(bot, user):
        return True

    if await send_follow_up(bot, user, answer) is not None:
        return True

    return await send_next_in_slot(bot, user, answer.slot) is not None


async def handle_answer_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if _resolvable_answer(int(query.data.split(":")[1])) is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(question_already_closed_message)
        return

    await query.message.reply_text(question_answer_prompt)


async def handle_skip_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    answer = _resolvable_answer(int(query.data.split(":")[1]))
    if answer is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(question_already_closed_message)
        return

    answer.skipped = True
    answer.answered_at = clock.now_kyiv()
    answer.save()

    logger.info(
        "user=%s skipped question=%s (day %s)",
        answer.user_id, answer.question_id, answer.cycle_day,
    )

    # Rewriting the message also drops its buttons.
    await show_resolved_answer(context.bot, answer)

    # Skipping a question ends the slot's run — but skipping a *follow-up*
    # shouldn't, since they already engaged with the question it hangs off.
    if answer.parent_id is not None:
        if await send_next_in_slot(context.bot, current_user(update), answer.slot) is not None:
            return

    await query.message.reply_text(question_skipped_message)


async def handle_group_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open a group of options, or go back to the top level. Only ever swaps
    the keyboard — it never resolves the answer."""
    query = update.callback_query
    await query.answer()

    _, answer_id, target = query.data.split(":")

    answer = _resolvable_answer(int(answer_id))
    if answer is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(question_already_closed_message)
        return

    group = None if target == BACK_ACTION else int(target)

    await query.edit_message_reply_markup(
        reply_markup=build_question_keyboard(answer.question, answer, group=group),
    )


async def handle_option_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Two or three trailing parts: an index, or a group and an index.
    _, answer_id, *path = query.data.split(":")

    answer = _resolvable_answer(int(answer_id))
    if answer is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(question_already_closed_message)
        return

    chosen = option_at(answer.question.option_list, [int(part) for part in path])
    if chosen is None:
        return

    answer.answer = chosen
    answer.answered_at = clock.now_kyiv()
    answer.save()

    logger.info(
        "user=%s chose an option for question=%s (day %s)",
        answer.user_id, answer.question_id, answer.cycle_day,
    )

    # Rewriting the message also drops its buttons.
    await show_resolved_answer(context.bot, answer)

    if not await _after_daily_answer(context.bot, current_user(update), answer):
        await query.message.reply_text(question_saved_message)


async def handle_answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = current_user(update)

    # FINISHED is allowed through: the closing block stays open for them.
    if user is None or user.status not in (Status.ACTIVE, Status.FINISHED):
        return

    # The closing block is the terminal state, so it takes priority.
    closing = pending_final_answer(user)
    if closing is not None:
        closing.answer = update.message.text
        closing.answered_at = clock.now_kyiv()
        closing.save()

        logger.info(
            "user=%s answered the closing block (%s)",
            user.telegram_id, describe(closing.answer),
        )

        await show_resolved_final_answer(context.bot, closing)
        await send_closing_summary(context.bot, user)
        return

    answer = pending_answer(user)
    if answer is None:
        return

    answer.answer = update.message.text
    answer.answered_at = clock.now_kyiv()
    answer.save()

    logger.info(
        "user=%s answered question=%s (day %s, %s)",
        user.telegram_id, answer.question_id, answer.cycle_day, describe(answer.answer),
    )

    await show_resolved_answer(context.bot, answer)

    if not await _after_daily_answer(context.bot, user, answer):
        await update.message.reply_text(question_saved_message)


async def handle_ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual trigger for testing: /ask <telegram_id>"""
    if not context.args:
        await update.message.reply_text("Usage: /ask <telegram_id>")
        return

    try:
        telegram_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Usage: /ask <telegram_id>")
        return

    user = User.get_or_none(User.telegram_id == telegram_id)
    if user is None:
        await update.message.reply_text(f"No user with id {telegram_id}.")
        return

    if user.status != Status.ACTIVE:
        await update.message.reply_text(
            f"User {telegram_id} is not ACTIVE (status: {Status(user.status).name})."
        )
        return

    logger.info("/ask used by user=%s targeting user=%s", update.effective_user.id, telegram_id)

    answer = await deliver_question(context.bot, user, reason="manual")
    if answer is None:
        await update.message.reply_text(
            f"Nothing sent to {telegram_id} — see the log for why."
        )
        return

    await update.message.reply_text(
        f"Sent question (order {answer.question.order}) to {telegram_id}."
    )


ask_command_handler = CommandHandler("ask", handle_ask_command)
answer_button_handler = CallbackQueryHandler(handle_answer_button, pattern="^answer:")
skip_button_handler = CallbackQueryHandler(handle_skip_button, pattern="^skip:")
option_button_handler = CallbackQueryHandler(handle_option_button, pattern="^option:")
group_button_handler = CallbackQueryHandler(handle_group_button, pattern="^group:")

# Menu buttons arrive as plain text, so they must be excluded or they'd be
# saved as answers.
answer_text_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & ~filters.Text(main_menu_buttons),
    handle_answer_text,
)
