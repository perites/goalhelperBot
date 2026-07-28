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

from app import clock
from app.enums import Status
from app.models import Answer, User
from app.services.cycle import complete_cycle, reached_final_day, send_closing_summary
from app.services.questions import (
    pending_answer,
    pending_final_answer,
    send_question,
    show_resolved_answer,
    show_resolved_final_answer,
)
from app.texts import (
    main_menu_buttons,
    question_already_closed_message,
    question_answer_prompt,
    question_saved_message,
    question_skipped_message,
)
from app.utils import current_user


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

    # Rewriting the message also drops its buttons.
    await show_resolved_answer(context.bot, answer)
    await query.message.reply_text(question_skipped_message)


async def handle_option_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, answer_id, index = query.data.split(":")

    answer = _resolvable_answer(int(answer_id))
    if answer is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(question_already_closed_message)
        return

    options = answer.question.option_list
    index = int(index)
    if options is None or index >= len(options):
        return

    answer.answer = options[index]
    answer.answered_at = clock.now_kyiv()
    answer.save()

    # Rewriting the message also drops its buttons.
    await show_resolved_answer(context.bot, answer)

    if not await _hand_off_if_final_day(context.bot, current_user(update)):
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

        await show_resolved_final_answer(context.bot, closing)
        await send_closing_summary(context.bot, user)
        return

    answer = pending_answer(user)
    if answer is None:
        return

    answer.answer = update.message.text
    answer.answered_at = clock.now_kyiv()
    answer.save()

    await show_resolved_answer(context.bot, answer)

    if not await _hand_off_if_final_day(context.bot, user):
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

    answer = await send_question(context.bot, user)
    if answer is None:
        await update.message.reply_text("Question bank is empty.")
        return

    await update.message.reply_text(
        f"Sent question (order {answer.question.order}) to {telegram_id}."
    )


ask_command_handler = CommandHandler("ask", handle_ask_command)
answer_button_handler = CallbackQueryHandler(handle_answer_button, pattern="^answer:")
skip_button_handler = CallbackQueryHandler(handle_skip_button, pattern="^skip:")
option_button_handler = CallbackQueryHandler(handle_option_button, pattern="^option:")

# Menu buttons arrive as plain text, so they must be excluded or they'd be
# saved as answers.
answer_text_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & ~filters.Text(main_menu_buttons),
    handle_answer_text,
)
