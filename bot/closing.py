"""Day 30: the closing questions, and everything that follows the reply.

Kept apart from `delivery.py` because it is a different shape entirely — one
message holding every question, answered in one message, with no buttons and no
quota. The state transition it wraps lives in `core.services.cycle`.
"""
from telegram.error import TelegramError

from bot.delivery import send_for_row
from bot.texts import (
    cycle_final_invite_message,
    cycle_final_summary_intro,
    final_questions_block,
    question_answered_suffix,
)
from bot.views import build_stats_text
from core import clock
from core.logs import get_logger
from core.models import FinalAnswer
from core.services.cycle import finish_user
from core.services.questions import (
    close_open_answers, closing_questions, has_received_closing_block,
)

logger = get_logger(__name__)


async def send_closing_block(bot, user):
    """The closing questions as one message. No buttons — it stays open
    indefinitely until the user replies."""
    close_open_answers(user)

    questions = closing_questions()
    if not questions:
        logger.warning("Closing block requested but no closing questions exist")
        return None

    body = final_questions_block(user.cycle_length, questions)
    final_answer = FinalAnswer.create(
        user=user, sent_at=clock.now_kyiv(), message_text=body,
    )

    # The row is what `has_received_closing_block` reads, and the daily sweep
    # uses that to decide who still needs one — so a row surviving a failed
    # send would retire the participant without ever asking them anything.
    await send_for_row(bot, final_answer, chat_id=user.telegram_id, text=body)

    logger.info("Closing block sent to user=%s (%s questions)", user.telegram_id, len(questions))

    return final_answer


async def complete_cycle(bot, user):
    """Last day done: send the closing block, then mark finished.

    The send comes first because FINISHED is exactly what takes someone out of
    `users_due_for_completion`. Flipping the status before a send that then
    failed would retire them silently — no closing questions, no summary, no
    invitation, and nothing left that would ever try again. Failing here
    leaves them ACTIVE, so tomorrow's sweep has another go.

    Nothing reaches them in the gap: `is_cycle_complete` already keeps the
    daily questions away, so the status flip is for the sweep's benefit rather
    than the participant's.

    An empty closing bank is not a failure — `send_closing_block` says so in
    the log and returns None, and the participant is still finished.
    """
    if has_received_closing_block(user):
        return None

    final_answer = await send_closing_block(bot, user)

    finish_user(user)
    logger.info("user=%s reached day %s and finished", user.telegram_id, user.cycle_day)

    return final_answer


async def send_closing_summary(bot, user):
    """Called once the closing block is answered: summary, then thanks and
    the invitation to book a session (ТЗ §15–16)."""
    await bot.send_message(
        chat_id=user.telegram_id,
        text=cycle_final_summary_intro.format(total=user.cycle_length),
    )

    await bot.send_message(chat_id=user.telegram_id, text=build_stats_text(user))
    await bot.send_message(chat_id=user.telegram_id, text=cycle_final_invite_message)


async def show_resolved_final_answer(bot, final_answer):
    """Same treatment as a daily question: the reply is written under the block
    it answers. Its text is stored rather than re-rendered, because the question
    list could have been edited in between."""
    if final_answer.message_id is None or final_answer.message_text is None:
        return

    # Cosmetic, and the summary that follows is not — see show_resolved_answer.
    try:
        await bot.edit_message_text(
            chat_id=final_answer.user.telegram_id,
            message_id=final_answer.message_id,
            text=final_answer.message_text + question_answered_suffix.format(
                answer=final_answer.answer
            ),
        )
    except TelegramError:
        logger.info(
            "Could not rewrite the closing block for user=%s; the answer itself "
            "is saved", final_answer.user_id, exc_info=True,
        )
