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

from bot import callbacks
from bot.closing import (
    complete_cycle, send_closing_summary, show_resolved_final_answer,
)
from bot.delivery import (
    deliver_question, send_follow_up, send_next_in_slot, show_resolved_answer,
)
from bot.keyboards import build_question_keyboard
from core import clock
from core.enums import Status
from core.logs import describe, get_logger
from core.models import Answer, User
from core.services.cycle import reached_final_day
from core.services.questions import (
    option_at, pending_answer, pending_final_answer,
)
from core.settings import admin_chat_ids
from bot.texts import (
    main_menu_buttons,
    question_already_closed_message,
    question_answer_prompt,
    question_saved_message,
    question_skipped_message,
)
from bot.utils import current_user

logger = get_logger(__name__)


def _resolvable_answer(data):
    """The Answer a callback names, or None if it is gone or already resolved.

    The id travels to Telegram and back, so it is parsed rather than trusted —
    an old chat can hand back anything it still has on screen.
    """
    parts = callbacks.parts(data)

    try:
        answer_id = int(parts[0])
    except (IndexError, ValueError):
        return None

    answer = Answer.get_or_none(Answer.id == answer_id)

    if answer is None or answer.answered_at is not None or answer.skipped:
        return None

    return answer


async def _resolve_or_close(query):
    """The Answer this tap is about — or None, having told the participant the
    question is closed and cleared the dead buttons.

    Every button handler opens this way, because a stale keyboard is the normal
    case rather than an edge one: the buttons live in the chat and outlive
    whatever they pointed at.
    """
    answer = _resolvable_answer(query.data)
    if answer is not None:
        return answer

    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(question_already_closed_message)

    return None


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

    if await _resolve_or_close(query) is None:
        return

    await query.message.reply_text(question_answer_prompt)


async def handle_skip_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    answer = await _resolve_or_close(query)
    if answer is None:
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

    answer = await _resolve_or_close(query)
    if answer is None:
        return

    target = callbacks.parts(query.data)[1]

    if target == callbacks.BACK:
        group = None
    else:
        indexes = callbacks.indexes(query.data)
        if indexes is None:
            return
        group = indexes[1]

    await query.edit_message_reply_markup(
        reply_markup=build_question_keyboard(answer.question, answer, group=group),
    )


async def handle_option_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    answer = await _resolve_or_close(query)
    if answer is None:
        return

    # Two or three parts: the answer, then an index — or a group and an index.
    path = callbacks.indexes(query.data)
    if path is None:
        return

    chosen = option_at(answer.question.option_list, path[1:])
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
    """Manual trigger for testing: /ask <telegram_id>

    Admins only. It sends to *another* participant, which closes whatever they
    had open and consumes a rotation slot — and its replies say whether an id
    belongs to a participant and what state they are in. Neither is anyone
    else's to know.

    Unauthorised use is answered with silence rather than a refusal: there is
    nothing to gain by confirming the command exists. It is logged at INFO
    rather than WARNING deliberately — WARNING reaches the admin chats, so any
    stranger could otherwise use this to buzz Ксенія's phone at will.
    """
    if update.effective_user.id not in admin_chat_ids():
        logger.info("Ignoring /ask from non-admin user=%s", update.effective_user.id)
        return

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
answer_button_handler = CallbackQueryHandler(
    handle_answer_button, pattern=callbacks.pattern(callbacks.ANSWER)
)
skip_button_handler = CallbackQueryHandler(
    handle_skip_button, pattern=callbacks.pattern(callbacks.SKIP)
)
option_button_handler = CallbackQueryHandler(
    handle_option_button, pattern=callbacks.pattern(callbacks.OPTION)
)
group_button_handler = CallbackQueryHandler(
    handle_group_button, pattern=callbacks.pattern(callbacks.GROUP)
)

# Menu buttons arrive as plain text, so they must be excluded or they'd be
# saved as answers.
answer_text_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & ~filters.Text(main_menu_buttons),
    handle_answer_text,
)
