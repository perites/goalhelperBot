"""Putting questions in front of people, and tidying up once they answer.

What to send is decided in `core.services.questions`; this is the part that
talks to Telegram.
"""
from telegram.error import TelegramError

from bot.keyboards import build_question_keyboard
from bot.texts import question_answered_suffix, question_skipped_suffix
from bot.views import render_question
from core import clock
from core.logs import get_logger
from core.models import Answer
from core.services.questions import (
    close_open_answers,
    next_follow_up,
    next_question_for,
    sent_in_slot_today,
    slot_quota,
)

logger = get_logger(__name__)


async def send_for_row(bot, row, chat_id, text, reply_markup=None):
    """Send the message a just-created row stands for, and undo the row if it
    doesn't arrive.

    The row has to exist before the send: the keyboard's callback data is built
    from its id. But a row is also the only thing that says a question is
    waiting for an answer — so one left behind by a failed send is worse than
    no row at all. It would make the slot look already started, and the next
    thing the participant typed about anything else would be filed as the
    answer to a question they never saw.

    Telegram refuses sends for ordinary reasons — the participant blocked the
    bot, deleted their account, or we're being rate limited — so this is a
    normal path, not a corruption case. The caller sees the original error.
    """
    try:
        message = await bot.send_message(
            chat_id=chat_id, text=text, reply_markup=reply_markup,
        )
    except Exception:
        row.delete_instance()
        raise

    if message is not None:
        row.message_id = message.message_id
        row.save()

    return message


async def send_question(bot, user, slot=None, rng=None):
    """Close out the previous question, then send the next one."""
    close_open_answers(user)

    question, category_index = next_question_for(user, rng=rng)
    if question is None:
        return None

    answer = Answer.create(
        user=user,
        question=question,
        sent_at=clock.now_kyiv(),
        cycle_day=user.cycle_day,
        slot=slot,
        category_index=category_index,
    )

    await send_for_row(
        bot, answer,
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

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
        # Carried for the record; the quota ignores follow-ups anyway.
        slot=parent_answer.slot,
        parent=parent_answer,
    )

    await send_for_row(
        bot, answer,
        chat_id=user.telegram_id,
        text=render_question(answer),
        reply_markup=build_question_keyboard(question, answer),
    )

    logger.info(
        "Sent follow-up to user=%s question=%s (after answer=%s)",
        user.telegram_id, question.id, parent_answer.id,
    )

    return answer


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

    # Tidying the chat history is the least important thing happening here. The
    # answer is already saved, and a follow-up or the closing block may still
    # be due — so a message that can't be rewritten (deleted, chat cleared,
    # text unchanged) must not take those down with it. INFO, not WARNING:
    # this is an ordinary thing for a participant to cause, and WARNING would
    # put it on Ксенія's phone.
    try:
        await bot.edit_message_text(
            chat_id=answer.user.telegram_id,
            message_id=answer.message_id,
            text=body,
        )
    except TelegramError:
        logger.info(
            "Could not rewrite the question message for answer=%s; the answer "
            "itself is saved", answer.id, exc_info=True,
        )
