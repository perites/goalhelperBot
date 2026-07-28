import json
from datetime import datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram import Update
from telegram.ext import (
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters, CallbackQueryHandler,
)

from database import User, Question, Answer, Status, CYCLE_LENGTH_DAYS
from messages_texts import *

ORDER_STEP = 10


FINAL_ORDER_BASE = 10000


def seed_questions():
    """Populate the question bank once, leaving sparse gaps in `order`
    so questions can be inserted later without renumbering."""
    if Question.select().exists():
        return

    for position, (text, question_type, options) in enumerate(sample_questions, start=1):
        Question.create(
            text=text,
            type=question_type,
            options=json.dumps(options, ensure_ascii=False) if options else None,
            order=position * ORDER_STEP,
        )

    # Closing questions live in the same table so their answers export
    # uniformly, but `is_final` keeps them out of the daily rotation.
    for position, (text, question_type) in enumerate(final_questions, start=1):
        Question.create(
            text=text,
            type=question_type,
            options=None,
            order=FINAL_ORDER_BASE + position * ORDER_STEP,
            is_final=True,
        )


def daily_questions():
    return Question.select().where(Question.is_final == False)  # noqa: E712


def next_question_for(user):
    """The next question in `order`, wrapping to the first once the bank runs out."""
    first_question = daily_questions().order_by(Question.order).first()
    last_sent = (
        Answer.select()
        .join(Question)
        .where((Answer.user == user) & (Question.is_final == False))  # noqa: E712
        .order_by(Answer.sent_at.desc(), Answer.id.desc())
        .first()
    )

    if last_sent is None:
        return first_question

    following = (
        daily_questions()
        .where(Question.order > last_sent.question.order)
        .order_by(Question.order)
        .first()
    )

    return following or first_question


def close_open_questions(user):
    """Mark anything still unanswered as skipped, so a user has at most one open question."""
    return (
        Answer.update(skipped=True)
        .where(
            (Answer.user == user)
            & Answer.answered_at.is_null(True)
            & (Answer.skipped == False)  # noqa: E712 - peewee needs the comparison
        )
        .execute()
    )


def _build_question_keyboard(question, answer):
    options = question.option_list

    if options:
        keyboard = [
            [InlineKeyboardButton(option, callback_data=f"option:{answer.id}:{index}")]
            for index, option in enumerate(options)
        ]
    else:
        keyboard = [[InlineKeyboardButton(question_answer_button, callback_data=f"answer:{answer.id}")]]

    keyboard.append([InlineKeyboardButton(question_skip_button, callback_data=f"skip:{answer.id}")])

    return InlineKeyboardMarkup(keyboard)


async def deliver(bot, user, question, text):
    """Create the pending Answer row and send it. Shared by the daily
    rotation and the closing questions."""
    answer = Answer.create(user=user, question=question, sent_at=datetime.now())

    await bot.send_message(
        chat_id=user.telegram_id,
        text=text,
        reply_markup=_build_question_keyboard(question, answer),
    )

    return answer


async def send_question(bot, user):
    """Close out the previous question, then send the next one. Returns the new Answer row."""
    close_open_questions(user)

    question = next_question_for(user)
    if question is None:
        return None

    text = question_message_template.format(
        day=user.cycle_day,
        total=user.cycle_length,
        intention=user.intention,
        question=question.text,
    )

    return await deliver(bot, user, question, text)


def next_final_question_for(user):
    """Closing questions are asked once each, in order — no wrap-around."""
    already_asked = (
        Answer.select(Answer.question)
        .join(Question)
        .where((Answer.user == user) & (Question.is_final == True))  # noqa: E712
    )

    return (
        Question.select()
        .where((Question.is_final == True) & Question.id.not_in(already_asked))  # noqa: E712
        .order_by(Question.order)
        .first()
    )


async def send_final_question(bot, user):
    """Next closing question, or None when they've all been asked."""
    close_open_questions(user)

    question = next_final_question_for(user)
    if question is None:
        return None

    return await deliver(bot, user, question, question.text)


def _open_answer(answer_id):
    """The Answer row for this callback, or None if it was already answered or skipped."""
    answer = Answer.get_or_none(Answer.id == answer_id)

    if answer is None or answer.answered_at is not None or answer.skipped:
        return None

    return answer


async def handle_answer_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if _open_answer(int(query.data.split(":")[1])) is None:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(question_already_closed_message)
        return

    await query.message.reply_text(question_answer_prompt)


async def handle_skip_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    await query.edit_message_reply_markup(reply_markup=None)

    answer = _open_answer(int(query.data.split(":")[1]))
    if answer is None:
        await query.message.reply_text(question_already_closed_message)
        return

    answer.skipped = True
    answer.answered_at = datetime.now()
    answer.save()

    await query.message.reply_text(question_skipped_message)


async def handle_option_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, answer_id, index = query.data.split(":")

    await query.edit_message_reply_markup(reply_markup=None)

    answer = _open_answer(int(answer_id))
    if answer is None:
        await query.message.reply_text(question_already_closed_message)
        return

    options = answer.question.option_list
    index = int(index)
    if options is None or index >= len(options):
        return

    answer.answer = options[index]
    answer.answered_at = datetime.now()
    answer.save()

    await query.message.reply_text(question_saved_message)


async def handle_answer_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = User.get_or_none(User.telegram_id == update.effective_user.id)
    if user is None or user.status != Status.ACTIVE:
        return

    answer = (
        Answer.select()
        .where(
            (Answer.user == user)
            & Answer.answered_at.is_null(True)
            & (Answer.skipped == False)  # noqa: E712 - peewee needs the comparison
        )
        .order_by(Answer.sent_at)
        .first()
    )

    if answer is None:
        return

    answer.answer = update.message.text
    answer.answered_at = datetime.now()
    answer.save()

    await update.message.reply_text(question_saved_message)


async def ask_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Manual trigger until the scheduler exists: /ask <telegram_id>"""
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


ask_command_handler = CommandHandler("ask", ask_command)
answer_button_handler = CallbackQueryHandler(handle_answer_button, pattern="^answer:")
skip_button_handler = CallbackQueryHandler(handle_skip_button, pattern="^skip:")
option_button_handler = CallbackQueryHandler(handle_option_button, pattern="^option:")
# Menu buttons arrive as plain text, so they must be excluded or they'd be saved as answers.
answer_text_handler = MessageHandler(
    filters.TEXT & ~filters.COMMAND & ~filters.Text(main_menu_buttons),
    handle_answer_text,
)
