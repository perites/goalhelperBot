"""Question bank: seeding, rotation, and delivery.

Pure service layer — no Telegram handlers live here, so nothing in this module
needs to know about updates or callbacks.
"""
import json
from datetime import timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app import clock
from app.config import QUESTION_ORDER_STEP
from app.logs import get_logger
from app.models import Answer, FinalAnswer, FinalQuestion, Question
from app.services.slots import questions_per_slot, saved_slots
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

logger = get_logger(__name__)


def _encode_options(options):
    return json.dumps(options, ensure_ascii=False) if options else None


def seed_questions():
    """Populate both banks once, leaving sparse gaps in `order` so questions
    can be inserted later without renumbering."""
    if not Question.select().exists():
        for position, (text, question_type, options, follow_ups) in enumerate(
            sample_questions, start=1
        ):
            order = position * QUESTION_ORDER_STEP
            parent = Question.create(
                text=text,
                type=question_type,
                options=_encode_options(options),
                order=order,
            )

            # Follow-ups sit inside the parent's order gap, so they stay
            # between it and the next rotation question.
            for offset, (sub_text, sub_type, sub_options) in enumerate(follow_ups, start=1):
                Question.create(
                    text=sub_text,
                    type=sub_type,
                    options=_encode_options(sub_options),
                    order=order + offset,
                    parent=parent,
                )

    if not FinalQuestion.select().exists():
        for position, text in enumerate(final_questions, start=1):
            FinalQuestion.create(text=text, order=position * QUESTION_ORDER_STEP)

    logger.info(
        "Question banks ready: %s daily, %s closing",
        Question.select().count(), FinalQuestion.select().count(),
    )


# --- Daily rotation --------------------------------------------------------

def rotation_questions():
    """The daily bank: follow-ups are reachable only through their parent."""
    return Question.select().where(Question.parent.is_null(True))


def next_question_for(user):
    """The next question in `order`, wrapping to the first once the bank runs out."""
    first_question = rotation_questions().order_by(Question.order).first()

    # Follow-ups are excluded here too, or the rotation pointer would jump to
    # a follow-up's order and the daily sequence would derail from then on.
    last_sent = (
        Answer.select()
        .where((Answer.user == user) & Answer.parent.is_null(True))
        .order_by(Answer.sent_at.desc(), Answer.id.desc())
        .first()
    )

    if last_sent is None:
        return first_question

    following = (
        rotation_questions()
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
    # A follow-up arrives mid-exchange, so it skips the day/intention header
    # that has just been shown above it.
    if answer.parent_id is not None:
        return answer.question.text

    user = answer.user

    return question_message_template.format(
        day=answer.cycle_day if answer.cycle_day is not None else user.cycle_day,
        total=user.cycle_length,
        intention=user.intention,
        question=answer.question.text,
    )


async def send_question(bot, user, slot=None):
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
        slot=slot,
    )

    message = await bot.send_message(
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

    if message is not None:
        answer.message_id = message.message_id
        answer.save()

    logger.debug(
        "Question sent: user=%s answer=%s question=%s day=%s",
        user.telegram_id, answer.id, question.id, answer.cycle_day,
    )

    return answer


async def deliver_question(bot, user, reason, slot=None):
    """Send the next question and log the outcome. Returns the Answer, or None
    if nothing went out.

    Never raises — one unreachable user (blocked the bot, deleted account)
    must not break whatever loop the caller is in. `reason` says what
    triggered it, so the log distinguishes scheduled sends from manual ones.
    """
    try:
        answer = await send_question(bot, user, slot=slot)
    except Exception:  # noqa: BLE001
        logger.warning(
            "Failed to send question to user=%s (%s)", user.telegram_id, reason, exc_info=True
        )
        return None

    if answer is None:
        logger.warning(
            "Question bank is empty; nothing sent to user=%s (%s)", user.telegram_id, reason
        )
        return None

    logger.info(
        "Sent question to user=%s day=%s question=%s slot=%s (%s)",
        user.telegram_id, answer.cycle_day, answer.question_id, slot or "-", reason,
    )

    return answer


def sent_in_slot_today(user, slot):
    """How many questions have gone out for this slot today.

    Follow-ups don't count: a question and its follow-up are one reflective
    unit, so a quota of three means three topics rather than three messages.
    """
    if slot is None:
        return 0

    day_start = clock.now_kyiv().replace(hour=0, minute=0, second=0, microsecond=0)

    return (
        Answer.select()
        .where(
            (Answer.user == user)
            & (Answer.slot == slot)
            & Answer.parent.is_null(True)
            & (Answer.sent_at >= day_start)
            & (Answer.sent_at < day_start + timedelta(days=1))
        )
        .count()
    )


def next_follow_up(parent_answer):
    """The next unasked follow-up for this particular answer.

    Keyed on the answer, not the question, so the same question asked again on
    a later day gets its follow-up again.
    """
    already_asked = Answer.select(Answer.question).where(Answer.parent == parent_answer)

    return (
        Question.select()
        .where(
            (Question.parent == parent_answer.question_id)
            & Question.id.not_in(already_asked)
        )
        .order_by(Question.order)
        .first()
    )


async def send_follow_up(bot, user, parent_answer):
    """Send the next follow-up to an answer, if that question has one."""
    question = next_follow_up(parent_answer)
    if question is None:
        return None

    answer = Answer.create(
        user=user,
        question=question,
        sent_at=clock.now_kyiv(),
        cycle_day=parent_answer.cycle_day,
        # Carried for the record; the quota above ignores follow-ups anyway.
        slot=parent_answer.slot,
        parent=parent_answer,
    )

    message = await bot.send_message(
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

    if message is not None:
        answer.message_id = message.message_id
        answer.save()

    logger.info(
        "Sent follow-up to user=%s question=%s (after answer=%s)",
        user.telegram_id, question.id, parent_answer.id,
    )

    return answer


def slot_quota(user, slot):
    """How many questions this slot owes today, which depends on how many
    other slots the user picked."""
    return questions_per_slot(saved_slots(user)).get(slot, 0)


async def send_next_in_slot(bot, user, slot):
    """Continue a slot's run, if the day's quota leaves room. Returns None
    when the run is finished, which is the caller's cue to acknowledge the
    answer instead."""
    if slot is None:
        return None

    already = sent_in_slot_today(user, slot)
    quota = slot_quota(user, slot)

    if already >= quota:
        logger.debug(
            "Slot %s finished for user=%s (%s of %s)",
            slot, user.telegram_id, already, quota,
        )
        return None

    return await deliver_question(bot, user, reason="chain", slot=slot)


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
        logger.warning("Closing block requested but no closing questions exist")
        return None

    body = final_questions_block(user.cycle_length, questions)
    final_answer = FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), message_text=body,
    )

    message = await bot.send_message(chat_id=user.telegram_id, text=body)

    if message is not None:
        final_answer.message_id = message.message_id
        final_answer.save()

    logger.info("Closing block sent to user=%s (%s questions)", user.telegram_id, len(questions))

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

