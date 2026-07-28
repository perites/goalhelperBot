"""Question bank: seeding, rotation, and delivery.

Pure service layer — no Telegram handlers live here, so nothing in this module
needs to know about updates or callbacks.
"""
import json

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app import clock
from app.config import QUESTION_ORDER_STEP
from app.models import Answer, FinalAnswer, FinalQuestion, Question
from app.texts import (
    final_questions,
    final_questions_block,
    question_answer_button,
    question_answered_suffix,
    question_message_template,
    question_skip_button,
    question_skipped_suffix,
    sample_questions,
)


def seed_questions():
    """Populate both banks once, leaving sparse gaps in `order` so questions
    can be inserted later without renumbering."""
    if not Question.select().exists():
        for position, (text, question_type, options) in enumerate(sample_questions, start=1):
            Question.create(
                text=text,
                type=question_type,
                options=json.dumps(options, ensure_ascii=False) if options else None,
                order=position * QUESTION_ORDER_STEP,
            )

    if not FinalQuestion.select().exists():
        for position, text in enumerate(final_questions, start=1):
            FinalQuestion.create(text=text, order=position * QUESTION_ORDER_STEP)


# --- Daily rotation --------------------------------------------------------

def next_question_for(user):
    """The next question in `order`, wrapping to the first once the bank runs out."""
    first_question = Question.select().order_by(Question.order).first()
    last_sent = (
        Answer.select()
        .where(Answer.user == user)
        .order_by(Answer.sent_at.desc(), Answer.id.desc())
        .first()
    )

    if last_sent is None:
        return first_question

    following = (
        Question.select()
        .where(Question.order > last_sent.question.order)
        .order_by(Question.order)
        .first()
    )

    return following or first_question


def pending_answer(user):
    """The one question still awaiting a reply, if any."""
    return Answer.open_for(user).order_by(Answer.sent_at).first()


def close_open_answers(user):
    """Mark anything still unanswered as skipped, so a user has at most one
    open question at a time."""
    return (
        Answer.update(skipped=True)
        .where(Answer.id.in_(Answer.open_for(user).select(Answer.id)))
        .execute()
    )


def build_question_keyboard(question, answer):
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


def render_question(answer):
    """The question message as it was originally sent. Uses the stored
    cycle_day so a reply arriving the next day doesn't redraw a wrong number."""
    user = answer.user

    return question_message_template.format(
        day=answer.cycle_day if answer.cycle_day is not None else user.cycle_day,
        total=user.cycle_length,
        intention=user.intention,
        question=answer.question.text,
    )


async def send_question(bot, user):
    """Close out the previous question, then send the next one."""
    close_open_answers(user)

    question = next_question_for(user)
    if question is None:
        return None

    answer = Answer.create(
        user=user,
        question=question,
        sent_at=clock.now_kyiv(),
        cycle_day=user.cycle_day,
    )

    message = await bot.send_message(
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

    if message is not None:
        answer.message_id = message.message_id
        answer.save()

    return answer


async def show_resolved_answer(bot, answer):
    """Rewrite the original question message so the answer sits beneath it,
    which also clears the buttons."""
    if answer.message_id is None:
        return

    body = render_question(answer)
    body += (
        question_skipped_suffix if answer.skipped
        else question_answered_suffix.format(answer=answer.answer)
    )

    await bot.edit_message_text(
        chat_id=answer.user.telegram_id,
        message_id=answer.message_id,
        text=body,
    )


# --- Closing block ---------------------------------------------------------

def has_received_closing_block(user):
    return FinalAnswer.select().where(FinalAnswer.user == user).exists()


def pending_final_answer(user):
    return (
        FinalAnswer.select()
        .where((FinalAnswer.user == user) & FinalAnswer.answered_at.is_null(True))
        .first()
    )


async def send_closing_block(bot, user):
    """The closing questions as one message. No buttons — it stays open
    indefinitely until the user replies."""
    close_open_answers(user)

    questions = [q.text for q in FinalQuestion.select().order_by(FinalQuestion.order)]
    if not questions:
        return None

    body = final_questions_block(user.cycle_length, questions)
    final_answer = FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), message_text=body,
    )

    message = await bot.send_message(chat_id=user.telegram_id, text=body)

    if message is not None:
        final_answer.message_id = message.message_id
        final_answer.save()

    return final_answer


async def show_resolved_final_answer(bot, final_answer):
    """Same treatment for the closing block. Its text is stored rather than
    re-rendered because the question list could be edited in between."""
    if final_answer.message_id is None or final_answer.message_text is None:
        return

    await bot.edit_message_text(
        chat_id=final_answer.user.telegram_id,
        message_id=final_answer.message_id,
        text=final_answer.message_text + question_answered_suffix.format(
            answer=final_answer.answer
        ),
    )
